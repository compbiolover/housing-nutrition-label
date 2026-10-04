#!/usr/bin/env python3
"""The Minnesota adapter — seven metro counties from one regional parcel service.

Nothing here touches the network. The Metropolitan Council's service is stubbed
with row shapes recorded from it live, for the reason every adapter test file
gives: an adapter fails open on purpose, so a renamed column or a broken match
reads as "Minnesota has no record here" and would never announce itself. A test
that called the real service would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Minnesota's own:

1. **Stacked polygons.** Hennepin, Ramsey and Washington draw every condominium
   unit (and garage stall) as its own copy of one polygon; Anoka draws a
   quadplex as four polygons at one address.
2. **Spelled-out address parts**: "Street" "Northwest", which the matcher writes
   "ST NW", and St Paul's directionals, which the matcher moves, adds and drops.
3. **One vocabulary per county** for what is a home and what is one dwelling, and
   a unit count that Hennepin zeroes everywhere.
4. **Home style** carries the story count, and in two counties the wall material.

This file alone: ``pytest tests/test_assessor_mn.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

from housing_label.enrich.assessor import _shared, mn

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── rows recorded live, 2026-10-04 ─────────────────────────────────────────────

_RAMSEY_DATES = {"TAX_YEAR": 2026, "MKT_YEAR": 2025, "EXP_DATE": 1782864000000}

# Ramsey: a single-family house in St Paul — one dwelling, so its finished area and
# story count are that home's.
_HOUSE = {"COUNTY_PIN": "082823130131", "ANUMBER": 414, "ST_NAME": "Woodlawn",
          "ST_POS_TYP": "Avenue", "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
          "DWELL_TYPE": "SINGLE FAMILY DWELLING, PLATT", "HOME_STYLE": "TWO STORY",
          "FIN_SQ_FT": 4350, "YEAR_BUILT": 2006, "NUM_UNITS": 1, **_RAMSEY_DATES,
          "Shape__Area": 835.35255621, "Shape__Length": 128.04188452748224}

# Ramsey: St Paul writes the directional after the street; the matcher before it.
_MINNEHAHA = {"COUNTY_PIN": "342923220005", "ANUMBER": 1478, "ST_NAME": "Minnehaha",
              "ST_POS_TYP": "Avenue", "ST_POS_DIR": "West",
              "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
              "DWELL_TYPE": "SINGLE FAMILY DWELLING, PLATT", "HOME_STYLE": "TWO STORY",
              "FIN_SQ_FT": 1287, "YEAR_BUILT": 1911, "NUM_UNITS": 1, **_RAMSEY_DATES,
              "Shape__Area": 480.45753342, "Shape__Length": 100.36541492308646}

# Ramsey: no directional in the roll; the matcher returns "1938 W JEFFERSON AVE".
_JEFFERSON = {"COUNTY_PIN": "092823240028", "ANUMBER": 1938, "ST_NAME": "Jefferson",
              "ST_POS_TYP": "Avenue", "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
              "DWELL_TYPE": "SINGLE FAMILY DWELLING, PLATT", "HOME_STYLE": "ONE STORY",
              "FIN_SQ_FT": 1011, "YEAR_BUILT": 1922, "NUM_UNITS": 1, **_RAMSEY_DATES,
              "Shape__Area": 631.14903209, "Shape__Length": 119.2853946660005}

# Ramsey: a Vadnais Heights condominium building — one polygon, six units, each at
# its own house number with its own area. Two of them.
_PONDVIEW = [
    {"COUNTY_PIN": "213022240251", "ANUMBER": 1014, "ST_NAME": "Pondview",
     "ST_POS_TYP": "Court", "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
     "DWELL_TYPE": "CONDO", "HOME_STYLE": "CONDO", "FIN_SQ_FT": 1015,
     "YEAR_BUILT": 1988, "NUM_UNITS": 1, **_RAMSEY_DATES,
     "Shape__Area": 1908.10107358, "Shape__Length": 174.9055330909269},
    {"COUNTY_PIN": "213022240252", "ANUMBER": 1016, "ST_NAME": "Pondview",
     "ST_POS_TYP": "Court", "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
     "DWELL_TYPE": "CONDO", "HOME_STYLE": "CONDO", "FIN_SQ_FT": 951,
     "YEAR_BUILT": 1988, "NUM_UNITS": 1, **_RAMSEY_DATES,
     "Shape__Area": 1908.10107358, "Shape__Length": 174.9055330909269},
]

# Ramsey: a condominium garage stall — residential class, but no home.
_RAMSEY_GARAGE = {"COUNTY_PIN": "312922440239", "ANUMBER": 168, "ST_NAME": "6th",
                  "ST_POS_TYP": "Street", "ST_POS_DIR": "East", "SUB_ID1": "G-340",
                  "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
                  "DWELL_TYPE": "CONDO GARAGE", "YEAR_BUILT": 1984, **_RAMSEY_DATES,
                  "Shape__Area": 1408.713143225, "Shape__Length": 150.65750352395136}

_ANOKA_DATES = {"TAX_YEAR": 2026, "MKT_YEAR": 2025, "EXP_DATE": 1783468800000}

# Anoka: an Andover house on a quadrant-addressed street, spelled out in full.
_CRANE = {"COUNTY_PIN": "263224230068", "ANUMBER": 14544, "ST_NAME": "Crane",
          "ST_POS_TYP": "Street", "ST_POS_DIR": "Northwest",
          "USECLASS1": "1a RESIDENTIAL SINGLE UNIT", "DWELL_TYPE": "01",
          "HOME_STYLE": "Bi-level", "FIN_SQ_FT": 1159, "YEAR_BUILT": 1997,
          **_ANOKA_DATES, "Shape__Area": 1650.94168136,
          "Shape__Length": 167.11245974781104}


# Anoka: a Blaine townhouse quadplex — four polygons at one street address, one
# unit each, no unit count.
def _waconia(unit, pin, area, sqft):
    return {"COUNTY_PIN": pin, "ANUMBER": 12162, "ST_NAME": "Waconia",
            "ST_POS_TYP": "Street", "ST_POS_DIR": "Northeast", "SUB_ID1": unit,
            "USECLASS1": "1a RESIDENTIAL SINGLE UNIT", "DWELL_TYPE": "01",
            "HOME_STYLE": "TOWNHOUSE, 2 STORY", "FIN_SQ_FT": sqft, "YEAR_BUILT": 2006,
            **_ANOKA_DATES, "Shape__Area": area, "Shape__Length": area / 3}


_QUADPLEX = [_waconia("A", "093123140284", 208.289654455, 1702),
             _waconia("B", "093123140285", 164.87445552, 1704),
             _waconia("C", "093123140286", 164.86849981, 1694),
             _waconia("D", "093123140287", 208.34987702, 1436)]

# Anoka: a commercial parcel with a year built and a house-like style.
_ANOKA_COMMERCIAL = {"COUNTY_PIN": "323425120001", "ANUMBER": 8310,
                     "ST_NAME": "Hill And Dale", "ST_POS_TYP": "Drive",
                     "ST_POS_DIR": "Northwest", "USECLASS1": "3a COMMERCIAL PREFERENTIAL",
                     "DWELL_TYPE": "06", "HOME_STYLE": "One Story", "FIN_SQ_FT": 960,
                     "YEAR_BUILT": 1975, **_ANOKA_DATES,
                     "Shape__Area": 72458.921078885, "Shape__Length": 1181.8896128504928}


# Hennepin: 730 4th St N, Minneapolis — 241 copies of one polygon. Three units and
# a garage stall; Hennepin sends no finished area and zeroes the unit count.
def _tower(unit, pin, use="Condominium (also Market Rate Cooperative)"):
    return {"COUNTY_PIN": pin, "ANUMBER": 730, "ANUMBERSUF": "", "ST_NAME": "4th",
            "ST_POS_TYP": "Street", "ST_POS_DIR": "North", "SUB_ID1": unit,
            "USECLASS1": use, "FIN_SQ_FT": 0, "YEAR_BUILT": 2007, "NUM_UNITS": 0,
            "EXP_DATE": 1783934863000, "Shape__Area": 2955.624171495,
            "Shape__Length": 219.53631486286847}


_TOWER = [_tower("111", "2202924240471"), _tower("205", "2202924240478"),
          _tower("404", "2202924240503"),
          _tower("404", "2202924240999", use="Condo - Garage/Miscellaneous")]

# Hennepin: an Edina house. NUM_UNITS 0, as on every Hennepin row.
_HENNEPIN_HOUSE = {"COUNTY_PIN": "1802824110022", "ANUMBER": 4619, "ANUMBERSUF": "",
                   "ST_NAME": "Townes", "ST_POS_TYP": "Circle", "SUB_ID1": "",
                   "USECLASS1": "Residential", "FIN_SQ_FT": 0, "YEAR_BUILT": 1939,
                   "NUM_UNITS": 0, "EXP_DATE": 1783934863000,
                   "Shape__Area": 1542.27047671, "Shape__Length": 157.01398764542265}

_WASH_DATES = {"TAX_YEAR": 2027, "MKT_YEAR": 2026, "EXP_DATE": 1782691200000}


# Washington: a Woodbury eight-plex — one polygon, units A-H at one address.
def _quarry(unit, pin, sqft):
    return {"COUNTY_PIN": pin, "ANUMBER": 8741, "ST_NAME": "Quarry Ridge",
            "ST_POS_TYP": "Lane", "SUB_ID1": unit, "USECLASS1": "100",
            "DWELL_TYPE": "Condominium", "HOME_STYLE": "2 Story Condo",
            "FIN_SQ_FT": sqft, "YEAR_BUILT": 1998, "NUM_UNITS": 1, **_WASH_DATES,
            "Shape__Area": 3404.670725865, "Shape__Length": 238.26744552751993}


_QUARRY = [_quarry("A", "1602821420109", 1324), _quarry("E", "1602821420108", 1324),
           _quarry("F", "1602821420110", 1175)]

# Washington: a Stillwater house whose style names its construction.
_STILLWATER = {"COUNTY_PIN": "2002920430004", "ANUMBER": 2261,
               "ST_NAME": "Northridge Avenue", "ST_POS_TYP": "Circle",
               "ST_POS_DIR": "North", "USECLASS1": "100",
               "DWELL_TYPE": "Single-Family / Owner Occupied",
               "HOME_STYLE": "1 Story Frame", "FIN_SQ_FT": 2572, "YEAR_BUILT": 1995,
               "NUM_UNITS": 1, **_WASH_DATES, "Shape__Area": 11108.173659285,
               "Shape__Length": 460.76321158545653}

_DAKOTA_DATES = {"TAX_YEAR": 2027, "MKT_YEAR": 2026, "EXP_DATE": 1783328565000}

# Dakota: a duplex — two dwellings, one parcel.
_DUPLEX = {"COUNTY_PIN": "014717501040", "ANUMBER": 13880, "ST_NAME": "Glendale",
           "ST_POS_TYP": "Court", "USECLASS1": "Residential", "DWELL_TYPE": "Duplex",
           "HOME_STYLE": "One Story", "FIN_SQ_FT": 3684, "YEAR_BUILT": 1958,
           "NUM_UNITS": 2, **_DAKOTA_DATES, "Shape__Area": 1250.998640545,
           "Shape__Length": 144.38064574484252}

# Dakota: a 2025 house filed with 0 units — not a statement of "no dwelling".
_DAKOTA_NEW = {"COUNTY_PIN": "120230003013", "ANUMBER": 19021, "ST_NAME": "Blaine",
               "ST_POS_TYP": "Avenue", "USECLASS1": "Residential",
               "DWELL_TYPE": "S.fam.res", "HOME_STYLE": "Two Story", "FIN_SQ_FT": 1680,
               "YEAR_BUILT": 2025, "NUM_UNITS": 0, **_DAKOTA_DATES,
               "Shape__Area": 1201.5, "Shape__Length": 141.2}

# Dakota: a placeholder polygon — no parcel id, no facts.
_PLACEHOLDER = {**_DAKOTA_DATES, "Shape__Area": 2318.745717785,
                "Shape__Length": 889.0370775597884}

# Carver: a house on a county road, written into the name column.
_COUNTY_ROAD = {"COUNTY_PIN": "010310610", "ANUMBER": 15525, "ST_NAME": "COUNTY ROAD 33",
                "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
                "HOME_STYLE": "1 3/4 Story Frame", "FIN_SQ_FT": 2007, "YEAR_BUILT": 1890,
                "EXP_DATE": 1782518400000, "Shape__Area": 20218.69837758,
                "Shape__Length": 570.2235178536303}

# Carver: a house on a Curve.
_CURVE = {"COUNTY_PIN": "250500150", "ANUMBER": 1050, "ST_NAME": "FALLS",
          "ST_POS_TYP": "Curve", "USECLASS1": "1A/1B/4BB RESIDENTIAL SINGLE UNIT",
          "HOME_STYLE": "2 Story Frame", "FIN_SQ_FT": 2410, "YEAR_BUILT": 2001,
          "EXP_DATE": 1782518400000, "Shape__Area": 1300.25, "Shape__Length": 150.5}

#: A point in St Paul. Which records a coordinate lands in is decided here by the
#: stubbed rows, not by the coordinate.
_POINT = (44.95, -93.10)
_RAMSEY, _ANOKA, _HENNEPIN = "27123", "27003", "27053"
_WASHINGTON, _DAKOTA, _CARVER = "27163", "27037", "27019"


def _lookup(exact, near=(), address=None, county=_RAMSEY, slices=None, params=None,
            urls=None, extra=None, tiger=None):
    """Drive ``mn.lookup()`` over recorded rows, beneath the real transport call.

    ``exact`` is what the point lands inside; ``near`` is what the 80 m buffer
    finds. ``tiger`` is the county TIGERweb would name, for a call without one.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if "tigerweb" in url:
            return {"features": [{"attributes": {"GEOID": tiger}}] if tiger else []}
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": dict(a)} for a in rows], **(extra or {})}

    mn._lookup_cached.cache_clear()
    saved = _shared._fetch_json
    _shared._fetch_json = fake
    try:
        return mn.lookup(*_POINT, address, county_fips=county)
    finally:
        _shared._fetch_json = saved
        mn._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_year_area_and_stories():
    got = _lookup([_HOUSE], address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105")
    assert got is not None
    assert got.parcel_id == "082823130131"
    assert (got.year_built, got.sqft, got.stories) == (2006, 4350, 2)
    assert got.construction is None and got.foundation is None and got.condition is None
    assert "Ramsey County" in got.source


def test_a_house_found_by_the_buffer_reports_the_same():
    got = _lookup([], near=[_HOUSE], address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105")
    assert got is not None and (got.year_built, got.sqft) == (2006, 4350)


def test_the_assessment_year_travels_with_the_value():
    got = _lookup([_HOUSE])
    assert got.data_vintage.endswith("Ramsey County 2025 assessment (taxes payable 2026)")


def test_a_county_that_sends_no_assessment_year_is_dated_by_its_export():
    """Hennepin and Carver send no tax or market year; the export date is the
    honest date for a quarterly copy, and a hard-coded year would go stale."""
    got = _lookup([_HENNEPIN_HOUSE], county=_HENNEPIN)
    assert got.data_vintage.endswith("Hennepin County export of 2026-07-13")


# ── stacked polygons ───────────────────────────────────────────────────────────


def test_a_condominium_unit_is_picked_out_of_its_stack_by_its_unit():
    got = _lookup(_TOWER, address="730 4TH ST N #404, MINNEAPOLIS, MN, 55401",
                  county=_HENNEPIN)
    assert got is not None
    assert got.parcel_id == "2202924240503"   # the unit, not its garage stall
    assert got.year_built == 2007
    assert got.sqft is None                   # Hennepin sends no area


def test_a_stack_without_a_unit_reports_only_the_buildings_year():
    """No unit, no unit-level answer — and no parcel id, because none of the
    stack's parcels was singled out."""
    got = _lookup(_TOWER, address="730 4TH ST N, MINNEAPOLIS, MN, 55401",
                  county=_HENNEPIN)
    assert got is not None
    assert got.year_built == 2007
    assert got.parcel_id is None and got.sqft is None and got.stories is None


def test_units_that_disagree_on_a_year_give_no_building_answer():
    stack = [dict(_TOWER[0]), dict(_TOWER[1], YEAR_BUILT=2015)]
    assert _lookup(stack, address="730 4TH ST N, MINNEAPOLIS, MN, 55401",
                   county=_HENNEPIN) is None


def test_a_garage_stall_cannot_veto_or_stand_in_for_the_units():
    """The stall carries the units' address and even a unit's number; it is set
    aside inside the stack, so it neither vetoes the units' year nor answers."""
    stall = dict(_TOWER[3], YEAR_BUILT=1950)
    got = _lookup(_TOWER[:3] + [stall],
                  address="730 4TH ST N, MINNEAPOLIS, MN, 55401", county=_HENNEPIN)
    assert got is not None and got.year_built == 2007


def test_a_unit_record_found_by_its_unit_reports_the_units_area():
    got = _lookup(_QUARRY, address="8741 QUARRY RIDGE LN #E, WOODBURY, MN, 55125",
                  county=_WASHINGTON)
    assert got is not None
    assert got.parcel_id == "1602821420108"
    assert (got.year_built, got.sqft) == (1998, 1324)
    assert got.stories is None                # "2 Story Condo": unit or building?


def test_a_unit_the_roll_does_not_have_is_refused_rather_than_guessed():
    """A typed unit drops every record naming another unit; a polygon with none
    left is not a candidate."""
    assert _lookup(_QUARRY, address="8741 QUARRY RIDGE LN #Z, WOODBURY, MN, 55125",
                   county=_WASHINGTON) is None


def test_a_condominium_unit_at_its_own_house_number_is_picked_by_the_number():
    got = _lookup(_PONDVIEW, address="1016 PONDVIEW CT, VADNAIS HEIGHTS, MN, 55127")
    assert got is not None
    assert got.parcel_id == "213022240252"
    assert (got.year_built, got.sqft) == (1988, 951)


def test_a_unit_per_polygon_quadplex_is_resolved_by_the_typed_unit():
    """Four polygons agree with "12162 WACONIA ST NE"; only one can be unit C's."""
    got = _lookup([], near=_QUADPLEX,
                  address="12162 WACONIA ST NE #C, MINNEAPOLIS, MN, 55449", county=_ANOKA)
    assert got is not None
    assert got.parcel_id == "093123140286"
    assert (got.sqft, got.stories) == (1694, 2)


def test_the_quadplex_without_a_unit_is_ambiguous_in_the_buffer():
    assert _lookup([], near=_QUADPLEX,
                   address="12162 WACONIA ST NE, MINNEAPOLIS, MN, 55449",
                   county=_ANOKA) is None


def test_another_units_polygon_under_the_point_gives_only_the_year():
    """The geocode lands in unit C's polygon and the address agrees — but the
    reader typed no unit, so C's area and stories may be a neighbor's."""
    got = _lookup([_QUADPLEX[2]], address="12162 WACONIA ST NE, MINNEAPOLIS, MN, 55449",
                  county=_ANOKA)
    assert got is not None and got.year_built == 2006
    assert got.sqft is None and got.stories is None


def test_two_polygons_containing_the_point_are_still_ambiguous():
    other = dict(_HOUSE, COUNTY_PIN="082823130132", Shape__Length=99.0)
    assert _lookup([_HOUSE, other]) is None


def test_the_same_area_with_another_perimeter_is_another_polygon():
    """The polygon key is area AND perimeter; matching on one is not enough."""
    assert mn._polygon_key(_HOUSE) != mn._polygon_key(dict(_HOUSE, Shape__Length=1.0))
    assert mn._polygon_key(_TOWER[0]) == mn._polygon_key(_TOWER[2])


def test_a_placeholder_polygon_is_not_a_candidate():
    got = _lookup([_PLACEHOLDER, _DAKOTA_NEW], county=_DAKOTA)
    assert got is not None and got.parcel_id == "120230003013"
    assert _lookup([_PLACEHOLDER], county=_DAKOTA) is None


# ── addresses ──────────────────────────────────────────────────────────────────


def test_a_spelled_out_quadrant_joins_the_matchers_abbreviation():
    """"Street Northwest" left unabbreviated keeps "st" in the name, and 34 of 39
    sampled Anoka homes failed to join "ST NW"."""
    got = _lookup([], near=[_CRANE], address="14544 CRANE ST NW, ANDOVER, MN, 55304",
                  county=_ANOKA)
    assert got is not None and got.year_built == 1997
    assert mn._street(_CRANE) == "14544 Crane st NW"


def test_a_directional_in_another_place_is_the_same_address():
    """St Paul's roll writes "Minnehaha Avenue West"; the matcher "W MINNEHAHA
    AVE". The same directional, so the same address — spelled or abbreviated."""
    got = _lookup([_MINNEHAHA], address="1478 W MINNEHAHA AVE, SAINT PAUL, MN, 55104")
    assert got is not None and got.year_built == 1911
    assert _lookup([_MINNEHAHA], address="1478 MINNEHAHA AVE WEST, SAINT PAUL, MN"
                   ).year_built == 1911


def test_a_directional_the_matcher_added_is_never_forgiven():
    """Recorded live: the roll's "1938 Jefferson Avenue" came back "1938 W JEFFERSON
    AVE". Forgiving it would also forgive the matcher dropping or swapping a
    directional, and grid twins sit kilometers apart, beyond any buffer check."""
    assert _lookup([_JEFFERSON], near=[_JEFFERSON],
                   address="1938 W JEFFERSON AVE, SAINT PAUL, MN, 55105") is None


def test_a_directional_the_matcher_dropped_is_never_forgiven():
    """1478 Minnehaha Ave W and 1478 Minnehaha Ave E are ~3 km apart. A matcher
    answer with the directional dropped could have placed the point at either."""
    assert _lookup([_MINNEHAHA], near=[_MINNEHAHA],
                   address="1478 MINNEHAHA AVE, SAINT PAUL, MN, 55104") is None
    assert not mn._agrees("1478 MINNEHAHA AVE, SAINT PAUL, MN", _MINNEHAHA)
    assert not mn._agrees("1938 E JEFFERSON AVE, SAINT PAUL, MN", _JEFFERSON)


def test_two_written_directionals_that_differ_never_agree():
    east = dict(_MINNEHAHA, ST_POS_DIR="East")
    assert _lookup([east], near=[east],
                   address="1478 W MINNEHAHA AVE, SAINT PAUL, MN, 55104") is None


def test_a_curve_is_one_street_however_the_matcher_spells_it():
    for spelling in ("1050 FALLS CURVE, CHASKA, MN, 55318",
                     "1050 FALLS CURV, CHASKA, MN, 55318"):
        got = _lookup([], near=[_CURVE], address=spelling, county=_CARVER)
        assert got is not None and got.year_built == 2001, spelling
    assert _lookup([], near=[_CURVE], address="1050 FALLS CT, CHASKA, MN, 55318",
                   county=_CARVER) is None


def test_a_county_road_matches_its_own_number_only():
    """The shared comparison reads "33" after "RD" as a unit; the road's number
    must appear in the query."""
    got = _lookup([], near=[_COUNTY_ROAD], address="15525 CO RD 33, HAMBURG, MN, 55339",
                  county=_CARVER)
    assert got is not None and got.year_built == 1890
    assert _lookup([], near=[_COUNTY_ROAD],
                   address="15525 CO RD 10, HAMBURG, MN, 55339", county=_CARVER) is None


def test_a_lettered_house_number_offers_no_address():
    assert mn._street(dict(_HOUSE, ANUMBERSUF="A")) is None
    assert mn._street(dict(_HOUSE, ANUMBERSUF="1/2")) == "414 1/2 Woodlawn ave"
    assert _lookup([dict(_HOUSE, ANUMBERSUF="A")],
                   address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105") is None


def test_a_neighbors_polygon_under_the_point_is_not_the_answer():
    neighbor = dict(_HOUSE, COUNTY_PIN="082823130130", ANUMBER=410, YEAR_BUILT=1925)
    got = _lookup([neighbor], near=[neighbor, _HOUSE],
                  address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105")
    assert got is not None and got.parcel_id == "082823130131"


# ── which records hold a home, and how many ────────────────────────────────────


def test_a_commercial_parcel_reports_nothing():
    assert _lookup([_ANOKA_COMMERCIAL], county=_ANOKA) is None


def test_a_garage_stall_on_its_own_reports_nothing():
    """Zero dwellings, said in words: the year would date a garage."""
    assert _lookup([_RAMSEY_GARAGE]) is None


def test_a_unit_count_of_zero_is_not_a_statement_of_no_dwelling():
    """Hennepin zeroes NUM_UNITS on every row; Dakota files 2025 houses with 0."""
    assert _lookup([_HENNEPIN_HOUSE], county=_HENNEPIN).year_built == 1939
    got = _lookup([_DAKOTA_NEW], county=_DAKOTA)
    assert (got.year_built, got.sqft, got.stories) == (2025, 1680, 2)


def test_a_duplex_reports_its_year_but_not_its_area_or_stories():
    got = _lookup([_DUPLEX], county=_DAKOTA)
    assert got.year_built == 1958
    assert got.sqft is None and got.stories is None


def test_area_is_never_divided_by_a_unit_count():
    got = _lookup([dict(_DUPLEX, DWELL_TYPE="S.fam.res")], county=_DAKOTA)
    assert got.sqft is None                   # NUM_UNITS 2 still vetoes


def test_a_record_that_says_nothing_about_dwellings_keeps_its_year_only():
    silent = dict(_HOUSE, USECLASS1="", DWELL_TYPE="", NUM_UNITS=None)
    got = _lookup([silent])
    assert got.year_built == 2006 and got.sqft is None and got.stories is None


def test_a_house_with_an_accessory_unit_is_not_one_dwelling():
    got = _lookup([dict(_HOUSE, DWELL_TYPE="SINGLE FAMILY W/ACCESSORY UNI")])
    assert got.year_built == 2006 and got.sqft is None


# ── the home style ─────────────────────────────────────────────────────────────


def test_only_whole_story_counts_are_read():
    cases = {"One Story": 1, "TWO STORY": 2, "2 Story Frame": 2, "3 Story": 3,
             "TOWNHOUSE, 2 STORY": 2, "Detached Townhome - 1 story": 1,
             "2 Story Townhouse": 2, "Rambler": 1,
             "1 1/2 Story Frame": None, "1-3/4 Stry": None, "1-2 Story": None,
             "Two+ Story": None, "Modified two story": None, "Split Level": None,
             "Bi-level": None, "BUNGALOW": None, "2 Story Condo": None,
             "CONDO-APT STYLE-3RD FLR": None, "Condo-TH Style-2 sty end unit": None}
    for style, want in cases.items():
        assert mn._stories(dict(_HOUSE, HOME_STYLE=style), unit_matched=False) == want, style


def test_only_wood_frame_is_read_as_a_wall_material():
    cases = {"1 Story Frame": "frame", "Split Foyer Frame": "frame",
             "2 Story Frame": "frame", "2 Story Brick": None, "1 Story A-Frame": None,
             "1 Story Metal Post Frame": None, "1 Story Log-Pine": None,
             "1 Story Earth": None, "Two Story": None, "": None}
    for style, want in cases.items():
        assert mn._construction(dict(_HOUSE, HOME_STYLE=style)) == want, style


def test_a_frame_house_reports_its_construction():
    got = _lookup([_STILLWATER],
                  address="2261 NORTHRIDGE AVENUE CIR N, STILLWATER, MN, 55082",
                  county=_WASHINGTON)
    assert got is not None
    assert (got.construction, got.stories, got.sqft) == ("frame", 1, 2572)


# ── the year ───────────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, YEAR_BUILT=0)])
    assert got is not None and got.year_built is None and got.sqft == 4350


def test_a_colonial_year_survives_and_the_floor_is_the_scorers():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert _lookup([dict(_HOUSE, YEAR_BUILT=1885)]).year_built == 1885
    below = _lookup([dict(_HOUSE, YEAR_BUILT=EARLIEST_PLAUSIBLE_YEAR - 1)])
    assert below.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_HOUSE, YEAR_BUILT=0, FIN_SQ_FT=0, HOME_STYLE="")
    assert _lookup([empty]) is None


# ── the request ────────────────────────────────────────────────────────────────


def test_the_field_list_is_explicit_and_carries_no_owner_or_sale_data():
    fields = mn._FIELDS.split(",")
    for private in ("*", "OWNER_NAME", "OWNER_MORE", "OWN_ADD_L1", "OWN_ADD_L2",
                    "OWN_ADD_L3", "OWN_ADD_L4", "TAX_NAME", "TAX_ADD_L1", "TAX_ADD_L2",
                    "TAX_ADD_L3", "TAX_ADD_L4", "SALE_DATE", "SALE_VALUE", "HOMESTEAD",
                    "EMV_LAND", "EMV_BLDG", "EMV_TOTAL", "TOTAL_TAX", "TAX_CAPAC"):
        assert private not in fields, private
    assert "BASEMENT" not in fields


def test_the_requested_fields_are_what_reaches_the_service():
    params, urls = [], []
    _lookup([], near=[_HOUSE], address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105",
            params=params, urls=urls)
    assert len(params) == 2
    assert all(p["outFields"] == mn._FIELDS for p in params)
    assert all(p.get("outSR") == "4326" and p["returnGeometry"] == "false" for p in params)
    assert params[1]["distance"] == str(_shared.SEARCH_RADIUS_M)
    assert urls == [mn.url_for(_RAMSEY)] * 2


def test_each_county_reads_its_own_layer():
    assert mn.url_for("27053").endswith("/Parcels/FeatureServer/3/query")
    assert mn.url_for("27003").endswith("/Parcels/FeatureServer/0/query")
    assert len({mn.url_for(f) for f in mn.COUNTY_FIPS}) == 7
    assert mn.url_for("27109") is None
    urls = []
    _lookup([_HENNEPIN_HOUSE], county=_HENNEPIN, urls=urls)
    assert urls == [mn.url_for(_HENNEPIN)]


def test_without_a_county_the_point_is_routed_by_tigerweb():
    urls = []
    got = _lookup([_HOUSE], county=None, tiger="27123", urls=urls)
    assert got is not None and got.year_built == 2006
    assert "tigerweb" in urls[0] and urls[1] == mn.url_for(_RAMSEY)
    assert _lookup([_HOUSE], county=None, tiger="27109") is None


def test_a_truncated_response_is_refused_rather_than_read():
    """The layer stops at 2,000 records. Losing one of two parcels at one address
    would turn "ambiguous" into a confident wrong answer."""
    assert _lookup([], near=[_HOUSE], address="414 WOODLAWN AVE, SAINT PAUL, MN, 55105",
                   extra={"exceededTransferLimit": True}) is None


# ── coverage ───────────────────────────────────────────────────────────────────


def test_the_seven_metro_counties_are_covered_and_no_other_county_is():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)}
    metro = {"27003", "27019", "27037", "27053", "27123", "27139", "27163"}
    assert metro <= census
    assert mn.COUNTY_FIPS == metro


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_shared_read_slice_reaches_the_transport():
    slices = []
    assert _lookup([_HOUSE], slices=slices) is not None
    assert slices and all(s == mn.READ_SLICE_S for s in slices)


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert mn.LOOKUP_TIMEOUT + mn.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    mn._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        mn.lookup(*_POINT, "414 WOODLAWN AVE, SAINT PAUL, MN, 55105", county_fips=_RAMSEY)
    finally:
        _shared.get_json = saved
        mn._lookup_cached.cache_clear()
    assert len(seen) == 2 and seen[0] == seen[1]
    assert abs((seen[0] - started) - mn.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error")

    mn._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert mn.lookup(*_POINT, "414 WOODLAWN AVE, SAINT PAUL, MN, 55105",
                         county_fips=_RAMSEY) is None
    finally:
        _shared.get_json = saved
        mn._lookup_cached.cache_clear()


def test_a_malformed_body_fails_open():
    def junk(url, request, deadline, read_slice=None):
        return {"features": [None, {"attributes": None},
                             {"attributes": {"COUNTY_PIN": 7, "YEAR_BUILT": "x"}}]}

    mn._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = junk
    try:
        assert mn.lookup(*_POINT, county_fips=_RAMSEY) is None
    finally:
        _shared.get_json = saved
        mn._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
