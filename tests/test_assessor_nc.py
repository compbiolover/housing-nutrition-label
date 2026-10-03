#!/usr/bin/env python3
"""The North Carolina adapter — one statewide layer, filled by only some counties.

Nothing here touches the network. NC OneMap's service is stubbed with response
shapes recorded from it live, for the reason every adapter test file gives: an
adapter fails open on purpose, so a renamed column or a broken match reads as
"North Carolina has no record here" and would never announce itself. A test that
called the real service would pass just as quietly.

What is worth pinning is what is genuinely North Carolina's. The dangerous shared
parts — choosing which parcel an address means, comparing two addresses, bounding
the request budget — live in ``_shared`` and are tested against Cook in
``test_assessor.py``.

North Carolina's own five:

1. **51 counties never fill the year built**, and three more fill it uselessly,
   so the county list is a measurement rather than the state.
2. The only fact is ``structyear``, and two of its values are not years: **0**
   (not recorded) and Wilkes County's **1600** placeholder.
3. The use description is **2,611 county vocabularies** in one column. It is read
   only to refuse a parcel the county says is not a home — and in Duplin it is
   one filler string on every parcel.
4. The ``struct`` flag looks like a dwelling count and is **written "N" on every
   parcel** in five counties.
5. The street address arrives in **four shapes**: alone, with the city run into
   it, after a comma-separated unit, or only as components.

This file alone: ``pytest tests/test_assessor_nc.py``
"""

from __future__ import annotations

import csv
import pathlib
import time

from housing_label.enrich.assessor import _shared, nc

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Recorded live from NC1Map_Parcels/FeatureServer/1. A Raleigh house: Wake files
# the address alone in `siteadd` and writes "R" for the use.
_HOUSE = {"parno": "1713072013", "altparno": "0007442", "siteadd": "420 HAYWOOD ST",
          "saddno": "420", "saddpref": "", "saddstr": "HAYWOOD", "saddsttyp": "ST",
          "saddstsuf": "", "scity": "RALEIGH", "structyear": 1930,
          "parusedesc": "R", "stcntyfips": "37183", "transfdate": 1778994000000}

# Recorded live. A Charlotte condominium unit: its own parcel, with the unit and
# the city run into `siteadd` after a comma.
_CONDO = {"parno": "17103426", "altparno": "17103426",
          "siteadd": "1000 E WOODLAWN RD, 203 CHARLOTTE NC", "saddno": "1000",
          "saddpref": "", "saddstr": "WOODLAWN RD", "saddsttyp": "", "saddstsuf": "",
          "scity": "CHARLOTTE", "structyear": 2008, "parusedesc": "CONDOMINIUM",
          "stcntyfips": "37119", "transfdate": 1767762000000}

# Recorded live. Guilford leaves `siteadd` empty and fills only the components.
_COMPONENTS_ONLY = {"parno": "7875501059-000", "altparno": "", "siteadd": "",
                    "saddno": "1900", "saddpref": "", "saddstr": "BESSEMER",
                    "saddsttyp": "AVE", "saddstsuf": "E", "scity": "Greensboro",
                    "structyear": 1925, "parusedesc": "RESIDENTIAL",
                    "stcntyfips": "37081", "transfdate": 1778734800000}

# Recorded live. The layer's blank placeholder polygon: nothing on it at all.
_BLANK = {"parno": "", "altparno": "", "siteadd": "", "saddno": "", "saddpref": "",
          "saddstr": "", "saddsttyp": "", "saddstsuf": "", "scity": "",
          "structyear": 0, "parusedesc": "", "stcntyfips": "37189",
          "transfdate": 1776142800000}

#: A point in Raleigh. Every test uses the same one: which parcel a coordinate
#: lands in is decided here by the stubbed rows, not by the coordinate.
_POINT = (35.7745, -78.6284)


def _lookup(exact, near=(), address=None, slices=None, params=None, deadlines=None):
    """Drive ``nc.lookup()`` over recorded rows.

    ``exact`` is what the point lands inside; ``near`` is what a buffered search
    would find. Both are answered through the real transport helper, so the field
    list, the placeholder filter, the address handling and the parcel choice are
    all exercised rather than stepped over.

    ``slices``, ``params`` and ``deadlines``, when passed, collect what each
    request was handed, so a test can check what reaches the transport rather
    than only what a constant says.
    """
    slices = [] if slices is None else slices
    params = [] if params is None else params
    deadlines = [] if deadlines is None else deadlines

    def fake(url, request, deadline, read_slice=None):
        slices.append(read_slice)
        params.append(request)
        deadlines.append(deadline)
        rows = list(near) if request.get("distance") else list(exact)
        return {"features": [{"attributes": a} for a in rows]}

    nc._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = fake
    try:
        return nc.lookup(*_POINT, address)
    finally:
        _shared.get_json = saved
        nc._lookup_cached.cache_clear()


# ── the one fact, and the values of it that are not years ───────────────────────


def test_a_house_reports_its_year_parcel_and_county_file_date():
    got = _lookup([_HOUSE], address="420 HAYWOOD ST, RALEIGH, NC, 27604")
    assert got is not None
    assert got.year_built == 1930
    assert got.parcel_id == "1713072013"
    assert "county file of 2026-05-17" in got.data_vintage


def test_the_year_is_the_only_field_this_source_can_fill():
    """The statewide schema has no floor area, storeys, wall, foundation or
    condition. A later edit that read one of the 72 columns as a stand-in for
    them would be a guess wearing the ``observed`` tag."""
    got = _lookup([_HOUSE])
    assert got is not None and got.fields() == {"year_built": 1930}


def test_a_year_of_zero_is_not_the_year_zero():
    """The schema's "not recorded", on 3.2 million parcels — every parcel in 51
    counties. With no other fact on the row there is nothing to report."""
    assert nc._year_built(dict(_HOUSE, structyear=0)) is None
    assert _lookup([dict(_HOUSE, structyear=0)]) is None
    assert _lookup([dict(_HOUSE, structyear=None)]) is None


def test_wilkes_countys_1600_is_a_placeholder_not_a_year():
    """2,501 Wilkes parcels carry exactly 1600 and no other county has it. It sits
    ON the scorer's plausibility floor, so the floor alone lets it through — it
    has to be refused by value."""
    from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
    assert EARLIEST_PLAUSIBLE_YEAR <= 1600, "the floor would not catch it"
    wilkes = dict(_HOUSE, stcntyfips="37193", parusedesc="", structyear=1600)
    assert _lookup([wilkes]) is None
    assert _lookup([dict(wilkes, structyear=1975)]).year_built == 1975


def test_a_genuinely_old_year_survives():
    """Wake's oldest recorded house is 1760. Refusing the 1600 placeholder must
    not drag the floor up with it."""
    for year in (1760, 1799, 1900):
        got = _lookup([dict(_HOUSE, structyear=year)])
        assert got is not None and got.year_built == year, year


def test_a_year_past_the_ceiling_is_refused():
    """Catawba carries 2205 on two parcels."""
    assert _lookup([dict(_HOUSE, structyear=2205)]) is None


# ── a year built has to belong to somebody's home ──────────────────────────────


def test_a_parcel_the_county_calls_vacant_reports_no_year():
    """19,513 parcels say "VACANT LAND" and still carry a year — a shed's, or a
    demolished house's. Not the reader's home."""
    for desc in ("VACANT LAND", "CLASS: RESIDENTIAL - VAC", "RESIDENTIAL VACANT"):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]) is None, desc


def test_a_common_area_reports_no_year():
    """An HOA common area's year is the clubhouse's — even when the county
    describes it as "SINGLE FAMILY RESIDENTIAL - COMMON"."""
    for desc in ("SINGLE FAMILY RESIDENTIAL - COMMON", "TOWN HOUSE COMMON AREA"):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]) is None, desc


def test_a_parcel_the_county_calls_commercial_reports_no_year():
    for desc in ("COMMERCIAL", "INDUSTRIAL WAREHOUSE", "17 - OFFICE",
                 "RA 04-OFF-CONST(71-CHURCHES)", "C-Commercial", "HOTEL/MOTEL"):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]) is None, desc


def test_a_home_on_commercial_land_keeps_its_year():
    """The exception is the point of the rule: these all name somebody's home,
    and refusing them would be the guess the rule exists to avoid."""
    for desc in ("House on Commercial Site", "SINGLE FAMILY ON COMM LD",
                 "Mixed Use Commercial", "COMMERCIAL APARTMENT",
                 "RETAIL-50%,SINGLE FAMILY RESIDENCE-50%"):
        got = _lookup([dict(_HOUSE, parusedesc=desc)])
        assert got is not None and got.year_built == 1930, desc


def test_an_office_condominium_is_not_a_home():
    """CONDO is deliberately not a residential word: "OFFICE CONDOMINIUM",
    "WAREHOUSE CONDOMINIUM" and "MEDICAL CONDOMINIUM" are all in the vocabulary.
    A residential condominium has no non-residential word, so it is unaffected."""
    for desc in ("OFFICE CONDOMINIUM", "WAREHOUSE CONDOMINIUM", "MEDICAL CONDOMINIUM"):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]) is None, desc
    assert _lookup([dict(_HOUSE, parusedesc="CONDOMINIUM")]).year_built == 1930


def test_a_homestead_exemption_is_not_a_non_residential_use():
    """EXEMPT is not a refusal: "ELDERLY & DISABLED - PART EXEMPT" is a homestead
    exemption on somebody's home."""
    for desc in ("ELDERLY & DISABLED - PART EXEMPT", "DISABLED VETERAN - PART EXEMPT"):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]).year_built == 1930, desc


def test_a_single_letter_code_is_never_read():
    """What "C" or "E" means is a fact about one county's code table. Reading it
    statewide would be a guess."""
    for desc in ("C", "E", "R", "D", ""):
        assert _lookup([dict(_HOUSE, parusedesc=desc)]).year_built == 1930, desc


def test_whole_words_only():
    """COMM is a word in "COMM VACANT LAND"; it is not a prefix of COMMUNITY."""
    assert not nc._says_it_is_not_a_home(dict(_HOUSE, parusedesc="COMMUNITY HOME"))
    assert nc._says_it_is_not_a_home(dict(_HOUSE, parusedesc="COMM"))


def test_duplins_filler_description_is_ignored():
    """Duplin writes "VACANT LAND" on all 43,612 of its parcels, 19,109 of which
    carry a year. Read literally the words would refuse the whole county; they say
    nothing about any one parcel there.

    Scoped to the county code, so the same words still refuse anywhere else."""
    duplin = dict(_HOUSE, stcntyfips="37061", parusedesc="VACANT LAND",
                  structyear=1978)
    got = _lookup([duplin])
    assert got is not None and got.year_built == 1978
    assert _lookup([dict(duplin, stcntyfips="37183")]) is None
    assert _lookup([dict(duplin, parusedesc="COMMERCIAL")]) is None, (
        "only the filler string is ignored in Duplin, not the rule")


def test_the_structure_flag_is_not_a_dwelling_count():
    """``struct`` reads like Florida's zero-dwelling statement and is not one:
    Union, Burke, Duplin and Currituck write "N" on every parcel, and Catawba on
    64,171 of its 64,174 parcels that carry a year. It is not even requested, so a
    later edit cannot refuse on it by mistake."""
    assert "struct" not in nc._FIELDS.split(",")
    assert "structno" not in nc._FIELDS.split(",")
    catawba = dict(_HOUSE, stcntyfips="37035", parusedesc="", struct="N",
                   structno=0, structyear=1999)
    assert _lookup([catawba]).year_built == 1999


# ── where the street address lives ─────────────────────────────────────────────


def test_a_city_state_and_zip_run_into_the_address_are_trimmed():
    """Carteret. Left in, BEAUFORT would read as part of the street's name and the
    parcel would never confirm."""
    carteret = dict(_HOUSE, siteadd="486 HARKERS ISLAND RD BEAUFORT NC 28516",
                    scity="BEAUFORT", stcntyfips="37031")
    assert nc._address_of(carteret) == "486 HARKERS ISLAND RD"
    got = _lookup([], near=[carteret],
                  address="486 HARKERS ISLAND RD, BEAUFORT, NC, 28516")
    assert got is not None and got.year_built == 1930


def test_a_city_with_no_scity_to_match_is_cut_after_the_street_type():
    """Haywood leaves ``scity`` blank and sometimes cuts the ZIP to four digits."""
    for site in ("450 SHADY RIDGE RD WAYNESVILLE NC 28786",
                 "147 PRESERVATION WAY WAYNESVILLE NC 2878"):
        row = dict(_HOUSE, siteadd=site, scity="")
        assert nc._address_of(row) == " ".join(site.split()[:-3]), site
    quadrant = dict(_HOUSE, siteadd="1544 STANLEY RD SW BOLIVIA NC", scity="")
    assert nc._address_of(quadrant) == "1544 STANLEY RD SW", "the quadrant stays"


def test_a_city_with_no_state_is_trimmed_when_it_is_the_rows_own():
    """Harnett: "1504 S CLINTON AVE  DUNN"."""
    harnett = dict(_HOUSE, siteadd="1504 S CLINTON AVE  DUNN", scity="DUNN")
    assert nc._address_of(harnett) == "1504 S CLINTON AVE"


def test_a_tail_that_cannot_be_told_from_the_street_is_left_alone():
    """No street type and no ``scity``: the city cannot be found, so nothing is
    cut. The comparison then refuses the parcel rather than guessing."""
    row = dict(_HOUSE, siteadd="98 CHESTNUT KNOB ROBBINSVILLE NC 28771", scity="")
    assert nc._address_of(row) == "98 CHESTNUT KNOB ROBBINSVILLE NC 28771"


def test_a_cove_is_a_street_type_so_its_city_tail_is_found():
    """COVE joined the shared street types (USPS "CV"), so the city run on after
    it is now recognised and cut — the address this test used to pin as
    unreadable is in fact an ordinary one."""
    row = dict(_HOUSE, siteadd="98 CHESTNUT COVE ROBBINSVILLE NC 28771", scity="")
    assert nc._address_of(row) == "98 CHESTNUT COVE"


def test_a_route_number_after_nc_is_not_a_state():
    """"7352 NC HWY 18" is a highway address, not a city tail."""
    row = dict(_HOUSE, siteadd="7352 NC HWY 18", scity="")
    assert nc._address_of(row) == "7352 NC HWY 18"


def test_the_unit_after_a_comma_is_dropped_and_the_condo_reports_its_buildings_year():
    """Mecklenburg files each condominium unit as its own parcel, with the unit
    after a comma. The year is the building's, right for every unit; there is no
    floor area to refuse because this source carries none."""
    assert nc._address_of(_CONDO) == "1000 E WOODLAWN RD"
    got = _lookup([_CONDO], address="1000 E WOODLAWN RD, CHARLOTTE, NC, 28209")
    assert got is not None and got.year_built == 2008
    assert got.sqft is None and got.stories is None


def test_stacked_condominium_units_are_ambiguous_and_refused():
    """Many unit parcels at one coordinate. Naming one of them would be the
    confident-but-wrong answer the shared chooser exists to reject — even where
    they agree on the year, since this adapter does not merge records."""
    other = dict(_CONDO, parno="17103458", siteadd="1000 E WOODLAWN RD, 312 CHARLOTTE NC")
    assert _lookup([_CONDO, other], address="1000 E WOODLAWN RD, CHARLOTTE, NC") is None


def test_a_county_that_files_only_the_components_is_reachable():
    """Guilford: ``siteadd`` empty, the address in five columns."""
    assert nc._address_of(_COMPONENTS_ONLY) == "1900 BESSEMER AVE E"


def test_broken_components_do_not_veto_a_good_siteadd():
    """Wilson's components carry the parcel number where the house number belongs.
    ``siteadd`` is right, and a disagreement rule would refuse the whole county
    for a fault in a column it never needs."""
    wilson = dict(_HOUSE, siteadd="2505 WILLIAMSBURG DR NW", saddno="1300599",
                  saddstr="2505", saddsttyp="", saddstsuf="NW", stcntyfips="37195")
    assert nc._address_of(wilson) == "2505 WILLIAMSBURG DR NW"


def test_a_parcel_with_no_address_cannot_be_confirmed():
    """Orange and Franklin file no address on any parcel — which is why they are
    not in COUNTY_FIPS. With an address to confirm against, such a parcel is never
    the answer."""
    bare = {k: ("" if k.startswith("sadd") or k == "siteadd" else v)
            for k, v in _HOUSE.items()}
    assert nc._address_of(bare) is None
    assert _lookup([bare], address="420 HAYWOOD ST, RALEIGH, NC") is None
    got = _lookup([bare])
    assert got is not None and got.year_built == 1930, (
        "with no address to confirm, containment alone is the answer")


# ── spelling, on both sides ────────────────────────────────────────────────────


def test_a_trailing_directional_matches_a_leading_one():
    """Guilford writes "1900 BESSEMER AVE E"; the Census matcher writes "1900 E
    BESSEMER AVE". Seen in the end-to-end run, and the same house."""
    got = _lookup([], near=[_COMPONENTS_ONLY],
                  address="1900 E BESSEMER AVE, GREENSBORO, NC, 27405")
    assert got is not None and got.parcel_id == "7875501059-000"


def test_spelled_out_directionals_and_street_types():
    assert nc._comparable("6511 EAST LANGLEY RD") == nc._comparable("6511 E LANGLEY RD")
    assert nc._comparable("1861 QUEENS RD WEST") == nc._comparable("1861 QUEENS RD W")
    assert _shared.same_address(nc._comparable("6824 CARRADALE WY"),
                                nc._comparable("6824 CARRADALE WAY"))
    assert nc._comparable("1004 WINDRACE TR NORTH") == "1004 N WINDRACE TRL"


def test_respelling_never_makes_two_buildings_one():
    """Every part still has to agree after respelling."""
    same = _shared.same_address
    assert not same(nc._comparable("100 N MAIN ST"), nc._comparable("100 S MAIN ST"))
    assert not same(nc._comparable("100 MAIN ST N"), nc._comparable("100 MAIN ST S"))
    assert not same(nc._comparable("102 N MAIN ST"), nc._comparable("100 MAIN ST N"))
    # A one-sided directional is NOT forgiven: 100 N Main and 100 S Main differ.
    assert not same(nc._comparable("802 MEMORIAL BLVD"),
                    nc._comparable("802 N MEMORIAL BLVD"))


def test_a_street_named_for_a_direction_keeps_its_name():
    assert nc._comparable("100 EAST ST") == "100 EAST ST"
    assert not _shared.same_address(nc._comparable("100 EAST ST"),
                                    nc._comparable("100 E ST"))


def test_the_quadrant_stays_where_both_sources_write_it():
    assert nc._comparable("1630 OLD CC RD NW") == "1630 OLD CC RD NW"


def test_a_missing_directional_does_not_match_end_to_end():
    """The rule above, through the real lookup: Dare files "802 MEMORIAL BLVD",
    the matcher says "802 N MEMORIAL BLVD", and the parcel is refused."""
    dare = dict(_HOUSE, parno="988419629367", siteadd="802 MEMORIAL BLVD")
    assert _lookup([], near=[dare],
                   address="802 N MEMORIAL BLVD, KILL DEVIL HILLS, NC") is None


# ── the rows that are not records ──────────────────────────────────────────────


def test_a_placeholder_polygon_is_not_a_record():
    assert _lookup([_BLANK]) is None


def test_a_placeholder_does_not_make_a_real_parcel_ambiguous():
    """A polygon with nothing on it can never be the answer, so it must not be
    counted as a rival. The filter runs before the choice."""
    got = _lookup([_BLANK, _HOUSE], address="420 HAYWOOD ST, RALEIGH, NC")
    assert got is not None and got.parcel_id == "1713072013"


def test_a_right_of_way_polygon_with_an_id_is_not_a_record_either():
    """Carteret files rights-of-way with the parcel number "ROW". An identifier
    alone does not make a candidate; an address or a year does."""
    row = dict(_BLANK, parno="ROW", stcntyfips="37031")
    got = _lookup([row, _HOUSE], address="420 HAYWOOD ST, RALEIGH, NC")
    assert got is not None and got.parcel_id == "1713072013"


def test_a_real_parcel_without_a_year_still_counts_as_a_candidate():
    """Dropping it would leave a neighbour as the only parcel under the point."""
    neighbour_no_year = dict(_HOUSE, parno="1713072014", siteadd="422 HAYWOOD ST",
                             structyear=0)
    assert _lookup([neighbour_no_year, _HOUSE]) is None, "two parcels: ambiguous"


def test_a_parcel_with_no_identifier_is_still_an_answer():
    """Cumberland files its newest parcels without a parcel number. The year is a
    fact with or without one."""
    cumberland = dict(_HOUSE, parno="", altparno="", siteadd="1507 FAWN WOOD PL",
                      structyear=2022, parusedesc="R101-RES", stcntyfips="37051")
    got = _lookup([cumberland], address="1507 FAWN WOOD PL, FAYETTEVILLE, NC")
    assert got is not None and got.year_built == 2022 and got.parcel_id is None


def test_the_alternate_parcel_number_is_the_fallback_id():
    got = _lookup([dict(_HOUSE, parno="")])
    assert got is not None and got.parcel_id == "0007442"


# ── the vintage a reader can date ──────────────────────────────────────────────


def test_a_missing_file_date_falls_back_rather_than_inventing_one():
    for bad in (None, 0, -2208970800000):
        got = _lookup([dict(_HOUSE, transfdate=bad)])
        assert got is not None and got.data_vintage == nc.DATA_VINTAGE, bad


# ── the field list is the privacy boundary ─────────────────────────────────────


def test_no_owner_mailing_sale_or_value_column_is_requested():
    fields = nc._FIELDS.split(",")
    for private in ("ownname", "ownname2", "ownfrst", "ownlast", "mailadd", "munit",
                    "mcity", "mstate", "mzip", "saledate", "saledatetx",
                    "legdecfull", "parval", "improvval", "landval", "subsurfown",
                    "*"):
        assert private not in fields, private


def test_the_requested_fields_are_what_reaches_the_service():
    """Pinned on what the transport is handed, not on the constant."""
    params = []
    _lookup([_HOUSE], params=params)
    assert params and all(p["outFields"] == nc._FIELDS for p in params)


# ── the county list ────────────────────────────────────────────────────────────


def _nc_counties() -> set[str]:
    path = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
    with open(path, newline="") as fh:
        return {r["geoid"] for r in csv.DictReader(fh)
                if r["geoid"].startswith("37") and len(r["geoid"]) == 5}


def test_every_listed_county_is_a_north_carolina_county():
    """Checked against the Census-derived county table this repository ships."""
    census = _nc_counties()
    assert len(census) == 100, f"expected 100 NC counties, got {len(census)}"
    assert census == {f"37{n:03d}" for n in range(1, 200, 2)}, "37001–37199, odd"
    assert nc.COUNTY_FIPS <= census
    assert len(nc.COUNTY_FIPS) == 46


def test_the_counties_with_no_year_built_are_not_claimed():
    """51 counties write 0 on every parcel. Claiming them would cost every label
    there a request for an answer that cannot exist, and would count 1.7 million
    homes this source does not describe."""
    for fips, name in (("37067", "Forsyth"), ("37063", "Durham"),
                       ("37021", "Buncombe"), ("37129", "New Hanover"),
                       ("37025", "Cabarrus"), ("37057", "Davidson")):
        assert fips not in nc.COUNTY_FIPS, name
    assert len(_nc_counties() - nc.COUNTY_FIPS - set(nc.EXCLUDED_WITH_DATA)) == 51


def test_the_three_counties_with_data_but_no_answer_are_left_out_and_say_why():
    assert set(nc.EXCLUDED_WITH_DATA) == {"37015", "37069", "37135"}
    assert not set(nc.EXCLUDED_WITH_DATA) & nc.COUNTY_FIPS


# ── the clock ──────────────────────────────────────────────────────────────────


def test_north_carolina_runs_on_the_shared_budget_and_slice():
    """Measured, the service answers a containment query in a median 76 ms and a
    buffered one in 84 ms, with nothing over 0.41 s — well inside the shared
    one-second slice and four-second budget. So, like Cook and the District, it
    defines neither, and a hung connection is cut off as quickly as anywhere."""
    assert not hasattr(nc, "READ_SLICE_S")
    assert not hasattr(nc, "LOOKUP_TIMEOUT")
    slices = []
    assert _lookup([_HOUSE], slices=slices) is not None
    assert slices and all(s == _shared._READ_SLICE_S for s in slices), slices


def test_the_whole_budget_fits_inside_what_the_host_allows_one_service():
    """The two halves of a socket timeout add up — the connect half keeps the
    whole remaining budget — so the sum is what has to fit. Pinned against the
    host constant rather than a literal."""
    from housing_label import config
    assert _shared.TIMEOUT + _shared._READ_SLICE_S < config.UPSTREAM_HOST_BUDGET


def test_both_requests_share_one_clock_started_once():
    """The budget is a ceiling on the WHOLE lookup, not an allowance per request."""
    deadlines = []
    nc._lookup_cached.cache_clear()
    started = time.monotonic()
    _lookup([], near=[], address="420 HAYWOOD ST, RALEIGH, NC", deadlines=deadlines)
    assert len(deadlines) == 2, "expected a containment and a buffered request"
    assert deadlines[0] == deadlines[1], "each request was handed its own budget"
    assert abs((deadlines[0] - started) - _shared.TIMEOUT) < 0.5


def test_the_buffered_query_carries_an_output_spatial_reference():
    params = []
    _lookup([], near=[_HOUSE], address="420 HAYWOOD ST, RALEIGH, NC", params=params)
    assert len(params) == 2 and params[1].get("distance")
    assert all(p.get("outSR") == "4326" for p in params)


# ── failing open ───────────────────────────────────────────────────────────────


def test_the_service_falling_over_is_not_evidence_of_absence():
    def boom(url, request, deadline, read_slice=None):
        raise RuntimeError("upstream error: layer not found")

    nc._lookup_cached.cache_clear()
    saved = _shared.get_json
    _shared.get_json = boom
    try:
        assert nc.lookup(*_POINT, "420 HAYWOOD ST, RALEIGH, NC") is None
    finally:
        _shared.get_json = saved
        nc._lookup_cached.cache_clear()


def test_a_malformed_row_does_not_escape():
    """A renamed or retyped column must read as "no answer", not as a crash."""
    assert _lookup([dict(_HOUSE, structyear="nineteen thirty")]) is None
    assert _lookup([dict(_HOUSE, transfdate="yesterday")]) is not None


def test_no_parcel_at_the_point_is_simply_no_answer():
    assert _lookup([]) is None


# ── one record, many polygons; one parcel number, many houses ─────────────────


def test_one_record_drawn_as_two_polygons_is_one_candidate():
    """Mecklenburg's 1861 Queens Rd W came back twice, identical in every field,
    and was refused as two parcels."""
    got = _lookup([], near=[_HOUSE, dict(_HOUSE)],
                  address="420 HAYWOOD ST, RALEIGH, NC, 27604")
    assert got is not None and got.parcel_id == "1713072013"


def test_one_parcel_number_on_different_houses_stays_ambiguous():
    """Mecklenburg parcel 02756104 carries the same street address on rows built
    in 2016 and 2017, and parcel 22910115 is 19 stacked houses with their own
    addresses. Rows that differ in any field are not merged."""
    a = dict(_HOUSE, parno="02756104", siteadd="7208 BRICE KNOLL LN", structyear=2017)
    b = dict(a, structyear=2016)
    assert _lookup([], near=[a, b], address="7208 BRICE KNOLL LN, CHARLOTTE, NC") is None
    c = dict(a, parno="22910115", siteadd="7905 ANGELICA LN", structyear=2001)
    d = dict(c, siteadd="8009 ANGELICA LN")
    assert _lookup([c, d]) is None, "stacked houses with no address to choose by"


def test_lenoirs_cr_is_a_circle():
    assert nc._comparable("736 CAVALIER CR") == nc._comparable("736 CAVALIER CIR")
