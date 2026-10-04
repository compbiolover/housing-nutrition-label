#!/usr/bin/env python3
"""The Portland-metro adapter — one regional layer, three county rolls, and what it refuses.

Nothing here touches the network. Metro's service is stubbed with response shapes
recorded from it live, for the reason every adapter test file gives: an adapter
fails open on purpose, so a renamed column or a broken match reads as "this county
has no record here" and would never announce itself. A test that called the real
service would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested in
``test_assessor.py``. What is pinned here is RLIS's own:

1. A **condominium unit is its own taxlot**: a 20-square-foot stand-in polygon in a
   grid beside the building, carrying the unit's own floor area. Its area belongs
   to the reader only when the reader typed that unit.
2. **Washington County writes no unit** into a condominium's site address, so the
   units of one building are indistinguishable by address.
3. The **land-use and property-class columns** are the only statement of whether
   anybody lives on a taxlot, and a commercial condominium is labeled "MFR".
4. A taxlot can hold **several tax accounts**, and the polygon then describes only
   one of them.
5. Two **year values that are not years** — Multnomah's 1800 and 9999.

This file alone: ``pytest tests/test_assessor_pdx.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, pdx

# Recorded live from RLIS Taxlots (Public), 2026-07-17 release. A Clackamas house:
# its BLDGSQFT equals the county's own LIVING_AREA (CMap), as it did on all 120
# Clackamas houses compared.
_HOUSE = {"TLID": "22E32AC05105", "PRIMACCNUM": "05024411",
          "SITEADDR": "13688 JUNEBERRY LN", "YEARBUILT": 2010, "BLDGSQFT": 1408,
          "PROP_CODE": "101", "LANDUSE": "SFR", "HAS_MANY": 0}

# Recorded live. One unit of the 143-account tower at 1500 SW 11th Ave, Portland:
# a 20.7 sq ft stand-in polygon, the unit's own 603 sq ft.
_UNIT = {"TLID": "1S1E04AD  -60062", "PRIMACCNUM": "R603606",
         "SITEADDR": "1500 SW 11TH AVE UNIT #1006", "YEARBUILT": 2006, "BLDGSQFT": 603,
         "PROP_CODE": "122", "LANDUSE": "MFR", "HAS_MANY": 0}
_UNIT_2101 = dict(_UNIT, TLID="1S1E04AD  -60115", PRIMACCNUM="R603659",
                  SITEADDR="1500 SW 11TH AVE UNIT #2101", BLDGSQFT=1051)
_UNIT_507 = dict(_UNIT, TLID="1S1E04AD  -60028", PRIMACCNUM="R603571",
                 SITEADDR="1500 SW 11TH AVE UNIT #507", BLDGSQFT=708)

# Recorded live. A Washington County condominium unit: class 102, and a site
# address with no unit in it — every unit of the building reads the same.
_W_UNIT = {"TLID": "1S101CA92552", "PRIMACCNUM": "R2063390",
           "SITEADDR": "7524 SW BARNES RD", "YEARBUILT": 1977, "BLDGSQFT": 416,
           "PROP_CODE": "102", "LANDUSE": "MFR", "HAS_MANY": 0}

# Recorded live. A taxlot with no tax account (a tract): a record of nothing.
_TRACT = {"TLID": "1N1E13BC  -TR-A", "PRIMACCNUM": " ", "SITEADDR": " ",
          "YEARBUILT": 0, "BLDGSQFT": 0, "PROP_CODE": " ", "LANDUSE": " ", "HAS_MANY": 0}

#: A point in Oregon City. Which taxlot it lands in is decided by the stubbed rows.
_POINT = (45.3573, -122.6068)


def _lookup(exact, near=(), address=None, params=None, slices=None):
    """Drive ``pdx.lookup()`` over recorded rows through the real transport helper.

    ``exact`` is what the point lands inside; ``near`` is what the 80 m search
    finds. ``params`` and ``slices``, when passed, collect what each request was
    handed.
    """
    params = [] if params is None else params
    slices = [] if slices is None else slices

    def fake(url, request, deadline, read_slice=None):
        params.append(request)
        slices.append(read_slice)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    pdx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return pdx.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        pdx._lookup_cached.cache_clear()


# ── the happy path ─────────────────────────────────────────────────────────────


def test_a_house_reports_its_year_and_floor_area():
    got = _lookup([_HOUSE], address="13688 JUNEBERRY LN, OREGON CITY, OR, 97045")
    assert got is not None
    assert got.year_built == 2010 and got.sqft == 1408.0
    assert got.parcel_id == "22E32AC05105"
    assert got.stories is None and got.construction is None
    assert got.foundation is None and got.condition is None


def test_an_off_parcel_geocode_is_rescued_by_its_address():
    got = _lookup([], near=[dict(_HOUSE, SITEADDR="13690 JUNEBERRY LN"), _HOUSE],
                  address="13688 JUNEBERRY LN, OREGON CITY, OR, 97045")
    assert got is not None and got.parcel_id == "22E32AC05105"


def test_rlis_hyphenated_and_spaced_road_names_are_one_road():
    """RLIS writes "BEAVERTON-HILLSDALE HWY" on some taxlots and "BEAVERTON
    HILLSDALE HWY" on others; the Census matcher returns the hyphenated form. In
    the verification run that difference alone refused 4736 SW Beaverton
    Hillsdale Hwy. A hyphen beside a digit is a range or a unit and stays."""
    row = dict(_HOUSE, SITEADDR="4736 SW BEAVERTON HILLSDALE HWY", YEARBUILT=1931)
    got = _lookup([], near=[row],
                  address="4736 SW BEAVERTON-HILLSDALE HWY, PORTLAND, OR, 97221")
    assert got is not None and got.year_built == 1931
    hyphen = dict(row, SITEADDR="7280 SW BEAVERTON-HILLSDALE HWY")
    assert _lookup([], near=[hyphen],
                   address="7280 SW BEAVERTON HILLSDALE HWY, PORTLAND, OR") is not None
    assert pdx._unhyphenated("2405-2411 SE CORA ST UNIT #C-1") == "2405-2411 SE CORA ST UNIT #C-1"


def test_a_relative_locator_lot_is_never_confirmed_as_the_named_house():
    """Multnomah files a lot beside a house under the house's number with a
    locator — "5655 S/ SE HARNEY DR" (south of 5655), "8631 W/ NE HOLLADAY ST" —
    and the lot carries no building (BLDGSQFT 0; year 9999 or the house's year).
    The reader typing 5655 SE Harney Dr means the house, and the lot must never be
    confirmed in its place. Both cases were drawn in the verification sample."""
    lot = dict(_HOUSE, TLID="1S2E19DD  -12300", SITEADDR="5655 S/ SE HARNEY DR",
               YEARBUILT=1952, BLDGSQFT=0)
    house = dict(_HOUSE, TLID="1S2E19DD  -10400", SITEADDR="5655 SE HARNEY DR",
                 YEARBUILT=1952, BLDGSQFT=1947)
    got = _lookup([], near=[lot, house], address="5655 SE HARNEY DR, PORTLAND, OR")
    assert got is not None and got.parcel_id == "1S2E19DD  -10400"
    assert _lookup([lot], address="5655 SE HARNEY DR, PORTLAND, OR") is None


def test_a_taxlot_with_no_tax_account_is_not_a_candidate():
    """A tract or other account-less polygon overlapping a real taxlot would make
    the real one ambiguous; it is dropped before the choice, not after."""
    assert _lookup([_TRACT]) is None
    got = _lookup([_TRACT, _HOUSE])
    assert got is not None and got.year_built == 2010


# ── the buffered search asks only for the house number it can confirm ─────────


def test_the_buffered_search_is_narrowed_to_the_house_number():
    """Downtown, 80 m around a condominium tower reaches about 1,600 taxlots — the stand-
    in polygons of every unit and parking space nearby — against a 2,000-row
    transfer cap, and a truncated page is refused. A taxlot whose address does not
    start with the house number can never be confirmed, so asking only for those
    changes no answer and keeps the page short."""
    params = []
    _lookup([], near=[_HOUSE], address="13688 JUNEBERRY LN, OREGON CITY, OR, 97045",
            params=params)
    buffered = [p for p in params if p.get("distance")]
    contained = [p for p in params if not p.get("distance")]
    assert buffered and buffered[0]["where"] == "SITEADDR LIKE '13688 %'"
    assert contained and "where" not in contained[0], "containment stays unfiltered"


def test_a_truncated_page_is_no_answer():
    def truncated(url, request, deadline, read_slice=None):
        if request.get("distance"):
            raise _shared.TruncatedResponse("cut off")
        return {"features": []}

    pdx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = truncated
    try:
        assert pdx.lookup(*_POINT, "1500 SW 11TH AVE, PORTLAND, OR") is None
    finally:
        _shared.get_json = saved
        pdx._lookup_cached.cache_clear()


# ── the condominium unit that is its own taxlot ────────────────────────────────


def test_a_condo_stack_with_no_unit_typed_is_refused():
    """Every unit shares the street address, so naming one would be a guess."""
    assert _lookup([], near=[_UNIT, _UNIT_2101, _UNIT_507],
                   address="1500 SW 11TH AVE, PORTLAND, OR, 97201") is None


def test_the_typed_unit_picks_its_own_taxlot_and_its_own_floor_area():
    got = _lookup([], near=[_UNIT, _UNIT_2101, _UNIT_507],
                  address="1500 SW 11TH AVE #2101, PORTLAND, OR, 97201")
    assert got is not None
    assert got.parcel_id == "1S1E04AD  -60115"
    assert got.year_built == 2006
    assert got.sqft == 1051.0, "the unit's own area, not the tower's or a neighbor's"


def test_a_unit_matched_without_a_typed_unit_keeps_its_year_but_not_its_area():
    """A sole unit polygon confirmed by street address alone: the building's year
    is right, but which unit the reader lives in is unknown."""
    got = _lookup([_UNIT], address="1500 SW 11TH AVE, PORTLAND, OR, 97201")
    assert got is not None and got.year_built == 2006
    assert got.sqft is None


def test_washington_condo_units_carry_no_unit_so_their_area_is_never_reported():
    """Washington County's site address names the building only. A geocode that
    lands in one unit's polygon gets the building's year — 1977 for all eight units
    of 7524 SW Barnes Rd — and no floor area, typed unit or not."""
    for typed in ("7524 SW BARNES RD, PORTLAND, OR, 97225",
                  "7524 SW BARNES RD #3, PORTLAND, OR, 97225"):
        got = _lookup([_W_UNIT], address=typed)
        assert got is not None and got.year_built == 1977, typed
        assert got.sqft is None, typed
    twins = [_W_UNIT, dict(_W_UNIT, TLID="1S101CA92553", BLDGSQFT=753)]
    assert _lookup([], near=twins, address="7524 SW BARNES RD #3, PORTLAND, OR") is None


def test_the_typed_unit_is_not_made_ambiguous_by_the_buildings_unitless_accounts():
    """Recorded live at 1025 NW Couch St: unit 1514's own taxlot sits within 80 m
    of three accounts filed under the bare street address — the building's
    commercial spaces and common elements. Kept as candidates, they made the
    reader's own unit ambiguous and the verification run refused it."""
    unit = dict(_UNIT, TLID="1N1E34CB  -40295", PRIMACCNUM="R552596",
                SITEADDR="1025 NW COUCH ST UNIT #1514", YEARBUILT=2004, BLDGSQFT=2146)
    base = [dict(unit, TLID=f"1N1E34CB  -4001{i}", PRIMACCNUM=f"R55250{i}",
                 SITEADDR="1025 NW COUCH ST", PROP_CODE="202", BLDGSQFT=4000 + i)
            for i in range(3)]
    other = dict(unit, TLID="1N1E34CB  -40296", SITEADDR="1025 NW COUCH ST UNIT #613")
    got = _lookup([], near=[unit, other, *base],
                  address="1025 NW COUCH ST #1514, PORTLAND, OR, 97209")
    assert got is not None and got.parcel_id == "1N1E34CB  -40295"
    assert got.year_built == 2004 and got.sqft == 2146.0
    assert _lookup([], near=[unit, other, *base],
                   address="1025 NW COUCH ST, PORTLAND, OR, 97209") is None, \
        "with no unit typed the stack stays ambiguous"


def test_a_typed_unit_nobody_names_falls_back_to_the_unitless_candidates():
    got = _lookup([], near=[_HOUSE], address="13688 JUNEBERRY LN #2, OREGON CITY, OR")
    assert got is not None and got.year_built == 2010
    assert got.sqft == 1408.0


def test_unit_spellings_fold_but_leading_zeros_do_not():
    assert pdx._norm_unit("#C-1") == pdx._norm_unit("c1")
    assert pdx._norm_unit("01") != pdx._norm_unit("1")


# ── the one-dwelling rule for floor area ───────────────────────────────────────


def test_an_apartment_building_keeps_its_year_and_drops_its_area():
    """Class 701 is five or more homes; 205,034 sq ft is all of them."""
    apts = dict(_HOUSE, SITEADDR="1610 NE 66TH AVE", PROP_CODE="701", LANDUSE="MFR",
                BLDGSQFT=205034, YEARBUILT=1950)
    got = _lookup([apts], address="1610 NE 66TH AVE, PORTLAND, OR")
    assert got is not None and got.year_built == 1950 and got.sqft is None


def test_a_range_address_is_a_plex_and_reports_no_area():
    """Class 101 includes two-to-four-unit buildings, and they are filed under a
    house-number range — "2405-2411 SE CORA ST" — which no comparison can confirm.
    Reached by containment alone (a label scored from coordinates), the year may
    stand but the area of four homes may not."""
    plex = dict(_HOUSE, SITEADDR="2405-2411 SE CORA ST", BLDGSQFT=1560, YEARBUILT=1917)
    got = _lookup([plex])
    assert got is not None and got.year_built == 1917 and got.sqft is None


def test_a_farm_or_tract_record_reports_no_area():
    """BLDGSQFT is "square footage of building(s)"; on a farm or tract the
    buildings can be several, and nothing says which is the home."""
    for code, use in (("401", "RUR"), ("551", "AGR"), ("641", "FOR")):
        got = _lookup([dict(_HOUSE, PROP_CODE=code, LANDUSE=use)])
        assert got is not None and got.year_built == 2010, code
        assert got.sqft is None, code


def test_a_manufactured_structure_account_reports_its_year_not_its_area():
    got = _lookup([dict(_HOUSE, PROP_CODE="119", LANDUSE=" ")])
    assert got is not None and got.year_built == 2010 and got.sqft is None


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_commercial_condo_labeled_mfr_reports_nothing():
    """RLIS derives LANDUSE "MFR" from class 202, which the Department of Revenue
    defines as a commercial condominium — measured live, office suites of 5,000-
    plus sq ft at 13339 NE Airport Way. The class is read as well as the label."""
    office = dict(_UNIT, SITEADDR="13339 NE AIRPORT WAY UNIT #200", PROP_CODE="202",
                  BLDGSQFT=5896)
    assert _lookup([office]) is None


def test_the_land_uses_that_say_nobody_lives_here_refuse_the_year():
    for use, code in (("COM", "201"), ("IND", "301"), ("PUB", "940"), ("VAC", "100")):
        assert _lookup([dict(_HOUSE, LANDUSE=use, PROP_CODE=code)]) is None, use


def test_a_vacant_class_refuses_the_year_whatever_the_land_use():
    """Washington writes YEARBUILT 2025 on 1,438 class-100 lots — houses finished
    after the assessment date — and Multnomah 2027 on lots not yet built."""
    assert _lookup([dict(_HOUSE, PROP_CODE="550", LANDUSE="AGR")]) is None
    assert _lookup([dict(_HOUSE, PROP_CODE="100", LANDUSE="SFR", YEARBUILT=2025)]) is None


def test_utilities_and_machinery_are_not_homes_but_a_manufactured_home_is():
    assert _lookup([dict(_HOUSE, PROP_CODE="033", LANDUSE=" ")]) is None
    assert _lookup([dict(_HOUSE, PROP_CODE="009", LANDUSE=" ")]).year_built == 2010


def test_silence_is_not_a_refusal():
    """A blank land use and a code Clackamas wrote without its leading zero are
    the roll saying nothing; refusing on silence would discard homes."""
    for row in (dict(_HOUSE, LANDUSE=" ", PROP_CODE=" "),
                dict(_HOUSE, LANDUSE="SFR", PROP_CODE="81")):
        got = _lookup([row])
        assert got is not None and got.year_built == 2010
        assert got.sqft is None, "the area needs a class that says one home"


def test_a_taxlot_holding_several_accounts_reports_nothing():
    """HAS_MANY = 1: the taxlot carries other tax accounts in Metro's separate
    additional-records layer — a second home, a manufactured home on its own
    account — and the polygon describes only one of them."""
    assert _lookup([dict(_HOUSE, HAS_MANY=1)]) is None


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, YEARBUILT=0)])
    assert got is not None and got.year_built is None and got.sqft == 1408.0


def test_the_placeholder_years_are_refused():
    """1800: five Multnomah records, then nothing until 1846. 9999: 675 records."""
    for year in (1800, 9999):
        got = _lookup([dict(_HOUSE, YEARBUILT=year)])
        assert got is not None and got.year_built is None, year
    assert _lookup([dict(_HOUSE, YEARBUILT=1846)]).year_built == 1846


def test_a_record_with_nothing_to_say_is_not_an_answer():
    """Checked through ``assessor_for_point`` too, the door the label uses."""
    empty = dict(_HOUSE, YEARBUILT=0, BLDGSQFT=0)
    assert _lookup([empty]) is None

    def fake(url, request, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    pdx._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    saved_adapters = dict(A.ADAPTERS)
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    A.ADAPTERS["41005"] = pdx
    try:
        assert A.assessor_for_point(*_POINT, "41005") is None
    finally:
        A.ADAPTERS.clear()
        A.ADAPTERS.update(saved_adapters)
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        pdx._lookup_cached.cache_clear()


# ── the field list is the privacy boundary ─────────────────────────────────────


def test_only_named_fields_are_requested_and_none_is_private():
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["outFields"] == pdx._FIELDS for p in params)
    fields = pdx._FIELDS.split(",")
    for private in ("*", "SALEPRICE", "SALEDATE", "OWNERTYPE", "PUBLIC_OWN", "LANDVAL",
                    "BLDGVAL", "TOTALVAL", "ASSESSVAL", "TAXCODE"):
        assert private not in fields, private


def test_the_attribution_carries_the_statement_the_license_requires():
    assert ("Regional Land Information System data are a product of Metro and made "
            "publicly available according to the license agreement found in "
            "https://rlisdiscovery.oregonmetro.gov/pages/open-database-license"
            ) in pdx.ATTRIBUTION
    got = _lookup([_HOUSE])
    assert got is not None and got.source == pdx.ATTRIBUTION


# ── the counties ───────────────────────────────────────────────────────────────


def test_the_three_counties_exist_in_the_repository_county_table():
    with open(_ROOT / "src" / "housing_label" / "data" / "year_built_county.csv",
              newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert pdx.COUNTY_FIPS == {"41005", "41051", "41067"}
    assert pdx.COUNTY_FIPS <= geoids


def test_every_county_is_answered_by_the_one_layer():
    for fips in pdx.COUNTY_FIPS:
        assert pdx.url_for(fips) == pdx.TAXLOT_URL
    assert pdx.url_for("41047") is None, "Marion is not in RLIS"


# ── the clock ──────────────────────────────────────────────────────────────────


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert pdx.LOOKUP_TIMEOUT + pdx.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_every_request_is_handed_this_adapters_slice_and_one_clock():
    seen, slices = [], []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        slices.append(read_slice)
        return {"features": []}

    pdx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        pdx.lookup(*_POINT, "13688 JUNEBERRY LN, OREGON CITY, OR")
    finally:
        _shared.get_json = saved
        pdx._lookup_cached.cache_clear()
    assert len(seen) == 2 and seen[0] == seen[1]
    assert abs((seen[0] - started) - pdx.LOOKUP_TIMEOUT) < 0.5
    assert all(s == pdx.READ_SLICE_S for s in slices)


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_portal_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error")

    pdx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert pdx.lookup(*_POINT, "13688 JUNEBERRY LN, OREGON CITY, OR") is None
    finally:
        _shared.get_json = saved
        pdx._lookup_cached.cache_clear()


def test_no_taxlot_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
