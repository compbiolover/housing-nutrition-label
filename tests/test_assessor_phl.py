#!/usr/bin/env python3
"""The Philadelphia adapter — one SQL query, and the things it has to refuse.

Nothing here touches the network. The City's Carto service is stubbed with row
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Philadelphia has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely Philadelphia's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Philadelphia's own:

1. The source is **SQL**, so the query is built here — and only a coordinate may
   ever be written into it.
2. A **condominium** is hundreds of accounts at one point, and only the unit the
   reader typed can pick theirs out.
3. **House-number ranges** ("2018-32 WALNUT ST") that the shared address parse
   cannot anchor on.
4. A storey count stored as an **integer that rounds half storeys**.
5. An exterior-condition scale whose **published numbering disagrees with the
   data**.
6. A year-built **estimate flag** on 70% of the city.

This file alone: ``pytest tests/test_assessor_phl.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, phl

# Recorded live (OPA account 521423200). A single-family brick row in Overbrook:
# one home, legacy building code and storey count agreeing on 2.
_HOUSE = {"parcel_number": "521423200", "location": "3710 LANKENAU RD", "unit": None,
          "category_code": "1", "building_code_description": "ROW B/GAR 2 STY MASONRY",
          "year_built": "1959", "year_built_estimate": "Y", "total_livable_area": 1415,
          "number_stories": 2, "exterior_condition": "4", "basements": "D",
          "other_building": None, "assessment_date": "2026-04-29T15:38:02Z"}


def _condo_unit(unit, area, pid):
    """Recorded live: 2001 Hamilton St, several hundred units at one coordinate,
    every one with the same `location` and the unit in its own column."""
    return {"parcel_number": pid, "location": "2001 HAMILTON ST", "unit": unit,
            "category_code": "1", "building_code_description": "RES CONDO 5+ STY MAS+OTH",
            "year_built": "1970", "year_built_estimate": "Y", "total_livable_area": area,
            "number_stories": 1, "exterior_condition": "3", "basements": None,
            "other_building": None, "assessment_date": "2026-04-29T15:38:02Z"}


_TOWER = [_condo_unit("1221", 674, "888091242"), _condo_unit("1029", 937, "888091194"),
          _condo_unit("2008", 1465, "888091902"), _condo_unit("P501", 978, "888092032"),
          _condo_unit("1621", 450, "888091338")]

# Recorded live. A parcel filed under a house-number range.
_RANGED = dict(_HOUSE, parcel_number="881234500", location="2018-32 WALNUT ST",
               category_code="2", building_code_description="APT 2-4 UNITS 3 STY MASON",
               year_built="1925", total_livable_area=9800, number_stories=3)

#: A point in Philadelphia. Every test uses the same one: which account a
#: coordinate lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (39.9850, -75.2490)


def _lookup(exact, near=(), address=None, calls=None):
    """Drive ``phl.lookup()`` over recorded rows.

    ``exact`` is what the containment query returns; ``near`` is what the buffered
    query would. Both are answered through the module's real request path, so the
    SQL, the dedupe, the unit narrowing and the parcel choice are all exercised.

    ``calls``, when passed, collects every request exactly as the transport saw it
    — positional and keyword arguments — so a test can check what reaches the
    service rather than what a constant says.
    """
    calls = [] if calls is None else calls

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        params = args[1]
        rows = list(near) if "ST_DWithin" in params["q"] else list(exact)
        return {"rows": rows, "time": 0.06, "total_rows": len(rows)}

    phl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return phl.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        phl._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_everything_the_label_reads():
    got = _lookup([_HOUSE], address="3710 LANKENAU RD, PHILADELPHIA, PA, 19131")
    assert got is not None
    assert got.parcel_id == "521423200"
    assert got.year_built == 1959
    assert got.sqft == 1415.0
    assert got.stories == 2
    assert got.condition == "average"
    assert got.foundation == "full-basement"
    assert got.construction is None, "construction is never read; see the module"
    assert "2026-04" in got.data_vintage


def test_containment_with_no_address_is_still_an_answer():
    """The label is scored from bare coordinates when the geocoder echoes no
    address; a point inside a parcel holding exactly one account is then enough."""
    got = _lookup([_HOUSE])
    assert got is not None and got.year_built == 1959


def test_an_off_parcel_geocode_is_rescued_by_its_address():
    """The Census matcher interpolates onto the centerline; in the verification
    run 147 of 150 lookups fell through to the buffer."""
    neighbour = dict(_HOUSE, parcel_number="521423300", location="3712 LANKENAU RD")
    got = _lookup([], near=[neighbour, _HOUSE],
                  address="3710 LANKENAU RD, PHILADELPHIA, PA, 19131")
    assert got is not None and got.parcel_id == "521423200"


def test_containment_in_the_neighbours_parcel_is_not_believed():
    neighbour = dict(_HOUSE, parcel_number="521423300", location="3712 LANKENAU RD",
                     year_built="1961")
    got = _lookup([neighbour], near=[neighbour, _HOUSE],
                  address="3710 LANKENAU RD, PHILADELPHIA, PA, 19131")
    assert got is not None and got.parcel_id == "521423200"
    assert _lookup([neighbour], near=[neighbour],
                   address="3710 LANKENAU RD, PHILADELPHIA, PA") is None


def test_an_account_returned_twice_is_one_candidate():
    """A point inside two overlapping PWD polygons comes back twice from the join.
    Counted twice it would be ambiguous with itself and refused."""
    got = _lookup([_HOUSE, dict(_HOUSE)])
    assert got is not None and got.parcel_id == "521423200"


def test_a_row_with_no_parcel_number_is_not_a_record():
    blank = dict(_HOUSE, parcel_number=" ", location="3712 LANKENAU RD")
    got = _lookup([blank, _HOUSE])
    assert got is not None and got.parcel_id == "521423200"
    assert _lookup([blank]) is None


# ── condominiums: hundreds of accounts at one point ────────────────────────────


def test_a_condominium_without_a_unit_has_no_answer():
    """Every unit shares the street address and the coordinate. Answering with one
    of them would be the confident guess the selection policy refuses."""
    assert _lookup(_TOWER, near=_TOWER,
                   address="2001 HAMILTON ST, PHILADELPHIA, PA, 19130") is None
    assert _lookup(_TOWER) is None


def test_the_unit_the_reader_typed_picks_their_home():
    """Recorded live: unit 1221 is 674 sq ft, its neighbours 937 and 1,465. The
    unit's own area is reported, as the District reports LIVING_GBA."""
    got = _lookup(_TOWER, near=_TOWER,
                  address="2001 HAMILTON ST #1221, PHILADELPHIA, PA, 19130")
    assert got is not None
    assert got.parcel_id == "888091242"
    assert got.year_built == 1970
    assert got.sqft == 674.0
    assert got.condition == "good"


def test_a_condo_units_storey_count_is_its_floor_level_and_is_refused():
    """OPA's definition: 'In condominiums, this would relate to floor level.'"""
    got = _lookup(_TOWER, address="2001 HAMILTON ST #2008, PHILADELPHIA, PA")
    assert got is not None and got.parcel_id == "888091902"
    assert got.stories is None


def test_a_unit_that_does_not_exist_is_not_rounded_to_one_that_does():
    assert _lookup(_TOWER, near=_TOWER,
                   address="2001 HAMILTON ST #9999, PHILADELPHIA, PA") is None


def test_unit_spelling_is_normalised_but_leading_zeros_are_not():
    """'#p-501' is P501. Unit 01 and unit 1 can both exist in one building."""
    got = _lookup(_TOWER, address="2001 HAMILTON ST Apt p-501, PHILADELPHIA, PA")
    assert got is not None and got.parcel_id == "888092032"
    tower = _TOWER + [_condo_unit("01", 500, "888090001")]
    got = _lookup(tower, address="2001 HAMILTON ST #1, PHILADELPHIA, PA")
    assert got is None, "unit 1 is not unit 01"


def test_a_matching_unit_in_the_wrong_building_does_not_win():
    """The unit narrows only among rows at the reader's address. A unit 1 next
    door must not displace the reader's own (unit-less) house."""
    house = dict(_HOUSE, location="1506 N 7TH ST")
    next_door = dict(_condo_unit("1", 1284, "888200686"), location="1510 N 7TH ST")
    got = _lookup([], near=[house, next_door], address="1506 N 7TH ST #1, PHILADELPHIA, PA")
    assert got is not None and got.parcel_id == "521423200"


def test_a_house_with_a_separately_assessed_rear_unit_resolves_to_the_house():
    rear = dict(_HOUSE, parcel_number="521423299", unit="B", year_built="1990")
    got = _lookup([_HOUSE, rear])
    assert got is not None and got.parcel_id == "521423200"


def test_a_condo_buildings_account_without_a_unit_reports_no_area():
    """Its area may be the building's, not anybody's home."""
    master = _condo_unit(None, 250000, "888091000")
    got = _lookup([master])
    assert got is not None and got.year_built == 1970
    assert got.sqft is None and got.stories is None


# ── house-number ranges ────────────────────────────────────────────────────────


def test_an_address_inside_a_range_on_the_same_side_confirms_it():
    got = _lookup([], near=[_RANGED], address="2024 WALNUT ST, PHILADELPHIA, PA, 19103")
    assert got is not None and got.parcel_id == "881234500"
    assert got.year_built == 1925


def test_the_other_side_of_the_street_is_not_inside_the_range():
    """Odd and even numbers are on opposite sides; 2025 is across the street."""
    assert _lookup([], near=[_RANGED], address="2025 WALNUT ST, PHILADELPHIA, PA") is None
    assert _lookup([], near=[_RANGED], address="2034 WALNUT ST, PHILADELPHIA, PA") is None


def test_a_range_is_offered_under_its_low_number_otherwise():
    assert phl._address_of(_RANGED) == "2018 WALNUT ST"
    assert phl._address_of(_RANGED, "2034 WALNUT ST") == "2018 WALNUT ST"
    assert phl._address_of(_RANGED, "2032 WALNUT ST, PHILADELPHIA") == "2032 WALNUT ST"


def test_a_malformed_range_never_widens():
    for loc in ("400-26 S BROAD ST", "100-900 MAIN ST", "98-12 PINE ST"):
        row = dict(_RANGED, location=loc)
        low = loc.split("-")[0]
        if loc.startswith("400"):
            assert phl._address_of(row, "424 S BROAD ST") == "424 S BROAD ST"
        else:
            assert phl._address_of(row, f"{int(low) + 2} X ST").startswith(low + " ")


def test_a_rear_property_never_confirms_as_the_front_house():
    """'406R S 21ST ST' is a separate dwelling behind 406; the shared parse cannot
    anchor on it and it must not be bent into 406."""
    rear = dict(_HOUSE, location="406R S 21ST ST")
    assert _lookup([], near=[rear], address="406 S 21ST ST, PHILADELPHIA, PA") is None


# ── one dwelling, or no area and no storeys ────────────────────────────────────


def test_a_multi_family_building_keeps_its_year_and_loses_its_area():
    got = _lookup([_RANGED], address="2018 WALNUT ST, PHILADELPHIA, PA")
    assert got is not None and got.year_built == 1925
    assert got.sqft is None and got.stories is None


def test_mixed_use_and_apartments_are_not_one_dwelling():
    for category in ("3", "14"):
        got = _lookup([dict(_HOUSE, category_code=category)])
        assert got is not None and got.year_built == 1959, category
        assert got.sqft is None and got.stories is None, category


def test_a_second_dwelling_on_the_lot_refuses_area_and_storeys():
    got = _lookup([dict(_HOUSE, other_building="Y")])
    assert got is not None and got.year_built == 1959
    assert got.sqft is None and got.stories is None


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_commercial_account_reports_nothing_at_all():
    """Its condition and basement describe a shop as surely as its year does."""
    for category in ("4", "5", "6", "9", "10", "13", "16"):
        assert _lookup([dict(_HOUSE, category_code=category)]) is None, category


def test_a_condo_parking_space_is_not_a_home():
    """Category 1, a unit number, a year and 153 sq ft — and a parking space."""
    space = dict(_condo_unit("P12", 153, "888099999"),
                 building_code_description="CONDO PARKING SPACE")
    assert _lookup([space], address="2001 HAMILTON ST #P12, PHILADELPHIA, PA") is None


def test_a_stale_building_code_does_not_refuse_a_new_house():
    """3,805 single-family houses with a median year of 2021 still carry 'VACANT
    LAND RESIDE < ACRE'. The category is the dwelling statement, not the code."""
    new = dict(_HOUSE, building_code_description="VACANT LAND RESIDE < ACRE",
               year_built="2021", year_built_estimate=None, number_stories=3)
    got = _lookup([new])
    assert got is not None and got.year_built == 2021 and got.sqft == 1415.0
    assert got.stories is None, "no storey count in the code to agree with"


def test_a_blank_category_is_silence_not_a_statement():
    got = _lookup([dict(_HOUSE, category_code=None)])
    assert got is not None and got.year_built == 1959
    assert got.sqft is None, "area still needs the single-family statement"


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, year_built="0")])
    assert got is not None and got.year_built is None
    assert got.sqft == 1415.0


def test_a_blank_or_garbled_year_is_not_a_year():
    for raw in (None, "", "19O5", "1920.5"):
        got = _lookup([dict(_HOUSE, year_built=raw)])
        assert got is not None and got.year_built is None, raw


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR as floor
    assert _lookup([dict(_HOUSE, year_built=str(floor))]).year_built == floor
    assert _lookup([dict(_HOUSE, year_built=str(floor - 1))]).year_built is None


def test_an_estimated_year_is_reported_and_says_so():
    """70% of the city is flagged. Refusing them would hand seven homes in ten back
    to a tract quantile; reporting them silently would overstate them. The note
    travels in the vintage, which the label prints beside the value."""
    got = _lookup([_HOUSE])
    assert got.year_built == 1959
    assert "year built is OPA's estimate" in got.data_vintage


def test_an_unflagged_year_carries_no_estimate_note():
    for flag in ("N", None, ""):
        got = _lookup([dict(_HOUSE, year_built_estimate=flag)])
        assert "estimate" not in got.data_vintage, flag


def test_the_estimate_note_is_not_attached_to_a_record_with_no_year():
    got = _lookup([dict(_HOUSE, year_built="0")])
    assert got is not None and "estimate" not in got.data_vintage


def test_a_missing_assessment_date_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_HOUSE, assessment_date=None, year_built_estimate="N")])
    assert got.data_vintage == phl.DATA_VINTAGE


def test_a_record_with_nothing_the_label_reads_is_not_an_answer():
    empty = dict(_HOUSE, year_built="0", total_livable_area=0, number_stories=None,
                 exterior_condition=None, basements=None)
    assert _lookup([empty]) is None


# ── storeys: an integer column that rounds half storeys ────────────────────────


def test_a_rounded_half_storey_is_refused():
    """Recorded live: 7,140 '2.5 STY' houses carry number_stories = 3."""
    for code, n in (("SEMI/DET 2.5 STY MASONRY", 3), ("DET 1.5 STY FRAME", 2),
                    ("ROW 2.5 STY MASONRY", 2)):
        got = _lookup([dict(_HOUSE, building_code_description=code, number_stories=n)])
        assert got is not None and got.stories is None, code


def test_a_code_and_a_count_that_disagree_are_refused():
    """'2 STY' with number_stories = 1 on 30,711 houses: one of them is wrong."""
    got = _lookup([dict(_HOUSE, number_stories=1)])
    assert got is not None and got.stories is None


def test_an_open_topped_storey_bucket_is_not_a_count():
    got = _lookup([dict(_HOUSE, building_code_description="ROW 5+ STY MASONRY",
                        number_stories=5)])
    assert got.stories is None


def test_an_agreeing_three_storey_row_is_reported():
    got = _lookup([dict(_HOUSE, building_code_description="ROW 3 STY MASONRY",
                        number_stories=3)])
    assert got.stories == 3


# ── condition: a published scale the data does not follow ──────────────────────


def test_exterior_condition_follows_the_numbering_the_data_uses():
    """4 is AVERAGE — 78% of graded accounts, which is how the catalog itself
    defines average ('majority of properties') — not the printed 5."""
    expected = {"2": "good", "3": "good", "4": "average", "5": "fair"}
    for code, label in expected.items():
        assert _lookup([dict(_HOUSE, exterior_condition=code)]).condition == label, code


def test_codes_that_are_not_a_condition_are_not_mapped():
    """1 is age relative to the neighbours, 6 is occupancy, 7 lumps a sealed sound
    house with one open to the weather, 0 is 'not applicable', 8 has one row on a
    scale with no 8."""
    for code in ("0", "1", "6", "7", "8", "9", "", None, "A"):
        got = _lookup([dict(_HOUSE, exterior_condition=code)])
        assert got is not None and got.condition is None, code


def test_below_average_is_read_down_to_fair_not_poor():
    assert phl._CONDITION["5"] == "fair"
    assert "poor" not in phl._CONDITION.values()
    assert "unsound" not in phl._CONDITION.values()
    assert "excellent" not in phl._CONDITION.values()


# ── foundation ─────────────────────────────────────────────────────────────────


def test_the_published_basement_table():
    for code in "ABCD":
        assert _lookup([dict(_HOUSE, basements=code)]).foundation == "full-basement"
    for code in "EFGH":
        assert _lookup([dict(_HOUSE, basements=code)]).foundation == "partial-basement"


def test_basement_codes_that_say_nothing_about_the_foundation():
    """I/J are 'Unknown Size'; 0 'None' does not say slab or crawl; 1 and 2 are on
    12,798 rows and in no published table."""
    for code in ("I", "J", "0", "1", "2", "", None):
        got = _lookup([dict(_HOUSE, basements=code)])
        assert got is not None and got.foundation is None, code


# ── the query, which is the privacy and injection boundary ─────────────────────


def _sql_sent(address="3710 LANKENAU RD, PHILADELPHIA, PA"):
    calls = []
    _lookup([], near=[_HOUSE], address=address, calls=calls)
    return [args[1]["q"] for args, _ in calls], calls


def test_only_named_columns_are_selected_and_none_of_them_is_personal():
    """The OPA table carries owner names, mailing addresses, sale prices and
    market values; the PWD table carries owner names. None is requested."""
    sqls, _ = _sql_sent()
    assert len(sqls) == 2, "containment, then the buffer"
    for sql in sqls:
        low = sql.lower()
        assert "*" not in sql
        for private in ("owner", "mailing", "sale_", "market_value", "taxable",
                        "exempt", "book_and_page", "registry_number"):
            assert private not in low, private
        assert "p.address" not in low and "p.owner" not in low
        select = low.split(" from ")[0]
        assert select == "select " + ", ".join(f"o.{c}" for c in phl._COLUMNS)


def test_nothing_the_reader_typed_reaches_the_sql():
    hostile = "1 X ST'); DROP TABLE opa_properties_public; -- #'1, PHILADELPHIA"
    sqls, _ = _sql_sent(hostile)
    for sql in sqls:
        assert "DROP" not in sql and "X ST" not in sql and "'" not in sql


def test_a_non_finite_coordinate_never_reaches_the_service():
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        return {"rows": []}

    phl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        assert phl.lookup(float("nan"), -75.2, "3710 LANKENAU RD") is None
        assert phl.lookup(39.98, float("inf"), "3710 LANKENAU RD") is None
    finally:
        _shared.get_json = saved
        phl._lookup_cached.cache_clear()
    assert calls == []


def test_the_coordinate_is_formatted_as_a_number():
    sql = phl._sql(39.98501234567, -75.249)
    assert "ST_MakePoint(-75.2490000, 39.9850123)" in sql
    assert "ST_DWithin" not in sql
    buffered = phl._sql(39.985, -75.249, 80)
    assert "ST_DWithin(p.the_geom::geography" in buffered and ", 80.0)" in buffered
    assert "ST_Expand" in buffered, "the bbox prefilter that lets the index work"


# ── the county ────────────────────────────────────────────────────────────────


def test_philadelphia_is_the_county_and_the_only_one():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert phl.COUNTY_FIPS == frozenset({"42101"})
    assert phl.COUNTY_FIPS <= geoids, "the county table must know this code"


def test_the_module_names_its_source():
    assert phl.SQL_URL.startswith("https://phl.carto.com/")
    assert phl.NAME and phl.ATTRIBUTION and phl.DATA_VINTAGE


# ── the clock ─────────────────────────────────────────────────────────────────


def test_philadelphia_runs_on_the_shared_clock():
    """Measured median 0.07 s / max 0.72 s over 300 in-product lookups: the shared
    four-second budget and one-second slice fit with room to spare, so the
    adapter neither defines nor passes its own."""
    assert not hasattr(phl, "READ_SLICE_S")
    assert not hasattr(phl, "LOOKUP_TIMEOUT")
    _, calls = _sql_sent()
    for args, kwargs in calls:
        assert len(args) == 3 and "read_slice" not in kwargs, "no private slice"


def test_the_shared_worst_case_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert _shared.TIMEOUT + _shared._READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(*args, **kwargs):
        seen.append(args[2])
        return {"rows": []}

    phl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        phl.lookup(*_POINT, "3710 LANKENAU RD, PHILADELPHIA, PA")
    finally:
        _shared.get_json = saved
        phl._lookup_cached.cache_clear()
    assert len(seen) == 2
    assert seen[0] == seen[1], "each request was handed its own budget"
    assert abs((seen[0] - started) - _shared.TIMEOUT) < 0.5


# ── failing open ──────────────────────────────────────────────────────────────


def test_a_carto_error_is_not_evidence_of_absence():
    """Carto reports SQL errors as {"error": [...]} in the body, which the shared
    transport raises on; the adapter swallows it."""
    def boom(*args, **kwargs):
        raise RuntimeError("upstream error: ['relation \"opa_properties_public\" does not exist']")

    phl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert phl.lookup(*_POINT, "3710 LANKENAU RD, PHILADELPHIA, PA") is None
    finally:
        _shared.get_json = saved
        phl._lookup_cached.cache_clear()


def test_the_shared_transport_raises_on_a_carto_error_body(monkeypatch):
    """Pinned against the real transport: the error shape is Carto's, and if the
    shared check ever stopped matching it, an error would be cached as absence."""
    class _Resp:
        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b'{"error": ["syntax error at or near \\"dec\\""]}'

        def close(self):
            pass

    class _Session:
        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(_shared.utils, "http_session", lambda: _Session())
    monkeypatch.setattr(_shared.utils, "note_dropped", lambda host: None)
    try:
        _shared.get_json(phl.SQL_URL, {"q": "SELECT 1"}, time.monotonic() + 4)
    except RuntimeError as exc:
        assert "upstream error" in str(exc)
    else:
        raise AssertionError("a Carto error body was returned as data")


def test_no_account_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
    assert _lookup([], near=[], address="3710 LANKENAU RD, PHILADELPHIA, PA") is None


def test_a_missing_rows_key_is_no_answer_not_a_crash():
    def odd(*args, **kwargs):
        return {"time": 0.01}

    phl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = odd
    try:
        assert phl.lookup(*_POINT) is None
    finally:
        _shared.get_json = saved
        phl._lookup_cached.cache_clear()
