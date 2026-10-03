#!/usr/bin/env python3
"""Massachusetts — all 351 cities and towns from MassGIS's statewide parcel layer.

The fifth adapter and the third statewide one, after Florida and Connecticut. It
exists for the reason those two do: the state has already joined its
municipalities' records into one layer, so one module answers for every home in
it.

Assessment in Massachusetts is municipal — 351 cities and towns, each with its own
board of assessors and its own CAMA vendor. What the state contributed is the
**MassGIS Digital Parcel Standard, "Level 3"**: a procurement that redrew every
community's tax map to one specification and attached a fixed extract of the
assessor's database to every parcel — the same roughly 25 columns in every town,
including year built, residential area, storeys, units and the Department of
Revenue's property-use code. Boston, the last community, was added in July 2020.
MassGIS publishes the joined result (``L3_TAXPAR_POLY_ASSESS``) as one hosted
feature layer and folds in municipal updates monthly.

  ``Massachusetts_Property_Tax_Parcels/FeatureServer/0`` — owner ``MassGIS`` on
  ArcGIS Online, 2,559,636 features, keyless, verified live 2026-10-03. 2,063,535
  of them carry a residence, apartment or mixed-residential use code (10x, 11x,
  013) and a year built; 1,440,812 are single-family houses with one.

One request, like Florida and Connecticut
-----------------------------------------
The geometry and the assessor extract are on the same feature, so the whole lookup
is one question — *which parcel is this point inside, and what does its record
say?* — asked as a containment query, and as an 80 m buffered query only when the
geocode landed off every parcel or on the wrong one.

Stacked records: the part that is Massachusetts's own
-----------------------------------------------------
The Level 3 standard links one polygon to *many* assessor records wherever the
town taxes more than one thing on one lot, and the published layer repeats the
polygon once per record. MassGIS's own words: the export "includes 'stacked'
polygons for features that link to multiple assessor records (such as
condominiums)". A Boston brownstone of five condominiums is six identical
polygons: the five units and the association's master record. A Grafton townhouse
development is one polygon carrying a dozen townhouses, each at its own street
number.

``_shared.select_parcel`` correctly refuses more than one containing record, so a
stacked point would always be refused — about a sixth of the state's homes
(363,208 condominium records alone), and most of Boston. This adapter therefore
groups records **by polygon** (``LOC_ID``) before the shared chooser sees them:

* The chooser decides *which polygon*, with its rules untouched. Two different
  polygons containing the point are still ambiguous; a buffered polygon still has
  to agree with the address, uniquely.
* Inside the chosen polygon, *which record* is decided by the address and the
  unit, never by position: only records whose own street address agrees with the
  geocoded one are kept, and a unit the reader typed must match exactly one of
  them. A group whose records do not agree on an address offers none, so it can
  never be confirmed by accident.
* Where several records remain and no unit singles one out, the polygon's **year**
  is reported only if every remaining record agrees on it — true of every unit in a
  condominium building, so it is right for whichever unit the reader lives in —
  and nothing else is. Floor area and storeys always belong to one record.

This is the District's condominium idea reached from a point instead of from a
second table, and like the District's it never guesses: no unit, no unit-level
answer. A non-dwelling record inside a stack (Boston files the condominium master
as ``995``, with the *conversion* year — 1999 on an 1890 brownstone, measured) is
dropped from the group before the vote, so it cannot veto the units' agreement.
It is dropped only inside a stack: a polygon whose only records are non-dwellings
stays a candidate, so it still counts towards "two polygons here" and still
resolves to nothing.

Which records hold a home: the Department of Revenue's use codes
-----------------------------------------------------------------
Every record carries ``USE_CODE``, the state classification every assessor must
apply (M.G.L. c.59 §2A; DOR Bureau of Local Assessment, *Property Type
Classification Codes*, rev. April 2019,
``mass.gov/doc/property-type-classification-codes-non-arms-length-codes-and-sales-report-spreadsheet-specifications``).
The code is three digits; the layer's column holds four characters, and towns use
the fourth for a local subdivision — ``1010`` (749,427 records), ``1021``,
``102U``. So the first three characters are read as the DOR code, which is how
the DOR's own guidance says local codes must be built ("maintain the overall
pattern of the coding system", DLS Assessment Administration ch. 4 §2.2.4).

Only codes whose meaning the DOR booklet documents are acted on:

* **A home is here**: 101 single family, 102 condominium, 103 mobile home, 104
  two-family, 105 three-family, 109 multiple houses on one parcel, 111/112
  apartments, 114 affordable housing, 121–125 non-transient group quarters, the
  exempt housing codes 945, 959, 961 and 970, and any multiple-use code (leading
  ``0``) one of whose two class digits is ``1``, residential — the booklet's own
  example of 021 is "a single-family house with substantial acreage designated
  open space".
* **No home is here**: 106 accessory land with improvement ("garage, etc."), 130–
  132 vacant residential land, classes 2 (open space), 3 (commercial — the statute
  excludes hotels from residential, and a building with flats over a shop must be
  coded 013 or 031 instead), 4 (industrial), 5 (personal property) and 6–8
  (Chapter 61/61A/61B land), multiple-use codes with no residential digit, and
  the exempt codes whose description is a vacant lot or a use nobody lives in
  (see ``_NO_HOME_EXEMPT``). A year built read from these would describe a
  building nobody lives in while carrying the ``observed`` tag, so it is refused.
* **Anything else** — a code the DOR leaves "intentionally blank" that a town
  uses anyway (108 is used 8,226 times, mostly by Boston), a local code like
  Cambridge's 199, a malformed one — says nothing either way. The year is
  allowed through, exactly as Florida lets a missing dwelling count through, and
  the floor area is refused because it needs a positive statement of one home.

``UNITS`` would be the obvious dwelling count and cannot be one: the standard
defines it as living units "and also other units, for example, commercial condos
and storage units", and towns write **0** for "not recorded" — 619,056
single-family records carry ``UNITS = 0``. So a zero is never read as "no
dwelling". A value of 2 or more still refuses the floor area, because it is a
positive statement that the record covers more than one unit.

The floor area, and when it describes one home
----------------------------------------------
``RES_AREA`` is defined by the standard as applying "primarily to 1, 2 & 3 family
dwellings ... or residential condominiums based on deeded unit areas". It is
reported only where the record is one dwelling:

* a single-family record, coded exactly ``101`` (or ``1010``, the padded form), not
  claiming two or more units; or
* a condominium record coded exactly ``102``/``1020`` whose unit the reader named
  and the record matches — or, where the record carries no unit designator at all,
  whose street address no other record on the same polygon shares, which is how a
  townhouse condominium (one house number per home) identifies a dwelling.

Locally suffixed codes (``1013``, ``1021``, ``102U``…) keep their year and lose
their area: the suffix is a town's own subdivision of the class with no published
meaning, and some vendors use it for exactly the cases (an in-law apartment, a
parking unit) that make the area wrong. That costs 0.9% of single-family records.
Never divided by a unit count, for the reason ``fl.py`` gives.

The standard is candid that the measurement basis varies by vendor — "gross
square-feet, adjusted gross square-feet, or finished area" — so this is the
assessor's residential area, not a harmonised living area. Florida's and
Connecticut's columns carry the same caveat in practice; Massachusetts is the one
that says so.

Storeys: a column three towns use as a code
-------------------------------------------
``STORIES`` is a story height ("1.5", "1.75", "2A" for Patriot's attic stories)
on 348 of 351 towns. Medfield, Upton and Dartmouth write a code table into it
instead — Medfield's single-family houses are "7" (1,698), "8" (472) and "14"
(278) storeys — measured as the only towns where whole values of 5 or more exceed
1% of single-family records (70%, 28% and 2.3%; the next is 0.7%). Those three
towns report no storeys at all, since their "1" and "2" are codes too. Elsewhere
only a whole number from 1 to 4 on a one-dwelling single-family record is
reported; a half storey is not rounded into one, the same call Cook and the
District make, and a condominium's storey count is never reported because it can
be the unit's or the building's.

What is not read
----------------
``STYLE`` is free text per town: "COLONIAL", "Cape Cod", "CONDO-GRDN",
"7:RANCH SLAB". It is an architectural style, not a wall material, so nothing in
it maps to the label's ``construction`` vocabulary and it is not requested. There
is no foundation or condition column in the standard. ``BLD_AREA`` is the
building's gross area, which "applies primarily to apartment buildings and
commercial" property, so it is never a home's area and is not requested either.

Terms of use
------------
MassGIS: "All MassGIS data available for download from our website are public
records ... MassGIS data may be freely redistributed and integrated into
commercial products and applications, including any derivative works", with a
liability disclaimer and a requested credit line ("Learn about MassGIS data",
``mass.gov/info-details/learn-about-massgis-data``; the MassGIS FAQ calls its data
"public domain ... can be used by anyone for any purpose"). The item's licence
note says only that parcel mapping is not an authoritative boundary record, and
the data page that the assessing extract is an "as is" copy "with errors and
discrepancies". Verdict: clear for live query and cache, and the most permissive
terms in the registry. The query-and-cache-live posture is kept anyway, as every
adapter keeps it, and the credit travels in ``ATTRIBUTION``.

Why this service needs its own clock
------------------------------------
Measured from this environment over 220 requests at real residential rooftops
drawn at random from the layer itself, and a second sweep of one random
single-family home in each of the 351 towns (new connection per request):

  ===================================  ======  ======  ======  ======  ======
  request                              median     p90     p95     p99     max
  ===================================  ======  ======  ======  ======  ======
  "which parcel is this dot inside?"    0.13 s  0.19 s  0.26 s  0.64 s  2.55 s
  "what is within 80 m of this dot?"    0.14 s  0.23 s  0.40 s  4.29 s  8.19 s
  351-town sweep, containment           0.49 s  0.59 s  0.64 s  1.49 s  5.62 s
  351-town sweep, 80 m buffer           0.50 s  0.61 s  0.81 s  2.91 s  5.07 s
  ===================================  ======  ======  ======  ======  ======

The typical lookup is fast. The tail is not random: it is the southeast. Buffered
queries in Dartmouth repeat at 3.3–10.6 s at the same point, and Fairhaven,
Acushnet and New Bedford were the slowest buffers in the sweep (3.6–5.1 s);
containment at the same points answers in 0.1–0.3 s. Under the shared one-second
read slice 6 of the 220 buffered queries were cut off, nearly all in Bristol
County — and a cut-off does not look like a timeout to anyone reading the label,
it looks like a county with no records.

So ``READ_SLICE_S`` is 5 seconds, which clears every buffered query measured
except the slowest repeats in Dartmouth, and ``LOOKUP_TIMEOUT`` is 6.5 seconds,
which holds a p99 containment plus a five-second buffer. The two halves of a
socket timeout add up, so the number that has to fit the host's allowance is
6.5 + 5 = 11.5 s, inside the 12 s ``config.UPSTREAM_HOST_BUDGET`` allows any one
service; a test pins the sum against that constant. The slowest Dartmouth buffers
(6–10 s) cannot be covered inside that allowance and are left to fail open.

Response bodies are small — median 3.5 KB, largest buffered response 131 KB (500
records, beside Boston's Millennium Tower) — so the slice is the service
thinking, not bytes moving. The layer's ``maxRecordCount`` is 2,000, and a
truncated buffer would silently remove candidates, which can turn "two parcels at
this address" into "one" — the wrong-house failure the chooser exists to prevent.
So a response flagged ``exceededTransferLimit`` is refused rather than read; see
``_query``.

What the adapter is worth, end to end
-------------------------------------
260 homes drawn at random from the layer itself (random object ids, any
dwelling use code, 147 towns), typed as the roll spells them — with the unit
where the record has one — geocoded through the Census matcher exactly as the
product does, then looked up:

* 240 geocoded, all 240 routed to a Massachusetts county code.
* **197 resolved**: 196 with the exact year built, and all 155 floor areas and
  all 106 storey counts reported exactly equal to the record's.
* **1 named a different parcel, and it is the geocoder's**: the matcher turned
  "21 LONGWOOD AVE, WAREHAM" into "21 LINWOOD AVE" — another street, 3 km
  away — and the adapter correctly returned 21 Linwood Ave. Nothing inside an
  adapter can see this, because it is only ever handed the matched address; it
  is a fault one layer up, in ``assessor_address``.
* An earlier run had a second: a Cambridge unit answered by its building's
  locally coded master record (same polygon, same year, different record). That
  is what the "documented home codes first" rule in ``_parcels`` closes; see the
  test pinning it.

The stacked-record path is the reason condominiums resolve at all: **17 of the
24 sampled condominium units resolved, every one of them from a stacked
polygon**, which ``select_parcel`` alone refuses — 11 with the unit's own area,
4 with only the building's year. So it is worth its code, measured.

The 43 that did not resolve: 31 where the geocoder put the point more than 80 m
from the home's parcel (large rural lots, mostly), 9 whose roll address the
comparison cannot join to the matcher's ("162 -1 MYRTLE ST", "SEA MEADOW" against
"SEAMEADOW", "MYSTIC VLLY PY", "200 202 SOUTH ST"), 2 where two polygons carry
the same address (a Weymouth house and a vacant Holbrook lot across the town
line; two Cambridge parcels at 132 Hampshire St) and 1 where the only agreeing
record had a range number that does not parse. The shared chooser declining to
guess in every case.

Privacy, and why the field list is short
----------------------------------------
This layer has 50 columns, among them ``OWNER1``, ``OWN_ADDR``, ``OWN_CITY``,
``OWN_STATE``, ``OWN_ZIP``, ``OWN_CO``, the last sale's date, price and deed book
and page, and every assessed value. None of it is an input to any dimension of
the label. Thirteen columns are requested by name and the other 37 are never
fetched. Nothing from this source is written into the repository.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, same_address, select_parcel,
    unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# All 14 Massachusetts counties: the odd numbers 25001 (Barnstable) to 25027
# (Worcester). Massachusetts abolished eight of its county governments between
# 1997 and 2000, but the counties survive as Census county-equivalents and the
# geocoder still returns them — and assessment was never county-level here anyway,
# so the code only routes. Written as a rule; a test checks it against the
# repository's own county table.
COUNTY_FIPS = frozenset(f"25{n:03d}" for n in range(1, 28, 2))

NAME = "MassGIS"
ATTRIBUTION = ("Massachusetts municipal assessors via MassGIS (Bureau of Geographic "
               "Information), Commonwealth of Massachusetts EOTSS — Level 3 "
               "parcels, keyless")
DATA_VINTAGE = "MassGIS Level 3 standardized assessor parcels"

PARCEL_URL = ("https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services"
              "/Massachusetts_Property_Tax_Parcels/FeatureServer/0/query")

#: How long this service may go quiet before the silence is read as a stall, and
#: the budget for a whole Massachusetts lookup. Both measured; see "Why this
#: service needs its own clock" in the module docstring. Named as Florida and
#: Connecticut name theirs, so neither can be mistaken for the shared TIMEOUT.
READ_SLICE_S = 5.0
LOOKUP_TIMEOUT = 6.5

# What the label scores, plus what decides which record and whether its area is
# one home's. Never STYLE, BLD_AREA, owner, sale or value columns — see "What is
# not read" and "Privacy" in the module docstring.
_FIELDS = ("LOC_ID,PROP_ID,TOWN_ID,USE_CODE,SITE_ADDR,ADDR_NUM,FULL_STR,LOCATION,"
           "YEAR_BUILT,RES_AREA,UNITS,STORIES,FY")

# --- the Department of Revenue's codes ------------------------------------------
#
# Every code below is quoted from the DOR booklet cited in the module docstring.
_HOME_CODES = frozenset({
    "101",   # Single Family
    "102",   # Condominium
    "103",   # Mobile Home
    "104",   # Two-Family
    "105",   # Three-Family
    "109",   # Multiple Houses on one parcel
    "111",   # Apartments, Four to Eight Units
    "112",   # Apartments, More than Eight Units
    "114",   # Affordable Housing Units
    "121",   # Rooming and Boarding Houses
    "122",   # Fraternity and Sorority Houses
    "123",   # Residence Halls or Dormitories
    "124",   # Rectories, Convents, Monasteries
    "125",   # Other Congregate Housing
    "945",   # Educational Private — Affiliated Housing
    "959",   # Charitable — Housing, Other
    "961",   # Religious — Rectory or Parsonage
    "970",   # Housing Authority
})
_NO_HOME_RESIDENTIAL = frozenset({
    "106",   # Accessory Land with Improvement — garage, etc.
    "130",   # Vacant land in a residential zone — Developable
    "131",   # — Potentially Developable
    "132",   # — Undevelopable
})
# Exempt (class 9) is a statement about the OWNER, not the use, so the class as a
# whole says nothing about whether anyone lives there — 970 is a housing
# authority. Only the codes whose own description is a vacant lot or a use nobody
# lives in are read as "no home".
_NO_HOME_EXEMPT = frozenset({
    "924",                                   # Mass Highway Department
    "930", "932", "933", "936", "938",       # municipal, vacant
    "946",                                   # educational private, vacant
    "950",                                   # charitable, vacant conservation
    "952",                                   # auxiliary use (storage, barns)
    "953",                                   # cemeteries
    "955", "956",                            # hospitals; libraries, museums
    "960",                                   # church, mosque, synagogue, temple
    "971", "972",                            # utility, transportation authority
    "973", "974", "975",                     # authorities, vacant
    "980", "982", "988", "991",              # other towns / county, vacant
    "995",                                   # other, open space
    "996",                                   # non-taxable condominium common land
})

# The exact codes that state "one single-family house" and "one condominium
# unit". The padded four-character forms are included because "1010" is how the
# largest CAMA vendors write 101 (749,427 records); any other fourth character is
# a town's own subdivision with no published meaning.
_SINGLE_FAMILY = frozenset({"101", "1010"})
_CONDOMINIUM = frozenset({"102", "1020"})

#: MassGIS TOWN_IDs whose STORIES column holds a code table rather than a count:
#: Medfield (175), Upton (303), Dartmouth (72). Measured as the only towns where
#: whole values of five or more are over 1% of single-family records.
_STOREY_CODE_TOWNS = frozenset({72, 175, 303})
_MAX_STOREYS = 4


def _dor_code(raw) -> str | None:
    """The three-digit DOR code at the front of ``USE_CODE``, or None."""
    code = str(raw or "").strip().upper()
    if len(code) not in (3, 4) or not code[:3].isdigit():
        return None
    return code[:3]


def _says_a_home_is_here(row: dict) -> bool | None:
    """True, False, or None for "the code does not say".

    False only for a code whose DOR description rules a dwelling out; see the
    module docstring for the list and why ``UNITS`` cannot do this job.
    """
    code = _dor_code(row.get("USE_CODE"))
    if code is None:
        return None
    if code in _HOME_CODES:
        return True
    if code[0] == "0":
        # Multiple use: the second and third digits are the two classes present.
        # A residential digit means somebody lives there; none means nobody does.
        return "1" in code[1:]
    if code in _NO_HOME_RESIDENTIAL or code in _NO_HOME_EXEMPT:
        return False
    if code[0] in "2345678":
        return False
    return None


# --- addresses and units --------------------------------------------------------
#
# Spellings this state's assessors use that the Census matcher never returns, each
# rewritten on the ROW side only, before the shared comparison sees it. Every
# rewrite turns one spelling of a street into the matcher's spelling of the SAME
# street; none can make two different streets equal, and a rewrite the matcher
# does not share can only produce a refusal, the safe direction.
#
# * Street types the shared table does not know: "WY" (8,158 residential
#   records), "TERR" (3,596), "CI" (3,322) and "CR" (6,674). "CI" and "CR" are not
#   USPS abbreviations for anything; the matcher returned "CIR" for every one in
#   the verification sample ("59 BOUNDARY CR" → "59 BOUNDARY CIR"). Forms that do
#   stand for two types ("TR" terrace/trail, "PK" park/pike, "LA") are left alone.
# * Directionals. USPS standardisation abbreviates a leading or trailing
#   directional, and the matcher does — "1114 N MAIN ST" for the roll's "1114 NO
#   MAIN ST", "624 BOSTON POST RD E" for "...RD EAST". A directional is rewritten
#   only where it is not itself the street's name: "NORTH ST" stays as it is.
# * Ordinal words before a bare street type: the matcher writes "15 5TH ST" for
#   the roll's "15 FIFTH ST".
_LOCAL_SUFFIXES = {"wy": "WAY", "terr": "TER", "ci": "CIR", "cr": "CIR"}
_DIRECTIONAL_WORDS = {"north": "N", "south": "S", "east": "E", "west": "W",
                      "no": "N", "no.": "N", "so": "S", "so.": "S"}
_ORDINALS = {"first": "1ST", "second": "2ND", "third": "3RD", "fourth": "4TH",
             "fifth": "5TH", "sixth": "6TH", "seventh": "7TH", "eighth": "8TH",
             "ninth": "9TH", "tenth": "10TH"}
# Barnstable writes its villages into the street name — "MAIN ST (HYANNIS)", 284
# residential records — which is locality, not street.
_PAREN_TAIL_RE = re.compile(r"\s*\([^)]*\)\s*$")
_LEADING_NUMBER_RE = re.compile(r"^\s*(\d+)")
# The secondary-location column holds units ("3", "#4", "12-1", "A-2", "UNIT 5")
# and also "REAR", "SIDE" and "BASEMENT". A unit must carry a digit or be at most
# two letters, which keeps every unit form seen and none of the words.
_LOCATION_UNIT_RE = re.compile(
    r"^(?:#|UNIT|APT\.?|STE\.?|SUITE|NO\.?)?\s*#?\s*([A-Z0-9][A-Z0-9\-]*)$")


def _normalise(raw: str | None) -> str:
    """A row's street address in the Census matcher's spelling; see above.

    Only the street part before any unit marker is touched, and only when it
    starts with a house number — anything else is returned whitespace-collapsed
    and otherwise as it was, for ``address_key`` to accept or refuse.
    """
    text = _PAREN_TAIL_RE.sub("", " ".join(str(raw or "").split()))
    parts = text.split(" ")
    if len(parts) < 3 or not parts[0].isdigit():
        return text
    cut = next((i for i, p in enumerate(parts) if p.startswith("#")
                or p.lower() in _shared.UNIT_MARKERS), len(parts))
    number, street, tail = parts[0], parts[1:cut], parts[cut:]
    if street and street[-1].lower() in _LOCAL_SUFFIXES:
        street[-1] = _LOCAL_SUFFIXES[street[-1].lower()]
    is_type = [p.lower() in _shared.SUFFIXES for p in street]
    if (len(street) >= 3 and street[-1].lower() in _DIRECTIONAL_WORDS
            and is_type[-2]):
        street[-1] = _DIRECTIONAL_WORDS[street[-1].lower()]
    # Leading: only when a real name follows it, so "NORTH ST" and "EAST AVE"
    # keep the directional as their name.
    if (len(street) >= 2 and street[0].lower() in _DIRECTIONAL_WORDS
            and not all(t for t in is_type[1:])):
        street[0] = _DIRECTIONAL_WORDS[street[0].lower()]
    if len(street) == 2 and street[0].lower() in _ORDINALS and is_type[1]:
        street[0] = _ORDINALS[street[0].lower()]
    return " ".join([number, *street, *tail])


def _structured_address(row: dict) -> str | None:
    """``ADDR_NUM FULL_STR`` where the number is a plain house number."""
    number = str(row.get("ADDR_NUM") or "").strip()
    street = str(row.get("FULL_STR") or "").strip()
    if not (number.isdigit() and street):
        return None
    return _normalise(f"{number} {street}")


def _address_of(row: dict) -> str | None:
    """This record's street address, or None where it does not agree on one.

    Two sources, both the town's own: ``ADDR_NUM``/``FULL_STR``, which the
    standard has vendors split out, and ``SITE_ADDR``, "the complete original site
    address as listed in the tax record". The split form is preferred because the
    original is free text — "1  LENOX STREET  #203", "3 -1 GRANT PL", "2 A ARBOR
    WY" — and the split form is checked with the same ``address_key`` the
    comparison runs, so neither is offered unless it parses.

    Where both parse and name different buildings, neither is offered, the rule
    Connecticut established: a record that contradicts itself has no address it
    can be confirmed against.
    """
    structured = _structured_address(row)
    site = _normalise(row.get("SITE_ADDR"))
    # The shared comparison, not a looser local one: it tolerates one side
    # omitting the street type and refuses two different ones, so "24 MAIN ST"
    # against "24 MAIN AVE" is a contradiction here exactly as it is everywhere
    # else. Comparing only the number and name tokens would let that record
    # confirm a parcel as either building.
    if (address_key(structured) and address_key(site)
            and not same_address(structured, site)):
        return None
    for candidate in (structured, site):
        if candidate and address_key(candidate):
            return candidate
    return None


def _row_unit(row: dict) -> str | None:
    """The unit this record names, or None."""
    location = " ".join(str(row.get("LOCATION") or "").upper().split())
    m = _LOCATION_UNIT_RE.match(location)
    if m:
        token = m.group(1)
        if any(c.isdigit() for c in token) or len(token) <= 2:
            return token
    return unit_of(row.get("SITE_ADDR"))


def _norm_unit(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def _same_unit(a, b) -> bool:
    """Case and punctuation aside, the same unit. Leading zeros stay significant —
    unit 01 and unit 1 can both exist — the District's rule."""
    return bool(_norm_unit(a)) and _norm_unit(a) == _norm_unit(b)


def _house_number(row: dict) -> str | None:
    for raw in (row.get("ADDR_NUM"), row.get("SITE_ADDR")):
        m = _LEADING_NUMBER_RE.match(str(raw or ""))
        if m:
            return m.group(1)
    return None


# --- fetching and grouping ------------------------------------------------------


def _query(lat: float, lon: float, distance_m: float, *, deadline: float) -> list[dict]:
    """Record attributes at (or within ``distance_m`` of) a point.

    The same request ``_shared.arcgis_parcels`` sends, made here so the
    response's ``exceededTransferLimit`` is checked by this module as well as by
    the transport. This layer stops at 2,000 records, and a buffer beside a
    Boston tower already returns 500. A truncated list can only lose candidates —
    and losing one of two parcels at one address turns "ambiguous" into a
    confident wrong answer — so a truncated response raises, which the lookup
    treats as no answer.

    ``_shared.get_json`` now raises ``TruncatedResponse`` on that flag itself, so
    the check below is belt and braces: it keeps this adapter's refusal pinned by
    its own test, whatever the transport underneath does.
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
        raise RuntimeError("MassGIS response truncated at the layer's record limit")
    return [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]


def _parcels(lat: float, lon: float, distance_m: float = 0,
             address: str | None = None, *, deadline: float) -> list[dict]:
    """One candidate per polygon, each carrying the records stacked on it.

    A record with no ``PROP_ID`` has no assessor record behind it — the layer
    includes polygons the town never linked to its roll — and is dropped, the
    placeholder rule Florida set.

    Within a polygon carrying more than one record:

    * only records whose DOR code positively says "a home" are kept where there
      are any. A condominium master record is not anyone's home and must not
      veto the units' agreement on a year — nor stand in for them: Cambridge
      files its masters under a local 199, and the master for 35 Washburn Ave
      says 1916 where its three units say 1873. Measured in the verification
      run, that master answered for a unit whose own address did not parse;
      with this rule it cannot. Records whose code says nothing are kept only
      where no record says "a home", and records that rule one out only where
      nothing else is on the polygon;
    * when an address is in hand, only records whose own address agrees with it
      are kept, unless none does — then the whole group stays, offers no common
      address, and fails confirmation as it should.

    Polygons are never merged or dropped here, so the number of candidates the
    shared chooser counts is exactly the number of distinct polygons: two
    overlapping polygons are still two.
    """
    groups: dict[str, list[dict]] = {}
    for row in _query(lat, lon, distance_m, deadline=deadline):
        prop = str(row.get("PROP_ID") or "").strip()
        if not prop:
            continue
        key = str(row.get("LOC_ID") or "").strip() or f"prop:{prop}"
        groups.setdefault(key, []).append(row)

    candidates = []
    for loc_id, rows in groups.items():
        members = rows
        if len(rows) > 1:
            homes = [r for r in rows if _says_a_home_is_here(r) is True]
            silent = [r for r in rows if _says_a_home_is_here(r) is None]
            members = homes or silent or rows
            if address:
                agreeing = [r for r in members
                            if same_address(address, _address_of(r))]
                members = agreeing or members
        candidates.append({"loc_id": loc_id, "members": members, "all": rows})
    return candidates


def _candidate_address(candidate: dict) -> str | None:
    """The street address every record in the candidate shares, or None."""
    addresses = [_address_of(r) for r in candidate["members"]]
    if not addresses or any(address_key(a) is None for a in addresses):
        return None
    # Every pair must agree under the shared rule — the same reason as in
    # _address_of: "24 MAIN ST" and "24 MAIN AVE" are two buildings even though
    # each agrees with a bare "24 MAIN".
    if not all(same_address(a, b) for i, a in enumerate(addresses)
               for b in addresses[i + 1:]):
        return None
    # The most specific spelling: one that carries its street type, so the
    # chooser compares against that rather than against a bare name.
    return next((a for a in addresses if address_key(a)[2]), addresses[0])


def _candidate_at(lat: float, lon: float, address: str | None = None,
                  *, deadline: float | None = None) -> dict | None:
    """The polygon this point belongs to, chosen by the shared policy."""
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, address, deadline=deadline),
        address, _candidate_address)


# --- reading a record -----------------------------------------------------------


def _year(row: dict) -> int | None:
    year = num(row.get("YEAR_BUILT"))
    # 0 is a town's "not recorded", not the year zero.
    return int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None


def _claims_several_units(row: dict) -> bool:
    units = num(row.get("UNITS"))
    return units is not None and units >= 2


def _area(row: dict, *, unit_matched: bool, siblings: list[dict]) -> float | None:
    """``RES_AREA`` where it is one dwelling's area; see the module docstring."""
    area = num(row.get("RES_AREA"))
    if area is None or area <= 0 or _claims_several_units(row):
        return None
    code = str(row.get("USE_CODE") or "").strip().upper()
    if code in _SINGLE_FAMILY:
        return area
    if code in _CONDOMINIUM:
        if unit_matched:
            return area
        if _row_unit(row) is not None:
            return None            # one unit of several; which one is unknown
        number = _house_number(row)
        shared = [s for s in siblings
                  if s is not row and number and _house_number(s) == number]
        return None if (number is None or shared) else area
    return None


def _stories(row: dict) -> int | None:
    """A whole storey count for a one-dwelling single-family record, or None."""
    if str(row.get("USE_CODE") or "").strip().upper() not in _SINGLE_FAMILY:
        return None
    if _claims_several_units(row) or num(row.get("TOWN_ID")) in _STOREY_CODE_TOWNS:
        return None
    v = num(str(row.get("STORIES") or "").strip())
    if v is None or not float(v).is_integer() or not 1 <= v <= _MAX_STOREYS:
        return None
    return int(v)


def _vintage(rows: list[dict]) -> str:
    """Dated from the records: ``FY`` is the fiscal year of the assessment.

    Towns deliver on their own schedules, so the year is per record — FY2026 on
    1,505,063 features, FY2018 on 8,315 — and a hard-coded year would present old
    data at the same confidence as fresh. Stated only where every record agrees.
    """
    years = {int(y) for y in (num(r.get("FY")) for r in rows) if y and 1900 <= y <= 2100}
    return f"{DATA_VINTAGE}, FY{years.pop()} assessment" if len(years) == 1 \
        else DATA_VINTAGE


def _row_record(row: dict, *, unit_matched: bool = False,
                siblings: list[dict] = ()) -> AssessorRecord | None:
    if _says_a_home_is_here(row) is False:
        return None
    year_built = _year(row)
    sqft = _area(row, unit_matched=unit_matched, siblings=list(siblings))
    stories = _stories(row)
    if year_built is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage([row]),
        parcel_id=str(row.get("PROP_ID") or "").strip() or None,
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        # No wall material, foundation or condition in the standard; STYLE is an
        # architectural style. Left empty on purpose — see the module docstring.
    )


def _building_record(candidate: dict) -> AssessorRecord | None:
    """The polygon's year, when every record left on it agrees, and nothing else."""
    members = [r for r in candidate["members"] if _says_a_home_is_here(r) is not False]
    if not members:
        return None
    years = {_year(r) for r in members} - {None}
    if len(years) != 1:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(members),
        parcel_id=candidate["loc_id"],
        year_built=years.pop(),
    )


def _resolve(candidate: dict, address: str | None) -> AssessorRecord | None:
    """Which record on the chosen polygon is the reader's home."""
    members = candidate["members"]
    unit = unit_of(address)
    if len(members) == 1:
        row = members[0]
        return _row_record(row, unit_matched=bool(unit) and _same_unit(unit, _row_unit(row)),
                           siblings=candidate["all"])
    if unit:
        hits = [r for r in members if _same_unit(unit, _row_unit(r))]
        if len(hits) == 1:
            return _row_record(hits[0], unit_matched=True, siblings=candidate["all"])
    return _building_record(candidate)


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    candidate = _candidate_at(lat, lon, address)
    if not candidate:
        return None
    return _resolve(candidate, address)


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Massachusetts's municipal rolls say is standing at this point, or None.

    ``address`` is the geocoder's matched address, carrying the reader's unit
    where they typed one (``_shared.with_unit``). It confirms the parcel, and the
    unit picks the record on a stacked condominium polygon.

    Fails open on everything — a timeout, a 500, a truncated response, a renamed
    column, a parcel with no record.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Massachusetts assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
