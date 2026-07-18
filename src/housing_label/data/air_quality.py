"""Ambient air quality by location — PM2.5, ozone, and radon (keyless + offline).

Backs the **Air Quality** dimension: how clean the outdoor (and, for radon, the
indoor-potential) air is at a county, scored 0-100 where higher is cleaner/safer.
Three national, public-domain layers, looked up by 5-digit county FIPS with no
network call:

  • **PM2.5** — annual mean fine-particulate concentration (µg/m³). The pollutant
    most tightly linked to mortality; the US annual NAAQS is 9 µg/m³, the WHO
    guideline 5.
  • **Ozone** — annual mean of the daily maximum 8-hour ozone (ppb). Ground-level
    ozone drives respiratory harm and smog.
  • **Radon** — EPA Map of Radon Zones class (1 = highest predicted indoor level,
    ≥4 pCi/L; 2 = 2–4; 3 = <2). Radon is the leading cause of lung cancer among
    non-smokers.

Scoring
-------
Each layer is mapped to a 0-100 sub-score by piecewise-linear interpolation over
the **national county quantiles** of that layer (from the bundled table), so a
sub-score reads directly as "cleaner than N% of US counties". The dimension score
is their weighted mean (PM2.5 0.45, ozone 0.25, radon 0.30; radon's weight is
redistributed when a county has no EPA zone). Because the breakpoints are anchored
to national quantiles, the composite tracks a national percentile rank — which is
why the score is returned as-is by ``data/national_percentile.py`` (an identity
dimension), comparable across locations.

Data
----
  air_quality.csv, built by scripts/build_air_quality.py:
    • PM2.5 / ozone — CDC Environmental Public Health Tracking downscaler model
      (county, latest available year), population-weighted annual means.
    • Radon — EPA Map of Radon Zones, joined to FIPS via the Census county codes.

Scope: CONUS counties. The CDC PM2.5/ozone downscaler model covers the contiguous
US only, so Alaska (FIPS 02), Hawai'i (15), Puerto Rico (72), and the territories
are not in the bundled table; ``air_quality_for_county`` returns None there (the
caller leaves Air Quality unscored), the same as for any county absent from the
table. Within CONUS a handful of counties (≈0.2%) lack an EPA radon zone
(abolished/renamed areas, a few independent cities) and are scored on PM2.5 +
ozone alone.

Sources (public domain / open):
  CDC Tracking Network (PM2.5, ozone modeled county estimates);
  EPA Map of Radon Zones; US Census county code list.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

AIR_QUALITY_VINTAGE = "CDC Tracking PM2.5/ozone (2022) + EPA radon zones"

_CSV = pathlib.Path(__file__).resolve().parent / "air_quality.csv"

# ── Score breakpoints: (pollutant value → sub-score), anchored to the national
# county quantiles [min, p10, p25, p50, p75, p90, p95, max]. Higher pollutant =
# lower score. Values from scripts/build_air_quality.py's quantile report.
_PM25_XS = [3.0, 5.29, 6.33, 7.43, 8.36, 8.81, 9.12, 14.0]
_PM25_YS = [100.0, 90.0, 75.0, 50.0, 25.0, 10.0, 5.0, 0.0]

_OZONE_XS = [30.0, 36.1, 37.2, 38.1, 39.5, 43.0, 45.0, 55.0]
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
            fips = raw.zfill(5)
            zone = row.get("radon_zone")
            try:
                zone = int(zone) if zone not in (None, "") else None
            except (TypeError, ValueError):
                zone = None
            table[fips] = {
                "pm25": _num(row.get("pm25_ugm3")),
                "ozone": _num(row.get("ozone_ppb")),
                "radon_zone": zone,
            }
    return table


def air_quality_for_county(county_fips: str | None) -> dict | None:
    """Return the Air Quality reading + 0-100 score for a 5-digit county FIPS.

    The returned dict has:
      score            0-100 (higher = cleaner/safer air), or None if PM2.5 and
                       ozone are both missing (nothing to score).
      pm25, ozone      annual county values (µg/m³, ppb) or None.
      radon_zone       EPA zone 1/2/3 or None.
      pm25_score, ozone_score, radon_score  the component sub-scores.
      label            short provenance string.

    Returns None for a missing/blank FIPS or a county absent from the table, so
    the caller leaves Air Quality unscored.
    """
    if not county_fips:
        return None
    rec = _table().get(str(county_fips).strip().zfill(5))
    if rec is None:
        return None

    pm25, ozone, zone = rec["pm25"], rec["ozone"], rec["radon_zone"]
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
        score = None
    else:
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
        "label": AIR_QUALITY_VINTAGE,
    }
