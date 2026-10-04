#!/usr/bin/env python3
"""The Indiana adapter — Vanderburgh County's assessor layer, and what it refuses.

Nothing here touches the network. The service is stubbed with row shapes recorded
from it live, for the reason every adapter test file gives: an adapter fails open
on purpose, so a renamed column or a broken match reads as "no record here" and
would never announce itself.

The shared parts — choosing the parcel, comparing addresses, the request budget —
are tested against Cook in ``test_assessor.py``. Pinned here:

1. **The property class decides whether a year is a home's.** The layer fills
   ``YearBuilt`` on shops and churches too.
2. **Only a one-family class with a single-family dwelling record** reports an
   area, a story count or a condition.
3. **Indiana's condition rating** translates where it is unambiguous.
4. **Marion and Hamilton are not claimed** — one for a stale source, one for its
   terms (see the module docstring).

This file alone: ``pytest tests/test_assessor_ind.py``
"""

from __future__ import annotations

import csv
import inspect
import pathlib
import time

from housing_label.enrich.assessor import _shared, ind
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

_ROOT = pathlib.Path(__file__).resolve().parent.parent

VANDERBURGH, MARION, HAMILTON = "18163", "18097", "18057"


def _row(**kw):
    """A Vanderburgh row, recorded live: a ranch house on Valley Ct by default."""
    row = {"PARCELID": "82-02-32-009-144.012-030", "PROPSTREET": "16040 VALLEY CT",
           "PROPERTYCLASS": "510", "occupancy": "1", "YearBuilt": 1975,
           "SquareFootage": 1702, "StoryHeight": 1, "condition": "A"}
    row.update(kw)
    return row


_HOUSE = _row()
# Recorded live: a 1.5-story house on Stephanie Ln.
_HALF = _row(PARCELID="82-05-19-007-286.001-024", PROPSTREET="10538 STEPHANIE LN",
             YearBuilt=1981, SquareFootage=2634, StoryHeight=1.5)
# Recorded live: a condominium unit with its own small outline.
_CONDO = _row(PARCELID="82-06-14-014-193.041-027", PROPSTREET="4601 MYSTIC CREEK DR",
              PROPERTYCLASS="550", occupancy="6", YearBuilt=2016, SquareFootage=1732)
# A commercial building: the layer fills its YearBuilt too (class 420).
_SHOP = _row(PARCELID="82-06-01-000-000.000-029", PROPSTREET="16040 VALLEY CT",
             PROPERTYCLASS="420", occupancy="60", YearBuilt=1998, SquareFootage=8800,
             condition="A")
# Vacant residential land beside the house, under the house's own address.
_LOT = _row(PARCELID="82-02-32-009-144.013-030", PROPERTYCLASS="500", occupancy="",
            YearBuilt=0, SquareFootage=0, StoryHeight=0, condition="")

_ADDRESS = "16040 VALLEY CT, EVANSVILLE, IN, 47725"
_POINT = (38.0406, -87.5711)


def _lookup(exact, near=(), address=_ADDRESS, county=VANDERBURGH, slices=None,
            params=None, urls=None, exceeded=False):
    """Drive ``ind.lookup()`` over recorded rows, through the real transport helper."""
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if exceeded:
            raise _shared.TruncatedResponse("truncated at the transfer limit")
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    ind._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return ind.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        ind._lookup_cached.cache_clear()


# ── the ordinary house ─────────────────────────────────────────────────────────


def test_a_house_reports_year_area_stories_and_condition():
    got = _lookup([_HOUSE])
    assert got is not None
    assert (got.year_built, got.sqft, got.stories, got.condition) == (1975, 1702, 1,
                                                                       "average")
    assert got.parcel_id == "82-02-32-009-144.012-030"
    assert "Vanderburgh" in got.source and "nightly" in got.data_vintage


def test_a_geocode_in_the_street_is_settled_by_the_address_in_the_buffer():
    """Every verification geocode landed in the roadway, not on a lot."""
    neighbor = _row(PARCELID="82-02-32-009-144.011-030", PROPSTREET="16030 VALLEY CT")
    got = _lookup([], near=[neighbor, _HOUSE])
    assert got is not None and got.parcel_id == "82-02-32-009-144.012-030"


def test_containment_on_the_neighbors_lot_falls_through_to_the_buffer():
    neighbor = _row(PARCELID="82-02-32-009-144.011-030", PROPSTREET="16030 VALLEY CT",
                    YearBuilt=1990)
    got = _lookup([neighbor], near=[neighbor, _HOUSE])
    assert got is not None and got.year_built == 1975


def test_a_directional_the_matcher_adds_is_not_forgiven():
    roll = _row(PROPSTREET="2308 POWELL AVE")
    assert _lookup([], near=[roll], address="2308 E POWELL AVE, EVANSVILLE, IN") is None


def test_a_house_inside_its_lot_with_no_address_is_still_answered():
    got = _lookup([_HOUSE], address=None)
    assert got is not None and got.year_built == 1975


# ── whose year it is ───────────────────────────────────────────────────────────


def test_a_shops_year_is_never_read():
    assert _lookup([_SHOP]) is None


def test_a_shop_or_a_vacant_lot_beside_the_house_does_not_hide_it():
    got = _lookup([], near=[_SHOP, _LOT, _HOUSE])
    assert got is not None and got.parcel_id == "82-02-32-009-144.012-030"


def test_vacant_land_and_outbuildings_are_never_homes():
    for cls in ("500", "501", "509", "599"):
        assert _lookup([_row(PROPERTYCLASS=cls)]) is None, cls


def test_two_family_three_family_condominium_and_apartments_keep_their_year_only():
    for cls in ("520", "530", "550", "401", "403", "540"):
        got = _lookup([_row(PROPERTYCLASS=cls)])
        assert got is not None and got.year_built == 1975, cls
        assert (got.sqft, got.stories, got.condition) == (None, None, None), cls


def test_a_farmhouse_keeps_its_year_only_with_a_dwelling_record():
    farm = _row(PROPERTYCLASS="101", occupancy="1")
    got = _lookup([farm])
    assert got is not None and got.year_built == 1975 and got.sqft is None
    assert _lookup([_row(PROPERTYCLASS="101", occupancy="")]) is None


def test_a_condominium_unit_reports_its_year_and_never_its_area():
    got = _lookup([_CONDO], address="4601 MYSTIC CREEK DR, EVANSVILLE, IN")
    assert got is not None and got.year_built == 2016
    assert got.sqft is None and got.stories is None


def test_a_one_family_class_with_another_occupancy_refuses_the_area():
    got = _lookup([_row(occupancy="2")])
    assert got is not None and got.year_built == 1975
    assert (got.sqft, got.stories, got.condition) == (None, None, None)


def test_an_address_naming_a_unit_refuses_the_area():
    got = _lookup([_row(PROPSTREET="16040 VALLEY CT UNIT 2")])
    assert got is not None and got.year_built == 1975 and got.sqft is None


# ── numbers ────────────────────────────────────────────────────────────────────


def test_whole_stories_only():
    for raw, want in ((1, 1), (2, 2), (3, 3), (1.5, None), (1.75, None), (0, None),
                      (None, None), (6, None)):
        got = _lookup([_row(StoryHeight=raw)])
        assert got is not None and got.stories == want, raw
    got = _lookup([_HALF], address="10538 STEPHANIE LN, EVANSVILLE, IN")
    assert got is not None and got.stories is None and got.sqft == 2634


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([_row(YearBuilt=0)])
    assert got is not None and got.year_built is None and got.sqft == 1702


def test_the_adapter_floor_is_the_scorer_floor():
    at = _lookup([_row(YearBuilt=EARLIEST_PLAUSIBLE_YEAR)])
    assert at is not None and at.year_built == EARLIEST_PLAUSIBLE_YEAR
    below = _lookup([_row(YearBuilt=EARLIEST_PLAUSIBLE_YEAR - 1)])
    assert below is not None and below.year_built is None
    above = _lookup([_row(YearBuilt=2101)])
    assert above is not None and above.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = _row(YearBuilt=0, SquareFootage=0, StoryHeight=0, condition="")
    assert _lookup([empty]) is None


def test_rows_of_one_parcel_that_disagree_are_not_offered():
    assert _lookup([_HOUSE, _row(YearBuilt=1990)]) is None
    got = _lookup([_HOUSE, dict(_HOUSE)])
    assert got is not None and got.year_built == 1975


def test_two_parcels_at_one_address_are_ambiguous():
    twin = _row(PARCELID="82-02-32-009-144.099-030", YearBuilt=1975)
    assert _lookup([], near=[_HOUSE, twin]) is None


# ── the condition rating ───────────────────────────────────────────────────────


def test_unambiguous_conditions_translate():
    for raw, want in (("Ex", "excellent"), ("G", "good"), ("A", "average"),
                      ("F", "fair"), ("P", "poor")):
        got = _lookup([_row(condition=raw)])
        assert got is not None and got.condition == want, raw


def test_a_condition_between_two_grades_stays_empty():
    for raw in ("VP", "", None, "X"):
        got = _lookup([_row(condition=raw)])
        assert got is not None and got.condition is None, raw


def test_every_translation_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import CONDITION_VALUES
    assert set(ind._CONDITION.values()) <= CONDITION_VALUES


# ── the field list ─────────────────────────────────────────────────────────────

#: Owner, mailing, sale and value columns that exist in this layer.
_PRIVATE = ("NAME", "OWNER1", "OWNER2", "OwnerName", "OWNERSTREET", "OWNERCITY",
            "OWNERSTATE", "OWNERZIP", "LastSaleDate", "LastSalePrice",
            "LANDVALUATION", "IMPVALUATION", "TOTVALUATION", "LEGALDESCRIPTION")


def test_the_field_list_is_explicit_and_carries_nothing_private():
    for cfg in ind.COUNTIES.values():
        fields = cfg.out_fields.split(",")
        assert "*" not in fields and cfg.out_fields.strip()
        for private in _PRIVATE:
            assert private not in fields, private
        assert not any("owner" in f.lower() or "sale" in f.lower() for f in fields)


def test_every_column_read_is_a_column_requested():
    cfg = ind.COUNTIES[VANDERBURGH]
    assert set(_HOUSE) == set(cfg.fields)
    source = inspect.getsource(ind)
    for col in ("PARCELID", "PROPSTREET", "PROPERTYCLASS", "occupancy", "YearBuilt",
                "SquareFootage", "StoryHeight", "condition"):
        assert f'"{col}"' in source and col in cfg.fields, col


def test_the_requested_fields_are_what_reaches_the_service():
    params, urls = [], []
    _lookup([], params=params, urls=urls)
    cfg = ind.COUNTIES[VANDERBURGH]
    assert params and all(p["outFields"] == cfg.out_fields for p in params)
    assert urls and all(u == ind.VANDERBURGH_URL for u in urls)


def test_grade_and_effective_years_are_never_requested():
    for col in ind.COUNTIES[VANDERBURGH].fields:
        assert "EFF" not in col.upper() and col.lower() != "grade"


# ── the county list ────────────────────────────────────────────────────────────


def test_every_claimed_county_is_a_real_indiana_county():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        indiana = {r["geoid"] for r in csv.DictReader(fh)
                   if r["geoid"].startswith("18") and len(r["geoid"]) == 5}
    assert len(indiana) == 92, f"expected 92 Indiana counties, got {len(indiana)}"
    assert ind.COUNTY_FIPS <= indiana
    assert ind.COUNTY_FIPS == {VANDERBURGH}


def test_marion_and_hamilton_are_not_claimed():
    """Marion's only year table is a 2009 snapshot that names a demolished house's
    year on a rebuilt one; Hamilton's layer calls itself "internal use only"."""
    for fips in (MARION, HAMILTON):
        assert fips not in ind.COUNTY_FIPS
        assert ind.url_for(fips) is None
        urls = []
        assert _lookup([_HOUSE], county=fips, urls=urls) is None
        assert urls == []


def test_url_for_names_the_countys_own_layer():
    assert ind.url_for(VANDERBURGH) == ind.VANDERBURGH_URL


def test_a_direct_call_without_a_county_means_vanderburgh():
    got = _lookup([_HOUSE], county=None)
    assert got is not None and got.year_built == 1975


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to fit.
    Pinned against the host constant, not a literal."""
    from housing_label import config
    for cfg in ind.COUNTIES.values():
        assert cfg.timeout + cfg.read_slice < config.UPSTREAM_HOST_BUDGET, cfg.name
    assert ind.LOOKUP_TIMEOUT + ind.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_every_request_passes_the_countys_read_slice():
    slices = []
    assert _lookup([_HOUSE], slices=slices) is not None
    assert slices and all(s == ind.COUNTIES[VANDERBURGH].read_slice for s in slices)
    assert ind.COUNTIES[VANDERBURGH].read_slice > _shared._READ_SLICE_S


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    ind._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        ind.lookup(*_POINT, _ADDRESS, VANDERBURGH)
    finally:
        _shared.get_json = saved
        ind._lookup_cached.cache_clear()
    assert len(seen) == 2, f"expected containment and buffer, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs(seen[0] - started - ind.COUNTIES[VANDERBURGH].timeout) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    ind._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert ind.lookup(*_POINT, _ADDRESS, VANDERBURGH) is None
    finally:
        _shared.get_json = saved
        ind._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer():
    assert _lookup([_HOUSE], exceeded=True) is None


def test_garbage_coordinates_fail_open():
    assert ind.lookup("not a number", None) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
