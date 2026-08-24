#!/usr/bin/env python3
"""The DC adapter, and what it proves about the shared layer.

Everything dangerous in an adapter — picking the right parcel from an interpolated
geocode, comparing two addresses, bounding the request budget — lives in
``_shared`` and is tested against Cook in ``test_assessor.py``. These tests cover
what is genuinely DC's: its address format, its vocabulary translation, and the
two refusals its data forces that Cook's did not.

No network. The transport is stubbed with recorded response shapes, for the reason
the Cook file gives: the adapter fails open, so a renamed column or a broken join
reads as "this county has no record here" and would never announce itself.

Run standalone: ``python tests/test_assessor_dc.py``
"""

from __future__ import annotations

import os
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich.assessor import _shared, dc  # noqa: E402
from housing_label.enrich.assessor._shared import address_key, same_address  # noqa: E402

_PARCEL = {"SSL": "2076    0099",
           "PREMISEADD": "3401 NEWARK ST NW WASHINGTON DC 20016"}
_CAMA = {"SSL": "2076    0099", "AYB": 1895.0, "GBA": 1840.0, "STORIES": 2.0,
         "EXTWALL_D": "Common Brick", "CNDTN_D": "Good", "NUM_UNITS": 1.0}


def _lookup(parcels, cama, lat=38.9347, lon=-77.0665, address=None):
    """Drive dc.lookup() over recorded response shapes."""
    def fake(url, params, deadline):
        if url == dc.PARCEL_URL:
            return {"features": [{"attributes": a} for a in parcels]}
        return {"features": [{"attributes": a} for a in cama]}

    dc._lookup_cached.cache_clear()
    saved = (dc.get_json, _shared.get_json)
    dc.get_json, _shared.get_json = fake, fake
    try:
        return dc.lookup(lat, lon, address)
    finally:
        dc.get_json, _shared.get_json = saved
        dc._lookup_cached.cache_clear()


# --- the address format DC forced ----------------------------------------------


def test_a_run_together_mailing_address_still_reduces_to_its_street():
    """DC's parcel layer has no comma to split on — "3401 NEWARK ST NW WASHINGTON
    DC 20016" is one field. Without a locality trim the city and ZIP become street
    tokens and nothing ever matches, so the adapter resolves nothing and looks like
    a county with no data rather than a broken comparison."""
    assert same_address("3401 NEWARK ST NW, WASHINGTON, DC, 20016",
                        "3401 NEWARK ST NW WASHINGTON DC 20016", dc._LOCALITY)


def test_the_quadrant_is_part_of_the_street_not_decoration():
    """NEWARK ST NW and NEWARK ST NE are different streets on opposite sides of the
    city. Dropping the quadrant as a directional would match them to each other."""
    assert not same_address("3401 NEWARK ST NW WASHINGTON DC 20016",
                            "3401 NEWARK ST NE WASHINGTON DC 20002", dc._LOCALITY)
    assert not same_address("3401 NEWARK ST NW, WASHINGTON, DC",
                            "3401 NEWARK ST, WASHINGTON, DC", dc._LOCALITY)


def test_a_postal_code_ends_the_street_even_with_no_locality_word():
    """ZIP+4 appears on some rows ("...WASHINGTON DC 20008-3329"). The trim keys on
    the postal code too, so a source that omits the city still parses."""
    assert address_key("1349 MARYLAND AVE NE 20002-4406", dc._LOCALITY) == \
        ("1349", ("maryland", "ave", "ne"), None)


def test_a_neighbouring_house_number_is_still_refused():
    """The DC failure mode measured live: at 1350 Maryland Ave NE the parcels within
    the search radius are 1341 and 1349 — near misses on the same street. This is
    the case a nearest-parcel match would get confidently wrong."""
    assert not same_address("1350 MARYLAND AVE NE WASHINGTON DC 20002",
                            "1349 MARYLAND AVE NE WASHINGTON DC 20002", dc._LOCALITY)


# --- the translation ------------------------------------------------------------


def test_a_full_row_maps_end_to_end():
    rec = _lookup([_PARCEL], [_CAMA], address="3401 Newark St NW, Washington, DC")
    assert rec is not None and rec.parcel_id == "2076    0099"
    assert rec.fields() == {"year_built": 1895, "sqft": 1840.0, "stories": 2,
                            "construction": "brick", "condition": "good"}


def test_a_veneer_is_a_framed_wall_not_solid_masonry():
    """The reason this adapter's table is worth having. DC distinguishes veneer from
    structural brick; the label has `brick-frame` for exactly that. Reading a veneer
    as `brick` would tell the durability and resilience models the opposite of the
    truth about the structure."""
    rec = _lookup([_PARCEL], [dict(_CAMA, EXTWALL_D="Brick Veneer")],
                  address="3401 Newark St NW, Washington, DC")
    assert rec.fields()["construction"] == "brick-frame"


def test_an_ambiguous_cladding_is_left_unmapped():
    """Stucco goes over frame and over masonry alike, so it says nothing about the
    structure — the same call the Cook adapter makes. Measured live: this is why
    3401 Newark St NW resolves with no construction value."""
    rec = _lookup([_PARCEL], [dict(_CAMA, EXTWALL_D="Stucco")],
                  address="3401 Newark St NW, Washington, DC")
    assert rec is not None
    assert "construction" not in rec.fields()


def test_a_half_storey_is_not_rounded_into_a_whole_one():
    """2.5 storeys is common in DC's stock and the label's field is a whole number.
    Rounding would invent a precision the county did not record."""
    rec = _lookup([_PARCEL], [dict(_CAMA, STORIES=2.5)],
                  address="3401 Newark St NW, Washington, DC")
    assert "stories" not in rec.fields()
    assert rec.fields()["year_built"] == 1895, "the rest of the row still applies"


def test_very_good_reads_down_rather_than_up():
    """DC's scale has a step the label's does not. Where two scales disagree the
    reading that claims less is the one to take."""
    rec = _lookup([_PARCEL], [dict(_CAMA, CNDTN_D="Very Good")],
                  address="3401 Newark St NW, Washington, DC")
    assert rec.fields()["condition"] == "good"


def test_the_effective_year_is_not_mistaken_for_the_year_built():
    """AYB is when the building went up; EYB is a depreciation figure that moves
    when a property is improved. Reading EYB would report a 1900 rowhouse as built
    in 1985 and tag it observed."""
    rec = _lookup([_PARCEL], [dict(_CAMA, EYB=1985.0)],
                  address="3401 Newark St NW, Washington, DC")
    assert rec.fields()["year_built"] == 1895


def test_a_whole_building_area_is_not_published_as_one_unit_s():
    rec = _lookup([_PARCEL], [dict(_CAMA, NUM_UNITS=6.0, GBA=12000.0)],
                  address="3401 Newark St NW, Washington, DC")
    assert "sqft" not in rec.fields()
    assert rec.fields()["year_built"] == 1895


def test_a_parcel_with_no_residential_row_yields_nothing():
    """DC keeps condominium units in a separate CAMA table, so a condo finds its
    parcel and then no row. Failing open is correct; the point of the test is that
    it fails open rather than raising."""
    assert _lookup([_PARCEL], [], address="3401 Newark St NW, Washington, DC") is None


def test_a_containing_parcel_whose_address_disagrees_is_not_accepted():
    assert _lookup([_PARCEL], [_CAMA], address="3405 Newark St NW, Washington, DC") is None


# --- registry -------------------------------------------------------------------


def test_the_registry_routes_dc_to_this_adapter():
    from housing_label.enrich.assessor import adapter_for_county
    assert adapter_for_county("11001") is dc
    assert adapter_for_county("17031") is not dc


def test_the_gate_covers_this_adapter_too():
    """Off by default is a property of the registry, not of one adapter."""
    from housing_label.enrich.assessor import assessor_for_point
    prev = os.environ.pop("ASSESSOR_ADAPTERS", None)
    try:
        assert assessor_for_point(38.9347, -77.0665, "11001") is None
    finally:
        if prev is not None:
            os.environ["ASSESSOR_ADAPTERS"] = prev


def test_the_parcel_query_never_asks_for_owner_data():
    """DC's parcel layer carries OWNERNAME, owner mailing address and tax balances
    beside the geometry. Cook's source split those out; this one does not, so the
    field list is the safeguard and it is pinned."""
    fields = dc._PARCEL_FIELDS.split(",")
    assert fields == ["SSL", "PREMISEADD"]
    banned = ("OWNER", "ADDRESS1", "ADDRESS2", "CAREOF", "SALE", "TAX", "*")
    combined = (dc._PARCEL_FIELDS + "," + dc._CAMA_FIELDS).upper()
    for token in banned:
        assert token not in combined, f"{token} must not be requested"


def test_a_street_named_after_the_city_still_matches():
    """The locality tail was stripped at the FIRST locality token anywhere in the
    string, so "401 WASHINGTON AVE SW WASHINGTON DC 20024" truncated at token zero
    and address_key returned None. No DC address on a Washington-named street could
    confirm a parcel — the adapter returned nothing for them, and the measured
    coverage absorbed it silently as though those homes simply had no record.

    These are real addresses from DC's own parcel layer. The same shape waits in
    any jurisdiction whose name is also a street name, which is most of them, so
    this is pinned before a third adapter inherits it.
    """
    from housing_label.enrich.assessor._shared import same_address
    from housing_label.enrich.assessor.dc import _LOCALITY
    for premise, typed in (
        ("401 WASHINGTON AVE SW WASHINGTON DC 20024-2134",
         "401 Washington Ave SW, Washington, DC 20024"),
        ("2211 WASHINGTON CIR NW WASHINGTON DC 20037",
         "2211 Washington Cir NW, Washington, DC 20037"),
        ("3401 NEWARK ST NW WASHINGTON DC 20016",
         "3401 Newark St NW, Washington, DC 20016"),
    ):
        assert same_address(typed, premise, _LOCALITY), premise


def test_the_city_named_street_fix_did_not_loosen_the_match():
    """The whole point of this comparison is refusing a confident wrong answer, so
    the repair must not buy coverage with a wrong-house match."""
    from housing_label.enrich.assessor._shared import same_address
    from housing_label.enrich.assessor.dc import _LOCALITY
    assert not same_address("2211 Washington Cir NW, Washington, DC",
                            "2213 WASHINGTON CIR NW WASHINGTON DC 20037", _LOCALITY)
    assert not same_address("401 Washington Ave SW, Washington, DC",
                            "401 WASHINGTON ST SW WASHINGTON DC 20024", _LOCALITY)


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
