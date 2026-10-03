#!/usr/bin/env python3
"""The Maryland adapter — one statewide layer, and the five things it has to refuse.

Nothing here touches the network. The state's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"Maryland has no record here" and would never announce itself. A test that called
the real service would pass just as quietly.

What is worth pinning is what is genuinely Maryland's. The dangerous shared parts —
choosing which parcel an address means, comparing two addresses, bounding the
request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

Maryland's own five:

1. The ``ADDRESS`` column is the **owner's mailing address** on 1,438 parcels, and
   must never be fetched, let alone confirmed against.
2. Rights of way, water and condominium **common elements** are polygons with a
   word where the account should be.
3. Each **condominium unit** is its own account with its own small square inside
   the building: the unit's floor area is right only for the unit the reader typed,
   and seven squares at one address are one building, not seven rivals.
4. A record the roll describes as a **store or an office** is not anybody's home,
   though no dwelling count says zero.
5. The floor area is a **property total** where there is more than one building.

This file alone: ``pytest tests/test_assessor_md.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent

from housing_label.enrich import assessor as A
from housing_label.enrich.assessor import _shared, md
from housing_label.enrich.assessor.base import CONSTRUCTION_VALUES

# Recorded live from MD_ParcelBoundaries. A single-family house in Harford County:
# one unit, so its enclosed area is that home's. SDATDATE as the layer carried it on
# 2026-10-03.
_HOUSE = {"ACCTID": "1301189425", "ADDRTYP": "P", "RESITYP": "SF",
          "ADDRESS": "1202 ASHMEAD SQ", "STRTUNT": None, "YEARBLT": "1989",
          "SQFTSTRC": 1822, "DESCCNST": "CNST Siding",
          "DESCSTYL": "STRY 2 Story With Basement", "DESCBLDG": "DWEL Standard Unit",
          "BLDG_UNITS": 1, "SDATDATE": "2026MAY"}

# Recorded live. Two of the seven condominium units at 43 S Prospect St, Hagerstown:
# a small square each, one street address, one year, two very different areas.
_UNIT_3 = {"ACCTID": "2203032582", "ADDRTYP": "P", "RESITYP": "CN",
           "ADDRESS": "43 S PROSPECT ST", "STRTUNT": "UNIT 3", "YEARBLT": "2005",
           "SQFTSTRC": 567, "DESCCNST": None, "DESCSTYL": None,
           "DESCBLDG": "DWEL Condo Garden", "BLDG_UNITS": 1, "SDATDATE": "2026MAY"}
_UNIT_5 = dict(_UNIT_3, ACCTID="2203032604", STRTUNT="UNIT 5", SQFTSTRC=1178)
_UNIT_7 = dict(_UNIT_3, ACCTID="2203032620", STRTUNT="UNIT 7", SQFTSTRC=1311)

# Recorded live, beside those units: the polygon for the building's common elements,
# and a real account that is the common area of the condominium next door.
_COMMON = {"ACCTID": "COMMON", "ADDRTYP": None, "RESITYP": None, "ADDRESS": None,
           "STRTUNT": None, "YEARBLT": None, "SQFTSTRC": None}
_COMMON_AREA = {"ACCTID": "2203007359", "ADDRTYP": "P", "RESITYP": None,
                "ADDRESS": "37 S PROSPECT ST", "STRTUNT": "COMMON AREA",
                "YEARBLT": None, "SQFTSTRC": None}
_ROW = {"ACCTID": "ROW", "ADDRTYP": None, "ADDRESS": None, "YEARBLT": None}

# Recorded live. 401 Naylor St, Wicomico: a 1920 house of 1,868 ft² and a 1988 one of
# 1,456 on one account. SQFTSTRC is their sum; YEARBLT is the first building's.
_TWO_HOUSES = {"ACCTID": "2305006783", "ADDRTYP": "P", "RESITYP": "SF",
               "ADDRESS": "401 NAYLOR ST", "STRTUNT": None, "YEARBLT": "1920",
               "SQFTSTRC": 3324, "DESCCNST": "CNST Frame",
               "DESCSTYL": "STRY 2 Story With Basement",
               "DESCBLDG": "DWEL Standard Unit", "BLDG_UNITS": 2,
               "SDATDATE": "2026MAY"}

# The shape of a plain commercial parcel as the layer returns it — Planning gives it no
# residential class and SDAT describes the building as a store. The year is what
# 34,031 commercial polygons carry; the row itself is composed, not recorded.
_SHOP = {"ACCTID": "0205000049378", "ADDRTYP": "P", "RESITYP": None,
         "ADDRESS": "172 MAIN ST", "STRTUNT": None, "YEARBLT": "1900",
         "SQFTSTRC": 11115, "DESCCNST": None, "DESCSTYL": "STORE Retail Store",
         "DESCBLDG": "STORE Retail Store", "BLDG_UNITS": 1, "SDATDATE": "2026MAY"}

#: A point in Bel Air. Every test uses the same one: which parcel a coordinate lands
#: in is decided here by the stubbed rows, not by the coordinate.
_POINT = (39.5359, -76.3483)


def _lookup(exact, near=(), address=None, slices=None, params=None, points=(),
            urls=None):
    """Drive ``md.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search of
    the polygons would find; ``points`` is what a buffered search of the account
    points would find. All are answered through the real transport helper, so the
    field list, the predicate, the drops and the parcel selection are exercised.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if url == md.POINTS_URL:
            assert request.get("distance"), "a point is never inside anything"
            rows = list(points)
        else:
            rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    md._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return md.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        md._lookup_cached.cache_clear()


# ── the ordinary house ─────────────────────────────────────────────────────────


def test_a_house_reports_everything_the_roll_carries():
    got = _lookup([_HOUSE], address="1202 ASHMEAD SQ, BEL AIR, MD, 21015")
    assert got is not None
    assert got.parcel_id == "1301189425"
    assert got.year_built == 1989
    assert got.sqft == 1822.0
    assert got.stories == 2
    assert got.construction == "frame"
    assert got.foundation is None and got.condition is None


def test_the_sdat_month_travels_with_the_value():
    """SDATDATE advances under an unchanged URL; a hard-coded date would go stale
    silently and present old data at the confidence of fresh."""
    got = _lookup([_HOUSE])
    assert got is not None and got.data_vintage.endswith("SDAT data of 2026-05")
    bare = _lookup([dict(_HOUSE, SDATDATE=None)])
    assert bare is not None and bare.data_vintage == md.DATA_VINTAGE


def test_a_parcel_that_records_nothing_at_all_is_not_an_answer():
    empty = dict(_HOUSE, YEARBLT="0000", SQFTSTRC=0, DESCSTYL="STRY Split Foyer",
                 DESCCNST="CNST Stucco")
    assert _lookup([empty]) is None


# ── 1. the address that is sometimes the owner's ───────────────────────────────


def test_owner_derived_addresses_are_excluded_in_the_request_itself():
    """ADDRESS is filled from the owner's mailing address line where SDAT has no
    premise address (ADDRTYP 'O'). Discarding it after it arrives would still be
    fetching a mailing address, so the predicate keeps it out of the response."""
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["where"] == md._WHERE for p in params)
    assert "ADDRTYP <> 'O'" in md._WHERE


def test_an_owner_derived_row_is_refused_even_if_the_server_ignored_the_predicate():
    """Belt and braces: a row whose address came from the owner can only ever be
    confirmed against an address that is not the property's."""
    owners = dict(_HOUSE, ADDRTYP="O")
    assert _lookup([owners]) is None
    assert _lookup([], near=[owners], address="1202 ASHMEAD SQ, BEL AIR, MD") is None


def test_the_field_list_is_the_privacy_boundary():
    """The layer carries owner mailing address fields, the last sale and every
    assessed value. None of it is an input to any dimension."""
    fields = md._FIELDS.split(",")
    for private in ("OWNADD1", "OWNADD2", "OWNCITY", "OWNSTATE", "OWNERZIP",
                    "OWNZIP2", "TRADATE", "CONSIDR1", "NFMTTLVL", "NFMIMPVL",
                    "NFMLNDVL", "OOI", "CITY", "ZIPCODE", "*"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    """Pinned on what the transport is handed, not on the constant."""
    params = []
    _lookup([], near=[_HOUSE], address="1202 ASHMEAD SQ, BEL AIR, MD", params=params)
    assert len(params) == 2
    assert all(p["outFields"] == md._FIELDS for p in params)
    assert all(p.get("outSR") == "4326" for p in params)


def test_the_quality_grade_is_not_even_requested():
    """STRUGRAD is SDAT's grade — quality of construction, Low to Superior — not the
    state of repair the label's condition means. Not requested, so a later edit
    cannot read it by mistake."""
    assert "STRUGRAD" not in md._FIELDS.split(",")
    assert "DESCGRAD" not in md._FIELDS.split(",")


# ── 2. placeholders and common elements ────────────────────────────────────────


def test_a_placeholder_polygon_is_not_a_record():
    for row in (_ROW, _COMMON, {"ACCTID": None}, {"ACCTID": "WATER"},
                {"ACCTID": "C001601"}):
        assert not md._is_candidate(row), row


def test_a_placeholder_does_not_make_a_real_parcel_ambiguous():
    """A right-of-way polygon overlapping the house would otherwise be a second
    candidate, and the shared chooser would — correctly — give up."""
    got = _lookup([_HOUSE, _ROW])
    assert got is not None and got.year_built == 1989


def test_a_condominiums_common_area_account_is_not_a_home():
    """It is a real account at the building's street address, so leaving it in would
    sit beside the units as a rival candidate."""
    assert not md._is_candidate(_COMMON_AREA)


def test_real_account_formats_from_every_jurisdiction_pass():
    """Baltimore City's accounts carry a space and letters; Anne Arundel's run to
    fifteen digits. Only the jurisdiction code and district digits are checked."""
    for acct in ("0312023690 001", "0327595210C108", "020600004937800",
                 "160203031873", "2410226074"):
        assert md._account({"ACCTID": acct}) == acct


# ── 3. condominium units ───────────────────────────────────────────────────────


def test_a_square_the_geocode_lands_in_gives_the_year_but_not_the_area():
    """The squares are symbols, not floor plans: landing in unit 3's says nothing
    about which unit is the reader's. The building's year is right for every unit."""
    got = _lookup([_UNIT_3], address="43 S PROSPECT ST, HAGERSTOWN, MD")
    assert got is not None and got.year_built == 2005
    assert got.sqft is None and got.stories is None
    assert got.parcel_id is None, "the account is unit 3's, not the reader's"


def test_units_of_one_building_fold_into_one_year():
    """Seven records at one address are one building to the reader, and seven
    rivals to the shared chooser. Folded first, the year comes through — and only
    the year: no account, no area."""
    got = _lookup([_COMMON], near=[_UNIT_3, _UNIT_5, _UNIT_7, _COMMON_AREA],
                  address="43 S PROSPECT ST, HAGERSTOWN, MD, 21740")
    assert got is not None
    assert got.year_built == 2005
    assert got.parcel_id is None and got.sqft is None and got.stories is None


def test_units_that_disagree_about_the_year_answer_nothing():
    other = dict(_UNIT_7, YEARBLT="2008")
    assert _lookup([], near=[_UNIT_3, _UNIT_5, other],
                   address="43 S PROSPECT ST, HAGERSTOWN, MD") is None


def test_a_unit_that_records_no_year_does_not_veto_the_others():
    silent = dict(_UNIT_7, YEARBLT=None)
    got = _lookup([], near=[_UNIT_3, _UNIT_5, silent],
                  address="43 S PROSPECT ST, HAGERSTOWN, MD")
    assert got is not None and got.year_built == 2005


def test_the_typed_unit_picks_its_own_record_and_its_own_area():
    got = _lookup([], near=[_UNIT_3, _UNIT_5, _UNIT_7],
                  address="43 S PROSPECT ST #5, HAGERSTOWN, MD, 21740")
    assert got is not None
    assert got.parcel_id == "2203032604"
    assert got.sqft == 1178.0


def test_a_typed_unit_the_roll_does_not_have_still_gets_the_building_year():
    got = _lookup([], near=[_UNIT_3, _UNIT_5, _UNIT_7],
                  address="43 S PROSPECT ST #12, HAGERSTOWN, MD")
    assert got is not None and got.year_built == 2005
    assert got.sqft is None and got.parcel_id is None


def test_two_records_of_the_same_unit_are_ambiguous_not_a_tie_to_break():
    twin = dict(_UNIT_5, ACCTID="2203099999", SQFTSTRC=700)
    got = _lookup([], near=[_UNIT_5, twin],
                  address="43 S PROSPECT ST #5, HAGERSTOWN, MD")
    assert got is None or got.sqft is None


def test_a_unit_at_a_different_address_is_not_the_typed_unit():
    elsewhere = dict(_UNIT_5, ADDRESS="37 S PROSPECT ST")
    assert _lookup([], near=[elsewhere],
                   address="43 S PROSPECT ST #5, HAGERSTOWN, MD") is None


def test_only_a_marked_unit_field_is_a_unit():
    """Address ranges, rear lots and boat slips sit in the same column."""
    assert md._row_unit({"STRTUNT": "UNIT 505"}) == "505"
    assert md._row_unit({"STRTUNT": "# 2"}) == "2"
    assert md._row_unit({"STRTUNT": "APT R1"}) == "R1"
    assert md._row_unit({"STRTUNT": "STE 9A"}) == "9A"
    for not_a_unit in ("114-116", "REAR", "BOAT SLIP B3", "OPEN SPACE",
                       "918-920-928", "PARKING SPC 10", None, ""):
        assert md._row_unit({"STRTUNT": not_a_unit}) is None, not_a_unit


def test_a_condominium_without_a_unit_field_is_still_a_unit_record():
    """Howard County writes the unit into the house number ("7434B"), leaving
    STRTUNT blank. The class says condominium, and that is enough to refuse an area
    nobody confirmed."""
    howard = dict(_UNIT_3, STRTUNT=None, ADDRESS="7434B SAINT MARGARETS BLVD",
                  SQFTSTRC=1651)
    got = _lookup([howard])
    assert got is not None and got.year_built == 2005 and got.sqft is None


# ── accounts with no polygon ───────────────────────────────────────────────────

# Recorded live from MD_PropertyData (Parcel Points). Two of the units of 5600
# Wisconsin Ave, Chevy Chase: Montgomery County draws no square per unit — the
# polygon at the building is a condominium-regime placeholder ("C001670") — and
# stacks the unit points at one spot inside it.
_PT_106 = {"ACCTID": "160702782585", "ADDRTYP": "P", "RESITYP": "CN",
           "ADDRESS": "5600 WISCONSIN AVE", "STRTUNT": "UNIT 106", "YEARBLT": "1988",
           "SQFTSTRC": 2278, "DESCCNST": None, "DESCSTYL": None,
           "DESCBLDG": "DWEL Condo Hi Rise", "BLDG_UNITS": 1, "SDATDATE": "2026MAY"}
_PT_107 = dict(_PT_106, ACCTID="160702782596", STRTUNT="UNIT 107", SQFTSTRC=2099)
_REGIME = {"ACCTID": "C001670", "ADDRTYP": None, "ADDRESS": None, "YEARBLT": None}


def test_a_condominium_unit_with_no_polygon_is_found_among_the_account_points():
    """About 100,000 condominium units — 41,357 in Montgomery alone against 547
    squares — exist only as points. Without the fallback the whole of a
    Montgomery high-rise reads as "no record"."""
    urls = []
    got = _lookup([_REGIME], points=[_PT_106, _PT_107],
                  address="5600 WISCONSIN AVE #107, CHEVY CHASE, MD, 20815", urls=urls)
    assert got is not None
    assert got.parcel_id == "160702782596" and got.sqft == 2099.0
    assert urls[-1] == md.POINTS_URL


def test_the_points_fold_a_building_exactly_as_the_polygons_do():
    got = _lookup([_REGIME], points=[_PT_106, _PT_107],
                  address="5600 WISCONSIN AVE, CHEVY CHASE, MD, 20815")
    assert got is not None and got.year_built == 1988
    assert got.sqft is None and got.parcel_id is None


def test_the_typed_unit_is_looked_for_among_the_points_before_the_building():
    """1 Ginford Pl, Catonsville, is one polygon labeled with unit 202's account;
    unit 102 exists only among the points. Asking the polygons about the building
    first would answer the reader in 102 with 202's account (measured live: four of
    50 random condominium units got another unit's account that way)."""
    poly_202 = dict(_UNIT_3, ACCTID="04012100013589", ADDRESS="1 GINFORD PL",
                    STRTUNT="UNIT 202", YEARBLT="1989", SQFTSTRC=1100)
    pt_102 = dict(poly_202, ACCTID="04012100013585", STRTUNT="UNIT 102", SQFTSTRC=950)
    got = _lookup([poly_202], points=[pt_102, poly_202],
                  address="1 GINFORD PL #102, CATONSVILLE, MD, 21228")
    assert got is not None
    assert got.parcel_id == "04012100013585" and got.sqft == 950.0


def test_a_building_polygon_carrying_one_units_account_gives_only_the_year():
    """Where the typed unit is in neither source, the polygon still names the
    building: its year, and not the account of whichever unit labels it."""
    poly_1a = dict(_UNIT_3, ACCTID="1114321381", ADDRESS="3860 SHADYWOOD DR",
                   STRTUNT="UNIT 1A", YEARBLT="1992", SQFTSTRC=1200)
    got = _lookup([poly_1a], points=[],
                  address="3860 SHADYWOOD DR #2D, JEFFERSON, MD, 21755")
    assert got is not None and got.year_built == 1992
    assert got.parcel_id is None and got.sqft is None


def test_the_points_are_not_asked_when_a_polygon_was_chosen():
    """Never instead of a polygon's answer — and not when the chosen polygon
    recorded nothing either, since its point is the same account."""
    urls = []
    _lookup([_HOUSE], points=[dict(_HOUSE, YEARBLT="1950")], urls=urls)
    assert md.POINTS_URL not in urls
    urls = []
    blank = dict(_HOUSE, YEARBLT=None, SQFTSTRC=None, DESCSTYL=None, DESCCNST=None)
    got = _lookup([blank], points=[_HOUSE],
                  address="1202 ASHMEAD SQ, BEL AIR, MD", urls=urls)
    assert got is None and md.POINTS_URL not in urls


def test_the_points_are_not_asked_without_an_address():
    """A point is reachable only by the address-confirmed buffer, so with nothing to
    confirm against there is nothing to ask."""
    urls = []
    assert _lookup([_REGIME], points=[_PT_106], urls=urls) is None
    assert md.POINTS_URL not in urls


def test_the_points_refuse_a_duplicate_address_like_the_polygons():
    twin = dict(_HOUSE, ACCTID="1301189499", YEARBLT="1990")
    assert _lookup([], points=[_HOUSE, twin],
                   address="1202 ASHMEAD SQ, BEL AIR, MD") is None


# ── 4. records that are not homes ──────────────────────────────────────────────


def test_a_store_is_not_anybodys_home():
    """No dwelling count in this roll says zero, so the refusal reads the building
    type the roll does record."""
    assert _lookup([_SHOP]) is None
    assert _lookup([_SHOP], address="172 MAIN ST, ANNAPOLIS, MD") is None


def test_a_store_planning_classes_as_residential_is_kept():
    """172 Main St, Annapolis, is a store with apartments upstairs, and Planning
    gives it a residential class. The class is the statement that a home is here."""
    upstairs = dict(_SHOP, RESITYP="AP", BLDG_UNITS=2)
    got = _lookup([upstairs])
    assert got is not None and got.year_built == 1900 and got.sqft is None


def test_a_record_that_says_nothing_about_its_building_is_let_through():
    silent = dict(_HOUSE, RESITYP=None, DESCBLDG=None)
    got = _lookup([silent])
    assert got is not None and got.year_built == 1989


def test_a_condominium_boat_slip_is_not_a_dwelling_whatever_its_keyword():
    for kind in ("DWEL Boat Slip", "DWEL Storage Unit", "DWEL Parking Space"):
        assert _lookup([dict(_UNIT_3, DESCBLDG=kind)]) is None, kind


def test_an_explicit_zero_units_is_refused():
    assert _lookup([dict(_HOUSE, BLDG_UNITS=0)]) is None


# ── 5. the floor area that is a total ──────────────────────────────────────────


def test_two_dwellings_refuse_the_area_and_keep_the_year():
    got = _lookup([_TWO_HOUSES])
    assert got is not None and got.year_built == 1920
    assert got.sqft is None and got.stories is None


def test_an_unrecorded_unit_count_is_not_a_count_of_one():
    got = _lookup([dict(_HOUSE, BLDG_UNITS=None)])
    assert got is not None and got.year_built == 1989
    assert got.sqft is None


# ── the year built ─────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero():
    got = _lookup([dict(_HOUSE, YEARBLT="0000")])
    assert got is not None and got.year_built is None
    assert got.sqft == 1822.0, "the area survives; only the year is missing"


def test_a_colonial_year_survives_and_the_floor_is_the_scorers():
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    old = _lookup([dict(_HOUSE, YEARBLT="1680")])
    assert old is not None and old.year_built == 1680
    below = _lookup([dict(_HOUSE, YEARBLT=str(EARLIEST_PLAUSIBLE_YEAR - 1))])
    assert below is not None and below.year_built is None


# ── two spellings the roll and the geocoder disagree on ────────────────────────


def test_saint_in_the_roll_matches_st_from_the_geocoder():
    """Measured: three of 150 random Maryland homes failed to confirm on "9205 SAINT
    ANDREWS PL" against the Census matcher's "9205 ST ANDREWS PL", with the right
    polygon inside the buffer each time."""
    saint = dict(_HOUSE, ADDRESS="9205 SAINT ANDREWS PL")
    got = _lookup([], near=[saint], address="9205 ST ANDREWS PL, COLLEGE PARK, MD, 20740")
    assert got is not None and got.year_built == 1989


def test_a_spelled_out_prefix_directional_matches_its_letter():
    """"1438 NORTH BEND RD" in the roll, "1438 N BEND RD" from the matcher — and the
    point was inside the right polygon, refused only on the spelling."""
    north = dict(_HOUSE, ADDRESS="1438 NORTH BEND RD")
    got = _lookup([north], address="1438 N BEND RD, JARRETTSVILLE, MD, 21084")
    assert got is not None and got.year_built == 1989


def test_the_rewrites_do_not_loosen_the_comparison():
    """"North" as a street's own name is not a directional; a different house number
    or street type still never matches; SAINT as the last word is not "ST"."""
    assert not _shared.same_address("100 N ST", "100 NORTH ST")
    assert not _shared.same_address("9207 ST ANDREWS PL", "9205 SAINT ANDREWS PL")
    assert not _shared.same_address("9205 ST ANDREWS CT", "9205 SAINT ANDREWS PL")
    assert not _shared.same_address("12 SAINT", "12 ST")


# ── stories and construction ───────────────────────────────────────────────────


def test_only_a_whole_story_count_is_a_story_count():
    for style, want in (("STRY 1 Story No Basement", 1),
                        ("STRY Townhouse-End Unit 3 Story No Basement", 3),
                        ("STRY Townhouse-Center Unit 2 Story With Basem", 2),
                        ("STRY 1.5 Story With Basement", None),
                        ("STRY 2.5 Story No Basement", None),
                        ("STRY Split Foyer", None),
                        ("HOUSING Condominium (residential)", None)):
        got = _lookup([dict(_HOUSE, DESCSTYL=style)])
        assert got is not None and got.stories == want, style


def test_the_basement_words_are_not_read_as_a_foundation():
    """"With Basement" does not say full or partial; "No Basement" does not say slab
    or crawlspace. The label distinguishes both."""
    for style in ("STRY 2 Story With Basement", "STRY 1 Story No Basement"):
        got = _lookup([dict(_HOUSE, DESCSTYL=style)])
        assert got is not None and got.foundation is None


def test_the_ambiguous_masonry_words_are_not_translated():
    """The residential list has one brick code and one stone code, covering solid
    masonry and veneer on frame alike — exactly the difference between the label's
    brick and brick-frame."""
    for wall in ("CNST Brick", "CNST Stone", "CNST Stucco", "CNST Brick Face",
                 "CNST 1/2 Stone Frame", "CNST 1/2 Stone Siding", "CNST Log",
                 "CNST Concrete", "CNST Metal", None):
        got = _lookup([dict(_HOUSE, DESCCNST=wall)])
        assert got is not None and got.construction is None, wall


def test_the_mapped_walls_speak_the_labels_vocabulary():
    assert set(md._CONSTRUCTION.values()) <= CONSTRUCTION_VALUES
    for wall, want in (("CNST 1/2 Brick Frame", "brick-frame"),
                       ("CNST 1/2 Brick Siding", "brick-frame"),
                       ("CNST Block", "block"), ("CNST Frame", "frame"),
                       ("CNST Shingle Asbestos", "frame")):
        got = _lookup([dict(_HOUSE, DESCCNST=wall)])
        assert got is not None and got.construction == want, wall


# ── the county list ────────────────────────────────────────────────────────────


def test_every_maryland_jurisdiction_is_covered_and_no_other_county_is():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        census = {r["geoid"] for r in csv.DictReader(fh)
                  if r["geoid"].startswith("24") and len(r["geoid"]) == 5}
    assert len(census) == 24, f"expected 23 counties and Baltimore City, got {len(census)}"
    assert md.COUNTY_FIPS == census


def test_the_two_codes_a_rule_gets_wrong():
    """24007 was never assigned, and Baltimore City sits outside the odd run."""
    assert "24007" not in md.COUNTY_FIPS
    assert "24510" in md.COUNTY_FIPS, "Baltimore City"
    assert "24005" in md.COUNTY_FIPS, "Baltimore County"


def test_maryland_claims_no_county_another_adapter_answers_for():
    for mod in set(A.ADAPTERS.values()):
        if mod is md:
            continue
        assert not (md.COUNTY_FIPS & mod.COUNTY_FIPS), mod.__name__


# ── the clock ──────────────────────────────────────────────────────────────────


def test_maryland_asks_for_its_own_read_slice_not_the_shared_one():
    """The buffered tail measured 0.90–0.95 s on dense Baltimore blocks, a
    twentieth of a second inside the shared one-second slice."""
    slices = []
    got = _lookup([], near=[_HOUSE], address="1202 ASHMEAD SQ, BEL AIR, MD",
                  slices=slices)
    assert got is not None
    assert slices and all(s == md.READ_SLICE_S for s in slices), slices
    assert md.READ_SLICE_S > _shared._READ_SLICE_S


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    from housing_label import config
    assert md.LOOKUP_TIMEOUT + md.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET, (
        f"worst case {md.LOOKUP_TIMEOUT + md.READ_SLICE_S}s is not under the "
        f"{config.UPSTREAM_HOST_BUDGET}s this host allows one service")


def test_both_passes_share_their_requests_and_one_clock():
    """A typed unit runs two selection passes; each fetch is memoized so the second
    pass costs nothing, and every request is handed the same deadline."""
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    md._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        md.lookup(*_POINT, "43 S PROSPECT ST #5, HAGERSTOWN, MD")
    finally:
        _shared.get_json = saved
        md._lookup_cached.cache_clear()

    # Containment and buffer on the polygons, then the buffer on the account points
    # because the polygons chose nothing. Not four: the unit pass and the ordinary
    # pass share each fetch.
    assert len(seen) == 3, f"expected three requests, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs((seen[0] - started) - md.LOOKUP_TIMEOUT) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: Failed to execute query.")

    md._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert md.lookup(*_POINT, "1202 ASHMEAD SQ, BEL AIR, MD") is None
    finally:
        _shared.get_json = saved
        md._lookup_cached.cache_clear()


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


def test_two_houses_containing_the_point_are_ambiguous_and_refused():
    other = dict(_HOUSE, ACCTID="1301189426", ADDRESS="1204 ASHMEAD SQ")
    assert _lookup([_HOUSE, other]) is None


def test_the_neighbors_house_is_not_confirmed_against_this_address():
    """The geocode can land inside the neighbor's polygon. A sole containing parcel
    whose address disagrees is not evidence, and the buffer must find the right one
    by address or nothing."""
    neighbor = dict(_HOUSE, ACCTID="1301189426", ADDRESS="1204 ASHMEAD SQ",
                     YEARBLT="1975")
    got = _lookup([neighbor], near=[neighbor, _HOUSE],
                  address="1202 ASHMEAD SQ, BEL AIR, MD")
    assert got is not None and got.parcel_id == "1301189425"
    assert got.year_built == 1989
