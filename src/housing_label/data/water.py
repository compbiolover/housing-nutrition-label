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
The exposure share is a **zero-inflated** variable — ~28% of counties (~27% of the
CWS population) sit at exactly 0% (no recent health-based violation), a genuine and
common optimum — so it is scored with a **hurdle (two-part) model** rather than a
single percentile:

  • **X == 0 → 100.** A spotless county has achieved the best possible outcome; all
    such ties for first receive the top score.
  • **X > 0 → the conditional national percentile among the exposed population** —
    the share of residents-on-a-flagged-system whose exposure is worse than this
    county's (lower exposure → higher score). This is continuous with the clean
    class (the least-exposed county ≈ 100) and monotone down to 0 at full exposure.

This replaces an earlier single population-weighted percentile with **mid-rank**
tie-breaking, which capped a spotless county at the tie-adjusted rank of the zero
mass (~86.5) — so "perfect water" could never read as ~100 and the score fell off a
cliff at the first sign of any exposure. Mid-rank is only appropriate when ties are
a measurement artifact; here 0 is a real, reachable optimum, so the two parts are
scored on their own terms. Anchors come from scripts/build_water.py.

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

# ── Hurdle (two-part) score for a zero-inflated exposure variable ─────────────────
# `pct_pop_hb_violation` piles a huge point mass at its own optimum: ~28% of
# counties (~27% of the CWS population) sit at exactly 0% — no recent health-based
# violation, the best achievable outcome. A single population-weighted percentile
# with mid-rank tie-breaking capped that spotless mass at its tie-adjusted rank
# (0.73 strictly-worse + 0.27/2 tied ≈ 86.5) — so "perfect water" could never reach
# ~100, and the score fell off a cliff at the first sign of any exposure. Mid-rank
# is only right when ties are a measurement artifact; here 0 is a genuine, common
# optimum, so we score the two parts separately:
#
#   • X == 0  → 100  (the "clean class"; ties for first all win).
#   • X  > 0  → the county's population-weighted CONDITIONAL national percentile
#     among the EXPOSED population — the share of residents-on-a-flagged-system
#     whose exposure is *worse* than this county's. Continuous with the clean class
#     (the least-exposed county ≈ 100, no cliff) and monotone down to 0 at full
#     exposure. HIGHER score = safer.
#
# `_EXPOSED_*` are the conditional-survival anchors of the exposed distribution,
# emitted by scripts/build_water.py (`--print-anchors`); X == 0 is handled directly
# in water_for_county, so these cover only the X > 0 branch.
_EXPOSED_XS = [0.001, 0.2, 0.5, 1.0, 2.0, 5.0, 11.83, 25.0, 52.72, 76.16, 100.0]
_EXPOSED_YS = [100.0, 90.5, 83.9, 78.7, 68.6, 49.3, 34.2, 23.5, 12.0, 6.8, 0.0]


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
    pct = rec["pct_pop_hb_violation"]
    # Hurdle: a spotless county (no recent health-based violation) is the optimum →
    # top score; any exposure is scored by its conditional rank among the exposed.
    score = 100.0 if pct <= 0 else _interp(pct, _EXPOSED_XS, _EXPOSED_YS)
    return {
        "score": round(score, 1),
        "pct_pop_hb_violation": pct,
        "n_cws": rec["n_cws"],
        "geo_level": "county",
        "label": WATER_VINTAGE,
    }
