#!/usr/bin/env python3
"""The Southeast Michigan adapter — a building layer, and the refusals it needs.

Nothing here touches the network. SEMCOG's service is stubbed with row shapes
recorded from it live, for the reason every adapter test file gives: an adapter
fails open on purpose, so a renamed column or a broken match reads as "SEMCOG has
no record here" and would never announce itself. A test that called the real
service would pass just as quietly.

What is worth pinning is what is genuinely this source's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

SEMCOG's own:

1. One row is one **building footprint**, not a parcel, so a street geocode never
   lands inside one. The buffered search is the whole adapter, and it reaches
   ``BUFFER_RADIUS_M`` rather than the shared 80 m.
2. Several buildings can share **one address** — apartment complexes, a farmhouse
   and a second house down the lane, a house traced twice — and the Census matcher
   drops directionals, so "4963 N CAPAC RD" and "4963 CAPAC RD" are confusable
   too. None of them may be silently picked.
3. **Mobile homes** are placeholder footprints with placeholder years, and mixed-use
   and commercial buildings are not homes: candidates, never answers.
4. An attached-condo or apartment building's floor area is the **whole
   building's**, single-family stories come in **quarter steps**, and a floor area
   divisible by 100 is, in SEMCOG's own words, **an estimate**.
5. **Demolished** buildings stay in the inventory and must be filtered out of every
   request.

This file alone: ``pytest tests/test_assessor_mi.py``
"""

from __future__ import annotations

import csv
import pathlib
import re
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, mi

# Recorded live from SEMCOG Buildings_2024. A 1921 two-story single-family house
# in Monroe County: one unit, so its floor area is that home's.
_HOUSE = {"building_id": 5031027, "apn": "02 006 008 11", "address": "3678 SCHOOL RD",
          "build_type": 81, "year_built": 1921, "res_sqft": 2752, "stories": 2,
          "housing_units": 1}

# Recorded live. A DIFFERENT house — its own parcel, built 2004 — carrying the very
# same address 420 m away. The first verification run reported the 1921 house's
# year for a reader who lives in this one, before the twin check existed.
_SAME_ADDRESS_ELSEWHERE = {"building_id": 5031432, "apn": "02 006 008 20",
                           "address": "3678 SCHOOL RD", "build_type": 81,
                           "year_built": 2004, "res_sqft": 3138, "stories": 1,
                           "housing_units": 1}

# Recorded live, St. Clair County: two houses on two parcels 90 m apart, one filed
# with the directional and one without. Typed "4963 N CAPAC RD" came back from the
# Census matcher as "4963 CAPAC RD".
_WITH_DIRECTIONAL = {"building_id": 6112358, "apn": "27-016-2001-000",
                     "address": "4963 N CAPAC RD", "build_type": 81,
                     "year_built": 1989, "res_sqft": 1676, "stories": 1.25,
                     "housing_units": 1}
_WITHOUT_DIRECTIONAL = {"building_id": 6112636, "apn": "27-016-2002-000",
                        "address": "4963 CAPAC RD", "build_type": 81,
                        "year_built": 0, "res_sqft": 1448, "stories": 1,
                        "housing_units": 1}

# Recorded live. An attached-condo building: four units, the building's summed
# area, and the placeholder SEMCOG writes where the units are the parcels.
_CONDO_BUILDING = {"building_id": 2575169, "apn": "CONDO BUILDING",
                   "address": "2347 LONDON BRIDGE DR", "build_type": 82,
                   "year_built": 1987, "res_sqft": 5180, "stories": 2,
                   "housing_units": 4}

# Recorded live. A 24-unit, three-story apartment building.
_APARTMENTS = {"building_id": 1277874, "apn": "56 019 99 0005 716",
               "address": "7350 DREW CIR", "build_type": 83, "year_built": 1984,
               "res_sqft": 27200, "stories": 3, "housing_units": 24}

# Recorded live. A two-unit building filed as single-family — SEMCOG's own rule
# for a duplex whose two units have one owner.
_DUPLEX = {"building_id": 1075825, "apn": "56 074 05 1072 000",
           "address": "34164 DECATUR CT", "build_type": 81, "year_built": 1942,
           "res_sqft": 2108, "stories": 2, "housing_units": 2}

# Recorded live. A mobile home: an algorithmic footprint whose year is the
# inventory's own date, and a lot number appended to the park's address.
_MOBILE_HOME = {"building_id": 4806231, "apn": "T -20-01-100-023",
                "address": "10885 EDWARDS LN LOT 324", "build_type": 84,
                "year_built": 2020, "res_sqft": 1672, "stories": 1,
                "housing_units": 1}

# Recorded live. A retail building with two apartments upstairs.
_SHOP_WITH_FLATS = {"building_id": 1587637, "apn": "34 013 01 0002 000",
                    "address": "4460 W JEFFERSON AVE", "build_type": 21,
                    "year_built": 1926, "res_sqft": 1633, "stories": 1,
                    "housing_units": 2}

# Recorded live: the one live residential building recorded with no dwelling.
_NO_DWELLING = {"building_id": 6918326, "apn": "02-475-0234-100",
                "address": "121 WASHINGTON ST", "build_type": 81,
                "year_built": 1965, "res_sqft": 2174, "stories": 2,
                "housing_units": 0}

# A corner building filed under both its streets. The address pair is exactly as
# recorded live; the year and unit count are not (its own are 0 and 2, which would
# stop it answering for reasons that have nothing to do with the two addresses).
_CORNER = {"building_id": 6079415, "apn": "06-743-0529-000",
           "address": "1004 8TH ST | 742 PINE ST", "build_type": 81,
           "year_built": 1915, "res_sqft": 2283, "stories": 2, "housing_units": 1}

#: A point in Monroe County. Every test uses the same one: which building a
#: coordinate finds is decided here by the stubbed rows, not by the coordinate.
_POINT = (41.8146, -83.6369)

_NUMBER_RE = re.compile(r"address LIKE '(?:% \| )?(\d+) %'")


def _served(rows, where):
    """What the service would return for ``where``: the house-number filter applied
    the way the server applies it, so a test exercises the clause rather than
    stepping over it."""
    numbers = set(_NUMBER_RE.findall(where or ""))
    if not numbers:
        return list(rows)
    return [r for r in rows
            if any(part.strip().split(" ")[0] in numbers
                   for part in str(r.get("address") or "").split("|"))]


def _lookup(exact=(), near=(), far=(), address=None, params=None, slices=None):
    """Drive ``mi.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what the buffered search
    finds within ``BUFFER_RADIUS_M``; ``far`` is what only the wider twin search
    finds, out to ``TWIN_RADIUS_M`` (which also sees ``near``). All three are
    answered through the real transport helper, so the field list, the filters and
    the parcel selection are exercised rather than stepped over.
    """
    params = [] if params is None else params
    slices = [] if slices is None else slices

    def fake(url, request, deadline, read_slice=None):
        params.append(request)
        slices.append(read_slice)
        distance = float(request.get("distance") or 0)
        if not distance:
            rows = exact
        elif distance == mi.TWIN_RADIUS_M:
            rows = list(exact) + list(near) + list(far)
        else:
            rows = near
        return {"features": [{"attributes": a}
                             for a in _served(rows, request.get("where"))]}

    mi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return mi.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        mi._lookup_cached.cache_clear()


_ADDR = "3678 SCHOOL RD, TEMPERANCE, MI, 48182"


# ── a building layer: the buffer is the whole adapter ──────────────────────────


def test_a_house_beside_the_street_geocode_is_found_by_its_address():
    """The ordinary case, and the only one that happens in practice: the Census
    point is on the street centerline, no footprint contains it, and the house is
    found within the buffer by its address."""
    got = _lookup(near=[_HOUSE], address=_ADDR)
    assert got is not None
    assert got.year_built == 1921
    assert got.sqft == 2752.0
    assert got.stories == 2
    assert got.parcel_id == "02 006 008 11"
    assert got.construction is None and got.foundation is None and got.condition is None


def test_the_buffer_reaches_this_modules_radius_not_the_shared_80_m():
    """Footprints sit back from the street. Measured from the geocoded point to the
    confirmed building over 314 random homes, 90% are within 95 m but 95% only
    within 162 m and 98% within 243 m — so the shared parcel radius would refuse
    about one home in nine that this layer can answer.

    Pinned on what reaches the transport: ``select_parcel`` still asks for
    ``SEARCH_RADIUS_M``, and ``fetch`` must translate."""
    params = []
    _lookup(near=[_HOUSE], address=_ADDR, params=params)
    buffered = [p for p in params if p.get("distance")]
    assert buffered, "the buffered search was never made"
    assert float(buffered[0]["distance"]) == mi.BUFFER_RADIUS_M
    assert buffered[0]["units"] == "esriSRUnit_Meter"
    assert mi.BUFFER_RADIUS_M > _shared.SEARCH_RADIUS_M
    assert mi.TWIN_RADIUS_M > mi.BUFFER_RADIUS_M, (
        "the twin search must see at least everything the buffer can confirm")


def test_the_widened_radius_still_requires_the_exact_address():
    """Widening is safe only because the radius never decides; the address does. A
    house at a different number, or on a different street type, inside the wider
    circle is not an answer."""
    assert _lookup(near=[dict(_HOUSE, address="3680 SCHOOL RD")], address=_ADDR) is None
    assert _lookup(near=[dict(_HOUSE, address="3678 SCHOOL ST")], address=_ADDR) is None
    assert _lookup(near=[dict(_HOUSE, address="3678 SCHOOL HOUSE RD")],
                   address=_ADDR) is None


def test_the_buffered_search_asks_only_for_the_house_number_being_confirmed():
    """A 250 m circle in Detroit holds several hundred footprints. Filtering on the
    house number server-side keeps the response a few rows — far under the 2,000-row
    cap that would otherwise raise TruncatedResponse — and changes no decision,
    because a row with another number could never have matched."""
    params = []
    _lookup(near=[_HOUSE], address=_ADDR, params=params)
    buffered = [p for p in params if p.get("distance")]
    assert all("address LIKE '3678 %'" in p["where"] for p in buffered)
    assert all("address LIKE '% | 3678 %'" in p["where"] for p in buffered), (
        "a building's second address follows SEMCOG's ' | ' separator")
    containment = [p for p in params if not p.get("distance")]
    assert containment and all("LIKE" not in p["where"] for p in containment), (
        "containment must stay unfiltered, so overlapping footprints stay ambiguous")


def test_an_address_with_no_house_number_to_confirm_makes_no_buffered_request():
    """Nothing could confirm, so the request would only spend budget."""
    params = []
    assert _lookup(near=[_HOUSE], address="SCHOOL RD, TEMPERANCE, MI", params=params) is None
    assert all(not p.get("distance") for p in params)


def test_a_rooftop_coordinate_inside_the_footprint_answers_without_an_address():
    """A point placed on the roof — a map click — lands inside the footprint, and
    containment is the one unambiguous answer there is."""
    got = _lookup(exact=[_HOUSE])
    assert got is not None and got.year_built == 1921


def test_two_footprints_containing_the_point_are_ambiguous_and_refused():
    other = dict(_HOUSE, building_id=5031028, address="3676 SCHOOL RD")
    assert _lookup(exact=[_HOUSE, other]) is None


# ── several buildings at one address ───────────────────────────────────────────


def test_two_buildings_at_the_address_inside_the_buffer_are_refused():
    """An apartment complex filed under one address — 35477 Garner, Romulus is 20
    buildings of it — or a house and a second dwelling. Naming one would be a
    guess carrying the ``observed`` tag."""
    second = dict(_HOUSE, building_id=5031099, year_built=1988)
    assert _lookup(near=[_HOUSE, second], address=_ADDR) is None


def test_a_second_house_with_the_same_address_beyond_the_buffer_refuses_the_answer():
    """Recorded live: the 1921 house is 85 m from the geocode and the 2004 house the
    reader lives in is 420 m away, both "3678 SCHOOL RD" on their own parcels. The
    buffer sees exactly one and would confirm it; only the wider twin search knows
    there are two."""
    assert _lookup(near=[_HOUSE], far=[_SAME_ADDRESS_ELSEWHERE], address=_ADDR) is None


def test_the_twin_search_is_not_refused_by_the_chosen_building_itself():
    """It sees the chosen building too; finding it again is not a twin. Guards the
    refusal above from being the only thing the twin check ever does."""
    params = []
    got = _lookup(near=[_HOUSE], address=_ADDR, params=params)
    assert got is not None
    twin = [p for p in params if float(p.get("distance") or 0) == mi.TWIN_RADIUS_M]
    assert len(twin) == 1, "the chosen building must be twin-checked"


def test_a_directional_the_geocoder_dropped_refuses_the_answer():
    """Typed "4963 N CAPAC RD" came back from the Census matcher as "4963 CAPAC RD",
    which SEMCOG also has: a different house, its own parcel, 90 m away. The
    confirmation is strict and correctly matches the directionless one; it is the
    reader's neighbor. The twin check sets directionals aside for exactly this."""
    assert _lookup(near=[_WITHOUT_DIRECTIONAL], far=[_WITH_DIRECTIONAL],
                   address="4963 CAPAC RD, CAPAC, MI, 48014") is None
    assert _lookup(near=[_WITH_DIRECTIONAL], far=[_WITHOUT_DIRECTIONAL],
                   address="4963 N CAPAC RD, CAPAC, MI, 48014") is None
    # Guards the two refusals above from passing for another reason: alone, each
    # house is confirmed and answers.
    alone = _lookup(near=[_WITHOUT_DIRECTIONAL], address="4963 CAPAC RD, CAPAC, MI, 48014")
    assert alone is not None and alone.sqft == 1448.0
    alone = _lookup(near=[_WITH_DIRECTIONAL], address="4963 N CAPAC RD, CAPAC, MI, 48014")
    assert alone is not None and alone.year_built == 1989


def test_what_counts_as_confusable_is_only_a_directional():
    """Looser than ``same_address`` in one respect and no other: a different house
    number, street name or street type is still a different building, and a name
    made only of directionals keeps them."""
    assert mi._confusable("100 N MAIN ST", "100 MAIN ST")
    assert mi._confusable("100 N MAIN ST", "100 S MAIN ST")
    assert mi._confusable("100 MAIN ST", "100 MAIN")
    assert not mi._confusable("100 MAIN ST", "102 MAIN ST")
    assert not mi._confusable("100 MAIN ST", "100 MAIN AVE")
    assert not mi._confusable("100 MAIN ST", "100 MAINE ST")
    assert not mi._confusable("100 N ST", "100 S ST")


# ── candidates that are never answers ──────────────────────────────────────────


def test_a_mobile_home_is_never_the_answer():
    """68,000 algorithmic footprints whose years spike at 2020 and 2024 — the
    inventory's own dates."""
    assert _lookup(exact=[_MOBILE_HOME]) is None
    assert _lookup(near=[_MOBILE_HOME], address="10885 EDWARDS LN, MI 48176") is None


def test_a_mobile_home_lot_is_read_as_a_unit_of_the_parks_address():
    """SEMCOG appends the lot to the park's address. Read as a street name it would
    match nothing; read as a unit, it is the park's address. Only a trailing LOT
    with a number — "LITTLE SCHOOL LOT LAKE RD" is a street."""
    assert mi._addresses(_MOBILE_HOME) == ["10885 EDWARDS LN"]
    assert mi._addresses({"address": "809 LITTLE SCHOOL LOT LAKE RD"}) == [
        "809 LITTLE SCHOOL LOT LAKE RD"]


def test_a_house_at_a_mobile_home_parks_address_is_ambiguous_not_confirmed():
    """Why the lot is stripped: a manager's house filed single-family at the park's
    own address would otherwise be the unique match for every reader in the park —
    the Census matcher drops "Lot 324" — and its year would be reported as theirs."""
    office = dict(_HOUSE, building_id=4806001, address="10885 EDWARDS LN")
    assert _lookup(near=[office, _MOBILE_HOME], address="10885 EDWARDS LN, MI 48176") is None
    assert _lookup(near=[office], far=[_MOBILE_HOME],
                   address="10885 EDWARDS LN, MI 48176") is None
    assert _lookup(near=[office], address="10885 EDWARDS LN, MI 48176") is not None, (
        "the fixture would answer on its own")


def test_a_shop_with_flats_upstairs_is_a_candidate_but_not_an_answer():
    """Its floor area and year are a retail building's. It is fetched, because
    someone lives there and it can make a match ambiguous."""
    assert _lookup(near=[_SHOP_WITH_FLATS],
                   address="4460 W JEFFERSON AVE, DETROIT, MI, 48209") is None
    params = []
    _lookup(near=[_HOUSE], address=_ADDR, params=params)
    assert all("housing_units > 0" in p["where"] for p in params)
    assert all("84" in p["where"] for p in params)


def test_every_request_excludes_demolished_buildings():
    """SEMCOG keeps 59,725 demolished buildings in the inventory with their date. A
    request without the filter offers a house that was torn down as a candidate —
    the sole match, or the reason the house that replaced it is ambiguous."""
    params = []
    _lookup(near=[_HOUSE], address=_ADDR, params=params)
    assert len(params) == 3, "containment, buffer and twin search"
    assert all("demolished IS NULL" in p["where"] for p in params)


# ── what one row can say about one home ────────────────────────────────────────


def test_an_attached_condo_building_reports_its_year_and_stories_but_not_its_area():
    """5,180 sq ft is four homes. The building went up in 1987 for all of them, and
    two stories is the building's own count — what the label's ``stories`` means
    for a multi-unit home."""
    got = _lookup(near=[_CONDO_BUILDING], address="2347 LONDON BRIDGE DR, MI 48326")
    assert got is not None
    assert got.year_built == 1987 and got.stories == 2
    assert got.sqft is None


def test_an_apartment_building_reports_its_year_and_stories_but_not_its_area():
    got = _lookup(near=[_APARTMENTS], address="7350 DREW CIR, MI 48185")
    assert got is not None
    assert got.year_built == 1984 and got.stories == 3
    assert got.sqft is None


def test_a_duplex_filed_as_single_family_does_not_report_its_area():
    """SEMCOG files a duplex with one owner as single-family — 29,178 buildings
    record two units. The build type alone would pass it."""
    got = _lookup(near=[_DUPLEX], address="34164 DECATUR CT, MI 48185")
    assert got is not None and got.year_built == 1942
    assert got.sqft is None


def test_a_condo_buildings_placeholder_parcel_number_is_not_offered_as_one():
    """Every attached-condo building's ``apn`` is the literal "CONDO BUILDING"."""
    got = _lookup(near=[_CONDO_BUILDING], address="2347 LONDON BRIDGE DR, MI 48326")
    assert got.parcel_id == "SEMCOG building 2575169"


def test_quarter_stories_are_not_rounded_into_a_whole_story():
    """Single-family stories come as 1.25, 1.5, 1.75 — 290,000 of them."""
    for value in (1.25, 1.5, 1.75, 2.5):
        got = _lookup(near=[dict(_HOUSE, stories=value)], address=_ADDR)
        assert got is not None and got.stories is None, value
    for value in (0, None):
        got = _lookup(near=[dict(_HOUSE, stories=value)], address=_ADDR)
        assert got is not None and got.stories is None, value


def test_a_floor_area_divisible_by_100_is_semcogs_estimate_and_is_not_reported():
    """"Square footage evenly divisible by 100 is an estimate, based on size and/or
    type of building, where the true value is unknown." 1,200 on 27727 Clarita St,
    recorded live."""
    got = _lookup(near=[dict(_HOUSE, res_sqft=1200)], address=_ADDR)
    assert got is not None and got.year_built == 1921
    assert got.sqft is None


def test_a_year_of_zero_is_not_the_year_zero():
    """SEMCOG's "unknown", on 33,728 live residential buildings."""
    got = _lookup(near=[dict(_HOUSE, year_built=0)], address=_ADDR)
    assert got is not None and got.year_built is None
    assert got.sqft == 2752.0, "the area survives; only the year is missing"


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR, _valid_year

    floor = EARLIEST_PLAUSIBLE_YEAR
    at_floor = _lookup(near=[dict(_HOUSE, year_built=floor)], address=_ADDR)
    assert at_floor is not None and at_floor.year_built == floor
    assert _valid_year(floor)
    below = _lookup(near=[dict(_HOUSE, year_built=floor - 1)], address=_ADDR)
    assert below is not None and below.year_built is None
    assert not _valid_year(floor - 1)


def test_a_building_recorded_with_no_dwelling_reports_nothing():
    """An explicit 0 is SEMCOG saying nobody lives there; its year and its stories
    describe a building, not the reader's home."""
    assert _lookup(exact=[_NO_DWELLING]) is None
    assert _lookup(near=[_NO_DWELLING], address="121 WASHINGTON ST, MI 48060") is None


def test_a_missing_unit_count_does_not_cost_the_year():
    silent = {k: v for k, v in _HOUSE.items() if k != "housing_units"}
    got = _lookup(near=[silent], address=_ADDR)
    assert got is not None and got.year_built == 1921
    assert got.sqft is None, "the area still needs the count it is built on"


def test_a_building_that_records_nothing_reportable_is_not_an_answer():
    """Year unknown, area an estimate, stories fractional: matched, and no fact."""
    empty = dict(_HOUSE, year_built=0, res_sqft=2700, stories=1.5)
    assert _lookup(near=[empty], address=_ADDR) is None


# ── SEMCOG's addresses ─────────────────────────────────────────────────────────


def test_a_corner_building_confirms_on_either_of_its_addresses():
    """Filed "1004 8TH ST | 742 PINE ST"; joined, neither address parses as one."""
    for typed in ("742 PINE ST, PORT HURON, MI, 48060",
                  "1004 8TH ST, PORT HURON, MI, 48060"):
        got = _lookup(near=[_CORNER], address=typed)
        assert got is not None and got.year_built == 1915, typed
    assert mi._address_of(_CORNER, "742 PINE ST") == "742 PINE ST"
    assert mi._address_of(_CORNER, None) == "1004 8TH ST"


def test_a_range_address_does_not_confirm_a_house_number_inside_it():
    """"3379-3401 BURBANK DR" on 59,831 residential rows. ``address_key`` cannot
    anchor on a range, and a reader's 3385 names one unit inside it — a refusal,
    which costs coverage and no accuracy."""
    ranged = dict(_CONDO_BUILDING, address="3379-3401 BURBANK DR")
    assert _shared.address_key("3379-3401 BURBANK DR") is None
    assert _lookup(near=[ranged], address="3385 BURBANK DR, MI 48326") is None


# ── the columns that must not be read ──────────────────────────────────────────


def test_the_field_list_is_the_privacy_boundary():
    """``ref_name`` is "Owner or business name of the building, if known", and the
    editor columns carry user names. None is an input to any dimension."""
    fields = mi._FIELDS.split(",")
    for private in ("ref_name", "created_user", "last_edited_user", "*"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    """Pinned on what the transport is handed, not on the constant. The twin search
    asks for even less: the id and the address."""
    params = []
    _lookup(near=[_HOUSE], address=_ADDR, params=params)
    assert len(params) == 3
    for p in params:
        assert "ref_name" not in p["outFields"] and "*" not in p["outFields"]
        assert p["returnGeometry"] == "false"
    assert params[0]["outFields"] == mi._FIELDS and params[1]["outFields"] == mi._FIELDS
    assert params[2]["outFields"] == "building_id,address"


def test_the_copyright_notice_the_license_requires_travels_with_every_value():
    """SEMCOG's Copyright License Agreement grants the use on one condition: every
    use "shall prominently state … 'Copyright © [year] SEMCOG. All Rights
    Reserved. Reproduction or Use Without Permission is Prohibited.'" The record's
    ``source`` is what the label prints beside the value."""
    assert re.search(r"Copyright © 20\d\d SEMCOG\. All Rights Reserved\. "
                     r"Reproduction or Use Without Permission is Prohibited\.",
                     mi.ATTRIBUTION)
    got = _lookup(near=[_HOUSE], address=_ADDR)
    assert got.source == mi.ATTRIBUTION
    assert "2024" in got.data_vintage


# ── which counties ─────────────────────────────────────────────────────────────


def test_the_seven_semcog_counties_are_real_michigan_counties_in_the_county_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        table = {r["geoid"] for r in csv.DictReader(fh)}
    assert len(mi.COUNTY_FIPS) == 7
    assert mi.COUNTY_FIPS <= table
    assert all(f.startswith("26") and len(f) == 5 for f in mi.COUNTY_FIPS)
    assert mi.COUNTY_FIPS == {"26163", "26125", "26099", "26161", "26093", "26147",
                              "26115"}


def test_no_registered_adapter_already_claims_a_semcog_county():
    for fips in mi.COUNTY_FIPS:
        assert A.adapter_for_county(fips) in (None, mi), fips


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_request_carries_this_modules_read_slice():
    slices = []
    assert _lookup(near=[_HOUSE], address=_ADDR, slices=slices) is not None
    assert len(slices) == 3 and all(s == mi.READ_SLICE_S for s in slices), slices


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert mi.LOOKUP_TIMEOUT + mi.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_all_three_requests_share_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        rows = [] if not request.get("distance") else [_HOUSE]
        return {"features": [{"attributes": a} for a in rows]}

    mi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        assert mi.lookup(*_POINT, _ADDR) is not None
    finally:
        _shared.get_json = saved
        mi._lookup_cached.cache_clear()
    assert len(seen) == 3, f"expected containment, buffer and twin, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs(seen[0] - started - mi.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    mi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert mi.lookup(*_POINT, _ADDR) is None
    finally:
        _shared.get_json = saved
        mi._lookup_cached.cache_clear()


def test_a_truncated_response_is_refused_not_read_as_the_whole_answer():
    def truncated(url, request, deadline, read_slice=None):
        if request.get("distance"):
            raise _shared.TruncatedResponse("gis.semcog.org: truncated")
        return {"features": []}

    mi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = truncated
    try:
        assert mi.lookup(*_POINT, _ADDR) is None
    finally:
        _shared.get_json = saved
        mi._lookup_cached.cache_clear()


def test_a_failing_twin_search_fails_the_lookup_rather_than_skipping_the_check():
    """The twin check is a refusal; an outage in it must not be read as "no twin"."""
    def twin_down(url, request, deadline, read_slice=None):
        if float(request.get("distance") or 0) == mi.TWIN_RADIUS_M:
            raise TimeoutError("assessor lookup budget exhausted")
        rows = [] if not request.get("distance") else [_HOUSE]
        return {"features": [{"attributes": a} for a in rows]}

    mi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = twin_down
    try:
        assert mi.lookup(*_POINT, _ADDR) is None
    finally:
        _shared.get_json = saved
        mi._lookup_cached.cache_clear()


def test_nothing_near_the_point_is_simply_no_answer():
    assert _lookup(address=_ADDR) is None
    assert _lookup() is None
