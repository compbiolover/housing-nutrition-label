"""
score_resilience.py — Housing Nutrition Label: Disaster Resilience Scoring
Methodology: Expected Annual Loss Rate (EAL Rate = EAL / property value)
EAL Rate is dimensionless (fraction of property value lost per year, on average).

Three independent hazards are modeled and summed:
  1. Flood        — FEMA flood zone damage curves
  2. Tornado      — path-area strike probability × EF-scaled damage ratios
  3. Seismic      — two-point hazard curve integration (2%/50yr + 10%/50yr)

Each hazard's raw EAL rate is multiplied by a Building Resilience Modifier (BRM)
derived from CAMA construction attributes (year built, wall type, foundation,
condition). BRM = 1.0 is the baseline; values < 1.0 indicate more resilient
construction; values > 1.0 indicate greater vulnerability.

Composite adjusted EAL rate is mapped to a 0-100 score via log-linear
interpolation, then translated to a letter grade. Per-hazard sub-scores use
the same mapping.

Sources / rationale are cited at each threshold.
"""

import numpy as np
import pandas as pd

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
# Approach: for each EF category, compute the expected annual loss rate as
#   EAL_EF = frequency × EF_fraction × (path_area / circle_area) × damage_ratio
# then sum across EF categories.
#
# Frequency source: avg_tornadoes_per_yr_25mi from NOAA SPC tornado database
#   (1950-2023), counts within 25-mile radius of each parcel.
#
# EF distribution (Tennessee / Mid-South region, SPC 1950-2023):
#   Approximated from statewide TN tornado database; EF0 heavy, EF5 absent.
#   EF0: 45%, EF1: 33%, EF2: 14%, EF3: 6%, EF4: 2%
#   Note: max_ef_25mi in dataset is 3–4, consistent with this distribution.
#
# Mean path dimensions by EF (NOAA SPC climatology, Ashley 2007):
#   Width and length are averages across all tornadoes in that EF category.
#   Path area (sq mi) = (width_yards / 1760) × length_miles
#
# Damage ratios by EF (HAZUS-MH methodology, FEMA 2012):
#   EF0=2%, EF1=10%, EF2=30%, EF3=60%, EF4=90%
#   These represent mean structural damage to wood-frame residential buildings.
#
# Circle area = π × 25² ≈ 1963.5 sq mi (the denominator for strike probability)

EF_DISTRIBUTION = {  # fraction of tornadoes in each EF category (sums to 1.0)
    0: 0.45,  # EF0: most common, weakest
    1: 0.33,  # EF1
    2: 0.14,  # EF2
    3: 0.06,  # EF3: ~6% of TN tornadoes (SPC climatology)
    4: 0.02,  # EF4: ~2%; EF5 effectively absent in this dataset
}

# (width_yards, length_miles) mean path dimensions → path area in sq mi
EF_PATH_AREA_SQ_MI = {
    0: (50, 0.5),    # EF0: narrow, short → 0.014 sq mi
    1: (100, 1.5),   # EF1              → 0.085 sq mi
    2: (200, 3.0),   # EF2              → 0.341 sq mi
    3: (400, 7.0),   # EF3              → 1.591 sq mi
    4: (800, 15.0),  # EF4              → 6.818 sq mi
}

EF_DAMAGE_RATIO = {  # HAZUS-MH mean damage ratio for wood-frame residential
    0: 0.02,   # EF0: minor damage (broken windows, minor roof loss)
    1: 0.10,   # EF1: moderate damage (roof peeled, some structural)
    2: 0.30,   # EF2: major damage (roof removed, walls damaged)
    3: 0.60,   # EF3: severe damage (complete destruction common)
    4: 0.90,   # EF4: near-total destruction
}

CIRCLE_AREA_SQ_MI = np.pi * 25**2  # ≈ 1963.5 sq mi, constant for all parcels


def calc_tornado_eal(row) -> float:
    """Return tornado EAL rate (fraction/year) for one parcel."""
    freq = row["avg_tornadoes_per_yr_25mi"]  # tornadoes/year in 25-mi radius
    eal = 0.0
    for ef, ef_frac in EF_DISTRIBUTION.items():
        width_yd, length_mi = EF_PATH_AREA_SQ_MI[ef]
        path_area = (width_yd / 1760.0) * length_mi  # sq mi
        strike_prob = freq * ef_frac * (path_area / CIRCLE_AREA_SQ_MI)
        eal += strike_prob * EF_DAMAGE_RATIO[ef]
    return eal


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
# 4. SCORE MAPPING — log-linear interpolation
# ---------------------------------------------------------------------------
# The score-to-EAL-rate breakpoints below are anchored to physical meaning:
#   100: EAL < 0.005% → virtually no hazard (e.g., interior low-risk US zones)
#    80: EAL ~ 0.020% → low risk (national average for combined hazards ≈ here)
#    60: EAL ~ 0.100% → moderate risk (coastal/flood-prone non-SFHA areas)
#    40: EAL ~ 0.300% → high risk (Zone AE flood or high seismic + moderate flood)
#    20: EAL ~ 1.000% → very high risk (Zone AE + high seismic + tornado)
#     0: EAL > 2.000% → extreme risk (above this, 2% property loss every year)
#
# Log-linear interpolation is appropriate because hazard scales span orders
# of magnitude; a linear scale would compress the meaningful low-risk range.

SCORE_BREAKPOINTS = [
    # (score, eal_rate_fraction)  — must be strictly descending in score,
    #                               strictly ascending in eal_rate
    (100, 0.00005),   # 0.005%
    (80,  0.0002),    # 0.020%
    (60,  0.001),     # 0.100%
    (40,  0.003),     # 0.300%
    (20,  0.010),     # 1.000%
    (0,   0.020),     # 2.000%
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


def score_to_grade(score: float) -> str:
    """Convert 0-100 score to letter grade (A/B/C/D/F)."""
    if score >= 80:
        return "A"
    elif score >= 60:
        return "B"
    elif score >= 40:
        return "C"
    elif score >= 20:
        return "D"
    else:
        return "F"


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

def percentile_to_local_grade(pct: float) -> str:
    """
    Convert a 0-100 percentile rank to a local letter grade.
    Breakpoints distribute grades across five bands:
        A = top 10%     (≥90th percentile)
        B = next 25%    (≥65th percentile)
        C = middle 30%  (≥35th percentile)
        D = next 25%    (≥10th percentile)
        F = bottom 10%  (<10th percentile)
    """
    if pct >= 90:
        return "A"
    elif pct >= 65:
        return "B"
    elif pct >= 35:
        return "C"
    elif pct >= 10:
        return "D"
    else:
        return "F"


# ---------------------------------------------------------------------------
# 5. BUILDING RESILIENCE MODIFIER (BRM)
# ---------------------------------------------------------------------------
# The BRM adjusts each hazard's raw EAL rate to reflect construction quality.
# BRM is a multiplier:  0.5 = very resilient, 1.0 = baseline, 1.5 = vulnerable.
# adjusted_eal = raw_eal × BRM   (clamped to [0.5, 1.5])
#
# Parcels without CAMA data (~28%) receive BRM = 1.0 (neutral baseline).
#
# Component factors are multiplied together, then clamped.
# Sources are cited per factor below.

# --- 5a. Code Era Factor (from YRBLT) ---
# Rationale: Building codes improve structural performance over time.
# The International Building Code (IBC) was adopted by Tennessee in 2003
# (IBHS "Building Codes & Wind" report 2023; NCIUA state adoption tracker).
# Pre-1970 buildings predate ANSI A58.1-1972 wind load standards and the
# 1971 San Fernando earthquake-driven seismic code reforms (SEAOC Blue Book).
# 1970-1989: ANSI/ASCE 7 era; modern load calculations but pre-IRC prescriptive
#   wood-frame improvements. Moderate improvement over older stock.
# 1990-2002: Post-Hurricane Hugo (1989) / Northridge (1994) code revisions;
#   better detailing but pre-IBC uniformity.
# 2003+: IBC adoption brings uniform wind/seismic provisions statewide;
#   ASCE 7-02 load maps applied; ~15% reduction in expected losses vs. 1990s
#   stock (IBHS Premium 2023 estimate for TN residential).

def code_era_factor(yrblt) -> float:
    """Return code-era vulnerability multiplier based on year built."""
    if pd.isna(yrblt):
        return 1.0  # neutral if unknown
    yr = int(yrblt)
    if yr < 1970:
        return 1.3   # pre-modern codes: ANSI 58.1 / pre-seismic-reform era
    elif yr < 1990:
        return 1.1   # early modern codes: post-ANSI 7 wind, pre-Northridge
    elif yr < 2003:
        return 1.0   # baseline: post-Hugo reforms, pre-IBC adoption
    else:
        return 0.85  # post-IBC (TN adopted IBC 2003): best code provisions


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
    if pd.isna(extwall):
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
    if pd.isna(bsmt):
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
    if pd.isna(cond):
        return 1.0  # neutral if unknown
    return COND_FACTOR.get(int(cond), 1.0)


# --- 5e. BRM assembly ---
# Flood BRM   = code_era × construction_type × foundation × condition
# Wind/Seismic BRM = code_era × construction_type × condition
# (Foundation factor is flood-specific; basements do not meaningfully increase
#  tornado or seismic vulnerability in the same way.)
# BRMs are clamped to [floor, 1.5] where the floor is construction-type-specific.
# Using a universal 0.5 floor was too conservative for high-performance systems
# like ICF; per-type floors allow literature-supported maximum reductions.

BRM_MAX = 1.5

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


def calc_brm_row(row):
    """
    Compute BRM components and both flood and wind/seismic BRM for one row.
    Returns a dict of factor columns plus the two BRM values and source flag.
    """
    has_cama = not pd.isna(row.get("YRBLT"))  # YRBLT as sentinel for CAMA presence

    if not has_cama:
        return {
            "code_era_factor":    1.0,
            "construction_factor": 1.0,
            "foundation_factor":  1.0,
            "condition_factor":   1.0,
            "flood_brm":         1.0,
            "wind_seismic_brm":  1.0,
            "brm_source":        "default",
        }

    cef = code_era_factor(row.get("YRBLT"))
    ctf = construction_type_factor(row.get("EXTWALL"))
    ff  = foundation_factor(row.get("BSMT"))
    cf  = condition_factor(row.get("COND"))

    extwall_code = int(row.get("EXTWALL")) if not pd.isna(row.get("EXTWALL")) else None
    brm_floor = EXTWALL_BRM_FLOOR.get(extwall_code, DEFAULT_BRM_FLOOR)

    flood_brm       = np.clip(cef * ctf * ff * cf,  brm_floor, BRM_MAX)
    wind_seismic_brm = np.clip(cef * ctf * cf,       brm_floor, BRM_MAX)

    return {
        "code_era_factor":    cef,
        "construction_factor": ctf,
        "foundation_factor":  ff,
        "condition_factor":   cf,
        "flood_brm":         flood_brm,
        "wind_seismic_brm":  wind_seismic_brm,
        "brm_source":        "cama",
    }


# ---------------------------------------------------------------------------
# 6. MAIN — apply to all parcels, save output
# ---------------------------------------------------------------------------

def main():
    pipeline_path = "shelby_parcels_seismic.csv"   # latest enrichment output
    sample_path   = "shelby_parcels_sample.csv"     # source of CAMA fields
    output_path   = "shelby_parcels_scored.csv"

    # --- Load pipeline output ---
    df = pd.read_csv(pipeline_path, low_memory=False)
    print(f"Loaded {len(df):,} parcels from {pipeline_path}")

    # --- Join CAMA fields from sample file ---
    # The enrichment pipeline does not carry CAMA columns forward; join them
    # here on PARCELID using a left join so all pipeline parcels are retained.
    cama_cols = ["PARCELID", "YRBLT", "EXTWALL", "BSMT", "COND",
                 "GRADE", "SFLA", "RTOTAPR", "APRBLDG"]
    sample = pd.read_csv(sample_path, usecols=cama_cols, low_memory=False)
    sample = sample.drop_duplicates(subset="PARCELID")

    df = df.merge(sample, on="PARCELID", how="left")
    cama_present = df["YRBLT"].notna().sum()
    print(f"CAMA data joined: {cama_present:,} parcels have CAMA records "
          f"({cama_present/len(df)*100:.1f}%); "
          f"{len(df)-cama_present:,} will use BRM=1.0 default")

    # --- RTOTAPR: use for dollar-denominated EAL reporting ---
    # EAL Rate is dimensionless (fraction/year); multiply by appraised value
    # to obtain expected annual dollar loss. For parcels missing RTOTAPR, use
    # the sample median so that dollar estimates remain meaningful.
    # Source: Shelby County Assessor CAMA data; median from 1,000-parcel sample.
    rtotapr_median = df["RTOTAPR"].median()
    df["property_value"] = df["RTOTAPR"].fillna(rtotapr_median)
    print(f"Property value: median ${rtotapr_median:,.0f}; "
          f"{df['RTOTAPR'].isna().sum()} parcels using median fallback")

    # --- Compute raw per-hazard EAL rates (before BRM) ---
    df["flood_eal_rate_raw"]   = df.apply(calc_flood_eal,   axis=1)
    df["tornado_eal_rate_raw"] = df.apply(calc_tornado_eal, axis=1)
    df["seismic_eal_rate_raw"] = df.apply(calc_seismic_eal, axis=1)

    # --- Compute BRM for every parcel ---
    brm_df = df.apply(calc_brm_row, axis=1, result_type="expand")
    df = pd.concat([df, brm_df], axis=1)

    # --- Apply BRM: adjusted_eal = raw_eal × BRM ---
    df["flood_eal_rate"]   = df["flood_eal_rate_raw"]   * df["flood_brm"]
    df["tornado_eal_rate"] = df["tornado_eal_rate_raw"] * df["wind_seismic_brm"]
    df["seismic_eal_rate"] = df["seismic_eal_rate_raw"] * df["wind_seismic_brm"]

    # Independent-hazard assumption: total EAL = sum of individual EALs.
    df["total_eal_rate"] = (
        df["flood_eal_rate"] + df["tornado_eal_rate"] + df["seismic_eal_rate"]
    )

    # --- Dollar-denominated EAL (informational, not used in scoring) ---
    df["flood_eal_dollars"]   = df["flood_eal_rate"]   * df["property_value"]
    df["tornado_eal_dollars"] = df["tornado_eal_rate"] * df["property_value"]
    df["seismic_eal_dollars"] = df["seismic_eal_rate"] * df["property_value"]
    df["total_eal_dollars"]   = df["total_eal_rate"]   * df["property_value"]

    # --- Map adjusted EAL rates to 0-100 scores ---
    df["flood_score"]      = df["flood_eal_rate"].apply(eal_rate_to_score)
    df["tornado_score"]    = df["tornado_eal_rate"].apply(eal_rate_to_score)
    df["seismic_score"]    = df["seismic_eal_rate"].apply(eal_rate_to_score)
    df["resilience_score"] = df["total_eal_rate"].apply(eal_rate_to_score)

    # --- National absolute grade (cross-city comparison) ---
    df["national_grade"] = df["resilience_score"].apply(score_to_grade)

    # --- Percentile rank within Shelby County dataset (0-100) ---
    df["percentile_rank"] = df["resilience_score"].rank(pct=True) * 100

    # --- Local percentile-based grade (within-market comparison) ---
    df["local_grade"] = df["percentile_rank"].apply(percentile_to_local_grade)

    # --- Per-hazard local grades (same percentile bands applied per sub-score) ---
    df["flood_local_grade"]   = (df["flood_score"].rank(pct=True) * 100).apply(percentile_to_local_grade)
    df["tornado_local_grade"] = (df["tornado_score"].rank(pct=True) * 100).apply(percentile_to_local_grade)
    df["seismic_local_grade"] = (df["seismic_score"].rank(pct=True) * 100).apply(percentile_to_local_grade)

    # --- Save ---
    df.to_csv(output_path, index=False)
    print(f"Saved scored parcels to {output_path}\n")

    # -----------------------------------------------------------------------
    # SUMMARY REPORT
    # -----------------------------------------------------------------------
    pd.set_option("display.float_format", "{:.5f}".format)
    pd.set_option("display.max_columns", 25)
    pd.set_option("display.width", 160)

    print("=" * 70)
    print("BRM SUMMARY")
    print("=" * 70)
    brm_cols = ["code_era_factor", "construction_factor",
                "foundation_factor", "condition_factor",
                "flood_brm", "wind_seismic_brm"]
    print(df[brm_cols].describe().map(lambda x: f"{x:.4f}").to_string())
    print(f"\nBRM source breakdown:")
    print(df["brm_source"].value_counts().to_string())

    print("\n" + "=" * 70)
    print("EAL RATE SUMMARY — ADJUSTED (fraction/year × 100 = %/yr)")
    print("=" * 70)
    eal_cols = ["flood_eal_rate", "tornado_eal_rate",
                "seismic_eal_rate", "total_eal_rate"]
    print(df[eal_cols].describe().map(lambda x: f"{x:.6f}").to_string())

    print("\n" + "=" * 70)
    print("SCORE SUMMARY — ADJUSTED (0–100, higher = more resilient)")
    print("=" * 70)
    score_cols = ["flood_score", "tornado_score", "seismic_score", "resilience_score"]
    print(df[score_cols].describe().map(lambda x: f"{x:.1f}").to_string())

    print("\n" + "=" * 70)
    print("GRADE DISTRIBUTION — NATIONAL (absolute) vs LOCAL (percentile)")
    print("=" * 70)
    national_counts = df["national_grade"].value_counts().sort_index()
    local_counts    = df["local_grade"].value_counts().sort_index()
    all_grades = sorted(set(national_counts.index) | set(local_counts.index))
    print(f"  {'Grade':<6} {'National':>8}  {'Local':>8}")
    print(f"  {'-'*5:<6} {'-'*8:>8}  {'-'*8:>8}")
    for g in all_grades:
        n = national_counts.get(g, 0)
        l = local_counts.get(g, 0)
        print(f"  {g:<6} {n:>8,}  {l:>8,}")

    print("\n  Per-hazard local grade distributions:")
    for hazard, col in [("Flood", "flood_local_grade"),
                        ("Tornado", "tornado_local_grade"),
                        ("Seismic", "seismic_local_grade")]:
        counts = df[col].value_counts().sort_index()
        row_str = "  ".join(f"{g}:{counts.get(g,0):,}" for g in ["A","B","C","D","F"])
        print(f"  {hazard:<8}: {row_str}")

    print("\n" + "=" * 70)
    print("SCORE DISTRIBUTION (resilience_score, BRM-adjusted)")
    print("=" * 70)
    bins   = [0, 20, 40, 60, 80, 100]
    labels = ["0-20 (F)", "20-40 (D)", "40-60 (C)", "60-80 (B)", "80-100 (A)"]
    df["_band"] = pd.cut(df["resilience_score"], bins=bins,
                         labels=labels, include_lowest=True)
    for band, cnt in df["_band"].value_counts().sort_index().items():
        bar = "#" * (cnt // 10)
        print(f"  {band}: {cnt:>5}  {bar}")
    df.drop(columns=["_band"], inplace=True)

    # --- BRM effect: score shift ---
    # Compute pre-BRM scores for comparison (using raw EAL rates)
    df["_score_pre_brm"] = (
        df["flood_eal_rate_raw"] + df["tornado_eal_rate_raw"] + df["seismic_eal_rate_raw"]
    ).apply(eal_rate_to_score)
    df["_score_shift"] = df["resilience_score"] - df["_score_pre_brm"]

    print("\n" + "=" * 70)
    print("BRM SCORE SHIFT (adjusted − pre-BRM, positive = more resilient)")
    print("=" * 70)
    shift = df["_score_shift"]
    print(f"  Mean shift:   {shift.mean():+.2f} points")
    print(f"  Std dev:      {shift.std():.2f} points")
    print(f"  Range:        {shift.min():+.2f} to {shift.max():+.2f}")
    print(f"  Improved (↑): {(shift > 0).sum():,} parcels")
    print(f"  Worsened (↓): {(shift < 0).sum():,} parcels")
    print(f"  Unchanged:    {(shift == 0).sum():,} parcels")

    df.drop(columns=["_score_pre_brm", "_score_shift"], inplace=True)

    # --- 5 examples: extreme BRM values ---
    print("\n" + "=" * 70)
    print("EXAMPLE ROWS — HIGH & LOW BRM (illustrating modifier effect)")
    print("=" * 70)
    # Pick 2 with highest flood_brm (most vulnerable) + 2 with lowest + 1 median
    examples = pd.concat([
        df.nlargest(2, "flood_brm"),
        df.nsmallest(2, "flood_brm"),
        df.iloc[[(df["flood_brm"] - df["flood_brm"].median()).abs().idxmin()]],
    ]).drop_duplicates()

    ex_cols = [
        "flood_risk", "YRBLT", "EXTWALL", "BSMT", "COND",
        "code_era_factor", "construction_factor", "foundation_factor",
        "condition_factor", "flood_brm", "wind_seismic_brm",
        "flood_eal_rate", "total_eal_rate", "resilience_score",
        "national_grade", "local_grade", "percentile_rank", "brm_source",
    ]
    print(examples[ex_cols].to_string(index=False))

    # --- 5 examples: national vs local grade divergence ---
    print("\n" + "=" * 70)
    print("EXAMPLE ROWS — NATIONAL vs LOCAL GRADE DIVERGENCE")
    print("=" * 70)
    # Find parcels where the two grades differ and pick the most extreme splits
    df["_grade_diff"] = (df["national_grade"] != df["local_grade"]).astype(int)
    # Sort by how far apart the scores and percentile are (large percentile, mid score)
    df["_divergence"] = (df["percentile_rank"] - 50).abs()
    divergent = df[df["_grade_diff"] == 1].nlargest(5, "_divergence")
    if len(divergent) < 5:
        # Pad with any differing rows
        divergent = df[df["_grade_diff"] == 1].head(5)

    div_cols = [
        "PARCELID", "flood_risk", "YRBLT", "COND",
        "resilience_score", "percentile_rank",
        "national_grade", "local_grade",
        "flood_local_grade", "tornado_local_grade", "seismic_local_grade",
    ]
    print(divergent[div_cols].to_string(index=False))

    # --- Grade shift summary ---
    print("\n" + "=" * 70)
    print("GRADE SHIFT SUMMARY (national → local)")
    print("=" * 70)
    total_different = df["_grade_diff"].sum()
    total_same      = len(df) - total_different
    print(f"  Same grade (national = local): {total_same:,} parcels "
          f"({total_same/len(df)*100:.1f}%)")
    print(f"  Different grade:               {total_different:,} parcels "
          f"({total_different/len(df)*100:.1f}%)")

    print(f"\n  Local grade A-F all populated: "
          f"{sorted(df['local_grade'].unique())}")

    df.drop(columns=["_grade_diff", "_divergence"], inplace=True)

    print("\n" + "=" * 70)
    print("DOLLAR EAL SUMMARY (expected annual loss in $, using RTOTAPR)")
    print("=" * 70)
    dollar_cols = ["flood_eal_dollars", "tornado_eal_dollars",
                   "seismic_eal_dollars", "total_eal_dollars"]
    print(df[dollar_cols].describe().map(lambda x: f"${x:,.0f}").to_string())


if __name__ == "__main__":
    main()
