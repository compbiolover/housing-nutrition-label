"""Per-county climate-hazard projections (CMRA / NCA4, keyless + offline).

Returns a 0–100 **Climate Projections** sub-score (higher = a less hazardous
projected future climate) for a county, plus the low/high emissions band and the
underlying projected hazard drivers. Replaces the former uniform placeholder so
the climate dimension reflects the county's real downscaled projections.

Data
----
County values come from the NOAA/DOI **Climate Mapping for Resilience and
Adaptation (CMRA)** screening dataset — LOCA-downscaled CMIP5 (NCA4) projections
aggregated to counties as 30-year means, bundled offline as
``climate_projections.csv`` by ``scripts/build_climate_projections.py``. We use
the **mid-century (~2050) ensemble mean** under two pathways:

  • low band  = RCP4.5  (≈ SSP2-4.5 analog)
  • high band = RCP8.5  (≈ SSP5-8.5 analog)

across five hazard metrics grouped into three legs:

  • heat    — days > 95 °F and days > 100 °F
  • precip  — days > 1" precip and the annual max 5-day precip total (flood)
  • drought — annual max consecutive dry days

The composite climate score is the equal-weight mean of the three legs; the
headline ``score`` uses the low (RCP4.5) band, with the high (RCP8.5) band
surfaced as the downside.

Caveats
-------
CMRA is a ~6 km downscaled grid aggregated to counties — a **county aggregate,
never parcel-scale precision**. It is CMIP5/RCP (not CMIP6/SSP); RCP4.5/8.5 are
treated as low/high analogs of SSP2-4.5/5-8.5. CMRA carries no native Fire
Weather Index, so the drought leg (consecutive dry days) stands in for the
fire/drought hazard until a 12 km ClimRR FWI layer is added. Counties absent from
the crosswalk fall back to the national-average score, with the label flagging it.
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

DATA_VINTAGE = "CMRA NCA4 (RCP4.5–8.5, mid-century)"
US_AVG_LABEL = f"US average ({DATA_VINTAGE})"

_CSV = pathlib.Path(__file__).resolve().parent / "climate_projections.csv"

# Per-hazard scoring breakpoints: (increasing-hazard x values, matching 0–100 y
# values). Anchored to the national quantiles of the RCP4.5 mid-century
# distribution (printed by build_climate_projections.py), so a county scores by
# where its projected hazard sits nationally. Higher hazard → lower score.
# xs strictly increasing; values clamp to the end scores outside the range.
_BREAKPOINTS: dict[str, tuple[list[float], list[float]]] = {
    # days/yr > 95 °F           p5≈1  p25≈12  p50≈28  p75≈51  p90≈70  p95≈86
    "heat_days95":      ([1, 12, 28, 51, 70, 90],     [100, 80, 60, 40, 20, 0]),
    # days/yr > 100 °F          p5≈0  p25≈2.4 p50≈7   p75≈15.5 p90≈31  p95≈40
    "heat_days100":     ([0.5, 2.4, 7, 15.5, 31, 45], [100, 80, 60, 40, 20, 0]),
    # days/yr > 1" precip       p5≈0.8 p25≈2.8 p50≈5.1 p75≈8.1 p90≈11  p95≈12
    "precip_days1in":   ([1, 3, 5, 8, 11, 13],        [100, 80, 60, 40, 20, 0]),
    # annual max 5-day precip   p5≈2.1 p25≈3.3 p50≈4.1 p75≈4.9 p90≈5.6 p95≈6.1
    "precip_max5day":   ([2, 3.3, 4.1, 5, 6, 7.5],    [100, 80, 60, 40, 20, 0]),
    # max consecutive dry days  p5≈10.5 p25≈13.3 p50≈16 p75≈21 p90≈29 p95≈36
    "drought_consecdd": ([10, 13, 16, 21, 29, 40],    [100, 80, 60, 40, 20, 0]),
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


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → raw CMRA row."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open() as f:
        for row in csv.DictReader(f):
            fips = str(row["geoid"]).strip().zfill(5)
            if fips:
                table[fips] = row
    return table


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


def climate_projection_for_county(county_fips: str | None) -> dict:
    """Return the climate-projection sub-score + bands for a 5-digit county FIPS.

    Always returns a dict (never None). For a county in the crosswalk it carries
    the resolved low/high composite scores and the projected hazard drivers; for
    a missing/unmapped county it falls back to the national-average score with
    ``resolved=False`` and the label flagging it.

    Keys: ``label``, ``score`` (headline = low band), ``score_low``,
    ``score_high``, ``hazards`` (per-leg low/high), ``drivers`` (raw hist/low/high
    per metric), ``resolved``.
    """
    row = _table().get(str(county_fips).strip().zfill(5)) if county_fips else None
    if row is None:
        low, high = _national_average()
        return {
            "label": US_AVG_LABEL,
            "score": low,
            "score_low": low,
            "score_high": high,
            "hazards": {},
            "drivers": {},
            "resolved": False,
        }

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
    place = f"{name}, {state}".strip(", ") or str(county_fips)
    return {
        "label": f"{place} ({DATA_VINTAGE})",
        "score": _band_score(row, "low"),
        "score_low": _band_score(row, "low"),
        "score_high": _band_score(row, "high"),
        "hazards": hazards,
        "drivers": drivers,
        "resolved": True,
    }


def _leg_score(row: dict, metrics: list[str], band: str) -> float | None:
    parts = [_metric_score(m, _num(row.get(f"{m}_{band}"))) for m in metrics]
    parts = [p for p in parts if p is not None]
    return round(sum(parts) / len(parts), 1) if parts else None
