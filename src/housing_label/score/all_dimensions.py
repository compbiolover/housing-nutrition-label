"""Score breakpoints and the letter-grade tables, shared by every scoring path.

What is left here after the Shelby batch scorer was retired: the two breakpoint
curves that are not owned by a data module (energy EUI and the infrastructure
fiscal ratio), the calibration basis behind the infrastructure one, and the two
grade functions.

  score_to_grade              absolute 0-100 -> A/B/C/D/F (A>=80 ... F<20)
  percentile_to_local_grade   0-100 percentile rank -> A/B/C/D/F
                              (A = top 10%, B = next 25%, C = next 30%,
                               D = next 25%, F = bottom 10%)

Both map a missing value to an em dash rather than "F": an unscored dimension is
not a failing one, and printing a grade for something we do not know would be a
claim about somebody's house that the data does not support.

One definition each, deliberately. simulate/dimensions.py and batch.py both
import from here, so a grade means exactly the same thing wherever it is read.
"""

from __future__ import annotations

import logging


from housing_label.utils import isna

# NOTE: no logging.basicConfig() at import time — this module is imported by the
# live scorer (simulate/dimensions.py pulls in its breakpoints + score_to_grade),
# so reconfiguring the root logger on import would leak CLI formatting into the
# API/simulator. main() configures logging at the CLI entrypoint instead.
log = logging.getLogger("score_all")



# Walk Score columns and the composite weighting (walk dominates, then transit,
# then bike) used when all three sub-scores are present for a parcel.



# ---------------------------------------------------------------------------
# Grade helpers — identical thresholds to score_resilience.py so grades are
# directly comparable across scripts.
# ---------------------------------------------------------------------------
def score_to_grade(score: float) -> str:
    """Absolute 0–100 score → letter grade (national grade)."""
    if isna(score):
        return "—"
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"


def percentile_to_local_grade(pct: float) -> str:
    """0–100 percentile rank → local letter grade.

    A = top 10%   (≥90th)   B = next 25% (≥65th)   C = middle 30% (≥35th)
    D = next 25%  (≥10th)   F = bottom 10% (<10th)
    """
    if isna(pct):
        return "—"
    if pct >= 90:
        return "A"
    if pct >= 65:
        return "B"
    if pct >= 35:
        return "C"
    if pct >= 10:
        return "D"
    return "F"




# ---------------------------------------------------------------------------
# Per-dimension raw scorers (each returns a 0–100 Series, NaN where unscored).
# ---------------------------------------------------------------------------
# Energy: lower EUI is better.  Breakpoints (EUI kBTU/sqft/yr → score):
#   ≤15→100, 25→80, 40→60, 55→40, 70→20, ≥90→0   (log-linear between).
ENERGY_XS = [15.0, 25.0, 40.0, 55.0, 70.0, 90.0]
ENERGY_YS = [100.0, 80.0, 60.0, 40.0, 20.0, 0.0]

# Infrastructure: higher fiscal ratio (revenue / cost of services) is better.
# Breakpoints are anchored to the NATIONAL distribution of fiscal ratios — a
# population-weighted reference over US counties × residential density archetypes,
# computed with the localized cost+revenue model (see
# scripts/calibrate_infra_breakpoints.py). The score therefore tracks national
# percentile rank: A = top ~20%, B = 60–80th, C = 40–60th, D = 20–40th,
# F = bottom ~20%.
#
# Both sides of the ratio cover the same services. NON-SCHOOL: the revenue is
# municipal property tax with the school-district share netted out, matching the
# school-excluded cost side. And FEE-INCLUSIVE: the revenue also counts modeled
# user-fee income (water, sewer, trash), because the cost side counts those
# services in full and residents pay for them through bills rather than property
# tax. Counting the cost but not the fee was the single largest distortion in this
# dimension — it put the national median fiscal ratio at 0.31, implying almost no
# American home comes close to paying its way.
#
# The national median is now ≈ 0.67 → score ≈ 50: the typical US home covers about
# two-thirds of what it costs to serve, and ~18% of homes clear 1.0 (p90 ≈ 1.23).
# The remaining gap is real, not an artifact — fire and police have no user charge
# anywhere in the Census data, so property tax is the only thing paying for them.
#
# The reference mix now includes a large-multifamily archetype (20+ units). Before it,
# the densest point in the distribution was a 10-unit parcel, so every mid-rise and
# high-rise in the country was ranked against a population of houses, duplexes and small
# walk-ups — and since big buildings spread infrastructure cost over many doors, leaving
# them out held the top of the distribution low and inflated their own percentiles. Adding
# them raised p95 by 6.7% (1.456 → 1.553) and everything below p60 by under 1%, so an A is
# modestly harder to earn than it was, which is the correct direction.
# Reading of the constants below, with all six anchors rounded to 2dp — the exact values
# are the list itself, which is generated by the calibrator and pasted verbatim:
#   ≥1.62→100, 0.99→80, 0.75→60, 0.61→40, 0.47→20, ≤0.33→0   (log-linear between).
#
# Re-anchored again when Texas moved onto MEASURED school netting (data/school_millage.py).
# The revenue side used to net schools by multiplying an owner-occupied ACS rate by an
# all-property school share; in Texas, where the homestead exemption is school-specific,
# that removed the school component twice. Computing the owner's school tax and subtracting
# it lifted the Texas municipal rate by ~34% population-weighted, which is 9.2% of the
# reference distribution — so the top of the curve moved (p95 1.565 → 1.623) while the
# bottom barely did (p5 0.325 → 0.326). Texas homes score better; everyone else moves only
# by being ranked against them.
#
# Re-anchored again when the cost model stopped double-counting ruralness.
#
# ``enrich_row`` multiplied the Halifax density shape straight into the county's
# Census-of-Governments per-capita spending multiplier. That charges a rural county
# twice for the same sparseness — its measured per-capita spending is already
# elevated because its households are spread out — and it produced figures like
# $9,137/yr to serve one rural household, implying ~$178M/yr of local spending for
# a county of 47,694 people. The shape is now expressed relative to the density
# that county's own spending was observed at (see SHELBY_LOT_DU_ACRE in
# enrich/infrastructure.py).
#
# The two changes move the distribution in OPPOSITE directions, and the result is a
# widening rather than a shift:
#
#   * the normalization lowers modeled cost for counties sparser than the Shelby
#     pilot — most of them — lifting the middle and the top:
#     p50 0.671 -> 0.689, p95 1.622 -> 1.738.
#   * the utility mix introduces well/septic households, whose ratios are genuinely
#     low, deepening the bottom: p5 0.321 -> 0.296, p1 0.212 -> 0.171.
#
# Percentile RANK is what the score tracks, so a typical home barely moves. What
# changes is that a parcel's rank reflects its own density relative to its county
# rather than how rural the county is, and that an off-network home is ranked
# against a population that contains off-network homes.
INFRA_XS = [0.296, 0.463, 0.619, 0.77, 1.044, 1.738]
INFRA_YS = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]

# Which jurisdictions carried an active property-tax classification correction when the
# breakpoints above were last computed, and at what multiplier. The reference
# distribution has to be built by the same model the app runs, or "score = national
# percentile" stops being true — so adding a state to data/assessment.py without
# re-running scripts/calibrate_infra_breakpoints.py must fail loudly rather than quietly
# mis-scoring every parcel in the country. tests/test_infra_breakpoints.py recomputes this
# from the rules table and asserts it matches.
#
# A sorted tuple rather than a hash, so the diff is legible: a reviewer sees exactly which
# jurisdictions entered the distribution and at what strength.
#
# The NY/<fips> entries are New York City's five boroughs, reached through the rules
# table's sub_state map. New York City's correction starts at 11 dwelling units (RPTL
# § 1805(2)), so it reaches the reference distribution only through the large-multifamily
# archetype; while the densest archetype was a 10-unit building the city's rule was live
# for a real label request and invisible to the yardstick. That gap is now closed.
#
# It still contributes almost nothing to the anchors, and that is expected rather than
# suspicious: five counties out of ~3,140 cannot move a population-weighted national
# percentile. Dropping NY entirely and recalibrating leaves p95 at 1.553, unchanged to
# three decimals. Encoding it matters for the parcels it scores, not for the yardstick.
INFRA_XS_BASIS = ("AL:2.00", "MN:1.25", "MS:1.50", "ND:1.11",
                  "NY/36005:1.81", "NY/36047:1.81", "NY/36061:1.81",
                  "NY/36081:1.81", "NY/36085:1.81", "SC:1.50", "TN:1.60", "WV:2.00")
















# ---------------------------------------------------------------------------
# Dimension registry.  `requires` is the source column that must be present;
# `composite` flags whether the dimension feeds the composite average.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------






