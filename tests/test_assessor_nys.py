#!/usr/bin/env python3
"""The New York State adapter — one opt-in statewide layer, and what it has to refuse.

Nothing here touches the network. The state's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"New York has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely New York's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

New York's own:

1. Only **33 opt-in counties** outside the city are served, and the list comes from
   the layer, not from the state. New York City is in the same layer and must not
   be claimed — another adapter answers for it.
2. The **property class** decides the floor area (one-family only) and, together
   with the residential inventory, whether a year belongs to a home at all.
3. The roll gives the **same street address to two parcels** often enough that an
   address-confirmed answer has to be checked for uniqueness.
4. **Condominium units** are stacked copies of one polygon (``DUP_GEO``), told
   apart only by ``LOC_UNIT``.
5. The roll **spells streets** its own way — "Sixth Ave", "West Hill Rd",
   "ASPEN LA NEW CITY" — where the Census matcher writes "6TH AVE", "W HILL RD"
   and "ASPEN LN".

This file alone: ``pytest tests/test_assessor_nys.py``
"""

from __future__ import annotations

import csv
import pathlib
import re
import time

from housing_label.enrich.assessor import _shared, nys

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Recorded live from NYS_Tax_Parcels_Public. A one-family townhouse in the Town of
# Colonie, Albany County: class 210, one kitchen, so its living area is that home's.
_HOUSE = {"SWIS_SBL_ID": "01010004001200020060000068", "PARCEL_ADDR": "68 Point Of Woods Dr", "LOC_ST_NBR": "68",
          "LOC_STREET": "Point Of Woods Dr", "LOC_UNIT": None, "PROP_CLASS": "210",
          "YR_BLT": 1974, "SQFT_LIVING": 1431.0, "NBR_KITCHENS": 1, "ROLL_YR": 2025}
_HOUSE_ADDR = "68 POINT OF WOODS DR, ALBANY, NY, 12203"

# Recorded live. A two-family house in Akron, Erie County: class 220, two kitchens.
# Its living area covers both homes.
_TWO_FAMILY = {"SWIS_SBL_ID": "14560104716000020190000000",
               "PARCEL_ADDR": "188 East Ave",
               "LOC_ST_NBR": "188", "LOC_STREET": "East Ave", "LOC_UNIT": None,
               "PROP_CLASS": "220", "YR_BLT": 1920, "SQFT_LIVING": 2200.0,
               "NBR_KITCHENS": 2, "ROLL_YR": 2025}

# Recorded live. A distribution warehouse in Albany County: class 449, a year from
# the commercial inventory and no residential inventory at all.
_WAREHOUSE = {"SWIS_SBL_ID": "01010004000000030070000000",
              "PARCEL_ADDR": "3 Charles Blvd",
              "LOC_ST_NBR": "3", "LOC_STREET": "Charles Blvd", "LOC_UNIT": None,
              "PROP_CLASS": "449", "YR_BLT": 1974, "SQFT_LIVING": None,
              "NBR_KITCHENS": None, "ROLL_YR": 2025}

# Recorded live. An Albany row house filed under class 311, "residential vacant
# land" — and carrying a full residential inventory: 2,100 sq ft, two kitchens,
# built 1890. The class is stale; the building is real.
_ROW_HOUSE_ON_VACANT_CLASS = {
    "SWIS_SBL_ID": "01010006506600020090000000", "PARCEL_ADDR": "226 Colonie St", "LOC_ST_NBR": "226", "LOC_STREET": "Colonie St",
    "LOC_UNIT": None, "PROP_CLASS": "311", "YR_BLT": 1890, "SQFT_LIVING": 2100.0,
    "NBR_KITCHENS": 2, "ROLL_YR": 2025}

# Recorded live. An apartment complex in Albany County: class 411, a year, gross
# floor area only.
_APARTMENTS = {"SWIS_SBL_ID": "01010004100000020110010000",
               "PARCEL_ADDR": "30 Pine Ln",
               "LOC_ST_NBR": "30", "LOC_STREET": "Pine Ln", "LOC_UNIT": None,
               "PROP_CLASS": "411", "YR_BLT": 2023, "SQFT_LIVING": None,
               "NBR_KITCHENS": None, "ROLL_YR": 2025}

# Recorded live, Town of Remsen, Oneida County: two separate parcels that the roll
# gives the SAME street address. One is an 1840 house on ten acres, the other a
# 1950 seasonal cottage 190 m away. The end-to-end check once reported the house
# for an address sampled from the cottage.
_SAME_ADDRESS_HOUSE = {
    "SWIS_SBL_ID": "30528910400000010440010000", "PARCEL_ADDR": "10876 Bardwell Mills Rd", "LOC_ST_NBR": "10876",
    "LOC_STREET": "Bardwell Mills Rd", "LOC_UNIT": None, "PROP_CLASS": "210",
    "YR_BLT": 1840, "SQFT_LIVING": 1787.0, "NBR_KITCHENS": 1, "ROLL_YR": 2025}
_SAME_ADDRESS_COTTAGE = {
    "SWIS_SBL_ID": "30528910400000010450000000", "PARCEL_ADDR": "10876 Bardwell Mills Rd", "LOC_ST_NBR": "10876",
    "LOC_STREET": "Bardwell Mills Rd", "LOC_UNIT": None, "PROP_CLASS": "260",
    "YR_BLT": 1950, "SQFT_LIVING": 520.0, "NBR_KITCHENS": 1, "ROLL_YR": 2025}
_SAME_ADDRESS = "10876 BARDWELL MILLS RD, REMSEN, NY, 13438"

# A condominium unit in Erie County, recorded live with DUP_GEO = "Y": the whole
# complex polygon is copied once per unit. Its neighbour in the stack is the same
# row with another unit, year and area — synthetic, because only the shape of the
# stack is under test.
_UNIT_29 = {"SWIS_SBL_ID": "14628906900000040010290000", "PARCEL_ADDR": "270 Buffalo Rd Unit 29", "LOC_ST_NBR": "270",
            "LOC_STREET": "Buffalo Rd", "LOC_UNIT": "Unit 29", "PROP_CLASS": "210",
            "YR_BLT": 1988, "SQFT_LIVING": 1180.0, "NBR_KITCHENS": 1, "ROLL_YR": 2025}
_UNIT_30 = dict(_UNIT_29, SWIS_SBL_ID="14628906900000040010300000", PARCEL_ADDR="270 Buffalo Rd Unit 30",
                LOC_UNIT="Unit 30", YR_BLT=1989, SQFT_LIVING=1420.0)
_UNIT_ADDR = "270 BUFFALO RD, EAST AURORA, NY, 14052"

#: A point in Albany County. Every test uses the same one: which parcel a
#: coordinate lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (42.6866, -73.7735)


def _serve(exact, near, same_number, calls):
    """A stand-in for the state's service, answering the three requests the adapter
    makes: containment, the 80 m buffer, and the same-number uniqueness search.

    The uniqueness search is answered as the server would: rows from
    ``same_number`` (by default everything within reach) whose house number is the
    one in the ``where`` clause.
    """
    def fake(url, params, deadline, read_slice=None):
        calls.append({"params": params, "deadline": deadline, "slice": read_slice})
        if params.get("where"):
            number = re.search(r"LOC_ST_NBR='(\d+)'", params["where"]).group(1)
            pool = list(same_number) if same_number is not None else list(exact) + list(near)
            rows = [r for r in pool if str(r.get("LOC_ST_NBR")) == number
                    or str(r.get("PARCEL_ADDR") or "").startswith(number + " ")]
        elif params.get("distance"):
            rows = list(near)
        else:
            rows = list(exact)
        return {"features": [{"attributes": a} for a in rows]}
    return fake


def _lookup(exact, near=(), address=None, same_number=None, calls=None):
    """Drive ``nys.lookup()`` over recorded rows, through the real transport helper,
    so the field list, the row filters and the parcel choice are all exercised."""
    calls = [] if calls is None else calls
    nys._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = _serve(exact, near, same_number, calls)
    try:
        return nys.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        nys._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_one_family_house_reports_its_year_and_floor_area():
    got = _lookup([_HOUSE], address=_HOUSE_ADDR)
    assert got is not None
    assert got.parcel_id == "01010004001200020060000068"
    assert got.year_built == 1974
    assert got.sqft == 1431.0


def test_the_house_is_found_from_the_roadway_too():
    """The Census matcher puts most New York addresses in the street: in the
    end-to-end run only 5 of 145 lookups were settled by containment. The
    buffered search, confirmed by the address, is the normal path here."""
    got = _lookup([], near=[_TWO_FAMILY, _HOUSE], address=_HOUSE_ADDR)
    assert got is not None and got.parcel_id == _HOUSE["SWIS_SBL_ID"]


def test_construction_and_the_rest_stay_empty():
    """BLDG_STYLE_DESC is an architectural style (Colonial, Ranch, Cape cod), not a
    wall material, and the layer carries no storey count, foundation or condition."""
    got = _lookup([_HOUSE], address=_HOUSE_ADDR)
    assert got is not None
    assert (got.construction, got.foundation, got.condition, got.stories) == (
        None, None, None, None)


def test_the_roll_year_travels_with_the_value():
    got = _lookup([_HOUSE], address=_HOUSE_ADDR)
    assert got is not None and "2025 assessment roll" in got.data_vintage


def test_a_missing_roll_year_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_HOUSE, ROLL_YR=None)], address=_HOUSE_ADDR)
    assert got is not None and got.data_vintage == nys.DATA_VINTAGE


# ── the floor area that describes more than one home ───────────────────────────


def test_a_two_family_house_keeps_its_year_and_loses_its_area():
    """Class 220, two kitchens: the 2,200 sq ft is both homes together."""
    got = _lookup([_TWO_FAMILY], address="188 EAST AVE, AKRON, NY, 14001")
    assert got is not None and got.year_built == 1920
    assert got.sqft is None


def test_only_the_one_family_class_reports_an_area():
    """215 (with an accessory apartment), 230, 240 (up to three dwellings), 260,
    280 and 281 can all hold more than one home, or describe a cottage that is not
    year-round living area. Only 210 says one family, one dwelling."""
    for cls in ("215", "220", "230", "240", "260", "270", "280", "281", "411"):
        got = _lookup([dict(_HOUSE, PROP_CLASS=cls)], address=_HOUSE_ADDR)
        assert got is not None and got.year_built == 1974, cls
        assert got.sqft is None, cls


def test_a_one_family_class_with_two_kitchens_loses_its_area():
    """12,049 class-210 records with a floor area record two or more kitchens — the
    roll's own sign of a second household that the class has not caught up with."""
    got = _lookup([dict(_HOUSE, NBR_KITCHENS=2)], address=_HOUSE_ADDR)
    assert got is not None and got.year_built == 1974 and got.sqft is None


def test_an_unrecorded_kitchen_count_is_not_a_second_kitchen():
    got = _lookup([dict(_HOUSE, NBR_KITCHENS=None)], address=_HOUSE_ADDR)
    assert got is not None and got.sqft == 1431.0


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_warehouse_reports_no_year():
    """Class 449 with no residential inventory: the year is the warehouse's."""
    assert _lookup([_WAREHOUSE], address="3 CHARLES BLVD, ALBANY, NY, 12205") is None


def test_every_clearly_non_residential_class_is_refused_without_an_inventory():
    for cls in ("105", "311", "330", "449", "464", "534", "612", "710", "822", "910"):
        row = dict(_WAREHOUSE, PROP_CLASS=cls)
        assert _lookup([row], address="3 CHARLES BLVD, ALBANY, NY, 12205") is None, cls


def test_classes_that_can_hold_homes_keep_their_year():
    """Apartments (411), boarding houses (418), the mixed-use rows with flats
    upstairs (481-483), homes for the aged (633), farms (1xx) and every residential
    class: none of these says "no dwelling", so the year is kept."""
    for cls in ("112", "210", "411", "418", "481", "482", "483", "633"):
        row = dict(_WAREHOUSE, PROP_CLASS=cls)
        got = _lookup([row], address="3 CHARLES BLVD, ALBANY, NY, 12205")
        assert got is not None and got.year_built == 1974, cls
    got = _lookup([_APARTMENTS], address="30 PINE LN, ALBANY, NY, 12203")
    assert got is not None and got.year_built == 2023 and got.sqft is None


def test_a_residential_inventory_outranks_a_stale_class():
    """Class 311 says vacant land; the residential inventory says an 1890 row house
    with two kitchens. Refusing on the class would throw away a real building's
    year — 2,976 vacant-class parcels carry a residential inventory like this."""
    got = _lookup([_ROW_HOUSE_ON_VACANT_CLASS],
                  address="226 COLONIE ST, ALBANY, NY, 12210")
    assert got is not None and got.year_built == 1890
    assert got.sqft is None, "not a one-family class, so the area is still refused"


def test_an_unrecognised_class_is_not_a_refusal():
    for cls in (None, "", "01", "21O"):
        got = _lookup([dict(_WAREHOUSE, PROP_CLASS=cls)],
                      address="3 CHARLES BLVD, ALBANY, NY, 12205")
        assert got is not None and got.year_built == 1974, cls


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_missing_or_zero_year_is_not_a_year():
    """This layer writes null for "not recorded"; a zero is refused as well, so a
    future change of convention cannot age a building by two thousand years."""
    for year in (None, 0):
        got = _lookup([dict(_HOUSE, YR_BLT=year)], address=_HOUSE_ADDR)
        assert got is not None and got.year_built is None, year
        assert got.sqft == 1431.0, "the area survives; only the year is missing"


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR as floor
    at = _lookup([dict(_HOUSE, YR_BLT=floor)], address=_HOUSE_ADDR)
    below = _lookup([dict(_HOUSE, YR_BLT=floor - 1)], address=_HOUSE_ADDR)
    assert at is not None and at.year_built == floor
    assert below is not None and below.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_TWO_FAMILY, YR_BLT=None)
    assert _lookup([empty], address="188 EAST AVE, AKRON, NY, 14001") is None


# ── the same address on two parcels ────────────────────────────────────────────


def test_an_address_the_roll_gives_to_two_parcels_is_refused():
    """The buffer reached only the house; the cottage with the same address sits
    190 m away, outside it. Taking the house would be a confident answer to a
    question the roll itself cannot answer."""
    got = _lookup([], near=[_SAME_ADDRESS_HOUSE], address=_SAME_ADDRESS,
                  same_number=[_SAME_ADDRESS_HOUSE, _SAME_ADDRESS_COTTAGE])
    assert got is None


def test_the_check_applies_to_a_containing_parcel_too():
    got = _lookup([_SAME_ADDRESS_HOUSE], address=_SAME_ADDRESS,
                  same_number=[_SAME_ADDRESS_HOUSE, _SAME_ADDRESS_COTTAGE])
    assert got is None


def test_a_unique_address_passes_the_check():
    """The fixture would answer without the duplicate — guards the two tests above
    from passing for some other reason."""
    got = _lookup([], near=[_SAME_ADDRESS_HOUSE], address=_SAME_ADDRESS,
                  same_number=[_SAME_ADDRESS_HOUSE])
    assert got is not None and got.year_built == 1840 and got.sqft == 1787.0


def test_the_uniqueness_search_carries_only_a_house_number():
    """The one request with a ``where`` clause. The number is taken from the parsed
    address, which is digits by construction, so nothing a reader typed reaches the
    query text."""
    calls = []
    _lookup([_HOUSE], address=_HOUSE_ADDR, calls=calls)
    wheres = [c["params"]["where"] for c in calls if c["params"].get("where")]
    assert wheres == ["LOC_ST_NBR='68' OR PARCEL_ADDR LIKE '68 %'"]
    hostile = "68' OR 1=1 -- POINT OF WOODS DR, ALBANY, NY"
    calls = []
    _lookup([_HOUSE], address=hostile, calls=calls)
    assert not [c for c in calls if c["params"].get("where")]


def test_without_an_address_there_is_nothing_to_check():
    calls = []
    got = _lookup([_HOUSE], calls=calls)
    assert got is not None and got.year_built == 1974
    assert len(calls) == 1, "containment alone; no buffer and no uniqueness search"


def test_a_row_returned_twice_under_one_full_id_is_one_candidate():
    """The same roll record twice (one parcel drawn as two polygons) is not a rival
    to itself."""
    got = _lookup([_HOUSE, dict(_HOUSE)], address=_HOUSE_ADDR)
    assert got is not None and got.year_built == 1974


def test_rows_sharing_an_sbl_under_different_swis_codes_both_survive():
    """SBL is only the section-block-lot part of the id and repeats across
    municipalities (recorded live: Chester and Crawford, Orange County, both have
    SBL 02900000010010000003). Two such rows agreeing on every other fact are still
    two parcels, so the point is ambiguous and the lookup refuses — this is also
    the deliberate answer for a village-boundary parcel assessed twice."""
    other_town = dict(_HOUSE, SWIS_SBL_ID="33260004001200020060000068")
    assert len(nys._candidates([_HOUSE, other_town], None)) == 2
    assert _lookup([_HOUSE, other_town], address=_HOUSE_ADDR) is None
    assert _lookup([_HOUSE, other_town]) is None


def test_one_full_id_with_disagreeing_facts_is_still_ambiguous():
    twin = dict(_HOUSE, YR_BLT=1975)
    assert _lookup([_HOUSE, twin], address=_HOUSE_ADDR) is None


# ── condominium stacks ─────────────────────────────────────────────────────────


def test_a_condominium_stack_without_a_unit_is_refused():
    """Every unit is a copy of one polygon. Without the reader's unit there is no
    way to choose, and choosing anyway is the nearest-parcel guess."""
    assert _lookup([_UNIT_29, _UNIT_30], address=_UNIT_ADDR) is None
    assert _lookup([_UNIT_29, _UNIT_30]) is None


def test_the_readers_unit_picks_its_row_out_of_the_stack():
    """``assessor_address`` carries the unit the reader typed onto the geocoder's
    canonical address; a row for a different unit is not an answer for them."""
    got = _lookup([_UNIT_29, _UNIT_30], address="270 BUFFALO RD #30, EAST AURORA, NY, 14052")
    assert got is not None and got.parcel_id == _UNIT_30["SWIS_SBL_ID"]
    assert got.year_built == 1989 and got.sqft == 1420.0


def test_a_unit_the_stack_does_not_hold_is_no_answer():
    assert _lookup([_UNIT_29, _UNIT_30],
                   address="270 BUFFALO RD #31, EAST AURORA, NY, 14052") is None


def test_a_building_with_no_unit_rows_still_answers_a_typed_unit():
    """Apartment 3 in a rental building: the building's own record is the only one,
    and its year is right for every flat in it."""
    got = _lookup([_APARTMENTS], address="30 PINE LN #3, ALBANY, NY, 12203")
    assert got is not None and got.year_built == 2023


# ── the roll's spelling against the geocoder's ─────────────────────────────────


def test_numbered_streets_spelled_out_in_the_roll_match_either_way():
    """Recorded live: Troy writes "734 Fifth Ave" where the matcher returns
    "734 5TH AVE" — while in Smithtown the matcher returns "140 SIXTH ST" for a
    roll's "140 Sixth St". Both spellings have to be offered."""
    troy = dict(_TWO_FAMILY, LOC_ST_NBR="734", LOC_STREET="Fifth Ave",
                PARCEL_ADDR="734 Fifth Ave")
    assert _lookup([], near=[troy], address="734 5TH AVE, TROY, NY, 12182") is not None
    st_james = dict(_HOUSE, LOC_ST_NBR="140", LOC_STREET="Sixth St",
                    PARCEL_ADDR="140 Sixth St")
    assert _lookup([], near=[st_james],
                   address="140 SIXTH ST, SAINT JAMES, NY, 11780") is not None


def test_a_spelled_out_direction_matches_the_abbreviated_one():
    row = dict(_HOUSE, LOC_ST_NBR="4293", LOC_STREET="West Hill Rd",
               PARCEL_ADDR="4293 West Hill Rd")
    got = _lookup([], near=[row], address="4293 W HILL RD, LOCKE, NY, 13092")
    assert got is not None


def test_a_street_named_for_a_direction_is_left_alone():
    """"East Ave" is a street called East, and the matcher writes it "EAST AVE"."""
    assert nys._street_spellings("East Ave") == ["East Ave"]


def test_a_trailing_direction_matches_a_leading_one():
    row = dict(_HOUSE, LOC_ST_NBR="257", LOC_STREET="Edwards Ave N",
               PARCEL_ADDR="257 Edwards Ave N")
    got = _lookup([], near=[row], address="257 N EDWARDS AVE, SYRACUSE, NY, 13206")
    assert got is not None


def test_spellings_are_offered_one_step_at_a_time():
    """"West Hill Rd" may be "W Hill Rd", never "Hill Rd W": a direction the roll
    spelled out as part of a name is not moved to the other end of it."""
    assert "Hill Rd W" not in nys._street_spellings("West Hill Rd")


def test_clarkstown_runs_the_hamlet_into_the_street_and_is_still_reachable():
    """Recorded live: "ASPEN LA NEW CITY". Lane as LA and the hamlet as a tail —
    the whole town, about 25,000 homes, is written this way."""
    row = dict(_HOUSE, LOC_ST_NBR="9", LOC_STREET="ASPEN LA NEW CITY",
               PARCEL_ADDR="9 ASPEN LA NEW CITY")
    got = _lookup([], near=[row], address="9 ASPEN LN, NEW CITY, NY, 10956")
    assert got is not None


def test_a_hamlet_tail_is_cut_only_after_a_street_type():
    assert nys._street_spellings("NEW CITY") == ["NEW CITY"]
    assert nys._street_spellings("NORMANDY VILLAGE NANUET") == ["NORMANDY VILLAGE NANUET"]


def test_apostrophes_are_dropped_as_the_matcher_drops_them():
    row = dict(_HOUSE, LOC_ST_NBR="29", LOC_STREET="Tinker's Ln",
               PARCEL_ADDR="29 Tinker's Ln")
    assert _lookup([], near=[row], address="29 TINKERS LN, GARDINER, NY, 12525")


def test_the_unit_column_is_kept_out_of_the_street_address():
    """PARCEL_ADDR runs the unit in after the street ("12 S Lake Dr 2", "... Lot 5");
    the roll keeps number, street and unit in their own columns, which is the form
    the comparison wants."""
    assert nys._address_of(_UNIT_29) == "270 Buffalo Rd"
    assert nys._address_of({"PARCEL_ADDR": "Peasley Rd"}) == "Peasley Rd"


def test_placeholder_polygons_are_not_records():
    """5,276 polygons outside the city were never joined to a roll record: no
    SWIS_SBL_ID, no class, no year. One overlapping a real parcel must not make it
    ambiguous."""
    blank = {k: None for k in _HOUSE}
    got = _lookup([blank, _HOUSE], address=_HOUSE_ADDR)
    assert got is not None and got.year_built == 1974


# ── the county list ────────────────────────────────────────────────────────────


def test_every_county_is_a_new_york_county_in_this_repos_county_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        ny = {r["geoid"] for r in csv.DictReader(fh)
              if r["geoid"].startswith("36") and len(r["geoid"]) == 5}
    assert len(ny) == 62, f"expected 62 New York counties, got {len(ny)}"
    assert nys.COUNTY_FIPS <= ny
    assert len(nys.COUNTY_FIPS) == 33


def test_new_york_city_is_not_claimed():
    """The five boroughs are in the same layer (from MapPLUTO, with a different
    class code system) and a separate adapter answers for them."""
    for borough in ("36005", "36047", "36061", "36081", "36085"):
        assert borough not in nys.COUNTY_FIPS, borough


def test_counties_that_have_not_opted_in_are_not_claimed():
    """Nassau, Monroe, Dutchess, Saratoga and others publish no parcels here. An
    adapter registered on them would make a request for every lookup and answer
    nothing — a cost with no record behind it."""
    for county in ("36059", "36055", "36027", "36091"):
        assert county not in nys.COUNTY_FIPS, county


# ── privacy ────────────────────────────────────────────────────────────────────


def test_the_field_list_is_the_privacy_boundary():
    fields = nys._FIELDS.split(",")
    for private in ("PRIMARY_OWNER", "ADD_OWNER", "MAIL_ADDR", "PO_BOX", "MAIL_CITY",
                    "ADD_MAIL_ADDR", "TOTAL_AV", "LAND_AV", "FULL_MARKET_VAL",
                    "BOOK", "PAGE", "*"):
        assert private not in fields, private


def test_future_inputs_are_not_fetched_until_something_reads_them():
    """Heating type, fuel, sewer and water supply are what make this source unique,
    and ``AssessorRecord`` has no slot for any of them yet."""
    fields = nys._FIELDS.split(",")
    for future in ("HEAT_TYPE", "HEAT_TYPE_DESC", "FUEL_TYPE", "FUEL_TYPE_DESC",
                   "SEWER_DESC", "WATER_DESC", "BLDG_STYLE_DESC"):
        assert future not in fields, future


def test_the_requested_fields_are_what_reaches_the_service():
    calls = []
    _lookup([], near=[_HOUSE], address=_HOUSE_ADDR, calls=calls)
    assert len(calls) == 3
    assert all(c["params"]["outFields"] == nys._FIELDS for c in calls)


# ── the clock ──────────────────────────────────────────────────────────────────


def test_new_york_runs_on_the_shared_clock():
    """Measured: no request to GeoHub came near the one-second read slice, so the
    shared budget stands and this module defines no clock of its own."""
    assert not hasattr(nys, "READ_SLICE_S")
    assert not hasattr(nys, "LOOKUP_TIMEOUT")
    calls = []
    _lookup([], near=[_HOUSE], address=_HOUSE_ADDR, calls=calls)
    assert all(c["slice"] in (None, _shared._READ_SLICE_S) for c in calls), calls


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert _shared.TIMEOUT + _shared._READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_all_three_requests_share_one_clock_started_once():
    calls = []
    started = time.monotonic()
    _lookup([], near=[_HOUSE], address=_HOUSE_ADDR, calls=calls)
    deadlines = {c["deadline"] for c in calls}
    assert len(calls) == 3 and len(deadlines) == 1
    assert abs(deadlines.pop() - started - _shared.TIMEOUT) < 0.5


def test_the_service_is_the_geohub_one_not_the_retired_server():
    """The legacy gisservices.its.ny.gov copy stopped receiving updates on
    2026-09-18 and is retired after October 2026."""
    assert nys.PARCEL_URL.startswith("https://nysgeohub.ny.gov/")
    assert "gisservices.its.ny.gov" not in nys.PARCEL_URL


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    nys._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert nys.lookup(*_POINT, _HOUSE_ADDR) is None
    finally:
        _shared.get_json = saved
        nys._lookup_cached.cache_clear()


def test_the_uniqueness_search_failing_is_not_an_answer():
    """A confirmed parcel whose uniqueness could not be checked is not reported."""
    def half(url, params, deadline, read_slice=None):
        if params.get("where"):
            raise TimeoutError("assessor lookup budget exhausted")
        return {"features": [{"attributes": _HOUSE}]}

    nys._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = half
    try:
        assert nys.lookup(*_POINT, _HOUSE_ADDR) is None
    finally:
        _shared.get_json = saved
        nys._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
    assert _lookup([], address=_HOUSE_ADDR) is None
