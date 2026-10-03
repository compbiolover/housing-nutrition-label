#!/usr/bin/env python3
"""The Allegheny County adapter — two hops, and the five things it has to refuse.

Nothing here touches the network. Both services are stubbed with response shapes
recorded from them live, for the reason every adapter test file gives: an adapter
fails open on purpose, so a renamed column or a broken match reads as "Allegheny
County has no record here" and would never announce itself. A test that called
the real services would pass just as quietly.

What is worth pinning is what is genuinely Allegheny's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Allegheny's own five:

1. The parcel layer carries **no address**, so every candidate has to be looked
   up in the roll before it can be confirmed — in batches, because WPRDC's
   firewall refuses a query string over ~2 KB.
2. A **condominium** is one parcel per unit, drawn as small tiles inside the
   building with the common-property parcel underneath them all, so a point in a
   tower lands on the common parcel and on one arbitrary unit.
3. The roll has no dwelling count; its **land use** is the statement that a
   church, a garage or a common area is not somebody's home.
4. ``FINISHEDLIVINGAREA`` and ``STORIES`` describe **one card** of a building, and
   a two-family building or a second card is not the home being scored.
5. **House-number ranges** ("1622-1624 FORBES AVE") are filed under their low
   number.

This file alone: ``pytest tests/test_assessor_allegheny.py``
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import time
from urllib.parse import urlencode

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, allegheny

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Recorded live from WPRDC's "Property Assessments Parcel Data (for downloads)",
# with this adapter's own field list. A single-family house in McKeesport.
_HOUSE = {"PARID": "0462S00049000000", "PROPERTYHOUSENUM": 412,
          "PROPERTYFRACTION": " ", "PROPERTYADDRESS": "OLIVER DR",
          "PROPERTYUNIT": " ", "USEDESC": "SINGLE FAMILY", "YEARBLT": 1950,
          "FINISHEDLIVINGAREA": 1040, "STORIES": 1, "EXTFINISH_DESC": "Brick",
          "CONDITIONDESC": "AVERAGE", "BASEMENTDESC": "Full", "CARDNUMBER": 1,
          "TAXYEAR": 2026, "ASOFDATE": "30-SEP-26"}
_HOUSE_ADDRESS = "412 OLIVER DR, MCKEESPORT, PA, 15131"

# Recorded live. Two units of First Side, 151 Fort Pitt Blvd, and the
# condominium's common-property parcel that lies under every unit's tile.
_UNIT_1101 = {"PARID": "0001G00224110100", "PROPERTYHOUSENUM": 151,
              "PROPERTYFRACTION": " ", "PROPERTYADDRESS": "FORT PITT BLVD",
              "PROPERTYUNIT": "UNIT 1101", "USEDESC": "CONDOMINIUM", "YEARBLT": 2007,
              "FINISHEDLIVINGAREA": 1465, "STORIES": 1, "EXTFINISH_DESC": "Concrete",
              "CONDITIONDESC": "AVERAGE", "BASEMENTDESC": "None", "CARDNUMBER": 1,
              "TAXYEAR": 2026, "ASOFDATE": "30-SEP-26"}
_UNIT_1204 = dict(_UNIT_1101, PARID="0001G00224120400", PROPERTYUNIT="UNIT 1204",
                  FINISHEDLIVINGAREA=1310, CONDITIONDESC="GOOD")
_COMMON = {"PARID": "0001G00224000000", "PROPERTYHOUSENUM": 0,
           "PROPERTYFRACTION": " ", "PROPERTYADDRESS": "FORT PITT BLVD",
           "PROPERTYUNIT": " ", "USEDESC": "CONDOMINIUM COMMON PROPERTY",
           "YEARBLT": None, "FINISHEDLIVINGAREA": None, "STORIES": None,
           "EXTFINISH_DESC": None, "CONDITIONDESC": None, "BASEMENTDESC": None,
           "CARDNUMBER": None, "TAXYEAR": 2026, "ASOFDATE": "30-SEP-26"}
_TOWER = "151 FORT PITT BLVD, PITTSBURGH, PA, 15222"

# Recorded live. A two-family building filed under a house-number range.
_RANGE = {"PARID": "0002M00231000000", "PROPERTYHOUSENUM": 1622,
          "PROPERTYFRACTION": " -1624", "PROPERTYADDRESS": "FORBES AVE",
          "PROPERTYUNIT": " ", "USEDESC": "TWO FAMILY", "YEARBLT": 1900,
          "FINISHEDLIVINGAREA": 1600, "STORIES": 2, "EXTFINISH_DESC": "Brick",
          "CONDITIONDESC": "FAIR", "BASEMENTDESC": "Full", "CARDNUMBER": 1,
          "TAXYEAR": 2026, "ASOFDATE": "30-SEP-26"}

#: A point in McKeesport. Every test uses the same one: which parcel a coordinate
#: lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (40.337973, -79.816607)


def _lookup(exact, near=(), rows=(), address=None, calls=None):
    """Drive ``allegheny.lookup()`` over recorded rows.

    ``exact`` and ``near`` are the PINs the parcel layer returns for the point and
    for the 80 m buffer; ``rows`` is the roll, answered by PARID filter exactly as
    WPRDC answers it. Both go through the real transport seam, so the field lists,
    the batching, the dropping of non-homes, the unit narrowing and the parcel
    choice are all exercised rather than stepped over.

    ``calls``, when passed, collects ``(url, params, deadline, read_slice)`` for
    every request, so a test can check what reaches the transport rather than
    only what a constant says.
    """
    calls = [] if calls is None else calls
    roll = {r["PARID"]: r for r in rows}

    def fake(url, params, deadline, read_slice=None):
        calls.append((url, dict(params), deadline, read_slice))
        if url == allegheny.PARCEL_URL:
            pins = list(near) if params.get("distance") else list(exact)
            return {"features": [{"attributes": {"PIN": p}} for p in pins]}
        if url == allegheny.ASSESSMENT_URL:
            asked = json.loads(params["filters"])["PARID"]
            records = [roll[p] for p in asked if p in roll]
            return {"success": True, "result": {"records": records,
                                                "total": len(records)}}
        raise AssertionError(f"unexpected request to {url}")

    allegheny._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return allegheny.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        allegheny._lookup_cached.cache_clear()


def _house(**changes):
    return dict(_HOUSE, **changes)


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_everything_the_roll_records():
    got = _lookup([_HOUSE["PARID"]], rows=[_HOUSE], address=_HOUSE_ADDRESS)
    assert got is not None
    assert got.parcel_id == "0462S00049000000"
    assert got.year_built == 1950
    assert got.sqft == 1040.0
    assert got.stories == 1
    assert got.construction == "brick"
    assert got.foundation == "full-basement"
    assert got.condition == "average"


def test_the_roll_date_travels_with_the_value():
    """TAXYEAR and ASOFDATE advance each month under an unchanged resource id, so a
    hard-coded year would go stale silently."""
    got = _lookup([_HOUSE["PARID"]], rows=[_HOUSE])
    assert got is not None
    assert "2026 tax year" in got.data_vintage
    assert "file of 2026-09-30" in got.data_vintage


def test_a_missing_roll_date_falls_back_rather_than_inventing_one():
    got = _lookup([_HOUSE["PARID"]], rows=[_house(TAXYEAR=None, ASOFDATE="")])
    assert got is not None and got.data_vintage == allegheny.DATA_VINTAGE


def test_an_off_parcel_geocode_is_found_by_address_in_the_buffer():
    """The parcel layer carries no address, so the buffered candidates are looked
    up in the roll and confirmed there — the neighbor at 410 is not taken."""
    neighbor = _house(PARID="0462S00048000000", PROPERTYHOUSENUM=410, YEARBLT=1948)
    got = _lookup([], near=[neighbor["PARID"], _HOUSE["PARID"]],
                  rows=[neighbor, _HOUSE], address=_HOUSE_ADDRESS)
    assert got is not None and got.parcel_id == _HOUSE["PARID"]


def test_a_containing_parcel_at_another_address_is_not_taken():
    """The same interpolation error that puts a point in the roadway can put it in
    the neighbor's lot; the shared chooser widens rather than accepting it."""
    neighbor = _house(PARID="0462S00048000000", PROPERTYHOUSENUM=410, YEARBLT=1948)
    got = _lookup([neighbor["PARID"]], near=[neighbor["PARID"]],
                  rows=[neighbor], address=_HOUSE_ADDRESS)
    assert got is None


# ── the condominium tiles ──────────────────────────────────────────────────────


def test_the_common_parcel_does_not_make_every_condominium_ambiguous():
    """The common-property parcel lies under every unit's tile. Left among the
    candidates it would make every point in the building two parcels, which
    ``select_parcel`` refuses outright without ever reaching the buffer."""
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  rows=[_COMMON, _UNIT_1101], address=f"151 FORT PITT BLVD #1101, "
                                                     f"PITTSBURGH, PA, 15222")
    assert got is not None and got.parcel_id == _UNIT_1101["PARID"]


def test_a_condominium_unit_reports_its_own_area_but_not_a_story_count():
    """FINISHEDLIVINGAREA on a unit is the unit's own. STORIES is 1 on 3,919 of
    3,967 high-rise units: it describes the flat, not the tower."""
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  rows=[_COMMON, _UNIT_1101], address="151 FORT PITT BLVD UNIT 1101")
    assert got is not None
    assert got.year_built == 2007
    assert got.sqft == 1465.0
    assert got.stories is None


def test_the_tile_under_the_point_is_not_taken_for_another_unit():
    """The geocode lands on one arbitrary unit's tile. The reader asked for 1204;
    1101 drops out, the search widens, and 1204 is found among the building's
    tiles in the buffer."""
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  near=[_COMMON["PARID"], _UNIT_1101["PARID"], _UNIT_1204["PARID"]],
                  rows=[_COMMON, _UNIT_1101, _UNIT_1204],
                  address="151 FORT PITT BLVD #1204, PITTSBURGH, PA, 15222")
    assert got is not None
    assert got.parcel_id == _UNIT_1204["PARID"]
    assert got.sqft == 1310.0


def test_a_condominium_address_without_a_unit_has_no_answer():
    """Every unit shares the street address. Answering with whichever tile the
    geocode landed on would be the confident guess the selection policy refuses."""
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  near=[_COMMON["PARID"], _UNIT_1101["PARID"], _UNIT_1204["PARID"]],
                  rows=[_COMMON, _UNIT_1101, _UNIT_1204], address=_TOWER)
    assert got is None


def test_a_unit_tile_is_not_returned_from_bare_coordinates():
    """With no address at all, ``select_parcel`` accepts a sole containing parcel
    unconfirmed. A unit tile must not be that parcel: it is an arbitrary unit."""
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  rows=[_COMMON, _UNIT_1101], address=None)
    assert got is None


def test_a_unit_nobody_has_does_not_fall_back_to_a_neighbor():
    got = _lookup([_COMMON["PARID"], _UNIT_1101["PARID"]],
                  near=[_COMMON["PARID"], _UNIT_1101["PARID"], _UNIT_1204["PARID"]],
                  rows=[_COMMON, _UNIT_1101, _UNIT_1204],
                  address="151 FORT PITT BLVD #9999, PITTSBURGH, PA, 15222")
    assert got is None


def test_a_garden_condominium_with_its_own_house_number_is_a_house():
    """9,512 condominium records carry no unit: every unit has its own number.
    They confirm on the house number like any house, and the common parcel under
    them is dropped."""
    garden = dict(_UNIT_1101, PARID="0856D00187000000", PROPERTYHOUSENUM=305,
                  PROPERTYADDRESS="GLENWOOD DR", PROPERTYUNIT=" ",
                  FINISHEDLIVINGAREA=1587, STORIES=2)
    got = _lookup([_COMMON["PARID"], garden["PARID"]], rows=[_COMMON, garden],
                  address="305 GLENWOOD DR, PITTSBURGH, PA")
    assert got is not None and got.sqft == 1587.0
    assert got.stories is None, "a condominium's story count is never reported"


def test_unit_markers_are_stripped_before_comparing():
    assert allegheny._unit({"PROPERTYUNIT": "UNIT 1204"}) == "1204"
    assert allegheny._unit({"PROPERTYUNIT": "APT 3-B"}) == "3B"
    assert allegheny._unit({"PROPERTYUNIT": "TRLR 68"}) == "68"
    assert allegheny._unit({"PROPERTYUNIT": " "}) == ""


def test_markers_that_are_not_a_dwelling_unit_never_match_a_typed_unit():
    """"REAR" is a second house behind the first, "BLDG B" a building and "GAR 1"
    a garage. A reader's "#B" or "#1" must not be read as either."""
    assert allegheny._unit({"PROPERTYUNIT": "REAR"}) == "REAR"
    assert allegheny._unit({"PROPERTYUNIT": "BLDG B"}) == "BLDGB"
    assert allegheny._unit({"PROPERTYUNIT": "GAR 1"}) == "GAR1"


def test_a_typed_unit_on_a_house_still_finds_the_house():
    """A reader who writes "Apt 2" for a flat in a house with no units on the roll
    is not refused: no row carries that unit, so the rows with none are offered."""
    got = _lookup([_HOUSE["PARID"]], rows=[_HOUSE],
                  address="412 OLIVER DR #2, MCKEESPORT, PA, 15131")
    assert got is not None and got.year_built == 1950


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_parcel_whose_use_is_not_a_home_reports_nothing():
    """The roll has no dwelling count, but its land use is a statement. 157
    churches carry a residential card; its year is not the reader's home's."""
    for use in ("CHURCHES, PUBLIC WORSHIP", "COMMERCIAL GARAGE", "VACANT LAND",
                "RES AUX BUILDING (NO HOUSE)", "CONDEMNED/BOARDED-UP",
                "CONDOMINIUM COMMON PROPERTY"):
        assert _lookup([_HOUSE["PARID"]], rows=[_house(USEDESC=use)]) is None, use


def test_the_residential_uses_outside_class_r_are_kept():
    """A farm's residential card is its farmhouse; apartments over a store are
    homes. Their year comes through; their area does not (not one dwelling)."""
    for use in ("GENERAL FARM", "RETL/APT'S OVER", "APART: 5-19 UNITS",
                "OWNED BY METRO HOUSING AU"):
        got = _lookup([_HOUSE["PARID"]], rows=[_house(USEDESC=use)])
        assert got is not None and got.year_built == 1950, use
        assert got.sqft is None and got.stories is None, use


# ── the area and the story count describe one home or nothing ──────────────────


def test_a_two_family_building_keeps_its_year_and_refuses_its_area():
    """The area covers both homes, and is never divided by two."""
    got = _lookup([_RANGE["PARID"]], rows=[_RANGE],
                  address="1622 FORBES AVE, PITTSBURGH, PA, 15219")
    assert got is not None and got.year_built == 1900
    assert got.sqft is None
    assert got.stories is None


def test_a_card_other_than_one_refuses_area_and_stories():
    """CARDNUMBER names which building is shown, "usually the main dwelling".
    Usually is not enough to tag an area observed."""
    got = _lookup([_HOUSE["PARID"]], rows=[_house(CARDNUMBER=2)])
    assert got is not None and got.year_built == 1950
    assert got.sqft is None and got.stories is None


def test_a_missing_card_number_is_not_card_one():
    got = _lookup([_HOUSE["PARID"]], rows=[_house(CARDNUMBER=None)])
    assert got is not None and got.sqft is None


def test_a_half_story_is_not_rounded_into_one():
    for half in (1.5, 2.5, "1.5"):
        got = _lookup([_HOUSE["PARID"]], rows=[_house(STORIES=half)])
        assert got is not None and got.stories is None, half
    got = _lookup([_HOUSE["PARID"]], rows=[_house(STORIES="2")])
    assert got is not None and got.stories == 2


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([_HOUSE["PARID"]], rows=[_house(YEARBLT=0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 1040.0, "the area survives; only the year is missing"


def test_a_null_year_is_not_a_year():
    got = _lookup([_HOUSE["PARID"]], rows=[_house(YEARBLT=None)])
    assert got is not None and got.year_built is None


def test_the_oldest_houses_on_the_roll_survive():
    """The roll's range is 1755–2026; the adapter floor is the scorer floor."""
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    got = _lookup([_HOUSE["PARID"]], rows=[_house(YEARBLT=1755)])
    assert got is not None and got.year_built == 1755
    below = _lookup([_HOUSE["PARID"]], rows=[_house(YEARBLT=EARLIEST_PLAUSIBLE_YEAR - 1)])
    assert below is not None and below.year_built is None


def test_a_record_that_records_nothing_is_not_an_answer():
    empty = _house(YEARBLT=None, FINISHEDLIVINGAREA=None, STORIES=None,
                   EXTFINISH_DESC=None, CONDITIONDESC=None, BASEMENTDESC=None)
    assert _lookup([_HOUSE["PARID"]], rows=[empty]) is None


# ── the vocabulary ─────────────────────────────────────────────────────────────


def test_the_wall_vocabulary():
    expected = {"Brick": "brick", "Frame": "frame", "Masonry FRAME": "brick-frame",
                "Stone": "stone", "Concrete Block": "block"}
    for county, label in expected.items():
        got = _lookup([_HOUSE["PARID"]], rows=[_house(EXTFINISH_DESC=county)])
        assert got is not None and got.construction == label, county


def test_walls_that_say_nothing_about_the_structure_are_unmapped():
    """Stucco goes over frame and over masonry; cast concrete is not block; the
    label has no log wall."""
    for county in ("Stucco", "Concrete", "Log", "", None):
        got = _lookup([_HOUSE["PARID"]], rows=[_house(EXTFINISH_DESC=county)])
        assert got is not None and got.construction is None, county


def test_the_condition_scale_reads_down_where_it_differs():
    expected = {"EXCELLENT": "excellent", "VERY GOOD": "good", "GOOD": "good",
                "AVERAGE": "average", "FAIR": "fair", "POOR": "poor",
                "VERY POOR": "poor", "UNSOUND": "unsound"}
    for county, label in expected.items():
        got = _lookup([_HOUSE["PARID"]], rows=[_house(CONDITIONDESC=county)])
        assert got is not None and got.condition == label, county
    got = _lookup([_HOUSE["PARID"]], rows=[_house(CONDITIONDESC="REMODELED")])
    assert got is not None and got.condition is None


def test_basements_that_do_not_name_a_foundation_are_unmapped():
    """"None" says there is no basement, not whether the house is on a slab or a
    crawl space; "Slab/Piers" names two different foundations at once."""
    for county, label in {"Full": "full-basement", "Part": "partial-basement",
                          "Crawl": "crawl", "None": None, "Slab/Piers": None}.items():
        got = _lookup([_HOUSE["PARID"]], rows=[_house(BASEMENTDESC=county)])
        assert got is not None and got.foundation == label, county


def test_every_mapped_value_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import (
        CONDITION_VALUES, CONSTRUCTION_VALUES, FOUNDATION_VALUES,
    )
    assert set(allegheny._EXT_WALL.values()) <= CONSTRUCTION_VALUES
    assert set(allegheny._CONDITION.values()) <= CONDITION_VALUES
    assert set(allegheny._BASEMENT.values()) <= FOUNDATION_VALUES


# ── house-number ranges and fractions ──────────────────────────────────────────


def test_a_number_inside_a_range_on_the_same_side_confirms_the_ranged_parcel():
    got = _lookup([], near=[_RANGE["PARID"]], rows=[_RANGE],
                  address="1624 FORBES AVE, PITTSBURGH, PA, 15219")
    assert got is not None and got.parcel_id == _RANGE["PARID"]


def test_a_number_across_the_street_or_outside_the_range_does_not():
    for n in (1623, 1626, 1620):
        got = _lookup([], near=[_RANGE["PARID"]], rows=[_RANGE],
                      address=f"{n} FORBES AVE, PITTSBURGH, PA, 15219")
        assert got is None, n


def test_a_half_number_is_a_different_house():
    """123½ and 123 are separate buildings; a reader's plain 123 must not confirm
    the half."""
    half = _house(PROPERTYFRACTION=" 1/2")
    assert allegheny._address_of(half) == "412 1/2 OLIVER DR"
    assert _lookup([], near=[half["PARID"]], rows=[half], address=_HOUSE_ADDRESS) is None


def test_a_house_number_of_zero_is_no_address():
    assert allegheny._address_of(_COMMON) is None


# ── the two hops, and WPRDC's firewall ─────────────────────────────────────────


def test_candidates_are_looked_up_in_batches_under_the_firewalls_limit():
    """WPRDC's firewall answers 403 to a query string over ~2,040 bytes (bisected
    live: 70 ids pass, 71 do not). 120 candidates go in three batches."""
    pins = [f"0462S{n:05d}000000" for n in range(120)]
    calls = []
    _lookup([], near=pins, rows=[], address=_HOUSE_ADDRESS, calls=calls)
    batches = [json.loads(p["filters"])["PARID"] for u, p, *_ in calls
               if u == allegheny.ASSESSMENT_URL]
    assert [len(b) for b in batches] == [50, 50, 20]
    assert sorted(sum(batches, [])) == sorted(pins)


def test_a_full_batch_fits_under_the_query_string_limit():
    """Pinned on the encoded request, so adding a field to the list cannot push a
    full batch over the firewall's limit without this failing."""
    params = allegheny._request([f"0462S{n:05d}000000" for n in range(allegheny._BATCH)])
    assert len(urlencode(params)) < 1900, len(urlencode(params))


def test_the_buffer_does_not_ask_again_for_what_containment_fetched():
    calls = []
    neighbor = _house(PARID="0462S00048000000", PROPERTYHOUSENUM=410)
    _lookup([neighbor["PARID"]], near=[neighbor["PARID"], _HOUSE["PARID"]],
            rows=[neighbor, _HOUSE], address=_HOUSE_ADDRESS, calls=calls)
    asked = [json.loads(p["filters"])["PARID"] for u, p, *_ in calls
             if u == allegheny.ASSESSMENT_URL]
    assert asked == [[neighbor["PARID"]], [_HOUSE["PARID"]]]


def test_too_many_candidates_fails_open_without_spending_the_budget():
    """Past _MAX_CANDIDATES the lookup stops before asking WPRDC at all — it is
    not "no record here", and is raised like a truncated page so nothing caches."""
    pins = [f"0001G{n:05d}000000" for n in range(allegheny._MAX_CANDIDATES + 1)]
    calls = []
    assert _lookup([], near=pins, rows=[], address=_TOWER, calls=calls) is None
    assert not [c for c in calls if c[0] == allegheny.ASSESSMENT_URL]


def test_a_pin_that_is_not_a_pin_never_reaches_the_filter():
    calls = []
    _lookup(["", None, "0462S00049", "not-a-pin-at-all", _HOUSE["PARID"]],
            rows=[_HOUSE], calls=calls)
    asked = [json.loads(p["filters"])["PARID"] for u, p, *_ in calls
             if u == allegheny.ASSESSMENT_URL]
    assert asked == [[_HOUSE["PARID"]]]


def test_a_parcel_the_roll_has_no_row_for_is_not_a_candidate():
    """The layer has 580,039 polygons and the roll 585,005 rows; they do not pair
    off exactly. A polygon with no row is a record of nothing."""
    got = _lookup(["0462S00099000000", _HOUSE["PARID"]], rows=[_HOUSE])
    assert got is not None and got.parcel_id == _HOUSE["PARID"]


# ── the fields that are requested, and the ones that never are ────────────────


def test_the_field_lists_are_explicit_and_carry_no_owner_data():
    """The roll carries CHANGENOTICEADDRESS1-4 (the tax bill's mailing address),
    sale dates and prices, deed references and every assessed value. None is an
    input to any dimension."""
    for private in ("CHANGENOTICEADDRESS1", "CHANGENOTICEADDRESS2",
                    "CHANGENOTICEADDRESS3", "CHANGENOTICEADDRESS4", "SALEPRICE",
                    "SALEDATE", "PREVSALEPRICE", "DEEDBOOK", "DEEDPAGE",
                    "FAIRMARKETTOTAL", "COUNTYTOTAL", "OWNERDESC", "*"):
        assert private not in allegheny._FIELDS, private


def test_the_requested_fields_are_what_reaches_both_services():
    """Pinned on what the transport is handed. WPRDC returns every column when
    ``fields`` is omitted, so its presence on every request is the privacy
    boundary, not a nicety."""
    calls = []
    _lookup([], near=[_HOUSE["PARID"]], rows=[_HOUSE], address=_HOUSE_ADDRESS,
            calls=calls)
    parcel = [p for u, p, *_ in calls if u == allegheny.PARCEL_URL]
    roll = [p for u, p, *_ in calls if u == allegheny.ASSESSMENT_URL]
    assert parcel and all(p["outFields"] == "PIN" for p in parcel)
    assert roll and all(p["fields"] == ",".join(allegheny._FIELDS) for p in roll)
    assert all(p["resource_id"] == allegheny.ASSESSMENT_RESOURCE for p in roll)


def test_no_sql_endpoint_is_used():
    """WPRDC's firewall refuses datastore_search_sql with a WHERE clause."""
    assert allegheny.ASSESSMENT_URL.endswith("/datastore_search")


# ── failing open ───────────────────────────────────────────────────────────────


def test_a_service_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("403 Forbidden")

    allegheny._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert allegheny.lookup(*_POINT, _HOUSE_ADDRESS) is None
    finally:
        _shared.get_json = saved
        allegheny._lookup_cached.cache_clear()


def test_a_ckan_error_body_or_a_short_page_fails_open():
    for body in ({"success": False, "error": {"message": "nope"}},
                 {"success": True, "result": {"records": [_HOUSE], "total": 2}},
                 None):
        def fake(url, params, deadline, read_slice=None, body=body):
            if url == allegheny.PARCEL_URL:
                return {"features": [{"attributes": {"PIN": _HOUSE["PARID"]}}]}
            return body

        allegheny._lookup_cached.cache_clear()
        saved = _shared.get_json
        _shared.get_json = fake
        try:
            assert allegheny.lookup(*_POINT, _HOUSE_ADDRESS) is None, body
        finally:
            _shared.get_json = saved
            allegheny._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


def test_an_empty_record_is_not_an_answer_through_the_registry_door_either():
    """Checked through ``assessor_for_point`` semantics: an adapter answer with no
    fields is dropped. Driven directly because registration is a separate step."""
    empty = _house(YEARBLT=None, FINISHEDLIVINGAREA=None, STORIES=None,
                   EXTFINISH_DESC="Log", CONDITIONDESC=None, BASEMENTDESC="None")
    assert _lookup([_HOUSE["PARID"]], rows=[empty]) is None


# ── the county ─────────────────────────────────────────────────────────────────


def test_allegheny_is_one_county_in_the_repos_own_county_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert allegheny.COUNTY_FIPS == frozenset({"42003"})
    assert allegheny.COUNTY_FIPS <= geoids


def test_allegheny_does_not_claim_a_county_another_adapter_has():
    for mod in set(A.ADAPTERS.values()):
        if mod is not allegheny:
            assert not (mod.COUNTY_FIPS & allegheny.COUNTY_FIPS), mod.__name__


def test_the_module_carries_what_the_registry_reads():
    for name in ("NAME", "ATTRIBUTION", "DATA_VINTAGE", "PARCEL_URL", "ASSESSMENT_URL"):
        assert getattr(allegheny, name), name
    assert "CC0" in allegheny.ATTRIBUTION


# ── the clock ──────────────────────────────────────────────────────────────────


def test_both_services_get_allegheny_s_read_slice():
    """WPRDC's slowest successful answer was 2.50 s inside the product path; the
    shared 1 s slice would cut answers like that off, and they would read as "no
    record". Pinned on the transport, not on the constant."""
    calls = []
    got = _lookup([], near=[_HOUSE["PARID"]], rows=[_HOUSE], address=_HOUSE_ADDRESS,
                  calls=calls)
    assert got is not None
    assert calls and all(c[3] == allegheny.READ_SLICE_S for c in calls)
    assert allegheny.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so
    one request can cost the budget plus one read slice. Pinned against the host
    constant rather than a literal."""
    from housing_label import config
    assert allegheny.LOOKUP_TIMEOUT + allegheny.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET, (
        f"worst case {allegheny.LOOKUP_TIMEOUT + allegheny.READ_SLICE_S}s is not "
        f"under the {config.UPSTREAM_HOST_BUDGET}s this host allows one service")
    assert allegheny.LOOKUP_TIMEOUT > _shared.TIMEOUT


def test_every_request_shares_one_clock_started_once():
    """Four requests for an off-parcel house — containment, its batch, the buffer,
    its batch — all against one deadline, set to Allegheny's budget."""
    calls = []
    neighbor = _house(PARID="0462S00048000000", PROPERTYHOUSENUM=410)
    started = time.monotonic()
    _lookup([neighbor["PARID"]], near=[neighbor["PARID"], _HOUSE["PARID"]],
            rows=[neighbor, _HOUSE], address=_HOUSE_ADDRESS, calls=calls)
    deadlines = {c[2] for c in calls}
    assert len(calls) == 4, [c[0] for c in calls]
    assert len(deadlines) == 1, "each request was handed its own budget"
    budget = deadlines.pop() - started
    assert abs(budget - allegheny.LOOKUP_TIMEOUT) < 0.5, budget


def test_the_lookup_is_cached_on_the_rounded_point_and_address():
    calls = []
    roll = {_HOUSE["PARID"]: _HOUSE}

    def fake(url, params, deadline, read_slice=None):
        calls.append(url)
        if url == allegheny.PARCEL_URL:
            return {"features": [{"attributes": {"PIN": _HOUSE["PARID"]}}]}
        asked = json.loads(params["filters"])["PARID"]
        recs = [roll[p] for p in asked if p in roll]
        return {"success": True, "result": {"records": recs, "total": len(recs)}}

    allegheny._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        a = allegheny.lookup(40.3379731, -79.8166071, _HOUSE_ADDRESS)
        b = allegheny.lookup(40.3379729, -79.8166069, _HOUSE_ADDRESS)
    finally:
        _shared.get_json = saved
        allegheny._lookup_cached.cache_clear()
    assert a == b and a is not None
    assert len(calls) == 2, "the second click on the same rooftop was not cached"


def test_the_gate_still_governs_the_registry_door():
    """Off by default: with ASSESSOR_ADAPTERS unset nothing is asked, whatever is
    registered. Restores the environment it found."""
    saved = os.environ.pop(A.ENABLE_ENV, None)
    try:
        assert A.assessor_for_point(*_POINT, "42003") is None
    finally:
        if saved is not None:
            os.environ[A.ENABLE_ENV] = saved
