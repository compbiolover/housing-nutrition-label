#!/usr/bin/env python3
"""Maryland — all 23 counties and Baltimore City from one statewide layer, usually in one request.

The fifth statewide-scale adapter, and the one where the obvious design was not the
right one. The plan (``research/next-adapters-and-revenue-plan.md`` §1.2 #8) named
the Maryland Department of Planning's CAMA service — four point layers keyed on the
tax account (``ACCTID``) — and expected a two-hop lookup: a point to a parcel to get
the account, then the account to a CAMA row. Inspecting the services found a better
one. The parcel *polygon* layer already carries the State Department of Assessments
and Taxation (SDAT) facts on the same feature as the boundary:

  ``PlanningCadastre/MD_ParcelBoundaries/MapServer/0`` — "Parcel Boundaries",
  2,288,725 polygons, keyless, verified live, ``minScale 0``.

So the lookup is one question, as in Florida and Connecticut: *which parcel is this
point inside, and what does its record say?*

Why the CAMA layers are not used
--------------------------------
Because they say the same thing, one hop later. ``YEARBLT`` and ``SQFTSTRC`` on the
parcel polygon are copied from the same SDAT CAMA extract as ``BL_YEARBLT`` and
``BL_ENCSQFT`` on ``MD_ComputerAssistedMassAppraisal/MapServer/0``. Checked on 14
random single-family and townhouse accounts in 11 jurisdictions: the year built was
identical on all 14, and ``SQFTSTRC`` equalled both the principal building's
``BL_ENCSQFT`` and the property total ``PR_ENCSQFT`` on all 14. The CAMA service
would add only ``CM_BLDTOTL`` (the number of buildings on the property), and that is
not worth a second request: on 400 random single-family and townhouse parcels whose
record says one dwelling unit, ``CM_BLDTOTL`` was 1 on 395 and absent on the other 5
— never more than one. The ``minScale 10000`` the plan flagged turned out not to gate
attribute queries, but it no longer matters.

``MD_PropertyData/MapServer/0`` (Parcel Points) carries the same columns again on a
point per account. A point cannot be "inside" anything, so as the primary source it
would turn every lookup into a buffered search; the polygon layer answers most
lookups with containment alone. It is kept as a fallback for the accounts that have
no polygon — see "Accounts with no polygon".

Words this file cannot avoid
----------------------------
* **SDAT** — the State Department of Assessments and Taxation. Maryland assesses
  property at the state level, not the county level, which is why one roll covers
  every jurisdiction with one schema.
* **account** (``ACCTID``) — SDAT's identifier for one assessed property. A house is
  one account; so is each condominium unit.
* **MdProperty View** — the Department of Planning's product built on that roll. Its
  User's Guide (Appendices C, D and J; the edition cited here is dated 2016-11-30) is
  the data dictionary this file quotes.

The address column that is sometimes the owner's
------------------------------------------------
``ADDRESS`` is not always the property's address. The User's Guide, Appendix C:
"If ADDRESS cannot be populated by premise address, the field is populated with
owner address line 1 (OWNADD1) for parcel accounts with an owner occupied
indicator ... of either H ... or D". ``ADDRTYP`` records which: ``P`` for premise,
``O`` for owner. 1,438 polygons carry ``O``.

That is a mailing address arriving under an innocent column name, and this package
never fetches mailing addresses. So the request itself excludes those rows —
``where ADDRTYP IS NULL OR ADDRTYP <> 'O'`` — and no owner-derived string ever
reaches this process. (``ADDRTYP`` is null exactly where ``ADDRESS`` is: zero
polygons have one without the other.) The cost is those 1,438 parcels, 0.06% of the
layer, which could only ever have been confirmed against an address that was not the
property's. The rows are also dropped client-side, so a server that ignored the
predicate would not change the answer.

Owner names are not in this layer at all. ``OWNADD1``–``OWNZIP2`` (mailing),
``TRADATE`` and ``CONSIDR1`` (the last sale) and the assessed values are, and none of
them is requested.

Placeholders, common elements, and things that are not homes
------------------------------------------------------------
Rights of way, water and condominium common elements are drawn as polygons with a
word where the account should be — ``ROW``, ``WATER``, ``MEDIAN``, ``COMMON``,
``PRIVATE LANE`` and about 4,200 others — or with no account at all. A real account
begins with SDAT's two-digit jurisdiction code (01–24) and the district digits
after it. Anything else is dropped before the parcel is chosen, as Florida drops its
blank polygons, and so is a real account whose unit field says it is a condominium's
common area: neither can be anybody's home, and leaving them in would make a real
parcel look ambiguous.

So is a record the roll explicitly describes as something other than a dwelling.
SDAT has no dwelling *count* that can be zero — ``BLDG_UNITS`` is "number of
building units", and the Guide warns it counts commercial condominium units on a
commercial property; it is never 0 in the layer and is 1 on 29,221 plain commercial
parcels. What the roll does have is a building-type description whose first word is
a keyword (Appendix J): ``DWEL ...`` and ``HOUSING ...`` for homes, ``STORE``,
``OFFICE``, ``WAREHOUSE`` and the rest for everything else. A record the Planning
Department did not class as residential (``RESITYP`` blank) whose building is a
store is the roll saying "no dwelling here", and is not an answer. A blank
description says nothing and is let through. Three ``DWEL`` types are not dwellings
either — ``Boat Slip``, ``Storage Unit`` and ``Parking Space``, the condominium
accounts for exactly those — and are refused whatever else the row says.

Condominiums: one account per unit, and a polygon per account
-------------------------------------------------------------
Maryland files each condominium unit as its own account, and where a county's maps
allow, the Department draws a small square for each one — 45 to 90 m² — inside the
building, beside a ``COMMON`` polygon for the shared elements. (Where they do not, see
"Accounts with no polygon".) 43 S Prospect St in Hagerstown is seven squares,
each with its own unit (``STRTUNT = 'UNIT 3'``), its own floor area (``SQFTSTRC`` of
567 against 1,311 next door) and the same year built, 2005.

That shape has three consequences, and each has its own rule:

1. **A square a geocode happens to land in says nothing about which unit is the
   reader's.** The squares are symbols, not floor plans. So the floor area and the
   storey count of a unit record are reported only when the reader typed a unit and
   the record's own unit matches it. The year built is reported either way: the
   building went up when it went up. Same split Connecticut makes. Such a record is
   also not attributed to the unit's account — it is evidence about the building,
   and the account would be some other unit's.
2. **With a unit typed, it decides.** The candidates are narrowed to records whose
   unit matches what the reader typed *before* the shared chooser sees them, so the
   six other squares at the same street address are not rivals. Only records whose
   unit field is unambiguously a unit — ``UNIT 505``, ``APT R1``, ``STE 9A``,
   ``# 2`` — can match. ``114-116`` (an address range), ``REAR``, ``BOAT SLIP B3``
   and ``OPEN SPACE`` are not units.
3. **With no unit typed, the building still has a year.** Seven squares sharing one
   street address are, to the shared chooser, seven candidates and therefore
   ambiguous. They are seven records of one building, so before the choice they are
   folded into one candidate that carries the year *if every unit that records one
   agrees on it* — and nothing else: no account, no floor area, no storey count, no
   wall. Units that disagree fold into a candidate with no year, which then answers
   nothing. Folding can only turn "ambiguous" into "one building"; the address
   confirmation that follows is untouched.

Both narrowings happen inside the fetch handed to ``_shared.select_parcel``, which is
the sanctioned place to remove non-answers. The parcel-choosing policy itself is not
reimplemented. The two passes share one memoised fetch, so the unit pass costs no
extra request.

Units written into the house number — Howard County's ``7434B SAINT MARGARETS
BLVD`` — have no house number the shared address parse can anchor on, so they are
reachable only by containment without an address, and then report a year alone.

Accounts with no polygon
------------------------
Not every county draws the squares. Counting condominium accounts by jurisdiction,
points against polygons: Montgomery 41,357 against 547, Prince George's 17,118
against 400, Baltimore County 14,357 against 868, Baltimore City 8,309 against 209.
Harford draws all 5,947 of its own, Worcester two thirds. Statewide there are 134,993
condominium points against 31,505 condominium polygons, and 509,174 townhouse points
against 463,115 townhouse polygons: roughly 150,000 homes that exist only as points.
5600 Wisconsin Ave in Chevy Chase is a five-hectare condominium-regime
placeholder polygon (``C001670``) with its unit points stacked at one spot inside it.

So the account points are a second source for the same passes. The points carry
the same columns, so the same predicate, drops, unit rule and folding apply, and the
shared chooser's buffered search is the only way in: a point is never inside
anything, so the containment half is answered empty without a request. A typed unit
is looked for among the polygons and then among the points *before* either is asked
about the building, because some polygons stand for a whole building while carrying
one unit's account: 1 Ginford Pl in Catonsville is a single polygon labelled
``UNIT 202``, with unit 102 present only among the points, and asking about the
building first would answer every reader there with unit 202's record. Otherwise the
points are asked only where the polygons chose nothing — never instead of a
polygon's answer, nor where a polygon was chosen but recorded nothing, since its
point is the same account. Its reach is the shared 80 m radius,
which a geocode at the street front of a large complex can miss — the Census matcher
puts 5600 Wisconsin Ave about 105 m from its stack, and that building stays
unanswered rather than widening the search for one adapter.

The floor area that is not a footprint
--------------------------------------
The 2016 User's Guide defines ``SQFTSTRC`` as "Foundation square footage of the
principal structure". The live values are not that. On every one of the 14 accounts
above it equals ``BL_ENCSQFT``, which the same Guide defines as "enclosed square
feet ... multiplied by the story height of each section", and which the subarea table
confirms: 7007 Plymouth Rd is a 770 ft² two-storey footprint and reports 1,320 —
two storeys less a 220 ft² built-in garage, not 770. It is the dwelling's enclosed
living area, which is the label's ``sqft``.

On a property with more than one building it is the *total*: 401 Naylor St in
Wicomico has a 1920 house of 1,868 ft² and a 1988 one of 1,456, and reports 3,324.
Every such property seen also records ``BLDG_UNITS`` above 1, so the area is reported
only where the record says exactly one unit — Florida's rule, and never divided.

What the roll carries, and what is translated
---------------------------------------------
* **Year built** — ``YEARBLT``, "Year the structure was built", the actual year; the
  roll has no effective year to confuse it with. ``0000`` and blank are "not
  recorded".
* **Storeys** — from the building-style description (Appendix J, keyword ``STRY``):
  ``STRY 2 Story With Basement``, ``STRY Townhouse-End Unit 3 Story No Basement``.
  Whole numbers only. ``1.5 Story``, ``2.5 Story`` and ``Split Foyer`` are not a
  whole-number storey count and stay empty, the same call Cook makes for "1.5
  Story" and "Split Level". The numeric ``BLDG_STORY`` column is blank on all but
  296 of 1,745,940 single-family and townhouse records and is not used.
* **Construction** — from the type-of-construction description (Appendix J, keyword
  ``CNST``), mapped only where the wording names the wall system; see ``_CONSTRUCTION``.
* **Foundation** — not mapped, though the style says ``With Basement`` or ``No
  Basement``. The label distinguishes a full basement from a partial one and a slab
  from a crawlspace, and the roll's two words decide neither.
* **Condition** — not mapped. ``STRUGRAD`` is the SDAT *grade*, "quality of
  construction" on a nine-step scale from Low to Superior (Appendix J). It describes
  how well a house was built, not what state it is in now, and the label's
  ``condition`` is the second. Not requested.

Terms of use
------------
The Department of Planning's datasets on MD iMAP are published by the State of
Maryland under its standard disclaimer (data.gov entries for "MD iMAP: Maryland
Property Data - Parcel Points" and "MD iMAP: Maryland Computer Assisted Mass
Appraisal", read 2026-10-03): the data are provided "as is", the State accepts no
liability, and "The Data can be freely distributed as long as the metadata entry is
not modified or deleted. Any data derived from the Data must acknowledge the State
of Maryland in the metadata." The service names its sources as "MD iMAP, MDP, SDAT".
Nothing there restricts querying, caching or commercial use; the one obligation is
acknowledgement, which ``ATTRIBUTION`` carries onto the label. This adapter takes the
same posture as every other — queried live, cached in process, nothing written into
the repository — although these terms would permit more.

Why this service gets its own read slice
----------------------------------------
Measured first on its own — 40 real Maryland parcels drawn at random from the polygon
layer in 16 of the 24 jurisdictions, and 30 more against the account points, with the
production field list and predicate:

  ====================================  ======  ======  ======  ======
  request                               median     p90     p95     max
  ====================================  ======  ======  ======  ======
  polygons: "which parcel is this in?"   0.42 s  0.48 s  0.50 s  0.64 s
  polygons: "what is within 80 m?"       0.46 s  0.56 s  0.90 s  0.95 s
  points:   "what is within 80 m?"       0.44 s  0.48 s  0.54 s  0.58 s
  ====================================  ======  ======  ======  ======

and then in flight, over the 143 geocoded lookups of the end-to-end run below (308
requests; the buffered row mixes both layers):

  ====================================  ======  ======  ======  ======
  request                               median     p90     p95     max
  ====================================  ======  ======  ======  ======
  containment                            0.18 s  0.58 s  0.81 s  1.31 s
  buffered, 80 m                         0.20 s  0.62 s  0.67 s  1.19 s
  whole lookup                           0.46 s  1.22 s  1.80 s  2.47 s
  ====================================  ======  ======  ======  ======

Usually quick, but the tail runs past the shared one-second read slice — the slowest
single request across every run, well over a thousand requests in all, took 1.35 s — and a
cut-off reads as "no record here", not as a timeout. Dense Baltimore City blocks
return 100+ parcels within 80 m. So ``READ_SLICE_S`` is 2.5 s, nearly twice the
slowest request seen, and ``LOOKUP_TIMEOUT`` is five seconds, twice the slowest whole
lookup (three requests at most: containment, polygon buffer, points buffer). Neither
is what a lookup costs: the typical lookup is a single containment query. The connect
half of a socket timeout keeps the whole remaining budget, so the worst case for one
request is 5 + 2.5 = 7.5 s, inside the 12 s the host allows one service
(``config.UPSTREAM_HOST_BUDGET``); a test pins that sum against the constant.

The buffered responses are at most 42 KB, so no body can stream for seconds.

What the adapter is worth, end to end
-------------------------------------
150 homes drawn at random from the polygon layer (single-family, townhouse and
condominium accounts with a premise address and a year built, 23 of the 24
jurisdictions), geocoded through the Census matcher exactly as the product does, the
reader's unit carried by ``assessor_address``, then looked up: 143 geocoded, all 143
routed to a Maryland county code, **117 resolved and 0 matched to the wrong parcel**.
The year built was exact on all 117 and the floor area on all 112 that reported one.

Of the 26 that did not resolve, 23 are addresses the geocoder placed more than 80 m
from the edge of their own parcel — typically 100 to 450 m, the Census matcher
interpolating along rural and suburban roads — so the right polygon was never among
the candidates. The other three are spellings the shared matcher declines: a lettered
house number (``309A``), the matcher adding a directional the roll does not have
(``N SAINT AUGUSTINE RD``), and its abbreviation ``FAR CORS LP``. An earlier sample of
150 also showed two addresses that the roll gives to two accounts within 80 m of each
other, refused as ambiguous, and four ``SAINT``/``NORTH`` spellings that the
shared comparison now reconciles.

That earlier sample also flagged one apparent wrong parcel, and it was the roll's:
SDAT gives two accounts the premise address 404 S Talbot St, St Michaels, 700 m apart.
One stands at 404 S Talbot St; the other stands next to 400 *N* Talbot St, where the
Census matcher puts 404 N Talbot St. The adapter answered with the first, which is the
building at the address asked about.

Condominiums were measured separately, because the polygon layer under-represents
them: 100 condominium units drawn at random from the account points, 93 geocoded, 46
resolved, 0 wrong. The year was exact on all 46 and the floor area on all 22 that
reported one — the typed unit found and confirmed. The rest are mostly unit stacks
more than 80 m from the geocode and units written into the house number. A first run
of that sample found four readers given another unit's account (the year right, the
account not), which is what the unit-first ordering and the unattributed building
answer in ``_record_at`` and ``_record`` now prevent.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# All 23 Maryland counties and Baltimore City. The counties are the odd codes from
# 24001 to 24047 — except 24007, which is not assigned to any county (the repository's
# own county table has no 24007 either). Baltimore City is an independent city and takes 24510, outside the county run. Written as a rule so it
# cannot drift; a test checks it against the county table this repository ships.
COUNTY_FIPS = frozenset(
    f"24{n:03d}" for n in range(1, 48, 2) if n != 7
) | {"24510"}

NAME = "Maryland Department of Planning"
ATTRIBUTION = ("State of Maryland — SDAT assessment data via the Maryland Department "
               "of Planning (MD iMAP parcel boundaries, keyless)")
DATA_VINTAGE = "Maryland SDAT real property data on MDP parcel boundaries"

PARCEL_URL = ("https://mdgeodata.md.gov/imap/rest/services/PlanningCadastre"
              "/MD_ParcelBoundaries/MapServer/0/query")
#: The same SDAT columns on one point per account. Asked for a typed unit the
#: polygons do not hold, or when the polygons chose nothing; see "Accounts with no
#: polygon" in the module docstring.
POINTS_URL = ("https://mdgeodata.md.gov/imap/rest/services/PlanningCadastre"
              "/MD_PropertyData/MapServer/0/query")

#: How long this service may go quiet before the silence is treated as a stall, and
#: the budget for a whole Maryland lookup. Both measured rather than chosen — see "Why
#: this service gets its own read slice" in the module docstring. Named
#: LOOKUP_TIMEOUT, not TIMEOUT, so it cannot collide with the shared budget.
READ_SLICE_S = 2.5
LOOKUP_TIMEOUT = 5.0

# Only what the label scores, what decides whether the area describes one home, and
# what dates the record. ADDRTYP is the indicator that ADDRESS came from the owner's
# mailing address; it is requested so the rows the predicate below excludes are also
# refused here. See "The address column that is sometimes the owner's".
_FIELDS = ("ACCTID,ADDRTYP,RESITYP,ADDRESS,STRTUNT,YEARBLT,SQFTSTRC,DESCCNST,"
           "DESCSTYL,DESCBLDG,BLDG_UNITS,SDATDATE")

# A constant, never built from input. It keeps owner-derived addresses out of the
# response entirely rather than discarding them after they have arrived.
_WHERE = "ADDRTYP IS NULL OR ADDRTYP <> 'O'"

# SDAT's jurisdiction code (01-24) and two district digits. ROW, WATER, COMMON,
# MEDIAN, PRIVATE LANE and the other placeholder words fail it, as does a null.
_REAL_ACCOUNT = re.compile(r"^(?:0[1-9]|1\d|2[0-4])\d\d")

# The roll's type-of-construction wording (Appendix J, keyword CNST) → the label's
# vocabulary. Anything absent is dropped, for the reasons listed below the table.
_CONSTRUCTION = {
    "CNST Frame": "frame",
    # Siding, shingles, hardboard and plain wood are claddings hung on a framed wall,
    # so the wall system is frame — the reading the District's adapter makes for its
    # own siding types. Plain "Siding" is NOT read as `vinyl`: the label's vinyl means
    # vinyl or aluminium cladding specifically, and the roll's word does not say which
    # siding it is. Frame is also the reading that claims less (its resilience factor
    # is the higher of the two).
    "CNST Siding": "frame",
    "CNST Shingle Wood": "frame",
    # Asbestos-cement shingles, nailed over sheathing on a frame wall.
    "CNST Shingle Asbestos": "frame",
    "CNST Hardboard": "frame",
    "CNST Wood": "frame",
    "CNST Vinyl": "vinyl",
    # Half brick, half siding or frame: a framed house with a brick face on part of
    # it, which is what the label's brick-frame (brick veneer on frame) describes.
    "CNST 1/2 Brick Siding": "brick-frame",
    "CNST 1/2 Brick Frame": "brick-frame",
    "CNST Brick Veneer": "brick-frame",
    # Common brick is laid in structural wythes; the District maps its own the same.
    "CNST Brick Common": "brick",
    "CNST Block": "block",
}
# Deliberately unmapped, each for a reason:
#
#   Brick            321,525 residential records, the second-largest class — and the
#                    only brick code the RESIDENTIAL list has (veneer exists only in
#                    the commercial list, C106). It covers Baltimore's solid-masonry
#                    rowhouses and the suburbs' brick-veneer-on-frame houses alike,
#                    and the label's `brick` and `brick-frame` are exactly that
#                    difference. Choosing either would be wrong for a large share.
#   Stone            the same problem: no residential stone-veneer code, so solid
#                    fieldstone and a stone face on frame share one word
#   Brick Face       the exterior wythe, which can be a veneer — the same ambiguity
#   1/2 Stone Siding,  a stone face on part of a framed wall; the label has
#   1/2 Stone Frame    brick-frame but no stone-frame, and `stone` asserts solid masonry
#   Stucco           applied over frame and over masonry alike, so it says nothing
#                    about the structure (Cook's and the District's call too)
#   Concrete         cast concrete is not concrete block, the label's only concrete
#   Metal, Brick and Metal, Log    no unambiguous equivalent

# The building-type keywords (Appendix J) that describe a home.
_DWELLING_KEYWORDS = frozenset({"DWEL", "DWLL", "HOUSING"})
# DWEL-keyword building types that are not dwellings: the condominium accounts for a
# boat slip, a storage unit and a parking space.
_NOT_DWELLINGS = frozenset({"DWEL Boat Slip", "DWEL Storage Unit", "DWEL Parking Space"})

# A unit field that is unambiguously one unit: a marker and one designator. Address
# ranges ("114-116"), "REAR", "BOAT SLIP B3" and the like do not match.
_ROW_UNIT_RE = re.compile(r"^(?:UNIT|APT|APARTMENT|STE|SUITE|#)\s*([A-Z0-9]+(?:-[A-Z0-9]+)?)$")
_RANGE_RE = re.compile(r"^\d+-\d+$")

# A whole storey count in the style description. The space before the digit is what
# keeps "1.5 Story" from reading as 5.
_STORIES_RE = re.compile(r"(?:^|\s)([1-9]) Story\b")

_SDAT_DATE_RE = re.compile(r"^(\d{4})([A-Z]{3})$")
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    start=1)}


def _text(row: dict, column: str) -> str:
    return " ".join(str(row.get(column) or "").split())


def _account(row: dict) -> str | None:
    """SDAT's account number for this parcel, or None for a placeholder polygon."""
    acct = _text(row, "ACCTID")
    return acct if _REAL_ACCOUNT.match(acct) else None


def _row_unit(row: dict) -> str | None:
    """The unit designator the roll records for this account, or None.

    Only the unambiguous form counts — a marker and one designator. A range is an
    address range on a multi-number building, not a unit.
    """
    raw = _text(row, "STRTUNT").upper()
    if not raw or _RANGE_RE.match(raw):
        return None
    m = _ROW_UNIT_RE.match(raw)
    return m.group(1) if m else None


def _same_unit(a: str | None, b: str | None) -> bool:
    """Whether two unit designators are the same one — case and punctuation aside.
    Leading zeros stay significant, as in the District's adapter."""
    def norm(v):
        return "".join(ch for ch in str(v or "").upper() if ch.isalnum())
    return bool(norm(a)) and norm(a) == norm(b)


def _is_unit_record(row: dict) -> bool:
    """Whether this account is one unit of a building rather than a building.

    A unit designator, the Planning Department's condominium class, or a condominium
    building type. Any of them means the floor area belongs to *a* unit, not
    necessarily to the reader's.
    """
    return (_row_unit(row) is not None
            or _text(row, "RESITYP").upper() == "CN"
            or _text(row, "DESCBLDG").startswith(("DWEL Condo", "DWEL Penthouse")))


def _says_no_home_is_here(row: dict) -> bool:
    """Whether the roll explicitly describes this record as something other than a
    dwelling. See "Placeholders, common elements, and things that are not homes".

    Silence is not a statement: a blank building type with no residential class is
    let through, as Florida lets a missing dwelling count through.
    """
    building = _text(row, "DESCBLDG")
    if building in _NOT_DWELLINGS:
        return True
    units = num(row.get("BLDG_UNITS"))
    if units is not None and units == 0:
        return True
    if _text(row, "RESITYP"):
        return False
    keyword = building.split(" ", 1)[0].upper() if building else ""
    return bool(keyword) and keyword not in _DWELLING_KEYWORDS


def _is_candidate(row: dict) -> bool:
    """Whether a row could ever be an answer. Non-answers are dropped before the
    parcel is chosen, so they cannot make a real parcel look ambiguous."""
    if _text(row, "ADDRTYP").upper() == "O":
        return False                      # owner-derived address; see the docstring
    if _account(row) is None:
        return False                      # placeholder polygon
    if "COMMON" in _text(row, "STRTUNT").upper():
        return False                      # a condominium's common elements
    return not _says_no_home_is_here(row)


def _address_of(row: dict) -> str | None:
    # "SAINT ANDREWS PL" and "NORTH BEND RD", which the roll spells out and the
    # Census matcher abbreviates, are reconciled by the shared comparison.
    return _text(row, "ADDRESS") or None


def _query(url: str, lat: float, lon: float, distance_m: float,
           *, deadline: float) -> list[dict]:
    """``_shared.arcgis_parcels`` with the predicate that keeps owner-derived
    addresses out of the response — the shared budget, read slice, dropped-dataset
    accounting and truncated-page refusal all apply."""
    return _shared.arcgis_parcels(url, lat, lon, _FIELDS, distance_m,
                                  deadline=deadline, read_slice=READ_SLICE_S,
                                  where=_WHERE)


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Polygon rows at (or within ``distance_m`` of) a point that could be an answer."""
    return [r for r in _query(PARCEL_URL, lat, lon, distance_m, deadline=deadline)
            if _is_candidate(r)]


def _points(lat: float, lon: float, distance_m: float = 0,
            *, deadline: float) -> list[dict]:
    """Account points within ``distance_m`` of a point that could be an answer.

    A point is never *inside* anything, so the containment half of the shared
    chooser has nothing to ask and no request is made for it: the account points are
    reached only by the address-confirmed buffer.
    """
    if not distance_m:
        return []
    return [r for r in _query(POINTS_URL, lat, lon, distance_m, deadline=deadline)
            if _is_candidate(r)]


def _fold_units(rows: list[dict]) -> list[dict]:
    """Unit records sharing one street address, folded into one building.

    See consequence 3 under "Condominiums" in the module docstring. The folded row
    carries the address and — only where every unit that records a year agrees on
    it — the year. Nothing else: no account (it is no one account), no area, no
    storeys, no wall. A group of one is left as it is.
    """
    groups: dict[tuple, list[dict]] = {}
    out: list[dict] = []
    for row in rows:
        key = address_key(_address_of(row)) if _is_unit_record(row) else None
        if key is None:
            out.append(row)
        else:
            groups.setdefault(key, []).append(row)
    for members in groups.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        years = {_year(m) for m in members} - {None}
        out.append({"ADDRESS": _address_of(members[0]), "_FOLDED": len(members),
                    "YEARBLT": str(years.pop()) if len(years) == 1 else None,
                    "SDATDATE": members[0].get("SDATDATE")})
    return out


def _year(row: dict) -> int | None:
    year = num(_text(row, "YEARBLT"))
    # "0000" is SDAT's "not recorded", not the year zero.
    return int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None


def _stories(row: dict) -> int | None:
    m = _STORIES_RE.search(_text(row, "DESCSTYL"))
    return int(m.group(1)) if m else None


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row: ``SDATDATE`` is the month of
    the assessment data linked to the polygon ("2026MAY"), and it advances under an
    unchanged URL."""
    m = _SDAT_DATE_RE.match(_text(row, "SDATDATE").upper())
    if m and m.group(2) in _MONTHS and 1990 <= int(m.group(1)) <= 2100:
        return f"{DATA_VINTAGE}, SDAT data of {m.group(1)}-{_MONTHS[m.group(2)]:02d}"
    return DATA_VINTAGE


def _record(row: dict, unit_confirmed: bool) -> AssessorRecord | None:
    """The chosen row, in the label's vocabulary, or None if it says nothing."""
    year = _year(row)
    if row.get("_FOLDED"):
        # A building folded from its units: the year all of them agree on, only.
        return AssessorRecord(source=ATTRIBUTION, data_vintage=_vintage(row),
                              year_built=year) if year else None
    # The area and the storeys describe the reader's home only where the record is
    # one unit and — for a condominium unit — the unit the reader typed.
    # A unit record nobody confirmed is evidence about the BUILDING — its year and
    # its walls — and not about any one account in it, so it is not attributed to
    # one: the account would be some other unit's.
    building_only = _is_unit_record(row) and not unit_confirmed
    one_home = num(row.get("BLDG_UNITS")) == 1 and not building_only
    area = num(row.get("SQFTSTRC"))
    sqft = area if one_home and area and area > 0 else None
    stories = _stories(row) if one_home else None
    construction = _CONSTRUCTION.get(_text(row, "DESCCNST"))
    if year is None and sqft is None and stories is None and construction is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=None if building_only else _account(row),
        year_built=year,
        sqft=sqft,
        stories=stories,
        construction=construction,
    )


def _choose_unit(fetch, unit: str, asked: str | None) -> dict | None:
    """The record of the unit the reader typed, or None. Candidates are narrowed to
    records of that unit before the shared chooser sees them, so the other units at
    the same street address are not rivals."""
    return select_parcel(
        lambda d: [r for r in fetch(d) if _same_unit(unit, _row_unit(r))],
        asked, _address_of)


def _choose_building(fetch, asked: str | None) -> dict | None:
    """The record of the building at this point, or None, with the units of one
    building folded together first."""
    return select_parcel(lambda d: _fold_units(fetch(d)), asked, _address_of)


def _memo(source, lat: float, lon: float, deadline: float):
    """``source`` memoised per radius, so every pass over it shares one request."""
    seen: dict[float, list[dict]] = {}

    def fetch(distance_m: float) -> list[dict]:
        if distance_m not in seen:
            seen[distance_m] = source(lat, lon, distance_m, deadline=deadline)
        return seen[distance_m]
    return fetch


def _record_at(lat: float, lon: float, address: str | None,
               *, deadline: float | None = None) -> AssessorRecord | None:
    """The record of the home at this point, or None.

    Up to four selection passes, every one a ``select_parcel`` call, over at most
    three requests:

    1. the typed unit among the polygons, then among the account points;
    2. the building among the polygons, then among the account points.

    The unit is looked for in both sources before either is asked about the
    building, because a polygon can stand for a whole building while carrying one
    unit's account: 1 Ginford Pl in Catonsville is one polygon labelled ``UNIT 202``,
    with unit 102 present only among the points. Asking the polygons about the
    building first would answer every reader in it with unit 202's account.

    The account points are asked only where the polygons chose nothing and there is
    an address to confirm against — never instead of a polygon's answer, and never
    where a polygon was chosen but recorded nothing, since its point is the same
    account.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    polygons = _memo(_parcels, lat, lon, deadline)
    points = _memo(_points, lat, lon, deadline)
    unit = unit_of(address)
    if unit:
        for fetch in (polygons, points):
            chosen = _choose_unit(fetch, unit, address)
            if chosen:
                return _record(chosen, unit_confirmed=True)
    chosen = _choose_building(polygons, address)
    if chosen is None and address:
        chosen = _choose_building(points, address)
    return _record(chosen, unit_confirmed=False) if chosen else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    return _record_at(lat, lon, address)


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Maryland's assessment roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address (with the reader's unit carried
    over by ``assessor_address``). It confirms the parcel, and its unit picks a
    condominium unit; the lookup still works without one wherever the coordinate
    lands inside a boundary.

    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    roll has no record for. The caller then keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Maryland assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
