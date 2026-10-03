#!/usr/bin/env python3
"""Philadelphia — the Office of Property Assessment's own records, in one SQL query.

The fifth adapter, and the first whose source is a database rather than a map
service. The City publishes the Office of Property Assessment (OPA) roll as a
table, ``opa_properties_public`` — one row per OPA account, 583,783 of them, with
a year built, a livable area, a story count, an exterior condition grade and a
basement code — on its Carto account, which answers arbitrary read-only SQL over
HTTPS with no key. Philadelphia is a city and a county at once, so one table is
the whole of county 42101: roughly 700,000 homes.

One query, two tables
---------------------
The OPA table holds **points**, not parcel shapes: each account carries one
coordinate, inside its lot. A point cannot contain a geocode, so the
"which parcel is this dot inside?" question every other adapter asks has no
answer from that table alone.

The same Carto account also publishes the Water Department's parcel polygons,
``pwd_parcels`` (547,410 shapes). So the lookup is one SQL statement that does both
hops inside the database: find the polygon the geocode falls in, then every OPA
account whose point lies inside that polygon. Measured on 500 random
single-family accounts, 497 have their point inside a PWD polygon — the other
0.6% are unreachable by this route, and that is the whole cost.

Joining on the shape rather than on an id is deliberate. ``pwd_parcels.brt_id``
names *one* OPA account per polygon, and agreed with the account whose point sits
inside it on 456 of 500 sampled rows; a condominium building is one polygon and
hundreds of accounts, and only the spatial join returns all of them — which is
what the unit match below needs.

The buffered query, for a geocode that landed in the roadway, is the same join
over every polygon within 80 m (a bounding-box prefilter in degrees so the index
is used, then the exact ``geography`` distance), so it asks the same question
``_shared.arcgis_parcels`` asks of an ArcGIS layer: *which parcels are near this
dot?* — not *which parcel points are*, which would miss a deep lot whose point
sits back from the street.

Only the coordinate is ever written into the SQL, formatted from a ``float`` and
refused if not finite. Nothing the reader typed reaches the query: the address and
the unit are compared in Python, after the rows arrive.

Condominiums: one account per unit, all at one point
----------------------------------------------------
Philadelphia files a condominium the way the District does — every unit is its
own OPA account with its own year, area and parcel number — and, unlike the
District, puts all of them in the same table at the *same coordinate*. 2001
Hamilton St is several hundred accounts at one point, every one with
``location = "2001 HAMILTON ST"`` and the unit in a separate ``unit`` column.

That makes the containment query return the whole building, which
``_shared.select_parcel`` correctly refuses as ambiguous. The unit the reader
typed (carried past the geocoder by ``_shared.with_unit``) is the only thing that
can pick their home out of it, so candidates are narrowed before the shared
chooser runs:

* The reader gave a unit and exactly that unit exists at their address → only the
  matching rows are offered. The address is still confirmed by the shared
  chooser; the unit only removes rows that are certainly not the reader's home.
* Otherwise → only rows with **no** unit are offered. A condominium address with
  no unit therefore has no candidate and no answer, which is the same refusal
  the District makes and for the same reason: answering with one of three hundred
  units would be the confident guess the selection policy exists to refuse. A
  house with a separately assessed rear unit resolves to the house.

Unit designators compare on letters and digits only ("#3-B" = "3B"), with leading
zeros kept significant, exactly as the District's do.

A condo unit's ``total_livable_area`` is the unit's own (450, 674 and 1,465 sq ft
at three units of one tower, verified live), so — like the District's
``LIVING_GBA`` — it is reported. Its ``number_stories`` is not: OPA's own field
definition says that "in condominiums, this would relate to floor level", which
is not a story count at all.

Ranges: "2018-32 WALNUT ST"
---------------------------
15,909 residential accounts (3%) are filed under a house-number range — one
parcel covering 2018, 2020 … 2032. ``_shared.address_key`` cannot anchor on
"2018-32", so such a row would never confirm. When the reader's house number
falls inside the range *on the same side of the street* (same parity — Philadelphia
puts odd and even numbers on opposite sides), the row is offered under the
reader's number; otherwise under its low number. This can only add a candidate
that genuinely covers the address asked for; two rows claiming it still make the
shared chooser refuse. Extensions never wrap in this table (0 of 25,087 checked),
and a range wider than 200 numbers is treated as malformed and offered only under
its low number.

What the label gets, and what it is refused
-------------------------------------------
Field definitions are quoted from the City's metadata catalog for this dataset
(metadata.phila.gov, "Properties" representation ``55d624fdad35c7e854cb21a4``).

**Year built** — ``year_built``, a string; ``"0"`` (985 rows) and blank are "not
recorded". There is no effective-year column to confuse it with.

``year_built_estimate`` is ``"Y"`` on **407,810 accounts — 70% of the city** — and
"N" on only 290; the rest are blank. The estimates are coarse: 84% of flagged
years end in 0 or 5, against 5.5% of the unflagged "N" ones. They are reported
anyway, and the record's ``data_vintage`` says so in words ("year built is OPA's
estimate"), which the label prints beside the value. The reasoning:

* Refusing them would turn away seven homes in ten for a reason the reader never
  sees, and hand the field back to a census-tract quantile — a span of decades —
  in place of the assessor's own estimate for this building, which is typically
  within five years. That is a straight loss of accuracy.
* The flag is not a clean line between estimated and exact anyway: blank-flag
  rows in the 1900–1940 bins are 97% multiples of five, i.e. estimated in
  everything but name. A rule that trusted "not flagged" would trust them too.
* Other adapters already report assessor years that are estimates without saying
  so. This one at least says so.

The ``observed`` confidence is not lowered — ``AssessorRecord`` has no slot for
"estimated", and adding one is a contract change (see the report).

**Livable area** — reported only where the record is one dwelling: category 1
("Single Family"), no ``other_building = "Y"`` (a second dwelling on the lot),
and not a condominium building account without a unit. Categories 2 ("Multi
Family"), 3 ("Mixed Use") and 14 ("Apartments > 4 Units") describe the whole
building and are refused, never divided.

**Stories** — ``number_stories`` is an integer column, but OPA measures in half
stories ("only measure in half stories, which should be expressed as decimal
(.5)") and the integer column rounds them: 7,140 houses whose building code says
"2.5 STY" carry 3, and 2,481 carry 2. The label's field is a whole number and a
half story is not rounded into one (the District's and Cook's rule). So the
count is reported only where the legacy building code names a **whole** story
count and ``number_stories`` agrees with it — two independent statements that
concur. They disagree often enough to matter ("2 STY" with 1 story on 30,711
houses), and the agreeing set is still 85% of non-condominium single-family
houses (360,999 of 424,816). Never for a
condo unit (floor level, above) or a multi-dwelling record.

**Condition** — ``exterior_condition``, "how the exterior appears based on
observation". The published definition and the data disagree about the
numbering, and the mapping follows the data, for reasons worth setting down:

  The catalog lists 1 NEWER CONSTRUCTION, 2 REHABILITATED, 3 ABOVE AVERAGE,
  then (no 4) 5 AVERAGE, 6 BELOW AVERAGE, 7 VACANT, 8 SEALED, 9 STRUCTURALLY
  COMPROMISED. The data has codes 0–7 plus a single 8, and no 9. It also says
  AVERAGE is the condition of the "majority of properties" — and the majority
  (421,528 of 540,950 graded accounts, 78%) is code **4**, not 5. Read the
  other way, every code from 4 up shifts by one: 5 behaves as BELOW AVERAGE
  (median market value $166k, against $250k at 4 and $423k at 3), 7 co-occurs
  with interior code 7 "Sealed / Structurally Compromised" on 1,386 houses, and
  code 1's median year built is 2021 — "newer construction" exactly. That is
  the numbering of ``interior_condition``'s own published scale (2 New/Rehabbed,
  3 Above Average, 4 Average, 5 Below Average, 6 Vacant, 7 Sealed/Structurally
  Compromised), which is internally consistent.

Mapped, reading DOWN where the scales differ (the reading that claims less wins):

  ==  ==================  ===========  ==========================================
  2   REHABILITATED       ``good``     "superior to most other properties on the
                                       block" — not read up to ``excellent``
  3   ABOVE AVERAGE       ``good``     "well-maintained ... preventive maintenance"
  4   AVERAGE             ``average``  "typical and most common"
  5   BELOW AVERAGE       ``fair``     "excessive deferred maintenance ... minor
                                       fire damage" — not read up to ``poor``,
                                       the same call Cook makes for its own
                                       "Below Average"
  ==  ==================  ===========  ==========================================

Deliberately unmapped: **1** NEWER CONSTRUCTION is a statement about age relative
to the neighbors, not about upkeep, and the year built already carries it;
**6** VACANT is occupancy, not condition; **7** SEALED / STRUCTURALLY COMPROMISED
lumps a boarded-up sound house with one open to the weather, which would be
``poor`` or ``unsound`` respectively and cannot be told apart; **0** is "not
applicable", **8** is one row on a scale that has no 8, blank is not recorded.
``interior_condition`` is not read: the label's condition feeds the
hazard-vulnerability multiplier, which is about the structure, and the exterior
grade is the observation of it.

**Foundation** — ``basements``, a letter code with a published table:
A–D are "Full" (finished, semi-finished, unfinished, unknown finish) →
``full-basement``; E–H are "Partial" → ``partial-basement``. Unmapped: I and J
("Unknown Size"), 0 "None" (no basement says nothing about slab versus crawl
space), and "1"/"2" (12,798 rows), which are not in the published table at all.

**Not read: construction.** The legacy building code ends in a material word
(``ROW 2 STY MASONRY``, ``DET 1.5 STY FRAME``) and was tempting. It is refused for
two measured reasons. It does not distinguish solid masonry from a framed wall
with a masonry face — the brick/brick-frame difference the label's vocabulary
exists for — and 13,822 post-2000 houses, the era of brick-faced frame rows, say
MASONRY. And the code is **stale on new construction**: 3,805 single-family
houses with a median year built of 2021 still carry "VACANT LAND RESIDE < ACRE",
and 229 carry "IND WAREHOUSE MASONRY". A material word from a code that has not
been updated since the lot was empty is not an observation of the house. (The
stories rule above survives this: a stale code cannot name the right whole
story count by accident often enough to matter, and when it does not, the
count is refused.) ``general_construction`` (codes A–J, 1–9) has no published
definition and is not read.

**Not read: heating, rooms, ``unfinished``.** ``type_heater`` and
``number_of_rooms`` have no slot in ``AssessorRecord`` and are not requested;
``unfinished`` is blank on every row.

A year built has to belong to somebody's home
---------------------------------------------
``category_code`` is the dwelling statement: 1 Single Family, 2 Multi Family,
3 Mixed Use (store with dwelling), 14 Apartments > 4 Units hold homes; 4
Commercial, 5 Industrial, 6/12/13 vacant land, 7/8 garages, 9 Hotel, 10 Offices,
11 Special Purpose, 15 Retail and the undocumented 16 (30 rows, all garages,
warehouses and lots) do not, and a year from those is refused like Florida's
zero-dwelling parcels. A blank category is silence, not a statement, and is let
through (none exist today). The building code is NOT used for this — it is stale
on exactly the new houses above — except for the two condominium account types
that are never homes: "CONDO PARKING SPACE" and "CONDO STORAGE UNIT".

The service's clock
-------------------
Measured inside the product path — every request the adapter made while looking
up 300 random homes geocoded through the Census matcher (the verification below,
two traced runs):

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which parcel is this dot inside?"   0.06 s  0.07 s  0.08 s  0.72 s
  "what is within 80 m of this dot?"   0.08 s  0.10 s  0.11 s  0.19 s
  ==================================  ======  ======  ======  ======

(300 containment and 296 buffered requests, zero errors. A separate run of 60
of each at random residential OPA points gave the same picture: medians 0.07 s
and 0.08 s, maxima 0.11 s and 0.16 s.) The buffered query returns up to 657
accounts (226 KB) beside a Center City condo tower and still answers in 0.4 s.

That fits the shared four-second budget and one-second read slice with an order
of magnitude to spare, so this adapter defines no clock of its own; the shared
worst case, 4 + 1 = 5 s, is far inside the host's 12 s per-service allowance
(``config.UPSTREAM_HOST_BUDGET``), and a test pins that sum. A typical lookup
costs ~0.15 s: the Census matcher puts nearly every Philadelphia address on the
street centerline, so 296 of 300 lookups made both requests.

What the adapter is worth, end to end
-------------------------------------
450 residential accounts drawn at random from the table itself (categories 1, 2,
3 and 14, condo units included and typed with their unit, ranges typed by their
low number), geocoded through the Census one-line matcher exactly as the product
does, routed (every geocode returned 42101), and looked up, in three runs of 150:

  ===========  =========  ========  ============  ===========  ==============
  run          geocoded   resolved  wrong parcel  year exact   sqft exact
  ===========  =========  ========  ============  ===========  ==============
  1            149        123       **0**         123 / 123    111 / 111
  2            150        140       **0**         140 / 140    125 / 125
  3            150        133       **0**         133 / 133    119 / 119
  ===========  =========  ========  ============  ===========  ==============

Run 1 was not yet tracing requests, and 13 of its misses resolved on a re-run
with the code unchanged — transient request failures, which ``get_json`` reports
through ``utils.note_dropped`` so the label is not cached. Runs 2 and 3 traced
every request and saw none fail. Their 27 misses are the shared chooser
declining, never this adapter guessing:

* **The Census matcher adds or drops a directional that OPA does not write** — 14
  of 27. "1511 SHUNK ST" in OPA is "1511 W SHUNK ST" from the geocoder; likewise
  W PORTER, N HOPE, N MASCHER, E CARDEZA, and "901 N PENN ST" geocoded as "901
  PENN ST". ``_shared.same_address`` keeps directionals significant on purpose
  (213 W Main and 213 E Main are different houses), so these are refused. This is
  the largest single loss, 14 of 300 homes (4.7%); a fix belongs in the shared
  comparison, not here.
* **The geocode lands more than 80 m from its own parcel** — 10 (measured 81 to
  346 m; one matched into a different ZIP altogether).
* **The two sources disagree on the street type** — 3 ("1501 LOTT AVE" against
  the geocoder's "LOTT ST", NAPFLE, CHAMPLOST).

Ranges and condominium units both resolved in the sample (815 ARCH ST #302
against "815-37 ARCH ST" unit 302; 441 TOMLINSON RD #E8).

Terms of use
------------
The dataset is published under the "City of Philadelphia License", whose text is
the metadata catalog's Terms of Use (metadata.phila.gov/#help/help-faqs/
what-are-the-terms-of-use/): the City "reserves all rights in the database and
any data contained therein", use "does not constitute a transfer of ... any title
or interest", the data is "as is" without warranty, and the user holds the City
harmless. It grants no explicit right to redistribute and imposes no attribution
or non-commercial condition. The separate phila.gov *website* terms
(phila.gov/terms-of-use/) prohibit commercial republication of the website's
pages; they are scoped to "the www.phila.gov Website" and its pages, not to the
open-data API. So: querying live and caching in-process, never bundling — the
posture ``base.py`` records for Cook — fits; a bulk copy of the table would assert
a right the license reserves.

Privacy, and why the field list is short
----------------------------------------
``opa_properties_public`` carries ``owner_1``, ``owner_2``, five ``mailing_*``
columns, ``sale_price``, ``sale_date``, ``market_value`` and the taxable values;
``pwd_parcels`` carries ``owner1`` and ``owner2``. None of it is an input to any
dimension. Thirteen OPA columns are selected by name, none from the PWD table;
``*`` is never used. Nothing from this source is written into the repository.
"""

from __future__ import annotations

import logging
import math
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

# Philadelphia is a consolidated city-county: one county code, and the City is its
# only assessor.
COUNTY_FIPS = frozenset({"42101"})          # Philadelphia County, PA

NAME = "Philadelphia Office of Property Assessment"
ATTRIBUTION = ("City of Philadelphia Office of Property Assessment "
               "(OpenDataPhilly via Carto, keyless)")
DATA_VINTAGE = "Philadelphia OPA property characteristics (refreshed nightly)"

SQL_URL = "https://phl.carto.com/api/v2/sql"

# Only what the label scores, plus what decides whether a value describes one home:
# the category, the unit, the second-building flag, and the building code (for the
# story cross-check and the two condo account types that are never homes). See
# "Privacy" in the module docstring for what is never selected.
_COLUMNS = ("parcel_number", "location", "unit", "category_code",
            "building_code_description", "year_built", "year_built_estimate",
            "total_livable_area", "number_stories", "exterior_condition",
            "basements", "other_building", "assessment_date")
_SELECT = ", ".join(f"o.{c}" for c in _COLUMNS)

# The join both queries share: every OPA account whose point lies inside a PWD
# parcel polygon. See "One query, two tables".
_FROM = ("FROM pwd_parcels p JOIN opa_properties_public o "
         "ON ST_Contains(p.the_geom, o.the_geom)")

# Bounding-box half-width for the buffered query, in degrees, so the spatial index
# narrows the polygons before the exact geography distance runs. 0.0015° is
# ~167 m of latitude and ~128 m of longitude at Philadelphia's 40°N — wider than
# the 80 m radius in both directions, so it never cuts a candidate off.
_BBOX_DEG = 0.0015

# category_code values that hold dwellings. See "A year built has to belong to
# somebody's home" in the module docstring for the others and why.
_DWELLING_CATEGORIES = frozenset({"1", "2", "3", "14"})
_SINGLE_FAMILY = "1"
_NEVER_A_HOME = frozenset({"CONDO PARKING SPACE", "CONDO STORAGE UNIT"})

# OPA's exterior_condition, read by the numbering the data uses (which is the
# interior scale's) — see "Condition" in the module docstring for why that is not
# the catalog's printed numbering, and for every unmapped code.
_CONDITION = {
    "2": "good",        # REHABILITATED — read down from excellent
    "3": "good",        # ABOVE AVERAGE
    "4": "average",     # AVERAGE — 78% of graded accounts
    "5": "fair",        # BELOW AVERAGE — read down from poor
}

# OPA's published basement table. I/J (unknown size), 0 (none — slab or crawl, not
# said) and the unpublished 1/2 are deliberately absent.
_BASEMENT = {
    "A": "full-basement", "B": "full-basement",
    "C": "full-basement", "D": "full-basement",
    "E": "partial-basement", "F": "partial-basement",
    "G": "partial-basement", "H": "partial-basement",
}

# "2018-32 WALNUT ST": a parcel filed under a house-number range.
_RANGE_RE = re.compile(r"^(\d+)-(\d+)(\s+\S.*)$")
_MAX_RANGE_SPAN = 200

# The whole-number story count in a legacy building code: "ROW 2 STY MASONRY".
# "2.5 STY" and "5+ STY" deliberately do not match.
_STY_RE = re.compile(r"(?:^|\s)(\d+)\s+STY\b")


# --- the query ----------------------------------------------------------------


def _point_sql(lat: float, lon: float) -> str:
    """The geocode as a PostGIS point. The only value ever written into the SQL.

    Formatted from a float, never from a string, and refused if not finite: a
    ``nan`` would format as the bare word ``nan`` and reach the database as an
    identifier. Raising here is safe — it lands in the fail-open path.
    """
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("non-finite coordinate")
    return f"ST_SetSRID(ST_MakePoint({lon:.7f}, {lat:.7f}), 4326)"


def _sql(lat: float, lon: float, distance_m: float = 0) -> str:
    """Containment (``distance_m == 0``) or the buffered query, as one statement."""
    pt = _point_sql(lat, lon)
    if not distance_m:
        return f"SELECT {_SELECT} {_FROM} WHERE ST_Contains(p.the_geom, {pt})"
    radius = float(distance_m)
    if not (math.isfinite(radius) and radius > 0):
        raise ValueError("bad search radius")
    return (f"SELECT {_SELECT} {_FROM} "
            f"WHERE p.the_geom && ST_Expand({pt}, {_BBOX_DEG}) "
            f"AND ST_DWithin(p.the_geom::geography, {pt}::geography, {radius:.1f})")


def _parcel_number(row: dict) -> str | None:
    pid = str(row.get("parcel_number") or "").strip()
    return pid or None


def _rows(lat: float, lon: float, distance_m: float = 0,
          *, deadline: float) -> list[dict]:
    """OPA accounts in (or near) the parcel at this point — real records only.

    A row with no parcel number is a record of nothing and is dropped before the
    choice, as Florida drops its placeholder polygons. An account whose point sits
    in two overlapping polygons comes back twice; it is one candidate, not two,
    and counting it twice would make it ambiguous with itself.
    """
    body = _shared.get_json(SQL_URL, {"q": _sql(lat, lon, distance_m)}, deadline)
    seen, out = set(), []
    for row in (body or {}).get("rows") or []:
        pid = _parcel_number(row or {})
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        out.append(row)
    return out


# --- addresses and units ------------------------------------------------------


def _range_high(low: str, ext: str) -> int | None:
    """The top of a "2018-32" range, or None if the range is malformed."""
    lo = int(low)
    high = int(ext) if len(ext) >= len(low) else int(low[:-len(ext)] + ext)
    if high <= lo or high - lo > _MAX_RANGE_SPAN:
        return None
    return high


def _address_of(row: dict, asked: str | None = None) -> str | None:
    """The account's street address, as the comparison should see it.

    A ranged location is offered under the reader's own number when that number
    is inside the range on the same side of the street, and under its low number
    otherwise. See "Ranges" in the module docstring.
    """
    loc = " ".join(str(row.get("location") or "").split())
    if not loc:
        return None
    m = _RANGE_RE.match(loc)
    if not m:
        return loc
    low, ext, rest = m.groups()
    high = _range_high(low, ext)
    key = address_key(asked) if asked else None
    if high is not None and key:
        n, lo = int(key[0]), int(low)
        if lo <= n <= high and (n - lo) % 2 == 0:
            return f"{n}{rest}"
    return f"{low}{rest}"


def _norm_unit(value) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _unit(row: dict) -> str:
    """The account's own unit designator, normalized; "" when it has none."""
    return _norm_unit(row.get("unit"))


def _candidates(rows: list[dict], address: str | None) -> list[dict]:
    """The rows that could be the reader's home. See "Condominiums" above.

    Only ever removes rows, so it can turn "ambiguous" into "one candidate" but
    never let a wrong account through: the address confirmation in
    ``select_parcel`` still runs on whatever is left.
    """
    typed = _norm_unit(unit_of(address))
    if typed:
        mine = [r for r in rows if _unit(r) == typed]
        if any(same_address(address, _address_of(r, address)) for r in mine):
            return mine
    return [r for r in rows if not _unit(r)]


def _row_at(lat: float, lon: float, address: str | None = None,
            *, deadline: float | None = None) -> dict | None:
    """The OPA account this point and address belong to, or None.

    The choice itself is ``_shared.select_parcel``'s, shared by every
    jurisdiction; see that function for why it never takes the nearest parcel.
    No locality trim is needed: ``location`` is the bare street address
    ("1234 MARKET ST"), with the city in no column at all.
    """
    deadline = deadline_from(deadline)
    return select_parcel(
        lambda d: _candidates(_rows(lat, lon, d, deadline=deadline), address),
        address, lambda r: _address_of(r, address))


# --- the translation ----------------------------------------------------------


def _category(row: dict) -> str:
    return str(row.get("category_code") or "").strip()


def _building_code(row: dict) -> str:
    return " ".join(str(row.get("building_code_description") or "").upper().split())


def _says_a_home_is_here(row: dict) -> bool:
    """Whether OPA's own category says this account holds a dwelling.

    An explicit non-dwelling category is a statement — a shop, a garage, a lot —
    and a year built from it would describe a building nobody lives in. A blank
    category is silence and is let through, the same distinction Florida and
    Connecticut draw on their dwelling counts.
    """
    if _building_code(row) in _NEVER_A_HOME:
        return False
    category = _category(row)
    return not category or category in _DWELLING_CATEGORIES


def _is_condo(row: dict) -> bool:
    return "CONDO" in _building_code(row)


def _one_dwelling(row: dict) -> bool:
    """Whether this account is exactly one home: the basis for area and stories.

    Single-family category, no second dwelling on the lot, and not a condominium
    building's account without a unit (whose area may be the building's). A
    condo *unit* account passes — its area is the unit's own — but see
    :func:`_stories` for why its story count does not.
    """
    if _category(row) != _SINGLE_FAMILY:
        return False
    if str(row.get("other_building") or "").strip().upper() == "Y":
        return False
    return not (_is_condo(row) and not _unit(row))


def _year_built(row: dict) -> int | None:
    raw = str(row.get("year_built") or "").strip()
    if not raw.isdigit():
        return None
    year = int(raw)
    # 0 is OPA's "not recorded" (985 accounts), not the year zero.
    if not (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100):
        return None
    return year if _says_a_home_is_here(row) else None


def _sqft(row: dict) -> float | None:
    area = num(row.get("total_livable_area"))
    if area is None or area <= 0 or not _one_dwelling(row):
        return None
    return area


def _stories(row: dict) -> int | None:
    """``number_stories`` where the building code names the same whole number.

    The integer column rounds OPA's half stories; see "Stories" in the module
    docstring. A condominium unit's count is its floor level, not a story count,
    and is never reported.
    """
    if not _one_dwelling(row) or _unit(row) or _is_condo(row):
        return None
    count = num(row.get("number_stories"))
    m = _STY_RE.search(_building_code(row))
    if count is None or count <= 0 or not float(count).is_integer() or not m:
        return None
    return int(count) if int(m.group(1)) == int(count) else None


def _vintage(row: dict, year_built: int | None) -> str:
    """What this record reflects, dated from the row, and honest about estimates.

    ``assessment_date`` is when OPA last changed the account. The estimate note
    is attached only when a year is actually reported and OPA flags it, because
    the label prints this beside every value from the record.
    """
    out = DATA_VINTAGE
    date = str(row.get("assessment_date") or "").strip()
    if re.match(r"^\d{4}-\d{2}", date):
        out += f", account last assessed {date[:7]}"
    if year_built is not None and \
            str(row.get("year_built_estimate") or "").strip().upper() == "Y":
        out += "; year built is OPA's estimate"
    return out


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _row_at(lat, lon, address)
    if not row:
        return None
    year_built = _year_built(row)
    fields = {
        "year_built": year_built,
        "sqft": _sqft(row),
        "stories": _stories(row),
        "condition": _CONDITION.get(str(row.get("exterior_condition") or "").strip()),
        "foundation": _BASEMENT.get(str(row.get("basements") or "").strip().upper()),
    }
    # An account that is not a home contributes nothing: its condition and
    # basement describe a shop as surely as its year does.
    if not _says_a_home_is_here(row):
        return None
    # An account that matched but recorded nothing the label reads contributed
    # nothing; keep the fact-free record out of the cache. The registry drops it
    # either way.
    if all(v is None for v in fields.values()):
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row, year_built),
        parcel_id=_parcel_number(row),
        # No construction: see "Not read: construction" in the module docstring.
        **fields,
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Philadelphia's assessment roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address with the reader's unit carried
    over (``_shared.with_unit``). It confirms the account and, for a
    condominium, picks the unit; without one the lookup still answers wherever
    the point lands in a parcel holding exactly one account.

    Fails open on everything — a timeout, a Carto error body, a renamed column.
    The caller keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Philadelphia assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
