#!/usr/bin/env python3
"""San Francisco — the Assessor-Recorder's secured roll, reached through DataSF's parcels.

San Francisco is a consolidated city and county (``06075``, 414,602 homes), and
its Office of the Assessor-Recorder publishes the whole closed secured roll as an
open dataset on DataSF, the City's Socrata portal. The roll carries a year built,
a unit count, a story count, a floor area and a use classification for every
parcel, and no owner name at all. Both datasets are queried in SoQL —
Socrata's query language — over HTTPS, keyless, and Socrata has two traps of its
own that this file handles: a buffer function that does not mean what its name
says, and a silent row cap.

DataSF moved hosts: ``data.sfgov.org`` now answers every request with a 301 to
``data.sf.gov`` (verified 2026-10-03), so the new host is called directly rather
than paying a redirect on every lookup.

Two datasets, two requests
--------------------------
The roll is keyed by parcel number and carries only a parcel *centroid*, which a
geocode cannot land inside, so it cannot answer "which parcel is this dot in?"
by itself. The City's parcel polygons can:

1. ``acdm-wktn`` "Parcels – Active and Retired" — every parcel's shape and its
   ``blklot`` (block and lot, the Assessor's parcel number). One request asks for
   every **active** parcel reaching within 80 m of the geocode (``intersects``
   against an 80 m polygon) and, in the same breath, whether each one contains
   the point (``intersects(shape, POINT)`` evaluated in ``$select``). That one
   answer is both of the candidate sets ``_shared.select_parcel`` asks for —
   containment and the 80 m buffer — so the buffered question costs no extra
   request.
2. ``wv5m-vpq2`` "Assessor Historical Secured Property Tax Rolls" — the roll rows
   for those parcel numbers (``block in (...) AND parcel_number in (...)``), in
   the latest closed roll and the one before it.

The buffer is **not** Socrata's ``within_circle``, which is the obvious call and
is wrong here: on a polygon column it returns shapes lying *wholly inside* the
circle. A small house lot fits inside 80 m, so it looks right on a residential
street; a condominium tower's lot never does, and the first draft of this adapter
found no candidates at all beside 388 Beale St (0 rows, against 1,501 lots that
reach within 80 m) and resolved 124 of 160 sampled homes where the corrected
query resolves 150 on the same sample — the difference nearly all tower units,
lost without a single error. See ``_search_area``.

The parcel is then chosen from the **roll rows**, not from the polygons, because
only the roll knows a condominium unit's number (below). Two requests per lookup
whatever the geocode did, plus a third — the latest roll year — once per process
every six hours.

Only the coordinate and parcel numbers the parcel layer itself returned are ever
written into a query. The coordinate is formatted from a ``float`` and refused if
not finite; a parcel number must look like one (``^[0-9A-Z]{4,12}$``) or it is
dropped. Nothing the reader typed reaches SoQL: the address and the unit are
compared in Python after the rows arrive.

Which roll: the latest *closed* one, found rather than assumed
--------------------------------------------------------------
The dataset holds every closed roll since 2007 — one row per parcel per year,
211,547 in the 2025 roll alone — and gains a year each summer, after the roll is closed and
certified (2025's arrived 2026-06-26). The dataset's own description still says
"2007 to June 30, 2024"; it is out of date, which is why the year is read from
the data and not from the description or a constant.

``max(closed_roll_year)`` answers in 0.14 s (median of 10; the same question as
a ``GROUP BY`` timed out at 60 s), and is cached for one cache bucket. The roll
request then asks for that year **and the one before it** and keeps each parcel's
newest row. The second year is the robust part: a roll that is part-way through
loading, or a parcel the newest roll has not reached, falls back to the parcel's
previous certified row — dated as such in ``data_vintage`` — instead of
vanishing. A hard-coded year would go stale silently each August, and "the
current calendar year minus one" would lose the whole city the first summer the
publisher ran late.

Condominiums: one roll row per unit, stacked on one polygon
-----------------------------------------------------------
San Francisco files each condominium unit as its own lot with its own parcel
number and its own roll row, and draws every unit with the building's footprint:
a point on 468 07th Ave lands in six lots at once, and on 301 Mission St in 421.
Each unit's row carries the unit in ``property_location`` and the unit's own
``property_area`` (617 to 3,185 sq ft across 468 07th Ave's six units).

So the rows are narrowed by unit before the shared chooser runs, exactly as the
Philadelphia adapter does:

* The reader gave a unit (carried past the geocoder by ``_shared.with_unit``) and
  that unit exists at their address → only the matching rows are offered.
* Otherwise → only rows with **no** unit are offered. A condominium address with
  no unit has no candidate, which is the refusal the District and Philadelphia
  make: answering with one of 421 units would be the confident guess the
  selection policy exists to refuse. A two-unit condominium filed as "816
  ALVARADO ST" plus "816 ALVARADO ST #A" answers the reader who gave no unit with
  the unit that has none.

Where that leaves no answer and the reader's address is a stack, the building's
year is still reported if every dwelling record at that address within 80 m
agrees on it — the year a building went up is the same for every unit in it, the
fallback the Los Angeles adapter makes — with no area, no story count and no
parcel id, since no single record was chosen. Parking-stall, garage, store and
office condominiums at the same address (``PZ``, ``GZ``, ``CZ``, ``OZ`` …) are
not dwellings and do not get a vote.

Unit designators are compared on letters, digits and ``/`` with **leading zeros
stripped** — the opposite of the District's rule, and for a reason that is the
roll's: it zero-pads every unit to four characters ("0001", "0003G", "0PH4"), so
"#1" and "#01" can only ever mean "0001" here. ``/`` survives so that the roll's
half-number unit "01/2" can never equal a reader's unit "12".

``property_location``: a fixed-width field
------------------------------------------
The roll's address is one 36- or 37-character string, laid out by column
(verified over 20,000 rows of the 2025 roll; every one had this shape):

  ======  =================================  ==========================
  cols    meaning                            example
  ======  =================================  ==========================
  0–3     top of a house-number range, or    ``0473`` (``0000`` = none)
          0000 for a single number
  4       the range top's letter suffix      ``A`` in ``1986A1986``
  5–8     the house number (range bottom)    ``0471``
  9       the house number's letter suffix   ``A`` in ``0429A06TH``
  10–29   street name, padded to 20          ``CAPP``, ``07TH``
  30–31   street type, two letters           ``ST``, ``AV``, ``BL``
  32–     unit, zero-padded to 4, plus an    ``0000``, ``0003G``,
          optional letter                    ``0PH4``, ``01/2``
  ======  =================================  ==========================

Read as such, it becomes an ordinary street address for ``_shared``'s
comparison. Four things in it are the roll's own and are handled here, each
pinned by a test:

* **Ordinals are zero-padded** ("07TH AV"). The shared fold reads "07TH" as "07",
  never equal to the geocoder's "7TH" → "7", so the pad is dropped first.
* **Street types are the roll's own two-letter codes.** ``AV``/``ST``/``DR``/
  ``WY``/``CT``/``PL``/``LN``/``RD`` the shared table already knows; ``BL``
  (boulevard), ``HW`` (highway, "GREAT HW"), ``TE`` (terrace), ``CR`` (circle),
  ``AL`` (alley), ``PZ`` (plaza) and ``XI`` (crossing, "TONI STONE XI") it does
  not, and are respelled into the USPS forms it does. ``CR`` is circle or creek
  in general, which is why the shared table refuses it; in this roll it is only
  ever a circle ("ATOLL CR", Treasure Island). An unknown code (``RA``, freeway
  ramps) is kept as written, so it can never match an ordinary street.
* **A letter suffix belongs to the house number.** "429A 6TH AVE" is a
  different door from "429 6TH AVE" (110 of 20,000 sampled rows carry one). The
  shared parse wants a bare number and returns nothing for "429A", so such a
  door could never confirm; and dropping the letter would let 429A answer for
  429. So both the reader's address and the row are rewritten "429 DOOR-A 6TH
  AVE" (``_canon``): the letter travels as the first word of the street's name,
  which equals only the same letter on the same street. "1986A1986 42ND AV" — one
  parcel filed for 1986 and 1986A together — answers both.
* **Ranges.** 2,147 of the 20,000 sampled rows are filed under a range: "0473
  0471 CAPP" is 471–473. As in Philadelphia, a reader's number inside the range
  on the same side of the street (same parity) is offered under the reader's
  number; otherwise the row is offered under its bottom number. A range wider
  than 200 numbers is offered only under its bottom number, and so is the range
  of any record that is not a home: a vacant lot's or a park's range is
  frontage, not doors — "0198 0100 BRADFORD" (vacant land) otherwise claimed 160
  Bradford St beside the house filed under that number and made it ambiguous,
  and four such lots and parks cost four homes in the first verification draw.
  A range can only add a candidate; two rows claiming one address still make
  the chooser refuse.

The street name is truncated at 20 characters ("SERGEANT JOHN V YOUN", 1 row in
20,000). It then never matches the geocoder's full name, so those rows are
refused rather than matched by a prefix.

What the label gets, and what it is refused
-------------------------------------------
**Year built** — ``year_property_built``, text; absent where the roll records
none (339 of 17,765 sampled residential rows, 1.9%). The publisher defines it as
"Year improvement was built (can be blend of original and newer construction)":
there is no separate effective-year column, and the City's own caveat is that a
substantially rebuilt house may carry a blended year. It is the only year the
roll publishes and it is reported, in the plausible range shared with the
scorer.

**A year has to belong to somebody's home.** ``number_of_units`` cannot carry
the explicit-zero rule Florida and Connecticut apply: it is **0 on 3,203 of
6,348 sampled condominium (class Z) units** and on 110 of 111 townhouses — the
roll not counting units on a per-unit lot, not the roll saying nobody lives
there. What
the roll does state is its use code, from the Assessor's published class table
(DataSF ``pa56-ek2h``): ``SRES`` (Single Family Residential) and ``MRES``
(Multi-Family Residential) hold homes, and so do classes ``AC``/``ACG``
"Apartment & Commercial Store", filed under ``COMM``. Every other explicit use —
``COMR``/``COMO``/``COMM`` shops, offices, garages and parking-stall condos,
``COMH`` hotels (including ``RH`` residential hotels and SROs, which the label
does not score as a home), ``IND``, ``GOVT``, ``MISC`` vacant land — refuses the
record. A blank use code is silence and is let through.

**Floor area** — ``property_area``, the Assessor's square footage of the
improvement — only where the record is one dwelling, by the roll's own class:

* condominium and townhouse classes (``Z``, ``ZBM``, ``LZ``, ``LZBM``, ``TH``,
  ``THBM``) are one home per lot by definition, and the area is that home's —
  provided the unit the record names is the unit the reader named (both absent
  counts), the Los Angeles rule;
* single-dwelling classes (``D``, ``DBM``, ``PD``) only where
  ``number_of_units`` is exactly 1, with no unit typed by the reader (a reader
  who writes a unit at an address the roll files as one dwelling is telling us
  something the record does not know about).

Everything else — flats, apartments, TICs, co-ops, condominium "economic units"
(``ZEU``) — describes a whole building and is refused, never divided.

**Stories** — ``number_of_stories``, a whole number, only where the area rule
above holds and the record is not a condominium unit: on a unit the field is the
unit's own floor count (468 07th Ave #4, a two-level unit, says 2; most of 301
Mission St's units say 0 or 1 in a tower).

**Not read: construction.** ``construction_type`` holds ``D`` (114,898 SRES
rows), ``NA``, ``A``, ``B``, ``C``, ``WOO``, ``STE``, ``S`` and ``REI``. They
look like the State Board of Equalization's construction classes (D = wood
frame), but the column's own definition says only "See code book", and no code
book is published with the dataset or anywhere on DataSF; ``D`` beside ``WOO``
and ``S`` beside ``STE`` suggests two vocabularies mixed. Deciding that ``D``
means frame would be a guess wearing the ``observed`` tag — the call Florida makes
for its unpublished ``CONST_CLAS`` — so it is not requested. Condition and
foundation have no column.

The service's clock
-------------------
Measured 2026-10-03, keyless. The first row is a standalone containment-only
query at 40 fresh residential points (centroids of random 2025-roll parcels,
shifted 12 m toward the street), there only to show that folding containment
into the buffered request costs nothing; the adapter never sends it. The rest
are every request the adapter made inside the product path while looking up the
320 homes of the verification below:

  ==========================================  ======  ======  ======  ======
  request                                     median     p90     p95     max
  ==========================================  ======  ======  ======  ======
  parcels containing the point (alone, 40)    0.13 s  0.18 s  0.22 s  0.37 s
  parcels within 80 m + containment (319)     0.21 s  0.41 s  0.51 s  2.50 s
  roll rows for those parcels (356)           0.19 s  0.29 s  0.34 s  1.40 s
  latest roll year (once per bucket)          0.14 s  0.16 s  0.18 s  0.20 s
  whole lookup (319)                          0.42 s  0.72 s  0.92 s  3.21 s
  ==========================================  ======  ======  ======  ======

The roll request was far slower before the ``block in (...)`` clause: median
0.72 s and maximum 2.09 s at 45 points, with Socrata answering a repeat of the
same request in ~0.15 s from its own cache — and a lookup is always a first
request.

Under the shared one-second read slice 5 of these 675 requests would have been
cut off, and a cut-off reads as "San Francisco has no record", not as a timeout.
A lookup beside a cluster of towers also makes up to six requests (the parcel
request and five roll requests of 400; 388 Beale St does). So ``READ_SLICE_S`` is
3 s, clearing every measured request, and ``LOOKUP_TIMEOUT`` is 6 s, nearly twice
the slowest whole lookup measured. The host allows one service 12 s
(``config.UPSTREAM_HOST_BUDGET``); the true worst case is the budget spent
connecting plus one read slice, 6 + 3 = 9 s, and a test pins that sum against the
constant. A typical lookup costs about 0.4 s.

No app token: Socrata throttles keyless requests per client address more
tightly than tokened ones, and documents no fixed number. Every request in the
measurements and the verification below ran keyless with no throttling seen. If
the hosted API ever sees ``429`` from ``data.sf.gov``, an app token in the
``X-App-Token`` header is the fix; ``_shared.get_json`` sends fixed headers today,
so that would be a shared change.

What the adapter is worth, end to end
-------------------------------------
Two independent random draws of 160 residential records each from the 2025
roll (use ``SRES``/``MRES``, condominium units included and typed with their
unit, ranges typed by their bottom number), geocoded through the Census
one-line matcher exactly as the product does, the unit carried over by
``location.assessor_address``, then looked up:

  =====  ========  ======  ========  ============  ==========  ==========
  draw   geocoded  routed  resolved  wrong parcel  year exact  sqft exact
  =====  ========  ======  ========  ============  ==========  ==========
  1      159       159     156       **0**         154 / 154   131 / 131
  2      160       160     158       **0**         158 / 158   129 / 129
  =====  ========  ======  ========  ============  ==========  ==========

"Routed" is the geocoder's county code landing in ``COUNTY_FIPS``. "Wrong
parcel" is a record whose parcel number or year differs from the record
sampled; there were none in 314 answers. 118 of the 320 were condominium units
(94 typed with a unit): 116 resolved, 114 to the unit's own parcel number (113
with its own floor area; one unit records none) and 2 through the building-year
fallback, whose year matched. 147 answers carried a story count, 28 of the
sampled records were filed under a range, and both lettered doors drawn
(862A De Haro St, 309C Castro St) resolved. No request failed.

The 5 misses: two condominium units whose roll rows record nothing at all (no
year, area 0 — correctly no answer), and three homes the geocoder placed more
than 80 m from their own lot, whose parcel was then not among the candidates
(one of them, a 1942 apartment building on 19th Ave, beside an office parcel
filed at the same address, which the use code refused). One address did not
geocode.

The first draft of this adapter resolved 124 of the first draw. Three fixes
took it to 156: the buffer (``within_circle``, above), the vacant-lot ranges
(below) and lettered doors.

Terms of use
------------
Both datasets carry DataSF's license, "Open Data Commons Public Domain
Dedication and License" (PDDL 1.0, ``licenseId: PDDL`` in each dataset's
metadata). DataSF's Terms of Use (sf.gov/reports/april-2017/datasf-terms-use)
say data "is made available under the Public Domain Dedication and License v1.0"
except where otherwise stated, and nothing on either dataset says otherwise; the
Terms disclaim every warranty ("subject to error, and cannot be relied upon
without verification or site inspection"), and forbid re-identifying people or
combining the data with other data sets "for the purpose of re-identification".
The roll's own disclaimer: "The Office of the Assessor-Recorder makes no
representation or warranty that the information provided is accurate and/or has
no errors or omissions." Verdict: commercial use and caching are permitted
outright, with no attribution condition; this adapter queries live and caches in
process anyway, the posture every adapter takes, and fetches nothing about a
person, so the re-identification clause has nothing to bite on. Attribution is
carried regardless, because the label always says where a value came from.

Privacy, and why the column lists are short
-------------------------------------------
The roll has no owner name, but it does carry ``exemption_code`` (including the
homeowner's exemption, which says whether the owner lives there),
``current_sales_date``, ``percent_of_ownership`` and every assessed value; the
parcel layer carries supervisor names. None of it is an input to any dimension.
Nine roll columns and two parcel columns (plus the computed containment flag) are
selected by name; ``*`` — or an empty ``$select``, which Socrata reads as every
column — is never sent. Nothing from either dataset is written into the
repository.
"""

from __future__ import annotations

import logging
import math
import re
import time
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SEARCH_RADIUS_M, address_key, cache_bucket, deadline_from, num, same_address,
    select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# A consolidated city and county: one county code, and the City's Assessor-Recorder
# is its only assessor.
COUNTY_FIPS = frozenset({"06075"})          # City and County of San Francisco, CA

NAME = "San Francisco Office of the Assessor-Recorder"
ATTRIBUTION = ("City and County of San Francisco Office of the Assessor-Recorder "
               "(DataSF secured roll, public domain, keyless)")
DATA_VINTAGE = "San Francisco Assessor-Recorder closed secured roll"

PARCELS_URL = "https://data.sf.gov/resource/acdm-wktn.json"
ROLL_URL = "https://data.sf.gov/resource/wv5m-vpq2.json"

#: San Francisco's own clock; see "The service's clock" in the module docstring.
#: A lookup makes the parcel request, the roll request and — once per cache
#: bucket — the latest-roll-year request, all against one deadline.
READ_SLICE_S = 3.0
LOOKUP_TIMEOUT = 6.0

# Only what the label scores, plus what decides whether a value describes one home:
# the use and class codes, the unit count and the address (which carries the unit).
# See "Privacy" in the module docstring for what is never selected.
_ROLL_COLUMNS = ("closed_roll_year", "parcel_number", "property_location",
                 "use_code", "property_class_code", "year_property_built",
                 "number_of_units", "number_of_stories", "property_area")
_PARCEL_COLUMNS = ("blklot", "block_num")

# Socrata answers 1,000 rows unless told otherwise, and says nothing when it stops.
# Every request names its limit, and a response that reaches it is treated as
# truncated: the rows it dropped could include the second record that would have
# made a match ambiguous.
_ROW_LIMIT = 5000

# How many parcel numbers one roll request may carry. 421 (a 7.0 KB URL) answered
# in 0.2 s; 1,000 (18 KB) was refused with 414 URI Too Long. Five requests of 400
# cover the most crowded 80 m measured around a home — 1,501 lots reach within
# 80 m of 388 Beale St, among Rincon Hill's towers — at ~0.2 s a request. The
# only single stacks larger than that are hotel timeshares (2,393 lots at 441
# Mason St), which are not homes. Past the cap, the point's own parcels are still
# asked about and the buffered search is refused (see _memo).
_IDS_PER_REQUEST = 400
_MAX_ROLL_REQUESTS = 5

_PARCEL_NUMBER_RE = re.compile(r"^[0-9A-Z]{4,12}$")
# A block is four digits and an optional letter ("3595", "2999A", "0306T").
_BLOCK_RE = re.compile(r"^[0-9]{4}[A-Z]?$")

# The first roll in the dataset. A "latest year" older than this, or later than
# the current calendar year, is a malformed answer, not a roll.
_FIRST_ROLL_YEAR = 2007

# The roll's two-letter street types, respelled into forms the shared table knows.
# Only the codes it does not already know are listed (AV, ST, DR, WY, CT, PL, LN
# and RD pass through), and each is the roll's only use of that code; see
# "property_location" in the module docstring.
_STREET_TYPES = {
    # AV is known to the shared table too; respelled only so the rendered address
    # reads as the geocoder writes it.
    "AV": "AVE",
    "BL": "BLVD", "HW": "HWY", "TE": "TER", "CR": "CIR", "AL": "ALY",
    "PZ": "PLZ", "XI": "XING",
}

# Use codes that hold homes, and the two classes filed under COMM that do too. See
# "A year has to belong to somebody's home" in the module docstring.
_HOME_USES = frozenset({"SRES", "MRES"})
_HOME_CLASSES = frozenset({"AC", "ACG"})

# One home per lot by the class's definition: condominium units (including
# live/work and below-market-rate) and townhouses.
_ONE_HOME_CLASSES = frozenset({"Z", "ZBM", "LZ", "LZBM", "TH", "THBM"})
# One home only if the roll counts exactly one: dwelling, BMR dwelling, PUD.
_COUNTED_CLASSES = frozenset({"D", "DBM", "PD"})
# Classes whose story count is the unit's own floors, not the building's.
_CONDO_CLASSES = frozenset({"Z", "ZBM", "LZ", "LZBM"})

_MAX_RANGE_SPAN = 200

# The search disk as a polygon; see _search_area.
_CIRCLE_SIDES = 32
_METERS_PER_DEGREE = 111_320.0


# --- the requests ---------------------------------------------------------------


def _coord(value: float) -> float:
    """A coordinate fit to write into SoQL, or a raise (which fails open).

    Formatted from a float, never from a string: a ``nan`` would format as the
    bare word ``nan`` and reach the query as an identifier.
    """
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite coordinate")
    return value


def _search_area(lat: float, lon: float) -> str:
    """The search radius as a WKT polygon: a 32-gon whose edges, not its corners,
    lie on the circle, so it covers the whole 80 m disk (overshooting by at most
    0.4 m at a corner).

    Not ``within_circle``. On a polygon column Socrata's ``within_circle`` means
    *the whole shape lies inside the circle*, not *the shape reaches into it*: a
    tower's lot never fits inside 80 m, so every condominium tower came back with
    no candidates at all (388 Beale St: 0 rows, against 1,501 parcels that reach
    within 80 m). ``intersects`` against this polygon returns exactly the set
    ``distance_in_meters(shape, point) <= 80`` does, in 0.1–0.3 s where the
    distance filter, which no index serves, took 5–11 s.
    """
    reach = float(SEARCH_RADIUS_M) / math.cos(math.pi / _CIRCLE_SIDES)
    dlat = reach / _METERS_PER_DEGREE
    dlon = reach / (_METERS_PER_DEGREE * math.cos(math.radians(lat)))
    ring = [(lon + dlon * math.cos(2 * math.pi * k / _CIRCLE_SIDES),
             lat + dlat * math.sin(2 * math.pi * k / _CIRCLE_SIDES))
            for k in range(_CIRCLE_SIDES)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in ring) + "))"


def _parcel_params(lat: float, lon: float) -> dict:
    """The one parcel request: every active parcel reaching within the search
    radius, each with whether it contains the point. See "Two datasets, two
    requests"."""
    lat, lon = _coord(lat), _coord(lon)
    point = f"'POINT({lon:.7f} {lat:.7f})'"
    return {
        "$select": ", ".join(_PARCEL_COLUMNS) + f", intersects(shape, {point}) AS inside",
        "$where": f"active AND intersects(shape, '{_search_area(lat, lon)}')",
        "$limit": str(_ROW_LIMIT),
    }


def _rows_of(body) -> list[dict]:
    """A Socrata row list, or a raise. A 200 that is not a list is not an answer."""
    if not isinstance(body, list):
        raise RuntimeError(f"unexpected Socrata response: {type(body).__name__}")
    if len(body) >= _ROW_LIMIT:
        raise _shared.TruncatedResponse("data.sf.gov: response reached $limit")
    return [r for r in body if isinstance(r, dict)]


def _is_inside(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _parcels(lat: float, lon: float, *, deadline: float) -> list[tuple[str, str, bool]]:
    """``(blklot, block, contains the point)`` for every active parcel within 80 m.

    A row whose parcel number does not look like one is dropped — it could never
    be joined to the roll, and it must not be written into the next query. A
    block that does not look like one is kept as "" (see :func:`_roll_params`):
    the parcel is still a candidate, and dropping a real candidate could make a
    neighbor's record look unique.
    """
    body = _shared.get_json(PARCELS_URL, _parcel_params(lat, lon), deadline,
                            READ_SLICE_S)
    found: dict[str, tuple[str, bool]] = {}
    for row in _rows_of(body):
        blklot = str(row.get("blklot") or "").strip().upper()
        if not _PARCEL_NUMBER_RE.match(blklot):
            continue
        block = str(row.get("block_num") or "").strip().upper()
        if not (_BLOCK_RE.match(block) and blklot.startswith(block)):
            block = ""
        # One lot drawn as two shapes is one candidate, inside if either shape is.
        held = found.get(blklot, ("", False))
        found[blklot] = (block or held[0], held[1] or _is_inside(row.get("inside")))
    return [(b, block, inside) for b, (block, inside) in found.items()]


# The latest closed roll year, per cache bucket. A dict rather than lru_cache
# because the request needs the lookup's deadline, which must not be a cache key.
_ROLL_YEAR: dict[int, int] = {}


def _latest_roll_year(*, deadline: float) -> int:
    """The newest ``closed_roll_year`` in the dataset. See "Which roll"."""
    bucket = cache_bucket()
    if bucket in _ROLL_YEAR:
        return _ROLL_YEAR[bucket]
    body = _shared.get_json(ROLL_URL, {"$select": "max(closed_roll_year) AS latest"},
                            deadline, READ_SLICE_S)
    rows = _rows_of(body)
    year = num(rows[0].get("latest")) if rows else None
    if year is None or not (_FIRST_ROLL_YEAR <= year <= time.gmtime().tm_year):
        # Not cached: a malformed answer is a glitch, and failing open on it lets
        # the next lookup ask again.
        raise RuntimeError(f"implausible latest roll year: {year!r}")
    _ROLL_YEAR.clear()
    _ROLL_YEAR[bucket] = int(year)
    return int(year)


def _roll_params(parcels: list[tuple[str, str]], since: int) -> dict:
    """The roll request for ``(blklot, block)`` pairs.

    The ``block in (...)`` clause is redundant with the parcel numbers — a lot's
    block is the front of its number — and is there for speed: on parcels the
    service had not been asked about before, it brought the median roll request
    from 1.34 s to 0.31 s and the slowest of 15 from 1.89 s to 0.68 s. If any
    parcel's block is unknown the clause is left out rather than letting it
    exclude that parcel.
    """
    ids = ",".join(f"'{b}'" for b, _ in parcels)
    where = f"closed_roll_year >= {int(since)} AND parcel_number in ({ids})"
    blocks = sorted({block for _, block in parcels})
    if blocks and all(blocks):
        where += f" AND block in ({','.join(repr(b) for b in blocks)})"
    return {"$select": ",".join(_ROLL_COLUMNS), "$where": where,
            "$limit": str(_ROW_LIMIT)}


def _roll_rows(parcels: list[tuple[str, str]], *, deadline: float) -> list[dict]:
    """Each parcel's newest row from the latest closed roll or the one before it,
    for ``(blklot, block)`` pairs.

    Rows with no parcel number are records of nothing and are dropped, as Florida
    drops its placeholder polygons.
    """
    if not parcels:
        return []
    if len(parcels) > _IDS_PER_REQUEST * _MAX_ROLL_REQUESTS:
        raise _shared.TruncatedResponse(
            f"{len(parcels)} parcels at this point; more than one lookup may ask for")
    since = _latest_roll_year(deadline=deadline) - 1
    newest: dict[str, dict] = {}
    for i in range(0, len(parcels), _IDS_PER_REQUEST):
        chunk = parcels[i:i + _IDS_PER_REQUEST]
        body = _shared.get_json(ROLL_URL, _roll_params(chunk, since), deadline,
                                READ_SLICE_S)
        for row in _rows_of(body):
            pid = _parcel_number(row)
            year = num(row.get("closed_roll_year"))
            if pid is None or year is None:
                continue
            held = newest.get(pid)
            if held is None or year > num(held.get("closed_roll_year")):
                newest[pid] = row
    return list(newest.values())


def _parcel_number(row: dict) -> str | None:
    pid = str(row.get("parcel_number") or "").strip()
    return pid or None


def _memo(lat: float, lon: float, deadline: float):
    """``fetch(distance_m)`` for one lookup: roll rows in, or near, the parcel.

    The parcel request runs once and serves both distances. The roll request asks
    for every parcel within the radius at once, so an off-parcel geocode — the
    common case, since the Census matcher interpolates along the street — costs no
    second request. Where the radius holds more parcels than one lookup may ask
    for (a cluster of towers) but the point's own parcels do not, the containment
    answer is still given and the buffered one is refused as truncated.
    """
    state: dict = {}

    def fetch(distance_m: float) -> list[dict]:
        if "parcels" not in state:
            state["parcels"] = _parcels(lat, lon, deadline=deadline)
        parcels = state["parcels"]
        inside = [(b, block) for b, block, i in parcels if i]
        everything = [(b, block) for b, block, _ in parcels]
        wanted = {b for b, _ in (inside if distance_m == 0 else everything)}
        if "rows" not in state:
            cap = _IDS_PER_REQUEST * _MAX_ROLL_REQUESTS
            first = everything if len(everything) <= cap else inside
            state["rows"] = _roll_rows(first, deadline=deadline)
            state["asked"] = {b for b, _ in first}
        if not wanted <= state["asked"]:
            raise _shared.TruncatedResponse("too many parcels within the search radius")
        return [r for r in state["rows"] if _parcel_number(r) in wanted]
    return fetch


# --- property_location ------------------------------------------------------------


def _parse_location(raw) -> dict | None:
    """The roll's fixed-width address, as its parts, or None if it is not one.

    See "property_location: a fixed-width field" in the module docstring for the
    layout. Leading and trailing spaces are significant, so the string is not
    stripped before slicing.
    """
    loc = str(raw or "")
    if len(loc) < 32:
        return None
    top, top_suffix, low, low_suffix = loc[0:4], loc[4], loc[5:9], loc[9]
    if not (top.isdigit() and low.isdigit()):
        return None
    return {
        "top": int(top), "top_suffix": top_suffix.strip(),
        "low": int(low), "low_suffix": low_suffix.strip(),
        "street": " ".join(loc[10:30].split()),
        "type": loc[30:32].strip(),
        "unit": loc[32:].strip(),
    }


def _street(parts: dict) -> str:
    """The street name and type as the shared comparison wants them.

    Drops the roll's ordinal padding ("07TH" → "7TH") and respells its own street
    types; see the module docstring.
    """
    words = [(w.lstrip("0") or w) if w[:1].isdigit() else w
             for w in parts["street"].split()]
    kind = parts["type"]
    if kind:
        words.append(_STREET_TYPES.get(kind, kind))
    return " ".join(words)


_LETTERED_RE = re.compile(r"^(\d+)([A-Za-z])$")
_DOOR_RE = re.compile(r"^door-([a-z])$")


def _door(number: int, letter: str) -> str:
    """A lettered house number in the form the comparison keeps distinct: "429A"
    becomes "429 DOOR-A". See :func:`_canon`."""
    return f"{number} DOOR-{letter.upper()}"


def _canon(address: str | None) -> str | None:
    """The reader's address with a lettered house number made comparable.

    The shared parse wants a bare number and returns nothing for "429A 6TH AVE",
    so a lettered door could never confirm — 0.6% of the roll's rows. Rewritten
    as "429 DOOR-A 6TH AVE" on both sides, the letter travels as the first word
    of the street's name: "429 DOOR-A 6TH AVE" equals only itself, never "429
    6TH AVE" (different name tokens) nor "429 DOOR-B 6TH AVE". Nothing else
    changes. The roll's rows are rendered the same way by :func:`_address_of`.
    """
    if not address:
        return address
    head, sep, tail = str(address).partition(",")
    words = head.split()
    m = _LETTERED_RE.match(words[0]) if words else None
    if not m:
        return address
    return " ".join([_door(int(m.group(1)), m.group(2))] + words[1:]) + sep + tail


def _asked_door(key) -> str | None:
    """The letter of a lettered door in an ``address_key``, or None."""
    m = _DOOR_RE.match(key[1][0]) if key and key[1] else None
    return m.group(1).upper() if m else None


def _address_of(row: dict, asked: str | None = None) -> str | None:
    """The row's street address, offered under the reader's number when a range
    covers it. See "Ranges" in the module docstring.

    ``asked`` must already have been through :func:`_canon`.
    """
    parts = _parse_location(row.get("property_location"))
    if parts is None or parts["low"] <= 0:
        return None
    street = _street(parts)
    if not street:
        return None
    low, top = parts["low"], parts["top"]
    if parts["low_suffix"]:
        if not parts["low_suffix"].isalpha():
            return None              # "0015-": not a house number at all
        # A lettered door is its own address; see _canon.
        return f"{_door(low, parts['low_suffix'])} {street}"
    key = address_key(asked) if asked else None
    letter = _asked_door(key)
    if letter and top == low and parts["top_suffix"] == letter and key[0] == str(low):
        # "1986A1986": one parcel filed for 1986 and 1986A together.
        return f"{_door(low, letter)} {street}"
    # A range is offered under the reader's number only on a record the roll says
    # holds a home. A vacant lot's or a park's range is frontage, not doors:
    # "0198 0100 BRADFORD" (vacant) otherwise claims 160 Bradford St beside the
    # house actually filed there and makes it ambiguous.
    if key and key[0].isdigit() and not letter and low < top <= low + _MAX_RANGE_SPAN \
            and _says_a_home_is_here(row):
        n = int(key[0])
        if low <= n <= top and (n - low) % 2 == 0:
            return f"{n} {street}"
    return f"{low} {street}"


def _norm_unit(value) -> str:
    """A unit designator for comparison: letters, digits and ``/``, upper-cased,
    leading zeros stripped. See "Condominiums" in the module docstring."""
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum() or ch == "/")
    return text.lstrip("0")


def _unit(row: dict) -> str:
    """The row's own unit, normalized; "" when it has none."""
    parts = _parse_location(row.get("property_location"))
    return _norm_unit(parts["unit"]) if parts else ""


def _candidates(rows: list[dict], address: str | None) -> list[dict]:
    """The rows that could be the reader's home.

    Only ever removes rows, so it can turn "ambiguous" into "one candidate" but
    never let a wrong record through: ``select_parcel`` still confirms the address
    on whatever is left.
    """
    typed = _norm_unit(unit_of(address))
    if typed:
        mine = [r for r in rows if _unit(r) == typed]
        if any(same_address(address, _address_of(r, address)) for r in mine):
            return mine
    return [r for r in rows if not _unit(r)]


# --- the translation --------------------------------------------------------------


def _code(row: dict, column: str) -> str:
    return str(row.get(column) or "").strip().upper()


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the roll's own use classification says this record holds a home.

    An explicit non-dwelling use is a statement — a shop, an office, a parking
    stall — and a year built read off it would describe a building nobody lives
    in. A blank use code is silence and is let through, the distinction Florida
    and Connecticut draw on their dwelling counts. ``number_of_units`` cannot do
    this job here; see the module docstring.
    """
    use = _code(row, "use_code")
    return not use or use in _HOME_USES or _code(row, "property_class_code") in _HOME_CLASSES


def _year_built(row: dict) -> int | None:
    raw = str(row.get("year_property_built") or "").strip()
    if not raw.isdigit():
        return None
    year = int(raw)
    # 0 is "not recorded", not the year zero.
    if not (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100):
        return None
    return year if _says_a_home_is_here(row) else None


def _one_home(row: dict, reader_unit: str) -> bool:
    """Whether this record is exactly the reader's one dwelling: the basis for area
    and stories. See "Floor area" in the module docstring."""
    if not _says_a_home_is_here(row):
        return False
    klass = _code(row, "property_class_code")
    if klass in _ONE_HOME_CLASSES:
        return _unit(row) == reader_unit
    if klass in _COUNTED_CLASSES:
        return num(row.get("number_of_units")) == 1 and not reader_unit and not _unit(row)
    return False


def _sqft(row: dict, reader_unit: str) -> float | None:
    area = num(row.get("property_area"))
    if area is None or area <= 0 or not _one_home(row, reader_unit):
        return None
    return area


def _stories(row: dict, reader_unit: str) -> int | None:
    """A whole story count for a one-dwelling building, never a condo unit's own
    floor count. A half story is not rounded into one (the District's rule)."""
    if not _one_home(row, reader_unit) or _code(row, "property_class_code") in _CONDO_CLASSES:
        return None
    count = num(row.get("number_of_stories"))
    if count is None or count <= 0 or not float(count).is_integer():
        return None
    return int(count)


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row's own roll year."""
    year = num(row.get("closed_roll_year"))
    if year and _FIRST_ROLL_YEAR <= year <= 2100:
        year = int(year)
        return f"{DATA_VINTAGE}, {year} roll (fiscal {year}–{str(year + 1)[-2:]})"
    return DATA_VINTAGE


def _record(row: dict, address: str | None) -> AssessorRecord | None:
    """The label's record of the home this roll row describes, or None."""
    if not _says_a_home_is_here(row):
        return None
    reader_unit = _norm_unit(unit_of(address))
    fields = {
        "year_built": _year_built(row),
        "sqft": _sqft(row, reader_unit),
        "stories": _stories(row, reader_unit),
    }
    # A record that matched but recorded nothing the label reads contributed
    # nothing; keep the fact-free record out of the cache. The registry drops it
    # either way.
    if all(v is None for v in fields.values()):
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_number(row),
        # No construction, foundation or condition: see "Not read: construction".
        **fields,
    )


def _building_year(fetch, address: str) -> tuple[int, dict] | None:
    """The year a condominium building went up, when the reader's unit is unknown.

    ``(year, one of the rows)``, or None. Reached only when no single record was
    chosen. Every dwelling record at this street address within the radius must
    agree on the year; records that are not dwellings (parking stalls, the shop
    on the ground floor) do not vote. No area, no stories and no parcel id come
    with it, since no unit was chosen.

    It has to be a stack: at least two dwelling records. A lone record the reader's
    unit did not match is not a building of units whose year is shared — and a
    half-number door ("3432 1/2 20TH ST", the roll's unit "01/2") is a separate
    house, usually a rear cottage, so any such record at the address refuses.
    """
    rows = [r for r in fetch(SEARCH_RADIUS_M)
            if same_address(address, _address_of(r, address))]
    homes = [r for r in rows if _says_a_home_is_here(r)]
    if len(homes) < 2 or any("/" in _unit(r) for r in homes):
        return None
    years = {_year_built(r) for r in homes}
    if len(years) != 1 or None in years:
        return None
    return next(iter(years)), homes[0]


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    """The record, then the building — the second only if the first declined."""
    address = _canon(address)
    fetch = _memo(lat, lon, deadline_from(None, LOOKUP_TIMEOUT))
    try:
        row = select_parcel(lambda d: _candidates(fetch(d), address),
                            address, lambda r: _address_of(r, address))
        if row is not None:
            return _record(row, address)
        building = _building_year(fetch, address) if address else None
    except _shared.TruncatedResponse:
        # Deterministic for this point, not a portal glitch: the same query will
        # be too large the same way next time, so "no answer" is the answer.
        return None
    if building is None:
        return None
    year, sample = building
    return AssessorRecord(source=ATTRIBUTION, data_vintage=_vintage(sample),
                          parcel_id=None, year_built=year)


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What San Francisco's secured roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address with the reader's unit carried
    over (``location.assessor_address``). It confirms the record and, for a
    condominium, picks the unit; without one the lookup still answers wherever
    the point lands in a parcel holding exactly one record.

    Fails open on everything — a timeout, a Socrata error, a renamed column. The
    caller keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("San Francisco assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
