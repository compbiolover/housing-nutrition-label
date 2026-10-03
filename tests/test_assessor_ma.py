#!/usr/bin/env python3
"""The Massachusetts adapter — one statewide layer, and the stacked records on it.

Nothing here touches the network. MassGIS's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Massachusetts has no record here" and would never announce itself.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Massachusetts's own:

1. **Stacked records.** One polygon carries every assessor record on the lot — a
   condominium's units and its master record, a townhouse development's houses —
   and the shared chooser refuses more than one containing record. The adapter
   groups by polygon first, and picks the record by address and unit, never by
   position.
2. **The DOR use code** decides whether a record is a home, and ``UNITS`` cannot:
   towns write 0 for "not recorded" on 619,056 single-family records.
3. **``STORIES`` is a code table** in three towns.
4. **A truncated response** can remove one of two parcels at one address.

This file alone: ``pytest tests/test_assessor_ma.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

from housing_label.enrich.assessor import _shared, ma

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Recorded live. A Westford single-family house: one dwelling, one record, so its
# residential area and storey count are that home's.
_HOUSE = {"LOC_ID": "F_668355_3050015", "PROP_ID": "071 0036 0000", "TOWN_ID": 330,
          "USE_CODE": "101", "SITE_ADDR": "57  DUNSTABLE RD", "ADDR_NUM": "57",
          "FULL_STR": "DUNSTABLE RD", "LOCATION": None, "YEAR_BUILT": 1933,
          "RES_AREA": 1840, "UNITS": 1, "STORIES": "2", "FY": 2025}

# Recorded live: 17 Durham St, Boston — one polygon, six records. Five condominium
# units carrying the unit in LOCATION, and the association's master record coded
# 995 ("Other, Open Space" in the DOR booklet; Boston uses it for the condo main).
_LOC = "F_769452_2950518"


def _unit(n, area):
    return {"LOC_ID": _LOC, "PROP_ID": f"04024230{10 + 2 * n}", "TOWN_ID": 35,
            "USE_CODE": "102", "SITE_ADDR": f"17 DURHAM ST {n}", "ADDR_NUM": "17",
            "FULL_STR": "DURHAM ST", "LOCATION": str(n), "YEAR_BUILT": 1880,
            "RES_AREA": area, "UNITS": 1, "STORIES": "1", "FY": 2023}


_MASTER = {"LOC_ID": _LOC, "PROP_ID": "0402423010", "TOWN_ID": 35, "USE_CODE": "995",
           "SITE_ADDR": "17 DURHAM ST", "ADDR_NUM": "17", "FULL_STR": "DURHAM ST",
           "LOCATION": None, "YEAR_BUILT": 1880, "RES_AREA": 0, "UNITS": 5,
           "STORIES": "4", "FY": 2023}
_STACK = [_unit(1, 1217), _unit(2, 1016), _unit(3, 1123), _unit(4, 1117),
          _unit(5, 1217), _MASTER]

# Recorded live: a Grafton townhouse condominium — one polygon, each home at its
# own street number with no unit designator, and two construction phases.
_GRAFTON = "F_594429_2904429"
_TOWNHOUSES = [
    {"LOC_ID": _GRAFTON, "PROP_ID": "043.0-3206-0002.J", "TOWN_ID": 110,
     "USE_CODE": "1020", "SITE_ADDR": "56 JOHN DRIVE", "ADDR_NUM": "56",
     "FULL_STR": "JOHN DRIVE", "LOCATION": None, "YEAR_BUILT": 1996,
     "RES_AREA": 1604, "UNITS": 0, "STORIES": "0", "FY": 2025},
    {"LOC_ID": _GRAFTON, "PROP_ID": "043.0-2607-0002.J", "TOWN_ID": 110,
     "USE_CODE": "1020", "SITE_ADDR": "30 JOHN DRIVE", "ADDR_NUM": "30",
     "FULL_STR": "JOHN DRIVE", "LOCATION": None, "YEAR_BUILT": 1996,
     "RES_AREA": 1770, "UNITS": 0, "STORIES": "0", "FY": 2025},
    {"LOC_ID": _GRAFTON, "PROP_ID": "043.0-4506-0002.E", "TOWN_ID": 110,
     "USE_CODE": "1020", "SITE_ADDR": "43 EDWARD DRIVE", "ADDR_NUM": "43",
     "FULL_STR": "EDWARD DRIVE", "LOCATION": None, "YEAR_BUILT": 2003,
     "RES_AREA": 1651, "UNITS": 0, "STORIES": "0", "FY": 2025},
]

#: A point in Westford. Which records a coordinate lands in is decided here by the
#: stubbed rows, not by the coordinate.
_POINT = (42.5793, -71.4378)


def _lookup(exact, near=(), address=None, slices=None, params=None, extra=None):
    """Drive ``ma.lookup()`` over recorded rows, through the real transport call.

    ``exact`` is what the point lands inside; ``near`` is what the 80 m buffer
    finds. ``extra`` is merged into every response body.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": dict(a)} for a in rows], **(extra or {})}

    ma._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return ma.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        ma._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_year_area_and_storeys():
    got = _lookup([_HOUSE], address="57 DUNSTABLE RD, WESTFORD, MA, 01886")
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1933, 1840, 2)
    assert got.parcel_id == "071 0036 0000"
    assert got.construction is None and got.foundation is None and got.condition is None


def test_a_house_found_by_the_buffer_reports_the_same():
    """The geocoder often lands in the roadway; the buffer is anchored on the
    address."""
    got = _lookup([], near=[_HOUSE], address="57 DUNSTABLE RD, WESTFORD, MA")
    assert got is not None and got.year_built == 1933


def test_the_fiscal_year_travels_with_the_value():
    got = _lookup([_HOUSE])
    assert got is not None and got.data_vintage.endswith("FY2025 assessment")
    bare = _lookup([dict(_HOUSE, FY=None)])
    assert bare is not None and bare.data_vintage == ma.DATA_VINTAGE


# ── stacked records ────────────────────────────────────────────────────────────


def test_a_condominium_stack_with_a_unit_reports_that_units_area():
    """Six records on one polygon. The shared chooser alone would refuse them all;
    grouped by polygon, the reader's unit picks one record, whose RES_AREA is the
    unit's own deeded area."""
    got = _lookup(_STACK, address="17 DURHAM ST #3, BOSTON, MA, 02120")
    assert got is not None
    assert (got.year_built, got.sqft, got.parcel_id) == (1880, 1123, "0402423016")
    assert got.stories is None, "a condominium's storey count is never reported"


def test_a_condominium_stack_without_a_unit_reports_only_the_buildings_year():
    """Every unit agrees on 1880, so the year is right for whichever unit the
    reader lives in. The area is right for at most one of them."""
    got = _lookup(_STACK, address="17 DURHAM ST, BOSTON, MA, 02120")
    assert got is not None
    assert got.year_built == 1880 and got.sqft is None and got.stories is None
    assert got.parcel_id == _LOC


def test_a_unit_the_roll_does_not_have_falls_back_to_the_building():
    got = _lookup(_STACK, address="17 DURHAM ST #9, BOSTON, MA")
    assert got is not None and got.year_built == 1880 and got.sqft is None


def test_the_master_record_cannot_veto_the_units():
    """Boston's master record for 180 Marlborough St carries 1999 — the conversion
    — on an 1890 building. It is not anyone's home, so it is dropped from the stack
    before the vote."""
    stack = [dict(r, YEAR_BUILT=1890) for r in _STACK[:-1]] + [dict(_MASTER, YEAR_BUILT=1999)]
    got = _lookup(stack, address="17 DURHAM ST, BOSTON, MA")
    assert got is not None and got.year_built == 1890


def test_units_that_disagree_on_a_year_give_no_answer():
    stack = [dict(_STACK[0], YEAR_BUILT=1880), dict(_STACK[1], YEAR_BUILT=1985)]
    assert _lookup(stack, address="17 DURHAM ST, BOSTON, MA") is None


def test_a_townhouse_is_picked_by_its_own_street_number():
    """One polygon, a dozen houses, each with its own number and no unit. The
    address identifies the dwelling, so its year and its own area come through —
    and the other phase's year does not leak in."""
    got = _lookup(_TOWNHOUSES, address="43 EDWARD DR, GRAFTON, MA, 01519")
    assert got is not None
    assert (got.year_built, got.sqft) == (2003, 1651)
    assert got.parcel_id == "043.0-4506-0002.E"


def test_a_townhouse_development_without_an_address_has_no_single_year():
    """Two phases on one polygon: with nothing to pick a house, there is no year
    true of the whole polygon."""
    assert _lookup(_TOWNHOUSES) is None


def test_a_condo_record_sharing_its_number_with_a_neighbour_keeps_no_area():
    """Holyoke files "2 A ARBOR WY" and "2 C ARBOR WY" as separate records whose
    split address is just "2 ARBOR WY". The unit letter sits between the number and
    the street, so the free-text form does not parse alike and that record offers
    no address — which leaves a single record agreeing with "2 ARBOR WAY" while
    another home on the polygon shares its number. An address two homes share does
    not identify either one, so the area is refused and the year kept."""
    a = {"LOC_ID": "F_356456_2904128", "PROP_ID": "007-01-402A", "TOWN_ID": 137,
         "USE_CODE": "102", "SITE_ADDR": "2 ARBOR WY", "ADDR_NUM": "2",
         "FULL_STR": "ARBOR WY", "LOCATION": None, "YEAR_BUILT": 1978,
         "RES_AREA": 738, "UNITS": 1, "STORIES": "1", "FY": 2026}
    c = dict(a, PROP_ID="007-01-402C", SITE_ADDR="2 C ARBOR WY", RES_AREA=644)
    assert ma._address_of(c) is None
    got = _lookup([a, c], address="2 ARBOR WAY, HOLYOKE, MA")
    assert got is not None and got.year_built == 1978 and got.sqft is None
    alone = _lookup([a], address="2 ARBOR WAY, HOLYOKE, MA")
    assert alone is not None and alone.sqft == 738, "the rule, not the fixture, refused it"


def test_way_abbreviated_wy_matches_and_still_not_another_type():
    assert _shared.same_address("2 ARBOR WAY", ma._normalise("2 ARBOR WY"))
    assert not _shared.same_address("2 ARBOR ST", ma._normalise("2 ARBOR WY"))
    assert ma._normalise("12 MAIN ST (HYANNIS)") == "12 MAIN ST"


def test_the_rolls_spellings_become_the_matchers_spellings():
    """Each pair recorded live: the roll's spelling, then what the Census matcher
    returned for it. Unmatched, every one of these homes read as "no record"."""
    for roll, census in (("1114 NO MAIN ST", "1114 N MAIN ST"),
                         ("1661 NO. BROOKFIELD ROAD", "1661 N BROOKFIELD RD"),
                         ("624 BOSTON POST RD EAST #10", "624 BOSTON POST RD E"),
                         ("59 BOUNDARY CR", "59 BOUNDARY CIR"),
                         ("21 THAYER CI", "21 THAYER CIR"),
                         ("15 FIFTH ST", "15 5TH ST"),
                         ("10 EAST BROADWAY", "10 E BROADWAY")):
        assert _shared.same_address(census, ma._normalise(roll)), roll


def test_a_directional_that_is_the_streets_name_is_left_alone():
    """"NORTH ST" is a street called North; abbreviating it would make it equal to
    a street called "N"."""
    assert ma._normalise("21 NORTH ST") == "21 NORTH ST"
    assert ma._normalise("5 EAST AVE") == "5 EAST AVE"
    assert not _shared.same_address("21 N ST", ma._normalise("21 NORTH ST"))
    assert not _shared.same_address("1114 S MAIN ST", ma._normalise("1114 NO MAIN ST"))


def test_a_master_record_with_a_local_code_cannot_stand_in_for_the_units():
    """Cambridge files condominium masters under its own code 199. The master for
    35 Washburn Ave says 1916; its units, whose free-text address "33-35 WASHBURN
    AVE" does not parse, say 1873. Kept as a member, the master was the only record
    agreeing with "35 WASHBURN AVE" and answered for the units — measured in the
    verification run. Where any record on the polygon is a documented home, a
    record whose code says nothing does not take part."""
    loc = "F_755781_2970903"
    master = {"LOC_ID": loc, "PROP_ID": "184-38", "TOWN_ID": 49, "USE_CODE": "199",
              "SITE_ADDR": "35 WASHBURN AVE", "ADDR_NUM": "35",
              "FULL_STR": "WASHBURN AVE", "LOCATION": None, "YEAR_BUILT": 1916,
              "RES_AREA": None, "UNITS": 3, "STORIES": "3", "FY": 2026}
    units = [{"LOC_ID": loc, "PROP_ID": f"184-38-{n}", "TOWN_ID": 49, "USE_CODE": "102",
              "SITE_ADDR": "33-35 WASHBURN AVE", "ADDR_NUM": "33-35",
              "FULL_STR": "WASHBURN AVE", "LOCATION": None, "YEAR_BUILT": 1873,
              "RES_AREA": 956, "UNITS": None, "STORIES": "1", "FY": 2026}
             for n in (1, 2, 3)]
    assert _lookup([master, *units], address="35 WASHBURN AVE #1, CAMBRIDGE, MA") is None
    alone = _lookup([master], address="35 WASHBURN AVE, CAMBRIDGE, MA")
    assert alone is not None and alone.year_built == 1916, "alone, it is the record"


def test_two_polygons_containing_the_point_are_still_ambiguous():
    """Grouping is by polygon, so it can never merge two polygons into one."""
    other = dict(_HOUSE, LOC_ID="F_668355_3050099", PROP_ID="071 0036 0001")
    assert _lookup([_HOUSE, other], address="57 DUNSTABLE RD, WESTFORD, MA") is None
    assert _lookup([_HOUSE, other]) is None


def test_two_polygons_at_the_address_within_the_buffer_are_refused():
    other = dict(_HOUSE, LOC_ID="F_668355_3050099", PROP_ID="071 0036 0001")
    assert _lookup([], near=[_HOUSE, other],
                   address="57 DUNSTABLE RD, WESTFORD, MA") is None


def test_a_neighbours_polygon_under_the_point_is_not_the_answer():
    neighbour = dict(_HOUSE, PROP_ID="X", SITE_ADDR="59 DUNSTABLE RD", ADDR_NUM="59",
                     LOC_ID="F_1", YEAR_BUILT=1999)
    got = _lookup([neighbour], near=[neighbour, _HOUSE],
                  address="57 DUNSTABLE RD, WESTFORD, MA")
    assert got is not None and got.year_built == 1933


def test_a_record_whose_two_addresses_name_different_buildings_has_none():
    """Springfield writes "24-26" as ADDR_NUM "2426" against SITE_ADDR "24 MALDEN
    ST". A record that contradicts itself cannot confirm a parcel."""
    row = dict(_HOUSE, SITE_ADDR="24 MALDEN ST", ADDR_NUM="2426", FULL_STR="MALDEN ST")
    assert ma._address_of(row) is None
    assert _lookup([], near=[row], address="24 MALDEN ST, SPRINGFIELD, MA") is None


def test_a_polygon_with_no_assessor_record_is_not_a_candidate():
    """The layer includes polygons the town never linked to its roll."""
    blank = {"LOC_ID": _HOUSE["LOC_ID"], "PROP_ID": None, "USE_CODE": None}
    got = _lookup([_HOUSE, dict(blank, LOC_ID="F_other")],
                  address="57 DUNSTABLE RD, WESTFORD, MA")
    assert got is not None and got.year_built == 1933


# ── the one-dwelling rule ──────────────────────────────────────────────────────


def test_a_two_family_reports_its_year_but_not_its_area_or_storeys():
    """104 is two homes: the area covers both."""
    got = _lookup([dict(_HOUSE, USE_CODE="104", UNITS=2, RES_AREA=2968)])
    assert got is not None and got.year_built == 1933
    assert got.sqft is None and got.stories is None


def test_a_single_family_record_claiming_several_units_keeps_no_area():
    got = _lookup([dict(_HOUSE, UNITS=3)])
    assert got is not None and got.year_built == 1933
    assert got.sqft is None and got.stories is None


def test_units_of_zero_is_not_a_statement_of_no_dwelling():
    """619,056 single-family records carry UNITS = 0 — a town's "not recorded"."""
    got = _lookup([dict(_HOUSE, UNITS=0)])
    assert got is not None and (got.year_built, got.sqft) == (1933, 1840)


def test_a_locally_suffixed_code_keeps_its_year_and_loses_its_area():
    """The fourth character is a town's own subdivision with no published meaning;
    "1010" is the padded form of 101 and is not one."""
    padded = _lookup([dict(_HOUSE, USE_CODE="1010")])
    assert padded is not None and padded.sqft == 1840
    local = _lookup([dict(_HOUSE, USE_CODE="1013")])
    assert local is not None and local.year_built == 1933
    assert local.sqft is None and local.stories is None


def test_area_is_never_divided_by_a_unit_count():
    got = _lookup([dict(_HOUSE, USE_CODE="111", UNITS=6, RES_AREA=6000)])
    assert got is not None and got.sqft is None


# ── the zero-dwelling rule ─────────────────────────────────────────────────────


def test_a_record_the_dor_code_says_holds_no_home_reports_nothing():
    for code in ("325", "3250", "106", "132", "201", "400", "601", "960", "996", "034"):
        assert _lookup([dict(_HOUSE, USE_CODE=code)]) is None, code


def test_a_code_that_says_nothing_lets_the_year_through_but_not_the_area():
    """108 is "intentionally left blank" in the DOR booklet and used 8,226 times
    anyway; silence is not a statement of no dwelling."""
    for code in ("108", "199", "0101", "", None):
        got = _lookup([dict(_HOUSE, USE_CODE=code)])
        assert got is not None and got.year_built == 1933, code
        assert got.sqft is None, code


def test_mixed_use_with_a_residential_class_is_a_home():
    for code in ("013", "031", "0130", "021"):
        assert ma._says_a_home_is_here({"USE_CODE": code}) is True, code
    assert ma._says_a_home_is_here({"USE_CODE": "034"}) is False


def test_exempt_housing_codes_are_homes():
    for code in ("970", "945", "959", "961"):
        assert ma._says_a_home_is_here({"USE_CODE": code}) is True, code
    assert ma._says_a_home_is_here({"USE_CODE": "931"}) is None


# ── storeys ────────────────────────────────────────────────────────────────────


def test_storeys_in_a_town_that_writes_a_code_table_are_not_read():
    """Medfield's single-family houses are "7", "8" and "14" storeys."""
    medfield = dict(_HOUSE, TOWN_ID=175, STORIES="7")
    got = _lookup([medfield])
    assert got is not None and got.stories is None and got.sqft == 1840
    assert _lookup([dict(medfield, STORIES="2")]).stories is None


def test_half_storeys_and_letters_are_not_rounded():
    for raw in ("1.5", "1.75", "2A", "1T", "0", "5", None):
        got = _lookup([dict(_HOUSE, STORIES=raw)])
        assert got is not None and got.stories is None, raw
    assert _lookup([dict(_HOUSE, STORIES="02")]).stories == 2
    assert _lookup([dict(_HOUSE, STORIES="2.00")]).stories == 2


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, YEAR_BUILT=0)])
    assert got is not None and got.year_built is None and got.sqft == 1840


def test_a_colonial_year_survives_and_the_floor_is_the_scorers():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    got = _lookup([dict(_HOUSE, YEAR_BUILT=1690)])
    assert got is not None and got.year_built == 1690
    below = _lookup([dict(_HOUSE, YEAR_BUILT=EARLIEST_PLAUSIBLE_YEAR - 1)])
    assert below is not None and below.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_HOUSE, YEAR_BUILT=None, RES_AREA=0, STORIES=None)
    assert _lookup([empty]) is None


# ── the request ────────────────────────────────────────────────────────────────


def test_the_field_list_is_explicit_and_carries_no_owner_or_sale_data():
    fields = ma._FIELDS.split(",")
    for private in ("*", "OWNER1", "OWN_ADDR", "OWN_CITY", "OWN_STATE", "OWN_ZIP",
                    "OWN_CO", "LS_DATE", "LS_PRICE", "LS_BOOK", "LS_PAGE", "REG_ID",
                    "BLDG_VAL", "LAND_VAL", "OTHER_VAL", "TOTAL_VAL"):
        assert private not in fields, private
    assert "STYLE" not in fields and "BLD_AREA" not in fields


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([], near=[_HOUSE], address="57 DUNSTABLE RD, WESTFORD, MA", params=params)
    assert len(params) == 2
    assert all(p["outFields"] == ma._FIELDS for p in params)
    assert all(p.get("outSR") == "4326" and p["returnGeometry"] == "false" for p in params)
    assert params[1]["distance"] == str(_shared.SEARCH_RADIUS_M)


def test_a_truncated_response_is_refused_rather_than_read():
    """The layer stops at 2,000 records. Losing one of two parcels at one address
    would turn "ambiguous" into a confident wrong answer."""
    other = dict(_HOUSE, LOC_ID="F_2", PROP_ID="Y")
    assert _lookup([], near=[_HOUSE], address="57 DUNSTABLE RD, WESTFORD, MA",
                   extra={"exceededTransferLimit": True}) is None
    assert other  # the parcel the truncation could have hidden


# ── coverage ───────────────────────────────────────────────────────────────────


def test_every_massachusetts_county_is_covered_and_no_other_county_is():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("25") and len(r["geoid"]) == 5}
    assert len(census) == 14
    assert ma.COUNTY_FIPS == census


# ── the clock ──────────────────────────────────────────────────────────────────


def test_massachusetts_asks_for_its_own_read_slice():
    """Bristol County's buffered queries take 3.5–5 s; under the shared 1 s slice
    they read as "no record"."""
    slices = []
    assert _lookup([_HOUSE], slices=slices) is not None
    assert slices and all(s == ma.READ_SLICE_S for s in slices)
    assert ma.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert ma.LOOKUP_TIMEOUT + ma.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET
    assert ma.LOOKUP_TIMEOUT > ma.READ_SLICE_S, "room for containment plus a slow buffer"


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    ma._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        ma.lookup(*_POINT, "57 DUNSTABLE RD, WESTFORD, MA")
    finally:
        _shared.get_json = saved
        ma._lookup_cached.cache_clear()
    assert len(seen) == 2 and seen[0] == seen[1]
    assert abs((seen[0] - started) - ma.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error")

    ma._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert ma.lookup(*_POINT, "57 DUNSTABLE RD, WESTFORD, MA") is None
    finally:
        _shared.get_json = saved
        ma._lookup_cached.cache_clear()


def test_a_malformed_body_fails_open():
    def junk(url, request, deadline, read_slice=None):
        return {"features": [None, {"attributes": None}, {"attributes": {"PROP_ID": 7}}]}

    ma._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = junk
    try:
        assert ma.lookup(*_POINT) is None
    finally:
        _shared.get_json = saved
        ma._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
