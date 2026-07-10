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

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from functools import lru_cache

import numpy as np
import pandas as pd

from housing_label.simulate.dimensions import (
    simulate_all_dimensions, per_unit_home_value, effective_structure,
    AUTOFILL_VALUE_SOURCE, VALUE_PER_DOOR_SOURCE,
)
from housing_label.confidence import (
    confidence_for_label, bands_for_label, CONFIDENCE_NOTES, CONFIDENCE_LEGEND,
)
from housing_label.enrich.seismic_lookup import get_pga

# ── File paths ─────────────────────────────────────────────────────────────────
BASE_DIR   = pathlib.Path(__file__).resolve().parents[3]   # repo root; data lives here
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
SHELBY_LAT     = 35.15  # default location when none is supplied
SHELBY_LON     = -89.98
BBOX_DEG       = 0.50   # ±0.50° lat ≈ 34 mi coarse pre-filter (lon widened by 1/cos(lat))
# Fallback tornado rate used only if the national SPC dataset can't be loaded.
NATIONAL_AVG_TORNADO_RATE = 0.5

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
# No upper clamp on the Building Resilience Modifier: old / poorly-built / poor-
# condition stock should be free to exceed the code-current baseline so condition
# and pre-code age actually bite. Only a per-construction floor (below) applies.

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
    **CONSTRUCTION_FACTOR,  # default: same as wind/seismic
    "icf": 0.45,  # NFIP Class 5; concrete survives, finishes still damaged
}

# ── Fire peril ────────────────────────────────────────────────────────────────
# The fire EAL has two parts, summed: a structural/electrical baseline (this
# constant) plus the location's WILDFIRE EAL rate. The structural base is the
# national average loss share: NFPA reports ~$9B annual home-fire property loss
# across ~130M housing units (~$70/home/yr); on a ~$350k median home that's
# ≈0.02%/yr. The wildfire term comes from the FEMA National Risk Index, resolved
# for the location and passed in as cfg["wildfire_eal_base"] by build_label_parts
# (0.0 when the location wasn't resolved, keeping simulate() offline-safe). The
# base is calibrated to an "average" home (modifiers = 1.0); age (wiring era) and
# construction (combustibility) scale the whole peril from there.
FIRE_EAL_BASE = 0.0002          # 0.020%/yr national-average residential fire EAL
FIRE_BRM_FLOOR = 0.5            # construction/age alone can at most halve fire EAL

# Construction → fire vulnerability (combustibility of the structure).
FIRE_CONSTRUCTION_FACTOR = {
    "frame":       1.10,  # combustible light-frame structure
    "vinyl":       1.10,  # wood frame; vinyl cladding adds no fire benefit
    "brick-frame": 1.00,  # brick veneer over combustible frame — baseline
    "brick":       0.85,  # masonry structure; less combustible
    "block":       0.80,  # reinforced CMU; non-combustible structure
    "stone":       0.80,  # solid masonry; non-combustible structure
    "icf":         0.70,  # concrete core is fire-resistant (high fire rating)
    "sip":         1.05,  # OSB/foam composite; roughly frame-like fire behavior
}
BONUS_FIRE_SPRINKLERS = 0.40   # residential sprinklers ≈ 60% property-loss reduction
                                # per fire (NFPA); applied to the fire peril only

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

# ── Detected multi-family building material → resilience factors ───────────────
# For a building the NSI detects as multi-family, its actual construction material
# is ground truth and drives resilience better than the (often defaulted) single-
# family construction profile. Grounded in HAZUS building classes: reinforced
# concrete (C) and steel (S) mid-rises are far less wind/seismic-vulnerable than
# wood frame; reinforced masonry (M) is intermediate. Keys: ``ctf`` (tornado /
# seismic), ``flood`` (structure survives inundation; finishes still damaged),
# ``fire`` (combustibility), ``floor`` (BRM floor). Wood/manufactured/other are
# absent → keep the construction-profile factors (a wood multi-family is no more
# wind-robust per unit than a wood house).
_MATERIAL_RESILIENCE = {
    "concrete": {"ctf": 0.30, "flood": 0.45, "fire": 0.65, "floor": 0.15},
    "steel":    {"ctf": 0.35, "flood": 0.55, "fire": 0.60, "floor": 0.20},
    "masonry":  {"ctf": 0.90, "flood": 0.90, "fire": 0.80, "floor": 0.40},
}


def flood_floor_factor(stories) -> float:
    """Flood-exposure multiplier for a representative unit in a stacked multi-family
    building. Flood damage is concentrated on the lowest floor (FEMA P-259 depth-
    damage), so a unit averaged over ``stories`` floors has ~1/stories the exposure
    — floored at 0.15 because ground-floor lobbies, parking, and mechanicals never
    reach zero. 1 story (or unknown) = no reduction."""
    try:
        s = int(stories or 1)
    except (TypeError, ValueError):
        return 1.0
    if s <= 1:
        return 1.0
    return max(round(1.0 / s, 3), 0.15)

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

# Resilience-upgrade flag names (the single source of truth shared by the CLI's
# argparse flags, resolve_config(), and the HTTP API's `upgrades` param).
BONUS_FLAGS = [
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
]
ELEVATION_FLAGS = ["elevation_1ft", "elevation_2ft", "elevation_3ft"]

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
    "duplex": {
        # New brick duplex: 2 units, 1,200 sqft each, small lot.
        "year_built": 2026, "construction": "brick", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 300_000,
        "units": 2, "sqft": 1200, "lot_acres": 0.15,
    },
    "quadplex": {
        # New brick quadplex: 4 units, 900 sqft each.
        "year_built": 2026, "construction": "brick", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 500_000,
        "units": 4, "sqft": 900, "lot_acres": 0.20,
    },
    "icf-quadplex": {
        # ICF quadplex: 4 units, 1,000 sqft each, full resilience package.
        "year_built": 2026, "construction": "icf", "foundation": "slab",
        "condition": "excellent", "flood_zone": "X", "value": 600_000,
        "units": 4, "sqft": 1000, "lot_acres": 0.20,
        "solar": True, "passive_house": True,
        "hurricane_straps": True, "hip_roof": True,
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


_SPC_DF = None   # process cache for the national SPC tornado table


def _load_spc(allow_network: bool = True):
    """Load the national SPC tornado table, downloading + caching it if needed.

    Returns a cleaned DataFrame (slat/slon floats) or None if unavailable.
    """
    global _SPC_DF
    if _SPC_DF is not None:
        return _SPC_DF
    if not SPC_CACHE.exists() and allow_network:
        try:
            import requests
            from housing_label.config import SPC_TORNADO_URL, HEADERS, TIMEOUT
            r = requests.get(SPC_TORNADO_URL, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            SPC_CACHE.write_bytes(r.content)
        except Exception:  # noqa: BLE001
            return None
    if not SPC_CACHE.exists():
        return None
    # The tornado rate only needs the touchdown coordinates, so read just those two
    # columns — the full 29-column SPC table is ~28 MB resident, the two-column slice
    # ~1 MB, which matters on a 512 MB instance. usecols matches on the stripped header
    # so it's robust to any leading/trailing whitespace in the CSV.
    df = pd.read_csv(SPC_CACHE, usecols=lambda c: c.strip() in ("slat", "slon"),
                     low_memory=False)
    df.columns = df.columns.str.strip()
    df = df[df["slat"].notna() & df["slon"].notna() & (df["slat"] != 0)].copy()
    df["slat"] = df["slat"].astype(float)
    df["slon"] = df["slon"].astype(float)
    _SPC_DF = df
    return df


def compute_tornado_rate(lat: float, lon: float,
                         allow_network: bool = True) -> tuple[float, str]:
    """
    Return (avg_tornadoes_per_yr_25mi, source_note) for any US location.

    Counts historical SPC tornado touchdowns within 25 mi of the point (over the
    national 1950–2023 record) and divides by the record length. The national SPC
    dataset is downloaded and cached on first use. Falls back to a national
    average only if the dataset is unavailable.

    The count is a full-table scan of the ~68k-row SPC set, so the result is memoized
    per coordinate (rounded to ~110 m, well inside the 25-mi radius) to avoid
    re-scanning — and re-allocating masks over — the whole table on every request.
    """
    # Resolve (and one-time cache) the SPC table here, NOT inside the memoized helper,
    # so a transient load failure returns the national fallback WITHOUT poisoning the
    # per-coordinate cache — once the table loads, later calls scan it and memoize.
    if _load_spc(allow_network) is None:
        return NATIONAL_AVG_TORNADO_RATE, "national average (SPC dataset unavailable)"
    return _tornado_rate_cached(round(lat, 3), round(lon, 3))


@lru_cache(maxsize=4096)
def _tornado_rate_cached(lat: float, lon: float) -> tuple[float, str]:
    df = _load_spc()   # the singleton table, guaranteed loaded by the caller

    # Coarse bbox pre-filter around the query point, then exact distance.
    # Longitude degrees shrink with latitude, so widen the lon half-window by
    # 1/cos(lat) (clamped) to keep the bbox a safe superset of the 25-mi radius.
    lon_margin = BBOX_DEG / max(math.cos(math.radians(lat)), 0.2)
    nearby = df[
        df["slat"].between(lat - BBOX_DEG, lat + BBOX_DEG) &
        df["slon"].between(lon - lon_margin, lon + lon_margin)
    ]
    if nearby.empty:
        return 0.0, "SPC 1950-2023 (0 tornadoes in 25 mi)"
    # Vectorized haversine over the pre-filtered subset (no per-row Python apply).
    dists = _haversine_miles_np(lat, lon, nearby["slat"].to_numpy(), nearby["slon"].to_numpy())
    count = int((dists <= RADIUS_25_MI).sum())
    rate  = round(count / SPC_DATA_YEARS, 3)
    return rate, f"SPC 1950-2023 ({count} tornadoes in 25 mi)"


def _haversine_miles_np(lat1: float, lon1: float, lat2, lon2):
    """Vectorized great-circle distance (miles) from one point to arrays of points."""
    r1, l1 = math.radians(lat1), math.radians(lon1)
    r2, l2 = np.radians(lat2), np.radians(lon2)
    a = np.sin((r2 - r1) / 2) ** 2 + math.cos(r1) * np.cos(r2) * np.sin((l2 - l1) / 2) ** 2
    a = np.clip(a, 0.0, 1.0)     # guard arcsin against FP drift > 1 (near-antipodal)
    return 2 * 3958.8 * np.arcsin(np.sqrt(a))


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
    """Code-era vulnerability multiplier (wind/seismic). Steepened for pre-code stock."""
    yr = int(year_built)
    if yr < 1940: return 1.6    # pre-WWII: balloon framing, unreinforced masonry, no
                                 # engineered connections or seismic/wind provisions
    if yr < 1970: return 1.3    # pre-modern codes: before ANSI 58.1 / seismic reforms
    if yr < 1990: return 1.1    # early modern: ASCE 7 wind, pre-Northridge
    if yr < 2003: return 1.0    # post-Hugo/Northridge baseline
    return 0.85                  # post-IBC (TN adopted IBC 2003): best provisions


def fire_age_factor(year_built: int) -> float:
    """Structural-fire vulnerability by electrical/wiring era (ignition risk).
    Pre-1950 knob-and-tube and mid-century aluminum branch wiring raise fire risk;
    NEC 2002+ (AFCI breakers, tamper-resistant receptacles) lowers it."""
    yr = int(year_built)
    if yr < 1950: return 1.5    # knob-and-tube era — highest residential electrical-fire risk
    if yr < 1975: return 1.2    # cloth/early-plastic insulation, aluminum branch wiring era
    if yr < 2002: return 1.0    # modern NM-B cable, but pre-AFCI
    return 0.85                  # NEC 2002+ AFCI / tamper-resistant requirements


@lru_cache(maxsize=4)
def _load_local_scores(path_str: str):
    """Load + clean the ``resilience_score`` column from ``path_str`` (cached).

    Keyed on the path so it's read/parsed once per process — the bundled
    scored-parcels CSV is invariant and ``simulate()`` runs up to ~6× per API
    request, so re-reading the whole column every call was pure waste. Keying on
    the path (rather than a no-arg cache) also lets tests point ``SCORED_CSV`` at
    a fixture and still get a fresh load. Returns ``None`` if the file is absent.
    """
    path = pathlib.Path(path_str)
    if not path.exists():
        return None
    col = pd.read_csv(path, usecols=["resilience_score"], low_memory=False)["resilience_score"]
    # Coerce first: a stray non-numeric cell would otherwise make the column
    # object dtype, and `scores < sim_score` / min/max/median would then raise or
    # compare lexicographically. errors="coerce" turns junk into NaN, dropna drops it.
    return pd.to_numeric(col, errors="coerce").dropna().to_numpy()


def _local_scores():
    """Cached county ``resilience_score`` array for the local-percentile compare,
    or ``None`` when the (Shelby-only) scored CSV isn't present."""
    return _load_local_scores(str(SCORED_CSV))


def compute_local_percentile(sim_score: float, scores) -> float:
    """Fraction of county parcels with resilience_score < sim_score (×100).

    ``scores`` is a 1-D array of already-clean county resilience scores.
    """
    return round((scores < sim_score).sum() / len(scores) * 100, 1)


# ── Argument parsing ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Simulate a hypothetical house's disaster resilience score.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Presets: baseline | premium | icf-passive | worst-case | fortified-gold\n"
               "         duplex | quadplex | icf-quadplex\n"
               "Example: python simulate_house.py --preset icf-passive --lat 35.15 --lon -89.85",
    )
    p.add_argument("--preset", choices=list(PRESETS.keys()), default=None,
                   help="Load a named preset profile (all fields can still be overridden).")
    p.add_argument("--address", type=str, default=None,
                   help="Free-text US address; geocoded to lat/lon + county/tract. "
                        "Alternative to --lat/--lon for scoring a house anywhere.")
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
    p.add_argument("--units",      type=int,   default=None,
                   help="Number of dwelling units (e.g. 2 = duplex, 4 = quadplex). Default: 1.")
    p.add_argument("--sqft",       type=float, default=None,
                   help="Heated area per unit (sqft). Default: 2,000.")
    p.add_argument("--lot-acres",  type=float, default=None,
                   help="Lot size (acres). Default: 0.25.")
    p.add_argument("--building-material", dest="bldg_material",
                   choices=["wood", "masonry", "concrete", "steel"], default=None,
                   help="Structural shell material for a multi-unit building (drives "
                        "Resilience/Durability when NSI didn't detect the building).")
    p.add_argument("--stories",    type=int,   default=None,
                   help="Number of floors, for a multi-unit building (floor-aware flood).")

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

    # ── Full nutrition label (all 9 dimensions) ───────────────────────────────────
    label_grp = p.add_argument_group("full nutrition label (all 9 dimensions)")
    label_grp.add_argument("--json", action="store_true",
                           help="Emit the full nutrition label as JSON (all dimensions) and exit.")
    label_grp.add_argument("--density", action="store_true",
                           help="Compare this parcel at 1–4 dwelling units (fixed lot, "
                                "constant per-unit value): the 'density dividend'. "
                                "Combine with --json for machine-readable output.")
    label_grp.add_argument("--density-units", type=str, default=None,
                           help="Comma-separated unit counts for --density "
                                "(default 1,2,3,4), e.g. --density-units 1,2,4.")
    label_grp.add_argument("--no-fetch", action="store_true",
                           help="Skip live API calls for the location dimensions (health, "
                                "socioeconomic, walkability); leave them unscored.")
    label_grp.add_argument("--health-index", type=float, default=None,
                           help="Override the health dimension score (0-100) instead of fetching.")
    label_grp.add_argument("--socioeconomic-index", type=float, default=None,
                           help="Override the socioeconomic dimension score (0-100) instead of fetching.")
    label_grp.add_argument("--walk-score", type=float, default=None,
                           help="Override the walkability dimension score (0-100) instead of fetching.")
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
        "units": 1, "sqft": 2000, "lot_acres": 0.25,
        # Multi-family structure inputs (optional): the building's shell material and
        # its height, used to score Resilience/Durability for a multi-unit building
        # the NSI lookup didn't (or couldn't) classify. Default absent → single-family.
        "bldg_material": None, "stories": None,
    }
    cfg = dict(PRESETS[args.preset]) if args.preset else {}

    # Core fields: CLI > preset > global default
    CLI_FIELDS = {
        "year_built":   args.year_built,
        "construction": args.construction,
        "foundation":   args.foundation,
        "condition":    args.condition,
        "value":        args.value,
        "units":        args.units,
        "sqft":         args.sqft,
        "lot_acres":    args.lot_acres,
        "bldg_material": getattr(args, "bldg_material", None),
        "stories":      getattr(args, "stories", None),
    }
    for key, cli_val in CLI_FIELDS.items():
        if cli_val is not None:
            cfg[key] = cli_val
        elif key not in cfg:
            cfg[key] = GLOBAL_DEFAULTS[key]

    # Flood zone: CLI > preset. If absent it is auto-derived from the location
    # later (main), so it's no longer required up front.
    if args.flood_zone is not None:
        cfg["flood_zone"] = args.flood_zone

    # Location: default to county center if not provided. (When --address is used,
    # main() geocodes it and sets args.lat/args.lon before calling resolve_config.)
    cfg["lat"] = args.lat if args.lat is not None else SHELBY_LAT
    cfg["lon"] = args.lon if args.lon is not None else SHELBY_LON

    # Bonus flags: preset OR CLI (either can activate)
    for flag in BONUS_FLAGS:
        cfg[flag] = cfg.get(flag, False) or getattr(args, flag, False)

    # Validate: at most one flood elevation tier (argparse mutually_exclusive_group handles
    # CLI, but presets could theoretically set multiple — enforce here too).
    elev_flags = [f for f in ELEVATION_FLAGS if cfg.get(f)]
    if len(elev_flags) > 1:
        print(f"ERROR: Flood elevation flags are mutually exclusive; got: {elev_flags}",
              file=sys.stderr)
        sys.exit(1)

    return cfg


# ── Core simulation ────────────────────────────────────────────────────────────

def simulate(cfg: dict, local_compare: bool = True, structure: dict | None = None) -> dict:
    """Run the full EAL + BRM + bonus calculation. Returns a results dict.

    ``structure`` (from the resolved Location) carries the detected building type,
    material, and stories. For a detected multi-family building its material drives
    the construction resilience factors, and flood exposure is reduced for the
    representative unit by the building's height (only the lowest floors flood).

    ``local_compare`` controls the resilience *local grade* — a percentile rank
    against the bundled Shelby County dataset, which is only meaningful for a
    Shelby address. build_label_parts passes False off-Shelby so the rank isn't
    computed (and the CSV isn't read) for locations it doesn't describe.
    """
    r = {}

    # ── Hazard parameters from location ───────────────────────────────────────
    # Seismic: national USGS lookup (any US location); fall back to the New Madrid
    # model only if USGS and the bundled grid are both unavailable. Network is
    # off by default so simulate() stays offline-safe for callers that don't opt
    # in (tests, batch scripts); main() sets cfg["allow_network"] for the CLI.
    allow_network = cfg.get("allow_network", False)
    pga = get_pga(cfg["lat"], cfg["lon"], allow_network=allow_network)
    if pga is not None:
        pga_2pct, pga_10pct, pga_source = pga
    else:
        pga_2pct, pga_10pct, _ = compute_seismic_pga(cfg["lat"], cfg["lon"])
        pga_source = "New Madrid model (no USGS/grid)"

    tornado_rate, tornado_src       = compute_tornado_rate(cfg["lat"], cfg["lon"],
                                                            allow_network=allow_network)
    flood_risk = FLOOD_ZONE_TO_RISK[cfg["flood_zone"]]

    r.update(pga_2pct=pga_2pct, pga_10pct=pga_10pct,
             pga_source=pga_source,
             tornado_rate=tornado_rate, tornado_src=tornado_src, flood_risk=flood_risk)

    # ── BRM components ────────────────────────────────────────────────────────
    cef      = code_era_factor(cfg["year_built"])
    # Construction resilience factors. For a building detected as multi-family, its
    # actual material (NSI) drives resilience better than the (often defaulted)
    # single-family construction profile; wood/unknown multi-family keeps the
    # profile factors (a wood multi-family is no more wind-robust per unit).
    is_mf = bool(structure and structure.get("structure_type") == "multifamily")
    mat_res = _MATERIAL_RESILIENCE.get(structure.get("bldg_material")) if is_mf else None
    if mat_res:
        ctf, ctf_flood, fire_ctf = mat_res["ctf"], mat_res["flood"], mat_res["fire"]
        brm_floor = mat_res["floor"]
    else:
        ctf       = CONSTRUCTION_FACTOR[cfg["construction"]]        # tornado/seismic
        ctf_flood = FLOOD_CONSTRUCTION_FACTOR[cfg["construction"]]  # flood (ICF differs)
        fire_ctf  = FIRE_CONSTRUCTION_FACTOR[cfg["construction"]]
        brm_floor = BRM_FLOOR.get(cfg["construction"], 0.50)
    ff       = FOUNDATION_FACTOR[cfg["foundation"]]
    cf       = CONDITION_FACTOR[cfg["condition"]]

    flood_brm        = max(cef * ctf_flood * ff * cf, brm_floor)   # floor only, no ceiling
    wind_seismic_brm = max(cef * ctf * cf,            brm_floor)
    fire_brm         = max(fire_age_factor(cfg["year_built"]) * fire_ctf * cf, FIRE_BRM_FLOOR)

    # Floor-aware flood exposure: a stacked multi-family unit isn't all on the
    # ground floor, so only a fraction of the building's units actually flood.
    flood_floor = flood_floor_factor(structure.get("stories")) if is_mf else 1.0

    r.update(cef=cef, ctf=ctf, ctf_flood=ctf_flood, ff=ff, cf=cf,
             brm_floor=brm_floor, flood_floor=flood_floor,
             flood_brm=flood_brm, wind_seismic_brm=wind_seismic_brm, fire_brm=fire_brm)

    # ── Raw EAL rates (before BRM) ────────────────────────────────────────────
    flood_raw   = calc_flood_eal_raw(flood_risk)
    tornado_raw = calc_tornado_eal_raw(tornado_rate)
    seismic_raw = calc_seismic_eal_raw(pga_2pct, pga_10pct)
    # Fire = national-average structural/electrical fire baseline + the location's
    # FEMA NRI wildfire EAL rate (0.0 when the location wasn't resolved, keeping
    # simulate() offline-safe). build_label_parts sets cfg["wildfire_eal_base"]
    # from the resolved Location; tests/batch callers that omit it get the
    # structural baseline alone, as before.
    try:
        wildfire_base = float(cfg.get("wildfire_eal_base") or 0.0)
        if not math.isfinite(wildfire_base):
            wildfire_base = 0.0
    except (TypeError, ValueError):    # non-numeric override (JSON/CLI) → ignore
        wildfire_base = 0.0
    wildfire_base = max(0.0, wildfire_base)   # clamp once so the reported base matches use
    fire_raw    = FIRE_EAL_BASE + wildfire_base
    r["wildfire_eal_base"] = wildfire_base

    # ── BRM-adjusted EAL rates ────────────────────────────────────────────────
    flood_adj   = flood_raw   * flood_brm * flood_floor
    tornado_adj = tornado_raw * wind_seismic_brm
    seismic_adj = seismic_raw * wind_seismic_brm
    fire_adj    = fire_raw    * fire_brm

    # ── Hazard-specific bonus modifiers (existing) ────────────────────────────
    if cfg.get("leak_detection"):    flood_adj   *= BONUS_LEAK_DETECT
    if cfg.get("tornado_safe_room"): tornado_adj *= BONUS_SAFE_ROOM
    if cfg.get("seismic_retrofit"):  seismic_adj *= BONUS_SEISMIC_RET
    if cfg.get("fire_sprinklers"):   fire_adj    *= BONUS_FIRE_SPRINKLERS

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

    # ── General bonus modifiers (apply to flood/tornado/seismic EAL) ─────────
    # Fire is excluded: solar/generator/passive don't reduce ignition, and
    # sprinklers already apply a strong fire-specific reduction above.
    gen_mod = 1.0
    if cfg.get("solar"):           gen_mod *= BONUS_SOLAR
    if cfg.get("backup_generator"):gen_mod *= BONUS_GENERATOR
    if cfg.get("passive_house"):   gen_mod *= BONUS_PASSIVE
    if cfg.get("fire_sprinklers"): gen_mod *= BONUS_SPRINKLERS

    flood_adj   *= gen_mod
    tornado_adj *= gen_mod
    seismic_adj *= gen_mod

    r.update(flood_raw=flood_raw, tornado_raw=tornado_raw, seismic_raw=seismic_raw,
             fire_raw=fire_raw,
             flood_adj=flood_adj, tornado_adj=tornado_adj, seismic_adj=seismic_adj,
             fire_adj=fire_adj, gen_mod=gen_mod)

    total_eal = flood_adj + tornado_adj + seismic_adj + fire_adj
    r["total_eal"] = total_eal

    # ── Scores and national grade ─────────────────────────────────────────────
    r["flood_score"]   = eal_rate_to_score(flood_adj)
    r["tornado_score"] = eal_rate_to_score(tornado_adj)
    r["seismic_score"] = eal_rate_to_score(seismic_adj)
    r["fire_score"]    = eal_rate_to_score(fire_adj)
    r["total_score"]   = eal_rate_to_score(total_eal)
    r["national_grade"] = score_to_national_grade(r["total_score"])

    # ── Dollar-denominated EAL ────────────────────────────────────────────────
    # Per the representative-unit framing, the dollar loss is on ONE unit's value:
    # a total-building value is split across the units, an already-per-unit value
    # (county median / value-per-door) is used as-is — the same basis the
    # Infrastructure fiscal ratio uses, so a multi-unit label doesn't mix per-unit
    # and whole-building dollars.
    v = per_unit_home_value(cfg)
    r["flood_loss"]   = flood_adj   * v
    r["tornado_loss"] = tornado_adj * v
    r["seismic_loss"] = seismic_adj * v
    r["fire_loss"]    = fire_adj    * v
    r["total_loss"]   = total_eal   * v

    # ── Local comparison against scored dataset (Shelby pilot only) ───────────
    scores = _local_scores() if local_compare else None
    if scores is not None and len(scores):
        local_pct = compute_local_percentile(r["total_score"], scores)
        r["local_pct"]   = local_pct
        r["local_grade"] = percentile_to_local_grade(local_pct)
        r["n_parcels"]   = len(scores)
        r["score_min"]   = float(scores.min())
        r["score_max"]   = float(scores.max())
        r["score_median"] = float(np.median(scores))
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


def _box(inner: int = 64):
    """Return the (TOP, SEP, BOT, row) box-drawing pieces the fixed-width printers
    share, so the border strings and padding width live in one place."""
    top = "╔" + "═" * inner + "╗"
    sep = "╠" + "═" * inner + "╣"
    bot = "╚" + "═" * inner + "╝"

    def row(content: str = "") -> str:
        return f"║{content:<{inner}}║"

    return top, sep, bot, row


def print_scorecard(cfg: dict, r: dict) -> None:
    """Print a clean, fixed-width resilience scorecard to stdout."""
    TOP, SEP, BOT, row = _box()

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
    unit_label = "unit" if cfg.get("units", 1) == 1 else "units"
    print(row(f"    Units / size     : {cfg.get('units', 1)} {unit_label} × "
              f"{cfg.get('sqft', 2000):,.0f} sqft on {cfg.get('lot_acres', 0.25):.2f} ac"))
    print(row(f"    Flood zone       : {cfg['flood_zone']}  ({r['flood_risk']} risk)"))
    print(row(f"    Location         : {cfg['lat']:.4f}°N, {abs(cfg['lon']):.4f}°W"))
    print(row(f"    Appraised value  : ${cfg['value']:,.0f}"))
    if active_bonuses:
        bonus_str = ", ".join(BONUS_LABELS[b] for b in active_bonuses)
        # Wrap long bonus list across multiple lines
        words, lines = bonus_str.split(", "), []
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
    print(row(f"    PGA 2%/50yr      : {r['pga_2pct']:.3f} g  (2,475-yr return period)"))
    print(row(f"    PGA 10%/50yr     : {r['pga_10pct']:.3f} g  (475-yr return period)"))
    print(row(f"    Seismic source   : {r.get('pga_source', 'n/a')}"))
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
    print(row(f"    Flood BRM          : {r['flood_brm']:.3f}  (code×type×foundation×cond, floor {r['brm_floor']}, no ceiling)"))
    print(row(f"    Wind/Seismic BRM   : {r['wind_seismic_brm']:.3f}  (code×type×cond, floor {r['brm_floor']}, no ceiling)"))
    print(row(f"    Fire BRM           : {r['fire_brm']:.3f}  (wiring-era×type×cond, floor {FIRE_BRM_FLOOR})"))
    if active_bonuses:
        print(row(f"    General bonus mod  : {r['gen_mod']:.4f}  (flood/tornado/seismic)"))
        if cfg.get("fire_sprinklers"):
            print(row(f"    + {'Fire sprinklers':<30}: ×{BONUS_FIRE_SPRINKLERS} fire only"))
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
        ("Fire",    r["fire_raw"],    r["fire_adj"],    r["fire_score"]),
    ]:
        g = score_to_national_grade(score)
        row_str = (f"  {label:<9} {raw*100:>8.4f}% {adj*100:>8.4f}%"
                   f" {score:>7.1f} {g:>6}")
        print(row(f"    {row_str}"))
    print(row(f"    {'─'*52}"))
    total_raw = r["flood_raw"] + r["tornado_raw"] + r["seismic_raw"] + r["fire_raw"]
    total_row = (f"  {'TOTAL':<9} {total_raw*100:>8.4f}% {r['total_eal']*100:>8.4f}%"
                 f" {r['total_score']:>7.1f} {r['national_grade']:>6}")
    print(row(f"    {total_row}"))
    print(SEP)

    # ── Dollar EAL ────────────────────────────────────────────────────────────
    print(section("EXPECTED ANNUAL LOSS  (appraised value × adj EAL rate)"))
    print(row(f"    Flood            : ${r['flood_loss']:>10,.0f} / year"))
    print(row(f"    Tornado          : ${r['tornado_loss']:>10,.0f} / year"))
    print(row(f"    Seismic          : ${r['seismic_loss']:>10,.0f} / year"))
    print(row(f"    Fire             : ${r['fire_loss']:>10,.0f} / year"))
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


# ── Full nutrition label (all dimensions) ───────────────────────────────────────

# The pilot county. Seismic (USGS), tornado (SPC), energy rates (EIA), grid factor
# (eGRID), and infrastructure cost/tax are all resolved nationally per address; this
# FIPS only anchors the bundled resilience reference dataset and the cost-model
# numeraire, and picks the local-comparison branch.
CALIBRATED_COUNTY_FIPS = "47157"


def _approx_caveats(location, cfg: dict | None = None) -> list[str]:
    """Caveats for dimensions that aren't locally calibrated.

    Seismic (USGS) and tornado (SPC) are nationwide. Infrastructure is calibrated
    to each county's local-government spending (Census of Governments) where the
    county is in the crosswalk, a national-average cost model when the county isn't
    in it, and the Memphis pilot baseline if the crosswalk isn't bundled at all. The
    Environmental grid factor is the county's eGRID2022 subregion rate when the
    county maps, and the US-average factor otherwise — flagged off the actually
    resolved subregion so the fallback is never reported incorrectly.

    A multi-unit building (NSI-detected, or declared by the caller's unit count)
    adds a dense-housing caveat. Energy, Infrastructure, Environmental, and the
    income-based value-per-door always reflect it. Resilience and Durability need
    the building's material and height: present for a detected building or when the
    caller enters them, otherwise those two stay on single-family assumptions and the
    caveat prompts for the missing inputs. ``cfg`` carries the caller's entered
    ``units``/``bldg_material``/``stories`` (merged with detection via
    ``effective_structure``)."""
    from housing_label.data.egrid import US_AVG_LABEL

    caveats: list[str] = []
    struct = effective_structure(cfg or {}, location)

    # Dense-housing caveat: fires for any multi-family building (detected or entered).
    # Energy/Infrastructure/Environmental and the value-per-door value always apply;
    # Resilience/Durability apply only with the building's material and height.
    if struct["is_multifamily"]:
        detected_mf = getattr(location, "structure_type", None) == "multifamily"
        has_material = bool(struct.get("bldg_material"))
        has_stories = bool(struct.get("stories"))
        detail = ""
        if detected_mf:
            # Report NSI's *detected* unit count here (not a caller override) so the
            # "detected from the National Structure Inventory" attribution stays honest.
            # When the count is only estimated (NSI mislabeled the complex and we
            # recognized it from the building cluster), say so and prompt to confirm.
            det_n = getattr(location, "num_units", None)
            estimated = getattr(location, "units_confidence", None) == "estimated"
            unit_str = ""
            if det_n and det_n > 1:
                unit_str = (f" (~{det_n} units, estimated — enter the actual count to refine"
                            " Energy & Infrastructure)" if estimated else f" (~{det_n} units)")
            detail = (" This address was recognized as a multi-unit building" + unit_str
                      + ", from the National Structure Inventory.")
        # The material/height-driven Resilience & Durability adjustments only run when
        # we actually have both — for a detected building NSI may give an unusable
        # material ("other") or no stories, so gate the "full" caveat on the values
        # being present, not merely on detection.
        if has_material and has_stories:
            caveats.append(
                "Multi-unit building: scored in its building context — Energy credits "
                "its shared walls, Resilience its material and height, Durability its "
                "shared structural shell, Infrastructure its unit density, and "
                "Environmental drops the private-yard water use. The per-unit value is "
                "an income-based value-per-door estimate (local rent capitalized by the "
                "income / cap-rate method), a neighborhood-average approximation rather "
                "than an appraisal, so its dollar figures are approximate for an "
                "apartment or condo." + detail
            )
        else:
            missing = ([] if has_material else ["construction material"]) + \
                      ([] if has_stories else ["number of stories"])
            caveats.append(
                "Multi-unit building: Energy (shared walls), Infrastructure (per-unit "
                "density), Environmental (no private-yard water), and the per-unit "
                "value-per-door estimate reflect it, but Resilience and Durability still "
                "use single-family assumptions — add the building's "
                + " and ".join(missing) + " to score those too. Figures are approximate "
                "for an apartment, townhome, or condo." + detail
            )

    if location is None:
        caveats.append(
            "Location could not be resolved: Infrastructure Burden and the "
            "Environmental grid factor fall back to the pilot default calibration."
        )
        return caveats

    fips = getattr(location, "county_fips", None)
    if fips is None:
        caveats.append(
            "County could not be resolved: Infrastructure Burden may be approximate "
            "(it falls back to the pilot cost model)."
        )
    elif fips != CALIBRATED_COUNTY_FIPS:
        from housing_label.data.govfinance import govfinance_for_county
        gov = govfinance_for_county(fips)
        if gov["resolved"] == "county":
            from housing_label.data.propertytax import property_tax_for_county
            tax = property_tax_for_county(fips)
            revenue = ("its municipal (non-school) effective property-tax rate (Census ACS)"
                       if tax["resolved"] == "county"
                       else "a national-average property-tax rate (this county isn't in "
                            "the ACS crosswalk)")
            caveats.append(
                "Infrastructure Burden is calibrated to this county's local-government "
                "spending (Census of Governments, cost side) and " + revenue + " (revenue "
                "side, with the school-district share netted out to match the non-school "
                "cost model), layered on a density cost model — a county-level estimate, "
                "not parcel-level."
            )
        elif gov["resolved"] == "national":
            caveats.append(
                "Infrastructure Burden uses a national-average cost model (this county "
                "is not in the local-finance crosswalk) — treat it as an estimate."
            )
        else:  # "none" — the local-finance crosswalk isn't bundled
            caveats.append(
                "Infrastructure Burden falls back to the pilot cost model (the "
                "local-finance crosswalk is unavailable) — treat it as an estimate."
            )

    # Environmental: flag whenever it used the US-average grid factor instead of a
    # real eGRID subregion — i.e. the county was unresolved or not in the crosswalk.
    egrid_sub = getattr(location, "egrid_subregion", None)
    if egrid_sub is None or egrid_sub == US_AVG_LABEL:
        caveats.append(
            "Environmental uses the US-average grid factor (the location's eGRID "
            "subregion could not be determined)."
        )
    return caveats


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word-wrap to `width` columns."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if len(t) > width and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def print_label(cfg: dict, label: dict) -> None:
    """Print the full multi-dimension nutrition label below the resilience card."""
    TOP, SEP, BOT, row = _box()

    print(TOP)
    print(row("  FULL NUTRITION LABEL — ALL DIMENSIONS"))
    print(row(f"  {label['n_scored']} of {len(label['dimensions'])} dimensions scored (location data optional)"))
    loc = label.get("location")
    if loc is not None:
        place = (loc.label or "")[:34]
        cz = loc.climate_zone or "—"
        grid = loc.egrid_factor if loc.egrid_factor is not None else "—"
        print(row(f"  Location: {place}"))
        print(row(f"    IECC zone {cz}  ·  grid {grid} kgCO2e/kWh  ·  "
                  f"tract {label.get('census_tract') or '—'}"))
    print(SEP)
    print(row(f"  {'Dimension':<24}{'Score':>8}  {'Grade':<6}{'Profile':<20}"))
    print(row(f"  {'─'*58}"))
    for d in label["dimensions"]:
        if d["score"] is None:
            bar = "·" * 12
            score_str = "   N/A"
        else:
            filled = int(round(d["score"] / 100 * 12))
            bar = "█" * filled + "░" * (12 - filled)
            score_str = f"{d['score']:>6.1f}"
        print(row(f"  {d['label']:<24}{score_str}  {d['national_grade']:<6}{bar:<20}"))
    print(row(f"  {'─'*58}"))

    comp = label["composite_score"]
    comp_str = "N/A" if comp is None else f"{comp:.1f} / 100"
    print(row(f"  {'COMPOSITE':<24}{comp_str:>8}  {label['composite_national_grade']:<6}"))
    print(SEP)

    # Side metrics from the construction-driven models.
    m = label["metrics"]
    print(row("  KEY METRICS"))
    if m.get("eui_kbtu_sqft_yr") is not None:
        print(row(f"    Energy use intensity : {m['eui_kbtu_sqft_yr']:.1f} kBTU/sqft/yr"))
    if m.get("est_monthly_energy_cost") is not None:
        print(row(f"    Est. monthly energy  : ${m['est_monthly_energy_cost']:,.0f}/mo (per unit)"))
    if m.get("fiscal_ratio") is not None:
        print(row(f"    Fiscal ratio         : {m['fiscal_ratio']:.2f} "
                  f"(tax ÷ infra cost, per unit)"))

    # Explain any unscored location dimensions.
    unscored = [d["label"] for d in label["dimensions"] if d["score"] is None]
    if unscored:
        print(row(f"    {'─'*54}"))
        print(row("  Location dimensions not scored (excluded from composite):"))
        for d in label["dimensions"]:
            if d["score"] is None:
                note = label["location_notes"].get(d["key"], "unavailable")
                print(row(f"    • {d['label']:<22}: {note}"))

    # Honest caveat: some dimensions are not yet location-generalized.
    caveats = _approx_caveats(label.get("location"), cfg)
    if caveats:
        print(row(f"    {'─'*54}"))
        print(row("  ⚠ Approximate outside Shelby County:"))
        for c in caveats:
            for line in _wrap(c, 58):
                print(row(f"    {line}"))
    print(BOT)
    print()


def cost_flows(r: dict, label: dict) -> dict:
    """Annual dollar flows the lifetime-cost strip discounts: expected annual
    loss and annual energy cost (monthly × 12). See
    research/lifetime-cost-research.md."""
    out = {"expectedAnnualLoss": round(r["total_loss"])}
    monthly = (label.get("metrics") or {}).get("est_monthly_energy_cost")
    if monthly is not None:
        out["annualEnergyCost"] = round(monthly * 12)
    return out


def _finite(v):
    """Coerce to float, or None if missing / non-finite (NaN, ±inf). Metrics can
    originate from pandas/numpy, so a NaN must read as "unavailable" (row dropped),
    not format into a user-visible ``$nan``."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _money(v, suffix: str = "") -> str | None:
    """Format a dollar figure like ``$1,234`` (+ optional ``/yr`` etc.)."""
    v = _finite(v)
    return None if v is None else f"${v:,.0f}{suffix}"


def dimension_details(cfg: dict, r: dict, label: dict) -> dict:
    """Per-dimension "what drove this score" detail: for each dimension, a list of
    pre-formatted ``{label, value}`` rows built from the *real* model outputs
    (never reconstructed on the front-end), keyed by dimension key.

    These render inside each expandable label row so a reader can see the actual
    numbers behind the grade. Values are formatted here — one source of truth — so
    the client only prints them. Rows whose value is unavailable are dropped.
    """
    m = label.get("metrics") or {}
    loc_notes = label.get("location_notes") or {}
    scores = {d["key"]: d.get("score") for d in label.get("dimensions", [])}

    def rows(*pairs) -> list:
        return [{"label": lbl, "value": val} for lbl, val in pairs if val is not None]

    def qty(v, unit: str) -> str | None:
        v = _finite(v)
        return None if v is None else f"{v:,.0f} {unit}"

    details: dict = {}

    # Resilience — expected annual dollar loss by peril, on one unit's value (the
    # same per-unit basis the dollar EAL uses elsewhere).
    details["resilience"] = rows(
        ("Expected annual loss", _money(r.get("total_loss"), "/yr")),
        ("Flood", _money(r.get("flood_loss"), "/yr")),
        ("Wind / tornado", _money(r.get("tornado_loss"), "/yr")),
        ("Earthquake", _money(r.get("seismic_loss"), "/yr")),
        ("Wildfire", _money(r.get("fire_loss"), "/yr")),
        ("On a home value of", _money(per_unit_home_value(cfg))),
    )

    # Energy — modeled energy-use intensity and the resulting cost.
    eui = _finite(m.get("eui_kbtu_sqft_yr"))
    details["energy"] = rows(
        ("Energy use intensity", None if eui is None else f"{eui:.1f} kBTU/sqft·yr"),
        ("Est. energy cost", _money(m.get("est_monthly_energy_cost"), "/mo")),
    )

    # Durability — component-lifespan drivers.
    past = _finite(m.get("durability_components_past_life"))
    rem = _finite(m.get("durability_remaining_life_pct"))
    details["durability"] = rows(
        ("Structural material", m.get("durability_material_class")),
        ("Remaining service life", None if rem is None else f"{rem:.0f}%"),
        ("Components past service life", None if past is None else str(int(past))),
        ("Condition", m.get("durability_condition")),
    )

    # Environmental — annual carbon legs + water.
    details["environmental"] = rows(
        ("Total carbon footprint", qty(m.get("env_total_co2e_kg_yr"), "kg CO₂e/yr")),
        ("— operational (energy)", qty(m.get("env_operational_co2e_kg_yr"), "kg CO₂e/yr")),
        ("— embodied (materials)", qty(m.get("env_embodied_co2e_kg_yr"), "kg CO₂e/yr")),
        ("Water use", qty(m.get("env_water_gal_yr"), "gal/yr")),
    )

    # Infrastructure — the fiscal ratio and the two sides that make it (per unit).
    fr = _finite(m.get("fiscal_ratio"))
    details["infrastructure"] = rows(
        ("Fiscal ratio (tax ÷ cost to serve)", None if fr is None else f"{fr:.2f}"),
        ("Est. property tax (per unit)", _money(m.get("est_property_tax"), "/yr")),
        ("Est. public cost to serve (per unit)", _money(m.get("est_annual_infra_cost"), "/yr")),
    )

    # Location dimensions — the score is a within-county percentile index; show it
    # with its provenance, or explain why it isn't scored at this location.
    def location_rows(key: str, index_label: str, source: str) -> list:
        # Show the score to 1 decimal — matching the row summary and the precision
        # dimensions.py already stored — and guard non-finite as unavailable.
        s, note = _finite(scores.get(key)), loc_notes.get(key)
        if s is not None:
            return rows((index_label, f"{s:.1f} / 100"), ("Source", note or source))
        return rows(("Status", "Not scored here" + (f" — {note}" if note else "")))

    details["health"] = location_rows("health", "Neighborhood health index (national percentile)", "CDC PLACES")
    details["socioeconomic"] = location_rows("socioeconomic", "Socioeconomic index (national percentile)", "Census ACS")
    details["walkability"] = location_rows(
        "walkability", "Walkability (national index)", "EPA National Walkability Index")

    # Climate — projection score, the mid-century warming band, and provenance.
    cs = _finite(scores.get("climate"))
    if cs is not None:
        details["climate"] = rows(
            ("Projection score", f"{cs:.1f} / 100"),
            ("Mid-century band (SSP2-4.5 – 5-8.5)",
             m.get("Climate band (SSP2-4.5–5-8.5, mid-century)")),
            ("Source", loc_notes.get("climate") or "CMIP6-LOCA2"),
        )
    else:
        details["climate"] = location_rows("climate", "Projection score", "CMIP6-LOCA2")

    return details


def label_payload(cfg: dict, r: dict, label: dict, include_building: bool = True) -> dict:
    """Build the full nutrition-label payload (JSON-serializable) shared by the
    CLI's --json output and the HTTP API.

    ``include_building=False`` omits the per-field construction-profile provenance
    block — used by the /presets grid, which scores fixed hypothetical profiles and
    has no "detected from the address" panel to feed."""
    payload = {
        "house": {
            "year_built": cfg["year_built"],
            "construction": cfg["construction"],
            "foundation": cfg["foundation"],
            "condition": cfg["condition"],
            "units": cfg.get("units", 1),
            "sqft": cfg.get("sqft", 2000),
            "lot_acres": cfg.get("lot_acres", 0.25),
            "flood_zone": cfg["flood_zone"],
            "value": cfg["value"],
            # How the home value was determined: "county median (ACS)" when
            # auto-filled, else None (taken as entered / from the profile).
            "value_source": cfg.get("value_source"),
            "lat": cfg["lat"],
            "lon": cfg["lon"],
        },
        "dimensions": label["dimensions"],
        # Per-dimension "what drove this score" detail rows (real model numbers),
        # keyed by dimension key — rendered inside each expandable label row.
        "details": dimension_details(cfg, r, label),
        "composite_score": label["composite_score"],
        "composite_national_grade": label["composite_national_grade"],
        "n_scored": label["n_scored"],
        "metrics": label["metrics"],
        "census_tract": label["census_tract"],
        "location_notes": label["location_notes"],
        # Data-quality confidence channel (research/uncertainty-confidence-research.md).
        "confidence": confidence_for_label(label),
        "bands": bands_for_label(label),
        "confidence_notes": dict(CONFIDENCE_NOTES),  # copy — never hand out the shared constant
        "confidence_legend": CONFIDENCE_LEGEND,
        # Annual $ flows for the lifetime-cost strip (delta vs. a baseline is
        # added by the API, which scores a typical comparable at this location).
        "cost": cost_flows(r, label),
        "total_loss": round(r["total_loss"], 2),
        "fire_loss": round(r["fire_loss"], 2),
    }
    # Per-field construction-profile provenance (value + estimated/confirmed/assumed
    # + source) for the "Refine building details" panel — present for address/point
    # scoring, omitted for the /presets grid (include_building=False).
    if include_building and label.get("building"):
        payload["building"] = label.get("building")
    loc = label.get("location")
    if loc is not None:
        payload["location"] = {
            "label": loc.label,
            "county_fips": loc.county_fips,
            "county_name": loc.county_name,
            "climate_zone": loc.climate_zone,
            "egrid_subregion": loc.egrid_subregion,
            "egrid_factor": loc.egrid_factor,
            "in_urban_area": loc.in_urban_area,
            "notes": loc.notes,
        }
        # Detected building context (USACE NSI): what kind of building is here.
        # Report the *effective* building context actually used for scoring — the
        # caller's entered units/material/stories merged over the NSI detection — so
        # the payload matches how the dimensions were computed. ``source`` names where
        # the multi-family classification came from (NSI detection vs. entered count).
        est = effective_structure(cfg, loc)
        if getattr(loc, "structure_source", None) or est["is_multifamily"]:
            detected_mf = getattr(loc, "structure_type", None) == "multifamily"
            source = (getattr(loc, "structure_source", None) if detected_mf
                      else "entered" if est["is_multifamily"]
                      else getattr(loc, "structure_source", None))
            # Units are "estimated" only when NSI's heuristic count stands (no caller
            # override); an entered count is authoritative.
            entered_units = int(cfg.get("units") or 1) > 1
            units_conf = (None if entered_units
                          else getattr(loc, "units_confidence", None))
            payload["structure"] = {
                "structure_type": est["structure_type"],
                "num_units": est["num_units"],
                "stories": est["stories"],
                "bldg_material": est["bldg_material"],
                "source": source,
                # ``detection`` names the NSI method behind the building-type
                # classification, so it reflects the *original* NSI signal and is
                # emitted only when the classification came from NSI (source == "NSI").
                # A caller units override changes the count, not the detection method,
                # so it reads loc.units_confidence rather than the override-nulled one.
                "detection": (("nsi-cluster"
                               if getattr(loc, "units_confidence", None) == "estimated"
                               else "nsi") if source == "NSI" else None),
                "units_confidence": units_conf,
            }
        # Wildfire hazard behind the fire peril (FEMA NRI; rating + EAL rate).
        wf = getattr(loc, "wildfire", None)
        if wf is not None:
            payload["wildfire"] = {
                "risk_rating": wf.get("risk_rating"),
                "eal_rate": wf.get("eal_rate"),
                "geo_level": wf.get("geo_level"),
            }
    payload["caveats"] = _approx_caveats(loc, cfg)
    return payload


def emit_json(cfg: dict, r: dict, label: dict) -> None:
    """Print the full nutrition label (all dimensions) as JSON to stdout."""
    print(json.dumps(label_payload(cfg, r, label), indent=2))


# ── Shared orchestration (used by the CLI and the HTTP API) ──────────────────────

# Editable construction-profile fields surfaced on the label's "Refine building
# details" panel, each with provenance (confirmed / estimated / assumed).
_EDITABLE_FIELDS = ["year_built", "construction", "foundation", "condition",
                    "sqft", "units", "stories", "lot_acres", "value", "bldg_material"]


def _nsi_per_unit_sqft(location, units: int | None = None) -> float | None:
    """Auto-filled living area per *dwelling unit*.

    A genuine NSI multi-unit record (``units_confidence == "detected"``) reports the
    WHOLE building's floor area, so it is split across the unit count to match the
    label's per-unit sqft convention (``SFLA`` per unit) — this keeps the energy
    cost, EUI, and the lifetime-cost comparison per apartment rather than scoring the
    entire 100k+ sqft building against one typical house. Single-family sqft, and the
    cluster heuristic's sqft (already one mislabeled house), are returned as-is.

    ``units`` is the *effective* dwelling-unit count so the divisor matches the rest
    of the per-unit math: a caller's explicit override wins, falling back to the
    NSI-detected count when it isn't supplied."""
    sqft = getattr(location, "sqft", None)
    if sqft is None:
        return None
    n = units if (units and units > 1) else getattr(location, "num_units", None)
    if (getattr(location, "units_confidence", None) == "detected"
            and getattr(location, "structure_type", None) == "multifamily"
            and n and n > 1):
        return round(float(sqft) / n, 1)
    return sqft


def _autofill_construction_from_nsi(cfg: dict, explicit: set, location,
                                    units: int | None = None) -> dict:
    """Fill year_built / sqft / construction / foundation from the NSI-detected
    Location when the user left them unset. Returns ``{field: (source, confidence)}``
    for the fields that were auto-filled, so the label can tag them as estimates.

    year_built is a census-area MEDIAN and construction is a coarse 5-class guess,
    so both are always low-confidence estimates; sqft/foundation ride NSI's
    per-structure provenance (parcel-observed → higher confidence than modeled).
    For a detected multi-unit building the sqft is stored per dwelling unit, split by
    the effective ``units`` count (see ``_nsi_per_unit_sqft``)."""
    filled: dict = {}
    if location is None:
        return filled
    observed = getattr(location, "structure_attr_source", None) == "P"
    plan = [
        ("year_built",   getattr(location, "year_built", None), "NSI · neighborhood median (estimated)", "low"),
        ("sqft",         _nsi_per_unit_sqft(location, units),   "NSI · structure record", "high" if observed else "moderate"),
        ("construction", getattr(location, "construction", None), "NSI · material class (coarse estimate)", "low"),
        ("foundation",   getattr(location, "foundation", None), "NSI · structure record", "moderate" if observed else "low"),
    ]
    for field, val, source, conf in plan:
        if field not in explicit and val is not None:
            cfg[field] = val
            filled[field] = (source, conf)
    return filled


def _building_block(cfg: dict, struct: dict, explicit: set, autofilled: dict,
                    location) -> dict:
    """Per-field provenance for the construction profile — what the UI renders as a
    prefilled, editable panel. Each field: ``{value, status, source, confidence}``
    where status is ``confirmed`` (user-entered), ``estimated`` (derived from public
    data), or ``assumed`` (a typical default we couldn't derive)."""
    stories = (struct.get("stories") if struct.get("stories") is not None
               else cfg.get("stories"))
    material = struct.get("bldg_material") or cfg.get("bldg_material")
    # Units: show the *effective* count actually used for scoring (NSI-detected
    # multi-family flows through struct, not cfg — cfg stays the default 1), so a
    # detected 30-unit building doesn't display "1" while tagged estimated.
    units = struct.get("num_units") if struct.get("num_units") is not None else cfg.get("units")
    vals = {
        "year_built": cfg.get("year_built"), "construction": cfg.get("construction"),
        "foundation": cfg.get("foundation"), "condition": cfg.get("condition"),
        "sqft": cfg.get("sqft"), "units": units, "stories": stories,
        "lot_acres": cfg.get("lot_acres"), "value": cfg.get("value"),
        "bldg_material": material,
    }
    # A supplied units of 1 is not a real override (1 is the default), so it must
    # not tag the field "confirmed" — especially when NSI detected a multi-unit
    # building and the *displayed* value is the detected count, not 1.
    eff_explicit = set(explicit)
    try:
        if "units" in eff_explicit and int(cfg.get("units") or 1) <= 1:
            eff_explicit.discard("units")
    except (TypeError, ValueError):
        pass

    # Fields NSI detects even when a preset is chosen (units/stories/material feed
    # the multifamily path); mark them estimated when detected and not user-set.
    detected: dict = {}
    if location is not None:
        if getattr(location, "num_units", None) and location.num_units != 1 \
                and "units" not in eff_explicit:
            detected["units"] = ("NSI · structure record", "moderate")
        if struct.get("stories") is not None and "stories" not in eff_explicit:
            detected["stories"] = ("NSI · structure record", "moderate")
        if struct.get("bldg_material") and "bldg_material" not in eff_explicit:
            detected["bldg_material"] = ("NSI · structure record", "moderate")

    out: dict = {}
    for field, value in vals.items():
        if value is None:
            continue
        if field in eff_explicit:
            out[field] = {"value": value, "status": "confirmed",
                          "source": "you entered", "confidence": "high"}
        elif field in autofilled or field in detected:
            source, conf = autofilled.get(field) or detected[field]
            out[field] = {"value": value, "status": "estimated",
                          "source": source, "confidence": conf}
        else:
            out[field] = {"value": value, "status": "assumed",
                          "source": "typical default", "confidence": "low"}
    return out


def build_label_parts(*, address: str | None = None,
                      lat: float | None = None, lon: float | None = None,
                      preset: str | None = None, flood_zone: str | None = None,
                      allow_network: bool = True, overrides: dict | None = None,
                      upgrades: list[str] | None = None, location=None,
                      **fields) -> tuple[dict, dict, dict]:
    """Resolve a location, build the house config, and run the full simulation.

    Returns (cfg, r, label). ``fields`` may carry house overrides (year_built,
    construction, foundation, condition, value, units, sqft, lot_acres) and
    ``upgrades`` is a list of resilience-upgrade flag names (see BONUS_FLAGS).
    Mirrors the CLI flow so both share one code path.
    """
    from argparse import Namespace
    from housing_label.simulate.location import resolve_location

    # A caller may pass a pre-resolved location to reuse (skips geocoding — used
    # when scoring a baseline comparable at the same place for the cost strip).
    if location is not None:
        lat, lon = location.lat, location.lon
    elif address:
        try:
            location = resolve_location(address=address, allow_network=allow_network)
        except Exception as exc:  # noqa: BLE001 — surface as a clean validation error
            raise ValueError(f"Could not geocode address {address!r}: {exc}") from exc
        lat, lon = location.lat, location.lon
    else:
        lat = lat if lat is not None else SHELBY_LAT
        lon = lon if lon is not None else SHELBY_LON
        try:
            location = resolve_location(lat=lat, lon=lon, allow_network=allow_network)
        except Exception:  # noqa: BLE001
            location = None

    ns = Namespace(
        preset=preset, lat=lat, lon=lon, flood_zone=flood_zone,
        year_built=fields.get("year_built"), construction=fields.get("construction"),
        foundation=fields.get("foundation"), condition=fields.get("condition"),
        value=fields.get("value"), units=fields.get("units"),
        sqft=fields.get("sqft"), lot_acres=fields.get("lot_acres"),
        bldg_material=fields.get("bldg_material"), stories=fields.get("stories"),
    )
    for flag in BONUS_FLAGS:            # resilience upgrades → Namespace booleans
        setattr(ns, flag, flag in (upgrades or []))
    cfg = resolve_config(ns)
    cfg["allow_network"] = allow_network
    if "flood_zone" not in cfg:
        cfg["flood_zone"] = _auto_flood_zone(cfg["lat"], cfg["lon"], allow_network)

    # Location-based wildfire EAL feeds the fire peril (structural baseline +
    # wildfire), resolved offline from the bundled FEMA NRI crosswalk via the
    # Location's tract/county. A resolved Location always carries a wildfire dict:
    # the real tract/county rate when mapped, else the national-average fallback
    # (resolved=False). Only when no Location resolved at all (e.g. offline with
    # no geocode) is wildfire left unset, so simulate() uses 0.0.
    if location is not None and getattr(location, "wildfire", None):
        cfg["wildfire_eal_base"] = location.wildfire.get("eal_rate") or 0.0

    # Auto-fill the home value when the caller didn't specify one, so the
    # Infrastructure fiscal ratio (and dollar EALs) reflect the local market instead
    # of the construction profile's flat default. An explicit value (CLI --value /
    # API value=) always wins. For a multi-family building — detected by NSI OR
    # declared by the caller's unit count — the single-family owner-occupied median
    # is wrong (a rental building carries no such value), so use the income-based
    # value-per-door estimate (rent-derived NOI ÷ cap rate); other addresses keep the
    # single-family county median.
    struct = effective_structure(cfg, location)
    explicit = {f for f in _EDITABLE_FIELDS if fields.get(f) is not None}
    autofilled: dict = {}
    if location is not None and fields.get("value") is None:
        county_fips = getattr(location, "county_fips", None)
        if struct["is_multifamily"]:
            from housing_label.data.multifamily_value import value_per_door_for_county
            cfg["value"] = value_per_door_for_county(county_fips)["value_per_door"]
            cfg["value_source"] = VALUE_PER_DOOR_SOURCE
        else:
            from housing_label.data.propertytax import median_home_value_for_county
            median_value = median_home_value_for_county(county_fips)
            if median_value:
                cfg["value"] = median_value
                cfg["value_source"] = AUTOFILL_VALUE_SOURCE
    if cfg.get("value_source"):
        autofilled["value"] = (cfg["value_source"], "low")   # a county-area estimate

    # Auto-fill the rest of the construction profile from the NSI-detected building
    # when the caller is scoring a real address (no hypothetical preset) and didn't
    # supply the field — so "type an address" needs no manual entry. Each stays a
    # tagged, editable estimate. A preset means the user wants a hypothetical build,
    # so its values win (no NSI override).
    if preset is None:
        autofilled.update(_autofill_construction_from_nsi(
            cfg, explicit, location, struct.get("num_units")))
    building = _building_block(cfg, struct, explicit, autofilled, location)

    # The resilience local grade ranks against the bundled Shelby dataset, so it's
    # only meaningful for a Shelby address; compute it only then (N/A elsewhere).
    is_shelby = getattr(location, "county_fips", None) == CALIBRATED_COUNTY_FIPS
    structure = {
        "structure_type": struct["structure_type"],
        "num_units": struct["num_units"],
        "stories": struct["stories"],
        "bldg_material": struct["bldg_material"],
    }
    r = simulate(cfg, local_compare=is_shelby, structure=structure)
    label = simulate_all_dimensions(
        cfg, r["total_score"], location=location,
        allow_network=allow_network, overrides=overrides,
    )
    label["building"] = building     # per-field provenance for the "Refine details" panel
    return cfg, r, label


# ── Per-parcel density comparison ────────────────────────────────────────────────
# "What would density look like on this parcel?" — hold the location and the lot
# fixed and vary the number of dwelling units (a duplex, triplex, quadplex on the
# same land). The per-unit value is the comparison's invariant: it stays ~constant
# while total value scales with units. This surfaces the "density dividend" — the
# same land and municipal services get shared across more homes, so the per-unit
# cost-to-serve falls and the Infrastructure Burden fiscal ratio improves.

DENSITY_UNIT_COUNTS = (1, 2, 3, 4)

# Human names for small multi-unit buildings; larger counts fall back to "N-plex".
_DENSITY_NAMES = {1: "Single-family", 2: "Duplex", 3: "Triplex", 4: "Quadplex"}


def _density_unit_name(units: int) -> str:
    return _DENSITY_NAMES.get(units, f"{units}-plex")


def _density_scenario_summary(units: int, cfg: dict, label: dict) -> dict:
    """Compact per-scenario record for a density comparison (JSON-serializable)."""
    by_key = {d["key"]: d for d in label["dimensions"]}
    infra = by_key.get("infrastructure", {})
    energy = by_key.get("energy", {})
    metrics = label["metrics"]
    lot = cfg.get("lot_acres", 0.25)
    value = cfg["value"]

    # Fiscal productivity per ACRE (the "value per acre" lens): the infra metrics
    # are per dwelling unit, so total-per-lot ÷ lot = per-unit ÷ per_unit_acres.
    # This surfaces the infill dividend the per-unit ratio hides — denser forms
    # generate far more property-tax revenue on the same land and shared infra.
    pu_acres = lot / units if lot and units else None
    pu_tax = metrics.get("est_property_tax")
    pu_cost = metrics.get("est_annual_infra_cost")
    revenue_per_acre = (round(float(pu_tax) / pu_acres, 2)
                        if pu_tax is not None and pu_acres else None)
    cost_per_acre = (round(float(pu_cost) / pu_acres, 2)
                     if pu_cost is not None and pu_acres else None)
    net_per_acre = (round(revenue_per_acre - cost_per_acre, 2)
                    if revenue_per_acre is not None and cost_per_acre is not None else None)

    return {
        "units": units,
        "name": _density_unit_name(units),
        "value": round(float(value), 2),
        "per_unit_value": round(float(value) / units, 2),
        "lot_acres": lot,
        "per_unit_acres": round(lot / units, 4),
        "composite_score": label["composite_score"],
        "composite_national_grade": label["composite_national_grade"],
        "fiscal_ratio": metrics.get("fiscal_ratio"),
        "infrastructure_score": infra.get("score"),
        "infrastructure_grade": infra.get("national_grade"),
        "energy_score": energy.get("score"),
        "eui_kbtu_sqft_yr": metrics.get("eui_kbtu_sqft_yr"),
        "est_monthly_energy_cost": metrics.get("est_monthly_energy_cost"),
        # Fiscal productivity per acre ($/acre/yr).
        "revenue_per_acre": revenue_per_acre,
        "cost_per_acre": cost_per_acre,
        "net_fiscal_per_acre": net_per_acre,
        "dimensions": label["dimensions"],
    }


def density_comparison(*, address: str | None = None,
                       lat: float | None = None, lon: float | None = None,
                       preset: str | None = None, flood_zone: str | None = None,
                       allow_network: bool = True, overrides: dict | None = None,
                       upgrades: list[str] | None = None,
                       unit_counts=None, per_unit_value: float | None = None,
                       **fields) -> dict:
    """Compare what a parcel scores at different densities (fixed lot, vary units).

    Holds the location and lot size fixed and re-scores the parcel for each unit
    count in ``unit_counts`` (default 1→4). The per-unit value stays constant, so
    the total appraised value scales with the number of units. Returns a dict of
    per-scenario summaries plus the headline "density dividend" (how the fiscal
    ratio / Infrastructure grade move from the fewest to the most units).

    Per-unit value precedence: explicit ``per_unit_value`` > an explicit ``value``
    in ``fields`` (treated as the per-unit value) > the county median home value
    (ACS auto-fill), established from a single-unit baseline run.
    """
    def _coerce_unit(n):
        try:
            iv = int(n)
        except (TypeError, ValueError):
            raise ValueError(f"unit_counts must contain positive integers, got {n!r}") from None
        if isinstance(n, float) and iv != n:      # don't silently truncate 2.9 → 2
            raise ValueError(f"unit_counts must contain whole numbers, got {n!r}")
        return iv

    counts = sorted({c for c in map(_coerce_unit, unit_counts or DENSITY_UNIT_COUNTS) if c >= 1})
    if not counts:
        raise ValueError("unit_counts must contain at least one positive integer")

    base_value = per_unit_value if per_unit_value is not None else fields.get("value")
    cache: dict[int, tuple] = {}

    def _run(n: int, val: float | None) -> tuple:
        f = dict(fields)
        f["units"] = n
        if val is not None:
            f["value"] = round(float(val) * n, 2)
        else:
            f.pop("value", None)            # let build_label_parts auto-fill
        return build_label_parts(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            allow_network=allow_network, overrides=overrides, upgrades=upgrades, **f,
        )

    # Establish the per-unit value from a single-unit baseline when none was given,
    # so every scenario scales from the same baseline (the auto-fill returns a
    # single-home value, which is exactly the per-unit value at units == 1).
    if base_value is None:
        cfg1, r1, label1 = _run(1, None)
        base_value = cfg1["value"]
        cache[1] = (cfg1, r1, label1)

    scenarios: list[dict] = []
    loc_payload = caveats = wildfire = value_source = None
    for n in counts:
        cfg, r, label = cache[n] if n in cache else _run(n, base_value)
        scenarios.append(_density_scenario_summary(n, cfg, label))
        if loc_payload is None:             # capture shared context once
            full = label_payload(cfg, r, label)
            loc_payload = full.get("location")
            caveats = full.get("caveats")
            wildfire = full.get("wildfire")
            value_source = (cfg.get("value_source")
                            if per_unit_value is None and fields.get("value") is None
                            else None)

    first, last = scenarios[0], scenarios[-1]
    dividend = {
        "from_units": first["units"],
        "to_units": last["units"],
        "fiscal_ratio_from": first["fiscal_ratio"],
        "fiscal_ratio_to": last["fiscal_ratio"],
        "infrastructure_score_from": first["infrastructure_score"],
        "infrastructure_score_to": last["infrastructure_score"],
        "infrastructure_grade_from": first["infrastructure_grade"],
        "infrastructure_grade_to": last["infrastructure_grade"],
        "revenue_per_acre_from": first["revenue_per_acre"],
        "revenue_per_acre_to": last["revenue_per_acre"],
        "net_fiscal_per_acre_from": first["net_fiscal_per_acre"],
        "net_fiscal_per_acre_to": last["net_fiscal_per_acre"],
    }
    return {
        "model": "fixed-lot-vary-units",
        "per_unit_value": round(float(base_value), 2),
        "value_source": value_source,
        "lot_acres": scenarios[0]["lot_acres"],
        "scenarios": scenarios,
        "density_dividend": dividend,
        "location": loc_payload,
        "wildfire": wildfire,
        "caveats": caveats,
    }


def print_density(comp: dict) -> None:
    """Print a fixed-width density comparison (units vs. key dimensions)."""
    TOP, SEP, BOT, row = _box()

    loc = comp.get("location")
    place = (loc.get("label") if isinstance(loc, dict) else None) or "this parcel"

    print()
    print(TOP)
    print(row("  DENSITY ON THIS PARCEL"))
    print(row(f"  {place[:60]}"))
    print(row(f"  Fixed {comp['lot_acres']:.2f}-ac lot · per-unit value "
              f"${comp['per_unit_value']:,.0f}"
              + (f"  ({comp['value_source']})" if comp.get("value_source") else "")))
    print(SEP)
    print(row(f"  {'Scenario':<14}{'Value':>11}{'Infra':>9}{'Fiscal':>8}"
              f"{'Energy':>7}{'Comp':>7}"))
    print(row(f"  {'─'*55}"))
    for s in comp["scenarios"]:
        fr = "—" if s["fiscal_ratio"] is None else f"{s['fiscal_ratio']:.2f}"
        infra = ("—" if s["infrastructure_score"] is None
                 else f"{s['infrastructure_score']:.0f} {s['infrastructure_grade']}")
        energy = "—" if s["energy_score"] is None else f"{s['energy_score']:.0f}"
        comp_s = ("—" if s["composite_score"] is None
                  else f"{s['composite_score']:.0f} {s['composite_national_grade']}")
        print(row(f"  {s['name']:<14}{'$'+format(s['value'],',.0f'):>11}"
                  f"{infra:>9}{fr:>8}{energy:>7}{comp_s:>7}"))
    print(row(f"  {'─'*55}"))

    d = comp["density_dividend"]
    if d["fiscal_ratio_from"] is not None and d["fiscal_ratio_to"] is not None:
        line = (f"Density dividend {d['from_units']}→{d['to_units']} units: "
                f"fiscal {d['fiscal_ratio_from']:.2f}→{d['fiscal_ratio_to']:.2f} · "
                f"Infra {d['infrastructure_grade_from']}→{d['infrastructure_grade_to']}")
        for ln in _wrap(line, 60):
            print(row(f"  {ln}"))
    rpa_from, rpa_to = d.get("revenue_per_acre_from"), d.get("revenue_per_acre_to")
    if rpa_from and rpa_to:        # both present and non-zero (guards the divide)
        mult = rpa_to / rpa_from
        line = (f"Property tax per acre ${rpa_from:,.0f}→${rpa_to:,.0f}/ac"
                f" (×{mult:.1f} on the same land)")
        for ln in _wrap(line, 60):
            print(row(f"  {ln}"))
    caveats = comp.get("caveats") or []
    if caveats:
        print(row(f"  {'─'*60}"))
        for c in caveats:
            for line in _wrap(c, 60):
                print(row(f"  {line}"))
    print(BOT)
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

_RISK_TO_ZONE = {"high": "AE", "moderate": "X500", "minimal": "X"}


def _auto_flood_zone(lat: float, lon: float, allow_network: bool) -> str:
    """Derive a flood zone (X/X500/AE) from the location via FEMA NFHL; default X."""
    if not allow_network:
        return "X"
    try:
        from housing_label.enrich.fema_flood import fetch_flood_zone
        risk = fetch_flood_zone(lat, lon).get("flood_risk")
    except Exception:  # noqa: BLE001
        risk = None
    return _RISK_TO_ZONE.get(risk, "X")


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    allow_network = not args.no_fetch

    if args.address and not allow_network:
        parser.error("--address requires network access (omit --no-fetch).")

    overrides = {
        "health":        args.health_index,
        "socioeconomic": args.socioeconomic_index,
        "walkability":   args.walk_score,
    }
    upgrades = [f for f in BONUS_FLAGS if getattr(args, f, False)]   # CLI resilience flags

    if args.density:
        unit_counts = None
        if args.density_units:
            try:
                unit_counts = [int(x) for x in args.density_units.split(",") if x.strip()]
            except ValueError:
                parser.error("--density-units must be comma-separated integers, "
                             "e.g. 1,2,4")
        try:
            comp = density_comparison(
                address=args.address, lat=args.lat, lon=args.lon,
                preset=args.preset, flood_zone=args.flood_zone,
                allow_network=allow_network, overrides=overrides, upgrades=upgrades,
                unit_counts=unit_counts,
                year_built=args.year_built, construction=args.construction,
                foundation=args.foundation, condition=args.condition,
                value=args.value, sqft=args.sqft, lot_acres=args.lot_acres,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(comp, indent=2))
        else:
            print_density(comp)
        return

    try:
        cfg, r, label = build_label_parts(
            address=args.address, lat=args.lat, lon=args.lon,
            preset=args.preset, flood_zone=args.flood_zone,
            allow_network=allow_network, overrides=overrides, upgrades=upgrades,
            year_built=args.year_built, construction=args.construction,
            foundation=args.foundation, condition=args.condition,
            value=args.value, units=args.units, sqft=args.sqft, lot_acres=args.lot_acres,
            bldg_material=args.bldg_material, stories=args.stories,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        emit_json(cfg, r, label)
    else:
        print_scorecard(cfg, r)
        print_label(cfg, label)


if __name__ == "__main__":
    main()
