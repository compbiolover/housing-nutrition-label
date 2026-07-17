#!/usr/bin/env python3
"""Environmental-footprint scoring model library.

Models a parcel's environmental footprint (operational + embodied carbon and
water use) from its CAMA fields and the modeled energy estimates (est_annual_kwh /
est_annual_therms). Import ``model_parcel_environment`` to score a single parcel.

Methodology
-----------
  Three components, each grounded in published sources (see
  research/environmental-footprint-research.md for the full citation trail and the
  adversarial fact-check that backs every constant below):

  1. OPERATIONAL CARBON (strongest data leg)
     Convert the already-modeled annual energy use to CO2e with authoritative
     emission factors, split into an AVERAGE-rate leg for the energy the home
     consumes and a MARGINAL-rate credit for the energy it avoids:
       operational = consumed_kwh * EF_GRID_avg
                   + avoided_kwh * (EF_GRID_avg - EF_GRID_marginal)
                   + est_annual_therms * EF_GAS
     where avoided_kwh = baseline_kwh - consumed_kwh, the baseline being the SAME
     home with a standard envelope (no ICF/SIP/passive efficiency factor) and no
     rooftop solar. Rationale: a kWh the home no longer draws turns off *marginal*
     generation, not the average mix, so efficiency/solar savings are worth the
     marginal rate, while the kWh it still consumes carry the grid average. This
     reduces exactly to consumed_kwh * EF_GRID_avg (today's number) when the
     marginal rate equals the average or no avoided kWh exist — see the
     reduces-to-average test.
     EF_GRID_avg = 0.4097 kg CO2e/kWh — EPA eGRID2023 Rev 2, subregion SRTV (SERC
     Tennessee Valley), the correct subregion for the Memphis/TVA grid (903.306 lb
     CO2e/MWh). Matches data/egrid.py's SRTV factor exactly. Per location the live
     path passes the county's own eGRID subregion average (data/egrid.py) and its
     long-run marginal rate (data/cambium.py — NREL Cambium 2023 LRMER, Combustion
     CO2e so it shares eGRID's stack-emissions basis; CONUS only, average-only
     fallback elsewhere).
     EF_GAS  = 5.3 kg CO2e/therm — EPA GHG Emission Factors Hub.
     (Location-based. TVA self-reports a lower system rate but it is not
     apples-to-apples with eGRID; eGRID SRTV is the standard. Treat as dated
     constants — refresh on each eGRID / Cambium release; the grid is decarbonizing.)

  2. EMBODIED CARBON (bottom-up, EPD-grounded, geometry-aware)
     Built up from published industry-average EPD GWP factors (concrete, steel,
     lumber, gypsum, insulation, cladding, roofing, glazing) applied to the home's
     OWN geometry: a foundation term from footprint slab + perimeter walls (× actual
     or per-BSMT basement depth) + footings — the dominant driver of residential
     embodied carbon (Jungclaus et al. 2024) — plus roof (roof area), envelope (wall
     area × EXTWALL type), and interior (floor area) terms. Smaller / single-story
     homes carry more envelope + foundation per m2 of floor (Rauf et al. 2025). Then
     nudged by GRADE and amortized over SERVICE LIFE. See data/embodied_carbon.py and
     research/embodied-carbon-geometry-research.md:
       embodied_total  = embodied_intensity(EXTWALL, GRADE, BSMT, floor_area,
                                             stories, basement_depth) * floor_area_m2
       embodied_annual = embodied_total / service_life_years(EXTWALL)
     The sub-score is computed on the per-year intensity (kgCO2e/m2/yr), so a
     longer-lived shell (masonry/concrete/ICF ~100yr) is rewarded for spreading
     its upfront carbon over more years, calibrated so a 60-yr shell is unchanged.
     See SERVICE_LIFE_BY_WALL for the basis and caveats (the standardized EN 15978
     approach instead uses a fixed period with replacement cycles).
     NOTE: the claim that embodied dominates operational over a building's life was
     refuted for this grid — operational stays the heavier-weighted leg.

  3. WATER USE (locally favorable)
     EPA WaterSense benchmarks. Indoor use scales with occupancy (RMBED+1 proxy)
     and fixture count (FIXBATH); outdoor use scales with irrigable lot area
     (CALC_ACRE minus building footprint, capped, outlier-aware). Embedded
     water-carbon is LOW here because Memphis draws minimally-treated artesian
     water from the Memphis Sand aquifer:
       water_co2e = (water_gal / 1000) * WATER_EMBEDDED_KWH_PER_KGAL * EF_GRID

  SCORING
     Each component is normalized to a 0-100 sub-score against published "good vs
     poor" benchmarks (log-linear interpolation; higher score = lower footprint),
     then blended into a composite weighted 0.50 operational / 0.30 embodied /
     0.20 water — operational heaviest (dominant, best-measured), embodied
     moderate (EPD-grounded), water lightest (locally low-carbon). A parcel with no
     living-area (SFLA) — i.e. vacant / non-residential land — is left unscored
     (NaN), the same ~280 parcels that lack all CAMA building data.

  Upgrade path: meter-read MLGW utility + water data; per-home LCA takeoffs via
  BEAM / Athena (finer than the shared residential archetype used here); foundation
  concrete from actual basement depth; parcel-level irrigation from remote sensing.
  See the research docs.

Columns added
-------------
  env_operational_co2e_kg_yr   Annual operational emissions (kg CO2e/yr)
  env_embodied_co2e_kg_yr      Annualized embodied emissions (kg CO2e/yr, over RSP)
  env_embodied_intensity_kgm2  Total embodied intensity (kg CO2e/m2) — the 39-121 metric
  env_water_gal_yr             Estimated annual water use (gallons/yr)
  env_water_co2e_kg_yr         Annual embedded water emissions (kg CO2e/yr)
  env_total_co2e_kg_yr         operational + embodied(annual) + water (kg CO2e/yr)
  env_operational_subscore     0-100 (higher = lower operational footprint)
  env_embodied_subscore        0-100 (higher = lower embodied footprint)
  env_water_subscore           0-100 (higher = lower water footprint)
  environmental_score          0-100 composite (NaN if unscored)
  env_data_source              Citation + eGRID vintage + embodied confidence flag
"""

import numpy as np
import pandas as pd

# ── Emission factors (verified — see research doc) ────────────────────────────
EF_GRID_KG_PER_KWH   = 0.4097  # EPA eGRID2023 Rev 2 SRTV: 903.306 lb CO2e/MWh (matches data/egrid.py)
EF_GAS_KG_PER_THERM  = 5.3     # EPA GHG Emission Factors Hub (2025; natural-gas factor unchanged)
EGRID_VINTAGE        = "eGRID2023 Rev 2 SRTV"

# ── Embodied carbon ───────────────────────────────────────────────────────────
RSP_YEARS = 60.0   # EN 15978 / RICS reference study period (legacy constant)
SQFT_TO_M2 = 0.092903

# ── Service life by wall/structure type (years) ───────────────────────────────
# Embodied carbon is amortized per year of service: a longer-lived shell spreads
# its upfront embodied carbon over more years (kgCO2e/m2/yr), so durable
# construction is rewarded environmentally rather than only on the Durability
# dimension. Typical/reference service lives (ISO 15686 service-life planning;
# Athena Institute and national WLCA reference lives): light wood frame ~60 yr;
# brick veneer / stucco / EIFS ~70 yr; solid masonry / concrete / ICF / stone
# ~100 yr.
#
# CAVEATS (deliberately kept conservative): standardized WLCA (EN 15978 / RICS)
# instead holds a fixed study period and books replacement cycles (Module B4) to
# credit longevity — per-year amortization is the simpler defensible alternative
# used here. Real building lifespans are often governed by demolition /
# obsolescence rather than material durability, and per-year amortization
# understates the near-term impact of the upfront carbon spike.
DEFAULT_SERVICE_LIFE_YR = 60.0
SERVICE_LIFE_BY_WALL = {
    7:  60.0,   # frame / wood
    5:  60.0,   # aluminum / vinyl (light frame)
    9:  70.0,   # brick veneer
    8:  70.0,   # stucco
    10: 70.0,   # EIFS
    1:  100.0,  # solid brick
    3:  100.0,  # block / concrete (incl. ICF, mapped to this code)
    4:  100.0,  # stone
}
# Amortization is calibrated to a 60-yr reference so a 60-yr shell keeps its
# previous embodied sub-score; only longer-/shorter-lived shells move.
EMB_REF_PERIOD_YR = 60.0

# Embodied intensity (kg CO2e/m2) is now built up bottom-up from published
# industry-average EPD factors x a representative residential material takeoff,
# split into a foundation term (BSMT) and a shell term (EXTWALL). See
# data/embodied_carbon.py for the model and research/embodied-carbon-research.md
# for the factor-by-factor provenance. EC_INTENSITY_DEFAULT (unknown wall +
# unknown foundation) is re-exported so callers/tests keep a stable name.
from housing_label.data.embodied_carbon import (   # noqa: E402
    EC_INTENSITY_DEFAULT as EC_INTENSITY_DEFAULT,   # re-exported for callers/tests
    embodied_intensity_kgm2,
)

# GRADE (construction quality) nudge: higher grade ⇒ more/heavier finishes ⇒ more
# embodied. Linear around midpoint 40, clamped to ±10%.
GRADE_MIDPOINT = 40.0
GRADE_SLOPE    = 0.0033
GRADE_MIN_F, GRADE_MAX_F = 0.90, 1.10

# ── Water (EPA WaterSense benchmarks) ─────────────────────────────────────────
INDOOR_GPCD            = 75.0   # modeled indoor gallons/capita/day (EPA ~82 nominal)
DEFAULT_OCCUPANCY      = 2.65   # avg US household when RMBED is missing
OUTDOOR_GAL_PER_SQFT_YR = 2.0   # modeled irrigation over irrigable lot area
IRRIGABLE_CAP_SQFT     = 43560.0   # cap irrigable area at 1 acre (outlier guard)
# Embedded energy of supply + treatment + distribution + wastewater, per 1,000
# gallons. National-average default (~4-15 kWh/kgal across the energy-water-nexus
# literature; pumping-heavy/arid regions run high, minimal-treatment groundwater
# low). A coarse national estimate pending a regional table; only affects the
# reported total-CO2e figure (the water sub-score is consumption/gpcd based).
WATER_EMBEDDED_KWH_PER_KGAL = 8.0

# ── Sub-score breakpoints (lower footprint metric → higher 0-100 score) ───────
# Operational emissions intensity, kg CO2e/m2/yr:
OP_XS = [10.0, 20.0, 35.0, 50.0, 70.0, 100.0]
OP_YS = [100.0, 80.0, 60.0, 40.0, 20.0, 0.0]
# Embodied intensity, kg CO2e/m2 (A1-A3). Anchored to the geometry-aware model's
# actual distribution of US single-family homes: a low-carbon home (compact,
# multi-story, slab, wood) lands near ~55 and a high-carbon one (masonry over a full
# basement) near ~210 — spanning the empirical Jungclaus/RMI/BFCA band. (The prior
# 40-120 band was calibrated to the earlier model that under-counted the foundation;
# keeping it would push every home to the low-scoring end rather than discriminate.)
EMB_XS = [55.0, 95.0, 135.0, 175.0, 210.0]
EMB_YS = [100.0, 75.0, 50.0, 25.0, 0.0]
# Annualized embodied breakpoints (kg CO2e/m2/yr) = total breakpoints ÷ the 60-yr
# reference period, so the embodied sub-score is scored on per-year intensity.
EMB_XS_ANNUAL = [x / EMB_REF_PERIOD_YR for x in EMB_XS]
# Water use, gallons/capita/day:
WAT_XS = [40.0, 60.0, 90.0, 130.0, 180.0]
WAT_YS = [100.0, 80.0, 55.0, 30.0, 0.0]

# ── Composite weights ─────────────────────────────────────────────────────────
W_OPERATIONAL = 0.50
W_EMBODIED    = 0.30
W_WATER       = 0.20

ENV_COLS = [
    "env_operational_co2e_kg_yr",
    "env_embodied_co2e_kg_yr",
    "env_embodied_intensity_kgm2",
    "env_service_life_yr",
    "env_water_gal_yr",
    "env_water_co2e_kg_yr",
    "env_total_co2e_kg_yr",
    "env_operational_subscore",
    "env_embodied_subscore",
    "env_water_subscore",
    "environmental_score",
    "env_data_source",
]

_EMBODIED_WATER_SOURCE = (
    "Embodied: bottom-up A1-A3 from industry-average EPD factors x per-home "
    "geometry (foundation from footprint+perimeter x basement depth, roof/envelope/"
    "interior by area), amortized over service life (60-100yr), scored per "
    "kgCO2e/m2/yr (modeled, EPD-grounded); "
    "Water: EPA WaterSense + Memphis Sand aquifer low embedded energy"
)

# Module-level default citation (pilot/batch path: grid average only, no marginal
# credit). The live per-location path builds a citation via _data_source that also
# names the Cambium marginal rate when avoided kWh are credited.
DATA_SOURCE = (
    f"Operational: EPA {EGRID_VINTAGE} {EF_GRID_KG_PER_KWH} kgCO2e/kWh "
    f"+ EPA gas {EF_GAS_KG_PER_THERM} kgCO2e/therm; " + _EMBODIED_WATER_SOURCE
)


def _data_source(grid_factor: float, grid_marginal_factor: float | None,
                 avoided_kwh: float) -> str:
    """Per-call env_data_source citation; names the Cambium marginal rate only
    when it actually moves the number — i.e. some kWh are avoided AND the marginal
    rate differs from the average (a zero credit, including the reduce-to-average
    case where marginal == average, keeps the citation to the eGRID average)."""
    op = f"Operational: EPA {EGRID_VINTAGE} {grid_factor} kgCO2e/kWh avg"
    if (grid_marginal_factor is not None and (avoided_kwh or 0.0)
            and grid_marginal_factor != grid_factor):
        op += (f" + avoided kWh at NREL Cambium 2023 LRMER "
               f"{grid_marginal_factor} kgCO2e/kWh marginal")
    op += f" + EPA gas {EF_GAS_KG_PER_THERM} kgCO2e/therm; "
    return op + _EMBODIED_WATER_SOURCE


# ── Helpers ──────────────────────────────────────────────────────────────────
def _num(v):
    """Coerce to float or return None for missing/non-numeric."""
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _loglin_score(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear score in log10(x) space; clamps to the end values."""
    xv = max(x, 1e-9)
    return float(np.interp(np.log10(xv), np.log10(xs), ys))


def embodied_intensity(extwall, grade, bsmt=None, floor_area_m2=None,
                       stories=None, basement_depth_m=None, footprint_area_m2=None,
                       footprint_perimeter_m=None) -> float:
    """EXTWALL + BSMT + home geometry + GRADE → embodied intensity (kg CO2e/m2).

    Base intensity is the geometry-aware bottom-up build-up (``data/embodied_carbon``:
    foundation from footprint/perimeter × basement depth, roof from roof area,
    envelope from wall area, interior from floor area). A real footprint
    (``footprint_area_m2`` + ``footprint_perimeter_m``, e.g. USA Structures) replaces
    the shape-factor/stories estimate when available. GRADE (construction quality)
    then nudges it ±10% around the average, since higher-grade homes carry more/
    heavier finishes."""
    base = embodied_intensity_kgm2(extwall, bsmt, floor_area_m2=floor_area_m2,
                                   stories=stories, basement_depth_m=basement_depth_m,
                                   footprint_area_m2=footprint_area_m2,
                                   footprint_perimeter_m=footprint_perimeter_m)
    g = _num(grade)
    if g is not None:
        f = 1.0 + (g - GRADE_MIDPOINT) * GRADE_SLOPE
        base *= min(GRADE_MAX_F, max(GRADE_MIN_F, f))
    return base


def service_life_years(extwall) -> float:
    """Expected structural service life (years) for an EXTWALL code, used to
    amortize embodied carbon per year of service."""
    code = _num(extwall)
    if code is None:
        return DEFAULT_SERVICE_LIFE_YR
    return SERVICE_LIFE_BY_WALL.get(int(code), DEFAULT_SERVICE_LIFE_YR)


def water_use_gal_yr(rmbed, fixbath, sfla, stories, calc_acre, acre_outlier,
                     is_multifamily: bool = False) -> tuple[float, float]:
    """Return (annual water gallons, occupancy). Indoor by occupancy+fixtures,
    outdoor by irrigable lot area.

    ``is_multifamily`` drops the private-yard outdoor irrigation: a unit in a
    stacked or attached multi-unit building doesn't have the single-family private
    yard this model otherwise imputes from the (per-unit) lot area — any shared
    landscaping is common area, not the unit's own irrigation load."""
    rb = _num(rmbed)
    occupancy = (rb + 1.0) if rb is not None else DEFAULT_OCCUPANCY

    fb = _num(fixbath)
    fixture_factor = 1.0
    if fb is not None:
        fixture_factor = min(1.2, max(0.9, 1.0 + 0.05 * (fb - 2.0)))

    indoor = occupancy * INDOOR_GPCD * fixture_factor * 365.0

    # Outdoor: irrigable area = lot − building footprint, capped at 1 acre and
    # guarded against the institutional acre outliers. A multi-unit building's
    # representative unit carries no private yard, so its outdoor load is dropped.
    outdoor = 0.0
    acre = _num(calc_acre)
    if not is_multifamily and acre is not None and not (
            acre_outlier is True or str(acre_outlier).lower() == "true"):
        lot_sqft = acre * 43560.0
        area = _num(sfla) or 0.0
        st = _num(stories) or 1.0
        footprint = area / max(st, 1.0)
        irrigable = min(IRRIGABLE_CAP_SQFT, max(0.0, lot_sqft - footprint))
        outdoor = irrigable * OUTDOOR_GAL_PER_SQFT_YR

    return indoor + outdoor, occupancy


# ── Per-parcel model ──────────────────────────────────────────────────────────
def model_parcel_environment(row: pd.Series,
                             grid_factor: float = EF_GRID_KG_PER_KWH,
                             water_embedded_kwh_per_kgal: float = WATER_EMBEDDED_KWH_PER_KGAL,
                             is_multifamily: bool = False,
                             grid_marginal_factor: float | None = None,
                             avoided_kwh: float = 0.0) -> dict:
    """Compute environmental-footprint metrics. Returns all-None when the parcel
    has no living area (vacant / non-residential).

    `grid_factor` is the grid CO2 emission factor (kgCO2e/kWh) for the location —
    the eGRID subregion **average**; defaults to the Shelby/TVA eGRID value used
    by the pilot pipeline.
    `grid_marginal_factor` is the long-run **marginal** grid factor (NREL Cambium
    LRMER, kgCO2e/kWh) used to credit `avoided_kwh` — the kWh the home no longer
    draws (rooftop solar + envelope/passive efficiency) relative to a standard-
    envelope, no-solar baseline of the same home. Consumed kWh (``est_annual_kwh``)
    are booked at the average; the avoided reduction is credited at the marginal
    rate, since it turns off marginal, not average, generation. When None (e.g.
    outside CONUS Cambium regions) the marginal rate defaults to the average, so
    the operational leg reduces exactly to consumed × average — today's number.
    `water_embedded_kwh_per_kgal` is the embedded energy of water/wastewater;
    defaults to a national average (a regional table can override it later).
    `is_multifamily` drops the private-yard outdoor irrigation for a unit in a
    stacked/attached multi-unit building (no private yard).
    """
    sfla = _num(row.get("SFLA"))
    if sfla is None or sfla <= 0:
        return {c: None for c in ENV_COLS}

    floor_m2 = sfla * SQFT_TO_M2

    # --- Operational ---
    # Consumed kWh at the grid AVERAGE; the reduction from the standard-envelope,
    # no-solar baseline (avoided_kwh) credited at the long-run MARGINAL rate, since
    # avoided load turns off marginal generation, not the average mix. Reduces to
    # consumed × average when marginal == average (or no marginal / no avoided).
    kwh    = _num(row.get("est_annual_kwh")) or 0.0
    therms = _num(row.get("est_annual_therms")) or 0.0
    marginal = grid_marginal_factor if grid_marginal_factor is not None else grid_factor
    # Clamp to >= 0: the parameter means "kWh avoided", so a negative value (a
    # caller bug, or a home that somehow uses more than its standard-envelope
    # baseline) must not be credited as extra consumption.
    avoided  = max(0.0, _num(avoided_kwh) or 0.0)
    operational = (kwh * grid_factor
                   + avoided * (grid_factor - marginal)
                   + therms * EF_GAS_KG_PER_THERM)
    op_intensity = operational / floor_m2

    # --- Embodied (amortized over the shell's service life, not a flat period) ---
    emb_intensity = embodied_intensity(
        row.get("EXTWALL"), row.get("GRADE"), row.get("BSMT"),
        floor_area_m2=floor_m2, stories=row.get("STORIES"),
        basement_depth_m=row.get("basement_depth_m"),
        footprint_area_m2=row.get("footprint_area_m2"),
        footprint_perimeter_m=row.get("footprint_perimeter_m"))
    service_life = service_life_years(row.get("EXTWALL"))
    emb_total  = emb_intensity * floor_m2
    emb_annual = emb_total / service_life
    emb_annual_intensity = emb_intensity / service_life   # kg CO2e/m2/yr

    # --- Water ---
    water_gal, occupancy = water_use_gal_yr(
        row.get("RMBED"), row.get("FIXBATH"), sfla,
        row.get("STORIES"), row.get("CALC_ACRE"), row.get("acre_outlier"),
        is_multifamily=is_multifamily)
    water_co2e = (water_gal / 1000.0) * water_embedded_kwh_per_kgal * grid_factor
    gpcd = water_gal / occupancy / 365.0

    total_co2e = operational + emb_annual + water_co2e

    # --- Sub-scores (higher = lower footprint) ---
    op_sub  = _loglin_score(op_intensity, OP_XS, OP_YS)
    emb_sub = _loglin_score(emb_annual_intensity, EMB_XS_ANNUAL, EMB_YS)
    wat_sub = _loglin_score(gpcd, WAT_XS, WAT_YS)

    composite = (W_OPERATIONAL * op_sub + W_EMBODIED * emb_sub + W_WATER * wat_sub)

    return {
        "env_operational_co2e_kg_yr":  round(operational, 1),
        "env_embodied_co2e_kg_yr":     round(emb_annual, 1),
        "env_embodied_intensity_kgm2": round(emb_intensity, 1),
        "env_service_life_yr":         round(service_life, 0),
        "env_water_gal_yr":            round(water_gal, 0),
        "env_water_co2e_kg_yr":        round(water_co2e, 1),
        "env_total_co2e_kg_yr":        round(total_co2e, 1),
        "env_operational_subscore":    round(op_sub, 1),
        "env_embodied_subscore":       round(emb_sub, 1),
        "env_water_subscore":          round(wat_sub, 1),
        "environmental_score":         round(composite, 1),
        "env_data_source":             _data_source(grid_factor, grid_marginal_factor, avoided),
    }
