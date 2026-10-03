#!/usr/bin/env python3
"""The Los Angeles County adapter — one parcel layer, five buildings a parcel, and stacks.

Nothing here touches the network. The county's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Los Angeles has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely Los Angeles's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Los Angeles's own five:

1. Up to **five buildings per parcel** in numbered columns, sharing one address,
   with nothing saying which one the reader lives in.
2. **Condominium units stacked** on the building's footprint, one record per unit,
   so containment always finds many — and the reader's unit is what picks one.
3. A service that returns **at most 1,000 records**, and a truncated answer that
   could make a match look unique.
4. A ``Units`` column that is **not a dwelling count** — a store counts as 1, some
   houses as 0 — so ``UseType`` decides what is a home.
5. **Lettered and numbered avenues** ("AVENUE L8", "AVENUE 64") whose identifier
   the shared parser would drop as a unit number.

This file alone: ``pytest tests/test_assessor_la.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, la

_EMPTY_SLOTS = {f"{col}{i}": None for i in (2, 3, 4, 5)
                for col in ("DesignType", "YearBuilt", "Units", "SQFTmain")}


def _row(**kw):
    """A roll row in the service's own shape: blank strings are single spaces and
    unused building slots are null, exactly as recorded."""
    base = {"SitusFraction": " ", "SitusDirection": " ", "SitusUnit": " ",
            "UseType": "Residential", "Roll_Year": "2026", **_EMPTY_SLOTS}
    base.update(kw)
    return base


# Recorded live. A 1904 single-family house in South LA: one building, one
# dwelling, so its floor area is that home's.
_HOUSE = _row(AIN="5103026007", SitusHouseNo="897", SitusDirection="E",
              SitusStreet="52ND PL", DesignType1="0110", YearBuilt1="1904",
              Units1=1, SQFTmain1=912)

# Recorded live. A neighbor on the same block, for the buffered search.
_NEIGHBOR = _row(AIN="5103026008", SitusHouseNo="893", SitusDirection="E",
                  SitusStreet="52ND PL", DesignType1="0110", YearBuilt1="1911",
                  Units1=1, SQFTmain1=1020)

# Recorded live. A duplex filed as two buildings that went up 16 years apart.
_TWO_ERAS = _row(AIN="5175009014", SitusHouseNo="448", SitusDirection="N",
                 SitusStreet="BREED ST", DesignType1="0110", YearBuilt1="1910",
                 Units1=1, SQFTmain1=1040, DesignType2="0100", YearBuilt2="1926",
                 Units2=1, SQFTmain2=500)

# Recorded live. A 1957 house with a 1957 second building (400 sq ft).
_SAME_YEAR = _row(AIN="2671006017", SitusHouseNo="15632", SitusStreet="LABRADOR ST",
                  DesignType1="0121", YearBuilt1="1957", Units1=1, SQFTmain1=1656,
                  DesignType2="0130", YearBuilt2="1957", Units2=1, SQFTmain2=400)

# Recorded live. A house whose second building has an area and units but no year.
_UNDATED_SECOND = _row(AIN="4127023012", SitusHouseNo="5512", SitusDirection="W",
                       SitusStreet="82ND ST", DesignType1="0130", YearBuilt1="1950",
                       Units1=1, SQFTmain1=1082, DesignType2="0110",
                       YearBuilt2="0000", Units2=1, SQFTmain2=400)

# Recorded live. A 24-unit apartment building, one building, one parcel.
_APARTMENTS = _row(AIN="2162012006", SitusHouseNo="5155", SitusStreet="YARMOUTH AVE",
                   DesignType1="0531", YearBuilt1="1959", Units1=24, SQFTmain1=21244)

# Recorded live. A warehouse: `UseType` says Industrial.
_WAREHOUSE = _row(AIN="7306017011", SitusHouseNo="19010", SitusDirection="S",
                  SitusStreet="ALAMEDA ST", UseType="Industrial", DesignType1="3300",
                  YearBuilt1="1977", Units1=0, SQFTmain1=27691)

# Recorded live. A three-bedroom single-family house in La Crescenta whose Units1
# is 0 — the roll not filling the column, not saying nobody lives there.
_UNITS_ZERO = _row(AIN="5801020059", SitusHouseNo="2771", SitusStreet="COMMUNITY AVE",
                   DesignType1="0130", YearBuilt1="1999", Units1=0, SQFTmain1=2603)


def _unit(ain, unit, sqft, year="2008"):
    """A unit of the stacked condominium at 9049 Alcott St, as recorded live."""
    return _row(AIN=ain, SitusHouseNo="9049", SitusUnit=unit, SitusStreet="ALCOTT ST",
                DesignType1="0130", YearBuilt1=year, Units1=1, SQFTmain1=sqft)


_STACK = [_unit("4305007045", "102", 1913), _unit("4305007046", "103", 1590),
          _unit("4305007047", "104", 1471), _unit("4305007048", "105", 1590)]

# Recorded live: Long Beach writes its unit with a "NO" marker the shared parser
# does not know.
_OCEAN = [_row(AIN=f"72650221{n:02d}", SitusHouseNo="850", SitusDirection="E",
               SitusUnit=u, SitusStreet="OCEAN BLVD", DesignType1="0130",
               YearBuilt1="1992", Units1=1, SQFTmain1=s)
          for n, u, s in ((28, "NO  1108", 1590), (1, "NO    B5", 2020),
                          (5, "NO    B1", 1187))]

# Recorded live. A planned development: stacked like condominium units, but each
# home has its own house number and no unit.
_PUD = [_row(AIN="8701012020", SitusHouseNo="1", SitusStreet="WILDERNESS PL",
             DesignType1="0130", YearBuilt1="1984", Units1=1, SQFTmain1=1526),
        _row(AIN="8701012019", SitusHouseNo="2", SitusStreet="WILDERNESS PL",
             DesignType1="0130", YearBuilt1="1984", Units1=1, SQFTmain1=1526)]

#: A point in Los Angeles. Every test uses the same one: which parcel a coordinate
#: lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (33.9951, -118.2596)
_ADDR = "897 E 52ND PL, LOS ANGELES, CA, 90011"


def _lookup(exact, near=(), address=None, slices=None, params=None, truncated=()):
    """Drive ``la.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find. Both are answered beneath the real transport helper, so the field
    list, the truncation check, the AIN filter, the parcel choice and the unit
    paths are all exercised.

    ``slices`` and ``params`` collect what each request was handed; ``truncated``
    names the distances (0 or the buffer) whose answer carries the service's
    ``exceededTransferLimit`` flag.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        buffered = bool(request.get("distance"))
        rows = list(near) if buffered else list(exact)
        body = {"features": [{"attributes": a} for a in rows]}
        if (_shared.SEARCH_RADIUS_M if buffered else 0) in truncated:
            body["exceededTransferLimit"] = True
        return body

    la._lookup_cached.cache_clear()
    saved = _shared._fetch_json
    _shared._fetch_json = fake
    try:
        return la.lookup(*_POINT, address)
    finally:
        _shared._fetch_json = saved
        la._lookup_cached.cache_clear()


# ── the ordinary house ─────────────────────────────────────────────────────────


def test_a_house_reports_its_year_and_floor_area():
    got = _lookup([_HOUSE], address=_ADDR)
    assert got is not None
    assert got.parcel_id == "5103026007"
    assert got.year_built == 1904
    assert got.sqft == 912.0
    assert got.stories is None and got.construction is None
    assert got.foundation is None and got.condition is None


def test_the_year_is_a_string_in_the_roll_and_an_integer_on_the_label():
    """``YearBuilt1`` is a four-character string. Passed through, "1904" would reach
    the scorer as text."""
    got = _lookup([_HOUSE])
    assert got is not None and isinstance(got.year_built, int)


def test_an_off_parcel_geocode_is_confirmed_by_its_address():
    got = _lookup([], near=[_NEIGHBOR, _HOUSE], address=_ADDR)
    assert got is not None and got.parcel_id == "5103026007"


def test_the_roll_year_travels_with_the_value():
    got = _lookup([_HOUSE])
    assert got is not None and "2026 roll" in got.data_vintage
    blank = _lookup([dict(_HOUSE, Roll_Year=None)])
    assert blank is not None and blank.data_vintage == la.DATA_VINTAGE


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


# ── five buildings a parcel ────────────────────────────────────────────────────


def test_buildings_that_disagree_on_the_year_give_no_year():
    """A 1910 front house and a 1926 rear one share a parcel and an address. The
    reader could be in either, and slot 1 is not evidence of which."""
    assert la._year_of_the_home(_TWO_ERAS) is None
    assert _lookup([_TWO_ERAS], address="448 N BREED ST, LOS ANGELES, CA") is None


def test_buildings_that_agree_on_the_year_give_it_but_not_an_area():
    """Whichever building is the home, it went up in 1957. The floor area is
    another matter: two buildings means two areas, and either could be the home."""
    got = _lookup([_SAME_YEAR])
    assert got is not None and got.year_built == 1957
    assert got.sqft is None


def test_a_building_with_no_recorded_year_breaks_the_agreement():
    """Its year could be anything, so skipping it would let the other building's
    year speak for a building nobody dated."""
    assert _lookup([_UNDATED_SECOND]) is None


def test_the_fixture_would_answer_without_its_undated_building():
    """Guards the test above from passing for some other reason."""
    alone = dict(_UNDATED_SECOND, DesignType2=None, YearBuilt2=None, Units2=None,
                 SQFTmain2=None)
    got = _lookup([alone])
    assert got is not None and got.year_built == 1950 and got.sqft == 1082.0


def test_a_year_of_zero_is_not_the_year_zero():
    """The roll's "not recorded" is the string "0000"."""
    got = _lookup([dict(_HOUSE, YearBuilt1="0000")])
    assert got is not None and got.year_built is None
    assert got.sqft == 912.0, "the area survives; only the year is missing"


def test_a_year_below_the_scorer_floor_is_not_a_year():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR as floor
    at = _lookup([dict(_HOUSE, YearBuilt1=str(floor))])
    assert at is not None and at.year_built == floor
    below = _lookup([dict(_HOUSE, YearBuilt1=str(floor - 1))])
    assert below is not None and below.year_built is None


def test_the_effective_year_is_never_read_or_requested():
    """A 1941 Santa Monica house carries an effective year of 1993."""
    got = _lookup([dict(_HOUSE, EffectiveYear1="1993")])
    assert got is not None and got.year_built == 1904
    for i in range(1, 6):
        assert f"EffectiveYear{i}" not in la._FIELDS.split(",")


# ── the floor area that describes one home ─────────────────────────────────────


def test_an_apartment_building_reports_its_year_but_not_its_floor_area():
    got = _lookup([_APARTMENTS])
    assert got is not None and got.year_built == 1959
    assert got.sqft is None, "21,244 sq ft is 24 homes, not one"


def test_a_house_whose_unit_count_is_zero_keeps_its_year_but_not_its_area():
    """Recorded live: a three-bedroom single-family house with ``Units1 = 0``. The
    year is not refused, because the zero is the roll not filling the column; the
    area is, because it needs a count of one to stand on."""
    got = _lookup([_UNITS_ZERO])
    assert got is not None and got.year_built == 1999
    assert got.sqft is None


def test_a_unit_typed_at_a_one_dwelling_address_costs_the_area_not_the_year():
    """A reader who wrote "#B" at an address the roll files as one dwelling is in
    some part of it the record does not describe separately."""
    got = _lookup([_HOUSE], address="897 E 52ND PL #B, LOS ANGELES, CA, 90011")
    assert got is not None and got.year_built == 1904
    assert got.sqft is None


# ── which parcels are homes ────────────────────────────────────────────────────


def test_a_parcel_the_roll_classifies_as_non_residential_reports_nothing():
    """The roll's own ``UseType``. A warehouse's year built is not the year anyone's
    home went up, and it would carry the ``observed`` tag."""
    assert _lookup([_WAREHOUSE]) is None
    for use in ("Commercial", "Industrial", "Institutional", "Government",
                "Recreational", "Miscellaneous", "Irrigated Farm"):
        assert _lookup([dict(_HOUSE, UseType=use)]) is None, use


def test_a_blank_use_type_is_silence_not_a_refusal():
    got = _lookup([dict(_HOUSE, UseType=None)])
    assert got is not None and got.year_built == 1904


def test_a_parcel_that_records_nothing_at_all_is_not_an_answer():
    """Checked through ``assessor_for_point`` too, which is the door the label uses.
    The registry entry is added for this test only; wiring the real one is a
    separate step."""
    empty = dict(_HOUSE, YearBuilt1="0000", SQFTmain1=0)
    assert _lookup([empty]) is None

    def fake(url, request, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    la._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    saved_entry = A.ADAPTERS.get("06037")
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    A.ADAPTERS["06037"] = la
    try:
        assert A.assessor_for_point(*_POINT, "06037") is None
    finally:
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        if saved_entry is None:
            A.ADAPTERS.pop("06037", None)
        else:
            A.ADAPTERS["06037"] = saved_entry
        la._lookup_cached.cache_clear()


# ── condominium units, stacked ─────────────────────────────────────────────────


def test_a_stack_without_an_address_is_ambiguous():
    """Every unit contains the point. With nothing to pick one by, there is no
    answer — not the first unit, not the building."""
    assert _lookup(_STACK) is None


def test_the_readers_unit_picks_its_record_and_its_own_floor_area():
    got = _lookup(_STACK, near=_STACK,
                  address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035")
    assert got is not None
    assert got.parcel_id == "4305007046"
    assert got.year_built == 2008
    assert got.sqft == 1590.0, "unit 103's own area, not unit 104's 1,471"


def test_a_unit_the_roll_writes_with_a_marker_word_still_matches():
    """Long Beach writes "NO  1108"; the reader writes "#1108"."""
    got = _lookup(_OCEAN, near=_OCEAN,
                  address="850 E OCEAN BLVD #1108, LONG BEACH, CA, 90802")
    assert got is not None and got.parcel_id == "7265022128" and got.sqft == 1590.0


def test_a_unit_is_found_through_the_buffer_when_the_geocode_misses_the_lot():
    got = _lookup([], near=[_HOUSE] + _STACK,
                  address="9049 ALCOTT ST APT 104, LOS ANGELES, CA, 90035")
    assert got is not None and got.parcel_id == "4305007047" and got.sqft == 1471.0


def test_two_records_claiming_one_unit_are_an_ambiguity():
    """Neither record is chosen, so neither area is reported. The building's year
    still is, because every record at the address agrees on it — the same answer
    whichever of the two is the reader's."""
    twice = _STACK + [_unit("4305007099", "103", 1700)]
    got = _lookup(twice, near=twice,
                  address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035")
    assert got is not None and got.parcel_id is None and got.sqft is None
    assert got.year_built == 2008
    split = _STACK + [_unit("4305007099", "103", 1700, year="2015")]
    assert _lookup(split, near=split,
                   address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035") is None


def test_no_unit_given_reports_the_buildings_year_and_nothing_else():
    """Which unit is unknowable, but every unit says 2008. No area, which belongs to
    one unit, and no parcel id, since no single record was chosen."""
    got = _lookup(_STACK, near=_STACK, address="9049 ALCOTT ST, LOS ANGELES, CA, 90035")
    assert got is not None
    assert got.year_built == 2008
    assert got.sqft is None and got.parcel_id is None


def test_an_unknown_unit_falls_back_to_the_buildings_year():
    got = _lookup(_STACK, near=_STACK,
                  address="9049 ALCOTT ST #999, LOS ANGELES, CA, 90035")
    assert got is not None and got.year_built == 2008 and got.sqft is None


def test_units_that_disagree_on_the_year_give_no_building_year():
    mixed = _STACK + [_unit("4305007070", "501", 1500, year="2015")]
    assert _lookup(mixed, near=mixed,
                   address="9049 ALCOTT ST, LOS ANGELES, CA, 90035") is None


def test_the_building_year_reads_the_whole_radius_not_just_the_stack_underfoot():
    """A complex can file two buildings as two stacks at one address. The stack the
    point lands in says nothing about the other."""
    other = [_unit("4305007080", "601", 1500, year="1975")]
    assert _lookup(_STACK, near=_STACK + other,
                   address="9049 ALCOTT ST, LOS ANGELES, CA, 90035") is None


def test_a_planned_development_is_picked_by_its_house_number():
    """Stacked like units, but "1 WILDERNESS PL" and "2 WILDERNESS PL" are two
    addresses, so the address alone names the home — and its area is its own."""
    got = _lookup(_PUD, near=_PUD, address="1 WILDERNESS PL, POMONA, CA, 91766")
    assert got is not None and got.parcel_id == "8701012020" and got.sqft == 1526.0


def test_the_unit_path_never_overrides_the_parcel_path():
    """A house answered by containment is never second-guessed by a path designed
    for condominiums."""
    got = _lookup([_HOUSE], near=[_HOUSE] + _STACK, address=_ADDR)
    assert got is not None and got.parcel_id == "5103026007"


def test_the_unit_paths_reuse_what_was_already_fetched():
    """The parcel path, the unit path and the building path read the same
    candidates. Asking again would spend the budget twice."""
    params = []
    _lookup(_STACK, near=_STACK, address="9049 ALCOTT ST, LOS ANGELES, CA, 90035",
            params=params)
    assert len(params) <= 2, f"{len(params)} requests for one lookup"


# ── the 1,000-record page ──────────────────────────────────────────────────────


def test_a_truncated_answer_is_no_answer():
    """The service stops at 1,000 records and says so. A truncated page can drop
    the second record that would have made a match ambiguous — here unit 103 looks
    unique in a page that may have held another."""
    page = [_unit("4305007046", "103", 1590)]
    assert _lookup(page, near=page, truncated=(0,),
                   address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035") is None
    assert _lookup([], near=page, truncated=(_shared.SEARCH_RADIUS_M,),
                   address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035") is None


def test_the_same_page_untruncated_answers():
    page = [_unit("4305007046", "103", 1590)]
    got = _lookup(page, near=page,
                  address="9049 ALCOTT ST #103, LOS ANGELES, CA, 90035")
    assert got is not None and got.parcel_id == "4305007046"


def test_a_row_with_no_ain_does_not_make_a_real_parcel_ambiguous():
    """22 of the county's rows carry no AIN. One overlapping a house would otherwise
    be counted as a rival candidate."""
    blank = _row(AIN=None, SitusHouseNo=None, SitusStreet=None)
    got = _lookup([blank, _HOUSE])
    assert got is not None and got.parcel_id == "5103026007"


# ── addresses ──────────────────────────────────────────────────────────────────


def test_a_lettered_avenue_keeps_its_letter_and_number():
    """The shared parser drops a digit-bearing token after a street type as a unit,
    so "5142 W AVE L8" and "5142 W AVENUE L10" — two Lancaster streets a few hundred
    meters apart — would match each other."""
    l8 = _row(AIN="3102023031", SitusHouseNo="5142", SitusDirection="W",
              SitusStreet="AVENUE L8", DesignType1="0110", YearBuilt1="1957",
              Units1=1, SQFTmain1=990)
    l10 = dict(l8, AIN="3102099999", SitusStreet="AVENUE L10", YearBuilt1="1988")
    addr = "5142 W AVE L8, LANCASTER, CA, 93536"
    got = _lookup([], near=[l10, l8], address=addr)
    assert got is not None and got.parcel_id == "3102023031"
    assert _lookup([], near=[l10], address=addr) is None
    assert not _shared.same_address(la._canon(addr), la._address_of(l10))


def test_the_census_spellings_of_a_lettered_avenue_match_the_rolls():
    """The geocoder writes "AVE R-9" and "AVE Q 12" for the roll's "AVENUE R9" and
    "AVENUE Q12"; and a bare letter, "AVE I"."""
    for census, roll in (("231 E AVE R-9, PALMDALE, CA", "231 E AVENUE R9"),
                         ("3114 E AVE Q 12, PALMDALE, CA", "3114 E AVENUE Q12"),
                         ("5 AVE I, LANCASTER, CA", "5 AVENUE I")):
        assert _shared.same_address(la._canon(census), la._canon(roll)), census


def test_a_numbered_avenue_is_not_its_neighbor():
    """Northeast LA's Avenue 63 and Avenue 64 run parallel a block apart."""
    assert not _shared.same_address(la._canon("223 N AVE 64, LOS ANGELES, CA"),
                                    la._canon("223 N AVENUE 63"))
    assert _shared.same_address(la._canon("223 N AVE 64 #3, LOS ANGELES, CA"),
                                la._canon("223 N AVENUE 64"))


def test_an_avenue_with_a_name_is_left_alone():
    assert la._canon("1801 AVENUE OF THE STARS") == "1801 AVENUE OF THE STARS"


def test_the_rolls_wy_is_a_way():
    pud = _row(AIN="3004040018", SitusHouseNo="1301", SitusStreet="CHEETAH WY",
               DesignType1="0130", YearBuilt1="1994", Units1=1, SQFTmain1=2098)
    got = _lookup([], near=[pud], address="1301 CHEETAH WAY, PALMDALE, CA, 93551")
    assert got is not None and got.year_built == 1994


def test_a_half_address_is_not_the_whole_one():
    """"4028 1/2 CLARA ST" is its own address, and often its own parcel."""
    half = _row(AIN="6225024001", SitusHouseNo="4028", SitusFraction="1/2",
                SitusStreet="CLARA ST", DesignType1="0110", YearBuilt1="1924",
                Units1=1, SQFTmain1=943)
    assert la._address_of(half) == "4028 1/2 CLARA ST"
    assert _lookup([], near=[half], address="4028 CLARA ST, CUDAHY, CA, 90201") is None


def test_house_number_zero_is_not_an_address():
    vacant = _row(AIN="3080014009", SitusHouseNo="0",
                  SitusStreet="VAC/COR 166 STE/AVE T")
    assert la._address_of(vacant) is None


def test_unit_designators_are_compared_by_what_identifies_them():
    assert la._unit_key("NO    B5") == la._unit_key("B-5") == "B5"
    assert la._unit_key("APT 104S") == "104S"
    assert la._unit_key("# 6") == la._unit_key("UNIT 6") == "6"
    assert la._unit_key(" ") is None and la._unit_key(None) is None
    assert la._unit_key("01") != la._unit_key("1"), "leading zeros are significant"


# ── the columns that must not be read ──────────────────────────────────────────


def test_the_quality_class_is_not_requested():
    """A construction class (D = wood frame) that the label's three-way split of
    wood frame by its skin cannot be read from; see the module docstring."""
    for i in range(1, 6):
        assert f"QualityClass{i}" not in la._FIELDS.split(",")


def test_the_field_list_is_the_privacy_boundary():
    for private in ("Roll_LandValue", "Roll_ImpValue", "Roll_PersPropValue",
                    "Roll_HomeOwnersExemp", "Roll_RealEstateExemp", "LegalDescription",
                    "LegalDescLine1", "CENTER_LAT", "CENTER_LON", "LAT_LON", "*"):
        assert private not in la._FIELDS.split(","), private
    assert len(la._FIELDS.split(",")) == 28


def test_the_requested_fields_are_what_reaches_the_service():
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["outFields"] == la._FIELDS for p in params)


def test_the_buffered_query_is_in_meters_and_carries_an_output_reference():
    params = []
    _lookup([], near=[_HOUSE], address=_ADDR, params=params)
    assert len(params) == 2
    assert params[1]["distance"] == str(_shared.SEARCH_RADIUS_M)
    assert params[1]["units"] == "esriSRUnit_Meter"
    assert all(p["inSR"] == "4326" and p["outSR"] == "4326" for p in params)


# ── the county list ────────────────────────────────────────────────────────────


def test_the_county_code_is_in_the_repos_own_county_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert la.COUNTY_FIPS == {"06037"}
    assert la.COUNTY_FIPS <= geoids


# ── the clock ──────────────────────────────────────────────────────────────────


def test_los_angeles_asks_for_its_own_read_slice_not_the_shared_one():
    """Measured: the service's slow tail passes one second on both requests, and an
    earlier run at the shared slice lost an address to a 1.004 s cut-off. Pinned on
    what reaches the transport, not on the constant."""
    slices = []
    got = _lookup([_HOUSE], slices=slices)
    assert got is not None
    assert slices and all(s == la.READ_SLICE_S for s in slices), slices
    assert la.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert la.LOOKUP_TIMEOUT + la.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET, (
        f"worst case {la.LOOKUP_TIMEOUT + la.READ_SLICE_S}s is not under the "
        f"{config.UPSTREAM_HOST_BUDGET}s this host allows one service")


def test_every_request_shares_one_clock_started_once():
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": [{"attributes": a} for a in _STACK]}

    la._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        la.lookup(*_POINT, "9049 ALCOTT ST, LOS ANGELES, CA, 90035")
    finally:
        _shared.get_json = saved
        la._lookup_cached.cache_clear()

    assert len(seen) == 2, f"expected a containment and a buffered request, got {len(seen)}"
    assert seen[0] == seen[1], "each request was handed its own budget"
    assert abs((seen[0] - started) - la.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    la._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert la.lookup(*_POINT, _ADDR) is None
    finally:
        _shared.get_json = saved
        la._lookup_cached.cache_clear()


def test_a_malformed_body_is_not_an_exception_for_the_caller():
    def odd(url, request, deadline, read_slice=None):
        return {"features": [None, {"attributes": None}]}

    la._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = odd
    try:
        assert la.lookup(*_POINT, _ADDR) is None
    finally:
        _shared.get_json = saved
        la._lookup_cached.cache_clear()
