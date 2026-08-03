#!/usr/bin/env python3
"""Tests for the incorporated-municipality detection and what it gates.

The Infrastructure model allocates a full municipal service bundle to every
parcel, but a parcel in unincorporated county territory has no municipal
government at all — the county is its general-purpose government, and no city
serves or taxes it. The Census TIGER PLACE layer settles this per point, for free.

The trap these tests exist to guard is the **Census Designated Place**: a CDP is a
statistical convenience with no government, and Silver Spring, MD is a CDP of
80,000 people that has never been incorporated. "Has a place name" is therefore
exactly the wrong test, and it is the obvious one to reach for.

The parsing tests run offline against captured geocoder shapes. Execute directly
(python tests/test_incorporated_place.py) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.simulate.location import Location, _parse_geographies   # noqa: E402
from housing_label.simulate.house import build_label_parts                  # noqa: E402


# Real geocoder response shapes, captured 2026-08-03 from
# geocoding.geo.census.gov/geocoder/geographies/coordinates.
# Every successful geocode returns the county layer, incorporated or not — it is
# what makes a missing "Incorporated Places" key mean "no municipality here"
# rather than "this response is unusable".
_COUNTY = {"Counties": [{"GEOID": "47157", "NAME": "Shelby", "STATE": "47"}]}
_MEMPHIS = {**_COUNTY, "Incorporated Places": [
    {"NAME": "Memphis city", "GEOID": "4748000", "MTFCC": "G4110", "FUNCSTAT": "A"}]}
_SILVER_SPRING = {**_COUNTY, "Census Designated Places": [
    {"NAME": "Silver Spring CDP", "GEOID": "2472450", "MTFCC": "G4210", "FUNCSTAT": "S"}]}
# A real unincorporated point: the geocoder omits the places layer entirely while
# still returning counties/tracts (verified live against a rural parcel).
_RURAL = dict(_COUNTY)
# A response that resolved nothing — a failed lookup, or a future layer change.
# Indistinguishable from _RURAL on the places key alone, which is the whole point.
_UNUSABLE = {}
# Leading-zero GEOID: Alabama places start "01", so an unpadded int-ish value
# would lose the zero.
_ALABAMA = {**_COUNTY, "Incorporated Places": [
    {"NAME": "Akron town", "GEOID": "100124", "MTFCC": "G4110", "FUNCSTAT": "A"}]}
# Defensive: a layer or vintage change folding CDPs back into the incorporated
# layer must not flip an unincorporated parcel to incorporated.
_CDP_IN_WRONG_LAYER = {**_COUNTY, "Incorporated Places": [
    {"NAME": "Silver Spring CDP", "GEOID": "2472450", "MTFCC": "G4210", "FUNCSTAT": "S"}]}
# An inactive/nonfunctioning place is not an active general-purpose government.
_INACTIVE_PLACE = {**_COUNTY, "Incorporated Places": [
    {"NAME": "Defunct town", "GEOID": "4700000", "MTFCC": "G4110", "FUNCSTAT": "N"}]}


def test_incorporated_city_is_detected():
    out = _parse_geographies(_MEMPHIS)
    assert out["incorporated"] is True
    assert out["place_label"] == "Memphis city"
    assert out["place_geoid"] == "4748000"


def test_a_cdp_is_not_a_municipality():
    """The whole point. A CDP has a name and a GEOID and no government."""
    out = _parse_geographies(_SILVER_SPRING)
    assert out["incorporated"] is False
    assert out.get("place_geoid") is None


def test_unincorporated_territory_reads_as_such():
    """The geocoder omits the places layer rather than returning it empty, so its
    absence — in an otherwise well-formed response — is the unincorporated signal."""
    out = _parse_geographies(_RURAL)
    assert out["incorporated"] is False
    assert out.get("place_label") is None


def test_an_unusable_response_is_unknown_not_unincorporated():
    """A missing places layer means "no municipality here" only when the rest of the
    response vouches for it. With no county either, the layer may simply not have
    been returned — a failed lookup or an API change — and guessing False would hand
    an unknown parcel the unincorporated discount. Unknown must stay None."""
    assert _parse_geographies(_UNUSABLE)["incorporated"] is None


def test_place_geoid_keeps_its_leading_zero():
    """PLACE GEOIDs are 7 digits (2-digit state + 5-digit place); Alabama and Alaska
    lead with a zero. Padded like the county and tract GEOIDs alongside it."""
    assert _parse_geographies(_ALABAMA)["place_geoid"] == "0100124"
    assert _parse_geographies(_MEMPHIS)["place_geoid"] == "4748000"


def test_mtfcc_and_funcstat_are_both_required():
    """Neither check alone is enough: a CDP in the wrong layer has FUNCSTAT S, and a
    nonfunctioning incorporated place has MTFCC G4110."""
    assert _parse_geographies(_CDP_IN_WRONG_LAYER)["incorporated"] is False
    assert _parse_geographies(_INACTIVE_PLACE)["incorporated"] is False


# ── What incorporation gates ─────────────────────────────────────────────────
def _loc(incorporated):
    return Location(lat=35.53, lon=-84.42, state_fips="47", county_fips="47123",
                    county_name="Monroe", tract=None, place_label="Monroe",
                    in_urban_area=False, climate_zone="4A", egrid_subregion=None,
                    egrid_factor=None, climate_projection=None, wildfire=None,
                    structure_type="single_family", num_units=1,
                    incorporated=incorporated, notes=None)


def _metrics(incorporated):
    _cfg, _r, lbl = build_label_parts(location=_loc(incorporated), allow_network=False,
                                      lot_acres=10, value=237_300)
    return lbl["metrics"], lbl["location_notes"]


def test_unincorporated_is_not_charged_municipal_collection():
    """Curbside collection stops at the city limit — unincorporated residents haul
    to a convenience centre or contract privately, which is not a public cost
    allocated to that parcel."""
    inc, _ = _metrics(True)
    unin, _ = _metrics(False)
    assert unin["est_annual_infra_cost"] < inc["est_annual_infra_cost"]


def test_the_trash_fee_leaves_with_the_service():
    """Same treatment a well and a septic field get: an unincorporated household
    pays no city trash fee either, so the revenue side drops too. Crediting the fee
    while dropping the cost would invent a discount."""
    inc, _ = _metrics(True)
    unin, _ = _metrics(False)
    assert unin["est_fee_revenue"] < inc["est_fee_revenue"]
    assert unin["est_property_tax"] == inc["est_property_tax"]


def test_unknown_location_keeps_the_full_service_bundle():
    """None means no geocode resolved. That is not the same as False and must never
    be read as one — an unknown location must not be handed a rural discount."""
    unknown, _ = _metrics(None)
    inc, _ = _metrics(True)
    assert unknown["est_annual_infra_cost"] == inc["est_annual_infra_cost"]


def test_unincorporated_parcels_say_so_on_the_label():
    _m, notes = _metrics(False)
    note = notes.get("infrastructure", "")
    assert "unincorporated" in note.lower()
    _m2, notes2 = _metrics(True)
    assert "infrastructure" not in notes2


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_"):
            _fn()
            print(f"  ok  {_name}")
    print("incorporated-place tests passed")
