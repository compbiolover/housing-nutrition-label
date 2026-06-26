"""Sub-county climate-hazard projections (CMIP6-LOCA2, keyless + offline).

Returns a 0–100 **Climate Projections** sub-score (higher = a less hazardous
projected future climate) for a tract or county, plus the low/high emissions band
and the underlying projected hazard drivers.

Data
----
Values come from the USGS **CMIP6-LOCA2** threshold/extreme-event metric
projections — the Weighted Multi-Model Mean (WMMM), an ensemble mean over CMIP6
LOCA2-downscaled models on a ~6 km CONUS grid (DOI 10.5066/P13OV6GY). The grid is
sampled at each census tract's internal point and bundled offline by
``scripts/build_climate_projections.py --source loca2`` as
``climate_projections_tracts.csv.gz`` (tract) and ``climate_projections.csv``
(county = the mean of its tracts, so tract→county is coherent). We use a
**mid-century 30-yr window (2040–2069) ensemble mean** under two pathways:

  • low band  = SSP2-4.5
  • high band = SSP5-8.5

across five hazard metrics grouped into three legs:

  • heat    — days > 95 °F and days > 100 °F
  • precip  — days > 1" precip and the annual max 5-day precip total (flood)
  • drought — annual max consecutive dry days

The composite climate score is the equal-weight mean of the three legs; the
headline ``score`` uses the low (SSP2-4.5) band, with the high (SSP5-8.5) band
surfaced as the downside.

Resolution
----------
The lookup is **resolution-aware**: ``climate_projection_for_tract`` resolves a
tract → its parent county → the national average, and ``climate_projection_for_county``
resolves a county → the national average. Every result carries a ``geo_level``
(``"tract"`` / ``"county"`` / ``"us"``) so callers can label the actual geography
that answered.

The bundled tract crosswalk (``climate_projections_tracts.csv.gz``) carries real
sub-county variation — sampling the ~6 km grid at each tract's internal point, so
tracts within a large/diverse county genuinely differ (unlike CMRA's tract layer,
which broadcast the county value). A tract resolves at ``geo_level="tract"``; a
tract absent from the crosswalk falls back to its parent county, then the national
average.

Caveats
-------
The ~6 km grid is sampled at a tract's **internal point** — a representative
sub-county value, **not parcel-scale precision**. Values are a multi-model
ensemble mean (WMMM); SSP2-4.5/SSP5-8.5 are the low/high bands. CMIP6-LOCA2
carries no native Fire Weather Index, so the drought leg (consecutive dry days)
stands in for the fire/drought hazard until a 12 km ClimRR FWI layer is added.
Tracts/counties absent from the crosswalk (e.g. outside the CONUS grid) fall back
to a coarser geography or the national-average score, with the label flagging it.
"""

from __future__ import annotations

import csv
import gzip
import pathlib
from functools import lru_cache

DATA_VINTAGE = "CMIP6-LOCA2 (SSP2-4.5–5-8.5, mid-century 2040–2069)"
US_AVG_LABEL = f"US average ({DATA_VINTAGE})"

_DIR = pathlib.Path(__file__).resolve().parent
_CSV = _DIR / "climate_projections.csv"
# Tract crosswalk (gzipped). Bundled — sub-county values sampled from the ~6 km
# grid. A plain-CSV variant is also accepted if present.
_TRACT_CSV = _DIR / "climate_projections_tracts.csv"
_TRACT_CSV_GZ = _DIR / "climate_projections_tracts.csv.gz"

# Per-hazard scoring breakpoints: (increasing-hazard x values, matching 0–100 y
# values). Anchored to the national quantiles of the SSP2-4.5 (low) mid-century
# distribution (printed by build_climate_projections.py), so a place scores by
# where its projected hazard sits nationally. Higher hazard → lower score.
# xs strictly increasing; values clamp to the end scores outside the range.
_BREAKPOINTS: dict[str, tuple[list[float], list[float]]] = {
    # days/yr > 95 °F           p5 p25 p50 p75 p90 p95 (SSP2-4.5 mid, national)
    "heat_days95":      ([2.4, 13.1, 28.9, 52.1, 74.4, 91.9], [100, 80, 60, 40, 20, 0]),
    # days/yr > 100 °F
    "heat_days100":     ([0.2, 2.3, 6.4, 14.9, 35.0, 46.0],   [100, 80, 60, 40, 20, 0]),
    # days/yr > 1" precip
    "precip_days1in":   ([0.9, 4.8, 8.3, 11.9, 14.9, 16.5],   [100, 80, 60, 40, 20, 0]),
    # annual max 5-day precip [in]
    "precip_max5day":   ([2.0, 3.4, 4.3, 5.2, 5.9, 6.4],      [100, 80, 60, 40, 20, 0]),
    # max consecutive dry days
    "drought_consecdd": ([16.1, 19.8, 24.3, 34.4, 46.0, 56.8], [100, 80, 60, 40, 20, 0]),
}

# Three hazard legs → the driver metrics averaged into each leg.
_LEGS: dict[str, list[str]] = {
    "heat": ["heat_days95", "heat_days100"],
    "precip": ["precip_days1in", "precip_max5day"],
    "drought": ["drought_consecdd"],
}


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Clamped piecewise-linear interpolation (no log; hazard counts hit 0)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def _metric_score(metric: str, value: float | None) -> float | None:
    if value is None:
        return None
    xs, ys = _BREAKPOINTS[metric]
    return _interp(float(value), xs, ys)


def _band_score(row: dict, band: str) -> float | None:
    """Composite 0–100 climate score for one emissions band (equal-weight legs)."""
    leg_scores: list[float] = []
    for metrics in _LEGS.values():
        parts = [_metric_score(m, _num(row.get(f"{m}_{band}"))) for m in metrics]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        leg_scores.append(sum(parts) / len(parts))
    return round(sum(leg_scores) / len(leg_scores), 1)


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_rows(path: pathlib.Path, width: int) -> dict[str, dict]:
    """geoid (zero-padded to ``width``) → raw CMRA row, from a CSV or .csv.gz."""
    table: dict[str, dict] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            geoid = str(row["geoid"]).strip().zfill(width)
            if geoid:
                table[geoid] = row
    return table


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → raw CMRA row."""
    return _load_rows(_CSV, 5) if _CSV.exists() else {}


@lru_cache(maxsize=1)
def _tract_table() -> dict[str, dict]:
    """tract GEOID (11-digit) → raw CMRA row. Empty unless a tract crosswalk
    is bundled (none is today — see module docstring)."""
    path = _TRACT_CSV_GZ if _TRACT_CSV_GZ.exists() else _TRACT_CSV
    return _load_rows(path, 11) if path.exists() else {}


@lru_cache(maxsize=1)
def _national_average() -> tuple[float | None, float | None]:
    """National mean of the low/high composite scores (the unmapped fallback)."""
    lows, highs = [], []
    for row in _table().values():
        lo, hi = _band_score(row, "low"), _band_score(row, "high")
        if lo is not None:
            lows.append(lo)
        if hi is not None:
            highs.append(hi)
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    return avg(lows), avg(highs)


def _us_result() -> dict:
    """National-average fallback (used when no county/tract row resolves)."""
    low, high = _national_average()
    return {
        "label": US_AVG_LABEL,
        "score": low,
        "score_low": low,
        "score_high": high,
        "hazards": {},
        "drivers": {},
        "resolved": False,
        "geo_level": "us",
    }


def _resolved_result(row: dict, geo_level: str, geoid: str) -> dict | None:
    """Build a resolved climate-projection result from a raw CMRA row.

    Returns None if the row can't yield a low-band composite (e.g. a missing
    hazard leg), so callers can fall back to a coarser geography.
    """
    score_low = _band_score(row, "low")
    if score_low is None:
        return None
    hazards = {
        leg: {
            "low": _leg_score(row, metrics, "low"),
            "high": _leg_score(row, metrics, "high"),
        }
        for leg, metrics in _LEGS.items()
    }
    drivers = {
        m: {b: _num(row.get(f"{m}_{b}")) for b in ("hist", "low", "high")}
        for m in _BREAKPOINTS
    }
    name = (row.get("county_name") or "").strip()
    state = (row.get("state") or "").strip()
    place = f"{name}, {state}".strip(", ") or geoid
    if geo_level == "tract":
        place = f"Census Tract {geoid} ({place})"
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "score": score_low,
        "score_low": score_low,
        "score_high": _band_score(row, "high"),
        "hazards": hazards,
        "drivers": drivers,
        "resolved": True,
        "geo_level": geo_level,
    }


def climate_projection_for_county(county_fips: str | None) -> dict:
    """Return the climate-projection sub-score + bands for a 5-digit county FIPS.

    Always returns a dict (never None). For a county in the crosswalk it carries
    the resolved low/high composite scores and the projected hazard drivers
    (``geo_level="county"``); for a missing/unmapped county it falls back to the
    national-average score with ``resolved=False`` and ``geo_level="us"``.

    Keys: ``label``, ``score`` (headline = low band), ``score_low``,
    ``score_high``, ``hazards`` (per-leg low/high), ``drivers`` (raw hist/low/high
    per metric), ``resolved``, ``geo_level``.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    row = _table().get(fips) if fips else None
    # Unmapped county, or a row missing a hazard leg (so the low band can't be
    # computed): fall back to the national average so callers always get a
    # concrete float, never None.
    result = _resolved_result(row, "county", fips) if row is not None else None
    return result or _us_result()


def climate_projection_for_tract(tract_geoid: str | None) -> dict:
    """Return the climate-projection sub-score + bands for an 11-digit tract GEOID.

    Resolution-aware: a tract in the (optional) tract crosswalk resolves at
    ``geo_level="tract"``; otherwise it falls back to its parent county (the first
    5 digits of the GEOID), then to the national average. Same dict shape as
    ``climate_projection_for_county``. No tract crosswalk is bundled today (see
    module docstring), so this resolves at the parent county — but the plumbing is
    ready for a genuinely finer tract dataset to drop in.
    """
    geoid = str(tract_geoid).strip().zfill(11) if tract_geoid else None
    if geoid:
        row = _tract_table().get(geoid)
        if row is not None:
            result = _resolved_result(row, "tract", geoid)
            if result is not None:
                return result
        return climate_projection_for_county(geoid[:5])
    return climate_projection_for_county(None)


def _leg_score(row: dict, metrics: list[str], band: str) -> float | None:
    parts = [_metric_score(m, _num(row.get(f"{m}_{band}"))) for m in metrics]
    parts = [p for p in parts if p is not None]
    return round(sum(parts) / len(parts), 1) if parts else None
