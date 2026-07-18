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
import pandas as pd

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
EXTWALL_CODE = {
    "frame": 7, "vinyl": 5, "brick-frame": 9, "brick": 1,
    "block": 3, "stone": 4, "icf": 3, "sip": 7,
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
    "block": 46, "stone": 52, "icf": 50, "sip": 45,
}

# ── High-performance feature adjustments (v1 estimates, like the BRM bonuses) ──
# Applied to the modeled EUI before scoring the energy dimension and before
# deriving operational carbon for the environmental dimension.
#   • ICF/SIP envelopes outperform the EXTWALL masonry proxy on air-tightness and
#     continuous insulation.
#   • Passive-house certification targets ~40–60% below code (PHIUS / RMI).
ENVELOPE_EUI_FACTOR = {"icf": 0.92, "sip": 0.95}
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
CONSTRUCTION_DRIVEN = {"energy", "durability", "environmental", "infrastructure"}
LOCATION_DRIVEN = {"health", "air_quality", "noise", "socioeconomic", "walkability", "climate", "solar", "water"}


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


def build_parcel_row(cfg: dict) -> pd.Series:
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

    return pd.Series({
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
    })


def _adjusted_energy(cfg: dict, row: pd.Series, climate_zone: str | None = None,
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
    infra = infra_enrich_row(infra_row, **infra_params) if infra_params else infra_enrich_row(infra_row)
    fr = infra.get("fiscal_ratio")
    infrastructure_score = (
        round(_loglin(fr, INFRA_XS, INFRA_YS), 1)
        if fr is not None and not pd.isna(fr) else None
    )

    metrics = {
        "eui_kbtu_sqft_yr": eui,
        "est_monthly_energy_cost": energy.get("est_monthly_energy_cost"),
        "fiscal_ratio": None if fr is None or pd.isna(fr) else round(float(fr), 2),
        "est_annual_infra_cost": infra.get("est_annual_infra_cost"),
        "est_property_tax": infra.get("est_property_tax"),
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
    infra_params = infra_params_for_county(
        location.county_fips if location else None,
        in_urban_area=location.in_urban_area if location else None,
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
        mf_units=mf_units, mf_material=mf_material, building_type=building_type)
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
    air_quality_score = air_quality["score"] if air_quality else None

    # Noise: bundled tract transportation-noise exposure (BTS/UW). Resolved at the
    # tract (county-mean fallback); a location absent from the map is left unscored.
    from housing_label.data.noise import noise_for_tract, noise_for_county
    noise = None
    if tract:
        noise = noise_for_tract(tract)
    elif have_county:
        noise = noise_for_county(location.county_fips)
    noise_score = noise["score"] if noise else None

    # Solar Potential: bundled county rooftop specific yield (PVGIS). Scored whenever
    # a county resolved; the drill-down turns the yield into a representative-system
    # production estimate, the dollars it offsets at the local electricity rate, and
    # the CO₂ it avoids at the marginal grid rate (eGRID average fallback).
    from housing_label.data.solar import solar_for_county, TYPICAL_SYSTEM_KW
    solar = solar_for_county(location.county_fips) if have_county else None
    solar_score = solar["score"] if solar else None

    # Water Quality: bundled county drinking-water compliance (EPA SDWIS). Scored
    # whenever a county resolved; a county with no community water system in SDWIS
    # is left unscored.
    from housing_label.data.water import water_for_county
    water = water_for_county(location.county_fips) if have_county else None
    water_score = water["score"] if water else None

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
    if noise and noise_score is not None:
        metrics["noise_pct_ge60db"] = noise["pct_ge60db"]
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
    if water and water_score is not None:
        metrics["water_pct_hb_violation"] = water["pct_pop_hb_violation"]
        metrics["water_n_cws"] = round(water["n_cws"])

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
            "kind": "location" if key in LOCATION_DRIVEN else "construction",
        })

    scored_vals = [d["score"] for d in dims if d["score"] is not None]
    composite = round(sum(scored_vals) / len(scored_vals), 1) if scored_vals else None

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
        location_notes["noise"] = f"BTS transportation-noise exposure ({_n_geo})"
    if solar and solar_score is not None:
        location_notes["solar"] = f"PVGIS-NSRDB rooftop yield (county {location.county_fips})"
    if water and water_score is not None:
        location_notes["water"] = f"EPA SDWIS drinking-water compliance (county {location.county_fips})"

    return {
        "dimensions": dims,
        "composite_score": composite,
        "composite_national_grade": score_to_grade(composite) if composite is not None else "—",
        "n_scored": len(scored_vals),
        "metrics": metrics,
        "location_notes": location_notes,
        "census_tract": location_dims.get("_tract"),
        "location": location,
    }
