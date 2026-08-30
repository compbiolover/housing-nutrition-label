"""Disaster-resilience scoring: the Expected Annual Loss model behind the label.

Methodology: Expected Annual Loss Rate (EAL Rate = EAL / property value)
EAL Rate is dimensionless (fraction of property value lost per year, on average).

Four independent hazards are modeled and summed:
  1. Flood        — FEMA flood zone damage curves
  2. Tornado      — path-area strike probability × EF-scaled damage ratios
  3. Seismic      — two-point hazard curve integration (2%/50yr + 10%/50yr)
  4. Fire         — structural-fire baseline + FEMA NRI wildfire EAL (location-based)

Each hazard's raw EAL rate is multiplied by a Building Resilience Modifier (BRM)
derived from CAMA construction attributes (year built, wall type, foundation,
condition). BRM = 1.0 is the baseline; values < 1.0 indicate more resilient
construction; values > 1.0 indicate greater vulnerability.

Composite adjusted EAL rate is mapped to a 0-100 score via log-linear
interpolation, then translated to a letter grade. Per-hazard sub-scores use
the same mapping.

Sources / rationale are cited at each threshold.

Importable functions only. The Shelby County batch scorer that used to drive
these over a parcel CSV was retired along with the enrichment stages that fed
it; simulate/house.py and simulate/dimensions.py are the callers now.
"""

import logging

import numpy as np

from housing_label.utils import isna

# NOTE: no logging.basicConfig at import time — this module is imported by the
# live simulator/API (simulate/house.py pulls in the shared BRM factors), and
# reconfiguring the root logger on import would leak into that process. The
# application boundary that configures logging is api.serve().
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

# Default input is the LAST enrichment in the chain (fire). The chained file
# already carries the CAMA columns forward from clean_parcels plus all
# hazard/energy/infra/health/wildfire columns.

# CAMA construction columns (PARCELID is the join key; the rest are values).

# ---------------------------------------------------------------------------
# 1. FLOOD EAL RATE
# ---------------------------------------------------------------------------
# Source: FEMA NFIP actuarial studies and USACE depth-damage curves.
# Annual exceedance probability (AEP) × mean damage ratio (MDR).
#
# Zone AE  = 1% AEP floodplain (100-yr flood).  MDR ≈ 28% based on FEMA's
#            average residential structure losses in AE zones (FEMA 2022 NFIP
#            actuarial data; Zhu et al. 2020 depth-damage review).
# Zone X (moderate / shaded) = 0.2% AEP (500-yr).  MDR ≈ 15%: shallower
#            average flood depths produce lower relative damage.
# Zone X (minimal / unshaded) = nominal ~0.04% AEP.  MDR ≈ 5%: very shallow,
#            infrequent inundation.  Chosen conservatively above zero because
#            even "minimal" zones receive occasional localized flooding.
#
# EAL rate = AEP × MDR  (single-event approximation; valid when AEP << 1)

FLOOD_EAL = {
    "high":     0.010 * 0.28,   # AE zone:       1.0% AEP × 28% MDR = 0.280%
    "moderate": 0.002 * 0.15,   # Shaded X:      0.2% AEP × 15% MDR = 0.030%
    "minimal":  0.0004 * 0.05,  # Unshaded X:   0.04% AEP ×  5% MDR = 0.002%
}


def calc_flood_eal(row) -> float:
    """Return flood EAL rate (fraction/year) for one parcel."""
    return FLOOD_EAL.get(row["flood_risk"], FLOOD_EAL["minimal"])


# ---------------------------------------------------------------------------
# 2. TORNADO EAL RATE
# ---------------------------------------------------------------------------
# The tornado EAL rate (fraction of building value lost to tornadoes per year)
# comes straight from the FEMA National Risk Index, attached upstream by
# enrich/tornado.py as ``tornado_nri_eal_rate`` (tract → county → national
# fallback via data/tornado.py). NRI defines it as
#   AnnualizedFrequency × HistoricLossRatio
# so both the local frequency AND the local building-loss experience shape it —
# "tornado alley" reads high, low-risk regions read near-zero (~30× spread in the
# raw data). This replaces the old NOAA SPC touchdown-count model, which applied a
# single TN/Mid-South EF-magnitude distribution (Ashley 2007) nationally and so
# could not tell a Plains home from a coastal one. Same units as the flood /
# seismic / fire rates below, so it folds directly into the summed EAL.


def calc_tornado_eal(row) -> float:
    """Return the raw tornado EAL rate (fraction/year) for one parcel, pre-BRM.

    The NRI tornado rate from ``tornado_nri_eal_rate`` (0.0 if the enrichment
    column is absent or non-numeric), mirroring ``calc_fire_eal``.
    """
    rate = row.get("tornado_nri_eal_rate")
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(rate) or rate < 0:
        return 0.0
    return rate


# ---------------------------------------------------------------------------
# 3. SEISMIC EAL RATE
# ---------------------------------------------------------------------------
# Two-point trapezoidal integration over the hazard curve avoids double-
# counting between the 10%/50yr and 2%/50yr exceedance levels.
#
# Annual rates from Poisson: λ = -ln(1 - p) / t
#   10%/50yr → λ_10 = -ln(0.90)/50 ≈ 0.002107 /yr  (≈ 475-yr return period)
#    2%/50yr → λ_2  = -ln(0.98)/50 ≈ 0.000404 /yr  (≈ 2475-yr return period)
#
# EAL contribution from two segments of the hazard curve:
#   Rare events   (> 2%/50yr shaking level):   λ_2  × DR(pga_2pct)
#   Moderate events (between 10% and 2%/50yr): (λ_10 - λ_2) × DR(pga_10pct)
# This separates the rate-of-occurrence into non-overlapping bins.
#
# Simplified fragility (damage ratio vs. PGA, g) for wood-frame residential:
#   Based on HAZUS-MH Annex A fragility curves, rounded for clarity.
#   <0.10g → 0.5%  (imperceptible to minor: no structural damage)
#   0.10–0.20g → 3%  (light: chimney/plaster damage, minor cracking)
#   0.20–0.40g → 10% (moderate: significant cracking, some structural)
#   0.40–0.60g → 25% (heavy: major structural damage, partial collapse)
#   >0.60g → 50%     (near-complete destruction for typical wood-frame)
#
# Shelby County context: all parcels in SDC D (highest seismic category);
#   pga_2pct_50yr ≈ 0.45–0.54g → all fall in "heavy" damage band.
#   pga_10pct_50yr ≈ 0.18–0.21g → "light to moderate" band.

LAMBDA_10 = -np.log(0.90) / 50  # ≈ 0.002107 /yr
LAMBDA_2  = -np.log(0.98) / 50  # ≈ 0.000404 /yr


def pga_to_damage_ratio(pga_g: float) -> float:
    """Map Peak Ground Acceleration (g) to mean structural damage ratio."""
    if pga_g < 0.10:
        return 0.005   # imperceptible shaking
    elif pga_g < 0.20:
        return 0.03    # light damage
    elif pga_g < 0.40:
        return 0.10    # moderate damage
    elif pga_g < 0.60:
        return 0.25    # heavy damage
    else:
        return 0.50    # severe/near-complete damage


def calc_seismic_eal(row) -> float:
    """Return seismic EAL rate (fraction/year) for one parcel."""
    pga_rare     = row["pga_2pct_50yr"]   # g, 2%/50yr (design-level)
    pga_moderate = row["pga_10pct_50yr"]  # g, 10%/50yr (service-level)

    dr_rare     = pga_to_damage_ratio(pga_rare)
    dr_moderate = pga_to_damage_ratio(pga_moderate)

    # Rare segment:    events that exceed the 2%/50yr PGA level
    eal_rare     = LAMBDA_2 * dr_rare
    # Moderate segment: events between 10%/50yr and 2%/50yr levels
    eal_moderate = (LAMBDA_10 - LAMBDA_2) * dr_moderate

    return eal_rare + eal_moderate


# ---------------------------------------------------------------------------
# 4. FIRE EAL RATE  (structural fire baseline + location wildfire)
# ---------------------------------------------------------------------------
# The fire peril combines two independent contributions, summed as a rate:
#
#   • Structural / electrical fire — a national-average residential fire EAL.
#     NFPA reports ~$9B annual home-fire property loss across ~US residential
#     value → ≈0.020%/yr. Every home carries this regardless of location; it is
#     the same baseline the CLI simulator (simulate/house.py) uses.
#
#   • Wildfire — the FEMA National Risk Index wildfire EAL rate for the parcel's
#     census tract (county/national fallback), attached upstream by
#     the input parcels as ``wildfire_eal_rate``. This is what makes "fire"
#     location-aware: near-zero in Memphis, materially higher in the fire-prone
#     West. Absent (e.g. fire enrichment not run) → treated as 0.0.
#
# Both contributions scale with the same fire Building Resilience Modifier
# (combustibility): wiring-era × wall-material × condition (see §5f).

STRUCTURAL_FIRE_EAL_BASE = 0.0002   # 0.020%/yr national-average residential fire EAL (NFPA)


def calc_fire_eal(row) -> float:
    """Return the raw fire EAL rate (fraction/year) for one parcel, pre-BRM.

    Structural-fire baseline plus the parcel's NRI wildfire rate (0.0 if the
    wildfire enrichment column is absent or non-numeric).
    """
    wildfire = row.get("wildfire_eal_rate")
    try:
        wildfire = float(wildfire)
    except (TypeError, ValueError):
        wildfire = 0.0
    if not np.isfinite(wildfire) or wildfire < 0:
        wildfire = 0.0
    return STRUCTURAL_FIRE_EAL_BASE + wildfire


# ---------------------------------------------------------------------------
# 5. SCORE MAPPING — log-linear interpolation
# ---------------------------------------------------------------------------
# The score-to-EAL-rate breakpoints below are anchored to physical meaning:
#   100: EAL < 0.001% → virtually no hazard (e.g., interior low-risk US zones)
#    95: EAL ~ 0.003% → near-perfect build (fine discrimination near the top)
#    80: EAL ~ 0.020% → low risk (national average for combined hazards ≈ here)
#    60: EAL ~ 0.100% → moderate risk (coastal/flood-prone non-SFHA areas)
#    40: EAL ~ 0.300% → high risk (Zone AE flood or high seismic + moderate flood)
#    20: EAL ~ 1.000% → very high risk (Zone AE + high seismic + tornado)
#     0: EAL > 2.000% → extreme risk (above this, 2% property loss every year)
#
# Log-linear interpolation is appropriate because hazard scales span orders
# of magnitude; a linear scale would compress the meaningful low-risk range.

SCORE_BREAKPOINTS = [
    # (score, eal_rate_fraction)  — strictly descending in score, ascending in EAL.
    # Single source of truth for the resilience score curve, shared with the live
    # simulator (simulate/house.py imports this). Recalibrated from the old 0.005%
    # top anchor: a perfect build should be genuinely hard to reach, so the top is
    # 5× harder (0.001%) with a 95 anchor added for finer discrimination near the top.
    (100, 0.00001),   # 0.001%/yr — virtually no hazard
    (95,  0.00003),   # 0.003%/yr — near-perfect build
    (80,  0.0002),    # 0.020%/yr — low risk (≈ national average)
    (60,  0.001),     # 0.100%/yr — moderate risk
    (40,  0.003),     # 0.300%/yr — high risk
    (20,  0.010),     # 1.000%/yr — very high risk
    (0,   0.020),     # 2.000%/yr — extreme risk
]


def eal_rate_to_score(eal_rate: float) -> float:
    """
    Map a fractional EAL rate to a 0-100 score via log-linear interpolation.
    EAL rates ≤ lower bound → 100; ≥ upper bound → 0.
    """
    if eal_rate <= SCORE_BREAKPOINTS[0][1]:
        return 100.0
    if eal_rate >= SCORE_BREAKPOINTS[-1][1]:
        return 0.0

    # Find the two bracketing breakpoints
    for i in range(len(SCORE_BREAKPOINTS) - 1):
        s_hi, e_lo = SCORE_BREAKPOINTS[i]      # higher score, lower EAL
        s_lo, e_hi = SCORE_BREAKPOINTS[i + 1]  # lower score, higher EAL
        if e_lo <= eal_rate <= e_hi:
            # Log-linear interpolation
            log_pos = (np.log(eal_rate) - np.log(e_lo)) / (np.log(e_hi) - np.log(e_lo))
            return s_hi + (s_lo - s_hi) * log_pos

    return 0.0  # fallback (should not reach here)


# ---------------------------------------------------------------------------
# DUAL-GRADING RATIONALE
# ---------------------------------------------------------------------------
# This script produces two complementary letter grades for each parcel:
#
#   national_grade — absolute thresholds on the 0-100 EAL-rate score.
#       Tells you how Memphis compares to other US cities. A parcel scoring
#       Grade B nationally is genuinely low-risk by national standards. The
#       catch: Shelby County sits in Seismic Design Category D (New Madrid
#       fault zone) and has meaningful tornado exposure, so its fixed hazard
#       baseline compresses scores into roughly 36-80 — making nearly every
#       parcel Grade B nationally. That's accurate (Memphis IS higher risk
#       than Phoenix), but it gives homebuyers no signal about which parcels
#       are relatively better or worse within Memphis.
#
#   local_grade — percentile rank within the Shelby County dataset.
#       Tells you how a parcel compares to other parcels in the same market.
#       A = top 10%, B = next 25%, C = middle 30%, D = next 25%, F = bottom 10%.
#       This surfaces within-market differentiation driven by flood zone,
#       building condition, construction era, and foundation type. Useful for
#       side-by-side comparisons: "this house vs. that house in Memphis."
#
# Both grades have value for different audiences:
#   • City planners / policy makers → national_grade (cross-city benchmarking)
#   • Homebuyers / lenders / insurers → local_grade (intra-market comparison)
#   • Nutrition label UI → show both with clear labels explaining the context
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 6. BUILDING RESILIENCE MODIFIER (BRM)
# ---------------------------------------------------------------------------
# The BRM adjusts each hazard's raw EAL rate to reflect construction quality.
# BRM is a multiplier:  < 1.0 = more resilient, 1.0 = baseline, > 1.0 = vulnerable.
# adjusted_eal = raw_eal × BRM. There is a construction-type-specific lower FLOOR
# but NO upper ceiling, so vulnerability compounds above the baseline (a pre-1940
# unsound frame home exceeds 2.5×) instead of being clipped. See section 5e.
#
# Parcels without CAMA data (~28%) receive BRM = 1.0 (neutral baseline).
#
# Component factors are multiplied together, then clamped.
# Sources are cited per factor below.

# --- 5a. Code Era Factor (from YRBLT) ---
# Rationale: Building codes improve structural performance over time, so
# vulnerability declines roughly monotonically with year built. We model it as a
# CONTINUOUS curve anchored at code-milestone years and linearly interpolated
# between them (np.interp), rather than the old coarse bins — a 1969 and a 1970
# build no longer differ by a full 0.2x cliff. np.interp clamps beyond the
# endpoints, so the curve plateaus outside the anchored range.
#
# Anchor years and factors. This module is the single source of truth — the live
# single-address simulator (simulate/house.py) imports code_era_factor /
# fire_age_factor from here, so both paths score the same house identically:
#   1940 -> 1.60  Pre-WWII: balloon framing, unreinforced masonry, no engineered
#                 connections or seismic/wind provisions (clamps for older stock).
#   1970 -> 1.30  Pre-modern codes: predate ANSI A58.1-1972 wind loads and the
#                 1971 San Fernando seismic reforms (SEAOC Blue Book).
#   1990 -> 1.10  Early modern (ANSI/ASCE 7 wind), pre-Northridge (1994) detailing.
#   2003 -> 1.00  Baseline: post-Hurricane Hugo (1989) / Northridge revisions,
#                 around IBC maturity (IBC first published 2000; ASCE 7-02 maps).
#                 TN statewide adoption phased in through the 2000s, so 2003 is a
#                 provisions-maturity anchor, not a hard statewide-adoption date.
#   2010 -> 0.85  Fully modern IBC / ASCE 7-05/7-10 provisions (clamps for newer
#                 stock); ~15% lower expected losses vs. 1990s stock (IBHS est.).

# Continuous year-built vulnerability curves (see 5a rationale). np.interp clamps
# outside the endpoints: pre-1940 stays 1.60, post-2010 stays 0.85 — no bin cliffs.
CODE_ERA_ANCHOR_YEARS   = (1940, 1970, 1990, 2003, 2010)
CODE_ERA_ANCHOR_FACTORS = (1.60, 1.30, 1.10, 1.00, 0.85)


def code_era_factor(yrblt) -> float:
    """Return code-era vulnerability multiplier, continuous in year built.

    Linearly interpolated between the CODE_ERA anchors (1940->1.60 ... 2010->0.85)
    and clamped beyond them. This is the single implementation; simulate/house.py
    imports it rather than defining its own."""
    if isna(yrblt):
        return 1.0  # neutral if unknown
    return float(np.interp(int(yrblt), CODE_ERA_ANCHOR_YEARS, CODE_ERA_ANCHOR_FACTORS))


# --- 5b. Construction Type Factor (from EXTWALL) ---
# Rationale: Exterior wall material determines structural response to wind,
# wind-borne debris, and seismic lateral loading.
# Frame (1): Light wood frame — most vulnerable to tornado and seismic lateral
#   loads; HAZUS-MH W1 occupancy class has highest damage ratios (FEMA 2012).
# Aluminum/vinyl (4): Similar framing as wood frame; siding itself provides no
#   structural benefit; slightly less than wood-frame due to lighter cladding
#   reducing debris potential (IBHS roof-to-wall connection research 2018).
# Brick veneer (7): Structural frame with brick cladding; veneer reduces
#   wind-borne debris but frame carries loads — modest improvement.
# Brick & frame (9): Combined system; better than veneer alone due to partially
#   composite lateral resistance (ASCE 7-16 masonry provisions).
# Block/masonry (2): Reinforced CMU construction; significantly better wind and
#   seismic lateral resistance than wood frame (HAZUS-MH RM1/URM classes).
# Stone (8): Solid masonry; highest lateral resistance but heavier — performs
#   best in wind, slightly elevated seismic mass concern offset by rigidity.
# ICF (not a CAMA code; used by simulate_house.py):
#   Tornado/seismic factor 0.25 — PCA racking test data: 5-10× wood frame
#   resistance; FEMA MAT Joplin/Moore reports; U.S. Resiliency Council data
#   showing 170-270% higher losses for wood vs ICF in seismic events.
# SIP (not a CAMA code; used by simulate_house.py):
#   Tornado/seismic factor 0.35 — engineered wood composite; superior racking
#   resistance vs. wood frame; below ICF but well above traditional frame.
# Unknown codes (3, 5, 10, 11, etc.): default to 1.0 (neutral baseline).

EXTWALL_FACTOR = {
    1:  1.20,  # Frame: most vulnerable to wind/seismic (HAZUS-MH W1 class)
    4:  1.15,  # Aluminum/vinyl: frame structure, minor cladding benefit
    9:  1.00,  # Brick & frame: composite system, baseline
    7:  0.95,  # Brick veneer: improved cladding, structural frame still governs
    2:  0.90,  # Block/masonry: reinforced CMU, strong lateral resistance
    8:  0.85,  # Stone: solid masonry, highest lateral resistance
    # ICF and SIP are not CAMA codes but are documented here for reference;
    # see simulate_house.py CONSTRUCTION_FACTOR for their applied values.
    # "icf": 0.25  # Tornado/seismic (PCA racking; FEMA MAT Joplin/Moore)
    # "sip": 0.35  # Tornado/seismic (engineered composite; above frame)
}

# ICF-specific flood construction factor (used by simulate_house.py):
# NFIP Class 5 flood-resistant material — monolithic concrete structure survives
# inundation with 80-95% structural loss reduction; finishes remain vulnerable.
# Source: NFIP Class 5 classification; FEMA P-259 depth-damage curves for
# concrete construction; "ICF flood: structural 80-95% reduction; finishes
# still vulnerable."
ICF_FLOOD_CONSTRUCTION_FACTOR = 0.45


def construction_type_factor(extwall) -> float:
    """Return construction-type vulnerability multiplier based on EXTWALL code."""
    if isna(extwall):
        return 1.0  # neutral if unknown
    return EXTWALL_FACTOR.get(int(extwall), 1.0)  # default 1.0 for unlisted codes


# --- 5c. Foundation Factor (flood only, from BSMT) ---
# Rationale: Foundation/basement type dominates flood damage variability.
# Basements flood readily and cause massive damage; slab-on-grade structures
# suffer far less flood intrusion.
# Source: FEMA P-259 "Engineering Principles and Practices" (2012) depth-damage
#   curves for basement vs. slab; FEMA NFIP actuarial studies show 2-3× higher
#   losses for basement structures in AE zones vs. elevated/slab structures.
# Full basement (4): Entire below-grade space; any flood inundation causes
#   catastrophic loss to mechanical, electrical, contents → factor 1.4.
# Partial basement (3): 25-75% finished below grade; intermediate loss → 1.2.
# Crawl space (2): 0-24%; minimal habitable below-grade area → 1.0 baseline.
# Slab/none (1): Ground-floor at or above grade; first-floor damage only → 0.7.
#   (FEMA P-259 shows ~40% reduction in expected loss vs. crawl space.)
# This factor applies ONLY to flood EAL, not tornado or seismic.

BSMT_FLOOD_FACTOR = {
    4: 1.4,   # Full basement ≥75%: catastrophic flood loss (FEMA P-259)
    3: 1.2,   # Partial 25-75%: substantial below-grade exposure
    2: 1.0,   # Crawl space 0-24%: baseline (limited below-grade)
    1: 0.7,   # Slab/none: elevated first floor, minimal flood intrusion
}


def foundation_factor(bsmt) -> float:
    """Return foundation flood-vulnerability multiplier based on BSMT code."""
    if isna(bsmt):
        return 1.0  # neutral if unknown
    return BSMT_FLOOD_FACTOR.get(int(bsmt), 1.0)


# --- 5d. Condition Factor (from COND) ---
# Rationale: Structural condition directly scales damage under any hazard.
# A building in poor condition has weakened connections, degraded materials, and
# reduced ductility — all of which amplify damage in a loss event.
# Source: HAZUS-MH §3.5 deterioration adjustment factors; ASCE 41-17 building
#   performance levels map to condition ratings as follows.
# COND 0 (Unsound): imminent collapse risk; ASCE 41 IO level already exceeded.
# COND 1 (Poor): significant deterioration; damage functions shift ~30% higher.
# COND 2 (Fair): some deficiencies; modest upward shift.
# COND 3 (Average): design-intent performance; baseline.
# COND 4 (Good): well-maintained; minor reduction in expected damage.
# COND 5 (Excellent): superior maintenance/upgrades; best expected performance.

COND_FACTOR = {
    0: 1.5,   # Unsound: near-collapse baseline (ASCE 41 CP+ exceeded)
    1: 1.3,   # Poor: major deterioration, high damage amplification
    2: 1.1,   # Fair: minor deficiencies, modest amplification
    3: 1.0,   # Average: baseline (design-intent performance)
    4: 0.9,   # Good: well-maintained, minor loss reduction
    5: 0.8,   # Excellent: superior condition, maximum loss reduction
}


def condition_factor(cond) -> float:
    """Return condition vulnerability multiplier based on COND code."""
    if isna(cond):
        return 1.0  # neutral if unknown
    return COND_FACTOR.get(int(cond), 1.0)


# --- 5e. BRM assembly ---
# Flood BRM   = code_era × construction_type × foundation × condition
# Wind/Seismic BRM = code_era × construction_type × condition
# (Foundation factor is flood-specific; basements do not meaningfully increase
#  tornado or seismic vulnerability in the same way.)
# BRMs have a construction-type-specific lower FLOOR but NO upper ceiling, so
# vulnerability compounds: an old, poor-condition, wood-frame house can exceed the
# code-current baseline (e.g. a pre-1940 unsound frame home > 2x) without being
# clipped. This matches simulate/house.py (floor only, no ceiling) and the
# published methodology. Capping at 1.5 previously understated the worst stock.
# Using a universal 0.5 floor was too conservative for high-performance systems
# like ICF; per-type floors allow literature-supported maximum reductions.

# Construction-type-specific BRM floors (lower bound on adjusted EAL multiplier).
# Wood/vinyl/composite-frame types: 0.50 (best traditional performance ceiling).
# Brick veneer / block / stone:    0.40 (solid masonry outperforms frame meaningfully).
# ICF: 0.15 — 85% max EAL reduction supported by PCA racking test data and
#   FEMA MAT reports (Joplin 2011, Moore 2013); U.S. Resiliency Council seismic data.
# SIP: 0.25 — engineered composite; significant improvement over frame but less
#   than monolithic concrete ICF shell.
EXTWALL_BRM_FLOOR = {
    1: 0.50,  # Frame: worst-case performance ceiling
    4: 0.50,  # Vinyl/aluminum
    9: 0.50,  # Brick & frame
    7: 0.40,  # Brick veneer
    2: 0.40,  # Block/masonry
    8: 0.40,  # Stone
    # ICF/SIP floors applied in simulate_house.py (not CAMA codes):
    # "icf": 0.15, "sip": 0.25
}
DEFAULT_BRM_FLOOR = 0.50  # fallback for unknown/unlisted EXTWALL codes


# --- 5f. Fire BRM (combustibility) ---
# The fire peril scales with how readily the structure ignites and burns, not
# with wind/seismic lateral resistance — so it uses its own modifier built from
# wall-material combustibility, electrical-wiring era, and condition. These
# mirror the CLI simulator (simulate/house.py) so the offline pipeline and the
# live API share one fire model.
#
# Wall-material combustibility by EXTWALL code (frame burns; masonry/concrete
# resist): values track simulate/house.py's FIRE_CONSTRUCTION_FACTOR.
FIRE_EXTWALL_FACTOR = {
    1:  1.10,  # Frame: combustible structure
    4:  1.10,  # Aluminum/vinyl: frame structure, cladding adds no fire benefit
    9:  0.95,  # Brick & frame: partial masonry protection
    7:  0.90,  # Brick veneer: masonry skin over frame
    2:  0.80,  # Block/masonry: non-combustible shell
    8:  0.80,  # Stone: non-combustible shell
}
FIRE_BRM_FLOOR = 0.50  # material/age/condition alone can at most halve fire EAL


# Continuous fire-age (wiring-era) curve, anchored to electrical-code milestones
# and interpolated like the code-era curve (clamped beyond the endpoints):
#   1950 -> 1.50  Knob-and-tube era: highest residential electrical-fire risk.
#   1975 -> 1.20  Cloth/early-plastic insulation, aluminum branch-wiring era.
#   2002 -> 1.00  Modern NM-B cable, pre-AFCI baseline.
#   2010 -> 0.85  NEC 2002+ AFCI / tamper-resistant receptacles fully in force.
# Single source of truth: simulate/house.py imports fire_age_factor from here.
FIRE_AGE_ANCHOR_YEARS   = (1950, 1975, 2002, 2010)
FIRE_AGE_ANCHOR_FACTORS = (1.50, 1.20, 1.00, 0.85)


def fire_age_factor(yrblt) -> float:
    """Structural-fire vulnerability by electrical/wiring era, continuous in
    year built.

    Pre-1950 knob-and-tube and mid-century aluminum branch wiring raise fire
    risk; the 2002 NEC (AFCI / tamper-resistant) era lowers it. Linearly
    interpolated between the FIRE_AGE anchors and clamped beyond them.
    """
    if isna(yrblt):
        return 1.0
    return float(np.interp(int(yrblt), FIRE_AGE_ANCHOR_YEARS, FIRE_AGE_ANCHOR_FACTORS))


def fire_construction_factor(extwall) -> float:
    """Return wall-material fire-combustibility multiplier based on EXTWALL code."""
    if isna(extwall):
        return 1.0
    return FIRE_EXTWALL_FACTOR.get(int(extwall), 1.0)


def calc_brm_row(row):
    """
    Compute BRM components and both flood and wind/seismic BRM for one row.
    Returns a dict of factor columns plus the two BRM values and source flag.
    """
    has_cama = not isna(row.get("YRBLT"))  # YRBLT as sentinel for CAMA presence

    if not has_cama:
        return {
            "code_era_factor":    1.0,
            "construction_factor": 1.0,
            "foundation_factor":  1.0,
            "condition_factor":   1.0,
            "flood_brm":         1.0,
            "wind_seismic_brm":  1.0,
            "fire_brm":          1.0,
            "brm_source":        "default",
        }

    cef = code_era_factor(row.get("YRBLT"))
    ctf = construction_type_factor(row.get("EXTWALL"))
    ff  = foundation_factor(row.get("BSMT"))
    cf  = condition_factor(row.get("COND"))

    extwall_code = int(row.get("EXTWALL")) if not isna(row.get("EXTWALL")) else None
    brm_floor = EXTWALL_BRM_FLOOR.get(extwall_code, DEFAULT_BRM_FLOOR)

    # Floor only, no upper ceiling: vulnerability compounds above the baseline.
    flood_brm       = max(cef * ctf * ff * cf,  brm_floor)
    wind_seismic_brm = max(cef * ctf * cf,       brm_floor)
    # Fire uses combustibility (wiring era × wall material × condition), not the
    # wind/seismic factors, floored at FIRE_BRM_FLOOR (no ceiling).
    fire_brm        = max(fire_age_factor(row.get("YRBLT"))
                          * fire_construction_factor(row.get("EXTWALL")) * cf,
                          FIRE_BRM_FLOOR)

    return {
        "code_era_factor":    cef,
        "construction_factor": ctf,
        "foundation_factor":  ff,
        "condition_factor":   cf,
        "flood_brm":         flood_brm,
        "wind_seismic_brm":  wind_seismic_brm,
        "fire_brm":          fire_brm,
        "brm_source":        "cama",
    }


# ---------------------------------------------------------------------------
# 6b. VECTORIZED EQUIVALENTS (used by main() over the whole parcel table)
# ---------------------------------------------------------------------------
# The scalar calc_* / *_factor functions above are the single-row reference
# (used by the CLI simulator and the unit tests). main() scores the entire
# parcel set, so it calls these column-wise equivalents instead of
# df.apply(..., axis=1) — identical math, without a Python call per row.
# tests/test_resilience_vectorized.py asserts the two paths agree on random
# parcels, so any divergence fails the suite rather than silently shifting scores.

























# ---------------------------------------------------------------------------
# 7. MAIN — apply to all parcels, save output
# ---------------------------------------------------------------------------







# ── Decomposing resilience into its site and building legs ───────────────────
# Resilience is the one dimension that is genuinely BOTH axes at once: expected
# annual loss is the site's hazard rate multiplied by how the building responds to
# it. Reported as a single number it cannot be assigned to either headline grade
# honestly — measured at a fixed Los Angeles tract, varying only the preset, it
# swung from the 1st national percentile to the 99th, so putting it in the Site &
# environment aggregate made that grade move 98 points on facts about the house.
# It was excluded there as an interim (#263); this is the real fix.
#
# The seam is already in simulate(): it records `*_raw` — the peril hazard rates
# before any construction adjustment — alongside the `*_adj` rates after. So:
#
#   SITE leg      eal_rate_to_score(sum of the raw rates). What this location does
#                 to a neutral building. Constant across buildings at a fixed
#                 parcel, which is the property the site grade needs and the
#                 combined score does not have.
#
#   BUILDING leg  the same construction multiplier applied to a REFERENCE site,
#                 so the answer is "how would this house score at a typical US
#                 location" rather than a number entangled with this one. Reusing
#                 eal_rate_to_score keeps it on the familiar 0-100 scale and
#                 inherits its calibration rather than inventing a second one.
#
# The row the user sees is unchanged: it still reports the actual expected loss for
# this building at this site, which is the question an owner is asking. The legs
# exist so the two aggregates can each take the half that belongs to them.

# Household-weighted median site hazard over 3,000 sampled census tracts (raw EAL
# rate, no construction adjustment). Scoring the building's multiplier against this
# answers "at a typical US site", so two houses are comparable on build quality
# even when one of them sits on a floodplain.
REFERENCE_SITE_EAL_RATE = 4.676422e-04


def resilience_legs(r: dict) -> dict:
    """Split a simulate() result into its site-hazard and building-response legs.

    Returns ``{"site": float|None, "building": float|None, "multiplier": float|None}``
    — both legs on the same 0-100 scale as the combined score, higher = better.

    ``multiplier`` is the building's effect on expected loss (adjusted ÷ raw): below
    1 the construction reduces the site's expected loss, above 1 it worsens it.
    Returned so callers can show the mechanism rather than only its scored result.
    """
    try:
        raw = sum(float(r[f"{p}_raw"]) for p in ("flood", "tornado", "seismic", "fire"))
        adj = float(r["total_eal"])
    except (KeyError, TypeError, ValueError):
        return {"site": None, "building": None, "multiplier": None}
    if not (raw > 0.0):
        # No modelled hazard at all: the site leg is the top of the scale, and the
        # building's multiplier is undefined rather than 1.0 — dividing by zero
        # hazard would report every building as neutral, which is not a measurement.
        return {"site": round(eal_rate_to_score(0.0), 1),
                "building": None, "multiplier": None}
    mult = adj / raw
    return {
        "site": round(eal_rate_to_score(raw), 1),
        "building": round(eal_rate_to_score(REFERENCE_SITE_EAL_RATE * mult), 1),
        "multiplier": round(mult, 4),
    }
