#!/usr/bin/env python3
"""The Virginia adapter — Chesterfield in one request, Richmond in two.

Nothing here touches the network. Each locality's services are stubbed with row
shapes recorded from them live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Virginia has no record here" and would never announce itself. A test that called
the real services would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Virginia's own:

1. Chesterfield's layer carries **placeholder polygons** (holes, a county-sized
   "0") and **commercial occupancy codes** whose year is a bank's or a church's.
2. Both localities **stack condominium units** on one polygon, and Chesterfield
   writes a garden building's units under one address with no unit at all.
3. Richmond writes a unit as a trailing **"U" token** the shared parser cannot
   read, and its parcels carry only a house number, so the address comes from a
   second layer.
4. Richmond's improvement records are **points inside the lot**, so its buffered
   search needs the lot's depth added to the shared radius.
5. Fairfax and Arlington have the data and are **held for their terms**.

This file alone: ``pytest tests/test_assessor_va.py``
"""

from __future__ import annotations

import csv
import inspect
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, va

CHESTERFIELD, RICHMOND = "51041", "51760"

# ── rows recorded live, 2026-10-04 ─────────────────────────────────────────────

# Chesterfield: a single-family house (sampled at random from the layer).
_CH_HOUSE = {"Name": "755636085900000", "GPIN": "7556360859", "TaxID": 755636085900000,
             "ParcelType": "Parcel", "UseCode": "SD", "Address": "10121 REEDY BRANCH RD",
             "AssessmentYear": 2026, "YearBuilt": 1981, "FinishedArea": 1056,
             "Stories": 1}
# Chesterfield: a townhouse with a two-and-a-half-story record.
_CH_TOWNHOUSE = {"Name": "696670709900000", "GPIN": "6966707099",
                 "TaxID": 696670709900000, "ParcelType": "Parcel", "UseCode": "TH",
                 "Address": "18609 PALISADES RDG", "AssessmentYear": 2026,
                 "YearBuilt": 2023, "FinishedArea": 2173, "Stories": 2.5}
# Chesterfield: the layer's non-records — a "Hole" inside a parcel's outline and
# the county-sized polygon named "0" — every attribute null.
_CH_HOLE = {"Name": "697647243300000", "GPIN": "6976472433", "TaxID": None,
            "ParcelType": "Hole", "UseCode": None, "Address": None,
            "AssessmentYear": None, "YearBuilt": None, "FinishedArea": None,
            "Stories": None}
_CH_ZERO = {"Name": "0", "GPIN": None, "TaxID": None, "ParcelType": None,
            "UseCode": None, "Address": None, "AssessmentYear": None,
            "YearBuilt": None, "FinishedArea": None, "Stories": None}
# Chesterfield: a bank, under the commercial occupancy code 510.
_CH_BANK = {"Name": "717000000000000", "GPIN": "7170000000", "TaxID": 717000000000000,
            "ParcelType": "Parcel", "UseCode": "510", "Address": "17211 HULL STREET RD",
            "AssessmentYear": 2026, "YearBuilt": 1991, "FinishedArea": 12000,
            "Stories": 1}
# Chesterfield: a duplex — one record for both halves.
_CH_DUPLEX = {"Name": "796609039000000", "GPIN": "7966090390", "TaxID": 796609039000000,
              "ParcelType": "Parcel", "UseCode": "DU", "Address": "3500 MAIN ST",
              "AssessmentYear": 2026, "YearBuilt": 1972, "FinishedArea": 1548,
              "Stories": 1}
# Chesterfield: Keswick Apartments, one record per address on the complex (100).
_CH_APARTMENT = {"Name": "770000000000000", "GPIN": "7700000000",
                 "TaxID": 770000000000000, "ParcelType": "Parcel", "UseCode": "100",
                 "Address": "3929 KESWICK PL", "AssessmentYear": 2026,
                 "YearBuilt": 1984, "FinishedArea": 413, "Stories": 1}
# Chesterfield: three units of one garden condominium building, all at one street
# address with no unit designator; only TaxID tells them apart.
_CH_GARDEN = [
    {"Name": "723704173400000", "GPIN": "7237041734", "TaxID": 723704173400000 + n,
     "ParcelType": "Parcel", "UseCode": "CD", "Address": "1111 BRIARS CT",
     "AssessmentYear": 2026, "YearBuilt": 2018, "FinishedArea": area, "Stories": 1}
    for n, area in ((7, 1489), (8, 1547), (13, 1776))
]
# Chesterfield: two villas of a condominium complex on the complex's outline, each
# unit with its own house number.
_CH_VILLAS = [
    {"Name": "709674500800000", "GPIN": "7096745008", "TaxID": 709674500800000 + n,
     "ParcelType": None, "UseCode": "CN", "Address": addr, "AssessmentYear": 2026,
     "YearBuilt": 2025, "FinishedArea": area, "Stories": 1}
    for n, addr, area in ((1, "6647 MAYLAND RIDGE LN", 1870),
                          (2, "6649 MAYLAND RIDGE LN", 2377))
]

# Richmond: a house's parcel (current layer) and its improvement record.
_RVA_PARCEL = {"PIN": "W0001078015"}
_RVA_HOUSE = {"parcel_id": "W0001078015               ",
              "prop_street": "6 N Stafford Ave                        ",
              "property_class": 120, "year_built": 1916, "sfla": 1210, "cdu": "G ",
              "eff_year": 20250101}
# Richmond: one parcel, a 1939 house and a 2001 second dwelling (an accessory
# unit), both under the parcel's street address.
_RVA_TWO_DWELLINGS = [
    {"parcel_id": "W0002024017               ", "prop_street": "4508 Leonard Pkwy",
     "property_class": 115, "year_built": y, "sfla": a, "cdu": c, "eff_year": 20250101}
    for y, a, c in ((1939, 1564, "G "), (2001, 412, "VG"))
]
# Richmond: condominium units, the unit written as a trailing "U" token.
_RVA_UNITS = [
    {"parcel_id": f"E00003880{n:02d}               ",
     "prop_street": f"2501 E Franklin St U{u}", "property_class": 211,
     "year_built": 1910, "sfla": a, "cdu": "G ", "eff_year": 20250101}
    for n, u, a in ((29, "8", 1332), (30, "9", 1100), (31, "10", 1201))
]
# Richmond: the condominium's common-area record, under the units' street address.
_RVA_COMMON = {"parcel_id": "E0000388001               ",
               "prop_street": "2501 E Franklin St", "property_class": 205,
               "year_built": 1910, "sfla": None, "cdu": None, "eff_year": 20250101}

#: A point in Chesterfield, and one in Richmond. Which parcel a coordinate lands in
#: is decided here by the stubbed rows, not by the coordinate.
_CH_POINT = (37.3073, -77.5632)
_RVA_POINT = (37.5516, -77.4706)


def _lookup(exact=(), near=(), address=None, county=CHESTERFIELD, parcels=(),
            pin_rows=None, slices=None, params=None, urls=None, county_answer=None,
            exceeded=False, point=None):
    """Drive ``va.lookup()`` over recorded rows, through the real transport helper.

    Chesterfield: ``exact`` is what the point lands inside, ``near`` what a
    buffered search finds. Richmond: ``parcels`` are the containing parcels,
    ``pin_rows`` the improvement records their PINs find (default: ``exact``),
    and ``near`` the improvement points a buffered search finds. ``slices``,
    ``params`` and ``urls`` collect what each request was handed.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls
    pin_rows = list(exact) if pin_rows is None else list(pin_rows)

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if url == va.COUNTY_URL:
            feats = ([{"attributes": {"GEOID": county_answer}}] if county_answer else [])
            return {"features": feats}
        if exceeded:
            raise _shared.TruncatedResponse("truncated at the transfer limit")
        if url == va.RICHMOND_PARCEL_URL:
            rows = list(parcels)
        elif url == va.RICHMOND_IMPROVEMENT_URL and not request.get("distance"):
            rows = pin_rows
        else:
            rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    va._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        where = point or (_RVA_POINT if county == RICHMOND else _CH_POINT)
        return va.lookup(*where, address, county)
    finally:
        _shared.get_json = saved
        va._lookup_cached.cache_clear()


def _rva(pin_rows=(), near=(), address=None, parcels=None, **kw):
    if parcels is None:
        # The parcels containing the point are the ones the records belong to,
        # unless a test says otherwise.
        parcels = [{"PIN": r["parcel_id"].strip()} for r in pin_rows] or [_RVA_PARCEL]
    return _lookup(near=near, address=address, county=RICHMOND, parcels=parcels,
                   pin_rows=pin_rows, **kw)


# ── Chesterfield: the ordinary house ──────────────────────────────────────────


def test_a_chesterfield_house_reports_its_year_area_and_stories():
    got = _lookup([_CH_HOUSE])
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1981, 1056.0, 1)
    assert got.parcel_id == "755636085900000"
    assert "2026 assessment" in got.data_vintage


def test_a_house_off_its_lot_is_found_by_address_in_the_buffer():
    """Recorded live: the Census matcher put 10121 Reedy Branch Rd inside 10101's
    lot. Containment must not accept the neighbor; the buffer, by address, finds
    the house."""
    neighbor = dict(_CH_HOUSE, TaxID=755636366900000, Address="10101 REEDY BRANCH RD",
                    YearBuilt=1980, FinishedArea=1908)
    got = _lookup([neighbor], near=[neighbor, _CH_HOUSE],
                  address="10121 REEDY BRANCH RD, CHESTERFIELD, VA, 23838")
    assert got is not None and got.year_built == 1981
    assert got.parcel_id == "755636085900000"


def test_a_half_story_is_not_rounded_into_a_whole_one():
    got = _lookup([_CH_TOWNHOUSE])
    assert got is not None and got.year_built == 2023
    assert got.stories is None
    assert got.sqft == 2173.0


# ── Chesterfield: non-records and non-homes ───────────────────────────────────


def test_placeholder_polygons_are_not_records():
    assert _lookup([_CH_HOLE]) is None
    assert _lookup([_CH_ZERO]) is None


def test_a_placeholder_does_not_make_a_real_parcel_ambiguous():
    got = _lookup([_CH_HOLE, _CH_ZERO, _CH_HOUSE])
    assert got is not None and got.year_built == 1981


def test_a_commercial_occupancy_code_reports_no_year():
    """A bank's year built is not anybody's home's, and it would carry the
    ``observed`` tag."""
    assert _lookup([_CH_BANK]) is None


def test_an_apartment_complex_reports_its_year_but_not_an_area():
    got = _lookup([_CH_APARTMENT])
    assert got is not None and got.year_built == 1984
    assert got.sqft is None and got.stories is None


def test_a_duplex_keeps_its_year_and_stories_but_not_its_area():
    got = _lookup([_CH_DUPLEX])
    assert got is not None and got.year_built == 1972 and got.stories == 1
    assert got.sqft is None, "a duplex's record covers both halves"


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_CH_HOUSE, YearBuilt=0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 1056.0


def test_a_record_that_says_nothing_is_not_an_answer():
    vacant = dict(_CH_HOUSE, UseCode=None, YearBuilt=0, FinishedArea=0, Stories=0)
    assert _lookup([vacant]) is None


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    got = _lookup([dict(_CH_HOUSE, YearBuilt=EARLIEST_PLAUSIBLE_YEAR - 1)])
    assert got is not None and got.year_built is None
    got = _lookup([dict(_CH_HOUSE, YearBuilt=EARLIEST_PLAUSIBLE_YEAR)])
    assert got is not None and got.year_built == EARLIEST_PLAUSIBLE_YEAR


# ── Chesterfield: condominiums ─────────────────────────────────────────────────


def test_a_garden_buildings_units_are_one_building_with_one_year_and_no_area():
    """Eight units share "1111 BRIARS CT" with no unit designator. Offered as
    eight candidates they are ambiguous; as one building they agree on 2018.
    Which unit's area is the reader's is not known, so none is reported."""
    got = _lookup(list(_CH_GARDEN))
    assert got is not None and got.year_built == 2018
    assert got.sqft is None and got.stories is None
    assert got.parcel_id == "7237041734", "the building's parcel, not a unit's"


def test_a_building_whose_units_disagree_about_the_year_has_none():
    split = [_CH_GARDEN[0], dict(_CH_GARDEN[1], YearBuilt=2019)]
    assert _lookup(split) is None


def test_a_villa_with_its_own_address_is_found_and_keeps_its_area():
    """Two villas on the complex's outline: the point is inside both, so
    containment cannot choose; the address can, through the buffer."""
    got = _lookup(list(_CH_VILLAS), near=list(_CH_VILLAS),
                  address="6649 MAYLAND RIDGE LN, CHESTERFIELD, VA, 23832")
    assert got is not None and got.year_built == 2025
    assert got.sqft == 2377.0
    assert got.parcel_id == "709674500800002"


def test_without_an_address_a_complex_stays_ambiguous():
    assert _lookup(list(_CH_VILLAS)) is None


def test_chesterfields_wall_and_foundation_codes_are_never_requested():
    """No code table is published for WF/CB/BB/VY; a column never fetched cannot
    be read by a later edit."""
    for col in ("ConstructionType", "FoundationType", "ExteriorFinish", "Basement"):
        assert col not in va._CHESTERFIELD_FIELDS.split(",")


# ── Richmond: two hops ─────────────────────────────────────────────────────────


def test_a_richmond_house_is_found_through_its_parcels_pin():
    params, urls = [], []
    got = _rva([_RVA_HOUSE], address="6 N STAFFORD AVE, RICHMOND, VA, 23220",
               params=params, urls=urls)
    assert got is not None
    assert (got.year_built, got.sqft, got.stories, got.condition) == (1916, 1210.0, 2,
                                                                      "good")
    assert got.parcel_id == "W0001078015"
    assert "2025 assessment" in got.data_vintage
    assert "snapshot" in got.data_vintage
    assert urls[:2] == [va.RICHMOND_PARCEL_URL, va.RICHMOND_IMPROVEMENT_URL]
    assert params[1]["where"] == "parcel_id LIKE 'W0001078015%'"


def test_a_parcel_with_no_improvement_record_widens_to_the_buffer():
    near_house = dict(_RVA_HOUSE)
    got = _rva([], near=[near_house], address="6 N STAFFORD AVE, RICHMOND, VA")
    assert got is not None and got.year_built == 1916


def test_the_buffer_on_points_adds_the_lots_depth_to_the_shared_radius():
    params = []
    _rva([], near=[], address="6 N STAFFORD AVE, RICHMOND, VA", params=params)
    buffered = [p for p in params if p.get("distance")]
    assert buffered, "the lookup never widened"
    assert float(buffered[0]["distance"]) == (_shared.SEARCH_RADIUS_M
                                              + va._RVA_POINT_ALLOWANCE_M)


def test_a_condominium_stack_asks_by_block_rather_than_with_a_404_url():
    """Recorded live: 64 unit parcels under one Cargreen Road point made a 4.8 KB
    query string, which ArcGIS Online answers with a 404."""
    parcels = [{"PIN": f"C0070553{n:03d}"} for n in range(193, 257)]
    params = []
    _rva([], parcels=parcels, params=params)
    pin_query = [p for p in params if "parcel_id LIKE" in str(p.get("where"))]
    assert pin_query and pin_query[0]["where"] == "parcel_id LIKE 'C0070553%'"


def test_block_rows_are_filtered_back_to_the_containing_pins():
    parcels = [{"PIN": f"W0001078{n:03d}"} for n in range(0, 25)] + [_RVA_PARCEL]
    stranger = dict(_RVA_HOUSE, parcel_id="W0001078999", year_built=1999)
    got = _rva([stranger], parcels=parcels)
    assert got is None, "a row of the same block but another PIN is not a candidate"


def test_a_pin_is_reduced_to_letters_and_digits_before_it_reaches_a_predicate():
    params = []
    _rva([], parcels=[{"PIN": "W0001078015' OR 1=1 --"}], params=params)
    pin_query = [p for p in params if "parcel_id LIKE" in str(p.get("where"))]
    assert pin_query and pin_query[0]["where"] == "parcel_id LIKE 'W0001078015OR11%'"


def test_two_dwellings_built_in_different_years_have_no_single_year():
    """Recorded live: a 1939 house with a 2001 accessory dwelling, one parcel and
    one street address. Neither year is "the house's" without knowing which one
    the reader lives in."""
    assert _rva(list(_RVA_TWO_DWELLINGS), address="4508 LEONARD PKWY, RICHMOND, VA") \
        is None


def test_a_garage_class_reports_no_year():
    assert _rva([dict(_RVA_HOUSE, property_class=190)]) is None


def test_stories_come_only_from_classes_that_name_a_whole_count():
    one = _rva([dict(_RVA_HOUSE, property_class=110)])
    assert one is not None and one.stories == 1
    for cls in (115, 130, 150):
        got = _rva([dict(_RVA_HOUSE, property_class=cls)])
        assert got is not None and got.stories is None, cls


def test_a_two_family_house_keeps_its_year_but_not_its_area():
    got = _rva([dict(_RVA_HOUSE, property_class=160)])
    assert got is not None and got.year_built == 1916 and got.sqft is None


def test_cdu_grades_between_two_of_the_labels_stay_empty():
    for cdu in ("VG", "VP"):
        got = _rva([dict(_RVA_HOUSE, cdu=cdu)])
        assert got is not None and got.condition is None, cdu
    for cdu, want in (("EX", "excellent"), ("AV", "average"), ("F ", "fair"),
                      ("P ", "poor")):
        got = _rva([dict(_RVA_HOUSE, cdu=cdu)])
        assert got is not None and got.condition == want, cdu


# ── Richmond: units ────────────────────────────────────────────────────────────


def test_richmonds_trailing_u_token_is_its_unit():
    assert va._richmond_street("3510 East Richmond Road U9    ") == (
        "3510 East Richmond Road", "9")
    assert va._richmond_street("507 N Hamilton St UE") == ("507 N Hamilton St", "E")
    assert va._richmond_street("1101 Haxall Pt U1002") == ("1101 Haxall Pt", "1002")
    assert va._richmond_street("1 Stuart Cir UPL-D") == ("1 Stuart Cir", "PL-D")


def test_a_street_address_without_a_unit_is_left_alone():
    assert va._richmond_street("6 N Stafford Ave") == ("6 N Stafford Ave", None)
    assert va._richmond_street("2416 Buford Ave") == ("2416 Buford Ave", None)
    assert va._richmond_street("") == (None, None)


def test_a_typed_unit_picks_its_own_record_and_its_area():
    got = _rva(list(_RVA_UNITS) + [_RVA_COMMON],
               address="2501 E FRANKLIN ST #8, RICHMOND, VA, 23223")
    assert got is not None
    assert got.parcel_id == "E0000388029"
    assert (got.year_built, got.sqft) == (1910, 1332.0)


def test_the_common_area_beside_a_named_unit_does_not_demote_it_to_a_building():
    """Recorded live: 2501 E Franklin St #8 came back as "a building" with no
    area, because the condominium's common-area record shares the street address
    and carries no unit."""
    got = _rva([_RVA_UNITS[0], _RVA_COMMON],
               address="2501 E FRANKLIN ST #8, RICHMOND, VA, 23223")
    assert got is not None and got.sqft == 1332.0


def test_without_a_unit_the_stack_is_one_building_reporting_its_year_only():
    got = _rva(list(_RVA_UNITS), address="2501 E FRANKLIN ST, RICHMOND, VA, 23223")
    assert got is not None and got.year_built == 1910
    assert got.sqft is None and got.parcel_id is None


def test_a_unit_that_is_not_the_typed_one_never_lends_its_area():
    got = _rva([_RVA_UNITS[1]], address="2501 E FRANKLIN ST #8, RICHMOND, VA")
    assert got is None, "the only unit at the address is a different unit"


def test_a_unit_inside_the_complex_outline_survives_a_buffer_that_misses_its_point():
    """Recorded live: 1453 Cargreen Road #B. The geocode lands inside the
    complex's outline, under every unit's parcel, so containment cannot choose —
    and the units' points all sit on one spot 143 m away, beyond the buffer. The
    widened search must still hold what the point was inside."""
    other = dict(_RVA_UNITS[0], parcel_id="C0070553240", prop_street="1455 Cargreen Road UB")
    mine = dict(_RVA_UNITS[0], parcel_id="C0070553238", prop_street="1453 Cargreen Road UB",
                year_built=1970, sfla=1084)
    got = _rva([other, mine], near=[], address="1453 CARGREEN RD #B, RICHMOND, VA, 23225")
    assert got is not None and got.parcel_id == "C0070553238"
    assert (got.year_built, got.sqft) == (1970, 1084.0)


def test_one_record_arriving_twice_is_still_one_record_with_its_area():
    """The same row from both searches, or from two parts of a multipart parcel,
    is not a second unit of a building."""
    neighbor = dict(_CH_HOUSE, TaxID=755636366900000, Address="10101 REEDY BRANCH RD")
    got = _lookup([neighbor], near=[_CH_HOUSE, dict(_CH_HOUSE), neighbor],
                  address="10121 REEDY BRANCH RD, CHESTERFIELD, VA")
    assert got is not None and got.sqft == 1056.0 and got.stories == 1


def test_a_lone_unit_record_reports_no_area_to_a_reader_who_named_no_unit():
    got = _rva([_RVA_UNITS[0]], address="2501 E FRANKLIN ST, RICHMOND, VA")
    assert got is not None and got.year_built == 1910
    assert got.sqft is None


# ── fields, privacy, and the effective year ────────────────────────────────────


def test_every_field_list_is_explicit_and_carries_nothing_private():
    for fields in (va._CHESTERFIELD_FIELDS, va._RICHMOND_PARCEL_FIELDS,
                   va._RICHMOND_IMPROVEMENT_FIELDS):
        cols = fields.split(",")
        assert "*" not in cols
        for private in ("OwnerName", "OwnerAddress", "OwnerCity", "SalePrice",
                        "MailAddress", "owner1", "MaskedOwner", "SaleDate"):
            assert private not in cols, private


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([_CH_HOUSE], params=params)
    assert params and all(p["outFields"] == va._CHESTERFIELD_FIELDS for p in params)
    params = []
    _rva([_RVA_HOUSE], params=params)
    assert params[0]["outFields"] == va._RICHMOND_PARCEL_FIELDS
    assert params[1]["outFields"] == va._RICHMOND_IMPROVEMENT_FIELDS


def test_the_effective_year_is_never_requested():
    """Richmond's EfYr/max_EfYr move when a house is improved. (``eff_year`` is
    the assessment's effective DATE, 20250101, read only for the vintage.)"""
    cols = va._RICHMOND_IMPROVEMENT_FIELDS.split(",")
    assert "EfYr" not in cols and "max_EfYr" not in cols


# ── the locality list ──────────────────────────────────────────────────────────


def test_every_claimed_locality_is_a_real_virginia_county_equivalent():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        virginia = {r["geoid"] for r in csv.DictReader(fh)
                    if r["geoid"].startswith("51") and len(r["geoid"]) == 5}
    assert len(virginia) >= 133, f"expected Virginia's 133 localities, got {len(virginia)}"
    assert va.COUNTY_FIPS <= virginia
    assert va.COUNTY_FIPS == {CHESTERFIELD, RICHMOND}


def test_richmond_city_is_not_richmond_county_or_its_neighbors():
    """51760 is the independent city. 51159 is Richmond County, on the Northern
    Neck; Henrico (51087) surrounds the city. None of them is this layer."""
    for fips in ("51159", "51087"):
        assert fips not in va.COUNTY_FIPS, fips


def test_localities_held_for_terms_or_without_data_are_not_answered():
    """Fairfax's disclaimer grants reproduction "for internal or personal use";
    Arlington's portal terms forbid reuse without written permission. Prince
    William, Loudoun and Alexandria publish no usable assessor year."""
    assert va._HELD_FOR_TERMS == {"51059", "51013"}
    for fips in va._HELD_FOR_TERMS | va._NO_PUBLIC_YEAR:
        assert fips not in va.COUNTY_FIPS, fips
        assert va.url_for(fips) is None, fips


def test_no_held_locality_has_a_service_url_in_the_module():
    source = inspect.getsource(va)
    for host in ("ioennV6PpG5Xodq0", "JrtUzVcH8S2wnzVH", "datahub-v2.arlingtonva.us"):
        assert f"{host}/" not in source.replace(" ", ""), host


def test_url_for_names_each_localitys_own_publisher():
    assert va.url_for(CHESTERFIELD) == va.CHESTERFIELD_URL
    assert va.url_for(RICHMOND) == va.RICHMOND_IMPROVEMENT_URL
    from housing_label import utils
    assert utils.host_of(va.CHESTERFIELD_URL) != utils.host_of(va.RICHMOND_IMPROVEMENT_URL)
    assert utils.host_of(va.RICHMOND_PARCEL_URL) == utils.host_of(va.RICHMOND_IMPROVEMENT_URL)


def test_the_callers_county_picks_the_layer_and_skips_the_county_request():
    urls = []
    _lookup([_CH_HOUSE], urls=urls)
    assert urls and all(u == va.CHESTERFIELD_URL for u in urls)
    urls = []
    _rva([_RVA_HOUSE], urls=urls)
    assert va.COUNTY_URL not in urls and va.CHESTERFIELD_URL not in urls


def test_without_a_county_the_point_is_located_first():
    urls = []
    got = _lookup([_CH_HOUSE], county=None, county_answer=CHESTERFIELD, urls=urls)
    assert got is not None and got.year_built == 1981
    assert urls[0] == va.COUNTY_URL


def test_a_point_outside_the_covered_localities_is_no_answer():
    assert _lookup([_CH_HOUSE], county=None, county_answer=None) is None
    assert _lookup([_CH_HOUSE], county=None, county_answer="51059") is None


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_localitys_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to
    fit — strictly under, not on, the host's allowance."""
    from housing_label import config
    for fips, cfg in va.COUNTIES.items():
        assert cfg.timeout + cfg.read_slice < config.UPSTREAM_HOST_BUDGET, fips
    assert va.LOOKUP_TIMEOUT + va.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_each_request_is_handed_its_localitys_read_slice():
    slices = []
    _rva([_RVA_HOUSE], slices=slices)
    assert slices and all(s == va.COUNTIES[RICHMOND].read_slice for s in slices)


def test_every_request_of_one_lookup_shares_one_clock():
    seen = []

    def note(url, params, deadline, read_slice=None):
        seen.append(deadline)
        if url == va.RICHMOND_PARCEL_URL:
            return {"features": [{"attributes": _RVA_PARCEL}]}
        return {"features": []}

    va._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        va.lookup(*_RVA_POINT, "6 N STAFFORD AVE, RICHMOND, VA", RICHMOND)
    finally:
        _shared.get_json = saved
        va._lookup_cached.cache_clear()
    assert len(seen) == 3, f"parcel, PIN and buffered requests expected, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs((seen[0] - started) - va.COUNTIES[RICHMOND].timeout) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_portal_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    va._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert va.lookup(*_CH_POINT, "10121 REEDY BRANCH RD", CHESTERFIELD) is None
        assert va.lookup(*_RVA_POINT, "6 N STAFFORD AVE", RICHMOND) is None
    finally:
        _shared.get_json = saved
        va._lookup_cached.cache_clear()


def test_a_truncated_page_is_no_answer_rather_than_a_unique_match():
    assert _lookup([_CH_HOUSE], exceeded=True) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
    assert _rva([], parcels=()) is None
