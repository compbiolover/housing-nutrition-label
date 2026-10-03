#!/usr/bin/env python3
"""Los Angeles County — the largest county in the country, from one parcel layer.

The fifth jurisdiction, and a county rather than a state: but Los Angeles County
alone holds about 3.6 million homes, more than most states, under one assessor.
The Office of the Assessor publishes its roll joined to its parcel map through
the county's enterprise GIS, keyless:

  ``LACounty_Cache/LACounty_Parcel/MapServer/0`` — "Parcels", 2,433,059 records,
  2,172,834 of them classified Residential. Verified live 2026-10-03.

One request, like Florida and Connecticut: the building facts sit on the parcel
polygon, so the lookup is one question — *which parcel is this point inside, and
what does its record say?* The layer answers point and buffered queries sent in
4326 with the buffer in metres (``esriSRUnit_Meter``), checked live: an 80 m
buffer returns the surrounding parcels, and an address whose geocode landed 73 m
off its own lot resolves through it.

Up to five buildings per parcel
-------------------------------
The roll does not describe a parcel's building; it describes up to five, in
numbered columns — ``YearBuilt1..5``, ``SQFTmain1..5``, ``Units1..5`` and so on.
Measured on 2,000 parcels drawn at random, 8% of residential parcels with any
building carry more than one: a house and a garage, a front house and a rear one,
a 1946 house and a 2022 accessory dwelling. They share one parcel and one
address, and nothing says which one the reader lives in.

So the adapter does not pick. The year built is reported only where every
building on the parcel records the same year — one building, or several that went
up together — and the floor area only where there is exactly one building holding
exactly one dwelling. A building whose year reads ``"0000"`` breaks the agreement
rather than being skipped, since its year could be anything. Taking slot 1 as
"the main house" would usually be right; the reader in the back unit would be told
the wrong decade as observed fact.

What the rule costs, on the same 2,000-parcel sample: of 1,711 residential
parcels with a building, 1,613 (94%) carry a year every building agrees on, and
1,481 (87%) are one building holding one dwelling, so qualify for an area.

``YearBuilt1..5`` are strings (``"1904"``, ``"0000"``), parsed rather than trusted.
``EffectiveYear1..5`` is the effective year the assessor moves forward after
improvements — a 1941 Santa Monica house carries 1993 — and is never requested.

Condominiums: one record per unit, stacked
------------------------------------------
Los Angeles files each condominium unit as its own parcel (its own AIN, ``UseCode``
``010C``, ``ParcelTypeCode`` 1), and draws every unit with the building lot's full
footprint. So a point on a condominium lands inside all of them at once — 19 rows
at 9049 Alcott St, 187 at 850 E Ocean Blvd — and ``_shared.select_parcel``
correctly calls that ambiguous.

Each unit's record does carry its own situs unit and its own floor area (a 1,590
sq ft unit beside a 1,471 sq ft one, both ``Units1 = 1``). So when the parcel path
declines, the reader's unit picks the record, as the District's adapter does with
its unit table: the street address must agree by the shared comparison and the
unit exactly, in exactly one record. That unit's own area is then right for this
reader and reported. Where the reader gave no unit, or one the roll spells
differently, the building's year is still reported if every record at that
address within the search radius agrees on it — the year a building went up is
the same for every unit in it, the point Florida makes about towers — with no
area and no parcel id, since no single record was chosen. Planned developments
are filed the same stacked way but give each home its own house number ("1
WILDERNESS PL", "2 WILDERNESS PL"), so the address alone picks those.

The stack is also why one flag from the service matters. It returns at most 1,000
records, and 790 came back from one 80 m buffer measured here. A truncated answer
can drop exactly the second record that would have made a match ambiguous, so a
response marked ``exceededTransferLimit`` ends the lookup with no answer.

Which parcels are homes
-----------------------
Florida and Connecticut refuse a year built where the dwelling count is an
explicit zero. Here the per-building ``Units`` column cannot carry that rule: a
Long Beach store records ``Units1 = 1``, and a three-bedroom, 2,603 sq ft house in
La Crescenta records ``Units1 = 0`` — 88 of the 2,000 sampled parcels carry a zero,
houses among them. What the roll does state is ``UseType``: an explicit
Commercial, Industrial, Institutional, Government, Recreational, Miscellaneous or
Irrigated Farm classification refuses the record; Residential or blank lets it
through. The floor area still needs ``Units == 1``, so a zero costs a house its
area, never its year.

Addresses
---------
The comparison is built from the roll's parts — ``SitusHouseNo``,
``SitusFraction``, ``SitusDirection``, ``SitusStreet`` — not from
``SitusAddress``, which runs the unit onto the end in forms ("NO  1108") the
shared parser does not know. The fraction is kept: "123 1/2" is a different
address. Two spellings are put right on both sides before comparing, because the
shared parser misreads them (see ``_canon``): lettered and numbered avenues
("AVENUE L8", "N AVENUE 64"), whose identifier it would otherwise drop as a unit
number and so match Avenue L8 to L10, and the roll's "WY" for Way.

What this source does not carry, and what it carries but is not used
--------------------------------------------------------------------
No storey count, foundation, exterior wall or condition grade. Two columns look
closer than they are:

* ``QualityClass1..5`` is the California Standard Classification System code
  (State Board of Equalization, Assessors' Handbook 531): ``D6A`` is
  construction type D, quality class 6, shape A. Type D is defined there as
  wood-frame construction — "two-by-four or two-by-six vertical studs ... The
  exterior finish or skin may be wood siding, shingle, stucco, masonry veneer, or
  sheet metal" — and 98% of the classified main buildings on residential
  parcels in the sample are type D. The structure is unambiguous; the label's
  value is not. The label splits wood frame three ways by its skin — ``frame``, ``vinyl``, ``brick-frame`` — and scores them
  differently, and type D covers all three. Mapping D to ``frame`` would be the
  knowingly lossy kind of translation ``base.TRANSLATED`` exists for, without even
  Cook's measured dominance to justify it, so it is left unmapped. Types A
  (fireproofed steel frame), B (reinforced-concrete frame), C (masonry walls:
  brick, tile, stone or concrete) and S (special) are unmapped for the same
  reason or for want of a label value at all. The quality digit grades materials
  and workmanship, not upkeep, so it is not a condition either.
* ``DesignType1..5`` is a four-digit design code with no published key in the
  service; not used.

The clock
---------
Measured against real residential rooftops — 105 dedicated pairs at parcel
centroids, and 149 containment and 143 buffered queries from the final end-to-end
run below, at the geocoder's points:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  containment, dedicated (105)         0.19 s  0.51 s  0.58 s  1.12 s
  80 m buffer, dedicated (105)         0.24 s  0.57 s  0.66 s  0.85 s
  containment, end-to-end (149)        0.18 s  0.59 s  0.80 s  1.24 s
  80 m buffer, end-to-end (143)        0.24 s  0.52 s  0.82 s  1.12 s
  ==================================  ======  ======  ======  ======

Bodies are small (3.5 KB for a house, 420 KB for the largest condominium buffer
seen), so this is the service thinking. The shared four-second budget is ample —
the worst observed containment and buffer sum to 2.4 s, and a lookup makes at most
those two requests, the unit and building paths reusing their rows — but the
shared one-second read slice is not: the end-to-end run's slow tail passes one
second on both requests, and an earlier run at the shared slice lost one address
with its slowest request at 1.004 s, the cut-off's signature, which resolved on a
re-run. So ``READ_SLICE_S`` is 2 seconds and ``LOOKUP_TIMEOUT`` the shared 4. The
worst case for one request is the budget spent connecting plus one slice, 6 s,
under the host's 12 s per service (``config.UPSTREAM_HOST_BUDGET``); a test pins
that against the constant.

What the adapter is worth, end to end
-------------------------------------
150 residential homes drawn at random from the roll by object id (spread across
the county; 23 of them condominium units, typed with their unit as a reader
would), geocoded through the Census matcher exactly as the product does, then
looked up: 149 geocoded, all 149 routed to 06037, **122 resolved and 0 matched to
the wrong parcel**. All 122 years built are exact, and all 110 floor areas
reported are exact. Two earlier runs on other random draws (130 and 150 homes)
gave 104 and 132 resolved, also with no wrong parcel — 358 of 430 across the
three.

The 28 that did not resolve in the final run, every one traced:

* 11 — the geocoder placed the point off the lot by more than the search radius
  (95 m to 1 km), or in another neighbourhood entirely: two San Pedro addresses
  came back as same-named streets downtown, in a different ZIP.
* 8 — parcels with several buildings that disagree on the year: the refusal
  described above.
* 5 — a directional the geocoder adds and the roll omits, or the reverse ("1806
  HOLGUIN ST" against "1806 E HOLGUIN ST"). The shared comparison treats a
  directional as part of the street, rightly in general, so these are refused.
* 3 — spelling: "PASEO" against "PSO", "SUNNYSLOPE" against "SUNNY SLOPE",
  "AVENIDA" against "AVE".
* 1 — no geocode.

Terms of use
------------
The service's catalogue entry (ArcGIS item ``5b277305f006459586a70165065d0fd6``,
owner ``lacounty_isd``) binds users of "any LA County REST URLs" to the County of
Los Angeles eGIS Terms of Use (``egis-lacounty.hub.arcgis.com/pages/terms-of-use``,
read 2026-10-03), which grant "a license to copy, publish, distribute and/or
transmit the Data, to adapt the Data and to exploit the Data for commercial
and/or personal use", provide it "as is", and bar any use suggesting the County's
endorsement. That permits this use outright — more than Cook's terms do — and the
adapter still takes the registry's posture: query and cache live, bundle nothing,
and attribute the Assessor without implying endorsement. Copies of the parcel
dataset that other agencies republish carry "For Official County Use Only ...
cannot be provided to 3rd party vendors ... with personal identifiable information
(owner ...)"; that is about the owner-bearing extract, and this public layer
carries no owner field at all.

Privacy, and why the field list is short
----------------------------------------
The layer has 92 columns. There is no owner name or mailing address in it, but
there are assessed land, improvement and personal-property values, the
homeowners' exemption (which says whether the owner lives there), base years,
the legal description and the exact centroid. None of it is an input to any
dimension. 28 columns are requested by name and nothing else is fetched; nothing
from this source is written into the repository.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SEARCH_RADIUS_M, address_key, cache_bucket, deadline_from, num, same_address,
    select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({"06037"})          # Los Angeles County, CA
NAME = "Los Angeles County Office of the Assessor"
ATTRIBUTION = ("Los Angeles County Office of the Assessor (LA County eGIS parcel "
               "service, keyless)")
DATA_VINTAGE = "Los Angeles County Assessor secured roll, joined to the county parcel map"

PARCEL_URL = ("https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache"
              "/LACounty_Parcel/MapServer/0/query")

#: How long this service may go quiet before the silence is treated as a stall,
#: and the budget for a whole lookup. Measured rather than chosen — see "The
#: clock" in the module docstring. The budget is the shared four seconds; only the
#: slice differs.
#:
#: Named LOOKUP_TIMEOUT rather than TIMEOUT so it cannot be mistaken for, or
#: collide with, the shared budget of the same name, as Florida and Connecticut
#: name theirs.
READ_SLICE_S = 2.0
LOOKUP_TIMEOUT = 4.0

#: The five numbered building slots the roll carries per parcel.
_SLOTS = (1, 2, 3, 4, 5)

# Only what the label scores, plus what decides whether a number describes the
# reader's home: the situs address in its parts, the use the roll assigns the
# parcel, the roll year, and four columns per building slot. See "Privacy" in the
# module docstring for what the other columns hold. EffectiveYear1..5 and
# QualityClass1..5 are not among these on purpose.
_FIELDS = ",".join(
    ["AIN", "SitusHouseNo", "SitusFraction", "SitusDirection", "SitusUnit",
     "SitusStreet", "UseType", "Roll_Year"]
    + [f"{col}{i}" for i in _SLOTS
       for col in ("DesignType", "YearBuilt", "Units", "SQFTmain")])


class _Truncated(Exception):
    """The service returned fewer parcels than matched the query."""


# --- addresses ------------------------------------------------------------------

# A lettered or numbered avenue — "AVENUE L8" in Lancaster, "AVE 64" in Highland
# Park — written as AVE/AVENUE followed by a single short identifier that ends the
# street name. Joined into one token, on both sides of the comparison, before the
# shared parser sees it. See _canon for why.
_NAMED_AVENUE_RE = re.compile(
    r"^(?P<head>\d+(?:\s+\d+/\d+)?\s+(?:[NSEW]\s+)?)AVE(?:NUE)?\s+"
    r"(?P<id>[A-Z](?:[\s-]?\d{1,3})?|\d{1,3}[A-Z]?)(?=\s*(?:,|#|$))")

# The roll writes WAY as "WY", which the shared suffix table does not know, while
# the Census matcher writes "WAY". Only a terminal "WY" is a street type.
_WY_RE = re.compile(r"\bWY(?=\s*(?:,|#|$))")


def _canon(text: str | None) -> str | None:
    """``text`` with the two LA spellings the shared parser misreads put right.

    Applied identically to the reader's address and to the roll's, so it can only
    make two spellings of one street agree or two different streets disagree.

    **Lettered and numbered avenues.** The shared parser reads a digit-bearing
    token after a street type as a unit number — "234 W STATION ST B12" — and drops
    it. "5142 W AVENUE L8" is not a unit: Avenue L8 is a street, and so are L6 and
    L10, a few hundred metres either side, with the same house numbers. Left to the
    shared rule, every one of those parses to "5142 W AVE" and they all match each
    other; northeast LA's "N AVENUE 63" and "N AVENUE 64", which run parallel a
    block apart, likewise. Joining the identifier onto the street word keeps it in
    the street's name. A bare letter ("AVENUE I") is joined too, because the
    Census matcher abbreviates it to "AVE I" and the roll does not.

    **WY.** The roll's abbreviation for Way, which the shared table lacks, so
    "1301 CHEETAH WY" would never match the Census matcher's "1301 CHEETAH WAY".
    """
    if not text:
        return text
    head, sep, tail = " ".join(str(text).upper().split()).partition(",")
    head = _NAMED_AVENUE_RE.sub(
        lambda m: m["head"] + "AVENUE_" + m["id"].replace("-", "").replace(" ", ""),
        head)
    head = _WY_RE.sub("WAY", head)
    return f"{head}{sep}{tail}"


def _address_of(attrs: dict) -> str | None:
    """The parcel's street address without its unit, or None if it has none.

    Built from the roll's parts rather than read from ``SitusAddress``, which runs
    the unit onto the end in forms the shared parser cannot all recognise —
    "850 E OCEAN BLVD   NO  1108" carries no marker it knows, and would parse as a
    street called "OCEAN BLVD NO 1108". The unit is compared separately, by
    :func:`_unit_key`, where it can be compared exactly.

    The fraction is kept. "123 1/2 MAIN ST" is a different address from "123 MAIN
    ST" in Los Angeles, often a different parcel, and dropping it would let one
    confirm the other.

    House number 0 is the roll's "no situs" — vacant land described as "VAC/COR AVE
    U/146 ST E" — and is not an address.
    """
    number = str(attrs.get("SitusHouseNo") or "").strip()
    street = " ".join(str(attrs.get("SitusStreet") or "").split())
    if not (number.isdigit() and int(number) > 0 and street):
        return None
    parts = [number, str(attrs.get("SitusFraction") or "").strip(),
             str(attrs.get("SitusDirection") or "").strip(), street]
    text = _canon(" ".join(p for p in parts if p))
    return text if address_key(text) else None


# Words the roll and readers put in front of a unit number.
_UNIT_WORDS = frozenset({"NO", "APT", "UNIT", "STE", "SUITE", "#"})


def _unit_key(raw: str | None) -> str | None:
    """A unit designator reduced to what identifies it, or None if there is none.

    The roll writes one unit several ways — "103", "APT 104S", "NO    B5",
    "# 6", "UNIT  2E" — and a reader writes it others ("#B-5"). The marker word and
    punctuation go; case is folded. Nothing else is normalised: leading zeros stay
    significant because unit 01 and unit 1 can both exist in one building, which
    is the call the District's adapter makes too.
    """
    tokens = str(raw or "").upper().replace("#", " # ").split()
    while tokens and tokens[0] in _UNIT_WORDS:
        tokens = tokens[1:]
    key = "".join(ch for ch in "".join(tokens) if ch.isalnum())
    return key or None


# --- the request ------------------------------------------------------------------


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Parcel records at (or within ``distance_m`` of) a point.

    The same request ``_shared.arcgis_parcels`` makes, sent through the same
    ``_shared.get_json`` so the budget and the dropped-dataset bookkeeping are
    identical — but reading one flag that helper discards. The service returns at
    most 1,000 records, and a condominium stack is one record per unit on one
    shared footprint: a single coordinate measured here returned 226 rows, and an
    80 m buffer around it 790. A truncated answer is not a smaller answer. It can
    drop the second record that would have made a match ambiguous, and present the
    first as unique. So ``exceededTransferLimit`` ends the lookup.

    Rows without an AIN are dropped before the parcel is chosen, as Florida drops
    its placeholder polygons: 22 of the county's 2,433,059 rows have none, and a
    row that can never be an answer must not make a real one ambiguous.
    """
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": _FIELDS, "returnGeometry": "false", "f": "json",
    }
    if distance_m:
        params["distance"] = str(distance_m)
        params["units"] = "esriSRUnit_Meter"
    body = _shared.get_json(PARCEL_URL, params, deadline, READ_SLICE_S) or {}
    if body.get("exceededTransferLimit"):
        raise _Truncated(f"more than one page of parcels within {distance_m} m")
    rows = [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]
    return [r for r in rows if str(r.get("AIN") or "").strip()]


def _memo(lat: float, lon: float, deadline: float):
    """``fetch(distance_m)`` for one lookup, asking the service once per distance.

    The unit path below reads the same candidates the parcel path already fetched;
    without this it would ask for them again and spend the budget twice.
    """
    seen: dict[float, list[dict]] = {}

    def fetch(distance_m: float) -> list[dict]:
        if distance_m not in seen:
            seen[distance_m] = _parcels(lat, lon, distance_m, deadline=deadline)
        return seen[distance_m]
    return fetch


def _unit_row(fetch, address: str) -> dict | None:
    """The one record at this address whose unit is the reader's unit, or None.

    Reached only when ``select_parcel`` declined, which is what a condominium looks
    like from a parcel layer that stacks one record per unit on the building's
    footprint: every unit contains the point, so containment is "ambiguous", and
    every unit shares the street address, so the buffer is too.

    The roll does give each unit its own situs, so the reader's address can name
    one — the same move the District's adapter makes with its unit table. Every
    part has to agree: the street address by the shared comparison, and the unit
    exactly. A reader who gave no unit matches only a record that has none, which
    is how a planned development's townhouses are filed (stacked like units, but
    "1 WILDERNESS PL", "2 WILDERNESS PL", each its own house number). Two records
    claiming the same address and unit are an ambiguity, not a tie to break, and
    widening the search cannot resolve one.
    """
    wanted = _unit_key(unit_of(address))
    for distance in (0, SEARCH_RADIUS_M):
        hits = [r for r in fetch(distance)
                if same_address(address, _address_of(r))
                and _unit_key(r.get("SitusUnit")) == wanted]
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


# --- reading the record -----------------------------------------------------------


def _year(raw) -> int | None:
    y = num(str(raw or "").strip())
    return int(y) if y and EARLIEST_PLAUSIBLE_YEAR <= y <= 2100 else None


def _buildings(row: dict) -> list[dict]:
    """The populated building slots, in the roll's order.

    A slot counts if it records anything at all — a year, an area, a unit count or
    a design type. A slot with an area and units but year ``"0000"`` is rare (3 of
    the 372 slots on the 158 multi-building parcels in a 2,000-parcel random
    sample) but it is a building whose age is unknown, not an empty slot. A Pomona
    apartment parcel recorded live carries one in its fifth slot: 4 units, 3,459
    sq ft, no year.
    """
    out = []
    for i in _SLOTS:
        year_raw = str(row.get(f"YearBuilt{i}") or "").strip()
        sqft = num(row.get(f"SQFTmain{i}"))
        units = num(row.get(f"Units{i}"))
        design = str(row.get(f"DesignType{i}") or "").strip()
        if year_raw.strip("0") or (sqft or 0) > 0 or (units or 0) > 0 or design:
            out.append({"year": _year(year_raw), "sqft": sqft, "units": units})
    return out


def _year_of_the_home(row: dict) -> int | None:
    """The year built, where every building on the parcel agrees on it.

    Up to five buildings share one parcel and one address, and nothing in the roll
    says which of them the reader lives in: a 1946 house with a 2022 garage
    conversion, a duplex filed as a 1910 front house and a 1926 rear one. Picking
    the first slot would usually be the main house and sometimes not, and the
    reader in the back unit would be told the wrong decade as observed fact.

    So the year is reported only where it is the same answer whichever building is
    meant — a single building, or several that went up the same year (a 1957 house
    and its 1957 garage). A building with no recorded year breaks the agreement,
    since its year could be anything.
    """
    years = {b["year"] for b in _buildings(row)}
    if len(years) != 1:
        return None
    return next(iter(years))


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the roll classifies this parcel as somewhere people live.

    ``UseType`` is the roll's own classification. An explicit non-residential one
    — Commercial, Industrial, Institutional, Government — is a statement, and a
    year built read off a warehouse or a store would describe a building nobody
    lives in while carrying the ``observed`` tag. A blank one is silence and is let
    through, as Florida and Connecticut let a missing dwelling count through.

    The per-building ``Units`` count cannot do this job here, though it is the
    column Florida and Connecticut use. On a commercial parcel it counts shops — a
    Long Beach store records ``Units1 = 1`` — and on a house it is sometimes
    zero: a three-bedroom, 2,603 sq ft single-family house in La Crescenta records
    ``Units1 = 0``. A zero there is the roll not filling the column, not the roll
    saying nobody lives there.
    """
    use = str(row.get("UseType") or "").strip()
    return not use or use == "Residential"


def _area_of_one_home(row: dict, reader_unit: str | None) -> float | None:
    """``SQFTmain`` when it describes the reader's home, otherwise None.

    Three conditions, each catching a different row:

    * **One building.** With more than one, the reader could be in either.
    * **One dwelling in it.** A 24-unit building's 21,244 sq ft is not anybody's
      home. Zero or blank is not one either — see :func:`_says_a_home_is_here`.
    * **The same unit.** A condominium unit's record carries the unit's own area,
      which is right for that unit and for no other. So the area is reported only
      when the unit the reader named is the unit the record names — both absent
      for a house. A reader who wrote a unit at an address the roll files as one
      dwelling is telling us something the record does not know about, and the
      record's area describes the whole building.

    Dividing a total by a count was not considered: it would turn a measurement
    into an average and then tag the average ``observed``.
    """
    buildings = _buildings(row)
    if len(buildings) != 1:
        return None
    only = buildings[0]
    if only["units"] != 1 or not only["sqft"] or only["sqft"] <= 0:
        return None
    if _unit_key(row.get("SitusUnit")) != reader_unit:
        return None
    return only["sqft"]


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row's own roll year."""
    year = str(row.get("Roll_Year") or "").strip()
    return f"{DATA_VINTAGE}, {year} roll" if year.isdigit() and len(year) == 4 \
        else DATA_VINTAGE


# --- the lookup -------------------------------------------------------------------


def _building_year(fetch, address: str) -> tuple[int, dict] | None:
    """The year a condominium building went up, when the reader's unit is unknown.

    ``(year, one of the rows)``, or None. Reached when neither path above found the
    reader's home: an address that is a stack of units, and no unit the roll
    recognises — the reader gave none, or gave one the roll spells some other way.

    Which unit is unknowable, but for the year it does not matter if every unit at
    the address says the same thing: the building went up when it went up, the
    point Florida makes for a tower filed as one parcel. So the year is reported
    where every record at this street address within the search radius is
    residential and agrees on it, and nothing else is: no area, which belongs to
    one unit, and no parcel id, since no single record was chosen.

    The radius, not containment, because the units at one address are not always
    on one footprint — a complex can file two buildings as two stacks, and the
    stack the point happens to land in is not evidence about the other one.
    """
    rows = [r for r in fetch(SEARCH_RADIUS_M) if same_address(address, _address_of(r))]
    if not rows or not all(_says_a_home_is_here(r) for r in rows):
        return None
    years = {_year_of_the_home(r) for r in rows}
    if len(years) != 1 or None in years:
        return None
    return next(iter(years)), rows[0]


def _record(row: dict, address: str | None) -> AssessorRecord | None:
    """The label's record of the home this roll row describes, or None."""
    if not _says_a_home_is_here(row):
        return None
    year_built = _year_of_the_home(row)
    sqft = _area_of_one_home(row, _unit_key(unit_of(address)))
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=str(row.get("AIN") or "").strip() or None,
        year_built=year_built,
        sqft=sqft,
    )


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    """The parcel, then the unit, then the building — each only if the last declined.

    The order matters for the same reason it does in the District's adapter: the
    parcel path is the one every house takes, and its answer is never
    second-guessed by a path designed for condominiums.
    """
    address = _canon(address)
    fetch = _memo(lat, lon, deadline_from(None, LOOKUP_TIMEOUT))
    try:
        row = select_parcel(fetch, address, _address_of)
        if row is None and address:
            row = _unit_row(fetch, address)
        if row is not None:
            return _record(row, address)
        building = _building_year(fetch, address) if address else None
    except _Truncated:
        # Deterministic for this point, not a portal glitch: the same query will
        # be truncated the same way next time, so "no answer" is the answer.
        return None
    if building is None:
        return None
    year, sample = building
    return AssessorRecord(source=ATTRIBUTION, data_vintage=_vintage(sample),
                          parcel_id=None, year_built=year)


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What the Los Angeles County roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address, carrying the reader's unit where
    they gave one (``location.assessor_address``). It confirms the parcel and,
    for a condominium, picks the unit; the lookup still works without one wherever
    the coordinate lands inside a single boundary.

    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    roll has no record for. The caller then keeps whatever it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Los Angeles assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None

