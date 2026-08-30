#!/usr/bin/env python3
"""Tests for the water-source / sewer inputs at the label level.

A home on a private well and a septic field is not on the public network. Two
dimensions were reading it as if it were:

  • Water Quality scored it from EPA SDWIS, which measures the share of a county's
    COMMUNITY-WATER-SYSTEM-served population under a health-based violation. A
    well household is not in that population at all, so the county figure is a
    measurement of somebody else's water — and it was shown at full confidence.
  • Infrastructure Burden charged it the modeled public water/sewer cost, and
    credited it the utility fees that go with it.

The per-component cost/fee arithmetic is covered in tests/test_infrastructure.py;
these tests pin the behaviour a visitor actually sees on the label.

Runs without network (a pre-resolved Location is injected). This file alone: ``pytest tests/test_utility_connections.py``.
"""

from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.simulate.location import Location
from housing_label.simulate.house import (
    build_label_parts, WATER_SOURCES, SEWER_TYPES)


def _loc():
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=None, place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1, notes=None)


def _label(**kw):
    _cfg, _r, lbl = build_label_parts(location=_loc(), allow_network=False,
                                      year_built=2025, sqft=1515, lot_acres=10,
                                      value=237_300, **kw)
    return lbl


def _dim(lbl, key):
    return next(d for d in lbl["dimensions"] if d["key"] == key)


def test_year_built_is_labelled_as_a_tract_median_not_a_measurement():
    """NSI's med_yr_blt is, in its own documentation, "the median year built of
    structures within the Census tract" — a property of the tract, never of this
    building. It is kept as the best available prior, but it must render as a
    stand-in ("assumed"), not as something derived about this home ("estimated")."""
    loc = _loc()
    loc.year_built = 1976        # as NSI supplies it
    _cfg, _r, lbl = build_label_parts(location=loc, allow_network=False, sqft=1515,
                                      lot_acres=10, value=237_300)
    yb = lbl["building"]["year_built"]
    assert yb["value"] == 1976
    assert yb["status"] == "assumed", yb
    assert "census-tract median" in yb["source"].lower()
    assert "not this building" in yb["source"].lower()


def test_an_entered_year_built_is_still_confirmed():
    loc = _loc()
    loc.year_built = 1976
    _cfg, _r, lbl = build_label_parts(location=loc, allow_network=False,
                                      year_built=2025, value=237_300)
    yb = lbl["building"]["year_built"]
    assert yb["value"] == 2025 and yb["status"] == "confirmed"


def test_vocabularies():
    assert WATER_SOURCES == ("public", "well")
    assert SEWER_TYPES == ("public", "septic")


def test_public_is_the_default():
    """An unstated water source must score exactly like a stated public one, so a
    visitor who never opens the panel is not quietly given a rural discount."""
    default, stated = _label(), _label(water_source="public", sewer="public")
    assert default["composite_score"] == stated["composite_score"]
    assert default["n_scored"] == stated["n_scored"]
    assert _dim(default, "water")["score"] is not None


def test_private_well_leaves_water_quality_unscored():
    """SDWIS covers community water systems only. Reporting the county figure for a
    well household would not approximate their water — it would measure a
    population they are not part of."""
    lbl = _label(water_source="well")
    assert _dim(lbl, "water")["score"] is None
    assert lbl["n_scored"] == _label()["n_scored"] - 1
    note = lbl["location_notes"]["water"]
    assert "private well" in note.lower()
    assert "community water system" in note.lower()


def test_private_well_skips_the_sdwis_lookup_entirely():
    """Not just discarded — never fetched. Nothing downstream reads the county row
    unless a score was set, so looking it up would only pay to parse the SDWIS table
    for an answer this home cannot use."""
    from unittest import mock
    import housing_label.data.water as water_data

    with mock.patch.object(water_data, "water_for_county",
                           wraps=water_data.water_for_county) as spy:
        _label(water_source="well")
    assert spy.call_count == 0
    with mock.patch.object(water_data, "water_for_county",
                           wraps=water_data.water_for_county) as spy:
        _label()
    assert spy.call_count == 1


def test_septic_alone_does_not_touch_water_quality():
    """The wastewater connection says nothing about where the drinking water comes
    from — a home on public water with a septic field still has scoreable tap water."""
    lbl = _label(sewer="septic")
    assert _dim(lbl, "water")["score"] is not None


def test_off_network_legs_reduce_the_modeled_public_cost():
    """The label's reported cost-to-serve must stop including infrastructure that
    was never built to the parcel."""
    on = _label()["metrics"]["est_annual_infra_cost"]
    well = _label(water_source="well")["metrics"]["est_annual_infra_cost"]
    both = _label(water_source="well", sewer="septic")["metrics"]["est_annual_infra_cost"]
    assert both < well < on


def test_the_fee_credit_leaves_with_the_service():
    """Water/sewer is ~100% fee-recovered, so dropping the cost without dropping the
    fees would credit a rural home with a utility bill it never pays. Both sides go."""
    on = _label()["metrics"]
    off = _label(water_source="well", sewer="septic")["metrics"]
    assert off["est_fee_revenue"] < on["est_fee_revenue"]
    assert off["est_property_tax"] == on["est_property_tax"]


def test_connections_are_reported_in_the_building_panel():
    """The refine panel clears any field the payload omits, so an unreported choice
    would visibly reset itself on the next re-score."""
    b = _label(water_source="well", sewer="septic")["building"]
    assert b["water_source"]["value"] == "well"
    assert b["water_source"]["status"] == "confirmed"
    assert b["sewer"]["value"] == "septic"
    # Untouched: present, and honest about being an assumption rather than detected.
    assert _label()["building"]["water_source"]["status"] == "assumed"


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("utility-connection tests passed")
