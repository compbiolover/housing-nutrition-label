"""Ambient air quality by location — PM2.5, ozone, and radon (keyless + offline).

Backs the **Air Quality** dimension: how clean the outdoor (and, for radon, the
indoor-potential) air is at a location, scored 0-100 where higher is cleaner/safer.
Three national, public-domain layers, looked up with no network call:

  • **PM2.5** — annual mean fine-particulate concentration (µg/m³). The pollutant
    most tightly linked to mortality; the US annual NAAQS is 9 µg/m³, the WHO
    guideline 5.
  • **Ozone** — annual mean of the daily maximum 8-hour ozone (ppb). Ground-level
    ozone drives respiratory harm and smog.
  • **Radon** — EPA Map of Radon Zones class (1 = highest predicted indoor level,
    ≥4 pCi/L; 2 = 2–4; 3 = <2). Radon is the leading cause of lung cancer among
    non-smokers.

Resolution
----------
PM2.5 and ozone are resolved at the **census tract** (the CDC downscaler model is
published per tract), falling back to the tract's county when a tract is missing.
Radon is a **county-level** dataset (the EPA zones have no finer public source), so
it is broadcast to the tract's county. ``air_quality_for_tract`` resolves
tract → county; ``air_quality_for_county`` resolves the county directly. Every
result carries a ``geo_level`` (``"tract"`` / ``"county"``).

Scoring
-------
Each layer is mapped to a 0-100 sub-score by piecewise-linear interpolation over
the **national tract quantiles** of that layer, so a sub-score reads directly as
"cleaner than N% of US tracts". The dimension score is their weighted mean
(PM2.5 0.45, ozone 0.25, radon 0.30; radon's weight is redistributed when the
county has no EPA zone). Because the breakpoints are anchored to national
quantiles, the composite tracks a national percentile rank — which is why the
score is returned as-is by ``data/national_percentile.py`` (an identity
dimension), comparable across locations.

Data
----
  air_quality_tracts.csv.gz (tract) + air_quality.csv (county + radon), built by
  scripts/build_air_quality.py from the CDC Environmental Public Health Tracking
  downscaler model (PM2.5/ozone, 2021) and the EPA Map of Radon Zones.

Scope: CONUS. The CDC downscaler covers the contiguous US only, so Alaska
(FIPS 02), Hawai'i (15), Puerto Rico (72), and the territories are not in the
bundled tables; the lookups return None there (the caller leaves Air Quality
unscored), the same as for any tract/county absent from the tables. Within CONUS a
handful of counties (≈0.2%) lack an EPA radon zone (abolished/renamed areas, a few
independent cities) and are scored on PM2.5 + ozone alone.

Sources (public domain / open):
  CDC Tracking Network (PM2.5, ozone modeled tract/county estimates);
  EPA Map of Radon Zones; US Census county code list.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

AIR_QUALITY_VINTAGE = "CDC Tracking PM2.5/ozone (2021, tract-level) + EPA radon zones"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "air_quality.csv"                        # county (fallback + radon)
_TRACT_CSV = _DIR / "air_quality_tracts.csv"           # plain CSV accepted if present
_TRACT_CSV_GZ = _DIR / "air_quality_tracts.csv.gz"     # bundled (gzipped) tract table

# ── Score breakpoints: (pollutant value → sub-score), anchored to the national
# TRACT quantiles [min, p10, p25, p50, p75, p90, p95, max]. Higher pollutant =
# lower score. Interior values from scripts/build_air_quality.py's quantile report.
_PM25_XS = [4.0, 6.55, 7.42, 8.40, 9.15, 10.01, 10.88, 16.0]
_PM25_YS = [100.0, 90.0, 75.0, 50.0, 25.0, 10.0, 5.0, 0.0]

_OZONE_XS = [30.0, 34.61, 36.12, 37.49, 38.92, 44.61, 47.51, 58.0]
_OZONE_YS = [100.0, 90.0, 75.0, 50.0, 25.0, 10.0, 5.0, 0.0]

# Radon sub-score by EPA zone (≈ even national thirds → percentile-like).
_RADON_SCORE = {1: 25.0, 2: 55.0, 3: 85.0}

# Dimension weights (radon redistributed across PM2.5/ozone when a zone is absent).
_W_PM25, _W_OZONE, _W_RADON = 0.45, 0.25, 0.30

_RADON_LABEL = {
    1: "Zone 1 (high radon potential, ≥4 pCi/L predicted)",
    2: "Zone 2 (moderate radon potential, 2–4 pCi/L)",
    3: "Zone 3 (low radon potential, <2 pCi/L)",
}


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation, flat outside the anchor range."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → {pm25, ozone, radon_zone}."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            raw = str(row.get("county_fips") or "").strip()
            if not raw:
                continue          # skip a malformed/blank row (don't pad "" → "00000")
            zone = row.get("radon_zone")
            try:
                zone = int(zone) if zone not in (None, "") else None
            except (TypeError, ValueError):
                zone = None
            table[raw.zfill(5)] = {
                "pm25": _num(row.get("pm25_ugm3")),
                "ozone": _num(row.get("ozone_ppb")),
                "radon_zone": zone,
            }
    return table


@lru_cache(maxsize=1)
def _tract_table():
    """tract GEOID (11-digit) → row {pm25_ugm3, ozone_ppb}, via the shared columnar
    TractStore (memory-frugal for the ~84k-tract table)."""
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    if not path.exists():
        return {}
    from housing_label.data._tractstore import load_tract_store
    return load_tract_store(path, 11)


def _reading(pm25, ozone, zone, geo_level: str) -> dict | None:
    """Assemble the scored reading dict from raw pollutant values + radon zone.

    Returns None only when nothing is scorable (no PM2.5, ozone, or radon)."""
    pm_s = _interp(pm25, _PM25_XS, _PM25_YS) if pm25 is not None else None
    oz_s = _interp(ozone, _OZONE_XS, _OZONE_YS) if ozone is not None else None
    rn_s = _RADON_SCORE.get(zone) if zone is not None else None

    parts = []
    if pm_s is not None:
        parts.append((_W_PM25, pm_s))
    if oz_s is not None:
        parts.append((_W_OZONE, oz_s))
    if rn_s is not None:
        parts.append((_W_RADON, rn_s))
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    score = round(sum(w * s for w, s in parts) / wsum, 1)

    return {
        "score": score,
        "pm25": pm25,
        "ozone": ozone,
        "radon_zone": zone,
        "pm25_score": None if pm_s is None else round(pm_s, 1),
        "ozone_score": None if oz_s is None else round(oz_s, 1),
        "radon_score": None if rn_s is None else round(rn_s, 1),
        "radon_label": _RADON_LABEL.get(zone),
        "geo_level": geo_level,
        "label": AIR_QUALITY_VINTAGE,
    }


def air_quality_for_county(county_fips: str | None) -> dict | None:
    """Air Quality reading + 0-100 score for a 5-digit county FIPS (county grain).

    Returns None for a missing/blank FIPS or a county absent from the table (e.g.
    a non-CONUS county), so the caller leaves Air Quality unscored.
    """
    if not county_fips:
        return None
    rec = _table().get(str(county_fips).strip().zfill(5))
    if rec is None:
        return None
    return _reading(rec["pm25"], rec["ozone"], rec["radon_zone"], "county")


def air_quality_for_tract(tract_geoid: str | None) -> dict | None:
    """Air Quality reading + 0-100 score for an 11-digit tract GEOID.

    PM2.5/ozone resolve at the tract (falling back to the tract's county for a
    pollutant the tract table is missing); radon is the tract's county zone. The
    returned ``geo_level`` is ``"tract"`` when a tract pollutant value was used,
    else ``"county"``. Returns None when neither the tract nor its county is in the
    bundled tables (e.g. non-CONUS).
    """
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if not geoid:
        return None
    crow = _table().get(geoid[:5])            # county: radon + pollutant fallback
    trow = _tract_table().get(geoid)          # tract: pollutant (primary)

    pm25 = ozone = None
    if trow is not None:
        pm25 = _num(trow.get("pm25_ugm3"))
        ozone = _num(trow.get("ozone_ppb"))
    used_tract = pm25 is not None or ozone is not None
    if crow is not None:
        if pm25 is None:
            pm25 = crow["pm25"]
        if ozone is None:
            ozone = crow["ozone"]
    zone = crow["radon_zone"] if crow is not None else None

    return _reading(pm25, ozone, zone, "tract" if used_tract else "county")
