#!/usr/bin/env python3
"""The Florida adapter — one statewide table, and the three refusals it needs.

Nothing here touches the network. The state's portal is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Florida has no record here" and would never announce itself. A test that called
the real service would pass just as quietly.

What is worth pinning is what is genuinely Florida's. The dangerous shared parts —
choosing which parcel an address means, comparing two addresses, bounding the
request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Florida's own three:

1. The state ships **placeholder polygons** with no parcel identifier and every
   value zero. One of them was the sole parcel returned at a real Fort Lauderdale
   coordinate, so this is not a theoretical row.
2. A parcel can be a **269-unit tower**, and its total floor area is not the size
   of anybody's home.
3. The county roll carries **two year-built columns**, and the more prominent one
   is the wrong one.

Run standalone: ``python tests/test_assessor_fl.py``
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.enrich import assessor as A  # noqa: E402
from housing_label.enrich.assessor import _shared, fl  # noqa: E402

# Recorded live from FDOR Cadastral 2025. A single-family house in Orlando: one
# home, one building, so its floor area is that home's.
_HOUSE = {"PARCEL_ID": "352229534800041", "PHY_ADDR1": "740 W SOUTH ST",
          "ASMNT_YR": 2025.0, "ACT_YR_BLT": 1986.0, "TOT_LVG_AR": 840.0,
          "NO_RES_UNT": 1.0, "NO_BULDNG": 1.0}

# Recorded live. The whole 269-unit tower at 9701 Collins Ave, Bal Harbour, as one
# parcel — which is how Florida files a condominium.
_TOWER = {"PARCEL_ID": "1222260010020", "PHY_ADDR1": "9701 COLLINS AVE",
          "ASMNT_YR": 2025.0, "ACT_YR_BLT": 2011.0, "TOT_LVG_AR": 895557.0,
          "NO_RES_UNT": 269.0, "NO_BULDNG": 2.0}

# Recorded live. The state's placeholder polygon: every field blank or zero,
# including the parcel identifier.
_BLANK = {"PARCEL_ID": " ", "PHY_ADDR1": " ", "ASMNT_YR": 0.0,
          "ACT_YR_BLT": 0.0, "TOT_LVG_AR": 0.0, "NO_RES_UNT": 0.0,
          "NO_BULDNG": 0.0}


def _lookup(exact, near=(), address=None, lat=28.5400, lon=-81.4000, slices=None):
    """Drive ``fl.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find. Both are answered through the real transport helper, so the field
    list, the placeholder filter and the parcel choice are all exercised rather
    than stepped over.

    ``slices``, when passed, collects the read slice each request was given, so a
    test can check what reaches the transport rather than only what the constant
    says.
    """
    slices = [] if slices is None else slices
    def fake(url, params, deadline, read_slice=None):
        slices.append(read_slice)
        rows = list(near) if params.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    fl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return fl.lookup(lat, lon, address)
    finally:
        _shared.get_json = saved
        fl._lookup_cached.cache_clear()


# ── the state's placeholder polygons ────────────────────────────────────────────


def test_a_placeholder_polygon_is_not_a_record():
    """Recorded live: a Fort Lauderdale coordinate returned exactly one parcel, and
    every field on it was blank or zero.

    Containment with a single candidate is normally the strongest answer there is,
    so nothing downstream would have questioned this one. It has to be refused
    here."""
    assert _lookup([_BLANK]) is None


def test_a_placeholder_does_not_make_a_real_parcel_ambiguous():
    """Two containing parcels are ambiguous and the shared selector refuses them —
    correctly, since it cannot tell which is meant.

    But a polygon with no identifier can never be an answer, so counting it as a
    rival loses a real record to a row that was never a candidate. The filter runs
    before the choice, not after."""
    got = _lookup([_BLANK, _HOUSE])
    assert got is not None
    assert got.parcel_id == "352229534800041"
    assert got.year_built == 1986


def test_a_parcel_with_no_identifier_is_dropped_from_a_buffered_search_too():
    """The buffer path is where an off-parcel geocode is rescued, and it is exactly
    where a stray placeholder would sit — in the roadway."""
    got = _lookup([], near=[_BLANK, _HOUSE], address="740 W SOUTH ST, ORLANDO, FL")
    assert got is not None and got.parcel_id == "352229534800041"


# ── the floor area that describes a tower, not a home ───────────────────────────


def test_a_condominium_tower_reports_its_year_but_not_its_floor_area():
    """Florida files the building as the parcel, so a condo address resolves through
    the ordinary path — no second lookup chain, unlike Washington.

    The year is right for every unit in the tower. The 895,557 sq ft is right for
    none of them, and tagging it ``observed`` would tell a reader not to doubt it."""
    got = _lookup([_TOWER])
    assert got is not None
    assert got.year_built == 2011
    assert got.sqft is None


def test_a_house_reports_its_floor_area():
    """The other side of the same rule — one home in one building, so the total
    living area IS this home's area. Without this the rule would be safe and
    useless."""
    got = _lookup([_HOUSE])
    assert got is not None and got.sqft == 840.0


def test_both_counts_have_to_say_one():
    """Two homes in one building, or one home plus a second building, each make the
    total larger than the home being scored."""
    two_homes = dict(_HOUSE, NO_RES_UNT=2.0)
    two_buildings = dict(_HOUSE, NO_BULDNG=2.0)
    for row in (two_homes, two_buildings):
        got = _lookup([row])
        assert got is not None and got.sqft is None, row
        assert got.year_built == 1986, "the year survives; only the area is refused"


def test_an_unrecorded_count_is_not_a_count_of_one():
    """Florida writes 0 where a count is not recorded. Treating "not recorded" as
    "one home" would report a shopping centre's floor area as a house's."""
    got = _lookup([dict(_HOUSE, NO_RES_UNT=0.0, NO_BULDNG=0.0, TOT_LVG_AR=62104.0)])
    assert got is not None and got.sqft is None


# ── the two year-built columns ──────────────────────────────────────────────────


def test_the_effective_year_is_never_read():
    """Counties move the effective year forward when a property is improved, so it
    describes condition rather than when the building went up. Recorded live: a
    1925 Orlando house carries an effective year of 2015.

    Reading it would make the oldest housing in the state look new — and would do
    it while carrying the ``observed`` tag."""
    got = _lookup([dict(_HOUSE, ACT_YR_BLT=1925.0, EFF_YR_BLT=2015.0)])
    assert got is not None and got.year_built == 1925


def test_the_effective_year_is_not_even_requested():
    """Cheaper than trusting the mapping: if the column never arrives it cannot be
    read by a later edit. The field list is also the privacy boundary — this layer
    carries owner names, fiduciary names and sale prices in its other columns."""
    assert "EFF_YR_BLT" not in fl._FIELDS
    for private in ("OWN_NAME", "OWN_ADDR1", "FIDU_NAME", "SALE_PRC1", "JV",
                    "S_LEGAL", "*"):
        assert private not in fl._FIELDS.split(","), private


def test_a_year_of_zero_is_not_the_year_zero():
    """Florida's "not recorded". Passed through it would age the building by two
    thousand years and be scored as a fact."""
    got = _lookup([dict(_HOUSE, ACT_YR_BLT=0.0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 840.0, "the area survives; only the year is missing"


def test_a_parcel_that_records_nothing_at_all_is_not_an_answer():
    """A real parcel with no year and no area contributed no fact. Passing it on
    would count as "the assessor answered" in both the reader's tag and the
    coverage metric, so a parcel that told us nothing would be tallied beside ones
    that did.

    Checked through ``assessor_for_point``, which is the door the label actually
    uses. Testing ``fl.lookup`` alone would assert something about the adapter's
    private shape rather than about what reaches a reader — the mistake that once
    let the whole DC condominium path ship unreachable from the product."""
    empty = dict(_HOUSE, ACT_YR_BLT=0.0, TOT_LVG_AR=0.0)
    assert not _lookup([empty]).fields(), "the adapter found a parcel but no facts"

    def fake(url, params, deadline):
        return {"features": [{"attributes": empty}]}

    fl._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    try:
        assert A.assessor_for_point(28.54, -81.40, "12095") is None
    finally:
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        fl._lookup_cached.cache_clear()


# ── the vintage a reader can date ───────────────────────────────────────────────


def test_the_assessment_year_travels_with_the_value():
    """The Department republishes the joined layer each August under an unchanged
    URL, so a hard-coded year would go stale silently — presenting old data at the
    same confidence as fresh data."""
    got = _lookup([_HOUSE])
    assert got is not None and "2025 assessment roll" in got.data_vintage


def test_a_missing_assessment_year_falls_back_rather_than_inventing_one():
    got = _lookup([dict(_HOUSE, ASMNT_YR=0.0)])
    assert got is not None
    assert got.data_vintage == fl.DATA_VINTAGE
    assert "assessment roll" not in got.data_vintage


# ── the county list ─────────────────────────────────────────────────────────────


def test_every_florida_county_is_covered_and_no_other_county_is():
    """The set is computed from a rule rather than typed out, which is safer but
    only if the rule is checked. Checked against the Census-derived county table
    this repository already ships, so the two cannot drift apart."""
    import csv
    path = _ROOT / "src" / "housing_label" / "data" / "county_lot_density.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("12") and len(r["geoid"]) == 5}
    assert len(census) == 67, f"expected 67 Florida counties, got {len(census)}"
    assert fl.COUNTY_FIPS == census


def test_the_two_codes_a_hand_typed_list_gets_wrong():
    """Dade County was renamed Miami-Dade in 1997: 12025 was retired and 12086 took
    its place. 12086 is the only even county code in Florida, so a rule written as
    "the odd numbers" silently drops the state's largest county — 1.0 million
    homes."""
    assert "12086" in fl.COUNTY_FIPS, "Miami-Dade"
    assert "12025" not in fl.COUNTY_FIPS, "Dade, retired in 1997"


def test_the_registry_routes_florida_to_this_adapter():
    """Registration is a separate step from writing the adapter, and forgetting it
    is invisible: every Florida address simply keeps reading as "no adapter"."""
    for fips in ("12086", "12095", "12103", "12001", "12133"):
        assert A.adapter_for_county(fips) is fl, fips
    assert A.adapter_for_county("17031") is not fl, "Cook must be unaffected"
    assert A.adapter_for_county("11001") is not fl, "DC must be unaffected"


def test_no_two_adapters_claim_the_same_county():
    """A duplicate would be resolved by dict-build order — silently, and differently
    depending on the order of one tuple."""
    seen = {}
    for mod in {m for m in A.ADAPTERS.values()}:
        for fips in mod.COUNTY_FIPS:
            assert fips not in seen, f"{fips} claimed by {seen.get(fips)} and {mod}"
            seen[fips] = mod.__name__


# ── the clock, which was silently discarding most of the state ─────────────────


def test_florida_asks_for_its_own_read_slice_not_the_shared_one():
    """The shared one-second slice is how long a portal may go quiet before the
    silence is read as a stall. Measured over 40 requests to real Florida rooftops,
    it cut off 21 of 40 containment queries and 25 of 40 buffered ones — and a
    cut-off reads as "this state has no record", not as a timeout, because every
    adapter fails open.

    Pinned on what reaches the transport, not on the constant. A constant nothing
    passes through is a comment."""
    slices = []
    got = _lookup([_HOUSE], slices=slices)
    assert got is not None
    assert slices and all(s == fl.READ_SLICE_S for s in slices), slices
    assert fl.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_other_adapters_keep_the_shared_slice():
    """Florida's upstream is slow; Cook's and the District's are not. Raising the
    shared default to fix Florida would have let a genuinely hung connection hold
    a Chicago or Washington label four times as long, for no benefit."""
    from housing_label.enrich.assessor import cook_il, dc
    for mod in (cook_il, dc):
        assert not hasattr(mod, "READ_SLICE_S"), mod.__name__
    assert _shared._READ_SLICE_S == 1.0


def test_the_budget_holds_two_requests_and_is_not_the_shared_one():
    """A lookup makes at most two requests — the containment query every lookup
    makes, and the buffered query an off-parcel geocode falls through to. A budget
    smaller than two slices would cut the second one off by arithmetic, whatever
    the service did."""
    assert fl.TIMEOUT >= 2 * fl.READ_SLICE_S
    assert fl.TIMEOUT > _shared.TIMEOUT


def test_both_requests_share_one_clock_started_once():
    """The budget is a ceiling on the WHOLE lookup, not an allowance each request
    gets afresh. Giving each request its own eight seconds would let a slow day
    hold the label for as long as the adapter cared to keep asking.

    Pinned on the deadline the two requests actually receive: one instant, computed
    once. The transport then measures each request against it and refuses one that
    starts with nothing left — so an off-parcel lookup on a slow day is bounded by
    the budget rather than by twice it."""
    seen = []

    def note(url, params, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}          # nothing contains the point, so it buffers

    fl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        fl.lookup(28.54, -81.40, "740 W SOUTH ST, ORLANDO, FL")
    finally:
        _shared.get_json = saved
        fl._lookup_cached.cache_clear()

    assert len(seen) == 2, f"expected a containment and a buffered request, got {len(seen)}"
    assert seen[0] == seen[1], "each request was handed its own budget"
    assert started < seen[0] <= started + fl.TIMEOUT + 0.5


def test_a_request_that_starts_with_no_budget_left_is_refused():
    """The other half of sharing one clock: the second request has to be stopped by
    a spent budget, not merely handed one. Checked against the real transport, since
    that is where the refusal lives."""
    try:
        _shared.get_json("https://example.invalid/query", {}, time.monotonic() - 1,
                         fl.READ_SLICE_S)
    except TimeoutError:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"a spent budget reached the network: {exc!r}")
    raise AssertionError("a spent budget was not refused")


# ── failing open ────────────────────────────────────────────────────────────────


def test_the_portal_falling_over_is_not_evidence_of_absence():
    """Every adapter swallows its own failures so a slow or broken state portal
    cannot stop a label rendering."""
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    fl._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert fl.lookup(28.54, -81.40, "740 W SOUTH ST, ORLANDO, FL") is None
    finally:
        _shared.get_json = saved
        fl._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
