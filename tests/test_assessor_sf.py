#!/usr/bin/env python3
"""The San Francisco adapter — two Socrata datasets, and the things they have to refuse.

Nothing here touches the network. DataSF is stubbed with row shapes recorded from
it live, for the reason every adapter test file gives: an adapter fails open on
purpose, so a renamed column or a broken match reads as "San Francisco has no
record here" and would never announce itself. A test that called the real service
would pass just as quietly.

What is worth pinning is what is genuinely San Francisco's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

San Francisco's own:

1. The source is **SoQL**, so the queries are built here — and only a coordinate
   and the parcel layer's own parcel numbers may ever be written into them.
2. The roll's address is a **fixed-width string** with a range, a lettered door,
   zero-padded ordinals, two-letter street types and a zero-padded unit in it.
3. A **condominium** is hundreds of lots on one polygon, and only the unit the
   reader typed can pick theirs out.
4. ``number_of_units`` is **0 on half the condominium units**, so it cannot say
   "nobody lives here"; the use code does.
5. The roll gains a year every summer, and **which year is latest** is read from
   the data, not assumed.
6. Socrata stops at ``$limit`` silently, and a long ``IN`` list is refused with
   **414**.

This file alone: ``pytest tests/test_assessor_sf.py``
"""

from __future__ import annotations

import csv
import math
import pathlib
import re
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, sf

# Recorded live from the 2025 closed roll (wv5m-vpq2). A single-family house in the
# Mission: one dwelling, so its area and story count are that home's.
_HOUSE = {"closed_roll_year": "2025", "parcel_number": "3595013",
          "property_location": "0000 3432 20TH                ST0000",
          "use_code": "SRES", "property_class_code": "D", "year_property_built": "1900",
          "number_of_units": "1.0", "number_of_stories": "2.0", "property_area": "3862.0"}

# Recorded live. Two flats filed under a house-number range, 471–473 Capp St.
_FLATS = {"closed_roll_year": "2025", "parcel_number": "3595007A",
          "property_location": "0473 0471 CAPP                ST0000",
          "use_code": "MRES", "property_class_code": "F", "year_property_built": "1941",
          "number_of_units": "2.0", "number_of_stories": "2.0", "property_area": "2832.0"}


def _unit(pid, unit, area, year="1996", stories="1.0", units="1.0"):
    """Recorded live: 468 07th Ave, six condominium lots stacked on one polygon,
    each with its unit zero-padded into the address and its own floor area."""
    row = {"closed_roll_year": "2025", "parcel_number": pid,
           "property_location": f"0000 0468 07TH                AV{unit}",
           "use_code": "SRES", "property_class_code": "Z",
           "number_of_units": units, "number_of_stories": stories,
           "property_area": area}
    if year is not None:
        row["year_property_built"] = year
    return row


_STACK = [_unit("1538040", "0001", "1825.0"), _unit("1538041", "0002", "1870.0"),
          _unit("1538042", "0003", "1825.0"),
          _unit("1538043", "0004", "3185.0", stories="2.0"),
          _unit("1538045", "0006", "617.0")]
# Recorded live: the stack's fifth lot records no year, no area and no units.
_EMPTY_LOT = _unit("1538044", "0005", "0.0", year=None, stories="0.0", units="0.0")

# Recorded live. A Millennium Tower unit: unit "5B" padded to "0005B", and — like
# 3,203 of 6,348 sampled condominium units — a unit count of zero.
_TOWER_UNIT = {"closed_roll_year": "2025", "parcel_number": "3719040",
               "property_location": "0000 0301 MISSION             ST0005B",
               "use_code": "SRES", "property_class_code": "Z",
               "year_property_built": "2009", "number_of_units": "0.0",
               "number_of_stories": "0.0", "property_area": "668.0"}

# Recorded live. A parking-stall condominium that carries a year built.
_PARKING = {"closed_roll_year": "2025", "parcel_number": "0127C204",
            "property_location": "0000 1022 VALLEJO             ST0004",
            "use_code": "COMM", "property_class_code": "PZ",
            "year_property_built": "1956", "number_of_units": "0.0",
            "number_of_stories": "0.0", "property_area": "0.0"}

#: A point in San Francisco. Which parcels it lands in is decided by the stubbed
#: parcel rows, not by the coordinate.
_POINT = (37.7597, -122.4148)

_HOUSE_ADDRESS = "3432 20TH ST, SAN FRANCISCO, CA, 94110"
_STACK_ADDRESS = "468 7TH AVE, SAN FRANCISCO, CA, 94118"


def _block(pid):
    m = re.match(r"^(\d{4}[A-Z]?)\d{3}", pid)
    return m.group(1) if m else ""


def _parcels_for(rows, inside=None):
    """Parcel-layer rows for these roll rows. ``inside`` names the parcel numbers
    that contain the point; None means all of them."""
    out = []
    for r in rows:
        pid = r["parcel_number"]
        out.append({"blklot": pid, "block_num": _block(pid),
                    "inside": inside is None or pid in inside})
    return out


def _transport(parcels, roll, calls, latest="2025"):
    """A stand-in for ``_shared.get_json`` that answers like DataSF.

    The roll is filtered by the parcel numbers the request names, so the request
    the adapter builds is what decides which rows come back — not the fixture.
    """
    def fake(url, params, deadline, read_slice=None):
        calls.append((url, dict(params), deadline, read_slice))
        if url == sf.PARCELS_URL:
            return [dict(p) for p in parcels]
        if url == sf.ROLL_URL and "max(" in params.get("$select", ""):
            return [{"latest": latest}]
        if url == sf.ROLL_URL:
            asked = set(re.findall(r"'([0-9A-Z]+)'", params["$where"].split(
                "parcel_number in", 1)[1].split(")", 1)[0]))
            since = int(re.search(r"closed_roll_year >= (\d+)", params["$where"]).group(1))
            return [dict(r) for r in roll if r["parcel_number"] in asked
                    and int(r["closed_roll_year"]) >= since]
        raise AssertionError(f"unexpected url {url}")
    return fake


def _lookup(roll, address=None, inside=None, parcels=None, calls=None, latest="2025"):
    """Drive ``sf.lookup()`` over recorded rows, through the module's real
    request path: parameter building, row filtering, unit narrowing and the
    shared parcel choice are all exercised."""
    calls = [] if calls is None else calls
    parcels = _parcels_for(roll, inside) if parcels is None else parcels
    sf._lookup_cached.cache_clear()
    sf._ROLL_YEAR.clear()
    saved = _shared.get_json
    _shared.get_json = _transport(parcels, roll, calls, latest)
    try:
        return sf.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        sf._lookup_cached.cache_clear()
        sf._ROLL_YEAR.clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_everything_the_roll_carries():
    got = _lookup([_HOUSE], address=_HOUSE_ADDRESS)
    assert got is not None
    assert got.parcel_id == "3595013"
    assert got.year_built == 1900
    assert got.sqft == 3862.0
    assert got.stories == 2
    assert got.construction is None and got.foundation is None and got.condition is None
    assert "2025 roll" in got.data_vintage


def test_containment_with_no_address_is_still_an_answer():
    """The label is scored from bare coordinates when the geocoder echoes no
    address; a point inside exactly one record is then all there is."""
    got = _lookup([_HOUSE])
    assert got is not None and got.year_built == 1900


def test_an_off_parcel_geocode_is_rescued_by_the_address():
    """The Census matcher puts most addresses on the street centerline, inside no
    parcel. The buffered candidates come from the same parcel request — and the
    address, not the distance, decides."""
    neighbor = dict(_HOUSE, parcel_number="3595014",
                    property_location="0000 3436 20TH                ST0000",
                    year_property_built="1908")
    calls = []
    got = _lookup([neighbor, _HOUSE], address=_HOUSE_ADDRESS, inside=set(), calls=calls)
    assert got is not None and got.parcel_id == "3595013" and got.year_built == 1900
    parcel_requests = [c for c in calls if c[0] == sf.PARCELS_URL]
    assert len(parcel_requests) == 1, "containment and buffer share one parcel request"


def test_a_neighbor_under_the_point_is_not_the_answer():
    """Containment is confirmed against the address too: city lots are narrower
    than the geocoder's error, so the polygon under the point can be next door."""
    neighbor = dict(_HOUSE, parcel_number="3595014",
                    property_location="0000 3436 20TH                ST0000",
                    year_property_built="1908")
    got = _lookup([neighbor], address=_HOUSE_ADDRESS)
    assert got is None


# ── property_location, the fixed-width address ────────────────────────────────


def test_the_fixed_width_layout_is_read_by_column():
    parts = sf._parse_location("0473 0471 CAPP                ST0000")
    assert parts == {"top": 473, "top_suffix": "", "low": 471, "low_suffix": "",
                     "street": "CAPP", "type": "ST", "unit": "0000"}
    tower = sf._parse_location("0000 0301 MISSION             ST0005B")
    assert tower["low"] == 301 and tower["top"] == 0 and tower["unit"] == "0005B"
    lettered = sf._parse_location("1986A1986 42ND                AV0000")
    assert lettered["top"] == 1986 and lettered["top_suffix"] == "A"
    assert lettered["low"] == 1986 and lettered["low_suffix"] == ""


def test_a_string_that_is_not_the_layout_is_not_an_address():
    for raw in (None, "", "3432 20TH ST", "1700 0015-HOFFMAN",
                "ABCD 0015 HOFFMAN             AV0000"):
        assert sf._address_of({"property_location": raw}) is None, raw
    assert sf._parse_location("0000 0000 MARKET              ST0000")["low"] == 0
    assert sf._address_of({"property_location": "0000 0000 MARKET              ST0000"}) is None


def test_the_rolls_zero_padded_ordinal_matches_the_geocoders():
    """"07TH" folds to "07" in the shared comparison and "7TH" to "7", so without
    dropping the pad no numbered street in the city would ever confirm."""
    row = {"property_location": "0000 0468 07TH                AV0000"}
    assert sf._address_of(row) == "468 7TH AVE"
    assert _shared.same_address("468 7TH AVE, SAN FRANCISCO, CA", sf._address_of(row))
    assert not _shared.same_address("468 17TH AVE", sf._address_of(row))


def test_the_rolls_own_street_types_are_respelled():
    """BL, HW, TE, CR, AL, PZ and XI are this roll's two-letter codes, unknown to
    the shared table; respelled, they match the geocoder's USPS forms and still
    refuse a different street type."""
    cases = {"BL": ("SUNSET", "1901 SUNSET BLVD"), "HW": ("GREAT", "2538 GREAT HWY"),
             "TE": ("CULEBRA", "30 CULEBRA TER"), "CR": ("ATOLL", "5 ATOLL CIR"),
             "AL": ("ARGENT", "8 ARGENT ALY"), "PZ": ("UNITED NATIONS", "1 UNITED NATIONS PLZ"),
             "XI": ("TONI STONE", "7 TONI STONE XING")}
    for code, (name, geocoded) in cases.items():
        number = geocoded.split()[0]
        loc = f"0000 {int(number):04d} {name:<20}{code}0000"
        got = sf._address_of({"property_location": loc})
        assert _shared.same_address(geocoded, got), (code, got)
    blvd = sf._address_of({"property_location": f"0000 1901 {'SUNSET':<20}BL0000"})
    assert not _shared.same_address("1901 SUNSET ST", blvd)


def test_an_unknown_street_type_never_matches_an_ordinary_street():
    """Freeway ramps are filed with type RA. Kept as written, the code becomes part
    of the name and cannot pass for anyone's street."""
    ramp = sf._address_of({"property_location": f"0000 0001 {'I-280 N OFF':<20}RA0000"})
    assert not _shared.same_address("1 I-280 N OFF ST", ramp)


def test_a_lettered_door_is_not_the_door_without_the_letter():
    """429A 6th Ave and 429 6th Ave are different doors on one block. Rendering the
    roll's "0429A" as 429 would let it answer for 429."""
    row = {"property_location": "0000 0429A06TH                AV0000"}
    assert sf._address_of(row) == "429 DOOR-A 6TH AVE"
    assert not _shared.same_address("429 6TH AVE", sf._address_of(row))
    assert not _shared.same_address(sf._canon("429B 6TH AVE"), sf._address_of(row))
    assert _shared.same_address(sf._canon("429A 6TH AVE, SAN FRANCISCO, CA"),
                                sf._address_of(row))


def test_a_lettered_door_resolves_and_never_answers_for_its_neighbor():
    """Recorded live: 309C Castro St, a condominium filed under a lettered number,
    beside the plain-numbered building. Before the rewrite neither side parsed and
    the door could not be reached at all."""
    lettered = dict(_HOUSE, parcel_number="3562047", property_class_code="Z",
                    property_location="0000 0309CCASTRO              ST0000",
                    year_property_built="1900", number_of_units="1.0",
                    property_area="1107.0")
    plain = dict(_HOUSE, parcel_number="3562044", year_property_built="1912",
                 property_location="0000 0309 CASTRO              ST0000")
    got = _lookup([lettered, plain], address="309C CASTRO ST, SAN FRANCISCO, CA, 94114",
                  inside=set())
    assert got is not None and got.parcel_id == "3562047" and got.sqft == 1107.0
    got = _lookup([lettered, plain], address="309 CASTRO ST, SAN FRANCISCO, CA, 94114",
                  inside=set())
    assert got is not None and got.parcel_id == "3562044"
    assert _lookup([lettered], address="309D CASTRO ST, SAN FRANCISCO, CA",
                   inside=set()) is None


def test_the_rewrite_touches_only_a_lettered_number():
    assert sf._canon("429A 6TH AVE, SAN FRANCISCO, CA") == "429 DOOR-A 6TH AVE, SAN FRANCISCO, CA"
    assert sf._canon("429 6TH AVE #A, SAN FRANCISCO, CA") == "429 6TH AVE #A, SAN FRANCISCO, CA"
    assert sf._canon("100 AVENUE B, SAN FRANCISCO, CA") == "100 AVENUE B, SAN FRANCISCO, CA"
    assert sf._canon(None) is None and sf._canon("") == ""


def test_a_parcel_filed_for_a_number_and_its_lettered_twin_answers_both():
    twin = dict(_HOUSE, property_location="1986A1986 42ND                AV0000")
    assert sf._address_of(twin, sf._canon("1986A 42ND AVE")) == "1986 DOOR-A 42ND AVE"
    assert sf._address_of(twin, sf._canon("1986 42ND AVE")) == "1986 42ND AVE"
    assert sf._address_of(twin, sf._canon("1986B 42ND AVE")) == "1986 42ND AVE"


def test_a_truncated_street_name_is_refused_not_guessed():
    """The name column is 20 characters; a longer name is cut off. A prefix match
    would be a guess, so the row simply never confirms."""
    row = {"property_location": "0099 0001 SERGEANT JOHN V YOUNST0000"}
    assert not _shared.same_address("1 SERGEANT JOHN V YOUNG ST", sf._address_of(row))


def test_a_range_answers_for_a_number_on_its_own_side_of_the_street():
    assert sf._address_of(_FLATS, "473 CAPP ST, SAN FRANCISCO, CA") == "473 CAPP ST"
    assert sf._address_of(_FLATS, "471 CAPP ST, SAN FRANCISCO, CA") == "471 CAPP ST"
    # 472 is across the street; offered under the range's bottom number instead.
    assert sf._address_of(_FLATS, "472 CAPP ST, SAN FRANCISCO, CA") == "471 CAPP ST"
    assert sf._address_of(_FLATS) == "471 CAPP ST"
    got = _lookup([_FLATS], address="473 CAPP ST, SAN FRANCISCO, CA, 94110", inside=set())
    assert got is not None and got.year_built == 1941
    assert _lookup([_FLATS], address="472 CAPP ST, SAN FRANCISCO, CA", inside=set()) is None


def test_a_range_too_wide_to_be_a_building_is_offered_only_at_its_bottom():
    wide = {"property_location": "0999 0001 MAIN                ST0000", "use_code": "SRES"}
    assert sf._address_of(wide, "501 MAIN ST") == "1 MAIN ST"


def test_a_vacant_lots_range_does_not_claim_the_house_inside_it():
    """Recorded live: "0198 0100 BRADFORD" is a vacant lot whose frontage range
    covers 160 Bradford St, where a 1-unit house is filed under its own number.
    Offered under the reader's number, the lot made the house ambiguous; a range
    is doors only on a record that holds a home."""
    lot = {"closed_roll_year": "2025", "parcel_number": "5657041",
           "property_location": "0198 0100 BRADFORD            ST0000",
           "use_code": "MISC", "property_class_code": "VR"}
    house = dict(_HOUSE, parcel_number="5656022", year_property_built="1951",
                 property_location="0000 0160 BRADFORD            ST0000")
    assert sf._address_of(lot, "160 BRADFORD ST") == "100 BRADFORD ST"
    got = _lookup([lot, house], address="160 BRADFORD ST, SAN FRANCISCO, CA", inside=set())
    assert got is not None and got.parcel_id == "5656022" and got.year_built == 1951


# ── condominiums ───────────────────────────────────────────────────────────────


def test_a_condominium_unit_is_picked_by_the_unit_the_reader_typed():
    """Six lots contain the point. The reader's unit is the only thing that can
    pick theirs out, and the area reported is that unit's own."""
    got = _lookup(_STACK + [_EMPTY_LOT], address="468 7TH AVE #4, SAN FRANCISCO, CA, 94118")
    assert got is not None
    assert got.parcel_id == "1538043"
    assert got.year_built == 1996
    assert got.sqft == 3185.0
    assert got.stories is None, "a unit's story count is its own floors, not the building's"


def test_the_rolls_zero_padding_is_not_part_of_the_unit():
    """The roll pads every unit to four characters, so "#4", "#04" and "Unit 0004"
    can only mean "0004" here."""
    for typed in ("#4", "#04", "Unit 0004", "Apt 4"):
        got = _lookup(_STACK, address=f"468 7TH AVE {typed}, SAN FRANCISCO, CA")
        assert got is not None and got.parcel_id == "1538043", typed


def test_a_lettered_unit_matches_only_itself():
    got = _lookup([_TOWER_UNIT, dict(_TOWER_UNIT, parcel_number="3719041",
                   property_location="0000 0301 MISSION             ST0005",
                   property_area="900.0")],
                  address="301 MISSION ST #5B, SAN FRANCISCO, CA, 94105")
    assert got is not None and got.parcel_id == "3719040" and got.sqft == 668.0


def test_a_half_number_unit_is_not_unit_twelve():
    """The roll writes "01/2" for a half number. Stripped to letters and digits it
    would read "12" and answer a reader in unit 12."""
    half = dict(_HOUSE, property_location="0000 3432 20TH                ST01/2")
    assert sf._unit(half) == "1/2"
    assert _lookup([half], address="3432 20TH ST #12, SAN FRANCISCO, CA") is None


def test_a_half_number_door_is_not_a_unit_of_the_house_in_front():
    """"3432 1/2" is usually a rear cottage: a separate building. The building
    fallback must not lend the front house's year to it, nor take its year for
    the front house."""
    half = dict(_HOUSE, parcel_number="3595099", year_property_built="1952",
                property_location="0000 3432 20TH                ST01/2")
    front = dict(_HOUSE, property_location="0000 3432 20TH                ST0001")
    assert _lookup([front, half], address="3432 20TH ST #7, SAN FRANCISCO, CA") is None


def test_a_lone_record_the_unit_did_not_match_is_not_a_building():
    """The fallback is for a stack of units. One record whose unit is not the
    reader's is a different home, not a building whose year all units share."""
    one = dict(_TOWER_UNIT)
    assert _lookup([one], address="301 MISSION ST #9Z, SAN FRANCISCO, CA") is None


def test_a_condominium_address_with_no_unit_names_no_unit():
    """Answering with one of the six units would be the confident guess the
    selection policy exists to refuse. With every unit agreeing on the year, the
    building's year is still reported — and nothing that belongs to one unit."""
    got = _lookup(_STACK, address=_STACK_ADDRESS)
    assert got is not None
    assert got.year_built == 1996
    assert got.parcel_id is None and got.sqft is None and got.stories is None


def test_one_unit_with_no_recorded_year_breaks_the_buildings_agreement():
    """Recorded live: 468 07th Ave's fifth lot records no year. Its year could be
    anything, so the building's year is not reported for a reader with no unit."""
    assert _lookup(_STACK + [_EMPTY_LOT], address=_STACK_ADDRESS) is None


def test_a_parking_stall_at_the_address_gets_no_vote():
    """Stall and store condominiums share the building's address but are not
    homes; they do not decide what year a home went up."""
    stall = dict(_PARKING, property_location="0000 0468 07TH                AV0001P",
                 year_property_built="1950")
    got = _lookup(_STACK + [stall], address=_STACK_ADDRESS)
    assert got is not None and got.year_built == 1996


def test_a_condominium_with_no_address_at_all_is_no_answer():
    assert _lookup(_STACK) is None


def test_a_unit_the_roll_does_not_have_is_no_answer():
    got = _lookup(_STACK, address="468 7TH AVE #9, SAN FRANCISCO, CA")
    # No unit 9, so the unit-less rows are offered — there are none — and the
    # building fallback reports the agreed year with nothing of any one unit's.
    assert got is not None and got.parcel_id is None and got.sqft is None


def test_a_two_unit_condominium_answers_the_reader_who_gave_no_unit():
    """816 Alvarado St, recorded live: one lot with no unit and one with unit A.
    A reader with no unit is answered with the lot that has none."""
    plain = {"closed_roll_year": "2025", "parcel_number": "6544030",
             "property_location": "0000 0816 ALVARADO            ST0000",
             "use_code": "SRES", "property_class_code": "Z",
             "year_property_built": "1903", "number_of_units": "1.0",
             "number_of_stories": "1.0", "property_area": "1082.0"}
    upper = dict(plain, parcel_number="6544031",
                 property_location="0000 0816 ALVARADO            ST0000A",
                 property_area="1290.0")
    got = _lookup([plain, upper], address="816 ALVARADO ST, SAN FRANCISCO, CA")
    assert got is not None and got.parcel_id == "6544030" and got.sqft == 1082.0
    got = _lookup([plain, upper], address="816 ALVARADO ST #A, SAN FRANCISCO, CA")
    assert got is not None and got.parcel_id == "6544031" and got.sqft == 1290.0


# ── the floor area that describes a building, not a home ───────────────────────


def test_flats_report_their_year_but_not_their_floor_area():
    """Two flats in one building: 2,832 sq ft is both homes. Never divided."""
    got = _lookup([_FLATS], address="471 CAPP ST, SAN FRANCISCO, CA")
    assert got is not None and got.year_built == 1941
    assert got.sqft is None and got.stories is None


def test_a_dwelling_the_roll_does_not_count_as_one_reports_no_area():
    for units in ("0.0", "2.0", None):
        row = dict(_HOUSE, number_of_units=units)
        got = _lookup([row], address=_HOUSE_ADDRESS)
        assert got is not None and got.year_built == 1900, units
        assert got.sqft is None and got.stories is None, units


def test_a_unit_typed_at_a_house_refuses_the_area():
    """A reader writing "#2" at an address the roll files as one dwelling is
    telling us something the record does not know about: the area is the whole
    building's."""
    got = _lookup([_HOUSE], address="3432 20TH ST #2, SAN FRANCISCO, CA")
    assert got is not None and got.year_built == 1900
    assert got.sqft is None and got.stories is None


def test_a_condominium_unit_with_no_unit_count_still_reports_its_area():
    """Half of the city's condominium units carry ``number_of_units`` of 0. The
    class is what says one lot is one home here; requiring a count of one would
    throw away every one of them."""
    got = _lookup([_TOWER_UNIT], address="301 MISSION ST #5B, SAN FRANCISCO, CA")
    assert got is not None and got.sqft == 668.0 and got.year_built == 2009


def test_an_apartment_buildings_area_is_never_reported():
    building = dict(_HOUSE, use_code="MRES", property_class_code="A15",
                    number_of_units="182.0", property_area="144256.0",
                    number_of_stories="12.0")
    got = _lookup([building], address=_HOUSE_ADDRESS)
    assert got is not None and got.sqft is None and got.stories is None


def test_a_half_story_is_not_rounded_into_one():
    got = _lookup([dict(_HOUSE, number_of_stories="1.5")], address=_HOUSE_ADDRESS)
    assert got is not None and got.stories is None and got.sqft == 3862.0


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_record_the_roll_classifies_as_no_home_reports_nothing():
    """A store's or an office's year built is not the year the reader's home went
    up. The use code is the statement; see the next test for why the unit count
    cannot be."""
    for use, klass in (("COMR", "C"), ("COMO", "O"), ("IND", "I"), ("COMH", "RH"),
                       ("GOVT", "PI"), ("MISC", "VA15")):
        assert _lookup([dict(_HOUSE, use_code=use, property_class_code=klass)],
                       address=_HOUSE_ADDRESS) is None, use


def test_a_parking_stall_with_a_year_is_not_a_home():
    """Recorded live: a parking-stall condominium at 1022 Vallejo St records 1956.
    A reader who types its unit must not be told their home was built then."""
    assert _lookup([_PARKING], address="1022 VALLEJO ST #4, SAN FRANCISCO, CA") is None


def test_a_zero_unit_count_is_not_a_statement_that_nobody_lives_here():
    """Florida and Connecticut refuse a year on an explicit zero dwelling count.
    Here the column is 0 on half the condominium units and on every townhouse, so
    that rule would throw away the city's condominiums. The year survives."""
    got = _lookup([dict(_TOWER_UNIT, number_of_units="0.0")],
                  address="301 MISSION ST #5B, SAN FRANCISCO, CA")
    assert got is not None and got.year_built == 2009


def test_apartments_over_a_store_are_homes():
    """Class AC, "Apartment & Commercial Store", is filed under COMM but holds
    dwellings."""
    got = _lookup([dict(_HOUSE, use_code="COMM", property_class_code="AC",
                        number_of_units="4.0")], address=_HOUSE_ADDRESS)
    assert got is not None and got.year_built == 1900 and got.sqft is None


def test_a_blank_use_code_is_silence_and_is_let_through():
    got = _lookup([dict(_HOUSE, use_code=None)], address=_HOUSE_ADDRESS)
    assert got is not None and got.year_built == 1900


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_missing_or_zero_year_is_not_a_year():
    for missing in ({"year_property_built": "0"}, {"year_property_built": ""},
                    {"year_property_built": None}, {"year_property_built": "19O0"}):
        got = _lookup([dict(_HOUSE, **missing)], address=_HOUSE_ADDRESS)
        assert got is not None and got.year_built is None, missing
        assert got.sqft == 3862.0, "the area survives; only the year is missing"


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    at = _lookup([dict(_HOUSE, year_property_built=str(EARLIEST_PLAUSIBLE_YEAR))],
                 address=_HOUSE_ADDRESS)
    assert at is not None and at.year_built == EARLIEST_PLAUSIBLE_YEAR
    below = _lookup([dict(_HOUSE, year_property_built=str(EARLIEST_PLAUSIBLE_YEAR - 1))],
                    address=_HOUSE_ADDRESS)
    assert below is not None and below.year_built is None


def test_a_record_that_records_nothing_is_not_an_answer():
    empty = dict(_HOUSE, year_property_built=None, property_area="0.0",
                 number_of_stories="0.0")
    assert _lookup([empty], address=_HOUSE_ADDRESS) is None


# ── which roll ────────────────────────────────────────────────────────────────


def test_the_latest_roll_year_is_read_from_the_data():
    calls = []
    got = _lookup([_HOUSE], address=_HOUSE_ADDRESS, calls=calls, latest="2025")
    assert got is not None
    roll = [c for c in calls if c[0] == sf.ROLL_URL and "max(" not in c[1]["$select"]]
    assert roll and all("closed_roll_year >= 2024" in c[1]["$where"] for c in roll), \
        "the latest year and the one before it"


def test_each_parcel_keeps_its_newest_row():
    """The request spans two rolls so a parcel the newest roll has not reached
    falls back to its previous certified row, dated as such."""
    old = dict(_HOUSE, closed_roll_year="2024", year_property_built="1899",
               property_area="3000.0")
    got = _lookup([old, _HOUSE], address=_HOUSE_ADDRESS)
    assert got is not None and got.year_built == 1900 and "2025 roll" in got.data_vintage
    got = _lookup([old], address=_HOUSE_ADDRESS)
    assert got is not None and got.year_built == 1899 and "2024 roll" in got.data_vintage


def test_a_roll_older_than_the_one_before_latest_is_not_read():
    stale = dict(_HOUSE, closed_roll_year="2019")
    assert _lookup([stale], address=_HOUSE_ADDRESS) is None


def test_the_latest_year_is_asked_once_per_cache_bucket():
    calls = []
    sf._lookup_cached.cache_clear()
    sf._ROLL_YEAR.clear()
    saved = _shared.get_json
    _shared.get_json = _transport(_parcels_for([_HOUSE]), [_HOUSE], calls)
    try:
        assert sf.lookup(*_POINT, _HOUSE_ADDRESS) is not None
        assert sf.lookup(_POINT[0] + 0.001, _POINT[1], _HOUSE_ADDRESS) is not None
    finally:
        _shared.get_json = saved
        sf._lookup_cached.cache_clear()
        sf._ROLL_YEAR.clear()
    assert sum(1 for c in calls if "max(" in c[1].get("$select", "")) == 1


def test_an_implausible_latest_year_fails_open_and_is_not_cached():
    for latest in ("1999", "2999", None):
        assert _lookup([_HOUSE], address=_HOUSE_ADDRESS, latest=latest) is None, latest
        assert not sf._ROLL_YEAR


# ── the queries ───────────────────────────────────────────────────────────────


def test_the_column_lists_are_the_privacy_boundary():
    """The roll carries exemption codes (the homeowner's exemption says whether the
    owner lives there), the latest sale date, ownership shares and every assessed
    value; none is an input to any dimension."""
    for private in ("exemption_code", "exemption_code_definition",
                    "homeowner_exemption_value", "current_sales_date",
                    "percent_of_ownership", "assessed_land_value",
                    "assessed_improvement_value", "misc_exemption_value", "*"):
        assert private not in sf._ROLL_COLUMNS, private
    assert "construction_type" not in sf._ROLL_COLUMNS, "no published code book"
    for private in ("supname", "shape", "*"):
        assert private not in sf._PARCEL_COLUMNS, private


def test_every_request_names_its_columns_and_its_limit():
    """Pinned on what reaches the transport. An empty $select is every column to
    Socrata, and a missing $limit is a silent 1,000-row cap."""
    calls = []
    _lookup([_HOUSE], address=_HOUSE_ADDRESS, inside=set(), calls=calls)
    assert len(calls) == 3, calls
    for url, params, _, _ in calls:
        assert params.get("$select"), url
        assert "*" not in params["$select"]
        if "max(" not in params["$select"]:
            assert params.get("$limit") == str(sf._ROW_LIMIT)
    roll = [p for u, p, _, _ in calls if u == sf.ROLL_URL and "max(" not in p["$select"]]
    assert roll[0]["$select"] == ",".join(sf._ROLL_COLUMNS)
    parcels = [p for u, p, _, _ in calls if u == sf.PARCELS_URL]
    assert parcels[0]["$select"].startswith("blklot, block_num, intersects(shape, ")


def test_the_parcel_request_asks_containment_and_buffer_at_once():
    params = sf._parcel_params(37.75971234567, -122.4148)
    assert params["$where"].startswith("active AND intersects(shape, 'POLYGON(("), \
        "retired parcels have shapes too"
    assert "intersects(shape, 'POINT(-122.4148000 37.7597123)') AS inside" in params["$select"]


def test_the_buffer_is_not_within_circle():
    """On a polygon column Socrata's ``within_circle`` means the WHOLE shape lies
    inside the circle. A tower's lot never does, so the first version of this
    adapter found no candidates at all beside 388 Beale St (0 rows, against 1,501
    lots reaching within 80 m) and missed most of the city's condominium towers.
    The buffer is a polygon that the shapes need only touch."""
    params = sf._parcel_params(37.7875680, -122.3914240)
    assert "within_circle" not in params["$where"]


def test_the_search_polygon_covers_the_whole_disc_and_little_more():
    lat, lon = 37.7875680, -122.3914240
    wkt = sf._search_area(lat, lon)
    pts = [tuple(map(float, p.split())) for p in
           wkt[len("POLYGON(("):-2].split(", ")]
    assert pts[0] == pts[-1] and len(pts) == sf._CIRCLE_SIDES + 1

    def meters(x, y):
        dy = (y - lat) * sf._METERS_PER_DEGREE
        dx = (x - lon) * sf._METERS_PER_DEGREE * math.cos(math.radians(lat))
        return math.hypot(dx, dy)

    corners = [meters(x, y) for x, y in pts]
    # Edge midpoints are the closest the boundary comes to the center.
    mids = [meters((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:])]
    assert min(mids) >= sf.SEARCH_RADIUS_M - 0.05, "the disk must be covered"
    assert max(corners) <= sf.SEARCH_RADIUS_M + 0.5, "and not much more than it"


def test_a_non_finite_coordinate_never_reaches_the_query():
    calls = []
    sf._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = _transport([], [], calls)
    try:
        assert sf.lookup(math.nan, -122.4, _HOUSE_ADDRESS) is None
        assert sf.lookup(37.7, math.inf, _HOUSE_ADDRESS) is None
    finally:
        _shared.get_json = saved
        sf._lookup_cached.cache_clear()
    assert calls == []


def test_a_parcel_number_that_is_not_one_is_never_written_into_a_query():
    calls = []
    bad = [{"blklot": "3595013' OR '1'='1", "block_num": "3595", "inside": True}]
    assert _lookup([_HOUSE], address=_HOUSE_ADDRESS, parcels=bad + _parcels_for([_HOUSE]),
                   calls=calls) is not None
    for _, params, _, _ in calls:
        assert "OR '1'" not in params.get("$where", "")


def test_the_block_clause_is_added_only_when_every_block_is_known():
    """The block clause is there for speed and is redundant with the parcel
    numbers; an unknown block must never exclude a candidate."""
    known = sf._roll_params([("3595013", "3595"), ("2999A019", "2999A")], 2024)
    assert "block in ('2999A','3595')" in known["$where"]
    unknown = sf._roll_params([("3595013", "3595"), ("3595014", "")], 2024)
    assert "block in" not in unknown["$where"]
    assert "'3595014'" in unknown["$where"]


def test_a_block_that_does_not_lead_the_parcel_number_is_unknown():
    parcels = [{"blklot": "3595013", "block_num": "9999", "inside": True}]
    calls = []
    _lookup([_HOUSE], address=_HOUSE_ADDRESS, parcels=parcels, calls=calls)
    roll = [p for u, p, _, _ in calls if u == sf.ROLL_URL and "max(" not in p["$select"]]
    assert roll and "block in" not in roll[0]["$where"]


def test_a_long_parcel_list_is_split_under_the_url_limit():
    """1,000 parcel numbers in one URL was refused with 414 URI Too Long; 421
    answered. A 450-lot stack goes in two requests of at most 400."""
    stack = [_unit(f"1538{n:03d}", f"{n:04d}", "900.0") for n in range(450)]
    calls = []
    got = _lookup(stack, address="468 7TH AVE #7, SAN FRANCISCO, CA", calls=calls)
    assert got is not None and got.parcel_id == "1538007"
    roll = [p for u, p, _, _ in calls if u == sf.ROLL_URL and "max(" not in p["$select"]]
    assert len(roll) == 2
    for p in roll:
        ids = p["$where"].split("parcel_number in (", 1)[1].split(")", 1)[0]
        assert ids.count("'") // 2 <= sf._IDS_PER_REQUEST


def test_more_parcels_than_a_lookup_may_ask_for_is_no_answer():
    """Hotel timeshares stack 2,393 lots on one polygon. Past the cap the lookup
    ends without asking, and without guessing."""
    many = [_unit(f"0306{n:04d}"[:8], f"{n:04d}", "900.0")
            for n in range(sf._IDS_PER_REQUEST * sf._MAX_ROLL_REQUESTS + 1)]
    calls = []
    assert _lookup(many, address="468 7TH AVE #7, SAN FRANCISCO, CA", calls=calls) is None
    assert not [c for c in calls if c[0] == sf.ROLL_URL and "max(" not in c[1]["$select"]]


def test_a_crowded_radius_still_answers_from_the_point_itself():
    """Towers within 80 m can exceed the cap while the point's own parcel does
    not; containment is still asked and answered, and only the buffer refused."""
    crowd = [dict(_HOUSE, parcel_number=f"37{n:05d}",
                  property_location="0000 0001 FOLSOM              ST0000")
             for n in range(sf._IDS_PER_REQUEST * sf._MAX_ROLL_REQUESTS)]
    got = _lookup([_HOUSE] + crowd, address=_HOUSE_ADDRESS, inside={"3595013"})
    assert got is not None and got.parcel_id == "3595013"
    # Off the parcel, the buffer would be needed — and is refused.
    assert _lookup([_HOUSE] + crowd, address=_HOUSE_ADDRESS, inside=set()) is None


def test_a_response_that_reaches_the_limit_is_treated_as_truncated():
    """Socrata stops at $limit without saying so. The rows it dropped could include
    the record that makes a match ambiguous."""
    flood = _parcels_for([_HOUSE]) * sf._ROW_LIMIT
    assert _lookup([_HOUSE], address=_HOUSE_ADDRESS, parcels=flood) is None


def test_a_body_that_is_not_a_row_list_is_not_an_answer():
    sf._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = lambda *a, **k: {"error": False, "message": "maintenance"}
    try:
        assert sf.lookup(*_POINT, _HOUSE_ADDRESS) is None
    finally:
        _shared.get_json = saved
        sf._lookup_cached.cache_clear()


def test_one_lot_drawn_as_two_shapes_is_one_candidate():
    parcels = [{"blklot": "3595013", "block_num": "3595", "inside": False},
               {"blklot": "3595013", "block_num": "3595", "inside": True}]
    got = _lookup([_HOUSE], parcels=parcels)
    assert got is not None and got.parcel_id == "3595013"


# ── the county and the source ─────────────────────────────────────────────────


def test_san_francisco_is_the_county_and_the_only_one():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert sf.COUNTY_FIPS == frozenset({"06075"})
    assert sf.COUNTY_FIPS <= geoids, "the county table must know this code"


def test_the_module_names_its_source():
    """DataSF moved from data.sfgov.org, which now answers with a 301."""
    for url in (sf.PARCELS_URL, sf.ROLL_URL):
        assert url.startswith("https://data.sf.gov/resource/"), url
    assert sf.NAME and sf.ATTRIBUTION and sf.DATA_VINTAGE
    assert "public domain" in sf.ATTRIBUTION


# ── the clock ─────────────────────────────────────────────────────────────────


def test_san_francisco_asks_for_its_own_read_slice():
    """A first roll request takes about a second and up to two; the shared
    one-second slice would cut off about one in five, reading as "no record".
    Pinned on what reaches the transport."""
    calls = []
    assert _lookup([_HOUSE], address=_HOUSE_ADDRESS, calls=calls) is not None
    assert calls and all(c[3] == sf.READ_SLICE_S for c in calls)
    assert sf.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert sf.LOOKUP_TIMEOUT + sf.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET
    assert sf.LOOKUP_TIMEOUT > _shared.TIMEOUT


def test_every_request_shares_one_clock_started_once():
    calls = []
    started = time.monotonic()
    _lookup([_HOUSE], address=_HOUSE_ADDRESS, inside=set(), calls=calls)
    deadlines = {c[2] for c in calls}
    assert len(calls) == 3 and len(deadlines) == 1, "each request was handed its own budget"
    assert abs((deadlines.pop() - started) - sf.LOOKUP_TIMEOUT) < 0.5


# ── failing open ──────────────────────────────────────────────────────────────


def test_the_portal_falling_over_is_not_evidence_of_absence():
    def boom(*args, **kwargs):
        raise RuntimeError("503 Service Unavailable")

    sf._lookup_cached.cache_clear()
    sf._ROLL_YEAR.clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert sf.lookup(*_POINT, _HOUSE_ADDRESS) is None
    finally:
        _shared.get_json = saved
        sf._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([], address=_HOUSE_ADDRESS) is None
