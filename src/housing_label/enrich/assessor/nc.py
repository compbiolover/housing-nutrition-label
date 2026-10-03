#!/usr/bin/env python3
"""North Carolina — 46 of the state's 100 counties from one statewide layer, in a single request.

The fifth adapter, and the third that answers from one statewide service. It
exists for the same reason Florida's and Connecticut's do: the state has already
gathered the counties' parcel files into one place.

NC OneMap — run by the Center for Geographic Information and Analysis (CGIA) in
the state's Department of Information Technology — collects every county's
parcel file, rewrites each into one standard set of columns (the Integrated
Cadastral Data Exchange schema), and republishes the result as a single layer:

  ``NC1Map_Parcels/FeatureServer/1`` — "Parcels (polys)", 5,938,900 parcels
  across all 100 counties, keyless, verified live.

Why 46 counties and not 100
---------------------------
The schema has a column for the year built — ``structyear``, defined in the
state's data dictionary as "the year built of the primary building on the
parcel" — but filling it is up to each county, and **51 of the 100 counties
leave it at 0 for every parcel they file.** Measured over the whole layer, not a
sample (2026-10-03):

  * **51 counties: no year built at all.** Among them are some of the largest in
    the state — Forsyth, Durham, Buncombe, New Hanover, Cabarrus, Davidson,
    Rowan, Robeson, Craven, Cleveland — and 41 smaller ones.
  * **Bertie: 499 of 18,788 parcels (2.7%).** Close enough to nothing that a
    lookup there would cost a request for a 3% chance of an answer.
  * **Orange and Franklin: a year on 47,225 and 30,145 parcels, and no street
    address on any of them** — neither ``siteadd`` nor its components. The
    product always confirms a parcel against the geocoder's matched address
    (``_shared.select_parcel``), so a parcel that carries no address can never
    be confirmed, and every lookup there would end in a refusal after two
    requests.
  * **The other 46: 39% to 88% of all parcels carry a year** — vacant land and
    farm tracts included, so the share of *homes* is higher. Next lowest after
    Bertie is Columbus at 39%; there is no county in between, so the line is
    not a judgment call.

``COUNTY_FIPS`` is those 46, and not the state, because registering a county
here is a claim the label makes to a reader: that an observed year built is
available. Registering all 100 would make every lookup in the other 54 cost a
request (or two) for an answer that cannot exist, and would let anyone counting
coverage from the registry count 1.7 million homes that this source does not
describe. The 46 hold 3.15 million of the state's 4.90 million housing units
(ACS, this repository's ``year_built_county.csv``) — 64%.

The table is a measurement, so it can go stale in the good direction: if a
county starts filling ``structyear``, it is not served here until someone
re-measures and adds it. That is the safe way round.

One request, like Florida
-------------------------
The parcel shape and the county's record sit on the same feature, so a lookup is
one question: *which parcel is this point inside, and what does its record say?*
Attribute and spatial queries are not scale-gated, though the layer advertises
``minScale`` 50,000 — that governs drawing the layer in a map viewer, not
answering a query, and every number below was measured through ``/query``.

What this source carries, and what it does not
----------------------------------------------
**Only the year built.** The standard schema has no floor area, no story
count, no wall material, no foundation and no condition, so those stay empty and
NSI's estimate stands for them. That also means the condominium trap that
Florida and Connecticut spend a page on — a parcel's floor area describing a
tower rather than a home — cannot arise: there is no area to report. The year a
building went up is the same for every unit in it.

Three columns look as if they should help, and are deliberately not used:

* ``struct`` — "Is there a structure on the parcel? (Y/N/U)". It reads like the
  zero-dwelling statement Florida's ``NO_RES_UNT == 0`` gives, and it is not
  one. Union, Burke, Duplin and Currituck write ``N`` on every parcel they file,
  and Catawba writes ``N`` on 64,171 of its 64,174 parcels that *do* carry a
  year built. Even where a county uses both values, an ``N`` beside a year is
  mostly a house: the commonest descriptions on such parcels in Wayne, Nash and
  Rockingham are "50 - RURAL SINGLE FAMILY RESIDENCE", "D-Dwelling" and "SINGLE
  FAMILY RES". Refusing on it would discard five whole counties to turn away
  almost nothing.
* ``structno`` and ``multistruc`` — the number of structures. ``structno`` is 0
  on 1,725,996 of the 2,717,832 parcels that carry a year, which is "not
  recorded", not "none".
* ``sourcedate`` — the date of the source *document* (typically the deed), so it
  dates a sale, not the record.

The use description, read only where it is unambiguous
------------------------------------------------------
``parusedesc`` is each county's own land-use wording, passed through: 2,611
distinct values among the parcels that carry a year — "R", "SINGLE FAMILY
RESIDENTIAL", "R101-RES", "D-Dwelling", "50 - RURAL SINGLE FAMILY RESIDENCE",
"RA20 01-SFR-CONST(01-SFR)". No code table travels with the service, so it is
never *translated* into anything. It is used for one thing only: to refuse a
year built from a parcel the county itself says is not a home, which is the same
rule Florida applies with its dwelling count.

Two kinds of statement are taken as refusals:

* **"There is no home here"** — the words VACANT, VAC or COMMON anywhere in the
  description: "VACANT LAND", "CLASS: RESIDENTIAL - VAC", "SINGLE FAMILY
  RESIDENTIAL - COMMON", "TOWN HOUSE COMMON AREA". A year on a vacant lot is a
  shed's, or a demolished house's; a year on an HOA common area is the
  clubhouse's.
* **"This is not a dwelling"** — a clearly non-residential word (COMMERCIAL,
  INDUSTRIAL, OFFICE, RETAIL, CHURCH, WAREHOUSE, RESTAURANT, HOTEL, MOTEL, BANK,
  SCHOOL, STORE, MEDICAL, …) *with no residential word beside it*. The
  exception is the point: "House on Commercial Site" (1,155 parcels), "SINGLE
  FAMILY ON COMM LD", "Mixed Use Commercial", "COMMERCIAL APARTMENT" and
  "RETAIL-50%,SINGLE FAMILY RESIDENCE-50%" all name somebody's home and are all
  kept. "Office condominium" is refused: CONDO is deliberately not a
  residential word, because "OFFICE CONDOMINIUM", "WAREHOUSE CONDOMINIUM" and
  "MEDICAL CONDOMINIUM" are all in the vocabulary.

Words are matched whole — COMM is a word in "COMM VACANT LAND", not a prefix of
everything — and EXEMPT is *not* a refusal, because "ELDERLY & DISABLED - PART
EXEMPT" and "DISABLED VETERAN - PART EXEMPT" are homestead exemptions on homes.
Single-letter codes ("C", "E", "R") are never read: what "C" means is a fact
about one county's code table, and that is a guess this adapter must not make.

One county's description is filler, and is ignored. **Duplin writes "VACANT
LAND" on every one of its 43,612 parcels**, including the 19,109 that carry a
year built, so in Duplin the words say nothing about the parcel — the same fault
as ``struct``, in a different column. Read literally it would refuse the whole
county; it is skipped there by county code, and a test pins it.

Measured across the 46 counties, the two refusals together turn away 77,213 of
the 2,639,963 parcels that carry a year — 2.9%, almost all of it "COMMERCIAL",
"INDUSTRIAL", "OFFICE" and "VACANT LAND". No county loses more than Vance's
10.6%, which is its "CLASS: COMMERCIAL - IMP" and "CLASS: RESIDENTIAL - VAC".

The two year-built values that are not years
--------------------------------------------
* **0** — the schema's "not recorded", on 3.2 million parcels. Without the
  check it would age the building by two thousand years.
* **1600** — Wilkes County's placeholder, on 2,501 parcels and on no parcel in
  any other county. Most of them are ordinary rural homes ("1519 CONLEY
  SHUMAKER RD", "336 HAPPY OAKS LANE"); it is how Wilkes writes "year not
  known", and no building standing in North Carolina went up in 1600 — lasting
  English settlement there came half a century later. It sits *exactly* on the
  scorer's plausibility floor (``EARLIEST_PLAUSIBLE_YEAR``, which Connecticut's
  genuine colonial houses moved down to 1600), so the floor alone would let it
  through. It is refused by value: across the other 45 counties, the whole span
  from 1600 to 1699 holds three parcels.

Year values heap on round numbers in several counties — 1900 is 7.8% of Wayne's
recorded years, 1910 is 6.4% of Nash's, 1901 is 3.6% of Person's — which is how
an appraiser writes "old, exact year unknown". Those are kept: they are the
county's own record of an old building, and the scorer's tract fallback is no
closer.

Where the street address lives
------------------------------
Counties fill the address in different places and forms, and the adapter needs
one it can compare against the geocoder's matched address:

* Most counties fill ``siteadd`` with the street address alone —
  ``"420 HAYWOOD ST"``.
* Some run the city, state and ZIP into it: Carteret writes
  ``"486 HARKERS ISLAND RD BEAUFORT NC 28516"``, Haywood ``"450 SHADY RIDGE RD
  WAYNESVILLE NC 28786"`` (sometimes with the ZIP cut to four digits), Harnett
  ``"1504 S CLINTON AVE  DUNN"``, Mecklenburg ``"1000 E WOODLAWN RD, 203
  CHARLOTTE NC"``. That tail is trimmed here — see ``_trim_locality`` — because
  the shared comparison expects a street address and would otherwise read
  ``BEAUFORT`` as part of the street's name and refuse the parcel.
* Guilford, and part of Mecklenburg, leave ``siteadd`` empty and fill only the
  components (``saddno``, ``saddpref``, ``saddstr``, ``saddsttyp``,
  ``saddstsuf``), which are joined back into one string.

``siteadd`` is preferred whenever it parses, and the components are a fallback
rather than a cross-check. Unlike Connecticut's two address columns — two
*filings*, joined per town and sometimes joined wrongly — these are one county
file split two ways by the same transformation, and some counties' components
are simply broken: Wilson's carry the parcel number where the house number
belongs (``saddno = "1300599"``, ``saddstr = "2505"``) beside a correct
``siteadd`` of ``"2505 WILLIAMSBURG DR NW"``. A disagreement rule would refuse
Wilson outright for a fault in a column that is never needed there.

Why this service does NOT need its own clock
--------------------------------------------
Florida and Connecticut each define their own read slice and lookup budget,
because their services think for seconds before answering and the shared
one-second slice was cutting them off. This one does not. Measured over the
286 real lookups of the end-to-end run below (41 counties), timing each request
the adapter actually made:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which parcel is this dot inside?"   76 ms   97 ms  138 ms  403 ms
  "what is within 80 m of this dot?"   84 ms  111 ms  159 ms  315 ms
  ==================================  ======  ======  ======  ======

A separate run of 60 containment and 60 buffered queries at parcel centroids in
23 counties agreed (medians 73 and 81 ms, maxima 233 and 390 ms). Responses are
at most 22 KB. Nothing comes within a factor of two of the shared one-second
slice, and the worst pair sums to 0.7 s against the shared four-second budget,
so this adapter takes both shared defaults, like Cook and the District — and a
genuinely hung connection is cut off as quickly here as anywhere. The shared
worst case (4 s budget spent connecting plus one 1 s slice = 5 s) is inside the
12 s the host allows one service (``config.UPSTREAM_HOST_BUDGET``); a test pins
that sum against the constant.

What the adapter is worth, end to end
-------------------------------------
300 homes drawn at random from the layer itself (random object ids, so spread in
proportion to parcels: 41 of the 46 counties), each a parcel this adapter would
answer for — a plausible year, no refusing use description, an address that
parses. Each address was typed with its ZIP, geocoded through the Census matcher
exactly as the product does, passed through ``assessor_address`` and looked up:

* 286 geocoded, and all 286 routed to a county in ``COUNTY_FIPS`` — the very
  county the parcel is filed in, every time.
* **210 resolved, and 0 matched to the wrong parcel.** All 210 years are exact.
* 76 did not resolve. 56 are geocodes the Census matcher placed out of reach
  of the shared 80 m search — interpolated along the street, 91 m to 2.7 km
  from the parcel's center, median 156 m. 14 are spellings the two sources
  genuinely disagree on: a directional present on one side only ("802 MEMORIAL
  BLVD" against "802 N MEMORIAL BLVD", which is not forgiven — see
  ``_comparable``), "STEEPLECHASE" against "STEEPLE CHASE", "OLE" against
  "OLD", "NC HWY 45 S" against "S STATE HWY 45". 6 are the shared chooser
  declining an ambiguity: two parcels under the point, or one address on
  several parcels (Mecklenburg's stacked build-to-rent parcels, a Carteret
  condominium complex).

The respelling in ``_comparable`` and the collapsing of identical rows were added
because of this run; before them, the same kind of sample resolved 105 of 144.

Terms of use
------------
NC OneMap's terms (``https://www.nconemap.gov/pages/terms``, linked as the
layer's license) describe a "free and unrestricted use policy" that every
contributing county accepts by sharing its data, state that "written release
agreements to authorize use of the geospatial data, web services, and
applications found on the NC OneMap website are not required and will not be
issued", disclaim every warranty, and add one condition: "Any sale of this data
must not violate applicable state laws or regulations." The state law in point
is N.C.G.S. §132-10, which lets a county or city, as a condition of furnishing
an electronic copy of its GIS files, require that the copy not be resold or used
for trade or commercial purposes. This adapter queries the
service live and caches in-process only; it never copies, bundles or sells the
county records, and nothing from the service is written into the repository —
the same posture every adapter here takes (``base.py``). Verdict: permitted.

Privacy, and why the field list is short
----------------------------------------
This layer has 70 columns, among them ``ownname``, ``ownname2``, ``ownfrst``,
``ownlast``, ``mailadd`` and the rest of the owner's mailing address,
``saledate``, ``legdecfull`` and every assessed value. None of it is an input to
any dimension of the label. Thirteen columns are requested by name and the
other 57 are never fetched — the shared helper refuses ``*`` for precisely this
reason.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache

from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, arcgis_parcels, cache_bucket, deadline_from, num,
    select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# The 46 North Carolina counties whose parcel files carry a year built. Listed
# rather than computed, because the list IS the measurement: see "Why 46 counties
# and not 100" in the module docstring for the 54 that are left out and why. A
# test checks every code against the county table this repository ships, and
# that none of the counties measured as empty has crept in.
COUNTY_FIPS = frozenset({
    "37001",   # Alamance
    "37011",   # Avery
    "37013",   # Beaufort
    "37019",   # Brunswick
    "37023",   # Burke
    "37031",   # Carteret
    "37035",   # Catawba
    "37047",   # Columbus
    "37051",   # Cumberland
    "37053",   # Currituck
    "37055",   # Dare
    "37061",   # Duplin
    "37071",   # Gaston
    "37075",   # Graham
    "37081",   # Guilford
    "37083",   # Halifax
    "37085",   # Harnett
    "37087",   # Haywood
    "37089",   # Henderson
    "37097",   # Iredell
    "37101",   # Johnston
    "37105",   # Lee
    "37107",   # Lenoir
    "37119",   # Mecklenburg
    "37123",   # Montgomery
    "37125",   # Moore
    "37127",   # Nash
    "37131",   # Northampton
    "37133",   # Onslow
    "37145",   # Person
    "37147",   # Pitt
    "37151",   # Randolph
    "37157",   # Rockingham
    "37163",   # Sampson
    "37167",   # Stanly
    "37175",   # Transylvania
    "37177",   # Tyrrell
    "37179",   # Union
    "37181",   # Vance
    "37183",   # Wake
    "37187",   # Washington
    "37189",   # Watauga
    "37191",   # Wayne
    "37193",   # Wilkes
    "37195",   # Wilson
    "37197",   # Yadkin
})

#: Counties that carry a year built and are still left out, with the reason —
#: kept beside the list so that the next person to re-measure sees that these
#: were looked at, not missed. The 51 counties with no year at all are not
#: listed; they are every other ``37`` code.
EXCLUDED_WITH_DATA = {
    "37015": "Bertie: a year on 499 of 18,788 parcels (2.7%)",
    "37069": "Franklin: a year on 30,145 parcels, a street address on none",
    "37135": "Orange: a year on 47,225 parcels, a street address on none",
}

NAME = "NC OneMap"
ATTRIBUTION = ("North Carolina county tax offices via NC OneMap / NC CGIA "
               "(statewide standardized parcels, keyless)")
DATA_VINTAGE = ("NC OneMap statewide parcels, county files standardized under "
                "the Integrated Cadastral Data Exchange schema")

PARCEL_URL = ("https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels"
              "/FeatureServer/1/query")

# Only what the label scores, what confirms the parcel, and what dates the
# record. See "Privacy" in the module docstring for what the other 57 columns
# hold. ``struct``, ``structno`` and ``sourcedate`` are absent on purpose — see
# "What this source carries" for why each looks useful and is not.
_FIELDS = ("parno,altparno,siteadd,saddno,saddpref,saddstr,saddsttyp,saddstsuf,"
           "scity,structyear,parusedesc,stcntyfips,transfdate")

# The street address's components, in the order they are written.
_ADDRESS_PARTS = ("saddno", "saddpref", "saddstr", "saddsttyp", "saddstsuf")

# --- the use description -------------------------------------------------------
#
# Matched as whole words of letters, so "R101-RES" reads as R and RES, and COMM is
# a word only where a county wrote it as one. See "The use description, read only
# where it is unambiguous" in the module docstring for the measured vocabulary.
_WORD = re.compile(r"[A-Z]+")

#: The county says there is no home on this parcel, whatever else it says.
_NO_HOME_WORDS = frozenset({"VACANT", "VAC", "COMMON"})

#: The county says this is a non-residential use. Refused only when no word from
#: ``_HOME_WORDS`` appears beside it. EXEMPT is deliberately absent: the
#: vocabulary's exempt parcels include homestead exemptions on homes.
_NOT_A_HOME_WORDS = frozenset({
    "COMMERCIAL", "COMM", "INDUSTRIAL", "OFFICE", "OFFICES", "RETAIL", "CHURCH",
    "CHURCHES", "RELIGIOUS", "WAREHOUSE", "WAREHOUSES", "RESTAURANT",
    "RESTAURANTS", "HOTEL", "HOTELS", "MOTEL", "MOTELS", "BANK", "BANKS",
    "SCHOOL", "SCHOOLS", "STORE", "STORES", "MEDICAL",
})

#: Any of these beside a non-residential word means the parcel names a home too
#: ("House on Commercial Site", "RETAIL-50%,SINGLE FAMILY RESIDENCE-50%"), so it
#: is not refused. CONDO / CONDOMINIUM is deliberately absent — "OFFICE
#: CONDOMINIUM" and "WAREHOUSE CONDOMINIUM" are both in the vocabulary — and so
#: is every single-letter code.
_HOME_WORDS = frozenset({
    "RES", "RESID", "RESIDENTIAL", "RESIDENCE", "RESIDENCES", "DWELLING",
    "DWELLINGS", "HOME", "HOMES", "HOMESITE", "HOUSE", "HOUSES", "FAMILY", "SFR",
    "MFR", "SGL", "APART", "APARTMENT", "APARTMENTS", "DUPLEX", "TRIPLEX",
    "MOBILE", "MH", "MANUFACTURED", "TOWNHOUSE", "TOWNHOUSES", "TOWNHOME",
    "TOWNHOMES", "LIVING", "MIXED",
})

#: Counties whose use description is one constant string on every parcel, so it
#: says nothing about any one of them. Duplin: "VACANT LAND" on all 43,612.
_FILLER_DESCRIPTION = {"37061": "VACANT LAND"}

#: Year-built values that are a county's placeholder rather than a year. 1600 is
#: Wilkes's, on 2,501 parcels and nowhere else; see the module docstring.
_PLACEHOLDER_YEARS = frozenset({1600})


def _parcel_id(attrs: dict) -> str | None:
    """The county's identifier for this parcel, or None if it filed none.

    ``parno`` is the county's own parcel number; ``altparno`` is a second
    numbering some counties also keep (Wake's ``"0448960"`` beside its PIN). The
    first is preferred because it is what the county's own tax site looks up.
    """
    for column in ("parno", "altparno"):
        pid = str(attrs.get(column) or "").strip()
        if pid:
            return pid
    return None


_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})

# What follows "NC" when it is the state: a ZIP, a ZIP+4, or a ZIP the county's
# 40-character field cut short ("WAYNESVILLE NC 2878"). A route number after "NC"
# ("7352 NC HWY 18") sits straight after the house number and is never read as a
# state, because the state is only looked for from the third token on.
_ZIP_ISH = re.compile(r"^\d{4,5}(-\d{0,4})?$")


def _trim_locality(street: str, city: str | None) -> str:
    """``street`` without a city / state / ZIP tail a county ran into it.

    Two shapes are handled, both measured:

    * ``... NC <ZIP>`` or ``... NC`` — Carteret, Haywood, Mecklenburg. The state
      and ZIP go; then the city, either because it matches the row's own
      ``scity`` or, where that is blank (Haywood), because everything after the
      last street-type token — and a directional straight after it — is the
      city. "450 SHADY RIDGE RD WAYNESVILLE NC 28786" → "450 SHADY RIDGE RD".
    * ``... <scity>`` with no state — Harnett's "1504 S CLINTON AVE  DUNN".

    Only ever removes words from the right. Trimming can make a string that
    would never have matched into one that does; it cannot make two different
    street addresses equal, because the house number, the street name and the
    street type are never touched — and two parcels inside one 80 m buffer do
    not differ by city.

    Where the tail cannot be told apart from the street — no street-type token
    and no ``scity`` to match — the string is returned unchanged, and the
    comparison then refuses it. Declining to guess costs a parcel; guessing
    could cost the right one.
    """
    tokens = street.split()
    upper = [t.upper() for t in tokens]
    city_tokens = (city or "").upper().split()

    def strip_city(words: list[str]) -> list[str] | None:
        n = len(city_tokens)
        if n and len(words) > n + 1 and [w.upper() for w in words[-n:]] == city_tokens:
            return words[:-n]
        return None

    if "NC" in upper[2:]:
        at = len(upper) - 1 - upper[::-1].index("NC")
        if all(_ZIP_ISH.match(t) for t in upper[at + 1:]):
            head = tokens[:at]
            stripped = strip_city(head)
            if stripped is not None:
                return " ".join(stripped)
            # No usable scity: cut after the last street-type token, keeping a
            # directional that follows it ("... RD SW BOLIVIA").
            for i in range(len(head) - 1, 0, -1):
                if head[i].lower() in SUFFIXES:
                    end = i + 1
                    if end < len(head) and head[end].upper() in _DIRECTIONS:
                        end += 1
                    return " ".join(head[:end])
            return street
    stripped = strip_city(tokens)
    return " ".join(stripped) if stripped is not None else street


def _address_of(attrs: dict) -> str | None:
    """The parcel's street address, or None where it has none that parses.

    ``siteadd`` first, with any locality tail trimmed and anything after a comma
    dropped; then the joined components. Checked with ``address_key`` — the same
    parse the comparison itself runs — so a string that could never match is not
    offered. See "Where the street address lives" in the module docstring for why
    the components are a fallback and not a cross-check.
    """
    site = str(attrs.get("siteadd") or "").split(",")[0].strip()
    if site:
        site = _trim_locality(site, attrs.get("scity"))
        if address_key(site):
            return site
    parts = [str(attrs.get(c) or "").strip() for c in _ADDRESS_PARTS]
    joined = " ".join(p for p in parts if p)
    return joined if address_key(joined) else None


# --- spelling, applied to BOTH sides of the comparison --------------------------
#
# The shared comparison already canonicalizes the common street types ("STREET"
# = "ST", "AV" = "AVE"). North Carolina's county files and the Census matcher
# disagree in three further ways, each seen in the end-to-end run and each a
# matter of spelling, not of which building:
#
# * a directional spelled out — "6511 EAST LANGLEY RD" against the matcher's
#   "6511 E LANGLEY RD"; "1861 QUEENS RD WEST" against "1861 QUEENS RD W";
# * a single-letter directional written after the street rather than before it —
#   Guilford's "1900 BESSEMER AVE E" against "1900 E BESSEMER AVE";
# * a street type the shared table does not take, because elsewhere it means
#   something else — "TR" for trail, "CR" for circle. (Mecklenburg's "WY" for
#   Way was a third; the shared table now has it.)
#
# Both strings are rewritten the same way before the shared comparison sees them,
# so the comparison itself is untouched: every part still has to agree. The risk
# would be two DIFFERENT buildings rewritten into one string, and none of these
# rewrites can do that within one 80 m search. "100 MAIN ST N" and "100 N MAIN
# ST" are the same house on North Main Street wherever both spellings occur. The
# two-letter quadrants (NW, SW, …) are left where they are: Brunswick's and
# Catawba's files and the matcher all write them after the street already, and
# moving them would only invent a disagreement.
#
# A directional is never taken from a street NAMED for one: "100 EAST ST" keeps
# EAST as its name, because only a word with a street name beside it is read as
# a directional. A missing directional on one side ("802 MEMORIAL BLVD" against
# "802 N MEMORIAL BLVD") is NOT forgiven — 100 N Main and 100 S Main are
# different houses, and a one-sided match could join either.
_SPELLED_DIRECTIONS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
    "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
_SINGLE_DIRECTIONS = frozenset({"N", "S", "E", "W"})
# CR is Lenoir's circle ("736 CAVALIER CR" against the matcher's "736 CAVALIER
# CIR"). It cannot be a county road here: North Carolina has none — the state
# maintains every public road outside the towns, and numbers them SR.
_EXTRA_SUFFIXES = {"TR": "TRL", "CR": "CIR"}


def _comparable(address: str | None) -> str | None:
    """``address`` respelled so the two sources' conventions compare equal.

    Rewrites only the street part (before the first comma), and only the three
    things described above. Anything it does not recognize passes through
    untouched, so the worst it can do is leave a pair unmatched.
    """
    if not address:
        return address
    head, sep, tail = str(address).partition(",")
    words = [w.upper().strip(".") for w in head.split()]
    if len(words) < 3 or not words[0].isdigit():
        return address

    def is_type(word: str) -> bool:
        return word.lower() in SUFFIXES or word in _EXTRA_SUFFIXES

    # A leading spelled directional, when a street name follows it.
    if words[1] in _SPELLED_DIRECTIONS and not (len(words) == 3 and is_type(words[2])):
        words[1] = _SPELLED_DIRECTIONS[words[1]]
    # A trailing directional straight after the street type.
    if len(words) >= 4 and is_type(words[-2]):
        last = _SPELLED_DIRECTIONS.get(words[-1], words[-1])
        if last in _DIRECTIONS:
            words[-1] = last
            if last in _SINGLE_DIRECTIONS and words[1] not in _DIRECTIONS:
                words = [words[0], last] + words[1:-1]
    # The street type itself, where it is terminal or sits before a quadrant.
    at = len(words) - 2 if words[-1] in _DIRECTIONS and len(words) >= 4 else len(words) - 1
    if words[at] in _EXTRA_SUFFIXES and at >= 2:
        words[at] = _EXTRA_SUFFIXES[words[at]]
    return " ".join(words) + sep + tail


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Parcel records at (or within ``distance_m`` of) a point.

    A row with neither a street address nor a recorded year is dropped here,
    before the parcel is chosen. It can never be confirmed against an address
    and has no fact to contribute, and the layer is full of them where they do
    harm: right-of-way polygons (Carteret files them with the parcel number
    ``"ROW"``), unmapped remainders with every field blank (6 of 3,662 parcels
    drawn at random), and parcels whose county filed no address. Overlapping a
    real parcel, any of these would make it look ambiguous to the shared chooser
    and lose a real answer to a row that was never a candidate. Removing them is
    the sanctioned shape for this (see ``select_parcel``), and the safe one: it
    can only turn "ambiguous" into "one real parcel", and the address
    confirmation that follows is untouched.

    Rows that repeat one parcel number are NOT merged unless they repeat every
    field. Mecklenburg files some build-to-rent communities as one tax parcel
    drawn once per house: parcel ``22910115`` comes back as 19 stacked polygons
    at one point, each with its own street address, and parcel ``02756104``
    carries the same address on rows built in 2016 and in 2017. Those are
    different houses, or one house the county cannot date consistently, and the
    shared chooser is right to call them ambiguous.

    A row with an address and no year is KEPT, and so is one with a year the
    adapter will refuse (a shop). Both are real records: dropping them could make
    a neighbor the only parcel left under the point. A row with no parcel
    number is kept too — Cumberland files its newest parcels without one ("1507
    FAWN WOOD PL", built 2022), and the year is a fact with or without it.
    """
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline)
    out, seen = [], set()
    for r in rows:
        if _address_of(r) is None and (num(r.get("structyear")) or 0) <= 0:
            continue
        # One record drawn as several polygons comes back once per polygon, with
        # every requested field identical — Mecklenburg's 1861 Queens Rd W came
        # back twice and was refused as "two parcels". Rows identical in every
        # field are one record; rows that differ in ANY field (the same parcel
        # number on different houses, below) are kept apart.
        key = tuple(sorted((k, str(v)) for k, v in r.items()))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the parcel this point belongs to, or None.

    Deciding *which* parcel an address means is the dangerous part of any adapter
    — name the wrong one and the label reports a neighbor's house as observed
    fact — so the policy lives in ``_shared.select_parcel`` and is shared by every
    jurisdiction. No shared locality set is passed: the city tail is per row here
    (it is the row's own ``scity``), so ``_address_of`` trims it instead. Both
    the asked address and every candidate's go through ``_comparable`` first.
    """
    deadline = deadline_from(deadline)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        _comparable(address), lambda a: _comparable(_address_of(a)))


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row itself where possible.

    ``transfdate`` is the day NC OneMap standardized that county's file — the
    snapshot the record comes from. Counties are refreshed on their own
    schedules (the 46 here run from June 2025 to May 2026), so the date is genuinely
    per-record, and a hard-coded one would go stale silently and present old data
    at the same confidence as fresh data.
    """
    ms = num(row.get("transfdate"))
    if ms and ms > 0:
        try:
            day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return DATA_VINTAGE
        if 2000 <= day.year <= 2100:
            return f"{DATA_VINTAGE}, county file of {day.isoformat()}"
    return DATA_VINTAGE


def _says_it_is_not_a_home(row: dict) -> bool:
    """Whether the county's own use description rules out a dwelling.

    See "The use description, read only where it is unambiguous" in the module
    docstring. Silence is never a refusal: a blank description, a single-letter
    code, or one this adapter does not recognize all let the year through, the
    same way Florida treats a missing dwelling count.
    """
    desc = str(row.get("parusedesc") or "").strip().upper()
    if not desc:
        return False
    county = str(row.get("stcntyfips") or "").strip()
    if _FILLER_DESCRIPTION.get(county) == desc:
        return False
    words = set(_WORD.findall(desc))
    if words & _NO_HOME_WORDS:
        return True
    return bool(words & _NOT_A_HOME_WORDS) and not words & _HOME_WORDS


def _year_built(row: dict) -> int | None:
    """``structyear`` when it is a year somebody's home went up, otherwise None."""
    year = num(row.get("structyear"))
    if not year or year != int(year):
        return None
    year = int(year)
    if year in _PLACEHOLDER_YEARS or not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100:
        return None
    if _says_it_is_not_a_home(row):
        return None
    return year


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year_built = _year_built(row)
    # The year is the only fact this source carries, so a parcel without one
    # contributed nothing. Saying so here keeps a fact-free record out of the
    # cache; the registry drops it either way.
    if year_built is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        # The statewide schema carries no floor area, story count, wall
        # material, foundation or condition. Left empty on purpose, which lets
        # the label fall back to its modeled estimate for those rather than to
        # a guess dressed up as an observation.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What North Carolina's county tax records say is standing at this point, or None.

    ``address`` is the geocoder's matched address. It is used only to confirm the
    parcel, and the lookup still works without one wherever the coordinate lands
    inside a boundary.

    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    county has no year for. The caller then keeps whatever it had, which is the
    behavior that existed before this adapter.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("North Carolina assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
