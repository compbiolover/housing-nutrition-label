#!/usr/bin/env python3
"""Tests for the steel wall / construction type.

Steel-framed and steel-walled homes had no entry in the construction vocabulary,
so the closest a caller could get was "frame" — and NSI's own Hazus steel class
("S") was mapped there too. That scored a steel home as wood on four separate
models. These tests pin the option's presence end to end and, more importantly,
that it is not merely an alias for frame: it must move each dimension in the
direction the material actually differs.

Runs without network (a pre-resolved Location is injected). This file alone: ``pytest tests/test_steel_construction.py``.
"""

from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.simulate.location import Location
from housing_label.simulate.house import (
    build_label_parts, BRM_FLOOR, CONSTRUCTION_FACTOR,
    FLOOD_CONSTRUCTION_FACTOR, FIRE_CONSTRUCTION_FACTOR)
from housing_label.simulate.dimensions import (
    EXTWALL_CODE, GRADE_BY_CONSTRUCTION)
from housing_label.enrich.structure import _CONSTRUCTION
from housing_label.enrich.durability import WALL_FACTOR
from housing_label.enrich.energy import _wall_factor
from housing_label.enrich.environmental import SERVICE_LIFE_BY_WALL
from housing_label.data.embodied_carbon import _ENV_KG_PER_M2WALL

STEEL_CODE = 6


def _loc():
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=None, place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1, notes=None)


def _dims(construction):
    _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                      construction=construction, year_built=2025,
                                      sqft=1515, lot_acres=10, value=237_300)
    return {d["key"]: d["score"] for d in lbl["dimensions"]}


def test_steel_is_in_every_resilience_table():
    """A construction type missing from any one table silently falls back to that
    table's default, which is how a gap becomes a wrong score instead of an error."""
    for table, name in ((BRM_FLOOR, "BRM_FLOOR"),
                        (CONSTRUCTION_FACTOR, "CONSTRUCTION_FACTOR"),
                        (FLOOD_CONSTRUCTION_FACTOR, "FLOOD_CONSTRUCTION_FACTOR"),
                        (FIRE_CONSTRUCTION_FACTOR, "FIRE_CONSTRUCTION_FACTOR"),
                        (GRADE_BY_CONSTRUCTION, "GRADE_BY_CONSTRUCTION"),
                        (EXTWALL_CODE, "EXTWALL_CODE")):
        assert "steel" in table, f"steel missing from {name}"


def test_steel_has_its_own_extwall_code():
    """Steel must not ride frame's code (7): the downstream models key off EXTWALL,
    so sharing a code makes every one of them score steel as wood."""
    assert EXTWALL_CODE["steel"] == STEEL_CODE
    assert EXTWALL_CODE["steel"] != EXTWALL_CODE["frame"]


def test_every_extwall_consumer_knows_the_steel_code():
    """Each model that reads EXTWALL has a real entry for 6 — not a silent default."""
    assert STEEL_CODE in WALL_FACTOR
    assert STEEL_CODE in SERVICE_LIFE_BY_WALL
    assert STEEL_CODE in _ENV_KG_PER_M2WALL
    label, factor = _wall_factor(STEEL_CODE)
    assert label != "other", "energy model fell through to its unknown-wall default"
    assert factor != _wall_factor(EXTWALL_CODE["frame"])[1]


def test_steel_is_penalised_on_energy_for_thermal_bridging():
    """Steel studs conduct ~400x wood and short-circuit the cavity insulation, so a
    steel-framed envelope must cost MORE to condition than the same wood-framed one.
    The old frame alias gave it a free pass — this is the regression that matters."""
    assert _wall_factor(STEEL_CODE)[1] > _wall_factor(EXTWALL_CODE["frame"])[1]
    assert _dims("steel")["energy"] < _dims("frame")["energy"]


def test_steel_beats_frame_on_resilience_and_durability():
    """Non-combustible, screwed/bolted, and immune to rot and termites."""
    assert CONSTRUCTION_FACTOR["steel"] < CONSTRUCTION_FACTOR["frame"]
    assert FIRE_CONSTRUCTION_FACTOR["steel"] < FIRE_CONSTRUCTION_FACTOR["frame"]
    assert BRM_FLOOR["steel"] < BRM_FLOOR["frame"]
    assert WALL_FACTOR[STEEL_CODE][1] > WALL_FACTOR[EXTWALL_CODE["frame"]][1]
    assert SERVICE_LIFE_BY_WALL[STEEL_CODE] > SERVICE_LIFE_BY_WALL[EXTWALL_CODE["frame"]]

    steel, frame = _dims("steel"), _dims("frame")
    assert steel["resilience"] > frame["resilience"]
    assert steel["durability"] > frame["durability"]


def test_steel_carries_more_embodied_carbon_per_wall_area():
    """Light-gauge framing is light, but steel's per-kg intensity is high and metal
    cladding beats vinyl — so the wall term is above frame, below brick veneer."""
    frame_code = EXTWALL_CODE["frame"]
    veneer_code = EXTWALL_CODE["brick-frame"]
    assert _ENV_KG_PER_M2WALL[frame_code] < _ENV_KG_PER_M2WALL[STEEL_CODE]
    assert _ENV_KG_PER_M2WALL[STEEL_CODE] < _ENV_KG_PER_M2WALL[veneer_code]


def test_nsi_steel_class_maps_to_steel():
    """Hazus 'S' is NSI's steel class. It used to fall back to 'frame', so an
    auto-filled steel home was scored as wood without the visitor touching a thing."""
    assert _CONSTRUCTION["S"] == "steel"


def test_steel_scores_end_to_end():
    """The option survives the whole pipeline, not just the lookup tables."""
    d = _dims("steel")
    for key in ("resilience", "energy", "durability", "environmental"):
        assert d[key] is not None, key


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("steel-construction tests passed")
