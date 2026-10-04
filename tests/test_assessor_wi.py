#!/usr/bin/env python3
"""The Wisconsin adapter — two city rolls, both configured and both held.

Nothing here touches the network. Each city's service is stubbed with row
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"no record here" and would never announce itself.

The dangerous shared parts — choosing which parcel an address means, comparing two
addresses, bounding the request budget — live in ``_shared`` and are tested
against Cook in ``test_assessor.py``. What is pinned here is Wisconsin's own:

1. **The hold.** Neither county is registered: each roll covers one city, 61% of
   Milwaukee County's homes and 51% of Dane County's. A held county answers
   nothing and costs no request. Every other test lifts the hold (``_lifted``),
   because the configuration is meant to be ready the day a decision registers it.
2. **Milwaukee's duplex ranges** (9371-9373), house-number suffixes (923A) and
   its own street-type codes (BL, CR, LA, PK, TR, WA).
3. **Street names the matcher spells differently** in both cities, offered under
   both spellings.
4. **Condominiums**: units stacked on one outline, merged into their building
   where they agree on the year, never reporting an area.
5. **Explicit zeros** and non-home land uses refuse the year.
6. Each city has its own **clock**.

This file alone: ``pytest tests/test_assessor_wi.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

import pytest

from housing_label.enrich.assessor import _shared, wi
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

_ROOT = pathlib.Path(__file__).resolve().parent.parent

MILWAUKEE, DANE = "55079", "55025"

# ── rows recorded live, 2026-10-04 ─────────────────────────────────────────────


def _mke(**kw):
    """A Milwaukee MPROP row: a single-family house on N 51st Blvd by default."""
    row = {"TAXKEY": "0840193000", "HOUSE_NR_LO": 7609, "HOUSE_NR_HI": 7609,
           "HOUSE_NR_SFX": "", "SDIR": "N", "STREET": "51ST", "STTYPE": "BL", "UNIT": "",
           "LAND_USE": 8810, "NR_UNITS": 1, "YR_BUILT": 1957, "BLDG_AREA": 1721.0,
           "NR_STORIES": "2.0", "YR_ASSMT": 2026}
    row.update(kw)
    return row


_MKE_HOUSE = _mke()
# A duplex filed under a range: one building, two doors.
_MKE_DUPLEX = _mke(TAXKEY="0050077000", HOUSE_NR_LO=9371, HOUSE_NR_HI=9373,
                   STREET="BURBANK", STTYPE="AV", LAND_USE=8820, NR_UNITS=2,
                   YR_BUILT=1981, BLDG_AREA=2623.0)
# 923 S 10th St: two parcels, one with the suffix "A".
_MKE_923A = _mke(TAXKEY="4320681000", HOUSE_NR_LO=923, HOUSE_NR_HI=923,
                 HOUSE_NR_SFX="A", SDIR="S", STREET="10TH", STTYPE="ST",
                 YR_BUILT=1885, BLDG_AREA=860.0, NR_STORIES="1.5")
_MKE_923 = _mke(TAXKEY="4320682000", HOUSE_NR_LO=923, HOUSE_NR_HI=923, SDIR="S",
                STREET="10TH", STTYPE="ST", LAND_USE=8820, NR_UNITS=2,
                YR_BUILT=1875, BLDG_AREA=2364.0)
# The roll's "MC KINLEY", which the Census matcher writes "MCKINLEY".
_MKE_MCKINLEY = _mke(TAXKEY="3611473000", HOUSE_NR_LO=1219, HOUSE_NR_HI=1219,
                     SDIR="W", STREET="MC KINLEY", STTYPE="AV", YR_BUILT=1897,
                     BLDG_AREA=1553.0, NR_STORIES="1.5")
# A vacant lot: land use 8880, no units, no year.
_MKE_VACANT = _mke(TAXKEY="0010001000", HOUSE_NR_LO=11505, HOUSE_NR_HI=11505,
                   SDIR="W", STREET="COUNTY LINE", STTYPE="RD", LAND_USE=8880,
                   NR_UNITS=0, YR_BUILT=0, BLDG_AREA=0.0, NR_STORIES="")


def _water(unit, year=1875, taxkey=None):
    """A unit of 200 S Water St, a condominium building stacked on one outline."""
    return _mke(TAXKEY=taxkey or f"42806{unit}000", HOUSE_NR_LO=200, HOUSE_NR_HI=200,
                SDIR="S", STREET="WATER", STTYPE="ST", UNIT=str(unit), LAND_USE=8811,
                YR_BUILT=year, BLDG_AREA=991.0, NR_STORIES="1")


def _msn(**kw):
    """A Madison row: a single-family house on Pine Ridge Trl by default."""
    row = {"Parcel": "070823408145", "XRefParcel": "070823408145", "HouseNbr": 117,
           "StreetDir": "", "StreetName": "Pine Ridge", "StreetType": "Trl", "Unit": "",
           "PropertyUse": "Single family", "TotalDwellingUnits": 1, "YearBuilt": 1986.0,
           "TotalLivingArea": 1322.0, "ExteriorWall1": "Aluminum/Vinyl",
           "ExteriorWall2": ""}
    row.update(kw)
    return row


_MSN_HOUSE = _msn()
# 901 Waban Hl: the roll's "HL" is the matcher's "HILL"; a vinyl house with a
# masonry front.
_MSN_WABAN = _msn(Parcel="070932102084", XRefParcel="070932102084", HouseNbr=901,
                  StreetName="WABAN", StreetType="HL", YearBuilt=1946.0,
                  TotalLivingArea=2156.0, ExteriorWall2="Masonry Facing")
# "Council Crest", the type inside the name and none in StreetType.
_MSN_CREST = _msn(Parcel="070928320020", XRefParcel="070928320020", HouseNbr=3705,
                  StreetName="Council Crest", StreetType="", YearBuilt=1937.0,
                  TotalLivingArea=1302.0, ExteriorWall1="Wood")
# An office: YearBuilt filled, no dwelling.
_MSN_OFFICE = _msn(Parcel="071006114343", XRefParcel="071006114343", HouseNbr=2565,
                   StreetDir="E", StreetName="Johnson", StreetType="St",
                   PropertyUse="Office 2 sty or lg.", TotalDwellingUnits=0,
                   YearBuilt=1939.0, TotalLivingArea=4186.0, ExteriorWall1="Stucco")
# The condominium notation laid over a complex: no year, no dwelling.
_MSN_NOTATION = _msn(Parcel="080925101977", XRefParcel="080925101977", HouseNbr=1,
                     StreetName="Cherokee", StreetType="Cir", Unit="CDM",
                     PropertyUse="Condominium-Notation", TotalDwellingUnits=0,
                     YearBuilt=0.0, TotalLivingArea=0.0, ExteriorWall1="")


def _cherokee(unit, year=2002.0, parcel=None):
    """A unit of 1 Cherokee Cir, every unit carrying the complex's outline."""
    return _msn(Parcel=parcel or f"0809251131{unit}", XRefParcel="080925101977",
                HouseNbr=1, StreetName="Cherokee", StreetType="Cir", Unit=str(unit),
                PropertyUse="Condominium", YearBuilt=year, TotalLivingArea=1717.0,
                ExteriorWall1="Aluminum/Vinyl")


#: A point in Milwaukee. Which parcel a coordinate lands in is decided here by
#: the stubbed rows, not by the coordinate.
_POINT = (43.0731, -87.9906)


@pytest.fixture
def _lifted(monkeypatch):
    """Both cities registered, as a decision to lift the hold would make them."""
    monkeypatch.setattr(wi, "COUNTY_FIPS", frozenset(wi.CITIES))


def _lookup(exact, near=(), address=None, county=MILWAUKEE, slices=None,
            params=None, urls=None, county_answer=MILWAUKEE, exceeded=False):
    """Drive ``wi.lookup()`` over recorded rows, through the real transport helper.

    ``exact`` is what the point lands inside; ``near`` what a buffered search
    finds. ``county`` is what the caller passes (None makes the adapter ask
    TIGERweb, which answers ``county_answer``).
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    urls = [] if urls is None else urls

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        urls.append(url)
        if url == wi.COUNTY_URL:
            feats = ([{"attributes": {"GEOID": county_answer}}] if county_answer else [])
            return {"features": feats}
        if exceeded:
            raise _shared.TruncatedResponse("truncated at the transfer limit")
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    wi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return wi.lookup(*_POINT, address, county)
    finally:
        _shared.get_json = saved
        wi._lookup_cached.cache_clear()


# ── the hold ───────────────────────────────────────────────────────────────────


def test_neither_county_is_registered_while_held():
    assert wi._HELD_FOR_COVERAGE == {MILWAUKEE, DANE}
    assert wi.COUNTY_FIPS == frozenset()


def test_a_held_county_answers_nothing_and_asks_nobody():
    urls = []
    assert _lookup([_MKE_HOUSE], address="7609 N 51ST BLVD, MILWAUKEE, WI",
                   urls=urls) is None
    assert urls == []


def test_lifting_the_hold_is_the_only_change_needed(_lifted):
    got = _lookup([_MKE_HOUSE], address="7609 N 51ST BLVD, MILWAUKEE, WI, 53223")
    assert got is not None and got.year_built == 1957


# ── Milwaukee ──────────────────────────────────────────────────────────────────


def test_a_milwaukee_house_reports_year_area_and_stories(_lifted):
    got = _lookup([_MKE_HOUSE], address="7609 N 51ST BLVD, MILWAUKEE, WI, 53223")
    assert got is not None
    assert (got.year_built, got.sqft, got.stories) == (1957, 1721.0, 2)
    assert got.parcel_id == "0840193000"
    assert "2026 assessment" in got.data_vintage
    assert "Milwaukee" in got.source and "MPROP" in got.source


def test_milwaukees_own_street_types_are_respelled():
    """BL is Boulevard, CR Circle, LA Lane, PK Parkway, TR Terrace, WA Way — the
    City's official codes, in a column holding nothing else."""
    for code, spelled in (("BL", "BLVD"), ("CR", "CIR"), ("LA", "LN"), ("PK", "PKWY"),
                          ("TR", "TER"), ("WA", "WAY")):
        assert wi._mke_addresses(_mke(STTYPE=code))[0] == f"7609 N 51ST {spelled}", code
    # AV, ST, CT ... are the shared table's already and pass through untouched.
    assert wi._mke_addresses(_mke(STTYPE="AV"))[0] == "7609 N 51ST AV"


def test_a_duplex_range_answers_to_either_end_and_nothing_between(_lifted):
    for n in (9371, 9373):
        got = _lookup([], near=[_MKE_DUPLEX],
                      address=f"{n} N BURBANK AVE, MILWAUKEE, WI, 53224")
        assert got is not None and got.year_built == 1981, n
        assert got.sqft is None and got.stories is None, "two flats are one area"
    assert _lookup([], near=[_MKE_DUPLEX],
                   address="9372 N BURBANK AVE, MILWAUKEE, WI") is None


def test_a_suffix_door_refuses_the_area_but_keeps_the_year(_lifted):
    got = _lookup([_MKE_923A], address="923 S 10TH ST, MILWAUKEE, WI, 53204")
    assert got is not None and got.year_built == 1885
    assert got.sqft is None and got.stories is None


def test_two_parcels_differing_only_by_a_suffix_are_ambiguous(_lifted):
    assert _lookup([], near=[_MKE_923A, _MKE_923],
                   address="923 S 10TH ST, MILWAUKEE, WI, 53204") is None


def test_a_milwaukee_name_answers_to_both_spellings(_lifted):
    """The matcher's "MCKINLEY" (a reader who typed McKinley) and the roll's own
    "MC KINLEY" (a reader whose words the product keeps because they differ from
    the matcher's) both confirm the parcel."""
    for address in ("1219 W MCKINLEY AVE, MILWAUKEE, WI, 53205",
                    "1219 W Mc Kinley Ave, Milwaukee, WI"):
        got = _lookup([_MKE_MCKINLEY], address=address)
        assert got is not None and got.year_built == 1897, address
        assert got.stories is None, "1.5 stories has no whole-number reading"
    assert _lookup([_MKE_MCKINLEY], near=[_MKE_MCKINLEY],
                   address="1219 W MCKINLEY BLVD, MILWAUKEE, WI") is None


def test_both_spellings_do_not_make_one_house_two_doors():
    """The second spelling is the same door; it must not read as a range and
    cost the house its area."""
    assert len(wi._mke_addresses(_MKE_MCKINLEY)) == 2
    assert wi._mke_one_dwelling(_MKE_MCKINLEY)


def test_whole_stories_only_and_only_on_a_house(_lifted):
    address = "7609 N 51ST BLVD, MILWAUKEE, WI"
    for raw, want in (("1", 1), ("2.0", 2), ("1.5", None), ("2.5", None), ("", None),
                      ("0.0", None), ("9", None), ("42", None)):
        got = _lookup([_mke(NR_STORIES=raw)], address=address)
        assert got is not None and got.stories == want, raw


def test_two_dwellings_on_a_single_family_parcel_refuse_area_and_stories(_lifted):
    got = _lookup([_mke(NR_UNITS=2)], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.year_built == 1957
    assert got.sqft is None and got.stories is None


def test_a_recorded_zero_dwellings_refuses_the_year(_lifted):
    assert _lookup([_mke(NR_UNITS=0)], address="7609 N 51ST BLVD, MILWAUKEE, WI") is None


def test_a_missing_unit_count_is_silence_not_zero(_lifted):
    got = _lookup([_mke(NR_UNITS=None)], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.year_built == 1957
    assert got.sqft is None, "without a count the record does not say ONE home"


def test_vacant_land_and_shops_are_never_candidates(_lifted):
    assert _lookup([_MKE_VACANT], address="11505 W COUNTY LINE RD, MILWAUKEE, WI") is None
    shop = _mke(LAND_USE=5812, NR_UNITS=0)       # a restaurant, year filled
    assert _lookup([shop], address="7609 N 51ST BLVD, MILWAUKEE, WI") is None


def test_a_vacant_lot_beside_a_house_does_not_hide_it(_lifted):
    """A side lot filed under the house's own address is not a second candidate."""
    lot = _mke(TAXKEY="0840193100", LAND_USE=8880, NR_UNITS=0, YR_BUILT=0)
    got = _lookup([], near=[_MKE_HOUSE, lot], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.parcel_id == "0840193000"


def test_mixed_residential_and_multifamily_keep_their_year(_lifted):
    for use, units in ((8830, 10), (8899, 4)):
        got = _lookup([_mke(LAND_USE=use, NR_UNITS=units)],
                      address="7609 N 51ST BLVD, MILWAUKEE, WI")
        assert got is not None and got.year_built == 1957 and got.sqft is None, use


# ── condominiums ───────────────────────────────────────────────────────────────


def test_a_condominium_stack_is_found_by_address_as_its_building(_lifted):
    """Every unit carries the building's outline. With an address the stack is
    left out of containment and found in the buffer, merged into the building
    because all its units agree on the year."""
    stack = [_water(101), _water(102), _water(103)]
    got = _lookup(stack, near=stack, address="200 S WATER ST, MILWAUKEE, WI, 53204")
    assert got is not None and got.year_built == 1875
    assert got.sqft is None and got.stories is None
    assert got.parcel_id is None, "the building has no single tax key of its own"


def test_units_that_disagree_about_the_year_are_not_offered(_lifted):
    stack = [_water(101), _water(102), _water(103, year=2006)]
    assert _lookup(stack, near=stack, address="200 S WATER ST, MILWAUKEE, WI") is None


def test_a_typed_unit_picks_its_own_record(_lifted):
    stack = [_water(101), _water(102), _water(103, year=2006, taxkey="4280623100")]
    got = _lookup(stack, near=stack, address="200 S WATER ST #103, MILWAUKEE, WI")
    assert got is not None and got.year_built == 2006
    assert got.parcel_id == "4280623100" and got.sqft is None


def test_without_an_address_a_stack_is_ambiguous(_lifted):
    stack = [_water(101), _water(102, year=1990)]
    assert _lookup(stack, near=stack) is None


def test_a_madison_complex_merges_on_its_complex_id(_lifted):
    units = [_cherokee(103), _cherokee(104), _MSN_NOTATION]
    got = _lookup(units, near=units, address="1 CHEROKEE CIR, MADISON, WI, 53704",
                  county=DANE)
    assert got is not None and got.year_built == 2002
    assert got.parcel_id == "080925101977" and got.sqft is None
    assert got.construction is None, "a building's wall is not read off one unit"


def test_a_madison_unit_typed_is_that_unit(_lifted):
    units = [_cherokee(103), _cherokee(104, parcel="080925113120")]
    got = _lookup(units, near=units, address="1 CHEROKEE CIR #104, MADISON, WI",
                  county=DANE)
    assert got is not None and got.parcel_id == "080925113120"


def test_units_of_two_complexes_at_one_address_are_not_merged(_lifted):
    other = dict(_cherokee(201), XRefParcel="080925199999")
    units = [_cherokee(103), other]
    assert _lookup(units, near=units, address="1 CHEROKEE CIR, MADISON, WI",
                   county=DANE) is None


# ── Madison ────────────────────────────────────────────────────────────────────


def test_a_madison_house_reports_year_area_and_wall(_lifted):
    got = _lookup([_MSN_HOUSE], address="117 PINE RIDGE TRL, MADISON, WI, 53717",
                  county=DANE)
    assert got is not None
    assert (got.year_built, got.sqft, got.construction) == (1986, 1322.0, "frame")
    assert got.stories is None, "Madison records no story count"
    assert got.parcel_id == "070823408145" and "Madison" in got.source


def test_madisons_abbreviated_types_answer_to_both_spellings(_lifted):
    for address in ("901 WABAN HILL, MADISON, WI, 53711", "901 Waban Hl, Madison, WI"):
        got = _lookup([_MSN_WABAN], address=address, county=DANE)
        assert got is not None and got.year_built == 1946, address
    for raw, spelled in (("Bnd", "BEND"), ("Rdg", "RIDGE"), ("IS", "ISLAND")):
        assert wi._msn_addresses(_msn(StreetType=raw))[0] == f"117 Pine Ridge {spelled}"


def test_a_crest_street_answers_to_the_matchers_crst(_lifted):
    for address in ("3705 COUNCIL CRST, MADISON, WI, 53711", "3705 Council Crest, Madison"):
        got = _lookup([_MSN_CREST], address=address, county=DANE)
        assert got is not None and got.year_built == 1937, address


def test_a_second_wall_that_disagrees_leaves_the_wall_empty(_lifted):
    got = _lookup([_MSN_WABAN], address="901 WABAN HILL, MADISON, WI", county=DANE)
    assert got is not None and got.construction is None
    same = _lookup([_msn(ExteriorWall1="Wood", ExteriorWall2="Aluminum/Vinyl")],
                   address="117 PINE RIDGE TRL, MADISON, WI", county=DANE)
    assert same is not None and same.construction == "frame"


def test_unambiguous_madison_walls_translate():
    for raw, want in (("Aluminum/Vinyl", "frame"), ("Wood", "frame"), ("Wd", "frame"),
                      ("Composition", "frame"), ("Cement/Smart", "frame"),
                      ("Brick", "brick"), ("Stone", "stone")):
        assert wi._msn_wall(_msn(ExteriorWall1=raw)) == want, raw


def test_ambiguous_madison_walls_stay_empty():
    for raw in ("Stucco", "Masonry Facing", "RStl", "", None, "Log"):
        assert wi._msn_wall(_msn(ExteriorWall1=raw)) is None, raw


def test_an_office_with_a_year_and_no_dwelling_is_not_a_home(_lifted):
    assert _lookup([_MSN_OFFICE], address="2565 E JOHNSON ST, MADISON, WI",
                   county=DANE) is None


def test_a_madison_parcel_with_zero_dwellings_reports_nothing(_lifted):
    assert _lookup([_msn(TotalDwellingUnits=0)], address="117 PINE RIDGE TRL, MADISON, WI",
                   county=DANE) is None


def test_two_units_refuse_the_area_and_keep_the_year(_lifted):
    got = _lookup([_msn(PropertyUse="2 Unit", TotalDwellingUnits=2)],
                  address="117 PINE RIDGE TRL, MADISON, WI", county=DANE)
    assert got is not None and got.year_built == 1986 and got.sqft is None


def test_apartments_keep_their_year(_lifted):
    got = _lookup([_msn(PropertyUse="Apartments", TotalDwellingUnits=48)],
                  address="117 PINE RIDGE TRL, MADISON, WI", county=DANE)
    assert got is not None and got.year_built == 1986 and got.sqft is None


# ── years ──────────────────────────────────────────────────────────────────────


def test_a_year_of_zero_is_not_the_year_zero(_lifted):
    got = _lookup([_mke(YR_BUILT=0)], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.year_built is None and got.sqft == 1721.0
    got = _lookup([_msn(YearBuilt=0.0)], address="117 PINE RIDGE TRL, MADISON, WI",
                  county=DANE)
    assert got is not None and got.year_built is None


def test_the_adapter_floor_is_the_scorer_floor(_lifted):
    at = _lookup([_mke(YR_BUILT=EARLIEST_PLAUSIBLE_YEAR)],
                 address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert at is not None and at.year_built == EARLIEST_PLAUSIBLE_YEAR
    below = _lookup([_mke(YR_BUILT=EARLIEST_PLAUSIBLE_YEAR - 1)],
                    address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert below is not None and below.year_built is None
    above = _lookup([_mke(YR_BUILT=2101)], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert above is not None and above.year_built is None


def test_a_parcel_that_records_nothing_is_not_an_answer(_lifted):
    empty = _mke(YR_BUILT=0, BLDG_AREA=0.0, NR_STORIES="")
    assert _lookup([empty], address="7609 N 51ST BLVD, MILWAUKEE, WI") is None


def test_rows_of_one_parcel_that_disagree_are_not_offered(_lifted):
    assert _lookup([_MKE_HOUSE, _mke(YR_BUILT=1990)],
                   address="7609 N 51ST BLVD, MILWAUKEE, WI") is None
    got = _lookup([_MKE_HOUSE, dict(_MKE_HOUSE)], address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.year_built == 1957


def test_every_translation_is_in_the_labels_vocabulary():
    from housing_label.enrich.assessor.base import CONSTRUCTION_VALUES
    assert set(wi._MADISON_WALL.values()) <= CONSTRUCTION_VALUES


# ── the field lists ────────────────────────────────────────────────────────────

#: Owner, mailing, sale and tax columns that exist in these layers.
_PRIVATE = {
    MILWAUKEE: ("OWNER_NAME_1", "OWNER_NAME_2", "OWNER_NAME_3", "OWNER_MAIL_ADDR",
                "OWNER_CITY_STATE", "OWNER_ZIP", "CONVEY_DATE", "CONVEY_FEE",
                "C_A_TOTAL", "OWN_OCPD", "TAX_DELQ"),
    DANE: ("OwnerOccupied", "OwnerChangeDate", "CurrentTotal", "NetTaxes",
           "TotalTaxes", "MaxConstructionYear"),
}


def test_every_field_list_is_explicit_and_carries_nothing_private():
    for fips, cfg in wi.CITIES.items():
        fields = cfg.out_fields.split(",")
        assert "*" not in fields and cfg.out_fields.strip(), cfg.name
        for private in _PRIVATE[fips]:
            assert private not in fields, (cfg.name, private)
        lowered = {f.lower() for f in fields}
        assert not any("owner" in f or "mail" in f or "convey" in f or "tax" in f
                       and f != "taxkey" for f in lowered), (cfg.name, fields)


def test_every_column_read_is_a_column_requested(_lifted):
    """A column read but not requested is None on every row — silently. So the
    row a lookup sees is cut down to the requested fields before it is read."""
    for fips, row, address in ((MILWAUKEE, _MKE_HOUSE, "7609 N 51ST BLVD, MILWAUKEE, WI"),
                               (DANE, _MSN_HOUSE, "117 PINE RIDGE TRL, MADISON, WI")):
        cfg = wi.CITIES[fips]
        trimmed = {k: v for k, v in row.items() if k in cfg.fields}
        assert trimmed == row, "the recorded row carries only requested columns"
        got = _lookup([trimmed], address=address, county=fips)
        assert got is not None and got.year_built and got.sqft, cfg.name


def test_the_requested_fields_are_what_reaches_the_service(_lifted):
    for fips, rows in ((MILWAUKEE, [_MKE_HOUSE]), (DANE, [_MSN_HOUSE])):
        params, urls = [], []
        _lookup(rows, county=fips, params=params, urls=urls)
        cfg = wi.CITIES[fips]
        assert params and all(p["outFields"] == cfg.out_fields for p in params)
        assert urls and all(u == cfg.url for u in urls)


def test_the_effective_years_are_never_requested():
    for cfg in wi.CITIES.values():
        for col in cfg.fields:
            assert "EFF" not in col.upper() and "MAXCONSTRUCTION" not in col.upper()


# ── the county list ────────────────────────────────────────────────────────────


def test_every_configured_county_is_a_real_wisconsin_county():
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        wisconsin = {r["geoid"] for r in csv.DictReader(fh)
                     if r["geoid"].startswith("55") and len(r["geoid"]) == 5}
    assert len(wisconsin) == 72, f"expected 72 Wisconsin counties, got {len(wisconsin)}"
    assert set(wi.CITIES) <= wisconsin
    assert wi.COUNTY_FIPS <= set(wi.CITIES)
    assert wi._HELD_FOR_COVERAGE <= set(wi.CITIES)


def test_url_for_names_each_citys_own_layer():
    assert wi.url_for(MILWAUKEE) == wi.MILWAUKEE_URL
    assert wi.url_for(DANE) == wi.MADISON_URL
    assert wi.url_for("55133") is None


def test_without_a_county_the_point_is_located_first(_lifted):
    urls = []
    got = _lookup([_MSN_HOUSE], address="117 PINE RIDGE TRL, MADISON, WI",
                  county=None, county_answer=DANE, urls=urls)
    assert got is not None and got.year_built == 1986
    assert urls[0] == wi.COUNTY_URL and all(u == wi.MADISON_URL for u in urls[1:])


def test_without_a_county_a_held_or_uncovered_point_is_no_answer():
    assert _lookup([_MKE_HOUSE], county=None, county_answer=MILWAUKEE) is None
    assert _lookup([_MKE_HOUSE], county=None, county_answer=None) is None


def test_a_county_passed_explicitly_but_not_registered_is_not_rerouted(_lifted):
    urls = []
    assert _lookup([_MKE_HOUSE], county="55133", urls=urls) is None
    assert urls == []


# ── the clock ──────────────────────────────────────────────────────────────────


def test_every_citys_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The connect half of a socket timeout keeps the whole remaining budget, so one
    request can cost the budget plus one read slice; it is that SUM that has to fit.
    Pinned against the host constant, not a literal."""
    from housing_label import config
    for cfg in wi.CITIES.values():
        assert cfg.timeout + cfg.read_slice < config.UPSTREAM_HOST_BUDGET, cfg.name
    assert wi.LOOKUP_TIMEOUT + wi.READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_both_cities_ask_for_more_than_the_shared_read_slice():
    """Milwaukee was cut off at 2 s once and Madison at 1 s twice in the
    verification run; one second is not enough for either."""
    assert wi.CITIES[MILWAUKEE].read_slice >= 3.0
    assert wi.CITIES[DANE].read_slice > _shared._READ_SLICE_S


def test_every_request_passes_its_citys_read_slice(_lifted):
    for fips, rows, address in ((MILWAUKEE, [_MKE_HOUSE], "7609 N 51ST BLVD, MILWAUKEE, WI"),
                                (DANE, [_MSN_HOUSE], "117 PINE RIDGE TRL, MADISON, WI")):
        slices = []
        assert _lookup(rows, address=address, county=fips, slices=slices) is not None
        assert slices and all(s == wi.CITIES[fips].read_slice for s in slices)


def test_every_request_shares_one_clock_started_once(_lifted):
    seen = []

    def note(url, request, deadline, read_slice=None):
        seen.append(deadline)
        return {"features": []}

    wi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = note
    try:
        started = time.monotonic()
        wi.lookup(*_POINT, "7609 N 51ST BLVD, MILWAUKEE, WI", MILWAUKEE)
    finally:
        _shared.get_json = saved
        wi._lookup_cached.cache_clear()
    assert len(seen) == 2, f"expected containment and buffer, got {len(seen)}"
    assert len(set(seen)) == 1, "each request was handed its own budget"
    assert abs(seen[0] - started - wi.CITIES[MILWAUKEE].timeout) < 0.5


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence(_lifted):
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    wi._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert wi.lookup(*_POINT, "7609 N 51ST BLVD, MILWAUKEE, WI", MILWAUKEE) is None
    finally:
        _shared.get_json = saved
        wi._lookup_cached.cache_clear()


def test_a_truncated_response_is_no_answer(_lifted):
    assert _lookup([_MKE_HOUSE], address="7609 N 51ST BLVD, MILWAUKEE, WI",
                   exceeded=True) is None


def test_garbage_coordinates_fail_open(_lifted):
    assert wi.lookup("not a number", None, None, MILWAUKEE) is None


def test_no_parcel_at_the_point_is_simply_no_answer(_lifted):
    assert _lookup([], address="7609 N 51ST BLVD, MILWAUKEE, WI") is None


def test_a_house_inside_its_lot_with_no_address_is_still_answered(_lifted):
    got = _lookup([_MKE_HOUSE])
    assert got is not None and got.year_built == 1957


def test_containment_on_the_neighbors_lot_falls_through_to_the_buffer(_lifted):
    neighbor = _mke(TAXKEY="0840194000", HOUSE_NR_LO=7619, HOUSE_NR_HI=7619,
                    BLDG_AREA=1060.0, NR_STORIES="1")
    got = _lookup([neighbor], near=[neighbor, _MKE_HOUSE],
                  address="7609 N 51ST BLVD, MILWAUKEE, WI")
    assert got is not None and got.parcel_id == "0840193000"
