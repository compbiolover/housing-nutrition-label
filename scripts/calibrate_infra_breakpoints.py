#!/usr/bin/env python3
"""Calibrate the Infrastructure Burden fiscal-ratio → score breakpoints to a
NATIONAL distribution (replacing the original Shelby-pilot-anchored thresholds).

Why
---
``src/housing_label/score/all_dimensions.py`` maps a parcel's fiscal ratio (property-tax revenue ÷
modeled cost-to-serve) to a 0–100 score via ``INFRA_XS`` breakpoints. Those were
anchored to the Shelby pilot's distribution, so once the cost and revenue sides
were localized per county (Census of Governments + ACS), the absolute grades were
no longer defensible nationally. This tool builds a national distribution of
fiscal ratios and prints percentile-anchored breakpoints so a given score means
roughly the same national percentile everywhere (e.g. a D ≈ bottom 20–40%).

Method (reproducible, from already-bundled crosswalks — no downloads)
--------------------------------------------------------------------
Build the national distribution over a grid of {US county} × {density archetype}:

  • county inputs (bundled): median home value + effective property-tax rate
    (``property_tax_county.csv``); per-function cost multipliers + population
    (``govfinance_county.csv``).
  • density archetypes: a documented spread of US residential densities, each with
    an approximate national household share (DENSITY_ARCHETYPES below).
  • each (county, archetype) fiscal ratio is computed with the SAME cost model the
    app uses (``housing_label.enrich.infrastructure.enrich_row``), and weighted by
    county population × archetype share — so the distribution reflects where US
    homes actually are, across the real density mix.

The printed percentiles are then baked into ``INFRA_XS`` (the repo's pattern:
breakpoints anchored to a printed national distribution, kept as a static const).

Run:  python scripts/calibrate_infra_breakpoints.py
"""

from __future__ import annotations

import csv
import pathlib

import pandas as pd

from housing_label.enrich.infrastructure import enrich_row
from housing_label.enrich.region_context import infra_params_for_county

_DATA = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

# Documented spread of US residential densities (DU/acre) with approximate national
# household shares. These are deliberately coarse but transparent — adjust the
# shares to reweight the reference mix. (Most US households are single-family on
# small-to-moderate lots, with a meaningful urban-multifamily tail.)
# Renter shares are ACS 2024 5-yr table B25032 (tenure by units in structure): 14.0% of
# 1-unit detached homes are renter-occupied, rising to 90.2% in 10-19 unit structures.
# Each archetype contributes TWO weighted points — an owner leg and a renter leg — with
# the total weight unchanged, so the only delta classification introduces is the
# reclassification of renter legs in states that have a rule. That keeps any movement in
# the breakpoints fully attributable.
#
# The multifamily split, and why there are two rows rather than one
# -----------------------------------------------------------------
# Until this was added the densest archetype was a 10-unit parcel, so the reference
# distribution contained NO mid-rise or high-rise anywhere — and every large apartment
# building in the country was percentile-ranked against a population of houses, duplexes
# and small walk-ups. Because large buildings spread road, water and sewer cost over many
# doors, they carry unusually high fiscal ratios, so excluding them held the top of the
# distribution artificially low and inflated their own percentiles.
#
# That was not a tail case. ACS 2024 5-yr B25032, occupied units by structure size:
#
#     band     occupied     % of all occupied     renter %
#     5-9      5,703,565          4.4%              88.3%
#     10-19    5,368,125          4.2%              90.2%
#     20-49    4,691,626          3.6%              87.1%
#     50+      8,206,790          6.4%              86.6%
#
# Structures of 20+ units are 53.8% of the 5+ segment — the MAJORITY of multifamily
# housing, not its tail — and the 50+ band alone is larger than any other multifamily
# band. So the existing 0.15 urban share is split 46.2/53.8 into the two rows below.
#
# Three judgment calls, recorded so they can be argued with:
#   • 50 DU/acre for the large row (a 50-unit building on ~1 acre). The top anchor lands
#     at 1.488 / 1.553 / 1.568 for 35 / 50 / 65 DU/acre, so this choice is worth ~5% at
#     p95 and almost nothing below p60. Its influence is bounded on purpose: the roads
#     and water/sewer cost anchors in enrich/infrastructure.py top out at 48 DU/acre and
#     interp_cost CLAMPS FLAT above the last anchor, so picking 50 rather than 65 or 200
#     cannot buy the archetype unlimited density credit. That is why 35 (below the clamp,
#     still interpolating) moves the anchor more than 65 (above it) does.
#   • units=50 represents the 20+ band because 50+ (8.2M) outweighs 20-49 (4.7M).
#   • the 5-19 row's renter share is 0.892, the combined 5-9/10-19 figure. It was 0.902,
#     which is the 10-19 figure alone and was right only while the row meant "10 units".
#
# KNOWN COARSENESS, deliberately not fixed here: B25032 puts 5+ unit structures at 18.5%
# of occupied units, against the 0.15 assigned here. The other four shares are round
# numbers that do not map onto ACS structure categories at all — "compact suburb /
# townhome" is 8 DU/acre carrying units=1 — so rebalancing the whole roster is a separate
# redesign, not a tweak. Splitting within the existing 0.15 keeps this change attributable.
#
# The rural split, and why one row was not enough
# -----------------------------------------------
# A single "rural / exurban (~2 ac)" row at 0.5 DU/acre was the sparsest thing in
# the reference distribution, so every genuinely large-lot home in the country was
# percentile-ranked against a population whose biggest lot was two acres. Those
# homes are not a rounding error. Census/CoreLogic property-tax records matched to
# the 2015 AHS (Census Bureau, "Imputing Lot Size with Property Tax Data",
# exhibit 4.1, all tenures) put the national lot-size distribution at:
#
#     1 up to 5 acres    11.6%      (respondent-reported: 17.7%)
#     5 up to 10 acres    2.5%      (respondent-reported:  2.7%)
#     10 acres or more    2.1%      (respondent-reported:  2.3%)
#
# The property-tax column is used rather than the respondent column because it is
# measured rather than recalled, and the same paper documents that owners
# systematically report their lots as larger than the tax record shows.
#
# So 4.6% of US housing sits on five acres or more — comparable to the entire 5-19
# unit multifamily band (4.4%), which already has its own row. The existing 0.12
# rural share is split across the three bands in their observed proportions
# (11.6 : 2.5 : 2.1 of 16.2), keeping the rural total unchanged at 0.12 so the
# change stays attributable — the same reasoning as the multifamily split above.
#
# Representative densities are the harmonic-ish middle of each band rather than its
# edge: 1-5 ac -> 0.5 DU/acre (2 ac), 5-10 ac -> 0.135 (7.4 ac), 10+ ac -> 0.05
# (20 ac). The last is a judgment call, since the band is open-ended; the road and
# water/sewer curves clamp flat at 0.025 DU/acre (40 ac), so picking 0.05 rather
# than 0.03 is worth little and cannot buy the archetype unlimited sprawl penalty.
DENSITY_ARCHETYPES = [
    # (label, dwelling_units_per_acre, national_household_share, is_urban,
    #  units_on_parcel, renter_share)
    ("rural / exurban (1-5 ac)",     0.5,   0.086, False,  1, 0.140),
    ("large rural (5-10 ac)",        0.135, 0.019, False,  1, 0.140),
    ("very large rural (10+ ac)",    0.05,  0.015, False,  1, 0.140),
    ("large-lot suburb (~0.6 ac)",   1.5, 0.18,  False,  1, 0.140),
    ("standard suburb (~0.2 ac)",    4.0, 0.35,  True,   1, 0.140),
    ("compact suburb / townhome",    8.0, 0.20,  True,   1, 0.140),
    ("urban multifamily (5-19)",    20.0, 0.069, True,  10, 0.892),
    ("large multifamily (20+)",     50.0, 0.081, True,  50, 0.868),
]

# ── Utility connections, by archetype ─────────────────────────────────────────
# The roster above put every household on public water and public sewer. That is
# not a small omission, and it is not neutral: a home on a well and a septic field
# loses the water/sewer component from BOTH sides of the fiscal ratio, and because
# that component is ~100% fee-recovered — it pays for itself — removing it drags a
# below-break-even ratio DOWN. Measured on one rural parcel: 0.259 with public
# utilities, 0.133 with a well and a septic field. Same house, same services from
# the county, half the score.
#
# So a well/septic household was being ranked against a population that is entirely
# on public utilities, and could not help but land at the bottom. That is a
# measurement artifact, not a finding about the house. The reference distribution
# has to contain the same mix of connections the housing stock has.
#
# National shares (mutually exclusive states):
#   private well               14.1% of housing units   (US EPA)
#   septic                    ~20%   of households      (US EPA, >60M people)
#   BOTH well and septic        9.1% of households      (Hernandez et al. 2023,
#                                                        JAWRA 59(5), 10.1111/1752-1688.13135)
# giving public/public 75.0%, septic-only 10.9%, well-only 5.0%, both 9.1%.
#
# Allocated across the roster below, concentrated at the sparse end where these
# connections actually are. The household-weighted totals come to well 13.6%,
# septic 19.8%, both 9.3% — each within half a point of the national figure, which
# is as close as a per-archetype split of three national aggregates gets without
# inventing joint data nobody publishes.
#
# Keyed by archetype label so a new archetype raises KeyError here until its
# connection mix is stated, rather than silently defaulting to all-public — the
# same drift guard the rest of this file uses.
UTILITY_MIX = {
    # label: ((public_water, public_sewer, share_within_archetype), ...)
    "rural / exurban (1-5 ac)":   ((True, True, 0.10), (True, False, 0.18),
                                   (False, True, 0.10), (False, False, 0.62)),
    "large rural (5-10 ac)":      ((True, True, 0.04), (True, False, 0.10),
                                   (False, True, 0.08), (False, False, 0.78)),
    "very large rural (10+ ac)":  ((True, True, 0.03), (True, False, 0.07),
                                   (False, True, 0.07), (False, False, 0.83)),
    "large-lot suburb (~0.6 ac)": ((True, True, 0.58), (True, False, 0.25),
                                   (False, True, 0.11), (False, False, 0.06)),
    "standard suburb (~0.2 ac)":  ((True, True, 0.865), (True, False, 0.10),
                                   (False, True, 0.03), (False, False, 0.005)),
    "compact suburb / townhome":  ((True, True, 0.965), (True, False, 0.03),
                                   (False, True, 0.005), (False, False, 0.0)),
    "urban multifamily (5-19)":   ((True, True, 1.0),),
    "large multifamily (20+)":    ((True, True, 1.0),),
}

# KNOWN GAP, deliberately not modelled: incorporation. An unincorporated parcel
# drops municipal curbside collection from both sides too, but its effect on the
# ratio is a rounding error next to water/sewer (0.259 -> 0.262 on the same test
# parcel, because sanitation is small and only ~97% fee-recovered), so adding a
# third leg dimension would triple the point count to move nothing.

# Map each score anchor to a percentile of the national fiscal-ratio distribution,
# so the resulting score tracks national percentile rank (score ≈ percentile).
SCORE_PERCENTILES = [(0, 5), (20, 20), (40, 40), (60, 60), (80, 80), (100, 95)]


def _load(path: pathlib.Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            g = str(row.get("geoid", "")).strip().zfill(5)
            if g:
                out[g] = row
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_distribution() -> list[tuple[float, float]]:
    """Return [(fiscal_ratio, weight)] over all (county × archetype) points."""
    tax = _load(_DATA / "property_tax_county.csv")
    gov = _load(_DATA / "govfinance_county.csv")

    points: list[tuple[float, float]] = []
    for fips, trow in tax.items():
        if fips == "00000":
            continue
        value = _num(trow.get("median_value"))
        grow = gov.get(fips)
        # A county absent from the gov-finance crosswalk is skipped outright rather than
        # falling back to national-average cost. This is what keeps Puerto Rico out of the
        # reference distribution: its 72 municipios carry ACS tax data but no Census of
        # Governments rows, so a fallback would score them against a cost model that was
        # never measured there. infra_params_for_county WOULD supply that fallback, so the
        # check has to happen here, before it is called.
        if value is None or value <= 0 or grow is None:
            continue
        pop = _num(grow.get("pop")) or 0.0
        if pop <= 0:
            continue

        # Build the county's parameters with the SAME function the app uses, rather than
        # re-deriving them here. A second implementation would let the reference
        # distribution drift away from the model it is supposed to be the yardstick for,
        # which would quietly invalidate "score = national percentile".
        params = infra_params_for_county(fips)
        if params is None:
            # Shelby is the pilot: infra_params_for_county returns None so enrich_row
            # falls back to its Memphis statutory defaults. Deliberately skipped — one
            # county of ~3,140 carries negligible weight, and mixing a statutory basis
            # into a distribution built on observed effective rates would not be
            # like-for-like.
            continue

        for label, du_acre, share, urban, units, renter_share in DENSITY_ARCHETYPES:
            row = pd.Series({"CALC_ACRE": 1.0 / du_acre, "latitude": None,
                             "longitude": None, "RTOTAPR": value})
            utilities = UTILITY_MIX[label]     # KeyError = undocumented archetype
            for owner_occupied, tenure_share in ((True, 1.0 - renter_share),
                                                 (False, renter_share)):
                if tenure_share <= 0:
                    continue
                for pub_water, pub_sewer, util_share in utilities:
                    if util_share <= 0:
                        continue
                    out = enrich_row(row, in_urban_area=urban, units=units,
                                     owner_occupied=owner_occupied,
                                     public_water=pub_water, public_sewer=pub_sewer,
                                     **params)
                    fr = out.get("fiscal_ratio")
                    if fr is not None and not pd.isna(fr):
                        points.append((float(fr),
                                       pop * share * tenure_share * util_share))
    return points


def weighted_percentile(points: list[tuple[float, float]], pct: float) -> float:
    """Population-weighted percentile of the fiscal-ratio distribution."""
    if not points:
        raise ValueError("no fiscal-ratio points to take a percentile of")
    pts = sorted(points)
    total = sum(w for _, w in pts)
    if total <= 0:
        raise ValueError("total weight is zero — cannot compute a weighted percentile")
    target = total * pct / 100.0
    cum = 0.0
    for val, w in pts:
        cum += w
        if cum >= target:
            return val
    return pts[-1][0]


def main() -> int:
    points = build_distribution()
    if not points:
        raise SystemExit(
            "No fiscal-ratio points were produced — check that the bundled "
            "crosswalks (property_tax_county.csv, govfinance_county.csv) exist and "
            "have the expected columns.")
    print(f"National distribution: {len(points):,} (county × archetype) points, "
          f"weight = population × household share.\n")

    print("Fiscal-ratio percentiles (weighted):")
    for p in (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99):
        print(f"  p{p:<3} = {weighted_percentile(points, p):.3f}")

    xs = [round(weighted_percentile(points, p), 3) for _, p in SCORE_PERCENTILES]
    ys = [s for s, _ in SCORE_PERCENTILES]
    # Enforce strictly increasing xs (log-linear interp requires it).
    for i in range(1, len(xs)):
        if xs[i] <= xs[i - 1]:
            xs[i] = round(xs[i - 1] + 0.001, 3)

    print("\nSuggested national breakpoints (paste into src/housing_label/score/all_dimensions.py):")
    print(f"  INFRA_XS = {xs}")
    print(f"  INFRA_YS = {[float(y) for y in ys]}")
    print("\n(score ≈ national percentile rank: A=top 20%, B=60–80th, C=40–60th, "
          "D=20–40th, F=bottom 20%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
