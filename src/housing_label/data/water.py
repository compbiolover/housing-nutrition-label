"""Drinking-water quality by location — EPA SDWIS compliance (keyless + offline).

Backs the **Water Quality** dimension: how safe the tap water is at a location,
scored 0-100 where higher = cleaner (fewer residents on a community water system
with a recent health-based violation). One national layer, looked up by 5-digit
county FIPS with no network call:

  • **Health-based violation exposure** — the share of the county's **community-
    water-system-served population** (residents on an active CWS — not all county
    residents, so private wells are out of scope) that is on a system with a
    health-based drinking-water violation (a contaminant exceedance or treatment-
    technique failure that can affect health — as opposed to a paperwork/monitoring
    lapse) whose non-compliance period began within the trailing 5-year window.
    Lower is better; a spotless county sits at 0%.

Scoring
-------
The exposure percentage is mapped to a 0-100 score by piecewise-linear
interpolation over the **population-weighted national distribution** (lower
exposure → higher score), so the score reads directly as "cleaner tap water than
N% of US homes" — an identity national percentile in
``data/national_percentile.py``, comparable across locations. Because a large share
of the population (~27%) lives in a county with zero recent health-based exposure,
the spotless anchor is the tie-adjusted percentile of that mass (not 100), and the
remaining anchors are the strict "cleaner-than" population share at each exposure
level.

Data
----
  water_county.csv, built by scripts/build_water.py from the EPA Safe Drinking
  Water Information System (SDWIS) federal-reporting bulk export (community water
  systems, geographic-area county mapping, and health-based violations).

Scope: US counties with at least one active community water system in SDWIS —
CONUS, Alaska, Hawai'i, and Puerto Rico. A county with no CWS in the table (or a
missing/blank FIPS) returns None, so the caller leaves Water Quality unscored.

Source (public domain): EPA SDWIS. https://www.epa.gov/ground-water-and-drinking-water/safe-drinking-water-information-system-sdwis-federal-reporting
"""

from __future__ import annotations

import csv
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

WATER_VINTAGE = "EPA SDWIS federal reporting (community water systems, health-based violations, 5-yr window)"

_CSV = pathlib.Path(__file__).resolve().parent / "water_county.csv"

# ── Score breakpoints: (pct of population on a CWS with a recent health-based
# violation → score) — a piecewise-linear approximation to the population-weighted
# national CDF, so the score reads directly as a national percentile. LOWER
# exposure = HIGHER score. The first two anchors handle the zero-inflated spike:
# ~27% of the population lives in a spotless (0%) county, so pct=0 maps to the
# tie-adjusted percentile of that mass (~86.5) and drops immediately once any
# exposure appears; the remaining anchors are the strict "cleaner-than" population
# share at each exposure level (from scripts/build_water.py). HIGHER score = safer.
_PCT_XS = [0.0, 0.001, 0.5, 1.0, 2.0, 5.0, 11.83, 25.0, 52.72, 76.16, 100.0]
_PCT_YS = [86.5, 73.0, 61.3, 57.5, 50.1, 36.0, 25.0, 17.2, 8.8, 5.0, 0.5]


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
    """county FIPS (5-digit) → {pct_pop_hb_violation, cws_pop, n_cws}."""
    table: dict[str, dict] = {}
    if not _CSV.exists():
        return table
    with _CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("county_fips") or "").strip()
            if not raw:
                continue
            pct = _num(row.get("pct_pop_hb_violation"))
            if pct is None:
                continue
            cws_pop = _num(row.get("cws_pop"))
            n_cws = _num(row.get("n_cws"))
            table[raw.zfill(5)] = {
                "pct_pop_hb_violation": pct,
                # cws_pop / n_cws are counts — keep them as ints, not floats.
                "cws_pop": None if cws_pop is None else int(cws_pop),
                "n_cws": None if n_cws is None else int(n_cws),
            }
    return table


def water_for_county(county_fips: str | None) -> dict | None:
    """Water Quality reading + 0-100 score for a 5-digit county FIPS.

    Returns a dict with ``score`` (higher = safer / less health-based exposure),
    ``pct_pop_hb_violation`` (share of CWS population with a recent health-based
    violation), ``n_cws`` (community water systems in the county), ``geo_level``,
    and ``label`` — or None for a missing/blank FIPS or a county with no community
    water system in SDWIS, so the caller leaves Water Quality unscored.
    """
    if not county_fips:
        return None
    rec = _table().get(str(county_fips).strip().zfill(5))
    if rec is None:
        return None
    return {
        "score": round(_interp(rec["pct_pop_hb_violation"], _PCT_XS, _PCT_YS), 1),
        "pct_pop_hb_violation": rec["pct_pop_hb_violation"],
        "n_cws": rec["n_cws"],
        "geo_level": "county",
        "label": WATER_VINTAGE,
    }
