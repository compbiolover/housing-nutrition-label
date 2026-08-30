#!/usr/bin/env python3
"""Tests for above-code bonus aggregation (BONUS_GROUPS / BONUS_FLOOR).

Bonuses used to be multiplied together, one constant per checked flag. That is
not how any published source prices these features — ARA's Florida study uses a
joint lookup table and states outright that "one cannot add the individual
effects together", because the envelope is a serial system where fixing one link
is worth less once another governs.

The concrete symptom, and the regression these tests lock down, was an
inversion: stacking the seven individual wind flags produced a 86.6% loss cut,
beating FORTIFIED Gold's 80% — even though the code deliberately makes the
certification supersede those very features, and Gold's number is the
best-evidenced one in the file (IBHS Hurricane Sally, n~40,000). A pile of
self-reported checkboxes outscored the engineer-stamped, inspected composite.

This file alone:  pytest tests/test_bonus_aggregation.py
"""

from __future__ import annotations

import numpy as np

from housing_label.simulate.house import (
    simulate, PRESETS, combine_bonuses, superseded_bonuses,
    BONUS_FORTIFIED_GOLD, BONUS_ELEVATION_3FT, BONUS_HIP_ROOF,
    BONUS_HURRICANE_STRAPS, BONUS_METAL_ROOF, BONUS_FLOOD_VENTS,
    BONUS_BACKFLOW_VALVE, BONUS_SUMP_BACKUP,
    TORNADO_BONUS_MODIFIERS, FLOOD_BONUS_MODIFIERS,
)

ALL_WIND = dict(hurricane_straps=True, hip_roof=True, impact_garage_door=True,
                sealed_roof_deck=True, metal_roof=True, reinforced_gable=True,
                ring_shank_nails=True)


def _cfg(**kw) -> dict:
    cfg = dict(PRESETS["baseline"])
    cfg.update(lat=35.13, lon=-89.99, flood_zone="AE", tornado_eal_base=0.0002)
    cfg.update(kw)
    return cfg


def _leg(leg: str, **kw) -> float:
    """One hazard leg, as a ratio against the same config with no upgrades, so the
    BRM (which foundation and construction also move) cancels out."""
    plain = dict(kw)
    for flag in list(plain):
        if plain[flag] is True:
            plain.pop(flag)
    return simulate(_cfg(**kw))[leg] / simulate(_cfg(**plain))[leg]


def test_wind_components_cannot_outscore_the_certification():
    """The regression that motivated the rule. Every individual wind flag set must
    still leave FORTIFIED Gold strictly better — Gold *is* the inspected composite
    of those features, so claiming the parts must never beat proving the whole."""
    components = _leg("tornado_adj", **ALL_WIND)
    assert components > BONUS_FORTIFIED_GOLD, (
        f"self-reported components ({components:.4f}) beat FORTIFIED Gold "
        f"({BONUS_FORTIFIED_GOLD}) — the inversion is back")

    # And the Gold branch itself is untouched: it supersedes, it does not stack.
    gold = _leg("tornado_adj", fortified_gold=True, **ALL_WIND)
    assert np.isclose(gold, BONUS_FORTIFIED_GOLD)
    assert gold < components


def test_same_failure_path_collapses_to_the_strongest():
    """Flags in one BONUS_GROUPS group do not stack — the lowest modifier wins.
    Sealed roof deck and a rated metal roof both buy "water stays out once the
    cover is stressed"; ARA couples them explicitly."""
    both = _leg("tornado_adj", sealed_roof_deck=True, metal_roof=True)
    assert np.isclose(both, BONUS_METAL_ROOF)          # not the product

    # The superseded flag is named rather than silently dropped.
    r = simulate(_cfg(sealed_roof_deck=True, metal_roof=True))
    assert r["superseded_upgrades"] == ["sealed_roof_deck"]
    assert "Counted once" in r["superseded_note"]


def test_different_failure_paths_still_multiply():
    """The rule is not "take the single best modifier". Roof shape and roof-uplift
    load path are separate ARA primary dimensions acting on different mechanisms
    (aerodynamic demand vs connection capacity), so they compound."""
    both = _leg("tornado_adj", hip_roof=True, hurricane_straps=True)
    assert np.isclose(both, BONUS_HIP_ROOF * BONUS_HURRICANE_STRAPS)
    assert simulate(_cfg(hip_roof=True, hurricane_straps=True))["superseded_upgrades"] == []


def test_flood_elevation_supersedes_vents_and_floors_the_leg():
    """FEMA's elevation figure is a TOTAL residual, and FEMA prices flood openings
    from a table indexed BY first floor height (-1.7% at 3 ft). So elevation
    supersedes vents, and nothing may push the leg below the elevation figure."""
    elev_only = _leg("flood_adj", foundation="crawl", elevation_3ft=True)
    assert np.isclose(elev_only, BONUS_ELEVATION_3FT)

    with_vents = _leg("flood_adj", foundation="crawl",
                      elevation_3ft=True, flood_vents=True)
    assert np.isclose(with_vents, BONUS_ELEVATION_3FT)      # vents add nothing

    everything = _leg("flood_adj", foundation="crawl", elevation_3ft=True,
                      flood_vents=True, backflow_valve=True, sump_backup=True)
    assert np.isclose(everything, BONUS_ELEVATION_3FT), "flood floor not applied"


def test_flood_vents_need_an_enclosure_to_vent():
    """FEMA's openings discount is available only for crawlspace and
    elevated-with-enclosure foundations — never slab. A slab has no enclosure, so
    the claim earns nothing and is named."""
    assert np.isclose(_leg("flood_adj", foundation="crawl", flood_vents=True),
                      BONUS_FLOOD_VENTS)
    assert np.isclose(_leg("flood_adj", foundation="slab", flood_vents=True), 1.0)
    assert simulate(_cfg(foundation="slab", flood_vents=True))[
        "inapplicable_upgrades"] == ["flood_vents"]


def test_backflow_and_sump_stay_independent_of_elevation():
    """Sewer backup and sump discharge are a different water path from the
    depth-damage inundation elevation prices, so absent elevation they compound."""
    both = _leg("flood_adj", foundation="crawl",
                backflow_valve=True, sump_backup=True)
    assert np.isclose(both, BONUS_BACKFLOW_VALVE * BONUS_SUMP_BACKUP)


def test_unclassified_flags_degrade_to_independent_multiplication():
    """A constant added to a modifier map but not to any group must still apply,
    so forgetting to classify one is a missed grouping rather than a lost credit."""
    mods = {"hip_roof": 0.5, "not_a_group_member": 0.5}
    cfg = {"hip_roof": True, "not_a_group_member": True}
    assert np.isclose(combine_bonuses(cfg, "tornado", mods), 0.25)
    assert superseded_bonuses(cfg, "tornado", mods) == []


def test_floor_binds_only_when_the_stack_would_pass_it():
    """The floor is a bound, not a target: a modest upgrade set keeps its own
    value rather than being snapped to the composite."""
    one = combine_bonuses({"hip_roof": True}, "tornado", TORNADO_BONUS_MODIFIERS)
    assert np.isclose(one, BONUS_HIP_ROOF) and one > BONUS_FORTIFIED_GOLD

    everything = combine_bonuses({k: True for k in TORNADO_BONUS_MODIFIERS},
                                 "tornado", TORNADO_BONUS_MODIFIERS)
    assert everything >= BONUS_FORTIFIED_GOLD

    assert combine_bonuses({k: True for k in FLOOD_BONUS_MODIFIERS},
                           "flood", FLOOD_BONUS_MODIFIERS) >= BONUS_ELEVATION_3FT
