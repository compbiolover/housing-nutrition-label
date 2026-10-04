#!/usr/bin/env python3
"""The Georgia adapter — four county layers in one table, and what each must refuse.

Nothing here touches the network. Each county's service is stubbed with row
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"this county has no record here" and would never announce itself. A test that
called the real services would pass just as quietly.

What is worth pinning is what is genuinely Georgia's. The dangerous shared parts —
choosing which parcel an address means, comparing two addresses, bounding the
request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Georgia's own:

1. **Fulton is two hops**, and its footprint layer carries an area column that is
   not a living area, several footprints per parcel, and story counts that
   split levels make meaningless.
2. **Clayton's UNIT column is the plat's**, not a dwelling's.
3. **Chatham's condominium units** share one street address and differ only in a
   unit written with a doubled marker.
4. **Forsyth is a tax-year-2024 snapshot**, and every record must say so.
5. **Richmond, Gwinnett and Cobb are not answered** — for their terms, not their
   data — and DeKalb has no data.
6. Parcel ids carry **inner runs of spaces** that are part of the id.

This file alone: ``pytest tests/test_assessor_ga.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

from housing_label.enrich.assessor import _shared, ga

_ROOT = pathlib.Path(__file__).resolve().parent.parent

FULTON, CLAYTON, CHATHAM, FORSYTH, RICHMOND = "13121", "13063", "13051", "13117", "13245"

# ── recorded rows ───────────────────────────────────────────────────────────────

# Recorded live from Fulton's Tax_Parcels. A one-family house in Atlanta.
_F_HOUSE = {"ParcelID": "17 005200020199", "Address": "833 CUMBERLAND RD NE",
            "AddrUnit": None, "LUCode": "101", "ClassCode": "R3", "LivUnits": 1,
            "TaxYear": 2026}
# Recorded live: its two Structure_Footprints rows (a house and an outbuilding,
# both carrying the parcel's CAMA dwelling attributes).
_F_HOUSE_FOOTPRINTS = [
    {"ParcelID": "17 005200020199", "FeatType": "Residential", "YearBuilt": "1939",
     "Stories": 1, "StructForm": "Conventional"},
    {"ParcelID": "17 005200020199", "FeatType": "Residential", "YearBuilt": "1939",
     "Stories": 1, "StructForm": "Conventional"},
]
# Recorded live. 7007 Riverside Dr: one parcel, two dwelling records — a 1976
# house and a 1973 one — so its residential footprints disagree on the year. The
# parcel id carries TWO spaces, exactly as Fulton writes it.
_F_TWO_HOMES = {"ParcelID": "17 0127  LL0599", "Address": "7007 RIVERSIDE DR",
                "AddrUnit": None, "LUCode": "101", "ClassCode": "R4", "LivUnits": 1,
                "TaxYear": 2026}
_F_TWO_HOMES_FOOTPRINTS = [
    {"ParcelID": "17 0127  LL0599", "FeatType": "Residential", "YearBuilt": "1976",
     "Stories": 2, "StructForm": "Modern"},
    {"ParcelID": "17 0127  LL0599", "FeatType": "Residential", "YearBuilt": "1973",
     "Stories": 1, "StructForm": "Conventional"},
    {"ParcelID": "17 0127  LL0599", "FeatType": "Residential", "YearBuilt": "1973",
     "Stories": 1, "StructForm": "Conventional"},
]
# Recorded live. 208 Camp St and 208½ Camp St are two parcels.
_F_HALF = {"ParcelID": "07 360800670849", "Address": "208 CAMP ST 1/2",
           "AddrUnit": "1/2", "LUCode": "101", "ClassCode": "R3", "LivUnits": 1,
           "TaxYear": 2026}

# Recorded live from Clayton's TaxAssessor/Parcels. A one-family ranch.
_C_HOUSE = {"PARCELID": "13083A A008", "SITEADDRES": "412 SPRINGSIDE DR",
            "LANDUSEC": "101", "STRUCTYPE": "RANCH", "YEARBUILT": "1962",
            "SQRFT": "1628"}
# Recorded live. A two-family ranch (LANDUSEC 102): its area is both homes'.
_C_DUPLEX = {"PARCELID": "05208D B007", "SITEADDRES": "1179 ORR RD",
             "LANDUSEC": "102", "STRUCTYPE": "RANCH", "YEARBUILT": "1948",
             "SQRFT": "1550"}
# Recorded live. An auto service garage: a year built, and no home.
_C_GARAGE = {"PARCELID": "05239 240008", "SITEADDRES": "9250 POSTON RD",
             "LANDUSEC": "332", "STRUCTYPE": "", "YEARBUILT": "1986", "SQRFT": ""}

# Recorded live from SAGIS's Parcel Digest 2025: three condominium units sharing
# one street address, each its own parcel with its own year.
_S_UNITS = [
    {"PIN": "10011 03024", "PropAddress_Full": "111 SAN MARCO DR ##A",
     "PropAddress_UnitNum": "#A", "Property_Use": "R3", "YearBuilt": 2004,
     "FMV_Building": 594400, "Date_Updated": 1746489600000},
    {"PIN": "10011 03025", "PropAddress_Full": "111 SAN MARCO DR ##B",
     "PropAddress_UnitNum": "#B", "Property_Use": "R3", "YearBuilt": 1984,
     "FMV_Building": 356600, "Date_Updated": 1746489600000},
    {"PIN": "10011 03026", "PropAddress_Full": "111 SAN MARCO DR ##C",
     "PropAddress_UnitNum": "#C", "Property_Use": "R3", "YearBuilt": 2005,
     "FMV_Building": 930300, "Date_Updated": 1746489600000},
]
# Recorded live. A Savannah house.
_S_HOUSE = {"PIN": "10010 01003", "PropAddress_Full": "154 SAN MARCO DR",
            "PropAddress_UnitNum": "", "Property_Use": "R3", "YearBuilt": 1982,
            "FMV_Building": 512000, "Date_Updated": 1746489600000}

# Recorded live from Forsyth's TylerParcels. A two-story house; the id carries
# three spaces, exactly as the export writes it.
_Y_HOUSE = {"VAL_PARID": "073   290", "SITEADDRES": "4925 SERENITY STONE CT",
            "UNIT": " ", "P_CLASS": "R3", "P_LUC": "0100", "D_YRBLT": "2007",
            "D_STORIES": "2", "BLDGAREA": "2536", "TAXYEAR": "2024"}
# Recorded live. A "RESIDENTIAL CONDOMINIUM" (P_LUC 0300).
_Y_CONDO = {"VAL_PARID": "111   483", "SITEADDRES": "2520 CALLAWAY CT", "UNIT": " ",
            "P_CLASS": "R3", "P_LUC": "0300", "D_YRBLT": "2007", "D_STORIES": "2",
            "BLDGAREA": "2188", "TAXYEAR": "2024"}

#: A point in Atlanta. Which parcel a coordinate lands in is decided here by the
#: stubbed rows, not by the coordinate, and the county by the stub or the caller.
_POINT = (33.79, -84.36)


def _lookup(county, exact, near=(), footprints=(), address=None, *, calls=None,
            pass_county=True, county_at=None):
    """Drive ``ga.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find; ``footprints`` is what Fulton's second hop returns. All are
    answered through the real transport helper, so the field lists, the id
    filter, the unit filter and the parcel choice are exercised rather than
    stepped over. ``calls``, when passed, collects (url, params, deadline, slice)
    for every request. ``county_at`` is what TIGERweb answers when the caller
    passes no county.
    """
    calls = [] if calls is None else calls

    def fake(url, params, deadline, read_slice=None):
        calls.append((url, params, deadline, read_slice))
        if url == ga.COUNTY_URL:
            return {"features": [{"attributes": {"GEOID": county_at or county}}]}
        if url == ga.FULTON_STRUCTURES_URL:
            return {"features": [{"attributes": a} for a in footprints]}
        rows = list(near) if params.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    ga._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        if pass_county:
            return ga.lookup(*_POINT, address, county_fips=county)
        return ga.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        ga._lookup_cached.cache_clear()


# ── Fulton: two hops ────────────────────────────────────────────────────────────


def test_a_fulton_house_resolves_through_its_footprints():
    got = _lookup(FULTON, [_F_HOUSE], footprints=_F_HOUSE_FOOTPRINTS)
    assert got is not None
    assert got.year_built == 1939
    assert got.stories == 1
    assert got.parcel_id == "17 005200020199"
    assert "2026" in got.data_vintage and "Fulton" in got.data_vintage
    assert "Fulton" in got.source


def test_fulton_never_reports_a_floor_area():
    """``AreaSqFt`` repeats unchanged across every footprint of a parcel and reads
    730–933 on two-story homes: it is not the living area the label's ``sqft``
    means. It is not requested, and even a row that carried it reports none."""
    assert "AreaSqFt" not in ga._FULTON_STRUCTURE_FIELDS.split(",")
    with_area = [dict(r, AreaSqFt=1356.0) for r in _F_HOUSE_FOOTPRINTS]
    got = _lookup(FULTON, [_F_HOUSE], footprints=with_area)
    assert got is not None and got.sqft is None


def test_footprints_that_disagree_on_the_year_are_refused():
    """Two dwelling records on one parcel — a 1973 house and a 1976 one. Naming
    either would be a guess, and "the largest footprint" would rank by the very
    area column that does not mean what it says."""
    assert _lookup(FULTON, [_F_TWO_HOMES], footprints=_F_TWO_HOMES_FOOTPRINTS) is None


def test_a_commercial_footprints_year_is_not_the_homes():
    shop = {"ParcelID": "17 005200020199", "FeatType": "Commercial",
            "YearBuilt": "1990", "Stories": None, "StructForm": None}
    got = _lookup(FULTON, [_F_HOUSE], footprints=_F_HOUSE_FOOTPRINTS + [shop])
    assert got is not None and got.year_built == 1939


def test_a_parcel_with_no_residential_footprint_reports_nothing():
    """Condominium unit parcels have no footprints at all (6 of 242 sampled), so a
    condo resolves to nothing rather than to the building's record."""
    shop = {"ParcelID": "17 005200020199", "FeatType": "Commercial",
            "YearBuilt": "1990", "Stories": None, "StructForm": None}
    assert _lookup(FULTON, [_F_HOUSE], footprints=[shop]) is None
    assert _lookup(FULTON, [_F_HOUSE], footprints=[]) is None


def test_the_second_hop_joins_on_the_id_exactly_as_fulton_writes_it():
    """"17 0127  LL0599" has two spaces. Collapsing them would join to nothing —
    and would hand a reader an id the county's own search does not know."""
    calls = []
    footprints = [dict(r, YearBuilt="1973", Stories=1, StructForm="Conventional")
                  for r in _F_TWO_HOMES_FOOTPRINTS]
    got = _lookup(FULTON, [_F_TWO_HOMES], footprints=footprints, calls=calls)
    assert got is not None and got.parcel_id == "17 0127  LL0599"
    hop = [p for u, p, _, _ in calls if u == ga.FULTON_STRUCTURES_URL]
    assert hop and hop[0]["where"] == "ParcelID='17 0127  LL0599'"


def test_an_explicit_zero_living_units_refuses_the_year():
    assert _lookup(FULTON, [dict(_F_HOUSE, LivUnits=0)],
                   footprints=_F_HOUSE_FOOTPRINTS) is None


def test_a_missing_living_unit_count_keeps_the_year_but_not_the_stories():
    """Silence is not a statement; but the stories need the count of one."""
    got = _lookup(FULTON, [dict(_F_HOUSE, LivUnits=None)],
                  footprints=_F_HOUSE_FOOTPRINTS)
    assert got is not None and got.year_built == 1939 and got.stories is None


def test_a_two_family_parcel_keeps_its_year_and_loses_its_stories():
    got = _lookup(FULTON, [dict(_F_HOUSE, LUCode="102", LivUnits=2)],
                  footprints=_F_HOUSE_FOOTPRINTS)
    assert got is not None and got.year_built == 1939 and got.stories is None


def test_story_counts_that_a_form_makes_meaningless_are_dropped():
    """Fulton files 10,119 split levels as one story, and 269 ranches as two."""
    for form, stories in (("Split-Level", 1), ("BI-Level", 1), ("Cape", 2),
                          ("Ranch", 2), ("Duplex", 1), ("Condominium", 3)):
        rows = [dict(r, StructForm=form, Stories=stories) for r in _F_HOUSE_FOOTPRINTS]
        got = _lookup(FULTON, [_F_HOUSE], footprints=rows)
        assert got is not None and got.stories is None, form
    rows = [dict(r, StructForm="Colonial", Stories=2) for r in _F_HOUSE_FOOTPRINTS]
    assert _lookup(FULTON, [_F_HOUSE], footprints=rows).stories == 2


def test_footprints_that_disagree_on_the_stories_report_none():
    rows = [_F_HOUSE_FOOTPRINTS[0], dict(_F_HOUSE_FOOTPRINTS[1], Stories=2)]
    got = _lookup(FULTON, [_F_HOUSE], footprints=rows)
    assert got is not None and got.year_built == 1939 and got.stories is None


def test_a_half_number_is_not_the_whole_number():
    """The shared comparison drops a digit-bearing token after a street type as an
    unmarked unit, which would confirm 208½ Camp St as 208 Camp St."""
    assert ga._fulton_address(_F_HALF) is None
    rows = [dict(r, ParcelID=_F_HALF["ParcelID"]) for r in _F_HOUSE_FOOTPRINTS]
    typed = "208 CAMP ST, ATLANTA, GA"
    assert _lookup(FULTON, [_F_HALF], footprints=rows, address=typed) is None
    assert _lookup(FULTON, [], near=[_F_HALF], footprints=rows, address=typed) is None
    # Guards the assertions above from passing vacuously: the same parcel, as a
    # whole number, does answer.
    whole = dict(_F_HALF, Address="208 CAMP ST", AddrUnit=None)
    got = _lookup(FULTON, [], near=[whole], footprints=rows, address=typed)
    assert got is not None and got.year_built == 1939


def test_a_fulton_unit_typed_by_the_reader_picks_its_own_parcel():
    a = dict(_F_HOUSE, ParcelID="A", Address="633 CARLTON POINTE DR 23",
             AddrUnit="23", LUCode="106")
    b = dict(_F_HOUSE, ParcelID="B", Address="633 CARLTON POINTE DR 24",
             AddrUnit="24", LUCode="106")
    rows = [dict(r, ParcelID="B") for r in _F_HOUSE_FOOTPRINTS]
    got = _lookup(FULTON, [], near=[a, b], footprints=rows,
                  address="633 CARLTON POINTE DR #24, ATLANTA, GA")
    assert got is not None and got.parcel_id == "B"
    assert got.stories is None, "a unit parcel's stories are the building's"


# ── Clayton ─────────────────────────────────────────────────────────────────────


def test_a_clayton_house_reports_year_area_and_stories():
    got = _lookup(CLAYTON, [_C_HOUSE])
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1962, 1628.0, 1)
    assert got.parcel_id == "13083A A008"
    assert "Clayton" in got.source


def test_a_two_family_parcel_keeps_its_year_and_loses_its_area():
    """The condo/multi-unit trap: a duplex's area is both homes'. Never divided."""
    got = _lookup(CLAYTON, [_C_DUPLEX])
    assert got is not None and got.year_built == 1948
    assert got.sqft is None and got.stories is None


def test_a_commercial_land_use_refuses_the_year():
    """Clayton's year column is filled for auto garages, warehouses and retail."""
    assert _lookup(CLAYTON, [_C_GARAGE]) is None
    vacant = dict(_C_HOUSE, LANDUSEC="100")
    assert _lookup(CLAYTON, [vacant]) is None


def test_a_home_on_commercial_land_is_still_a_home():
    got = _lookup(CLAYTON, [dict(_C_HOUSE, LANDUSEC="301")])
    assert got is not None and got.year_built == 1962
    assert got.sqft is None, "only one-family and townhouse parcels are one home"


def test_a_year_that_is_not_a_year_is_not_reported():
    """Clayton's YEARBUILT is a string: '' on 6,532 rows, '0' on 953, and junk
    as short as '970'. The area survives each."""
    for raw in ("0", "", " ", "970", None, "19x2"):
        got = _lookup(CLAYTON, [dict(_C_HOUSE, YEARBUILT=raw)])
        assert got is not None and got.year_built is None, raw
        assert got.sqft == 1628.0


def test_clayton_stories_only_where_the_style_names_a_whole_number():
    for style, want in (("RANCH", 1), ("TWO STORY", 2), ("3 STORY", 3),
                        ("SPLIT LEVEL", None), ("1 1/2 STORY", None), ("", None)):
        got = _lookup(CLAYTON, [dict(_C_HOUSE, STRUCTYPE=style)])
        assert got is not None and got.stories == want, style


def test_claytons_plat_unit_and_quality_grade_are_never_requested():
    """UNIT is the plat's ("UNIT 1 PHASE A" on every lot of a phase), and
    QUALITYOFBUILDING is a construction grade, not a condition."""
    fields = ga._CLAYTON_FIELDS.split(",")
    assert "UNIT" not in fields and "QUALITYOFBUILDING" not in fields
    plat = dict(_C_HOUSE, UNIT="UNIT 1 PHASE A")
    got = _lookup(CLAYTON, [plat])
    assert got is not None and got.sqft == 1628.0


# ── Chatham ─────────────────────────────────────────────────────────────────────


def test_a_chatham_house_resolves_and_dates_itself_from_its_row():
    got = _lookup(CHATHAM, [_S_HOUSE])
    assert got is not None and got.year_built == 1982
    assert got.sqft is None and got.stories is None, "the digest has neither"
    assert "Parcel Digest 2025" in got.data_vintage and "2025-05-06" in got.data_vintage


def test_a_typed_unit_picks_its_own_condominium_parcel():
    """Three units, one street address, a unit written '##A'. The reader's '#B' is
    the only thing that can say which home is theirs."""
    got = _lookup(CHATHAM, [], near=_S_UNITS, address="111 SAN MARCO DR #B, SAVANNAH, GA")
    assert got is not None and got.parcel_id == "10011 03025" and got.year_built == 1984


def test_a_typed_unit_is_never_answered_by_a_sibling_that_lost_its_unit():
    """Units A and C are filed with their letter, B as the bare address. A reader
    who typed #D has no parcel here; B is one of the numbered units, not theirs."""
    bare_b = dict(_S_UNITS[1], PropAddress_Full="111 SAN MARCO DR",
                  PropAddress_UnitNum="")
    near = [_S_UNITS[0], bare_b, _S_UNITS[2]]
    assert _lookup(CHATHAM, [], near=near, address="111 SAN MARCO DR #D, SAVANNAH, GA") is None
    got = _lookup(CHATHAM, [], near=near, address="111 SAN MARCO DR #C, SAVANNAH, GA")
    assert got is not None and got.parcel_id == "10011 03026"


def test_without_a_unit_the_stacked_units_are_ambiguous():
    assert _lookup(CHATHAM, [], near=_S_UNITS, address="111 SAN MARCO DR, SAVANNAH, GA") is None
    assert _lookup(CHATHAM, _S_UNITS[:2], address="111 SAN MARCO DR, SAVANNAH, GA") is None


def test_a_zero_building_value_or_commercial_class_refuses_the_year():
    assert _lookup(CHATHAM, [dict(_S_HOUSE, FMV_Building=0)]) is None
    assert _lookup(CHATHAM, [dict(_S_HOUSE, Property_Use="C3")]) is None
    exempt = _lookup(CHATHAM, [dict(_S_HOUSE, Property_Use="E1")])
    assert exempt is not None, "exemption is silence about who lives there"


def test_chatham_reads_the_open_data_layer_with_the_clear_license():
    assert "/OpenData/Parcels/MapServer/27/" in ga.CHATHAM_URL
    assert "Effective_YB" not in ga._CHATHAM_FIELDS.split(",")


# ── Forsyth ─────────────────────────────────────────────────────────────────────


def test_a_forsyth_house_reports_and_says_it_is_a_2024_snapshot():
    got = _lookup(FORSYTH, [_Y_HOUSE])
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (2007, 2536.0, 2)
    assert got.parcel_id == "073   290", "inner spaces are part of the id"
    assert "tax year 2024" in got.data_vintage and "snapshot" in got.data_vintage


def test_a_forsyth_row_without_its_tax_year_still_says_2024():
    got = _lookup(FORSYTH, [dict(_Y_HOUSE, TAXYEAR=" ")])
    assert got is not None and "2024" in got.data_vintage


def test_a_forsyth_condominium_keeps_its_year_and_loses_its_area():
    got = _lookup(FORSYTH, [_Y_CONDO])
    assert got is not None and got.year_built == 2007
    assert got.sqft is None and got.stories is None


def test_half_stories_and_blank_years_are_not_numbers():
    got = _lookup(FORSYTH, [dict(_Y_HOUSE, D_STORIES="1.5")])
    assert got is not None and got.stories is None and got.sqft == 2536.0
    got = _lookup(FORSYTH, [dict(_Y_HOUSE, D_YRBLT=" ")])
    assert got is not None and got.year_built is None and got.sqft == 2536.0


def test_forsyth_common_areas_and_commercial_classes_report_nothing():
    for row in (dict(_Y_HOUSE, P_LUC="0111"), dict(_Y_HOUSE, P_LUC="0207"),
                dict(_Y_HOUSE, P_CLASS="C3"), dict(_Y_HOUSE, P_CLASS="I3")):
        assert _lookup(FORSYTH, [row]) is None, row


def test_forsyths_commercial_card_year_is_never_requested():
    assert "CD_YRBLT" not in ga._FORSYTH_FIELDS.split(",")


# ── which counties, and which not ───────────────────────────────────────────────


def test_county_fips_are_real_georgia_counties():
    """Checked against the county table this repository already ships."""
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        georgia = {r["geoid"] for r in csv.DictReader(fh)
                   if r["geoid"].startswith("13") and len(r["geoid"]) == 5}
    assert len(georgia) == 159, f"expected 159 Georgia counties, got {len(georgia)}"
    assert ga.COUNTY_FIPS <= georgia
    assert ga.COUNTY_FIPS == {FULTON, CLAYTON, CHATHAM, FORSYTH}


def test_counties_held_or_excluded_for_terms_are_not_answered():
    """Gwinnett ("internal purposes by recipient only") and Cobb ("All rights
    reserved") await a product-owner decision and are not even configured.
    Richmond ("strictly forbidden to … reproduce these maps or data … without the
    written consent") is configured and held. DeKalb's year columns are empty."""
    for fips in ("13135", "13067", "13089", RICHMOND):
        assert fips not in ga.COUNTY_FIPS, fips
    assert "13135" not in ga._COUNTIES and "13067" not in ga._COUNTIES
    assert RICHMOND in ga._HELD_FOR_TERMS


def test_a_held_county_is_answered_with_nothing_and_asked_nothing():
    calls = []
    row = {"pin": "011-0-208-00-0", "siteaddress": "104 Tremont Way",
           "propdesc": "Residential Lots", "vacant": "No", "yr_built": 1963,
           "structsize": 2013.0}
    assert _lookup(RICHMOND, [row], calls=calls) is None
    assert calls == [], "a held county must not even be queried"
    assert _lookup(RICHMOND, [row], calls=calls, pass_county=False) is None
    assert all(u == ga.COUNTY_URL for u, *_ in calls)


def test_without_a_county_the_point_is_routed_by_tigerweb():
    calls = []
    got = _lookup(CLAYTON, [_C_HOUSE], calls=calls, pass_county=False)
    assert got is not None and got.year_built == 1962
    assert [u for u, *_ in calls][:2] == [ga.COUNTY_URL, ga.CLAYTON_URL]


def test_a_point_tigerweb_places_in_an_unanswered_county_gets_nothing():
    assert _lookup(CLAYTON, [_C_HOUSE], pass_county=False, county_at="13135") is None


# ── privacy: the field lists ────────────────────────────────────────────────────


def test_every_field_list_is_explicit_and_carries_no_owner_or_mailing_column():
    private = {"*", "Owner", "Owner2", "OwnerAddr1", "OwnerAddr2", "OWNERNME",
               "PSTLADDRES", "SALEPRICE", "Mailing_Address", "Sale_Price", "O_OWN1",
               "O_OWN2", "O_ADDR1", "own1", "owner_address1", "delinq_bill_amt"}
    lists = [c.fields for c in ga._COUNTIES.values()] + [ga._FULTON_STRUCTURE_FIELDS]
    for fields in lists:
        assert not private & set(fields.split(",")), fields


def test_the_requested_fields_are_what_reaches_each_service():
    for fips, rows in ((FULTON, [_F_HOUSE]), (CLAYTON, [_C_HOUSE]),
                       (CHATHAM, [_S_HOUSE]), (FORSYTH, [_Y_HOUSE])):
        calls = []
        _lookup(fips, rows, footprints=_F_HOUSE_FOOTPRINTS, calls=calls)
        parcel = [p for u, p, _, _ in calls if u == ga._COUNTIES[fips].url]
        assert parcel and all(p["outFields"] == ga._COUNTIES[fips].fields
                              for p in parcel), fips
    calls = []
    _lookup(FULTON, [_F_HOUSE], footprints=_F_HOUSE_FOOTPRINTS, calls=calls)
    hop = [p for u, p, _, _ in calls if u == ga.FULTON_STRUCTURES_URL]
    assert hop and hop[0]["outFields"] == ga._FULTON_STRUCTURE_FIELDS


# ── the vocabulary ──────────────────────────────────────────────────────────────


def test_no_county_vocabulary_reaches_the_translated_fields():
    """Fulton's StructForm and Forsyth's D_STYLE are architectural styles; the
    grades are construction quality. None maps onto construction, foundation or
    condition, so those stay empty everywhere."""
    for fips, rows in ((FULTON, [_F_HOUSE]), (CLAYTON, [dict(_C_HOUSE, QUALITYOFBUILDING="E")]),
                       (CHATHAM, [_S_HOUSE]), (FORSYTH, [dict(_Y_HOUSE, D_STYLE="01")])):
        got = _lookup(fips, rows, footprints=_F_HOUSE_FOOTPRINTS)
        assert got is not None, fips
        assert (got.construction, got.foundation, got.condition) == (None, None, None)


def test_the_georgia_land_use_reading():
    assert ga._luc_says_no_home("100")             # residential vacant
    assert ga._luc_says_no_home("188")             # HOA common area
    assert ga._luc_says_no_home("332")             # auto service garage
    assert ga._luc_says_no_home("3C3")             # low-rise office
    assert not ga._luc_says_no_home("101")
    assert not ga._luc_says_no_home("2C1"), "an apartment building is homes"
    assert not ga._luc_says_no_home("622"), "a parsonage is a home"
    assert not ga._luc_says_no_home(""), "silence is not a statement"
    assert not ga._luc_says_no_home(None)


def test_the_plausibility_floor_is_the_scorers():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert ga._year(str(EARLIEST_PLAUSIBLE_YEAR)) == EARLIEST_PLAUSIBLE_YEAR
    assert ga._year(str(EARLIEST_PLAUSIBLE_YEAR - 1)) is None
    assert ga._year("2101") is None and ga._year("1990.5") is None


# ── candidates ──────────────────────────────────────────────────────────────────


def test_a_row_with_no_parcel_id_is_not_a_candidate():
    blank = dict(_C_HOUSE, PARCELID=" ", SITEADDRES="412 SPRINGSIDE DR")
    got = _lookup(CLAYTON, [blank, _C_HOUSE])
    assert got is not None and got.parcel_id == "13083A A008"


def test_a_parcel_repeated_once_per_polygon_part_is_one_candidate():
    got = _lookup(CLAYTON, [_C_HOUSE, dict(_C_HOUSE)])
    assert got is not None and got.year_built == 1962


def test_two_different_parcels_at_the_point_are_ambiguous():
    other = dict(_C_HOUSE, PARCELID="13083A A009")
    assert _lookup(CLAYTON, [_C_HOUSE, other]) is None


# ── the clock ───────────────────────────────────────────────────────────────────


def test_every_request_carries_georgias_slice_and_one_deadline():
    """Fulton's off-parcel lookup is the longest: containment, buffer, footprints.
    All three share one deadline computed once, and each is handed READ_SLICE_S —
    pinned on what reaches the transport, not on the constant."""
    calls = []
    started = time.monotonic()
    got = _lookup(FULTON, [], near=[_F_HOUSE], footprints=_F_HOUSE_FOOTPRINTS,
                  address="833 CUMBERLAND RD NE, ATLANTA, GA", calls=calls)
    assert got is not None
    assert len(calls) == 3
    assert {d for _, _, d, _ in calls} == {calls[0][2]}, "each request got its own budget"
    assert all(s == ga.READ_SLICE_S for *_, s in calls)
    assert abs((calls[0][2] - started) - ga.LOOKUP_TIMEOUT) < 0.5


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert ga.LOOKUP_TIMEOUT + ga.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET, (
        f"worst case {ga.LOOKUP_TIMEOUT + ga.READ_SLICE_S}s is not under the "
        f"{config.UPSTREAM_HOST_BUDGET}s this host allows one service")


# ── failing open ────────────────────────────────────────────────────────────────


def _raising(exc):
    def boom(url, params, deadline, read_slice=None):
        raise exc
    return boom


def test_a_service_falling_over_is_not_evidence_of_absence():
    for exc in (RuntimeError("upstream error: layer not found"), TimeoutError("budget"),
                _shared.TruncatedResponse("truncated at the transfer limit")):
        ga._lookup_cached.cache_clear()
        saved = _shared.get_json
        _shared.get_json = _raising(exc)
        try:
            assert ga.lookup(*_POINT, "412 SPRINGSIDE DR", county_fips=CLAYTON) is None
            assert ga.lookup(*_POINT, "412 SPRINGSIDE DR") is None
        finally:
            _shared.get_json = saved
            ga._lookup_cached.cache_clear()


def test_the_second_hop_falling_over_fails_open_too():
    calls = []

    def fake(url, params, deadline, read_slice=None):
        calls.append(url)
        if url == ga.FULTON_STRUCTURES_URL:
            raise RuntimeError("upstream error")
        return {"features": [{"attributes": _F_HOUSE}]}

    ga._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        assert ga.lookup(*_POINT, None, county_fips=FULTON) is None
    finally:
        _shared.get_json = saved
        ga._lookup_cached.cache_clear()
    assert ga.FULTON_STRUCTURES_URL in calls


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup(CLAYTON, []) is None


def test_a_unit_written_with_its_marker_word_is_the_typed_unit():
    """Forsyth writes "UNIT 13"; a reader types "#13" or "Unit 13"."""
    assert ga._same_unit_or_none("UNIT 13", "13")
    assert ga._same_unit_or_none("#13", "13")
    assert ga._same_unit_or_none("Apt. 4B", "4b")
    assert not ga._same_unit_or_none("UNIT 13", "14")
    assert not ga._same_unit_or_none("UNIT 01", "1")
    assert ga._same_unit_or_none(None, "13")
