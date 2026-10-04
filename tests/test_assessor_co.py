#!/usr/bin/env python3
"""The Colorado adapter — five Denver-metro assessors, two shapes, and their traps.

Nothing here touches the network. Each county's services are stubbed with row
shapes recorded from them live (2026-10-04), for the reason every adapter test
file gives: an adapter fails open on purpose, so a renamed column or a broken
match reads as "Colorado has no record here" and would never announce itself. A
test that called the real services would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Colorado's own:

1. **Denver writes the implicit "N"** of its north-half streets, which the Census
   matcher never writes; only that N is forgiven, never an S, E or W.
2. **Denver dates multi-unit homes on its commercial schedule**, and stacks every
   condominium unit — and the building's own project record — on one polygon.
3. **Three counties are two hops**, and their second hop lists every building:
   houses, garages, sheds, barns.
4. **Douglas writes no leading directional** where the matcher adds one.
5. **Boulder writes one parcel row per street address** of an account.
6. **Arapahoe is not claimed**: its terms reserve all rights.
7. **Adams needs its own clock**.

This file alone: ``pytest tests/test_assessor_co.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, co
from housing_label.enrich.assessor.base import (
    CONDITION_VALUES, CONSTRUCTION_VALUES,
)

DENVER, JEFFERSON, ADAMS, DOUGLAS, BOULDER = "08031", "08059", "08001", "08035", "08013"

# ── rows recorded live, 2026-10-04 ─────────────────────────────────────────────


def _denver(**over):
    row = {"SCHEDNUM": None, "SITUS_ADDR_NBR": None, "SITUS_ADDR_NBR_SUFFIX": None,
           "SITUS_STR_NAME_PRE_DIR": None, "SITUS_STR_NAME_PRE_MOD": None,
           "SITUS_STR_NAME": None, "SITUS_STR_NAME_POST_TYPE": None,
           "SITUS_STR_NAME_POST_DIR": None, "SITUS_STR_NAME_POST_MOD": None,
           "SITUS_UNIT_IDENT": None, "D_CLASS_CN": None, "TOT_UNITS": None,
           "RES_ORIG_YEAR_BUILT": None, "COM_ORIG_YEAR_BUILT": None,
           "RES_ABOVE_GRADE_AREA": None}
    row.update(over)
    return row


# Denver: a single-family house, written with the implicit "N" the matcher omits.
_DEN_HOUSE = _denver(SCHEDNUM="0230325009000", SITUS_ADDR_NBR="2701",
                     SITUS_STR_NAME_PRE_DIR="N", SITUS_STR_NAME="WOLFF",
                     SITUS_STR_NAME_POST_TYPE="ST", D_CLASS_CN="SFR Grade B w/RK",
                     TOT_UNITS=1, RES_ORIG_YEAR_BUILT=1943, RES_ABOVE_GRADE_AREA=2102)
# Denver: a duplex, dated on the commercial schedule.
_DEN_DUPLEX = _denver(SCHEDNUM="0129103026000", SITUS_ADDR_NBR="7025",
                      SITUS_STR_NAME_PRE_DIR="E", SITUS_STR_NAME="33RD",
                      SITUS_STR_NAME_POST_TYPE="AVE", D_CLASS_CN="RESIDENTIAL-DUPLEX",
                      TOT_UNITS=2, COM_ORIG_YEAR_BUILT=1955)
# Denver: a shop, also dated on the commercial schedule.
_DEN_SHOP = _denver(SCHEDNUM="0004103004000", SITUS_ADDR_NBR="6691",
                    SITUS_STR_NAME_PRE_DIR="N", SITUS_STR_NAME="TOWER",
                    SITUS_STR_NAME_POST_TYPE="RD", D_CLASS_CN="COMMERCIAL-RETAIL",
                    COM_ORIG_YEAR_BUILT=2017)
# Denver: the common-elements parcel laid over a condominium complex.
_DEN_COMMON = _denver(SCHEDNUM="0003100118000", SITUS_ADDR_NBR="6663",
                      SITUS_STR_NAME_PRE_DIR="N", SITUS_STR_NAME="CEYLON",
                      SITUS_STR_NAME_POST_TYPE="ST",
                      D_CLASS_CN="VACANT LAND /GENERAL COMMON ELEMENTS", TOT_UNITS=0)
# Denver: 2525 S Dayton Way — one unit, and the building's own project record.
_DEN_UNIT = _denver(SCHEDNUM="0627401123123", SITUS_ADDR_NBR="2525",
                    SITUS_STR_NAME_PRE_DIR="S", SITUS_STR_NAME="DAYTON",
                    SITUS_STR_NAME_POST_TYPE="WAY", SITUS_UNIT_IDENT="2105",
                    D_CLASS_CN="RESIDENTIAL-CONDOMINIUM", TOT_UNITS=1,
                    RES_ORIG_YEAR_BUILT=1973, RES_ABOVE_GRADE_AREA=1200)
_DEN_PROJECT = _denver(SCHEDNUM="0627401001999", SITUS_ADDR_NBR="2525",
                       SITUS_STR_NAME_PRE_DIR="S", SITUS_STR_NAME="DAYTON",
                       SITUS_STR_NAME_POST_TYPE="WAY",
                       D_CLASS_CN="RESIDENTIAL-CONDOMINIUM", TOT_UNITS=148,
                       COM_ORIG_YEAR_BUILT=1973)
_DEN_OTHER_UNIT = dict(_DEN_UNIT, SCHEDNUM="0627401124124", SITUS_UNIT_IDENT="2106",
                       RES_ABOVE_GRADE_AREA=950)

# Jefferson: a brick ranch in Lakewood, the house number zero-padded.
_JEF_HOUSE = {"PIN": "49-254-10-093", "PRPSTRNUM": "02520", "PRPSTRDIR": "S",
              "PRPSTRNAM": "HARLAN", "PRPSTRTYP": "ST", "PRPSTRSFX": None,
              "PRPSTRUNT": None, "STTSTRC": "Single Family", "STTYRBLT": 1974,
              "STTGRSAREA": 2960, "STTTYPCNS": "BR - Brick-Good", "STTSTRC2": None,
              "STTYRBLT2": 0}
# Jefferson: a right-of-way polygon.
_JEF_ROW = {"PIN": "ROW", "PRPSTRNUM": None, "PRPSTRDIR": None, "PRPSTRNAM": None,
            "PRPSTRTYP": None, "PRPSTRSFX": None, "PRPSTRUNT": None, "STTSTRC": None,
            "STTYRBLT": None, "STTGRSAREA": None, "STTTYPCNS": None, "STTSTRC2": None,
            "STTYRBLT2": None}

# Adams: 7560 Yates St, Westminster, and its one improvement.
_ADA_PARCEL = {"PARCELNB": "0171931305004", "STREETNO": "7560", "STREETDIR": " ",
               "STREETNAME": "YATES", "STREETSUF": "ST", "STREETPOSTDIR": " ",
               "STREETALP": " "}
_ADA_HOUSE = {"parcelnb": "0171931305004", "bldgid": "1.00", "proptype": "Residential",
              "yrblt": 1965, "sf": 864, "exterior": "Frame Siding"}
_ADA_SHED = {"parcelnb": "0171931305004", "bldgid": "2.00", "proptype": "Out Building",
             "yrblt": 1990, "sf": 120, "exterior": "Metal Siding"}

# Douglas: 9230 Lark Sparrow Dr, Highlands Ranch, and its one improvement.
_DOU_PARCEL = {"STATE_PARCEL_NO": "223107207070", "ACCOUNT_NO": "R0393612",
               "ACCOUNT_TYPE_CODE": "Residential", "PARCEL_TYPE": "LOT",
               "ADDRESS_NUMBER": "9230", "ADDRESS_NUMBER_SUFFIX": "",
               "PRE_DIRECTION_CODE": "", "STREET_NAME": "LARK SPARROW",
               "STREET_TYPE_CODE": "DR", "POST_DIRECTION_CODE": "", "UNIT_NO": ""}
_DOU_HOUSE = {"ACCOUNT_NO": "R0393612", "BUILDING_ID": 1,
              "PROPERTY_TYPE_CODE": "Residential", "BUILT_YEAR": "1999",
              "IMPROVEMENT_SF": 2116, "NO_OF_UNIT": 1,
              "EXTERIOR_CONSTRUCTION_TYPE": "Frame Siding", "CONDITION": "Good",
              "etl_write_date": 1790989862000}

# Boulder: 315 Alder Ln and its two building rows — the house, and a detached
# garage filed under the account's single-family class with no finished area.
_BOU_PARCEL = {"AccountNo": "R0034667", "ParcelNo": "146123011016", "StrNum": 315,
               "StrPrx": None, "Street": "ALDER", "StrSuf": "LN", "StrUnit": None,
               "AcctType": "RESIDENTIAL", "CreatedDate": 1790878786000}
_BOU_HOUSE = {"AccountNo": "R0034667", "BuildingNumber": 1, "SectionNumber": 1,
              "ClassCodeDscr": "SINGLE FAM RES IMPROVEMENTS", "YearBuilt": 1968,
              "FinishedSqft": 3026}
_BOU_GARAGE = {"AccountNo": "R0034667", "BuildingNumber": 2, "SectionNumber": 2,
               "ClassCodeDscr": "SINGLE FAM RES IMPROVEMENTS", "YearBuilt": 2023,
               "FinishedSqft": 0}

#: Any point: which parcel a coordinate lands in is decided by the stubbed rows.
_POINT = (39.75, -105.0)


def _lookup(exact, near=(), address=None, county=DENVER, buildings=(), slices=None,
            params=None, urls=None, deadlines=None, county_answer=DENVER,
            exceeded=False):
    """Drive ``co.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` is what the point lands inside; ``near`` what a buffered search
    finds; ``buildings`` what the second hop returns. ``county`` is what the
    caller passes (None makes the adapter ask TIGERweb, which answers
    ``county_answer``). ``slices``, ``params``, ``urls`` and ``deadlines`` collect
    what each request was handed.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls
    deadlines = [] if deadlines is None else deadlines
    second = {c.buildings.url for c in co.COUNTIES.values() if c.buildings}

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        deadlines.append(deadline)
        if url == co.COUNTY_URL:
            feats = [{"attributes": {"GEOID": county_answer}}] if county_answer else []
            return {"features": feats}
        if exceeded:
            raise _shared.TruncatedResponse("truncated at the transfer limit")
        if url in second:
            rows = list(buildings)
        else:
            rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    co._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return co.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        co._lookup_cached.cache_clear()


# ── Denver ─────────────────────────────────────────────────────────────────────


def test_a_denver_house_reports_its_year_and_area():
    got = _lookup([_DEN_HOUSE], address="2701 WOLFF ST, DENVER, CO, 80212")
    assert got is not None
    assert (got.year_built, got.sqft, got.parcel_id) == (1943, 2102, "0230325009000")
    assert "CC BY 3.0" in got.source


def test_denvers_implicit_north_is_set_aside_against_the_matchers_spelling():
    """The roll writes "2701 N WOLFF ST"; the Census matcher writes "2701 WOLFF ST"
    for every north-half address. Without the rule the house is found and then
    refused for a letter the matcher never writes — across most of the city."""
    assert not _shared.same_address("2701 WOLFF ST", "2701 N WOLFF ST")
    got = _lookup([], near=[_DEN_HOUSE], address="2701 WOLFF ST, DENVER, CO, 80212")
    assert got is not None and got.year_built == 1943


def test_only_the_north_is_implicit():
    """A south-half address carries its S on both sides (typed "740 S PEARL ST"
    came back 2.8 km from "740 PEARL ST"), so a query with no directional names
    the north half — and never matches a roll S, E or W."""
    for d in ("S", "E", "W"):
        row = dict(_DEN_HOUSE, SITUS_STR_NAME_PRE_DIR=d)
        assert _lookup([], near=[row], address="2701 WOLFF ST, DENVER, CO") is None, d


def test_a_query_with_its_own_directional_is_not_relaxed():
    """The rule sets aside the ROLL's N for a query that has none. A query that
    says S is not compared with the N stripped off."""
    assert _lookup([], near=[_DEN_HOUSE], address="2701 S WOLFF ST, DENVER, CO") is None


def test_an_s_is_never_ignored_in_denver():
    """The N is a documented local convention — Denver's roll writes it on
    north-half streets, and USPS and the Census matcher never do. The S is
    written by everyone, so an S on one side only is a different house: a roll
    with no directional never matches a query's S, in containment or buffer."""
    bare = dict(_DEN_HOUSE, SITUS_STR_NAME_PRE_DIR=None)
    for exact, near in (([bare], ()), ((), [bare])):
        assert _lookup(exact, near=near, address="2701 S WOLFF ST, DENVER, CO") is None
    south = dict(_DEN_HOUSE, SITUS_STR_NAME_PRE_DIR="S")
    got = _lookup([south], address="2701 S WOLFF ST, DENVER, CO")
    assert got is not None and got.year_built == 1943, "an S on both sides agrees"


def test_the_implicit_north_rule_is_denvers_alone():
    for fips, cfg in co.COUNTIES.items():
        assert cfg.implicit_north == (fips == DENVER), fips


def test_a_duplex_is_dated_on_the_commercial_schedule():
    """2,767 of Denver's 2,776 duplexes carry their year only in
    COM_ORIG_YEAR_BUILT. Reading RES alone would lose every multi-unit home."""
    got = _lookup([_DEN_DUPLEX], address="7025 E 33RD AVE, DENVER, CO")
    assert got is not None and got.year_built == 1955
    assert got.sqft is None, "two dwellings: the area is not one home's"


def test_the_commercial_year_on_a_shop_is_the_shops():
    assert _lookup([_DEN_SHOP], address="6691 TOWER RD, DENVER, CO") is None


def test_a_recorded_zero_dwellings_refuses_the_year():
    """TOT_UNITS 0 is the assessor saying no dwelling stands here."""
    zero = dict(_DEN_HOUSE, TOT_UNITS=0)
    assert _lookup([zero], address="2701 WOLFF ST, DENVER, CO") is None


def test_a_missing_unit_count_is_silence_not_zero():
    silent = dict(_DEN_HOUSE, TOT_UNITS=None)
    got = _lookup([silent], address="2701 WOLFF ST, DENVER, CO")
    assert got is not None and got.year_built == 1943
    assert got.sqft is None, "the area needs the count it is built on"


def test_a_single_family_parcel_with_two_units_keeps_its_year_not_its_area():
    """2,137 SFR parcels record two units (a carriage house)."""
    two = dict(_DEN_HOUSE, TOT_UNITS=2)
    got = _lookup([two], address="2701 WOLFF ST, DENVER, CO")
    assert got is not None and got.year_built == 1943 and got.sqft is None


def test_the_common_elements_parcel_does_not_make_the_house_ambiguous():
    """The "GENERAL COMMON ELEMENTS" parcel is laid over and around condominium
    buildings. As a candidate it would make every home under it ambiguous."""
    got = _lookup([_DEN_HOUSE, _DEN_COMMON], address="2701 WOLFF ST, DENVER, CO")
    assert got is not None and got.year_built == 1943


def test_a_typed_unit_picks_its_record_and_sets_the_project_record_aside():
    """2525 S Dayton Way stacks 148 units on one polygon and files the building
    once more, unitless, as the project. Before the rule every unit in it read
    as ambiguous."""
    stack = [_DEN_PROJECT, _DEN_UNIT, _DEN_OTHER_UNIT]
    got = _lookup(stack, near=stack, address="2525 S DAYTON WAY #2105, DENVER, CO")
    assert got is not None
    assert got.parcel_id == "0627401123123" and got.year_built == 1973


def test_a_condominium_unit_never_reports_its_area():
    """One dwelling in a building of several: refused, as every adapter does."""
    got = _lookup([_DEN_UNIT], near=[_DEN_UNIT],
                  address="2525 S DAYTON WAY #2105, DENVER, CO")
    assert got is not None and got.sqft is None


def test_with_no_unit_typed_the_building_answers_for_its_building():
    """No unit record can be chosen without a unit — they are left out of the
    containment answer — but the project record IS the building, and its year is
    every unit's. It answers with that year and no area."""
    stack = [_DEN_PROJECT, _DEN_UNIT, _DEN_OTHER_UNIT]
    got = _lookup(stack, near=stack, address="2525 S DAYTON WAY, DENVER, CO")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("0627401001999", 1973, None)


def test_a_stack_of_units_alone_with_no_unit_typed_is_refused():
    stack = [_DEN_UNIT, _DEN_OTHER_UNIT]
    assert _lookup(stack, near=stack, address="2525 S DAYTON WAY, DENVER, CO") is None


def test_a_typed_unit_never_lands_on_another_unit():
    got = _lookup([_DEN_OTHER_UNIT], near=[_DEN_OTHER_UNIT],
                  address="2525 S DAYTON WAY #2105, DENVER, CO")
    assert got is None


def test_the_buffered_query_asks_only_for_the_querys_house_number():
    """710 S Alton Way has more than 2,000 unit records within 80 m; the unfiltered
    page came back truncated. A row with another number can never confirm, so
    leaving it out cannot change the answer. Containment is never filtered."""
    params = []
    _lookup([], near=[_DEN_HOUSE], address="2701 WOLFF ST, DENVER, CO", params=params)
    contain, buffer = params[0], params[1]
    assert "where" not in contain or not contain["where"]
    assert buffer["where"] == "SITUS_ADDR_NBR='2701'"


def test_jeffersons_number_filter_matches_its_zero_padding():
    assert co.COUNTIES[JEFFERSON].number_where("6390") == "PRPSTRNUM IN ('6390','06390')"
    assert co.COUNTIES[BOULDER].number_where("315") == "StrNum=315"


# ── Jefferson ──────────────────────────────────────────────────────────────────


def test_a_jefferson_house_reports_year_area_and_wall():
    got = _lookup([_JEF_HOUSE], address="2520 S HARLAN ST, LAKEWOOD, CO, 80227",
                  county=JEFFERSON)
    assert got is not None
    assert (got.year_built, got.sqft, got.construction) == (1974, 2960, "brick")
    assert got.parcel_id == "49-254-10-093"


def test_jeffersons_padded_house_number_still_confirms():
    """PRPSTRNUM is "02520"; the matcher writes 2520."""
    assert co._jefferson_street(_JEF_HOUSE) == "2520 S HARLAN ST"


def test_a_right_of_way_polygon_is_not_a_candidate():
    got = _lookup([_JEF_ROW, _JEF_HOUSE], address="2520 S HARLAN ST, LAKEWOOD, CO",
                  county=JEFFERSON)
    assert got is not None and got.year_built == 1974


def test_a_jefferson_shop_reports_nothing():
    shop = dict(_JEF_HOUSE, STTSTRC="General Retail")
    assert _lookup([shop], address="2520 S HARLAN ST, LAKEWOOD, CO",
                   county=JEFFERSON) is None


def test_two_dwellings_of_different_years_have_no_single_year():
    """859 single-family parcels carry a second dwelling structure."""
    rear = dict(_JEF_HOUSE, STTSTRC2="Single Family", STTYRBLT2=1925)
    assert _lookup([rear], address="2520 S HARLAN ST, LAKEWOOD, CO",
                   county=JEFFERSON) is None
    same = dict(_JEF_HOUSE, STTSTRC2="Single Family", STTYRBLT2=1974)
    got = _lookup([same], address="2520 S HARLAN ST, LAKEWOOD, CO", county=JEFFERSON)
    assert got is not None and got.year_built == 1974
    assert got.sqft is None and got.construction is None


def test_a_townhome_reports_its_year_not_its_area():
    town = dict(_JEF_HOUSE, STTSTRC="Townhomes", PRPSTRUNT="119")
    got = _lookup([], near=[town], address="2520 S HARLAN ST #119, LAKEWOOD, CO",
                  county=JEFFERSON)
    assert got is not None and got.year_built == 1974 and got.sqft is None


def test_jeffersons_unit_count_is_never_read():
    """STTNBRUNT is 0 on 207,333 of 208,875 parcels with a year, houses included:
    a count that says zero for everything is not a count."""
    assert "STTNBRUNT" not in co.COUNTIES[JEFFERSON].fields


# ── the two-hop counties ───────────────────────────────────────────────────────


def test_an_adams_house_is_two_requests_keyed_by_its_parcel_number():
    urls, params = [], []
    got = _lookup([_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO, 80030",
                  county=ADAMS, buildings=[_ADA_HOUSE, _ADA_SHED], urls=urls,
                  params=params)
    assert got is not None
    assert (got.year_built, got.sqft, got.construction) == (1965, 864, "frame")
    assert urls == [co.ADAMS_URL, co.ADAMS_IMPROVEMENTS_URL]
    assert params[1]["where"] == "parcelnb='0171931305004'"


def test_an_outbuilding_is_not_a_dwelling():
    """The shed's 1990 is not the house's year, and does not make it two homes."""
    got = _lookup([_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO",
                  county=ADAMS, buildings=[_ADA_SHED, _ADA_HOUSE])
    assert got is not None and got.year_built == 1965 and got.sqft == 864


def test_two_dwellings_of_different_years_on_one_record_have_no_year():
    second = dict(_ADA_HOUSE, bldgid="2.00", yrblt=2004, sf=600)
    assert _lookup([_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO",
                   county=ADAMS, buildings=[_ADA_HOUSE, second]) is None


def test_a_record_with_no_dwelling_reports_nothing():
    """A barn, a shop, a storage yard: the county saying nobody lives here."""
    assert _lookup([_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO",
                   county=ADAMS, buildings=[_ADA_SHED]) is None
    assert _lookup([_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO",
                   county=ADAMS, buildings=[]) is None


def test_an_adams_condominium_reports_its_year_not_its_area():
    condo_parcel = dict(_ADA_PARCEL, STREETALP="#A")
    condo = dict(_ADA_HOUSE, proptype="Condo")
    got = _lookup([], near=[condo_parcel], address="7560 YATES ST #A, WESTMINSTER, CO",
                  county=ADAMS, buildings=[condo])
    assert got is not None and got.year_built == 1965 and got.sqft is None


def test_a_join_key_that_is_not_a_key_is_never_sent():
    """The key goes into a where clause."""
    bad = dict(_ADA_PARCEL, PARCELNB="1' OR '1'='1")
    urls = []
    assert _lookup([bad], address="7560 YATES ST, WESTMINSTER, CO", county=ADAMS,
                   buildings=[_ADA_HOUSE], urls=urls) is None
    assert co.ADAMS_IMPROVEMENTS_URL not in urls


def test_a_douglas_house_reports_its_condition_and_dates_its_extract():
    got = _lookup([_DOU_PARCEL], address="9230 LARK SPARROW DR, HIGHLANDS RANCH, CO",
                  county=DOUGLAS, buildings=[_DOU_HOUSE])
    assert got is not None
    assert (got.year_built, got.sqft, got.construction, got.condition) == (
        1999, 2116, "frame", "good")
    assert "extract of 2026-" in got.data_vintage
    assert "CC BY-SA 4.0" in got.source


def test_douglas_refuses_a_directional_written_on_one_side_only():
    """Typed "8552 FORREST ST, Highlands Ranch" comes back "8552 S FORREST ST",
    and Douglas writes no leading directional on 120,758 of 131,089 residential
    parcels. Refused anyway, in containment and in the buffer: the Census matcher
    is measured to ignore, drop and swap directionals, so "100 W MAIN" and "100 E
    MAIN" can come back as one point, and a roll with no directional would be
    confirmed against whichever twin is near. Forgiving it rescued 5 of 36
    sampled Douglas homes and was removed all the same."""
    for exact, near in (([_DOU_PARCEL], ()), ((), [_DOU_PARCEL])):
        assert _lookup(exact, near=near,
                       address="9230 S LARK SPARROW DR, HIGHLANDS RANCH, CO",
                       county=DOUGLAS, buildings=[_DOU_HOUSE]) is None
    # ...and the other way round: the roll writes one, the query none.
    north = dict(_DOU_PARCEL, PRE_DIRECTION_CODE="N")
    assert _lookup([north], address="9230 LARK SPARROW DR, HIGHLANDS RANCH, CO",
                   county=DOUGLAS, buildings=[_DOU_HOUSE]) is None


def test_no_county_but_denver_relaxes_a_directional():
    """The module has one directional rule, Denver's documented implicit N."""
    assert not hasattr(co.County, "roll_omits_predir")
    for fips, cfg in co.COUNTIES.items():
        for query, roll in (("9230 S LARK SPARROW DR", "9230 LARK SPARROW DR"),
                            ("9230 LARK SPARROW DR", "9230 S LARK SPARROW DR"),
                            ("9230 LARK SPARROW DR", "9230 N LARK SPARROW DR")):
            relaxed = co._agrees(cfg, query, roll)
            expected = fips == DENVER and roll == "9230 N LARK SPARROW DR"
            assert relaxed == expected, (cfg.name, query, roll)


def test_the_matchers_dropped_directional_is_never_forgiven():
    """Typed "3569 W 89TH AVE" came back "3569 89TH AVE" in Adams — Utah's case,
    where the matcher ignores a typed directional and may sit on the twin."""
    west = dict(_ADA_PARCEL, STREETDIR="W")
    assert _lookup([], near=[west], address="7560 YATES ST, WESTMINSTER, CO",
                   county=ADAMS, buildings=[_ADA_HOUSE]) is None


def test_a_dwelling_type_that_records_no_dwelling_is_not_one():
    empty = dict(_DOU_HOUSE, NO_OF_UNIT=0)
    assert _lookup([_DOU_PARCEL], address="9230 LARK SPARROW DR, HIGHLANDS RANCH, CO",
                   county=DOUGLAS, buildings=[empty]) is None


def test_douglas_hoa_tracts_are_not_candidates():
    hoa = dict(_DOU_PARCEL, ACCOUNT_NO="R0999999", ACCOUNT_TYPE_CODE="HOA")
    got = _lookup([_DOU_PARCEL, hoa],
                  address="9230 LARK SPARROW DR, HIGHLANDS RANCH, CO",
                  county=DOUGLAS, buildings=[_DOU_HOUSE])
    assert got is not None and got.year_built == 1999


def test_a_boulder_garage_is_not_a_second_dwelling():
    """Boulder files sheds and garages under the account's single-family class,
    with zero finished area. Counted as dwellings, the 2023 garage would erase the
    house's 1968 and its area."""
    got = _lookup([_BOU_PARCEL], address="315 ALDER LN, LONGMONT, CO", county=BOULDER,
                  buildings=[_BOU_HOUSE, _BOU_GARAGE])
    assert got is not None and (got.year_built, got.sqft) == (1968, 3026)
    assert "parcel layer of 2026-" in got.data_vintage


def test_a_boulder_account_listed_under_two_addresses_matches_either():
    """One parcel row per street address of an account. Offered raw, 555 Main St,
    Louisville faced its own second row and was refused."""
    other = dict(_BOU_PARCEL, StrNum=317)
    for typed in ("315 ALDER LN, LONGMONT, CO", "317 ALDER LN, LONGMONT, CO"):
        got = _lookup([_BOU_PARCEL, other], address=typed, county=BOULDER,
                      buildings=[_BOU_HOUSE])
        assert got is not None and got.year_built == 1968, typed


def test_rows_of_one_record_that_disagree_beyond_the_address_are_not_offered():
    broken = dict(_BOU_PARCEL, AcctType="APARTMENT")
    assert _lookup([_BOU_PARCEL, broken], address="315 ALDER LN, LONGMONT, CO",
                   county=BOULDER, buildings=[_BOU_HOUSE]) is None


def test_land_only_accounts_are_not_candidates():
    land = dict(_BOU_PARCEL, AccountNo="R0999998", AcctType="VACANT LAND")
    got = _lookup([_BOU_PARCEL, land], address="315 ALDER LN, LONGMONT, CO",
                  county=BOULDER, buildings=[_BOU_HOUSE])
    assert got is not None and got.year_built == 1968


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_DEN_HOUSE, RES_ORIG_YEAR_BUILT=0)],
                  address="2701 WOLFF ST, DENVER, CO")
    assert got is not None and got.year_built is None and got.sqft == 2102
    assert _lookup([_DOU_PARCEL], address="9230 LARK SPARROW DR, HIGHLANDS RANCH, CO",
                   county=DOUGLAS, buildings=[dict(_DOU_HOUSE, BUILT_YEAR="0")]
                   ).year_built is None


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR, _valid_year
    floor = EARLIEST_PLAUSIBLE_YEAR
    at = _lookup([dict(_JEF_HOUSE, STTYRBLT=floor)], address="2520 S HARLAN ST, CO",
                 county=JEFFERSON)
    assert at is not None and at.year_built == floor and _valid_year(floor)
    below = _lookup([dict(_JEF_HOUSE, STTYRBLT=floor - 1)],
                    address="2520 S HARLAN ST, CO", county=JEFFERSON)
    assert below is not None and below.year_built is None


def test_a_record_that_contributes_nothing_is_not_an_answer():
    empty = dict(_DEN_HOUSE, RES_ORIG_YEAR_BUILT=None, RES_ABOVE_GRADE_AREA=None)
    assert _lookup([empty], address="2701 WOLFF ST, DENVER, CO") is None


# ── vocabulary ─────────────────────────────────────────────────────────────────


def test_unambiguous_walls_translate_and_ambiguous_ones_stay_empty():
    assert co._WALL["FRAME VINYL"] == "vinyl"
    assert co._WALL["FRAME BRICK VENEER"] == "brick-frame"
    for unmapped in ("FRAME MASONRY VENEER", "FRAME STONE VENEER", "LOG",
                     "METAL SIDING", "CONCRETE BLOCK"):
        assert unmapped not in co._WALL, unmapped
    combo = dict(_JEF_HOUSE, STTTYPCNS="FB - Combination-Good")
    got = _lookup([combo], address="2520 S HARLAN ST, CO", county=JEFFERSON)
    assert got is not None and got.construction is None
    veneer = dict(_ADA_HOUSE, exterior="Frame Masonry Veneer")
    got = _lookup([_ADA_PARCEL], address="7560 YATES ST, CO", county=ADAMS,
                  buildings=[veneer])
    assert got is not None and got.construction is None


def test_a_condition_between_two_grades_stays_empty():
    for raw in ("Very Good", "Badly Worn", "Worn Out"):
        got = _lookup([_DOU_PARCEL], address="9230 LARK SPARROW DR, CO",
                      county=DOUGLAS, buildings=[dict(_DOU_HOUSE, CONDITION=raw)])
        assert got is not None and got.condition is None, raw


def test_every_translation_is_in_the_labels_vocabulary():
    assert set(co._WALL.values()) <= CONSTRUCTION_VALUES
    assert set(co._JEFFERSON_WALL.values()) <= CONSTRUCTION_VALUES
    assert set(co._DOUGLAS_CONDITION.values()) <= CONDITION_VALUES


# ── what is requested ──────────────────────────────────────────────────────────

_PRIVATE = ("OWNER", "MAIL", "SALE", "PRICE", "VALUE", "NAME1", "CAREOF", "LEGAL",
            "TAXABLE", "ASSESSED", "APPRAISED")


def test_every_field_list_is_explicit_and_carries_nothing_private():
    for cfg in co.COUNTIES.values():
        lists = [cfg.fields] + ([cfg.buildings.fields] if cfg.buildings else [])
        for fields in lists:
            assert "*" not in fields, cfg.name
            for f in fields:
                assert not any(p in f.upper() for p in _PRIVATE), (cfg.name, f)


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([_ADA_PARCEL], address="7560 YATES ST, CO", county=ADAMS,
            buildings=[_ADA_HOUSE], params=params)
    assert params[0]["outFields"] == co.COUNTIES[ADAMS].out_fields
    assert params[-1]["outFields"] == ",".join(co.COUNTIES[ADAMS].buildings.fields)


def test_effective_and_remodel_years_are_never_requested():
    for cfg in co.COUNTIES.values():
        fields = cfg.fields + (cfg.buildings.fields if cfg.buildings else ())
        for f in fields:
            assert not any(w in f.upper() for w in ("EFF", "REMOD")), (cfg.name, f)


# ── which counties ─────────────────────────────────────────────────────────────


def test_every_claimed_county_is_a_real_colorado_county():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        colorado = {r["geoid"] for r in csv.DictReader(fh)
                    if r["geoid"].startswith("08") and len(r["geoid"]) == 5}
    assert len(colorado) == 64, f"expected 64 Colorado counties, got {len(colorado)}"
    assert co.COUNTY_FIPS <= colorado
    assert co.COUNTY_FIPS == {DENVER, JEFFERSON, ADAMS, DOUGLAS, BOULDER}


def test_the_counties_held_back_are_not_claimed():
    """Arapahoe reserves all rights ("furnished with all rights reserved"); Weld
    grants nothing and publishes points; Larimer publishes no year; El Paso was
    ruled out before. Claiming any would be a terms breach or an empty lookup."""
    for fips in ("08005", "08123", "08069", "08041"):
        assert fips not in co.COUNTY_FIPS, fips


def test_url_for_names_each_countys_own_publisher():
    for fips, cfg in co.COUNTIES.items():
        assert co.url_for(fips) == cfg.url
    assert co.url_for("08005") is None


def test_the_callers_county_picks_the_layer_and_skips_the_county_request():
    urls = []
    _lookup([_JEF_HOUSE], address="2520 S HARLAN ST, CO", county=JEFFERSON, urls=urls)
    assert co.COUNTY_URL not in urls and urls == [co.JEFFERSON_URL]


def test_without_a_county_the_point_is_asked_which_county_it_is_in():
    urls = []
    got = _lookup([_JEF_HOUSE], address="2520 S HARLAN ST, CO", county=None,
                  county_answer=JEFFERSON, urls=urls)
    assert got is not None and urls[0] == co.COUNTY_URL
    assert _lookup([_JEF_HOUSE], county=None, county_answer=None) is None


# ── the clock ──────────────────────────────────────────────────────────────────


def test_each_countys_requests_carry_its_own_read_slice():
    for fips, rows, buildings in ((DENVER, [_DEN_HOUSE], ()),
                                  (ADAMS, [_ADA_PARCEL], [_ADA_HOUSE])):
        slices = []
        _lookup(rows, county=fips, buildings=buildings, slices=slices)
        assert slices and all(s == co.COUNTIES[fips].read_slice for s in slices), fips
    assert co.COUNTIES[ADAMS].read_slice > _shared._READ_SLICE_S
    assert co.COUNTIES[DENVER].read_slice == _shared._READ_SLICE_S


def test_every_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    pairs = [(c.timeout, c.read_slice) for c in co.COUNTIES.values()]
    pairs.append((co.LOOKUP_TIMEOUT, co.READ_SLICE_S))
    for timeout, slice_ in pairs:
        assert timeout + slice_ < config.UPSTREAM_HOST_BUDGET, (timeout, slice_)
    assert co.COUNTIES[ADAMS].timeout > _shared.TIMEOUT, (
        "the slowest observed Adams lookup was 3.2 s across three requests")


def test_all_requests_of_a_lookup_share_one_clock_started_once():
    """Containment, buffer and second hop: one budget, not one each — and it is
    the county's own (Adams's five seconds, not the shared four)."""
    deadlines = []
    started = time.monotonic()
    _lookup([], near=[_ADA_PARCEL], address="7560 YATES ST, WESTMINSTER, CO",
            county=ADAMS, buildings=[_ADA_HOUSE], deadlines=deadlines)
    assert len(deadlines) == 3 and len(set(deadlines)) == 1
    assert abs((deadlines[0] - started) - co.COUNTIES[ADAMS].timeout) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    co._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert co.lookup(*_POINT, "2701 WOLFF ST, DENVER, CO", DENVER) is None
    finally:
        _shared.get_json = saved
        co._lookup_cached.cache_clear()


def test_a_truncated_page_fails_open():
    assert _lookup([_DEN_HOUSE], address="2701 WOLFF ST, DENVER, CO",
                   exceeded=True) is None


def test_a_second_hop_failure_fails_open():
    def half(url, request, deadline, read_slice=None):
        if url == co.ADAMS_IMPROVEMENTS_URL:
            raise TimeoutError("assessor lookup budget exhausted")
        return {"features": [{"attributes": _ADA_PARCEL}]}

    co._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = half
    try:
        assert co.lookup(*_POINT, "7560 YATES ST, CO", ADAMS) is None
    finally:
        _shared.get_json = saved
        co._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([], address="2701 WOLFF ST, DENVER, CO") is None


def test_two_houses_containing_the_point_are_ambiguous_and_refused():
    other = dict(_DEN_HOUSE, SCHEDNUM="0230325010000", SITUS_ADDR_NBR="2705")
    assert _lookup([_DEN_HOUSE, other]) is None
