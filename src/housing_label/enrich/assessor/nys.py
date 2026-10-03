#!/usr/bin/env python3
"""New York State — the 33 opt-in counties outside New York City, from one statewide layer.

New York assesses property in its 900-odd cities and towns, and every one of them
files its roll with the state's Office of Real Property Tax Services (ORPTS) in a
common format. NYS ITS Geospatial Services joins those rolls to the parcel maps the
counties send in and publishes the result as one layer — but only for the counties
that have *given permission* for public release. That is the whole shape of this
adapter: one statewide layer, like Florida and Connecticut, over a map with holes in
it. A lookup makes at most three requests to it — containment, the
address-confirmed 80 m buffer when containment does not confirm, and the
address-uniqueness check described below for any address-confirmed answer.

  ``Parcels/NYS_Tax_Parcels_Public/FeatureServer/1`` on GeoHub — 3,827,530 parcels
  in 38 counties, keyless, verified live 2026-10-03. Outside New York City,
  2,185,852 residential (class 2xx) parcels, **1,669,160 of them with a year
  built**.

The address in the research plan is not the one used
-----------------------------------------------------
The plan names ``gisservices.its.ny.gov/.../NYS_Tax_Parcels_Public/MapServer/1``.
ITS has migrated every service to its new GeoHub server, and its migration page
(``gis.ny.gov/migration-web-services``) says the legacy copies "stop receiving
updates on September 18th, 2026" and "remain online through October". An adapter
pointed at the old address would go dark within the month — and, failing open,
would look exactly like a state with no records. The GeoHub layer has the same
schema (only the shape-length column names differ) and returned identical
per-county counts, and it is also the faster of the two by far (see the clock,
below).

Which counties — taken from the data, not from the state
--------------------------------------------------------
Derived 2026-10-03 by grouping the layer on ``COUNTY_NAME`` (and cross-checked
against the service's own footprint layer, ``FeatureServer/0``, which carries
``COUNTY_FIPS``): 38 counties are present, five of them the boroughs of New York
City. The city's rows come from MapPLUTO with a different property-class code
system, and a separate adapter answers for them from PLUTO directly, so they are
not claimed here. The other 33 all carry ``YR_BLT`` on residential parcels.

Two of the 33 carry it for only part of the county, and are kept anyway because
the part is large: in **Suffolk** only Southampton, Smithtown, Riverhead and Shelter
Island file a residential inventory (76,935 of 464,486 residential parcels) —
Brookhaven, Islip, Huntington, Babylon and East Hampton file none — and in
**Westchester** 110,166 of 190,972, with Cortlandt, Mount Vernon, Peekskill,
Bedford and Eastchester nearly empty. A lookup there costs one fast request and
answers nothing, which is the same thing as having no adapter.

Nassau, Monroe, Dutchess, Saratoga and the other 20 counties that have not opted
in are absent from the layer and are not claimed.

What this source carries, and what it does not
----------------------------------------------
Two fields reach the label: ``YR_BLT`` and ``SQFT_LIVING`` ("square footage of
living area (residential)", from the ORPTS residential inventory).

* ``BLDG_STYLE_DESC`` is an *architectural style* — Colonial, Ranch, Cape cod,
  Raised ranch, Old style — not a wall material, so ``construction`` stays empty.
  There is no storey count, foundation or condition in the public schema.
* ``HEAT_TYPE_DESC``, ``FUEL_TYPE_DESC``, ``SEWER_DESC`` and ``WATER_DESC`` are
  what make this the only candidate source with heating fuel, sewer and water
  supply. They are **future inputs**: ``AssessorRecord`` has no slot for them, and
  feeding Energy, Environmental or Water Quality means extending that contract
  and the scoring paths first, as its own change. Until something reads them they
  are not fetched.
* ``YR_BLT`` is null, never zero, where it is not recorded, and every recorded
  value outside the city lies between 1700 and 2025. Old houses are heaped on
  round years — 88,525 residential parcels say 1900 against 685 for 1899 and
  1,355 for 1901 — which is the assessor's estimate, reported as the assessor
  wrote it.

The property class decides two things
-------------------------------------
``PROP_CLASS`` is the ORPTS property-type code
(``tax.ny.gov/research/property/assess/manuals/prclas.htm``).

**The floor area is reported only for class 210**, "one family year-round
residence" — and not where that record counts two or more kitchens (12,049
class-210 records do: the roll's own sign of a second household). 215 has an
accessory apartment, 220 and 230 are two and three families, 240 may hold three
dwellings, 280/281 are several residences on one lot, and 260 is a seasonal
cottage; the area on any of them is not one year-round home's. A condominium unit
(classed by its building, 210 for a townhouse unit, 411 for a flat) reports its
own unit's area, so the one-family rule needs no condo exception. 1,395,223
class-210 records carry an area.

**The year is refused only where both the class and the inventory say no
dwelling.** The year on a commercial parcel comes from the commercial inventory —
a warehouse's year is not anyone's home's. So a year is dropped when the row has
no residential inventory (no living area, no kitchen) *and* its class is one that
holds no dwelling: vacant land (3xx), recreation (5xx), community services (6xx)
other than welfare and homes for the aged (63x), industrial (7xx), public
services (8xx), wild and forest land (9xx), agricultural vacant land (105,
"does not have living accommodations"), and commercial (4xx) other than living
accommodations (41x — apartments, condominium flats, boarding houses) and the
mixed-use rows with flats upstairs (480-483). Measured: 73,399 parcels with a year
are turned away by this. Either condition alone would be wrong: 2,976
vacant-class parcels carry a full residential inventory — an Albany row house
filed as class 311 with two kitchens and an 1890 year — and farms (1xx) carry
farmhouses, so neither is refused on its class.

Three things this roll does that the shared chooser needs help with
-------------------------------------------------------------------
**The same street address on two parcels.** ``select_parcel`` confirms a parcel
by address within 80 m, and that is only decisive if the address is unique. In
the Town of Remsen two parcels are both "10876 Bardwell Mills Rd" — an 1840 house
on ten acres and a 1950 seasonal cottage 190 m away — and the geocode for the
cottage landed within 80 m of the house only, so the first end-to-end run reported
the house: the one wrong parcel it found. So every address-confirmed answer is
checked by one more request: every row within ``UNIQUENESS_RADIUS_M`` (500 m)
carrying the same house number, and if a second parcel shares the address the
lookup is refused. The ``where`` clause holds only the parsed house number,
which is digits by construction. Measured cost: median 196 ms.

**Condominium stacks.** The layer copies the whole complex polygon once per unit
(``DUP_GEO = "Y"``, 75,054 rows), so a point in a condominium lands in every unit
at once, which the shared chooser rightly refuses. The unit is in its own column
(``LOC_UNIT``: "Unit 29", "Unit 1-K"), so where the reader typed a unit — which
``assessor_address`` carries onto the geocoder's canonical address — rows for
*other* units are dropped before the choice. Rows with no unit stay: the record
of a rental building is right for every flat in it. Without a typed unit the
stack stays ambiguous and is refused.

**Duplicate rows, and the ones that only look duplicate.** A row returned twice
under the same full ``SWIS_SBL_ID`` with identical facts is one candidate, not two
rival ones. Rows are never merged on ``SBL`` alone: the section-block-lot number
repeats across municipalities — 539 residential SBLs appear under two SWIS codes in
the duplicated-geometry rows alone, nearly all distinct parcels in Orange County
towns with coincident numbering — so merging on it could silently remove an
ambiguity ``select_parcel`` must see. The cost is deliberate: the layer's
documentation says a parcel on a village boundary is assessed by both village and
town under two SWIS codes, and those genuinely-same parcels stay two candidates
and are refused as ambiguous.

The roll's spelling and the geocoder's
--------------------------------------
The comparison runs on the roll's own number and street columns, not on
``PARCEL_ADDR``, which runs the unit in after the street ("12 S Lake Dr 2",
"7 Constantine Ct Lot 5"). And the roll spells streets as the assessor typed them,
which the Census matcher does not echo:

* numbered streets spelled out — "734 Fifth Ave" in Troy where the matcher says
  "734 5TH AVE", while in Smithtown it says "140 SIXTH ST" for "140 Sixth St";
* directions spelled out or placed after the street — "West Hill Rd" for
  "W HILL RD", "Edwards Ave N" for "N EDWARDS AVE";
* apostrophes — "Tinker's Ln" for "TINKERS LN";
* and the whole Town of Clarkstown (about 25,000 homes) runs the hamlet into the
  street with Lane as LA: "ASPEN LA NEW CITY" for "ASPEN LN".

The geocoder is inconsistent itself (Fifth/5TH but SIXTH), so no single rewrite
of the roll can be right. Each roll street is offered in a short list of
spellings — as written, with the ordinal as a numeral, with one direction moved
or abbreviated — and the one the query matches is used, through the same strict
``same_address``. Every spelling names the same street, so this can only turn a
failed match into a match on that street, never confirm a different one. A
hamlet tail is cut only when it follows a street type and is one of the phrases
Clarkstown actually writes; single-letter and directional tokens are never
treated as locality, because "MAIN ST W" is not "MAIN ST".

Why this service runs on the shared clock
-----------------------------------------
Measured 2026-10-03. Rooftops are 120 residential parcel centroids drawn at random
from the layer; product points are the 145 Census geocodes of the end-to-end run
below, i.e. what the label actually sends:

  ====================================  ======  ======  ======  ======
  request (GeoHub)                      median     p90     p95     max
  ====================================  ======  ======  ======  ======
  containment, rooftops (n=120)         0.15 s  0.19 s  0.21 s  0.61 s
  80 m buffer, rooftops (n=120)         0.16 s  0.21 s  0.21 s  0.42 s
  containment, product points (n=145)   0.16 s  0.22 s  0.26 s  0.56 s
  80 m buffer, product points (n=140)   0.18 s  0.23 s  0.32 s  0.46 s
  same-number search (n=105)            0.20 s  0.22 s  0.24 s  0.55 s
  ====================================  ======  ======  ======  ======

No request came near the shared one-second read slice, and the worst three
requests together (0.56 + 0.46 + 0.55 s) sit far inside the shared four-second
budget, so this module defines no ``READ_SLICE_S`` or ``LOOKUP_TIMEOUT`` of its
own. The legacy server, on the same 60 rooftops, had a containment p95 of 3.85 s
and a maximum of 6.47 s — under the shared slice it would have been cut off on
one lookup in twelve. Responses are 0.2 to 34 KB.

What the adapter is worth, end to end
-------------------------------------
200 residential homes drawn at random from the layer (class 2xx with a year, by
random object id, across the 33 counties), geocoded through the Census matcher
exactly as the product does, routed by the geocoder's county, then looked up: 145
geocoded, all 145 routed here, **104 resolved, 0 matched to the wrong parcel**, and
every one of the 104 exact on the year built; 91 of them were one-family records
whose floor area was checked, and all 91 were exact. A second, independent draw
of 120 gave 64 resolved, 0 wrong, 64/64 years and 53/53 areas exact.

The 41 that did not resolve: 29 geocodes landed more than 80 m from their own
parcel (long rural lots, private lanes, interpolation along the road — including
the Remsen cottage, now refused rather than misreported); 11 roll addresses that
cannot be matched by rule — house-number ranges ("143-145 Hammond St"), lettered
numbers ("38A"), run-together names ("Shinhollow" for "SHIN HOLLOW"), route
designations ("Rt 212" for "STATE RTE 212") and USPS suffixes the shared table
does not know ("Fox Trace" for "FOX TRCE"); and one condominium stack with no unit
given. Only 5 of the 145 lookups were settled by containment: the Census matcher
puts nearly every New York address in the roadway, so the address-confirmed
buffer is the normal path here, not the fallback.

Of the 55 that did not geocode, 46 are an artefact of drawing addresses from the
roll: it has no ZIP for them and names the assessing town, which is often not the
postal city. A reader types the postal address.

Terms of use
------------
Read 2026-10-03: the layer description, the Clearinghouse parcels page
(``gis.ny.gov/parcels``) and the published metadata
(``gis.ny.gov/current-parcel-polygon-metadata``). The data is published for
"public access" by counties that "specifically authorized Geospatial Services to
share their GIS tax parcel data with the public"; the use limitation is an "as is"
disclaimer of every warranty, and the per-county constraints say "general
planning purposes only and not to determine property boundaries". No licence term
restricts commercial use or forbids querying; none grants redistribution of the
compilation either, and the counties are named as the data owners. Verdict: the
same posture as Cook — query live and cache in process, never bundle, attribute
the counties, ORPTS and ITS (as ``ATTRIBUTION`` does). Nothing from this source is
written into the repository.

Privacy, and why the field list is short
----------------------------------------
The layer has 74 columns, among them ``PRIMARY_OWNER``, ``ADD_OWNER``, the owner's
full mailing address in two sets of columns, deed book and page, and every
assessed and market value. None of it is an input to any dimension of the label.
Ten columns are requested by name and the rest are never fetched — the
shared helper refuses ``*`` for precisely this reason.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, arcgis_parcels, cache_bucket, deadline_from, num,
    same_address, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# The 33 counties outside New York City that the layer actually serves. Derived
# from the data on 2026-10-03, not from the state's list: the layer grouped on
# COUNTY_NAME (with returnDistinctValues/statistics) gave 38 counties, every one
# outside the city carrying YR_BLT on residential parcels, and the service's own
# footprint layer (FeatureServer/0) gave the same 38 with their COUNTY_FIPS. The
# five boroughs (36005, 36047, 36061, 36081, 36085) are left out on purpose — a
# separate adapter answers for them from PLUTO. Written as literals because the set
# is a fact about which counties opted in, which no rule can produce; re-derive it
# when ITS publishes a new year (the description lists the counties by name).
COUNTY_FIPS = frozenset({
    "36001",   # Albany
    "36007",   # Broome
    "36011",   # Cayuga
    "36013",   # Chautauqua
    "36023",   # Cortland
    "36029",   # Erie
    "36037",   # Genesee
    "36039",   # Greene
    "36041",   # Hamilton
    "36049",   # Lewis
    "36051",   # Livingston
    "36057",   # Montgomery
    "36065",   # Oneida
    "36067",   # Onondaga
    "36069",   # Ontario
    "36071",   # Orange
    "36075",   # Oswego
    "36077",   # Otsego
    "36079",   # Putnam
    "36083",   # Rensselaer
    "36087",   # Rockland
    "36089",   # St. Lawrence
    "36097",   # Schuyler
    "36101",   # Steuben
    "36103",   # Suffolk
    "36105",   # Sullivan
    "36107",   # Tioga
    "36109",   # Tompkins
    "36111",   # Ulster
    "36113",   # Warren
    "36117",   # Wayne
    "36119",   # Westchester
    "36121",   # Wyoming
})

NAME = "NYS ITS Geospatial Services"
ATTRIBUTION = ("New York county and municipal assessors via NYS ORPTS and NYS ITS "
               "Geospatial Services (public tax parcels, keyless)")
DATA_VINTAGE = "NYS public tax parcels (ORPTS assessment roll joined to county parcel maps)"

PARCEL_URL = ("https://nysgeohub.ny.gov/arcgis/rest/services/Parcels"
              "/NYS_Tax_Parcels_Public/FeatureServer/1/query")

# Only what the label scores, plus the columns that decide whether a value belongs
# to one home: the class, the kitchen count, the unit, and the roll year that dates
# the record. See "Privacy" in the module docstring for what the other 64 columns
# hold. The heating, fuel, sewer and water columns are not here because nothing
# reads them yet (see "What this source carries").
_FIELDS = ("SWIS_SBL_ID,PARCEL_ADDR,LOC_ST_NBR,LOC_STREET,LOC_UNIT,PROP_CLASS,"
           "YR_BLT,SQFT_LIVING,NBR_KITCHENS,ROLL_YR")

# Spellings the roll uses and the Census matcher does not; see "The roll's spelling
# and the geocoder's" in the module docstring. Each is applied as an ALTERNATIVE
# spelling of the same street, never as a replacement.
_ORDINALS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th",
    "sixth": "6th", "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th",
    "eleventh": "11th", "twelfth": "12th", "thirteenth": "13th",
    "fourteenth": "14th", "fifteenth": "15th", "sixteenth": "16th",
    "seventeenth": "17th", "eighteenth": "18th", "nineteenth": "19th",
    "twentieth": "20th",
}
_DIRECTIONS = {"north": "N", "south": "S", "east": "E", "west": "W"}
_TYPE_SPELLINGS = {"la": "Ln", "terr": "Ter"}
_STREET_TYPES = frozenset(SUFFIXES) | frozenset(_TYPE_SPELLINGS)
# The hamlet tails the Town of Clarkstown runs into its street column, exactly as
# written there (measured over its 1,660 residential street names). Matched only
# as a whole phrase directly after a street type; never single letters or
# directions, because "MAIN ST W" is not "MAIN ST".
_LOCALITY_TAILS = tuple(tuple(p.split()) for p in (
    "NEW CITY", "NANUET", "CONGERS", "WEST NYACK", "W NYACK", "W NYK",
    "VALLEY COTTAGE", "VALLEY COTTAG", "VALLEY COTTA", "VALLEY COTT", "VALL COTT",
    "VLY CTG", "BARDONIA", "UPPER NYACK", "U NYACK", "U NYK", "CENTRAL NYACK",
    "C NYACK", "CENTRAL NYK", "SPRING VALLEY", "SPR VLY",
))

#: How far to look for a second parcel carrying the confirmed address. The case
#: that set it: two Remsen parcels share "10876 Bardwell Mills Rd" 190 m apart.
#: Wide enough for long rural lots; the house-number filter keeps the response to
#: a handful of rows. See "Three things this roll does" in the module docstring.
UNIQUENESS_RADIUS_M = 500

# ORPTS categories whose every class holds no dwelling: vacant land, recreation,
# industrial, public services, wild and forest land. Community services (6) and
# commercial (4) have exceptions, handled in _class_says_no_dwelling.
_NON_DWELLING_CATEGORIES = frozenset("35789")
# Commercial classes that commonly carry flats: multiple-use buildings, downtown
# rows with apartments upstairs, converted residences.
_DWELLING_EXCEPTIONS = frozenset({"480", "481", "482", "483"})


def _parcel_id(attrs: dict) -> str | None:
    """The statewide parcel id (SWIS municipality code + SBL), or None.

    Null on 5,276 polygons outside the city that were never joined to a roll
    record — no class, no year, no address. They can never contribute a fact.
    """
    pid = str(attrs.get("SWIS_SBL_ID") or "").strip()
    return pid or None


def _base_tokens(raw: str) -> list[str]:
    """The roll's street as tokens: apostrophes dropped, a Clarkstown hamlet tail
    cut, and Lane/Terrace written the way the shared suffix table knows them."""
    tokens = raw.replace("'", "").replace("\u2019", "").split()
    for tail in _LOCALITY_TAILS:
        n = len(tail)
        if (len(tokens) > n + 1
                and tuple(t.upper() for t in tokens[-n:]) == tail
                and tokens[-n - 1].lower() in _STREET_TYPES):
            tokens = tokens[:-n]
            break
    if tokens and tokens[-1].lower() in _TYPE_SPELLINGS:
        tokens = tokens[:-1] + [_TYPE_SPELLINGS[tokens[-1].lower()]]
    return tokens


def _numeral_ordinal(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 2 and tokens[-1].lower() in SUFFIXES \
            and tokens[-2].lower() in _ORDINALS:
        return tokens[:-2] + [_ORDINALS[tokens[-2].lower()], tokens[-1]]
    return None


def _abbreviate_leading_direction(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 3 and tokens[0].lower() in _DIRECTIONS:
        return [_DIRECTIONS[tokens[0].lower()]] + tokens[1:]
    return None


def _lead_trailing_direction(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 3 and tokens[-2].lower() in SUFFIXES:
        word = tokens[-1].lower()
        abbr = _DIRECTIONS.get(word) or (word.upper() if word in ("n", "s", "e", "w") else None)
        if abbr:
            return [abbr] + tokens[:-1]
    return None


def _trail_leading_direction(tokens: list[str]) -> list[str] | None:
    if len(tokens) >= 3 and tokens[-1].lower() in SUFFIXES \
            and tokens[0].lower() in ("n", "s", "e", "w"):
        return tokens[1:] + [tokens[0].upper()]
    return None


def _street_spellings(raw: str) -> list[str]:
    """Every spelling of this roll street that is still the same street.

    One transformation at a time from the written form (and from its numeral
    form): "West Hill Rd" may become "W Hill Rd" but never "Hill Rd W", because a
    direction the roll spelled out as part of a name is not moved to its other end.
    """
    base = _base_tokens(raw)
    spellings = [base]
    numbered = _numeral_ordinal(base)
    if numbered:
        spellings.append(numbered)
    for tokens in list(spellings):
        for transform in (_abbreviate_leading_direction, _lead_trailing_direction,
                          _trail_leading_direction):
            changed = transform(tokens)
            if changed and changed not in spellings:
                spellings.append(changed)
    return [" ".join(t) for t in spellings if t]


def _address_for(attrs: dict, query: str | None) -> str | None:
    """The row's street address, in the spelling that matches ``query`` if any does.

    Built from LOC_ST_NBR and LOC_STREET, which leave the unit out; PARCEL_ADDR
    runs it in ("12 S Lake Dr 2") and is used only when the components are absent,
    in which case it is usually a bare street name that can never confirm anything.
    The comparison itself is still the shared, strict ``same_address``.
    """
    number = str(attrs.get("LOC_ST_NBR") or "").strip()
    street = str(attrs.get("LOC_STREET") or "").strip()
    if not (number and street):
        return (str(attrs.get("PARCEL_ADDR") or "").strip()) or None
    spellings = [f"{number} {s}" for s in _street_spellings(street)]
    if not spellings:
        return None
    if query:
        for spelling in spellings:
            if same_address(query, spelling):
                return spelling
    return spellings[0]


def _address_of(attrs: dict) -> str | None:
    return _address_for(attrs, None)


def _norm_unit(raw) -> str:
    """A unit designator reduced to compare: "Unit 1-K", "#1K" and "1k" are equal.
    "Lot 5" stays "LOT5", which no typed unit matches — a refusal, not a guess."""
    text = " ".join(str(raw or "").upper().replace("#", " # ").split())
    for marker in ("UNIT ", "APT ", "STE ", "SUITE ", "# "):
        if text.startswith(marker):
            text = text[len(marker):]
            break
    return "".join(ch for ch in text if ch.isalnum())


def _same_fact_key(attrs: dict) -> tuple:
    return (_parcel_id(attrs), _address_of(attrs),
            attrs.get("YR_BLT"), attrs.get("SQFT_LIVING"),
            attrs.get("PROP_CLASS"), attrs.get("NBR_KITCHENS"))


def _candidates(rows: list[dict], unit: str | None) -> list[dict]:
    """The rows that could be an answer, before the shared chooser sees them.

    Each filter can only turn "ambiguous" into "one real parcel", never let a
    wrong one through, because the address confirmation after it is untouched:

    * rows with no parcel id (unjoined polygons) are records of nothing;
    * where the reader typed a unit, a row for a DIFFERENT unit is not their home
      (rows with no unit stay — a rental building's record is right for every flat);
    * the same full id returned twice with identical facts is one row. Never on
      SBL alone — see "Duplicate rows" in the module docstring.
    """
    rows = [r for r in rows if _parcel_id(r) is not None]
    if unit:
        wanted = _norm_unit(unit)
        rows = [r for r in rows if _norm_unit(r.get("LOC_UNIT")) in ("", wanted)]
    seen, out = set(), []
    for r in rows:
        key = _same_fact_key(r)
        if key[0] and key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _parcels(lat: float, lon: float, distance_m: float = 0, unit: str | None = None,
             *, deadline: float) -> list[dict]:
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline)
    return _candidates(rows, unit)


def _same_number_nearby(lat: float, lon: float, number: str, unit: str | None,
                        *, deadline: float) -> list[dict]:
    body = _shared.get_json(PARCEL_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(UNIQUENESS_RADIUS_M), "units": "esriSRUnit_Meter",
        "where": f"LOC_ST_NBR='{number}' OR PARCEL_ADDR LIKE '{number} %'",
        "outFields": _FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline)
    rows = [(f or {}).get("attributes") or {}
            for f in ((body or {}).get("features") or [])]
    return _candidates(rows, unit)


def _address_is_unique(lat: float, lon: float, address: str, chosen: dict,
                       unit: str | None, *, deadline: float) -> bool:
    """Whether ``chosen`` is the only parcel near here that carries ``address``.

    One request on the lookup's own clock: rows within UNIQUENESS_RADIUS_M whose
    house number is the address's. The number comes from ``address_key``, which
    accepts only an all-digit first token, so nothing typed reaches the ``where``
    clause unparsed. A failure raises into the fail-open path — an answer whose
    uniqueness could not be checked is not reported.
    """
    key = address_key(address)
    if not key or not key[0].isdigit():
        return False
    ids = {_parcel_id(r)
           for r in _same_number_nearby(lat, lon, key[0], unit, deadline=deadline)
           if same_address(address, _address_for(r, address))}
    ids.add(_parcel_id(chosen))
    return len(ids) == 1


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the parcel this point belongs to, or None.

    The choice is ``_shared.select_parcel``'s, unchanged. Two things are added
    around it and neither loosens it: rows that cannot be the reader's home are
    dropped first (``_candidates``), and an address-confirmed answer must also be
    the only parcel nearby with that address. No locality trim is passed: the roll
    keeps the city out of its street column everywhere but Clarkstown, whose tails
    are cut on the roll side only (see _base_tokens).
    """
    deadline = deadline_from(deadline)
    unit = unit_of(address)
    chosen = select_parcel(
        lambda d: _parcels(lat, lon, d, unit, deadline=deadline),
        address, lambda attrs: _address_for(attrs, address))
    if chosen is None or not address:
        return chosen
    return chosen if _address_is_unique(lat, lon, address, chosen, unit,
                                        deadline=deadline) else None


def _vintage(row: dict) -> str:
    """Dated from ROLL_YR on the row: the layer is republished annually under an
    unchanged URL, so a hard-coded year would go stale silently."""
    year = num(row.get("ROLL_YR"))
    if year and 1900 <= year <= 2100:
        return f"{DATA_VINTAGE}, {int(year)} assessment roll"
    return DATA_VINTAGE


def _has_residential_inventory(row: dict) -> bool:
    """Whether the roll recorded a dwelling building here: a living area or a
    kitchen, both of which come only from the ORPTS residential inventory."""
    area = num(row.get("SQFT_LIVING"))
    kitchens = num(row.get("NBR_KITCHENS"))
    return bool((area and area > 0) or (kitchens and kitchens >= 1))


def _class_says_no_dwelling(prop_class) -> bool:
    """Whether the ORPTS class is one that holds no dwelling. Anything not a
    three-digit code (null, or a PLUTO land-use code) is not a refusal."""
    code = str(prop_class or "").strip()
    if len(code) != 3 or not code.isdigit():
        return False
    if code == "105":
        return True
    if code[0] in _NON_DWELLING_CATEGORIES:
        return True
    if code[0] == "4":
        return code[:2] != "41" and code not in _DWELLING_EXCEPTIONS
    if code[0] == "6":
        return code[:2] != "63"
    return False


def _says_a_home_is_here(row: dict) -> bool:
    """Whether a year on this row can belong to somebody's home.

    Refused only when BOTH the inventory and the class say no dwelling; see "The
    property class decides two things" in the module docstring for the parcels
    either test alone would get wrong.
    """
    return _has_residential_inventory(row) or not _class_says_no_dwelling(
        row.get("PROP_CLASS"))


def _area_of_one_home(row: dict) -> float | None:
    """SQFT_LIVING when the record is one year-round family home, otherwise None.

    Class 210 and not two kitchens. A missing kitchen count is silence, not a
    second kitchen. Never divided by anything: an average tagged ``observed``
    would tell a reader not to doubt it.
    """
    area = num(row.get("SQFT_LIVING"))
    if area is None or area <= 0:
        return None
    if str(row.get("PROP_CLASS") or "").strip() != "210":
        return None
    kitchens = num(row.get("NBR_KITCHENS"))
    if kitchens is not None and kitchens >= 2:
        return None
    return area


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year = num(row.get("YR_BLT"))
    # Null is this roll's "not recorded"; a zero is refused too, so a change of
    # convention upstream cannot age a building by two thousand years.
    year_built = int(year) if (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                               and _says_a_home_is_here(row)) else None
    sqft = _area_of_one_home(row)
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
        # No wall material (BLDG_STYLE_DESC is an architectural style), storey
        # count, foundation or condition in the public schema. Left empty so the
        # label falls back to its modelled estimate rather than a guess.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What New York's assessment rolls say is standing at this point, or None.

    ``address`` is the geocoder's matched address, carrying the reader's unit.
    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    roll has no record for.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("New York State assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
