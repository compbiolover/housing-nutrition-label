#!/usr/bin/env python3
"""Pennsylvania — four counties, each from its own county's parcel layer, one request each.

Pennsylvania has no statewide assessment layer. Assessment is a county function
(the Consolidated County Assessment Law), each county keeps its own CAMA system,
and the state's GIS clearinghouse (PASDA, ``maps.pasda.psu.edu``, 179 services)
carries imagery and parcel shapes but no building attributes. So this is not a
statewide adapter in Florida's or Connecticut's sense: it is four county
adapters sharing one module, the way Utah's 28 county layers share ``ut.py``.
Each county below publishes, keylessly, a parcel layer that carries the shape and
the assessor's residential card on one record, so every lookup is a point query
against ONE service — the county's own — chosen by ``COUNTIES``:

  =================  =====  ========================================  ==========
  county             FIPS   layer                                     ACS units
  =================  =====  ========================================  ==========
  Montgomery         42091  Montgomery_County_Parcels/FeatureServer/6    350,351
  York               42133  YCPC OPEN_DATA/Parcels/MapServer/0           189,857
  Northampton        42095  Land_Records_LGM/MapServer/0                 129,448
  Cumberland         42041  Tax_Parcels/FeatureServer/0                  111,278
  =================  =====  ========================================  ==========

780,934 housing units (this repository's ``year_built_county.csv``). What each
layer carries, measured 2026-10-03:

* **Montgomery** — ``YEAR_BUILT``, ``SFLA``, padded-text ``STORIES``, a one-digit
  ``EXTWALL``, and ``LIV_UNITS``, an explicit count of living units. 237,354 of
  237,460 single-family parcels (land use 1101) carry a year; "not recorded" is 0.
* **York** — ``YRBLT``, ``RES_LIVING_AREA``, ``NUM_STORIE`` and a land-use code
  whose meaning ships WITH the layer as a coded-value domain ("R - Two Family
  Residential"). 139,261 of 150,611 residential parcels carry a year. No wall
  material; ``GRADE`` and ``CDU`` exist and are 100% empty.
* **Northampton** — ``RES_YEAR_BUILT``, ``SQFT_LIVING_AREA``, ``NUMBER_OF_STORIES``
  and ``NUMBER_OF_CARDS``. The trap: the layer also has a ``YEAR_BUILT`` column
  and it is NULL on all 123,361 parcels; the residential year is
  ``RES_YEAR_BUILT`` (91,411 of 91,513 single-family parcels). Land-use codes are
  decoded by the county's own "Tax Record Codes and Descriptions" PDF.
* **Cumberland** — decoded words rather than codes: the year as a STRING
  (``YEAR_BLT``), ``SQFT``, ``STORY_HEIG`` ("2 Stories", "1.5 Stories (Ul 33% Of
  Lla)", "Split-Level"), ``PRIMARY_EX`` ("Vinyl", "Brick", …), ``DWELLING_T``
  ("Single Family", "Unit In Town House", "Condominium Unit", …) and the land use
  as "Residential 1 Family (101)". 72,296 of 72,309 one-family parcels carry a
  year.

Not here, and why
-----------------
* **Philadelphia** (42101) has its own adapter, ``phl.py``; **Allegheny** (42003)
  is a two-hop adapter of its own (parcel layer, then WPRDC's CC0 table).
* **Berks** (42011) was measured and is EXCLUDED pending a product decision. Its
  data is as good as Montgomery's (parcel layer, then a CAMA residential table
  with ``YRBLT``, ``SFLA``, ``EXTWALL``, ``PHYCOND``), but the County of Berks GIS
  Data General Agreement, clause 3, says the data "may NOT be copied,
  redistributed, resold, transferred, leased, or provided in whole or part to any
  other entity or person", and clause 4 requires a citation on any product that
  incorporates it. Showing a derived value with attribution may be within clause
  4; that is a licensing call, not an engineering one.
* **Lehigh** (42077) was measured and is EXCLUDED. The county's own server sits
  behind a bot wall; the only keyless source is a building-footprint layer
  (``BuildingsByAge``) last edited 2022-04-21 whose newest house is from 2015,
  licensed "Not to be sold. Some age data may not be accurate."
* **No year built in public GIS** (checked 2026-10-03): Bucks (42017), Delaware
  (42045), Chester (42029), Lancaster (42071 — its "Buildings" layer's YEAR is a
  capture date), Westmoreland (42129), Luzerne (42079), Dauphin (42043) and Erie
  (42049). Their parcel layers carry shapes, addresses, values and owners, and no
  building characteristics, so they fail the screening test
  (``parcel-level-data-research.md`` §4.1) outright.

Choosing the parcel, and the one-address-one-home rule
------------------------------------------------------
``_shared.select_parcel`` chooses first, as everywhere. Then one more rule,
which this module applies to every lookup that has an address: **the address
must name exactly one home within the 80 m search radius**, and that home must be
the one chosen. Rows sharing a parcel id are one parcel first (a multipart parcel
comes back once per polygon part — Montgomery's 370004317668, Northampton's "R7
22 19"); rows that share an id and disagree are a broken join and not offered.

The rule exists because the first end-to-end run found a wrong parcel that
``select_parcel`` could not have refused: Cumberland files a 1922 house on 1.05
acres and a 1960 house on 0.41 acres both as "529 W SIMPSON STREET". The geocode
landed inside the 1960 one, the address agreed, and containment confirmed it;
the sampled home was the other. Containment confirms an address, not a home.
The cost is one more request on lookups containment answered (median 0.14 s);
a rival must itself report something, so a vacant side lot carrying the house's
number does not refuse the house.

Condominiums
------------
The same rule is what makes condominiums safe, and Montgomery is the county
that needs it. Its units are their own parcels with their own small polygons,
**side by side, not stacked**: a point inside 2539 Jenkintown Rd returned exactly
ONE unit, #106, from a building whose units all share that street address. So a
containment hit on a condominium is an arbitrary unit, and ``select_parcel`` —
one candidate, address agrees — would confirm it. Here:

* A unit (``LOC_UNITNO`` in Montgomery; "UNIT 5" written into the address in
  Northampton, York and Cumberland) is answered only when the reader typed that
  unit — carried from the typed address by ``location.assessor_address`` — and
  exactly one parcel nearby agrees on address AND unit.
* A reader who typed no unit is never matched to a unit, and a unit with no
  address to confirm against is never answered from containment.
* Parcels naming a DIFFERENT unit are dropped before the choice (Utah's rule), so
  a stack of units can become one; the association's common-area parcel, which
  carries the building's address with no unit and no facts, cannot be anybody's
  unit and does not stand as a rival to the reader's.
* A unit's own floor area is its own (Montgomery #109: ``SFLA`` 882, matching
  "Square Feet of Living Area 882" on the county's record page), so it is
  reported. Its stories are not: the same page reads "Condo Level 1 … Number of
  Stories 2" — ``STORIES`` on a unit is the BUILDING's height.

This adapter's verification run found that the shared unit pattern let "ste"
run into the unit with no separator, so the geocoder's "147 LANTERN LN,
STEWARTSTOWN, PA" read as unit "WARTSTOWN"; the pattern now requires a separator
(see ``_shared._TYPED_UNIT_RE``).

One home, or the area is refused
--------------------------------
The label's ``sqft`` and ``stories`` mean one dwelling. Each county states it
differently, and only an explicit statement counts:

* Montgomery: ``LIV_UNITS == 1``. 5,485 base parcels say 2, 1,046 say 3.
* York: a land-use code naming one home (101–109, 112–116, 118, 119). Not 111
  "Residence And Mobile Home", 122/123 two/three family, 110 residence with
  commercial, or any farm (a farm can carry a tenant house).
* Northampton: land use 110 single family, 151/152 condominium, 171–173 mobile
  home or 199 parsonage, AND ``NUMBER_OF_CARDS == 1`` — 530 parcels carry a
  second residential card, whose area the figure may include.
* Cumberland: a one-unit land use (101, 107, 108, 121, 131) and a dwelling type
  that is not itself several homes ("Two Or Three Apartments", "Duplex Double").
  "Duplex Half (Two Family)" under 101 is Pennsylvania's half-double, one side
  of a twin on its own parcel (2,882 of them), and is one home.

The year survives all of these — the building went up when it went up — except
where the record says nobody lives there: Montgomery ``LIV_UNITS == 0``, and a
common-area parcel with no living unit recorded; York's and Northampton's
vacant, common-area and auxiliary codes; and in Cumberland a year with no
dwelling type on a non-residential land use, because Cumberland's ``YEAR_BLT``
is not a residential card's alone — offices, warehouses and cell towers carry
one. Silence (a blank count) is never a refusal, for the reason Florida's
dwelling count gives. Stories additionally need a whole number: York reads them
only where a land use that NAMES a story count (101, 102, 103) agrees with
``NUM_STORIE`` (45,443 of 45,495 do for 101), and split levels, high ranches and
half stories have no reading.

The year built
--------------
Actual year only; no county publishes an effective year in these layers, and
Montgomery's ``YR_REM`` (remodel year) is not requested. 0 and blank are "not
recorded". **Cumberland writes 1776 as a placeholder**: 6,255 records with no
dwelling carry it, every cell-tower lease among them, and so do 395 dwellings
against 10 at 1775 and 23 at 1780 — 13 of them mobile or manufactured homes. It
is refused. The heaping at 1800 in all four counties (969 in Montgomery) is an
assessor's round estimate for an old house, as 1900 is, and is kept.

Wall material, and the code tables
----------------------------------
Translated only where a published table makes the code's MEANING unambiguous:

* Montgomery's ``EXTWALL`` digit has no table in the layer, but the county's
  record pages (propertyrecords.montcopa.org, "Exterior Wall Material") print the
  decoded word for every parcel, and 26 parcels checked — three per code — agreed
  without exception: 1 FRAME, 2 BRICK, 3 MAS&FRAME, 4 BLOCK, 5 STUCCO, 6
  ALUM/VINYL, 7 STONE, 8 ASBESTOS, 9 CONCRETE. ``_MONTGOMERY_WALL`` translates
  the words that name a structure the label has, and lists the rest.
* Cumberland publishes the words themselves; ``_CUMBERLAND_WALL`` likewise.
* Northampton's ``EXTERIOR`` (01–09) appears in no table the county publishes —
  its codes PDF covers land use, outbuildings and additions — and is not
  requested. York publishes no wall at all.
* Montgomery's ``CONDITION`` (1–6) is decoded nowhere, not even on the record
  pages, and 225,026 of 237,460 single-family parcels hold the one value 3; it is
  not requested. No county publishes a foundation type.

Timing
------
Measured through the product's HTTP session at 160 real rooftops (40 per county,
drawn at random from the layers themselves), with the module's own field lists:

  ==============  ====================================  ====================================
  county          "which parcel is this dot inside?"    "what is within 80 m of this dot?"
                  median    p90     p95     max         median    p90     p95     max
  ==============  ====================================  ====================================
  Montgomery      0.14 s   0.16 s  0.16 s  0.53 s       0.15 s   0.16 s  0.17 s  0.22 s
  York            0.11 s   0.13 s  0.13 s  0.65 s       0.13 s   0.14 s  0.15 s  0.16 s
  Northampton     0.07 s   0.08 s  0.10 s  0.50 s       0.10 s   0.11 s  0.11 s  0.12 s
  Cumberland      0.14 s   0.18 s  0.20 s  0.29 s       0.23 s   0.30 s  0.34 s  0.43 s
  all four        0.13 s   0.15 s  0.19 s  0.65 s       0.14 s   0.25 s  0.28 s  0.43 s
  ==============  ====================================  ====================================

Each maximum is the first request on a fresh connection. An 80 m buffer returned
at most 86 parcels against transfer limits of 1,000 and 2,000. The county
request a direct call makes (Census TIGERweb counties) took 0.41–0.51 s over five.
So the SHARED clock stands — one-second read slice, four-second budget — and
``READ_SLICE_S``/``LOOKUP_TIMEOUT`` are named only so every request visibly
passes them; a test pins their sum under ``config.UPSTREAM_HOST_BUDGET``.

What the adapter is worth, end to end
-------------------------------------
220 homes drawn at random from the four layers themselves (random object ids
among residential records with a year; 72 Montgomery, 56 York, 46 Northampton,
46 Cumberland), each typed as "<roll address>[ #unit], PA <ZIP>", geocoded
through the Census matcher and ``assessor_address`` exactly as the product does,
then looked up with NO county passed (so the county request is exercised too):

  =====================================  =====  =====  =====  =====  =====
  (Montgomery / York / Northampton /       all     MC     YK     NH     CU
  Cumberland)
  =====================================  =====  =====  =====  =====  =====
  sampled                                  220     72     56     46     46
  geocoded                                 208     67     53     44     44
  routed by the geocoder to that county    208     67     53     44     44
  resolved                                 164     55     39     39     31
  **matched to the wrong parcel**        **0**      0      0      0      0
  year built exact                     164/164
  floor area reported / exact          155/155
  stories reported                         136
  wall translated                           70   (frame 42, brick 14, vinyl 14)
  =====================================  =====  =====  =====  =====  =====

79% of geocoded homes resolve. The 44 that did not: 38 geocodes that land more
than 80 m from the home's own parcel (rural road interpolation, mostly — the
nearest parcel with that address is simply out of reach); 5 spellings the shared
comparison does not reconcile, each a Census rewrite of the roll's street name
("DOUGLAS" for DOUGLASS, "MOUNTAINVIEW" for MOUNTAIN VIEW, "BRIARPATCH" for
BRIAR PATCH, "HEATHERWOOD HILL" for HEATHERWOOD HILLS RD, and an added "E" on a
roll's plain PLEASANT AVE — the last refused on purpose, as Utah refuses a
directional the roll does not write); and 1 refused by the one-address-one-home
rule (529 W Simpson Street, above). 12 typed addresses were unknown to Census.
End to end a lookup took a median of 0.34 s (p95 0.49 s, slowest 1.21 s),
county request included.

The first run, before two fixes, found 1 wrong parcel (529 W Simpson — hence
the rule) and 29 Northampton records whose id had lost its inner spacing
("Q6NW3 8 4A" for the county's "Q6NW3  8  4A"); ids are now trimmed only at the
ends.

The random sample holds only three condominiums, so the unit path was measured
separately: units drawn at random from parcels that share a street address with
other units, each typed twice, with and without the unit.

  ==========================  ==============================  ==================
  units sharing an address    typed WITH the unit             typed WITHOUT
  ==========================  ==============================  ==================
  Montgomery (30)             15 right unit, **0 wrong**,     0 answered,
                              14 refused, 1 not geocoded      29 refused
  Northampton (15)            3 right unit, **0 wrong**,      0 answered,
                              12 refused                      15 refused
  ==========================  ==============================  ==================

The refusals are geocodes more than 80 m from the unit's own polygon (the
Census point for 2830 Linden St, Bethlehem, sits among units 3A–3F, not 1A), two
Telford units the geocoder places across the line in Bucks, and units the roll
writes in a form no reader types ("CONDO 219", "108 U-3").

Privacy, and why the field lists are short
------------------------------------------
Every one of these layers carries owner names and mailing addresses beside the
geometry (Montgomery ``OWN1``/``ADDR1-3``; York ``OWNER_FULL``/``MAIL_ADDR*``/
``PREV_OWNER``; Northampton ``OWNERS_NAME_1/2``/``MAIL_ADDRESS_1-3``; Cumberland
``OWNER``), and sale prices and taxes. Six to ten columns per county are
requested by name; the shared helper refuses ``*``. Nothing from these sources is
written into the repository.

License
-------
Read 2026-10-03, from each layer's ArcGIS Online item (``licenseInfo``) or the
service itself. None grants an explicit license, and none prohibits querying,
caching or commercial use; the posture is the one every adapter takes — query
live, cache in process, bundle nothing — with each county credited on the record.

* **Montgomery** (item 228cad7975554088a350bee4caf3ca45): "Montgomery County
  provides this data as a free and open resource … All data is provided 'as is'
  without warranties of any kind." Open.
* **York** (item 803b4da39e7b457ab6e7a5eeb3410abb, published in YCPC's
  ``OPEN_DATA`` folder): "Intended for illustration and demonstration purposes
  only … THE DATA AND METADATA HAS BEEN DEVELOPED SOLELY FOR INTERNAL USE BY YORK
  COUNTY PLANNING COMMISSION … ALL DATA AND METADATA ARE PROVIDED 'AS IS.'" A
  warranty and liability disclaimer, not a grant and not a prohibition; the
  "illustration" wording is the weakest of the four and worth a line to YCPC.
* **Northampton** (item 55902152ae6f40d780fc7d81d8277215 and the service's
  iteminfo): ``licenseInfo`` is EMPTY; the service credits "Northampton County
  GIS Division". No license or disclaimer is published. Assessment records are
  public records in Pennsylvania; whether the county asserts rights in the
  compilation is unknown, and worth asking.
* **Cumberland** (item 6ce565f2f9c04cfaab1e63dc6663ff15): provided "as a public
  information service … intended for informational purposes only … CUMBERLAND
  COUNTY ASSUMES NO LIABILITY". A disclaimer with no use restriction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    cache_bucket, deadline_from, num, same_address, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Pennsylvania county assessment offices"
ATTRIBUTION = ("Montgomery, York, Northampton and Cumberland County (PA) assessment "
               "records via each county's public GIS parcel layer (keyless)")
DATA_VINTAGE = "Pennsylvania county assessment records, queried live from county GIS"

MONTGOMERY_URL = ("https://services1.arcgis.com/kOChldNuKsox8qZD/arcgis/rest/services"
                  "/Montgomery_County_Parcels/FeatureServer/6/query")
YORK_URL = ("https://arcweb1.ycpc.org/server/rest/services/OPEN_DATA/Parcels"
            "/MapServer/0/query")
NORTHAMPTON_URL = ("https://gis.northamptoncounty.org/arcgisweb/rest/services"
                   "/Assessment_Services/Land_Records_LGM/MapServer/0/query")
CUMBERLAND_URL = ("https://services1.arcgis.com/1Cfo0re3un0w6a30/arcgis/rest/services"
                  "/Tax_Parcels/FeatureServer/0/query")
#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (the registry always does). See ``_county_at``.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
              "/State_County/MapServer/1/query")

#: How long a county service may go quiet before the silence is a stall, and the
#: budget for a whole lookup. Both are the SHARED defaults, kept on purpose and
#: named here only so every request visibly passes them: measured over 160
#: rooftops (see "Timing" in the module docstring) the slowest of 320 requests
#: took 0.65 s, and a lookup makes at most three (county, containment, the 80 m
#: neighborhood). Raising them would only let a hung portal hold the label longer.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT


def _text(value) -> str:
    """A county text value with its padding removed ("         2" → "2")."""
    return " ".join(str(value if value is not None else "").split())


def _code(value) -> str:
    return _text(value).upper()


# ── units ──────────────────────────────────────────────────────────────────────

# The marker word a roll sometimes writes INTO its unit column — Montgomery's
# LOC_UNITNO holds "UNIT B" on some rows and "B" on others for the same kind of
# unit — and that a reader types in front of the unit ("#109", "Apt 109").
_UNIT_MARKER_RE = re.compile(r"^(?:UNIT|APT|APARTMENT|STE|SUITE|CONDO|#)\s*", re.I)


def _unit_of(address) -> str | None:
    """The marked unit in an address string, or None (``_shared.unit_of``)."""
    return unit_of(address)


def _norm_unit(value) -> str | None:
    """A unit designator in comparable form, or None for "no unit".

    Case, spaces, punctuation and a leading marker word are noise ("UNIT B",
    "#b", "b"); leading zeros are not, because unit 01 and unit 1 can both exist
    in one building — the District adapter's call, for the same reason.
    """
    text = _UNIT_MARKER_RE.sub("", _text(value).upper())
    norm = "".join(ch for ch in text if ch.isalnum())
    return norm or None


def _pid(column: str) -> Callable[[dict], str | None]:
    """A parcel-id reader. Only the ends are trimmed: Northampton's ids carry
    meaningful inner spacing ("Q6NW3  8  4A"), and collapsing it would make the
    id that travels with the record differ from the county's own."""
    return lambda row: str(row.get(column) or "").strip() or None


def _unit_from_address(column: str) -> Callable[[dict], str | None]:
    """A unit reader for a roll that writes the unit into its address string."""
    return lambda row: _norm_unit(_unit_of(row.get(column)))


# ── one county's facts ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _County:
    """Everything that differs between the four county layers.

    The parcel choice, the condominium rule and the record assembly are shared
    below; only these readers know a county's columns and code tables.
    """

    name: str
    url: str
    fields: str                                  # explicit outFields, never "*"
    source: str                                  # attribution on the record
    vintage: str
    pid: Callable[[dict], str | None]
    address: Callable[[dict], str | None]
    unit: Callable[[dict], str | None]           # normalized, or None
    shares_a_building: Callable[[dict], bool]    # a unit of a multi-unit property
    says_no_home: Callable[[dict], bool]         # an explicit "nobody lives here"
    one_dwelling: Callable[[dict], bool]         # the area describes ONE home
    year: Callable[[dict], float | None]
    area: Callable[[dict], float | None]
    stories: Callable[[dict], int | None]        # already gated on one dwelling
    construction: Callable[[dict], str | None]


def _whole_stories(value) -> int | None:
    """A whole-number story count, or None — a half story is not rounded into
    one, the call Cook makes for "1.5 Story" and the District for 2.5."""
    v = num(_text(value) or None)
    return int(v) if v is not None and v > 0 and float(v).is_integer() else None


# ── Montgomery 42091 ───────────────────────────────────────────────────────────

# EXTWALL is a one-digit code. Montgomery publishes no code table with the layer,
# but the county's own record pages (propertyrecords.montcopa.org, "Exterior Wall
# Material") print the decoded wording for every parcel, and 26 parcels checked
# there — three per code, two for the rare 9 — agreed without exception (measured
# 2026-10-03): 1 FRAME, 2 BRICK, 3 MAS&FRAME, 4 BLOCK, 5 STUCCO, 6 ALUM/VINYL,
# 7 STONE, 8 ASBESTOS, 9 CONCRETE. Translated from those words:
_MONTGOMERY_WALL = {
    "1": "frame",        # FRAME
    # BRICK. Unqualified, as DC's "Face Brick" is, and read the same way: as
    # brick. A brick face can be veneer on a frame, which the county does not
    # say; that is the knowingly lossy part, paid for in confidence (TRANSLATED).
    "2": "brick",
    "4": "block",        # BLOCK
    "6": "frame",        # ALUM/VINYL — aluminum OR vinyl siding, framed either way
    "7": "stone",        # STONE
    # ASBESTOS — asbestos-cement shingle siding, which is cladding hung on a
    # framed wall (the District reads its "Shingle" the same way).
    "8": "frame",
}
# Deliberately unmapped:
#   3 MAS&FRAME   masonry AND frame, but the masonry may be stone; `brick-frame`
#                 would assert brick (Utah's "Frame: Masonry Veneer" call)
#   5 STUCCO      applied over frame and over masonry alike (Cook's and DC's call)
#   9 CONCRETE    cast concrete is not concrete block, the label's only concrete
# CONDITION (codes 1–6) is not requested at all: the county's record pages do
# not show it, so nothing decodes it, and 225,026 of 237,460 single-family
# parcels sit on the one value 3 — a guess at "average" would be a guess.


def _montgomery_units(row: dict) -> int | None:
    v = num(_text(row.get("LIV_UNITS")) or None)
    return int(v) if v is not None else None


def _montgomery_shares(row: dict) -> bool:
    return (_code(row.get("PARCELTYPE")) in ("CONDOMINIUM", "MOBILE HOME")
            or bool(_text(row.get("LOC_UNITDE"))) or bool(_text(row.get("LOC_UNITNO"))))


def _montgomery_no_home(row: dict) -> bool:
    units = _montgomery_units(row)
    if units == 0:
        return True
    # A common-area parcel is the association's land — a clubhouse, a pool house
    # ("PEBBLE BEACH DR", 5,837 sq ft, 2007). It counts as a home only where the
    # county explicitly records a living unit on it: 404 do, and carry real house
    # addresses ("332 W BROAD ST").
    return _code(row.get("PARCELTYPE")) == "COMMON AREA" and not (units and units >= 1)


def _montgomery_one(row: dict) -> bool:
    return _montgomery_units(row) == 1


def _montgomery_stories(row: dict) -> int | None:
    # A condominium unit's STORIES is the BUILDING's: 2539 Jenkintown Rd #109
    # reads "Condo Level 1 … Number of Stories 2" on the county's record page.
    if _code(row.get("PARCELTYPE")) == "CONDOMINIUM":
        return None
    return _whole_stories(row.get("STORIES"))


MONTGOMERY = _County(
    name="Montgomery",
    url=MONTGOMERY_URL,
    # Owner (OWN1/OWN2/CAREOF), mailing (ADDR1-3), sale and tax columns are never
    # requested; nor is CONDITION (undecodable) or YR_REM (a remodel year).
    fields=("PARCEL,PARCELTYPE,LIV_UNITS,LOCATION1,LOC_UNITDE,LOC_UNITNO,"
            "YEAR_BUILT,SFLA,STORIES,EXTWALL"),
    source="Montgomery County (PA) assessment records via Montgomery County GIS (keyless)",
    vintage="Montgomery County assessment database, republished monthly",
    pid=_pid("PARCEL"),
    address=lambda r: _text(r.get("LOCATION1")) or None,
    unit=lambda r: _norm_unit(r.get("LOC_UNITNO")),
    shares_a_building=_montgomery_shares,
    says_no_home=_montgomery_no_home,
    one_dwelling=_montgomery_one,
    year=lambda r: num(r.get("YEAR_BUILT")),
    area=lambda r: num(r.get("SFLA")),
    stories=_montgomery_stories,
    construction=lambda r: _MONTGOMERY_WALL.get(_code(r.get("EXTWALL"))),
)


# ── York 42133 ─────────────────────────────────────────────────────────────────

# York's land-use codes are published WITH the layer, as the LUC field's coded-
# value domain (measured 2026-10-03). The ones this adapter reads:
#
#   one dwelling  101 one story, 102 two story, 103 three story, 104 2½ story,
#                 105 1½ story, 106 split level, 107 high ranch, 108 townhouse/
#                 row house, 109 cabin, 112 residence on retirement property,
#                 113 condominium, 114 single-wide, 115 double-wide, 116
#                 converted mobile home, 118 subsidized condo, 119 condo/planned
#                 community
#   NOT one       110 residence with commercial, 111 residence AND mobile home,
#                 121 bed and breakfast, 122 two family, 123 three family, every
#                 farm (9xx: a farm can carry a tenant house beside the farmhouse)
#   no home here  100 residential vacant land, 117 vacant space in a mobile-home
#                 park, 124 common area, 126 retention pond, 130 residential
#                 auxiliary (vacant land with an improvement), 150 condominium
#                 master record, 197 vacant split, 200/300/397/500/600/700/900/901
#                 vacant land of every class
#
# YRBLT is the residential card's year (commercial buildings carry their own
# COMM_YEAR_BUILT, never requested), so a residential year on a commercial or
# exempt parcel — 607 "Exempt – Veterans", 319 mixed residential/commercial —
# is a dwelling's and is kept; only the codes that say no building is a home are
# refused. GRADE and CDU have code tables too, and are 100% empty.
_YORK_ONE = frozenset({"101", "102", "103", "104", "105", "106", "107", "108", "109",
                       "112", "113", "114", "115", "116", "118", "119"})
_YORK_CONDO = frozenset({"113", "118", "119", "150"})
_YORK_NO_HOME = frozenset({"100", "117", "124", "126", "130", "150", "197", "200",
                           "300", "397", "500", "600", "700", "900", "901"})
# Codes that NAME a story count. NUM_STORIE agrees with them on 99.9% of rows
# (45,443 of 45,495 for 101), and the label reads stories only where both say
# the same thing. Split levels and high ranches (106, 107) have no whole-number
# reading and the half-story codes (104, 105) none either.
_YORK_LUC_STORIES = {"101": 1, "102": 2, "103": 3}
_YORK_NO_STORIES = frozenset({"104", "105", "106", "107"})


def _york_stories(row: dict) -> int | None:
    luc = _code(row.get("LUC"))
    if luc in _YORK_NO_STORIES or luc in _YORK_CONDO:
        return None
    floors = _whole_stories(row.get("NUM_STORIE"))
    if luc in _YORK_LUC_STORIES:
        return floors if floors == _YORK_LUC_STORIES[luc] else None
    return floors


YORK = _County(
    name="York",
    url=YORK_URL,
    # OWNER_FULL, OWN_NAME1/2, MAIL_ADDR*, PREV_OWNER, SALEDT/PRICE and every
    # value column are never requested.
    fields="PIDN,PROPADR,LUC,NUM_STORIE,RES_LIVING_AREA,YRBLT",
    source="York County (PA) Assessment via York County Planning Commission GIS (keyless)",
    vintage="York County assessment parcels, republished weekly",
    pid=_pid("PIDN"),
    address=lambda r: _text(r.get("PROPADR")) or None,
    unit=_unit_from_address("PROPADR"),
    shares_a_building=lambda r: (_code(r.get("LUC")) in _YORK_CONDO
                                 or bool(_unit_of(r.get("PROPADR")))),
    says_no_home=lambda r: _code(r.get("LUC")) in _YORK_NO_HOME,
    one_dwelling=lambda r: _code(r.get("LUC")) in _YORK_ONE,
    year=lambda r: num(r.get("YRBLT")),
    area=lambda r: num(r.get("RES_LIVING_AREA")),
    stories=_york_stories,
    construction=lambda r: None,      # York publishes no wall material
)


# ── Northampton 42095 ──────────────────────────────────────────────────────────

# Land-use codes from the county's own "Northampton Tax Record Codes and
# Descriptions" (ncpub.org/_Web/content/NHCodes_Descriptions.pdf, fetched
# 2026-10-03):
#
#   one dwelling  110 single family, 151 condo (common element), 152 condo (fee
#                 simple), 171/172/173 mobile home (owned land / rented land /
#                 in a park), 199 parsonage
#   NOT one       120 "2-4 family", 160 mixed residential/commercial, 210 rural
#                 property with residence (a farm can hold more than one)
#   no home here  90–99 vacant land of every class, 100 exempt institutional
#                 vacant, 101 conservation/floodplain, 102 landfill, 180
#                 auxiliary improvements, 200 rural land without buildings
#
# EXTERIOR (codes 01–09) and BUILDING_STYLE are in the layer and in no table the
# county publishes — the codes PDF lists land use, outbuildings and additions,
# not walls — so neither is requested.
_NORTHAMPTON_ONE = frozenset({"110", "151", "152", "171", "172", "173", "199"})
_NORTHAMPTON_CONDO = frozenset({"151", "152"})
_NORTHAMPTON_NO_HOME = frozenset({"90", "91", "92", "93", "94", "95", "96", "97",
                                  "98", "99", "100", "101", "102", "180", "200"})


def _northampton_cards(row: dict) -> float | None:
    return num(row.get("NUMBER_OF_CARDS"))


def _northampton_one(row: dict) -> bool:
    # NUMBER_OF_CARDS counts residential building records (commercial cards are
    # COMM_CARDS). 101,420 parcels carry one; the 530 with two or more hold a
    # second dwelling building, whose area the published figure may include.
    return (_code(row.get("LUC")) in _NORTHAMPTON_ONE
            and _northampton_cards(row) == 1)


def _northampton_stories(row: dict) -> int | None:
    if _code(row.get("LUC")) in _NORTHAMPTON_CONDO:
        return None
    return _whole_stories(row.get("NUMBER_OF_STORIES"))


NORTHAMPTON = _County(
    name="Northampton",
    url=NORTHAMPTON_URL,
    # YEAR_BUILT is in the schema and EMPTY on every one of the 123,361 parcels;
    # the residential card's year is RES_YEAR_BUILT (COM_YEAR_BUILT is a
    # commercial building's, never requested). OWNERS_NAME_1/2, MAIL_ADDRESS_1-3,
    # SALE_* and values are never requested.
    fields=("PARCEL_ID,LOCATION,LUC,NUMBER_OF_CARDS,NUMBER_OF_STORIES,"
            "SQFT_LIVING_AREA,RES_YEAR_BUILT"),
    source="Northampton County (PA) Assessment via Northampton County GIS Division (keyless)",
    vintage="Northampton County assessment records, joined live to the parcel map",
    pid=_pid("PARCEL_ID"),
    address=lambda r: _text(r.get("LOCATION")) or None,
    unit=_unit_from_address("LOCATION"),
    shares_a_building=lambda r: (_code(r.get("LUC")) in _NORTHAMPTON_CONDO
                                 or bool(_unit_of(r.get("LOCATION")))),
    says_no_home=lambda r: _code(r.get("LUC")) in _NORTHAMPTON_NO_HOME,
    one_dwelling=_northampton_one,
    year=lambda r: num(r.get("RES_YEAR_BUILT")),
    area=lambda r: num(r.get("SQFT_LIVING_AREA")),
    stories=_northampton_stories,
    construction=lambda r: None,
)


# ── Cumberland 42041 ───────────────────────────────────────────────────────────

# Cumberland publishes decoded text, not codes: LUC as "Residential 1 Family
# (101)", DWELLING_T as "Single Family" / "Unit In Town House" / …, the year as a
# STRING, stories as "2 Stories" / "1.5 Stories (Ul 33% Of Lla)" / "Split-Level",
# and the wall as "Vinyl" / "Brick" / "Aluminum" / ….
_LUC_CODE_RE = re.compile(r"\((\d+)\)\s*$")


def _cumberland_luc(row: dict) -> str | None:
    m = _LUC_CODE_RE.search(_text(row.get("LUC")))
    return m.group(1) if m else None


# LUC codes whose own words say one dwelling unit: 101 Residential 1 Family, 107
# Condominium (Fee Simple), 108 Mobile Home, 121 Seasonal Dwelling, 131 Planned
# Community (Fee Simple). 102/103 (2 and 3 family), the farm and Clean & Green
# codes (a farm can hold a tenant house) and every apartment code are not.
_CUMBERLAND_ONE_LUC = frozenset({"101", "107", "108", "121", "131"})
# DWELLING_T values that are themselves more than one home. "Duplex Half (Two
# Family)" is NOT here: under LUC 101 it is one side of a half-double on its own
# parcel (2,882 parcels) — Pennsylvania's twin house — and the LUC gate above
# already refuses it where the parcel is coded two-family.
_CUMBERLAND_MULTI_DWELLING = frozenset({
    "two or three apartments", "duplex double (two family)", "duplex",
})
_CUMBERLAND_STORIES = {"1 story": 1, "2 stories": 2, "3 stories": 3}
# Already words; translated only where the word names a structure the label has.
_CUMBERLAND_WALL = {
    "vinyl": "vinyl",
    "brick": "brick",            # unqualified, read as DC reads "Face Brick"
    "aluminum": "frame",         # siding: cladding hung on a framed wall
    "wood": "frame",
    "t-111 plywood": "frame",
    "masonite": "frame",
    "hardy plank": "frame",      # fiber-cement lap siding
    "clapboard": "frame",
    "asbestos": "frame",         # asbestos-cement shingle siding
}
# Deliberately unmapped: "Stone/Masonry" (stone OR some other masonry), "Stucco"
# (over frame and masonry alike), "Concrete/Block" (cast concrete or block),
# "Drivit" (EIFS, applied over frame or block), "Log" (no log value), "Metal"
# (siding or a steel building), "Composition" and "Asphalt" (roll or shingle
# sidings on unstated walls), "Siding Non-Specific", "Single Siding", "Other",
# "No Value/Na", "Reinforc Concr".


#: Cumberland's placeholder year. 6,255 records with no dwelling carry it —
#: every "Wireless SF On Leased Land" cell-tower lease among them — and so do 395
#: dwellings, against 10 at 1775 and 23 at 1780, including 13 mobile and
#: manufactured homes, which were not built in 1776. It is the roll's "old,
#: unknown", not a year. (Round-year heaping at 1800, seen in all four counties,
#: is different: an assessor's estimate for an old house, as 1900 is, and kept.)
_CUMBERLAND_PLACEHOLDER_YEAR = 1776


def _cumberland_year(row: dict) -> float | None:
    raw = _text(row.get("YEAR_BLT"))
    if not raw.isdigit() or int(raw) == _CUMBERLAND_PLACEHOLDER_YEAR:
        return None
    return float(raw)


def _cumberland_shares(row: dict) -> bool:
    return (_cumberland_luc(row) == "107"
            or _text(row.get("DWELLING_T")).lower() == "condominium unit"
            or bool(_unit_of(row.get("SITUS"))))


def _cumberland_no_home(row: dict) -> bool:
    """Whether the record says the building with this year is not a home.

    Cumberland's YEAR_BLT is not a residential card's alone: offices, warehouses,
    garages and a cell tower ("Wireless SF On Leased Land (721)") carry one too.
    So a year needs either a recorded dwelling type or a residential/apartment
    land use (1xx, 2xx); 100 is residential VACANT land and says no home outright.
    """
    luc = _cumberland_luc(row)
    if luc == "100":
        return True
    if _text(row.get("DWELLING_T")):
        return False
    return not (luc and luc[0] in "12")


def _cumberland_one(row: dict) -> bool:
    return (_cumberland_luc(row) in _CUMBERLAND_ONE_LUC
            and bool(_text(row.get("DWELLING_T")))
            and _text(row.get("DWELLING_T")).lower() not in _CUMBERLAND_MULTI_DWELLING)


def _cumberland_stories(row: dict) -> int | None:
    if _cumberland_shares(row):
        return None
    return _CUMBERLAND_STORIES.get(_text(row.get("STORY_HEIG")).lower())


CUMBERLAND = _County(
    name="Cumberland",
    url=CUMBERLAND_URL,
    # OWNER, SALEPRICE/SALEDATE and every value and tax column are never requested.
    fields="PID,SITUS,LUC,DWELLING_T,YEAR_BLT,SQFT,STORY_HEIG,PRIMARY_EX",
    source="Cumberland County (PA) Assessment via Cumberland County GIS (keyless)",
    vintage="Cumberland County tax parcels with assessment (CAMA) attributes",
    pid=_pid("PID"),
    address=lambda r: _text(r.get("SITUS")) or None,
    unit=_unit_from_address("SITUS"),
    shares_a_building=_cumberland_shares,
    says_no_home=_cumberland_no_home,
    one_dwelling=_cumberland_one,
    year=_cumberland_year,
    area=lambda r: num(r.get("SQFT")),
    stories=_cumberland_stories,
    construction=lambda r: _CUMBERLAND_WALL.get(_text(r.get("PRIMARY_EX")).lower()),
)


#: County FIPS → that county's layer and readers. Philadelphia (42101) and
#: Allegheny (42003) have adapters of their own; Berks and Lehigh are measured
#: and excluded (see the module docstring).
COUNTIES = {
    "42091": MONTGOMERY,
    "42133": YORK,
    "42095": NORTHAMPTON,
    "42041": CUMBERLAND,
}
COUNTY_FIPS = frozenset(COUNTIES)

#: Each layer's extent in WGS84, rounded outward to 0.01°, measured with
#: returnExtentOnly on 2026-10-03. Used only to skip the county request for a
#: point that cannot be in any of the four; Montgomery's and Northampton's boxes
#: overlap no other, York's and Cumberland's overlap along the Yellow Breeches.
_EXTENTS = {
    "42091": (-75.70, 39.97, -75.01, 40.45),
    "42133": (-77.15, 39.71, -76.22, 40.23),
    "42095": (-75.62, 40.53, -75.04, 40.98),
    "42041": (-77.62, 39.94, -76.85, 40.34),
}


# ── choosing the parcel ────────────────────────────────────────────────────────


def _candidates(county: _County, rows: list[dict]) -> list[dict]:
    """Real parcel records from one response, one per parcel id.

    A multipart parcel comes back once per polygon part (Montgomery's 370004317668
    and Northampton's "R7     22 19" each arrive twice, field for field
    identical), so identical rows sharing an id are one parcel. Rows sharing an id
    that DISAGREE are a broken join, and the parcel is not offered at all — the
    wrong-house failure Connecticut's contradictory rows taught. Rows with no id
    are records of nothing (``select_parcel``'s sanctioned drop).
    """
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        pid = county.pid(row)
        if pid is not None:
            by_id.setdefault(pid, []).append(row)
    out = []
    for group in by_id.values():
        if all(r == group[0] for r in group[1:]):
            out.append(group[0])
    return out


def _unit_agrees(county: _County, row: dict, typed_unit: str | None) -> bool:
    """Whether this row could be the home of a reader who typed ``typed_unit``.

    A row naming a unit must name the reader's — and a reader who typed none
    cannot be matched to any unit at all. A row naming no unit could be the
    reader's (a house, or a duplex filed as one parcel for a reader who wrote
    "Apt 2"), if it is a record of anything.
    """
    own = county.unit(row)
    if own is not None:
        return typed_unit is not None and own == typed_unit
    if typed_unit is None:
        return True
    # A reader who typed a unit, against a row naming none: a duplex filed as one
    # parcel is still a home, but a row that reports nothing at all is not one
    # anybody's unit could be. That is the condominium's common-area parcel, which
    # carries the building's street address with no unit and no year — measured
    # at 2539 Jenkintown Rd — and would otherwise stand as a second candidate
    # beside the reader's own unit and refuse it.
    return _record(county, row) is not None


def _parcel_at(county: _County, lat: float, lon: float, address: str | None,
               *, deadline: float) -> dict | None:
    """The parcel this point belongs to in ``county``'s layer, or None.

    ``select_parcel`` decides first, as everywhere. Then the condominium rule
    (see "Condominiums" in the module docstring): a parcel that is one unit of a
    multi-unit property — or any lookup where the reader typed a unit — is
    accepted only if, among every parcel within the search radius, exactly one
    agrees with the reader on both the address and the unit, and it is the one
    chosen. Containment alone cannot say which unit a point means, because
    side-by-side unit polygons put an arbitrary neighbor under an interpolated
    geocode.
    """
    typed_unit = _norm_unit(_unit_of(address))
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            # A truncated page raises _shared.TruncatedResponse; lookup catches it.
            rows = _shared.arcgis_parcels(county.url, lat, lon, county.fields,
                                          distance_m, deadline=deadline,
                                          read_slice=READ_SLICE_S)
            fetched[distance_m] = _candidates(county, rows)
        found = fetched[distance_m]
        # A reader who typed a unit cannot live in a parcel naming a DIFFERENT
        # unit. Dropping those can turn a stack of units into one; it never
        # admits a parcel the address check would not (select_parcel's rule).
        if typed_unit is None:
            return found
        return [r for r in found if _unit_agrees(county, r, typed_unit)]

    chosen = select_parcel(fetch, address, county.address)
    if chosen is None:
        return None
    if not address:
        # Containment with nothing to confirm against, which select_parcel allows
        # for a parcel that is the only thing under the point — but not for one
        # unit of several: which unit the point means is exactly what it cannot say.
        return None if county.shares_a_building(chosen) else chosen
    if not _unit_agrees(county, chosen, typed_unit):
        return None
    # The address must name ONE home within the search radius, not merely agree
    # with the parcel under the point. Rolls give one street address to two
    # parcels — 529 W Simpson Street, Mechanicsburg is a 1922 house on 1.05 acres
    # and a 1960 house on 0.41 — and to every unit of a condominium; a geocode
    # inside either is confirmed by select_parcel and names a house at random.
    # A rival is a parcel that agrees on the address and the unit AND would itself
    # report something; a vacant side lot carrying the house's number says
    # nothing, and is not confusable with an answer.
    hits = [r for r in fetch(_shared.SEARCH_RADIUS_M)
            if same_address(address, county.address(r))
            and _unit_agrees(county, r, typed_unit)
            and (county.pid(r) == county.pid(chosen) or _record(county, r) is not None)]
    if len(hits) == 1 and county.pid(hits[0]) == county.pid(chosen):
        return chosen
    return None


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the covered county this point is in, or None.

    Needed only when the caller does not pass the county the registry routed on.
    A point outside all four layers' extents costs nothing; inside one, Census
    TIGERweb's county polygons answer (median 0.43 s over 5 requests).
    """
    if not any(x0 <= lon <= x1 and y0 <= lat <= y1
               for x0, y0, x1, y1 in _EXTENTS.values()):
        return None
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "GEOID", "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    found = {_text((f or {}).get("attributes", {}).get("GEOID"))
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


# ── the record ─────────────────────────────────────────────────────────────────


def _record(county: _County, row: dict) -> AssessorRecord | None:
    no_home = county.says_no_home(row)
    year = county.year(row)
    # 0 and blank are each county's "not recorded"; a year below the plausibility
    # floor is junk (Cumberland carries 998, 1049 and 1653 — the last of which
    # the shared floor admits, being a possible colonial year). And a record that
    # says nobody lives here reports nothing: a shop's year is not a home's.
    year_built = (int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                  and not no_home else None)
    one = county.one_dwelling(row) and not no_home
    area = county.area(row)
    sqft = area if (one and area is not None and area > 0) else None
    stories = county.stories(row) if one else None
    construction = county.construction(row) if not no_home else None
    if year_built is None and sqft is None and stories is None and construction is None:
        return None
    return AssessorRecord(
        source=county.source,
        data_vintage=county.vintage,
        parcel_id=county.pid(row),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        construction=construction,
        # None of the four publishes a foundation type; Montgomery's condition
        # codes are undecodable and the others publish none (York's CDU column
        # exists and is empty).
    )


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    deadline = deadline_from(None, LOOKUP_TIMEOUT)
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips not in COUNTIES:
        fips = _county_at(lat, lon, deadline=deadline)
    if fips is None:
        return None
    county = COUNTIES[fips]
    row = _parcel_at(county, lat, lon, address, deadline=deadline)
    return _record(county, row) if row else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address (carrying the reader's unit,
    via ``location.assessor_address``), used to confirm the parcel and, for a
    condominium, the unit. ``county_fips`` is the county the registry routed on;
    without it the county is looked up from the point (one extra request).

    Fails open on everything — a timeout, a 500, a truncated page, a renamed
    column. The caller then keeps whatever it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Pennsylvania assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None

