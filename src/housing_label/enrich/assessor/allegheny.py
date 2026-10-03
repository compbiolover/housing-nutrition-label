#!/usr/bin/env python3
"""Allegheny County, Pennsylvania — the county's assessment roll, through WPRDC (two hops).

Allegheny County (Pittsburgh and its 129 other municipalities, ~607,000 homes) is
the largest single county in Pennsylvania outside Philadelphia, and the one whose
assessment roll is published under the most permissive terms of any adapter in
this package: Creative Commons Zero. The Office of Property Assessments writes the
roll; the Western Pennsylvania Regional Data Center (WPRDC, run by the University
of Pittsburgh) republishes it monthly as a CKAN datastore table that answers
keyless queries.

The chain, verified live
------------------------
The roll is a table keyed on the 16-character parcel id, with no geometry, so a
point takes two hops — the shape Cook County and the District have:

  1. **Point → PIN.** ``OPENDATA/Parcels/MapServer/0`` on the county's own GIS
     server, 580,039 polygons, point-in-polygon at 4326. It carries the ``PIN``
     and nothing else of use: no address, no owner.
  2. **PIN → record.** WPRDC's "Allegheny County Property Assessments" datastore
     (resource ``9a1c60bd-…``, the "for downloads" copy: 585,005 rows, rebuilt
     monthly — the current file on 2026-10-02 from the roll as of 2026-09-30),
     ``datastore_search`` filtered on ``PARID``, which is the same 16 characters
     as ``PIN``.

Because the parcel layer carries no address, the address that confirms a parcel
(``_shared.select_parcel``) only exists after hop 2 — so hop 2 runs for *every*
candidate the point or the 80 m buffer turns up, not just for the winner. CKAN
accepts a list as a filter value (``{"PARID": [...]}``, an ``IN``), so the
candidates go in one request rather than one each — see "Two things WPRDC's
firewall refuses" for why "one" means "one per fifty".

Two things WPRDC's firewall refuses
-----------------------------------
WPRDC sits behind a CloudFront web-application firewall, and it shapes this
adapter in two measured ways:

* **``datastore_search_sql`` is unusable.** Any statement with a ``WHERE`` or a
  ``count()`` is refused with HTTP 403, from every User-Agent tried, over GET and
  POST; a bare ``SELECT ... LIMIT 1`` passes. So the adapter uses
  ``datastore_search``'s structured ``filters`` instead, which the firewall lets
  through.
* **A query string longer than ~2,040 bytes is refused**, again with 403. Bisected
  live with this adapter's own field list: 70 parcel ids (a 2,092-byte URL)
  pass, 71 (2,117 bytes) do not; with a one-field list 76 ids at 2,055 bytes pass,
  so it is the length, not the count. Each id costs 25 bytes URL-encoded, so the
  candidates are sent in batches of ``_BATCH`` = 50 (~1.6 KB), with headroom for a
  longer field list; a test pins a full batch's encoded length under the limit.

An 80 m buffer holds a median of 29 parcels and a p95 of 65 (45 random
residential points), so a buffered lookup costs one or two batches. Around a
condominium unit it holds more, because every unit is a tile: median 76, p95 192,
maximum 332 at 95 random units' own tiles. Past ``_MAX_CANDIDATES`` (400, eight
batches, above every one of those 95) the lookup stops and fails open rather than
spend the budget: it raises ``TruncatedResponse``, exactly as an ArcGIS page
truncated at its transfer limit does, so nothing is cached. The first cap tried,
300, turned away 320 Fort Duquesne Blvd (325 parcels within 80 m) in the
verification below.

Condominiums: one parcel per unit, drawn inside the building
------------------------------------------------------------
Allegheny files a condominium the way Philadelphia and the District do — each unit
is its own parcel with its own year, area and id (``0001G00224110100`` is unit 1101
of First Side) — but draws it differently from both. Every unit gets a small polygon
of its own (a schematic tile of 150–250 sq ft, not a floor plan) laid out
*inside* the building's footprint, and the condominium's common-property parcel
(``0001G00224000000``, "CONDOMINIUM COMMON PROPERTY", house number 0) covers the
whole lot underneath them. Measured on First Side: 80 unit tiles with 80 distinct
extents, and the tile under the centroid of unit 1101's own tile is unit 1101 plus
the common parcel.

So a geocode in a condominium building lands on the common parcel and on *one
arbitrary unit's* tile. Two things follow:

* **The common parcel is dropped before the choice**, as Florida drops its
  placeholder polygons. It is not a home (``_says_a_home_is_here``), and left in,
  it would make every condominium point ambiguous — ``select_parcel`` refuses more
  than one containing parcel outright and never reaches the buffer.
* **The unit tile under the point is never accepted on the building's address
  alone.** Candidates are narrowed by the unit the reader typed (carried past the
  geocoder by ``_shared.with_unit``), Philadelphia's rule exactly: where the
  reader gave a unit and that unit exists at their address, only those rows are
  offered; otherwise only rows with **no** unit are. A unit tile under the point
  that is not the reader's unit therefore drops out, the search widens to the
  80 m buffer, and the reader's own unit is found among the building's tiles there.
  A condominium address with no unit has no candidate and no answer — answering
  with whichever tile the geocode happened to land on would be the confident
  guess the selection policy exists to refuse.

That rule also covers a lookup with no address at all (the label scored from bare
coordinates): a unit tile under the point is not offered without a typed unit to
match, so the arbitrary unit cannot be returned by containment alone.

9,512 of the 17,368 condominium records carry no unit — garden and townhouse-style
complexes where every unit has its own house number ("305 GLENWOOD DR"). They
behave exactly as houses do, confirmed on the house number, and are not affected.

``PROPERTYUNIT`` writes the designator with a marker — "UNIT 1204" (7,893 rows),
"APT 1103" (690), "STE 200" (261), "TRLR 68" (55), "LOT 7" (12) — which is stripped
before comparing, so a reader's "#1204" matches "UNIT 1204". Markers that name
something other than a dwelling unit are kept as part of the designator and so
never match a typed unit: "REAR" (521, a second house behind the first), "BLDG B"
(69), "GAR 1" (10). Designators compare on letters and digits only ("3-B" = "3B"),
leading zeros kept significant, as the District's and Philadelphia's do.

A condominium unit's ``FINISHEDLIVINGAREA`` is the unit's own (1,465 sq ft for
First Side unit 1101; a 400 sq ft studio at The Grenadier), so — like the
District's ``LIVING_GBA`` and Philadelphia's livable area — it is reported. Its
``STORIES`` is not: 3,919 of 3,967 high-rise ("CONDO HR") units say 1, which
describes the flat, not the tower the label's geometry model would read it as.

Ranges: "1622-1624 FORBES AVE"
------------------------------
7,187 records that carry a year built (1.6%) are filed under a house-number range,
the low number in ``PROPERTYHOUSENUM`` and the rest in ``PROPERTYFRACTION``
("-1624"). They are mostly two- to four-family buildings (6,496 of them).
``_shared.address_key`` cannot anchor on a range, so such a row is offered under
the reader's own number when it falls inside the range on the same side of the
street (same parity), and under its low number otherwise — Philadelphia's rule,
restated here because it lives in that module rather than in ``_shared`` (see the
report). Any other fraction is kept beside the number ("123 1/2 MAIN ST",
"123 A MAIN ST"), where it can never match a reader's plain "123 MAIN ST": 123½
and 123A are separate buildings from 123, and refusing is the safe answer.

What the label gets, and what it is refused
-------------------------------------------
Field definitions are quoted from WPRDC's data dictionary for this dataset
(``data-dictionary-open-data.csv``, resource ``c665470c-…``). Every
characteristic field is a "Dwelling" field: the county's residential card, "the
main dwelling".

**Year built** — ``YEARBLT``, "the original date of construction"; there is no
effective-year column to confuse it with. Missing values are SQL NULL, never 0
(no row in the 2026-09-30 file carries 0), but 0 is refused anyway. Range
1755–2026.

**Living area** — ``FINISHEDLIVINGAREA``, "finished living area, as measured from
the outside of the structure". Reported only where the record is one dwelling
(``_ONE_DWELLING_USES``: single family, townhouse, rowhouse, condominium unit,
mobile home) and the card shown is card 1. Two-, three- and four-family buildings
describe the whole building and are refused, never divided. ``CARDNUMBER`` is
"the number of the building being shown (which is usually the main dwelling)" on
a parcel with more than one; a card other than 1, or none (1,332 dwelling rows),
is *usually* the main dwelling, and "usually" is not enough to tag an area
``observed``.

**Stories** — ``STORIES``, "the story height of the main dwelling. Attics are not
included." Whole numbers only: a fractional height "denotes an upper story where
part of the living space is less than full height", and the label's field is a
whole number, so 1.5 and 2.5 (31,346 rows) are not rounded into one — the
District's and Cook's rule. Same one-dwelling and card-1 conditions as the area,
and never for a condominium unit (above).

**Construction** — ``EXTFINISH_DESC``:

  ===============  ===============  ==========================================
  Brick            ``brick``        219,639 dwellings; see below
  Frame            ``frame``        166,710
  Masonry FRAME    ``brick-frame``  52,899 — masonry and frame in one wall, the
                                    label's mixed class, as Cook's "Frame +
                                    Masonry" and the District's "Brick/Siding"
  Stone            ``stone``        5,155
  Concrete Block   ``block``        1,395
  ===============  ===============  ==========================================

``Brick`` is the one knowingly lossy entry, the same call Cook's "Masonry" and the
District's "Face Brick" make: the roll does not say whether a brick wall is solid
masonry or a brick face on a frame, which is the difference the label's
``brick-frame`` exists for. Where the misreading is most likely — new
construction, in which a brick wall is usually a veneer — the category is rare:
Brick is 81% of the 1950s stock but 12.7% of 2010s and 5.7% of 2020s houses. It is
kept, and paid for in confidence (``base.TRANSLATED``) rather than coverage,
because the alternative is NSI's modeled guess for half the county.

Deliberately unmapped: ``Stucco`` (2,313; applied over frame and over masonry
alike, so it says nothing about the structure — Cook's and the District's call),
``Concrete`` (923; cast concrete is not block, and ``block`` is the label's only
concrete value — the District's call), ``Log`` (316; no label equivalent), blank.

**Condition** — ``CONDITIONDESC``, "the overall physical condition or state of
repair of a structure, relative to its age", on the dictionary's eight-step
scale. Mapped, reading DOWN where the scales differ:

  =========  =============  ==============================================
  EXCELLENT  ``excellent``  "outstanding maintenance"
  VERY GOOD  ``good``       "high degree of upkeep" — not read up
  GOOD       ``good``       "above ordinary maintenance"
  AVERAGE    ``average``    "ordinary maintenance, shows normal wear"
  FAIR       ``fair``       "sound but with noticeable deferred maintenance"
  POOR       ``poor``       "structural deterioration caused by significant
                            and chronic deferred maintenance"
  VERY POOR  ``poor``       "barely livable" — not read down to unsound
  UNSOUND    ``unsound``    "not suitable for habitation"
  =========  =============  ==============================================

``CDU`` (a composite of condition, desirability and utility) and ``GRADE``
(quality of construction) are not read: neither is a statement about upkeep alone.

**Foundation** — ``BASEMENTDESC``, the dictionary's five codes: Full ("3/4 to full
basement area") → ``full-basement``; Part ("between 1/4 and 3/4") →
``partial-basement``; Crawl ("crawl space to 1/4 basement area") → ``crawl``.
Unmapped: None ("there is no basement" — which says nothing about slab versus
crawl space, Philadelphia's call) and Slab/Piers (a slab and a pier foundation are
different things, and the code does not say which).

A year built has to belong to somebody's home
---------------------------------------------
The roll has no dwelling count, but ``USEDESC`` (the land-use code, "about 200
self-explanatory categories") is an explicit statement of what a parcel is, and
it is read the way Florida reads ``NO_RES_UNT == 0``: a record whose use is not a
dwelling (``_DWELLING_USES``) contributes nothing at all. Of the 449,378 records
carrying a year built, that turns away 584 — residential cards on parcels whose
use is a church (157), a commercial garage (61), a small store (44), a college
(20), a group home (17), vacant land (17), a "dwelling used as office". The
residential uses outside class R are named in the set rather than lost: farms (a
farm's residential card is its farmhouse), apartments, "store with apartments
over", and the housing authority's scattered-site homes. "CONDEMNED/BOARDED-UP"
and "RES AUX BUILDING (NO HOUSE)" say outright that nobody lives there and are not
in the set.

The service's clock
-------------------
Measured 2026-10-03. Inside the product path — every request the adapter made
while looking up the 514 geocoded homes of the verification below, over the pooled
session ``utils.http_session`` holds, three runs with zero request errors:

  ========================================  ======  ======  ======  ======
  request                                   median     p90     p95     max
  ========================================  ======  ======  ======  ======
  "which parcel is this dot inside?"  (514)  0.06 s  0.08 s  0.09 s  0.45 s
  "what is within 80 m of this dot?"  (485)  0.07 s  0.08 s  0.09 s  0.28 s
  WPRDC, one batch of ≤ 50 ids        (821)  0.08 s  0.12 s  0.17 s  2.50 s
  a whole lookup                      (514)  0.27 s  0.40 s  0.45 s  3.43 s
  ========================================  ======  ======  ======  ======

A lookup makes a median of three requests and at most ten (a condominium tower:
containment, one batch, the buffer, seven batches). Separately: 900 more WPRDC
requests over one session, one and 30 ids alternately, median 0.09 s, p99 0.44 s,
maximum 1.93 s; 30 of each request type over a fresh connection per request
(a TLS handshake each time), parcel layer median 0.39 s and maximum 0.64 s, WPRDC
median 0.39–0.42 s and maximum 1.52 s. The research pass earlier the same day
measured WPRDC at 0.79–2.10 s per request with curl.

WPRDC's tail is the number that sizes the clock, and it has two shapes:

* **Slow answers.** The slowest successful response anywhere was 2.50 s, inside
  the product path; the research pass saw 2.10 s. Under the shared 1 s read slice
  responses like those are cut off and read as "no record". ``READ_SLICE_S`` is
  3 s: above the slowest answer measured rather than at it, which is the rule
  Connecticut's clock follows.
* **Incidents.** One verification attempt landed in a WPRDC incident: of 253
  requests over about fifty consecutive lookups, 46 came back HTTP 500 and 3
  stalled past the slice. A diagnostic burst earlier saw 2 more stalls. No slice
  rescues a server that has stopped answering; every one of those lookups failed
  open, uncached and recorded through ``utils.note_dropped``, and the same sample
  re-run minutes later resolved 139 of 172 with no errors.

``LOOKUP_TIMEOUT`` is 8 s. An off-parcel house makes four or five requests
(containment, one batch, the buffer, one or two batches), and at the research
pass's 2.10 s per WPRDC request that is 0.25 + 2.1 + 0.25 + 2 × 2.1 ≈ 6.8 s, which
8 s covers. Neither number is what a lookup costs: a ceiling is not a cost, and
the measured typical is 0.27 s.

The two halves of a socket timeout add up, so what has to fit the host's
allowance is the budget spent connecting plus one read slice: 8 + 3 = 11 s,
inside the 12 s ``config.UPSTREAM_HOST_BUDGET`` allows any one service — the same
sum as Florida's. A test pins it against that constant. (The two hosts are
separate services to that budget, so each is charged only for its own requests.)

What the adapter is worth, end to end
-------------------------------------
Three runs, each of 150 dwellings drawn at random from the roll itself (any use in
``_DWELLING_USES`` with a year built and a house number, ranges typed by their low
number) plus 25 random condominium units typed with their unit, geocoded through
the Census one-line matcher and handed to the adapter through
``assessor_address`` exactly as the product does. Every geocode routed to 42003.

  ================  ========  ========  ============  ==========  ==========
  run               geocoded  resolved  wrong parcel  year exact  sqft exact
  ================  ========  ========  ============  ==========  ==========
  1 (houses)        147       123       **0**         123 / 123   113 / 113
  2 (houses)        147       124       **0**         124 / 124   112 / 112
  3 (houses)        147       123       **0**         123 / 123   115 / 115
  1–3 (condo units)  73        49       **0**          49 / 49     49 / 49
  ================  ========  ========  ============  ==========  ==========

So 84% of random homes (370 of 441) and 67% of condominium units resolve, and every
value reported matched the roll. The misses are the shared chooser declining, never
this adapter guessing. Every one was traced:

* **The geocode lands more than 80 m from its own parcel** — 66 of the 71 house
  misses and 18 of the 24 condominium misses, measured at 80 to 626 m (one unit
  by way of another unit of the same building, 191 m out). This is the
  suburban county: deep lots on curving streets, where the Census matcher's
  interpolated point falls in a neighbor's lot or across the road, and the buffer
  never reaches the house it was asked about.
* **No polygon** — 3 houses (one a mobile home in a park, PIN ``8000T…``) and 3
  units whose PIN is not in the parcel layer at all, so no point can reach them.
* **The geocoder names a different street** — 1 ("869 BEACON LN" matched to
  "869 BEACON RD" in another ZIP 16 km away; ``assessor_address`` correctly fell
  back to the typed address, which the point could then not reach). A second
  spelling split, "BROOK LEDGE RD" on the roll against "BROOKLEDGE RD" from the
  matcher, refused a condominium unit; it is one street with two spellings, but
  joining words is not a fold ``_shared`` makes, and should not be one adapter's
  local fix.
* **The geocoder drops a directional** — 1 ("1365 N SHERIDAN AVE" matched as
  "1365 SHERIDAN AVE"); directionals stay significant in ``_shared`` on purpose.
* **Too many candidates** — 2 units of 320 Fort Duquesne Blvd, whose 80 m buffer
  holds 325 parcels, under the first cap of 300. The cap is now 400; both re-run
  and resolve to the right unit (1964, 1,033 and 1,420 sq ft).

Condominium units resolve less often than houses (67% against 84%) for the reason
houses miss — 18 of their 24 misses are geocodes more than 80 m from the
building. None was the unit rule refusing the right row.

Terms of use
------------
The assessment dataset is licensed **Creative Commons CCZero** (``license_id:
cc-zero`` on WPRDC's ``package_show`` for ``property-assessments``, verified live
2026-10-03): a public-domain dedication, with no attribution, share-alike or
non-commercial condition. WPRDC's own Data Use Agreement grants access "pursuant
to the license terms, restrictions, or designations placed upon the Data by the
Data owner" and requires that the "User shall abide by the licensing terms if
provided by the data owner"; the rest of it is a warranty disclaimer and an
indemnity. Owner names are not in the dataset at all ("Excludes name and contact
information for property owners, as required by Ordinance 3478-07").

The parcel polygons are the county's (ArcGIS Online item
``ebc3eb6a71dc4a60839b6eb80fa176aa``, "Allegheny County Parcel Boundaries"; WPRDC
lists its mirror as "License not specified"). Its use constraints are a
disclaimer — "the data is for informational purposes only, there is no guarantee
as to its completeness or accuracy" — and an indemnity clause ("The USER shall
indemnify, save harmless, and, if requested, defend those parties…"). Neither
restricts commercial use or caching. This adapter reads only a parcel id from the
layer and keeps nothing of the geometry.

So the posture ``base.py`` records for Cook — query live, cache in-process, never
bundle — is more than these terms require, and is kept for consistency; CC0 would
allow bundling the roll.

Privacy, and why the field list is short
----------------------------------------
The roll has 86 columns. Among them are ``CHANGENOTICEADDRESS1``–``4`` — the tax
bill's mailing address, which for most homes is the owner's — every sale date,
price, deed book and page, and every assessed and fair-market value. None is an
input to any dimension. Fifteen columns are requested by name (``_FIELDS``); the
datastore's ``fields`` parameter is always that explicit list, never omitted
(omitting it returns every column). From the parcel layer only ``PIN`` is
requested. Nothing from either source is written into the repository.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    TruncatedResponse, address_key, arcgis_parcels, cache_bucket, deadline_from,
    num, same_address, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

COUNTY_FIPS = frozenset({"42003"})          # Allegheny County, PA

NAME = "Allegheny County Office of Property Assessments"
ATTRIBUTION = ("Allegheny County Office of Property Assessments "
               "(via the Western Pennsylvania Regional Data Center, CC0; "
               "parcels from Allegheny County GIS)")
DATA_VINTAGE = "Allegheny County assessment roll (WPRDC, refreshed monthly)"

PARCEL_URL = ("https://gisdata.alleghenycounty.us/arcgis/rest/services"
              "/OPENDATA/Parcels/MapServer/0/query")
ASSESSMENT_URL = "https://data.wprdc.org/api/3/action/datastore_search"
#: WPRDC's "Property Assessments Parcel Data (for downloads)" — the copy WPRDC
#: re-runs monthly (2026-10-02, as of 2026-09-30, 585,005 rows) and the faster of
#: the two datastore copies (0.79–1.10 s against 1.20–2.10 s for the "API
#: version", whose last refresh was a month older). Both carry the same columns.
ASSESSMENT_RESOURCE = "9a1c60bd-f9f7-4aba-aeb7-af8c3aaa44e5"

#: How long either service may go quiet before the silence is treated as a stall,
#: and the budget for a whole lookup across both hosts. Measured, not chosen — see
#: "The service's clock" in the module docstring.
#:
#: Named LOOKUP_TIMEOUT rather than TIMEOUT so it cannot be mistaken for, or
#: collide with, the shared four-second budget of the same name — Florida and
#: Connecticut name their own deviations the same way.
READ_SLICE_S = 3.0
LOOKUP_TIMEOUT = 8.0

#: Parcel ids per WPRDC request. WPRDC's firewall refuses a query string over
#: ~2,040 bytes; 50 ids is ~1.6 KB with this field list. See "Two things WPRDC's
#: firewall refuses".
_BATCH = 50
#: The most candidates one lookup will look up: eight batches, above the largest
#: 80 m buffer measured around 95 random condominium units (332). Past it the
#: lookup fails open rather than spend its budget on a tower's tiles.
_MAX_CANDIDATES = 400

# Only what the label scores, plus what decides whether a value describes one
# home: the use, the unit, the card number, and the roll's own dates. See
# "Privacy" in the module docstring for what is never requested.
_FIELDS = ("PARID", "PROPERTYHOUSENUM", "PROPERTYFRACTION", "PROPERTYADDRESS",
           "PROPERTYUNIT", "USEDESC", "YEARBLT", "FINISHEDLIVINGAREA", "STORIES",
           "EXTFINISH_DESC", "CONDITIONDESC", "BASEMENTDESC", "CARDNUMBER",
           "TAXYEAR", "ASOFDATE")

# A PIN as the county writes it: 16 characters, digits and capitals
# ("0001G00224110100", "0372L00129000A00"). Anything else is not an id this
# adapter will put in a filter.
_PIN_RE = re.compile(r"^[0-9A-Z]{16}$")

# USEDESC values that hold one dwelling: the basis for area and stories. See
# "What the label gets" in the module docstring.
_ONE_DWELLING_USES = frozenset({
    "SINGLE FAMILY", "TOWNHOUSE", "ROWHOUSE", "CONDOMINIUM",
    "MOBILE HOME", "MOBILE HOME (IN PARK)",
})
_CONDO_USE = "CONDOMINIUM"
# USEDESC values that hold at least one dwelling: the basis for every field. See
# "A year built has to belong to somebody's home" in the module docstring.
_DWELLING_USES = _ONE_DWELLING_USES | frozenset({
    "TWO FAMILY", "THREE FAMILY", "FOUR FAMILY",
    "APART: 5-19 UNITS", "APART:20-39 UNITS", "APART:40+ UNITS",
    "RETL/APT'S OVER", "OFFICE/APARTMENTS OVER",
    "COMM APRTM CONDOS 5-19 UNITS", "COMM APRTM CONDOS 20-39 UNITS",
    "COMM APRTM CONDOS 40+ UNITS",
    "DWG APT CONVERSION",
    "GENERAL FARM", "LIVE STOCK FARM", "DAIRY FARM", "VEGETABLE FARM",
    "OWNED BY METRO HOUSING AU",
})

# EXTFINISH_DESC → the label's vocabulary. Stucco, Concrete and Log are absent on
# purpose; see "Construction" in the module docstring.
_EXT_WALL = {
    "Brick": "brick",               # knowingly lossy: solid or veneer, unsaid
    "Frame": "frame",
    "Masonry FRAME": "brick-frame",
    "Stone": "stone",
    "Concrete Block": "block",
}
# CONDITIONDESC, read down where the scales differ; see "Condition" above.
_CONDITION = {
    "EXCELLENT": "excellent",
    "VERY GOOD": "good",
    "GOOD": "good",
    "AVERAGE": "average",
    "FAIR": "fair",
    "POOR": "poor",
    "VERY POOR": "poor",
    "UNSOUND": "unsound",
}
# BASEMENTDESC. None and Slab/Piers are absent on purpose; see "Foundation".
_BASEMENT = {
    "Full": "full-basement",
    "Part": "partial-basement",
    "Crawl": "crawl",
}

# PROPERTYUNIT markers that introduce a dwelling unit's own designator. Others
# ("REAR", "BLDG", "GAR") stay part of the designator; see "Condominiums".
_UNIT_MARKERS = frozenset({"UNIT", "APT", "STE", "SUITE", "TRLR", "LOT", "#"})

# "-1624": the rest of a house-number range ("1622-1624 FORBES AVE").
_RANGE_RE = re.compile(r"^-(\d+)$")
_MAX_RANGE_SPAN = 200


# --- hop 1: the parcel layer ---------------------------------------------------


def _clean_pin(raw) -> str | None:
    pin = str(raw or "").strip().upper()
    return pin if _PIN_RE.match(pin) else None


def _pins(lat: float, lon: float, distance_m: float = 0,
          *, deadline: float) -> list[str]:
    """Parcel ids at (or within ``distance_m`` of) a point, each once."""
    rows = arcgis_parcels(PARCEL_URL, lat, lon, "PIN", distance_m,
                          deadline=deadline, read_slice=READ_SLICE_S)
    out = []
    for row in rows:
        pin = _clean_pin(row.get("PIN"))
        if pin and pin not in out:
            out.append(pin)
    return out


# --- hop 2: the roll -----------------------------------------------------------


def _request(pins: list[str]) -> dict:
    """The ``datastore_search`` parameters for one batch of parcel ids.

    ``fields`` is always the explicit list: omitting it returns all 86 columns,
    the tax-bill mailing address among them. ``limit`` is the batch size because
    ``PARID`` is unique, so a batch can never legitimately return more rows than
    it named — and ``total`` is checked against it all the same.
    """
    return {
        "resource_id": ASSESSMENT_RESOURCE,
        "filters": json.dumps({"PARID": pins}, separators=(",", ":")),
        "fields": ",".join(_FIELDS),
        "limit": str(len(pins)),
    }


def _records(pins: list[str], known: dict, *, deadline: float) -> list[dict]:
    """The roll's rows for these parcel ids, in their order — fetched in batches.

    ``known`` holds what this lookup has already fetched (and ``None`` for an id
    the roll has no row for), so the buffered search does not ask again for the
    parcels the containment search already looked up.
    """
    missing = [p for p in pins if p not in known]
    if len(missing) > _MAX_CANDIDATES:
        # Not "no parcels here": too many to look up inside the budget. Raised
        # the way a truncated ArcGIS page is, so the lookup fails open uncached.
        raise TruncatedResponse(f"{len(missing)} candidate parcels exceed the "
                                f"{_MAX_CANDIDATES} this adapter will look up")
    for i in range(0, len(missing), _BATCH):
        batch = missing[i:i + _BATCH]
        body = _shared.get_json(ASSESSMENT_URL, _request(batch), deadline,
                                READ_SLICE_S)
        if not isinstance(body, dict) or body.get("success") is not True:
            raise RuntimeError("WPRDC datastore_search did not succeed")
        result = body.get("result") or {}
        rows = result.get("records") or []
        total = num(result.get("total"))
        if total is not None and total > len(rows):
            raise TruncatedResponse("WPRDC returned part of a batch")
        for row in rows:
            pin = _clean_pin((row or {}).get("PARID"))
            if pin in batch:
                known[pin] = row
        for pin in batch:
            known.setdefault(pin, None)
    return [known[p] for p in pins if known.get(p)]


# --- addresses and units ---------------------------------------------------------


def _range_high(low: str, ext: str) -> int | None:
    """The top of a "1622-1624" range, or None if the range is malformed."""
    lo = int(low)
    high = int(ext) if len(ext) >= len(low) else int(low[:-len(ext)] + ext)
    if high <= lo or high - lo > _MAX_RANGE_SPAN:
        return None
    return high


def _address_of(row: dict, asked: str | None = None) -> str | None:
    """The record's street address, as the comparison should see it.

    The house number is its own numeric column, 0 where the parcel has none
    (vacant land, common property), which is "no address", not "number 0". A
    ranged record is offered under the reader's own number when that number is
    inside the range on the same side of the street, and under its low number
    otherwise; any other fraction stays beside the number. See "Ranges" in the
    module docstring.
    """
    number = num(row.get("PROPERTYHOUSENUM"))
    street = " ".join(str(row.get("PROPERTYADDRESS") or "").split())
    if not number or number <= 0 or not float(number).is_integer() or not street:
        return None
    low = str(int(number))
    fraction = " ".join(str(row.get("PROPERTYFRACTION") or "").split())
    if not fraction:
        return f"{low} {street}"
    m = _RANGE_RE.match(fraction)
    if not m:
        return f"{low} {fraction} {street}"
    high = _range_high(low, m.group(1))
    key = address_key(asked) if asked else None
    if high is not None and key:
        n, lo = int(key[0]), int(low)
        if lo <= n <= high and (n - lo) % 2 == 0:
            return f"{n} {street}"
    return f"{low} {street}"


def _norm_unit(value) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _unit(row: dict) -> str:
    """The record's own unit designator, marker stripped and normalized; ""
    when it has none."""
    tokens = str(row.get("PROPERTYUNIT") or "").upper().split()
    if len(tokens) > 1 and tokens[0] in _UNIT_MARKERS:
        tokens = tokens[1:]
    return _norm_unit("".join(tokens))


def _candidates(rows: list[dict], address: str | None) -> list[dict]:
    """The rows that could be the reader's home. See "Condominiums" above.

    Only ever removes rows, so it can turn "ambiguous" into "one candidate" but
    never let a wrong record through: the address confirmation in
    ``select_parcel`` still runs on whatever is left.
    """
    typed = _norm_unit(unit_of(address))
    if typed:
        mine = [r for r in rows if _unit(r) == typed]
        if any(same_address(address, _address_of(r, address)) for r in mine):
            return mine
    return [r for r in rows if not _unit(r)]


# --- the choice ------------------------------------------------------------------


def _row_at(lat: float, lon: float, address: str | None = None,
            *, deadline: float | None = None) -> dict | None:
    """The roll's record for the home at this point and address, or None.

    The choice is ``_shared.select_parcel``'s, shared by every jurisdiction; see
    that function for why it never takes the nearest parcel. What is local is the
    candidate list: parcel ids from the point (or the buffer), turned into roll
    records, with every record that is not a home dropped (the condominium common
    parcel among them) and condominium units narrowed by the typed unit. No
    locality trim is needed: ``PROPERTYADDRESS`` is the bare street, with the
    city in a column of its own.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    known: dict = {}

    def fetch(distance_m: float) -> list[dict]:
        pins = _pins(lat, lon, distance_m, deadline=deadline)
        rows = [r for r in _records(pins, known, deadline=deadline)
                if _says_a_home_is_here(r)]
        return _candidates(rows, address)

    return select_parcel(fetch, address, lambda r: _address_of(r, address))


# --- the translation ---------------------------------------------------------------


def _use(row: dict) -> str:
    return " ".join(str(row.get("USEDESC") or "").upper().split())


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the roll's land use says this parcel holds a dwelling.

    ``USEDESC`` is always filled, and every value is a statement — a church, a
    garage, vacant land, a condominium's common property — so there is no
    "silent" case to let through, unlike Florida's and Connecticut's counts. See
    "A year built has to belong to somebody's home" in the module docstring.
    """
    return _use(row) in _DWELLING_USES


def _card_one(row: dict) -> bool:
    """Whether the building shown is card 1, the parcel's main dwelling."""
    return num(row.get("CARDNUMBER")) == 1


def _one_dwelling(row: dict) -> bool:
    """Whether this record is exactly one home: the basis for area and stories."""
    return _use(row) in _ONE_DWELLING_USES and _card_one(row)


def _year_built(row: dict) -> int | None:
    year = num(row.get("YEARBLT"))
    # 0 would be "not recorded", not the year zero. The roll writes NULL today,
    # but a 0 reaching the scorer would age the house by two thousand years.
    if not (year and float(year).is_integer()
            and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100):
        return None
    return int(year)


def _sqft(row: dict) -> float | None:
    area = num(row.get("FINISHEDLIVINGAREA"))
    if area is None or area <= 0 or not _one_dwelling(row):
        return None
    return area


def _stories(row: dict) -> int | None:
    """A whole-number story count for one house, or None.

    A half story is not rounded into one, and a condominium unit's count
    describes the flat rather than the building; see "Stories" above.
    """
    if not _one_dwelling(row) or _use(row) == _CONDO_USE:
        return None
    count = num(row.get("STORIES"))
    if count is None or count <= 0 or not float(count).is_integer():
        return None
    return int(count)


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row itself.

    ``TAXYEAR`` is "the current certified tax year" and ``ASOFDATE`` "the run date
    of this file"; both advance under an unchanged resource id each month, so a
    hard-coded year would go stale silently.
    """
    parts = []
    year = num(row.get("TAXYEAR"))
    if year and 1900 <= year <= 2100:
        parts.append(f"{int(year)} tax year")
    raw = str(row.get("ASOFDATE") or "").strip()
    for fmt in ("%d-%b-%y", "%Y-%m-%d"):
        try:
            parts.append(f"file of {datetime.strptime(raw[:10], fmt).date().isoformat()}")
            break
        except ValueError:
            continue
    return f"{DATA_VINTAGE}, {', '.join(parts)}" if parts else DATA_VINTAGE


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _row_at(lat, lon, address)
    # Not a home → nothing at all. _row_at already offers only homes; this is the
    # rule restated where the record is built, so the two cannot drift apart.
    if not row or not _says_a_home_is_here(row):
        return None
    fields = {
        "year_built": _year_built(row),
        "sqft": _sqft(row),
        "stories": _stories(row),
        "construction": _EXT_WALL.get(str(row.get("EXTFINISH_DESC") or "").strip()),
        "condition": _CONDITION.get(str(row.get("CONDITIONDESC") or "").strip().upper()),
        "foundation": _BASEMENT.get(str(row.get("BASEMENTDESC") or "").strip()),
    }
    # A record that matched but recorded nothing the label reads contributed
    # nothing; keep the fact-free record out of the cache. The registry drops it
    # either way.
    if all(v is None for v in fields.values()):
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_clean_pin(row.get("PARID")),
        **fields,
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Allegheny County's assessment roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address with the reader's unit carried
    over (``_shared.with_unit``). It confirms the parcel and, for a condominium,
    picks the unit; without one the lookup still answers wherever the point lands
    in exactly one home's parcel.

    Fails open on everything — a timeout, a firewall 403, a CKAN error body, a
    renamed column, too many candidates. The caller keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Allegheny County assessor lookup failed at %s,%s: %s",
                  lat, lon, exc)
        return None
