#!/usr/bin/env python3
"""Georgia — four county assessors, each from its own layer, in one config table.

Georgia has no statewide parcel layer with building facts — no counterpart to
Florida's DOR roll or NC OneMap. An ArcGIS Online search for statewide, GIO and
DOR parcels, and the Atlanta Regional Commission's organization, turned up only
geometry and land use. So this module is Utah's shape without Utah's template:
one entry per county in ``_COUNTIES``, each naming its own service, its own
explicit field list, its own address column, and its own reading of its own
vocabulary. Every county was measured live on 2026-10-03.

Which counties, and which not
-----------------------------

  =========  =====  =========  ===================================  ============
  county     FIPS   housing    source                               status
                    units
  =========  =====  =========  ===================================  ============
  Fulton     13121    507,119  county AGOL: Tax_Parcels → Structure  answered
                               _Footprints (two hops)
  Chatham    13051    137,532  SAGIS OpenData Parcel Digest 2025     answered
  Clayton    13063    115,476  county TaxAssessor/Parcels MapServer  answered
  Forsyth    13117     92,575  county AGOL TylerParcels (TY2024)     answered
  Richmond   13245     93,145  Augusta Map_LayersTS/316              held: terms
  Gwinnett   13135    340,962  Property_and_Tax FeatureServer        excluded:
                                                                     terms
  Cobb       13067    314,104  tax/taxassessorsdaily MapServer       excluded:
                                                                     terms
  DeKalb     13089    330,830  TaxParcelsOD and five other layers    no data
  =========  =====  =========  ===================================  ============

The four answered counties hold 852,702 housing units (18.8% of Georgia's
4,541,835 in ``data/year_built_county.csv``).

**Gwinnett and Cobb were measured and excluded for their terms, not their data.**
Both have the best building records in the state — Gwinnett's improvements table
carries year built, finished area, stories, exterior wall and condition on 100%
of a 1,000-parcel sample; Cobb's year-built table 95% of non-condo homes — and
both reach a home in two requests. But Gwinnett's license says "the copyrighted
data shall be used for internal purposes by recipient only and may not be
distributed or sold in any way to any person or entity", and Cobb's service reads
"Copyright Cobb County. All rights reserved." beside a parcel-data sales program.
Showing a derived year built to a reader is arguably distribution, so both wait on
a product-owner decision, and neither is configured here.

**Richmond (Augusta) is configured, measured and held** (``_HELD_FOR_TERMS``) for
the same class of reason, found while verifying this adapter: Augusta's GIS
Disclaimer, which "applies to all hard copy and digital data formats", ends "It
is strictly forbidden to sell or reproduce these maps or data for any reason
without the written consent of the Augusta-Richmond County Commission"
(https://www.augustaga.gov/2324/GIS-Disclaimer). Its layer works — 29 of 40
random homes resolved, none wrongly — so the decision is a one-line change.

**DeKalb has no data.** Its public layers (``TaxParcelsOD``, ``PARCEL_TAX_JOIN``,
``Tax_Parcels_2021``–``2025``, the on-prem iasWorld views) all carry Esri's
``RESYRBLT``, ``RESFLRAREA`` and ``FLOORCOUNT`` columns, filled on 0 of 246,215
rows. Cherokee, Hall, Muscogee, Macon-Bibb and Paulding publish parcels with no
year built; Henry, Douglas and Houston publish no queryable parcel service.

Terms of use
------------
* **Fulton** — the Tax Parcels item's license: Fulton County "provides the data
  within these pages 'as is'. The data are not guaranteed to be accurate, correct,
  or complete … Fulton County assumes no responsibility for losses resulting from
  the use these data" (arcgis.com item e581a072dca9442e884d3682bff03484). The
  footprints item carries no license text. No restriction on use or caching.
* **Chatham** — the 2025 digest item's license: "Available for public use and
  download via the SAGIS Open Data website. SAGIS makes no warranty …" (item
  4468534af02640768b2038f0c2d080d8). The clearest grant of the four.
* **Clayton** — the service carries no license; the county's Parcel Viewer 2.0
  says only that "Clayton County makes no warranties or guarantees … Please verify
  any data displayed with the County Tax Assessors Office". The separate property
  SEARCH site (publicaccess.claytoncountyga.gov, a disclaimer pasted from Chatham
  County's) prohibits "applications designed to mine, gather or extract data";
  this adapter never touches that site, and asks the GIS service about one point.
* **Forsyth** — the item carries no license, description or terms; it is public
  in the county's ArcGIS Online organization, whose open-data hub links Esri's
  standard terms. Nothing found restricts this use; nothing grants it either.

The posture is the one every adapter takes: query live, cache in process, bundle
nothing, drop owner names and mailing addresses at the request. ``source`` on
each record names the county that published it.

Fulton: two hops, and the area that is not a living area
--------------------------------------------------------
Fulton's parcel layer (373,306 parcels, all ``TaxYear`` 2026) carries the site
address, land use, class and living-unit count, but no building facts. Those sit
on ``Structure_Footprints`` ("LandBase Structures", 386,176 imagery-derived
footprints), joined by ``ParcelID``: ``YearBuilt`` (a string), ``Stories``,
``StructForm`` and ``FeatType``. So the lookup is point → parcel → footprints.

**``AreaSqFt`` is never reported, and not even requested.** It is not the home's
living area: two-story homes read 730–933, and the value repeats unchanged
across every footprint of a parcel (833 Cumberland Rd NE: 1,356 on footprints
whose own polygon areas differ by more than 2:1), so it is neither the living
area nor a measured footprint. Whatever it is, it is not the label's ``sqft``,
and a column that never arrives cannot be misread by a later edit.

**A parcel can have several footprints** (18% of one-family parcels), and the
year is read from the RESIDENTIAL ones only — a commercial footprint's year is a
shop's. Each footprint carries the parcel's CAMA dwelling attributes rather than
its own, so a house and its garage both read 1939, and the rule is simple:
**report the year only when every residential footprint agrees.** Where they
disagree the parcel holds two dwelling records — 7007 Riverside Dr reads a 1973
house and a 1976 second home — and naming either would be a guess. Measured:
9 of 774 multi-footprint parcels disagree in one sample of land district 17,
1 of 85 in a second. "Take the largest footprint" was considered and rejected:
the area it would rank by is the column above that does not mean what it says.

Stories come from the same footprints, under the one-dwelling rule below, only
where every residential footprint agrees on both ``Stories`` and ``StructForm``,
and only where the form allows a whole number: split levels (10,119 filed as 1
story), bi-levels and Capes have none, a duplex's or condominium's count is the
building's, and a "Ranch" must read 1 (269 read 2). Condominium unit parcels
(LUC 106, 47,590) almost never have footprints (6 of 242 sampled do), so a
condo usually resolves to nothing rather than to the building's record.

Clayton: the unit that is not a unit
------------------------------------
One request: the parcel carries ``YEARBUILT`` and ``SQRFT`` (both strings; '',
'0' and junk such as '970' mean "not recorded", 99.7% filled on one-family
parcels), and ``STRUCTYPE``. Its ``UNIT`` column is the PLAT's unit — "UNIT 1
PHASE A" on every lot of a subdivision phase — not a dwelling unit, so it is not
requested: read as a unit it would have refused the floor area of whole
subdivisions. ``QUALITYOFBUILDING`` (A/G/F/L/V/E) is a construction-quality
grade, not a condition rating, and has no slot in the label. Stories come from
``STRUCTYPE`` where it names a whole number (RANCH, TWO STORY, 3 STORY).

Chatham: which of SAGIS's two layers
------------------------------------
SAGIS publishes Chatham's assessor digest twice. ``OpenData/Parcels/27`` is the
2025 digest (Date_Updated 2025-05-06, 125,156 parcels), released under the open-
data license quoted above. ``ChathamCounty/Parcels_Cyclomedia`` is the 2026 digest
(2026-06-22), sitting in the county's application-backend folder beside its
EnerGov and QAlert services, with no license text at all. The adapter reads the
open-data layer: the year a building went up does not change between digests,
and the fresher layer's whole advantage is the newest homes — 1,699 built in
2025 and about 330 more 2024 completions, about 2% of the digest's homes, which
fall back to the label's model rather than to a wrong value. Clear terms are
worth that. A 2026 digest is expected as layer 28; moving to it is a one-line
change to ``CHATHAM_URL``, and each record's vintage is read from its own
``Date_Updated``, so the change cannot leave a stale year on the label.

Chatham writes the unit with its marker doubled ("111 SAN MARCO DR ##A"); the
shared comparison already treats '#' as a unit marker, and the unit itself is
read from ``PropAddress_UnitNum`` ('#A') with the marker stripped.

Forsyth: a snapshot, and a fragile one
--------------------------------------
Forsyth's own assessor service (``geo.forsythco.com/.../Internal_AssessInfo``)
requires a token. What is public is ``TylerParcels/FeatureServer/90``, a Tyler
iasWorld export uploaded by a county staff member (item de26d7c7…, modified
2026-02-20), with ``TAXYEAR`` = 2024 on 131,599 of 131,836 rows. So:

* every record says **tax year 2024** in its vintage, read from the row;
* homes finished in 2025–26 are missing (the label falls back to its model);
* the layer's field names (``Q__relat00`` …) show a one-off join, not a published
  product. It could be deleted or replaced without notice, and the adapter then
  fails open — Forsyth reads as "no record" until this entry is updated. If the
  county publishes its live roll, switch to it.

``D_*`` columns are the residential dwelling card (``D_YRBLT``, ``D_STORIES``),
``BLDGAREA`` its finished area (it equals the main floor ``D_MGFA`` on one-story
houses and is about twice it on two-story ones); the commercial card's
``CD_YRBLT`` is not requested.

The one-dwelling rule, and the zero-dwelling refusals
-----------------------------------------------------
``sqft`` and ``stories`` mean one home. They are reported only where the county's
own land use says one home on its own parcel — Fulton and Clayton 101
(one-family) and 107 (townhouse), Forsyth's "SFR" family and "TOWNHOME" — and,
in Fulton, the parcel's ``LivUnits`` is 1 and its address names no unit. Never
for a duplex (102), condominium, rural acreage (which can hold a second dwelling
nothing here counts) or residence on commercial land. Chatham's digest has
neither field, and Richmond's "Residential Lots" includes duplexes.

A year is refused where the record says no one lives there: a Georgia digest
class of Commercial, Industrial or Utility; a land use of vacant land, common
area, or the commercial, industrial, exempt-institution and utility ranges
(``_luc_says_no_home``); Fulton's ``LivUnits`` of exactly 0; Chatham's building
value of exactly 0. Silence (a blank class, a missing count) is never a refusal.
Fulton's zero is conservative: 1,680 one-family and townhouse parcels read 0,
many of them homesteaded houses with 2006 footprints, so the column is often
unfilled rather than a statement — but it is the only dwelling count Fulton
publishes, and the rule is that an explicit zero refuses.

No layer carries a wall material, foundation or condition rating the label can
read: Fulton's ``StructForm`` and Forsyth's ``D_STYLE`` are architectural styles
(Forsyth's as codes with no published table), and Clayton's and Forsyth's grades
are construction quality. All are dropped.

Addresses
---------
Every county keeps the city out of its site-address column, so no locality trim
is needed. Three local facts, each left to the shared comparison rather than
forgiven here:

* Atlanta's quadrants appear in one source and not the other ("1895 NEW HOPE RD"
  on the roll, "… RD SW" from the Census matcher): 3 of 75 Fulton homes. NE and SW
  are different streets in Atlanta, so the shared rule that a directional must
  agree is right to refuse them.
* Fulton appends plat lot numbers ("7730 FANLIGHT PL LOT 861", 4,416 parcels).
  "LOT" is not a shared unit marker and is not made one here: Fulton also writes
  "LOT B" and "LOT REAR" for second houses sharing one number.
* A half-number ("208 CAMP ST 1/2", ``AddrUnit`` '1/2') offers no address at all
  (``_fulton_address``): the shared comparison would drop the "1/2" as an
  unmarked unit and confirm 208½ as 208.

Which county
------------
The registry passes the county it routed on to an adapter whose ``lookup``
accepts ``county_fips``, as this one does, so the product makes no extra request.
A direct call without one asks Census TIGERweb's county polygons (``COUNTY_URL``,
median 0.08 s); a county passed explicitly but outside ``COUNTY_FIPS`` is answered
with None.

Timing
------
Measured on 2026-10-03 at the random homes of the verification below, through the
product's HTTP session (Forsyth and Chatham twice):

  ===========================================  ======  ======  ======  ======
  request (n)                                  median     p90     p95     max
  ===========================================  ======  ======  ======  ======
  containment, four counties (300)             0.13 s  0.16 s  0.19 s  0.54 s
  80 m buffer, four counties (300)             0.13 s  0.16 s  0.17 s  4.93 s
  Fulton footprints by ParcelID (75)           0.21 s  0.25 s  0.27 s  0.44 s
  TIGERweb county (63; direct calls only)      0.08 s  0.09 s  0.10 s  0.40 s
  ===========================================  ======  ======  ======  ======

One request of 738 exceeded 0.75 s: a 4.9 s Forsyth buffered query that the
second pass at the same 45 points did not repeat (its max was 0.36 s). So Georgia
keeps the SHARED clock: a one-second read slice and a four-second budget against
a worst Fulton chain (county, containment, buffer, footprints) of about 2 s. A
lookup end to end took a median 0.34 s (p95 0.60 s, max 1.26 s), county request
included. ``READ_SLICE_S`` and ``LOOKUP_TIMEOUT`` are named so every request
visibly passes them; a test pins their sum under ``config.UPSTREAM_HOST_BUDGET``.

What the adapter is worth, end to end
-------------------------------------
210 homes drawn at random from the four answered layers themselves (Fulton 75,
from random residential footprints; Clayton, Chatham, Forsyth 45 each, from
random residential parcels with a year), typed as "address, city, GA ZIP",
geocoded through the Census matcher and ``assessor_address`` exactly as the
product does, then looked up with no county passed:

  =====================================  =========================================
  sampled                                  210
  geocoded                                 207   (3 unknown to Census)
  routed to the sampled county             207
  resolved                                 177   (86% of geocoded: Fulton 61/74,
                                                  Clayton 40/45, Chatham 32/43,
                                                  Forsyth 44/45)
  **matched to the wrong parcel**          **0**
  year built exact                     177/177
  floor area reported / exact            82/82   (Clayton 40, Forsyth 42)
  stories reported                         121
  =====================================  =========================================

The 30 that did not resolve: 23 geocodes more than 80 m from their own parcel
(Census interpolation through suburban subdivisions; two of them condominium
complexes with the unit typed), one parcel just at the 80 m edge, 3 Atlanta
quadrant disagreements, one Fulton "LOT" address, one "BOULEVARD GRANADA" that
the matcher abbreviates to "BLVD" in the leading position (the shared table
folds leading AVENUE and HIGHWAY only), and one street the matcher spells
differently (MIDDLEBURGH/MIDDLEBURG). Richmond, measured the same way but held:
40 sampled, 29 resolved, 0 wrong.

Privacy, and why the field lists are short
------------------------------------------
Fulton's parcel layer carries ``Owner``, ``OwnerAddr1`` and ``OwnerAddr2``;
Clayton's ``OWNERNME``, ``PSTLADDRES`` and sale prices; Chatham's ``Owner``,
``Owner2`` and ``Mailing_*``; Forsyth's ``O_OWN1`` and ``O_ADDR*``; Richmond's
``own1`` and delinquency amounts. None is an input to the label, every field list
is explicit, and the shared helper refuses ``*``. Nothing from these sources is
written into the repository.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable, NamedTuple

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Georgia county assessors"
ATTRIBUTION = ("Georgia county assessor records — Fulton, Clayton, Chatham (via SAGIS) "
               "and Forsyth county GIS services (keyless)")
#: The module-wide fallback. Every record carries its own county's roll instead
#: (see each county's ``vintage``), because the four rolls are four different
#: years: Fulton's 2026 digest, Chatham's 2025 digest, Forsyth's 2024 snapshot.
DATA_VINTAGE = ("Georgia county assessor rolls, per county (Fulton tax year 2026, "
                "Chatham 2025 digest, Forsyth tax year 2024 snapshot, Clayton current)")

# ── endpoints ──────────────────────────────────────────────────────────────────

_FULTON = "https://services1.arcgis.com/AQDHTHDrZzfsFsB5/arcgis/rest/services"
FULTON_PARCEL_URL = _FULTON + "/Tax_Parcels/FeatureServer/0/query"
FULTON_STRUCTURES_URL = _FULTON + "/Structure_Footprints/FeatureServer/0/query"
CLAYTON_URL = ("https://gis.claytoncountyga.gov/server/rest/services/TaxAssessor"
               "/Parcels/MapServer/0/query")
CHATHAM_URL = ("https://pub.sagis.org/arcgis/rest/services/OpenData/Parcels"
               "/MapServer/27/query")
FORSYTH_URL = ("https://services2.arcgis.com/StQaZGYzUARPnrpL/arcgis/rest/services"
               "/TylerParcels/FeatureServer/90/query")
RICHMOND_URL = ("https://gismap.augustaga.gov/arcgis/rest/services/Map_LayersTS"
                "/MapServer/316/query")
#: Census TIGERweb county polygons, asked only when the caller did not say which
#: county the point is in (a direct call). The registry passes the county it
#: routed on, so the product never makes this request. See ``_county_at``.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
              "/State_County/MapServer/1/query")

#: How long a county service may go quiet before the silence is a stall, and the
#: budget for a whole Georgia lookup. Both are the SHARED defaults, kept on
#: purpose and named here only so every request visibly passes them: measured
#: over 738 requests at random homes (see "Timing" in the module docstring), one
#: took longer than 0.75 s — a single 4.9 s Forsyth buffered query that a second
#: pass at the same 45 points did not repeat — and the slowest Fulton chain
#: (county + containment + buffer + footprints) sums to about 2 s. Neither
#: Florida's nor Connecticut's longer clock is warranted; raising them would only
#: let a hung portal hold the label longer, and a 2 s slice would not have
#: rescued the one 4.9 s request either.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT


# ── shared Georgia readings ────────────────────────────────────────────────────


def _text(value) -> str:
    """A county's string column, trimmed. Forsyth writes ' ' for missing."""
    return " ".join(str(value if value is not None else "").split())


def _year(value) -> int | None:
    """The actual year built, or None. Several of these columns are STRINGS
    (Fulton's footprints, Clayton, Forsyth), carrying '', ' ', '0' and junk such
    as Clayton's '970' for "not recorded" — so the parse is numeric and then
    range-checked, never trusted as written."""
    y = num(_text(value) or None)
    if y is None or not float(y).is_integer():
        return None
    y = int(y)
    return y if EARLIEST_PLAUSIBLE_YEAR <= y <= 2100 else None


def _whole(value) -> int | None:
    """A positive whole number (a story count), or None for 1.5, 0, blank."""
    v = num(_text(value) or None)
    if v is None or v <= 0 or not float(v).is_integer():
        return None
    return int(v)


def _area(value) -> float | None:
    v = num(_text(value) or None)
    return v if v is not None and v > 0 else None


#: Georgia digest classes (the Department of Revenue's statewide letters, used by
#: Fulton's ClassCode, Chatham's Property_Use and Forsyth's P_CLASS) that state
#: the parcel is not a home: Commercial, Industrial, Utility. Deliberately not E
#: (exempt): Fulton has 119 single-family, one-unit parcels classed E1 — a home
#: owned by a church or a housing authority is still a home — so exemption is
#: silence about who lives there, and refusing on silence is the error Florida's
#: dwelling count was written to avoid.
_NOT_A_HOME_CLASSES = ("C", "I", "U")


def _class_says_no_home(value) -> bool:
    return _text(value).upper().startswith(_NOT_A_HOME_CLASSES)


#: The Georgia appraisal land-use codes Fulton (LUCode) and Clayton (LANDUSEC)
#: share — 101 one-family, 106 condominium, 107 townhouse, 2xx apartments, 3xx
#: commercial, 4xx industrial, 6xx exempt institutions, 7xx utilities, 8xx tax
#: incentive — read for the codes that STATE no one lives on the parcel: vacant
#: land, common areas, and the commercial, industrial, exempt-institution and
#: utility ranges. Measured in Clayton, those ranges are where its 6,000-odd
#: non-residential year-built values live (auto garages, warehouses, retail).
_VACANT_OR_COMMON = frozenset({
    "100",   # residential vacant
    "111",   # homeowner association property
    "113",   # CUVA/preferential agricultural, vacant
    "166",   # condominium common element
    "188",   # homeowner association common area
    "200",   # apartment vacant land
    "300", "400", "600",   # vacant commercial / industrial / exempt land
})
#: Codes inside the non-residential ranges that are someone's home anyway.
_HOMES_IN_OTHER_RANGES = frozenset({
    "301",   # residential on commercial land
    "318",   # boarding / rooming house
    "319",   # mixed residential/commercial
    "614",   # single-family residence (institutional)
    "622",   # single-family residence (parsonage)
})


def _luc_says_no_home(value) -> bool:
    luc = _text(value).upper()
    if not luc:
        return False                       # silence, not a statement
    if luc in _VACANT_OR_COMMON:
        return True
    return luc[0] in "34678" and luc not in _HOMES_IN_OTHER_RANGES


# ── Fulton: two hops, parcel → structure footprints ────────────────────────────

_FULTON_FIELDS = "ParcelID,Address,AddrUnit,LUCode,ClassCode,LivUnits,TaxYear"
# AreaSqFt is deliberately absent: it is NOT the home's living area (see the
# module docstring), and a column that never arrives cannot be read by a later
# edit. LUC/LUCDesc duplicate the parcel's own code.
_FULTON_STRUCTURE_FIELDS = "ParcelID,FeatType,YearBuilt,Stories,StructForm"

# Building forms Fulton writes beside a story count that the count cannot be
# taken at face value for. Split levels, bi-levels and Capes (a story and a
# half) have no whole-number reading — the call Cook makes for "Split Level" —
# and Fulton files 10,119 split levels and 4,046 bi-levels as Stories = 1. A
# duplex's or condominium's story count is the building's, not one home's.
_FULTON_NO_STORY_FORMS = frozenset({"split-level", "bi-level", "cape", "duplex",
                                     "condominium"})
# Forms whose name fixes the count, so a disagreeing Stories is a data error:
# Fulton files 269 "Ranch" footprints with Stories = 2 against 56,417 with 1.
_FULTON_FORM_STORIES = {"ranch": 1}
# One home on its own parcel: one-family and townhouse.
_ONE_HOME_LUCS = frozenset({"101", "107"})


def _fulton_address(parcel: dict) -> str | None:
    """The parcel's site address — unless it is a half-number.

    Fulton writes "208 CAMP ST 1/2" with the "1/2" in AddrUnit. The shared
    comparison reads a digit-bearing token after a street type as an unmarked
    unit and drops it, which is right for "633 CARLTON POINTE DR 23" and wrong
    here: 208½ Camp St is a different house from 208 Camp St. Such a parcel
    offers no address, so it cannot be confirmed by either reader's address."""
    if "/" in _text(parcel.get("AddrUnit")):
        return None
    return parcel.get("Address")


def _fulton_footprints(pid: str, deadline: float) -> list[dict]:
    """Every structure footprint Fulton links to this parcel id."""
    body = _shared.get_json(FULTON_STRUCTURES_URL, {
        # Quoting is safe because the id comes from the parcel layer's own
        # response, not from user input; the apostrophe strip is belt and braces
        # against a malformed record breaking the predicate.
        "where": f"ParcelID='{pid.replace(chr(39), '')}'",
        "outFields": _FULTON_STRUCTURE_FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    return [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]


def _fulton_stories(rows: list[dict]) -> int | None:
    """The story count of the parcel's dwelling, where every residential
    footprint agrees on it and its form allows a whole-number reading."""
    readings = {(_whole(r.get("Stories")), _text(r.get("StructForm")).lower())
                for r in rows}
    if len(readings) != 1:
        return None
    stories, form = readings.pop()
    if stories is None or form in _FULTON_NO_STORY_FORMS:
        return None
    fixed = _FULTON_FORM_STORIES.get(form)
    return stories if fixed in (None, stories) else None


def _fulton_facts(parcel: dict, deadline: float) -> dict | None:
    """What Fulton's footprints say about the dwelling on this parcel.

    The year is read from the RESIDENTIAL footprints only (a commercial
    footprint's year is a shop's), and only where they all agree. They usually
    do, because each footprint carries the parcel's CAMA dwelling year rather
    than a year of its own — a house and its garage both read 1939. Where they
    disagree the parcel holds two dwelling records (a 1973 house and a 1976
    second home on 7007 Riverside Dr), and naming either would be a guess, so
    the parcel is refused. Measured: 9 of 774 and 1 of 85 multi-footprint
    parcels in two samples.
    """
    if _class_says_no_home(parcel.get("ClassCode")):
        return None
    if _luc_says_no_home(parcel.get("LUCode")):
        return None
    units = num(parcel.get("LivUnits"))
    if units == 0:
        # An explicit zero is the roll saying "no dwelling here". A missing count
        # (416 one-family parcels) says nothing and is let through.
        return None
    rows = [r for r in _fulton_footprints(str(parcel["ParcelID"]).strip(), deadline)
            if _text(r.get("FeatType")).lower() == "residential"]
    years = {_year(r.get("YearBuilt")) for r in rows}
    years.discard(None)
    if len(years) != 1:
        return None
    one_home = (_text(parcel.get("LUCode")) in _ONE_HOME_LUCS and units == 1
                and not _text(parcel.get("AddrUnit")))
    return {"year_built": years.pop(),
            "stories": _fulton_stories(rows) if one_home else None}


def _fulton_vintage(parcel: dict) -> str:
    year = _year(parcel.get("TaxYear"))
    if year:
        return (f"Fulton County Board of Assessors {year} tax parcels, with the "
                f"county's structure footprints")
    return "Fulton County Board of Assessors tax parcels, with structure footprints"


# ── Clayton: one hop ───────────────────────────────────────────────────────────

# UNIT is requested by nobody: in Clayton it is the PLAT's unit ("UNIT 1 PHASE A"
# on every lot of a subdivision phase), not a dwelling unit, and reading it as one
# would refuse the floor area of whole subdivisions. QUALITYOFBUILDING (A/G/F/L/
# V/E) is a construction-quality grade, not a condition rating, so it has no slot
# in the label and is not requested either. Owner and mailing columns (OWNERNME,
# PSTLADDRES…) and every value and sale column stay unrequested.
_CLAYTON_FIELDS = "PARCELID,SITEADDRES,LANDUSEC,STRUCTYPE,YEARBUILT,SQRFT"

# STRUCTYPE is the dwelling's style. Only the three that name a whole number of
# stories are read; "SPLIT LEVEL", "1 1/2 STORY" and "2 1/2 STORY" have none.
_CLAYTON_STORIES = {"RANCH": 1, "TWO STORY": 2, "3 STORY": 3}


def _clayton_facts(row: dict, deadline: float) -> dict | None:
    luc = _text(row.get("LANDUSEC"))
    if _luc_says_no_home(luc):
        return None
    one_home = luc in _ONE_HOME_LUCS
    return {"year_built": _year(row.get("YEARBUILT")),
            "sqft": _area(row.get("SQRFT")) if one_home else None,
            "stories": (_CLAYTON_STORIES.get(_text(row.get("STRUCTYPE")).upper())
                        if one_home else None)}


def _clayton_vintage(row: dict) -> str:
    return ("Clayton County Tax Assessor parcel service (the current roll; the "
            "service publishes no roll year)")


# ── Chatham: one hop, SAGIS's annual open-data digest ──────────────────────────

# No floor area, story count or material exists in the digest. Effective_YB is
# the effective year and is not requested; Owner, Owner2 and Mailing_* are on the
# layer and are not requested either.
_CHATHAM_FIELDS = ("PIN,PropAddress_Full,PropAddress_UnitNum,Property_Use,"
                   "YearBuilt,FMV_Building,Date_Updated")


def _chatham_unit(row: dict) -> str | None:
    """The parcel's own unit. The digest writes it '#A' (and the full address
    '111 SAN MARCO DR ##A', with the '#' doubled), so the marker is stripped."""
    unit = _text(row.get("PropAddress_UnitNum")).lstrip("#").strip()
    return unit or None


def _chatham_facts(row: dict, deadline: float) -> dict | None:
    if _class_says_no_home(row.get("Property_Use")):
        return None
    if num(row.get("FMV_Building")) == 0:
        # A building value of exactly zero is the roll saying no building stands
        # here (118 parcels carry a year anyway — demolitions, by the look).
        return None
    return {"year_built": _year(row.get("YearBuilt"))}


def _chatham_vintage(row: dict) -> str:
    day = _epoch_day(row.get("Date_Updated"))
    if day:
        return f"SAGIS Chatham County Parcel Digest {day.year}, updated {day.isoformat()}"
    return "SAGIS Chatham County Parcel Digest 2025"


# ── Forsyth: one hop, a staff-uploaded tax-year-2024 snapshot ──────────────────

# D_* columns are the residential DWELLING card; CD_YRBLT (the commercial card's
# year) is not requested, so a shop's year cannot be read as a home's. D_STYLE
# and D_GRADE are numeric codes with no published table (Cook's lesson: a code
# without its table is a guess). O_OWN1, O_ADDR* and every value column stay out.
_FORSYTH_FIELDS = "VAL_PARID,SITEADDRES,UNIT,P_CLASS,P_LUC,D_YRBLT,D_STORIES,BLDGAREA,TAXYEAR"

# Land uses that state there is no home: the county's own descriptions (LU_MSG)
# are "SFR COMMON AREA", "AMENITY AREA", "UNDEVELOPED LOT", "TOWNHOME COMMON AREA".
# Commercial and industrial land uses are classed C/I and refused by class.
_FORSYTH_NOT_A_HOME_LUCS = frozenset({"0111", "0117", "0207", "0311"})
# One home on its own parcel, by the county's own descriptions: "SFR" and its
# siting variants (CREEK, RIVER, MT VW, WATER, GOLF, NODOCK, COMMUNITY DOCK LOT,
# P LAKE), "SF RESIDENTIAL", and "TOWNHOME". Deliberately absent: "RESIDENTIAL
# CONDOMINIUM" (0300), the rural acreage classes (0120, 0130, 0140 — a farm can
# carry a second dwelling and nothing here counts them), "RURAL ZONE
# RESIDENTIAL" (0150, same) and "RES ON COMMERCIAL LAND" (0302).
_FORSYTH_ONE_HOME_LUCS = frozenset({"0100", "100", "0101", "0113", "0121", "0122",
                                    "0123", "0124", "0125", "0127", "0309"})


def _forsyth_unit(row: dict) -> str | None:
    return _text(row.get("UNIT")) or None


def _forsyth_facts(row: dict, deadline: float) -> dict | None:
    if _class_says_no_home(row.get("P_CLASS")):
        return None
    luc = _text(row.get("P_LUC"))
    if luc in _FORSYTH_NOT_A_HOME_LUCS:
        return None
    one_home = luc in _FORSYTH_ONE_HOME_LUCS and not _forsyth_unit(row)
    return {"year_built": _year(row.get("D_YRBLT")),
            "sqft": _area(row.get("BLDGAREA")) if one_home else None,
            "stories": _whole(row.get("D_STORIES")) if one_home else None}


def _forsyth_vintage(row: dict) -> str:
    year = _year(row.get("TAXYEAR"))
    return (f"Forsyth County tax year {year or 2024} parcel snapshot (a staff-"
            f"uploaded Tyler iasWorld export, not the live roll)")


# ── Richmond (Augusta): configured, measured, held for its terms ───────────────

# Owner (own1, owner_address1…), delinquency and fee columns stay unrequested.
_RICHMOND_FIELDS = "pin,siteaddress,propdesc,vacant,yr_built,structsize"


def _richmond_facts(row: dict, deadline: float) -> dict | None:
    if _text(row.get("vacant")).lower() == "yes":
        return None
    desc = _text(row.get("propdesc")).lower()
    if desc.startswith(("commercial", "exempt", "utility", "industrial")):
        return None
    # "Residential Lots" covers duplexes as well as houses, and nothing in the
    # layer counts dwellings, so no floor area is reported.
    return {"year_built": _year(row.get("yr_built"))}


def _richmond_vintage(row: dict) -> str:
    return "Augusta-Richmond County parcels (current digest year)"


# ── the county table ───────────────────────────────────────────────────────────


def _no_unit(row: dict) -> str | None:
    return None


class _County(NamedTuple):
    """Everything that differs between two Georgia counties."""

    name: str
    source: str                                  # attribution on each record
    url: str
    fields: str                                  # explicit; never '*'
    pid: str                                     # the parcel id column
    address_of: Callable[[dict], str | None]
    unit_of: Callable[[dict], str | None]        # the parcel's own unit
    facts: Callable[[dict, float], dict | None]  # (row, deadline) → facts
    vintage: Callable[[dict], str]


def _column(name: str) -> Callable[[dict], str | None]:
    return lambda row: row.get(name)


_COUNTIES: dict[str, _County] = {
    "13121": _County(
        "Fulton", "Fulton County Board of Assessors via Fulton County GIS (keyless)",
        FULTON_PARCEL_URL, _FULTON_FIELDS, "ParcelID", _fulton_address,
        lambda r: _text(r.get("AddrUnit")) or None, _fulton_facts, _fulton_vintage),
    "13063": _County(
        "Clayton", "Clayton County Tax Assessor via Clayton County GIS (keyless)",
        CLAYTON_URL, _CLAYTON_FIELDS, "PARCELID", _column("SITEADDRES"),
        _no_unit, _clayton_facts, _clayton_vintage),
    "13051": _County(
        "Chatham", "Chatham County Board of Assessors via SAGIS Open Data (keyless)",
        CHATHAM_URL, _CHATHAM_FIELDS, "PIN", _column("PropAddress_Full"),
        _chatham_unit, _chatham_facts, _chatham_vintage),
    "13117": _County(
        "Forsyth", "Forsyth County Tax Assessor via Forsyth County GIS (keyless)",
        FORSYTH_URL, _FORSYTH_FIELDS, "VAL_PARID", _column("SITEADDRES"),
        _forsyth_unit, _forsyth_facts, _forsyth_vintage),
    "13245": _County(
        "Richmond", "Augusta-Richmond County Board of Assessors via Augusta GIS",
        RICHMOND_URL, _RICHMOND_FIELDS, "pin", _column("siteaddress"),
        _no_unit, _richmond_facts, _richmond_vintage),
}

#: Counties configured and measured but NOT answered for, because their
#: publisher's terms forbid reproducing the data without written consent. See
#: "Terms of use" in the module docstring; remove a county from this set only on
#: a product-owner decision that the terms permit this use.
_HELD_FOR_TERMS = frozenset({"13245"})

COUNTY_FIPS = frozenset(_COUNTIES) - _HELD_FOR_TERMS


# ── the parcel ─────────────────────────────────────────────────────────────────


def _epoch_day(ms):
    v = num(ms)
    if not v:
        return None
    try:
        day = datetime.fromtimestamp(v / 1000, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return day if 1990 <= day.year <= 2100 else None


def _pid(county: _County, row: dict) -> str | None:
    """The county's parcel id, trimmed at the ends ONLY. Inner runs of spaces are
    part of the id — Fulton's "17 0127  LL0599", Forsyth's "073   290" — and
    collapsing them would hand a reader an id the county's own search does not
    know, and break Fulton's second hop, which joins on it."""
    raw = row.get(county.pid)
    pid = str(raw).strip() if raw is not None else ""
    return pid or None


def _parcels(county: _County, lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Real parcel records at (or within ``distance_m`` of) a point.

    Rows with no parcel id are records of nothing and are dropped before the
    choice (Florida's placeholder-polygon rule). Rows identical in every
    requested column are one parcel repeated — a multipart polygon returns one
    row per part — and are collapsed, which can only turn "ambiguous" into "one".
    Two rows sharing an id but differing in anything stay two candidates.
    """
    rows = _shared.arcgis_parcels(county.url, lat, lon, county.fields, distance_m,
                                  deadline=deadline, read_slice=READ_SLICE_S)
    out, seen = [], set()
    for row in rows:
        if _pid(county, row) is None:
            continue
        key = tuple(sorted((k, str(v)) for k, v in row.items()))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _same_unit_or_none(own: str | None, typed: str) -> bool:
    """Whether a parcel could be the typed unit's: it names that unit, or none."""
    return own is None or own.lstrip("#").lower() == typed.lstrip("#").lower()


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the Georgia county this point is in, from Census TIGERweb."""
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "GEOID", "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    found = {_text((f or {}).get("attributes", {}).get("GEOID"))
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


def _parcel_at(county: _County, lat: float, lon: float, address: str | None,
               *, deadline: float) -> dict | None:
    """The parcel this point belongs to, or None. The choice is
    ``_shared.select_parcel``'s; see it for why the nearest parcel is never
    taken. Every county here keeps the city out of its site-address column, so
    no locality trim is needed."""
    typed_unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            fetched[distance_m] = _parcels(county, lat, lon, distance_m,
                                           deadline=deadline)
        found = fetched[distance_m]
        # A reader who typed a unit cannot live in a parcel naming a DIFFERENT
        # unit. Chatham's and Fulton's condominium and duplex units are separate
        # parcels sharing a street address ("111 SAN MARCO DR ##A", "##B"), so
        # without this a typed "#B" faces every unit and is refused. Dropping rows
        # that cannot be the answer is the sanctioned shape (see select_parcel).
        if typed_unit:
            return [p for p in found if _same_unit_or_none(county.unit_of(p), typed_unit)]
        return found

    return select_parcel(fetch, address, county.address_of)


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    deadline = deadline_from(None, LOOKUP_TIMEOUT)
    fips = county_fips if county_fips else _county_at(lat, lon, deadline=deadline)
    if fips not in COUNTY_FIPS:
        return None
    county = _COUNTIES[fips]
    parcel = _parcel_at(county, lat, lon, address, deadline=deadline)
    if not parcel:
        return None
    facts = county.facts(parcel, deadline) or {}
    year_built, sqft, stories = (facts.get("year_built"), facts.get("sqft"),
                                 facts.get("stories"))
    if year_built is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=county.source,
        data_vintage=county.vintage(parcel),
        parcel_id=_pid(county, parcel),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        # No Georgia layer here carries a wall material, foundation type or
        # condition rating in a form the label can read; see the docstring.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher, not another's."""
    county = _COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What a Georgia county's roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is the county the registry routed on; without it the
    county is looked up from the point (one extra request). A county passed
    explicitly but not in ``COUNTY_FIPS`` is answered with None, not re-routed.

    Fails open on everything, a truncated page (``_shared.TruncatedResponse``)
    included. The caller then keeps whatever it had.
    """
    try:
        fips = str(county_fips).strip().zfill(5) if county_fips else None
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Georgia assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
