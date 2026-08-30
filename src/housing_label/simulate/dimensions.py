#!/usr/bin/env python3
"""All-dimension simulation for the CLI house simulator.

The resilience dimension is computed inline by ``house.py`` (EAL model). This
module fills in the *other seven* scored dimensions for a single hypothetical
house so the simulator can emit a complete nutrition label, not just a
resilience scorecard.

It does this by **reusing the production enrichment models** rather than
re-implementing them:

  • Energy Efficiency  → enrich.energy.model_parcel_energy
  • Durability         → enrich.durability.model_parcel_durability
  • Environmental      → enrich.environmental.model_parcel_environment
  • Infrastructure     → enrich.infrastructure.enrich_row
  • Health             → data.health          (CDC PLACES national percentile, bundled)
  • Socioeconomic      → data.socioeconomic   (Census ACS national percentile, bundled)
  • Walkability        → data.walkability     (EPA National Walkability Index, bundled)

Construction-driven dimensions (energy, durability, environmental,
infrastructure) are computed offline from the house config. The three
location-driven dimensions (health, socioeconomic, walkability) are bundled
NATIONAL references resolved by the house's census tract (offline, keyless,
comparable across locations). When the tract can't be resolved (no network to
geocode it, or a point outside the dataset) the dimension is returned as
``None`` and is *excluded* from the composite — it is never filled with a
placeholder, so an
otherwise-excellent house is not unfairly down-weighted by a missing input.

Config → CAMA mapping
---------------------
The simulator speaks a human vocabulary (construction="icf",
condition="excellent"); the enrichment models speak Shelby County CAMA codes
(EXTWALL=3, COND=5, …). ``build_parcel_row`` translates between the two.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from housing_label.utils import isna
from housing_label.score.all_dimensions import (
    ENERGY_XS, ENERGY_YS, INFRA_XS, INFRA_YS, score_to_grade,
)
from housing_label.enrich.energy import base_eui, model_parcel_energy
from housing_label.enrich.durability import model_parcel_durability
from housing_label.enrich.environmental import model_parcel_environment
from housing_label.enrich.infrastructure import enrich_row as infra_enrich_row
from housing_label.data import health as health_data
from housing_label.data import socioeconomic as socio_data
from housing_label.data import walkability as walk_data
from housing_label.data.water_system import RECENT_YEARS as WATER_RECENT_YEARS


# Markers set on cfg["value_source"] when the home value is an auto-filled *per-unit*
# figure — the county single-family median (per home) or the dense-housing
# value-per-door income estimate (per door). Neither may be split again across the
# unit count (doing so collapses the per-unit value — and the Infrastructure fiscal
# ratio — for a multi-unit building). An explicitly supplied value (preset case
# studies / CLI) keeps the total-building convention and is divided by units.
# Auto-filled single-family value: the ACS median home value at the finest
# geography that resolved (neighborhood tract → county → national). Each is a
# per-unit figure (a single home's typical value), so all are in the per-unit set.
HOME_VALUE_SOURCE = {
    "tract":  "neighborhood median (ACS)",
    "county": "county median (ACS)",
    "us":     "US median (ACS)",           # "us" = the shared national geo_level
}
AUTOFILL_VALUE_SOURCE = HOME_VALUE_SOURCE["county"]   # back-compat alias
VALUE_PER_DOOR_SOURCE = "value-per-door (ACS rent)"
_PER_UNIT_VALUE_SOURCES = frozenset({*HOME_VALUE_SOURCE.values(), VALUE_PER_DOOR_SOURCE})


# ── Config vocabulary → CAMA codes ─────────────────────────────────────────────
# EXTWALL codes (energy / durability / environmental). ICF maps to block/concrete
# (3) as the closest masonry-shell proxy; SIP to frame (7). The extra thermal
# performance of ICF/SIP envelopes is credited separately via ENVELOPE_EUI_FACTOR.
#
# Steel carries its OWN code (6) rather than riding frame (7). The pilot's CAMA
# vocabulary uses 1/3/4/5/7/8/9/10 and leaves 6 free, and steel differs from wood
# frame in the direction each downstream model cares about: it conducts heat
# (thermal bridging — an energy PENALTY, where the frame proxy gave it none), it
# neither rots nor feeds termites (a durability bonus), it outlasts a wood shell,
# and its embodied carbon per m² of wall is higher. Mapping it to 7 silently
# scored all four wrong.
EXTWALL_CODE = {
    "frame": 7, "vinyl": 5, "brick-frame": 9, "brick": 1,
    "block": 3, "stone": 4, "icf": 3, "sip": 7, "steel": 6,
}

# BSMT codes (energy foundation factor): 1 = crawl/slab, 2 = partial, 3 = full.
BSMT_CODE = {
    "slab": 1, "crawl": 1, "partial-basement": 2, "full-basement": 3,
}

# COND numeric (0–5) for the durability model (CDU letter is left absent).
COND_CODE = {
    "unsound": 0, "poor": 1, "fair": 2, "average": 3, "good": 4, "excellent": 5,
}

# Construction-quality GRADE (~15–70, 40 = average) used by the durability and
# environmental models. Keyed off the structural system, independent of upkeep
# (which the COND field already captures).
GRADE_BY_CONSTRUCTION = {
    "frame": 38, "vinyl": 35, "brick-frame": 42, "brick": 48,
    "block": 46, "stone": 52, "icf": 50, "sip": 45, "steel": 44,
}

# ── High-performance feature adjustments (v1 estimates) ───────────────────────
# Applied to the modeled EUI before scoring the energy dimension and before
# deriving operational carbon for the environmental dimension.
#   • ICF/SIP envelopes outperform the EXTWALL masonry proxy on air-tightness and
#     continuous insulation.
#   • Passive-house certification targets ~40–60% below code (PHIUS / RMI).
ENVELOPE_EUI_FACTOR = {"icf": 0.92, "sip": 0.95}

# ── Lot context → is this parcel in an urban service area? ────────────────────
# The other half of "what kind of place is this", alongside lot acreage. Acreage
# alone can't say it: a two-acre lot is exurban outside a city and a large in-town
# lot inside one, and the two are served very differently. Drives the fire-service
# multiplier in the infrastructure model, overriding the Census urban-area test on
# the geocoded point — which is a coarse call at the fringe, where the owner knows
# better than the boundary does. Unset (None) keeps the detection.
LOT_CONTEXT_URBAN = {"rural": False, "suburban": True, "urban": True}


def resolve_water_source(cfg: dict, location=None) -> str:
    """The parcel's drinking-water source: what the owner stated, else what the EPA
    service-area boundaries detected, else "public".

    Stated always wins — the owner knows, and the EPA layer is explicit that it
    cannot confirm service by address. Unstated, a point inside no mapped COMMUNITY
    system reads as a well: evidence rather than proof (~40% of the layer is
    EPA-modeled, and a small system may be unmapped), but the failure is in the safe
    direction — a dimension left blank with a note, rather than another population's
    water reported as this home's.

    An unreachable service leaves ``water_system`` None, which is NOT "outside" and
    resolves to "public" — the pre-detection behaviour, so an outage cannot unscore
    Water Quality for every address at once."""
    stated = cfg.get("water_source")
    if stated is not None:
        return stated
    ws = getattr(location, "water_system", None) or {}
    return "well" if ws.get("status") == "outside" else "public"
PASSIVE_HOUSE_EUI_FACTOR = 0.55

# Multi-family / mobile-home energy is now scored off the real ResStock benchmark
# for that building type (enrich/energy.base_eui), which *measures* the shared-wall
# effect directly, rather than modeling it as a per-unit multiplier off the detached
# curve. So the shared-wall EUI credit is retired; the building type drives it.


def energy_building_type(structure_type: str | None, num_units: int | None) -> str:
    """Map a detected/entered structure to the ResStock energy benchmark key.

    Manufactured/mobile → "mobile_home"; a multi-family building → "mf_2_4" or
    "mf_5plus" by unit count; everything else → "sf_detached" (the runtime cannot
    distinguish single-family attached today, so it rides the detached curve)."""
    st = (structure_type or "").lower()
    if st in ("manufactured", "mobile_home", "mobile"):
        return "mobile_home"
    try:
        n = int(num_units or 1)
    except (TypeError, ValueError):
        n = 1
    if st == "multifamily" or n > 1:
        return "mf_2_4" if n <= 4 else "mf_5plus"
    return "sf_detached"
# Rooftop solar offsets grid electricity for the *operational-carbon* leg of the
# environmental score (net-metering). It does not change the envelope EUI used
# for the energy-efficiency dimension. ~70% of annual electricity offset.
SOLAR_OPERATIONAL_REMAINING = 0.30

# Infrastructure: Shelby keeps its Memphis calibration; elsewhere the cost curves
# are recalibrated per county (Census of Governments) and the property-tax revenue
# uses the county's effective rate (Census ACS), both applied with assess_ratio 1.0.
SHELBY_COUNTY_FIPS = "47157"

# Dimension display order / labels (mirrors score/all_dimensions).
DIMENSIONS = [
    ("resilience",     "Disaster Resilience"),
    ("energy",         "Energy Efficiency"),
    ("durability",     "Durability"),
    ("environmental",  "Environmental Footprint"),
    ("infrastructure", "Infrastructure Burden"),
    ("health",         "Health Impact"),
    ("air_quality",    "Air Quality"),
    ("noise",          "Noise"),
    ("socioeconomic",  "Socioeconomic"),
    ("walkability",    "Walkability"),
    ("climate",        "Climate Projections"),
    ("solar",          "Solar Potential"),
    ("water",          "Water Quality"),
]
# ── The two headline axes, and the rows that sit outside them ────────────────
# A single composite answers neither question a buyer actually has. A 2025 build
# beside a freeway and a 1955 bungalow in a quiet walkable district can land within
# a point of each other, because the mean of thirteen percentiles has a standard
# deviation of about 29/sqrt(13) ~= 8 — so an A (>= 80) is a four-sigma event and
# every real house crowds the middle. Splitting the roster is most of the fix.
#
# CONSTRUCTION is what the structure IS: its envelope, its materials, how long it
# will last. Nothing here changes if you pick the house up and put it elsewhere.
CONSTRUCTION_DRIVEN = {"energy", "durability", "environmental"}

# LOCATION is what surrounds it. Two of these used to sit in the construction
# bucket and both were wrong in ways users could see:
#
#   * infrastructure is a COUNTY fiscal cost-to-serve ratio. It was pulling a
#     new build's construction score down by a dozen points for the shape of the
#     county's budget — which is the single thing that most broke the split's
#     motivating case.
#   * resilience was never in either set, so `else "construction"` below claimed
#     it by default rather than by decision, and docs/methodology.html filed it
#     under "Construction-driven (how the home is built)". It is FEMA flood zone,
#     NRI wildfire and tornado, and USGS seismic hazard, multiplied by
#     construction factors. Measured at a fixed point the location leg spans ~29
#     score points (flood zone X -> AE) against ~19-27 for the building leg
#     (1975 frame -> 2025 ICF), so neither side dominates. It belongs here as a
#     holding position, not a final answer: the honest fix is to decompose it into
#     its site-hazard and building-response parts, and the seam for that already
#     exists in score/resilience.py.
LOCATION_DRIVEN = {"resilience", "infrastructure", "air_quality", "noise",
                   "walkability", "climate", "solar", "water"}

# CONTEXT rows are shown in full — score, sources, drill-down — but deliberately
# do NOT feed the Location grade.
#
# Both measure the PEOPLE nearby rather than the place: Census ACS income,
# poverty and education; CDC PLACES chronic-disease prevalence. Both are constant
# across a census tract, so publishing a per-address letter grade built on them is
# publishing a map of neighbourhoods graded by their residents' income and health
# — which is what a residential security map was. Redfin, Realtor.com and Trulia
# all withdrew neighbourhood crime data in December 2021 over the same concern.
#
# Keeping the rows visible preserves the information for someone who wants it;
# keeping them out of the aggregate means the headline grade measures the site and
# its environment, not the residents. LEED v4 drew the same line when it split
# Location & Transportation out of Sustainable Sites.
CONTEXT_ONLY = {"health", "socioeconomic"}

# Graded under Location, but genuinely driven by both sides — so anything
# describing the roster to a reader should say so rather than implying the bucket
# is the whole story. Kept as data, not as a special case inside whichever script
# happens to render the table: sync_readme.py used to carry "resilience is in
# neither set" as a bare `else`, which is how Health and Socioeconomic silently
# inherited resilience's description the moment they left both sets.
HYBRID_DIMENSIONS = {"resilience"}

# Hybrids are GROUPED under Site & environment but the COMBINED dimension is kept
# out of its aggregate — because it is split instead, and each half joins the axis
# it belongs to (score/resilience.py:resilience_legs).
#
# Why splitting rather than assigning: measured at one fixed Los Angeles tract,
# varying only the preset, resilience ran from the 1st national percentile to the
# 99th — 98 points of a 100-point scale — while every other member of the axis
# moved 4 points or less and five did not move at all. Whichever side it was put
# on, that side inherited a number that was mostly about the other one. On the site
# axis it made the grade read F for a badly-built house and C for an ordinary one
# on the SAME parcel.
#
# Now the site leg (hazard with a neutral building) joins this aggregate and the
# building leg (the construction multiplier scored at a reference site) joins the
# construction one. The site leg is constant across buildings at a fixed parcel,
# which is the property a site grade needs and the combined score never had.
AGGREGATED_LOCATION = LOCATION_DRIVEN - HYBRID_DIMENSIONS


def _loglin(x: float, xs: list[float], ys: list[float]) -> float:
    """Scalar piecewise-linear interpolation in log10(x) space (clamped)."""
    return float(np.interp(np.log10(max(float(x), 1e-9)), np.log10(xs), ys))


_MF_MATERIALS = frozenset({"wood", "masonry", "concrete", "steel"})


def effective_structure(cfg: dict, location=None) -> dict:
    """Merge the caller-entered building fields over the NSI-detected structure.

    A building counts as multi-family when NSI detected it as such **or** the caller
    entered a unit count > 1 — NSI misses garden-apartment complexes it models as
    clusters of single-family structures, so an entered unit count is authoritative.

    When NSI did **not** detect multi-family, its ``bldg_material``/``stories``
    describe that (mis)reading of the site, so they are ignored for a caller-declared
    multi-unit building; only caller-entered material/stories drive the material- and
    height-based Resilience/Durability adjustments there. For a genuinely detected
    multi-family building the detected values are the base and the caller can override.

    Returns: ``structure_type``, ``is_multifamily``, ``num_units``, ``stories``,
    ``bldg_material``, ``mf_units`` (unit count when it should drive per-unit
    density/credits, else None), ``mf_material`` (shell material when multi-family).
    """
    entered_units = max(int(cfg.get("units", 1) or 1), 1)
    det_type = getattr(location, "structure_type", None)
    det_mf = det_type == "multifamily"
    is_mf = det_mf or entered_units > 1

    # Detected material/stories are only trustworthy when NSI actually saw MF.
    base_material = getattr(location, "bldg_material", None) if det_mf else None
    base_stories = getattr(location, "stories", None) if det_mf else None

    material = cfg.get("bldg_material") or base_material
    if material is not None:
        material = str(material).strip().lower()
        if material not in _MF_MATERIALS:
            material = None
    try:
        s = int(cfg.get("stories") or base_stories or 0)
        stories = s if s >= 1 else None          # a story count < 1 is invalid → unknown
    except (TypeError, ValueError):
        stories = None

    num_units = entered_units if entered_units > 1 else (
        getattr(location, "num_units", None) if det_mf else 1)
    mf_units = num_units if (is_mf and num_units and num_units > 1) else None

    # Material/stories are multi-unit-only context; drop them for a single-family
    # building so they don't leak into the structure payload for non-MF cases.
    if not is_mf:
        material = stories = None

    return {
        "structure_type": "multifamily" if is_mf else det_type,
        "is_multifamily": is_mf,
        "num_units": num_units,
        "stories": stories,
        "bldg_material": material,
        "mf_units": mf_units,
        "mf_material": material,
    }


def per_unit_home_value(cfg: dict) -> float:
    """The value of one representative dwelling unit.

    A *total-building* value (the multi-unit case-study presets / an explicit value)
    is split across the unit count; an already-per-unit auto-fill — the county
    single-family median or the dense-housing value-per-door estimate — is used as-is.
    Shared by the infrastructure parcel row (``build_parcel_row``) and the dollar-EAL
    calc (``simulate``) so both report the same per-unit basis for a multi-unit
    building instead of mixing per-unit and whole-building dollars on one label.
    """
    units = max(int(cfg.get("units", 1) or 1), 1)
    value = float(cfg.get("value", 160_000))
    if cfg.get("value_source") in _PER_UNIT_VALUE_SOURCES:
        return value
    return value / units


# ── Build a synthetic CAMA parcel row from the simulator config ─────────────────
def _feet_to_m(feet) -> float:
    """Feet → metres, tolerant of missing / non-numeric input (→ NaN)."""
    try:
        return float(feet) * 0.3048
    except (TypeError, ValueError):
        return np.nan


def build_parcel_row(cfg: dict) -> dict:
    """Translate a simulator config dict into a one-parcel CAMA-style Series.

    Per-unit framing: lot area is divided by the unit count (land is shared), so the
    infrastructure fiscal ratio and environmental water/footprint are reported per
    dwelling unit. The value is divided too when it is a *total-building* figure (the
    multi-unit case-study presets / an explicit value), but NOT when it was
    auto-filled as a per-unit figure — the county single-family median or the
    dense-housing value-per-door estimate — because those are already per-unit, and
    dividing again would collapse the per-unit value (and fiscal ratio) for a
    multi-unit building.
    """
    units = max(int(cfg.get("units", 1) or 1), 1)
    construction = cfg["construction"]
    per_unit_acres = float(cfg.get("lot_acres", 0.25)) / units
    per_unit_value = per_unit_home_value(cfg)

    return {
        "YRBLT":     cfg["year_built"],
        "EFFYR":     np.nan,
        "SFLA":      cfg.get("sqft", 2000),          # per unit
        "EXTWALL":   EXTWALL_CODE.get(construction, 7),
        "BSMT":      BSMT_CODE.get(cfg["foundation"], 1),
        "COND":      COND_CODE.get(cfg["condition"], 3),
        "CDU":       np.nan,                          # let COND drive condition
        "GRADE":     GRADE_BY_CONSTRUCTION.get(construction, 40),
        "HEAT":      np.nan,                          # → energy model defaults (heat pump)
        "FUEL":      np.nan,                          # → all-electric default
        "RMBED":     np.nan,
        "FIXBATH":   np.nan,
        # Stories drives the embodied-carbon footprint (a 1-story home spreads more
        # foundation + roof over its floor area than a 2-story of the same size).
        "STORIES":   cfg.get("stories") or np.nan,
        # Optional actual basement depth (metres) for the embodied foundation term;
        # absent / non-numeric → NaN, and the embodied model falls back to a
        # per-foundation-type default depth (degrades gracefully, never crashes).
        "basement_depth_m": _feet_to_m(cfg.get("basement_depth_ft")),
        # Optional REAL building footprint (FEMA/ORNL USA Structures) for the embodied
        # model — its actual area + perimeter replace the shape-factor estimate.
        "footprint_area_m2": cfg.get("footprint_area_m2") or np.nan,
        "footprint_perimeter_m": cfg.get("footprint_perimeter_m") or np.nan,
        "CALC_ACRE": per_unit_acres,
        "acre_outlier": False,
        "RTOTAPR":   per_unit_value,
        "latitude":  cfg["lat"],
        "longitude": cfg["lon"],
    }


def _adjusted_energy(cfg: dict, row: dict, climate_zone: str | None = None,
                     elec_rate: float | None = None, gas_rate: float | None = None,
                     building_type: str = "sf_detached") -> dict:
    """Run the energy model, then apply the high-performance feature factors.

    Returns the energy dict with eui / kwh / therms scaled, plus a separate
    ``env_kwh`` that additionally folds in the rooftop-solar offset for the
    environmental operational-carbon calculation. ``climate_zone`` (IECC label)
    scales the base EUI for the location; None falls back to the 4A baseline.
    ``elec_rate``/``gas_rate`` are the property's local utility rates; None keeps
    the energy model's Memphis/TVA pilot defaults. ``building_type`` selects the
    ResStock benchmark (sf_detached / sf_attached / mf_2_4 / mf_5plus /
    mobile_home) — a Multi-Family or Mobile-Home home is scored off its own
    measured EUI, not the detached curve times a modeled shared-wall credit.

    For a non-detached building it also returns ``energy_detached_ratio`` — the
    ResStock detached / this-building-type base-EUI ratio (all within-cell and
    feature factors cancel) — so the API can show the "same home standing alone"
    density-comparison cost without a second scoring pass.
    """
    rate_kw = {}
    if elec_rate is not None:
        rate_kw["elec_rate"] = elec_rate
    if gas_rate is not None:
        rate_kw["gas_rate"] = gas_rate
    energy = model_parcel_energy(row, climate_zone, building_type=building_type, **rate_kw)
    # Environmental baseline: the SAME home with a standard envelope (no ICF/SIP/
    # passive efficiency factor) and no solar — i.e. the raw energy-model kWh
    # before the high-performance feature factors below. The environmental model
    # credits the avoided kWh (baseline − adjusted) at the marginal grid rate.
    baseline_kwh = energy.get("est_annual_kwh") or 0.0
    factor = 1.0
    factor *= ENVELOPE_EUI_FACTOR.get(cfg["construction"], 1.0)
    if cfg.get("passive_house"):
        factor *= PASSIVE_HOUSE_EUI_FACTOR

    # The monthly cost is proportional to energy use, so it scales by the same
    # factor as the EUI/kWh/therms (keeps the displayed cost consistent with the
    # reduced EUI for passive/ICF builds).
    for k in ("eui_kbtu_sqft_yr", "est_annual_kbtu", "est_annual_kwh",
              "est_annual_therms", "est_monthly_energy_cost"):
        if energy.get(k) is not None:
            energy[k] = round(energy[k] * factor, 2)

    # Density comparison: what the SAME home would use standing alone (detached).
    # The base-EUI ratio is the only thing that differs — every within-cell and
    # feature factor is building-type-independent, so they cancel.
    if building_type != "sf_detached":
        vbin = energy.get("energy_vintage_bin")
        bt_base = base_eui(climate_zone, vbin, building_type)
        det_base = base_eui(climate_zone, vbin, "sf_detached")
        if bt_base:
            energy["energy_detached_ratio"] = round(det_base / bt_base, 4)

    # Operational carbon basis: apply the solar offset on top of the envelope EUI.
    solar_factor = SOLAR_OPERATIONAL_REMAINING if cfg.get("solar") else 1.0
    energy["env_kwh"] = round((energy.get("est_annual_kwh") or 0.0) * solar_factor, 1)
    # Standard-envelope, no-solar baseline for the environmental marginal-rate
    # credit (avoided_kwh = baseline_kwh − env_kwh).
    energy["baseline_kwh"] = round(baseline_kwh, 1)
    return energy


# ── Construction-driven dimensions (offline) ───────────────────────────────────
def compute_construction_dimensions(cfg: dict, climate_zone: str | None = None,
                                    grid_factor: float | None = None,
                                    grid_marginal_factor: float | None = None,
                                    infra_params: dict | None = None,
                                    elec_rate: float | None = None,
                                    gas_rate: float | None = None,
                                    mf_units: int | None = None,
                                    incorporated: bool | None = None,
                                    water_source: str | None = None,
                                    mf_material: str | None = None,
                                    building_type: str = "sf_detached") -> dict:
    """Compute energy / durability / environmental / infrastructure scores
    (0–100, or None when the model cannot score the parcel).

    ``climate_zone`` (IECC) scales the energy model; ``building_type`` selects the
    ResStock energy benchmark (Multi-Family / Mobile-Home get their own EUI curve);
    ``grid_factor`` (kgCO2e/kWh) is the eGRID subregion AVERAGE driving the
    environmental operational-carbon leg; ``grid_marginal_factor`` (kgCO2e/kWh) is
    the NREL Cambium LRMER long-run MARGINAL rate used to credit solar/efficiency-
    avoided kWh — None (outside CONUS Cambium regions) applies no marginal
    adjustment (avoided kWh valued at the average, i.e. today's number);
    ``elec_rate``/``gas_rate`` are the property's local utility rates for the
    energy-cost estimate; ``mf_units`` is the building's residential unit count
    (folds the detected unit density into the Infrastructure fiscal ratio — it no
    longer affects Energy, which is now driven by ``building_type``);
    ``mf_material`` is the detected building material for a multi-family building
    (lengthens the durability model's shared structural-shell service life);
    ``infra_params`` overrides the Memphis infrastructure calibration with a
    national-average one. All fall back to the single-family / Shelby / 4A / Memphis
    pilot defaults when None."""
    row = build_parcel_row(cfg)
    energy = _adjusted_energy(cfg, row, climate_zone, elec_rate=elec_rate,
                              gas_rate=gas_rate, building_type=building_type)

    # Energy: lower EUI → higher score (same breakpoints as the pipeline).
    eui = energy.get("eui_kbtu_sqft_yr")
    energy_score = round(_loglin(eui, ENERGY_XS, ENERGY_YS), 1) if eui is not None else None

    # Durability: passthrough 0–100 from the component-lifespan model. A detected
    # multi-family building's durable material lengthens its shared structural shell.
    dur = model_parcel_durability(row, mf_material=mf_material)
    durability_score = dur.get("durability_score")

    # A multi-unit building — an explicit count > 1, or a detected multi-family.
    # Detection always carries a material (mf_material), even when NSI gives no
    # reliable unit count (mf_units stays None), so its presence marks the detected
    # multi-family path. Its representative unit is stacked/attached, so the water
    # model below drops the single-family private yard.
    is_mf_building = bool(mf_units and mf_units > 1) or mf_material is not None

    # Environmental: feed the solar/envelope-adjusted electricity in so the
    # operational-carbon leg reflects the high-performance features. A multi-unit
    # building's representative unit carries no private-yard irrigation load.
    env_row = row.copy()
    env_row["est_annual_kwh"] = energy.get("env_kwh")
    env_row["est_annual_therms"] = energy.get("est_annual_therms")
    # Avoided kWh = standard-envelope, no-solar baseline − adjusted consumption;
    # the env model credits it at the marginal grid rate (grid_marginal_factor).
    consumed_kwh = energy.get("env_kwh") or 0.0
    baseline_kwh = energy.get("baseline_kwh") or 0.0
    avoided_kwh = max(0.0, baseline_kwh - consumed_kwh)
    env_kwargs = {"is_multifamily": is_mf_building,
                  "grid_marginal_factor": grid_marginal_factor,
                  "avoided_kwh": avoided_kwh}
    env = (model_parcel_environment(env_row, grid_factor, **env_kwargs)
           if grid_factor is not None
           else model_parcel_environment(env_row, **env_kwargs))
    environmental_score = env.get("environmental_score")

    # Infrastructure: fiscal ratio → score (higher ratio → higher score).
    # build_parcel_row already splits lot area per unit for an explicit unit count.
    # For a building only *detected* as multi-family (no explicit units), fold the
    # detected unit count into the DU/acre density here so it isn't scored as
    # single-family sprawl. Only the density (lot area per unit) changes; the
    # per-unit value/tax basis is left for Phase 3.
    infra_row = row
    cfg_units = max(int(cfg.get("units", 1) or 1), 1)
    if mf_units and mf_units > cfg_units:
        infra_row = row.copy()
        infra_row["CALC_ACRE"] = row["CALC_ACRE"] * (cfg_units / mf_units)
    # Dwelling units on the parcel — entered, or detected for a multi-family
    # structure. Drives property-tax classification: in Tennessee a parcel with 2+
    # rental units is assessed at the 40% commercial ratio, not 25% residential.
    # ``owner_occupied`` is unknown here, so it resolves to the ACS-backed default
    # (a multi-unit building is rental); callers can state it explicitly.
    parcel_units = max(cfg_units, int(mf_units or 0))
    # A parcel on a private well and/or a septic field is not served by the public
    # water/sewer network, so it is neither charged that cost nor credited the
    # utility fees it never pays. Default True — most homes are connected, and an
    # unstated water source must not quietly discount every parcel.
    # Unincorporated county territory receives no municipal curbside collection.
    # None (no geocode resolved) is NOT False — it means unknown, and an unknown
    # location must keep the full service bundle rather than be handed a discount.
    infra_kwargs = {"units": parcel_units,
                    "owner_occupied": cfg.get("owner_occupied"),
                    "incorporated": incorporated is not False,
                    "public_water": (water_source or cfg.get("water_source")) != "well",
                    "public_sewer": cfg.get("sewer") != "septic"}
    infra = infra_enrich_row(infra_row, **{**(infra_params or {}), **infra_kwargs})
    fr = infra.get("fiscal_ratio")
    infrastructure_score = (
        round(_loglin(fr, INFRA_XS, INFRA_YS), 1)
        if fr is not None and not isna(fr) else None
    )

    metrics = {
        "eui_kbtu_sqft_yr": eui,
        "est_monthly_energy_cost": energy.get("est_monthly_energy_cost"),
        "fiscal_ratio": None if fr is None or isna(fr) else round(float(fr), 2),
        "est_annual_infra_cost": infra.get("est_annual_infra_cost"),
        "est_property_tax": infra.get("est_property_tax"),
        "est_fee_revenue": infra.get("est_fee_revenue"),
        "est_total_revenue": infra.get("est_total_revenue"),
        "assess_ratio_applied": infra.get("assess_ratio_applied"),
        "classification_multiplier_applied": infra.get("classification_multiplier_applied"),
        # Durability drivers (component-lifespan model).
        "durability_material_class": dur.get("durability_material_class"),
        "durability_remaining_life_pct": dur.get("durability_remaining_life_pct"),
        "durability_components_past_life": dur.get("durability_components_past_life"),
        "durability_condition": dur.get("durability_condition"),
        # Environmental drivers (annual CO2e legs + water).
        "env_total_co2e_kg_yr": env.get("env_total_co2e_kg_yr"),
        "env_operational_co2e_kg_yr": env.get("env_operational_co2e_kg_yr"),
        "env_embodied_co2e_kg_yr": env.get("env_embodied_co2e_kg_yr"),
        "env_water_gal_yr": env.get("env_water_gal_yr"),
        # Marginal-rate credit drivers: kWh avoided vs the standard-envelope,
        # no-solar baseline and the long-run marginal factor they're credited at.
        "env_avoided_kwh": round(avoided_kwh, 1),
        "env_grid_marginal_factor": grid_marginal_factor,
    }
    # Detached / this-building-type base-EUI ratio — present ONLY for a non-detached
    # building (so detached payloads stay byte-identical), so the API can price "the
    # same home standing alone" for the density comparison. Not rendered as a row.
    if energy.get("energy_detached_ratio") is not None:
        metrics["energy_detached_ratio"] = energy["energy_detached_ratio"]

    return {
        "energy": energy_score,
        "durability": durability_score,
        "environmental": environmental_score,
        "infrastructure": infrastructure_score,
        # Side metrics surfaced on the label / for debugging. The per-dimension
        # "what drove this score" detail rows (dimension_details) read from here, so
        # each model's headline drivers are surfaced alongside the score.
        "_metrics": metrics,
    }


# ── Location-driven dimensions ──────────────────────────────────────────────────
# Health, Socioeconomic, and Walkability are now bundled, offline NATIONAL lookups
# (data/health.py, data/socioeconomic.py, data/walkability.py) — no live CDC/ACS/
# Walk Score fetch, no CENSUS_API_KEY, and no within-county ranking — so they are
# comparable across locations. The only network access left is geocoding the tract
# (when one isn't supplied by the resolved location).
@lru_cache(maxsize=256)
def _tract_for(lat: float, lon: float) -> str | None:
    from housing_label.enrich import health as health_mod
    return health_mod.get_census_tract(lat, lon)


def fetch_location_dimensions(
    lat: float,
    lon: float,
    tract: str | None = None,
    *,
    allow_network: bool = True,
    overrides: dict | None = None,
) -> dict:
    """Return {health, socioeconomic, walkability} scores for a location.

    ``tract`` is the 11-digit census-tract GEOID (from the location resolver); if
    omitted it is geocoded from lat/lon. Health, socioeconomic, and walkability are
    then resolved from the bundled NATIONAL crosswalks (data/health.py,
    data/socioeconomic.py, data/walkability.py) by that tract — a national
    percentile comparable across locations, not a within-county rank — with a
    tract -> county fallback.

    Manual ``overrides`` always win. Otherwise each dimension is a keyless offline
    lookup; when the tract can't be resolved (or the point is outside the dataset)
    the dimension is ``None`` (excluded from the composite, never placeholdered).
    Also returns ``_tract`` and ``_notes``.
    """
    overrides = overrides or {}
    out: dict = {"health": None, "socioeconomic": None, "walkability": None,
                 "_tract": tract, "_notes": {}}
    notes = out["_notes"]

    # Manual overrides first.
    for key in ("health", "socioeconomic", "walkability"):
        if overrides.get(key) is not None:
            out[key] = round(float(overrides[key]), 1)
            notes[key] = "manual override"

    # All three location dimensions now resolve by census tract, so any of them
    # being unscored means we still need the tract (to geocode if it wasn't passed).
    need_tract = any(out[k] is None for k in ("health", "socioeconomic", "walkability"))
    walk_override = "walkability" in notes

    # Census tract (shared by all three location dimensions). A tract passed in from
    # the resolved location is used offline; geocoding a missing one needs network.
    if tract is None and need_tract and allow_network:
        try:
            tract = _tract_for(round(float(lat), 6), round(float(lon), 6))
        except Exception as exc:  # noqa: BLE001
            # All three location dimensions resolve by tract now, so a geocoder
            # failure should surface as the real cause on each (not the vaguer
            # "no census tract"). A manual override already set on a key wins.
            for k in ("health", "socioeconomic", "walkability"):
                notes[k] = notes.get(k) or f"geocoder failed: {exc}"
    out["_tract"] = tract

    # Health (CDC PLACES NATIONAL percentile index — bundled, offline). Works with
    # or without network as long as a tract is known; scored against the full
    # national distribution of US tracts (population-weighted), not ranked within
    # the county, so a value is comparable across locations. Resolves tract ->
    # county; a national-only fallback (no local data) is left unscored rather
    # than filled with a placeholder.
    if out["health"] is None:
        if tract:
            res = health_data.health_for_tract(tract)
            if res["resolved"] and res["health_index"] is not None:
                out["health"] = round(float(res["health_index"]), 1)
                notes["health"] = res["label"]
            else:
                # Name the real scope. CDC PLACES omits some states wholesale, and
                # telling a Philadelphian "no health data for tract 42101000100"
                # points at their neighbourhood for a gap that is statewide and
                # upstream — it reads as a bad tract id rather than as the survey
                # having no outcome data for Pennsylvania at all.
                gap = health_data.states_without_data()
                st = str(tract)[:2]
                if st in gap:
                    from housing_label.data.states import usps_for_fips
                    notes["health"] = (
                        f"CDC PLACES publishes no health-outcome measures for "
                        f"{usps_for_fips(st) or st}, so Health Impact is unscored "
                        f"across the whole state — not a gap in this tract. Left "
                        f"unscored rather than filled with the national average, "
                        f"which would read as an average neighbourhood instead of "
                        f"an unmeasured one")
                else:
                    notes["health"] = f"no health data for tract {tract}"
        elif not allow_network:
            notes.setdefault("health", "skipped (--no-fetch)")
        else:
            notes.setdefault("health", "no census tract")

    # Socioeconomic (Census ACS NATIONAL percentile index — bundled, offline). No
    # live ACS call and no CENSUS_API_KEY: the value is a national percentile from
    # the bundled crosswalk, not a within-county rank, so it is comparable across
    # locations. Resolves tract -> county; a national-only fallback (no local data)
    # is left unscored rather than filled with a placeholder.
    if out["socioeconomic"] is None:
        if tract:
            res = socio_data.socio_for_tract(tract)
            if res["resolved"] and res["socioeconomic_index"] is not None:
                out["socioeconomic"] = round(float(res["socioeconomic_index"]), 1)
                notes["socioeconomic"] = res["label"]
            else:
                notes["socioeconomic"] = f"no socioeconomic data for tract {tract}"
        elif not allow_network:
            notes.setdefault("socioeconomic", "skipped (--no-fetch)")
        else:
            notes.setdefault("socioeconomic", "no census tract")

    # Walkability (EPA National Walkability Index — bundled, offline, public
    # domain). Replaces the Walk Score API, whose Terms of Use prohibit storing
    # scores and whose free tier caps at ~5,000 calls/day; NWI needs no key or
    # quota. Resolves tract -> county; a national-only fallback (no local data) is
    # left unscored. A caller can still inject a Walk Score (or any walkability
    # value) via overrides["walkability"].
    if not walk_override:
        if tract:
            res = walk_data.walkability_for_tract(tract)
            if res["resolved"] and res["walkability_score"] is not None:
                out["walkability"] = round(float(res["walkability_score"]), 1)
                notes["walkability"] = res["label"]
            else:
                notes["walkability"] = f"no walkability data for tract {tract}"
        elif not allow_network:
            notes.setdefault("walkability", "skipped (--no-fetch)")
        else:
            notes.setdefault("walkability", "no census tract")

    return out


# ── Assemble the full label ────────────────────────────────────────────────────
def simulate_all_dimensions(
    cfg: dict,
    resilience_score: float,
    *,
    location=None,
    allow_network: bool = True,
    overrides: dict | None = None,
    resilience_result: dict | None = None,
) -> dict:
    """Produce the complete nutrition label for a house config.

    ``location`` is an optional resolved ``Location`` (see simulate/location.py);
    when omitted it is resolved from cfg lat/lon. Its climate zone and grid factor
    drive the energy/environmental models, and its census tract drives the
    health/socioeconomic lookups so they rank within the location's own county.

    Returns a dict with an ordered ``dimensions`` list (each: key, label, score,
    national_grade, kind) plus the composite (mean of the scored dimensions) and
    the side metrics / fetch notes.
    """
    if location is None:
        from housing_label.simulate.location import resolve_location
        try:
            location = resolve_location(lat=cfg["lat"], lon=cfg["lon"],
                                        allow_network=allow_network)
        except Exception:  # noqa: BLE001
            location = None

    climate_zone = location.climate_zone if location else None
    grid_factor = location.egrid_factor if location else None
    grid_marginal_factor = location.cambium_factor if location else None
    tract = location.tract if location else None

    # Energy cost: use the property's state residential utility rates (EIA) instead
    # of the Memphis/TVA pilot constants. Run whenever a location resolved — a
    # missing/None state_fips returns the US-average pair, never the pilot rates.
    elec_rate = gas_rate = None
    if location:
        from housing_label.data.utility_rates import utility_rates_for_state
        _rates = utility_rates_for_state(location.state_fips)
        elec_rate, gas_rate = _rates["elec_per_kwh"], _rates["gas_per_therm"]

    # Infrastructure: for confirmed non-Shelby locations, recalibrate the cost
    # curves to the county's local-government spending (Census of Governments,
    # cost side) and use the county's effective property-tax rate (Census ACS,
    # revenue side) — each with a national-average fallback. The Memphis
    # calibration is kept for Shelby (multipliers there are 1.0 by construction)
    # and when the county is unknown.
    # Assembled by the shared region-context helper (also used by the batch
    # enrich stage) so the live and batch paths score a county identically.
    from housing_label.enrich.region_context import infra_params_for_county
    # Pass in_urban_area through as-is (bool | None): None means "unknown" and is
    # omitted so enrich_row falls back to its distance model, rather than being
    # forced to "rural" by bool(None).
    #
    # An explicit lot_context wins over the Census urban-area detection. The
    # detection asks whether the POINT falls inside a Census-delineated urban area,
    # which is a coarse call at the fringe — a subdivision just outside the boundary
    # reads rural, a farmhouse just inside reads urban — and the owner knows which
    # they are. Left unset (the default) nothing changes.
    stated = LOT_CONTEXT_URBAN.get(cfg.get("lot_context"))
    infra_params = infra_params_for_county(
        location.county_fips if location else None,
        in_urban_area=(stated if stated is not None
                       else (location.in_urban_area if location else None)),
    )

    # Building context for a representative unit — use the caller's explicit unit
    # count when > 1, else the detected multi-family unit count from the resolved
    # location. This drives Energy (via the ResStock building-type benchmark that
    # energy_building_type selects), Infrastructure (per-unit density), and
    # Durability (shared structural shell).
    # Effective building context: caller-entered units/material/stories merged over
    # the NSI-detected structure. An entered unit count > 1 makes it multi-family
    # even when NSI mislabels the site (e.g. a garden-apartment complex modeled as
    # single-family structures); the shell material only drives Durability when it is
    # detected or entered for such a building.
    es = effective_structure(cfg, location)
    mf_units = es["mf_units"]
    mf_material = es["mf_material"]
    # Energy benchmark key: mobile/MF get their own ResStock curve. Use the
    # building's residential unit count (detected or entered) to pick the MF band.
    building_type = energy_building_type(es["structure_type"], es["num_units"])

    construction = compute_construction_dimensions(
        cfg, climate_zone=climate_zone, grid_factor=grid_factor,
        grid_marginal_factor=grid_marginal_factor,
        infra_params=infra_params, elec_rate=elec_rate, gas_rate=gas_rate,
        mf_units=mf_units, mf_material=mf_material, building_type=building_type,
        incorporated=getattr(location, "incorporated", None),
        water_source=resolve_water_source(cfg, location))
    location_dims = fetch_location_dimensions(
        cfg["lat"], cfg["lon"], tract,
        allow_network=allow_network, overrides=overrides,
    )

    # Climate Projections: bundled sub-county hazard projection (low/SSP2-4.5 band
    # is the headline). Scored whenever a county resolved — a known-but-unmapped
    # county uses the national-average fallback — but excluded (like the other
    # location-driven dimensions) when no county resolved at all, e.g. offline.
    climate_proj = location.climate_projection if location else None
    have_county = bool(location and location.county_fips)
    climate_score = climate_proj["score"] if (climate_proj and have_county) else None

    # Air Quality: bundled tract PM2.5 + ozone (falling back to the county) + the
    # county radon zone. Resolved at the tract like health/socioeconomic/walkability;
    # a non-CONUS or unmodeled location returns None → left unscored.
    from housing_label.data.air_quality import (
        air_quality_for_tract, air_quality_for_county,
    )
    air_quality = None
    if tract:
        air_quality = air_quality_for_tract(tract)
    elif have_county:
        air_quality = air_quality_for_county(location.county_fips)
    # Radon is the one air-quality component the BUILDING moves: it enters through
    # the foundation, and a mitigation system pulls it back out. PM2.5 and ozone are
    # outdoor pollutants at ~12 km model resolution and the house does not move them.
    from housing_label.data.air_quality import radon_adjusted_reading
    air_quality = radon_adjusted_reading(
        air_quality, cfg.get("foundation"), bool(cfg.get("radon_mitigation")))
    air_quality_score = air_quality["score"] if air_quality else None

    # Noise: bundled tract transportation-noise exposure (BTS/UW). Resolved at the
    # tract (county-mean fallback); a location absent from the map is left unscored.
    from housing_label.data import noise as noise_data
    from housing_label.data.noise import noise_for_tract, noise_for_county
    noise = None
    if tract:
        noise = noise_for_tract(tract)
    elif have_county:
        noise = noise_for_county(location.county_fips)
    noise_score = noise["score"] if noise else None

    # ── Point-level refinement ────────────────────────────────────────────────
    # The tract figure is the share of the TRACT's residents exposed to >=60 dB —
    # a population statistic. In a rural tract containing one highway corridor it
    # belongs to the homes beside the corridor, and every other parcel inherits it.
    #
    # TIGERweb gives a real point-level fact: how far to the nearest primary road,
    # secondary road or railroad. >=60 dB is a loud bar that transportation noise
    # only clears close to its source, so a parcel outside every class's
    # attenuation distance is very unlikely to be in the exposed fraction.
    #
    # The refinement only ever IMPROVES a score, and only on positive evidence:
    #   * sources resolved (an outage refines nothing — otherwise one TIGERweb
    #     failure would hand every address in the country a quiet-parcel credit)
    #   * nothing within its threshold
    #   * the tract itself is below the national median, since above it the driver
    #     may be aviation, which is in the BTS map and not in TIGERweb
    # and it floors at the p10 score rather than reaching 100, because the evidence
    # supports "as quiet as the quietest tenth of tracts" and not "exactly zero".
    noise_sources = None
    noise_refined = False
    noise_sources_unavailable = False
    if noise_score is not None and noise.get("pct_ge60db") is not None:
        from housing_label.enrich.road_noise import (
            noise_sources_near, RoadDataUnavailable)
        try:
            noise_sources = noise_sources_near(cfg["lat"], cfg["lon"],
                                               allow_network=allow_network)
        except RoadDataUnavailable:
            # location_notes is assembled further down; record the fact and emit
            # it there rather than reaching forward into a name that does not exist
            # yet.
            noise_sources_unavailable = True
        if (noise_sources is not None
                and not noise_sources["any_within_threshold"]
                and noise["pct_ge60db"] < noise_data.MEDIAN_TRACT_PCT):
            noise_refined = True
            noise_score = max(noise_score, noise_data.QUIET_FLOOR_SCORE)

    # Solar Potential: bundled county rooftop specific yield (PVGIS). Scored whenever
    # a county resolved; the drill-down turns the yield into a representative-system
    # production estimate, the dollars it offsets at the local electricity rate, and
    # the CO₂ it avoids at the marginal grid rate (eGRID average fallback).
    from housing_label.data.solar import (solar_for_county, reading_for_yield,
                                          TYPICAL_SYSTEM_KW)
    solar = solar_for_county(location.county_fips) if have_county else None

    # ── Point-level refinement ────────────────────────────────────────────────
    # The county figure is not a county average. build_solar.py queries PVGIS ONCE
    # per county, at that county's gazetteer internal point, and serves the answer
    # to every parcel in it — so a coastal home under the marine layer and an inland
    # home in the clear got whichever of the two the centroid happened to land near.
    #
    # PVGIS is natively a point API. Asking it about this address is not a new data
    # source or a modelling assumption, it is the same query without the coarsening.
    # So unlike the noise refinement there is no gate and no direction restriction:
    # the point answer is strictly better evidence than the county one and replaces
    # it, up or down.
    #
    # The county figure remains the fallback for off-network runs, for points
    # outside PVGIS-NSRDB coverage, and for an outage — the last of which is said
    # out loud rather than served silently under a parcel-level label.
    solar_point_unavailable = False
    if cfg.get("lat") is not None and cfg.get("lon") is not None:
        from housing_label.enrich.solar_point import (
            solar_yield_near, SolarDataUnavailable)
        try:
            # allow_network is passed through rather than checked here: the lookup
            # returns None off-network, which is the same "no point answer" the
            # caller already handles.
            _pt = solar_yield_near(cfg["lat"], cfg["lon"],
                                   allow_network=allow_network)
        except SolarDataUnavailable:
            _pt = None
            # location_notes is assembled further down; record it and emit it there.
            solar_point_unavailable = True
        if _pt is not None:
            solar = reading_for_yield(_pt["yield_kwh_kwp"], _pt["irradiation"],
                                      "point")
    solar_score = solar["score"] if solar else None

    # Water Quality: bundled county drinking-water compliance (EPA SDWIS). Scored
    # whenever a county resolved; a county with no community water system in SDWIS
    # is left unscored.
    #
    # A home on a private well is left unscored too, and that is not a data gap we
    # are conceding — it is the only honest reading. SDWIS regulates COMMUNITY WATER
    # SYSTEMS; the EPA does not regulate private wells at all, and data/water.py
    # measures the share of a county's CWS-SERVED population under a health-based
    # violation. None of that population is this household. Reporting the county
    # figure here would not be an approximation of their water, it would be a
    # measurement of somebody else's, and the label showed it at full confidence.
    # Well water quality is a function of the individual well — its depth, casing,
    # aquifer and setback from the septic field — and only a lab test of that tap
    # can score it.
    # Not looked up at all on a well, rather than looked up and discarded: nothing
    # downstream reads `water` unless `water_score` is set, so fetching it would only
    # pay to parse the SDWIS table for an answer this home can't use.
    #
    # The owner's own statement wins; otherwise the EPA service-area boundaries
    # answer it. A point inside no mapped COMMUNITY system is evidence of a well —
    # not proof, since ~40% of the layer is EPA-modeled and a small system may be
    # unmapped — but unscoring on that evidence fails in the safe direction: the
    # cost of being wrong is a dimension left blank with a note, against the cost
    # of confidently reporting another population's water. An unreachable service
    # leaves water_system None, which is NOT "outside" and changes nothing.
    ws = getattr(location, "water_system", None) or {}
    stated = cfg.get("water_source")
    on_private_well = resolve_water_source(cfg, location) == "well"
    #
    # When the parcel resolved to a specific PWSID, that system's own SDWIS record
    # is what describes this home's tap — the county aggregate was only ever a
    # stand-in for not knowing which system it was. The county remains the fallback
    # for a system SDWIS has no active record of (a recent merger, a data lag),
    # since scoring an unknown system as clean would be a guess dressed as a fact.
    water = water_sys = None
    if not on_private_well:
        if ws.get("pwsid"):
            from housing_label.data.water_system import water_for_pwsid
            water_sys = water_for_pwsid(ws["pwsid"])
        if water_sys is None and have_county:
            from housing_label.data.water import water_for_county
            water = water_for_county(location.county_fips)
    water_score = water_sys["score"] if water_sys else (water["score"] if water else None)

    scores = {
        "resilience": round(float(resilience_score), 1),
        "energy": construction["energy"],
        "durability": construction["durability"],
        "environmental": construction["environmental"],
        "infrastructure": construction["infrastructure"],
        "health": location_dims["health"],
        "air_quality": air_quality_score,
        "noise": noise_score,
        "socioeconomic": location_dims["socioeconomic"],
        "walkability": location_dims["walkability"],
        "climate": climate_score,
        "solar": solar_score,
        "water": water_score,
    }

    metrics = dict(construction["_metrics"])
    if climate_proj and climate_proj.get("score_high") is not None:
        metrics["Climate band (SSP2-4.5–5-8.5, mid-century)"] = (
            f"{climate_proj['score_low']}–{climate_proj['score_high']}")
    if air_quality and air_quality_score is not None:
        metrics["aq_pm25_ugm3"] = air_quality["pm25"]
        metrics["aq_ozone_ppb"] = air_quality["ozone"]
        metrics["aq_radon_zone"] = air_quality["radon_zone"]
        metrics["aq_radon_label"] = air_quality["radon_label"]
        adj = air_quality.get("radon_adjusted")
        if adj:
            metrics["aq_radon_score"] = air_quality["radon_score"]
            metrics["aq_radon_adjusted_from"] = adj["from"]
            if adj["foundation"]:
                metrics["aq_radon_foundation"] = adj["foundation"]
            if adj["mitigated"]:
                metrics["aq_radon_mitigated"] = True
    if noise and noise_score is not None:
        metrics["noise_pct_ge60db"] = noise["pct_ge60db"]
        if noise_sources is not None:
            for _k, _v in noise_sources["distances_m"].items():
                if _v is not None:
                    metrics[f"noise_{_k}_road_m" if _k != "rail" else "noise_rail_m"] = _v
    if solar and solar_score is not None:
        prod = solar["yield_kwh_kwp"] * TYPICAL_SYSTEM_KW
        metrics["solar_system_kw"] = TYPICAL_SYSTEM_KW
        metrics["solar_yield_kwh_kwp"] = round(solar["yield_kwh_kwp"])
        metrics["solar_annual_kwh"] = round(prod)
        if elec_rate is not None:
            metrics["solar_savings_usd"] = round(prod * elec_rate)
        # Solar displaces marginal generation → value avoided kWh at the Cambium
        # marginal rate where available, else the eGRID average.
        co2_factor = grid_marginal_factor if grid_marginal_factor is not None else grid_factor
        if co2_factor is not None:
            metrics["solar_co2_avoided_kg"] = round(prod * co2_factor)
    if water_sys:
        metrics["water_pwsid"] = water_sys["pwsid"]
        metrics["water_years_in_violation"] = water_sys["years_in_violation"]
        if water_sys["pop_served"]:
            metrics["water_pop_served"] = water_sys["pop_served"]
    elif water and water_score is not None:
        metrics["water_pct_hb_violation"] = water["pct_pop_hb_violation"]
        if water["n_cws"] is not None:      # int count (or None on a blank CSV cell)
            metrics["water_n_cws"] = water["n_cws"]

    dims = []
    from housing_label.data.national_percentile import national_percentile
    for key, label in DIMENSIONS:
        score = scores[key]
        dims.append({
            "key": key,
            "label": label,
            "score": None if score is None else round(float(score), 1),
            "national_grade": score_to_grade(score) if score is not None else "—",
            # National percentile ("vs US homes", higher = better than more homes).
            "national_percentile": national_percentile(key, score),
            # Explicit lookup, not `else`: a dimension added to the roster and to
            # no set should be visibly unclassified rather than silently claimed
            # by whichever branch happens to be last. That default is exactly how
            # Disaster Resilience came to be displayed under "The building itself".
            "kind": ("location" if key in LOCATION_DRIVEN
                     else "construction" if key in CONSTRUCTION_DRIVEN
                     else "context" if key in CONTEXT_ONLY
                     else "unclassified"),
        })

    scored_vals = [d["score"] for d in dims if d["score"] is not None]
    composite = round(sum(scored_vals) / len(scored_vals), 1) if scored_vals else None

    # Resilience contributes to BOTH axes, as its own two legs rather than as one
    # number on one side. See score/resilience.py:resilience_legs.
    # Needs the full simulate() result, not just the combined score: the split
    # lives in the per-peril `*_raw` rates it records. Callers that pass only a
    # score (older tests, the utility-rate fixture) get no legs, and each axis
    # simply averages its remaining members — the same graceful path an unscored
    # dimension already takes.
    from housing_label.score.resilience import resilience_legs
    _legs = (resilience_legs(resilience_result) if resilience_result
             else {"site": None, "building": None, "multiplier": None})

    def _sub(keys: set[str], extra: float | None = None) -> tuple[float | None, int]:
        """Mean of members' NATIONAL PERCENTILES, not of their raw scores.

        Those are different quantities for five of the thirteen dimensions. The
        construction-driven scores are absolute 0-100 values with no percentile
        meaning of their own — they are remapped through a household-weighted
        reference in national_percentile.py — and walkability likewise. At one LA
        point: energy 84.0 -> 95th, environmental 79.4 -> 96th, resilience
        70.3 -> 81st, walkability 66.4 -> 80th. Averaging the raw column mixed
        absolute scores with percentiles and produced a number that was neither.
        """
        vals = [d["national_percentile"] for d in dims
                if d["key"] in keys and d["national_percentile"] is not None]
        if extra is not None:
            # A resilience leg, already a 0-100 score on the same curve the
            # combined dimension uses, so it goes through the same remapping to
            # reach a percentile — not appended raw, which would put an absolute
            # score into a mean of percentiles.
            pct = national_percentile("resilience", extra)
            if pct is not None:
                vals.append(pct)
        return (round(sum(vals) / len(vals), 1) if vals else None), len(vals)

    construction_raw, construction_n = _sub(CONSTRUCTION_DRIVEN, _legs["building"])
    # Ranked against the homes US households live in, for the same reason the site
    # axis is ranked against the places they live: a mean of percentiles is not
    # itself a percentile, and two headline grades that answer different questions
    # are worse than one that answers none.
    from housing_label.data.national_percentile import building_percentile
    construction_score = building_percentile(construction_raw)
    location_raw, location_n = _sub(AGGREGATED_LOCATION, _legs["site"])
    # Ranked against the places US households actually live, because a mean of
    # percentiles cannot reach the ends of a 0-100 ruler on its own — see
    # data/national_percentile.py.
    from housing_label.data.national_percentile import location_percentile
    location_score = location_percentile(location_raw)

    location_notes = dict(location_dims["_notes"])
    if climate_score is not None and climate_proj is not None:
        if not climate_proj.get("resolved"):
            location_notes["climate"] = "CMIP6-LOCA2 (national-average fallback)"
        elif climate_proj.get("geo_level") == "tract":
            location_notes["climate"] = (
                f"CMIP6-LOCA2 (tract {location.tract}, SSP2-4.5 mid-century)")
        else:
            location_notes["climate"] = (
                f"CMIP6-LOCA2 (county {location.county_fips}, SSP2-4.5 mid-century)")
    if air_quality and air_quality_score is not None:
        if air_quality.get("geo_level") == "tract" and location.tract:
            _aq_geo = f"tract {location.tract}"
        else:
            _aq_geo = f"county {location.county_fips}"
        location_notes["air_quality"] = (
            f"CDC Tracking PM2.5/ozone ({_aq_geo}) + EPA radon zone "
            f"(county {location.county_fips})")
    if noise and noise_score is not None:
        _n_geo = (f"tract {location.tract}" if noise.get("geo_level") == "tract" and location.tract
                  else f"county {location.county_fips}")
        if noise_refined:
            _d = noise_sources["distances_m"]
            _near = min((v for v in _d.values() if v is not None), default=None)
            _how = (f"nearest highway, arterial or railroad is {_near:.0f} m away"
                    if _near is not None else
                    "no highway, arterial or railroad within 1.2 km")
            location_notes["noise"] = (
                f"BTS transportation-noise exposure ({_n_geo}), refined to this "
                f"parcel: {_how} — beyond the distance >=60 dB carries, so this "
                f"parcel is very unlikely to be in the tract's exposed share. "
                f"Aviation noise is not visible to this check")
        elif noise_sources_unavailable:
            location_notes["noise"] = (
                f"BTS transportation-noise exposure ({_n_geo}) — TIGERweb "
                f"unavailable, so this is the tract figure, not refined to the parcel")
        else:
            location_notes["noise"] = f"BTS transportation-noise exposure ({_n_geo})"
    if solar and solar_score is not None:
        if solar.get("geo_level") == "point":
            location_notes["solar"] = (
                "PVGIS-NSRDB rooftop yield, queried at this parcel rather than at "
                "the county's centroid. Scored against the national spread of "
                "COUNTY yields, so the percentile still reads \"sunnier than N% of "
                "US counties\"")
        elif solar_point_unavailable:
            location_notes["solar"] = (
                f"PVGIS-NSRDB rooftop yield (county {location.county_fips}) — PVGIS "
                f"unavailable, so this is the county centroid's yield, not this "
                f"parcel's")
        else:
            location_notes["solar"] = (
                f"PVGIS-NSRDB rooftop yield (county {location.county_fips})")
    if getattr(location, "incorporated", None) is False:
        location_notes["infrastructure"] = (
            "unincorporated county territory — no municipal government serves or "
            "taxes this parcel, so municipal curbside collection is not charged to "
            "it (Census TIGER incorporated places)")
    if on_private_well:
        if stated == "well":
            how = "private well, as entered"
        else:
            how = ("no mapped community water system at this point, per EPA service "
                   "areas — evidence of a private well, not proof, since EPA cannot "
                   "confirm service by address")
        # Ends on the county-figure clause rather than an elliptical "…only a lab
        # test of the well can", which reads as though the sentence were truncated.
        location_notes["water"] = (
            f"not scored — {how}. EPA SDWIS covers community water systems only, so "
            "the county figure measures a population this household is not part of. "
            "Only a lab test of this well can describe its water.")
    elif water_sys:
        yrs = water_sys["years_in_violation"]
        # Phrased around YEARS, not violations. "violations in 1 of the last 5
        # years" is both awkward and misleading — the metric counts years out of
        # compliance, and a single such year can contain several violations, so any
        # wording that fronts the violation count claims something not measured.
        record = ("no health-based violation in the last "
                  f"{WATER_RECENT_YEARS} years" if yrs == 0
                  else f"out of health-based compliance in {yrs} of the last "
                       f"{WATER_RECENT_YEARS} years")
        location_notes["water"] = (
            f"EPA SDWIS record for {ws.get('name') or 'the serving system'} "
            f"({water_sys['pwsid']}) — {record}. Matched to this point by EPA "
            f"service-area boundaries")
    elif water and water_score is not None:
        # No SDWIS record for the system EPA maps here (a recent merger, a data
        # lag), so the county aggregate stands in — and the note says which of the
        # two the reader is looking at rather than leaving them the same shape.
        if ws.get("status") == "served" and ws.get("pwsid"):
            location_notes["water"] = (
                f"EPA SDWIS drinking-water compliance (county {location.county_fips}) — "
                f"served by {ws.get('name') or 'PWS'} ({ws['pwsid']}) per EPA service "
                f"areas, but SDWIS has no active record for it, so the county "
                f"aggregate stands in")
        else:
            location_notes["water"] = f"EPA SDWIS drinking-water compliance (county {location.county_fips})"

    return {
        "dimensions": dims,
        "composite_score": composite,
        "composite_national_grade": score_to_grade(composite) if composite is not None else "—",
        "n_scored": len(scored_vals),
        # The two headline axes, graded on the same absolute thresholds as the
        # composite (A >= 80 ... F < 20) — the existing convention, not a new one.
        #
        # MEASURED, because "it should spread better" is a prediction and this is
        # the check. Across the four presets at two fixed points, CONSTRUCTION runs
        # 37.7 (D, worst-case) to 96.4 (A, ICF passive) — a 58.7-point range using
        # the whole scale, which is the split doing its job. Against the old
        # thirteen-dimension composite those same eight houses spanned 43.0-68.5
        # and never left C/B, laundering a D-grade structure into a C.
        #
        # LOCATION does NOT yet grade honestly, and the number should not be read
        # as if it does. Over 40 randomly sampled US tracts it runs 35.5-73.1 with
        # a standard deviation of 8.0, and lands 29/40 in C with no A and no F: an
        # A is over three sigma out, so the letter is close to decorative at the
        # top of the range. That is the same arithmetic compression as before —
        # averaging eight percentiles only widens the spread so far — and the fix
        # is the one solar and climate already had: its own household-weighted
        # reference distribution, which is not in this change.
        #
        # Shipping the raw mean under the existing thresholds is consistent with
        # what the composite already does rather than a fresh overclaim, and the
        # grade is honest at the bottom (a genuinely bad site does score D). The
        # calibration is the next piece of work, not a nice-to-have.
        "construction_score": construction_score,
        "construction_national_grade": (score_to_grade(construction_score)
                                        if construction_score is not None else "—"),
        "construction_n_scored": construction_n,
        "construction_raw_mean": construction_raw,
        "location_score": location_score,
        "location_national_grade": (score_to_grade(location_score)
                                    if location_score is not None else "—"),
        "location_n_scored": location_n,
        # The un-ranked mean the percentile was derived from. Kept because the
        # ranking is a real transformation, not a formatting step, and a reader
        # comparing two labels should be able to see the quantity underneath it.
        "location_raw_mean": location_raw,
        # The two halves resilience was split into, surfaced so the label can
        # explain why one dimension appears on both sides of the split.
        "resilience_site_score": _legs["site"],
        "resilience_building_score": _legs["building"],
        "resilience_building_multiplier": _legs["multiplier"],
        "metrics": metrics,
        "location_notes": location_notes,
        "census_tract": location_dims.get("_tract"),
        "location": location,
    }
