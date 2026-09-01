#!/usr/bin/env python3
"""The Connecticut adapter — one statewide layer, and the four things it has to refuse.

Nothing here touches the network. The state's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Connecticut has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely Connecticut's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Connecticut's own four:

1. The street address arrives in **two columns**, and whole towns file only one of
   them. Greenwich writes the other one inverted.
2. A **condominium unit** is its own parcel here, and the roll's two address
   columns can name two different units — or two different buildings — on one row.
3. The ``Condition`` column looks exactly like what the label wants and is
   **forty-odd incompatible vocabularies** from 169 CAMA vendors.
4. Connecticut's county codes **changed**, and an adapter registered on the old
   ones would never be reached.

This file alone: ``pytest tests/test_assessor_ct.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, ct

# Recorded live from the Connecticut CAMA and Parcel Layer. A single-family house
# in West Hartford: one dwelling, so its living area is that home's.
_HOUSE = {"Parcel_ID": "2176 2 70    0001", "Location": "70 FOXCROFT ROAD ",
          "Location_1": "70 FOXCROFT ROAD", "AYB": 1941.0, "Living_Area": 3152.0,
          "Occupancy": 1.0, "Collection_year": "2025"}

# Recorded live. Manchester files no parcel-map address at all — the whole town is
# null in `Location` — so the CAMA column is the only one that can confirm it.
_CAMA_ONLY = {"Parcel_ID": "51800044774", "Location": None,
              "Location_1": "961 HILLSTOWN ROAD", "AYB": 1985.0,
              "Living_Area": 1602.0, "Occupancy": 1.0, "Collection_year": "2025"}

# Recorded live. Greenwich writes the CAMA column inverted — street first, house
# number zero-padded last — and the ordinary form only in the parcel-map column.
_INVERTED = {"Parcel_ID": "GW-200", "Location": "200 OLD MILL ROAD",
             "Location_1": "OLD MILL ROAD 0200", "AYB": 1955.0,
             "Living_Area": 2400.0, "Occupancy": 1.0, "Collection_year": "2025"}

# Recorded live. A Bridgeport condominium: one unit, one parcel, `Occupancy` of 1
# — and the two address columns naming two different units of the same building.
_CONDO = {"Parcel_ID": "116-2", "Location": "350 GROVERS AV #01A",
          "Location_1": "350 GROVERS AV #11C", "AYB": 1975.0,
          "Living_Area": 1284.0, "Occupancy": 1.0, "Collection_year": "2025"}

# Easton parcel 3771 27, whose two columns name two different streets — the
# parcel-map filing and the CAMA filing joined to each other wrongly. The address
# pair is exactly as recorded live; the year and occupancy are not.
#
# Its own are AYB 1725 and Occupancy 2, and BOTH would stop this row contributing
# a fact for reasons that have nothing to do with the contradiction — the year
# falls under the 1800 floor and the dwelling count refuses the area — so a
# fixture carrying them would make every assertion below pass without the
# contradiction rule existing at all. What is under test is the contradiction, so
# the row is given a year and a count that would otherwise answer.
_CONTRADICTORY = {"Parcel_ID": "3771 27", "Location": "80 SUNNY RIDGE ROAD",
                  "Location_1": "545 NORTH PARK AVENUE", "AYB": 1941.0,
                  "Living_Area": 2816.0, "Occupancy": 1.0,
                  "Collection_year": "2025"}

#: A point in West Hartford. Every test uses the same one: which parcel a
#: coordinate lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (41.7535, -72.7614)


def _lookup(exact, near=(), address=None, slices=None, params=None):
    """Drive ``ct.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find. Both are answered through the real transport helper, so the field
    list, the address choice and the parcel selection are all exercised rather
    than stepped over.

    ``slices`` and ``params``, when passed, collect what each request was handed,
    so a test can check what reaches the transport rather than only what a
    constant says.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    ct._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return ct.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        ct._lookup_cached.cache_clear()


# ── the address that arrives in two columns ────────────────────────────────────


def test_a_town_that_files_no_parcel_map_address_is_still_reachable():
    """`Location` is null for 231,524 of the state's 1,029,326 residential parcels,
    and not at random — Manchester, Enfield, Hartford, Rocky Hill, Wethersfield,
    Woodstock, Killingly and Stamford are blank in it entirely.

    Reading only that column would lose those towns wholesale, and silently: the
    parcel would be found, fail its address confirmation, and read as "no record"."""
    got = _lookup([], near=[_CAMA_ONLY], address="961 HILLSTOWN RD, MANCHESTER, CT")
    assert got is not None and got.year_built == 1985


def test_greenwich_writes_the_cama_column_backwards_and_is_still_reachable():
    """"OLD MILL ROAD 0200" is not an address any comparison can anchor on — there
    is no house number to anchor on, because it was moved to the end and padded.

    The column is skipped because it does not PARSE, not because the town is named
    in a table somewhere. That is one rule instead of 169, and it is checked with
    the same parse the comparison itself runs."""
    assert ct._address_of(_INVERTED) == "200 OLD MILL ROAD"
    got = _lookup([], near=[_INVERTED], address="200 OLD MILL RD, GREENWICH, CT")
    assert got is not None and got.year_built == 1955


def test_the_cama_column_wins_when_both_parse():
    """Preference, not fallback. New Haven's parcel-map column holds the bare
    string "93" for every parcel in a neighbourhood; the CAMA column holds the real
    address. Trying the parcel-map column first would pick the junk."""
    junk = dict(_HOUSE, Location="93")
    assert ct._address_of(junk) == "70 FOXCROFT ROAD"


def test_a_row_with_no_usable_address_in_either_column_offers_none():
    """Offering an unparseable string would not be dangerous — the comparison would
    reject it — but None is what ``select_parcel`` expects for "this row cannot be
    confirmed", and it keeps the containment-without-an-address path honest."""
    assert ct._address_of({"Location": None, "Location_1": "  "}) is None
    assert ct._address_of({"Location": "93", "Location_1": None}) is None


def test_a_row_whose_two_columns_name_different_buildings_has_no_address():
    """The two columns are two filings joined per town, and the join is sometimes
    wrong: Easton parcel 3771 27 reads "80 SUNNY RIDGE ROAD" against "545 NORTH
    PARK AVENUE".

    Preferring either would let ``select_parcel`` confirm the parcel against an
    address it does not have — a stranger's house reported as observed fact, which
    is precisely what the selection policy exists to prevent, arriving through the
    field accessor rather than through the geometry. So the row has no address and
    cannot be confirmed at all."""
    assert ct._address_of(_CONTRADICTORY) is None
    assert _lookup([_CONTRADICTORY],
                   address="545 NORTH PARK AVE, EASTON, CT") is None
    assert _lookup([], near=[_CONTRADICTORY],
                   address="80 SUNNY RIDGE RD, EASTON, CT") is None


def test_a_contradictory_row_is_refused_with_no_address_to_confirm_against():
    """The hole that refusing inside ``_address_of`` alone does not close.

    ``select_parcel`` returns a sole containing parcel WITHOUT consulting the
    address when the caller passed none — correctly, since containment is then all
    there is — and the label is scored from bare coordinates whenever the geocoder
    echoes no address, so this path runs in production. A mis-joined row under such
    a point would be emitted as observed fact with nothing to catch it, which is
    why the row is dropped in ``_parcels`` as well.

    The fixture deliberately carries a year and a dwelling count that WOULD answer;
    see its definition."""
    assert _lookup([_CONTRADICTORY]) is None
    assert _lookup([_CONTRADICTORY], address=None) is None


def test_the_fixture_would_answer_if_its_addresses_agreed():
    """Guards the test above from passing vacuously. If the contradictory row were
    refused for its year or its dwelling count rather than for its addresses, every
    assertion about the contradiction would hold with the rule deleted."""
    agreeing = dict(_CONTRADICTORY, Location_1="80 SUNNY RIDGE ROAD")
    got = _lookup([agreeing])
    assert got is not None and got.year_built == 1941 and got.sqft == 2816.0


def test_two_columns_that_differ_only_in_spelling_are_not_a_disagreement():
    """The rule is about which BUILDING the row names, not about which string. A
    town that abbreviates in one filing and spells out in the other is agreeing,
    and refusing it would cost most of the state."""
    spelled = dict(_HOUSE, Location="70 FOXCROFT RD", Location_1="70 FOXCROFT ROAD")
    assert ct._address_of(spelled) == "70 FOXCROFT ROAD"
    got = _lookup([spelled])
    assert got is not None and got.year_built == 1941


# ── the condominium unit that is its own parcel ────────────────────────────────


def test_a_condominium_unit_reports_its_year_but_not_its_floor_area():
    """Connecticut files each unit as its own parcel with `Occupancy` of 1, so the
    dwelling-count rule that catches Florida's towers passes here and catches
    nothing.

    What disqualifies the area is that the roll's own two address columns disagree
    about which unit the row describes — #01A in one, #11C in the other. The year
    is right for every unit in the building; the 1,284 sq ft is right for at most
    one of them, and we cannot tell which."""
    got = _lookup([_CONDO], address="350 GROVERS AVENUE, BRIDGEPORT, CT")
    assert got is not None
    assert got.year_built == 1975
    assert got.sqft is None


def test_two_spellings_of_a_unit_are_not_two_buildings():
    """The unit disagreement and the building disagreement are separate faults with
    separate answers, and conflating them would break one of the two.

    ``address_key`` drops the unit before comparing, so 116-2's "#01A" and "#11C"
    parse alike: the row still names 350 Grovers Avenue, which is the building the
    coordinate is in, so it stays confirmable and its year comes through. Only its
    floor area is refused. A row differing in the house number too — 106-35K's
    "120 BEACHVIEW AV" against "110 BEACHVIEW AV" — is refused outright instead."""
    assert ct._address_of(_CONDO) == "350 GROVERS AV #11C"
    two_buildings = dict(_CONDO, Location="120 BEACHVIEW AV #244",
                         Location_1="110 BEACHVIEW AV #202")
    assert ct._address_of(two_buildings) is None


def test_an_avenue_abbreviated_av_is_the_same_street_as_ave():
    """Bridgeport, New Haven and other Connecticut towns write "AV" where the
    Census matcher returns "AVE". Without the shared table knowing that spelling
    the two parse as different streets and the parcel is refused — a silent
    coverage loss across 17,766 of the state's residential parcels, and the reason
    the condominium case above resolves at all.

    Canonicalised, not dropped: an avenue still does not match a street."""
    assert _shared.same_address("350 GROVERS AVE", "350 GROVERS AV")
    assert _shared.same_address("350 GROVERS AVENUE", "350 GROVERS AV")
    assert not _shared.same_address("350 GROVERS AV", "350 GROVERS ST")


def test_a_unit_in_either_column_is_enough_to_refuse_the_area():
    """Both columns are consulted, not just the one the address choice landed on.
    A row that spells the unit in only one of them is still a unit record."""
    for row in (dict(_CONDO, Location="350 GROVERS AV"),
                dict(_CONDO, Location_1="350 GROVERS AV")):
        assert ct._is_a_unit_record(row), row
    assert not ct._is_a_unit_record(_HOUSE)


def test_a_house_reports_its_floor_area():
    """The other side of the same rule — one dwelling, no unit designator, so the
    living area IS this home's area. Without this the rule would be safe and
    useless."""
    got = _lookup([_HOUSE])
    assert got is not None and got.sqft == 3152.0


def test_more_than_one_dwelling_refuses_the_area_and_keeps_the_year():
    """A duplex's living area covers both homes. The building still went up when it
    went up.

    "Exactly one dwelling or nothing" is the easy rule to write here and would drop
    the year for every home in a building holding more than one."""
    got = _lookup([dict(_HOUSE, Occupancy=2.0, Living_Area=4300.0)])
    assert got is not None and got.year_built == 1941
    assert got.sqft is None


def test_a_parcel_the_roll_says_holds_no_dwelling_reports_no_year():
    """The area already refuses a commercial parcel; the year has to refuse it for
    the same reason. A town garage's year built is not the year the reader's home
    went up, and it would carry the ``observed`` tag that tells them not to doubt
    it."""
    shop = dict(_HOUSE, Occupancy=0.0, Living_Area=18000.0)
    assert _lookup([shop]) is None


def test_a_town_that_stops_filling_the_occupancy_column_does_not_lose_its_year():
    """An explicit 0 is the town saying "no dwelling here". A missing field is the
    town saying nothing — 180,410 parcels are null against 60,363 zero, so the two
    are separately populated — and refusing on silence would cost whole towns their
    coverage."""
    silent = {k: v for k, v in _HOUSE.items() if k != "Occupancy"}
    got = _lookup([silent])
    assert got is not None and got.year_built == 1941
    assert got.sqft is None, "the area still needs the count it is built on"


# ── the columns that must not be read ──────────────────────────────────────────


def test_the_condition_column_is_never_requested():
    """It is the field the label most wants and the one this source cannot supply:
    169 municipal CAMA vendors write more than forty distinct values on at least
    four incompatible scales — 'A', 'G', '7', '5', 'AV', 'VG', 'A+', '4.0', '33',
    'RB' — with no code table published anywhere with the service.

    Not requesting it is cheaper than trusting a mapping: a column that never
    arrives cannot be read by a later edit."""
    assert "Condition" not in ct._FIELDS.split(",")


def test_the_effective_year_is_not_even_requested():
    """Towns move EYB forward when a property is improved, so it describes
    condition rather than when the building went up."""
    assert "EYB" not in ct._FIELDS.split(",")
    assert "AYB" in ct._FIELDS.split(",")


def test_the_field_list_is_the_privacy_boundary():
    """This layer's other 48 columns carry owner names, co-owner names, owner
    mailing addresses, sale prices and every assessed and appraised value. None of
    it is an input to any dimension, and requesting it would put personal data in a
    process cache for no benefit."""
    for private in ("Owner", "Co_Owner", "Mailing_Address", "Mailing_City",
                    "Mailing_State", "Mailing_Zip", "Sale_Price", "Sale_Date",
                    "Assessed_Total", "Appraised_Building", "*"):
        assert private not in ct._FIELDS.split(","), private


def test_the_requested_fields_are_what_reaches_the_service():
    """Pinned on what the transport is handed, not on the constant. A field list
    nothing passes through is a comment — and the privacy assertion above would
    then be asserting about a string rather than about a request."""
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["outFields"] == ct._FIELDS for p in params)


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    """Connecticut's "not recorded", on 86,360 parcels. Passed through it would age
    the building by two thousand years and be scored as a fact."""
    got = _lookup([dict(_HOUSE, AYB=0.0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 3152.0, "the area survives; only the year is missing"


def test_a_parcel_that_records_nothing_at_all_is_not_an_answer():
    """A real parcel with no year and no area contributed no fact. Passing it on
    would count as "the assessor answered" in both the reader's tag and the
    coverage metric.

    Checked through ``assessor_for_point``, which is the door the label actually
    uses. Testing ``ct.lookup`` alone would assert something about the adapter's
    private shape rather than about what reaches a reader."""
    empty = dict(_HOUSE, AYB=0.0, Living_Area=0.0)
    assert _lookup([empty]) is None

    def fake(url, request, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    ct._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    try:
        assert A.assessor_for_point(*_POINT, "09110") is None
    finally:
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        ct._lookup_cached.cache_clear()


# ── the vintage a reader can date ──────────────────────────────────────────────


def test_the_collection_year_travels_with_the_value():
    """The GIS Office reruns the collection annually and republishes under an
    unchanged URL, so a hard-coded year would go stale silently. 57,231 parcels
    still carry 2024 against 1,217,852 at 2025, so the year is per-record rather
    than a property of the layer."""
    got = _lookup([_HOUSE])
    assert got is not None and "2025 collection" in got.data_vintage


def test_a_missing_collection_year_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_HOUSE, Collection_year=None)])
    assert got is not None
    assert got.data_vintage == ct.DATA_VINTAGE
    assert "collection" not in got.data_vintage


def test_a_parcel_with_no_identifier_is_still_an_answer():
    """The parcel id is null on roughly a fifth of the state's residential parcels.
    It is what lets a reader trace a value back to the town's roll, but the year
    built is a fact with or without it — and Florida's placeholder-polygon filter,
    which drops rows with no identifier, would here throw away 158,477 real
    records."""
    got = _lookup([dict(_HOUSE, Parcel_ID=None)])
    assert got is not None and got.year_built == 1941
    assert got.parcel_id is None


# ── the county codes that changed ──────────────────────────────────────────────


def test_the_planning_regions_route_here_because_that_is_what_the_geocoder_returns():
    """The Census Bureau retired Connecticut's eight legacy counties as
    county-equivalents and adopted the state's nine Planning Regions. The live
    geocoder returns the new codes — West Hartford resolves to 09110, not 09003 —
    so an adapter registered only on the legacy eight would never be reached, for
    the whole state, exactly the way a missing registry entry fails."""
    for fips in ("09110", "09120", "09130", "09140", "09150",
                 "09160", "09170", "09180", "09190"):
        assert A.adapter_for_county(fips) is ct, fips


def test_the_legacy_counties_route_here_too_because_this_repo_still_uses_them():
    """Not a hedge. This repository's own bundled county tables are split between
    the two code sets, so both are live in this codebase today — and either one
    names exactly Connecticut, so covering both cannot reach a parcel this adapter
    should not answer for."""
    path = _ROOT / "src" / "housing_label" / "data" / "county_lot_density.csv"
    with open(path, newline="") as fh:
        legacy = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("09") and len(r["geoid"]) == 5}
    assert len(legacy) == 8, f"expected 8 legacy CT counties, got {len(legacy)}"
    assert legacy <= ct.COUNTY_FIPS
    for fips in legacy:
        assert A.adapter_for_county(fips) is ct, fips


def test_connecticut_claims_nothing_outside_connecticut():
    """Every code is a 09 code, and the two sets together are all of them."""
    assert all(f.startswith("09") and len(f) == 5 for f in ct.COUNTY_FIPS)
    assert len(ct.COUNTY_FIPS) == 17, "nine planning regions plus eight counties"
    for other in ("17031", "11001", "12086"):
        assert A.adapter_for_county(other) is not ct, other


def test_no_two_adapters_claim_the_same_county():
    """A duplicate would be resolved by dict-build order — silently, and
    differently depending on the order of one tuple."""
    seen = {}
    for mod in set(A.ADAPTERS.values()):
        for fips in mod.COUNTY_FIPS:
            assert fips not in seen, f"{fips} claimed by {seen.get(fips)} and {mod}"
            seen[fips] = mod.__name__


# ── the clock ──────────────────────────────────────────────────────────────────


def test_connecticut_asks_for_its_own_read_slice_not_the_shared_one():
    """The shared one-second slice is how long a portal may go quiet before the
    silence is read as a stall. Measured over 86 requests to real Connecticut
    rooftops it cuts off 6 of the 39 buffered queries — and a cut-off reads as
    "this town has no record", not as a timeout, because every adapter fails open.

    Pinned on what reaches the transport, not on the constant."""
    slices = []
    got = _lookup([_HOUSE], slices=slices)
    assert got is not None
    assert slices and all(s == ct.READ_SLICE_S for s in slices), slices
    assert ct.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The two halves of a socket timeout add up, and it is the SUM that has to
    fit: the connect half keeps the whole remaining budget on purpose, so one
    request can cost the budget spent connecting plus one read slice.

    Pinned against the host constant rather than a literal, so the day the host's
    allowance changes this fails instead of quietly going over."""
    from housing_label import config
    assert ct.LOOKUP_TIMEOUT + ct.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET, (
        f"worst case {ct.LOOKUP_TIMEOUT + ct.READ_SLICE_S}s is not under the "
        f"{config.UPSTREAM_HOST_BUDGET}s this host allows one service")
    assert ct.LOOKUP_TIMEOUT > _shared.TIMEOUT, (
        "the worst observed pair of requests was 5.05s, which does not fit the "
        "shared four-second budget")


def test_both_requests_share_one_clock_started_once():
    """The budget is a ceiling on the WHOLE lookup, not an allowance each request
    gets afresh.

    Bounded on BOTH sides: an upper bound alone passes just as happily on the
    shared four-second budget, so dropping the LOOKUP_TIMEOUT argument from the
    ``deadline_from`` call would revert Connecticut to a clock that cuts off its
    own buffered queries, silently."""
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}          # nothing contains the point, so it buffers

    ct._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        ct.lookup(*_POINT, "70 FOXCROFT RD, WEST HARTFORD, CT")
    finally:
        _shared.get_json = saved
        ct._lookup_cached.cache_clear()

    assert len(seen) == 2, f"expected a containment and a buffered request, got {len(seen)}"
    assert seen[0] == seen[1], "each request was handed its own budget"
    budget = seen[0] - started
    assert abs(budget - ct.LOOKUP_TIMEOUT) < 0.5, (
        f"the lookup ran on a {budget:.1f}s budget, not Connecticut's "
        f"{ct.LOOKUP_TIMEOUT}s (the shared default is {_shared.TIMEOUT}s)")


def test_the_buffered_query_carries_an_output_spatial_reference():
    """Connecticut's service rejects a buffered query without ``outSR`` — "24204:
    The spatial reference identifier (SRID) is not valid" — while answering the
    containment query in 4326 quite happily.

    Left out, every Connecticut address whose geocode landed off its own lot would
    have read as "no record", because the raised error is swallowed by the
    fail-open path. Verified inert for Cook, the District and Florida, so it is
    sent for everyone rather than threaded through as an option."""
    params = []
    _lookup([], near=[_HOUSE], address="70 FOXCROFT RD, WEST HARTFORD, CT",
            params=params)
    assert len(params) == 2, "expected a containment and a buffered request"
    assert all(p.get("outSR") == "4326" for p in params), params
    assert params[1].get("distance"), "the second request is the buffered one"


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    """Every adapter swallows its own failures so a slow or broken state service
    cannot stop a label rendering."""
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    ct._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert ct.lookup(*_POINT, "70 FOXCROFT RD, WEST HARTFORD, CT") is None
    finally:
        _shared.get_json = saved
        ct._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


def test_two_parcels_containing_the_point_are_ambiguous_and_refused():
    """A condominium stack is many overlapping records at one coordinate, and so is
    a parcel filed twice. Naming one of them would be the confident-but-wrong
    ``observed`` answer the shared chooser exists to reject."""
    other = dict(_HOUSE, Parcel_ID="2176 2 72    0001",
                 Location="72 FOXCROFT ROAD", Location_1="72 FOXCROFT ROAD")
    assert _lookup([_HOUSE, other]) is None
