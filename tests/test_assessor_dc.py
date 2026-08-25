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


def _lookup(parcels, cama, lat=38.9347, lon=-77.0665, address=None,
            units=(), condo=(), trace=False):
    """Drive dc.lookup() over recorded response shapes.

    Every one of the four endpoints is answered explicitly. A test that exercises
    the parcel path and leaves the unit tables empty is then really asserting that
    the condominium fallback found nothing, rather than being handed the
    residential rows under a different URL.
    """
    asked = []

    def fake(url, params, deadline):
        asked.append(url)
        rows = {dc.PARCEL_URL: parcels, dc.CAMA_URL: cama,
                dc.UNITS_URL: units, dc.CONDO_CAMA_URL: condo}[url]
        return {"features": [{"attributes": a} for a in rows]}

    dc._lookup_cached.cache_clear()
    saved = (dc.get_json, _shared.get_json)
    dc.get_json, _shared.get_json = fake, fake
    try:
        record = dc.lookup(lat, lon, address)
        return (record, asked) if trace else record
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
        ("1349", ("maryland", "ne"), "ave")


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


# --- condominiums ---------------------------------------------------------------
#
# _UNIT_ROW and _CONDO_CAMA are what DC actually returns for 2123 California St NW
# unit D7, read from the live service. Its sibling D8 is SSL 2528    2030, AYB 1911,
# LIVING_GBA 1262 — same building, different area, which is the point of the second
# test. Rows built inline below (the 15th St one) are constructed to pose a case, not
# read from the portal, and are marked where they appear. The distinction matters:
# the first review of this file caught D8 carrying 1256, a neighbouring unit's area
# recorded under D8's name.

_UNIT_ROW = {"PRIMARY_ADDRESS": "2123 CALIFORNIA STREET NW",
             "UNIT_NUMBER": "D7", "CONDO_SSL": "2528    2029"}
_CONDO_CAMA = {"SSL": "2528    2029", "AYB": 1911.0, "LIVING_GBA": 680.0}


def test_a_unit_number_is_what_makes_a_condo_reachable():
    """No point-in-polygon can pick unit D7 out of a stack: the unit's SSL is not in
    the parcel layer at all. The address the reader typed carries the only thing
    that identifies their home, so the lookup is driven from it."""
    rec = _lookup([], [], address="2123 California St NW #D7",
                  units=[_UNIT_ROW], condo=[_CONDO_CAMA])
    assert rec is not None
    assert rec.parcel_id == "2528    2029"
    assert rec.year_built == 1911
    assert rec.sqft == 680.0


def test_the_condo_table_reports_the_units_own_floor_area():
    """LIVING_GBA is per unit, unlike the residential table's whole-building GBA —
    which is why the parcel path has to drop sqft on a multi-unit parcel and this
    one does not. Sibling units in one building carry different areas."""
    sibling = dict(_UNIT_ROW, UNIT_NUMBER="D8", CONDO_SSL="2528    2030")
    rec = _lookup([], [], address="2123 California St NW #D8",
                  units=[_UNIT_ROW, sibling],
                  condo=[{"SSL": "2528    2030", "AYB": 1911.0,
                          "LIVING_GBA": 1262.0}])
    assert rec is not None and rec.sqft == 1262.0


def test_a_condo_reports_only_what_its_table_records():
    """The condominium table has no exterior wall, no storey count and no condition
    column. Those stay absent rather than being borrowed from the building the unit
    happens to sit in, which is a different structure's record."""
    rec = _lookup([], [], address="2123 California St NW #D7",
                  units=[_UNIT_ROW], condo=[_CONDO_CAMA])
    assert rec is not None
    assert rec.stories is None
    assert rec.construction is None
    assert rec.condition is None
    assert rec.data_vintage == dc.CONDO_VINTAGE
    assert rec.data_vintage != dc.DATA_VINTAGE


def test_an_address_with_no_unit_is_not_even_asked_about():
    """Every unit in the building shares the street address. Answering with one of
    them would be the same confident guess as taking the nearest parcel, so the
    absence is reported — and the unit table is not consulted at all, which is what
    tells this refusal apart from a lookup that ran and found nothing."""
    record, asked = _lookup([], [], address="2123 California St NW",
                            units=[_UNIT_ROW], condo=[_CONDO_CAMA], trace=True)
    assert record is None
    assert dc.UNITS_URL not in asked
    # ...and the one difference that makes it answerable is the unit.
    with_unit, asked = _lookup([], [], address="2123 California St NW #D7",
                               units=[_UNIT_ROW], condo=[_CONDO_CAMA], trace=True)
    assert with_unit is not None and dc.UNITS_URL in asked


def test_two_units_claiming_the_same_designator_are_an_ambiguity():
    """Two different SSLs answering to unit D7 means the question has no single
    answer. Taking the first row would be picking one home out of two."""
    twin = dict(_UNIT_ROW, CONDO_SSL="2528    9999")
    assert _lookup([], [], address="2123 California St NW #D7",
                   units=[_UNIT_ROW], condo=[_CONDO_CAMA]) is not None
    assert _lookup([], [], address="2123 California St NW #D7",
                   units=[_UNIT_ROW, twin], condo=[_CONDO_CAMA]) is None


def test_the_same_unit_recorded_twice_is_not_an_ambiguity():
    """A duplicated row is one home listed twice, not two homes. The refusal is
    keyed on distinct SSLs so a repeated row does not read as a conflict."""
    rec = _lookup([], [], address="2123 California St NW #D7",
                  units=[_UNIT_ROW, dict(_UNIT_ROW)], condo=[_CONDO_CAMA])
    assert rec is not None and rec.parcel_id == "2528    2029"


def test_a_matching_unit_on_a_different_street_is_refused():
    """The unit query is narrowed by house number, so 2123 15th St NW comes back
    alongside 2123 California St NW. Unit D7 exists in both; only one is the
    address that was asked about."""
    # Constructed, not read from the portal — see the note above the fixtures.
    other = {"PRIMARY_ADDRESS": "2123 15TH STREET NW", "UNIT_NUMBER": "D7",
             "CONDO_SSL": "2666    2001"}
    assert _lookup([], [], address="2123 15th St NW #D7", units=[other],
                   condo=[{"SSL": "2666    2001", "AYB": 1925.0,
                           "LIVING_GBA": 900.0}]) is not None
    assert _lookup([], [], address="2123 California St NW #D7",
                   units=[other], condo=[_CONDO_CAMA]) is None


def test_the_parcel_path_is_asked_first_and_never_second_guessed():
    """The two paths answer for disjoint halves of the stock. Where point-in-polygon
    found a house, that is the answer — the condominium lookup must not be able to
    overwrite a record an existing caller already gets."""
    rec = _lookup([_PARCEL], [_CAMA],
                  address="3401 Newark St NW #D7",
                  units=[dict(_UNIT_ROW, PRIMARY_ADDRESS="3401 NEWARK ST NW")],
                  condo=[_CONDO_CAMA])
    assert rec is not None
    assert rec.parcel_id == "2076    0099"
    assert rec.data_vintage == dc.DATA_VINTAGE


def test_a_condo_with_no_cama_row_is_a_miss_not_a_bare_ssl():
    """A unit SSL that the characteristics table does not carry has nothing to say
    about the building. Returning the identifier alone would put an assessor-sourced
    record on the label with no observation in it."""
    assert _lookup([], [], address="2123 California St NW #D7",
                   units=[_UNIT_ROW], condo=[_CONDO_CAMA]) is not None
    assert _lookup([], [], address="2123 California St NW #D7",
                   units=[_UNIT_ROW], condo=[]) is None


def test_the_unit_is_read_from_every_form_a_reader_writes_it():
    """"#305", "Apt 305", "Unit 305" and the bare trailing token DC's own table
    uses ("2123 CALIFORNIA STREET NW D7")."""
    base = "2123 California St NW"
    for text, unit in ((f"{base} #305", "305"), (f"{base}, #305", "305"),
                       (f"{base} Apt 305", "305"), (f"{base} APT. 305", "305"),
                       (f"{base} Unit 305", "305"), (f"{base} Suite 305", "305"),
                       (f"{base} D7", "D7"), (f"{base} 305", "305")):
        assert dc._split_unit(text) == (base, unit), text


def test_a_plain_street_address_yields_no_unit():
    """The quadrant is the last token of a great many DC addresses and is not a unit
    designator. Reading it as one would send every non-condo lookup down the
    condominium path with a fabricated unit."""
    for text in ("2123 California St NW", "3401 Newark St NW Washington DC 20016",
                 "1349 Maryland Ave NE"):
        assert dc._split_unit(text)[1] is None, text


def test_unit_designators_compare_past_punctuation_but_not_past_zeros():
    """"#3-B" and "3B" are the same home written two ways. "01" and "1" are not:
    both can exist in one building, so the leading zero stays significant."""
    assert dc._same_unit("#3-B", "3B")
    assert dc._same_unit("d7", "D7")
    assert not dc._same_unit("01", "1")
    assert not dc._same_unit("", "")
    assert not dc._same_unit(None, "3B")


def test_a_street_type_before_a_quadrant_is_still_a_street_type():
    """"2123 CALIFORNIA STREET NW" and "2123 California St NW" are one address. The
    suffix table only reached a terminal token, so in every quadrant-addressed city
    the abbreviation went unrecognised and the two spellings never matched."""
    assert address_key("2123 CALIFORNIA STREET NW", dc._LOCALITY) == \
        address_key("2123 California St NW", dc._LOCALITY)
    assert same_address("2123 California St NW, Washington, DC",
                        "2123 CALIFORNIA STREET NW", dc._LOCALITY)


def test_normalising_the_street_type_did_not_swallow_the_quadrant():
    """Stepping over the quadrant to find the street type must not drop it: NW and
    SE are opposite corners of the city at the same house number."""
    assert not same_address("2123 California St NW", "2123 California St SE",
                            dc._LOCALITY)
    assert address_key("2123 California St NW", dc._LOCALITY)[1][-1] == "nw"


def test_the_condo_fallback_spends_the_same_budget_not_a_second_one():
    """Four hops now sit behind one lookup. They share the parcel path's deadline, so
    a condo address cannot cost twice the adapter's timeout on a host that allows
    twelve seconds for the whole label."""
    seen = []

    def fake(url, params, deadline):
        seen.append(deadline)
        rows = {dc.PARCEL_URL: [], dc.CAMA_URL: [], dc.UNITS_URL: [_UNIT_ROW],
                dc.CONDO_CAMA_URL: [_CONDO_CAMA]}[url]
        return {"features": [{"attributes": a} for a in rows]}

    dc._lookup_cached.cache_clear()
    saved = (dc.get_json, _shared.get_json)
    dc.get_json, _shared.get_json = fake, fake
    try:
        dc.lookup(38.9166, -77.0492, "2123 California St NW #D7")
    finally:
        dc.get_json, _shared.get_json = saved
        dc._lookup_cached.cache_clear()
    assert len(seen) > 1
    assert len(set(seen)) == 1, seen

# --- the unit has to survive the geocoder ---------------------------------------
#
# This is the seam the first version of the condominium path fell through. The
# adapter worked when called directly and the feature was unreachable from the
# product, because the address the product hands it is not the address the reader
# typed.


def test_the_geocoders_canonical_address_does_not_carry_a_unit():
    """The Census matcher answers with the address of a POINT, and a unit is not a
    point: it echoes "2123 California St NW #D7" back as "2123 CALIFORNIA ST NW".
    Preferring that spelling — which is right, it is what confirms a parcel —
    discarded the only token that identifies a condominium."""
    from housing_label.enrich.assessor._shared import unit_of
    assert unit_of("2123 CALIFORNIA ST NW, WASHINGTON, DC, 20008") is None
    assert unit_of("2123 California St NW #D7, Washington, DC") == "D7"


def test_the_address_handed_to_the_adapter_keeps_both_halves():
    """The canonical street spelling from the geocoder, the unit from the reader.
    This is the exact composition the location layer performs, called by name
    rather than restated here, so the test cannot drift from production."""
    from housing_label.simulate.location import assessor_address
    merged = assessor_address("2123 CALIFORNIA ST NW, WASHINGTON, DC, 20008",
                              "2123 California St NW #D7, Washington, DC")
    assert dc._split_unit(merged)[1] == "D7"
    # ...and the parcel path is unaffected, because a unit is noise to it.
    assert address_key(merged, dc._LOCALITY) == \
        address_key("2123 CALIFORNIA ST NW, WASHINGTON, DC, 20008", dc._LOCALITY)


def test_a_reader_who_gave_no_unit_has_none_invented_for_them():
    """Nothing is fabricated: with no unit typed, the canonical address is handed
    over untouched and the condominium lookup refuses as it should."""
    from housing_label.simulate.location import assessor_address
    merged = assessor_address("3401 NEWARK ST NW, WASHINGTON, DC, 20016",
                              "3401 Newark St NW, Washington, DC")
    assert merged == "3401 NEWARK ST NW, WASHINGTON, DC, 20016"
    assert dc._split_unit(merged)[1] is None


def test_a_geocode_that_echoed_nothing_falls_back_to_what_was_typed():
    """The matcher does not always return an address. The typed one then stands in
    whole, unit included — losing it here would be the same silent gap."""
    from housing_label.simulate.location import assessor_address
    assert assessor_address(None, "2123 California St NW #D7, Washington, DC") == \
        "2123 California St NW #D7, Washington, DC"


def test_the_unit_is_found_before_the_city_not_only_at_the_end():
    """"2123 California St NW #D7, Washington, DC" is how the label's own address
    box produces it. Matching only at the end of the string read the unit in the
    rarer trailing form and missed it in the common one."""
    from housing_label.enrich.assessor._shared import unit_of
    assert unit_of("2123 California St NW #D7, Washington, DC") == "D7"
    assert unit_of("2123 California St NW, #D7, Washington DC") == "D7"
    assert unit_of("2123 California St NW, Apt 3-B, Washington, DC 20008") == "3-B"


def test_a_street_that_merely_contains_a_marker_word_is_not_a_unit():
    """"Route 66" and "Suite Dreams Rd" are street names. Reading a unit out of
    them would send a house down the condominium path with a fabricated one."""
    from housing_label.enrich.assessor._shared import unit_of
    assert unit_of("100 Route 66, Springfield, IL") is None
    assert unit_of("1 Suite Dreams Rd, Springfield, IL") is None
    assert unit_of("2123 California St NW, Washington, DC") is None


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
