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
  • Health             → enrich.health        (CDC PLACES, live fetch)
  • Socioeconomic      → enrich.socioeconomic (Census ACS, live fetch)
  • Walkability        → enrich.walkscore     (Walk Score API, live fetch)

Construction-driven dimensions (energy, durability, environmental,
infrastructure) are computed offline from the house config. The three
location-driven dimensions (health, socioeconomic, walkability) are fetched
live for the house's lat/lon. When a source is unavailable (no network, no API
key, point outside the dataset) the dimension is returned as ``None`` and is
*excluded* from the composite — it is never filled with a placeholder, so an
otherwise-excellent house is not unfairly down-weighted by a missing input.

Config → CAMA mapping
---------------------
The simulator speaks a human vocabulary (construction="icf",
condition="excellent"); the enrichment models speak Shelby County CAMA codes
(EXTWALL=3, COND=5, …). ``build_parcel_row`` translates between the two.
"""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
import pandas as pd

from housing_label.score.all_dimensions import (
    ENERGY_XS, ENERGY_YS, INFRA_XS, INFRA_YS, score_to_grade,
)
from housing_label.enrich.energy import model_parcel_energy
from housing_label.enrich.durability import model_parcel_durability
from housing_label.enrich.environmental import model_parcel_environment
from housing_label.enrich.infrastructure import enrich_row as infra_enrich_row


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
# Rooftop solar offsets grid electricity for the *operational-carbon* leg of the
# environmental score (net-metering). It does not change the envelope EUI used
# for the energy-efficiency dimension. ~70% of annual electricity offset.
SOLAR_OPERATIONAL_REMAINING = 0.30

# Infrastructure: Shelby keeps its Memphis calibration; elsewhere a national model
# applies. National effective property-tax rate ≈ 1.1% of market value (US median;
# applied with assess_ratio 1.0).
SHELBY_COUNTY_FIPS = "47157"
NATIONAL_EFFECTIVE_TAX_RATE = 0.011

# Dimension display order / labels (mirrors score/all_dimensions).
DIMENSIONS = [
    ("resilience",     "Disaster Resilience"),
    ("energy",         "Energy Efficiency"),
    ("durability",     "Durability"),
    ("environmental",  "Environmental Footprint"),
    ("infrastructure", "Infrastructure Burden"),
    ("health",         "Health Impact"),
    ("socioeconomic",  "Socioeconomic"),
    ("walkability",    "Walkability"),
    ("climate",        "Climate Projections"),
]
CONSTRUCTION_DRIVEN = {"energy", "durability", "environmental", "infrastructure"}
LOCATION_DRIVEN = {"health", "socioeconomic", "walkability", "climate"}


def _loglin(x: float, xs: list[float], ys: list[float]) -> float:
    """Scalar piecewise-linear interpolation in log10(x) space (clamped)."""
    return float(np.interp(np.log10(max(float(x), 1e-9)), np.log10(xs), ys))


# ── Build a synthetic CAMA parcel row from the simulator config ─────────────────
def build_parcel_row(cfg: dict) -> pd.Series:
    """Translate a simulator config dict into a one-parcel CAMA-style Series.

    Per-unit framing: value and lot area are divided by the unit count so the
    infrastructure fiscal ratio and environmental water/footprint are reported
    per dwelling unit (matching how the multi-unit case studies are presented).
    """
    units = max(int(cfg.get("units", 1) or 1), 1)
    construction = cfg["construction"]
    per_unit_acres = float(cfg.get("lot_acres", 0.25)) / units
    per_unit_value = float(cfg.get("value", 160_000)) / units

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
        "STORIES":   np.nan,
        "CALC_ACRE": per_unit_acres,
        "acre_outlier": False,
        "RTOTAPR":   per_unit_value,
        "latitude":  cfg["lat"],
        "longitude": cfg["lon"],
    })


def _adjusted_energy(cfg: dict, row: pd.Series, climate_zone: str | None = None) -> dict:
    """Run the energy model, then apply the high-performance feature factors.

    Returns the energy dict with eui / kwh / therms scaled, plus a separate
    ``env_kwh`` that additionally folds in the rooftop-solar offset for the
    environmental operational-carbon calculation. ``climate_zone`` (IECC label)
    scales the base EUI for the location; None falls back to the 4A baseline.
    """
    energy = model_parcel_energy(row, climate_zone)
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

    # Operational carbon basis: apply the solar offset on top of the envelope EUI.
    solar_factor = SOLAR_OPERATIONAL_REMAINING if cfg.get("solar") else 1.0
    energy["env_kwh"] = round((energy.get("est_annual_kwh") or 0.0) * solar_factor, 1)
    return energy


# ── Construction-driven dimensions (offline) ───────────────────────────────────
def compute_construction_dimensions(cfg: dict, climate_zone: str | None = None,
                                    grid_factor: float | None = None,
                                    infra_params: dict | None = None) -> dict:
    """Compute energy / durability / environmental / infrastructure scores
    (0–100, or None when the model cannot score the parcel).

    ``climate_zone`` (IECC) scales the energy model; ``grid_factor`` (kgCO2e/kWh)
    drives the environmental operational-carbon leg; ``infra_params`` overrides the
    Memphis infrastructure calibration with a national-average one. All fall back
    to the Shelby/4A pilot defaults when None."""
    row = build_parcel_row(cfg)
    energy = _adjusted_energy(cfg, row, climate_zone)

    # Energy: lower EUI → higher score (same breakpoints as the pipeline).
    eui = energy.get("eui_kbtu_sqft_yr")
    energy_score = round(_loglin(eui, ENERGY_XS, ENERGY_YS), 1) if eui is not None else None

    # Durability: passthrough 0–100 from the component-lifespan model.
    dur = model_parcel_durability(row)
    durability_score = dur.get("durability_score")

    # Environmental: feed the solar/envelope-adjusted electricity in so the
    # operational-carbon leg reflects the high-performance features.
    env_row = row.copy()
    env_row["est_annual_kwh"] = energy.get("env_kwh")
    env_row["est_annual_therms"] = energy.get("est_annual_therms")
    env = (model_parcel_environment(env_row, grid_factor) if grid_factor is not None
           else model_parcel_environment(env_row))
    environmental_score = env.get("environmental_score")

    # Infrastructure: fiscal ratio → score (higher ratio → higher score).
    infra = infra_enrich_row(row, **infra_params) if infra_params else infra_enrich_row(row)
    fr = infra.get("fiscal_ratio")
    infrastructure_score = (
        round(_loglin(fr, INFRA_XS, INFRA_YS), 1)
        if fr is not None and not pd.isna(fr) else None
    )

    return {
        "energy": energy_score,
        "durability": durability_score,
        "environmental": environmental_score,
        "infrastructure": infrastructure_score,
        # Side metrics surfaced on the label / for debugging.
        "_metrics": {
            "eui_kbtu_sqft_yr": eui,
            "est_monthly_energy_cost": energy.get("est_monthly_energy_cost"),
            "fiscal_ratio": None if fr is None or pd.isna(fr) else round(float(fr), 2),
            "est_annual_infra_cost": infra.get("est_annual_infra_cost"),
        },
    }


# ── Location-driven dimensions (live fetch, cached per process) ─────────────────
@lru_cache(maxsize=8)
def _places_table(county_fips: str):
    """CDC PLACES table (tract → health_index) for a county. Cached per process."""
    from housing_label.enrich import health as health_mod
    return health_mod.fetch_places_data(county_fips)


@lru_cache(maxsize=8)
def _acs_table(state_fips: str, county3: str):
    """Census ACS table (tract → socioeconomic_index) for a county. Cached."""
    from housing_label.enrich import socioeconomic as socio_mod
    table, _vintage = socio_mod.fetch_acs_data(socio_mod.DEFAULT_YEAR, state_fips, county3)
    return table


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
    omitted it is geocoded from lat/lon. The county/state FIPS for the CDC PLACES
    and Census ACS queries are derived from the tract (GEOID = state+county+tract),
    so health and socioeconomic are ranked within that location's own county.

    Manual ``overrides`` always win. Otherwise each dimension is fetched live; any
    failure yields ``None`` for that dimension (excluded from the composite, never
    placeholdered). Also returns ``_tract`` and ``_notes``.
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

    need_tract = any(out[k] is None for k in ("health", "socioeconomic"))
    walk_override = "walkability" in notes

    if not allow_network:
        for k in ("health", "socioeconomic", "walkability"):
            notes.setdefault(k, "skipped (--no-fetch)")
        return out

    # Census tract (shared by health + socioeconomic) — geocode only if needed.
    if tract is None and need_tract:
        try:
            tract = _tract_for(round(float(lat), 6), round(float(lon), 6))
        except Exception as exc:  # noqa: BLE001
            notes["health"] = notes.get("health") or f"geocoder failed: {exc}"
            notes["socioeconomic"] = notes.get("socioeconomic") or f"geocoder failed: {exc}"
    out["_tract"] = tract
    county5 = tract[:5] if tract else None       # state(2)+county(3) from GEOID

    # Health (CDC PLACES percentile index for the tract, ranked within its county).
    if out["health"] is None:
        if tract and county5:
            try:
                table = _places_table(county5)
                if tract in table.index and not pd.isna(table.loc[tract, "health_index"]):
                    out["health"] = round(float(table.loc[tract, "health_index"]), 1)
                    notes["health"] = f"CDC PLACES (tract {tract})"
                else:
                    notes["health"] = f"no PLACES data for tract {tract}"
            except Exception as exc:  # noqa: BLE001
                notes["health"] = f"PLACES fetch failed: {exc}"
        else:
            notes.setdefault("health", "no census tract")

    # Socioeconomic (Census ACS percentile index for the tract).
    # The Census ACS API now requires a key — short-circuit with a clear note
    # rather than burning retries on the missing-key redirect.
    if out["socioeconomic"] is None:
        if not os.environ.get("CENSUS_API_KEY", "").strip():
            notes["socioeconomic"] = "no CENSUS_API_KEY"
        elif tract and county5:
            try:
                table = _acs_table(county5[:2], county5[2:])
                if tract in table.index and not pd.isna(table.loc[tract, "socioeconomic_index"]):
                    out["socioeconomic"] = round(float(table.loc[tract, "socioeconomic_index"]), 1)
                    notes["socioeconomic"] = f"Census ACS (tract {tract})"
                else:
                    notes["socioeconomic"] = f"no ACS data for tract {tract}"
            except Exception as exc:  # noqa: BLE001
                notes["socioeconomic"] = f"ACS fetch failed: {exc}"
        else:
            notes.setdefault("socioeconomic", "no census tract")

    # Walkability (Walk Score API — requires a paid key).
    if not walk_override:
        api_key = os.environ.get("WALKSCORE_API_KEY", "").strip()
        if not api_key:
            notes["walkability"] = "no WALKSCORE_API_KEY"
        else:
            try:
                from housing_label.enrich import walkscore as walk_mod
                s = walk_mod.fetch_scores(api_key, lat, lon, "")
                walk = s.get("walk_score")
                transit = s.get("transit_score")
                bike = s.get("bike_score")
                if walk is not None:
                    if transit is not None and bike is not None:
                        composite = 0.60 * walk + 0.25 * transit + 0.15 * bike
                    else:
                        composite = float(walk)
                    out["walkability"] = round(composite, 1)
                    notes["walkability"] = "Walk Score API"
                else:
                    notes["walkability"] = "Walk Score returned no data"
            except Exception as exc:  # noqa: BLE001
                notes["walkability"] = f"Walk Score fetch failed: {exc}"

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
    tract = location.tract if location else None

    # Infrastructure: for confirmed non-Shelby locations, use a national effective
    # property-tax rate (revenue side) and recalibrate the cost curves to the
    # county's local-government spending via the Census of Governments crosswalk
    # (cost side). The Memphis calibration is kept for Shelby (multipliers there
    # are 1.0 by construction) and when the county is unknown.
    infra_params = None
    if location and location.county_fips and location.county_fips != SHELBY_COUNTY_FIPS:
        from housing_label.data.govfinance import govfinance_for_county
        gov = govfinance_for_county(location.county_fips)
        infra_params = {
            "assess_ratio": 1.0,
            "tax_rate": NATIONAL_EFFECTIVE_TAX_RATE,
            "in_urban_area": bool(location.in_urban_area),
            "cost_multipliers": gov["multipliers"],
        }

    construction = compute_construction_dimensions(
        cfg, climate_zone=climate_zone, grid_factor=grid_factor,
        infra_params=infra_params)
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

    scores = {
        "resilience": round(float(resilience_score), 1),
        "energy": construction["energy"],
        "durability": construction["durability"],
        "environmental": construction["environmental"],
        "infrastructure": construction["infrastructure"],
        "health": location_dims["health"],
        "socioeconomic": location_dims["socioeconomic"],
        "walkability": location_dims["walkability"],
        "climate": climate_score,
    }

    metrics = dict(construction["_metrics"])
    if climate_proj and climate_proj.get("score_high") is not None:
        metrics["Climate band (SSP2-4.5–5-8.5, mid-century)"] = (
            f"{climate_proj['score_low']}–{climate_proj['score_high']}")

    dims = []
    for key, label in DIMENSIONS:
        score = scores[key]
        dims.append({
            "key": key,
            "label": label,
            "score": None if score is None else round(float(score), 1),
            "national_grade": score_to_grade(score) if score is not None else "—",
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
