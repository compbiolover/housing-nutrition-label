"""Rooftop solar potential by location — PVGIS specific yield (keyless + offline).

Backs the **Solar Potential** dimension: how productive a rooftop solar array is at
a location, scored 0-100 where higher = sunnier / more kWh per installed kW. One
national, openly-licensed layer (PVGIS, CC BY 4.0) looked up by 5-digit county
FIPS with no network call:

  • **Specific yield** — the annual energy a standard 1 kWp rooftop array produces
    (kWh per kW installed per year), modeled by the EU JRC's **PVGIS** performance
    model on the **PVGIS-NSRDB** satellite database (the same NREL NSRDB resource
    PVWatts uses), for a building-mounted array at the optimal tilt facing south
    with 14% system losses. A sunny Southwest county (~1,700+) roughly doubles a
    cloudy Pacific-Northwest one (~950).

Scoring
-------
The specific yield is mapped to a 0-100 score by piecewise-linear interpolation
over the **national county quantiles** (higher yield → higher score), so the score
reads directly as "sunnier than N% of US counties" — an identity national
percentile in ``data/national_percentile.py``, comparable across locations.

The dimension's drill-down turns the yield into an actionable estimate for a
representative ``TYPICAL_SYSTEM_KW`` array — annual production, the dollars it
offsets at the location's electricity rate, and the CO₂ it avoids at the marginal
grid rate — but those dollar/carbon figures are assembled in the scoring pipeline
(which already resolves the utility rate and the Cambium marginal factor), not here.

Data
----
  solar_yield_county.csv, built by scripts/build_solar.py from PVGIS v5.2 queried
  at each county's Census-gazetteer internal point (PVGIS-NSRDB, ~2005–2015).

Scope: US counties within PVGIS-NSRDB coverage — CONUS, Hawai'i, Puerto Rico, and
the parts of Alaska the database reaches (~14 southern/coastal boroughs, which
score low: their high-latitude yield bottoms out the national range). Far-north
Alaska is outside coverage, absent from the table, and ``solar_for_county``
returns None there, so the caller leaves Solar Potential unscored.

Source (CC BY 4.0): PVGIS © European Union, 2001-2024. https://re.jrc.ec.europa.eu/
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

SOLAR_VINTAGE = "PVGIS-NSRDB v5.2 (optimal-tilt 1 kWp rooftop, 14% losses)"

# Representative residential array for the drill-down's production / savings estimate.
TYPICAL_SYSTEM_KW = 6.0

_CSV = pathlib.Path(__file__).resolve().parent / "solar_yield_county.csv"

# ── Score breakpoints: (specific yield kWh/kWp → score) — a piecewise-linear
# approximation to the national CDF, so the score reads directly as a national
# percentile. HIGHER yield = HIGHER score. Anchors are the county-yield quantiles
# [p0/min, p1, p5, p10, p25, p50, p75, p90, p95, p99, p100/max] from
# scripts/build_solar.py. The extra low-tail anchors (p1, p5) keep a few very-low
# Alaska outliers at the p0 min from stretching cloudy northern counties upward.
_YIELD_XS = [485.2, 1041.3, 1172.4, 1215.0, 1287.0, 1368.0, 1433.4, 1559.0, 1654.1, 1765.3, 1850.9]
_YIELD_YS = [0.0, 1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0, 99.0, 100.0]


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


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    """county FIPS (5-digit) → {yield_kwh_kwp, irradiation}."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("county_fips") or "").strip()
            if not raw:
                continue
            y = _num(row.get("specific_yield_kwh_kwp"))
            if y is None:
                continue
            table[raw.zfill(5)] = {
                "yield_kwh_kwp": y,
                "irradiation": _num(row.get("irradiation_kwh_m2")),
            }
    return table


def solar_for_county(county_fips: str | None) -> dict | None:
    """Solar Potential reading + 0-100 score for a 5-digit county FIPS.

    Returns a dict with ``score`` (higher = sunnier), ``yield_kwh_kwp`` (annual kWh
    per installed kW), ``irradiation`` (kWh/m²/yr), ``geo_level``, and ``label`` —
    or None for a missing/blank FIPS or a county outside PVGIS coverage, so the
    caller leaves Solar Potential unscored.
    """
    if not county_fips:
        return None
    rec = _table().get(str(county_fips).strip().zfill(5))
    if rec is None:
        return None
    return {
        "score": round(_interp(rec["yield_kwh_kwp"], _YIELD_XS, _YIELD_YS), 1),
        "yield_kwh_kwp": rec["yield_kwh_kwp"],
        "irradiation": rec["irradiation"],
        "geo_level": "county",
        "label": SOLAR_VINTAGE,
    }
