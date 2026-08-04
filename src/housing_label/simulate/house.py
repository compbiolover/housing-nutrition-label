#!/usr/bin/env python3
"""simulate_house.py — Housing Nutrition Label: Disaster Resilience Simulator

Defines a hypothetical house and shows where it scores on the disaster
resilience dimension against national (absolute) thresholds.

Usage examples
--------------
  python simulate_house.py \\
      --flood-zone X --lat 35.15 --lon -89.85 \\
      --year-built 2026 --construction icf --foundation slab \\
      --condition excellent --value 350000 \\
      --solar --backup-generator --passive-house

  python simulate_house.py --preset icf-passive --lat 35.15 --lon -89.85
  python simulate_house.py --preset worst-case  --lat 35.15 --lon -89.85

Methodology is score/resilience.py — the shared EAL/BRM/score primitives are
imported from there (not re-implemented), so the live simulator and the batch
scorer apply one identical model:
  EAL rate = flood + tornado + seismic + fire, each × its Building Resilience Modifier (BRM).
  BRM = code_era × construction_type × (foundation for flood only) × condition; the fire leg
    uses a construction combustibility modifier instead.
  Score = log-linear interpolation of total EAL rate → 0-100.
  National grade = absolute score thresholds.
"""

from __future__ import annotations

import argparse
import json
import math
import sys


from housing_label.simulate.dimensions import (
    simulate_all_dimensions, per_unit_home_value, effective_structure,
    AUTOFILL_VALUE_SOURCE, VALUE_PER_DOOR_SOURCE, HOME_VALUE_SOURCE,
)
from housing_label.confidence import (
    confidence_for_label, bands_for_label, CONFIDENCE_NOTES, CONFIDENCE_LEGEND,
)
# Year-built vulnerability curves live in the batch scorer so the offline
# pipeline and this live simulator apply one identical (continuous) model.
from housing_label.score.resilience import (
    code_era_factor, fire_age_factor,
    FLOOD_EAL, LAMBDA_10, LAMBDA_2, pga_to_damage_ratio, eal_rate_to_score,
    score_to_grade as score_to_national_grade,
)
from housing_label.enrich.seismic_lookup import get_pga
from housing_label.utils import haversine_miles

# ── Seismic constants (enrich_seismic.py) ─────────────────────────────────────
NMSZ_LAT            = 36.5     # New Madrid Seismic Zone reference lat
NMSZ_LON            = -89.6    # New Madrid Seismic Zone reference lon
PGA_2PCT_BASE       = 0.48     # g, 2%/50yr baseline for Memphis (NSHM 2023)
PGA_10PCT_BASE      = 0.19     # g, 10%/50yr baseline for Memphis (NSHM 2023)
DIST_NEAR           = 76.0     # mi — closest parcels to NMSZ (NE county corner)
DIST_FAR            = 110.0    # mi — farthest parcels from NMSZ (SW county corner)
ALLUVIUM_LON_THRESH = -89.95   # west of this → deeper alluvial soils (+5% PGA)

# ── Default location (used when none is supplied) ─────────────────────────────
SHELBY_LAT     = 35.15
SHELBY_LON     = -89.98

# The flood EAL rates (FLOOD_EAL), the seismic Poisson rates (LAMBDA_10/LAMBDA_2),
# and the EAL→score mapping (pga_to_damage_ratio, eal_rate_to_score with its
# breakpoint curve) are the shared resilience-model primitives, imported from
# score.resilience above so the live simulator and the batch scorer apply one
# identical model. Only this flood-zone → risk-band mapping is simulator-specific.
FLOOD_ZONE_TO_RISK = {"AE": "high", "X500": "moderate", "X": "minimal"}

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
    "steel":       0.40,  # non-combustible, ductile bolted/screwed connections; masonry-like
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
    "steel":       0.90,  # Steel frame / steel wall — cold-formed steel studs or a
                           # red-iron / post-frame shell. Screwed and bolted connections
                           # develop far more uplift and racking capacity than nailed
                           # wood, and the members do not split. Placed at reinforced
                           # CMU rather than lower on purpose: this one option spans a
                           # wide real spread — HAZUS treats light-gauge steel close to
                           # wood frame (S3/W1), while an engineered red-iron frame
                           # behaves far better — so it sits mid-band, not at either end.
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
    "steel":       0.80,  # non-combustible structure — adds no fuel to a house fire
                           # (steel loses strength when hot, but residential fire LOSS
                           # is contents- and finish-driven, which is what this scales)
}
BONUS_FIRE_SPRINKLERS = 0.45   # Residential sprinklers. NFPA (McGree, "US Experience with
                                # Sprinklers", Apr 2024, NFIRS 2017-21): average property loss
                                # per HOME fire 55% lower with sprinklers ($10.5M vs $23.5M per
                                # 1,000 fires). The former 0.40 came from NFPA's broader
                                # "residential" occupancy row (60%), which also covers hotels and
                                # dormitories — not the home row this model scores. NIST NISTIR
                                # 7451 finds only 32% against smoke-alarm-equipped homes, so 0.45
                                # is the optimistic end of a defensible 0.45-0.68 band.
                                # Applied to the STRUCTURAL fire term only — see fire_raw below;
                                # the NFPA figure is derived from interior NFIRS structure fires
                                # and no source credits interior sprinklers with reducing wildfire
                                # loss (IBHS attributes wildfire survival to exterior hardening).
                                # Strong evidence.

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

# ── Utility connections ───────────────────────────────────────────────────────
# Whether the home is on the public water / sewer network or served on site. Not a
# scoring factor in itself: it decides which public services the Infrastructure
# model may charge the parcel for, and whether county community-water-system
# compliance describes this home's tap at all. "public" is the default on both —
# most US homes are connected, and an unstated source must never quietly discount a
# parcel's cost to serve.
WATER_SOURCES = ("public", "well")
SEWER_TYPES = ("public", "septic")

# ── Lot context ───────────────────────────────────────────────────────────────
# What kind of place the parcel sits in, as a companion to its acreage: acreage
# alone cannot distinguish two exurban acres from a large in-town lot, and the two
# are served very differently. Overrides the Census urban-area test on the geocoded
# point for the infrastructure model (see LOT_CONTEXT_URBAN in simulate/dimensions).
# Default None — unstated keeps the detection rather than asserting anything.
LOT_CONTEXTS = ("rural", "suburban", "urban")

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
# Applied multiplicatively on top of BRM-adjusted EAL rates.
# Every constant below now carries its source and an evidence grade; see
# research/resilience-bonus-calibration-research.md for the full review.
# Several are deliberately 1.00: the feature is real and often valuable, but it
# does not reduce expected annual loss from THIS model's four perils (flood,
# wind/tornado, earthquake, fire). A 1.00 records "reviewed, no EAL effect" and
# is not the same as an unreviewed default.

# General modifiers — applied to flood/tornado/seismic (fire is excluded below).
BONUS_SOLAR      = 1.00  # Rooftop PV: no property-damage mechanism. Grid-tied PV without
                          # storage disconnects within ~2s of grid loss (UL 1741 / IEEE 1547
                          # anti-islanding) and yields zero power for the outage, so the former
                          # "grid independence" rationale was void. Evidence runs the other way:
                          # FEMA USVI Recovery Advisory 5 (2018) records arrays becoming
                          # wind-borne debris that damages their own host roof, and RMI "Solar
                          # Under Storm II" (2020) found 96% of assessed systems used top-down
                          # clips that failed. No actuarial dataset shows lower loss for PV homes.
                          # Solar still earns its (well-founded) energy/environmental credit via
                          # SOLAR_OPERATIONAL_REMAINING. Moderate evidence.
BONUS_GENERATOR  = 1.00  # Backup generator/battery: the large, well-documented avoided losses
                          # sit OUTSIDE this model's four perils. Freeze/burst pipe averages
                          # ~$31k per paid claim (State Farm 2024-H1 2025) and Winter Storm Uri
                          # alone was $10.3B across ~500k claims (TDI 2022) — but there is no
                          # winter-weather leg here, so discounting the earthquake leg to
                          # represent a January cold snap is a category error. LBNL ICE 2.0
                          # (2025) puts total residential willingness-to-pay to avoid a 24h
                          # outage at $54.52, most of it non-property. The one in-peril
                          # mechanism is carried by BONUS_SUMP_BACKUP. Strong evidence that the
                          # benefit is real; strong evidence it is out of scope for the EAL.
BONUS_PASSIVE    = 0.92  # Passive house certification: superior envelope, airtightness,
                          # and thermal mass improve moisture resistance and thermal
                          # survivability (RMI study: 6+ days habitable without power).
                          # Structural wind benefit is indirect; 0.92 reflects envelope/
                          # recovery benefit without overstating direct structural effect.
BONUS_SPRINKLERS = 1.00  # Residential fire sprinklers: NO general all-hazard credit.
                          # Sprinklers act on the fire peril only (BONUS_FIRE_SPRINKLERS);
                          # the flood/tornado/seismic legs model inundation and shaking, which
                          # sprinklers cannot reduce. Fire-following-earthquake is real and large
                          # (ShakeOut: $87B of $191B) but is absent from calc_seismic_eal's
                          # shaking fragility, 13D piping is IRC-exempt from seismic bracing
                          # (2024 IRC R301.2.2.10), and it is fed by the domestic main that fails
                          # post-event (Northridge: 23,200+ service-line breaks). Contra: unbraced
                          # sprinkler piping is a documented EQ water-damage source — 74% leakage
                          # or failure in high-shaking Northridge facilities (FM Global / FEMA
                          # E-74) — which argues >1.00, not <1.00. Strong evidence for no credit.

# Hazard-specific modifiers.
BONUS_SAFE_ROOM   = 0.85  # FEMA P-361 tornado safe room: applied to property damage EAL
                            # only — the safe room does not prevent structural damage to
                            # the main building, so the 0.85 factor reflects partial
                            # contents/habitability loss reduction.
                            # NOTE: CDC 2011 Alabama tornado data shows ~99% fatality
                            # elimination for safe room occupants, but this property
                            # damage model does not capture life-safety directly.
BONUS_RADON_MITIGATION = 1.00  # Radon sub-slab depressurization: NO resilience credit,
                            # and the 1.00 is the point rather than an oversight. Radon is a
                            # chronic indoor-air hazard, not one of the four perils this EAL
                            # model scores, so crediting it here would be a category error.
                            # Its real effect is on Air Quality's radon leg, where EPA's
                            # "up to 99% reduction, successful below 2 pCi/L" floors the
                            # sub-score at the Zone 3 value (data/air_quality.py).
BONUS_LEAK_DETECT = 1.00  # Smart leak detection: NO flood-EAL credit — peril mismatch.
                            # LexisNexis/Flo (2020: -96% frequency, -72% severity) and
                            # Nationwide/Resideo (-$4k per claim) measure ESCAPE OF WATER, i.e.
                            # internal plumbing failure. Shutting the supply main is inert
                            # against external inundation, which is all this leg models (NFIP
                            # zone AEP × mean damage ratio, FEMA P-259 depth-damage). FEMA gives
                            # it no credit under NFIP Risk Rating 2.0 (only elevation, elevated
                            # machinery, flood openings) nor in P-312, and the USACE Day Curve
                            # pays 0% at the ~0 lead time a floor sensor provides. Belongs on a
                            # future non-weather-water peril (~0.35 auto-shutoff, ~0.80
                            # alarm-only). Strong evidence — for the wrong hazard.
BONUS_SUMP_BACKUP = 0.97  # Battery/generator-backed sump pump: the one genuinely in-peril
                            # backup-power mechanism. Loss of power is a leading sump-pump
                            # failure mode and co-occurs with the storm driving the flood.
                            # Kept conservative because this leg is FEMA-flood-zone
                            # depth-damage (inundation), while sump-pump water is typically
                            # groundwater/surface infiltration — an overlapping but not
                            # identical loss population. Weak-moderate evidence.
BONUS_SEISMIC_RET = 0.75  # Foundation / sill-plate anchorage retrofit WITHOUT cripple-wall
                            # bracing (the stem-wall crawlspace case). PEER-CEA 2020/22 Table
                            # 7.38: EAL residual 0.57-0.85 (mean 0.71, one-story, n=16); CEA
                            # rates this tier at 10-15% premium discount vs 20-25% for raised
                            # foundations, the same split. Two-story benefit is ~0 (PEER finds
                            # connection sliding acts as accidental base isolation), so 0.75 is
                            # the one-story figure. Mutually exclusive with BONUS_CRIPPLE_WALL,
                            # which supersedes it — you cannot brace a cripple wall to an
                            # unbolted sill, so they are two tiers of one retrofit, not two.
                            # NB: the former "FEMA P-420 / ~25-40%" citation was a
                            # misattribution — P-420 covers phased rehab of institutional and
                            # commercial buildings and contains no such figure; the dwelling
                            # standard is FEMA P-1100, which publishes no loss percentages at
                            # all. Base isolation (~0.25) is a different intervention entirely
                            # and is deliberately not represented here. Moderate evidence.

# ── Wind/Tornado above-code feature modifiers ─────────────────────────────────
# Applied multiplicatively to tornado/wind EAL only (after BRM).
# FORTIFIED tiers are composite — supersede individual wind features if specified.
BONUS_HURRICANE_STRAPS   = 0.92  # Engineered roof-to-wall connectors replacing a toe-nailed
                                  # legacy connection. ARA 2008 (FL OIR Rpt 18401) Tbl 4-13 prices
                                  # toe nail → wrap at 8.2% (Terrain B) / 16.6% (Terrain C) mean
                                  # loss reduction = 0.92 / 0.86, and ARA's 2024 restudy (Rpt
                                  # 005480 Tbls 4-3..4-11) gives 0.90 mean / 0.97 median in its
                                  # lowest-hazard inland region at Terrain B. Terrain B, not C:
                                  # our default is inland suburban, not coastal.
                                  # The former 0.70 read "50% uplift reduction" — a CAPACITY
                                  # figure (Tbl A-1: toe nail 415 lb vs clip 866 lb ultimate, a
                                  # 0.48 ratio) — as if it were a loss ratio. ARA prices that same
                                  # +189% capacity step at 8-17% of loss: 13-24x compression. The
                                  # figure could not be found in any IBHS publication; IBHS's own
                                  # continuous-load-path page carries no percentage at all.
                                  # Coherence check that settles it: the Hurricane Sally study
                                  # prices everything FORTIFIED Gold adds over FORTIFIED Roof —
                                  # load path, rated openings, gable bracing, wall sheathing and
                                  # more — at ×0.76 combined. A 0.70 for the load path alone
                                  # claimed more than the entire bundle containing it.
                                  # Baseline is a toe-nailed legacy connection. ARA and Florida's
                                  # filed tables both treat roof-to-wall as PRE-FBC-ONLY, so on a
                                  # strictly above-code baseline the clip→wrap step (0.95-0.99)
                                  # would give 0.97; 0.92 is the middle, because IRC prescriptive
                                  # tables long permitted toe nails at inland design speeds, so a
                                  # legacy connection is real here in a way it is not in Florida.
                                  # Strong evidence.
BONUS_HIP_ROOF           = 0.80  # Hip roof (≥90% of the wall perimeter sloped to horizontal
                                  # eaves) vs gable/other. ARA 2008 (FL OIR Rpt 18401) Tbl 4-13
                                  # "Gable/Hip" = 31.6% (Terrain B) / 35.3% (C) loss INCREASE →
                                  # 0.760 / 0.739, and ARA's own claims analysis (Tbl 3-3: 25.9%
                                  # and 14.1% across two insurers, 18 locations) reads "hips show
                                  # about a 20% average reduction in loss over gables" (§3.3.9) —
                                  # the same answer once an increase (denominator = hip) is not
                                  # mistaken for a reduction (denominator = gable). Citizens'
                                  # FILED factors replicate it: 0.70 pre-2002, 0.83 post-2002.
                                  # 0.80 rather than 0.76 because our base is FEMA NRI STOCK-average
                                  # tornado EAL, which already contains ~23% hip roofs:
                                  # 0.760 / (0.77 + 0.23×0.760) = 0.80.
                                  # The former 0.55 read Meecham et al. (1991) — worst peak POINT
                                  # pressure "as much as 50%" lower, one tap at one 4:12 slope, and
                                  # misattributed to IBHS — as if it were a loss ratio. ARA prices
                                  # that same ~2x load ratio at 1.32x loss: ~3x compression. That is
                                  # the mildest compression of the four constants corrected this way,
                                  # because roof shape acts on every zone and all four eaves rather
                                  # than one link of a serial system.
                                  # Unlike the flags retired for unobservability, this one is
                                  # genuinely self-reportable: street-visible, aerial-verifiable,
                                  # Q5 on Florida's OIR-B1-1802, and Citizens accepts roof photos.
                                  # Strong evidence for the loss magnitude; moderate for tornado
                                  # transfer — ASCE 7-22 Ch.32 reuses Ch.30 GCp and Razavi & Sarkar
                                  # (2021) find lower hip uplift under a translating vortex, but
                                  # Ch.32 exempts Risk Category I/II dwellings and no tornado study
                                  # isolates roof shape in loss. Hence the conservative end.
BONUS_IMPACT_GARAGE_DOOR = 0.95  # A PRESSURE-rated garage door (ANSI/DASMA 108, ASTM E330) —
                                  # not an impact-rated one. ARA's own base-case curves fail garage
                                  # doors 0.91-of-1 by panel/pressure and 0-of-1 by missile impact
                                  # (Rpt 18401 p.333); FEMA P-804 §4.2.1.3 and IBHS FORTIFIED TB
                                  # FH 2024-04 both rate the door for pressure and only its glazing
                                  # for debris. (The flag key is left as-is for API compatibility;
                                  # the label and CLI help say wind-rated.)
                                  # The former 0.75 rested on "80% of wind damage initiates via the
                                  # garage" — a FLASH advocacy figure with no primary source, whose
                                  # own page now says >90%, uncited. The real datum is Kovar,
                                  # Brown-Giammanco & Lombardo (2018): 94% of roof-damaged homes
                                  # also had garage damage — an attribution statistic, running the
                                  # opposite direction to what a credit needs, and whose Table 5
                                  # shows 60-73% of failed-door homes had NO roof structural damage.
                                  # ARA prices this increment directly: Secondary Factor 4 "Opening
                                  # Coverage - All Openings" = 0.98 (Tbl 4-15, unchanged in 2024),
                                  # covering all non-glazed doors. ARA's 0.849/0.621 (Tbl 4-13) is
                                  # WHOLE-HOUSE opening protection, explicitly earned with an
                                  # unglazed garage door left untouched (App. A.1.2.3) — a different
                                  # intervention, not an upper bound on this one.
                                  # Nudged above 0.98 because Jaffe, Riveros & Kopp (2019) put door
                                  # failure at 81-165 mph, squarely in the EF0-EF2 band that
                                  # dominates NRI tornado EAL, where the 10 psf garage door fails and
                                  # the 40 psf windows do not (Hazus; Vickery 2006 Tbl 1). Internal
                                  # pressurisation is real but compressive: ARA prices designing the
                                  # whole house for partially-enclosed GCpi at 0.98 too.
                                  # Moderate evidence.
BONUS_SEALED_ROOF_DECK   = 0.93  # Sealed roof deck / secondary water resistance: a self-adhered
                                  # membrane or taped deck seams keeps rain out after the cover
                                  # blows off. ARA 2008 (FL OIR Rpt 18401) Tbl 4-13 puts the
                                  # average benefit at 6.5% (Terrain B) / 8.0% (Terrain C) =
                                  # 0.94/0.93; Tbl 4-19/4-20 give 0.91-0.98 over a code-grade
                                  # roof cover and 0.67-0.98 over a weak one, and ARA's 2024
                                  # restudy medians land at 0.93. Florida's filed credits
                                  # replicate it (~0.94 code-grade cover, ~0.85 weak).
                                  # The former 0.80 read IBHS's "up to 95% less water intrusion"
                                  # — an attic water-VOLUME measurement, conditional on the cover
                                  # already being gone — as if it were a loss ratio. Set at the
                                  # strong-cover end deliberately: SWR is a backup whose value
                                  # falls as the cover improves, BONUS_METAL_ROOF already pays
                                  # for a strong cover, post-2015 code eras increasingly require
                                  # SWR, and anyone who knows they have one has had a recent
                                  # re-roof. Strong evidence.
BONUS_METAL_ROOF         = 0.75  # Standing seam metal roof; 150+ mph wind rating.
                                  # Source: industry testing data. Moderate evidence.
BONUS_REINFORCED_GABLE   = 0.98  # Gable-end bracing. ARA carries this as a SECONDARY factor —
                                  # "Unbraced Gable End" Ki = 1.02, identical in the 2008 (Tbl
                                  # 4-15 #5) and 2024 studies — so bracing is worth 1/1.02, and
                                  # less still once ARA's R' = R·K^(1-R) exponent is applied to a
                                  # strong house. The former 0.80 had no loss source at all: FEMA
                                  # MAT reports document gable-end failure as a MECHANISM, which
                                  # names a failure path rather than quantifying one — the same
                                  # confusion that took BONUS_SEISMIC_HOLD_DOWNS to 1.00. Pre-FBC
                                  # only, and not a line item on Florida's OIR-B1-1802 at all.
                                  # Cross-check: 0.80 for gable bracing alone exceeded the ×0.76
                                  # the Sally study measures for everything Gold adds over Roof,
                                  # a bundle that contains gable bracing. Strong evidence.
BONUS_RING_SHANK_NAILS   = 0.97  # Ring-shank sheathing nails ABOVE the code-era deck schedule
                                  # that code_era_factor already prices. ARA 2008 (FL OIR Rpt
                                  # 18401) "Enhanced Roof Deck" = 0.96 (Tbl 4-15) / 0.99 (Tbl
                                  # 4-2). The former 0.88 read a *withdrawal capacity* figure as
                                  # a loss ratio: ARA measures ring-shank at ~2x the uplift
                                  # capacity of 8d common at the same spacing, yet prices that
                                  # same upgrade at only 1-4% of loss — the capacity-to-loss
                                  # mapping is compressive by 25-100x, not 1:1. Ring-shank
                                  # became code in the 2006 FBC Supplement above 100 mph, so a
                                  # legacy-deck baseline would double-count code_era_factor;
                                  # this credit is strictly above-code. Strong evidence.
# BONUS_TRUSS_16OC removed (was 0.92). Framing spacing acts only through sheathing
# uplift capacity, which BONUS_RING_SHANK_NAILS already credits — Florida's
# OIR-B1-1802 mitigation form lists truss spacing as an ALTERNATIVE route to a rated
# deck uplift psf ("...or truss/rafter spacing that has an equivalent mean uplift
# resistance of 182 psf"), never as an additional credit, so stacking the two
# double-counted one physical quantity. No test program, fragility model, FEMA MAT
# report or claims study isolates framing spacing as a wind variable: APA T325D
# writes one schedule for "24 inches o.c. or less", FEMA 499 FS-18 omits spacing from
# its list of levers, and no FORTIFIED tier credits it. It is also not reliably
# self-reportable — ARA (2008) notes deck attachment can only be established by an
# inspector in the attic. Do not reintroduce without a quantified source.

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
BONUS_SEISMIC_HOLD_DOWNS = 1.00  # Hold-downs at shear-wall ends: NO independent credit —
                                  # double-counted at both places they could act. At the
                                  # foundation, tie-downs are a row of the FEMA P-1024/RA2
                                  # cripple-wall Earthquake Strengthening Schedule (sheets D4
                                  # "with" / D5 "without"), and PEER-CEA's 6-ft cripple-wall
                                  # retrofits "assume tie-downs" — so BONUS_CRIPPLE_WALL was
                                  # measured on retrofits that already include them. In the
                                  # superstructure they are what separates an engineered shear
                                  # wall from a prescriptive IRC braced wall panel, i.e. the
                                  # engineered-vs-conventional split code_era_factor already
                                  # carries. The former 0.85 (and the research doc's 0.75) came
                                  # from component capacity — +213% peak load, +88% stiffness —
                                  # which is a mechanical property, not a loss. No study
                                  # isolates hold-downs in dwelling loss; the CEA discount
                                  # schedule has no such item; and in-wall hardware is not
                                  # self-reportable (the only visible hold-downs are the
                                  # crawlspace ones already credited). Weak evidence for any
                                  # value below 1.00 — do not reintroduce without a dwelling
                                  # EAL or claims source.
                                  # Source: engineering practice. Moderate evidence.
BONUS_AUTO_GAS_SHUTOFF   = 0.90  # Automatic seismic gas shutoff valve; prevents fire.
                                  # Source: FEMA guidelines. Moderate evidence.

# ── Flood above-code feature modifiers ────────────────────────────────────────
# Elevation flags are mutually exclusive (validated in resolve_config).
# Applied multiplicatively to flood EAL only (after BRM).
# The ladder is an EAL RESIDUAL against THIS leg's own baseline house — not against
# a code-minimum house sitting at BFE. FLOOD_EAL's 28% AE-zone mean damage ratio
# corresponds to 1.53 ft of water above the first floor on the USACE EGM 01-03
# one-story curve, so the reference dwelling is already ~1.5 ft BELOW BFE, i.e.
# pre-FIRM stock. Two independent derivations from that anchor agree:
#   • legacy NFIP Rate Table 3B (AE, 1 floor, 1-4 family) building-rate ratios
#     against -1.5 ft → 0.144 / 0.077 / 0.053
#   • integrating the USACE curve over a central riverine stage-frequency curve
#     (~3 ft per log-cycle of return period) → 0.147 / 0.068 / 0.032
# NB the +3 tier is 0.05, not the 0.04 it used to be: 0.04 fell below BOTH
# derivations. NFIP's own table flattens after +3 ft (+3 → +4 buys only a further
# 11%), which is evidence of a real non-inundation tail — scour, below-floor
# utilities, site works, access — that first-floor depth-damage integration cannot
# see and which drives the integrated estimate too close to zero.
# The former "FEMA: 93% annual loss reduction" citation was unsourceable; no FEMA
# publication states it, and FEMA's freeboard material quotes premium savings only.
# Limitation: against a post-FIRM house already built at BFE the same NFIP table
# gives 0.43 / 0.23 / 0.16 — about 4x these. The model cannot observe as-built
# elevation, so it assumes the pre-FIRM stock average, which is right for a generic
# AE parcel. Strong evidence for the shape and +1/+2 ft; moderate for +3.
BONUS_ELEVATION_1FT      = 0.15  # Elevated 1 ft above BFE.
BONUS_ELEVATION_2FT      = 0.08  # Elevated 2 ft above BFE.
BONUS_ELEVATION_3FT      = 0.05  # Elevated 3 ft above BFE. Also BONUS_FLOOR["flood"].
BONUS_FLOOD_VENTS        = 0.85  # Engineered flood vents; reduces hydrostatic damage.
                                  # Source: FEMA. Moderate evidence.
BONUS_BACKFLOW_VALVE     = 1.00  # Backflow/backwater valve: NO flood-EAL credit — peril mismatch,
                                  # the same test that retired BONUS_LEAK_DETECT. This leg is NFIP
                                  # flood-zone AEP × depth-damage MDR, i.e. external inundation; a
                                  # valve acts on sewer-lateral surcharge driven by rainfall
                                  # intensity and municipal drainage capacity. CNT (2014, Cook
                                  # County IL: 181,094 claims, $773.8M paid, 2007-11) found NO
                                  # correlation between damage payouts and mapped floodplains — 33
                                  # ZIP codes contain no floodplain at all and nine of those are
                                  # among the worst hit, with NFIP just 8% of payouts. The two loss
                                  # states barely intersect: the NFIP policy pays sewer backup only
                                  # under a general condition of flooding, where the house is
                                  # already inundated and the valve moves the damage ratio
                                  # negligibly; backup without flooding needs an HO water-backup
                                  # endorsement and is outside this model entirely. FEMA P-259 and
                                  # P-312 list the device under dry floodproofing but publish no
                                  # loss percentage, and Risk Rating 2.0 credits only three actions
                                  # — First Floor Height, flood openings, elevated machinery — never
                                  # a backflow valve. Effectiveness is maintenance-bound in any
                                  # case: of ~1,500 Ottawa basement-flooding incidents in July 2009,
                                  # ~8% were in homes that had one, with a third of inspected covers
                                  # not screwed down. Belongs on a future urban-drainage peril
                                  # (~0.5-0.75 there). Strong evidence — for the wrong hazard.

# Resilience-upgrade flag names (the single source of truth shared by the CLI's
# argparse flags, resolve_config(), and the HTTP API's `upgrades` param).
BONUS_FLAGS = [
    # existing
    "solar", "backup_generator", "passive_house",
    "tornado_safe_room", "fire_sprinklers", "leak_detection", "seismic_retrofit",
    "sump_backup",
    # wind/tornado above-code
    "hurricane_straps", "hip_roof", "impact_garage_door", "sealed_roof_deck",
    "metal_roof", "reinforced_gable", "ring_shank_nails",
    # FORTIFIED tiers
    "fortified_roof", "fortified_silver", "fortified_gold",
    # seismic above-code
    "cripple_wall_bracing", "seismic_hold_downs", "auto_gas_shutoff",
    # flood above-code
    "elevation_1ft", "elevation_2ft", "elevation_3ft",
    "flood_vents", "backflow_valve",
    # air quality — not a resilience measure, so it carries no EAL multiplier.
    # Upgrades already span dimensions (solar moves environmental, passive_house
    # moves energy); this one moves Air Quality's radon leg.
    "radon_mitigation",
]
ELEVATION_FLAGS = ["elevation_1ft", "elevation_2ft", "elevation_3ft"]

# Foundation seismic-retrofit tiers, strongest first. These are two tiers of ONE
# retrofit rather than two independent measures — FEMA P-1100's crawlspace scope
# bolts the sill *and* braces the wall, and you cannot brace a cripple wall to an
# unbolted sill — so the stronger tier supersedes rather than stacking (the same
# composite-supersedes-components pattern as the FORTIFIED tiers). Stacking them
# gave 0.45 × 0.75 = 0.34 for a single physical intervention.
SEISMIC_FOUNDATION_FLAGS = ["cripple_wall_bracing", "seismic_retrofit"]

# ── Bonus aggregation: these features are not independent multipliers ─────────
# Above-code bonuses used to be multiplied together, one constant per checked
# flag. Every published source that prices these features does the opposite.
# ARA's Florida wind study — the actuarial basis for Florida's mitigation credits
# and the source BONUS_RING_SHANK_NAILS derives from — prices the primary
# features from a JOINT lookup table (4,608 combinations in 2008; 20,736 in the
# 2024 revalidation) and says so directly: "one cannot add the individual effects
# together to get a combined mitigation effect … the combined effects are
# nonlinear in their interaction" (2008 §3.3.9), and "secondary factors should
# not be applied independently of the primary factors" (§4.2.2). The reason is
# that the envelope is a SERIAL system, where fixing one link is worth much less
# once another governs: "no SWR tends to minimize the effect of deck strength"
# (§4.2.4.4). FEMA Hazus reaches the same place differently — a separate
# fragility function per combination of roof shape × SWR × deck attachment ×
# roof-to-wall, never a product of per-feature credits.
#
# Two rules replace the bare product, neither of which re-derives a constant:
#
#   1. BONUS_GROUPS — flags acting on the same failure path do not stack; the
#      strongest (lowest) modifier in the group wins. Boundaries mirror ARA's
#      primary-table dimensions. Flags in DIFFERENT groups still multiply, because
#      ARA models roof shape, roof cover, roof attachment and opening protection
#      as separate primary dimensions and they act on genuinely different
#      mechanisms. This is deliberately not "take the single best modifier",
#      which would discard real, independently evidenced features.
#   2. BONUS_FLOOR — the surviving product is floored at the best-evidenced
#      COMPOSITE credit for that hazard, exactly as BRM_FLOOR bounds the
#      code-era/construction/condition stack. A pile of self-reported checkboxes
#      must never outscore the inspected, engineer-stamped certification that
#      represents achieving all of them.
BONUS_GROUPS = {
    "tornado": [
        # Roof structure / uplift load path. Straps, gable-end bracing and deck
        # fastening are three ways to keep the same roof on the same building.
        ("hurricane_straps", "reinforced_gable", "ring_shank_nails"),
        # Roof aerodynamics. Its own ARA primary dimension in every edition, and
        # notably not part of any FORTIFIED tier — FORTIFIED is shape-agnostic —
        # so it legitimately multiplies against the others.
        ("hip_roof",),
        # Roof cover + water intrusion once the cover is stressed. ARA couples
        # these explicitly ("no SWR tends to minimize the effect of deck strength").
        ("sealed_roof_deck", "metal_roof"),
        # Large-opening pressure resistance — a separate failure path from roof
        # uplift (breach → internal pressurisation). Note this is NOT ARA's
        # "opening protection" dimension, which covers glazed openings and is not
        # modelled here; only the garage door is.
        ("impact_garage_door",),
    ],
    "flood": [
        # Elevation and flood openings are ONE rating variable, not two. FEMA's
        # NFIP Risk Rating 2.0 prices openings from a table indexed BY first floor
        # height: -1.7% at FFH 3 ft against -22.1% for the height itself. A house
        # already elevated has little residual inundation loss for vents to reduce,
        # so elevation supersedes them rather than stacking.
        ("elevation_3ft", "elevation_2ft", "elevation_1ft", "flood_vents"),
        # Sewer backup and sump discharge are a different water path from the
        # FEMA-zone depth-damage inundation elevation prices, so they stay
        # independent. In practice the floor usually swallows them once elevation
        # is claimed, which is the correct outcome.
        ("backflow_valve",),
        ("sump_backup",),
    ],
    # Seismic needs no entry: SEISMIC_FOUNDATION_FLAGS already supersedes the one
    # overlapping pair, and the remaining constants act on distinct failure paths
    # (shaking vs fire-following-earthquake), so their product is honest.
}

# Per-hazard lower bound on the COMBINED bonus stack — the analogue of BRM_FLOOR
# ("floor only, no ceiling").
BONUS_FLOOR = {
    # IBHS FORTIFIED Gold, the best-evidenced number in this file: Alabama DOI /
    # UA Center for Risk and Insurance Research, "Performance of IBHS FORTIFIED
    # Home Construction in Hurricane Sally" (2025), n=40,195 policies (5,712
    # Gold) — mean 69% claim-frequency and 32% severity reduction (0.31 × 0.68 =
    # 0.21), and 75% of insurer claim dollars avoided under an all-Gold scenario.
    # Five of the seven individual wind flags reconstruct Gold's own feature list
    # (deck fasteners + sealed deck = Roof; + gable bracing and a rated garage
    # door = part of Silver; + continuous load path = Gold), so the component
    # stack is close to a self-reported Gold and must not beat a certified one.
    # NB it no longer fully reconstructs Silver: Silver requires impact-rated
    # GLAZED openings, which this model has no flag for.
    # BONUS_FORTIFIED_SILVER (0.25) is the defensible stricter choice if we ever
    # want components to top out strictly below Gold: Gold's distinguishing
    # requirements are an engineered, inspected continuous load path and
    # design-pressure-rated openings, neither of which a checkbox can evidence.
    "tornado": BONUS_FORTIFIED_GOLD,
    # BONUS_ELEVATION_3FT is a TOTAL flood-loss residual at that elevation — the
    # ratio of expected annual loss at BFE+3 to this leg's own ~1.5 ft-below-BFE
    # baseline, cross-checked against legacy NFIP rate ratios and a USACE
    # depth-damage integration (see the elevation block) — not a partial credit
    # to multiply further. FEMA rates it the same way: First Floor Height is a
    # primary rating variable, and the only other credited measures are small and
    # conditioned on it.
    "flood":   BONUS_ELEVATION_3FT,
}

# Flood openings need an enclosure to vent. FEMA's Risk Rating 2.0 openings
# discount is available only for crawlspace and elevated-with-enclosure
# foundations — never slab-on-grade, never basement. Same eligibility pattern as
# CRIPPLE_WALL_FOUNDATIONS: claimed on the wrong foundation, it earns no credit
# rather than silently scoring.
FLOOD_VENT_FOUNDATIONS = frozenset({"crawl", "partial-basement"})

# Flag → modifier per hazard: one place to wire a new constant in, rather than a
# scattered call site. leak_detection sits here at 1.00 (reviewed, no EAL effect)
# so the aggregation sees the full flood roster.
TORNADO_BONUS_MODIFIERS = {
    "hurricane_straps":   BONUS_HURRICANE_STRAPS,
    "hip_roof":           BONUS_HIP_ROOF,
    "impact_garage_door": BONUS_IMPACT_GARAGE_DOOR,
    "sealed_roof_deck":   BONUS_SEALED_ROOF_DECK,
    "metal_roof":         BONUS_METAL_ROOF,
    "reinforced_gable":   BONUS_REINFORCED_GABLE,
    "ring_shank_nails":   BONUS_RING_SHANK_NAILS,
}
FLOOD_BONUS_MODIFIERS = {
    "elevation_1ft":  BONUS_ELEVATION_1FT,
    "elevation_2ft":  BONUS_ELEVATION_2FT,
    "elevation_3ft":  BONUS_ELEVATION_3FT,
    "flood_vents":    BONUS_FLOOD_VENTS,
    "backflow_valve": BONUS_BACKFLOW_VALVE,
    "sump_backup":    BONUS_SUMP_BACKUP,
    "leak_detection": BONUS_LEAK_DETECT,
}


def combine_bonuses(cfg: dict, hazard: str, modifiers: dict) -> float:
    """Aggregate one hazard's active above-code bonuses into a single multiplier.

    Not a plain product — see the BONUS_GROUPS block for why. Flags acting on the
    same failure path collapse to the strongest (lowest) active modifier; the
    survivors multiply across groups; the result is floored at BONUS_FLOOR.

    An active flag not named in any group multiplies on its own, so adding a
    constant without classifying it degrades to the old behaviour rather than
    being silently dropped.
    """
    groups = BONUS_GROUPS.get(hazard, ())
    grouped = {f for g in groups for f in g}
    mod = 1.0
    for group in groups:
        active = [modifiers[f] for f in group if f in modifiers and cfg.get(f)]
        if active:
            mod *= min(active)              # same failure path → strongest wins
    for flag, value in modifiers.items():
        if flag not in grouped and cfg.get(flag):
            mod *= value                    # unclassified → independent, as before
    return max(mod, BONUS_FLOOR.get(hazard, 0.0))


def superseded_bonuses(cfg: dict, hazard: str, modifiers: dict) -> list:
    """Flags that were set but earned nothing because a stronger flag in the same
    group superseded them. Mirrors ``inapplicable_upgrades`` so a checked box that
    did nothing stays visible instead of quietly vanishing."""
    out = []
    for group in BONUS_GROUPS.get(hazard, ()):
        active = [f for f in group if f in modifiers and cfg.get(f)]
        if len(active) > 1:
            best = min(active, key=lambda f: modifiers[f])
            out += [f for f in active if f != best]
    return out

# Which foundations each seismic retrofit tier is physically possible on. Both
# retrofits act on the connection between the framing and the foundation, so the
# foundation type decides whether there is anything there to retrofit — a claimed
# upgrade on the wrong foundation earns no credit rather than silently scoring.
#
# A cripple wall is the short stud wall between the foundation sill and the first
# floor, which is what defines raised/crawlspace construction. A slab has no such
# wall at all, and a full basement has full-height concrete walls instead — so the
# FEMA P-1100 crawlspace retrofit has nothing to brace on either. Sill anchorage
# (bolting) is the broader case and needs only a non-slab foundation; on a slab the
# sill is bolted into the slab itself, which is not the stem-wall case PEER-CEA
# measured. This mirrors the CEA's own eligibility split, which pays 20-25% on
# "raised" foundations, 10-15% on "other non-slab", and nothing on slab.
CRIPPLE_WALL_FOUNDATIONS = frozenset({"crawl", "partial-basement"})
SEISMIC_ANCHORAGE_FOUNDATIONS = frozenset({"crawl", "partial-basement", "full-basement"})

# Why a claimed tier cannot apply, keyed by (flag, foundation). Phrased per tier
# because the two do not fail for the same reason: a full basement has no cripple
# wall but *does* have a sill to bolt, so a single blanket reason would overstate
# what is missing and contradict SEISMIC_ANCHORAGE_FOUNDATIONS.
RETROFIT_INAPPLICABLE_REASON = {
    ("cripple_wall_bracing", "slab"):
        "there is no cripple wall to brace",
    ("cripple_wall_bracing", "full-basement"):
        "full-height basement walls take the place of a cripple wall",
    ("seismic_retrofit", "slab"):
        "the sill is bolted into the slab itself, not a raised stem wall",
}

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


def calc_flood_eal_raw(flood_risk: str) -> float:
    return FLOOD_EAL[flood_risk]


def calc_seismic_eal_raw(pga_2pct: float, pga_10pct: float) -> float:
    """Seismic EAL rate: two-point trapezoidal hazard curve integration
    (``pga_to_damage_ratio`` and LAMBDA_* are imported from score.resilience)."""
    dr_rare     = pga_to_damage_ratio(pga_2pct)    # 2%/50yr damage ratio
    dr_moderate = pga_to_damage_ratio(pga_10pct)   # 10%/50yr damage ratio
    return LAMBDA_2 * dr_rare + (LAMBDA_10 - LAMBDA_2) * dr_moderate


# The resilience score curve (eal_rate_to_score / SCORE_BREAKPOINTS), the seismic
# damage curve (pga_to_damage_ratio), the flood rates (FLOOD_EAL), the Poisson
# rates (LAMBDA_*), the grade thresholds (score_to_grade), and the code-era / fire-
# age factor curves all live in housing_label.score.resilience and are imported at
# the top of this module — so this live simulator and the batch scorer apply one
# identical model instead of two copies that can drift apart.


# ── Argument parsing ───────────────────────────────────────────────────────────

def _positive_float(s: str) -> float:
    """argparse type: a finite strictly-positive float (clear error, not a silent drop)."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        v = float("nan")
    if not math.isfinite(v) or v <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {s!r}")
    return v


def _positive_int(s: str) -> int:
    """argparse type: a strictly-positive int."""
    try:
        v = int(s)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {s!r}") from None
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {s!r}")
    return v


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
    # Tri-state tenure. This CLI has no BooleanOptionalAction/store_false precedent, so
    # use the mutually-exclusive-group idiom already used for flood elevation: both
    # flags write the same dest, and supplying neither leaves it None (unknown).
    #
    # BOTH actions carry an explicit default=None. argparse seeds a shared dest from the
    # first-declared action that has a default, so with store_false's implicit default of
    # True left in place the unknown state would survive only as long as
    # --owner-occupied stayed declared first — and a reorder would silently start
    # treating unspecified tenure as owner-occupied. Stating it on both makes the
    # tri-state independent of declaration order.
    tenure = p.add_mutually_exclusive_group()
    tenure.add_argument("--owner-occupied", dest="owner_occupied", action="store_true",
                        default=None,
                        help="The owner lives in the home (or in one unit of it). "
                             "Affects property-tax classification in split-roll states.")
    tenure.add_argument("--rental", dest="owner_occupied", action="store_false",
                        default=None,
                        help="Every unit is rented. In states that tax rental housing "
                             "as commercial, this raises the estimated property tax.")
    p.add_argument("--lot-acres",  type=float, default=None,
                   help="Lot size (acres). Default: 0.25.")
    p.add_argument("--water-source", dest="water_source",
                   choices=list(WATER_SOURCES), default=None,
                   help="Drinking-water source. 'well' means the home is not on a "
                        "community water system: it is not charged the public water "
                        "cost, and Water Quality is left unscored (EPA SDWIS covers "
                        "community systems only). Default: public.")
    p.add_argument("--lot-context", dest="lot_context",
                   choices=list(LOT_CONTEXTS), default=None,
                   help="What kind of place the lot sits in (rural | suburban | "
                        "urban). Overrides the Census urban-area test on the "
                        "geocoded point, which is coarse at a city's fringe. "
                        "Default: detected.")
    p.add_argument("--sewer", dest="sewer",
                   choices=list(SEWER_TYPES), default=None,
                   help="Wastewater disposal. 'septic' means an on-site field rather "
                        "than a public sewer connection. Default: public.")
    p.add_argument("--building-material", dest="bldg_material",
                   choices=["wood", "masonry", "concrete", "steel"], default=None,
                   help="Structural shell material for a multi-unit building (drives "
                        "Resilience/Durability when NSI didn't detect the building).")
    p.add_argument("--stories",    type=_positive_int,   default=None,
                   help="Number of floors. Drives floor-aware flood and the embodied-"
                        "carbon footprint (foundation + roof per m2 of floor).")
    p.add_argument("--allow-non-residential", dest="allow_non_residential",
                   action="store_true",
                   help="Score even when the address is detected as a non-residential "
                        "building (workplace/store/etc). By default such addresses are "
                        "refused — the label rates residential dwellings only.")
    p.add_argument("--basement-depth-ft", dest="basement_depth_ft", type=_positive_float,
                   default=None,
                   help="Actual basement/foundation-wall depth (ft) for the embodied-"
                        "carbon foundation term. Default: per foundation type.")

    # ── Existing bonus feature flags ──────────────────────────────────────────────
    p.add_argument("--solar",             action="store_true", help="Solar panels.")
    p.add_argument("--backup-generator",  action="store_true", help="Backup generator/battery.")
    p.add_argument("--passive-house",     action="store_true", help="Passive house certification.")
    p.add_argument("--tornado-safe-room", action="store_true", help="FEMA P-361 tornado safe room.")
    p.add_argument("--fire-sprinklers",   action="store_true", help="Residential fire sprinklers.")
    p.add_argument("--leak-detection",    action="store_true",
                   help="Smart leak detection system (no flood-EAL credit — mitigates "
                        "non-weather water damage, outside this model's four perils).")
    p.add_argument("--sump-backup",       action="store_true",
                   help="Battery/generator-backed sump pump (×0.97 flood EAL).")
    p.add_argument("--seismic-retrofit",  action="store_true",
                   help="Foundation/sill-plate anchorage retrofit — bolting without "
                        "cripple-wall bracing (×0.75 seismic EAL; superseded by "
                        "--cripple-wall-bracing). Non-slab foundations only.")

    # ── Wind/Tornado above-code features ──────────────────────────────────────────
    wind = p.add_argument_group("wind/tornado above-code features")
    # Multipliers are interpolated from the constants, never retyped: the hardcoded
    # copies drifted (ring-shank still advertised x0.88 after it moved to 0.97, and
    # hold-downs x0.85 after they moved to 1.00), which is the same duplication bug
    # the icon palette had.
    wind.add_argument("--hurricane-straps",    action="store_true",
                      help=f"Continuous load path connections (×{BONUS_HURRICANE_STRAPS} "
                           "tornado/wind EAL).")
    wind.add_argument("--hip-roof",            action="store_true",
                      help=f"Hip roof — sloped to eaves over ≥90%% of the wall perimeter "
                           f"(×{BONUS_HIP_ROOF} tornado/wind EAL).")
    wind.add_argument("--impact-garage-door",  action="store_true",
                      help=f"Wind/pressure-rated garage door, ANSI/DASMA 108 or ASTM "
                           f"E330 (×{BONUS_IMPACT_GARAGE_DOOR} tornado/wind EAL).")
    wind.add_argument("--sealed-roof-deck",    action="store_true",
                      help=f"Sealed roof deck / secondary water resistance "
                           f"(×{BONUS_SEALED_ROOF_DECK} tornado/wind EAL).")
    wind.add_argument("--metal-roof",          action="store_true",
                      help=f"Standing seam metal roof (×{BONUS_METAL_ROOF} tornado/wind EAL).")
    wind.add_argument("--reinforced-gable",    action="store_true",
                      help=f"Reinforced gable end walls (×{BONUS_REINFORCED_GABLE} "
                           "tornado/wind EAL).")
    wind.add_argument("--ring-shank-nails",    action="store_true",
                      help=f"Ring-shank sheathing nails above the code-era schedule "
                           f"(×{BONUS_RING_SHANK_NAILS} tornado/wind EAL).")

    # ── FORTIFIED certification (composite — supersedes individual wind features) ──
    fortified = p.add_argument_group("IBHS FORTIFIED certification (composite; supersedes "
                                     "individual wind features)")
    fortified.add_argument("--fortified-roof",   action="store_true",
                           help=f"IBHS FORTIFIED Roof designation (×{BONUS_FORTIFIED_ROOF} "
                                "tornado/wind EAL).")
    fortified.add_argument("--fortified-silver",  action="store_true",
                           help=f"IBHS FORTIFIED Silver (×{BONUS_FORTIFIED_SILVER} "
                                "tornado/wind EAL).")
    fortified.add_argument("--fortified-gold",    action="store_true",
                           help=f"IBHS FORTIFIED Gold (×{BONUS_FORTIFIED_GOLD} tornado/wind EAL).")

    # ── Seismic above-code features ───────────────────────────────────────────────
    seismic = p.add_argument_group("seismic above-code features")
    seismic.add_argument("--cripple-wall-bracing", action="store_true",
                         help=f"Cripple wall bracing (×{BONUS_CRIPPLE_WALL} seismic EAL). "
                              "Raised foundations only — crawl or partial-basement.")
    seismic.add_argument("--seismic-hold-downs",   action="store_true",
                         help="Hold-down connectors at shear walls (no EAL credit — already "
                              "counted in cripple-wall bracing and the code era).")
    seismic.add_argument("--auto-gas-shutoff",     action="store_true",
                         help=f"Automatic seismic gas shutoff valve (×{BONUS_AUTO_GAS_SHUTOFF} "
                              "seismic EAL).")

    # ── Flood above-code features (elevation flags are mutually exclusive) ────────
    flood = p.add_argument_group("flood above-code features")
    elev = flood.add_mutually_exclusive_group()
    elev.add_argument("--elevation-1ft", action="store_true",
                      help=f"Elevated 1 ft above BFE (×{BONUS_ELEVATION_1FT} flood EAL).")
    elev.add_argument("--elevation-2ft", action="store_true",
                      help=f"Elevated 2 ft above BFE (×{BONUS_ELEVATION_2FT} flood EAL).")
    elev.add_argument("--elevation-3ft", action="store_true",
                      help=f"Elevated 3 ft above BFE (×{BONUS_ELEVATION_3FT} flood EAL; also "
                           "the floor on the whole flood stack).")
    flood.add_argument("--flood-vents",    action="store_true",
                       help=f"Engineered flood vents (×{BONUS_FLOOD_VENTS} flood EAL). "
                            "Needs an enclosure — crawl or partial-basement only.")
    flood.add_argument("--backflow-valve", action="store_true",
                       help="Backflow prevention valve (no flood-EAL credit — acts on sewer "
                            "backup, outside the external flooding this leg scores).")

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
        "bldg_material": None, "stories": None, "basement_depth_ft": None,
        # Tenure, tri-state: None = unknown (resolved by an ACS-backed default in
        # data/assessment.rental_unit_count), True = owner-occupied, False = rental.
        # Drives property-tax classification in split-roll states.
        "owner_occupied": None,
        # Utility connections. "public" = on the municipal network, "well" /
        # "septic" = served on site. A private well also leaves Water Quality
        # unscored: EPA SDWIS covers community water systems only.
        #
        # water_source defaults to None = "detect it", now that the EPA service-area
        # boundaries can answer it (see enrich/water_system.py); an explicit value
        # still wins, and a point with no detection available resolves to public, so
        # an unstated source never discounts a parcel. sewer stays "public": nothing
        # detects it yet, and assuming septic would be a guess.
        "water_source": None, "sewer": "public",
        # Lot context: None = use the Census urban-area detection for the point.
        "lot_context": None,
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
        "basement_depth_ft": getattr(args, "basement_depth_ft", None),
        "owner_occupied": getattr(args, "owner_occupied", None),
        "water_source": getattr(args, "water_source", None),
        "sewer":        getattr(args, "sewer", None),
        "lot_context":  getattr(args, "lot_context", None),
    }
    for key, cli_val in CLI_FIELDS.items():
        if cli_val is not None:
            cfg[key] = cli_val
        elif key not in cfg:
            cfg[key] = GLOBAL_DEFAULTS[key]

    # Validate the closed vocabularies here rather than only at the CLI/API edges.
    # Every one of these is consumed by an equality test downstream
    # (``water_source == "well"``, ``LOT_CONTEXT_URBAN.get(lot_context)``), so a
    # typo from a library caller — ``build_label_parts(water_source="Well")`` —
    # would not raise. It would silently mean "public", scoring a well household's
    # tap water from a community system it isn't on. Failing loudly here makes the
    # library path behave like the CLI and API paths, which already reject these.
    for key, allowed in (("water_source", WATER_SOURCES), ("sewer", SEWER_TYPES),
                         ("lot_context", LOT_CONTEXTS)):
        val = cfg.get(key)
        if val is not None and val not in allowed:
            raise ValueError(
                f"invalid {key}={val!r}; choose one of: {', '.join(sorted(allowed))}")

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

def simulate(cfg: dict, structure: dict | None = None) -> dict:
    """Run the full EAL + BRM + bonus calculation. Returns a results dict.

    ``structure`` (from the resolved Location) carries the detected building type,
    material, and stories. For a detected multi-family building its material drives
    the construction resilience factors, and flood exposure is reduced for the
    representative unit by the building's height (only the lowest floors flood).
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

    flood_risk = FLOOD_ZONE_TO_RISK[cfg["flood_zone"]]

    r.update(pga_2pct=pga_2pct, pga_10pct=pga_10pct,
             pga_source=pga_source, flood_risk=flood_risk)

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
    # Tornado = the location's FEMA NRI tornado EAL rate, resolved exactly like
    # wildfire. build_label_parts sets cfg["tornado_eal_base"] whenever a Location is
    # present — including the national-average rate for an unmapped point (resolved
    # False). It's 0.0 only when no location was supplied at all (offline / no
    # geocode), which keeps simulate() offline-safe.
    try:
        tornado_raw = float(cfg.get("tornado_eal_base") or 0.0)
        if not math.isfinite(tornado_raw):
            tornado_raw = 0.0
    except (TypeError, ValueError):    # non-numeric override (JSON/CLI) → ignore
        tornado_raw = 0.0
    tornado_raw = max(0.0, tornado_raw)
    r["tornado_eal_base"] = tornado_raw
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
    # Sprinklers discount the STRUCTURAL fire term only. The NFPA loss reduction is
    # measured on interior NFIRS structure fires; interior 13D sprinklers have no
    # published effect on wildfire structure loss (IBHS attributes wildfire survival
    # to exterior hardening — Class A roof, ember-resistant vents, defensible space —
    # and treats sprinklers as a supplement, never a replacement). Discounting the
    # whole leg over-credited sprinklers wherever wildfire dominates the WUI baseline.
    structural_fire = FIRE_EAL_BASE
    if cfg.get("fire_sprinklers"):
        structural_fire *= BONUS_FIRE_SPRINKLERS
    fire_raw    = structural_fire + wildfire_base
    r["wildfire_eal_base"] = wildfire_base

    # ── BRM-adjusted EAL rates ────────────────────────────────────────────────
    flood_adj   = flood_raw   * flood_brm * flood_floor
    tornado_adj = tornado_raw * wind_seismic_brm
    seismic_adj = seismic_raw * wind_seismic_brm
    fire_adj    = fire_raw    * fire_brm

    # ── Hazard-specific bonus modifiers (existing) ────────────────────────────
    # leak_detection (1.00, peril mismatch) and sump_backup are applied by the
    # flood aggregation below, via FLOOD_BONUS_MODIFIERS — not here, or they would
    # count twice.
    if cfg.get("tornado_safe_room"): tornado_adj *= BONUS_SAFE_ROOM
    # Fire sprinklers are applied to the structural fire term in fire_raw above,
    # not to the whole fire leg — see the wildfire note there.

    # ── Wind/tornado above-code modifiers ─────────────────────────────────────
    # FORTIFIED tier is composite and supersedes individual wind features.
    superseded: list = []
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
        # Individual wind features: grouped by failure path and floored at the
        # best-evidenced composite, so a set of self-reported checkboxes cannot
        # outscore the certification that represents achieving all of them.
        tornado_adj *= combine_bonuses(cfg, "tornado", TORNADO_BONUS_MODIFIERS)
        superseded += superseded_bonuses(cfg, "tornado", TORNADO_BONUS_MODIFIERS)
    r["fortified_note"] = fortified_note

    # ── Seismic above-code modifiers ──────────────────────────────────────────
    # Foundation retrofit tiers supersede rather than stack (SEISMIC_FOUNDATION_FLAGS),
    # and each only applies on a foundation it is physically possible on.
    foundation = cfg.get("foundation")
    crip_claimed, ret_claimed = (bool(cfg.get(f)) for f in SEISMIC_FOUNDATION_FLAGS)
    crip_ok = crip_claimed and foundation in CRIPPLE_WALL_FOUNDATIONS
    ret_ok  = ret_claimed  and foundation in SEISMIC_ANCHORAGE_FOUNDATIONS

    seismic_retrofit_note = None
    if crip_ok:
        seismic_adj *= BONUS_CRIPPLE_WALL
        if ret_ok:
            seismic_retrofit_note = ("Cripple-wall bracing supersedes the generic foundation "
                                     "anchorage retrofit — it already includes sill anchorage.")
    elif ret_ok:
        seismic_adj *= BONUS_SEISMIC_RET
    r["seismic_retrofit_note"] = seismic_retrofit_note

    # Name any tier that was claimed but cannot apply, so a checked box that did
    # nothing is visible rather than silently ignored.
    seismic_inapplicable = [f for f, claimed, ok in
                            (("cripple_wall_bracing", crip_claimed, crip_ok),
                             ("seismic_retrofit",     ret_claimed,  ret_ok))
                            if claimed and not ok]
    r["seismic_applicability_note"] = (
        f"No seismic credit on a {foundation or 'unknown'} foundation — "
        + "; ".join(
            f"{BONUS_LABELS[f]}: "
            + RETROFIT_INAPPLICABLE_REASON.get(
                (f, foundation), "that retrofit does not apply to this foundation")
            for f in seismic_inapplicable)
        + "."
    ) if seismic_inapplicable else None
    # Collected across hazards below; the flood block adds to it.
    inapplicable = list(seismic_inapplicable)
    if cfg.get("seismic_hold_downs"):    seismic_adj *= BONUS_SEISMIC_HOLD_DOWNS
    if cfg.get("auto_gas_shutoff"):      seismic_adj *= BONUS_AUTO_GAS_SHUTOFF

    # ── Flood above-code modifiers ────────────────────────────────────────────
    # Elevation tiers are mutually exclusive (validated in resolve_config) and
    # supersede flood vents — FEMA prices openings from a table indexed by first
    # floor height, so the two are one rating variable. The stack is floored at
    # BONUS_ELEVATION_3FT because that FEMA figure is already a total residual.
    flood_mods = dict(FLOOD_BONUS_MODIFIERS)
    if foundation not in FLOOD_VENT_FOUNDATIONS:
        flood_mods.pop("flood_vents", None)      # no enclosure to vent
        if cfg.get("flood_vents"):
            inapplicable.append("flood_vents")
    flood_adj *= combine_bonuses(cfg, "flood", flood_mods)
    superseded += superseded_bonuses(cfg, "flood", flood_mods)

    # Claimed upgrades that earned nothing, so a checked box never looks counted:
    # `inapplicable` = ruled out by the foundation, `superseded` = outranked by a
    # stronger flag acting on the same failure path.
    r["inapplicable_upgrades"] = inapplicable
    r["superseded_upgrades"] = superseded
    r["superseded_note"] = (
        "Counted once, not twice — "
        + ", ".join(BONUS_LABELS[f] for f in superseded)
        + (" acts on the same failure path as a stronger upgrade claimed here."
           if len(superseded) == 1 else
           " act on the same failure paths as stronger upgrades claimed here.")
    ) if superseded else None

    # ── General bonus modifiers (apply to flood/tornado/seismic EAL) ─────────
    # Fire is excluded: solar/generator/passive don't reduce ignition, and
    # sprinklers apply to the structural fire term in fire_raw instead.
    gen_mod = 1.0
    if cfg.get("solar"):           gen_mod *= BONUS_SOLAR
    if cfg.get("backup_generator"):gen_mod *= BONUS_GENERATOR
    if cfg.get("passive_house"):   gen_mod *= BONUS_PASSIVE
    if cfg.get("fire_sprinklers"): gen_mod *= BONUS_SPRINKLERS

    flood_adj   *= gen_mod
    tornado_adj *= gen_mod
    seismic_adj *= gen_mod

    # Non-EAL note. Backup power and leak detection have real, well-measured
    # benefits that this four-peril property-damage model cannot express — winter
    # freeze/burst pipe, food spoilage, escape-of-water. Saying so beats either
    # inventing a multiplier for them or dropping the information entirely. Same
    # honesty pattern as the safe-room comment (life safety, not property damage).
    outage_bits = []
    if cfg.get("backup_generator") or cfg.get("solar"):
        outage_bits.append("winter-outage burst pipes")
        outage_bits.append("food spoilage")
    if cfg.get("leak_detection"):
        outage_bits.append("plumbing-failure water damage")
    if outage_bits:
        listed = (outage_bits[0] if len(outage_bits) == 1
                  else " and ".join([", ".join(outage_bits[:-1]), outage_bits[-1]]))
        r["outage_note"] = (f"Also mitigates {listed} — real losses, but outside the "
                            "four perils scored here.")
    else:
        r["outage_note"] = None

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
    "sump_backup":          "Backup-powered sump pump",
    "seismic_retrofit":     "Foundation anchorage retrofit (bolting)",
    # wind/tornado above-code
    "hurricane_straps":     "Hurricane straps (load path)",
    "hip_roof":             "Hip roof",
    "impact_garage_door":   "Wind-rated garage door",
    "sealed_roof_deck":     "Sealed roof deck",
    "metal_roof":           "Standing seam metal roof",
    "reinforced_gable":     "Reinforced gable end walls",
    "ring_shank_nails":     "Ring-shank nails",
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
    # The "general" modifiers below are applied to flood/tornado/seismic only —
    # gen_mod deliberately skips the fire leg (see the general-bonus block).
    # Several read "no EAL credit": reviewed against the literature and found to
    # have no effect on this model's four perils, which is not the same as unrated.
    "solar":                "no EAL credit (energy/carbon credit only)",
    "backup_generator":     "no EAL credit (see backup-powered sump pump)",
    "passive_house":        f"×{BONUS_PASSIVE} flood/tornado/seismic",
    "fire_sprinklers":      f"×{BONUS_FIRE_SPRINKLERS} structural fire only",
    "tornado_safe_room":    f"×{BONUS_SAFE_ROOM} tornado only",
    "leak_detection":       "no EAL credit (non-weather water, outside the four perils)",
    "sump_backup":          f"×{BONUS_SUMP_BACKUP} flood only",
    "seismic_retrofit":     f"×{BONUS_SEISMIC_RET} seismic only "
                            f"(superseded by cripple wall bracing)",
    "hurricane_straps":     f"×{BONUS_HURRICANE_STRAPS} wind/tornado",
    "hip_roof":             f"×{BONUS_HIP_ROOF} wind/tornado",
    "impact_garage_door":   f"×{BONUS_IMPACT_GARAGE_DOOR} wind/tornado",
    "sealed_roof_deck":     f"×{BONUS_SEALED_ROOF_DECK} wind/tornado",
    "metal_roof":           f"×{BONUS_METAL_ROOF} wind/tornado",
    "reinforced_gable":     f"×{BONUS_REINFORCED_GABLE} wind/tornado",
    "ring_shank_nails":     f"×{BONUS_RING_SHANK_NAILS} wind/tornado",
    "fortified_roof":       f"×{BONUS_FORTIFIED_ROOF} wind/tornado (composite)",
    "fortified_silver":     f"×{BONUS_FORTIFIED_SILVER} wind/tornado (composite)",
    "fortified_gold":       f"×{BONUS_FORTIFIED_GOLD} wind/tornado (composite)",
    "cripple_wall_bracing": f"×{BONUS_CRIPPLE_WALL} seismic only",
    "seismic_hold_downs":   "no EAL credit (counted in cripple-wall bracing / code era)",
    "auto_gas_shutoff":     f"×{BONUS_AUTO_GAS_SHUTOFF} seismic only",
    "elevation_1ft":        f"×{BONUS_ELEVATION_1FT} flood only",
    "elevation_2ft":        f"×{BONUS_ELEVATION_2FT} flood only",
    "elevation_3ft":        f"×{BONUS_ELEVATION_3FT} flood only",
    "flood_vents":          f"×{BONUS_FLOOD_VENTS} flood only",
    "backflow_valve":       f"×{BONUS_BACKFLOW_VALVE} flood only",
}


def _wrap_rows(text: str, indent: str = "", width: int = 64) -> list[str]:
    """Wrap one scorecard line to the box's inner width, indenting continuations.

    The bonus rows and the ⚑ notes carry prose long enough to blow past the border,
    which broke the box drawing. Wrapping keeps them inside it."""
    import textwrap
    return textwrap.wrap(text, width=width, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False) or [text]


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
    # Tenure only prints when the caller stated it — an unknown tenure is scored on a
    # documented default, and showing "unknown" would imply it was an input.
    oo = cfg.get("owner_occupied")
    tenure = "" if oo is None else ("  ·  owner-occupied" if oo else "  ·  rental")
    print(row(f"    Units / size     : {cfg.get('units', 1)} {unit_label} × "
              f"{cfg.get('sqft', 2000):,.0f} sqft on {cfg.get('lot_acres', 0.25):.2f} ac"
              f"{tenure}"))
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
    print(row(f"    Tornado EAL rate : {r.get('tornado_eal_base', 0.0):.2e} /yr  (FEMA NRI)"))
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
        haz_specific = [b for b in BONUS_LABELS if cfg.get(b)
                        and b not in ("solar","backup_generator","passive_house")]
        inapplicable = set(r.get("inapplicable_upgrades") or ())
        superseded = set(r.get("superseded_upgrades") or ())
        for b in haz_specific:
            # Show what actually happened: a flag the foundation rules out, or one
            # outranked on its failure path, never multiplied anything — printing
            # its modifier would misrepresent it.
            if b in inapplicable:
                desc = ("not applied — needs an enclosure to vent" if b == "flood_vents"
                        else f"not applied — needs a "
                             f"{'raised' if b == 'cripple_wall_bracing' else 'non-slab'} foundation")
            elif b in superseded:
                desc = "not applied — same failure path as a stronger upgrade"
            else:
                desc = BONUS_MODIFIER_DESC[b]
            # Modifier descriptions can be a full sentence now ("no EAL credit …"),
            # so wrap rather than overflow the box border.
            for line in _wrap_rows(f"    + {BONUS_LABELS[b]:<30}: {desc}", indent=" " * 6):
                print(row(line))
    for key in ("fortified_note", "seismic_retrofit_note",
                "seismic_applicability_note", "superseded_note", "outage_note"):
        if r.get(key):
            for line in _wrap_rows(f"    ⚑  {r[key]}", indent=" " * 7):
                print(row(line))
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
    print(BOT)
    print()


# ── Full nutrition label (all dimensions) ───────────────────────────────────────

# The pilot county. Seismic (USGS), tornado (FEMA NRI), energy rates (EIA), grid factor
# (eGRID), and infrastructure cost/tax are all resolved nationally per address; this
# FIPS only anchors the bundled resilience reference dataset and the cost-model
# numeraire, and picks the local-comparison branch.
CALIBRATED_COUNTY_FIPS = "47157"


def _approx_caveats(location, cfg: dict | None = None) -> list[str]:
    """Caveats for dimensions that aren't locally calibrated.

    Seismic (USGS) and tornado (FEMA NRI) are nationwide. Infrastructure is calibrated
    to each county's local-government spending (Census of Governments) where the
    county is in the crosswalk, a national-average cost model when the county isn't
    in it, and the Memphis pilot baseline if the crosswalk isn't bundled at all. The
    Environmental grid factor is the county's eGRID2023 Rev 2 subregion rate when the
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
                "Multi-unit building: scored in its building context — Energy uses the "
                "measured multi-family EUI for its type, Resilience its material and "
                "height, Durability its shared structural shell, Infrastructure its unit density, and "
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
                "Multi-unit building: Energy (multi-family EUI), Infrastructure (per-unit "
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
        marg = loc.cambium_factor if getattr(loc, "cambium_factor", None) is not None else "—"
        print(row(f"  Location: {place}"))
        print(row(f"    IECC zone {cz}  ·  tract {label.get('census_tract') or '—'}"))
        print(row(f"    grid avg {grid} · marginal {marg} kgCO2e/kWh"))
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
        # Not scored above — see the outage_note rationale in simulate().
        ("Beyond these perils", r.get("outage_note")),
        # A claimed upgrade that the foundation makes impossible earns no credit;
        # say so rather than letting the box look as though it counted.
        ("Upgrade not applicable", r.get("seismic_applicability_note")),
        # Claimed, but a stronger upgrade on the same failure path already counted it.
        ("Counted once", r.get("superseded_note")),
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
        ("Fiscal ratio (revenue ÷ cost to serve)", None if fr is None else f"{fr:.2f}"),
        ("Est. property tax (per unit)", _money(m.get("est_property_tax"), "/yr")),
        ("Est. user fees — water, sewer, trash (per unit)",
         _money(m.get("est_fee_revenue"), "/yr")),
        ("Est. total revenue (per unit)", _money(m.get("est_total_revenue"), "/yr")),
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

    # Air Quality — the national-percentile index plus the ambient pollutant + radon
    # drivers behind it; falls back to the generic status row when unscored.
    aq_s = _finite(scores.get("air_quality"))
    pm25, ozone = _finite(m.get("aq_pm25_ugm3")), _finite(m.get("aq_ozone_ppb"))
    if aq_s is not None:
        details["air_quality"] = rows(
            ("Air quality index (national percentile)", f"{aq_s:.1f} / 100"),
            ("Fine particulate (PM2.5, annual avg)", None if pm25 is None else f"{pm25:.1f} µg/m³"),
            ("Ozone (annual 8-hour avg)", None if ozone is None else f"{ozone:.0f} ppb"),
            ("Radon", m.get("aq_radon_label")),
            ("Source", loc_notes.get("air_quality") or "CDC Tracking + EPA radon"),
        )
    else:
        details["air_quality"] = location_rows("air_quality", "Air quality index (national percentile)", "CDC Tracking + EPA radon")

    # Noise — the national-percentile quiet score plus the exposure driver behind it.
    ns_s = _finite(scores.get("noise"))
    ns_pct = _finite(m.get("noise_pct_ge60db"))
    if ns_s is not None:
        details["noise"] = rows(
            ("Quiet index (national percentile)", f"{ns_s:.1f} / 100"),
            ("Residents exposed to loud transport noise (≥60 dB)",
             None if ns_pct is None else f"{ns_pct:.1f}%"),
            ("Source", loc_notes.get("noise") or "BTS National Transportation Noise Map"),
        )
    else:
        details["noise"] = location_rows("noise", "Quiet index (national percentile)", "BTS National Transportation Noise Map")

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

    # Solar Potential — the national-percentile score plus what a representative
    # rooftop array would produce here, the dollars it offsets, and the CO₂ avoided.
    ss = _finite(scores.get("solar"))
    sys_kw = _finite(m.get("solar_system_kw"))
    if ss is not None:
        details["solar"] = rows(
            ("Solar potential index (national percentile)", f"{ss:.1f} / 100"),
            ("Rooftop yield", None if _finite(m.get("solar_yield_kwh_kwp")) is None
             else f"{m['solar_yield_kwh_kwp']:,.0f} kWh per kW·yr"),
            (None if sys_kw is None else f"A {sys_kw:.0f} kW system would make",
             None if sys_kw is None else qty(m.get("solar_annual_kwh"), "kWh/yr")),
            ("— offsetting", _money(m.get("solar_savings_usd"), "/yr")),
            ("— avoiding", None if _finite(m.get("solar_co2_avoided_kg")) is None
             else f"{m['solar_co2_avoided_kg']:,.0f} kg CO₂e/yr"),
            ("Source", loc_notes.get("solar") or "PVGIS-NSRDB"),
        )
    else:
        details["solar"] = location_rows("solar", "Solar potential index (national percentile)", "PVGIS-NSRDB")

    wt_s = _finite(scores.get("water"))
    wt_pct = _finite(m.get("water_pct_hb_violation"))
    if wt_s is not None:
        details["water"] = rows(
            ("Drinking-water safety index (national percentile)", f"{wt_s:.1f} / 100"),
            ("Community-water-system users on a system with a recent health-based violation",
             None if wt_pct is None else f"{wt_pct:.1f}%"),
            ("Community water systems in the county",
             None if _finite(m.get("water_n_cws")) is None else f"{m['water_n_cws']:,.0f}"),
            ("Source", loc_notes.get("water") or "EPA SDWIS"),
        )
    else:
        details["water"] = location_rows("water", "Drinking-water safety index (national percentile)", "EPA SDWIS")

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
            "owner_occupied": cfg.get("owner_occupied"),
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
        # The two headline axes (simulate/dimensions.py). The composite is kept
        # alongside them rather than replaced — it is what every earlier label and
        # every downstream consumer already reads — but it is no longer the only
        # number, because it averages away the difference between a well-built
        # house in a hard place and a poor one in an easy place.
        "construction_score": label["construction_score"],
        "construction_national_grade": label["construction_national_grade"],
        "construction_n_scored": label["construction_n_scored"],
        "location_score": label["location_score"],
        "location_national_grade": label["location_national_grade"],
        "location_n_scored": label["location_n_scored"],
        "location_raw_mean": label["location_raw_mean"],
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
            "cambium_region": loc.cambium_region,
            "cambium_factor": loc.cambium_factor,
            "in_urban_area": loc.in_urban_area,
            # Inside an incorporated municipality, or unincorporated county
            # territory? None = no geocode resolved (unknown, not "no").
            "incorporated": loc.incorporated,
            "place_geoid": loc.place_geoid,
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
                    "sqft", "units", "stories", "lot_acres", "value", "bldg_material",
                    "water_source", "sewer", "lot_context"]


# Multifamily building efficiency: the fraction of gross floor area that is a
# unit's own living space, once the shared circulation/lobby/mechanical common
# areas are removed. NSI reports GROSS building area, so gross ÷ units overstates a
# dwelling's conditioned area; ~0.85 is a mid-range apartment efficiency ratio
# (corridors/stairs/elevators/lobby run ~15%). A modeled approximation — the sqft
# is surfaced as an estimate. (Distinct from the energy model, which scores a
# multi-unit dwelling off the measured ResStock multi-family EUI for its type.)
_MF_NET_TO_GROSS = 0.85


def _nsi_per_unit_sqft(location, units: int | None = None) -> float | None:
    """Auto-filled living area per *dwelling unit*.

    A genuine NSI multi-unit record (``units_confidence == "detected"``) reports the
    WHOLE building's GROSS floor area, so it is split across the unit count and
    scaled by ``_MF_NET_TO_GROSS`` (common-area allowance) to approximate one
    dwelling's living space — this keeps the energy cost, EUI, and the lifetime-cost
    comparison per apartment rather than scoring the entire 100k+ sqft building
    against one typical house. Single-family sqft, and the cluster heuristic's sqft
    (already one mislabeled house), are returned as-is.

    ``units`` is the *effective* dwelling-unit count so the divisor matches the rest
    of the per-unit math: an explicit override ``> 1`` wins, while ``units`` of 1 or
    None (the default, i.e. "not overridden") falls back to the NSI-detected count."""
    sqft = getattr(location, "sqft", None)
    if sqft is None:
        return None
    n = _nsi_sqft_divisor(location, units)
    return round(float(sqft) / n * _MF_NET_TO_GROSS, 1) if n else sqft


def _nsi_sqft_divisor(location, units: int | None = None) -> int | None:
    """The unit count to split a WHOLE-building NSI sqft by (per-unit living area),
    or None when the sqft already describes one dwelling (single-family, the cluster
    heuristic's one mislabeled house, or no genuine multi-unit record). Sole source
    of truth for *whether* per-unit division happens, so callers don't re-derive it
    from a value comparison (which would mis-tag a 0-sqft or rounding-equal record)."""
    n = units if (units and units > 1) else getattr(location, "num_units", None)
    if (getattr(location, "units_confidence", None) == "detected"
            and getattr(location, "structure_type", None) == "multifamily"
            and n and n > 1):
        return n
    return None


def _autofill_construction_from_nsi(cfg: dict, explicit: set, location,
                                    units: int | None = None) -> dict:
    """Fill year_built / sqft / construction / foundation from the NSI-detected
    Location when the user left them unset. Returns ``{field: (source, confidence)}``
    for the fields that were auto-filled, so the label can tag them as estimates.

    year_built is a CENSUS-TRACT MEDIAN — a fact about the tract, not the building —
    so it is tagged ``assumed`` rather than ``estimated``; construction is a coarse
    5-class guess, so it is low confidence too. sqft/foundation ride NSI's
    per-structure provenance (parcel-observed → higher confidence than modeled).
    For a detected multi-unit building the sqft is stored per dwelling unit, split by
    the effective ``units`` count (see ``_nsi_per_unit_sqft``)."""
    filled: dict = {}
    if location is None:
        return filled
    observed = getattr(location, "structure_attr_source", None) == "P"
    sqft_val = _nsi_per_unit_sqft(location, units)
    # A per-unit sqft divided out of the whole-building floor area is a derived
    # average (it depends on the unit divisor), not a direct NSI field — label it
    # as such and drop one confidence notch. Decided by the same predicate used to
    # divide, so it can't mis-tag a 0-sqft or rounding-equal record.
    if sqft_val is not None and _nsi_sqft_divisor(location, units) is not None:
        sqft_src, sqft_conf = "NSI · building area ÷ units, less common area (per unit)", "moderate" if observed else "low"
    else:
        sqft_src, sqft_conf = "NSI · structure record", "high" if observed else "moderate"
    plan = [
        # NSI's med_yr_blt is, in its own documentation, "the median year built of
        # structures within the Census tract" — a property of the tract, never of
        # this building. It is still the best prior available (dropping it would
        # fall back to a flat national default, which is worse), so it is kept and
        # relabelled rather than removed: "assumed", naming the tract, so the panel
        # renders it as a stand-in rather than as something measured here.
        ("year_built",   getattr(location, "year_built", None),
         "census-tract median year built (NSI) — not this building's", "low", "assumed"),
        ("sqft",         sqft_val, sqft_src, sqft_conf),
        ("construction", getattr(location, "construction", None), "NSI · material class (coarse estimate)", "low"),
        ("foundation",   getattr(location, "foundation", None), "NSI · structure record", "moderate" if observed else "low"),
        # NSI already returns stories; previously fetched but dropped before the
        # embodied model, so real addresses were scored as 1-story. Now wired through.
        ("stories",      getattr(location, "stories", None), "NSI · structure record", "moderate" if observed else "low"),
    ]
    for entry in plan:
        field, val, source, conf = entry[:4]
        if field not in explicit and val is not None:
            cfg[field] = val
            filled[field] = (source, conf) if len(entry) < 5 else (source, conf, entry[4])
    # Real building footprint (USA Structures) — internal geometry for the embodied
    # model, not a user-editable construction field, so set directly (not via plan).
    # Only a single-dwelling footprint maps cleanly onto the (per-unit) SFLA the model
    # scores. For a multi-unit building SFLA is per unit while the USA Structures
    # footprint is the WHOLE building, so propagating it would inflate the per-unit
    # geometry — skip it and let the model estimate per unit instead.
    if not (units and units > 1):
        for k in ("footprint_area_m2", "footprint_perimeter_m"):
            v = getattr(location, k, None)
            if v is not None and cfg.get(k) is None:   # don't stomp a caller value
                cfg[k] = v
    return filled


def _resolved_water_source(cfg: dict, location):
    """The water source the model will actually use, for the panel to display."""
    from housing_label.simulate.dimensions import resolve_water_source
    return resolve_water_source(cfg, location)


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
        # Utility connections. Reported so the panel keeps showing the visitor's own
        # choice across a re-score (the form clears any field the payload omits) and
        # so the default reads honestly as "assumed", not as something we detected.
        # Nothing infers these today — see the note in build_label_parts.
        # Resolved for DISPLAY only (stated > EPA detection > public). cfg keeps the
        # unstated None so the scorer can still tell a detection from a statement.
        "water_source": _resolved_water_source(cfg, location), "sewer": cfg.get("sewer"),
        "lot_context": cfg.get("lot_context"),
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
            # An entry may carry its own status as a third element. Almost all
            # auto-fills are "estimated" — derived from public data ABOUT THIS HOME —
            # but a few are an area typical standing in for a home we know nothing
            # about, which is what "assumed" means. NSI's year_built is the case
            # that forced the distinction: it is a census-tract median, so calling
            # it an estimate of this building implies a measurement nobody took.
            entry = autofilled.get(field) or detected[field]
            source, conf = entry[0], entry[1]
            status = entry[2] if len(entry) > 2 else "estimated"
            out[field] = {"value": value, "status": status,
                          "source": source, "confidence": conf}
        else:
            out[field] = {"value": value, "status": "assumed",
                          "source": "typical default", "confidence": "low"}
    return out


class NonResidentialProperty(ValueError):
    """Raised when a scored address is a positively-identified non-residential
    building (a workplace, store, warehouse, …) rather than a home.

    The Housing Nutrition Label rates *residential* dwellings, so scoring a
    commercial/industrial parcel produces a meaningless label. This is a subclass
    of ``ValueError`` so existing callers still treat it as bad input, but the API
    catches it specifically to return a friendly 422 (vs. a generic 400).

    Only fires on a *positive* NSI classification (Hazus COM*/IND*/AGR*/GOV*/…);
    an unknown building (NSI unavailable or no match) never blocks scoring.
    ``structure_type`` carries the coarse category for the caller's message.
    """

    def __init__(self, message: str, *, structure_type: str | None = None):
        super().__init__(message)
        self.structure_type = structure_type


# Human phrasing for the refusal message. The Hazus non-residential umbrella
# covers commercial, industrial, agricultural, and government/education/religious
# occupancy — all "not a home". Kept UI-agnostic: this is what the website shows a
# visitor, so it must NOT mention the CLI flag or the API override (a web user
# can't act on either). The CLI appends its own `--allow-non-residential` hint (see
# main()); the API documents `allow_non_residential` in its OpenAPI schema.
_NON_RESIDENTIAL_MESSAGE = (
    "This address looks like a non-residential property (e.g. a commercial, "
    "industrial, or institutional building) rather than a home, so it was not "
    "scored. The Housing Nutrition Label rates residential dwellings only."
)

# USA Structures OCC_CLS values that are positively non-residential. "Residential",
# "Unclassified", "Utility and Misc", and None are NOT here — they pass the screen
# (an oddly-classed or unmapped real home must not be refused).
_NON_RES_OCC_CLS = frozenset({
    "COMMERCIAL", "INDUSTRIAL", "EDUCATION", "GOVERNMENT", "ASSEMBLY", "AGRICULTURE",
})

# The one OCC_CLS that is a positive *residential* verdict on the addressed
# footprint — it vetoes an NSI non-residential call (see the screen in
# build_label_parts). "Unclassified" / "Utility and Misc" / None are not verdicts.
_RES_OCC_CLS = "RESIDENTIAL"


def build_label_parts(*, address: str | None = None,
                      lat: float | None = None, lon: float | None = None,
                      preset: str | None = None, flood_zone: str | None = None,
                      allow_network: bool = True, overrides: dict | None = None,
                      upgrades: list[str] | None = None, location=None,
                      allow_non_residential: bool = False,
                      **fields) -> tuple[dict, dict, dict]:
    """Resolve a location, build the house config, and run the full simulation.

    Returns (cfg, r, label). ``fields`` may carry house overrides (year_built,
    construction, foundation, condition, value, units, sqft, lot_acres) and
    ``upgrades`` is a list of resilience-upgrade flag names (see BONUS_FLAGS).
    Mirrors the CLI flow so both share one code path.

    Raises ``NonResidentialProperty`` when a real address (no ``preset``) resolves
    to a building NSI positively classifies as non-residential — unless
    ``allow_non_residential`` is set, or the USA Structures footprint at the point
    positively reads "Residential" (the two datasets disagree about one building,
    and NSI's occupancy is modeled). A ``preset`` is a hypothetical "what if you
    built this here" scenario, so it always bypasses the screen; so does an
    entered unit count > 1 (the caller is asserting it's a residence).
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
        owner_occupied=fields.get("owner_occupied"),
        water_source=fields.get("water_source"), sewer=fields.get("sewer"),
        lot_context=fields.get("lot_context"),
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

    # Location-based tornado EAL (FEMA NRI), resolved the same way as wildfire and
    # passed into the resilience model as cfg["tornado_eal_base"]. Left unset only
    # when no Location resolved (offline with no geocode), so simulate() uses 0.0.
    if location is not None and getattr(location, "tornado", None):
        cfg["tornado_eal_base"] = location.tornado.get("eal_rate") or 0.0

    # Auto-fill the home value when the caller didn't specify one, so the
    # Infrastructure fiscal ratio (and dollar EALs) reflect the local market instead
    # of the construction profile's flat default. An explicit value (CLI --value /
    # API value=) always wins. For a multi-family building — detected by NSI OR
    # declared by the caller's unit count — the single-family owner-occupied median
    # is wrong (a rental building carries no such value), so use the income-based
    # value-per-door estimate (rent-derived NOI ÷ cap rate); other addresses keep the
    # single-family county median.
    struct = effective_structure(cfg, location)

    # Residential screen: refuse a real address (no hypothetical preset) that NSI
    # positively identified as non-residential — a workplace / store / warehouse
    # produces a meaningless "home" label. ``struct["structure_type"]`` is
    # "non_residential" only when NSI classified it so AND the caller didn't declare
    # a multi-unit count (an entered units > 1 flips it to "multifamily" — an
    # explicit assertion that it's a residence, so it isn't screened). An unknown
    # building (NSI unavailable / no match) leaves the type None and is never
    # blocked, so a transient outage can't refuse a real home.
    #
    # Second, independent signal: the USA Structures (FEMA/ORNL) occupancy class of
    # the footprint at the point. It cuts both ways, and in neither direction does it
    # override a *positive residential* reading from the other source:
    #
    #   * As a TIE-BREAKER for an unknown structure — when NSI has no match
    #     (structure_type None), a positively non-residential OCC_CLS
    #     (Commercial/Industrial/…) screens the address out. It deliberately does NOT
    #     override a positive NSI residential detection: a mixed-use "Commercial"
    #     footprint sitting over real apartments (NSI-detected multifamily) must not
    #     refuse the residents.
    #   * As a VETO over an NSI non-residential call — an OCC_CLS of "Residential" on
    #     the footprint the address actually lands on means the two national datasets
    #     disagree about one building, and refusing is the costlier error. NSI's
    #     occupancy is modeled, not observed, wherever `attr_source` isn't "P", and it
    #     systematically types rural farmhouses as AGR1 (verified: 1614
    #     Jenkinsville-Jamestown Rd, Dyersburg TN — a 3,483 sqft home whose NSI record
    #     is a modeled AGR1, while the USA Structures footprint containing the rooftop
    #     geocode 2.9 m away is "Residential"). The veto needs that positive
    #     "Residential"; a genuine barn or grain store classes as "Agriculture" and is
    #     still refused, as is a footprint that is unmapped or "Unclassified".
    #
    # (The caller's `nonresidential` flag from the geocoder, handled at the API layer,
    # is a third signal and is unaffected by this veto — it is what catches a stadium
    # NSI misreads as the residential towers around it.)
    occ_cls = (getattr(location, "occ_cls", None) or "").strip().upper()
    occ_nonres = (occ_cls in _NON_RES_OCC_CLS
                  and struct["structure_type"] in (None, "non_residential"))
    nsi_nonres = (struct["structure_type"] == "non_residential"
                  and occ_cls != _RES_OCC_CLS)
    if preset is None and not allow_non_residential and (nsi_nonres or occ_nonres):
        raise NonResidentialProperty(
            _NON_RESIDENTIAL_MESSAGE,
            structure_type=("non_residential" if occ_nonres else struct["structure_type"]))

    explicit = {f for f in _EDITABLE_FIELDS if fields.get(f) is not None}
    autofilled: dict = {}
    if location is not None and fields.get("value") is None:
        county_fips = getattr(location, "county_fips", None)
        if struct["is_multifamily"]:
            from housing_label.data.multifamily_value import value_per_door_for_county
            cfg["value"] = value_per_door_for_county(county_fips)["value_per_door"]
            cfg["value_source"] = VALUE_PER_DOOR_SOURCE
        else:
            # Prefer the neighborhood (census-tract) median over the county-wide
            # one — far closer for a home in an expensive/cheap area — falling back
            # county → national. Still a neighborhood typical, not the specific
            # property's value (a user entry overrides it).
            from housing_label.data.home_value import median_home_value_for
            hv = median_home_value_for(getattr(location, "tract", None), county_fips)
            if hv["value"]:
                cfg["value"] = hv["value"]
                cfg["value_source"] = HOME_VALUE_SOURCE.get(hv["geo_level"], AUTOFILL_VALUE_SOURCE)
    if cfg.get("value_source"):
        # An area-median estimate (neighborhood tract / county / national, or the
        # income-based value-per-door) — a typical value, not this home's own.
        autofilled["value"] = (cfg["value_source"], "low")

    # Auto-fill the rest of the construction profile from the NSI-detected building
    # when the caller is scoring a real address (no hypothetical preset) and didn't
    # supply the field — so "type an address" needs no manual entry. Each stays a
    # tagged, editable estimate. A preset means the user wants a hypothetical build,
    # so its values win (no NSI override).
    if preset is None:
        autofilled.update(_autofill_construction_from_nsi(
            cfg, explicit, location, struct.get("num_units")))
        # Provenance for the detected drinking-water source (EPA service-area
        # boundaries) — only the tag, deliberately not the value.
        #
        # cfg["water_source"] is NOT written here. This block runs before
        # simulate_all_dimensions, so stamping the detected value into cfg would
        # make it indistinguishable from one the visitor entered — the distinction
        # the water note has to keep ("as entered" vs "evidence, not proof").
        # _building_block resolves the value for DISPLAY instead, so the panel still
        # shows the detection rather than an empty box: the one field a well owner
        # most needs to confirm must not be the one field with nothing in it.
        if "water_source" not in explicit:
            ws = getattr(location, "water_system", None) or {}
            if ws.get("status") == "served":
                autofilled["water_source"] = (
                    f"EPA service areas · served by {ws.get('name') or ws.get('pwsid')}",
                    "moderate")
            elif ws.get("status") == "outside":
                autofilled["water_source"] = (
                    "EPA service areas · no mapped community system at this point",
                    "moderate")
            else:
                # No detection (off-network, or the layer was unreachable). The model
                # still proceeds as public, so the panel says so — an assumption the
                # scoring acts on must be visible, not silent.
                autofilled["water_source"] = (
                    "typical default — water source not detected", "low", "assumed")
    building = _building_block(cfg, struct, explicit, autofilled, location)

    structure = {
        "structure_type": struct["structure_type"],
        "num_units": struct["num_units"],
        "stories": struct["stories"],
        "bldg_material": struct["bldg_material"],
    }
    r = simulate(cfg, structure=structure)
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
    # generate far more revenue on the same land and shared infra.
    # Revenue is total revenue (property tax + user fees), not tax alone, so it
    # covers the same services as cost_per_acre — otherwise net_fiscal_per_acre
    # charges the parcel for water, sewer, and trash while crediting none of the
    # bills residents pay for them.
    pu_acres = lot / units if lot and units else None
    pu_revenue = metrics.get("est_total_revenue")
    pu_cost = metrics.get("est_annual_infra_cost")
    revenue_per_acre = (round(float(pu_revenue) / pu_acres, 2)
                        if pu_revenue is not None and pu_acres else None)
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
        # The assessment ratio the parcel was taxed at — 0.25 residential vs 0.40
        # industrial-and-commercial in Tennessee, which flips at 2+ rental units and
        # is a real part of the density dividend.
        "assess_ratio_applied": metrics.get("assess_ratio_applied"),
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
            allow_network=allow_network, overrides=overrides, upgrades=upgrades,
            # Density is an explicit "what could be built on this parcel" tool, and
            # its units=1 baseline run would otherwise trip the residential screen
            # on a non-residential lot — so it opts out of the screen.
            allow_non_residential=True, **f,
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
        line = (f"Revenue per acre ${rpa_from:,.0f}→${rpa_to:,.0f}/ac"
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
            allow_non_residential=args.allow_non_residential,
            year_built=args.year_built, construction=args.construction,
            foundation=args.foundation, condition=args.condition,
            value=args.value, units=args.units, sqft=args.sqft, lot_acres=args.lot_acres,
            bldg_material=args.bldg_material, stories=args.stories,
        )
    except NonResidentialProperty as exc:
        # A deliberate refusal, not a usage error — print the guidance to stderr and
        # exit non-zero without argparse's "usage:" banner (which would bury it). The
        # override hint is CLI-only (appended here, not baked into the shared message)
        # so the website's notice stays free of instructions a web user can't follow.
        print(str(exc), file=sys.stderr)
        print("Pass --allow-non-residential to score it anyway.", file=sys.stderr)
        raise SystemExit(2)
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        emit_json(cfg, r, label)
    else:
        print_scorecard(cfg, r)
        print_label(cfg, label)


if __name__ == "__main__":
    main()
