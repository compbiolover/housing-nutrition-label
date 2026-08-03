#!/usr/bin/env python3
"""Modeled infrastructure cost-burden library.

Computes per-parcel infrastructure cost, property-tax revenue, and fiscal-balance
fields for the infrastructure dimension. Importable functions only; no batch runner.

Methodology: Density-Adjusted Cost Allocation
----------------------------------------------
Urban planning literature consistently shows that low-density sprawl costs
municipalities 2–3x more per household than compact development, driven by
longer road/pipe networks, greater fire/police patrol area, and reduced
transit efficiency.

Primary calibration sources
  - Halifax Regional Municipality, "The Cost of Sprawl" (2004, 2020 update):
      Published per-household cost curves for roads, water/sewer, fire, police
      across density quintiles. Values are the most-cited North American
      benchmark for density-cost relationships.
  - Strong Towns, "The Real Math of Sprawl" (2020): calibration overlay
      applied to Halifax curves for Sun Belt / car-dependent city context,
      roughly matching Memphis's development pattern.
  - City of Memphis FY2026 Adopted Budget ($883M, ~253,000 households):
      Implies ~$3,490/household blended baseline for all general-fund services.
      Source: Memphis City Council, FY2026 Budget Book (April 2025).
  - Memphis FY2026 Budget detail:
      Police  : 42% of $350M personnel = ~$147M → ~$581/household
      Fire    : 34% of $350M personnel = ~$119M → ~$470/household
      Roads   : $73.5M / 4yr = ~$18.4M/yr → ~$73/household capital allocation
                (operating roads budget estimated ~$40M/yr additional)
      Solid Waste: $42/month fee × 12 = $504/household (Memphis-specific flat fee)
      Water/Sewer: MLGW separate utility; $2.3B budget, ~140,000 sewer connections
                  → ~$1,640/connection/yr gross; density adjustment applied.
  - Victoria Transport Policy Institute, "Land Use Impacts on Transport" (2019):
      Fire response cost distance multipliers.

Memphis-specific calibration notes
  Memphis is ~300 sq mi with ~620,000 residents ≈ 2,067 persons/sq mi overall.
  This is roughly 1.0–1.5 DU/acre at the city average — classic Sun Belt sprawl.
  The cost curves below are calibrated to this context; they are NOT generic
  national averages. Comments flag where national benchmarks are used as-is.

Both sides of the fiscal ratio cover the same services
------------------------------------------------------
The cost side counts every service the public provides — including water, sewer,
and trash, which residents pay for through utility bills and a monthly fee rather
than through property tax. So the revenue side counts both: property tax **plus**
modeled user-fee revenue, derived from each county's actual charges-to-expenditure
ratio in the Census of Governments. Comparing tax revenue alone against the full
cost of service made every home look like a fiscal drain — nationally, water/sewer
recovers ~100% of its cost from charges and solid waste ~75%.

IMPORTANT: This is a modeled estimate, not an accounting audit. All cost
components are approximations intended for relative comparison across parcels.
Absolute dollar values carry ±30% uncertainty.

Columns added
-------------
  lot_density_du_acre       DU/acre (1 DU assumed per parcel)
  distance_to_core_mi       Haversine miles from parcel to Memphis city center
  infra_cost_roads          Road maintenance & capital cost ($/yr)
  infra_cost_water_sewer    Water/sewer pipe & treatment cost ($/yr)
  infra_cost_fire           Fire/EMS service cost ($/yr)
  infra_cost_police         Police patrol cost ($/yr)
  infra_cost_sanitation     Solid waste collection cost ($/yr)
  infra_cost_parks          Parks & other general services cost ($/yr)
  est_annual_infra_cost     Sum of all cost components ($/yr)
  est_property_tax          Estimated annual property tax revenue ($/yr)
  est_fee_revenue           Estimated annual user-fee revenue ($/yr)
  est_total_revenue         est_property_tax + est_fee_revenue ($/yr)
  assess_ratio_applied      Assessment ratio used, after classification
  classification_multiplier_applied
                            Rate multiplier from classification (1.0 = none)
  fiscal_balance            est_total_revenue − est_annual_infra_cost ($/yr)
  fiscal_ratio              est_total_revenue / est_annual_infra_cost
  infra_burden_rating       Categorical rating (net contributor / break-even /
                            minor burden / major burden)
"""

from __future__ import annotations

import math

import pandas as pd

from housing_label.data.assessment import classification_multiplier, classified_assess_ratio
from housing_label.utils import haversine_miles

REQUIRED_COLUMNS = ["latitude", "longitude", "CALC_ACRE"]

# ── Memphis city center (Main St & Beale St intersection, downtown core) ───────
# Used as proxy for proximity to high-density urban services & fire stations.
# Source: Google Maps, Memphis, TN 38103
MEMPHIS_CORE_LAT = 35.1495
MEMPHIS_CORE_LON = -90.0490

# ── Property tax parameters (Memphis / Shelby County, FY2026) ─────────────────
# Memphis city property tax rate: $3.19 per $100 of assessed value
# Source: City of Memphis FY2026 Budget Book, Revenue section
# Note: Shelby County levies an additional ~$2.71/$100 not included here;
#       this model estimates only the CITY portion of the tax.
CITY_TAX_RATE           = 0.0319    # per $1 of assessed value
RESIDENTIAL_ASSESS_RATIO = 0.25     # 25% of appraised value; Tenn. Code Ann. § 67-5-801

# Tennessee classifies residential property containing 2+ RENTAL units as
# industrial and commercial, assessed at 40% instead of 25% (Tenn. Const. art. II,
# § 28; Tenn. Code Ann. § 67-5-501(11), § 67-5-801). A rental apartment building
# therefore generates 1.6x the property tax per dollar of value that the flat 25%
# ratio credited it. See ``data/assessment.py`` for the statute, the controlling AG
# opinion, and why only Tennessee is encoded.
CLASSIFICATION_STATE = "TN"         # the pilot state these defaults describe

# ── Fee recovery: the share of each service's cost paid by user charges ───────
# Shelby County, from the bundled Census of Governments crosswalk
# (``data/govfinance_county.csv``, geoid 47157): current-charges revenue ÷ direct
# expenditure per function. Memphis residents pay the water and sewer bill (MLGW)
# and a $42/month solid-waste fee, so those services are already almost entirely
# funded outside the property tax — while fire and police have no user charge at
# all. Counting their COST against property-tax revenue alone, as this model did
# before, compared unlike things and understated every home's cost recovery.
# Ratios are capped at 1.0: MLGW recovers more than its own expenditure, but a home
# should not be credited with generating a surplus on its pipes.
SHELBY_FEE_RECOVERY = {
    "roads":       0.0079,
    "water_sewer": 1.0000,
    "fire":        0.0000,   # no current-charge code exists for fire protection
    "police":      0.0000,   # nor for police
    "sanitation":  0.9737,
    "parks":       0.1906,
}

# ── Road cost vs density (continuous, $/household/yr) ─────────────────────────
# Source: Halifax Regional Municipality "Cost of Sprawl" (2004, updated 2020);
#         Strong Towns Sun Belt calibration applied (1.15x multiplier for
#         lower-density suburban road network typical of Memphis metro).
# Covers: pavement maintenance, reconstruction capital, stormwater drainage,
#         sidewalks/curb, traffic signals — all amortized to annual $/HH.
# These are calibrated to Memphis; NOT simple national averages.
#
# Anchor points are the published Halifax band costs placed at each band's
# geometric-mean density, then EXTENDED past 12 DU/acre (24, 48) by continuing
# the curve's slope (≈ density^-0.7). Cost is log-log interpolated between
# anchors and clamped flat outside the range (interp_cost). Linear road network
# is shared per-frontage, so per-household cost keeps falling with density rather
# than flooring at 12 DU/acre — small-multiplex infill (a quadplex ≈ 16 DU/acre)
# is squarely in the responsive range, not pinned at the old floor.
ROAD_COST_BY_DENSITY = [
    # (du_acre, $/HH/yr)
    # ── Rural extension, below Halifax's published "rural/estate" anchor ──────
    # Without these the curve CLAMPED FLAT below 0.7 DU/acre, so a 1.5-acre lot
    # and a 40-acre lot were billed identically and entering a real rural acreage
    # changed nothing. Two different slopes, because two different things happen:
    #
    #   0.7 -> 0.2 DU/acre (1.4 -> 5 acres): continue the curve's OWN local slope
    #     (~density^-0.32, measured between the 0.7 and 1.73 anchors). A 3.5x
    #     extrapolation past the published anchor, in the direction the published
    #     curve is already heading — frontage per household keeps growing.
    #   0.2 -> 0.025 DU/acre (5 -> 40 acres): flatten hard (~density^-0.15). Past
    #     roughly five acres the household is on a county through-road that exists
    #     to connect places, not to serve that parcel, and it carries no curb,
    #     gutter, storm sewer, sidewalk or lighting. Marginal attributable cost
    #     stops scaling with frontage.
    #
    # Clamped flat below 0.025 (40 acres): beyond that the parcel is farm or
    # timber land whose road burden is not a per-household quantity at all.
    (0.025, 4_900),  # ~40-acre parcel (floor anchor)
    (0.05,  4_430),  # ~20-acre
    (0.1,   4_000),  # ~10-acre
    (0.2,   3_600),  # ~5-acre
    (0.35,  3_000),  # ~3-acre
    (0.7,   2_400),  # rural/estate
    (1.73,  1_800),  # suburban sprawl
    (4.24,  1_200),  # suburban
    (8.49,    700),  # urban
    (12.0,    400),  # dense urban (published floor anchor)
    (24.0,    250),  # very dense infill (extended)
    (48.0,    150),  # mid-rise / compact urban (extended)
    # High-rise / large-multifamily densities (extended along the same
    # density^-0.7 slope). A tower parcel's frontage road + stormwater is shared
    # across 100s of units, so per-household cost keeps falling — a 157-unit
    # building should not be billed the same road cost as a quadplex. Floored at
    # ~$60/HH: the irreducible per-unit share of local access + drainage.
    (96.0,     90),  # mid/high-rise
    (200.0,    60),  # high-rise tower (floor)
]

# ── Water/sewer cost vs density (continuous, $/household/yr) ───────────────────
# Source: Halifax "Cost of Sprawl" (2004/2020); MLGW sewer/stormwater capital
#         backlog (~$1B) amortized over 30 yr ÷ 140,000 connections adds ~$238/yr.
# Covers: water distribution pipe, sewer collection pipe, treatment plant
#         operations — all allocated per household by pipe-length-per-HH model.
# NOTE: MLGW is a separate utility from the City; these costs are included
#       because they represent public infrastructure burden even if not in the
#       general fund. Flag this if comparing to city-budget-only analyses.
# Same anchor/interpolation scheme as roads (band cost at geometric-mean density,
# extended past 12 DU/acre); the distribution/collection mains are shared linear
# infrastructure, so per-household cost keeps amortizing with density.
WATER_SEWER_COST_BY_DENSITY = [
    # Rural extension on the same two-slope basis as roads (mains are linear
    # infrastructure sharing the frontage argument). Only reached by a rural parcel
    # that is actually ON the public network — one on a well and a septic field
    # drops these legs entirely (see public_water / public_sewer in enrich_row).
    (0.025, 3_050),  # ~40-acre parcel (floor anchor)
    (0.05,  2_760),  # ~20-acre
    (0.1,   2_500),  # ~10-acre
    (0.2,   2_250),  # ~5-acre
    (0.35,  1_875),  # ~3-acre
    (0.7,  1_500),
    (1.73, 1_100),
    (4.24,   800),
    (8.49,   500),
    (12.0,   350),
    (24.0,   220),
    (48.0,   135),
    # High-rise densities: the distribution/collection mains keep amortizing, but
    # sewage TREATMENT is per-capita (volume scales with people, not density), so
    # this floors higher than roads — ~$90/HH is the treatment + service-lateral
    # residual that does not shrink with density.
    (96.0,   105),
    (200.0,   90),
]

# ── Split of the water/sewer component into its two legs ──────────────────────
# A parcel can be off the public network on one leg and on it for the other (a
# private well with a public sewer connection, or — far more commonly — public
# water with a septic field), so the combined cost above has to be splittable.
#
# 0.5 is a deliberately coarse split, and it is coarse for a data reason worth
# stating rather than hiding: the bundled Census of Governments crosswalk merges
# function 80 (sewerage) and function 91 (water utilities) into one `water_sewer`
# column, so the county-specific ratio between them is not recoverable at runtime.
# Splitting it properly means rebuilding govfinance_county.csv with the two
# functions kept apart — a separate change. Until then an even split is the
# neutral assumption, and it is applied to BOTH the cost and the fee-revenue side
# so neither is silently favoured.
WATER_LEG_SHARE = 0.5     # water supply / distribution
SEWER_LEG_SHARE = 0.5     # sewerage collection / treatment

# ── Density shape vs. spending level ──────────────────────────────────────────
# A parcel's cost is built from two layers that used to be multiplied together raw:
#
#     cost = shape(parcel_lot_density) x county_multiplier
#
# ``shape`` is the Halifax/Memphis density curve; ``county_multiplier`` is the
# county's per-capita spending on that function relative to Shelby's (Census of
# Governments). Multiplying them DOUBLE-COUNTS ruralness: a rural county's
# per-capita spending is high partly *because* its households are spread out —
# that is much of what the multiplier measures — and the rural end of the curve
# then charges for the same sparseness again. It asserted a rural Monroe County,
# TN household costs the public $9,137/yr in non-school services, implying
# ~$178M/yr of local spending for a county of 47,694 people.
#
# So the shape is expressed RELATIVE to the density that county's own spending was
# observed at:
#
#     cost = shape(parcel) x county_multiplier x shape(D_SHELBY) / shape(d_county)
#
# A parcel at its county's typical density then costs exactly what that county's
# multiplier says, and only its DEVIATION from typical moves it along the curve.
# Shelby is the pilot — multiplier 1.0 by construction, and its own density divides
# out to 1.0 here — so the Memphis calibration is untouched.
#
# Both densities are LOT densities (housing units per acre of the land class they
# occupy, data/county_lot_density.py). That correspondence is the whole point, and
# it is what an earlier attempt got wrong: gross county density — households over
# every acre of dry land — is dominated by how much forest a county contains, so it
# is not the same quantity as a parcel's lot size and cannot share this curve.
#
# The corroboration that this axis is right: Shelby measures 1.41 DU/acre, and the
# Memphis calibration notes at the top of this file independently put the city at
# "roughly 1.0-1.5 DU/acre at the city average". Derived separately, they agree.
SHELBY_LOT_DU_ACRE = 1.411511

# Bounds on the correction. County lot density spans Manhattan (63 DU/acre) to
# frontier counties (0.003), and the curve itself clamps at both ends, so the raw
# ratio is already bounded — but not tightly enough to stop one coarse county-level
# number from dominating every other term. Clamped, it stays a correction rather
# than becoming the model.
DENSITY_NORM_MIN = 0.4
DENSITY_NORM_MAX = 2.5

# ── Fire/EMS base cost ($/household/yr) ───────────────────────────────────────
# Source: Memphis FY2026 budget; Fire/EMS = ~$119M total, ~253,000 HH → $470/HH.
# Rounded up to $800 to include capital (apparatus, stations) and mutual-aid costs
# sourced from: VFIS "Cost of Fire Protection" (2022), national avg $800–$1,200/HH.
# Memphis-calibrated base = $800 (between budget implied and national capital-inclusive).
FIRE_BASE_COST = 800   # $/HH/yr; Memphis-calibrated

# Distance multipliers for fire cost:
#   Parcels >10 mi from core are beyond many Memphis fire station service zones
#   → longer response times → higher effective cost per call served.
#   Parcels <3 mi from core are near multiple downtown stations → lower cost.
# Source: VTPI "Land Use Impacts on Transport" Table 5.4.2 (2019);
#         NFPA "Fire Protection Coverage" distance-cost relationship.
FIRE_DIST_MULTIPLIER_INNER = 0.85   # <3 mi from core
FIRE_DIST_MULTIPLIER_MID   = 1.00   # 3–10 mi from core
FIRE_DIST_MULTIPLIER_OUTER = 1.30   # >10 mi from core

FIRE_INNER_THRESHOLD_MI = 3.0
FIRE_OUTER_THRESHOLD_MI = 10.0

# Density amortization of fire/EMS cost. A large multi-unit building is ONE
# address on ONE hydrant/standpipe within a station's existing coverage area, so
# the fixed coverage + capital share (stations, apparatus) spreads across many
# units. Call volume (the per-capita part) does not amortize, so this floors at
# 0.60 — ~$480/HH, the per-resident response residual. Below 8 DU/acre coverage is
# already dispersed, so no discount. (Directional model; calibrated by inspection,
# same convention as the police density multiplier.)
FIRE_DENSITY_MULTIPLIERS = [
    # (max_du_acre, multiplier)
    (8.0,   1.00),   # <8 DU/acre: dispersed coverage, full per-HH cost
    (16.0,  0.90),   # 8-16: compact
    (48.0,  0.75),   # 16-48: mid-rise / large multiplex
    (float("inf"), 0.60),  # 48+: high-rise, one address in-district (floor)
]

# ── Police cost by density ($/household/yr) ───────────────────────────────────
# Source: Memphis FY2026 budget; Police = ~$147M, ~253,000 HH → $581/HH.
# Rounded to $1,200 to include capital (vehicles, equipment, facilities).
# Low-density areas require more patrol-miles per call, increasing cost/HH.
# National benchmark: ICMA "Cost of Services" survey median $900–$1,400/HH.
# Memphis-calibrated base = $1,200 (higher than budget ratio; capital-inclusive).
POLICE_BASE_COST = 1_200   # $/HH/yr; Memphis-calibrated

POLICE_DENSITY_MULTIPLIERS = [
    # (max_du_acre, multiplier)
    (3.0,  1.20),   # <3 DU/acre: large patrol area per officer
    (8.0,  1.00),   # 3–8 DU/acre: moderate density
    (16.0, 0.80),   # 8–16 DU/acre: compact, efficient patrol
    (float("inf"), 0.70),  # 16+ DU/acre: dense infill, most efficient patrol
]

# ── Sanitation (solid waste) ──────────────────────────────────────────────────
# Source: City of Memphis Solid Waste fee = $42/month (FY2026, Memphis-specific).
# The resident FEE is flat, but the COST to serve is not: a dense building uses
# shared collection (one dumpster/compactor stop for many units vs. per-house
# curbside pickup), so the collection share amortizes with density. Disposal
# (tonnage) is per-capita and does not, so this floors at 0.60. The fiscal_ratio
# models cost-to-serve, so it uses the amortized cost, not the flat fee.
SANITATION_COST = 504   # $/HH/yr = $42 × 12; MEMPHIS-SPECIFIC flat fee
SANITATION_DENSITY_MULTIPLIERS = [
    # (max_du_acre, multiplier)
    (8.0,   1.00),   # <8 DU/acre: curbside per house
    (16.0,  0.85),
    (48.0,  0.70),
    (float("inf"), 0.60),  # 48+: shared compactor, one collection stop (floor)
]

# ── Parks & other general services ───────────────────────────────────────────
# Source: Memphis FY2026 budget; Parks + libraries + general govt = ~$75M
#         ÷ 253,000 HH ≈ $296/HH. Rounded to $300.
# Applied as flat rate (park access is not strongly density-dependent in
# Memphis's distributed park system; national benchmarks also show ~flat).
# National benchmark: Trust for Public Land "City Park Facts" (2023) avg $280–$350/HH.
PARKS_OTHER_COST = 300   # $/HH/yr; Memphis-calibrated (flat)

# ── Fiscal balance rating thresholds (fiscal_ratio) ──────────────────────────
# Interpretation: fiscal_ratio = (property_tax + user fees) / infra_cost
#   >1.0  = property generates more revenue than it costs to serve (net contributor)
#   0.75–1.0  = roughly break-even (within ±25% of cost recovery)
#   0.40–0.75 = minor burden (city subsidizes 25–60% of cost)
#   <0.40     = major burden (city subsidizes 60%+ of cost)
# Thresholds calibrated by inspection of pilot distribution; intended for
# relative comparison, not absolute policy determination.
RATING_THRESHOLDS = [
    (1.00, "net contributor"),
    (0.75, "break-even"),
    (0.40, "minor burden"),
    (0.00, "major burden"),
]


# ══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def interp_cost(density: float, anchors: list[tuple]) -> float:
    """Log-log linear interpolation of per-household cost vs density.

    ``anchors`` is an ascending list of (du_acre, cost) points. Between anchors,
    both axes are interpolated in log space (cost falls smoothly as a power of
    density); outside the anchor range the cost is clamped flat to the nearest
    endpoint. A continuous curve (vs the old step tiers) means every added unit
    moves the cost, and extending the anchors past 12 DU/acre keeps crediting
    denser infill instead of flooring at a triplex.
    """
    if density <= anchors[0][0]:
        return float(anchors[0][1])
    if density >= anchors[-1][0]:
        return float(anchors[-1][1])
    for (d_lo, c_lo), (d_hi, c_hi) in zip(anchors, anchors[1:]):
        if d_lo <= density <= d_hi:
            t = (math.log(density) - math.log(d_lo)) / (math.log(d_hi) - math.log(d_lo))
            return float(math.exp(math.log(c_lo) + t * (math.log(c_hi) - math.log(c_lo))))
    return float(anchors[-1][1])


def density_multiplier(density: float, table: list[tuple]) -> float:
    """Look up a stepwise density multiplier: the first (max_du_acre, mult) band
    whose max exceeds ``density`` (used by police, fire, and sanitation)."""
    for max_du, mult in table:
        if density < max_du:
            return mult
    return table[-1][1]


def _fee_rate(value) -> float:
    """Coerce one ``fee_recovery`` entry to a usable rate in [0, 1].

    ``enrich_row`` is importable, so this dict can arrive from somewhere other than
    the govfinance crosswalk that normally sanitizes it. A missing, ``None``,
    non-numeric, or NaN entry reads as 0.0 — no fee credit, which reproduces the
    tax-only behavior rather than raising. The 100% cap is enforced here too, so the
    documented "never credit a home with a utility surplus" invariant holds at the
    point of use and not only at the loader.
    """
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 0.0
    if rate != rate:                      # NaN (min/max would pass it through)
        return 0.0
    return min(max(rate, 0.0), 1.0)


def police_cost(base: float, density: float) -> float:
    """Apply density multiplier to base police cost."""
    return base * density_multiplier(density, POLICE_DENSITY_MULTIPLIERS)


def density_normalizer(county_du_acre: float | None) -> float:
    """``shape(D_SHELBY) / shape(county_du_acre)``, clamped.

    Returns 1.0 for an unknown county — no correction, the pre-existing behaviour —
    so a missing crosswalk row degrades to the old model rather than a wrong one.

    The ROAD curve is the reference shape for every component. Using each
    component's own curve would make the correction depend on which service is
    being priced, but what is being corrected — how spread out this county's
    households are — is one property of the county, not six.
    """
    if county_du_acre is None or county_du_acre <= 0:
        return 1.0
    county_shape = interp_cost(county_du_acre, ROAD_COST_BY_DENSITY)
    if county_shape <= 0:
        return 1.0
    ratio = interp_cost(SHELBY_LOT_DU_ACRE, ROAD_COST_BY_DENSITY) / county_shape
    return min(max(ratio, DENSITY_NORM_MIN), DENSITY_NORM_MAX)



def fiscal_rating(ratio: float) -> str:
    """Map fiscal_ratio to human-readable burden rating."""
    for threshold, label in RATING_THRESHOLDS:
        if ratio >= threshold:
            return label
    return "major burden"


def _fire_dist_multiplier(dist_mi: float) -> float:
    """Return the correct fire multiplier for a given distance."""
    if dist_mi < FIRE_INNER_THRESHOLD_MI:
        return FIRE_DIST_MULTIPLIER_INNER
    if dist_mi < FIRE_OUTER_THRESHOLD_MI:
        return FIRE_DIST_MULTIPLIER_MID
    return FIRE_DIST_MULTIPLIER_OUTER


# ══════════════════════════════════════════════════════════════════════════════
# Row-level enrichment
# ══════════════════════════════════════════════════════════════════════════════

def enrich_row(row: pd.Series, *,
               core_lat: float = MEMPHIS_CORE_LAT,
               core_lon: float = MEMPHIS_CORE_LON,
               assess_ratio: float = RESIDENTIAL_ASSESS_RATIO,
               tax_rate: float = CITY_TAX_RATE,
               in_urban_area: bool | None = None,
               cost_multipliers: dict | None = None,
               fee_recovery: dict | None = None,
               units: int = 1,
               county_du_acre: float | None = None,
               incorporated: bool = True,
               public_water: bool = True,
               public_sewer: bool = True,
               owner_occupied: bool | None = None,
               separately_parceled: bool | None = None,
               classification_state: str | None = CLASSIFICATION_STATE,
               classification_rate_state: str | None = None,
               classification_county_fips: str | None = None) -> pd.Series:
    """Compute all infrastructure cost and revenue fields for a single parcel row.

    Memphis defaults reproduce the Shelby pilot. For other locations the simulator
    passes a national-average parameterization: a national effective property-tax
    rate (``assess_ratio`` × ``tax_rate``) and, when ``in_urban_area`` is given,
    an urban/rural fire multiplier in place of distance-to-the-Memphis-core.

    ``cost_multipliers`` optionally recalibrates the per-household cost *levels* to
    a specific county's local-government spending (from the Census of Governments
    crosswalk, ``data/govfinance.py``): a dict with any of the keys ``roads``,
    ``water_sewer``, ``fire``, ``police``, ``sanitation``, ``parks``, each scaling
    that component. The Memphis-calibrated curves give the density *shape*; these
    multipliers give the local *level* (1.0 = Shelby pilot, the default).

    ``fee_recovery`` is the same six keys again, each the share of that service's
    cost residents already pay through user charges rather than property tax (also
    from the Census of Governments crosswalk). It converts the parcel's modeled cost
    into modeled fee revenue, which joins property tax in the fiscal-ratio numerator
    so both sides of the ratio cover the same services. Defaults to the Shelby
    pilot's own recovery rates.

    ``county_du_acre`` is the county's typical LOT density (data/county_lot_density),
    used to express the density shape relative to the density the county's spending
    multiplier was measured at, so ruralness is not counted twice — see
    ``density_normalizer`` and the ``SHELBY_LOT_DU_ACRE`` block comment. Left None
    the correction is 1.0 and the model behaves exactly as it did before.

    ``incorporated`` says whether the parcel sits inside an incorporated
    municipality (Census TIGER PLACE; see ``simulate/location.py``). Outside one,
    the county is the parcel's general-purpose government and no city serves it.
    Today this gates exactly one component — **sanitation** — and deliberately no
    others:

      * Municipal curbside collection stops at the city limit. Unincorporated
        county residents haul to a convenience centre or contract a private hauler
        privately; either way it is not a public cost allocated to that parcel, and
        the trash fee that recovers it is not paid to a city. So the cost and its
        fee revenue both leave, the same treatment a well and a septic field get.
      * Roads, fire, police and parks are NOT gated, because the county genuinely
        provides all four outside the city limit — a sheriff patrols, a volunteer
        or county department answers fires, the county maintains the road. What is
        wrong for those is the *level* (a county's share is thinner than a city's),
        not the existence, and correcting a level needs the county government's
        share of local direct expenditure — a field the bundled Census of
        Governments crosswalk does not carry. Gating them on/off would trade an
        overstatement for a bigger understatement.

    ``public_water`` / ``public_sewer`` say whether the parcel is actually connected
    to the public network. A home on a private well and a septic field receives no
    public water or sewer service, so charging it the modeled water/sewer cost bills
    it for infrastructure that was never built to it. Each leg that is off the
    network drops its share (``WATER_LEG_SHARE`` / ``SEWER_LEG_SHARE``) from the
    cost — and, because that leg is ~100% fee-recovered, from the modeled fee
    revenue too. Dropping only the cost would hand a rural parcel a utility bill it
    doesn't pay as revenue; dropping both keeps the ratio honest, and it usually
    moves the ratio DOWN, since the fee leg was carrying its own cost.

    ``units`` / ``owner_occupied`` / ``classification_state`` drive the property-tax
    *classification*: in Tennessee a parcel with two or more rental units is
    assessed at the 40% commercial ratio rather than 25% residential, so a rental
    apartment building generates 1.6x the tax the flat residential ratio implied.
    Pass ``classification_state=None`` to disable — required when ``tax_rate`` is an
    observed effective rate rather than a statutory levy, since an observed rate
    already embeds whatever classification produced it (see ``data/assessment.py``).
    """
    # Guard before computing anything: the two classification paths are alternatives, and
    # a caller wiring up both would apply the correction twice (1.6 x 1.6 = 2.56 in
    # Tennessee) — the exact silent over-correction this split exists to prevent. A loud
    # failure in a pure function is cheap; a silent precedence rule is not auditable.
    if classification_state and classification_rate_state:
        raise ValueError(
            "classification_state (statutory, absolute) and classification_rate_state "
            "(observed-rate, multiplicative) are alternatives — pass one, not both, or "
            "the classification correction is applied twice.")

    mult = cost_multipliers or {}
    fees = SHELBY_FEE_RECOVERY if fee_recovery is None else fee_recovery

    # ── Density metric ─────────────────────────────────────────────────────────
    acres = row["CALC_ACRE"]
    # Guard against zero/negative acres (data error); treat as very small lot
    if pd.isna(acres) or acres <= 0:
        acres = 0.01
    # Assuming 1 dwelling unit per parcel (single-family / DWELDAT record)
    lot_density = 1.0 / acres   # DU/acre

    # ── Fire service multiplier: urban-area flag (national) or core distance ────
    dist_mi = float("nan")
    if in_urban_area is not None:
        fire_mult = FIRE_DIST_MULTIPLIER_MID if in_urban_area else FIRE_DIST_MULTIPLIER_OUTER
    else:
        lat, lon = row["latitude"], row["longitude"]
        dist_mi = (5.0 if pd.isna(lat) or pd.isna(lon)
                   else haversine_miles(lat, lon, core_lat, core_lon))
        fire_mult = _fire_dist_multiplier(dist_mi)

    # ── Cost components ────────────────────────────────────────────────────────
    # Each density/urban-shape cost is scaled by the county's local-spending
    # multiplier (default 1.0 = Shelby pilot calibration), then by the density
    # normalizer so that multiplier is not applied on top of a shape already
    # charging for the same ruralness.
    dnorm = density_normalizer(county_du_acre)
    cost_roads       = interp_cost(lot_density, ROAD_COST_BY_DENSITY) * mult.get("roads", 1.0) * dnorm
    # Only the legs the parcel is actually connected to are a public cost to serve.
    public_share = ((WATER_LEG_SHARE if public_water else 0.0)
                    + (SEWER_LEG_SHARE if public_sewer else 0.0))
    cost_water_sewer = (interp_cost(lot_density, WATER_SEWER_COST_BY_DENSITY)
                        * mult.get("water_sewer", 1.0) * public_share * dnorm)
    cost_fire        = (FIRE_BASE_COST * fire_mult
                        * density_multiplier(lot_density, FIRE_DENSITY_MULTIPLIERS)
                        * mult.get("fire", 1.0) * dnorm)
    cost_police      = police_cost(POLICE_BASE_COST, lot_density) * mult.get("police", 1.0) * dnorm
    # Curbside collection is a municipal service; outside a city there is none to
    # allocate. Zeroing the cost also zeroes its fee revenue below (est_fees is
    # computed from the components), which is the point — an unincorporated
    # household pays no city trash fee either.
    cost_sanitation  = (float(SANITATION_COST)
                        * density_multiplier(lot_density, SANITATION_DENSITY_MULTIPLIERS)
                        * mult.get("sanitation", 1.0) * dnorm) if incorporated else 0.0
    cost_parks       = float(PARKS_OTHER_COST) * mult.get("parks", 1.0)

    components = {
        "roads": cost_roads, "water_sewer": cost_water_sewer, "fire": cost_fire,
        "police": cost_police, "sanitation": cost_sanitation, "parks": cost_parks,
    }
    total_infra = sum(components.values())

    # ── User-fee revenue estimate ──────────────────────────────────────────────
    # Each service's modeled cost times the share of that service residents fund
    # through charges. Water/sewer and trash are nearly all fee-funded; fire and
    # police are not fee-funded at all. Without this term the denominator counted
    # services the numerator had no way to be paid for.
    est_fees = sum(cost * _fee_rate(fees.get(name)) for name, cost in components.items())

    # ── Property tax revenue estimate ──────────────────────────────────────────
    appraised = row["RTOTAPR"]
    if pd.isna(appraised) or appraised <= 0:
        appraised = 0.0
    # Classification, by whichever path the caller is on.
    #
    # Statutory path: a 2+ rental-unit parcel in Tennessee is assessed at the 40%
    # commercial ratio, not 25% residential. Returns None unless the parcel is actually
    # reclassified, so ordinary housing — and any caller supplying its own assessment
    # basis — keeps the ratio it passed in.
    commercial = classified_assess_ratio(
        classification_state, units, owner_occupied=owner_occupied,
        separately_parceled=separately_parceled, county_fips=classification_county_fips)
    effective_assess_ratio = assess_ratio if commercial is None else commercial
    # Observed-rate path: tax_rate is an ACS effective rate measured over owner-occupied
    # homes, so it already carries the residential class in its denominator. The correction
    # is the ratio BETWEEN the classes, applied to the rate. 1.0 unless reclassified.
    class_mult = classification_multiplier(
        classification_rate_state, units, owner_occupied=owner_occupied,
        separately_parceled=separately_parceled, county_fips=classification_county_fips)
    est_tax = appraised * effective_assess_ratio * tax_rate * class_mult

    # ── Fiscal balance ─────────────────────────────────────────────────────────
    est_revenue = est_tax + est_fees
    fiscal_bal = est_revenue - total_infra
    if total_infra > 0:
        ratio = est_revenue / total_infra
    else:
        ratio = float("nan")

    rating = fiscal_rating(ratio) if not math.isnan(ratio) else "unknown"

    return pd.Series({
        "lot_density_du_acre":   round(lot_density, 4),
        "distance_to_core_mi":   round(dist_mi, 3),
        "infra_cost_roads":      round(cost_roads, 2),
        "infra_cost_water_sewer": round(cost_water_sewer, 2),
        "infra_cost_fire":       round(cost_fire, 2),
        "infra_cost_police":     round(cost_police, 2),
        "infra_cost_sanitation": round(cost_sanitation, 2),
        "infra_cost_parks":      round(cost_parks, 2),
        "est_annual_infra_cost": round(total_infra, 2),
        "est_property_tax":      round(est_tax, 2),
        "est_fee_revenue":       round(est_fees, 2),
        "est_total_revenue":     round(est_revenue, 2),
        "assess_ratio_applied":  round(effective_assess_ratio, 4),
        "classification_multiplier_applied": round(class_mult, 4),
        "fiscal_balance":        round(fiscal_bal, 2),
        "fiscal_ratio":          round(ratio, 4),
        "infra_burden_rating":   rating,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

ADDED_COLUMNS = [
    "lot_density_du_acre", "distance_to_core_mi",
    "infra_cost_roads", "infra_cost_water_sewer",
    "infra_cost_fire", "infra_cost_police",
    "infra_cost_sanitation", "infra_cost_parks",
    "est_annual_infra_cost", "est_property_tax",
    "est_fee_revenue", "est_total_revenue", "assess_ratio_applied",
    "classification_multiplier_applied",
    "fiscal_balance", "fiscal_ratio", "infra_burden_rating",
]


def _as_bool(v) -> bool:
    """Parse a CSV cell into a bool. Python treats every non-empty string as
    truthy, so ``"False"``/``"0"``/``"no"`` would wrongly read as urban — handle
    the common string forms explicitly, else fall back to ``bool(v)`` (numbers,
    real bools)."""
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "t"):
            return True
        if s in ("false", "0", "no", "n", "f", ""):
            return False
    return bool(v)
