#!/usr/bin/env python3
"""The New Jersey adapter — one statewide MOD-IV layer, and what it has to refuse.

Nothing here touches the network. The state's layer is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"New Jersey has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

The shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is New Jersey's own:

1. The **property class** is the dwelling statement, not the dwelling count:
   whole towns write ``DWELL = 0`` on ordinary houses.
2. **1700** is a placeholder in some rolls, and the roll has years in the future.
3. A **condominium unit** is its own line on a dummy sliver polygon, and the
   mother lot around the slivers is a common element with no year.
4. The **building description** documents a story prefix and nothing else this
   label can read safely.
5. House-number **ranges** and units **glued on with a hyphen** in ``PROP_LOC``.

This file alone: ``pytest tests/test_assessor_nj.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time
from datetime import date

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, nj

# Recorded live from the Parcels and MOD-IV Composite. A one-family house in
# Raritan Township: class 2, one dwelling, no qualifier.
_HOUSE = {"PAMS_PIN": "1021_7_39", "PCL_MUN": "1021", "PCLBLOCK": "7",
          "PCLLOT": "39", "PCLQCODE": " ", "PROP_CLASS": "2",
          "PROP_LOC": "98 SAND HILL ROAD", "YR_CONSTR": 1962, "DWELL": 1,
          "BLDG_DESC": "2SF 2G", "PCL_PBDATE": 1754888400000}

# Recorded live. Bayonne 159/18: the mother lot is the common element (class
# 15F, no year), and each of the four units is a C-qualified line on its own
# sliver, all built in 1920.
_COMMON = {"PAMS_PIN": "0901_159_18", "PCL_MUN": "0901", "PCLBLOCK": "159",
           "PCLLOT": "18", "PCLQCODE": "", "PROP_CLASS": "15F",
           "PROP_LOC": "435 AVENUE E", "YR_CONSTR": None, "DWELL": None,
           "BLDG_DESC": "3S-B-CONDO-4U-H", "PCL_PBDATE": 1761714000000}
_UNITS = [dict(_COMMON, PAMS_PIN=f"0901_159_18_{q}", PCLQCODE=q, PROP_CLASS="2",
               YR_CONSTR=1920, DWELL=1)
          for q in ("C0001", "C0101", "C0201", "C0301")]

# Recorded live: an unmatched polygon — a parcel with no MOD-IV line joined.
_UNMATCHED = {"PAMS_PIN": "0901_159_99", "PCL_MUN": "0901", "PCLBLOCK": "159",
              "PCLLOT": "99", "PCLQCODE": None, "PROP_CLASS": None,
              "PROP_LOC": None, "YR_CONSTR": None, "DWELL": None,
              "BLDG_DESC": None, "PCL_PBDATE": 1761714000000}

#: A point in Raritan Township. Which parcel a coordinate lands in is decided here
#: by the stubbed rows, not by the coordinate.
_POINT = (40.5070, -74.8640)


def _lookup(exact, near=(), address=None, slices=None, params=None):
    """Drive ``nj.lookup()`` over recorded rows, through the real transport helper,
    so the field list, the candidate filter and the parcel choice all run."""
    slices = [] if slices is None else slices
    params = [] if params is None else params

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    nj._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return nj.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        nj._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_its_year_and_its_stories():
    got = _lookup([_HOUSE], address="98 SAND HILL RD, RARITAN, NJ")
    assert got is not None
    assert got.year_built == 1962
    assert got.stories == 2
    assert got.parcel_id == "1021_7_39"
    assert got.sqft is None, "the layer carries no floor area"
    assert got.construction is None and got.foundation is None
    assert got.condition is None
    assert "NJOGIS" in got.source, "the license asks for the acknowledgement"


def test_an_off_parcel_geocode_is_rescued_by_its_address():
    got = _lookup([], near=[_HOUSE], address="98 SAND HILL RD, RARITAN, NJ")
    assert got is not None and got.year_built == 1962


def test_a_neighbor_under_the_point_is_not_taken_for_the_house():
    neighbor = dict(_HOUSE, PAMS_PIN="1021_7_40", PCLLOT="40",
                    PROP_LOC="100 SAND HILL ROAD", YR_CONSTR=1990)
    assert _lookup([neighbor], address="98 SAND HILL RD, RARITAN, NJ") is None


def test_the_county_parcel_publication_date_travels_with_the_value():
    got = _lookup([_HOUSE])
    assert got is not None
    assert got.data_vintage.startswith(nj.DATA_VINTAGE)
    assert "county parcels published 2025-08-11" in got.data_vintage


def test_a_missing_publication_date_falls_back_rather_than_inventing_one():
    for bad in (None, 0, -1, "junk"):
        got = _lookup([dict(_HOUSE, PCL_PBDATE=bad)])
        assert got is not None and got.data_vintage == nj.DATA_VINTAGE, bad


# ── the class is the dwelling statement ────────────────────────────────────────


def test_a_zero_dwelling_count_on_a_residential_line_is_not_a_refusal():
    """Upper Township writes DWELL 0 on 4,925 class-2 homes, Delran on 4,356,
    Secaucus on 1,688; Westfield's are new colonials. Read as "no dwelling" it
    would refuse three whole towns."""
    got = _lookup([dict(_HOUSE, DWELL=0)])
    assert got is not None and got.year_built == 1962
    assert got.stories is None, "stories still need one dwelling, stated"


def test_classes_that_say_nobody_lives_here_refuse_the_year():
    """Vacant land, qualified farmland (land only), industrial, railroad,
    utility and every exempt class: a year there is a shed's, a church's, a
    school's or a condominium's common elements."""
    for cls in ("1", "3B", "4B", "5A", "5B", "6A", "15A", "15B", "15C", "15D",
                "15E", "15F", None, ""):
        row = dict(_HOUSE, PROP_CLASS=cls, BLDG_DESC=None)
        assert _lookup([row]) is None, cls


def test_apartments_report_the_buildings_year():
    got = _lookup([dict(_HOUSE, PROP_CLASS="4C", DWELL=None, BLDG_DESC="3S-B-8APT")])
    assert got is not None and got.year_built == 1962
    assert got.stories is None, "a story count is one home's, not a building's"


def test_a_commercial_line_answers_only_where_a_dwelling_is_recorded():
    """The apartment over a shop: 30,829 class-4A parcels carry a year and a
    dwelling. A bare commercial line is somebody's shop."""
    assert _lookup([dict(_HOUSE, PROP_CLASS="4A", DWELL=1)]).year_built == 1962
    for dwell in (0, None):
        assert _lookup([dict(_HOUSE, PROP_CLASS="4A", DWELL=dwell,
                             BLDG_DESC=None)]) is None, dwell


def test_a_farm_answers_unless_it_explicitly_records_no_dwelling():
    assert _lookup([dict(_HOUSE, PROP_CLASS="3A", BLDG_DESC=None)]).year_built == 1962
    assert _lookup([dict(_HOUSE, PROP_CLASS="3A", DWELL=None,
                         BLDG_DESC=None)]).year_built == 1962
    assert _lookup([dict(_HOUSE, PROP_CLASS="3A", DWELL=0, BLDG_DESC=None)]) is None


# ── the years that are not years ───────────────────────────────────────────────


def test_year_zero_and_blank_are_not_years():
    for bad in (0, None, "", "  "):
        got = _lookup([dict(_HOUSE, YR_CONSTR=bad)])
        assert got is not None and got.year_built is None, bad
        assert got.stories == 2, "the row still carries a story count"
    assert _lookup([dict(_HOUSE, YR_CONSTR=0, BLDG_DESC=None)]) is None


def test_1700_is_a_placeholder_and_is_refused():
    """Union City writes 1700 on 207 homes and Elizabeth on 173, with nothing
    between 1700 and the 1770s in either."""
    got = _lookup([dict(_HOUSE, YR_CONSTR=1700, BLDG_DESC=None)])
    assert got is None
    assert _lookup([dict(_HOUSE, YR_CONSTR=1709)]).year_built == 1709


def test_keying_slips_below_the_floor_are_refused():
    for bad in (1, 2, 4, 18, 194, 1089):
        assert _lookup([dict(_HOUSE, YR_CONSTR=bad)]).year_built is None, bad


def test_a_year_in_the_future_is_refused():
    """2028, 2082, 2100, 9999 are all on the roll; none is when anything went up."""
    nxt = date.today().year + 1
    assert _lookup([dict(_HOUSE, YR_CONSTR=nxt)]).year_built == nxt
    for bad in (nxt + 1, 2082, 2100, 9999):
        assert _lookup([dict(_HOUSE, YR_CONSTR=bad)]).year_built is None, bad


# ── condominiums ───────────────────────────────────────────────────────────────


def test_a_condominium_common_element_is_not_an_answer():
    """The geocode usually lands in the mother lot, the common element around the
    unit slivers. It confirms against the building's address and has no year, so
    left in as a candidate it would end the lookup with nothing."""
    got = _lookup([_COMMON], near=[_COMMON] + _UNITS,
                  address="435 AVENUE E, BAYONNE, NJ")
    assert got is not None
    assert got.year_built == 1920
    assert got.parcel_id == "0901_159_18", "the lot's own PIN, not one unit's"


def test_agreeing_unit_lines_of_one_lot_are_one_answer():
    got = _lookup([], near=_UNITS, address="435 AVENUE E #3, BAYONNE, NJ")
    assert got is not None and got.year_built == 1920
    assert got.stories is None, "a unit line never reports the tower's floors"


def test_unit_lines_that_disagree_on_the_year_stay_ambiguous():
    """A complex built in phases, or a mobile-home park where each line is its own
    home: which one the reader lives in cannot be told from the address."""
    phased = _UNITS[:2] + [dict(_UNITS[2], YR_CONSTR=1985)]
    assert _lookup([], near=phased, address="435 AVENUE E, BAYONNE, NJ") is None


def test_unit_lines_of_different_lots_are_not_merged():
    other_lot = [dict(u, PCLLOT="19", PAMS_PIN=u["PAMS_PIN"].replace("_18_", "_19_"))
                 for u in _UNITS[:1]]
    assert _lookup([], near=_UNITS[:1] + other_lot,
                   address="435 AVENUE E, BAYONNE, NJ") is None


def test_a_single_unit_sliver_under_the_point_answers_under_its_own_pin():
    got = _lookup([_UNITS[0]], address="435 AVENUE E, BAYONNE, NJ")
    assert got is not None and got.year_built == 1920
    assert got.parcel_id == "0901_159_18_C0001"


def test_an_unmatched_polygon_does_not_make_a_real_parcel_unreachable():
    got = _lookup([_UNMATCHED], near=[_UNMATCHED, _HOUSE],
                  address="98 SAND HILL RD, RARITAN, NJ")
    assert got is not None and got.year_built == 1962
    assert _lookup([_UNMATCHED]) is None


def test_a_yearless_row_under_the_point_with_no_address_is_still_no_answer():
    """Dropping rows that cannot answer must not turn a bare coordinate into a
    buffered guess: with no address there is nothing to confirm a neighbor by."""
    assert _lookup([_COMMON], near=_UNITS) is None


# ── stories ────────────────────────────────────────────────────────────────────


def test_only_the_documented_story_prefix_is_read():
    for desc, want in (("1SF", 1), ("2S-F-L-AG", 2), ("2 SF", 2), ("3SB", 3),
                       ("2SFRDWG", 2), ("1S CB", 1)):
        assert _lookup([dict(_HOUSE, BLDG_DESC=desc)]).stories == want, desc


def test_a_square_footage_or_a_model_name_is_not_a_story_count():
    """"1970 SF" is a floor area in square feet, "1805 2BR 25BT 5" is Fort Lee's
    area and bedrooms, "HAMPTON" is a builder's model — all recorded live."""
    for desc in ("1970 SF", "1805 2BR 25BT 5", "HAMPTON", "1 FAMILY", "TOWNHOUSE",
                 "106A1SWS1G1F", "", None):
        assert _lookup([dict(_HOUSE, BLDG_DESC=desc)]).stories is None, desc


def test_half_stories_and_implausible_counts_are_dropped():
    for desc in ("1.5SF", "1.75 SF G", "2.5SF", "5SF4UG", "9S"):
        assert _lookup([dict(_HOUSE, BLDG_DESC=desc)]).stories is None, desc


def test_stories_need_one_home_in_one_building():
    for change in ({"DWELL": 2}, {"DWELL": None}, {"PCLQCODE": "C0001"},
                   {"PROP_LOC": "98 SAND HILL ROAD UNIT 2"},
                   {"BLDG_DESC": "2S-B-CONDO"}, {"PROP_CLASS": "4C"}):
        got = _lookup([dict(_HOUSE, **change)])
        assert got is not None and got.stories is None, change


def test_the_wall_codes_are_not_translated():
    """"2SST" is two-story stucco twin or two-story stone; towns add codes the
    manual does not have. Nothing in the description reaches construction."""
    for desc in ("2SST", "1SB", "2S-VS-L", "1.5SAL", "2SCB"):
        assert _lookup([dict(_HOUSE, BLDG_DESC=desc)]).construction is None, desc


# ── the address ────────────────────────────────────────────────────────────────


def test_a_unit_glued_on_with_a_hyphen_still_parses():
    """Recorded live: "1919 BAY BLVD-UNIT B37" (Toms River), "321 ELM ST - UNIT A"
    (Westfield). Unseparated, BLVD-UNIT is a street type nobody has heard of."""
    row = dict(_HOUSE, PROP_LOC="1919 BAY BLVD-UNIT B37")
    assert _lookup([], near=[row], address="1919 BAY BLVD, TOMS RIVER, NJ") is not None
    row = dict(_HOUSE, PROP_LOC="321 ELM ST - UNIT A")
    assert _lookup([], near=[row], address="321 ELM ST, WESTFIELD, NJ") is not None


def test_a_house_number_range_answers_for_a_number_inside_it():
    row = dict(_HOUSE, PROP_LOC="65-67 WESTFIELD AVE")
    for asked in ("65 WESTFIELD AVE, ELIZABETH, NJ", "67 WESTFIELD AVE, ELIZABETH, NJ"):
        assert _lookup([], near=[row], address=asked) is not None, asked
    short = dict(_HOUSE, PROP_LOC="3509-11 CENTRAL AVE")
    assert _lookup([], near=[short], address="3511 CENTRAL AVE, OCEAN CITY, NJ")


def test_a_number_outside_the_range_or_across_the_street_does_not():
    row = dict(_HOUSE, PROP_LOC="65-67 WESTFIELD AVE")
    for asked in ("66 WESTFIELD AVE, ELIZABETH, NJ", "69 WESTFIELD AVE, ELIZABETH, NJ",
                  "63 WESTFIELD AVE, ELIZABETH, NJ"):
        assert _lookup([], near=[row], address=asked) is None, asked


def test_a_malformed_range_is_offered_only_under_its_low_number():
    row = dict(_HOUSE, PROP_LOC="10-900 MAIN ST")
    assert _lookup([], near=[row], address="10 MAIN ST, TRENTON, NJ") is not None
    assert _lookup([], near=[row], address="12 MAIN ST, TRENTON, NJ") is None


def test_the_rolls_own_spellings_match_the_matchers():
    """Each recorded live in the end-to-end run, as a pair that failed before the
    respelling: the roll's string first, the Census matcher's second."""
    for roll, matched in (
            ("85 NO. GROVE ST.", "85 N GROVE ST, EAST ORANGE, NJ, 07017"),
            ("71 SO. HARRISON ST.", "71 S HARRISON ST, EAST ORANGE, NJ, 07018"),
            ("313 NO 16TH ST", "313 N 16TH ST, KENILWORTH, NJ, 07033"),
            ("61 TULANE STREET N", "61 N TULANE ST, PRINCETON, NJ, 08542"),
            ("561 GRANT AVE E", "561 E GRANT AVE, ROSELLE PARK, NJ, 07204"),
            ("235 MC ELROY AVE.", "235 MCELROY AVE, FORT LEE, NJ, 07024"),
            ("4 LANCELOT LA", "4 LANCELOT LN, MOUNT LAUREL, NJ, 08054"),
            ("110 BUCKNELL TR", "110 BUCKNELL TRL, HOPATCONG, NJ, 07843")):
        row = dict(_HOUSE, PROP_LOC=roll)
        assert _lookup([], near=[row], address=matched) is not None, roll


def test_respelling_never_forgives_a_directional_on_one_side_only():
    """"439 S WILLOW AVE" against the roll's "439 WILLOW AVE" (Galloway): 100 N
    Main and 100 S Main are different houses, and either could be the one meant."""
    row = dict(_HOUSE, PROP_LOC="439 WILLOW AVE")
    assert _lookup([], near=[row], address="439 S WILLOW AVE, GALLOWAY, NJ") is None
    row = dict(_HOUSE, PROP_LOC="561 GRANT AVE E")
    assert _lookup([], near=[row], address="561 W GRANT AVE, ROSELLE PARK, NJ") is None


def test_a_street_named_for_a_letter_keeps_its_name():
    """Bayonne's AVENUE E is a street called E, not an avenue with a direction."""
    assert nj._comparable("435 AVENUE E") == "435 AVENUE E"
    assert nj._comparable("100 NO ST") == "100 NO ST"
    got = _lookup([], near=[_UNITS[0]], address="435 AVENUE E, BAYONNE, NJ")
    assert got is not None
    assert _lookup([], near=[_UNITS[0]], address="435 E AVENUE, BAYONNE, NJ") is None


# ── the field list is the privacy boundary ─────────────────────────────────────


def test_no_owner_mailing_sale_or_value_column_is_requested():
    fields = nj._FIELDS.split(",")
    for private in ("OWNER_NAME", "ST_ADDRESS", "CITY_STATE", "ZIP_CODE", "ZIP5",
                    "ZIP_PLUS4", "DEED_BOOK", "DEED_PAGE", "DEED_DATE", "SALE_PRICE",
                    "SALES_CODE", "LAND_VAL", "IMPRVT_VAL", "NET_VALUE",
                    "LAST_YR_TX", "*"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["outFields"] == nj._FIELDS for p in params)


# ── the county list ────────────────────────────────────────────────────────────


def test_all_21_new_jersey_counties_and_nothing_else():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("34") and len(r["geoid"]) == 5}
    assert len(census) == 21
    assert nj.COUNTY_FIPS == census


def test_url_for_names_the_one_layer_for_every_county_and_none_elsewhere():
    for fips in nj.COUNTY_FIPS:
        assert nj.url_for(fips) == nj.PARCEL_URL
    assert nj.url_for("36061") is None


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert nj.LOOKUP_TIMEOUT + nj.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_the_shared_read_slice_is_what_reaches_the_transport():
    slices = []
    assert _lookup([_HOUSE], slices=slices) is not None
    assert slices and all(s == nj.READ_SLICE_S == _shared._READ_SLICE_S for s in slices)


def test_both_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    nj._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        nj.lookup(*_POINT, "98 SAND HILL RD, RARITAN, NJ")
    finally:
        _shared.get_json = saved
        nj._lookup_cached.cache_clear()
    assert len(seen) == 2 and seen[0] == seen[1]
    assert abs(seen[0] - started - nj.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    nj._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert nj.lookup(*_POINT, "98 SAND HILL RD, RARITAN, NJ") is None
    finally:
        _shared.get_json = saved
        nj._lookup_cached.cache_clear()


def test_a_truncated_page_is_refused():
    def truncated(url, request, deadline, read_slice=None):
        raise _shared.TruncatedResponse("truncated")

    nj._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = truncated
    try:
        assert nj.lookup(*_POINT, "98 SAND HILL RD, RARITAN, NJ") is None
    finally:
        _shared.get_json = saved
        nj._lookup_cached.cache_clear()


def test_a_parcel_that_records_nothing_is_not_an_answer_through_the_registry():
    """Checked through ``assessor_for_point`` where the registry has the module,
    and through the adapter directly either way."""
    empty = dict(_HOUSE, YR_CONSTR=0, BLDG_DESC=None)
    assert _lookup([empty]) is None
    if A.adapter_for_county("34035") is not nj:
        return

    def fake(url, request, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    nj._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    try:
        assert A.assessor_for_point(*_POINT, "34035") is None
    finally:
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        nj._lookup_cached.cache_clear()
