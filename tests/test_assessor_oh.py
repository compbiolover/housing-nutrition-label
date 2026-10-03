#!/usr/bin/env python3
"""The Ohio adapter — nine county layers, nine schemas, one land-use vocabulary.

Nothing here touches the network. Each county's service is stubbed with row
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Ohio has no record here" and would never announce itself. A test that called the
real services would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Ohio's own:

1. **Cuyahoga's ``min_age``/``max_age`` are years**, not ages, and the parcel's
   dwellings can disagree about them.
2. **Duplicate rows**: Cuyahoga repeats identical rows of one parcel, and Lorain
   writes one row per street address of a parcel.
3. **Placeholders**: Cuyahoga's MULTI footprints, Summit's blank-address
   association parcels, and every county's common areas and garage parcels.
4. The **shared land-use codes** say which parcels are vacant land, and the only
   positive evidence of ONE home (510-515).
5. **Lorain's two land-use columns** disagree, and its situs runs into the city.
6. **Delaware's year** also dates shops; it publishes no parcel id at all.
7. Each county has its own **clock**, and Montgomery needs a longer one.

This file alone: ``pytest tests/test_assessor_oh.py``
"""

from __future__ import annotations

import csv
import inspect
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, oh

# ── rows recorded live, 2026-10-03 ─────────────────────────────────────────────

# Franklin: a single-family house in Columbus.
_FR_HOUSE = {"PARCELID": "010-012132", "SITEADDRESS": "232 S CENTRAL AVE",
             "CLASSCD": "510", "RESYRBLT": 1918, "RESFLRAREA_AG": 1182}
# Franklin: four units stacked in one building, all at one street address with
# the unit written bare after the street type. 553 = "CONDO 40+ RENTAL UNITS".
_FR_STACK = [
    {"PARCELID": f"590-31374{i}", "SITEADDRESS": f"5500 BERMUDA BAY DR 55001{u}",
     "CLASSCD": "553", "RESYRBLT": 1985, "RESFLRAREA_AG": 1090}
    for i, u in zip("6789", "ABCD")
]

# Cuyahoga: one parcel returned as four identical rows (7506 Ira Ave, Brooklyn).
_CUY_HOUSE = {"parcel_id": "43306050", "par_addr_all": "7506 IRA AVE, BROOKLYN, OH, 44144",
              "parcel_unit": None, "tax_luc": "5100", "res_bldg_count": 1,
              "min_age": 1952, "max_age": 1952, "total_res_liv_area": 1131,
              "max_res_heights": 1.5, "update_date": 1790922659000}
# Cuyahoga: a condominium complex's MULTI footprint — every field null.
_CUY_MULTI = {"parcel_id": None, "par_addr_all": None, "parcel_unit": None,
              "tax_luc": None, "res_bldg_count": None, "min_age": None,
              "max_age": None, "total_res_liv_area": None, "max_res_heights": None,
              "update_date": None}
# Cuyahoga: a two-family lot holding a 1900 house and a 2003 house.
_CUY_TWO_HOUSES = {"parcel_id": "00106004",
                   "par_addr_all": "10107 CLIFF DR, CLEVELAND, OH, 44102",
                   "parcel_unit": None, "tax_luc": "5200", "res_bldg_count": 2,
                   "min_age": 1900, "max_age": 2003, "total_res_liv_area": 7927,
                   "max_res_heights": 2.5, "update_date": 1790922659000}

# Summit: a house, and a homeowners'-association parcel laid over a condominium
# complex with a blank house number and no facts.
_SUM_HOUSE = {"parcelid": "2304654", "siteaddress": "1344  SWIGART CT ", "unit": None,
              "usecd": "510", "resyrblt": 1940, "resflrarea": 1380, "floorcount": 1}
_SUM_HOA = {"parcelid": "0406452", "siteaddress": "  LAKE POINTE DR ", "unit": None,
            "usecd": "550", "resyrblt": None, "resflrarea": None, "floorcount": None}

# Montgomery: qualified names, because the layer is a join.
_M = "SDE.WEB_CAMA."
_MONT_HOUSE = {"SDE.mc_parcel_polygon.TAXPINNO": "R72 12307 0032",
               _M + "PARLOC": "4060 DELPHOS AVE ", _M + "LUC": "510",
               _M + "DWEL_YRBLT": 1966.0, _M + "DWEL_SFLA": 1217.0,
               _M + "DWEL_STORIES": 1.0, _M + "DWEL_EXTWALL": "BRICK",
               _M + "CREATEDATE": 1790978414613}

# Delaware: a house, and a commercial building whose YRBUILT is the shop's.
_DEL_HOUSE = {"ADDR1": "4784 MOONEY RD", "CLASS": "510", "YRBUILT": 1986,
              "SQFT": 1374, "STORYHGT": 1}
_DEL_SHOP = {"ADDR1": "825 KINTNER PKWY", "CLASS": "400", "YRBUILT": 2021,
             "SQFT": 46200, "STORYHGT": 1}

# Butler: a house with an average CDU, and one rated "very good".
_BUT_HOUSE = {"PIN": "L5300009000120", "LOCATION": "1604 WICHITA DR", "LUC": "510",
              "YRBLT": 1964, "SFLA": 1175, "STORIES": 1, "CDU": "AV"}
_BUT_VG = {"PIN": "M5620268000023", "LOCATION": "7883 CHESTERSHIRE DR", "LUC": "510",
           "YRBLT": 1988, "SFLA": 8474, "STORIES": 2, "CDU": "VG"}

# Lorain: one parcel, two rows — one per street address of a double.
_LOR_DOUBLE = [
    {"PARCELID": "0300094112004", "SITEADDRESS": f"{n}   GROVE AVE  LORAIN, OH 44055",
     "USECD": "520", "CLASSCD": "520  ", "RESYRBLT": 1900, "RESFLRAREA": 2160}
    for n in (3237, 3235)
]
# Lorain: a single-family parcel with a second dwelling, "618 1/2".
_LOR_HALF = [
    {"PARCELID": "0624065101007", "SITEADDRESS": f"{n}  DEWEY AVE  ELYRIA, OH 44035",
     "USECD": "510", "CLASSCD": "510  ", "RESYRBLT": 1928, "RESFLRAREA": 528}
    for n in ("618 ", "618 1/2")
]
# Lorain: USECD says vacant, CLASSCD says single-family, and a 2021 year.
_LOR_SPLIT = {"PARCELID": "0100002101008",
              "SITEADDRESS": "4100   MENLO PARK LN  VERMILION, OH 44089",
              "USECD": "500", "CLASSCD": "510  ", "RESYRBLT": 2021, "RESFLRAREA": 1894}
_LOR_HOUSE = {"PARCELID": "0201006119022",
              "SITEADDRESS": "1142  W 12TH ST  LORAIN, OH 44052",
              "USECD": "510", "CLASSCD": "510  ", "RESYRBLT": 1900, "RESFLRAREA": 1368}

# The City of Columbus mirror: Licking's rows were copied 2024-05-06.
_LICKING = {"PARCELID": "001-000024-00.002", "SITEADDRESS": "7990 BENNER RD ",
            "CLASSCD": "510", "RESYRBLT": 2000, "SHP_UPLD_DATE": 1714979018000}
_FAIRFIELD = {"PARCELID": "0010004900", "SITEADDRESS": "8150 ROYALTON RD SW",
              "CLASSCD": "510", "RESYRBLT": 1993, "SHP_UPLD_DATE": 1790733757000}

FRANKLIN, CUYAHOGA, SUMMIT, MONTGOMERY = "39049", "39035", "39153", "39113"
DELAWARE, BUTLER, LORAIN, FAIRFIELD, LICKING = "39041", "39017", "39093", "39045", "39089"

#: A point in Columbus. Which parcel a coordinate lands in is decided here by the
#: stubbed rows, not by the coordinate.
_POINT = (39.9529, -83.0371)


def _lookup(exact, near=(), address=None, county=FRANKLIN, slices=None,
            params=None, urls=None, county_answer=FRANKLIN, exceeded=False):
    """Drive ``oh.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` is what the point lands inside; ``near`` what a buffered search
    finds. ``county`` is what the caller passes (None makes the adapter ask
    TIGERweb, which answers ``county_answer``). ``slices``, ``params`` and
    ``urls`` collect what each request was handed.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if url == oh.COUNTY_URL:
            feats = ([{"attributes": {"GEOID": county_answer}}] if county_answer else [])
            return {"features": feats}
        if exceeded:
            raise _shared.TruncatedResponse("truncated at the transfer limit")
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    oh._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return oh.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        oh._lookup_cached.cache_clear()


# ── the ordinary house, in each county ─────────────────────────────────────────


def test_a_franklin_house_reports_its_year_and_area():
    got = _lookup([_FR_HOUSE], address="232 S CENTRAL AVE, COLUMBUS, OH, 43223")
    assert got is not None
    assert got.parcel_id == "010-012132"
    assert got.year_built == 1918 and got.sqft == 1182.0
    assert got.stories is None, "Franklin's FLOORCOUNT is empty and not requested"
    assert "Franklin County Auditor" in got.source


def test_franklins_cr_and_bl_are_circle_and_boulevard():
    """Franklin writes 2,837 circles as "CR" (131 as "CIR") and 9,767 boulevards
    as "BL" (464 as "BLVD"); the Census matcher writes CIR and BLVD. The shared
    table leaves CR alone because elsewhere it can mean creek — so the respelling
    is Franklin's own, and a name that IS "CR" is left as it is."""
    circle = dict(_FR_HOUSE, SITEADDRESS="3507 RIVER AVON CR")
    got = _lookup([circle], address="3507 RIVER AVON CIR, COLUMBUS, OH, 43221")
    assert got is not None and got.year_built == 1918
    blvd = dict(_FR_HOUSE, SITEADDRESS="4600 NORTHTOWNE BL")
    got = _lookup([blvd], address="4600 NORTHTOWNE BLVD, COLUMBUS, OH, 43229")
    assert got is not None and got.year_built == 1918
    assert oh._franklin_street("10 CR ST") == "10 CR ST"
    assert oh._franklin_street("2300 N WOODBROOK E CR UNIT E") \
        == "2300 N WOODBROOK E CIR UNIT E"
    assert not _shared.same_address("3507 RIVER AVON CR", "3507 RIVER AVON CIR"), \
        "the shared comparison must stay as it is; the fold is Franklin's"


def test_a_summit_house_with_padded_situs_still_confirms():
    """Summit writes "1344  SWIGART CT " — doubled and trailing spaces."""
    got = _lookup([], near=[_SUM_HOUSE], address="1344 SWIGART CT, AKRON, OH",
                  county=SUMMIT)
    assert got is not None and got.year_built == 1940
    assert got.sqft == 1380.0 and got.stories == 1


def test_a_montgomery_house_reads_the_qualified_columns():
    got = _lookup([_MONT_HOUSE], address="4060 DELPHOS AVE, DAYTON, OH",
                  county=MONTGOMERY)
    assert got is not None
    assert got.parcel_id == "R72 12307 0032"
    assert (got.year_built, got.sqft, got.stories) == (1966, 1217.0, 1)
    assert got.construction == "brick"
    assert "2026-10-02" in got.data_vintage


def test_a_butler_house_reports_its_condition():
    got = _lookup([_BUT_HOUSE], address="1604 WICHITA DR, HAMILTON, OH", county=BUTLER)
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1964, 1175.0, 1)
    assert got.condition == "average"
    assert "2024" in got.data_vintage, "a snapshot must say how old it is"


def test_a_lorain_house_is_confirmed_once_its_city_is_trimmed():
    """"1142  W 12TH ST  LORAIN, OH 44052": the city follows the last run of spaces
    before the comma, with no comma of its own. Left on, "LORAIN" reads as part of
    the street name and no Lorain address could ever confirm."""
    assert oh._lorain_street(_LOR_HOUSE["SITEADDRESS"]) == "1142 W 12TH ST"
    assert oh._lorain_street("1142 W 12TH ST  NORTH RIDGEVILLE, OH 44039") \
        == "1142 W 12TH ST"
    got = _lookup([_LOR_HOUSE], address="1142 W 12TH ST, LORAIN, OH, 44052",
                  county=LORAIN)
    assert got is not None and got.year_built == 1900 and got.sqft == 1368.0


def test_a_bare_street_address_is_never_cut():
    """The trim applies only where the ", OH" tail is present; without it the last
    run of spaces would be read as the start of a city."""
    assert oh._lorain_street("5683   BOXWOOD DR") == "5683   BOXWOOD DR"


# ── Cuyahoga's age columns that are years ──────────────────────────────────────


def test_cuyahogas_min_age_is_a_year_not_an_age():
    """The data dictionary calls min_age "Oldest Residential Building Age"; the
    values are years built (1952 here), and min_age <= max_age on every row of the
    layer (0 rows where min_age > max_age, 987 where it is smaller). So min_age is
    the oldest dwelling's YEAR — read as a year, never subtracted from anything."""
    got = _lookup([_CUY_HOUSE], address="7506 IRA AVE, BROOKLYN, OH, 44144",
                  county=CUYAHOGA)
    assert got is not None and got.year_built == 1952
    assert got.sqft == 1131.0
    assert "2026-10-02" in got.data_vintage


def test_two_dwellings_built_in_different_years_have_no_single_year():
    """A front house of 1900 and a rear house of 2003 on one lot: which is the
    reader's, the record cannot say. Neither the oldest nor the newest is "the
    house's year built", so none is reported — and the combined 7,927 sq ft is
    not one home's area either."""
    assert _lookup([_CUY_TWO_HOUSES], address="10107 CLIFF DR, CLEVELAND, OH",
                   county=CUYAHOGA) is None


def test_two_dwellings_of_one_year_keep_the_year_but_not_the_area():
    same_year = dict(_CUY_TWO_HOUSES, max_age=1900)
    got = _lookup([same_year], address="10107 CLIFF DR, CLEVELAND, OH",
                  county=CUYAHOGA)
    assert got is not None and got.year_built == 1900
    assert got.sqft is None and got.stories is None


def test_a_recorded_zero_dwellings_refuses_the_year():
    shop = dict(_CUY_HOUSE, res_bldg_count=0)
    assert _lookup([shop], address="7506 IRA AVE, BROOKLYN, OH", county=CUYAHOGA) is None


def test_whole_stories_only():
    """1.5 stories (a Cape Cod) has no whole-number reading — Cook's call."""
    got = _lookup([_CUY_HOUSE], address="7506 IRA AVE, BROOKLYN, OH", county=CUYAHOGA)
    assert got is not None and got.stories is None
    got = _lookup([dict(_CUY_HOUSE, max_res_heights=2)],
                  address="7506 IRA AVE, BROOKLYN, OH", county=CUYAHOGA)
    assert got is not None and got.stories == 2


def test_an_implausible_story_count_is_refused():
    """Delaware records 6-9 stories on a handful of single-family lots."""
    got = _lookup([dict(_DEL_HOUSE, STORYHGT=9)], address="4784 MOONEY RD, RADNOR, OH",
                  county=DELAWARE)
    assert got is not None and got.stories is None and got.year_built == 1986


# ── duplicate rows and placeholders ────────────────────────────────────────────


def test_identical_rows_of_one_parcel_are_one_candidate():
    """Cuyahoga returned parcel 43306050 four times at one point. Offered raw,
    that is four candidates and the shared selector correctly calls it
    ambiguous — refusing the most ordinary house in the county."""
    got = _lookup([_CUY_HOUSE] * 4, address="7506 IRA AVE, BROOKLYN, OH",
                  county=CUYAHOGA)
    assert got is not None and got.parcel_id == "43306050"


def test_rows_of_one_parcel_that_disagree_are_not_offered():
    broken = dict(_CUY_HOUSE, min_age=1990, max_age=1990)
    assert _lookup([_CUY_HOUSE, broken], address="7506 IRA AVE, BROOKLYN, OH",
                   county=CUYAHOGA) is None


def test_a_multi_footprint_does_not_make_a_unit_ambiguous():
    got = _lookup([_CUY_MULTI, _CUY_HOUSE], address="7506 IRA AVE, BROOKLYN, OH",
                  county=CUYAHOGA)
    assert got is not None and got.parcel_id == "43306050"


def test_a_row_with_no_parcel_id_is_a_record_of_nothing():
    no_id = dict(_CUY_HOUSE, parcel_id=None)
    assert _lookup([no_id], address="7506 IRA AVE, BROOKLYN, OH", county=CUYAHOGA) is None


def test_summits_blank_association_parcel_is_dropped():
    """The association parcel overlaps the units with a blank house number and no
    year. It can never contribute a fact, and counted as a candidate it would make
    every unit under it ambiguous."""
    got = _lookup([_SUM_HOA, _SUM_HOUSE], address="1344 SWIGART CT, AKRON, OH",
                  county=SUMMIT)
    assert got is not None and got.parcel_id == "2304654"


def test_a_common_area_parcel_is_dropped_before_the_choice():
    """Lorain's CLASSCD 553 is "H.O.A. COMMON AREA" — never anybody's home."""
    common = dict(_LOR_HOUSE, PARCELID="0201006119999", CLASSCD="553  ", USECD="500",
                  RESYRBLT=None, RESFLRAREA=None)
    got = _lookup([common, _LOR_HOUSE], address="1142 W 12TH ST, LORAIN, OH",
                  county=LORAIN)
    assert got is not None and got.parcel_id == "0201006119022"


def test_placeholder_codes_are_per_county():
    """540 is an association lot in Franklin and a four-family dwelling in Lorain;
    a statewide placeholder list would drop Lorain's four-family homes."""
    assert "540" in oh.COUNTIES[FRANKLIN].placeholder_codes
    assert "540" not in oh.COUNTIES[LORAIN].placeholder_codes
    four_family = dict(_LOR_HOUSE, USECD="540", CLASSCD="540  ")
    got = _lookup([four_family], address="1142 W 12TH ST, LORAIN, OH", county=LORAIN)
    assert got is not None and got.year_built == 1900
    assert got.sqft is None, "four homes' area is not one home's"


# ── a parcel with two addresses ────────────────────────────────────────────────


def test_a_parcel_listed_under_two_addresses_matches_either():
    """Lorain writes one row per street address: 3235 and 3237 GROVE AVE are one
    parcel. Merged, the parcel confirms under either number."""
    for typed in ("3235 GROVE AVE, LORAIN, OH", "3237 GROVE AVE, LORAIN, OH"):
        got = _lookup(_LOR_DOUBLE, address=typed, county=LORAIN)
        assert got is not None and got.parcel_id == "0300094112004", typed
        assert got.year_built == 1900
        assert got.sqft is None, "a two-family's area is both homes'"


def test_a_half_address_is_a_second_dwelling_and_refuses_the_area():
    """"618" and "618 1/2" DEWEY AVE on one 510 parcel: the code says one family,
    the second address says a second home. The area is refused."""
    got = _lookup(_LOR_HALF, address="618 DEWEY AVE, ELYRIA, OH", county=LORAIN)
    assert got is not None and got.year_built == 1928 and got.sqft is None
    assert not _shared.same_address("618 DEWEY AVE", "618 1/2 DEWEY AVE")


# ── condominiums ───────────────────────────────────────────────────────────────


def test_a_condominium_stack_without_a_unit_is_ambiguous():
    assert _lookup(_FR_STACK, near=_FR_STACK,
                   address="5500 BERMUDA BAY DR, COLUMBUS, OH") is None
    assert _lookup(_FR_STACK) is None, "and with no address at all"


def test_a_typed_unit_picks_its_own_parcel_and_reports_the_year_only():
    """The unit's own row survives the filter; its year is the building's. Its
    area is one apartment's and is refused: the record is not one dwelling in one
    building."""
    got = _lookup(_FR_STACK, near=_FR_STACK,
                  address="5500 BERMUDA BAY DR #55001C, COLUMBUS, OH")
    assert got is not None and got.parcel_id == "590-313748"
    assert got.year_built == 1985
    assert got.sqft is None and got.stories is None


def test_a_condominium_unit_with_its_own_polygon_still_refuses_its_area():
    unit = dict(_FR_STACK[0])
    got = _lookup([unit], near=[unit], address="5500 BERMUDA BAY DR, COLUMBUS, OH")
    assert got is not None and got.year_built == 1985 and got.sqft is None


# Delaware: three units of one complex, each row carrying the complex's whole
# outline (81 units of OAK CREEK CONDOS share one 222,542 sq ft polygon), each
# with its own street address, year and unit area.
_DEL_COMPLEX = [
    {"ADDR1": f"{n} OAK VILLAGE BLVD", "CLASS": "550", "YRBUILT": 1993,
     "SQFT": sqft, "STORYHGT": 1}
    for n, sqft in ((8930, 866), (8921, 754), (8915, 866))
]


def test_a_unit_whose_polygon_is_the_whole_complex_is_found_by_address():
    """Containment says nothing about which unit of the complex the point is in:
    the point is "inside" all of them. With an address in hand the unit is found
    by address in the buffer, exactly one of them agreeing."""
    got = _lookup(_DEL_COMPLEX, near=_DEL_COMPLEX,
                  address="8930 OAK VILLAGE BLVD, LEWIS CENTER, OH", county=DELAWARE)
    assert got is not None and got.year_built == 1993
    assert got.sqft is None, "a condominium unit is not one dwelling in one building"


def test_without_an_address_a_complex_is_still_ambiguous():
    assert _lookup(_DEL_COMPLEX, near=_DEL_COMPLEX, county=DELAWARE) is None


def test_a_house_inside_its_lot_is_still_confirmed_by_containment():
    """The condominium rule must not touch the ordinary path: one house polygon,
    its own address, answered by containment with no buffered request."""
    params = []
    got = _lookup([_DEL_HOUSE], address="4784 MOONEY RD, RADNOR, OH", county=DELAWARE,
                  params=params)
    assert got is not None and len(params) == 1 and "distance" not in params[0]


# ── the land-use codes ─────────────────────────────────────────────────────────


def test_vacant_land_reports_no_year():
    """Franklin has 35 rows coded 500-502 (vacant residential land) that carry a
    year — a demolished house's, or a keying slip. Either way no home stands."""
    vacant = dict(_FR_HOUSE, CLASSCD="500")
    assert _lookup([vacant], address="232 S CENTRAL AVE, COLUMBUS, OH") is None


def test_lorains_class_code_outranks_its_stale_use_code():
    """USECD 500 (vacant) against CLASSCD 510 (single family) on 3,944 rows, 3,922
    of them carrying a year built averaging 2013: houses on lots USECD still files
    as platted. The other way round (USECD 510, CLASSCD 500) on 682 rows, 18 with
    a year: demolitions. CLASSCD is the current column, so it decides."""
    got = _lookup([_LOR_SPLIT], address="4100 MENLO PARK LN, VERMILION, OH",
                  county=LORAIN)
    assert got is not None and got.year_built == 2021 and got.sqft == 1894.0
    demolished = dict(_LOR_SPLIT, USECD="510", CLASSCD="500  ")
    assert _lookup([demolished], address="4100 MENLO PARK LN, VERMILION, OH",
                   county=LORAIN) is None


def test_silence_about_the_land_use_is_not_a_refusal():
    """Lorain leaves USECD null on 13,267 rows and CLASSCD null on 2,857: the other
    column speaks for them. With neither, the year still comes through — silence
    is not a refusal — but nothing says one home, so the area does not."""
    got = _lookup([dict(_LOR_HOUSE, USECD=None)], address="1142 W 12TH ST, LORAIN, OH",
                  county=LORAIN)
    assert got is not None and got.year_built == 1900 and got.sqft == 1368.0
    got = _lookup([dict(_LOR_HOUSE, CLASSCD=None)], address="1142 W 12TH ST, LORAIN, OH",
                  county=LORAIN)
    assert got is not None and got.year_built == 1900 and got.sqft == 1368.0
    got = _lookup([dict(_LOR_HOUSE, CLASSCD=None, USECD=None)],
                  address="1142 W 12TH ST, LORAIN, OH", county=LORAIN)
    assert got is not None and got.year_built == 1900 and got.sqft is None


def test_a_side_lot_under_the_houses_address_does_not_hide_the_house():
    """Montgomery files 6415 LANDSEND CT's side lot as 500 (vacant) under the
    house's own address. Both are within 80 m of an off-lot geocode; offered as a
    candidate, the lot makes the house ambiguous though it could never answer."""
    lot = dict(_MONT_HOUSE, **{"SDE.mc_parcel_polygon.TAXPINNO": "A01 27618 0012",
                               _M + "LUC": "500", _M + "DWEL_YRBLT": 0.0,
                               _M + "DWEL_SFLA": 0.0, _M + "DWEL_EXTWALL": " "})
    got = _lookup([], near=[lot, _MONT_HOUSE], address="4060 DELPHOS AVE, DAYTON, OH",
                  county=MONTGOMERY)
    assert got is not None and got.parcel_id == "R72 12307 0032"


def test_a_quadrant_written_on_one_side_only_is_set_aside_in_fairfield_and_licking():
    """Census drops Fairfield's trailing quadrant ("13113 RUSTIC DR NW" comes back
    "13113 RUSTIC DR") and adds Licking's ("8297 BLACKS RD SW" for a roll with
    none). Two quadrants that are both written must still agree."""
    nw = dict(_FAIRFIELD, SITEADDRESS="13113 RUSTIC DR NW")
    got = _lookup([nw], address="13113 RUSTIC DR, PICKERINGTON, OH, 43147",
                  county=FAIRFIELD)
    assert got is not None and got.year_built == 1993
    assert _lookup([nw], address="13113 RUSTIC DR SE, PICKERINGTON, OH",
                   county=FAIRFIELD) is None
    assert _lookup([nw], address="13115 RUSTIC DR, PICKERINGTON, OH",
                   county=FAIRFIELD) is None
    assert _lookup([nw], address="13113 RUSTIC LN, PICKERINGTON, OH",
                   county=FAIRFIELD) is None
    bare = dict(_LICKING, SITEADDRESS="8297 BLACKS RD ")
    got = _lookup([bare], address="8297 BLACKS RD SW, PATASKALA, OH, 43062",
                  county=LICKING)
    assert got is not None and got.year_built == 2000


def test_the_quadrant_is_not_optional_elsewhere():
    """Only the two counties whose matcher disagreement was measured get the fold."""
    nw = dict(_FR_HOUSE, SITEADDRESS="232 S CENTRAL AVE NW")
    assert _lookup([nw], address="232 S CENTRAL AVE, COLUMBUS, OH") is None
    assert not oh.COUNTIES[FRANKLIN].quadrant_optional


def test_a_converted_dwelling_keeps_its_dwelling_year():
    """Franklin's RESYRBLT dates only dwellings, so on a commercial parcel it is
    the house's year (470, "DWELLING CONVERTED TO OFFICE")."""
    office = dict(_FR_HOUSE, CLASSCD="470")
    got = _lookup([office], address="232 S CENTRAL AVE, COLUMBUS, OH")
    assert got is not None and got.year_built == 1918
    assert got.sqft is None, "only a single-family code says one home"


def test_delawares_year_on_a_shop_is_the_shops():
    """Delaware's YRBUILT dates any building — 825 Kintner Pkwy is a 2021,
    46,200 sq ft commercial building coded 400. Its year needs a home's code."""
    assert _lookup([_DEL_SHOP], address="825 KINTNER PKWY, SUNBURY, OH",
                   county=DELAWARE) is None
    office = dict(_DEL_SHOP, CLASS="499", SQFT=2013)
    assert _lookup([office], address="825 KINTNER PKWY, SUNBURY, OH",
                   county=DELAWARE) is None


def test_delaware_publishes_no_parcel_id_and_still_answers():
    got = _lookup([_DEL_HOUSE], address="4784 MOONEY RD, RADNOR, OH", county=DELAWARE)
    assert got is not None and got.parcel_id is None
    assert (got.year_built, got.sqft, got.stories) == (1986, 1374.0, 1)


def test_delaware_rows_are_not_merged_without_an_id():
    """Two different Delaware houses at one point are two candidates, not one."""
    other = dict(_DEL_HOUSE, ADDR1="4800 MOONEY RD", YRBUILT=1985)
    assert _lookup([_DEL_HOUSE, other], address="4784 MOONEY RD, RADNOR, OH",
                   county=DELAWARE) is None


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_MONT_HOUSE, **{_M + "DWEL_YRBLT": 0.0})],
                  address="4060 DELPHOS AVE, DAYTON, OH", county=MONTGOMERY)
    assert got is not None and got.year_built is None
    assert got.sqft == 1217.0, "the area survives; only the year is missing"


def test_lorains_absurd_years_are_refused():
    """Lorain carries RESYRBLT values up to 5391."""
    got = _lookup([dict(_LOR_HOUSE, RESYRBLT=5391.0)], address="1142 W 12TH ST, LORAIN, OH",
                  county=LORAIN)
    assert got is not None and got.year_built is None


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    at = _lookup([dict(_FR_HOUSE, RESYRBLT=EARLIEST_PLAUSIBLE_YEAR)],
                 address="232 S CENTRAL AVE, COLUMBUS, OH")
    assert at is not None and at.year_built == EARLIEST_PLAUSIBLE_YEAR
    below = _lookup([dict(_FR_HOUSE, RESYRBLT=EARLIEST_PLAUSIBLE_YEAR - 1)],
                    address="232 S CENTRAL AVE, COLUMBUS, OH")
    assert below is not None and below.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_FR_HOUSE, RESYRBLT=None, RESFLRAREA_AG=None)
    assert _lookup([empty], address="232 S CENTRAL AVE, COLUMBUS, OH") is None


# ── the vocabulary translations ────────────────────────────────────────────────


def test_unambiguous_walls_translate():
    for raw, want in (("FRAME", "frame"), ("ALUMINUM/VINYL", "frame"),
                      ("ASBESTOS", "frame"), ("BRICK", "brick"), ("BLOCK", "block"),
                      ("STONE", "stone")):
        got = _lookup([dict(_MONT_HOUSE, **{_M + "DWEL_EXTWALL": raw})],
                      address="4060 DELPHOS AVE, DAYTON, OH", county=MONTGOMERY)
        assert got is not None and got.construction == want, raw


def test_ambiguous_walls_stay_empty():
    for raw in ("MASONRY & FRAME", "STUCCO", "CONCRETE", " ", None, "LOG"):
        got = _lookup([dict(_MONT_HOUSE, **{_M + "DWEL_EXTWALL": raw})],
                      address="4060 DELPHOS AVE, DAYTON, OH", county=MONTGOMERY)
        assert got is not None and got.construction is None, raw


def test_a_condition_between_two_grades_stays_empty():
    got = _lookup([_BUT_VG], address="7883 CHESTERSHIRE DR, WEST CHESTER, OH",
                  county=BUTLER)
    assert got is not None and got.condition is None and got.year_built == 1988
    for raw, want in (("EX", "excellent"), ("GD", "good"), ("FR", "fair"),
                      ("PR", "poor"), ("UN", "unsound")):
        got = _lookup([dict(_BUT_HOUSE, CDU=raw)], address="1604 WICHITA DR, HAMILTON, OH",
                      county=BUTLER)
        assert got is not None and got.condition == want, raw
    got = _lookup([dict(_BUT_HOUSE, CDU="VP")], address="1604 WICHITA DR, HAMILTON, OH",
                  county=BUTLER)
    assert got is not None and got.condition is None


def test_every_translation_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import CONDITION_VALUES, CONSTRUCTION_VALUES
    assert set(oh._WALL.values()) <= CONSTRUCTION_VALUES
    assert set(oh._CONDITION.values()) <= CONDITION_VALUES


# ── the vintage a reader can date ──────────────────────────────────────────────


def test_the_columbus_mirror_dates_each_county_by_its_own_copy():
    """Licking's rows in the mirror were copied 2024-05-06 and have not been
    refreshed since; Fairfield's on 2026-09-30 (UTC). Reading the date off the row is
    what keeps a stale copy from being presented at the confidence of a fresh one."""
    got = _lookup([_LICKING], address="7990 BENNER RD, JOHNSTOWN, OH", county=LICKING)
    assert got is not None and "2024-05-06" in got.data_vintage
    assert "Licking" in got.source and "Columbus" in got.source
    got = _lookup([_FAIRFIELD], address="8150 ROYALTON RD SW, LANCASTER, OH",
                  county=FAIRFIELD)
    assert got is not None and "2026-09-30" in got.data_vintage
    assert got.sqft is None, "the mirror carries no floor area outside Franklin"


def test_a_missing_date_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_LICKING, SHP_UPLD_DATE=None)], address="7990 BENNER RD, OH",
                  county=LICKING)
    assert got is not None
    assert got.data_vintage == "Licking County Auditor records via the City of Columbus"


def test_the_mirror_reads_only_the_routed_countys_rows():
    params = []
    _lookup([_LICKING], county=LICKING, params=params)
    assert params and all(p.get("where") == "COUNTY='Licking'" for p in params)


# ── the field lists ────────────────────────────────────────────────────────────

#: Owner, mailing and sale columns that exist in these layers, by county.
_PRIVATE = {
    FRANKLIN: ("OWNERNME1", "OWNERNME2", "MAILNME1", "PSTLADDRES", "SALEPRICE",
               "RESYRBLTEFF"),
    CUYAHOGA: ("parcel_owner", "second_owner", "grantor", "grantee", "mail_name",
               "mail_addr_street", "last_sales_amount", "lender"),
    SUMMIT: ("ownernme1", "ownernme2", "pstladdress", "pstlcity"),
    MONTGOMERY: ("SDE.WEB_CAMA.OWNER_NAME1", "SDE.WEB_CAMA.OWNER_ADDR1",
                 "SDE.WEB_CAMA.MAILING_NAME1", "SDE.WEB_CAMA.SALE_PRICE",
                 "SDE.WEB_CAMA.SALE_OLDOWN"),
    DELAWARE: ("OWNER1", "OWNER2", "MAILNAME1", "MAILADDR1", "SALE_AMNT", "YRREMOD"),
    BUTLER: ("OWNER", "PRICE", "EFFYR", "VPRICE"),
    LORAIN: ("OWNERNME1", "PSTLADDRESS", "MAILNAME", "OWNER_ADDRESS",
             "LASTSALEPRICE"),
    FAIRFIELD: ("OWNERNME1", "PSTLADDRES"),
    LICKING: ("OWNERNME1", "PSTLADDRES"),
}


def test_every_field_list_is_explicit_and_carries_nothing_private():
    for fips, cfg in oh.COUNTIES.items():
        fields = cfg.out_fields.split(",")
        assert "*" not in fields and cfg.out_fields.strip(), cfg.name
        for private in _PRIVATE[fips]:
            assert private not in fields, (cfg.name, private)
        lowered = {f.lower() for f in fields}
        assert not any("owner" in f or "mail" in f or "pstl" in f or "sale" in f
                       for f in lowered), (cfg.name, fields)


def test_every_column_read_is_a_column_requested():
    """A column read but not requested is None on every row — silently."""
    for cfg in oh.COUNTIES.values():
        fields = set(cfg.fields)
        for col in (cfg.pid, cfg.address, cfg.year, cfg.area, cfg.stories, cfg.wall,
                    cfg.condition, cfg.building_count, cfg.newest_year, *cfg.land_use):
            assert col is None or col in fields, (cfg.name, col)


def test_the_requested_fields_are_what_reaches_the_service():
    for fips, rows in ((FRANKLIN, [_FR_HOUSE]), (MONTGOMERY, [_MONT_HOUSE]),
                       (CUYAHOGA, [_CUY_HOUSE])):
        params, urls = [], []
        _lookup(rows, county=fips, params=params, urls=urls)
        cfg = oh.COUNTIES[fips]
        assert params and all(p["outFields"] == cfg.out_fields for p in params)
        assert urls and all(u == cfg.url for u in urls)


def test_the_effective_year_is_never_requested():
    for cfg in oh.COUNTIES.values():
        for col in cfg.fields:
            assert "EFF" not in col.upper() and "REMOD" not in col.upper(), (cfg.name, col)


def test_the_lapsed_warren_domain_is_nowhere_in_the_module():
    """Warren County's old auditor domain now redirects to an unrelated spam
    profile. It must never be queried, linked or named in code — including here,
    so the name is assembled rather than written."""
    source = inspect.getsource(oh).lower()
    assert "wc" + "auditor" not in source
    assert not any("warren" in cfg.url.lower() for cfg in oh.COUNTIES.values())


# ── the county list ────────────────────────────────────────────────────────────


def test_every_claimed_county_is_a_real_ohio_county():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        ohio = {r["geoid"] for r in csv.DictReader(fh)
                if r["geoid"].startswith("39") and len(r["geoid"]) == 5}
    assert len(ohio) == 88, f"expected 88 Ohio counties, got {len(ohio)}"
    assert oh.COUNTY_FIPS <= ohio
    assert oh.COUNTY_FIPS == {FRANKLIN, CUYAHOGA, SUMMIT, MONTGOMERY, DELAWARE,
                              BUTLER, LORAIN, FAIRFIELD, LICKING}


def test_the_counties_with_no_public_year_built_are_not_claimed():
    """Hamilton, Lucas, Stark, Mahoning and Warren publish no keyless,
    point-queryable year built (see the module docstring). Claiming them would
    spend each label's budget to return nothing."""
    for fips in ("39061", "39095", "39151", "39099", "39165"):
        assert fips not in oh.COUNTY_FIPS, fips


def test_the_callers_county_picks_the_layer_and_skips_the_county_request():
    for fips in oh.COUNTY_FIPS:
        urls = []
        _lookup([], county=fips, urls=urls)
        assert oh.COUNTY_URL not in urls
        assert urls and all(u == oh.COUNTIES[fips].url for u in urls), fips


def test_without_a_county_the_point_is_located_first():
    urls = []
    got = _lookup([_MONT_HOUSE], county=None, county_answer=MONTGOMERY, urls=urls)
    assert got is not None and got.year_built == 1966
    assert urls[0] == oh.COUNTY_URL
    assert all(u == oh.MONTGOMERY_URL for u in urls[1:])


def test_a_point_outside_the_covered_counties_is_no_answer():
    assert _lookup([_FR_HOUSE], county=None, county_answer=None) is None
    assert _lookup([_FR_HOUSE], county=None, county_answer="39061") is None


def test_a_county_this_adapter_does_not_claim_is_located_rather_than_trusted():
    urls = []
    _lookup([_FR_HOUSE], county="39061", urls=urls)
    assert urls[0] == oh.COUNTY_URL


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_countys_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to fit.
    Pinned against the host constant, not a literal."""
    from housing_label import config
    for cfg in oh.COUNTIES.values():
        assert cfg.timeout + cfg.read_slice < config.UPSTREAM_HOST_BUDGET, cfg.name
    assert oh.LOOKUP_TIMEOUT + oh.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_montgomery_gets_its_own_clock_and_the_quick_counties_keep_the_shared_one():
    """Montgomery's buffered query measured p95 1.94 s and max 2.04 s, past the
    shared one-second slice; Franklin's slowest of 80 requests was 0.40 s."""
    mont = oh.COUNTIES[MONTGOMERY]
    assert mont.read_slice > _shared._READ_SLICE_S and mont.timeout > _shared.TIMEOUT
    for fips in (FRANKLIN, CUYAHOGA, SUMMIT, BUTLER, LORAIN, FAIRFIELD, LICKING):
        cfg = oh.COUNTIES[fips]
        assert cfg.read_slice == _shared._READ_SLICE_S, cfg.name
        assert cfg.timeout == _shared.TIMEOUT, cfg.name


def test_every_request_passes_its_countys_read_slice():
    for fips, rows in ((MONTGOMERY, [_MONT_HOUSE]), (DELAWARE, [_DEL_HOUSE]),
                       (FRANKLIN, [_FR_HOUSE])):
        slices = []
        assert _lookup(rows, county=fips, slices=slices) is not None
        assert slices and all(s == oh.COUNTIES[fips].read_slice for s in slices)


def test_every_request_shares_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    oh._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        oh.lookup(*_POINT, "4060 DELPHOS AVE, DAYTON, OH", MONTGOMERY)
    finally:
        _shared.get_json = saved
        oh._lookup_cached.cache_clear()
    assert len(seen) == 2, f"expected containment and buffer, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    budget = seen[0] - started
    assert abs(budget - oh.COUNTIES[MONTGOMERY].timeout) < 0.5, budget


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    oh._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert oh.lookup(*_POINT, "232 S CENTRAL AVE, COLUMBUS, OH") is None
        assert oh.lookup(*_POINT, "232 S CENTRAL AVE, COLUMBUS, OH", FRANKLIN) is None
    finally:
        _shared.get_json = saved
        oh._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer():
    assert _lookup([_FR_HOUSE], address="232 S CENTRAL AVE, COLUMBUS, OH",
                   exceeded=True) is None


def test_garbage_coordinates_fail_open():
    assert oh.lookup("not a number", None) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
