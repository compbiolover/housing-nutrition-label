#!/usr/bin/env python3
"""Tests for the parcel → public-water-system join, and what it now decides.

Water Quality scores EPA SDWIS compliance, which is a property of a **community
water system**. The project joined it to a parcel by COUNTY, which broadcasts a
county aggregate onto every home in it — including homes on a private well that
are on no system at all. Until now the only way to say so was for the owner to
tell us. EPA's service-area boundaries supply the missing join.

The behaviour these tests pin is mostly about what happens when the answer is
*not* clean: an unreachable service must not read as "this house is on a well",
and a stated source must always beat a detected one.

Runs without network (the lookup is stubbed). Execute directly
(python tests/test_water_system.py) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import water_system as ws_mod                  # noqa: E402
from housing_label.simulate.location import Location                      # noqa: E402
from housing_label.simulate.dimensions import resolve_water_source        # noqa: E402
from housing_label.simulate.house import build_label_parts                # noqa: E402

_SERVED = {"status": "served", "pwsid": "TN0000450",
           "name": "MEMPHIS LIGHT, GAS, & WATER", "population_served": 659500,
           "provenance": "State Agency", "source": "EPA"}
_OUTSIDE = {"status": "outside", "pwsid": None, "name": None,
            "population_served": None, "provenance": None, "source": "EPA"}


def _loc(water_system):
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=None, place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1,
                    water_system=water_system, notes=None)


def _label(water_system, **kw):
    _cfg, _r, lbl = build_label_parts(location=_loc(water_system), allow_network=False,
                                      value=237_300, **kw)
    return lbl


def _water(lbl):
    return next(d["score"] for d in lbl["dimensions"] if d["key"] == "water")


# ── The lookup itself ────────────────────────────────────────────────────────
def test_non_community_systems_are_filtered_out():
    """SDWIS community-system compliance does not describe a campground's or a
    school's own well, and living inside its footprint is not being served by it."""
    assert ws_mod._is_community({"Service_Area_Type": "Residential Area"}) is True
    assert ws_mod._is_community({"Service_Area_Type": ""}) is True
    for kind in ("Non-Community", "Transient Non-Community", "non-transient"):
        assert ws_mod._is_community({"Service_Area_Type": kind}) is False, kind


def test_overlapping_areas_pick_the_larger_system():
    """A wholesaler's area can sit over a retailer's; the system serving the most
    people is the likelier provider at a dwelling."""
    feats = [{"PWSID": "SMALL", "Population_Served_Count": 200,
              "Service_Area_Type": "Residential Area"},
             {"PWSID": "BIG", "Population_Served_Count": 90_000,
              "Service_Area_Type": "Residential Area"}]
    with mock.patch.object(ws_mod, "_query", return_value=feats):
        ws_mod._system_at.cache_clear()
        out = ws_mod.water_system_for_point(35.0, -89.0)
    assert out["pwsid"] == "BIG"


def test_no_mapped_system_is_outside_not_none():
    with mock.patch.object(ws_mod, "_query", return_value=[]):
        ws_mod._system_at.cache_clear()
        out = ws_mod.water_system_for_point(35.1, -89.1)
    assert out["status"] == "outside" and out["pwsid"] is None


def test_off_network_returns_none():
    ws_mod._system_at.cache_clear()
    assert ws_mod.water_system_for_point(35.2, -89.2, allow_network=False) is None


def test_outage_raises_rather_than_reporting_outside():
    """An outage that read as "outside" would unscore Water Quality for every
    address while it lasted — and cache that. It has to be a distinct signal."""
    with mock.patch.object(ws_mod, "_query",
                           side_effect=ws_mod.ServiceAreaUnavailable("boom")):
        ws_mod._system_at.cache_clear()
        try:
            ws_mod.water_system_for_point(35.3, -89.3)
        except ws_mod.ServiceAreaUnavailable:
            return
    raise AssertionError("expected ServiceAreaUnavailable")


# ── What it decides ──────────────────────────────────────────────────────────
def test_stated_source_always_beats_detection():
    """The owner knows, and EPA is explicit that the layer cannot confirm service
    by address. Both directions."""
    cfg_well = {"water_source": "well"}
    cfg_public = {"water_source": "public"}
    assert resolve_water_source(cfg_well, _loc(_SERVED)) == "well"
    assert resolve_water_source(cfg_public, _loc(_OUTSIDE)) == "public"


def test_detection_fills_an_unstated_source():
    assert resolve_water_source({}, _loc(_OUTSIDE)) == "well"
    assert resolve_water_source({}, _loc(_SERVED)) == "public"


def test_unknown_detection_resolves_to_public():
    """No water_system means the lookup was skipped or the service was unreachable.
    That is NOT "outside", and must not unscore Water Quality — it resolves to the
    pre-detection behaviour."""
    assert resolve_water_source({}, _loc(None)) == "public"
    assert resolve_water_source({}, None) == "public"


def test_a_detected_well_leaves_water_quality_unscored():
    outside, served = _label(_OUTSIDE), _label(_SERVED)
    assert _water(outside) is None
    assert _water(served) is not None
    assert outside["n_scored"] == served["n_scored"] - 1


def test_the_note_says_detection_is_evidence_not_proof():
    """~40% of the layer is EPA-modeled and a small system may be unmapped, so the
    label must not overclaim a detection the owner never confirmed."""
    note = _label(_OUTSIDE)["location_notes"]["water"].lower()
    assert "evidence" in note and "not proof" in note
    stated = _label(_OUTSIDE, water_source="well")["location_notes"]["water"].lower()
    assert "as entered" in stated       # stated reads differently from detected


def test_a_served_parcel_names_its_system_and_admits_the_gap():
    """Naming the system makes visible that the SCORE is still a county aggregate
    rather than that system's own violation record."""
    note = _label(_SERVED)["location_notes"]["water"]
    assert "TN0000450" in note
    assert "county aggregate" in note


def test_detection_is_reported_in_the_building_panel():
    """The one field the visitor most needs to confirm must not be the one field
    with nothing in it."""
    b = _label(_OUTSIDE)["building"]["water_source"]
    assert b["value"] == "well" and b["status"] == "estimated"
    assert "EPA service areas" in b["source"]
    # No detection at all: the model still proceeds as public, so the panel says so.
    b2 = _label(None)["building"]["water_source"]
    assert b2["value"] == "public" and b2["status"] == "assumed"


def test_a_detected_well_also_drops_the_public_water_cost():
    """The same fact has to reach the infrastructure model, not just the water
    dimension — a well household is not served by public mains either."""
    assert (_label(_OUTSIDE)["metrics"]["est_annual_infra_cost"]
            < _label(_SERVED)["metrics"]["est_annual_infra_cost"])


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("water-system tests passed")
