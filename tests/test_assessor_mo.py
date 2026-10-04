#!/usr/bin/env python3
"""The Missouri adapter — Jackson County's parcel polygons joined to its records.

Nothing here touches the network. The county's two layers are stubbed with row
shapes recorded from them live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken join reads as
"Jackson County has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Jackson County's own:

1. **Two hops.** The polygons carry only a property id; the address that confirms
   the parcel, and every fact, come from the record table. The join, its
   de-duplication and its integer-only ``IN`` list are this module's.
2. **The land-use code** decides whether a record may describe a home at all, and
   whether it is ONE home (area and stories).
3. **Condominium units** share a street address and, where they have polygons,
   may share a footprint.
4. **St. Louis County and City are held for their terms** and must not be claimed.

This file alone: ``pytest tests/test_assessor_mo.py``
"""

from __future__ import annotations

import csv
import inspect
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, mo

# ── records recorded live, 2026-10-04 (Ascend_GisInfo) ──────────────────────────

# A single-family house in Kansas City.
_HOUSE = {"property_id": 826131, "parcel_number": "29-710-12-20-00-0-00-000",
          "situs_address": "2408 E 30TH ST", "landuse_cd": "1110", "year_built": 1915,
          "num_stories": 2, "num_families": 1, "tot_sqf_l_area": 1215,
          "tax_year": "2024"}
# A house from the verification run, whose geocode lands off its lot.
_OFF_LOT = {"property_id": 900001, "parcel_number": "50-230-10-06-00-0-00-000",
            "situs_address": "8909 E 90TH TER", "landuse_cd": "1110",
            "year_built": 1972, "num_stories": 1, "num_families": 1,
            "tot_sqf_l_area": 1226, "tax_year": "2024"}
_NEIGHBOR = {"property_id": 900002, "parcel_number": "50-230-10-07-00-0-00-000",
             "situs_address": "8913 E 90TH TER", "landuse_cd": "1110",
             "year_built": 1971, "num_stories": 1, "num_families": 1,
             "tot_sqf_l_area": 1180, "tax_year": "2024"}
# Two condominium units of one building: one street address, the unit after it.
_UNIT_53 = {"property_id": 1717119, "parcel_number": "30-410-37-03-00-0-02-018",
            "situs_address": "1111 W 46TH ST UNIT 53", "landuse_cd": "1112",
            "year_built": 1966, "num_stories": 1, "num_families": 0,
            "tot_sqf_l_area": 849, "tax_year": "2024"}
_UNIT_54 = dict(_UNIT_53, property_id=1717120,
                parcel_number="30-410-37-03-00-0-02-019",
                situs_address="1111 W 46TH ST UNIT 54")
# A truck terminal: a commercial use, recorded with no residential year.
_TERMINAL = {"property_id": 719208, "parcel_number": "13-500-03-04-00-0-00-000",
             "situs_address": "4401 GARDNER AVE", "landuse_cd": "2280",
             "year_built": 0, "num_stories": 0, "num_families": 0,
             "tot_sqf_l_area": 0, "tax_year": "2024"}
# A duplex: two dwellings, so its living area is the building's.
_DUPLEX = {"property_id": 825001, "parcel_number": "27-510-06-45-00-0-00-000",
           "situs_address": "1830 S GLENWOOD AVE", "landuse_cd": "1120",
           "year_built": 1955, "num_stories": 1, "num_families": 2,
           "tot_sqf_l_area": 1800, "tax_year": "2024"}

#: A point in Kansas City. Which parcels a coordinate lands in is decided here by
#: the stubbed rows, not by the coordinate.
_POINT = (39.07, -94.55)
_JACKSON = "29095"


def _lookup(exact=(), near=(), address=None, records=None, slices=None, calls=None,
            exceeded=False):
    """Drive ``mo.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` and ``near`` are the RECORDS whose polygons the point is inside, and
    within 80 m of; their property ids become the polygon rows the first hop
    returns. ``records`` overrides what the second hop returns (default: the
    records of the ids asked for). ``calls`` collects (url, params) per request.
    """
    slices = [] if slices is None else slices
    calls = [] if calls is None else calls
    table = list(records) if records is not None else list(exact) + list(near)

    def fake(url, params, deadline, read_slice=None):
        slices.append(read_slice)
        calls.append((url, dict(params)))
        if exceeded:
            raise _shared.TruncatedResponse("truncated")
        if url == mo.PARCEL_URL:
            rows = near if params.get("distance") else exact
            return {"features": [{"attributes": {"PropertyID": r["property_id"]}}
                                 for r in rows]}
        assert url == mo.RECORD_URL, url
        where = params["where"]
        ids = {int(x) for x in where[where.index("(") + 1:where.index(")")].split(",")}
        return {"features": [{"attributes": r} for r in table
                             if r.get("property_id") in ids]}

    mo._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return mo.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        mo._lookup_cached.cache_clear()


# ── the ordinary house ──────────────────────────────────────────────────────────


def test_a_house_reports_its_year_area_and_stories():
    got = _lookup([_HOUSE], address="2408 E 30TH ST, KANSAS CITY, MO, 64109")
    assert got is not None
    assert got.parcel_id == "29-710-12-20-00-0-00-000"
    assert (got.year_built, got.sqft, got.stories) == (1915, 1215.0, 2)
    assert got.construction is None and got.foundation is None and got.condition is None


def test_containment_alone_answers_without_an_address():
    got = _lookup([_HOUSE])
    assert got is not None and got.year_built == 1915


def test_the_tax_year_travels_with_the_value():
    """The records are the 2024 roll's while the polygons are live; the vintage says
    which, read off the row."""
    got = _lookup([_HOUSE])
    assert got.data_vintage.endswith("tax year 2024")


def test_a_missing_tax_year_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_HOUSE, tax_year=None)])
    assert got.data_vintage == mo.DATA_VINTAGE


def test_a_geocode_inside_the_neighbors_lot_is_rescued_by_the_address():
    """The Census matcher interpolates; the point can land on the next lot. The
    neighbor's address disagrees, so the buffer is searched and the one record
    whose address agrees is taken."""
    got = _lookup([_NEIGHBOR], near=[_NEIGHBOR, _OFF_LOT],
                  address="8909 E 90TH TER, KANSAS CITY, MO, 64138")
    assert got is not None and got.parcel_id == "50-230-10-06-00-0-00-000"
    assert got.year_built == 1972


def test_a_neighbor_is_never_taken_for_the_house_asked_about():
    assert _lookup([_NEIGHBOR], near=[_NEIGHBOR],
                   address="8909 E 90TH TER, KANSAS CITY, MO, 64138") is None


# ── the two hops ────────────────────────────────────────────────────────────────


def test_the_polygon_carries_only_the_id_and_the_record_carries_the_rest():
    calls = []
    assert _lookup([_HOUSE], calls=calls) is not None
    assert [u for u, _ in calls] == [mo.PARCEL_URL, mo.RECORD_URL]
    assert calls[0][1]["outFields"] == "PropertyID"
    assert calls[1][1]["where"] == "property_id IN (826131)"


def test_a_property_repeated_across_polygons_is_asked_for_once():
    """The fabric returned one condominium master parcel as 103 polygons."""
    ids = mo._property_ids([{"PropertyID": 5}, {"PropertyID": 5.0}, {"PropertyID": 3}])
    assert ids == [3, 5]


def test_a_polygon_with_no_property_id_is_a_record_of_nothing():
    """The fabric's "Pending" parcels carry no id. They cannot be joined, and must
    not reach the record request as a blank or a null."""
    assert mo._property_ids([{"PropertyID": None}, {"PropertyID": ""},
                             {"PropertyID": 0}]) == []
    calls = []
    _lookup([], calls=calls)
    assert all(u == mo.PARCEL_URL for u, _ in calls), "no ids, so no second request"


def test_only_integers_reach_the_record_query():
    """The ids are spliced into a WHERE clause. Anything that is not a plain
    positive integer is dropped, so nothing the first hop returns can become SQL."""
    assert mo._property_ids([{"PropertyID": "1) OR (1=1"}, {"PropertyID": 7.5},
                             {"PropertyID": -3}, {"PropertyID": 42}]) == [42]


def test_a_property_with_no_record_is_not_a_candidate():
    """A parcel newer than the 2024 records has a polygon and no record; it is not
    an answer, and must not count as a rival to the house beside it."""
    got = _lookup([_HOUSE], records=[_HOUSE])
    assert got is not None
    got = _lookup([], near=[{"property_id": 555}, _OFF_LOT], records=[_OFF_LOT],
                  address="8909 E 90TH TER, KANSAS CITY, MO, 64138")
    assert got is not None and got.year_built == 1972


def test_identical_records_of_one_property_are_one_candidate():
    got = _lookup([_HOUSE], records=[_HOUSE, dict(_HOUSE)])
    assert got is not None and got.year_built == 1915


def test_records_of_one_property_that_disagree_are_not_offered():
    got = _lookup([_HOUSE], records=[_HOUSE, dict(_HOUSE, year_built=1950)])
    assert got is None


def test_a_record_with_no_parcel_number_is_not_offered():
    assert _lookup([dict(_HOUSE, parcel_number="  ")]) is None


# ── the land-use code ─────────────────────────────────────────────────────────


def test_a_commercial_parcel_is_not_an_answer():
    assert _lookup([_TERMINAL]) is None
    assert _lookup([dict(_TERMINAL, year_built=1988)]) is None, (
        "a year on a commercial record dates a building nobody lives in")


def test_a_vacant_side_lot_under_the_houses_address_does_not_hide_the_house():
    """A side lot filed as vacant land (1101) under the house's own address would
    make the address match twice. It can never be an answer, so it is dropped
    before the choice."""
    side_lot = dict(_HOUSE, property_id=826132, parcel_number="29-710-12-21-00-0-00-000",
                    landuse_cd="1101", year_built=0, num_stories=0,
                    tot_sqf_l_area=0, num_families=0)
    got = _lookup([], near=[_HOUSE, side_lot],
                  address="2408 E 30TH ST, KANSAS CITY, MO, 64109")
    assert got is not None and got.parcel_id == "29-710-12-20-00-0-00-000"


def test_garages_common_areas_and_condo_parking_are_not_homes():
    for code in ("1101", "1102", "1103", "1113", "1114", "1115", "1190", "1191",
                 "4100", "4130"):
        assert _lookup([dict(_HOUSE, landuse_cd=code)]) is None, code


def test_silence_about_the_land_use_is_not_a_refusal():
    got = _lookup([dict(_HOUSE, landuse_cd="")])
    assert got is not None and got.year_built == 1915
    assert got.sqft is None, "only a single-family code says ONE home"


def test_a_duplex_keeps_its_year_but_not_its_area():
    got = _lookup([_DUPLEX])
    assert got is not None and got.year_built == 1955
    assert got.sqft is None and got.stories is None


def test_a_single_family_record_counting_two_families_refuses_the_area():
    got = _lookup([dict(_HOUSE, num_families=2)])
    assert got.year_built == 1915 and got.sqft is None and got.stories is None


def test_a_townhouse_and_a_farm_homesite_are_one_home_each():
    for code in ("1111", "4120"):
        got = _lookup([dict(_HOUSE, landuse_cd=code)])
        assert got.sqft == 1215.0 and got.stories == 2, code


def test_the_lot_size_is_never_read_as_a_floor_area():
    assert "total_sqft" not in mo._RECORD_FIELDS.split(",")


# ── condominiums ───────────────────────────────────────────────────────────────


def test_a_condominium_unit_reports_its_year_but_not_its_area():
    # The buffer always holds what containment held; the unit is confirmed there.
    got = _lookup([_UNIT_53], near=[_UNIT_53],
                  address="1111 W 46TH ST #53, KANSAS CITY, MO, 64112")
    assert got is not None and got.year_built == 1966
    assert got.sqft is None and got.stories is None


def test_a_stack_of_units_without_a_typed_unit_is_ambiguous():
    assert _lookup([_UNIT_53, _UNIT_54], near=[_UNIT_53, _UNIT_54],
                   address="1111 W 46TH ST, KANSAS CITY, MO, 64112") is None


def test_a_typed_unit_picks_its_own_record():
    got = _lookup([_UNIT_53, _UNIT_54], near=[_UNIT_53, _UNIT_54],
                  address="1111 W 46TH ST #54, KANSAS CITY, MO, 64112")
    assert got is not None and got.parcel_id == "30-410-37-03-00-0-02-019"


def test_a_unit_inside_its_footprint_is_confirmed_by_the_buffer_not_containment():
    """With an address in hand, a unit's polygon is not evidence (it may be the
    building's), so containment is skipped and the buffer must agree."""
    calls = []
    got = _lookup([_UNIT_53], near=[_UNIT_53], calls=calls,
                  address="1111 W 46TH ST UNIT 53, KANSAS CITY, MO, 64112")
    assert got is not None
    assert any(p.get("distance") for u, p in calls if u == mo.PARCEL_URL)


def test_a_typed_unit_never_lands_on_a_different_unit():
    assert _lookup([_UNIT_53], near=[_UNIT_53],
                   address="1111 W 46TH ST #54, KANSAS CITY, MO, 64112") is None


# ── the values themselves ──────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, year_built=0)])
    assert got is not None and got.year_built is None and got.sqft == 1215.0


def test_a_record_that_says_nothing_is_not_an_answer():
    assert _lookup([dict(_HOUSE, year_built=0, tot_sqf_l_area=0, num_stories=0)]) is None


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert _lookup([dict(_HOUSE, year_built=EARLIEST_PLAUSIBLE_YEAR - 1,
                         tot_sqf_l_area=0, num_stories=0)]) is None
    got = _lookup([dict(_HOUSE, year_built=EARLIEST_PLAUSIBLE_YEAR)])
    assert got.year_built == EARLIEST_PLAUSIBLE_YEAR


def test_whole_stories_only_and_never_a_tower():
    assert _lookup([dict(_HOUSE, num_stories=1.5)]).stories is None
    assert _lookup([dict(_HOUSE, num_stories=6)]).stories is None
    assert _lookup([dict(_HOUSE, num_stories=0)]).stories is None


# ── the field lists ────────────────────────────────────────────────────────────


def test_every_field_list_is_explicit_and_carries_nothing_private():
    for fields in (mo._PARCEL_FIELDS, mo._RECORD_FIELDS):
        cols = fields.split(",")
        assert "*" not in cols and fields.strip()
        lowered = [c.lower() for c in cols]
        assert not any(w in c for c in lowered
                       for w in ("owner", "mail", "mtgco", "sale", "assessed",
                                 "market", "taxable", "_impr", "_land")), cols


def test_the_effective_and_commercial_years_are_never_requested():
    cols = mo._RECORD_FIELDS.split(",")
    assert "eff_yr_built_csect" not in cols and "year_built_csect" not in cols


def test_every_column_read_is_a_column_requested():
    """A column read but not requested is None on every row — silently."""
    src = inspect.getsource(mo)
    requested = set(mo._RECORD_FIELDS.split(",")) | {"PropertyID"}
    import re
    read = set(re.findall(r'row\.get\("([A-Za-z_]+)"\)', src)) | set(mo._FACTS)
    assert read <= requested, read - requested


def test_the_requested_fields_are_what_reaches_the_service():
    calls = []
    _lookup([_HOUSE], calls=calls)
    assert calls[0][1]["outFields"] == mo._PARCEL_FIELDS
    assert calls[1][1]["outFields"] == mo._RECORD_FIELDS


# ── which counties ─────────────────────────────────────────────────────────────


def _county_table() -> set[str]:
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as f:
        return {row["geoid"] for row in csv.DictReader(f)}


def test_every_claimed_county_is_a_real_missouri_county():
    table = _county_table()
    assert mo.COUNTY_FIPS and mo.COUNTY_FIPS <= table
    assert all(f.startswith("29") for f in mo.COUNTY_FIPS)


def test_the_counties_held_for_their_terms_are_not_claimed():
    """St. Louis County's parcel license says "All rights reserved" and St. Louis
    City's GIS terms forbid redistribution without written permission. Claiming
    either is a product decision, not a code change to slip in."""
    assert mo.HELD_FOR_TERMS == {"29189", "29510"}
    assert not mo.HELD_FOR_TERMS & mo.COUNTY_FIPS
    assert mo.HELD_FOR_TERMS <= _county_table()
    src = inspect.getsource(mo)
    assert "stlouisco.com/hosting" in src and "stlouis-mo.gov" in src  # documented…
    assert not any(v for k, v in vars(mo).items()                      # …never queried
                   if k.endswith("_URL") and ("stlouis" in v.lower()))


def test_url_for_names_jacksons_publisher_and_nothing_else():
    assert mo.url_for(_JACKSON) == mo.PARCEL_URL
    assert mo.url_for("29189") is None and mo.url_for("29510") is None
    assert _shared.urlsplit(mo.PARCEL_URL).hostname == "jcgis.jacksongov.org"
    assert _shared.urlsplit(mo.RECORD_URL).hostname == "jcgis.jacksongov.org"


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to fit.
    Pinned against the host constant, not a literal."""
    from housing_label import config
    assert mo.LOOKUP_TIMEOUT + mo.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_jackson_keeps_the_shared_clock():
    """Its slowest request of 180 measured was 0.37 s."""
    assert mo.READ_SLICE_S == _shared._READ_SLICE_S
    assert mo.LOOKUP_TIMEOUT == _shared.TIMEOUT


def test_every_request_passes_the_modules_read_slice():
    slices = []
    assert _lookup([], near=[_OFF_LOT], slices=slices,
                   address="8909 E 90TH TER, KANSAS CITY, MO, 64138") is not None
    assert len(slices) == 3 and all(s == mo.READ_SLICE_S for s in slices)


def test_all_four_requests_share_one_clock_started_once():
    seen = []

    def note(url, params, deadline, read_slice=None):
        seen.append(deadline)
        if url == mo.PARCEL_URL:
            return {"features": [{"attributes": {"PropertyID": 900002}}]}
        return {"features": [{"attributes": _NEIGHBOR}]}

    mo._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        assert mo.lookup(*_POINT, "8909 E 90TH TER, KANSAS CITY, MO, 64138") is None
    finally:
        _shared.get_json = saved
        mo._lookup_cached.cache_clear()
    assert len(seen) == 4, f"expected two hops at two distances, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs(seen[0] - started - mo.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    mo._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert mo.lookup(*_POINT, "2408 E 30TH ST, KANSAS CITY, MO") is None
    finally:
        _shared.get_json = saved
        mo._lookup_cached.cache_clear()


def test_the_second_hop_failing_is_no_answer():
    def half(url, params, deadline, read_slice=None):
        if url == mo.PARCEL_URL:
            return {"features": [{"attributes": {"PropertyID": 826131}}]}
        raise TimeoutError("assessor lookup budget exhausted")

    mo._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = half
    try:
        assert mo.lookup(*_POINT) is None
    finally:
        _shared.get_json = saved
        mo._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer():
    assert _lookup([_HOUSE], exceeded=True) is None


def test_garbage_coordinates_fail_open():
    assert mo.lookup("not a number", None) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


def test_two_homes_containing_the_point_are_ambiguous_and_refused():
    assert _lookup([_HOUSE, _NEIGHBOR]) is None
