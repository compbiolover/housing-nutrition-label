#!/usr/bin/env python3
"""Offline tests for the all-dimension house simulation.

Runs without network access (location dimensions are skipped) and without
pytest — execute directly:  python tests/test_dimensions.py
(pytest will also collect the test_* functions if it is installed.)
"""

from argparse import Namespace

from housing_label.simulate.house import resolve_config, simulate
from housing_label.simulate.dimensions import (
    build_parcel_row, compute_construction_dimensions, simulate_all_dimensions,
    EXTWALL_CODE, COND_CODE, CONSTRUCTION_DRIVEN, LOCATION_DRIVEN,
)

_FIELDS = ["flood_zone", "year_built", "construction", "foundation",
           "condition", "value", "units", "sqft", "lot_acres"]


def _cfg(preset):
    args = Namespace(preset=preset, lat=35.15, lon=-89.85,
                     **{f: None for f in _FIELDS})
    return resolve_config(args)


def test_autofilled_value_not_divided_across_units():
    """An auto-filled county median is a per-home value, so it must not be split
    again across the unit count (which collapsed the fiscal ratio to ~0 for a
    multi-unit building). An explicit/total value keeps the per-unit division."""
    from housing_label.simulate.dimensions import AUTOFILL_VALUE_SOURCE
    cfg = _cfg("baseline")
    cfg["units"] = 30
    cfg["value"] = 250_000

    # Explicit (total-building) value → divided across the 30 units, as before.
    explicit = build_parcel_row(cfg)
    assert abs(explicit["RTOTAPR"] - 250_000 / 30) < 1e-6

    # Auto-filled per-home median → used as the per-unit value, not divided.
    cfg["value_source"] = AUTOFILL_VALUE_SOURCE
    autofill = build_parcel_row(cfg)
    assert abs(autofill["RTOTAPR"] - 250_000) < 1e-6

    # The value-per-door estimate is likewise per-unit → not divided either.
    from housing_label.simulate.dimensions import VALUE_PER_DOOR_SOURCE
    cfg["value_source"] = VALUE_PER_DOOR_SOURCE
    vpd = build_parcel_row(cfg)
    assert abs(vpd["RTOTAPR"] - 250_000) < 1e-6

    # The fiscal ratio no longer collapses to a 0.0 / F Infrastructure score.
    assert compute_construction_dimensions(cfg)["infrastructure"] > 20


def test_detected_multifamily_autofills_value_per_door():
    """A building detected as multi-family auto-fills the income-based value-per-door
    (not the single-family owner median), so a unit isn't valued as a whole house."""
    import unittest.mock as mock
    from housing_label.simulate import house
    from housing_label.simulate.location import Location
    from housing_label.simulate.dimensions import (
        AUTOFILL_VALUE_SOURCE, VALUE_PER_DOOR_SOURCE,
    )
    from housing_label.data.multifamily_value import value_per_door_for_county
    from housing_label.data.home_value import median_home_value_for
    county_median = median_home_value_for(county_fips="06037")["value"]

    def loc(structure_type):
        return Location(
            lat=34.05, lon=-118.24, state_fips="06", county_fips="06037",
            county_name="LA", tract=None, place_label="LA", in_urban_area=True,
            climate_zone=None, egrid_subregion="CAMX", egrid_factor=None,
            climate_projection=None, wildfire=None, structure_type=structure_type,
            num_units=20 if structure_type == "multifamily" else 1, stories=6,
            bldg_material="concrete", structure_source="NSI", notes=None)

    def cfg_for(structure_type):
        with mock.patch("housing_label.simulate.location.resolve_location",
                        return_value=loc(structure_type)):
            cfg, _, _ = house.build_label_parts(
                lat=34.05, lon=-118.24, preset="baseline", allow_network=False)
        return cfg

    mf = cfg_for("multifamily")
    assert mf["value_source"] == VALUE_PER_DOOR_SOURCE
    assert abs(mf["value"] - value_per_door_for_county("06037")["value_per_door"]) < 1.0
    # A detected apartment unit is valued far below the county single-family median.
    assert mf["value"] < county_median
    # A single-family address at the same county (no tract) keeps the owner-occupied
    # county median (ACS home-value crosswalk).
    sf = cfg_for("single_family")
    assert sf["value_source"] == AUTOFILL_VALUE_SOURCE
    assert abs(sf["value"] - county_median) < 1.0


def test_dollar_eal_uses_the_same_per_unit_value_as_infrastructure():
    """The dollar-denominated EAL is on one representative unit's value — the same
    per-unit basis the Infrastructure fiscal ratio uses — so a multi-unit label
    doesn't mix per-unit and whole-building dollars."""
    from housing_label.simulate.house import simulate
    from housing_label.simulate.dimensions import per_unit_home_value, build_parcel_row

    cfg = _cfg("baseline")
    cfg["units"] = 4
    cfg["value"] = 600_000                       # explicit total-building value

    # per_unit_home_value splits a total value across units, matching the infra basis.
    assert abs(per_unit_home_value(cfg) - 150_000) < 1e-6
    assert abs(build_parcel_row(cfg)["RTOTAPR"] - 150_000) < 1e-6

    r = simulate(cfg)
    assert abs(r["total_loss"] - r["total_eal"] * 150_000) < 1e-6      # per-unit, not 600k

    # Single-family (units 1) is unchanged — the full value is the per-unit value.
    sf = _cfg("baseline")
    sf["value"] = 250_000
    assert per_unit_home_value(sf) == 250_000
    assert abs(simulate(sf)["total_loss"] - simulate(sf)["total_eal"] * 250_000) < 1e-6

    # An already-per-unit auto-fill (county median / value-per-door) with units > 1 is
    # used as-is — NOT divided again — so the EAL stays consistent with infrastructure.
    from housing_label.simulate.dimensions import (
        AUTOFILL_VALUE_SOURCE, VALUE_PER_DOOR_SOURCE,
    )
    for src in (AUTOFILL_VALUE_SOURCE, VALUE_PER_DOOR_SOURCE):
        af = _cfg("baseline")
        af["units"] = 12
        af["value"] = 200_000
        af["value_source"] = src
        assert per_unit_home_value(af) == 200_000            # not 200k / 12
        assert abs(build_parcel_row(af)["RTOTAPR"] - 200_000) < 1e-6
        af_r = simulate(af)
        assert abs(af_r["total_loss"] - af_r["total_eal"] * 200_000) < 1e-6


def test_effective_structure_merges_entered_over_detected():
    """The effective structure trusts an entered unit count as multi-family (even
    when NSI mislabels the site) and uses entered material/stories, ignoring an
    unreliable single-family NSI reading."""
    from types import SimpleNamespace
    from housing_label.simulate.dimensions import effective_structure

    # No location, single unit → single-family, nothing multi-family. Entered
    # material/stories are multi-unit-only and must not leak into a single-family row.
    sf = effective_structure({"units": 1, "bldg_material": "concrete", "stories": 3})
    assert sf["is_multifamily"] is False and sf["mf_units"] is None and sf["mf_material"] is None
    assert sf["bldg_material"] is None and sf["stories"] is None

    # Entered 16 units, no material → multi-family, but no material/stories to score
    # Resilience/Durability with.
    e = effective_structure({"units": 16})
    assert e["is_multifamily"] and e["mf_units"] == 16
    assert e["mf_material"] is None and e["stories"] is None

    # Entered material + stories → carried through (drives Resilience/Durability).
    em = effective_structure({"units": 16, "bldg_material": "Concrete", "stories": 4})
    assert em["mf_material"] == "concrete" and em["stories"] == 4       # normalized lower

    # NSI mislabels the garden complex single-family: its wood/1-story is ignored for
    # a caller-declared multi-unit building — only entered values count.
    mislabel = SimpleNamespace(structure_type="single_family", num_units=1,
                               bldg_material="wood", stories=1)
    m = effective_structure({"units": 16}, mislabel)
    assert m["is_multifamily"] and m["bldg_material"] is None and m["stories"] is None

    # A genuinely detected multi-family uses its detected material/stories as the base.
    detected = SimpleNamespace(structure_type="multifamily", num_units=12,
                               bldg_material="concrete", stories=5)
    d = effective_structure({"units": 1}, detected)
    assert d["is_multifamily"] and d["mf_material"] == "concrete" and d["stories"] == 5
    assert d["mf_units"] == 12

    # An unrecognized material is dropped rather than trusted.
    assert effective_structure({"units": 4, "bldg_material": "adobe"})["mf_material"] is None

    # An invalid (< 1) story count is treated as unknown, not propagated.
    assert effective_structure({"units": 4, "stories": -3})["stories"] is None
    assert effective_structure({"units": 4, "stories": 0})["stories"] is None
    assert effective_structure({"units": 4, "stories": 1})["stories"] == 1


def test_parcel_row_mapping():
    """Config vocabulary maps to the expected CAMA codes (incl. per-unit split)."""
    cfg = _cfg("icf-quadplex")          # 4 units, icf, excellent, 0.20 ac, $600k
    row = build_parcel_row(cfg)
    assert row["EXTWALL"] == EXTWALL_CODE["icf"]      # icf → block/concrete proxy
    assert row["COND"] == COND_CODE["excellent"]      # excellent → 5
    # Per-unit framing: lot acres and value divided by the 4 units.
    assert abs(row["CALC_ACRE"] - 0.20 / 4) < 1e-9
    assert abs(row["RTOTAPR"] - 600_000 / 4) < 1e-6


def test_construction_dimensions_scored():
    """All four construction-driven dimensions score in range for a real house."""
    dims = compute_construction_dimensions(_cfg("baseline"))
    for key in ("energy", "durability", "environmental", "infrastructure"):
        assert dims[key] is not None, f"{key} should be scored"
        assert 0.0 <= dims[key] <= 100.0
    assert dims["_metrics"]["eui_kbtu_sqft_yr"] > 0


def test_better_build_scores_higher():
    """An ICF passive house out-scores the worst-case build on every
    construction-driven dimension (sanity check the models respond to config)."""
    worst = compute_construction_dimensions(_cfg("worst-case"))
    icf = compute_construction_dimensions(_cfg("icf-passive"))
    for key in ("energy", "durability", "environmental", "infrastructure"):
        assert icf[key] > worst[key], f"icf should beat worst-case on {key}"


def test_location_dims_excluded_offline():
    """With network off, location dimensions are None and the composite is the
    mean of only the scored (construction + resilience) dimensions."""
    cfg = _cfg("icf-passive")
    r = simulate(cfg)
    label = simulate_all_dimensions(cfg, r["total_score"], allow_network=False)

    by_key = {d["key"]: d for d in label["dimensions"]}
    for key in LOCATION_DRIVEN:
        assert by_key[key]["score"] is None
        assert by_key[key]["national_grade"] == "—"
    for key in CONSTRUCTION_DRIVEN | {"resilience"}:
        assert by_key[key]["score"] is not None

    assert label["n_scored"] == 5
    scored = [by_key[k]["score"] for k in CONSTRUCTION_DRIVEN | {"resilience"}]
    expected = round(sum(scored) / len(scored), 1)
    assert abs(label["composite_score"] - expected) < 0.05


def test_override_includes_location_dim():
    """A manual override supplies a location dimension without any network call."""
    cfg = _cfg("baseline")
    r = simulate(cfg)
    label = simulate_all_dimensions(
        cfg, r["total_score"], allow_network=False,
        overrides={"walkability": 79.6},
    )
    by_key = {d["key"]: d for d in label["dimensions"]}
    assert by_key["walkability"]["score"] == 79.6
    assert by_key["walkability"]["national_grade"] == "B"
    assert label["n_scored"] == 6


def test_national_location_dims_offline_with_tract():
    """The three bundled national location dimensions (health, socioeconomic,
    walkability) score fully OFFLINE from a known tract — no network, no API key,
    no Walk Score — and their values match the national loaders, with the source +
    vintage named in the notes (honest labeling)."""
    from housing_label.simulate.dimensions import fetch_location_dimensions
    from housing_label.data import health as h_ref
    from housing_label.data import socioeconomic as s_ref
    from housing_label.data import walkability as w_ref

    tract = "47157000200"                       # a real, distressed Memphis tract
    d = fetch_location_dimensions(35.13, -89.99, tract=tract, allow_network=False)

    assert d["health"] == round(h_ref.health_for_tract(tract)["health_index"], 1)
    assert d["socioeconomic"] == round(s_ref.socio_for_tract(tract)["socioeconomic_index"], 1)
    assert d["walkability"] == round(w_ref.walkability_for_tract(tract)["walkability_score"], 1)

    assert "CDC PLACES" in d["_notes"]["health"]
    assert "ACS" in d["_notes"]["socioeconomic"]
    assert "EPA National Walkability Index" in d["_notes"]["walkability"]


def test_embodied_amortized_over_service_life():
    """Embodied carbon is amortized over the shell's service life: a frame shell
    is 60 yr (its embodied sub-score is unchanged from the flat-period model),
    while a concrete/ICF shell is 100 yr and so its embodied sub-score is no
    longer near-zero despite the shell's high upfront embodied intensity."""
    import pandas as pd
    from housing_label.enrich.environmental import (
        service_life_years, model_parcel_environment,
    )
    assert service_life_years(7) == 60.0    # frame
    assert service_life_years(3) == 100.0   # block/concrete (ICF maps here)

    base = dict(SFLA=2000, GRADE=45, est_annual_kwh=3000, est_annual_therms=10,
                RMBED=3, FIXBATH=2, STORIES=1, CALC_ACRE=0.2, acre_outlier=False)
    frame = model_parcel_environment(pd.Series({**base, "EXTWALL": 7}))
    icf = model_parcel_environment(pd.Series({**base, "EXTWALL": 3}))

    assert frame["env_service_life_yr"] == 60
    assert icf["env_service_life_yr"] == 100
    # Frame sits mid-range under the geometry-aware build-up (~77): lower than the
    # old hand-set band gave, because the full foundation + gypsum are now counted.
    assert frame["env_embodied_subscore"] > 55
    # ICF's higher upfront carbon, amortized over 100 yr rather than 60, keeps its
    # embodied sub-score healthy — comparable to (here even above) the wood frame,
    # instead of the near-zero it would be at a flat 60-yr amortization.
    assert icf["env_embodied_subscore"] > 55


def test_resilience_fire_and_uncapped_brm():
    """Fire peril is modeled, the BRM cap is gone (condition bites), and pre-1940
    construction is penalized harder than pre-1970."""
    from housing_label.simulate.house import (
        resolve_config, simulate, code_era_factor, fire_age_factor,
    )

    def cfg(**over):
        fields = {f: None for f in _FIELDS}
        fields.update(over)
        return resolve_config(Namespace(preset="baseline", lat=35.15, lon=-89.85, **fields))

    # Pre-1940 is steeper than pre-1970; fire wiring-era captures the knob-and-tube era.
    assert code_era_factor(1920) == 1.6 > code_era_factor(1965) == 1.3
    assert fire_age_factor(1920) == 1.5 > fire_age_factor(2024)

    r = simulate(cfg(construction="vinyl", year_built=1920, condition="average"))
    # Fire peril is present and folded into the total EAL.
    assert r["fire_adj"] > 0 and "fire_score" in r
    assert abs(r["total_eal"] - (r["flood_adj"] + r["tornado_adj"]
                                 + r["seismic_adj"] + r["fire_adj"])) < 1e-12
    # BRM cap removed: a 1920 frame exceeds the old 1.5 ceiling.
    assert r["wind_seismic_brm"] > 1.5

    # Condition now bites (was flat at the cap before the change).
    avg = simulate(cfg(construction="vinyl", year_built=1920, condition="average"))["total_score"]
    poor = simulate(cfg(construction="vinyl", year_built=1920, condition="poor"))["total_score"]
    assert poor < avg

    # Fire sprinklers reduce the fire peril.
    base = cfg(construction="vinyl", year_built=1920, condition="poor")
    no_spr = simulate(base)["fire_adj"]
    base["fire_sprinklers"] = True
    assert simulate(base)["fire_adj"] < no_spr


def test_upgrades_flow_through_build_label_parts():
    """Resilience upgrades passed to build_label_parts take effect (guards the
    CLI path, which forwards its bonus flags as `upgrades`)."""
    from housing_label.simulate.house import build_label_parts
    common = dict(lat=35.15, lon=-89.85, preset="baseline", construction="frame",
                  year_built=1920, condition="poor", allow_network=False)
    _, base, _ = build_label_parts(**common)
    _, spr, _  = build_label_parts(**common, upgrades=["fire_sprinklers"])
    assert spr["fire_adj"] < base["fire_adj"]          # fire-specific sprinkler effect


def test_attachment_eui_factor_schedule():
    """The shared-wall credit is 1.0 for a detached home and grows with unit count."""
    from housing_label.simulate.dimensions import attachment_eui_factor
    assert attachment_eui_factor(1) == 1.0
    assert attachment_eui_factor(None) == 1.0
    assert attachment_eui_factor(2) < 1.0                       # duplex gets a credit
    assert attachment_eui_factor(50) < attachment_eui_factor(3)  # bigger building → bigger credit


def test_multifamily_energy_credit_improves_score():
    """A unit in a multi-unit building scores better on Energy than the same unit
    modeled as detached, because shared walls lower its EUI."""
    cfg = _cfg("baseline")
    detached = compute_construction_dimensions(cfg)["energy"]
    small_mf = compute_construction_dimensions(cfg, mf_units=3)["energy"]
    large_mf = compute_construction_dimensions(cfg, mf_units=50)["energy"]
    assert small_mf > detached
    assert large_mf > small_mf
    # Single-family (units default 1) is unchanged by the credit.
    assert compute_construction_dimensions(cfg, mf_units=1)["energy"] == detached


def test_flood_floor_factor_schedule():
    """The floor-aware flood factor is 1.0 for a 1-story (or unknown) building and
    shrinks toward the 0.15 floor as the building gets taller."""
    from housing_label.simulate.house import flood_floor_factor
    assert flood_floor_factor(1) == 1.0
    assert flood_floor_factor(None) == 1.0
    assert flood_floor_factor("bad") == 1.0
    assert flood_floor_factor(2) == 0.5
    assert flood_floor_factor(4) == 0.25
    assert flood_floor_factor(100) == 0.15          # floored, never zero
    assert flood_floor_factor(20) < flood_floor_factor(3)


def test_multifamily_material_improves_resilience():
    """A detected multi-family building scored with a concrete/masonry structure is
    more resilient (higher score, lower EAL) than the same unit modeled with the
    single-family construction profile; a wood-framed multi-family is unchanged."""
    cfg = _cfg("baseline")          # frame construction, single-family defaults

    sf = simulate(cfg)
    concrete = simulate(cfg, structure={"structure_type": "multifamily",
                                         "bldg_material": "concrete", "stories": 4})
    masonry = simulate(cfg, structure={"structure_type": "multifamily",
                                       "bldg_material": "masonry", "stories": 3})
    wood = simulate(cfg, structure={"structure_type": "multifamily",
                                    "bldg_material": "wood", "stories": 3})

    assert concrete["total_score"] > sf["total_score"]
    assert masonry["total_score"] > sf["total_score"]
    assert concrete["total_score"] > masonry["total_score"]   # concrete beats masonry
    # A material we don't have a resilience profile for keeps the single-family
    # wind/seismic factors (only the height-based flood term still applies).
    assert wood["wind_seismic_brm"] == sf["wind_seismic_brm"]
    single_story_wood = simulate(cfg, structure={"structure_type": "multifamily",
                                                 "bldg_material": "wood", "stories": 1})
    assert single_story_wood["total_score"] == sf["total_score"]


def test_floor_aware_flood_only_for_multifamily():
    """Flood exposure drops with building height for a detected multi-family unit,
    but a single-family home (no structure) keeps full ground-floor exposure."""
    cfg = _cfg("baseline")
    sf = simulate(cfg)
    assert sf["flood_floor"] == 1.0

    tall = simulate(cfg, structure={"structure_type": "multifamily",
                                    "bldg_material": "concrete", "stories": 5})
    assert tall["flood_floor"] == 0.2
    assert tall["flood_adj"] < sf["flood_adj"]

    # A detected single-family structure gets no floor reduction.
    sf_struct = simulate(cfg, structure={"structure_type": "single_family",
                                         "bldg_material": "wood", "stories": 2})
    assert sf_struct["flood_floor"] == 1.0


def test_age_basket_shell_life_override():
    """Lengthening the structural-shell service life raises the weighted
    remaining-life for an aged building and can pull a past-life shell back within
    life."""
    from housing_label.enrich.durability import age_basket
    base_score, base_past = age_basket(105.0)               # shell past its 100 yr life
    mf_score, mf_past = age_basket(105.0, shell_life=120.0)  # concrete/steel shell
    assert mf_score > base_score
    assert mf_past < base_past                               # shell no longer past-life
    # A shorter age below every life leaves the shell not-yet-past either way.
    assert age_basket(10.0, shell_life=120.0)[0] > age_basket(10.0)[0]


def test_multifamily_durable_shell_improves_durability():
    """A detected multi-family building with a concrete/steel/masonry shell scores
    higher on Durability than the same unit with the wood-frame baseline; a
    wood-framed (or unknown) multi-family is unchanged."""
    from housing_label.enrich.durability import model_parcel_durability
    row = build_parcel_row(_cfg("baseline"))                 # has a build year

    base = model_parcel_durability(row)["durability_score"]
    concrete = model_parcel_durability(row, mf_material="concrete")["durability_score"]
    masonry = model_parcel_durability(row, mf_material="masonry")["durability_score"]
    wood = model_parcel_durability(row, mf_material="wood")["durability_score"]

    assert concrete > base
    assert masonry > base
    assert concrete >= masonry                               # concrete/steel life ≥ masonry
    assert wood == base                                      # no profile → baseline


def test_durability_shell_flows_through_dimensions():
    """The material-driven shell threads through compute_construction_dimensions."""
    cfg = _cfg("baseline")
    base = compute_construction_dimensions(cfg)["durability"]
    mf = compute_construction_dimensions(cfg, mf_material="steel")["durability"]
    assert mf > base


def test_detected_multifamily_density_improves_infrastructure():
    """A building only *detected* as multi-family folds its unit count into the
    DU/acre density, so its shared land/services amortize and Infrastructure scores
    higher than the same lot read as a single detached home."""
    cfg = _cfg("baseline")                                   # no explicit units → 1
    base = compute_construction_dimensions(cfg)["infrastructure"]
    small = compute_construction_dimensions(cfg, mf_units=4)["infrastructure"]
    large = compute_construction_dimensions(cfg, mf_units=24)["infrastructure"]
    assert small > base
    assert large > small
    # A detected count of 1 (or None) is a no-op — single-family is unchanged.
    assert compute_construction_dimensions(cfg, mf_units=1)["infrastructure"] == base
    assert compute_construction_dimensions(cfg, mf_units=None)["infrastructure"] == base


def test_explicit_units_not_double_counted_by_detection():
    """When the unit count is already entered (build_parcel_row splits the lot),
    a detected count that isn't larger doesn't scale the density a second time."""
    cfg = _cfg("icf-quadplex")                               # 4 units entered
    base = compute_construction_dimensions(cfg)["infrastructure"]
    # mf_units equal to (or below) the entered count → no extra scaling.
    assert compute_construction_dimensions(cfg, mf_units=4)["infrastructure"] == base
    assert compute_construction_dimensions(cfg, mf_units=2)["infrastructure"] == base


def test_multifamily_drops_private_yard_water():
    """A stacked/attached multi-unit unit carries no private-yard irrigation, so its
    water use is indoor-only and lower than the same parcel as a detached home."""
    from housing_label.enrich.environmental import water_use_gal_yr
    args = dict(rmbed=3, fixbath=2, sfla=2000, stories=1, calc_acre=0.25,
                acre_outlier=False)
    detached, _ = water_use_gal_yr(**args)
    mf, _ = water_use_gal_yr(**args, is_multifamily=True)
    assert mf < detached                                     # outdoor irrigation gone
    # Indoor-only water is unchanged whatever the lot area for a multi-unit unit.
    mf_big_lot, _ = water_use_gal_yr(**{**args, "calc_acre": 5.0}, is_multifamily=True)
    assert mf_big_lot == mf


def test_multifamily_environmental_score_improves():
    """Dropping the private-yard water raises the Environmental score for a detected
    or entered multi-unit building; single-family (units 1/None) is unchanged."""
    cfg = _cfg("baseline")
    detached = compute_construction_dimensions(cfg)["environmental"]
    mf = compute_construction_dimensions(cfg, mf_units=4)["environmental"]
    assert mf > detached
    assert compute_construction_dimensions(cfg, mf_units=1)["environmental"] == detached
    assert compute_construction_dimensions(cfg, mf_units=None)["environmental"] == detached
    # A detected multi-family with no reliable unit count (mf_material set, mf_units
    # None) still drops the private yard, matching the caveat.
    assert compute_construction_dimensions(cfg, mf_material="concrete")["environmental"] > detached


def test_density_comparison_threads_material_and_stories():
    """The density what-if forwards entered material/stories to each scenario, so a
    multi-unit scenario's Resilience reflects the building (not single-family), while
    the 1-unit scenario stays single-family (1 unit isn't a multi-unit building)."""
    import unittest.mock as mock
    from housing_label.simulate import house
    from housing_label.simulate.location import Location

    def loc():
        return Location(
            lat=35.94, lon=-83.93, state_fips="47", county_fips="47093", county_name="Knox",
            tract=None, place_label="Knox", in_urban_area=True, climate_zone=None,
            egrid_subregion="SRTV", egrid_factor=None, climate_projection=None, wildfire=None,
            structure_type="single_family", num_units=1, stories=1, bldg_material="wood",
            structure_source="NSI", notes=None)

    def resilience(scn):
        dims = scn.get("dimensions") or []
        hit = [d["score"] for d in dims if d["key"] == "resilience"]
        return hit[0] if hit else scn.get("resilience")

    with mock.patch("housing_label.simulate.location.resolve_location", return_value=loc()):
        plain = house.density_comparison(lat=35.94, lon=-83.93, preset="baseline",
                                         allow_network=False, unit_counts=[1, 4])
        conc = house.density_comparison(lat=35.94, lon=-83.93, preset="baseline",
                                        allow_network=False, unit_counts=[1, 4],
                                        bldg_material="concrete", stories=4)

    by_units = lambda d: {s["units"]: resilience(s) for s in d["scenarios"]}
    plain_r, conc_r = by_units(plain), by_units(conc)
    # 4-unit scenario improves with a concrete shell; the 1-unit scenario is unchanged.
    assert conc_r[4] > plain_r[4]
    assert conc_r[1] == plain_r[1]


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
