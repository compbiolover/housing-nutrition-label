#!/usr/bin/env python3
"""The Utah adapter — 29 county layers, one row per building, and what that costs.

Nothing here touches the network. UGRC's services are stubbed with row shapes
recorded from them live, for the reason every adapter test file gives: an adapter
fails open on purpose, so a renamed column or a broken match reads as "Utah has no
record here" and would never announce itself. A test that called the real service
would pass just as quietly.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Utah's own:

1. The layer has **one row per building**, so a house with a shed is two rows under
   one coordinate, and the shed's year must never be reported as the home's.
2. ``HOUSE_CNT`` ("Number of Housing Units") **counts buildings**, not homes, so it
   cannot carry the one-dwelling rule. Only Utah County's building style and
   Carbon County's "Single Family" class can.
3. **Condominiums**: Salt Lake writes the tower's floor count (27, 30) onto every
   unit, and the unit's own address carries its number.
4. The counties write **four construction vocabularies**, one of them two-letter
   codes whose only published table is not the one the rows use.
5. The registry does not pass the **county**, and the records are 29 services.

This file alone: ``pytest tests/test_assessor_ut.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich.assessor import _shared, ut

_ASOF = 1761782400000          # 2025-10-30, Utah County's CURRENT_ASOF, recorded live

# Recorded live from Parcels_Utah_LIR: 924 E 100 N, a 1920 house with two wood
# sheds and a 1996 detached garage — four building rows, one parcel.
_HOUSE = {"PARCEL_ID": "140350270", "PARCEL_ADD": "924 E 100 N",
          "PROP_CLASS": "Residential", "BUILT_YR": 1920, "BLDG_SQFT": 1755,
          "BLDG_SQFT_INFO": "one_story", "FLOORS_CNT": 1,
          "CONST_MATERIAL": "Frame:  Masonry Veneer", "CURRENT_ASOF": _ASOF}
_SHED_1 = dict(_HOUSE, BUILT_YR=1920, BLDG_SQFT=240, BLDG_SQFT_INFO="shed:_wood",
               CONST_MATERIAL="Wood")
_SHED_2 = dict(_HOUSE, BUILT_YR=1920, BLDG_SQFT=192, BLDG_SQFT_INFO="shed:_wood",
               CONST_MATERIAL="Wood")
_GARAGE = dict(_HOUSE, BUILT_YR=1996, BLDG_SQFT=572, BLDG_SQFT_INFO="detached",
               CONST_MATERIAL="Wood Framed")

# Recorded live: 930 E 100 N, a 2013 two-storey house with a 2018 detached garage.
# The garage is the NEWER building, so taking the latest year would be wrong.
_TWO_STORY = {"PARCEL_ID": "140350267", "PARCEL_ADD": "930 E 100 N",
              "PROP_CLASS": "Residential", "BUILT_YR": 2013, "BLDG_SQFT": 2943,
              "BLDG_SQFT_INFO": "two_story", "FLOORS_CNT": 2,
              "CONST_MATERIAL": "Frame:  Wood Siding", "CURRENT_ASOF": _ASOF}
_ITS_GARAGE = dict(_TWO_STORY, BUILT_YR=2018, BLDG_SQFT=1197,
                   BLDG_SQFT_INFO="detached", FLOORS_CNT=1,
                   CONST_MATERIAL="Wood Framed")

# Recorded live from Parcels_Weber_LIR: 3854 S 800 W, house and shed. Weber writes
# no building style, so nothing positively says the house is one dwelling.
_WEBER = {"PARCEL_ID": "051730006", "PARCEL_ADD": "3854 S 800 W",
          "PROP_CLASS": "Residential", "BUILT_YR": 2000, "BLDG_SQFT": 1827,
          "BLDG_SQFT_INFO": None, "FLOORS_CNT": 1,
          "CONST_MATERIAL": "Frame:  Stucco Or Cement Fiber Siding",
          "CURRENT_ASOF": 1761696000000}
_WEBER_SHED = dict(_WEBER, BUILT_YR=2019, BLDG_SQFT=96, CONST_MATERIAL="Wood Framed")

# Recorded live from Parcels_SaltLake_LIR: a unit in the 27-storey tower at 48 W
# 300 S. FLOORS_CNT is the tower's; HOUSE_CNT (not requested) reads 1.
_CONDO = {"PARCEL_ID": "15012832180000", "PARCEL_ADD": "48 W 300 S # 1706N",
          "PROP_CLASS": "Residential", "BUILT_YR": 1982, "BLDG_SQFT": 1509,
          "BLDG_SQFT_INFO": None, "FLOORS_CNT": 27, "CONST_MATERIAL": "MT",
          "CURRENT_ASOF": 1774483200000}

# Recorded live: a Salt Lake house, one building, the county's two-letter code.
_SL_HOUSE = {"PARCEL_ID": "09323260020000", "PARCEL_ADD": "761 E 6TH AVE",
             "PROP_CLASS": "Residential", "BUILT_YR": 1920, "BLDG_SQFT": 2500,
             "BLDG_SQFT_INFO": None, "FLOORS_CNT": 2, "CONST_MATERIAL": "BR",
             "CURRENT_ASOF": 1774483200000}

# Recorded live: 235 E Hubbard Ave, Salt Lake — a 1918 brick house and a 2021
# frame cottage on one parcel. Two homes, not a house and a shed.
_SL_SECOND_HOUSE = dict(_SL_HOUSE, PARCEL_ID="16071810240000",
                        PARCEL_ADD="235 E HUBBARD AVE", BUILT_YR=1918,
                        BLDG_SQFT=1064, FLOORS_CNT=1, CONST_MATERIAL="BR")
_SL_COTTAGE = dict(_SL_SECOND_HOUSE, BUILT_YR=2021, BLDG_SQFT=416,
                   CONST_MATERIAL="FR")

# A Carbon County house: the one county whose PROP_CLASS says "Single Family".
_CARBON = {"PARCEL_ID": "1A-0123-0004", "PARCEL_ADD": "245 N 300 E",
           "PROP_CLASS": "Single Family", "BUILT_YR": 1948, "BLDG_SQFT": 1160,
           "BLDG_SQFT_INFO": None, "FLOORS_CNT": 1,
           "CONST_MATERIAL": "Masonry:  Common Brick", "CURRENT_ASOF": 1764115200000}

#: A point in Provo. Every test uses the same one: which parcel a coordinate lands
#: in is decided here by the stubbed rows, not by the coordinate.
_POINT = (40.2338, -111.6585)
_UTAH_COUNTY = "49049"


def _lookup(exact, near=(), address=None, county=_UTAH_COUNTY, slices=None,
            params=None, urls=None, county_answer=_UTAH_COUNTY, exceeded=False):
    """Drive ``ut.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` is what the point lands inside; ``near`` what a buffered search
    finds. ``county`` is what the caller passes (None makes the adapter ask the
    boundaries layer, which answers ``county_answer``). ``slices``, ``params`` and
    ``urls`` collect what each request was handed.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if url == ut.COUNTY_URL:
            feats = [{"attributes": {"FIPS_STR": county_answer}}] if county_answer else []
            return {"features": feats}
        if exceeded:
            # What the real get_json raises on ``exceededTransferLimit``.
            raise _shared.TruncatedResponse("services1.arcgis.com: truncated")
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    ut._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return ut.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        ut._lookup_cached.cache_clear()


# ── one row per building ───────────────────────────────────────────────────────


def test_a_house_with_sheds_and_a_garage_is_one_parcel_not_four():
    """Four rows share one PARCEL_ID under one coordinate. Offered to the shared
    chooser as four candidates they are "ambiguous" and the most ordinary house in
    the state is refused; grouped, they are one parcel and the house answers."""
    got = _lookup([_SHED_1, _HOUSE, _SHED_2, _GARAGE], address="924 E 100 N, PROVO, UT")
    assert got is not None
    assert got.parcel_id == "140350270"
    assert got.year_built == 1920 and got.sqft == 1755.0


def test_the_home_is_the_residential_card_not_the_newest_or_largest_building():
    """930 E 100 N: the detached garage is the newer building (2018 against 2013).
    The house is picked because it is the only residential card on the parcel, not
    by any ordering a garage could win."""
    got = _lookup([_ITS_GARAGE, _TWO_STORY])
    assert got is not None and got.year_built == 2013 and got.sqft == 2943.0
    got = _lookup([_TWO_STORY, _ITS_GARAGE])
    assert got is not None and got.year_built == 2013


def test_a_garage_alone_is_not_a_home():
    """A residential parcel whose only building row is a garage — the house filed
    elsewhere, or not yet assessed. The garage's year is not the home's."""
    assert _lookup([_GARAGE]) is None


def test_two_dwellings_on_one_parcel_are_refused():
    """Two residential cards is a house and a second home. Either year could be the
    one the reader means; naming one would be a guess."""
    adu = dict(_HOUSE, BUILT_YR=2019, BLDG_SQFT=820,
               CONST_MATERIAL="Frame:  Metal Vinyl Siding")
    assert _lookup([_HOUSE, adu, _SHED_1]) is None


def test_a_second_house_is_refused_where_the_county_writes_no_residential_card():
    """Salt Lake lists a parcel's second building only when it is another house:
    235 E Hubbard Ave is a 1918 brick house beside a 2021 frame cottage. Without a
    residential-card vocabulary the rule is simply "exactly one building"."""
    assert _lookup([_SL_SECOND_HOUSE, _SL_COTTAGE], county="49035") is None
    one = _lookup([_SL_HOUSE], county="49035")
    assert one is not None and one.year_built == 1920


def test_a_building_repeated_per_polygon_part_is_one_building():
    """A multipart parcel repeats every building once per polygon part — 1190 E 200
    N is 8 rows for 2 buildings. Identical building rows are the same building, so
    the house is still the only residential card."""
    rows = [dict(_HOUSE), dict(_HOUSE), dict(_GARAGE), dict(_GARAGE)]
    got = _lookup(rows)
    assert got is not None and got.year_built == 1920


def test_rows_of_one_parcel_that_disagree_about_its_address_are_not_offered():
    """Each row repeats the parcel's address. Rows of one id naming two buildings
    is a broken join, and confirming the parcel against an address it may not have
    is the wrong-house failure — so the parcel is not a candidate at all, with or
    without an address to confirm against."""
    other = dict(_GARAGE, PARCEL_ADD="926 E 100 N")
    assert _lookup([_HOUSE, other]) is None
    assert _lookup([_HOUSE, other], address="924 E 100 N, PROVO, UT") is None


def test_rows_with_no_parcel_id_are_records_of_nothing():
    blank = dict(_HOUSE, PARCEL_ID=" ", PARCEL_ADD="926 E 100 N")
    got = _lookup([blank, _HOUSE])
    assert got is not None and got.parcel_id == "140350270"


def test_two_different_parcels_at_the_point_are_ambiguous():
    neighbour = dict(_TWO_STORY)
    assert _lookup([_HOUSE, neighbour]) is None


def test_an_off_parcel_geocode_is_confirmed_by_address_in_the_buffer():
    """The ordinary interpolated-geocode case: nothing contains the point, the 80 m
    buffer finds both neighbours, and only the address decides."""
    got = _lookup([], near=[_TWO_STORY, _ITS_GARAGE, _HOUSE, _SHED_1],
                  address="924 E 100 N, PROVO, UT, 84606")
    assert got is not None and got.parcel_id == "140350270"
    assert _lookup([], near=[_TWO_STORY, _HOUSE], address="928 E 100 N, PROVO, UT") is None


def test_a_spelled_out_grid_street_is_the_same_street():
    """Beaver's roll writes "175 E 100 S"; the Census matcher returns "175 E 100
    SOUTH ST". One grid street, two spellings."""
    beaver = dict(_HOUSE, PARCEL_ID="B-1", PARCEL_ADD="175 E 100 S")
    got = _lookup([], near=[beaver], address="175 E 100 SOUTH ST, BEAVER, UT, 84713")
    assert got is not None and got.parcel_id == "B-1"


def test_the_grid_word_is_abbreviated_only_after_a_number():
    """"SOUTH WEBER DR" is a street's name, not a grid direction."""
    assert ut._grid_form("1820 E SOUTH WEBER DR, SOUTH WEBER, UT") == \
        "1820 E SOUTH WEBER DR, SOUTH WEBER, UT"
    assert ut._grid_form("20 E 200 NORTH ST, DUCHESNE, UT") == "20 E 200 N ST, DUCHESNE, UT"
    assert ut._grid_form(None) is None


def test_a_missing_leading_directional_is_still_a_different_address():
    """The commonest mismatch measured: the roll says "1526 E DOWNINGTON AVE", the
    Census matcher returns "1526 DOWNINGTON AVE". It is NOT forgiven, because the
    matcher ignores that directional outright — "571 N 200 W" and "571 S 200 W"
    geocode to the same point — so the point cannot tell which twin is meant."""
    north = dict(_HOUSE, PARCEL_ID="N-571", PARCEL_ADD="571 N 200 W")
    assert _lookup([], near=[north], address="571 200 W, PROVIDENCE, UT, 84332") is None
    assert _lookup([north], address="571 200 W, PROVIDENCE, UT, 84332") is None


def test_a_typed_unit_picks_its_own_parcel_from_a_condominium_stack():
    """947 Canyon Rd, Ogden: six "APT n" parcels share one street address. The unit
    the reader typed is the only thing that can choose between them; the year is
    the building's, and the unit's area is still refused."""
    # Each unit row keeps a one-dwelling style, so the unit in the roll's own
    # address is what refuses the area, not the absence of evidence.
    stack = [dict(_HOUSE, PARCEL_ID=f"13166000{n}", PARCEL_ADD=f"947 CANYON RD APT {n}")
             for n in range(1, 7)]
    got = _lookup([], near=stack, address="947 CANYON RD #3, OGDEN, UT, 84404")
    assert got is not None and got.parcel_id == "131660003"
    assert got.year_built == 1920 and got.sqft is None
    assert _lookup([], near=stack, address="947 CANYON RD, OGDEN, UT, 84404") is None
    assert _lookup([], near=stack, address="947 CANYON RD #9, OGDEN, UT, 84404") is None


def test_a_typed_unit_does_not_discard_a_parcel_that_names_no_unit():
    """The filter drops only parcels naming a DIFFERENT unit. A parcel with no unit
    in its address can still be the reader's building."""
    got = _lookup([_HOUSE], address="924 E 100 N #2, PROVO, UT")
    assert got is not None and got.parcel_id == "140350270"


def test_a_truncated_response_is_no_answer():
    """These layers cap a response at 2,000 rows and write one per building per
    polygon part. A cut-short buffer can drop the second of two parcels sharing an
    address and make the survivor look unique; the shared transport raises on it
    and the adapter fails open."""
    assert _lookup([], near=[_HOUSE], address="924 E 100 N, PROVO, UT",
                   exceeded=True) is None


# Recorded live from Parcels_Kane_LIR: two real Kanab houses whose addresses
# differ only in the order of the grid directions, 45 m and 55 m from one point.
_KANAB_MATCHED = {"PARCEL_ID": "U-C-15", "PARCEL_ADD": "325 N 300 E",
                  "PROP_CLASS": "Residential", "BUILT_YR": 1975, "BLDG_SQFT": 2204,
                  "BLDG_SQFT_INFO": None, "FLOORS_CNT": 1,
                  "CONST_MATERIAL": "Frame:  Synth Plaster (Eifs)",
                  "CURRENT_ASOF": 1761177600000}
_KANAB_TYPED = dict(_KANAB_MATCHED, PARCEL_ID="U-B-11", PARCEL_ADD="325 E 300 N",
                    BUILT_YR=1972, BLDG_SQFT=1808,
                    CONST_MATERIAL="Frame:  Plywood Hardboard")


def test_a_grid_twin_near_the_point_refuses_the_answer():
    """The one wrong parcel the end-to-end run found. Typed "325 E 300 N, Kanab",
    the Census matcher returned "325 N 300 E" — a different real house — and the
    adapter, handed only the matched address, confirmed it. Both houses sit within
    80 m of the point, and the geocoder has shown it cannot say which one is meant,
    so neither is named. Checked for containment and buffer alike."""
    matched = "325 N 300 E, KANAB, UT, 84741"
    assert _lookup([], near=[_KANAB_MATCHED, _KANAB_TYPED], address=matched,
                   county="49025") is None
    assert _lookup([_KANAB_MATCHED], near=[_KANAB_MATCHED, _KANAB_TYPED],
                   address=matched, county="49025") is None


def test_without_a_twin_nearby_the_grid_address_still_answers():
    """Guards the test above from passing vacuously: the same parcel, with only an
    ordinary neighbour in the buffer, resolves."""
    neighbour = dict(_KANAB_TYPED, PARCEL_ID="U-C-16", PARCEL_ADD="345 N 300 E")
    got = _lookup([_KANAB_MATCHED], near=[_KANAB_MATCHED, neighbour],
                  address="325 N 300 E, KANAB, UT, 84741", county="49025")
    assert got is not None and got.parcel_id == "U-C-15" and got.year_built == 1975


def test_twins_are_the_same_number_and_street_with_only_directionals_differing():
    assert ut._directionless("325 N 300 E") == ut._directionless("325 E 300 N")
    assert ut._directionless("1652 S 1100 W") == ut._directionless("1652 N 1100 E")
    assert ut._directionless("1526 E DOWNINGTON AVE") == ut._directionless("1526 DOWNINGTON AVE")
    assert ut._directionless("325 N 300 E") != ut._directionless("345 N 300 E")
    assert ut._directionless("325 N 300 E") != ut._directionless("325 N 400 E")


# ── HOUSE_CNT, and what may say "one dwelling" ─────────────────────────────────


def test_house_cnt_is_never_requested():
    """The schema calls it "Number of Housing Units"; the data counts building rows
    — a house with a shed reads 2, a duplex and every condominium unit read 1. A
    column that never arrives cannot be read by a later edit as a unit count."""
    assert "HOUSE_CNT" not in ut._FIELDS.split(",")


def test_a_house_without_one_dwelling_evidence_reports_its_year_but_not_its_area():
    """Weber writes no building style and its PROP_CLASS "Residential" covers
    duplexes, so nothing in the row says one home. The year is right whatever the
    building holds; the area and storeys are not reported."""
    got = _lookup([_WEBER, _WEBER_SHED], county="49057")
    assert got is not None and got.year_built == 2000
    assert got.sqft is None and got.stories is None


def test_utah_county_multi_unit_styles_refuse_area_and_stories():
    for style in ("duplex", "triplex", "fourplex:_two_story", "12_unit_building",
                  "4_unit_building"):
        got = _lookup([dict(_HOUSE, BLDG_SQFT_INFO=style, BLDG_SQFT=4100)])
        assert got is not None and got.year_built == 1920, style
        assert got.sqft is None and got.stories is None, style


def test_carbon_single_family_is_one_dwelling_evidence():
    got = _lookup([_CARBON], county="49007")
    assert got is not None and got.sqft == 1160.0 and got.stories == 1
    multi = dict(_CARBON, PROP_CLASS="Multi-Family")
    got = _lookup([multi], county="49007")
    assert got is not None and got.year_built == 1948 and got.sqft is None


def test_a_salt_lake_condo_reports_the_towers_year_and_nothing_else():
    """The trap the research memo confirmed live: FLOORS_CNT is 27, the tower's,
    on every unit. The year is the building's and right for every unit; the area
    and the storey count are refused — the unit number in PARCEL_ADD says the row
    is one unit of a larger building."""
    got = _lookup([_CONDO], county="49035", address="48 W 300 S, SALT LAKE CITY, UT")
    assert got is not None and got.year_built == 1982
    assert got.stories is None and got.sqft is None


def test_a_unit_designator_refuses_the_area_even_with_a_one_dwelling_style():
    """Lehi's "4027 W BIG HORN DR UNIT 301" is a condominium unit whose style row
    could read like a house; the unit in the roll's own address is enough."""
    unit = dict(_HOUSE, PARCEL_ADD="924 E 100 N UNIT 3")
    got = _lookup([unit])
    assert got is not None and got.year_built == 1920
    assert got.sqft is None and got.stories is None


def test_stories_need_the_style_and_the_floor_count_to_agree():
    """Utah County records 7,123 "one_story" buildings with FLOORS_CNT 2. Either
    column alone is wrong often enough to matter, so only agreement is reported."""
    assert _lookup([_HOUSE]).stories == 1
    assert _lookup([_TWO_STORY]).stories == 2
    assert _lookup([dict(_HOUSE, FLOORS_CNT=2)]).stories is None
    assert _lookup([dict(_HOUSE, BLDG_SQFT_INFO="split_level", FLOORS_CNT=2)]).stories is None
    split = _lookup([dict(_HOUSE, BLDG_SQFT_INFO="split_level", FLOORS_CNT=2)])
    assert split.sqft == 1755.0, "a split level is still one home"
    assert _lookup([dict(_HOUSE, FLOORS_CNT=1.5)]).stories is None


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, BUILT_YR=0)])
    assert got is not None and got.year_built is None
    assert got.sqft == 1755.0, "the area survives; only the year is missing"


def test_the_adapter_floor_is_the_scorer_floor():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert _lookup([dict(_HOUSE, BUILT_YR=EARLIEST_PLAUSIBLE_YEAR)]).year_built \
        == EARLIEST_PLAUSIBLE_YEAR
    assert _lookup([dict(_HOUSE, BUILT_YR=EARLIEST_PLAUSIBLE_YEAR - 1)]).year_built is None


def test_the_effective_year_is_not_even_requested():
    """EFFBUILT_YR is moved forward when a property is improved — 3913 S 2200 W's
    1946 house reads 1992 — so it describes condition, not when it went up."""
    assert "EFFBUILT_YR" not in ut._FIELDS.split(",")
    assert "BUILT_YR" in ut._FIELDS.split(",")


def test_a_parcel_the_roll_says_is_not_a_home_reports_nothing():
    """The zero-dwelling refusal. PROP_CLASS is the only statement the layer makes
    about it, and an explicit commercial, vacant or exempt class is that statement."""
    for cls in ("Commercial", "Commercial - Retail", "Vacant", "Tax Exempt - Government",
                "Industrial", "Vacant - Commercial", "Personal Property", "Land"):
        assert _lookup([dict(_HOUSE, PROP_CLASS=cls)]) is None, cls


def test_silence_about_the_class_is_not_a_refusal():
    """Utah County files its whole multi-unit stock as "Unknown" (117,386 rows), and
    a farmhouse sits on a greenbelt parcel. Neither says no one lives there."""
    for cls in ("Unknown", None, "", "Greenbelt", "Agricultural", "Mixed Use",
                "Commercial - Apartment & Condo", "PERSONAL PROPERTY MOBILE HOME"):
        got = _lookup([dict(_HOUSE, PROP_CLASS=cls)])
        assert got is not None and got.year_built == 1920, cls


def test_a_parcel_that_records_nothing_is_not_an_answer():
    empty = dict(_WEBER, BUILT_YR=0, CONST_MATERIAL="Frame:  Rustic Log")
    assert _lookup([empty], county="49057") is None


# ── construction ───────────────────────────────────────────────────────────────


def test_unambiguous_walls_translate():
    cases = {
        "Frame:  Metal Vinyl Siding": "frame",
        "Frame:  Stucco or Cement Fiber Siding": "frame",
        "Frame:  Synth Plaster (Eifs)": "frame",
        "Frame:  Brick Veneer": "brick-frame",
        "Masonry:  Common Brick": "brick",
        "Masonry:  Concrete Block": "block",
        "Frame Vinyl": "vinyl",
        "Frame Syn Plaster": "frame",
        "Masonry Stone": "stone",
    }
    for raw, want in cases.items():
        got = _lookup([dict(_HOUSE, CONST_MATERIAL=raw)])
        assert got is not None and got.construction == want, raw


def test_ambiguous_or_unknown_walls_stay_empty():
    """Masonry veneer is a brick OR stone face; a log wall and a manufactured-home
    wall have no value in the label; Salt Lake's codes have no table that matches
    the rows. Each is dropped rather than approximated."""
    for raw in ("Frame:  Masonry Veneer", "Frame:  Stone Veneer", "Frame:  Rustic Log",
                "Masonry:  Face Brick Or Stone", "Masonry:  Poured Concrete",
                "Frame:  Other", "Frame Masonry Veneer"):
        got = _lookup([dict(_HOUSE, CONST_MATERIAL=raw)])
        assert got is not None and got.construction is None, raw
    for code in ("SO", "BR", "AL", "FR", "SC", "BL", "MT", "ST"):
        got = _lookup([dict(_SL_HOUSE, CONST_MATERIAL=code)], county="49035")
        assert got is not None and got.construction is None, code


def test_a_manufactured_home_is_not_called_a_frame_house():
    mh = dict(_HOUSE, CONST_MATERIAL="2 X 4: Lap Siding",
              BLDG_SQFT_INFO="one-section_16'_wide", BLDG_SQFT=1100)
    got = _lookup([mh, _SHED_1])
    assert got is not None and got.construction is None
    assert got.year_built == 1920 and got.sqft == 1100.0, "still one home, still its year"


def test_every_translation_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import CONSTRUCTION_VALUES
    assert set(ut._CONSTRUCTION.values()) <= CONSTRUCTION_VALUES


# ── the vintage ────────────────────────────────────────────────────────────────


def test_the_rows_own_date_travels_with_the_value():
    """Box Elder's rows are current as of 2020 and Salt Lake's as of 2026, under
    one template URL; a hard-coded year would hide that."""
    assert "current as of 2025-10-30" in _lookup([_HOUSE]).data_vintage
    old = dict(_HOUSE, CURRENT_ASOF=1594944000000)
    assert "current as of 2020-07-17" in _lookup([old]).data_vintage
    none = _lookup([dict(_HOUSE, CURRENT_ASOF=None)])
    assert none.data_vintage == ut.DATA_VINTAGE


# ── the field list ─────────────────────────────────────────────────────────────


def test_the_field_list_is_explicit_and_carries_nothing_private():
    fields = ut._FIELDS.split(",")
    for private in ("*", "PRIMARY_RES", "TOTAL_MKT_VALUE", "LAND_MKT_VALUE",
                    "SERIAL_NUM", "TAXEXEMPT_TYPE", "OWNER", "OWN_NAME"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    params, urls = [], []
    _lookup([_HOUSE], params=params, urls=urls, county=None)
    parcel_requests = [p for p, u in zip(params, urls) if u != ut.COUNTY_URL]
    assert parcel_requests and all(p["outFields"] == ut._FIELDS for p in parcel_requests)
    county_requests = [p for p, u in zip(params, urls) if u == ut.COUNTY_URL]
    assert county_requests and all(p["outFields"] == "FIPS_STR" for p in county_requests)


# ── the county, and the 29 services ────────────────────────────────────────────


def test_every_utah_county_has_a_service_and_the_set_matches_the_county_table():
    """Checked against the Census-derived county table this repository ships."""
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("49") and len(r["geoid"]) == 5}
    assert len(census) == 29, f"expected 29 Utah counties, got {len(census)}"
    assert set(ut.COUNTY_SERVICES) == census
    assert ut.COUNTY_FIPS == census - ut._NOTHING_TO_SAY


def test_the_service_table_follows_ugrcs_own_county_numbering():
    """UGRC numbers counties alphabetically, Beaver = 1 … Weber = 29, and FIPS codes
    are the odd numbers in the same order — two independent orderings that must
    agree, which catches a transposed pair in a hand-typed table."""
    services = [ut.COUNTY_SERVICES[f] for f in sorted(ut.COUNTY_SERVICES)]
    names = [s.removeprefix("Parcels_").removesuffix("_LIR") for s in services]
    assert names == sorted(names)
    assert sorted(ut.COUNTY_SERVICES) == [f"49{n:03d}" for n in range(1, 58, 2)]


def test_juab_is_not_claimed_because_it_publishes_nothing_the_label_can_use():
    """Juab's layer has no year built, no material, and no one-dwelling evidence
    for its floor areas, so a lookup there could only spend requests to return
    nothing."""
    assert "49023" not in ut.COUNTY_FIPS
    assert "49023" in ut.COUNTY_SERVICES


def test_the_callers_county_picks_the_service_and_skips_the_boundary_request():
    urls = []
    _lookup([_SL_HOUSE], county="49035", urls=urls)
    assert ut.COUNTY_URL not in urls
    assert urls and all("/Parcels_SaltLake_LIR/" in u for u in urls)


def test_without_a_county_the_point_is_located_first():
    urls = []
    got = _lookup([_HOUSE], county=None, urls=urls, county_answer="49049")
    assert got is not None
    assert urls[0] == ut.COUNTY_URL
    assert all("/Parcels_Utah_LIR/" in u for u in urls[1:])


def test_a_point_outside_utah_is_no_answer():
    assert _lookup([_HOUSE], county=None, county_answer=None) is None
    assert _lookup([_HOUSE], county=None, county_answer="56041") is None


def test_a_county_this_adapter_does_not_claim_is_located_rather_than_trusted():
    urls = []
    _lookup([_HOUSE], county="17031", urls=urls)
    assert urls[0] == ut.COUNTY_URL


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_request_passes_the_modules_read_slice():
    slices = []
    assert _lookup([_HOUSE], slices=slices, county=None) is not None
    assert slices and all(s == ut.READ_SLICE_S for s in slices), slices


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to fit.
    Pinned against the host constant, not a literal."""
    from housing_label import config
    assert ut.LOOKUP_TIMEOUT + ut.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_every_request_shares_one_clock_started_once():
    """County, containment and buffer all run against one deadline — the budget is a
    ceiling on the whole lookup, not an allowance each request gets afresh."""
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        if url == ut.COUNTY_URL:
            return {"features": [{"attributes": {"FIPS_STR": "49049"}}]}
        return {"features": []}

    ut._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        ut.lookup(*_POINT, "924 E 100 N, PROVO, UT")
    finally:
        _shared.get_json = saved
        ut._lookup_cached.cache_clear()
    assert len(seen) == 3, f"expected county, containment and buffer, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs((seen[0] - started) - ut.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    ut._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert ut.lookup(*_POINT, "924 E 100 N, PROVO, UT") is None
        assert ut.lookup(*_POINT, "924 E 100 N, PROVO, UT", "49049") is None
    finally:
        _shared.get_json = saved
        ut._lookup_cached.cache_clear()


def test_garbage_coordinates_fail_open():
    assert ut.lookup("not a number", None) is None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None
