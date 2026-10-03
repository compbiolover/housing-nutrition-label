#!/usr/bin/env python3
"""The California adapter — three counties, three layouts, one set of refusals.

Nothing here touches the network. Each county's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"this county has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely these counties'. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

The counties' own:

1. **Contra Costa** returns placeholder rows ("189320xxx", every column null) over
   condominium complexes, and keeps two year columns of which only one is a
   house's.
2. **San Joaquin** writes its street types as two-letter codes, some of which
   mean two things, and files several residences under one year.
3. **Riverside** is two hops — a parcel layer AND a condominium layer, then a
   building table with one row per building, garages included — and the table
   gets its own clock.
4. In all three a condominium unit is its own record, and not always stacked, so
   the unit the reader typed has to choose it.

This file alone: ``pytest tests/test_assessor_ca.py``
"""

from __future__ import annotations

import csv
import os
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, ca

# ── recorded rows ───────────────────────────────────────────────────────────────


def _cc(**kw):
    """A Contra Costa row in the service's shape: suffixes padded to four, unused
    columns null, as recorded."""
    base = {"APN": "510104019", "USE_CODE": 11, "S_STR_NBR": "5433",
            "S_STR_NM": "VAN FLEET", "S_STR_SUF": "AVE ", "S_APT_NBR": None,
            "YR_HS_BLT": "1941", "YR_BUILT": None, "TLA": "1211"}
    base.update(kw)
    return base


# Recorded live. A 1941 single-family house in Richmond.
_CC_HOUSE = _cc()
# Recorded live. The placeholder the layer returns over condominium complexes.
_CC_PLACEHOLDER = {"APN": "189320xxx", "USE_CODE": None, "S_STR_NBR": None,
                   "S_STR_NM": None, "S_STR_SUF": None, "S_APT_NBR": None,
                   "YR_HS_BLT": None, "YR_BUILT": None, "TLA": None}
# Recorded live. Two units of a two-story building, stacked on one footprint.
_CC_UNIT_1 = _cc(APN="190090075", USE_CODE=29, S_STR_NBR="2033", S_STR_NM="PTARMIGAN",
                 S_STR_SUF="DR  ", S_APT_NBR="1", YR_HS_BLT="1971", TLA="1212")
_CC_UNIT_2 = _cc(APN="190090076", USE_CODE=29, S_STR_NBR="2033", S_STR_NM="PTARMIGAN",
                 S_STR_SUF="DR  ", S_APT_NBR="2", YR_HS_BLT="1971", TLA="1212")
# Recorded live. A Richmond duplex: the commercial-record year, no house year.
_CC_DUPLEX_YR_BUILT = _cc(APN="504152014", USE_CODE=21, S_STR_NBR="5122",
                          S_STR_NM="FRESNO", YR_HS_BLT=None, YR_BUILT="1938", TLA=None)
# Recorded live. A Moraga office condominium: YR_BUILT on use code 29.
_CC_OFFICE_CONDO = _cc(APN="256450007", USE_CODE=29, S_STR_NBR="533", S_STR_NM="MORAGA",
                       S_STR_SUF="RD  ", S_APT_NBR="230", YR_HS_BLT=None,
                       YR_BUILT="2008", TLA=None)

_CC_POINT = (37.937, -122.338)
_CC_ADDR = "5433 VAN FLEET AVE, RICHMOND, CA, 94804"


def _sj(**kw):
    base = {"APN": "13520004", "CATEGORY": "RESIDENTIAL", "USECODE": "10",
            "DESCRIPTION": "SINGLE FAMILY DWELLING(SFD)", "SITUSNUMBER": "1229",
            "SITUSDIRECTION": "N", "SITUSTREET": "CENTER", "SITUSTYPE": "ST",
            "SITUSUNIT": "", "YEAR_BUILT": "1905", "STORIES": 1,
            "TOTALLIV_AREA": 1685, "VALUE_ROLL_YEAR": "2026"}
    base.update(kw)
    return base


# Recorded live. 1229 N Center St, Stockton: 1905, one story, 1,685 sq ft.
_SJ_HOUSE = _sj()
_SJ_POINT = (37.966, -121.292)
_SJ_ADDR = "1229 N CENTER ST, STOCKTON, CA, 95202"

# Riverside: a parcel-layer row, condominium-layer rows, and building-table rows.


def _rv(**kw):
    base = {"APN": "218262008", "STREET_NUMBER": 3728, "STREET_PREDIRECTION": "",
            "STREET_NAME": "LINWOOD", "STREET_TYPE": "PL", "STREET_SUFFIX": "",
            "UNIT_NUMBER": "", "CLASS_CODE": "Single Family Dwelling"}
    base.update(kw)
    return base


# Recorded live. 3728 Linwood Pl, Riverside.
_RV_HOUSE = _rv()
# Recorded live: its two building rows — the 1914 house and the 1914 garage.
_RV_HOUSE_BUILDINGS = [
    {"PIN": "218262008", "BUILDING_ID": 199855, "YEAR_BUILT": 1914, "NUMBER_OF_STORIES": 1,
     "LIVING_AREA": 1428.0, "DESIGN_TYPE": "Conventional Single Family Residence (Pre-1950)"},
    {"PIN": "218262008", "BUILDING_ID": 199856, "YEAR_BUILT": 1914, "NUMBER_OF_STORIES": None,
     "LIVING_AREA": None, "DESIGN_TYPE": "Residential Garage"},
]
# Recorded live. At 3738 Harrison St the parcel layer returns only the complex's
# common lot — no situs, classed vacant — and the units live on the condo layer.
_RV_COMMON_LOT = _rv(APN="234052071", STREET_NUMBER=None, STREET_NAME="",
                     STREET_TYPE="", CLASS_CODE="Vacant Residential Land - Other")


def _rv_unit(apn, unit):
    return _rv(APN=apn, STREET_NUMBER=3738, STREET_NAME="HARRISON", STREET_TYPE="ST",
               UNIT_NUMBER=f"{unit:<8}", CLASS_CODE="Condo or PUD")


_RV_UNIT_27 = _rv_unit("234052027", "27")
_RV_UNIT_28 = _rv_unit("234052028", "28")
_RV_UNIT_BUILDINGS = {
    "234052027": [{"PIN": "234052027", "BUILDING_ID": 219796, "YEAR_BUILT": 1988,
                   "NUMBER_OF_STORIES": 1, "LIVING_AREA": 1009.0,
                   "DESIGN_TYPE": "Modern Single Family Residence (1950-1990)"}],
    "234052028": [{"PIN": "234052028", "BUILDING_ID": 219797, "YEAR_BUILT": 1988,
                   "NUMBER_OF_STORIES": 1, "LIVING_AREA": 808.0,
                   "DESIGN_TYPE": "Modern Single Family Residence (1950-1990)"}],
    # Recorded live: a parcel with no building returns one all-null row.
    "234052071": [{"PIN": "234052071", "BUILDING_ID": None, "YEAR_BUILT": None,
                   "NUMBER_OF_STORIES": None, "LIVING_AREA": None, "DESIGN_TYPE": ""}],
}
_RV_POINT = (33.951, -117.396)
_RV_ADDR = "3728 LINWOOD PL, RIVERSIDE, CA, 92506"


# ── the stub ────────────────────────────────────────────────────────────────────


def _lookup(exact=None, near=None, address=None, county="06013", *, buildings=None,
            point=None, slices=None, calls=None, truncated=False, raise_on=None):
    """Drive ``ca.lookup()`` over recorded rows, beneath the real transport helper.

    ``exact`` / ``near`` map a layer tag ("parcel", "condo") — or, for a one-layer
    county, simply a list — to the rows a containment and a buffered query
    return. ``buildings`` maps a Riverside PIN to its building-table rows; the
    stub answers the table with the rows of exactly the PINs the request names,
    so the query the adapter builds is what decides the answer.
    """
    exact, near = exact or {}, near or {}
    if isinstance(exact, list):
        exact = {"parcel": exact}
    if isinstance(near, list):
        near = {"parcel": near}
    buildings = buildings or {}
    slices = [] if slices is None else slices
    calls = [] if calls is None else calls

    def layer_of(url):
        return "condo" if url == ca.RIVERSIDE_CONDO_URL else "parcel"

    def fake(url, params, deadline, read_slice=None):
        slices.append(read_slice)
        calls.append((url, dict(params), deadline))
        if raise_on and raise_on in url:
            raise RuntimeError("upstream error: layer not found")
        if url == ca.RIVERSIDE_BUILDINGS_URL:
            where = params["where"]
            rows = [r for pin, rs in buildings.items() if f"'{pin}'" in where for r in rs]
        else:
            source = near if params.get("distance") else exact
            rows = list(source.get(layer_of(url), []))
        body = {"features": [{"attributes": a} for a in rows]}
        if truncated:
            body["exceededTransferLimit"] = True
        return body

    ca._lookup_cached.cache_clear()
    saved = _shared._fetch_json
    _shared._fetch_json = fake
    try:
        pt = point or {"06013": _CC_POINT, "06077": _SJ_POINT, "06065": _RV_POINT}[county]
        return ca.lookup(*pt, address, county_fips=county)
    finally:
        _shared._fetch_json = saved
        ca._lookup_cached.cache_clear()


# ── Contra Costa ────────────────────────────────────────────────────────────────


def test_a_contra_costa_house_reports_its_year_and_living_area():
    got = _lookup([_CC_HOUSE], address=_CC_ADDR)
    assert got is not None
    assert got.parcel_id == "510104019"
    assert got.year_built == 1941 and got.sqft == 1211.0
    assert got.stories is None, "the layer has no story count"
    assert "Contra Costa" in got.source


def test_the_placeholder_over_a_condominium_complex_is_not_a_record():
    """Recorded live: rows whose APN ends in x's and whose every other column is
    null. Counted as a candidate, one makes the real parcel under it ambiguous."""
    assert _lookup([_CC_PLACEHOLDER]) is None
    got = _lookup([_CC_PLACEHOLDER, _CC_HOUSE], address=_CC_ADDR)
    assert got is not None and got.parcel_id == "510104019"


def test_a_real_apn_with_nothing_on_it_is_a_placeholder_too():
    empty = dict(_CC_PLACEHOLDER, APN="510015019")
    got = _lookup([empty, _CC_HOUSE], address=_CC_ADDR)
    assert got is not None and got.parcel_id == "510104019"


def test_the_house_year_is_the_year_read():
    """YR_HS_BLT is the year the HOUSE was built; YR_BUILT is filled on the
    commercial-style records instead — never both on one row, measured over the
    whole layer. A house row carrying a YR_BUILT would be read for its house
    year."""
    got = _lookup([_cc(YR_BUILT="1990")], address=_CC_ADDR)
    assert got is not None and got.year_built == 1941


def test_a_multifamily_building_falls_back_to_its_building_year():
    """Triplexes, fourplexes and apartments carry no house year at all, only
    YR_BUILT, and the whole parcel is housing, so that year is a home's."""
    fourplex = _cc(APN="510011001", USE_CODE=23, S_STR_NBR="3409", S_STR_NM="BELMONT",
                   YR_HS_BLT=None, YR_BUILT="1959", TLA=None)
    got = _lookup([fourplex], address="3409 BELMONT AVE, RICHMOND, CA")
    assert got is not None and got.year_built == 1959 and got.sqft is None


def test_a_duplex_does_not_borrow_the_commercial_year():
    """Duplexes are the one multi-dwelling code where the house year IS filled
    (3,095 of 3,235); the fallback is limited to the codes that never carry it, so
    a duplex row without a house year stays without one."""
    assert _lookup([_CC_DUPLEX_YR_BUILT], address="5122 FRESNO AVE, RICHMOND, CA") is None


def test_an_office_condominium_reports_nothing():
    """Use code 29 includes commercial and industrial condominiums. Their year
    is the commercial-record YR_BUILT, which is never read for a condominium."""
    got = _lookup([_CC_OFFICE_CONDO], address="533 MORAGA RD #230, MORAGA, CA")
    assert got is None


def test_a_parcel_with_several_residences_reports_no_year():
    """Use code 13, "Single Family, 2 or more residences": one year column for
    more than one house, and nothing says which."""
    assert _lookup([_cc(USE_CODE=13)], address=_CC_ADDR) is None


def test_a_vacant_or_government_parcel_reports_no_year():
    """An explicit non-home use code is the roll saying nobody lives here — 486
    government parcels carry a house year."""
    for code in (17, 79, 31):
        assert _lookup([_cc(USE_CODE=code)], address=_CC_ADDR) is None, code


def test_a_blank_use_code_is_silence_not_a_refusal():
    got = _lookup([_cc(USE_CODE=None)], address=_CC_ADDR)
    assert got is not None and got.year_built == 1941
    assert got.sqft is None, "the area needs the code that says one dwelling"


def test_a_duplex_reports_its_year_but_not_its_area():
    got = _lookup([_cc(USE_CODE=21, TLA="2400")], address=_CC_ADDR)
    assert got is not None and got.year_built == 1941 and got.sqft is None


def test_the_contra_costa_zero_years_are_not_years():
    for raw in ("   0", "0000", "", None):
        got = _lookup([_cc(YR_HS_BLT=raw)], address=_CC_ADDR)
        assert got is not None and got.year_built is None, raw
        assert got.sqft == 1211.0


def test_the_range_end_is_not_a_fraction():
    """S_FRAC holds the END of a number range ("4889" … "4891"), not "1/2"; read as
    part of the address it would make "4889 4891 CENTRAL AVE" of every such row."""
    row = _cc(S_FRAC="5435")
    assert ca._cc_address(row) == "5433 VAN FLEET AVE"


# ── condominiums (Contra Costa's recorded stack) ────────────────────────────────


def test_the_readers_unit_picks_its_record_and_its_own_area():
    got = _lookup([_CC_UNIT_1, _CC_UNIT_2], near=[_CC_UNIT_1, _CC_UNIT_2],
                  address="2033 PTARMIGAN DR #2, WALNUT CREEK, CA, 94595")
    assert got is not None and got.parcel_id == "190090076"
    assert got.year_built == 1971 and got.sqft == 1212.0


def test_a_unit_footprint_under_the_point_is_not_the_readers_unit():
    """Units here are not always stacked: the point can land in ONE unit's
    polygon whichever unit the reader typed (the geocoder puts every unit of an
    address on one point). Containment alone would hand the reader their
    neighbor's record — and its area as observed fact."""
    got = _lookup([_CC_UNIT_1], near=[_CC_UNIT_1, _CC_UNIT_2],
                  address="2033 PTARMIGAN DR #2, WALNUT CREEK, CA, 94595")
    assert got is not None and got.parcel_id == "190090076", got


def test_no_unit_given_reports_the_buildings_year_and_nothing_else():
    got = _lookup([_CC_UNIT_1, _CC_UNIT_2], near=[_CC_UNIT_1, _CC_UNIT_2],
                  address="2033 PTARMIGAN DR, WALNUT CREEK, CA, 94595")
    assert got is not None and got.year_built == 1971
    assert got.sqft is None and got.parcel_id is None


def test_a_single_unit_under_the_point_is_not_taken_for_a_reader_who_gave_none():
    """The same building path, reached from the other side: one unit's polygon
    contains the point and its street address agrees, but the reader did not say
    which unit they live in."""
    got = _lookup([_CC_UNIT_1], near=[_CC_UNIT_1, _CC_UNIT_2],
                  address="2033 PTARMIGAN DR, WALNUT CREEK, CA, 94595")
    assert got is not None and got.parcel_id is None and got.sqft is None


def test_units_that_disagree_on_the_year_give_no_building_year():
    other = dict(_CC_UNIT_2, YR_HS_BLT="1972")
    assert _lookup([_CC_UNIT_1, other], near=[_CC_UNIT_1, other],
                   address="2033 PTARMIGAN DR, WALNUT CREEK, CA, 94595") is None


def test_two_records_claiming_one_unit_are_an_ambiguity():
    """Neither is chosen, so neither's area or id is reported; the building path
    still gives the year both agree on, as in Los Angeles."""
    twin = dict(_CC_UNIT_2, APN="190090099")
    got = _lookup([_CC_UNIT_2, twin], near=[_CC_UNIT_2, twin],
                  address="2033 PTARMIGAN DR #2, WALNUT CREEK, CA, 94595")
    assert got is not None and got.parcel_id is None and got.sqft is None
    split = dict(twin, YR_HS_BLT="1972")
    assert _lookup([_CC_UNIT_2, split], near=[_CC_UNIT_2, split],
                   address="2033 PTARMIGAN DR #2, WALNUT CREEK, CA, 94595") is None


def test_a_unit_typed_at_a_house_costs_the_area_not_the_year():
    got = _lookup([_CC_HOUSE], address="5433 VAN FLEET AVE #B, RICHMOND, CA")
    assert got is not None and got.year_built == 1941 and got.sqft is None


# ── San Joaquin ─────────────────────────────────────────────────────────────────


def test_a_san_joaquin_house_reports_year_area_stories_and_its_roll_year():
    got = _lookup([_SJ_HOUSE], address=_SJ_ADDR, county="06077")
    assert got is not None and got.parcel_id == "13520004"
    assert (got.year_built, got.sqft, got.stories) == (1905, 1685.0, 1)
    assert got.data_vintage.endswith("2026 roll")


def test_a_missing_roll_year_falls_back_rather_than_inventing_one():
    got = _lookup([_sj(VALUE_ROLL_YEAR="")], address=_SJ_ADDR, county="06077")
    assert got is not None and got.data_vintage == ca.COUNTIES["06077"].vintage


def test_san_joaquins_circle_code_is_a_circle():
    """SITUSTYPE "CI" (13,217 parcels): the Census matcher writes CIR, and the
    county writes CT for court, so CI has one reading."""
    row = _sj(SITUSNUMBER="8721", SITUSDIRECTION="W", SITUSTREET="JULIE LYNNE",
              SITUSTYPE="CI")
    got = _lookup([], near=[row], address="8721 W JULIE LYNNE CIR, TRACY, CA, 95304",
                  county="06077")
    assert got is not None and got.year_built == 1905


def test_an_ambiguous_two_letter_type_confirms_nothing():
    """CR is a circle or a crescent and the county also writes CI; mapped either
    way it could confirm the wrong street. Left as written, it confirms nothing."""
    row = _sj(SITUSNUMBER="5855", SITUSDIRECTION="", SITUSTREET="RIVERBANK",
              SITUSTYPE="CR")
    assert _lookup([], near=[row], address="5855 RIVERBANK CIR, STOCKTON, CA",
                   county="06077") is None


def test_san_joaquins_trail_code_is_a_trail():
    """TR is left alone by the shared table (trail or terrace elsewhere), but this
    county writes TE for its terraces; its TR streets are trails. Measured: the
    matcher returned "16812 FORTY NINER TRL" for the roll's "FORTY NINER TR"."""
    row = _sj(SITUSNUMBER="16812", SITUSDIRECTION="", SITUSTREET="FORTY NINER",
              SITUSTYPE="TR")
    assert _shared.same_address("16812 FORTY NINER TRL, LATHROP, CA", ca._sj_address(row))
    terrace = dict(row, SITUSTYPE="TE")
    assert _shared.same_address("16812 FORTY NINER TER", ca._sj_address(terrace))
    assert not _shared.same_address("16812 FORTY NINER TER", ca._sj_address(row))


def test_a_condominium_unit_reports_its_area_only_to_its_own_reader():
    unit = _sj(APN="24619054", USECODE="11", SITUSNUMBER="455", SITUSDIRECTION="",
               SITUSTREET="PEERLESS", SITUSTYPE="WY", SITUSUNIT="2", YEAR_BUILT="1983",
               STORIES=1, TOTALLIV_AREA=1118)
    got = _lookup([unit], near=[unit], address="455 PEERLESS WAY #2, STOCKTON, CA",
                  county="06077")
    assert got is not None and got.sqft == 1118.0 and got.stories == 1


def test_several_residences_on_one_parcel_report_no_year():
    """"TWO SFDS ON SINGLE PARCEL", "SINGLE FAMILY RESIDENCE W/SECONDARY RES":
    one year column, more than one house."""
    for code in ("22", "13", "52"):
        assert _lookup([_sj(USECODE=code)], address=_SJ_ADDR, county="06077") is None


def test_vacant_land_and_garage_only_parcels_report_no_year():
    for code in ("6A", "4A", "54"):
        assert _lookup([_sj(USECODE=code)], address=_SJ_ADDR, county="06077") is None


def test_a_non_residential_category_reports_no_year():
    assert _lookup([_sj(CATEGORY="COMMERCIAL", USECODE="")], address=_SJ_ADDR,
                   county="06077") is None


def test_a_farm_with_a_residence_reports_the_residences_year():
    farm = _sj(CATEGORY="AGRICULTURAL", USECODE="401",
               DESCRIPTION="IRRIGATED ORCHARD W/RESIDENCE")
    got = _lookup([farm], address=_SJ_ADDR, county="06077")
    assert got is not None and got.year_built == 1905 and got.sqft is None
    bare = dict(farm, USECODE="400", DESCRIPTION="IRRIGATED ORCHARD")
    assert _lookup([bare], address=_SJ_ADDR, county="06077") is None


def test_a_triplex_reports_its_year_but_not_its_area():
    got = _lookup([_sj(USECODE="31")], address=_SJ_ADDR, county="06077")
    assert got is not None and got.year_built == 1905
    assert got.sqft is None and got.stories is None


def test_san_joaquins_blank_year_and_future_years_are_not_years():
    """Recorded live: 2047 and 2109 among the residential years. 2109 is past the
    shared ceiling; 2047 is not, and is refused as a year that has not happened."""
    for raw in ("", "2047", "2109", "0"):
        got = _lookup([_sj(YEAR_BUILT=raw)], address=_SJ_ADDR, county="06077")
        assert got is not None and got.year_built is None, raw


def test_next_years_house_is_still_a_year():
    nxt = str(time.localtime().tm_year + 1)
    got = _lookup([_sj(YEAR_BUILT=nxt)], address=_SJ_ADDR, county="06077")
    assert got is not None and got.year_built == int(nxt)


# ── Riverside ───────────────────────────────────────────────────────────────────


def test_a_riverside_house_ignores_its_garage():
    """Garages are building rows of their own, carrying the house's year. Counted
    as a second dwelling, one would cost every house with a garage its area."""
    got = _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                  buildings={"218262008": _RV_HOUSE_BUILDINGS})
    assert got is not None and got.parcel_id == "218262008"
    assert (got.year_built, got.sqft, got.stories) == (1914, 1428.0, 1)


def test_dwellings_that_disagree_on_the_year_give_no_year():
    """An SFD with a secondary unit: the 1955 house and the 2019 guesthouse."""
    rows = [dict(_RV_HOUSE_BUILDINGS[0], YEAR_BUILT=1955),
            {"PIN": "218262008", "BUILDING_ID": 5, "YEAR_BUILT": 2019,
             "NUMBER_OF_STORIES": 1, "LIVING_AREA": 480.0,
             "DESIGN_TYPE": "Guesthouse - Modern (Post 1990)"}]
    assert _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                   buildings={"218262008": rows}) is None


def test_dwellings_that_agree_give_the_year_but_not_an_area():
    rows = [_RV_HOUSE_BUILDINGS[0],
            {"PIN": "218262008", "BUILDING_ID": 5, "YEAR_BUILT": 1914,
             "NUMBER_OF_STORIES": 1, "LIVING_AREA": 480.0,
             "DESIGN_TYPE": "Guesthouse - Conventional (Pre 1950)"}]
    got = _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                  buildings={"218262008": rows})
    assert got is not None and got.year_built == 1914
    assert got.sqft is None and got.stories is None


def test_a_building_of_unknown_kind_breaks_the_agreement():
    rows = _RV_HOUSE_BUILDINGS + [{"PIN": "218262008", "BUILDING_ID": 9,
                                   "YEAR_BUILT": 1990, "NUMBER_OF_STORIES": None,
                                   "LIVING_AREA": None, "DESIGN_TYPE": "Unknown"}]
    assert _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                   buildings={"218262008": rows}) is None


def test_a_dwelling_with_no_year_breaks_the_agreement():
    rows = [dict(_RV_HOUSE_BUILDINGS[0], YEAR_BUILT=None)]
    got = _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                  buildings={"218262008": rows})
    assert got is not None and got.year_built is None and got.sqft == 1428.0


def test_an_apartment_building_reports_its_year_and_no_area():
    rows = [{"PIN": "218262008", "BUILDING_ID": 1, "YEAR_BUILT": 1963,
             "NUMBER_OF_STORIES": 2, "LIVING_AREA": None, "DESIGN_TYPE": "Apartment"}]
    got = _lookup({"parcel": [_rv(CLASS_CODE="Fourplex")]}, address=_RV_ADDR,
                  county="06065", buildings={"218262008": rows})
    assert got is not None and got.year_built == 1963 and got.sqft is None


def test_a_parcel_with_no_dwelling_building_reports_nothing():
    """Only a garage, or a store, or the all-null row of a parcel with no building:
    the roll saying no home stands here."""
    for rows in ([_RV_HOUSE_BUILDINGS[1]],
                 [dict(_RV_HOUSE_BUILDINGS[1], DESIGN_TYPE="Commercial / Industrial")],
                 _RV_UNIT_BUILDINGS["234052071"]):
        assert _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                       buildings={"218262008": [dict(r, PIN="218262008") for r in rows]}
                       ) is None, rows


def test_a_vacant_class_beside_a_dwelling_row_is_a_contradiction():
    got = _lookup({"parcel": [_rv(CLASS_CODE="Vacant Residential Lot")]},
                  address=_RV_ADDR, county="06065",
                  buildings={"218262008": _RV_HOUSE_BUILDINGS})
    assert got is None


def test_the_condo_layer_is_asked_because_the_parcel_layer_holds_only_the_common_lot():
    """Recorded live at 3738 Harrison St: the parcel layer returns the complex's
    common lot, with no situs and no building; the unit is on the condo layer.
    Without the second layer every Riverside condominium reads as vacant land."""
    calls = []
    got = _lookup({"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27]},
                  near={"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27, _RV_UNIT_28]},
                  address="3738 HARRISON ST #27, RIVERSIDE, CA, 92503", county="06065",
                  buildings=_RV_UNIT_BUILDINGS, calls=calls)
    assert got is not None and got.parcel_id == "234052027"
    assert got.year_built == 1988 and got.sqft == 1009.0
    assert got.stories is None, "a unit's story count is not reported"
    asked = {url for url, _, _ in calls}
    assert ca.RIVERSIDE_CONDO_URL in asked and ca.RIVERSIDE_PARCEL_URL in asked


def test_a_riverside_unit_under_the_point_is_not_the_readers_unit():
    got = _lookup({"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27]},
                  near={"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27, _RV_UNIT_28]},
                  address="3738 HARRISON ST #28, RIVERSIDE, CA, 92503", county="06065",
                  buildings=_RV_UNIT_BUILDINGS)
    assert got is not None and got.parcel_id == "234052028" and got.sqft == 808.0


def test_a_riverside_condo_without_a_unit_reports_the_buildings_year():
    calls = []
    got = _lookup({"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27]},
                  near={"parcel": [_RV_COMMON_LOT], "condo": [_RV_UNIT_27, _RV_UNIT_28]},
                  address="3738 HARRISON ST, RIVERSIDE, CA, 92503", county="06065",
                  buildings=_RV_UNIT_BUILDINGS, calls=calls)
    assert got is not None and got.year_built == 1988
    assert got.parcel_id is None and got.sqft is None
    table = [p["where"] for url, p, _ in calls if url == ca.RIVERSIDE_BUILDINGS_URL]
    assert len(table) == 1, "every unit at the address in one table request"
    assert "'234052027'" in table[0] and "'234052028'" in table[0]


def test_riverside_trail_and_parkway_are_read_as_the_matcher_writes_them():
    """TR is Trail in Riverside (Preston Trail, Palm Desert; 7,102 parcels) and
    PKY its Parkway; the matcher writes TRL and PKWY. The shared table leaves TR
    alone because elsewhere it can be a terrace."""
    trail = _rv(STREET_NUMBER=74001, STREET_NAME="PRESTON", STREET_TYPE="TR")
    assert _shared.same_address("74001 PRESTON TRL, PALM DESERT, CA", ca._rv_address(trail))
    assert not _shared.same_address("74001 PRESTON TER", ca._rv_address(trail))
    pky = _rv(STREET_NUMBER=100, STREET_NAME="ALESSANDRO", STREET_TYPE="PKY")
    assert _shared.same_address("100 ALESSANDRO PKWY", ca._rv_address(pky))


def test_the_matchers_spanish_abbreviations_match_the_rolls_spellings():
    """Measured in the end-to-end run: the matcher returns CAM for CAMINO and AVE
    for a leading AVENIDA, VIS for a trailing VISTA, and the rolls spell all three
    out — 7 of 33 refusals, across the counties, were only this."""
    cases = [
        (_rv(STREET_NUMBER=32200, STREET_NAME="CAMINO CALIARI", STREET_TYPE=""),
         "32200 CAM CALIARI, TEMECULA, CA, 92592"),
        (_rv(STREET_NUMBER=31775, STREET_NAME="AVENIDA XIMINO", STREET_TYPE=""),
         "31775 AVE XIMINO, CATHEDRAL CITY, CA, 92234"),
        (_rv(STREET_NUMBER=472, STREET_NAME="MONTE VISTA", STREET_TYPE=""),
         "472 MONTE VIS, PALM DESERT, CA, 92260"),
    ]
    for row, matched in cases:
        assert _shared.same_address(ca._canon(matched), ca._rv_address(row)), matched
    peral = _cc(S_STR_NBR="1402", S_STR_NM="CAMINO PERAL", S_STR_SUF=None)
    assert _shared.same_address(ca._canon("1402 CAM PERAL, MORAGA"), ca._cc_address(peral))


def test_the_spanish_fold_does_not_join_different_streets():
    """The folded words stay part of the name: Avenida Ximino is not Ximino Avenue,
    and a VISTA in the middle of a name ("VISTA DEL MAR") is not a street type."""
    ave = ca._rv_address(_rv(STREET_NUMBER=31775, STREET_NAME="AVENIDA XIMINO",
                             STREET_TYPE=""))
    assert not _shared.same_address(ca._canon("31775 XIMINO AVE"), ave)
    assert ca._canon("10 VISTA DEL MAR, X") == "10 VISTA DEL MAR, X"
    assert ca._canon("472 MONTE VISTA #3, PALM DESERT") == "472 MONTE VIS #3, PALM DESERT"
    assert ca._canon("5 MONTE VISTA DR") == "5 MONTE VISTA DR"


def test_the_reader_side_is_folded_through_the_lookup():
    row = _rv(STREET_NUMBER=32200, STREET_NAME="CAMINO CALIARI", STREET_TYPE="",
              APN="959351014")
    got = _lookup({}, near={"parcel": [row]}, county="06065",
                  address="32200 CAMINO CALIARI, TEMECULA, CA, 92592",
                  buildings={"959351014": [dict(_RV_HOUSE_BUILDINGS[0], PIN="959351014")]})
    assert got is not None and got.parcel_id == "959351014"


def test_a_stray_value_in_the_suffix_column_makes_the_address_unconfirmable():
    assert ca._rv_address(_rv(STREET_SUFFIX="11501")) is None
    assert ca._rv_address(_rv(STREET_SUFFIX="1/2")) == "3728 1/2 LINWOOD PL"
    assert ca._rv_address(_rv(STREET_SUFFIX="EAST")) == "3728 LINWOOD PL E"


def test_the_building_table_gets_its_own_clock():
    """The table is a hop of its own: research saw one cold call take 19.9 s. Its
    deadline is started when the hop starts, so a slow parcel phase cannot leave
    it nothing to run in."""
    calls = []
    started = time.monotonic()
    _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
            buildings={"218262008": _RV_HOUSE_BUILDINGS}, calls=calls)
    parcel = [d for url, _, d in calls if url != ca.RIVERSIDE_BUILDINGS_URL]
    table = [d for url, _, d in calls if url == ca.RIVERSIDE_BUILDINGS_URL]
    assert parcel and len(set(parcel)) == 1, "every parcel request shares one deadline"
    assert abs((parcel[0] - started) - ca.LOOKUP_TIMEOUT) < 0.5
    assert len(table) == 1
    assert abs((table[0] - started) - ca.BUILDINGS_TIMEOUT) < 0.5
    assert table[0] != parcel[0]


def test_a_truncated_building_table_is_no_answer():
    assert _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                   buildings={"218262008": _RV_HOUSE_BUILDINGS}, truncated=True) is None


# ── shared refusals ─────────────────────────────────────────────────────────────


def test_a_parcel_that_records_nothing_at_all_is_not_an_answer():
    """Checked through ``assessor_for_point``, the door the label actually uses."""
    empty = _cc(YR_HS_BLT=None, TLA=None)
    assert _lookup([empty], address=_CC_ADDR) is None

    def fake(url, params, deadline, read_slice=None):
        return {"features": [{"attributes": empty}]}

    ca._lookup_cached.cache_clear()
    saved_get, saved_env = _shared._fetch_json, os.environ.get(A.ENABLE_ENV)
    _shared._fetch_json, os.environ[A.ENABLE_ENV] = fake, "1"
    try:
        if A.adapter_for_county("06013") is ca:
            assert A.assessor_for_point(*_CC_POINT, "06013") is None
        else:
            assert ca.lookup(*_CC_POINT, county_fips="06013") is None
    finally:
        _shared._fetch_json = saved_get
        os.environ.pop(A.ENABLE_ENV, None)
        if saved_env is not None:
            os.environ[A.ENABLE_ENV] = saved_env
        ca._lookup_cached.cache_clear()


def test_a_truncated_parcel_page_is_no_answer():
    assert _lookup([_CC_HOUSE], address=_CC_ADDR, truncated=True) is None


def test_the_portal_falling_over_is_not_evidence_of_absence():
    for county, url in (("06013", "gis.cccounty.us"), ("06077", "services2.arcgis.com"),
                        ("06065", "/80/query")):
        got = _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county=county,
                      buildings={"218262008": _RV_HOUSE_BUILDINGS}, raise_on=url)
        assert got is None, county


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([], address=_CC_ADDR) is None
    assert _lookup({}, address=_RV_ADDR, county="06065") is None


def test_two_houses_containing_the_point_are_ambiguous_without_an_address():
    other = _cc(APN="510104020", S_STR_NBR="5437")
    assert _lookup([_CC_HOUSE, other]) is None


# ── no translated vocabulary, and the field lists ───────────────────────────────


def test_no_translated_field_is_ever_reported():
    """Riverside's CONSTRUCTION_TYPE is the State Board's class D/C/A/B/S — D is
    wood frame with any skin, which the label splits three ways — and San
    Joaquin's QCS is a quality class; neither is requested, so neither can be read
    by a later edit."""
    got = _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
                  buildings={"218262008": [dict(_RV_HOUSE_BUILDINGS[0],
                                                CONSTRUCTION_TYPE="Wood or Light Steel (D)",
                                                QUALITY_CODE="D5")]})
    assert got is not None
    assert got.construction is None and got.foundation is None and got.condition is None
    assert "CONSTRUCTION_TYPE" not in ca._RV_BUILDING_FIELDS
    assert "QCS" not in ca.COUNTIES["06077"].fields


def test_the_effective_years_are_never_requested():
    """None of the three layers requested carries an effective year, and the
    California ones measured that do (San Bernardino's EFF_YEAR, Sacramento's
    EFFECTIVE_YEAR_BUILT, San Diego's year_effective) are not in this module."""
    every = ",".join([c.fields for c in ca.COUNTIES.values()] + [ca._RV_BUILDING_FIELDS])
    for name in every.split(","):
        assert "EFF" not in name.upper(), name


def test_the_field_lists_are_the_privacy_boundary():
    private = {
        "06013": ("N_STR_NM", "N_STR_NBR", "N_CTY_ST", "N_ZIP", "LAND_VALUE", "IMP_VAL",
                  "XMP_CODE1", "full_n_address"),
        "06077": ("CAREOF", "DBANAME", "MAILSTREET", "MAILCITY", "MAILING_ADDRESS",
                  "LAND_VALUE", "STRUCTURE_VALUE", "EXEMPCODE"),
        "06065": ("MAIL_STREET", "MAIL_CITY", "LAND", "STRUCTURES", "PRIMARY_OWNER",
                  "ALL_OWNER_LIST"),
    }
    for fips, names in private.items():
        fields = ca.COUNTIES[fips].fields.split(",")
        assert "*" not in fields
        for name in names:
            assert name not in fields, (fips, name)


def test_the_requested_fields_are_what_reaches_the_service():
    calls = []
    _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
            buildings={"218262008": _RV_HOUSE_BUILDINGS}, calls=calls)
    for url, params, _ in calls:
        want = (ca._RV_BUILDING_FIELDS if url == ca.RIVERSIDE_BUILDINGS_URL
                else ca.COUNTIES["06065"].fields)
        assert params["outFields"] == want, url


# ── the county list, the routing, and the clock ─────────────────────────────────


def test_the_counties_are_real_california_counties():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        geoids = {r["geoid"] for r in csv.DictReader(fh)}
    assert ca.COUNTY_FIPS <= geoids
    assert ca.COUNTY_FIPS == {"06013", "06077", "06065"}


def test_the_excluded_counties_are_not_claimed():
    """Los Angeles and San Francisco have their own adapters; San Bernardino and
    Ventura are pending a product decision; the rest publish no usable year."""
    for fips in ("06037", "06075", "06071", "06111", "06073", "06059", "06085",
                 "06001", "06067", "06019", "06029", "06081"):
        assert fips not in ca.COUNTY_FIPS, fips


def test_no_two_adapters_claim_the_same_county():
    seen = {}
    for mod in {m for m in A.ADAPTERS.values()} | {ca}:
        for fips in mod.COUNTY_FIPS:
            assert fips not in seen or seen[fips] == mod.__name__, (
                f"{fips} claimed by {seen.get(fips)} and {mod}")
            seen[fips] = mod.__name__


def test_a_direct_call_with_no_county_is_routed_by_the_layers_extent():
    calls = []
    ca._lookup_cached.cache_clear()
    saved = _shared._fetch_json

    def fake(url, params, deadline, read_slice=None):
        calls.append(url)
        return {"features": [{"attributes": _SJ_HOUSE}]} if url == ca.SAN_JOAQUIN_URL \
            else {"features": []}

    _shared._fetch_json = fake
    try:
        got = ca.lookup(*_SJ_POINT, _SJ_ADDR)
    finally:
        _shared._fetch_json = saved
        ca._lookup_cached.cache_clear()
    assert got is not None and got.parcel_id == "13520004"
    assert set(calls) == {ca.SAN_JOAQUIN_URL}, "Stockton is outside the other extents"


def test_a_county_this_module_does_not_cover_is_not_asked():
    assert _lookup([_CC_HOUSE], address=_CC_ADDR, county="06037", point=_CC_POINT) is None
    assert ca._counties_at(34.05, -118.25, None) == [], "Los Angeles is in no extent"


def test_every_request_is_handed_the_modules_read_slice():
    slices = []
    _lookup({"parcel": [_RV_HOUSE]}, address=_RV_ADDR, county="06065",
            buildings={"218262008": _RV_HOUSE_BUILDINGS}, slices=slices)
    assert slices and all(s == ca.READ_SLICE_S for s in slices), slices


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The two halves of a socket timeout add up: one request can cost the budget
    spent connecting plus one read slice. Riverside makes two such phases — the
    parcel requests on one clock, the building table on its own — so its worst
    case is both, each overshooting by a slice.

    Pinned against the host constant rather than a literal."""
    from housing_label import config
    assert ca.LOOKUP_TIMEOUT + ca.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET
    worst = ca.LOOKUP_TIMEOUT + ca.BUILDINGS_TIMEOUT + 2 * ca.READ_SLICE_S
    assert worst < config.UPSTREAM_HOST_BUDGET, (
        f"Riverside's worst case {worst}s is not under the "
        f"{config.UPSTREAM_HOST_BUDGET}s this host allows one service")
