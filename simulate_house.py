#!/usr/bin/env python3
"""simulate_house.py — Housing Nutrition Label: Disaster Resilience Simulator

Defines a hypothetical house and shows where it scores on the disaster
resilience dimension — nationally and locally against the Shelby County dataset.

Usage examples
--------------
  python simulate_house.py \\
      --flood-zone X --lat 35.15 --lon -89.85 \\
      --year-built 2026 --construction icf --foundation slab \\
      --condition excellent --value 350000 \\
      --solar --backup-generator --passive-house

  python simulate_house.py --preset icf-passive --lat 35.15 --lon -89.85
  python simulate_house.py --preset worst-case  --lat 35.15 --lon -89.85

Methodology mirrors score_resilience.py exactly:
  EAL rate = flood + tornado + seismic, each × Building Resilience Modifier (BRM).
  BRM = code_era × construction_type × (foundation for flood only) × condition.
  Score = log-linear interpolation of total EAL rate → 0-100.
  National grade = absolute score thresholds.
  Local grade = percentile rank vs. shelby_parcels_scored.csv.
"""

import argparse
import math
import pathlib
import sys

import numpy as np
import pandas as pd

# ── File paths ─────────────────────────────────────────────────────────────────
BASE_DIR   = pathlib.Path(__file__).resolve().parent
SCORED_CSV = BASE_DIR / "shelby_parcels_scored.csv"
SPC_CACHE  = BASE_DIR / "spc_tornadoes_raw.csv"

# ── Seismic constants (enrich_seismic.py) ─────────────────────────────────────
NMSZ_LAT            = 36.5     # New Madrid Seismic Zone reference lat
NMSZ_LON            = -89.6    # New Madrid Seismic Zone reference lon
PGA_2PCT_BASE       = 0.48     # g, 2%/50yr baseline for Memphis (NSHM 2023)
PGA_10PCT_BASE      = 0.19     # g, 10%/50yr baseline for Memphis (NSHM 2023)
DIST_NEAR           = 76.0     # mi — closest parcels to NMSZ (NE county corner)
DIST_FAR            = 110.0    # mi — farthest parcels from NMSZ (SW county corner)
ALLUVIUM_LON_THRESH = -89.95   # west of this → deeper alluvial soils (+5% PGA)

# ── Tornado constants (enrich_tornado.py) ─────────────────────────────────────
SPC_DATA_YEARS = 74     # SPC database covers 1950–2023
RADIUS_25_MI   = 25.0   # search radius for tornado count
SHELBY_LAT     = 35.15  # county center (bbox pre-filter reference)
SHELBY_LON     = -89.98
BBOX_DEG       = 0.50   # ±0.50° ≈ 34 mi coarse pre-filter around county

# Fallback when SPC cache is unavailable; empirical median from scored dataset.
COUNTY_AVG_TORNADO_RATE = 1.30  # tornadoes/yr within 25 mi (median of 1,000 parcels)

# ── Flood EAL rates (score_resilience.py) ─────────────────────────────────────
# AEP × mean damage ratio per FEMA NFIP actuarial data.
FLOOD_EAL_RATES = {
    "high":     0.010 * 0.28,   # AE zone:     1.0% AEP × 28% MDR = 0.280%/yr
    "moderate": 0.002 * 0.15,   # Shaded X500: 0.2% AEP × 15% MDR = 0.030%/yr
    "minimal":  0.0004 * 0.05,  # Unshaded X:  0.04% AEP × 5% MDR = 0.002%/yr
}

FLOOD_ZONE_TO_RISK = {"AE": "high", "X500": "moderate", "X": "minimal"}

# ── Tornado EAL constants (score_resilience.py) ───────────────────────────────
# EF distribution: TN/Mid-South region, SPC 1950–2023 (Ashley 2007 calibration).
EF_DISTRIBUTION = {0: 0.45, 1: 0.33, 2: 0.14, 3: 0.06, 4: 0.02}

# Mean path dimensions (width_yards, length_miles) → path area in sq mi.
EF_PATH_AREA = {0: (50, 0.5), 1: (100, 1.5), 2: (200, 3.0), 3: (400, 7.0), 4: (800, 15.0)}

# HAZUS-MH mean damage ratios for wood-frame residential (FEMA 2012).
EF_DAMAGE_RATIO = {0: 0.02, 1: 0.10, 2: 0.30, 3: 0.60, 4: 0.90}

CIRCLE_AREA_SQ_MI = np.pi * 25 ** 2   # ≈ 1963.5 sq mi (denominator for strike prob)

# ── Seismic hazard curve rates (score_resilience.py) ──────────────────────────
# Annual exceedance rates via Poisson: λ = −ln(1−p)/t
LAMBDA_10 = -np.log(0.90) / 50   # ≈ 0.002107 /yr  (10%/50yr, ~475-yr return)
LAMBDA_2  = -np.log(0.98) / 50   # ≈ 0.000404 /yr  (2%/50yr,  ~2475-yr return)

# ── Score/grade breakpoints (score_resilience.py) ─────────────────────────────
# Log-linear interpolation anchored to physically meaningful EAL thresholds.
SCORE_BREAKPOINTS = [
    (100, 0.00001),   # 0.001%/yr — virtually no hazard (5× harder than old 0.005% threshold)
    (95,  0.00003),   # 0.003%/yr — near-perfect build
    (80,  0.0002),    # 0.020%/yr — low risk (≈ national average)
    (60,  0.001),     # 0.100%/yr — moderate risk
    (40,  0.003),     # 0.300%/yr — high risk
    (20,  0.010),     # 1.000%/yr — very high risk
    (0,   0.020),     # 2.000%/yr — extreme risk
]
BRM_MAX = 1.5  # upper clamp on Building Resilience Modifier

# Construction-type-specific BRM floors (lower bound on adjusted EAL multiplier).
# Replaces the previous universal floor of 0.50 with per-type values supported
# by published test data and field reports.
BRM_FLOOR = {
    "frame":       0.50,  # worst-case performance ceiling for wood frame
    "vinyl":       0.50,  # same framing as wood; cladding provides no structural floor benefit
    "brick-frame": 0.50,  # composite system; governed by frame at extreme loads
    "brick":       0.40,  # solid masonry outperforms frame meaningfully
    "block":       0.40,  # reinforced CMU; significant lateral resistance
    "stone":       0.40,  # solid masonry; best of traditional types
    "icf":         0.15,  # 85% max EAL reduction — PCA racking test data: 5-10× wood frame;
                           # FEMA MAT Joplin/Moore reports; ICC-500 safe-room standard met
    "sip":         0.25,  # engineered composite; below ICF but large improvement over frame
}

# ── Construction type → BRM factor (tornado/seismic) ─────────────────────────
# Named types map to the same underlying factors as EXTWALL codes in
# score_resilience.py. ICF and SIP values updated from literature review.
CONSTRUCTION_FACTOR = {
    "frame":       1.20,  # Light wood frame — most vulnerable (HAZUS-MH W1 class)
    "vinyl":       1.15,  # Vinyl/aluminum siding on wood frame — minor cladding benefit
    "brick-frame": 1.00,  # Brick veneer on wood frame — composite system, baseline
    "brick":       0.95,  # Solid brick — improved cladding & lateral resistance vs. veneer
    "block":       0.90,  # Reinforced CMU — strong lateral resistance (HAZUS-MH RM1)
    "stone":       0.85,  # Solid masonry — best lateral resistance of traditional types
    "icf":         0.25,  # Insulated Concrete Forms — monolithic concrete shell; 75-90%
                           # damage reduction vs. wood frame for tornado/seismic.
                           # Sources: PCA racking test data: 5-10× wood frame;
                           # FEMA MAT Joplin/Moore reports; U.S. Resiliency Council:
                           # 170-270% higher losses for wood vs ICF (seismic events)
    "sip":         0.35,  # Structural Insulated Panels — engineered wood composite;
                           # superior racking resistance vs. wood frame, excellent air/
                           # moisture barrier. Below ICF but well above frame.
}

# ── Construction type → BRM factor (flood only) ───────────────────────────────
# ICF gets a separate, less aggressive flood factor because the concrete shell
# survives inundation structurally, but interior finishes remain vulnerable.
# Source: NFIP Class 5 flood-resistant material classification; FEMA P-259
# depth-damage curves for concrete; "ICF flood: structural 80-95% reduction;
# finishes still vulnerable."
FLOOD_CONSTRUCTION_FACTOR = {
    **{k: v for k, v in CONSTRUCTION_FACTOR.items()},  # default: same as wind/seismic
    "icf": 0.45,  # NFIP Class 5; concrete survives, finishes still damaged
}

# ── Foundation → BRM factor (flood EAL only) ──────────────────────────────────
# Matches BSMT_FLOOD_FACTOR in score_resilience.py (FEMA P-259 depth-damage curves).
FOUNDATION_FACTOR = {
    "slab":             0.7,   # At/above grade; minimal flood intrusion (FEMA P-259)
    "crawl":            1.0,   # Baseline; limited below-grade habitable area
    "partial-basement": 1.2,   # 25-75% below grade; substantial flood exposure
    "full-basement":    1.4,   # ≥75% below grade; catastrophic flood loss potential
}

# ── Condition → BRM factor ────────────────────────────────────────────────────
# Matches COND_FACTOR in score_resilience.py (HAZUS-MH §3.5 deterioration factors).
CONDITION_FACTOR = {
    "unsound":   1.5,  # Near-collapse baseline (ASCE 41 CP level exceeded)
    "poor":      1.3,  # Major deterioration; high damage amplification
    "fair":      1.1,  # Minor deficiencies; modest amplification
    "average":   1.0,  # Baseline (design-intent performance)
    "good":      0.9,  # Well-maintained; minor loss reduction
    "excellent": 0.8,  # Superior maintenance/upgrades; maximum loss reduction
}

# ── Bonus feature modifiers ───────────────────────────────────────────────────
# All values are v1 estimates, pending literature review.
# Applied multiplicatively on top of BRM-adjusted EAL rates.

# General modifiers — applied to every hazard's EAL.
BONUS_SOLAR      = 0.97  # Solar panels: grid independence reduces post-disaster
                          # recovery loss and secondary disruption costs. (v1)
BONUS_GENERATOR  = 0.95  # Backup generator/battery: critical systems stay operational;
                          # reduces secondary and contents losses post-event. (v1)
BONUS_PASSIVE    = 0.92  # Passive house certification: superior envelope, airtightness,
                          # and thermal mass improve moisture resistance and thermal
                          # survivability (RMI study: 6+ days habitable without power).
                          # Structural wind benefit is indirect; 0.92 reflects envelope/
                          # recovery benefit without overstating direct structural effect.
BONUS_SPRINKLERS = 0.92  # Residential fire sprinklers: limits fire severity; general
                          # resilience benefit (not disaster-specific). (v1)

# Hazard-specific modifiers.
BONUS_SAFE_ROOM   = 0.85  # FEMA P-361 tornado safe room: applied to property damage EAL
                            # only — the safe room does not prevent structural damage to
                            # the main building, so the 0.85 factor reflects partial
                            # contents/habitability loss reduction.
                            # NOTE: CDC 2011 Alabama tornado data shows ~99% fatality
                            # elimination for safe room occupants, but this property
                            # damage model does not capture life-safety directly.
BONUS_LEAK_DETECT = 0.95  # Smart leak detection: early water intrusion alarm limits
                            # flood damage duration and mold/secondary losses. (v1)
BONUS_SEISMIC_RET = 0.75  # Seismic retrofit / base isolation: FEMA P-420 retrofit
                            # standards reduce expected structural damage by ~25-40%;
                            # base isolation yields even larger reductions. (v1)

# ── Wind/Tornado above-code feature modifiers ─────────────────────────────────
# Applied multiplicatively to tornado/wind EAL only (after BRM).
# FORTIFIED tiers are composite — supersede individual wind features if specified.
BONUS_HURRICANE_STRAPS   = 0.70  # Continuous load path connections; IBHS: 50% uplift
                                  # reduction. Source: IBHS FORTIFIED research. Strong evidence.
BONUS_HIP_ROOF           = 0.55  # Hip roof vs. gable; IBHS: 45-50% peak pressure reduction.
                                  # Source: IBHS. Strong evidence.
BONUS_IMPACT_GARAGE_DOOR = 0.75  # Impact-rated garage door; 80% of wind damage initiates
                                  # via garage. Source: FEMA/IBHS. Strong evidence.
BONUS_SEALED_ROOF_DECK   = 0.80  # Secondary water barrier / peel-and-stick underlayment;
                                  # prevents water intrusion after shingle loss.
                                  # Source: IBHS. Strong evidence.
BONUS_METAL_ROOF         = 0.75  # Standing seam metal roof; 150+ mph wind rating.
                                  # Source: industry testing data. Moderate evidence.
BONUS_REINFORCED_GABLE   = 0.80  # Reinforced gable end walls; documented failure mode.
                                  # Source: FEMA failure mode documentation. Moderate evidence.
BONUS_RING_SHANK_NAILS   = 0.88  # Ring-shank nails for sheathing; IBHS: 12-25% better
                                  # withdrawal resistance. Source: IBHS. Moderate evidence.
BONUS_TRUSS_16OC         = 0.92  # 16" OC trusses vs 24"; expert structural estimate.
                                  # Source: engineering estimates. Weak direct evidence.

# FORTIFIED certification tiers — composite modifier (supersedes individual wind features).
BONUS_FORTIFIED_ROOF     = 0.35  # IBHS FORTIFIED Roof; actuarial: 73% claim reduction
                                  # (Hurricane Sally). Source: IBHS. Strong evidence.
BONUS_FORTIFIED_SILVER   = 0.25  # IBHS FORTIFIED Silver.
                                  # Source: IBHS. Strong evidence.
BONUS_FORTIFIED_GOLD     = 0.20  # IBHS FORTIFIED Gold; actuarial: 76% claim reduction.
                                  # Source: IBHS. Strong evidence.

# ── Seismic above-code feature modifiers ──────────────────────────────────────
# Applied multiplicatively to seismic EAL only (after BRM).
BONUS_CRIPPLE_WALL       = 0.45  # Cripple wall bracing for raised foundations;
                                  # PEER-CEA: 40-70% loss reduction. Strong evidence.
BONUS_SEISMIC_HOLD_DOWNS = 0.85  # Hold-down connectors at shear walls.
                                  # Source: engineering practice. Moderate evidence.
BONUS_AUTO_GAS_SHUTOFF   = 0.90  # Automatic seismic gas shutoff valve; prevents fire.
                                  # Source: FEMA guidelines. Moderate evidence.

# ── Flood above-code feature modifiers ────────────────────────────────────────
# Elevation flags are mutually exclusive (validated in resolve_config).
# Applied multiplicatively to flood EAL only (after BRM).
BONUS_ELEVATION_1FT      = 0.15  # Elevated 1 ft above BFE; FEMA: 93% annual loss reduction.
                                  # Source: FEMA depth-damage curves. Strong evidence.
BONUS_ELEVATION_2FT      = 0.08  # Elevated 2 ft above BFE.
                                  # Source: FEMA depth-damage curves. Strong evidence.
BONUS_ELEVATION_3FT      = 0.04  # Elevated 3 ft above BFE.
                                  # Source: FEMA depth-damage curves. Strong evidence.
BONUS_FLOOD_VENTS        = 0.85  # Engineered flood vents; reduces hydrostatic damage.
                                  # Source: FEMA. Moderate evidence.
BONUS_BACKFLOW_VALVE     = 0.90  # Backflow prevention valve; prevents sewer backup.
                                  # Source: FEMA. Moderate evidence.

# ── Preset profiles ────────────────────────────────────────────────────────────
PRESETS = {
    "baseline": {
        # Typical 2000s suburban tract home in Shelby County.
        "year_built": 2000, "construction": "frame", "foundation": "slab",
        "condition": "average", "flood_zone": "X", "value": 160_000,
    },
    "premium": {
        # High-end new build: solid brick, excellent condition, post-IBC.
        "year_built": 2026, "construction": "brick", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 450_000,
    },
    "icf-passive": {
        # The dream build: ICF passive house with full resilience package.
        "year_built": 2026, "construction": "icf", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 500_000,
        "solar": True, "backup_generator": True,
        "passive_house": True, "tornado_safe_room": True,
        # Above-code wind/flood upgrades added to dream spec.
        "hurricane_straps": True, "hip_roof": True, "metal_roof": True,
        "sealed_roof_deck": True, "elevation_1ft": True,
    },
    "worst-case": {
        # Pre-1950 wood frame, full basement, AE flood zone, poor condition.
        "year_built": 1945, "construction": "frame", "foundation": "full-basement",
        "condition": "poor", "flood_zone": "AE", "value": 80_000,
    },
    "fortified-gold": {
        # 2026 frame build on slab, zone X, IBHS FORTIFIED Gold + metal roof + sealed deck.
        "year_built": 2026, "construction": "frame", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 350_000,
        "fortified_gold": True, "sealed_roof_deck": True, "metal_roof": True,
    },
}


# ── Physics / calculation helpers ─────────────────────────────────────────────

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return 2 * 3958.8 * math.asin(math.sqrt(a))


def compute_seismic_pga(lat: float, lon: float) -> tuple[float, float, float]:
    """
    Return (pga_2pct, pga_10pct, nmsz_dist_mi) using the same method as
    enrich_seismic.py: distance factor ±10% over county range + soil bump.
    """
    dist_mi = haversine_miles(lat, lon, NMSZ_LAT, NMSZ_LON)
    clamped = max(DIST_NEAR, min(dist_mi, DIST_FAR))
    dist_factor = 1.10 - 0.20 * (clamped - DIST_NEAR) / (DIST_FAR - DIST_NEAR)
    soil_factor = 1.05 if lon < ALLUVIUM_LON_THRESH else 1.0
    return (
        round(PGA_2PCT_BASE  * dist_factor * soil_factor, 3),
        round(PGA_10PCT_BASE * dist_factor * soil_factor, 3),
        round(dist_mi, 1),
    )


def compute_tornado_rate(lat: float, lon: float) -> tuple[float, str]:
    """
    Return (avg_tornadoes_per_yr_25mi, source_note).
    Uses cached SPC data if available; otherwise falls back to county average.
    """
    if not SPC_CACHE.exists():
        return COUNTY_AVG_TORNADO_RATE, "county average (SPC cache not found)"

    df = pd.read_csv(SPC_CACHE, low_memory=False)
    df.columns = df.columns.str.strip()
    df = df[df["slat"].notna() & df["slon"].notna() & (df["slat"] != 0)].copy()
    df["slat"] = df["slat"].astype(float)
    df["slon"] = df["slon"].astype(float)

    nearby = df[
        df["slat"].between(SHELBY_LAT - BBOX_DEG, SHELBY_LAT + BBOX_DEG) &
        df["slon"].between(SHELBY_LON - BBOX_DEG, SHELBY_LON + BBOX_DEG)
    ]
    dists = nearby.apply(
        lambda row: haversine_miles(lat, lon, row["slat"], row["slon"]), axis=1
    )
    count = int((dists <= RADIUS_25_MI).sum())
    rate  = round(count / SPC_DATA_YEARS, 3)
    return rate, f"SPC 1950-2023 ({count} tornadoes in 25 mi)"


def pga_to_damage_ratio(pga_g: float) -> float:
    """Map PGA (g) to mean structural damage ratio (HAZUS-MH fragility curves)."""
    if pga_g < 0.10: return 0.005   # imperceptible — no structural damage
    if pga_g < 0.20: return 0.03    # light — chimney/plaster, minor cracking
    if pga_g < 0.40: return 0.10    # moderate — significant cracking, some structural
    if pga_g < 0.60: return 0.25    # heavy — major structural damage, partial collapse
    return 0.50                      # severe — near-complete destruction (wood-frame)


def calc_flood_eal_raw(flood_risk: str) -> float:
    return FLOOD_EAL_RATES[flood_risk]


def calc_tornado_eal_raw(tornado_rate: float) -> float:
    """Tornado EAL rate: sum over EF categories of (strike probability × damage ratio)."""
    eal = 0.0
    for ef, ef_frac in EF_DISTRIBUTION.items():
        w_yd, l_mi = EF_PATH_AREA[ef]
        path_area   = (w_yd / 1760.0) * l_mi          # sq mi
        strike_prob = tornado_rate * ef_frac * (path_area / CIRCLE_AREA_SQ_MI)
        eal        += strike_prob * EF_DAMAGE_RATIO[ef]
    return eal


def calc_seismic_eal_raw(pga_2pct: float, pga_10pct: float) -> float:
    """Seismic EAL rate: two-point trapezoidal hazard curve integration."""
    dr_rare     = pga_to_damage_ratio(pga_2pct)    # 2%/50yr damage ratio
    dr_moderate = pga_to_damage_ratio(pga_10pct)   # 10%/50yr damage ratio
    return LAMBDA_2 * dr_rare + (LAMBDA_10 - LAMBDA_2) * dr_moderate


def eal_rate_to_score(eal_rate: float) -> float:
    """Map fractional EAL rate to 0-100 via log-linear interpolation."""
    if eal_rate <= SCORE_BREAKPOINTS[0][1]:  return 100.0
    if eal_rate >= SCORE_BREAKPOINTS[-1][1]: return 0.0
    for i in range(len(SCORE_BREAKPOINTS) - 1):
        s_hi, e_lo = SCORE_BREAKPOINTS[i]
        s_lo, e_hi = SCORE_BREAKPOINTS[i + 1]
        if e_lo <= eal_rate <= e_hi:
            t = (np.log(eal_rate) - np.log(e_lo)) / (np.log(e_hi) - np.log(e_lo))
            return s_hi + (s_lo - s_hi) * t
    return 0.0


def score_to_national_grade(score: float) -> str:
    if score >= 80: return "A"
    if score >= 60: return "B"
    if score >= 40: return "C"
    if score >= 20: return "D"
    return "F"


def percentile_to_local_grade(pct: float) -> str:
    """A=top 10%, B=next 25%, C=middle 30%, D=next 25%, F=bottom 10%."""
    if pct >= 90: return "A"
    if pct >= 65: return "B"
    if pct >= 35: return "C"
    if pct >= 10: return "D"
    return "F"


def code_era_factor(year_built: int) -> float:
    """Code-era vulnerability multiplier (matches score_resilience.py exactly)."""
    yr = int(year_built)
    if yr < 1970: return 1.3    # pre-modern codes: before ANSI 58.1 / seismic reforms
    if yr < 1990: return 1.1    # early modern: ASCE 7 wind, pre-Northridge
    if yr < 2003: return 1.0    # post-Hugo/Northridge baseline
    return 0.85                  # post-IBC (TN adopted IBC 2003): best provisions


def compute_local_percentile(sim_score: float, scored_df: pd.DataFrame) -> float:
    """Fraction of county parcels with resilience_score < sim_score (×100)."""
    scores = scored_df["resilience_score"].dropna().values
    return round((scores < sim_score).sum() / len(scores) * 100, 1)


# ── Argument parsing ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Simulate a hypothetical house's disaster resilience score.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Presets: baseline | premium | icf-passive | worst-case | fortified-gold\n"
               "Example: python simulate_house.py --preset icf-passive --lat 35.15 --lon -89.85",
    )
    p.add_argument("--preset", choices=list(PRESETS.keys()), default=None,
                   help="Load a named preset profile (all fields can still be overridden).")
    p.add_argument("--lat", type=float, default=None, help="Latitude. Default: county center.")
    p.add_argument("--lon", type=float, default=None, help="Longitude. Default: county center.")

    p.add_argument("--flood-zone", choices=["X", "X500", "AE"],
                   help="FEMA flood zone: X (minimal), X500 (moderate/shaded X), AE (high).")
    p.add_argument("--year-built",   type=int, default=None, help="Year built. Default: 2024.")
    p.add_argument("--construction", choices=list(CONSTRUCTION_FACTOR.keys()), default=None,
                   help="Exterior wall / structural system. Default: frame.")
    p.add_argument("--foundation",   choices=list(FOUNDATION_FACTOR.keys()), default=None,
                   help="Foundation type. Default: slab.")
    p.add_argument("--condition",    choices=list(CONDITION_FACTOR.keys()), default=None,
                   help="Structural condition. Default: average.")
    p.add_argument("--value", type=float, default=None,
                   help="Appraised value ($). Default: county median ~$160,000.")

    # ── Existing bonus feature flags ──────────────────────────────────────────────
    p.add_argument("--solar",             action="store_true", help="Solar panels.")
    p.add_argument("--backup-generator",  action="store_true", help="Backup generator/battery.")
    p.add_argument("--passive-house",     action="store_true", help="Passive house certification.")
    p.add_argument("--tornado-safe-room", action="store_true", help="FEMA P-361 tornado safe room.")
    p.add_argument("--fire-sprinklers",   action="store_true", help="Residential fire sprinklers.")
    p.add_argument("--leak-detection",    action="store_true", help="Smart leak detection system.")
    p.add_argument("--seismic-retrofit",  action="store_true",
                   help="Seismic retrofit or base isolation.")

    # ── Wind/Tornado above-code features ──────────────────────────────────────────
    wind = p.add_argument_group("wind/tornado above-code features")
    wind.add_argument("--hurricane-straps",    action="store_true",
                      help="Continuous load path connections (×0.70 tornado/wind EAL; IBHS).")
    wind.add_argument("--hip-roof",            action="store_true",
                      help="Hip roof instead of gable (×0.55 tornado/wind EAL; IBHS).")
    wind.add_argument("--impact-garage-door",  action="store_true",
                      help="Impact-rated garage door (×0.75 tornado/wind EAL).")
    wind.add_argument("--sealed-roof-deck",    action="store_true",
                      help="Secondary water barrier / peel-and-stick underlayment (×0.80).")
    wind.add_argument("--metal-roof",          action="store_true",
                      help="Standing seam metal roof (×0.75 tornado/wind EAL).")
    wind.add_argument("--reinforced-gable",    action="store_true",
                      help="Reinforced gable end walls (×0.80 tornado/wind EAL; FEMA).")
    wind.add_argument("--ring-shank-nails",    action="store_true",
                      help="Ring-shank nails for sheathing (×0.88 tornado/wind EAL; IBHS).")
    wind.add_argument("--truss-16oc",          action="store_true",
                      help="16\" OC trusses vs 24\" (×0.92 tornado/wind EAL).")

    # ── FORTIFIED certification (composite — supersedes individual wind features) ──
    fortified = p.add_argument_group("IBHS FORTIFIED certification (composite; supersedes "
                                     "individual wind features)")
    fortified.add_argument("--fortified-roof",   action="store_true",
                           help="IBHS FORTIFIED Roof designation (×0.35 tornado/wind EAL).")
    fortified.add_argument("--fortified-silver",  action="store_true",
                           help="IBHS FORTIFIED Silver (×0.25 tornado/wind EAL).")
    fortified.add_argument("--fortified-gold",    action="store_true",
                           help="IBHS FORTIFIED Gold (×0.20 tornado/wind EAL).")

    # ── Seismic above-code features ───────────────────────────────────────────────
    seismic = p.add_argument_group("seismic above-code features")
    seismic.add_argument("--cripple-wall-bracing", action="store_true",
                         help="Cripple wall bracing for raised foundations (×0.45 seismic EAL).")
    seismic.add_argument("--seismic-hold-downs",   action="store_true",
                         help="Hold-down connectors at shear walls (×0.85 seismic EAL).")
    seismic.add_argument("--auto-gas-shutoff",     action="store_true",
                         help="Automatic seismic gas shutoff valve (×0.90 seismic EAL).")

    # ── Flood above-code features (elevation flags are mutually exclusive) ────────
    flood = p.add_argument_group("flood above-code features")
    elev = flood.add_mutually_exclusive_group()
    elev.add_argument("--elevation-1ft", action="store_true",
                      help="Elevated 1 ft above BFE (×0.15 flood EAL; FEMA: 93%% reduction).")
    elev.add_argument("--elevation-2ft", action="store_true",
                      help="Elevated 2 ft above BFE (×0.08 flood EAL; FEMA).")
    elev.add_argument("--elevation-3ft", action="store_true",
                      help="Elevated 3 ft above BFE (×0.04 flood EAL; FEMA).")
    flood.add_argument("--flood-vents",    action="store_true",
                       help="Engineered flood vents (×0.85 flood EAL).")
    flood.add_argument("--backflow-valve", action="store_true",
                       help="Backflow prevention valve (×0.90 flood EAL).")
    return p


def resolve_config(args: argparse.Namespace) -> dict:
    """
    Build final configuration dict by merging preset defaults with CLI overrides.
    CLI values always win; preset fills in anything not specified; global defaults
    fill in anything the preset doesn't cover.
    """
    GLOBAL_DEFAULTS = {
        "year_built": 2024, "construction": "frame", "foundation": "slab",
        "condition": "average", "value": 160_000,
    }
    cfg = dict(PRESETS[args.preset]) if args.preset else {}

    # Core fields: CLI > preset > global default
    CLI_FIELDS = {
        "year_built":   args.year_built,
        "construction": args.construction,
        "foundation":   args.foundation,
        "condition":    args.condition,
        "value":        args.value,
    }
    for key, cli_val in CLI_FIELDS.items():
        if cli_val is not None:
            cfg[key] = cli_val
        elif key not in cfg:
            cfg[key] = GLOBAL_DEFAULTS[key]

    # Flood zone: required unless preset provides it
    if args.flood_zone is not None:
        cfg["flood_zone"] = args.flood_zone
    elif "flood_zone" not in cfg:
        print("ERROR: --flood-zone is required when not using a preset.", file=sys.stderr)
        sys.exit(1)

    # Location: default to county center if not provided
    cfg["lat"] = args.lat if args.lat is not None else SHELBY_LAT
    cfg["lon"] = args.lon if args.lon is not None else SHELBY_LON

    # Bonus flags: preset OR CLI (either can activate)
    for flag in [
        # existing
        "solar", "backup_generator", "passive_house",
        "tornado_safe_room", "fire_sprinklers", "leak_detection", "seismic_retrofit",
        # wind/tornado above-code
        "hurricane_straps", "hip_roof", "impact_garage_door", "sealed_roof_deck",
        "metal_roof", "reinforced_gable", "ring_shank_nails", "truss_16oc",
        # FORTIFIED tiers
        "fortified_roof", "fortified_silver", "fortified_gold",
        # seismic above-code
        "cripple_wall_bracing", "seismic_hold_downs", "auto_gas_shutoff",
        # flood above-code
        "elevation_1ft", "elevation_2ft", "elevation_3ft",
        "flood_vents", "backflow_valve",
    ]:
        cfg[flag] = cfg.get(flag, False) or getattr(args, flag, False)

    # Validate: at most one flood elevation tier (argparse mutually_exclusive_group handles
    # CLI, but presets could theoretically set multiple — enforce here too).
    elev_flags = [f for f in ["elevation_1ft", "elevation_2ft", "elevation_3ft"] if cfg.get(f)]
    if len(elev_flags) > 1:
        print(f"ERROR: Flood elevation flags are mutually exclusive; got: {elev_flags}",
              file=sys.stderr)
        sys.exit(1)

    return cfg


# ── Core simulation ────────────────────────────────────────────────────────────

def simulate(cfg: dict) -> dict:
    """Run the full EAL + BRM + bonus calculation. Returns a results dict."""
    r = {}

    # ── Hazard parameters from location ───────────────────────────────────────
    pga_2pct, pga_10pct, nmsz_dist = compute_seismic_pga(cfg["lat"], cfg["lon"])
    tornado_rate, tornado_src       = compute_tornado_rate(cfg["lat"], cfg["lon"])
    flood_risk = FLOOD_ZONE_TO_RISK[cfg["flood_zone"]]

    r.update(pga_2pct=pga_2pct, pga_10pct=pga_10pct, nmsz_dist=nmsz_dist,
             tornado_rate=tornado_rate, tornado_src=tornado_src, flood_risk=flood_risk)

    # ── BRM components ────────────────────────────────────────────────────────
    cef      = code_era_factor(cfg["year_built"])
    ctf      = CONSTRUCTION_FACTOR[cfg["construction"]]       # tornado/seismic
    ctf_flood = FLOOD_CONSTRUCTION_FACTOR[cfg["construction"]] # flood (ICF differs)
    ff       = FOUNDATION_FACTOR[cfg["foundation"]]
    cf       = CONDITION_FACTOR[cfg["condition"]]
    brm_floor = BRM_FLOOR.get(cfg["construction"], 0.50)

    flood_brm        = float(np.clip(cef * ctf_flood * ff * cf, brm_floor, BRM_MAX))
    wind_seismic_brm = float(np.clip(cef * ctf * cf,            brm_floor, BRM_MAX))

    r.update(cef=cef, ctf=ctf, ctf_flood=ctf_flood, ff=ff, cf=cf,
             brm_floor=brm_floor,
             flood_brm=flood_brm, wind_seismic_brm=wind_seismic_brm)

    # ── Raw EAL rates (before BRM) ────────────────────────────────────────────
    flood_raw   = calc_flood_eal_raw(flood_risk)
    tornado_raw = calc_tornado_eal_raw(tornado_rate)
    seismic_raw = calc_seismic_eal_raw(pga_2pct, pga_10pct)

    # ── BRM-adjusted EAL rates ────────────────────────────────────────────────
    flood_adj   = flood_raw   * flood_brm
    tornado_adj = tornado_raw * wind_seismic_brm
    seismic_adj = seismic_raw * wind_seismic_brm

    # ── Hazard-specific bonus modifiers (existing) ────────────────────────────
    if cfg.get("leak_detection"):    flood_adj   *= BONUS_LEAK_DETECT
    if cfg.get("tornado_safe_room"): tornado_adj *= BONUS_SAFE_ROOM
    if cfg.get("seismic_retrofit"):  seismic_adj *= BONUS_SEISMIC_RET

    # ── Wind/tornado above-code modifiers ─────────────────────────────────────
    # FORTIFIED tier is composite and supersedes individual wind features.
    fortified_note = None
    if cfg.get("fortified_gold"):
        tornado_adj  *= BONUS_FORTIFIED_GOLD
        fortified_note = "FORTIFIED Gold certification supersedes individual wind features."
    elif cfg.get("fortified_silver"):
        tornado_adj  *= BONUS_FORTIFIED_SILVER
        fortified_note = "FORTIFIED Silver certification supersedes individual wind features."
    elif cfg.get("fortified_roof"):
        tornado_adj  *= BONUS_FORTIFIED_ROOF
        fortified_note = "FORTIFIED Roof certification supersedes individual wind features."
    else:
        # Stack individual wind features multiplicatively.
        if cfg.get("hurricane_straps"):    tornado_adj *= BONUS_HURRICANE_STRAPS
        if cfg.get("hip_roof"):            tornado_adj *= BONUS_HIP_ROOF
        if cfg.get("impact_garage_door"):  tornado_adj *= BONUS_IMPACT_GARAGE_DOOR
        if cfg.get("sealed_roof_deck"):    tornado_adj *= BONUS_SEALED_ROOF_DECK
        if cfg.get("metal_roof"):          tornado_adj *= BONUS_METAL_ROOF
        if cfg.get("reinforced_gable"):    tornado_adj *= BONUS_REINFORCED_GABLE
        if cfg.get("ring_shank_nails"):    tornado_adj *= BONUS_RING_SHANK_NAILS
        if cfg.get("truss_16oc"):          tornado_adj *= BONUS_TRUSS_16OC
    r["fortified_note"] = fortified_note

    # ── Seismic above-code modifiers ──────────────────────────────────────────
    if cfg.get("cripple_wall_bracing"):  seismic_adj *= BONUS_CRIPPLE_WALL
    if cfg.get("seismic_hold_downs"):    seismic_adj *= BONUS_SEISMIC_HOLD_DOWNS
    if cfg.get("auto_gas_shutoff"):      seismic_adj *= BONUS_AUTO_GAS_SHUTOFF

    # ── Flood above-code modifiers ────────────────────────────────────────────
    # Elevation tiers are mutually exclusive (validated in resolve_config).
    if cfg.get("elevation_3ft"):   flood_adj *= BONUS_ELEVATION_3FT
    elif cfg.get("elevation_2ft"): flood_adj *= BONUS_ELEVATION_2FT
    elif cfg.get("elevation_1ft"): flood_adj *= BONUS_ELEVATION_1FT
    if cfg.get("flood_vents"):     flood_adj *= BONUS_FLOOD_VENTS
    if cfg.get("backflow_valve"):  flood_adj *= BONUS_BACKFLOW_VALVE

    # ── General bonus modifiers (apply to every hazard EAL) ──────────────────
    gen_mod = 1.0
    if cfg.get("solar"):           gen_mod *= BONUS_SOLAR
    if cfg.get("backup_generator"):gen_mod *= BONUS_GENERATOR
    if cfg.get("passive_house"):   gen_mod *= BONUS_PASSIVE
    if cfg.get("fire_sprinklers"): gen_mod *= BONUS_SPRINKLERS

    flood_adj   *= gen_mod
    tornado_adj *= gen_mod
    seismic_adj *= gen_mod

    r.update(flood_raw=flood_raw, tornado_raw=tornado_raw, seismic_raw=seismic_raw,
             flood_adj=flood_adj, tornado_adj=tornado_adj, seismic_adj=seismic_adj,
             gen_mod=gen_mod)

    total_eal = flood_adj + tornado_adj + seismic_adj
    r["total_eal"] = total_eal

    # ── Scores and national grade ─────────────────────────────────────────────
    r["flood_score"]   = eal_rate_to_score(flood_adj)
    r["tornado_score"] = eal_rate_to_score(tornado_adj)
    r["seismic_score"] = eal_rate_to_score(seismic_adj)
    r["total_score"]   = eal_rate_to_score(total_eal)
    r["national_grade"] = score_to_national_grade(r["total_score"])

    # ── Dollar-denominated EAL ────────────────────────────────────────────────
    v = cfg["value"]
    r["flood_loss"]   = flood_adj   * v
    r["tornado_loss"] = tornado_adj * v
    r["seismic_loss"] = seismic_adj * v
    r["total_loss"]   = total_eal   * v

    # ── Local comparison against scored dataset ───────────────────────────────
    if SCORED_CSV.exists():
        scored = pd.read_csv(SCORED_CSV, usecols=["resilience_score"], low_memory=False)
        scores = scored["resilience_score"].dropna()
        local_pct = compute_local_percentile(r["total_score"], scored)
        r["local_pct"]   = local_pct
        r["local_grade"] = percentile_to_local_grade(local_pct)
        r["n_parcels"]   = len(scores)
        r["score_min"]   = scores.min()
        r["score_max"]   = scores.max()
        r["score_median"] = scores.median()
    else:
        r["local_pct"]   = None
        r["local_grade"] = "N/A"
        r["n_parcels"]   = 0

    return r


# ── Scorecard printer ──────────────────────────────────────────────────────────

BONUS_LABELS = {
    # existing
    "solar":                "Solar panels",
    "backup_generator":     "Backup generator/battery",
    "passive_house":        "Passive house certification",
    "tornado_safe_room":    "FEMA P-361 tornado safe room",
    "fire_sprinklers":      "Residential fire sprinklers",
    "leak_detection":       "Smart leak detection",
    "seismic_retrofit":     "Seismic retrofit/base isolation",
    # wind/tornado above-code
    "hurricane_straps":     "Hurricane straps (load path)",
    "hip_roof":             "Hip roof",
    "impact_garage_door":   "Impact-rated garage door",
    "sealed_roof_deck":     "Sealed roof deck",
    "metal_roof":           "Standing seam metal roof",
    "reinforced_gable":     "Reinforced gable end walls",
    "ring_shank_nails":     "Ring-shank nails",
    "truss_16oc":           "16\" OC trusses",
    # FORTIFIED tiers
    "fortified_roof":       "IBHS FORTIFIED Roof",
    "fortified_silver":     "IBHS FORTIFIED Silver",
    "fortified_gold":       "IBHS FORTIFIED Gold",
    # seismic above-code
    "cripple_wall_bracing": "Cripple wall bracing",
    "seismic_hold_downs":   "Seismic hold-down connectors",
    "auto_gas_shutoff":     "Auto seismic gas shutoff",
    # flood above-code
    "elevation_1ft":        "Elevated 1 ft above BFE",
    "elevation_2ft":        "Elevated 2 ft above BFE",
    "elevation_3ft":        "Elevated 3 ft above BFE",
    "flood_vents":          "Engineered flood vents",
    "backflow_valve":       "Backflow prevention valve",
}

BONUS_MODIFIER_DESC = {
    "solar":                f"×{BONUS_SOLAR} all hazards",
    "backup_generator":     f"×{BONUS_GENERATOR} all hazards",
    "passive_house":        f"×{BONUS_PASSIVE} all hazards",
    "fire_sprinklers":      f"×{BONUS_SPRINKLERS} all hazards",
    "tornado_safe_room":    f"×{BONUS_SAFE_ROOM} tornado only",
    "leak_detection":       f"×{BONUS_LEAK_DETECT} flood only",
    "seismic_retrofit":     f"×{BONUS_SEISMIC_RET} seismic only",
    "hurricane_straps":     f"×{BONUS_HURRICANE_STRAPS} wind/tornado",
    "hip_roof":             f"×{BONUS_HIP_ROOF} wind/tornado",
    "impact_garage_door":   f"×{BONUS_IMPACT_GARAGE_DOOR} wind/tornado",
    "sealed_roof_deck":     f"×{BONUS_SEALED_ROOF_DECK} wind/tornado",
    "metal_roof":           f"×{BONUS_METAL_ROOF} wind/tornado",
    "reinforced_gable":     f"×{BONUS_REINFORCED_GABLE} wind/tornado",
    "ring_shank_nails":     f"×{BONUS_RING_SHANK_NAILS} wind/tornado",
    "truss_16oc":           f"×{BONUS_TRUSS_16OC} wind/tornado",
    "fortified_roof":       f"×{BONUS_FORTIFIED_ROOF} wind/tornado (composite)",
    "fortified_silver":     f"×{BONUS_FORTIFIED_SILVER} wind/tornado (composite)",
    "fortified_gold":       f"×{BONUS_FORTIFIED_GOLD} wind/tornado (composite)",
    "cripple_wall_bracing": f"×{BONUS_CRIPPLE_WALL} seismic only",
    "seismic_hold_downs":   f"×{BONUS_SEISMIC_HOLD_DOWNS} seismic only",
    "auto_gas_shutoff":     f"×{BONUS_AUTO_GAS_SHUTOFF} seismic only",
    "elevation_1ft":        f"×{BONUS_ELEVATION_1FT} flood only",
    "elevation_2ft":        f"×{BONUS_ELEVATION_2FT} flood only",
    "elevation_3ft":        f"×{BONUS_ELEVATION_3FT} flood only",
    "flood_vents":          f"×{BONUS_FLOOD_VENTS} flood only",
    "backflow_valve":       f"×{BONUS_BACKFLOW_VALVE} flood only",
}


def print_scorecard(cfg: dict, r: dict) -> None:
    """Print a clean, fixed-width resilience scorecard to stdout."""
    INNER = 64   # width between ║ and ║ (content is padded to this)
    TOP = "╔" + "═" * INNER + "╗"
    SEP = "╠" + "═" * INNER + "╣"
    BOT = "╚" + "═" * INNER + "╝"

    def row(content: str = "") -> str:
        return f"║{content:<{INNER}}║"

    def section(title: str) -> str:
        return row(f"  {title}")

    active_bonuses = [k for k in BONUS_LABELS if cfg.get(k)]

    print()
    print(TOP)
    print(row("  DISASTER RESILIENCE SCORECARD"))
    print(row("  Simulated House — Shelby County, TN"))
    print(SEP)

    # ── House characteristics ─────────────────────────────────────────────────
    print(section("HOUSE CHARACTERISTICS"))
    print(row(f"    Year built       : {cfg['year_built']}"))
    print(row(f"    Construction     : {cfg['construction'].upper()}"))
    print(row(f"    Foundation       : {cfg['foundation']}"))
    print(row(f"    Condition        : {cfg['condition']}"))
    print(row(f"    Flood zone       : {cfg['flood_zone']}  ({r['flood_risk']} risk)"))
    print(row(f"    Location         : {cfg['lat']:.4f}°N, {abs(cfg['lon']):.4f}°W"))
    print(row(f"    Appraised value  : ${cfg['value']:,.0f}"))
    if active_bonuses:
        bonus_str = ", ".join(BONUS_LABELS[b] for b in active_bonuses)
        # Wrap long bonus list across multiple lines
        words, line_parts, lines = bonus_str.split(", "), [], []
        cur = ""
        for w in words:
            test = cur + (", " if cur else "") + w
            if len(test) > 40:
                if cur:
                    lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
        print(row(f"    Bonus features   : {lines[0]}"))
        for extra in lines[1:]:
            print(row(f"                       {extra}"))
    print(SEP)

    # ── Hazard parameters ─────────────────────────────────────────────────────
    print(section("HAZARD PARAMETERS (from lat/lon)"))
    print(row(f"    NMSZ distance    : {r['nmsz_dist']:.1f} mi to New Madrid fault"))
    print(row(f"    PGA 2%/50yr      : {r['pga_2pct']:.3f} g  (2,475-yr return period)"))
    print(row(f"    PGA 10%/50yr     : {r['pga_10pct']:.3f} g  (475-yr return period)"))
    print(row(f"    Tornado rate     : {r['tornado_rate']:.3f} tornadoes/yr within 25 mi"))
    print(row(f"    Tornado source   : {r['tornado_src']}"))
    print(SEP)

    # ── BRM breakdown ─────────────────────────────────────────────────────────
    print(section("BUILDING RESILIENCE MODIFIER (BRM)"))
    print(row(f"    Code era factor    ({cfg['year_built']})          : {r['cef']:.2f}"))
    print(row(f"    Construction type  ({cfg['construction']:<12})  : {r['ctf']:.2f}"))
    print(row(f"    Foundation factor  ({cfg['foundation']:<12})  : {r['ff']:.2f}  [flood EAL only]"))
    print(row(f"    Condition factor   ({cfg['condition']:<12})  : {r['cf']:.2f}"))
    print(row(f"    {'─'*54}"))
    print(row(f"    Flood BRM          : {r['flood_brm']:.3f}  (code×type×foundation×cond, clamped [{r['brm_floor']},{BRM_MAX}])"))
    print(row(f"    Wind/Seismic BRM   : {r['wind_seismic_brm']:.3f}  (code×type×cond, clamped [{r['brm_floor']},{BRM_MAX}])"))
    if active_bonuses:
        print(row(f"    General bonus mod  : {r['gen_mod']:.4f}  (all hazards combined)"))
        haz_specific = [b for b in BONUS_LABELS if cfg.get(b)
                        and b not in ("solar","backup_generator","passive_house","fire_sprinklers")]
        for b in haz_specific:
            print(row(f"    + {BONUS_LABELS[b]:<30}: {BONUS_MODIFIER_DESC[b]}"))
    if r.get("fortified_note"):
        print(row(f"    ⚑  {r['fortified_note']}"))
    print(SEP)

    # ── Per-hazard breakdown ──────────────────────────────────────────────────
    print(section("PER-HAZARD BREAKDOWN"))
    hdr = f"  {'Hazard':<9} {'Raw EAL':>9} {'Adj EAL':>9} {'Score':>7} {'Grade':>6}"
    print(row(f"    {hdr}"))
    print(row(f"    {'─'*52}"))
    for label, raw, adj, score in [
        ("Flood",   r["flood_raw"],   r["flood_adj"],   r["flood_score"]),
        ("Tornado", r["tornado_raw"], r["tornado_adj"], r["tornado_score"]),
        ("Seismic", r["seismic_raw"], r["seismic_adj"], r["seismic_score"]),
    ]:
        g = score_to_national_grade(score)
        row_str = (f"  {label:<9} {raw*100:>8.4f}% {adj*100:>8.4f}%"
                   f" {score:>7.1f} {g:>6}")
        print(row(f"    {row_str}"))
    print(row(f"    {'─'*52}"))
    total_raw = r["flood_raw"] + r["tornado_raw"] + r["seismic_raw"]
    total_row = (f"  {'TOTAL':<9} {total_raw*100:>8.4f}% {r['total_eal']*100:>8.4f}%"
                 f" {r['total_score']:>7.1f} {r['national_grade']:>6}")
    print(row(f"    {total_row}"))
    print(SEP)

    # ── Dollar EAL ────────────────────────────────────────────────────────────
    print(section("EXPECTED ANNUAL LOSS  (appraised value × adj EAL rate)"))
    print(row(f"    Flood            : ${r['flood_loss']:>10,.0f} / year"))
    print(row(f"    Tornado          : ${r['tornado_loss']:>10,.0f} / year"))
    print(row(f"    Seismic          : ${r['seismic_loss']:>10,.0f} / year"))
    print(row(f"    {'─'*40}"))
    print(row(f"    TOTAL            : ${r['total_loss']:>10,.0f} / year"))
    print(SEP)

    # ── Final scorecard ───────────────────────────────────────────────────────
    print(section("RESILIENCE SCORECARD"))
    # Score bar: 20 blocks spanning 0-100
    filled = int(round(r["total_score"] / 5))
    bar = "█" * filled + "░" * (20 - filled)
    print(row(f"    Composite score  : {r['total_score']:.1f} / 100  [{bar}]"))
    print(row(f"    National grade   : {r['national_grade']}  (absolute EAL thresholds, cross-city)"))

    if r["local_pct"] is not None:
        pct = r["local_pct"]
        print(row(f"    Local grade      : {r['local_grade']}  (percentile rank vs. Shelby County)"))
        print(row(f"    Percentile rank  : {pct:.1f}th  (n={r['n_parcels']:,} county parcels)"))
        print(row(f"    County range     : {r['score_min']:.1f} – {r['score_max']:.1f}  "
                  f"(median {r['score_median']:.1f})"))
        print(row())
        print(row(f"    ▶  Better than {pct:.0f}% of Shelby County parcels"))
    else:
        print(row(f"    Local grade      : N/A  ({SCORED_CSV.name} not found)"))
    print(BOT)
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if args.preset is None and args.flood_zone is None:
        parser.error("--flood-zone is required when not using --preset.")

    cfg = resolve_config(args)
    r   = simulate(cfg)
    print_scorecard(cfg, r)


if __name__ == "__main__":
    main()
