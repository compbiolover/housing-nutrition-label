#!/usr/bin/env python3
"""The Pennsylvania adapter — four county layers, and the refusals each one needs.

Nothing here touches the network. Each county's service is stubbed with row
shapes recorded from it live (2026-10-03), for the reason every adapter test file
gives: an adapter fails open on purpose, so a renamed column or a broken match
reads as "this county has no record here" and would never announce itself.

The shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Pennsylvania's own:

1. **Montgomery's condominium units are side-by-side polygons**, so the unit
   under an interpolated geocode is an arbitrary neighbor. A unit is answered
   only when the reader's address AND unit pick it out uniquely.
2. **One street address on two houses** — 529 W Simpson Street, Mechanicsburg —
   which containment alone would confirm at random.
3. **Northampton's YEAR_BUILT column is empty**; the year is RES_YEAR_BUILT.
4. **Cumberland writes its year as text**, its stories and walls as words, and
   uses 1776 as a placeholder year on cell towers and homes alike.
5. Each county's own dwelling count or land-use code decides whether a floor
   area describes one home, and whether anyone lives there at all.

This file alone: ``pytest tests/test_assessor_pa.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

from housing_label.enrich.assessor import _shared, pa
from housing_label.enrich.assessor.base import CONSTRUCTION_VALUES

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── rows recorded live ─────────────────────────────────────────────────────────

# Montgomery: an old colonial in Abington. One living unit, stucco (code 5).
_MONTCO_HOUSE = {"PARCEL": "300034228005", "PARCELTYPE": "BASE PARCEL",
                 "LIV_UNITS": "1", "LOCATION1": "1183 JERICHO RD", "LOC_UNITDE": " ",
                 "LOC_UNITNO": " ", "YEAR_BUILT": 1924, "SFLA": 1890,
                 "STORIES": "         2", "EXTWALL": "5"}
# Two units of one garden condominium, side by side, sharing one street address,
# and the association's common-area parcel under the same address.
_UNIT_109 = {"PARCEL": "300033973071", "PARCELTYPE": "CONDOMINIUM", "LIV_UNITS": "1",
             "LOCATION1": "2539 JENKINTOWN RD", "LOC_UNITDE": "CONDO",
             "LOC_UNITNO": "109", "YEAR_BUILT": 1975, "SFLA": 882,
             "STORIES": "         2", "EXTWALL": "2"}
_UNIT_106 = dict(_UNIT_109, PARCEL="300033973044", LOC_UNITNO="106")
_COMMON = {"PARCEL": "300033973099", "PARCELTYPE": "COMMON AREA", "LIV_UNITS": " ",
           "LOCATION1": "2539 JENKINTOWN RD", "LOC_UNITDE": " ", "LOC_UNITNO": " ",
           "YEAR_BUILT": 0, "SFLA": 0, "STORIES": " ", "EXTWALL": " "}

# York: a one-story bungalow in the city, and a two-family house.
_YORK_HOUSE = {"PIDN": "0100402002200", "PROPADR": "27 E SOUTH ST", "LUC": "101",
               "NUM_STORIE": 1.0, "RES_LIVING_AREA": 706, "YRBLT": 1890}
_YORK_TWO_FAMILY = {"PIDN": "0100301003900", "PROPADR": "48 E PRINCESS ST",
                    "LUC": "122", "NUM_STORIE": 2.0, "RES_LIVING_AREA": 2279,
                    "YRBLT": 1900}

# Northampton: note the inner spacing of the id and the trailing space of the
# address, both exactly as the county serves them.
_NORTHAMPTON_HOUSE = {"PARCEL_ID": "Q7NW3B 7  7", "LOCATION": "1429 KEILMAN AVE ",
                      "LUC": "110", "NUMBER_OF_CARDS": 1, "NUMBER_OF_STORIES": 1.0,
                      "SQFT_LIVING_AREA": 886, "RES_YEAR_BUILT": 1930}

# Cumberland: decoded words, and the year as a string.
_CUMBERLAND_HOUSE = {"PID": "9000058", "SITUS": "902 RIVER ROAD",
                     "LUC": "Residential 1 Family (101)", "DWELLING_T": "Single Family",
                     "YEAR_BLT": "1900", "SQFT": 1447,
                     "STORY_HEIG": "1.5 Stories (Ul 33% Of Lla)", "PRIMARY_EX": "Vinyl"}
# Two houses the roll files under one street address.
_SIMPSON_1922 = {"PID": "20000247", "SITUS": "529 W SIMPSON STREET",
                 "LUC": "Residential 1 Family (101)", "DWELLING_T": "Single Family",
                 "YEAR_BLT": "1922", "SQFT": 1549, "STORY_HEIG": "2 Stories",
                 "PRIMARY_EX": "Aluminum"}
_SIMPSON_1960 = dict(_SIMPSON_1922, PID="20000246", YEAR_BLT="1960", SQFT=1344,
                     STORY_HEIG="1 Story", PRIMARY_EX="Wood")
# A cell-tower lease, which carries a year and no dwelling.
_CELL_TOWER = {"PID": "520204", "SITUS": "2 BLUE MOUNTAIN TRAIL",
               "LUC": "Wireless SF On Leased Land (721)", "DWELLING_T": None,
               "YEAR_BLT": "1776", "SQFT": 0, "STORY_HEIG": None, "PRIMARY_EX": None}

_POINTS = {"42091": (40.10, -75.12), "42133": (39.957, -76.724),
           "42095": (40.63, -75.38), "42041": (40.25, -77.02)}


def _lookup(fips, exact, near=(), address=None, county_fips="same", seen=None,
            exceeded=False, county_answer=None):
    """Drive ``pa.lookup()`` over recorded rows through the real transport helpers.

    ``exact`` is what the point lands inside, ``near`` what an 80 m search finds.
    ``seen``, when passed, collects ``(url, params, deadline, read_slice)`` for
    every request, so a test can check what reaches the transport.
    """
    seen = [] if seen is None else seen

    def fake(url, params, deadline, read_slice=None):
        seen.append((url, params, deadline, read_slice))
        if url == pa.COUNTY_URL:
            return {"features": [{"attributes": {"GEOID": county_answer or fips}}]}
        rows = list(near) if params.get("distance") else list(exact)
        body = {"features": [{"attributes": a} for a in rows]}
        if exceeded:
            body["exceededTransferLimit"] = True
        return body

    # Stubbed BELOW get_json, so the real budget check and the real refusal of a
    # truncated page (exceededTransferLimit) both run.
    pa._lookup_cached.cache_clear()
    saved = _shared._fetch_json
    _shared._fetch_json = fake
    try:
        cf = fips if county_fips == "same" else county_fips
        return pa.lookup(*_POINTS[fips], address, county_fips=cf)
    finally:
        _shared._fetch_json = saved
        pa._lookup_cached.cache_clear()


# ── the ordinary house, in each county ─────────────────────────────────────────


def test_a_montgomery_house_reports_what_its_card_says():
    got = _lookup("42091", [_MONTCO_HOUSE], [_MONTCO_HOUSE],
                  address="1183 JERICHO RD, JENKINTOWN, PA, 19046")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft, got.stories) == (
        "300034228005", 1924, 1890.0, 2)
    assert got.construction is None, "stucco says nothing about the wall behind it"
    assert "Montgomery" in got.source


def test_a_york_house_reports_its_year_area_and_stories():
    got = _lookup("42133", [_YORK_HOUSE], [_YORK_HOUSE],
                  address="27 E SOUTH ST, YORK, PA, 17401")
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1890, 706.0, 1)
    assert got.construction is None, "York publishes no wall material"


def test_a_northampton_house_keeps_the_countys_own_parcel_id():
    """The id carries meaningful inner spacing ("Q7NW3B 7  7"). Collapsing it made
    every Northampton record in the first verification run carry an id that is
    not the county's — 29 of 39 resolved homes flagged as the wrong parcel."""
    got = _lookup("42095", [_NORTHAMPTON_HOUSE], [_NORTHAMPTON_HOUSE],
                  address="1429 KEILMAN AVE, BETHLEHEM, PA, 18017")
    assert got is not None
    assert got.parcel_id == "Q7NW3B 7  7"
    assert (got.year_built, got.sqft, got.stories) == (1930, 886.0, 1)


def test_a_cumberland_house_reads_its_text_columns():
    """The year is a string, the street type is spelled out ("RIVER ROAD"), the
    wall is a word — and "1.5 Stories (Ul 33% Of Lla)" has no whole-number
    reading."""
    got = _lookup("42041", [_CUMBERLAND_HOUSE], [_CUMBERLAND_HOUSE],
                  address="902 RIVER RD, MARYSVILLE, PA, 17053")
    assert got is not None
    assert (got.year_built, got.sqft, got.construction) == (1900, 1447.0, "vinyl")
    assert got.stories is None


def test_an_off_parcel_geocode_is_confirmed_by_address_in_the_buffer():
    neighbor = dict(_MONTCO_HOUSE, PARCEL="300034228006", LOCATION1="1185 JERICHO RD")
    got = _lookup("42091", [neighbor], [neighbor, _MONTCO_HOUSE],
                  address="1183 JERICHO RD, JENKINTOWN, PA, 19046")
    assert got is not None and got.parcel_id == "300034228005"


# ── condominiums: side-by-side units ───────────────────────────────────────────


def test_a_condominium_unit_under_the_point_is_not_the_readers_without_a_unit():
    """Recorded live: a point inside 2539 Jenkintown Rd returned exactly ONE unit
    polygon. Containment with one candidate whose address agrees is normally the
    strongest answer there is — and here it names an arbitrary unit."""
    got = _lookup("42091", [_UNIT_106], [_UNIT_106, _UNIT_109, _COMMON],
                  address="2539 JENKINTOWN RD, GLENSIDE, PA, 19038")
    assert got is None


def test_a_typed_unit_picks_its_own_unit_not_the_one_under_the_point():
    got = _lookup("42091", [_UNIT_106], [_UNIT_106, _UNIT_109, _COMMON],
                  address="2539 JENKINTOWN RD #109, GLENSIDE, PA, 19038")
    assert got is not None and got.parcel_id == "300033973071"
    assert got.year_built == 1975
    assert got.sqft == 882.0, "the unit's own living area, from its own card"


def test_a_condominium_units_stories_are_the_buildings_and_are_refused():
    """The county's record page for #109 reads "Condo Level 1 … Number of Stories
    2": STORIES on a unit is the building's height, not the home's."""
    got = _lookup("42091", [_UNIT_109], [_UNIT_109, _UNIT_106],
                  address="2539 JENKINTOWN RD #109, GLENSIDE, PA, 19038")
    assert got is not None and got.stories is None


def test_the_common_area_under_the_buildings_address_does_not_block_the_unit():
    """Guards the test above from passing for the wrong reason, and pins the rule
    that makes it pass: the association's parcel carries the building's address,
    no unit and no facts, so it cannot be anybody's unit. Give it a year and it
    becomes a candidate — and the unit is refused as ambiguous."""
    with_facts = dict(_COMMON, LIV_UNITS="1", YEAR_BUILT=1975)
    got = _lookup("42091", [_UNIT_106], [_UNIT_106, _UNIT_109, with_facts],
                  address="2539 JENKINTOWN RD #109, GLENSIDE, PA, 19038")
    assert got is None


def test_a_reader_who_types_a_unit_for_a_house_filed_as_one_parcel_still_matches():
    """"Apt 2" at a duplex the county files as one parcel: the parcel names no
    unit, so it could be the reader's, and its year is the building's."""
    duplex = dict(_MONTCO_HOUSE, LIV_UNITS="2")
    got = _lookup("42091", [duplex], [duplex],
                  address="1183 JERICHO RD #2, JENKINTOWN, PA, 19046")
    assert got is not None and got.year_built == 1924 and got.sqft is None


def test_a_typed_unit_that_matches_no_parcel_is_refused():
    got = _lookup("42091", [_UNIT_106], [_UNIT_106, _UNIT_109],
                  address="2539 JENKINTOWN RD #110, GLENSIDE, PA, 19038")
    assert got is None


def test_a_unit_without_an_address_is_refused():
    """select_parcel accepts a sole containing parcel when there is no address to
    confirm against. For a unit that is exactly the arbitrary pick."""
    assert _lookup("42091", [_UNIT_109], address=None) is None
    assert _lookup("42091", [_MONTCO_HOUSE], address=None) is not None


def test_two_parcels_claiming_the_typed_unit_are_refused():
    twin = dict(_UNIT_109, PARCEL="300033973080", LOC_UNITDE="BLDG 2")
    got = _lookup("42091", [_UNIT_109], [_UNIT_109, twin],
                  address="2539 JENKINTOWN RD #109, GLENSIDE, PA, 19038")
    assert got is None


def test_unit_spellings_compare_alike_but_leading_zeros_do_not():
    assert pa._norm_unit("UNIT B") == pa._norm_unit("b") == "B"
    assert pa._norm_unit("#3-B") == "3B"
    assert pa._norm_unit("   ") is None
    assert pa._norm_unit("01") != pa._norm_unit("1")


def test_a_city_starting_with_ste_is_not_a_unit():
    """The shared unit pattern lets "ste" run into the unit with no separator, so
    the geocoder's "147 LANTERN LN, STEWARTSTOWN, PA" read as unit "WARTSTOWN" in
    this adapter's verification run. A phantom unit refuses every condominium in
    the town; this adapter requires the separator."""
    assert pa._unit_of("147 LANTERN LN, STEWARTSTOWN, PA, 17363") is None
    assert pa._unit_of("100 N STEVENS") is None
    assert pa._unit_of("2539 JENKINTOWN RD #109, GLENSIDE, PA") == "109"
    assert pa._unit_of("2720 LINDEN ST UNIT 5 ") == "5"
    assert pa._unit_of("5 MAIN ST STE 4") == "4"


def test_a_northampton_unit_written_into_the_address_is_matched():
    unit5 = dict(_NORTHAMPTON_HOUSE, PARCEL_ID="N6NE2  2  16",
                 LOCATION="2720 LINDEN ST UNIT 5 ", LUC="151", SQFT_LIVING_AREA=1646,
                 RES_YEAR_BUILT=1989)
    unit2 = dict(unit5, PARCEL_ID="N6NE2  2  13", LOCATION="2720 LINDEN ST UNIT 2 ")
    got = _lookup("42095", [unit2], [unit2, unit5],
                  address="2720 LINDEN ST #5, BETHLEHEM, PA, 18017")
    assert got is not None and got.parcel_id == "N6NE2  2  16"
    assert got.stories is None
    assert _lookup("42095", [unit2], [unit2, unit5],
                   address="2720 LINDEN ST, BETHLEHEM, PA, 18017") is None


# ── one address, two houses ────────────────────────────────────────────────────


def test_one_street_address_on_two_houses_is_refused():
    """Recorded live, and the one wrong parcel the first verification run found:
    the roll files a 1922 house (1.05 acres) and a 1960 house (0.41) both as "529
    W SIMPSON STREET". The geocode landed inside the 1960 one, the address agreed,
    and select_parcel confirmed it — while the reader's home was the other."""
    got = _lookup("42041", [_SIMPSON_1960], [_SIMPSON_1960, _SIMPSON_1922],
                  address="529 W SIMPSON ST, MECHANICSBURG, PA, 17055")
    assert got is None


def test_a_vacant_lot_sharing_the_houses_number_is_not_a_rival():
    """A side lot that carries the house's number and reports nothing — no year,
    no area — cannot be confused with an answer, and refusing on it would cost
    every house that owns its neighboring lot."""
    lot = dict(_SIMPSON_1922, PID="20000248", LUC="Residential Vacant Land (100)",
               DWELLING_T=None, YEAR_BLT=None, SQFT=0, STORY_HEIG=None, PRIMARY_EX=None)
    got = _lookup("42041", [_SIMPSON_1960], [_SIMPSON_1960, lot],
                  address="529 W SIMPSON ST, MECHANICSBURG, PA, 17055")
    assert got is not None and got.year_built == 1960


def test_a_multipart_parcel_returned_twice_is_one_parcel():
    """Montgomery's 370004317668 and Northampton's "R7     22 19" each come back
    once per polygon part, field for field identical."""
    got = _lookup("42095", [_NORTHAMPTON_HOUSE, dict(_NORTHAMPTON_HOUSE)],
                  [_NORTHAMPTON_HOUSE, dict(_NORTHAMPTON_HOUSE)],
                  address="1429 KEILMAN AVE, BETHLEHEM, PA, 18017")
    assert got is not None and got.year_built == 1930


def test_rows_of_one_parcel_that_disagree_are_not_offered():
    broken = dict(_NORTHAMPTON_HOUSE, RES_YEAR_BUILT=1975)
    assert _lookup("42095", [_NORTHAMPTON_HOUSE, broken],
                   address="1429 KEILMAN AVE, BETHLEHEM, PA, 18017") is None


def test_a_row_with_no_parcel_id_is_a_record_of_nothing():
    blank = dict(_YORK_HOUSE, PIDN=" ", PROPADR=" ")
    got = _lookup("42133", [blank, _YORK_HOUSE], [blank, _YORK_HOUSE],
                  address="27 E SOUTH ST, YORK, PA, 17401")
    assert got is not None and got.parcel_id == "0100402002200"


# ── one dwelling, or the area is refused ───────────────────────────────────────


def test_montgomery_two_living_units_refuse_area_and_stories_and_keep_the_year():
    duplex = dict(_MONTCO_HOUSE, LIV_UNITS="2")
    got = _lookup("42091", [duplex], [duplex], address="1183 JERICHO RD, PA 19046")
    assert got is not None and got.year_built == 1924
    assert got.sqft is None and got.stories is None


def test_york_two_family_refuses_area_and_stories():
    got = _lookup("42133", [_YORK_TWO_FAMILY], [_YORK_TWO_FAMILY],
                  address="48 E PRINCESS ST, YORK, PA, 17403")
    assert got is not None and got.year_built == 1900
    assert got.sqft is None and got.stories is None


def test_northampton_second_card_refuses_area_and_keeps_the_year():
    two = dict(_NORTHAMPTON_HOUSE, NUMBER_OF_CARDS=2)
    got = _lookup("42095", [two], [two], address="1429 KEILMAN AVE, PA 18017")
    assert got is not None and got.year_built == 1930
    assert got.sqft is None and got.stories is None


def test_northampton_two_to_four_family_refuses_area():
    multi = dict(_NORTHAMPTON_HOUSE, LUC="120")
    got = _lookup("42095", [multi], [multi], address="1429 KEILMAN AVE, PA 18017")
    assert got is not None and got.sqft is None


def test_cumberland_half_double_is_one_home_only_on_a_one_family_parcel():
    """"Duplex Half (Two Family)" under LUC 101 is one side of a twin on its own
    parcel; under 102 the parcel is coded two-family, and the area may be both."""
    half = dict(_SIMPSON_1922, DWELLING_T="Duplex Half (Two Family)")
    got = _lookup("42041", [half], [half], address="529 W SIMPSON ST, PA 17055")
    assert got is not None and got.sqft == 1549.0
    two = dict(half, LUC="Residential 2 Family (102)")
    got = _lookup("42041", [two], [two], address="529 W SIMPSON ST, PA 17055")
    assert got is not None and got.sqft is None and got.year_built == 1922
    apartments = dict(_SIMPSON_1922, DWELLING_T="Two Or Three Apartments")
    got = _lookup("42041", [apartments], [apartments], address="529 W SIMPSON ST, PA 17055")
    assert got is not None and got.sqft is None


# ── nobody lives here ──────────────────────────────────────────────────────────


def test_montgomery_zero_living_units_reports_nothing():
    shop = dict(_MONTCO_HOUSE, LIV_UNITS="0")
    assert _lookup("42091", [shop], [shop], address="1183 JERICHO RD, PA 19046") is None


def test_montgomery_silence_about_living_units_is_not_a_refusal():
    silent = dict(_MONTCO_HOUSE, LIV_UNITS=" ")
    got = _lookup("42091", [silent], [silent], address="1183 JERICHO RD, PA 19046")
    assert got is not None and got.year_built == 1924
    assert got.sqft is None, "the area still needs the count it rests on"


def test_a_common_area_reports_only_where_a_living_unit_is_recorded():
    clubhouse = dict(_COMMON, LOCATION1="100 WESTMINSTER PL", YEAR_BUILT=1997,
                     SFLA=800, STORIES="         1", EXTWALL="1")
    assert _lookup("42091", [clubhouse], [clubhouse],
                   address="100 WESTMINSTER PL, PA 19002") is None
    house = dict(clubhouse, LIV_UNITS="1")
    assert _lookup("42091", [house], [house],
                   address="100 WESTMINSTER PL, PA 19002") is not None


def test_york_vacant_and_common_codes_report_nothing():
    for luc in ("100", "124", "130", "150"):
        row = dict(_YORK_HOUSE, LUC=luc)
        assert _lookup("42133", [row], [row], address="27 E SOUTH ST, PA 17401") is None, luc


def test_northampton_auxiliary_improvement_reports_nothing():
    row = dict(_NORTHAMPTON_HOUSE, LUC="180")
    assert _lookup("42095", [row], [row], address="1429 KEILMAN AVE, PA 18017") is None


def test_a_cumberland_commercial_building_year_is_not_a_homes():
    """Cumberland's YEAR_BLT is not a residential card's alone: an office or
    warehouse with no dwelling type carries one too."""
    office = dict(_CUMBERLAND_HOUSE, LUC="Office Building Low Rise (1-4) (353)",
                  DWELLING_T=None, YEAR_BLT="1985", PRIMARY_EX="Brick")
    assert _lookup("42041", [office], [office], address="902 RIVER RD, PA 17053") is None
    garden = dict(office, LUC="Apartment Garden-3 Sty & Under (211)")
    got = _lookup("42041", [garden], [garden], address="902 RIVER RD, PA 17053")
    assert got is not None and got.year_built == 1985, "an apartment building is homes"
    assert got.sqft is None


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup("42091", [dict(_MONTCO_HOUSE, YEAR_BUILT=0)],
                  [dict(_MONTCO_HOUSE, YEAR_BUILT=0)], address="1183 JERICHO RD, PA 19046")
    assert got is not None and got.year_built is None
    assert got.sqft == 1890.0, "the area survives; only the year is missing"


def test_northampton_reads_res_year_built_and_never_requests_year_built():
    """YEAR_BUILT is in Northampton's schema and empty on all 123,361 parcels."""
    fields = pa.NORTHAMPTON.fields.split(",")
    assert "RES_YEAR_BUILT" in fields and "YEAR_BUILT" not in fields
    assert "COM_YEAR_BUILT" not in fields


def test_cumberland_text_years_and_the_placeholder():
    for raw, want in (("1922", 1922), (" ", None), ("", None), (None, None),
                      ("998", None), ("1776", None), ("1775", 1775)):
        row = dict(_SIMPSON_1922, YEAR_BLT=raw)
        got = _lookup("42041", [row], [row], address="529 W SIMPSON ST, PA 17055")
        assert got is not None and got.year_built == want, raw
    tower = _lookup("42041", [_CELL_TOWER], [_CELL_TOWER],
                    address="2 BLUE MOUNTAIN TRL, PA 17013")
    assert tower is None


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    at = _lookup("42133", [dict(_YORK_HOUSE, YRBLT=EARLIEST_PLAUSIBLE_YEAR)],
                 [dict(_YORK_HOUSE, YRBLT=EARLIEST_PLAUSIBLE_YEAR)],
                 address="27 E SOUTH ST, PA 17401")
    assert at is not None and at.year_built == EARLIEST_PLAUSIBLE_YEAR
    below = _lookup("42133", [dict(_YORK_HOUSE, YRBLT=EARLIEST_PLAUSIBLE_YEAR - 1)],
                    [dict(_YORK_HOUSE, YRBLT=EARLIEST_PLAUSIBLE_YEAR - 1)],
                    address="27 E SOUTH ST, PA 17401")
    assert below is not None and below.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_YORK_HOUSE, YRBLT=None, RES_LIVING_AREA=None, NUM_STORIE=None)
    assert _lookup("42133", [empty], [empty], address="27 E SOUTH ST, PA 17401") is None


# ── stories ────────────────────────────────────────────────────────────────────


def test_york_stories_need_the_land_use_and_the_count_to_agree():
    """LUC 101 is "One Story House"; NUM_STORIE agrees on 45,443 of 45,495."""
    disagree = dict(_YORK_HOUSE, NUM_STORIE=2.0)
    got = _lookup("42133", [disagree], [disagree], address="27 E SOUTH ST, PA 17401")
    assert got is not None and got.stories is None and got.sqft == 706.0
    split = dict(_YORK_HOUSE, LUC="106")
    got = _lookup("42133", [split], [split], address="27 E SOUTH ST, PA 17401")
    assert got is not None and got.stories is None
    row = dict(_YORK_HOUSE, LUC="108", NUM_STORIE=3.0)
    got = _lookup("42133", [row], [row], address="27 E SOUTH ST, PA 17401")
    assert got is not None and got.stories == 3


def test_half_stories_and_split_levels_have_no_whole_number_reading():
    for raw in ("       1.5", "       2.5"):
        row = dict(_MONTCO_HOUSE, STORIES=raw)
        got = _lookup("42091", [row], [row], address="1183 JERICHO RD, PA 19046")
        assert got is not None and got.stories is None, raw
    for raw, want in (("Split-Level", None), ("Bi-Level", None), ("2 Stories", 2),
                      ("1 Story", 1), ("2.5 Stories", None)):
        row = dict(_SIMPSON_1922, STORY_HEIG=raw)
        got = _lookup("42041", [row], [row], address="529 W SIMPSON ST, PA 17055")
        assert got is not None and got.stories == want, raw


# ── wall material ──────────────────────────────────────────────────────────────


def test_montgomery_wall_codes_translate_only_where_the_word_names_a_structure():
    want = {"1": "frame", "2": "brick", "3": None, "4": "block", "5": None,
            "6": "frame", "7": "stone", "8": "frame", "9": None, " ": None, "X": None}
    for code, expected in want.items():
        row = dict(_MONTCO_HOUSE, EXTWALL=code)
        got = _lookup("42091", [row], [row], address="1183 JERICHO RD, PA 19046")
        assert got is not None and got.construction == expected, code


def test_cumberland_wall_words_translate_only_where_unambiguous():
    for raw, expected in (("Vinyl", "vinyl"), ("Brick", "brick"), ("Aluminum", "frame"),
                          ("Stone/Masonry", None), ("Stucco", None),
                          ("Concrete/Block", None), ("Log", None), ("Other", None),
                          ("No Value/Na", None), (None, None)):
        row = dict(_SIMPSON_1922, PRIMARY_EX=raw)
        got = _lookup("42041", [row], [row], address="529 W SIMPSON ST, PA 17055")
        assert got is not None and got.construction == expected, raw


def test_every_translation_is_in_the_labels_vocabulary():
    for table in (pa._MONTGOMERY_WALL, pa._CUMBERLAND_WALL):
        assert set(table.values()) <= CONSTRUCTION_VALUES


def test_no_condition_or_foundation_is_ever_reported():
    got = _lookup("42091", [_MONTCO_HOUSE], [_MONTCO_HOUSE],
                  address="1183 JERICHO RD, PA 19046")
    assert got is not None and got.condition is None and got.foundation is None
    assert "CONDITION" not in pa.MONTGOMERY.fields.split(",")


# ── privacy: the field lists ───────────────────────────────────────────────────


def test_the_field_lists_are_explicit_and_carry_nothing_private():
    private = {"*", "OWN1", "OWN2", "CAREOF", "ADDR1", "ADDR2", "ADDR3", "OWNER_FULL",
               "OWN_NAME1", "OWN_NAME2", "MAIL_ADDR_FULL", "MAIL_ADDR1", "PREV_OWNER",
               "OWNERS_NAME_1", "OWNERS_NAME_2", "MAIL_ADDRESS_1", "OWNERS_HIDENAME",
               "OWNER", "SALEPRICE", "SALEDATE", "SALE_PRICE", "SALE_DATE", "PRICE",
               "SALEDT", "CONSIDERAT", "TOTAL_APPR", "APRTOTAL", "TOTAL_VAL"}
    for county in pa.COUNTIES.values():
        fields = set(county.fields.split(","))
        assert not fields & private, (county.name, fields & private)


def test_the_requested_fields_are_what_reaches_the_service():
    for fips, row, addr in (("42091", _MONTCO_HOUSE, "1183 JERICHO RD, PA 19046"),
                            ("42041", _CUMBERLAND_HOUSE, "902 RIVER RD, PA 17053")):
        seen = []
        _lookup(fips, [row], [row], address=addr, seen=seen)
        assert seen and all(p["outFields"] == pa.COUNTIES[fips].fields
                            for _, p, _, _ in seen)
        assert all(u == pa.COUNTIES[fips].url for u, _, _, _ in seen)


# ── the county list ────────────────────────────────────────────────────────────


def test_the_counties_match_the_repositorys_county_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)}
    assert pa.COUNTY_FIPS <= census
    assert pa.COUNTY_FIPS == {"42091", "42133", "42095", "42041"}
    assert all(f.startswith("42") for f in pa.COUNTY_FIPS)


def test_the_counties_other_modules_or_decisions_own_are_not_claimed():
    """Philadelphia (phl.py) and Allegheny (its own adapter) are served elsewhere;
    Berks's license forbids redistribution pending a product decision; Lehigh's
    only source stops at 2015 and is "Not to be sold"."""
    for fips in ("42101", "42003", "42011", "42077"):
        assert fips not in pa.COUNTY_FIPS, fips


def test_the_callers_county_picks_the_layer_and_skips_the_boundary_request():
    seen = []
    _lookup("42133", [_YORK_HOUSE], [_YORK_HOUSE], address="27 E SOUTH ST, PA 17401",
            seen=seen)
    assert seen and all(u == pa.YORK_URL for u, _, _, _ in seen)


def test_without_a_county_the_point_is_routed_by_census_counties():
    seen = []
    got = _lookup("42133", [_YORK_HOUSE], [_YORK_HOUSE], address="27 E SOUTH ST, PA 17401",
                  county_fips=None, seen=seen)
    assert got is not None and got.year_built == 1890
    assert seen[0][0] == pa.COUNTY_URL
    assert seen[0][1]["outFields"] == "GEOID"


def test_a_point_outside_every_layer_makes_no_request():
    seen = []

    def fake(url, params, deadline, read_slice=None):
        seen.append(url)
        return {"features": []}

    pa._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        assert pa.lookup(39.95, -75.16, "1 S PENN SQ, PHILADELPHIA, PA") is None  # Philadelphia
    finally:
        _shared.get_json = saved
        pa._lookup_cached.cache_clear()
    assert seen == []


def test_a_boundary_answer_outside_the_four_counties_is_no_answer():
    seen = []
    got = _lookup("42133", [_YORK_HOUSE], address="27 E SOUTH ST, PA 17401",
                  county_fips=None, county_answer="42001", seen=seen)
    assert got is None
    assert [u for u, _, _, _ in seen] == [pa.COUNTY_URL]


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert pa.LOOKUP_TIMEOUT + pa.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_every_request_gets_the_modules_slice_and_one_shared_deadline():
    seen = []
    started = time.monotonic()
    _lookup("42091", [_MONTCO_HOUSE], [_MONTCO_HOUSE], county_fips=None,
            address="1183 JERICHO RD, PA 19046", seen=seen)
    assert len(seen) == 3, "county, containment, the address-uniqueness buffer"
    assert all(s == pa.READ_SLICE_S for _, _, _, s in seen)
    assert len({d for _, _, d, _ in seen}) == 1, "each request was handed its own budget"
    assert abs(seen[0][2] - started - pa.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    pa._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert pa.lookup(*_POINTS["42091"], "1183 JERICHO RD, PA 19046", "42091") is None
        assert pa.lookup(*_POINTS["42091"], "1183 JERICHO RD, PA 19046") is None
    finally:
        _shared.get_json = saved
        pa._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer():
    assert _lookup("42091", [_MONTCO_HOUSE], [_MONTCO_HOUSE],
                   address="1183 JERICHO RD, PA 19046", exceeded=True) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup("42095", [], [], address="1429 KEILMAN AVE, PA 18017") is None
