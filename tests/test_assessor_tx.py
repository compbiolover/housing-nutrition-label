#!/usr/bin/env python3
"""The Texas adapter — twelve appraisal districts, twelve schemas, one set of rules.

Nothing here touches the network. Each county's service is stubbed with row shapes
recorded from it live (2026-10-03 for the first seven counties, 2026-10-04 for
Collin, Denton, El Paso, Williamson and Cameron), for the reason every adapter
test file gives:
an adapter fails open on purpose, so a renamed column or a broken match reads as
"this county has no record here" and would never announce itself.

The shared parts — choosing which parcel an address means, comparing addresses,
bounding the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``. What is pinned here is Texas's own:

1. **The Comptroller's state code** is how a row says whether anyone lives there,
   and category A holds houses AND condominiums, so only an explicit
   single-family code is "one home".
2. **Stacks**: a condominium is many unit rows on one footprint (Harris), or many
   unit rows on the complex's polygon (Dallas). Rows must agree, or the answer is
   refused; a unit's floor area is never the home's.
3. **Shared addresses**: one street address on two accounts (Fort Bend's farm and
   the homesite cut out of it), which containment alone cannot see.
4. **Personal-property accounts** filed on a house's polygon (Dallas BPP, TAD L1).
5. **Spellings**: Harris's comma-joined building lists, Bexar's literal 'NULL',
   Tarrant's "TR" for Trail, Travis's directional written before the number,
   WCAD's written after the street type, Collin's line break before the city,
   El Paso's and Cameron's addresses in parts.
6. **Codes that are local**: CCAD's M4/M5 common areas, Denton's comma-joined
   code lists.
7. **Williamson's two Socrata hops**: parcels, then improvements by property id,
   with ArcGIS-shaped point, circle and same-number queries.

This file alone: ``pytest tests/test_assessor_tx.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, base, tx

HARRIS, FORT_BEND, MONTGOMERY = "48201", "48157", "48339"
DALLAS, TARRANT, BEXAR, TRAVIS = "48113", "48439", "48029", "48453"
COLLIN, DENTON, EL_PASO, WILLIAMSON, CAMERON = "48085", "48121", "48141", "48491", "48061"

# ── rows recorded live ──────────────────────────────────────────────────────────

# Harris (City of Houston "Current HCAD Parcels"). A house: one building.
_HARRIS_HOUSE = {"PARCEL_ID": "1955020050280", "ADDRESS": "6902 PASO DEL SOL DR",
                 "TAX_YEAR": "2025", "STATECLASS": "A1", "YEAR_BUILT": "1979",
                 "IMPR_SQ_FT": "1374", "BLDTYPE_DS": "Residential Single Family",
                 "BUILDCOUNT": 1}
# Two units of the 115-unit stack at 2200 Willowick Rd: HCAD's condominium class
# Z5, the unit written bare after the street type, the tower's year on each.
_WILLOWICK_16J = {"PARCEL_ID": "1115940000007", "ADDRESS": "2200 WILLOWICK RD 16J",
                  "TAX_YEAR": "2025", "STATECLASS": "Z5", "YEAR_BUILT": "1963",
                  "IMPR_SQ_FT": "2429", "BLDTYPE_DS": "Residential Condo",
                  "BUILDCOUNT": 1}
_WILLOWICK_16H = dict(_WILLOWICK_16J, PARCEL_ID="1115940000006",
                      ADDRESS="2200 WILLOWICK RD 16H", IMPR_SQ_FT="2152")
_WILLOWICK_16F = dict(_WILLOWICK_16J, PARCEL_ID="1115940000005",
                      ADDRESS="2200 WILLOWICK RD 16F", IMPR_SQ_FT="1433")
# The River Oaks Country Club parcel: every building in one comma-joined row.
_CLUB = {"PARCEL_ID": "0410170040004", "ADDRESS": "1600 RIVER OAKS BLVD",
         "TAX_YEAR": "2025", "STATECLASS": "F1",
         "YEAR_BUILT": "1968,2004,2007,2008,2014,2016",
         "IMPR_SQ_FT": "101484,10500,1480,19880", "BLDTYPE_DS": "Club House,Health Spa",
         "BUILDCOUNT": 12}
# Rienzi, 1406 Kirby Dr: a 1953 house, now a museum, totally exempt (X2).
_RIENZI = {"PARCEL_ID": "0601510000001", "ADDRESS": "1406 KIRBY DR", "TAX_YEAR": "2025",
           "STATECLASS": "X2", "YEAR_BUILT": "1953", "IMPR_SQ_FT": "11889",
           "BLDTYPE_DS": "Residential Single Family", "BUILDCOUNT": 1}

# Fort Bend (FBCAD's own public parcel layer).
_FB_HOUSE = {"propnumber": "5910-05-025-1300-907", "quickrefid": "R100169",
             "situs": "2027 Fall Meadow DR, Missouri City, TX  77459", "situsapt": None,
             "yearbuilt": 2017, "totsqftlvg": 2525, "building_sptb_code": "A1",
             "land_state_code": "A1"}
# 16417 Hubenak Rd, Needville: an 86-acre farm (1930 farmhouse) and the 1-acre
# homesite cut out of it (a 1984 house) — two accounts, one street address.
_FB_FARM = {"propnumber": "0033-00-000-4810-906", "quickrefid": "R33370",
            "situs": "16417 Hubenak RD, Needville, TX  77461", "situsapt": None,
            "yearbuilt": 1930, "totsqftlvg": 2938, "building_sptb_code": "E1",
            "land_state_code": "D3"}
_FB_HOMESITE = {"propnumber": "0033-00-000-4811-906", "quickrefid": "R33371",
                "situs": "16417 Hubenak RD, Needville, TX  77461", "situsapt": None,
                "yearbuilt": 1984, "totsqftlvg": 1691, "building_sptb_code": "A1",
                "land_state_code": "A1"}
# 2710 Grants Lake Blvd, Sugar Land: unit M1 beside two unit-less records.
_FB_M1 = {"propnumber": "x", "quickrefid": "R66916",
          "situs": "2710 Grants Lake BLVD #M1, Sugar Land, TX  77479", "situsapt": "M1",
          "yearbuilt": 1984, "totsqftlvg": 906, "building_sptb_code": "A3",
          "land_state_code": "A3"}
_FB_MASTER_1 = {"propnumber": "y", "quickrefid": "R167598",
                "situs": "2710 Grants Lake BLVD, Sugar Land, TX  77479", "situsapt": None,
                "yearbuilt": None, "totsqftlvg": None, "building_sptb_code": None,
                "land_state_code": "F1"}
_FB_MASTER_2 = dict(_FB_MASTER_1, quickrefid="R251713")

# Montgomery (City of Houston "Current MCAD Parcels"): an A1 house with a total
# exemption flag, and a mobile home whose year is the county's 0.
_MC_HOUSE = {"PARCEL_ID": 145360, "ADDRESS": "20396 RUSSELL DR, PORTER TX 77365",
             "TAX_YEAR": 2026, "STATECLASS": "A1XV", "YEAR_BUILT": 1967,
             "IMPR_SQ_FT": 1814}
_MC_MOBILE = {"PARCEL_ID": 37228, "ADDRESS": "97 WHITE SANDS DR, KINGWOOD TX 77339",
              "TAX_YEAR": 2026, "STATECLASS": "A2", "YEAR_BUILT": 0, "IMPR_SQ_FT": 1200}

# Dallas (DCAD ParcelQuery). The Aldredge House, 5500 Swiss Ave, built 1917.
_ALDREDGE = {"PARCELID": "00000181756000000", "SITEADDRESS": "5500 SWISS AVE",
             "UNIT": "", "CLASSCD": "1", "RESYRBLT": 1917.0, "RESFLRAREA": 7255.0,
             "RESSTRTYP": "TWO STORIES", "REVALYR": 2025}
# A commercial personal-property account filed on the same polygon and address.
_ALDREDGE_BPP = {"PARCELID": "99830030000099600", "SITEADDRESS": "5500 SWISS AVE",
                 "UNIT": "", "CLASSCD": "31", "RESYRBLT": None, "RESFLRAREA": None,
                 "RESSTRTYP": None, "REVALYR": 2026}
# Four units of the condominium at 6108 Abrams Rd, on the complex's polygon, which
# do NOT agree on a year.
_ABRAMS = [{"PARCELID": f"00C66800000{b}00{u}", "SITEADDRESS": "6108 ABRAMS RD",
            "UNIT": f"{u}  ", "CLASSCD": "3", "RESYRBLT": y, "RESFLRAREA": 600.0,
            "RESSTRTYP": "ONE STORY", "REVALYR": 2026}
           for b, u, y in (("D", "419", 1984.0), ("B", "218", 2021.0),
                           ("E", "504", 2019.0), ("A", "108", 2005.0))]

# Tarrant (TAD ParcelView): space-padded strings, "TR" for Trail.
_CONCHO = {"TAXPIN": "34557-21-8", "Situs_Addr": "2828 CONCHO TR",
           "Property_C": "A1", "Year_Built": "2000", "Living_Are": "   1728",
           "Appraisal_": "2025"}
_HARDNOSE_BPP = {"TAXPIN": "44033H-10-25", "Situs_Addr": "7033 HARDNOSE LN",
                 "Property_C": "L1", "Year_Built": "   0", "Living_Are": "      0",
                 "Appraisal_": "2025"}
_HARDNOSE = {"TAXPIN": "44033H-10-24", "Situs_Addr": "7033 HARDNOSE LN",
             "Property_C": "A1", "Year_Built": "2004", "Living_Are": "   2402",
             "Appraisal_": "2025"}

# Bexar (county parcel layer). The Steves Homestead, 509 King William, 1876: three
# houses on the parcel, the street type missing from the roll's address.
_STEVES = {"PropID": 108482.0, "Situs": "509 KING WILLIAM ", "YrBlt": "1876",
           "GBA": "7442", "TOT_GBA": "7442", "Stories": "2.5", "State_cd": "A1",
           "Houses": "3"}
_BEXAR_HOUSE = {"PropID": 467500.0, "Situs": "7819 SHETLAND DR ", "YrBlt": "2004",
                "GBA": "1560", "TOT_GBA": "1560", "Stories": "1", "State_cd": "A1",
                "Houses": "1"}

# Travis (county tax maps): the directional before the number, city optional.
_SMOOT = {"PROP_ID": 455147, "situs_address": "W 1316 6 ST   TX 78701",
          "F1year_imprv": 1887, "land_state_cd": "A1"}
_NEILL_COCHRAN = {"PROP_ID": 112425, "situs_address": "  2310 SAN GABRIEL ST   TX 78705",
                  "F1year_imprv": 1855, "land_state_cd": "F5"}
_BAY_HILL = {"PROP_ID": 1, "situs_address": "  1707 BAY HILL DR AUSTIN TX 78746",
             "F1year_imprv": 1990, "land_state_cd": "A1"}

#: A point. Which parcel a coordinate lands in is decided by the stubbed rows.
_POINT = (29.75, -95.43)


def _lookup(county, exact, near=(), twin=None, address=None, slices=None,
            params=None, urls=None):
    """Drive ``tx.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` is what the point lands inside, ``near`` what the 80 m buffer finds,
    ``twin`` what the same-house-number search finds (by default, everything the
    other two found — it is the widest net). ``slices``, ``params`` and ``urls``
    collect what each request was handed.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls
    twin = list(exact) + list(near) if twin is None else twin

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(dict(request))
        urls.append(url)
        if request.get("where"):
            rows = twin
        elif request.get("distance"):
            rows = near
        else:
            rows = exact
        return {"features": [{"attributes": dict(a)} for a in rows]}

    tx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return tx.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        tx._lookup_cached.cache_clear()


# ── the ordinary answer, county by county ──────────────────────────────────────


def test_a_harris_house_reports_its_year_area_and_roll():
    got = _lookup(HARRIS, [_HARRIS_HOUSE], address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("1955020050280", 1979, 1374.0)
    assert "HCAD 2025" in got.data_vintage and "City of Houston" in got.data_vintage


def test_a_fort_bend_house_reports_its_year_and_living_area():
    got = _lookup(FORT_BEND, [_FB_HOUSE],
                  address="2027 FALL MEADOW DR, MISSOURI CITY, TX, 77459")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("R100169", 2017, 2525.0)


def test_a_dallas_house_reports_its_year_area_and_stories():
    got = _lookup(DALLAS, [_ALDREDGE], address="5500 SWISS AVE, DALLAS, TX, 75214")
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1917, 7255.0, 2)
    assert "last revalued 2025" in got.data_vintage


def test_a_bexar_house_reports_its_area_and_whole_stories():
    got = _lookup(BEXAR, [_BEXAR_HOUSE], address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft, got.stories) == ("467500", 2004, 1560.0, 1)


def test_each_record_names_its_own_county_source():
    got = _lookup(TARRANT, [_CONCHO], address="2828 CONCHO TRL, FORT WORTH, TX, 76118")
    assert got is not None and "Tarrant Appraisal District" in got.source
    assert "TAD 2025" in got.data_vintage


# ── category A is houses AND condominiums ──────────────────────────────────────


def test_a_condominium_stack_that_agrees_answers_with_the_year_alone():
    """115 unit rows on one footprint, every one built 1963. Refusing them all as
    ambiguous would leave every condominium in Houston unanswered; picking one unit
    would be a guess. The rows agree on the building's year, so the year is
    reported — and nothing a unit owns: no floor area, no stories, no parcel id."""
    got = _lookup(HARRIS, [_WILLOWICK_16J, _WILLOWICK_16H, _WILLOWICK_16F],
                  address="2200 WILLOWICK RD, HOUSTON, TX, 77027")
    assert got is not None
    assert got.year_built == 1963
    assert got.sqft is None and got.stories is None
    assert got.parcel_id is None, "no single unit is the answer"


def test_a_stack_that_disagrees_is_refused():
    """6108 Abrams Rd, Dallas: units of 1984, 2021, 2019 and 2005 on one polygon.
    Any one of them would be an arbitrary row."""
    assert _lookup(DALLAS, _ABRAMS, address="6108 ABRAMS RD, DALLAS, TX, 75231") is None


def test_a_typed_unit_picks_its_own_row_and_still_gets_no_floor_area():
    """The reader's "#16J" selects the 16J row (written bare, "RD 16J", in HCAD's
    address). The year is the tower's; the area is the unit's share of nothing the
    label means by "the home", so it is still refused."""
    got = _lookup(HARRIS, [_WILLOWICK_16J, _WILLOWICK_16H],
                  address="2200 WILLOWICK RD #16J, HOUSTON, TX, 77027")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("1115940000007", 1963, None)


def test_a_typed_unit_sets_aside_the_records_that_name_no_unit():
    got = _lookup(FORT_BEND, [], near=[_FB_M1, _FB_MASTER_1, _FB_MASTER_2],
                  address="2710 GRANTS LAKE BLVD #M1, SUGAR LAND, TX, 77479")
    assert got is not None and got.parcel_id == "R66916" and got.year_built == 1984
    assert got.sqft is None, "an A3 unit is not one house"


def test_only_an_explicit_single_family_code_is_one_home():
    """Rienzi is a house by type and X2 (totally exempt) by class. Exempt is not a
    statement that no one lives there — 100% disabled veterans' homesteads are
    exempt — so the year stands; nor is it one-home evidence, so the area does not."""
    got = _lookup(HARRIS, [_RIENZI], address="1406 KIRBY DR, HOUSTON, TX, 77019")
    assert got is not None and got.year_built == 1953 and got.sqft is None


def test_a_harris_parcel_with_several_buildings_gives_no_area():
    two = dict(_HARRIS_HOUSE, BUILDCOUNT=2)
    got = _lookup(HARRIS, [two], address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None and got.year_built == 1979 and got.sqft is None


def test_harris_comma_lists_are_never_one_year_or_one_area():
    assert tx._year("1968,2004,2007") is None
    assert tx._year("1979,1979") == 1979, "buildings that agree do give the year"
    assert tx._area("101484,10500") is None
    assert _lookup(HARRIS, [_CLUB], address="1600 RIVER OAKS BLVD, HOUSTON, TX, 77019") is None


def test_bexar_needs_one_house_for_floor_area():
    """The Steves Homestead: A1, but three houses on the parcel. The year is the
    homestead's; the area is not one home's."""
    got = _lookup(BEXAR, [_STEVES], address="509 KING WILLIAM ST, SAN ANTONIO, TX, 78204")
    assert got is not None and got.year_built == 1876
    assert got.sqft is None and got.stories is None


def test_bexar_main_building_area_must_be_the_whole():
    got = _lookup(BEXAR, [dict(_BEXAR_HOUSE, TOT_GBA="2160")],
                  address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is not None and got.sqft is None


def test_montgomerys_exemption_flag_does_not_hide_the_house():
    got = _lookup(MONTGOMERY, [_MC_HOUSE], address="20396 RUSSELL DR, PORTER, TX, 77365")
    assert got is not None and got.year_built == 1967 and got.sqft == 1814.0
    assert tx._state_code("A1XV") == "A1" and tx._state_code("C1XV") == "C1"
    assert tx._state_code("XV") == "XV", "a bare exempt code stays exempt"
    assert tx._state_code("1D1") == "D1", "Harris writes open-space land 1D1"
    assert tx._reading(tx._state_code("1D1"), frozenset()) == tx.NOT_A_HOME
    assert tx._state_code("A1              ") == "A1", "Tarrant pads its codes"


# ── a year has to belong to somebody's home ────────────────────────────────────


def test_a_commercial_class_reports_nothing():
    """The Neill-Cochran House (1855) is filed F5, a commercial residence
    conversion: a museum. A year from a commercial record is not a home's year."""
    assert _lookup(TRAVIS, [_NEILL_COCHRAN],
                   address="2310 SAN GABRIEL ST, AUSTIN, TX, 78705") is None


def test_bexar_zero_houses_is_zero_dwellings():
    got = _lookup(BEXAR, [dict(_BEXAR_HOUSE, Houses="0")],
                  address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is None


def test_bexar_zero_houses_on_multifamily_is_not_a_refusal():
    """An apartment complex writes 0 houses — its buildings are not houses."""
    apt = dict(_BEXAR_HOUSE, State_cd="B2", Houses="0", GBA="193243", TOT_GBA="193243")
    got = _lookup(BEXAR, [apt], address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is not None and got.year_built == 2004 and got.sqft is None


def test_silence_about_the_class_is_not_a_refusal():
    got = _lookup(BEXAR, [dict(_BEXAR_HOUSE, State_cd="NULL", Houses=None)],
                  address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is not None and got.year_built == 2004 and got.sqft is None


def test_dallas_class_codes_are_dcads_own():
    """DCAD's CLASSCD is its own numbering, not the Comptroller's: "7" is SFR
    vacant lots, and an unknown code is read as a refusal, never as a house."""
    lot = dict(_ALDREDGE, CLASSCD="7")
    assert _lookup(DALLAS, [lot], address="5500 SWISS AVE, DALLAS, TX, 75214") is None
    duplex = dict(_ALDREDGE, CLASSCD="6")
    got = _lookup(DALLAS, [duplex], address="5500 SWISS AVE, DALLAS, TX, 75214")
    assert got is not None and got.year_built == 1917 and got.sqft is None


# ── years ──────────────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup(MONTGOMERY, [_MC_MOBILE], address="97 WHITE SANDS DR, KINGWOOD, TX, 77339")
    assert got is not None and got.year_built is None and got.sqft == 1200.0


def test_bexars_literal_null_is_not_a_year():
    assert tx._year("NULL") is None
    got = _lookup(BEXAR, [dict(_BEXAR_HOUSE, YrBlt="NULL")],
                  address="7819 SHETLAND DR, SAN ANTONIO, TX, 78250")
    assert got is not None and got.year_built is None and got.sqft == 1560.0


def test_implausible_years_are_dropped():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert tx._year(2502.0) is None, "recorded live in DCAD"
    assert tx._year("210") is None, "recorded live in Bexar"
    assert tx._year(EARLIEST_PLAUSIBLE_YEAR - 1) is None
    assert tx._year(EARLIEST_PLAUSIBLE_YEAR) == EARLIEST_PLAUSIBLE_YEAR
    assert tx._year("   0") is None and tx._year("") is None and tx._year(None) is None


def test_half_stories_have_no_whole_number():
    assert tx._stories("ONE AND ONE HALF STORIES") is None
    assert tx._stories("1.5") is None and tx._stories("2.5") is None
    assert tx._stories("1970") is None, "recorded live in Bexar's Stories column"
    assert tx._stories("TWO STORIES") == 2 and tx._stories("1") == 1


# ── records of nothing ─────────────────────────────────────────────────────────


def test_a_personal_property_account_does_not_make_the_house_ambiguous():
    """DCAD files 80,394 business-personal-property accounts on the polygon, and
    under the address, of the parcel they sit in. Counted as a rival, one would
    turn a single house into an ambiguous pair."""
    got = _lookup(DALLAS, [_ALDREDGE, _ALDREDGE_BPP], address="5500 SWISS AVE, DALLAS, TX, 75214")
    assert got is not None and got.year_built == 1917


def test_tads_l1_accounts_are_dropped_the_same_way():
    got = _lookup(TARRANT, [_HARDNOSE, _HARDNOSE_BPP],
                  address="7033 HARDNOSE LN, FORT WORTH, TX, 76135")
    assert got is not None and got.year_built == 2004


def test_rows_with_no_identifier_are_dropped():
    blank = dict(_HARRIS_HOUSE, PARCEL_ID="  ")
    got = _lookup(HARRIS, [blank, _HARRIS_HOUSE],
                  address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None and got.parcel_id == "1955020050280"


def test_a_row_repeated_verbatim_is_one_row():
    got = _lookup(HARRIS, [_HARRIS_HOUSE, dict(_HARRIS_HOUSE)],
                  address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None and got.sqft == 1374.0


def test_nothing_reportable_is_no_answer_through_the_registry():
    """Checked through ``assessor_for_point``, the door the label uses. Texas is
    registered by the orchestrator, so the route is added here for the test."""
    empty = dict(_HARRIS_HOUSE, YEAR_BUILT="0", IMPR_SQ_FT="0")

    def fake(url, params, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    tx._lookup_cached.cache_clear()
    saved_get, saved_env = _shared.get_json, os.environ.get(A.ENABLE_ENV)
    saved_route = A.ADAPTERS.get(HARRIS)
    _shared.get_json, os.environ[A.ENABLE_ENV] = fake, "1"
    A.ADAPTERS[HARRIS] = tx
    try:
        assert A.assessor_for_point(*_POINT, HARRIS) is None
    finally:
        _shared.get_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        if saved_route is None:
            A.ADAPTERS.pop(HARRIS, None)
        else:
            A.ADAPTERS[HARRIS] = saved_route
        tx._lookup_cached.cache_clear()


# ── the shared address ─────────────────────────────────────────────────────────


def test_an_address_two_accounts_share_is_refused_even_under_containment():
    """Recorded live: the point lands inside the farm, whose address matches, so
    containment alone names the 1930 farmhouse. The 1984 homesite carrying the same
    address is more than 80 m away and only the same-number search sees it."""
    got = _lookup(FORT_BEND, [_FB_FARM], near=[_FB_FARM],
                  twin=[_FB_FARM, _FB_HOMESITE],
                  address="16417 HUBENAK RD, NEEDVILLE, TX, 77461")
    assert got is None


def test_twins_that_agree_answer_with_the_year_and_no_area():
    twin = dict(_HARRIS_HOUSE, PARCEL_ID="1955020050281")
    got = _lookup(HARRIS, [_HARRIS_HOUSE], near=[_HARRIS_HOUSE],
                  twin=[_HARRIS_HOUSE, twin],
                  address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None and got.year_built == 1979
    assert got.sqft is None and got.parcel_id is None


def test_a_search_that_cannot_find_the_chosen_parcel_is_not_evidence():
    got = _lookup(HARRIS, [_HARRIS_HOUSE], twin=[],
                  address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is None


def test_the_same_number_search_asks_for_digits_only_in_the_address_column():
    params = []
    _lookup(TRAVIS, [_SMOOT], address="1316 W 6TH ST, AUSTIN, TX, 78703", params=params)
    wheres = [p["where"] for p in params if p.get("where")]
    assert wheres == ["situs_address LIKE '1316 %' OR situs_address LIKE '% 1316 %'"]
    twin = [p for p in params if p.get("where")][0]
    assert twin["distance"] == str(tx.TWIN_RADIUS_M)


def test_without_an_address_containment_alone_answers_and_no_search_is_made():
    params = []
    got = _lookup(HARRIS, [_HARRIS_HOUSE], params=params)
    assert got is not None and got.year_built == 1979
    assert not any(p.get("where") for p in params)


def test_an_off_parcel_geocode_is_confirmed_in_the_buffer():
    got = _lookup(DALLAS, [], near=[_ALDREDGE, dict(_ALDREDGE, PARCELID="2",
                                                    SITEADDRESS="5504 SWISS AVE")],
                  address="5500 SWISS AVE, DALLAS, TX, 75214")
    assert got is not None and got.parcel_id == "00000181756000000"


def test_two_different_parcels_under_the_point_are_ambiguous():
    other = dict(_ALDREDGE, PARCELID="2", SITEADDRESS="5504 SWISS AVE")
    assert _lookup(DALLAS, [_ALDREDGE, other], address="5500 SWISS AVE, DALLAS, TX, 75214") is None


# ── source spellings ───────────────────────────────────────────────────────────


def test_tads_tr_is_trail():
    """TAD writes "2828 CONCHO TR" where the Census matcher writes "TRL". Shared
    code leaves TR alone because elsewhere it can mean Terrace; TAD spells Terrace
    TERR, so in this roll TR is only Trail."""
    assert tx._tarrant_address("2828 CONCHO TR   ") == "2828 CONCHO TRL"
    assert tx._tarrant_address("1509 CARSWELL TERR") == "1509 CARSWELL TERR"
    got = _lookup(TARRANT, [_CONCHO], address="2828 CONCHO TRL, FORT WORTH, TX, 76118")
    assert got is not None and got.year_built == 2000 and got.sqft == 1728.0
    assert not _shared.same_address("2828 CONCHO TR", "2828 CONCHO TRL"), (
        "the shared table must not have learned TR; if it has, drop the local fix")


def test_travis_addresses_are_rebuilt():
    assert tx._travis_address("W 1316 6 ST   TX 78701") == "1316 W 6 ST"
    assert tx._travis_address("  1707 BAY HILL DR AUSTIN TX 78746") == "1707 BAY HILL DR"
    assert tx._travis_address("  13802 LOTHIAN DR PFLUGERVILLE TX 78660") == "13802 LOTHIAN DR"
    assert tx._travis_address("  100 AUSTIN   TX 78701") == "100 AUSTIN", (
        "a street named after the city keeps its name")
    got = _lookup(TRAVIS, [_SMOOT], address="1316 W 6TH ST, AUSTIN, TX, 78703")
    assert got is not None and got.year_built == 1887 and got.sqft is None


def test_an_unknown_travis_city_is_a_refusal_not_a_match():
    odd = dict(_BAY_HILL, situs_address="  1707 BAY HILL DR NOWHERESVILLE TX 78746")
    assert _lookup(TRAVIS, [odd], address="1707 BAY HILL DR, AUSTIN, TX, 78746") is None


def test_houston_column_names_arrive_in_another_case():
    """The Houston services answer ``Year_Built`` for the column their own metadata
    spells ``YEAR_BUILT``. Read case-sensitively, every Fort Bend year was lost."""
    row = {k.lower() if k != "YEAR_BUILT" else "Year_Built": v for k, v in _HARRIS_HOUSE.items()}
    got = _lookup(HARRIS, [row], address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert got is not None and got.year_built == 1979


def test_the_unmarked_unit_is_named():
    assert tx._unmarked_unit("829 YALE ST 504") == "504"
    assert tx._unmarked_unit("2200 WILLOWICK RD 16J") == "16j"
    assert tx._unmarked_unit("100 ROUTE 66") is None


# ── what is requested ──────────────────────────────────────────────────────────

_PRIVATE = ("OWNER", "OWNER_ADD", "OWNERNME1", "PSTLADDRESS", "ownername", "oaddr1",
            # Collin (Allen), Denton, El Paso, Cameron, Williamson
            "GIS_DBO_AD_Entity_file_as_name", "GIS_DBO_AD_Entity_addr_line1",
            "GIS_DBO_AD_Entity_deed_dt", "GIS_DBO_AD_Entity_cert_market", "name",
            "addrDeliveryLine", "ownerMarketValue", "deedDt", "FILE_AS_NA", "ADDR_LINE2",
            "X022_APPRA", "market", "ownernme1", "pstladdres", "cntassdval",
            "py_owner_name", "Owner", "AddrLn1", "Owner_Name", "deed_date", "deeddate",
            "APP_VALUE", "MARKET_VAL", "CNTASSDVAL", "market_value", "TotVal",
            "Total_Valu", "LEGALDSCR1", "legal_desc", "*")


def test_the_field_lists_are_explicit_and_carry_nothing_private():
    for fips, county in tx.COUNTIES.items():
        fields = county.fields.split(",")
        for private in _PRIVATE:
            assert private not in fields, (fips, private)
        assert all(f.strip() == f and f for f in fields), fips


def test_the_effective_and_remodel_years_are_not_requested():
    for county in tx.COUNTIES.values():
        lower = county.fields.lower()
        assert "remodel" not in lower and "eff" not in lower


def test_the_requested_fields_are_what_reaches_the_service():
    for fips, rows, address in ((HARRIS, [_HARRIS_HOUSE], None),
                                (TARRANT, [_CONCHO], None), (BEXAR, [_STEVES], None)):
        params, urls = [], []
        _lookup(fips, rows, address=address, params=params, urls=urls)
        assert params and all(p["outFields"] == tx.COUNTIES[fips].fields for p in params)
        assert all(u == tx.COUNTIES[fips].url for u in urls)


def test_the_statewide_stratmap_layer_is_not_used():
    """Its query operation is disabled and identify returns owner names and
    mailing addresses with no way to leave them out; see the module docstring."""
    for county in tx.COUNTIES.values():
        assert "geographic.texas.gov" not in county.url
        assert "tnris" not in county.url


def test_no_wall_foundation_or_condition_is_ever_reported():
    got = _lookup(DALLAS, [_ALDREDGE], address="5500 SWISS AVE, DALLAS, TX, 75214")
    assert got is not None
    assert (got.construction, got.foundation, got.condition) == (None, None, None)
    assert set(got.fields()) <= {"year_built", "sqft", "stories"}
    assert base.AssessorRecord(source="x", data_vintage="y", sqft=1.0).fields()


# ── the county list ────────────────────────────────────────────────────────────


def test_every_claimed_county_is_a_texas_county_in_the_repos_table():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        texas = {r["geoid"] for r in csv.DictReader(fh)
                 if r["geoid"].startswith("48") and len(r["geoid"]) == 5}
    # 253 of Texas's 254: Loving County (48301, a few dozen homes) has no row in
    # this table, which is a fact about the table, not about this adapter.
    assert len(texas) >= 253, f"expected Texas's counties, got {len(texas)}"
    assert tx.COUNTY_FIPS <= texas
    assert tx.COUNTY_FIPS == {HARRIS, FORT_BEND, MONTGOMERY, DALLAS, TARRANT, BEXAR, TRAVIS,
                              COLLIN, DENTON, EL_PASO, WILLIAMSON, CAMERON}


def test_the_callers_county_picks_the_service():
    urls = []
    _lookup(BEXAR, [_STEVES], urls=urls)
    assert urls and set(urls) == {tx.BEXAR_URL}


def test_without_a_county_there_is_no_guess():
    calls = []
    assert _lookup(None, [_HARRIS_HOUSE], urls=calls) is None
    assert _lookup("48215", [_HARRIS_HOUSE], urls=calls) is None, "Hidalgo: not covered"
    assert not calls, "no service is asked when the county is not one of ours"


def test_a_county_given_unpadded_is_still_found():
    got = _lookup(int(HARRIS), [_HARRIS_HOUSE])
    assert got is not None


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_request_passes_the_modules_read_slice():
    slices = []
    _lookup(HARRIS, [], near=[_HARRIS_HOUSE], slices=slices,
            address="6902 PASO DEL SOL DR, HOUSTON, TX, 77083")
    assert len(slices) == 3, "containment, buffer and the same-number search"
    assert all(s == tx.READ_SLICE_S for s in slices)


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert tx.LOOKUP_TIMEOUT + tx.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_every_request_shares_one_clock_started_once():
    seen = []

    def note(url, params, deadline, read_slice=None):
        seen.append(deadline)
        if params.get("where") or params.get("distance"):
            return {"features": [{"attributes": _HARRIS_HOUSE}]}
        return {"features": []}

    tx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        tx.lookup(*_POINT, "6902 PASO DEL SOL DR, HOUSTON, TX, 77083", HARRIS)
    finally:
        _shared.get_json = saved
        tx._lookup_cached.cache_clear()
    assert len(seen) == 3 and len(set(seen)) == 1, "each request was handed its own budget"
    assert abs((seen[0] - started) - tx.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, params, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    tx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert tx.lookup(*_POINT, "6902 PASO DEL SOL DR, HOUSTON, TX, 77083", HARRIS) is None
    finally:
        _shared.get_json = saved
        tx._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer():
    def truncated(url, params, deadline, read_slice=None):
        raise _shared.TruncatedResponse("cut at the transfer limit")

    tx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = truncated
    try:
        assert tx.lookup(*_POINT, None, HARRIS) is None
    finally:
        _shared.get_json = saved
        tx._lookup_cached.cache_clear()


def test_garbage_coordinates_fail_open():
    assert tx.lookup("not a number", None, None, HARRIS) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup(HARRIS, []) is None


# ══ the counties added second: Collin, Denton, El Paso, Cameron, Williamson ═══
#
# Rows recorded live 2026-10-04. Four are ArcGIS layers read through the same
# path as the first seven; Williamson is two Socrata datasets joined on the
# property id, stubbed by URL below.

_C = "GIS_DBO_AD_Entity_"


def _collin(**kw):
    """A row of the City of Allen's "CCAD Tax Parcels", its columns prefixed."""
    row = {"prop_id": 82, "situs_display": "6304 PIPER ST \r\nPLANO, TX 75093",
           "state_cd": "A1", "yr_blt": 2008, "living_area": 4687.0, "stories": 2,
           "curr_val_yr": 2027, "property_stat": "InProgress"}
    row.update(kw)
    return {_C + k: v for k, v in row.items()}


_PIPER = _collin()
# A condominium unit (CCAD A3), the unit written bare after the street type.
_WINDFLOWER_107 = _collin(prop_id=15659, situs_display="17905 WINDFLOWER WAY 107\r\nDALLAS, TX 75252",
                          state_cd="A3", yr_blt=1985, living_area=1934.0, stories=1)
# A subdivision's security office, filed M4 with a year and a floor area.
_OLD_POND = _collin(prop_id=20636, situs_display="4549 OLD POND DR \r\nPLANO, TX 75024",
                    state_cd="M4", yr_blt=1988, living_area=2045.0, stories=1)
# A townhome (CCAD A4).
_EARLSHIRE = _collin(prop_id=279264, situs_display="1445 EARLSHIRE PL \r\nPLANO, TX 75075",
                     state_cd="A4", yr_blt=1979, living_area=1748.0, stories=1)

# Denton (Denton County's copy of the Denton CAD roll).
_FOX_SEDGE = {"pid": 256876, "pYear": 2027, "stateCodes": "A1",
              "situs_street_address": "4708 FOX SEDGE LN", "imprvActualYearBuilt": 2005,
              "imprvMainArea": 2897.0}
_SEABORN = {"pid": 254152, "pYear": 2027, "stateCodes": "A1,D1,E1",
            "situs_street_address": "1862 SEABORN RD", "imprvActualYearBuilt": 1966,
            "imprvMainArea": 1536.0}
_CLUB_RIDGE = {"pid": 307851, "pYear": 2027, "stateCodes": "A4",
               "situs_street_address": "2700 CLUB RIDGE DR", "imprvActualYearBuilt": 2008,
               "imprvMainArea": 1750.0}

# El Paso (the City of El Paso's copy of the EPCAD roll): the address in parts.
_VILLANOVA = {"PROP_ID": 73700.0, "PROP_VAL_Y": 2026.0, "STATE_CD": "A1", "SITUS_NUM": "8424",
              "SITUS_STRE": "VILLANOVA", "SITUS_DIR": "DR", "SITUS_UNIT": " ", "YR_BLT": 1982.0}
_GEORGIA = {"PROP_ID": 168499.0, "PROP_VAL_Y": 2026.0, "STATE_CD": "XV-R", "SITUS_NUM": "809",
            "SITUS_STRE": "GEORGIA", "SITUS_DIR": " ", "SITUS_UNIT": " ", "YR_BLT": 1988.0}
# Two accounts at 721 La Mesa Ave, Canutillo, both A1, both 1982.
_LA_MESA = [{"PROP_ID": pid, "PROP_VAL_Y": 2026.0, "STATE_CD": "A1", "SITUS_NUM": "721",
             "SITUS_STRE": "LA MESA", "SITUS_DIR": "AVE", "SITUS_UNIT": " ", "YR_BLT": 1982.0}
            for pid in (58933.0, 351824.0)]

# Cameron (the CAD's 2026 export, hosted by the City of Brownsville).
_PONCIANA = {"prop_id": 402324, "pyear": 2026, "exportdt": "2026-05-31", "statecd": "A",
             "situsno": "24696", "sitpfx": " ", "sitstr": "PONCIANA", "sitsfx": "ST",
             "yrbuilt": 2004}


def test_a_collin_house_reports_year_area_stories_and_an_honest_roll():
    got = _lookup(COLLIN, [_PIPER], address="6304 PIPER ST, PLANO, TX, 75093")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft, got.stories) == ("82", 2008, 4687.0, 2)
    assert "CCAD 2027 appraisal year (in progress)" in got.data_vintage
    assert "City of Allen" in got.data_vintage and "Collin" in got.source


def test_a_collin_townhome_is_one_home():
    """CCAD's certified totals name A4 "RESIDENTIAL TOWNHOMES": one dwelling on its
    own lot, which is how Dallas's SFR - TOWNHOUSES is read too."""
    got = _lookup(COLLIN, [_EARLSHIRE], address="1445 EARLSHIRE PL, PLANO, TX, 75075")
    assert got is not None and (got.year_built, got.sqft) == (1979, 1748.0)


def test_a_collin_condominium_unit_gives_the_year_and_nothing_a_unit_owns():
    got = _lookup(COLLIN, [_WINDFLOWER_107],
                  address="17905 WINDFLOWER WAY #107, DALLAS, TX, 75252")
    assert got is not None and got.year_built == 1985
    assert got.sqft is None and got.stories is None


def test_collins_m4_is_a_common_area_not_a_mobile_home():
    """Elsewhere M is a mobile home; CCAD files subdivisions' common areas M4 and
    M5 — a security office here — and that building's year is no one's home's."""
    assert _lookup(COLLIN, [_OLD_POND], address="4549 OLD POND DR, PLANO, TX, 75024") is None
    assert tx._codes_reading("M3", tx._COLLIN_ONE, tx._COLLIN_CODES) == tx.ONE_HOME


def test_collins_address_stops_at_the_line_break():
    assert tx._first_line("6304 PIPER ST \r\nPLANO, TX 75093") == "6304 PIPER ST"
    assert tx._first_line(None) == ""


def test_a_denton_house_reports_its_main_area():
    got = _lookup(DENTON, [_FOX_SEDGE], address="4708 FOX SEDGE LN, DENTON, TX, 76208")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("256876", 2005, 2897.0)
    assert "Denton CAD" in got.data_vintage and "2027" in got.data_vintage


def test_denton_lists_several_codes_and_several_codes_are_not_one_home():
    """"A1,D1,E1": a house on open-space land with a rural improvement. Which part
    is the home is not stated, so the year stands and the area does not."""
    got = _lookup(DENTON, [_SEABORN], address="1862 SEABORN RD, DENTON, TX, 76226")
    assert got is not None and got.year_built == 1966 and got.sqft is None


def test_denton_codes_without_a_published_meaning_give_the_year_alone():
    got = _lookup(DENTON, [_CLUB_RIDGE], address="2700 CLUB RIDGE DR, LEWISVILLE, TX, 75067")
    assert got is not None and got.year_built == 2008 and got.sqft is None


def test_a_list_of_codes_refuses_only_when_every_code_refuses():
    one = frozenset({"A1"})
    assert tx._codes_reading("A1", one) == tx.ONE_HOME
    assert tx._codes_reading("A1,F1", one) == tx.SILENT
    assert tx._codes_reading("C1,PLAN", one) == tx.SILENT, "an unknown code is silence"
    assert tx._codes_reading("C1,F1", one) == tx.NOT_A_HOME
    assert tx._codes_reading("D1,D2", one) == tx.NOT_A_HOME
    assert tx._codes_reading("", one) == tx.SILENT and tx._codes_reading(None, one) == tx.SILENT


def test_an_el_paso_house_is_rebuilt_from_its_parts_and_gives_the_year():
    got = _lookup(EL_PASO, [_VILLANOVA], address="8424 VILLANOVA DR, EL PASO, TX, 79907")
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft, got.stories) == ("73700", 1982, None, None)
    assert "EPCAD 2026" in got.data_vintage and "City of El Paso" in got.data_vintage


def test_el_pasos_exempt_residence_is_silence_not_refusal():
    got = _lookup(EL_PASO, [_GEORGIA], address="809 GEORGIA, EL PASO, TX, 79902")
    assert got is not None and got.year_built == 1988


def test_el_pasos_same_number_search_asks_the_number_column():
    params = []
    got = _lookup(EL_PASO, _LA_MESA, address="721 LA MESA AVE, CANUTILLO, TX, 79835",
                  params=params)
    wheres = [p["where"] for p in params if p.get("where")]
    assert wheres == ["SITUS_NUM = '721' OR SITUS_NUM LIKE '721 %'"]
    # Two accounts at one address that agree on the year: the year, no parcel id.
    assert got is not None and got.year_built == 1982 and got.parcel_id is None


def test_cameron_gives_the_year_alone_and_drops_its_9999():
    got = _lookup(CAMERON, [_PONCIANA], address="24696 PONCIANA ST, SAN BENITO, TX, 78586")
    assert got is not None and (got.year_built, got.sqft) == (2004, None)
    assert "exported 2026-05-31" in got.data_vintage and "Brownsville" in got.data_vintage
    assert _lookup(CAMERON, [dict(_PONCIANA, yrbuilt=9999)],
                   address="24696 PONCIANA ST, SAN BENITO, TX, 78586") is None


# ── Williamson: two Socrata datasets ───────────────────────────────────────────

_LYDIA = {"parcelid": "R349410", "propertyid": "181845",
          "siteaddress": "2504 LYDIA LN, ROUND ROCK, TX  78665"}
_LYDIA_IMPS = [{"propertyid": "181845", "actyrbuilt": "1996.000000", "sqftcur": "2214.000000",
                "fsptb": "A1", "datadate": "2026-07-27T04:00:01.663"}]
# Two improvement rows on one rural account.
_PARKVIEW = {"parcelid": "R020130", "propertyid": "78745",
             "siteaddress": "11620 PARKVIEW DR, COUPLAND, TX  78615"}
_PARKVIEW_IMPS = [{"propertyid": "78745", "actyrbuilt": "1975.000000", "sqftcur": "1886.000000",
                   "fsptb": "E1", "datadate": "2026-07-27T04:00:01.663"}] * 2
_FIFTH_W = {"parcelid": "R015406", "propertyid": "74060",
            "siteaddress": "726 5TH ST W, TAYLOR, TX  76574"}


def _lookup_wcad(exact, imps, near=(), twin=None, address=None, params=None, urls=None):
    """Drive a Williamson lookup over recorded rows: parcels by the shape of the
    request (a point, a circle, or the same-number search), improvements by id."""
    params = [] if params is None else params
    urls = [] if urls is None else urls
    twin = list(exact) + list(near) if twin is None else twin

    def fake(url, request, deadline, read_slice=None):
        params.append(dict(request))
        urls.append(url)
        where = request["$where"]
        if url == tx.WILLIAMSON_CHARACTERISTICS_URL:
            ids = where.split("(", 1)[1].rstrip(")").split(",")
            return [dict(i) for i in imps if i["propertyid"] in ids]
        rows = twin if "starts_with" in where else near if "POLYGON" in where else exact
        return [dict(r) for r in rows]

    tx._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return tx.lookup(30.5, -97.7, address, WILLIAMSON)
    finally:
        _shared.get_json = saved
        tx._lookup_cached.cache_clear()


def test_a_williamson_house_joins_its_parcel_to_its_improvement():
    params, urls = [], []
    got = _lookup_wcad([_LYDIA], _LYDIA_IMPS, address="2504 LYDIA LN, ROUND ROCK, TX, 78665",
                       params=params, urls=urls)
    assert got is not None
    assert (got.parcel_id, got.year_built, got.sqft) == ("R349410", 1996, 2214.0)
    assert "exported 2026-07-27" in got.data_vintage and "WCAD" in got.data_vintage
    assert set(urls) == {tx.WILLIAMSON_URL, tx.WILLIAMSON_CHARACTERISTICS_URL}
    assert all(p["$limit"] == str(tx._SOCRATA_LIMIT) for p in params)


def test_williamson_asks_for_named_columns_only():
    """The characteristics dataset carries market values and deed dates, the
    parcels dataset owner names and mailing addresses; neither is asked for."""
    params = []
    _lookup_wcad([_LYDIA], _LYDIA_IMPS, address="2504 LYDIA LN, ROUND ROCK, TX, 78665",
                 params=params)
    selects = {p["$select"] for p in params}
    assert selects == {tx.COUNTIES[WILLIAMSON].fields, tx._WILLIAMSON_IMPROVEMENT_FIELDS}
    for select in selects:
        for private in ("ownernme1", "pstladdres", "totalmktcur", "deeddate", "cntassdval", "*"):
            assert private not in select.split(",")


def test_two_improvements_give_the_year_they_agree_on_and_no_area():
    got = _lookup_wcad([_PARKVIEW], _PARKVIEW_IMPS,
                       address="11620 PARKVIEW DR, COUPLAND, TX, 78615")
    assert got is not None and got.year_built == 1975 and got.sqft is None


def test_improvements_that_disagree_give_no_year():
    imps = [_PARKVIEW_IMPS[0], dict(_PARKVIEW_IMPS[0], actyrbuilt="2003.000000")]
    assert _lookup_wcad([_PARKVIEW], imps,
                        address="11620 PARKVIEW DR, COUPLAND, TX, 78615") is None


def test_a_parcel_with_no_improvement_row_says_nothing():
    assert _lookup_wcad([_LYDIA], [], address="2504 LYDIA LN, ROUND ROCK, TX, 78665") is None


def test_wcads_trailing_directional_is_moved_before_the_name():
    """WCAD writes "726 5TH ST W"; the Census matcher returned all four such
    addresses checked with the directional first, "726 W 5TH ST"."""
    assert tx._williamson_address("726 5TH ST W, TAYLOR, TX  76574") == \
        "726 W 5TH ST, TAYLOR, TX 76574"
    assert tx._williamson_address("2504 LYDIA LN, ROUND ROCK, TX  78665") == \
        "2504 LYDIA LN, ROUND ROCK, TX 78665"
    assert tx._williamson_address("100 N ST, TAYLOR, TX") == "100 N ST, TAYLOR, TX", (
        "a street named by a letter keeps it")
    imps = [dict(_LYDIA_IMPS[0], propertyid="74060")]
    got = _lookup_wcad([_FIFTH_W], imps, address="726 W 5TH ST, TAYLOR, TX, 76574")
    assert got is not None and got.year_built == 1996
    assert not _shared.same_address("726 5TH ST W", "726 W 5TH ST"), (
        "the shared comparison must not have learned this; if it has, drop the local fix")


def test_williamsons_buffer_and_same_number_search_are_shaped_like_arcgis():
    params = []
    got = _lookup_wcad([], _LYDIA_IMPS, near=[_LYDIA],
                       address="2504 LYDIA LN, ROUND ROCK, TX, 78665", params=params)
    assert got is not None and got.parcel_id == "R349410"
    wheres = [p["$where"] for p in params if "propertyid in" not in p["$where"]]
    assert wheres[0].startswith("intersects(geometry, 'POINT(")
    assert wheres[1].startswith("intersects(geometry, 'POLYGON((")
    assert "starts_with(siteaddress, '2504 ')" in wheres[2]


def test_the_circle_is_a_closed_ring_of_the_right_size():
    import math
    wkt = tx._circle_wkt(30.5, -97.7, 80)
    pts = [tuple(map(float, p.split())) for p in wkt[len("POLYGON(("):-2].split(", ")]
    assert pts[0] == pts[-1] and len(pts) == 33
    for lon, lat in pts:
        dy = (lat - 30.5) * 111_320
        dx = (lon + 97.7) * 111_320 * math.cos(math.radians(30.5))
        assert abs(math.hypot(dx, dy) - 80) < 0.5


def test_a_socrata_page_at_its_limit_is_no_answer():
    many = [dict(_LYDIA, parcelid=f"R{i}", propertyid=str(i)) for i in range(tx._SOCRATA_LIMIT)]
    assert _lookup_wcad(many, _LYDIA_IMPS, address="2504 LYDIA LN, ROUND ROCK, TX, 78665") is None


def test_url_for_names_each_new_countys_own_publisher():
    assert tx.url_for(COLLIN) == tx.COLLIN_URL and tx.url_for(DENTON) == tx.DENTON_URL
    assert tx.url_for(EL_PASO) == tx.EL_PASO_URL and tx.url_for(CAMERON) == tx.CAMERON_URL
    assert tx.url_for(WILLIAMSON) == tx.WILLIAMSON_URL
    assert tx.url_for("48215") is None
