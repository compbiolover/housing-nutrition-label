#!/usr/bin/env python3
"""The New York City adapter — one tax-lot layer, and the things it has to refuse.

Nothing here touches the network. DCP's MapPLUTO service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"New York has no record here" and would never announce itself. A test that called
the real service would pass just as quietly.

What is worth pinning is what is genuinely New York's. The dangerous shared parts —
choosing which lot an address means, comparing two addresses, bounding the request
budget — live in ``_shared`` and are tested against Cook in ``test_assessor.py``.

New York's own four:

1. **Two spellings of every address.** Queens house numbers are hyphenated, PLUTO
   drops ordinals the Census matcher keeps, and directions are spelled out on one
   side and abbreviated on the other. Without reconciling them almost nothing
   confirms — and the reconciliation must not let two different houses match.
2. **The condo trap is severe.** A 655-unit tower is one lot with one gross floor
   area, and PLUTO also holds unit lots with a unit's area on a one-unit count.
3. **The basement code** maps onto the label's foundation only in part, and only
   for the classes the city maintains it for.
4. **Placeholder polygons** — DCP mapping lots with a BBL and nothing else.

This file alone: ``pytest tests/test_assessor_nyc.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, nyc

# Recorded live from MapPLUTO 26v2. A one-family house in Forest Hills, Queens: one
# unit, one building, class A5 — so its floor area and floor count are that home's.
_HOUSE = {"BBL": 4032040021, "Address": "68-40 CLYDE STREET", "YearBuilt": 1930,
          "NumFloors": 3, "BldgArea": 1638, "AreaSource": "2", "UnitsRes": 1,
          "NumBldgs": 1, "BsmtCode": "2", "BldgClass": "A5", "Version": "26v2",
          "PLUTOMapID": "1"}

# Recorded live. 20 West 64th Street: a condominium billing lot, which is how
# MapPLUTO draws a whole tower — 655 units, one gross area for all of them.
_TOWER = {"BBL": 1011167501, "Address": "20 WEST 64 STREET", "YearBuilt": 1970,
          "NumFloors": 42, "BldgArea": 973738, "AreaSource": "2", "UnitsRes": 655,
          "NumBldgs": 1, "BsmtCode": "5", "BldgClass": "RM", "Version": "26v2",
          "PLUTOMapID": "1"}

# Recorded live from the PLUTO table (Socrata 64uk-42ks, 26v2), mapped onto the
# layer's column names. A condominium UNIT lot PLUTO could not yet roll up to a
# billing lot: one residential unit, and the unit's own area on it.
_UNIT_LOT = {"BBL": 1009231163, "Address": "350 EAST 18TH STREET", "YearBuilt": 0,
             "NumFloors": None, "BldgArea": 2287, "AreaSource": "2", "UnitsRes": 1,
             "NumBldgs": None, "BsmtCode": None, "BldgClass": "R4",
             "Version": "26v2", "PLUTOMapID": "1"}

# Recorded live. A newly declared condominium billing lot whose units Finance has
# not yet counted: UnitsRes is null, and the area is DCP's calculation (source 5).
_NEW_CONDO = {"BBL": 1009237502, "Address": "350 EAST 18TH STREET",
              "YearBuilt": 2024, "NumFloors": 13, "BldgArea": 95680,
              "AreaSource": "5", "UnitsRes": None, "NumBldgs": 1, "BsmtCode": "5",
              "BldgClass": "R0", "Version": "26v2", "PLUTOMapID": "1"}

# Recorded live. A Brooklyn house with a store: one residential unit, one
# building — and a gross area that includes the shop.
_HOUSE_AND_STORE = {"BBL": 3000330025, "Address": "52 HUDSON AVENUE",
                    "YearBuilt": 1831, "NumFloors": 3, "BldgArea": 2960,
                    "AreaSource": "2", "UnitsRes": 1, "NumBldgs": 1, "BsmtCode": "2",
                    "BldgClass": "S1", "Version": "26v2", "PLUTOMapID": "1"}

# Recorded live. A one-family house with a second structure on the lot (a garage):
# NumBldgs 2, so BldgArea covers both.
_HOUSE_AND_GARAGE = {"BBL": 4087860042, "Address": "84-74 257 STREET",
                     "YearBuilt": 1945, "NumFloors": 2, "BldgArea": 1864,
                     "AreaSource": "2", "UnitsRes": 1, "NumBldgs": 2,
                     "BsmtCode": "2", "BldgClass": "A1", "Version": "26v2",
                     "PLUTOMapID": "1"}

# Recorded live. A two-family house in the Bronx.
_TWO_FAMILY = {"BBL": 2044450005, "Address": "913 MACE AVENUE", "YearBuilt": 1935,
               "NumFloors": 2, "BldgArea": 2923, "AreaSource": "2", "UnitsRes": 2,
               "NumBldgs": 1, "BsmtCode": "1", "BldgClass": "B1", "Version": "26v2",
               "PLUTOMapID": "1"}

# Recorded live. A store building in Queens with no residential units.
_SHOP = {"BBL": 4000790029, "Address": "23-10 44 DRIVE", "YearBuilt": 1963,
         "NumFloors": 1, "BldgArea": 2500, "AreaSource": "2", "UnitsRes": 0,
         "NumBldgs": 1, "BsmtCode": "0", "BldgClass": "K1", "Version": "26v2",
         "PLUTOMapID": "1"}

# Recorded live. A DCP mapping lot: on Finance's tax map, not in PLUTO.
_MAPPING_LOT = {"BBL": 1000110028, "Address": None, "YearBuilt": None,
                "NumFloors": None, "BldgArea": None, "AreaSource": None,
                "UnitsRes": None, "NumBldgs": None, "BsmtCode": None,
                "BldgClass": None, "Version": "26v2", "PLUTOMapID": "3"}

#: A point in Queens. Every test uses the same one: which lot a coordinate lands in
#: is decided here by the stubbed rows, not by the coordinate.
_POINT = (40.7346, -73.7105)

_CLYDE = "68-40 CLYDE ST, FOREST HILLS, NY, 11375"   # as the Census matcher writes it


def _lookup(exact, near=(), address=None, slices=None, params=None):
    """Drive ``nyc.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find. Both are answered through the real transport helper, so the field
    list, the placeholder filter, the address rewrite and the lot choice are all
    exercised rather than stepped over.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    nyc._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return nyc.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        nyc._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_everything_the_lot_records():
    got = _lookup([_HOUSE], address=_CLYDE)
    assert got is not None
    assert got.parcel_id == "4032040021", "the BBL, without ArcGIS's trailing .0"
    assert got.year_built == 1930
    assert got.sqft == 1638.0
    assert got.stories == 3
    assert got.foundation == "full-basement"
    assert got.construction is None and got.condition is None, (
        "PLUTO carries no wall material and no condition grade")


def test_the_release_travels_with_the_value():
    """DCP republishes quarterly under one URL; a hard-coded release would go
    stale silently."""
    got = _lookup([_HOUSE])
    assert got is not None and got.data_vintage.endswith("release 26v2")
    bare = _lookup([dict(_HOUSE, Version=None)])
    assert bare is not None and bare.data_vintage == nyc.DATA_VINTAGE


# ── two spellings of every address ─────────────────────────────────────────────


def test_a_queens_hyphenated_house_number_confirms():
    """``address_key`` anchors on an all-digit first token and returns None for
    "68-40". Without the rewrite, no Queens address could confirm a lot from the
    buffer — and the Census matcher puts a great many of them in the roadway."""
    assert _shared.address_key("68-40 CLYDE ST") is None, "the problem being solved"
    got = _lookup([], near=[_HOUSE], address=_CLYDE)
    assert got is not None and got.parcel_id == "4032040021"


def test_the_hyphen_goes_but_both_halves_of_the_number_stay():
    """84-74 and 84-76 are next-door houses on one street; 84-74 and 85-74 are a
    block apart. Dropping either half of the number would make them the same house.
    Removing only the hyphen keeps every digit."""
    for a, b in (("84-74 257 ST", "84-76 257 STREET"),
                 ("84-74 257 ST", "85-74 257 STREET"),
                 ("84-74 257 ST", "74 257 STREET"),
                 ("84-74 257 ST", "84 257 STREET"),
                 ("84-7 257 ST", "847 257 STREET")):
        assert not _shared.same_address(nyc._street_form(a), nyc._street_form(b)), (a, b)


def test_the_two_sources_disagree_about_where_the_hyphen_goes():
    """Recorded live: PLUTO writes the Rockaways plain and the Census matcher
    hyphenates them; Ridgewood the other way round; and one Cambria Heights lot is
    hyphenated in the wrong place. Each pair is one house."""
    for census, pluto in (("4-32 BEACH 48TH ST, FAR ROCKAWAY, NY", "432 BEACH 48 STREET"),
                          ("611 BEACH 68TH ST, ARVERNE, NY", "6-11 BEACH 68 STREET"),
                          ("1875 STANHOPE ST, RIDGEWOOD, NY", "18-75 STANHOPE STREET"),
                          ("114-106 230TH ST, CAMBRIA HEIGHTS, NY", "1141-06 230 STREET"),
                          ("84-07 257TH ST", "84-7 257 STREET")):
        assert _shared.same_address(nyc._street_form(census),
                                    nyc._street_form(pluto)), (census, pluto)


def test_a_wrong_queens_neighbor_in_the_buffer_is_not_taken():
    """The buffer finds every lot within 80 m; the address must pick exactly one."""
    neighbor = dict(_HOUSE, BBL=4032040022, Address="68-42 CLYDE STREET",
                     YearBuilt=1931)
    got = _lookup([], near=[neighbor, _HOUSE], address=_CLYDE)
    assert got is not None and got.parcel_id == "4032040021" and got.year_built == 1930
    assert _lookup([], near=[neighbor], address=_CLYDE) is None


def test_ordinals_and_directions_are_spelled_one_way_on_both_sides():
    """PLUTO writes "203 WEST 131 STREET"; the Census matcher "203 W 131ST ST"."""
    pairs = [
        ("203 W 131ST ST, NEW YORK, NY, 10027", "203 WEST 131 STREET"),
        ("1870 3RD AVE, NEW YORK, NY, 10029", "1870 3 AVENUE"),
        ("29 PROSPECT PARK W, BROOKLYN, NY, 11215", "29 PROSPECT PARK WEST"),
        ("238 FORT WASHINGTON AVE, NEW YORK, NY", "238 FT WASHINGTON AVENUE"),
        ("451 FATHER CAPODANNO BLVD, STATEN ISLAND, NY", "451 FATHER CAPODANNO BL"),
        ("1234 AVE J, BROOKLYN, NY", "1234 AVENUE J"),
        ("350 E 18TH ST, BROOKLYN, NY, 11226", "350 EAST 18 STREET"),
    ]
    for census, pluto in pairs:
        assert _shared.same_address(nyc._street_form(census),
                                    nyc._street_form(pluto)), (census, pluto)


def test_the_rewrite_does_not_join_different_streets_or_numbers():
    """The rewrite runs on both sides and can only make two spellings of one
    address equal. Every distinction the shared comparison draws must survive it."""
    for a, b in (("203 W 131ST ST", "203 EAST 131 STREET"),     # W vs E
                 ("203 W 131ST ST", "203 WEST 132 STREET"),     # 131 vs 132
                 ("203 W 131ST ST", "205 WEST 131 STREET"),     # house number
                 ("100 3RD AVE", "100 3 STREET"),               # avenue vs street
                 ("770 GREENE AVE", "770A GREENE AVENUE"),      # half-lot
                 ("770B GREENE AVE", "770A GREENE AVENUE")):
        assert not _shared.same_address(nyc._street_form(a), nyc._street_form(b)), (a, b)


def test_a_brooklyn_half_lot_confirms_against_itself():
    """"770A" is not all digits either. It is re-encoded with its letter, not
    stripped of it: 770 and 770A are separate lots, often adjacent."""
    half = dict(_TWO_FAMILY, BBL=3016190031, Address="770A GREENE AVENUE")
    got = _lookup([], near=[half], address="770A GREENE AVE, BROOKLYN, NY, 11221")
    assert got is not None and got.parcel_id == "3016190031"


def test_a_lettered_number_cannot_equal_any_other():
    """The letter is encoded as eight digits starting with 2; plain and
    de-hyphenated numbers run to seven digits at most."""
    assert nyc._house_number("84-74") == "8474"
    assert nyc._house_number("84-7") == "8407"
    assert nyc._house_number("770A") == "20077001"
    assert nyc._house_number("770") == "770", "plain numbers pass through"
    assert len(nyc._house_number("1A")) == 8
    assert len(nyc._house_number("9999-999")) == 7


def test_split_gaelic_prefixes_are_closed_up_on_both_sides():
    """PTS writes "MAC DOUGAL STREET" (284 lots) and "MAC DONOUGH STREET" (613);
    the Census matcher "MACDOUGAL ST"."""
    assert _shared.same_address(nyc._street_form("111 MACDOUGAL ST, NEW YORK, NY"),
                                nyc._street_form("111 MAC DOUGAL STREET"))
    assert _shared.same_address(nyc._street_form("50 MCKINLEY AVE"),
                                nyc._street_form("50 MC KINLEY AVENUE"))
    assert not _shared.same_address(nyc._street_form("111 MACDOUGAL ST"),
                                    nyc._street_form("111 MAC DONOUGH STREET"))


def test_a_unit_the_reader_typed_survives_the_rewrite_and_is_ignored():
    """``with_unit`` carries "#5A" beside the street; the shared parse then drops
    it. The rewrite must leave the marker where that parse can see it."""
    got = _lookup([], near=[_TOWER],
                  address="20 W 64TH ST #5A, NEW YORK, NY, 10023")
    assert got is not None and got.year_built == 1970


# ── the condo trap ─────────────────────────────────────────────────────────────


def test_a_condominium_tower_reports_its_year_but_not_its_area_or_floors():
    """655 units on one billing lot: 973,738 sq ft and 42 floors describe the
    tower. The year is right for every unit in it."""
    got = _lookup([_TOWER], address="20 W 64TH ST, NEW YORK, NY, 10023")
    assert got is not None
    assert got.year_built == 1970
    assert got.sqft is None and got.stories is None
    assert got.foundation is None


def test_an_unrolled_unit_lot_does_not_pass_as_a_house():
    """One residential unit — the count test alone would accept its area. The
    building class (R4, a condominium unit) and the missing building count are what
    refuse it. Its year is 0, so nothing at all comes back."""
    assert nyc._area_of_one_home(_UNIT_LOT) is None
    assert nyc._stories_of_one_home(dict(_UNIT_LOT, NumFloors=1)) is None
    assert _lookup([_UNIT_LOT]) is None
    assert nyc._area_of_one_home(dict(_UNIT_LOT, NumBldgs=1)) is None, (
        "the class alone must refuse it, even with a building count of one")


def test_a_house_with_a_store_does_not_report_the_store_as_living_space():
    """S1 is "primarily one family with one store": one unit, one building, and a
    gross area that includes the shop. The unit count passes; the class does not."""
    got = _lookup([_HOUSE_AND_STORE])
    assert got is not None and got.year_built == 1831
    assert got.sqft is None and got.stories is None


def test_a_second_building_on_the_lot_refuses_the_area_and_keeps_the_year():
    """BldgArea is "for all the structures on the tax lot". 110,561 one-family lots
    carry a second building."""
    got = _lookup([_HOUSE_AND_GARAGE])
    assert got is not None and got.year_built == 1945
    assert got.sqft is None and got.stories is None
    assert got.foundation is None, "which building's basement?"


def test_a_two_family_house_keeps_its_year_and_basement_but_not_its_area():
    got = _lookup([_TWO_FAMILY])
    assert got is not None
    assert got.year_built == 1935
    assert got.sqft is None and got.stories is None
    assert got.foundation == "full-basement", "B classes are ones DOF maintains it for"


def test_an_area_dcp_computed_is_not_reported_as_one_finance_recorded():
    """AreaSource 5 is DCP's estimate from the primary building's dimensions times
    its floors. Tagging it ``observed`` would claim a measurement."""
    got = _lookup([dict(_HOUSE, AreaSource="5")])
    assert got is not None and got.sqft is None
    assert got.stories == 3, "the floor count is still Finance's"


def test_a_half_story_is_not_rounded_into_a_whole_one():
    got = _lookup([dict(_HOUSE, NumFloors=2.5)])
    assert got is not None and got.stories is None and got.sqft == 1638.0


def test_a_new_condominium_with_no_unit_count_keeps_its_year():
    """UnitsRes is null on 170 lots, every one a newly declared condominium billing
    lot. Silence is not "no dwelling here"."""
    got = _lookup([_NEW_CONDO])
    assert got is not None and got.year_built == 2024
    assert got.sqft is None and got.stories is None


# ── the zero-dwelling lot ──────────────────────────────────────────────────────


def test_a_lot_with_no_residential_units_reports_no_year():
    """A store's year built is not the year the reader's home went up, and it would
    carry the ``observed`` tag."""
    assert _lookup([_SHOP]) is None


def test_the_gate_is_at_least_one_dwelling_not_exactly_one():
    got = _lookup([dict(_TWO_FAMILY, UnitsRes=3, BldgClass="C0")])
    assert got is not None and got.year_built == 1935


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    """PLUTO: "If Year Built is null or 0, then the value is unknown"."""
    got = _lookup([dict(_HOUSE, YearBuilt=0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 1638.0, "the area survives; only the year is missing"


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    floor = EARLIEST_PLAUSIBLE_YEAR
    at = _lookup([dict(_HOUSE, YearBuilt=floor)])
    assert at is not None and at.year_built == floor
    below = _lookup([dict(_HOUSE, YearBuilt=floor - 1)])
    assert below is not None and below.year_built is None


def test_the_alteration_years_are_not_even_requested():
    """YearAlter1/2 are when the building was last altered, never when it went up.
    A column that never arrives cannot be read by a later edit."""
    fields = nyc._FIELDS.split(",")
    assert "YearBuilt" in fields
    assert "YearAlter1" not in fields and "YearAlter2" not in fields


def test_a_lot_that_records_nothing_is_not_an_answer():
    """A real lot with no year, no area, no floors and no basement contributed no
    fact; passing it on would count as "the assessor answered"."""
    empty = dict(_HOUSE, YearBuilt=0, BldgArea=0, NumFloors=None, BsmtCode="5")
    assert _lookup([empty]) is None


# ── the basement code ──────────────────────────────────────────────────────────


def test_the_basement_codes_map_only_where_they_are_unambiguous():
    """PLUTO Data Dictionary 26v2, BsmtCode. 0 "None/No Basement" is a slab or a
    crawlspace and the code does not say which; 5 is "Unknown"."""
    expect = {"1": "full-basement", "2": "full-basement",
              "3": "partial-basement", "4": "partial-basement",
              "0": None, "5": None, None: None, "": None, "9": None}
    for code, label in expect.items():
        got = _lookup([dict(_HOUSE, BsmtCode=code)])
        assert got is not None and got.foundation == label, code


def test_the_basement_code_is_read_only_for_the_classes_dof_maintains_it_for():
    """"This information is available for one, two or three family structures …
    A value may exist for other types of property, but the data is not verified."""
    assert nyc._foundation(dict(_HOUSE_AND_STORE, BsmtCode="2")) is None
    assert nyc._foundation(dict(_TOWER, BsmtCode="2")) is None
    assert nyc._foundation(dict(_TWO_FAMILY, BldgClass="C0")) == "full-basement"
    assert nyc._foundation(dict(_TWO_FAMILY, BldgClass="C1")) is None, (
        "C1 is a walk-up of more than six families, not a three-family house")


def test_every_mapped_value_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import FOUNDATION_VALUES
    assert set(nyc._BASEMENT.values()) <= FOUNDATION_VALUES


# ── placeholder polygons ───────────────────────────────────────────────────────


def test_a_mapping_lot_is_not_a_record():
    assert _lookup([_MAPPING_LOT]) is None


def test_a_mapping_lot_does_not_make_a_real_lot_ambiguous():
    got = _lookup([_MAPPING_LOT, _HOUSE], address=_CLYDE)
    assert got is not None and got.parcel_id == "4032040021"


def test_two_real_lots_containing_the_point_are_ambiguous_and_refused():
    other = dict(_HOUSE, BBL=4032040022, Address="68-42 CLYDE STREET")
    assert _lookup([_HOUSE, other]) is None


def test_a_containing_lot_whose_address_disagrees_is_not_taken():
    """The interpolation error that puts a geocode in the roadway can put it in the
    neighbor's lot. A sole containing lot must still agree with the address."""
    neighbor = dict(_HOUSE, BBL=4032040022, Address="68-42 CLYDE STREET")
    assert _lookup([neighbor], address=_CLYDE) is None


# ── privacy ────────────────────────────────────────────────────────────────────


def test_the_field_list_is_the_privacy_boundary():
    """MapPLUTO carries the owner's name and the assessed values. None of it is an
    input to any dimension."""
    fields = nyc._FIELDS.split(",")
    for private in ("OwnerName", "OwnerType", "AssessLand", "AssessTot",
                    "ExemptTot", "*"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([], near=[_HOUSE], address=_CLYDE, params=params)
    assert len(params) == 2
    assert all(p["outFields"] == nyc._FIELDS for p in params)


# ── the county list ────────────────────────────────────────────────────────────


def test_the_five_boroughs_and_nothing_else():
    """Checked against the county table this repository ships, so the five codes
    cannot be mistyped into a neighboring county."""
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert nyc.COUNTY_FIPS <= geoids
    assert nyc.COUNTY_FIPS == {"36005", "36047", "36061", "36081", "36085"}
    for neighbor in ("36059", "36119", "34017", "34003"):   # Nassau, Westchester, NJ
        assert neighbor in geoids and neighbor not in nyc.COUNTY_FIPS


# ── the clock ──────────────────────────────────────────────────────────────────


def test_new_york_runs_on_the_shared_clock():
    """Measured over 504 requests of each kind, the slowest was 0.98 s — inside the
    shared one-second read slice — and the worst pair well inside the shared
    budget. So the adapter defines no clock of its own; this pins that it hands the
    transport the shared defaults rather than something else by accident."""
    assert not hasattr(nyc, "READ_SLICE_S") and not hasattr(nyc, "LOOKUP_TIMEOUT")
    slices = []
    _lookup([], near=[_HOUSE], address=_CLYDE, slices=slices)
    assert slices and all(s == _shared._READ_SLICE_S for s in slices), slices


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so
    one request can cost the budget plus one read slice."""
    from housing_label import config
    assert _shared.TIMEOUT + _shared._READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    nyc._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        nyc.lookup(*_POINT, _CLYDE)
    finally:
        _shared.get_json = saved
        nyc._lookup_cached.cache_clear()
    assert len(seen) == 2, "a containment and a buffered request"
    assert seen[0] == seen[1], "each request was handed its own budget"
    assert abs((seen[0] - started) - _shared.TIMEOUT) < 0.5


def test_the_buffered_query_carries_an_output_spatial_reference():
    params = []
    _lookup([], near=[_HOUSE], address=_CLYDE, params=params)
    assert all(p.get("outSR") == "4326" for p in params)
    assert params[1].get("distance"), "the second request is the buffered one"


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    nyc._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert nyc.lookup(*_POINT, _CLYDE) is None
    finally:
        _shared.get_json = saved
        nyc._lookup_cached.cache_clear()


def test_a_renamed_column_fails_open_rather_than_raising():
    """A layer reorganized under the same URL returns rows without the columns
    this adapter reads. Nothing must raise past ``lookup``."""
    assert _lookup([{"OBJECTID": 1, "SomethingElse": "x"}]) is None
    assert nyc.lookup("not a number", None) is None


def test_no_lot_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
