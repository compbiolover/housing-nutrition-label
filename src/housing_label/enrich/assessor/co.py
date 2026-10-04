#!/usr/bin/env python3
"""Colorado — five Denver-metro county assessors, one per county, behind one module.

Colorado has no statewide parcel roll, so like Ohio and Utah this module is a
per-county table (``COUNTIES``), each county read from its own office's service.
Two of them carry the facts on the parcel itself (one request, Florida's shape);
three publish the parcel map and the characteristics table separately, joined by
the county's account or parcel number (two requests, the District's shape).

Which counties, and why only these
----------------------------------
Measured 2026-10-04. ACS housing units from this repository's own county table.

  =========  =====  =======  ====  =================================================
  county     FIPS     units  hops  source
  =========  =====  =======  ====  =================================================
  Denver     08031  359,581     1  Assessment Division parcels, ``ODC_PROP_PARCELS_A``
                                   (City of Denver Open Data Catalog), daily
  Jefferson  08059  253,574     1  Jefferson County ``Parcel`` layer 20 (the
                                   assessor's structure fields on the parcel)
  Adams      08001  195,793     2  ``Parcels`` -> ``Property_Improvements`` (weekly)
  Douglas    08035  144,432     2  ``Parcels_A_view`` (daily) -> the open-data
                                   ``Property_Improvements_Data`` table
  Boulder    08013  144,729     2  ``PARCELS_OWNER`` (nightly) -> the assessor's
                                   ``BLDG_ATTRIBUTES`` table
  =========  =====  =======  ====  =================================================

1,098,109 of Colorado's 2,589,053 units (42%). Year fill on homes is high in all
five: Denver 206,411 of 240,437 parcels (every single-family class, 41,852 of
43,998 condominium units, 29,194 of 31,004 rowhouses, plus the duplexes and
apartment houses dated on the commercial schedule — see Denver's traps);
Jefferson 203,846 dwelling parcels with a year; Adams 155,144, Douglas 133,485
and Boulder 109,685 dwelling improvement rows with one.

**Not covered**, and so not claimed. **Arapahoe** (08005, 269,345 units) is held
back for its terms: the assessor's Data Download Agreement
(gis.arapahoegov.com/assessordataexport/) says "The Data is protected by the
copyright laws of the United States of America and is being furnished with all
rights reserved", and the year built is published only in the assessor's own
map service (``CustomCAMA_WM``), never in the county's open-data service.
**Weld** (08123) publishes its year on account POINTS, not parcels, under a
license note that grants nothing ("developed solely for internal use only by
Weld County"). **Larimer** (08069): the county's parcel layer carries no year or
area, and no keyless characteristics table was found. **El Paso** was ruled out
earlier (``research/parcel-level-data-research.md`` §4.1).

Each county's traps
-------------------
**Denver writes the implicit "N".** This is a documented local convention, not a
geocoder quirk: Denver's roll writes "2701 N WOLFF ST" on every north-half
street, and the Postal Service and the Census matcher never write that N, while
both do write the S of the south half. Tested on twin addresses: typed "740 S
PEARL ST" and "740 PEARL ST" came back 2.8 km apart, each on its own half, as did
1500 S/N Clarkson and 300 S/N Downing, and typed "1500 N CLARKSON ST" came back
"1500 CLARKSON ST" at the north twin. So in Denver, and only there, a roll N is
set aside for a query that carries no directional (``_agrees``). An S is never
ignored — not on the roll, not in the query — and neither is an E or a W. It is
the module's only directional rule; see Douglas for why there is no other.
Without it most of the city could never confirm.

**Denver dates multi-unit homes on the commercial schedule.** Buildings of two or
more units are appraised as commercial, so 2,767 of 2,776 duplexes, the
triplexes and apartment houses, and 1,091 condominium units carry their year in
``COM_ORIG_YEAR_BUILT``. That column is read only on a RESIDENTIAL class; on a
shop it dates the shop.

**Denver stacks condominiums.** Every unit — and every garage and parking space,
filed as units ("GAR", "PRK") — shares the building's polygon, and the building
is filed once more with no unit, as the project (2525 S DAYTON WAY: 148 unit
records and one with ``TOT_UNITS`` 148). A typed unit picks its own record and
the project record is set aside. With no unit typed, no unit record can be
chosen (they are left out of the containment answer, and a stack of them at one
address is ambiguous in the buffer); where the project record is there, it
answers for its building — the building's year, which is every unit's, and no
area. One complex, 710 S ALTON WAY, has more than 2,000 unit records within
80 m, which truncated the buffered page; so the buffered query asks only for rows
carrying the query's house number (``number_where``), which cannot change the
answer (a row with another number never confirms) but keeps the page short. The
"VACANT LAND /GENERAL COMMON ELEMENTS" parcel laid over each complex is dropped
before the choice.

**Jefferson's unit count is not a count.** ``STTNBRUNT`` is 0 on 207,333 of the
208,875 parcels with a year — single-family houses included — so it is never
read as "no dwelling" and is not requested; the structure type (``STTSTRC``)
decides instead. 859 single-family parcels carry a second dwelling structure, and
where its year differs no year is reported. Right-of-way polygons carry the
parcel id "ROW" and nothing else.

**Adams, Douglas and Boulder list every building.** The second hop returns one
row per building (Boulder one per building section): the house, its detached
garage, the barn. Only dwelling rows count; the year is reported only where every
dwelling on the record agrees on one, and area, wall and condition only where
there is exactly one dwelling. Boulder files a single-family account's sheds and
garages under the account's own class ("SINGLE FAM RES IMPROVEMENTS") with zero
finished area, which is how they are told apart. Douglas files 6,397 rows with
``NO_OF_UNIT`` 0, mostly outbuildings: the county saying that building holds no
dwelling. Boulder also writes one parcel row per street address of an account;
the rows are merged, and the record is confirmable under either address.

**Douglas writes no leading directional** on 120,758 of its 131,089 residential
parcels, where the Census matcher adds the one TIGER carries ("8552 FORREST ST,
Highlands Ranch" comes back "8552 S FORREST ST"). Those addresses are refused,
deliberately. This codebase never forgives a directional written on one side
only (see ``nc.py`` and ``ut.py``): the matcher is measured to ignore, drop and
swap directionals, so "100 W MAIN" and "100 E MAIN" can come back as one point,
and against a roll that writes the house with no directional the adapter would
confirm whichever twin happened to be near. The cost was measured: a run that
forgave the matcher's added directional in Douglas resolved 5 more of its 36
geocoded sample homes (30 against 25 — see "What the adapter is worth"), all
in Highlands Ranch and the Littleton part of the county, and none of
them wrong; the rule was removed all the same, because zero wrong in a sample of
36 is not evidence that the twin case cannot happen. The same refusal applies in
every county, and the other direction too (Adams: typed "3569 W 89TH AVE" came
back "3569 89TH AVE").

What each county contributes
----------------------------
* **Year built**, everywhere: the actual (original) year. Effective and remodel
  years (Douglas's ``REMODELED_YEAR``, Adams's and Boulder's equivalents) are
  never requested.
* **Floor area** — one home in one building only: a single-family class with one
  dwelling and no unit in the situs. Denver's ``RES_ABOVE_GRADE_AREA`` (above
  grade), Jefferson's ``STTGRSAREA`` (its "gross" area; basement area is a
  separate column), Adams's ``sf``, Douglas's ``IMPROVEMENT_SF``, and Boulder's
  ``FinishedSqft``, which is the above-grade finished area (3,026 on R0034667 =
  2,033 first floor + 993 second; the 960 sq ft finished walk-out basement is
  excluded, checked against the county's area breakdown). A rowhouse or
  condominium unit is one dwelling in a building of several, and is refused.
  Nothing is divided by a unit count.
* **Exterior wall** — Jefferson, Adams, Douglas (see ``_WALL`` and
  ``_JEFFERSON_WALL`` for what is translated and what is deliberately not).
* **Condition** — Douglas only (``_DOUGLAS_CONDITION``).
* No story count: Douglas's ``NO_OF_STORY`` records a "1 1/2 Story" townhouse as
  1, and the other counties publish only style words. No foundation type: the
  basement fields record an area or a flag, not full versus partial.

Timing
------
Measured at the 209 geocoded sample homes, twice (418 points), through the
product's HTTP session, with each county's own field list:

  =========  ======================  ======================  ======================
  county     contain med/p95/max     buffer  med/p95/max     2nd hop med/p95/max
  =========  ======================  ======================  ======================
  Denver     0.13 / 0.16 / 0.59 s    0.15 / 0.22 / 0.37 s    —
  Jefferson  0.15 / 0.17 / 0.65 s    0.16 / 0.17 / 0.21 s    —
  Adams      0.12 / 0.17 / 0.62 s    0.16 / 0.38 / 1.48 s    0.16 / 0.22 / 0.25 s
  Douglas    0.14 / 0.17 / 0.60 s    0.14 / 0.21 / 0.37 s    0.20 / 0.29 / 0.46 s
  Boulder    0.10 / 0.12 / 0.55 s    0.11 / 0.12 / 0.13 s    0.11 / 0.13 / 0.15 s
  =========  ======================  ======================  ======================

Responses are at most 139 KB (a Denver condominium stack). Four counties keep the
SHARED clock (a one-second read slice, a four-second budget). **Adams** gets its
own: across the measurement and the verification runs it answered past one
second on all three request kinds (buffer 1.48 s, containment 0.87 s, second hop
0.84 s), and one verification run lost four homes to the shared slice. So a
2.5-second slice and a 5-second budget, which covers the slowest observed
three-request lookup (0.87 + 1.48 + 0.84 = 3.2 s) with room; 5 + 2.5 = 7.5 s is
under ``config.UPSTREAM_HOST_BUDGET``, pinned by a test. Denver once took 11.2 s
to answer a containment query (one of roughly 400 Denver requests); no clock
inside the host's allowance covers that, and that lookup fails open, uncached.

What the adapter is worth, end to end
-------------------------------------
215 homes drawn at random from the sources themselves (random object ids among
dwelling rows with a year: 50 Denver, 45 Jefferson, 40 each elsewhere), typed as
the roll writes them with city and ZIP, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up:

  =========  ======  ========  ========  =====  ==========  ===========
  county     sample  geocoded  resolved  wrong  year exact  sqft exact
  =========  ======  ========  ========  =====  ==========  ===========
  Denver         50        49        45      0       45/45        30/30
  Jefferson      45        45        41      0       41/41        31/31
  Adams          40        40        34      0       34/34        31/31
  Douglas        40        36        25      0       25/25        23/23
  Boulder        40        39        33      0       33/33        32/32
  **all**     **215**   **209**   **178**  **0**   **178/178**  **147/147**
  =========  ======  ========  ========  =====  ==========  ===========

Every geocode routed to the sampled county. 85% of geocoded homes resolved,
**none to the wrong parcel**, and every year and floor area reported equals the
sampled row's. A wall came back on 87, Douglas's condition on 25. A lookup took
a median of 0.31 s (p95 0.40 s, slowest 1.38 s).

The 31 that did not resolve: 18 geocodes more than 80 m from their own parcel
(92 m and 126 m in Denver, up to 200 m on Douglas's curving subdivision streets
and in the foothills), most with the point inside a neighbor's lot whose address
disagrees; 10 with a directional written on one side only, refused by design
(see Douglas above): five Douglas homes where the matcher added one the roll
does not write ("8552 S FORREST ST", "10434 S HOLLYHOCK CT", "4864 E APOLLO BAY
DR", "7070 W PINEVIEW DR", "10575 S KALAHARI CT"), one Douglas roll writing "N
APACHE RD" where the matcher writes none, Boulder's added "N 69TH ST", and three
the matcher dropped (Adams "W 89TH AVE" and "W 135TH CT", Boulder "W 10TH
AVE"); 2 street addresses shared by several records with no unit typed (Denver's
3136 W 19TH AVE is three rowhouses, Boulder's 6223 WILLOW LN a condominium
stack); and 1 Boulder point inside 29 overlapping parcels.

An earlier run on the same sample, with a rule that set aside a directional the
matcher added where the Douglas roll writes none, resolved 183 (Douglas 30 of
36), with the same zero wrong; that rule was removed (see Douglas above). The
first run, before the condominium-project, number-filter, merged-address and
Adams-clock rules, resolved 170 of 199 with the same zero wrong; each of those
rules was added for a miss it explains.

License and terms
-----------------
* **Denver** — CC BY 3.0. The Open Data Catalog's terms
  (denvergov.org/opendata/termsofuse): "You are free to copy, distribute,
  transmit and adapt the data, as long as you credit the 'City of Denver Open Data
  Catalog'". The layer's item adds an as-is disclaimer and an indemnity.
* **Jefferson** — CC BY 4.0, on the layer's item and on jeffco.us/3165 ("covered
  by the Creative Commons Attribution 4.0 International License").
* **Adams** — CC BY 4.0 on both items ("This work is licensed under a Creative
  Commons Attribution 4.0 International License"), with an as-is disclaimer.
* **Douglas** — CC BY-SA 4.0 on the open-data improvements table ("free to:
  Share ... Adapt ... for any purpose, even commercially"); share-alike binds an
  adapted database that is redistributed, which this adapter never makes — it
  queries facts and caches them in process. The daily parcel view carries no
  license text.
* **Boulder** — CC BY 4.0, on the county's own item for the assessor's property
  data. The assessor's download page adds that the data "has been developed
  solely for internal use only by Boulder County, and the county makes no
  warranties": a statement of why no warranty is given, not a restriction on
  use — unlike Arapahoe's identical sentence, which comes with "all rights
  reserved". This is the reading to confirm before a commercial launch.

The posture is the one every adapter takes regardless — query live, cache in
process, bundle nothing, never fetch owner data — and each record's ``source``
names its county office and license, as the attribution clauses ask.

What is never read
------------------
Every parcel layer here carries owner names and mailing addresses (Denver's and
Adams's also sale prices and values). Each county's ``fields`` is an explicit,
short list and the shared helper refuses ``*``. Nothing from these sources is
written into the repository.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, same_address, select_parcel,
    unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Colorado county assessors (Denver metro)"
ATTRIBUTION = ("Colorado county assessors' parcel records (Denver via the City of "
               "Denver Open Data Catalog, CC BY 3.0; Jefferson, Adams and Boulder, "
               "CC BY 4.0; Douglas, CC BY-SA 4.0; keyless)")
DATA_VINTAGE = "Colorado county assessor records, queried live"

# ── the services ───────────────────────────────────────────────────────────────

#: Denver's assessment parcels, with the residential and commercial
#: characteristics on the parcel itself (one request).
DENVER_URL = ("https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services"
              "/ODC_PROP_PARCELS_A/FeatureServer/245/query")
#: Jefferson County's parcels, with up to four structures' characteristics on
#: the parcel itself (one request).
JEFFERSON_URL = ("https://gisportal.jeffco.us/server2/rest/services"
                 "/Parcel/FeatureServer/20/query")
#: Adams County's parcels (situs, parcel number) and, keyed by the parcel number,
#: its "Property Improvements" table (two requests).
ADAMS_URL = ("https://services3.arcgis.com/4PNQOtAivErR7nbT/arcgis/rest/services"
             "/Parcels/FeatureServer/0/query")
ADAMS_IMPROVEMENTS_URL = ("https://services3.arcgis.com/4PNQOtAivErR7nbT/arcgis/rest"
                          "/services/Property_Improvements/FeatureServer/0/query")
#: Douglas County's parcels (situs, account) and, keyed by the account, its
#: "Property Improvements Data" table (two requests).
DOUGLAS_URL = ("https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services"
               "/Parcels_A_view/FeatureServer/0/query")
DOUGLAS_IMPROVEMENTS_URL = ("https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest"
                            "/services/OpenData/FeatureServer/8/query")
#: Boulder County's nightly parcel layer (situs, account) and, keyed by the
#: account, the assessor's building-attributes table (two requests).
BOULDER_URL = ("https://maps.bouldercounty.org/arcgis/rest/services"
               "/PARCELS/PARCELS_OWNER/FeatureServer/0/query")
BOULDER_BUILDINGS_URL = ("https://maps.bouldercounty.org/arcgis/rest/services"
                         "/CamaView/PropSearch_BLDG_ATTRIBUTES/MapServer/1/query")
#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (a direct call). The registry always says.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services"
              "/TIGERweb/State_County/MapServer/1/query")


# ── small readers ──────────────────────────────────────────────────────────────


def _text(value) -> str:
    """A column as a stripped, space-normalized upper-case string ("" if blank)."""
    return " ".join(str(value or "").split()).upper()


def _year(value) -> int | None:
    """An actual year built, or None for 0, blank, a fraction or an implausible
    year. The floor is the scorer's own (``EARLIEST_PLAUSIBLE_YEAR``)."""
    year = num(value)
    if year is None or not float(year).is_integer():
        return None
    return int(year) if EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None


def _area(value) -> float | None:
    area = num(value)
    return area if area is not None and area > 0 else None


def _house_number(value) -> str:
    """A house number as written, with Jefferson's zero padding ("06390") removed."""
    raw = str(value or "").strip()
    return str(int(raw)) if raw.isdigit() else raw


def _street(*parts) -> str | None:
    """Address components joined into one street address, blanks skipped."""
    tokens = [" ".join(str(p).split()) for p in parts if p is not None]
    joined = " ".join(t for t in tokens if t)
    return joined or None


def _date_of(ms) -> str | None:
    """An ArcGIS epoch-milliseconds date as YYYY-MM-DD, or None if implausible."""
    value = num(ms)
    if not value:
        return None
    try:
        day = datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return day.isoformat() if 1990 <= day.year <= 2100 else None


def _norm_unit(unit) -> str:
    return str(unit or "").strip().lstrip("#").strip().casefold()


@dataclass(frozen=True)
class Facts:
    """What one county's record says, already in the label's vocabulary."""

    year_built: int | None = None
    sqft: float | None = None
    construction: str | None = None
    condition: str | None = None

    def empty(self) -> bool:
        return all(v is None for v in (self.year_built, self.sqft,
                                       self.construction, self.condition))


# ── exterior walls ─────────────────────────────────────────────────────────────
#
# Adams and Douglas write the same CAMA wall vocabulary ("<structure> <cladding>")
# that Utah's Washington and Box Elder counties do, and the readings here are the
# ones ``ut._CONSTRUCTION`` settled for that vocabulary. Measured on Adams's
# 170,597 improvement rows: Frame Siding 105,563; Frame Masonry Veneer 38,927;
# blank 15,196; Frame Stucco 3,416; Frame Vinyl 2,705; Frame Brick Veneer 1,629;
# Frame Shingle 812; Frame Hardboard 545; Frame Plywood 513; Masonry Common Brick
# 253; Masonry Concrete Block 102; Frame Stone Veneer 88. Douglas's 151,440 rows
# have the same shape (Frame Siding 114,480; Frame Masonry Veneer 9,885; ...).
_WALL = {
    "FRAME SIDING": "frame",
    "WOOD FRAME SIDING": "frame",
    "FRAME STUCCO": "frame",
    "FRAME SHINGLE": "frame",
    "FRAME HARDBOARD": "frame",
    "FRAME PLYWOOD": "frame",
    "FRAME ALUMINUM": "frame",
    "FRAME VINYL": "vinyl",
    "FRAME BRICK VENEER": "brick-frame",
    "MASONRY COMMON BRICK": "brick",
    "MASONRY CONCRETE BLOCK": "block",
    "MASONRY STUCCO BLOCK": "block",
}
# Deliberately unmapped, each for a reason (Utah's, for the same words):
#   FRAME MASONRY VENEER   a framed wall faced in brick OR stone; the label has
#                          brick-frame and no stone-frame, so the face is a guess
#   FRAME STONE VENEER     no stone-frame value; `stone` asserts solid masonry
#   LOG, FRAME RUSTIC LOG, no log value in the label's vocabulary
#     PINE FINISHED CABIN
#   METAL SIDING, STUCCO,  the cladding is named and the structure is not
#     HARDBOARD SHEET, LAP SIDING, CONCRETE BLOCK (Adams's 16 bare rows are
#     kept out with the rest: "Masonry Concrete Block" is the vocabulary's
#     spelling, and a bare one is a different keying whose structure is unsaid)
#   POLE FRAME METAL SIDING, STEEL FRAME SIDING  agricultural and commercial
#                          frames, not a dwelling's wall

# Jefferson's STTTYPCNS is "<code> - <material>-<quality>": "FR - Frame-Average",
# "BR - Brick-Good". Measured over the 208,875 parcels with a year built: FR
# 120,107; BR 55,299; FB (Combination) 23,078; commercial classes A-D and S
# 7,972; MD (Pre-Fab Modular) 202; LG (Log) 351.
_JEFFERSON_WALL = {
    "FR": "frame",
    # A wall recorded as brick. Solid brick or a brick veneer on frame the code
    # does not say — the same knowingly lossy reading Ohio makes for Montgomery's
    # BRICK and Cook for its "Masonry", paid for in confidence
    # (base.TRANSLATED), not coverage.
    "BR": "brick",
}
# Deliberately unmapped: FB "Combination" (part frame, part masonry of an unnamed
# kind), MD modular, LG log, and the commercial construction classes A, B, C, D
# and S, which describe a building's structural frame, not a house's wall.


# ── per-county configuration ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Buildings:
    """A county's second hop: the characteristics table, keyed by the parcel."""

    url: str
    key: str                       # the parcel-layer column carrying the join key
    column: str                    # the table column it is matched against
    fields: tuple[str, ...]


@dataclass(frozen=True)
class County:
    """Everything that is a fact about one county's sources. See the docstring."""

    name: str
    url: str
    #: The explicit outFields list for the parcel layer. Every one of these layers
    #: also carries owner names and mailing addresses; none is ever listed here.
    fields: tuple[str, ...]
    pid: str                                   # the record's identifier column
    street: Callable[[dict], str | None]       # the situs, with no unit
    unit: Callable[[dict], str | None]         # the situs's unit, if any
    #: The parcel row says nothing anybody lives in stands here (vacant land,
    #: common elements, rights of way). Dropped before the parcel is chosen.
    no_home: Callable[[dict], bool]
    #: The record's facts: (parcel row, building rows or None for one hop).
    read: Callable[[dict, list | None], Facts]
    attribution: str
    vintage: Callable[[dict, list | None], str]
    #: The columns that spell the situs. Two rows of one record may differ in
    #: these (a record with two street addresses) and in nothing else.
    address_fields: tuple[str, ...] = ()
    #: The where clause selecting one house number, sent with the buffered query
    #: only; see _parcel_at.
    number_where: Callable[[str], str] | None = None
    buildings: Buildings | None = None
    #: Denver writes the implicit "N" of its north-half streets; see _offer.
    implicit_north: bool = False
    read_slice: float = _shared._READ_SLICE_S
    timeout: float = _shared.TIMEOUT

    @property
    def out_fields(self) -> str:
        return ",".join(self.fields)


# ── Denver ──

_DENVER_FIELDS = (
    "SCHEDNUM", "SITUS_ADDR_NBR", "SITUS_ADDR_NBR_SUFFIX", "SITUS_STR_NAME_PRE_DIR",
    "SITUS_STR_NAME_PRE_MOD", "SITUS_STR_NAME", "SITUS_STR_NAME_POST_TYPE",
    "SITUS_STR_NAME_POST_DIR", "SITUS_STR_NAME_POST_MOD", "SITUS_UNIT_IDENT",
    "D_CLASS_CN", "TOT_UNITS", "RES_ORIG_YEAR_BUILT", "COM_ORIG_YEAR_BUILT",
    "RES_ABOVE_GRADE_AREA",
)


def _denver_street(row: dict) -> str | None:
    return _street(row.get("SITUS_ADDR_NBR"), row.get("SITUS_ADDR_NBR_SUFFIX"),
                   row.get("SITUS_STR_NAME_PRE_DIR"), row.get("SITUS_STR_NAME_PRE_MOD"),
                   row.get("SITUS_STR_NAME"), row.get("SITUS_STR_NAME_POST_TYPE"),
                   row.get("SITUS_STR_NAME_POST_DIR"),
                   row.get("SITUS_STR_NAME_POST_MOD"))


def _denver_no_home(row: dict) -> bool:
    """Vacant land, common elements and land-only parcels, or a recorded zero
    dwelling units. D_CLASS_CN: "VACANT LAND /GENERAL COMMON ELEMENTS" (5,752,
    laid over and around condominium buildings), "VACANT LAND" (2,594),
    "RESIDENTIAL LAND CONTIGUOUS", "RESIDENTIAL  LAND FOR LAND/ IMPS PARCEL",
    "MOBILE HOME LAND", "DRY FARM LAND". A missing count is silence, not zero."""
    cls = _text(row.get("D_CLASS_CN"))
    if "VACANT" in cls or "LAND" in cls.split():
        return True
    units = num(row.get("TOT_UNITS"))
    return units is not None and units <= 0


def _denver_read(row: dict, _buildings=None) -> Facts:
    cls = _text(row.get("D_CLASS_CN"))
    if _denver_no_home(row):
        return Facts()
    # RES_ORIG_YEAR_BUILT is the residential improvement's original year. Denver
    # appraises buildings of two or more units on its commercial schedule, so a
    # duplex, a triplex, an apartment house — and 1,091 condominium units — carry
    # their year in COM_ORIG_YEAR_BUILT instead (2,767 of 2,776 duplexes). That
    # column is read only on a RESIDENTIAL class, where the building it dates is
    # somebody's home; on a shop it dates the shop.
    year = _year(row.get("RES_ORIG_YEAR_BUILT"))
    if year is None and cls.startswith("RESIDENTIAL"):
        year = _year(row.get("COM_ORIG_YEAR_BUILT"))
    # Above-grade living area, and only for a single-family class with exactly
    # one dwelling unit recorded and no unit in the situs. A rowhouse or a
    # condominium unit is one dwelling in a building of several, and 2,137 SFR
    # parcels record two units (a carriage house); none of them is "one home".
    sqft = None
    if (cls.startswith("SFR") and num(row.get("TOT_UNITS")) == 1
            and not _norm_unit(row.get("SITUS_UNIT_IDENT"))):
        sqft = _area(row.get("RES_ABOVE_GRADE_AREA"))
    return Facts(year_built=year, sqft=sqft)


# ── Jefferson ──

_JEFFERSON_FIELDS = (
    "PIN", "PRPSTRNUM", "PRPSTRDIR", "PRPSTRNAM", "PRPSTRTYP", "PRPSTRSFX",
    "PRPSTRUNT", "STTSTRC", "STTYRBLT", "STTGRSAREA", "STTTYPCNS", "STTSTRC2",
    "STTYRBLT2",
)

#: STTSTRC structure types that are somebody's home, measured over the 208,875
#: parcels with a year built: Single Family 158,955; Townhomes 21,484; Condo, Res:
#: Attached 13,243; Duplex 5,653; Apartment Low Rise 1,189; Single Family Rowhouse
#: 503; Triplex 133; and the smaller apartment and condominium classes. The rest
#: (offices, retail, the "/Condo" commercial classes, "Converted Res" businesses)
#: are not.
_JEFFERSON_DWELLINGS = frozenset({
    "SINGLE FAMILY", "TOWNHOMES", "CONDO, RES: ATTACHED", "DUPLEX: TWO FAMILY",
    "APARTMENT LOW RISE 1-3", "SINGLE FAMILY ROWHOUSE", "TRIPLEX: THREE FAMILY",
    "APARTMENT: TOWNHOME STYLE", "CONDOS, RES: LOW RISE (1-3)",
    "APARTMENT MID RISE 4 - 6", "APARTMENT/LOW INCOME", "CONDOS, RES: MID RISE (4-9)",
    "APARTMENT HIGH RISE 7+",
})


def _jefferson_street(row: dict) -> str | None:
    return _street(_house_number(row.get("PRPSTRNUM")), row.get("PRPSTRDIR"),
                   row.get("PRPSTRNAM"), row.get("PRPSTRTYP"), row.get("PRPSTRSFX"))


def _jefferson_no_home(row: dict) -> bool:
    """The first structure is not a dwelling, or there is none (50,066 parcels —
    vacant land, common areas, rights of way — carry no structure at all)."""
    return _text(row.get("STTSTRC")) not in _JEFFERSON_DWELLINGS


def _jefferson_read(row: dict, _buildings=None) -> Facts:
    if _jefferson_no_home(row):
        return Facts()
    year = _year(row.get("STTYRBLT"))
    second = _text(row.get("STTSTRC2"))
    # 859 single-family parcels carry a SECOND single-family structure (a front
    # and a rear house), and its year can differ. Which of them the reader lives
    # in the record does not say, so two dwellings of different years give none.
    if second in _JEFFERSON_DWELLINGS and _year(row.get("STTYRBLT2")) != year:
        year = None
    one_home = (_text(row.get("STTSTRC")) == "SINGLE FAMILY" and not second
                and not _norm_unit(row.get("PRPSTRUNT")))
    sqft = _area(row.get("STTGRSAREA")) if one_home else None
    code = _text(row.get("STTTYPCNS")).split(" - ")[0]
    construction = _JEFFERSON_WALL.get(code) if not second else None
    return Facts(year_built=year, sqft=sqft, construction=construction)


# ── the improvement tables (Adams, Douglas) ──

#: Property types that are somebody's home. Adams's 170,597 rows: Residential
#: 129,567; Townhouse 10,747; Condo 9,875; Commercial 8,747; Out Building 6,693;
#: Multiple Unit 3,787; Duplex 1,044; Triplex 125; Mobile Home 12. Douglas's are
#: the same words.
_DWELLING_TYPES = frozenset({"RESIDENTIAL", "TOWNHOUSE", "CONDO", "MULTIPLE UNIT",
                             "DUPLEX", "TRIPLEX", "MOBILE HOME"})


def _one_year(rows: list[dict], column: str) -> int | None:
    """The dwellings' year, where every dwelling on the record agrees on one."""
    years = {_year(r.get(column)) for r in rows}
    return years.pop() if len(years) == 1 else None


def _adams_dwellings(buildings: list | None) -> list[dict]:
    return [b for b in (buildings or []) if _text(b.get("proptype")) in _DWELLING_TYPES]


def _adams_read(parcel: dict, buildings: list | None) -> Facts:
    homes = _adams_dwellings(buildings)
    if not homes:
        # An account with no dwelling row at all — a shop, a barn, a storage
        # yard — is the county saying nobody lives here.
        return Facts()
    year = _one_year(homes, "yrblt")
    sqft = construction = None
    if len(homes) == 1:
        home = homes[0]
        if _text(home.get("proptype")) == "RESIDENTIAL" and not _adams_unit(parcel):
            sqft = _area(home.get("sf"))
        construction = _WALL.get(_text(home.get("exterior")))
    return Facts(year_built=year, sqft=sqft, construction=construction)


def _adams_unit(row: dict) -> str | None:
    """STREETALP holds the unit as "#A", "#12" (blank is a single space)."""
    return _norm_unit(row.get("STREETALP")) or None


# Douglas's CONDITION, measured on 151,440 rows: Good 93,183; Average 56,269;
# Badly Worn 1,051; Worn Out 317; Very Good 111; Excellent 7; blank 502.
_DOUGLAS_CONDITION = {"EXCELLENT": "excellent", "GOOD": "good", "AVERAGE": "average"}
# Deliberately unmapped: Very Good falls between good and excellent; Badly Worn
# and Worn Out each read as poor or as unsound, and choosing would be a guess.


def _douglas_dwellings(buildings: list | None) -> list[dict]:
    """Dwelling rows. A row of a dwelling type that records NO_OF_UNIT 0 is the
    county saying the building holds no dwelling, and is not one."""
    out = []
    for b in buildings or []:
        if _text(b.get("PROPERTY_TYPE_CODE")) not in _DWELLING_TYPES:
            continue
        units = num(b.get("NO_OF_UNIT"))
        if units is not None and units <= 0:
            continue
        out.append(b)
    return out


def _douglas_read(parcel: dict, buildings: list | None) -> Facts:
    homes = _douglas_dwellings(buildings)
    if not homes:
        return Facts()
    year = _one_year(homes, "BUILT_YEAR")
    sqft = construction = condition = None
    if len(homes) == 1:
        home = homes[0]
        if (_text(home.get("PROPERTY_TYPE_CODE")) == "RESIDENTIAL"
                and num(home.get("NO_OF_UNIT")) == 1
                and not _norm_unit(parcel.get("UNIT_NO"))):
            sqft = _area(home.get("IMPROVEMENT_SF"))
        construction = _WALL.get(_text(home.get("EXTERIOR_CONSTRUCTION_TYPE")))
        condition = _DOUGLAS_CONDITION.get(_text(home.get("CONDITION")))
    return Facts(year_built=year, sqft=sqft, construction=construction,
                 condition=condition)


# ── Boulder ──

#: Building classes that are somebody's home. Measured on the 139,421
#: building-attribute rows: SINGLE FAM RES 101,256; CONDOS 15,582; MANUFACTURED
#: HOUSING 3,688; DUP/TRIPLEX 1,840; FARM/RANCH RESIDENTIAL 1,190; MULTI-UNITS
#: (9+) 858; MULTI-UNITS (4-8) 836. The class is the ACCOUNT's, not the
#: building's: a single-family account's tool shed and detached garage are filed
#: "SINGLE FAM RES IMPROVEMENTS" too, with zero finished area — which is how a
#: dwelling row is told from them (see _boulder_dwellings).
_BOULDER_DWELLINGS = frozenset({
    "SINGLE FAM RES IMPROVEMENTS", "CONDOS-IMPROVEMENTS",
    "MANUFACTURED HOUSING IMPROVEMENTS", "DUP/TRIPLEX IMPROVEMENTS",
    "FARM/RANCH RESIDENTIAL IMPROVEMENTS", "MULTI-UNITS (9+) IMPROVEMENTS",
    "MULTI-UNITS (4-8) IMPROVEMENTS",
})
#: Account types that are land only (no building can be the reader's home).
_BOULDER_LAND = frozenset({"VACANT LAND", "RESIDENT LAND", "MINERALS",
                           "NATURAL RESRC"})


def _boulder_street(row: dict) -> str | None:
    number = num(row.get("StrNum"))
    if not number:
        return None
    return _street(str(int(number)), row.get("StrPrx"), row.get("Street"),
                   row.get("StrSuf"))


def _boulder_dwellings(buildings: list | None) -> list[dict]:
    return [b for b in (buildings or [])
            if _text(b.get("ClassCodeDscr")) in _BOULDER_DWELLINGS
            and (num(b.get("FinishedSqft")) or 0) > 0]


def _boulder_read(parcel: dict, buildings: list | None) -> Facts:
    homes = _boulder_dwellings(buildings)
    if not homes:
        return Facts()
    year = _one_year(homes, "YearBuilt")
    sqft = None
    # FinishedSqft is the ABOVE-GRADE finished area: on R0034667 it is 3,026 =
    # 2,033 first floor + 993 second, with the 960 sq ft finished walk-out
    # basement excluded (checked against the county's BLDG_AREA breakdown).
    if (len(homes) == 1
            and _text(homes[0].get("ClassCodeDscr")) == "SINGLE FAM RES IMPROVEMENTS"
            and not _norm_unit(parcel.get("StrUnit"))):
        sqft = _area(homes[0].get("FinishedSqft"))
    return Facts(year_built=year, sqft=sqft)


COUNTIES: dict[str, County] = {
    "08031": County(
        name="Denver",
        url=DENVER_URL,
        fields=_DENVER_FIELDS,
        pid="SCHEDNUM",
        street=_denver_street,
        unit=lambda row: _norm_unit(row.get("SITUS_UNIT_IDENT")) or None,
        no_home=lambda row: _denver_read(row).empty(),
        read=_denver_read,
        address_fields=tuple(f for f in _DENVER_FIELDS if f.startswith("SITUS_")),
        number_where=lambda n: f"SITUS_ADDR_NBR='{n}'",
        implicit_north=True,
        attribution=("City and County of Denver Assessment Division parcels, via "
                     "the City of Denver Open Data Catalog (CC BY 3.0)"),
        vintage=lambda row, _b: ("Denver assessment parcels (refreshed daily), "
                                 "queried live"),
    ),
    "08059": County(
        name="Jefferson",
        url=JEFFERSON_URL,
        fields=_JEFFERSON_FIELDS,
        pid="PIN",
        street=_jefferson_street,
        unit=lambda row: _norm_unit(row.get("PRPSTRUNT")) or None,
        no_home=lambda row: _jefferson_read(row).empty(),
        read=_jefferson_read,
        address_fields=tuple(f for f in _JEFFERSON_FIELDS if f.startswith("PRP")),
        # Jefferson zero-pads its house numbers to five digits ("06390").
        number_where=lambda n: f"PRPSTRNUM IN ('{n}','{n:0>5}')",
        attribution=("Jefferson County Assessor parcels via Jefferson County GIS "
                     "(CC BY 4.0)"),
        vintage=lambda row, _b: "Jefferson County Assessor parcels, queried live",
    ),
    "08001": County(
        name="Adams",
        url=ADAMS_URL,
        fields=("PARCELNB", "STREETNO", "STREETDIR", "STREETNAME", "STREETSUF",
                "STREETPOSTDIR", "STREETALP"),
        pid="PARCELNB",
        street=lambda row: _street(row.get("STREETNO"), row.get("STREETDIR"),
                                   row.get("STREETNAME"), row.get("STREETSUF"),
                                   row.get("STREETPOSTDIR")),
        unit=_adams_unit,
        no_home=lambda row: False,
        read=_adams_read,
        address_fields=("STREETNO", "STREETDIR", "STREETNAME", "STREETSUF",
                        "STREETPOSTDIR", "STREETALP"),
        number_where=lambda n: f"STREETNO='{n}'",
        buildings=Buildings(
            url=ADAMS_IMPROVEMENTS_URL, key="PARCELNB", column="parcelnb",
            fields=("parcelnb", "bldgid", "proptype", "yrblt", "sf", "exterior")),
        attribution=("Adams County Assessor parcels and property improvements "
                     "(CC BY 4.0)"),
        vintage=lambda row, _b: ("Adams County Assessor property improvements "
                                 "(updated weekly), queried live"),
        # Measured: the slowest buffered query 1.48 s, containment 0.87 s and
        # second hop 0.84 s — each past the shared one-second slice, and four
        # verified homes were lost to it in one run. See "Timing".
        read_slice=2.5, timeout=5.0,
    ),
    "08035": County(
        name="Douglas",
        url=DOUGLAS_URL,
        fields=("STATE_PARCEL_NO", "ACCOUNT_NO", "ACCOUNT_TYPE_CODE", "PARCEL_TYPE",
                "ADDRESS_NUMBER", "ADDRESS_NUMBER_SUFFIX", "PRE_DIRECTION_CODE",
                "STREET_NAME", "STREET_TYPE_CODE", "POST_DIRECTION_CODE", "UNIT_NO"),
        pid="ACCOUNT_NO",
        street=lambda row: _street(row.get("ADDRESS_NUMBER"),
                                   row.get("ADDRESS_NUMBER_SUFFIX"),
                                   row.get("PRE_DIRECTION_CODE"), row.get("STREET_NAME"),
                                   row.get("STREET_TYPE_CODE"),
                                   row.get("POST_DIRECTION_CODE")),
        unit=lambda row: _norm_unit(row.get("UNIT_NO")) or None,
        # ACCOUNT_TYPE_CODE "Vacant Land" (11,307) and "HOA" (4,487, common
        # areas laid around townhomes), and PARCEL_TYPE "RIGHT_OF_WAY" (6,063).
        no_home=lambda row: (_text(row.get("ACCOUNT_TYPE_CODE")) in ("VACANT LAND",
                                                                     "HOA")
                             or _text(row.get("PARCEL_TYPE")) == "RIGHT_OF_WAY"),
        read=_douglas_read,
        address_fields=("ADDRESS_NUMBER", "ADDRESS_NUMBER_SUFFIX", "PRE_DIRECTION_CODE",
                        "STREET_NAME", "STREET_TYPE_CODE", "POST_DIRECTION_CODE",
                        "UNIT_NO"),
        number_where=lambda n: f"ADDRESS_NUMBER='{n}'",
        buildings=Buildings(
            url=DOUGLAS_IMPROVEMENTS_URL, key="ACCOUNT_NO", column="ACCOUNT_NO",
            fields=("ACCOUNT_NO", "BUILDING_ID", "PROPERTY_TYPE_CODE", "BUILT_YEAR",
                    "IMPROVEMENT_SF", "NO_OF_UNIT", "EXTERIOR_CONSTRUCTION_TYPE",
                    "CONDITION", "etl_write_date")),
        attribution=("Douglas County Assessor parcels and property improvements "
                     "(CC BY-SA 4.0)"),
        vintage=lambda row, buildings: _douglas_vintage(buildings),
    ),
    "08013": County(
        name="Boulder",
        url=BOULDER_URL,
        fields=("AccountNo", "ParcelNo", "StrNum", "StrPrx", "Street", "StrSuf",
                "StrUnit", "AcctType", "CreatedDate"),
        pid="AccountNo",
        street=_boulder_street,
        unit=lambda row: _norm_unit(row.get("StrUnit")) or None,
        no_home=lambda row: _text(row.get("AcctType")) in _BOULDER_LAND,
        read=_boulder_read,
        address_fields=("StrNum", "StrPrx", "Street", "StrSuf", "StrUnit"),
        number_where=lambda n: f"StrNum={int(n)}",
        buildings=Buildings(
            url=BOULDER_BUILDINGS_URL, key="AccountNo", column="AccountNo",
            fields=("AccountNo", "BuildingNumber", "SectionNumber", "ClassCodeDscr",
                    "YearBuilt", "FinishedSqft")),
        attribution=("Boulder County Assessor parcels and building attributes "
                     "(CC BY 4.0)"),
        vintage=lambda row, _b: _boulder_vintage(row),
    ),
}

COUNTY_FIPS = frozenset(COUNTIES)

#: The module's own clock: the largest any county is given, which is what a
#: lookup that must first ask which county it is in starts with.
READ_SLICE_S = max(c.read_slice for c in COUNTIES.values())
LOOKUP_TIMEOUT = max(c.timeout for c in COUNTIES.values())


def _douglas_vintage(buildings: list | None) -> str:
    base = "Douglas County Assessor property improvements"
    days = sorted(d for d in (_date_of(b.get("etl_write_date"))
                              for b in buildings or []) if d)
    return f"{base}, extract of {days[-1]}" if days else f"{base}, queried live"


def _boulder_vintage(row: dict) -> str:
    base = "Boulder County Assessor parcels and building attributes"
    day = _date_of(row.get("CreatedDate"))
    return f"{base}, parcel layer of {day}" if day else f"{base}, queried live"


# ── the candidates ─────────────────────────────────────────────────────────────


def _candidates(cfg: County, rows: list[dict]) -> list[dict]:
    """Parcel rows that could be an answer, one per record.

    * A row with no identifier is a record of nothing (Jefferson's right-of-way
      polygons carry the identifier "ROW" and nothing else, and are caught by the
      next rule).
    * A row that says nothing anybody lives in stands here (``cfg.no_home``) is
      dropped. Every fact it could offer is refused anyway, so it can never be
      an answer — but as a candidate it makes the home beside or under it
      ambiguous: Denver lays a "GENERAL COMMON ELEMENTS" parcel over each
      condominium complex, Douglas an HOA tract around each row of townhomes.
      Removing rows that cannot be the answer can only turn "ambiguous" into
      "one"; the address confirmation that follows is untouched.
    * Rows sharing an identifier are ONE candidate when they differ only in the
      situs: Boulder writes one row per street address of an account ("Parcels
      may be stacked ... when multiple site addresses exist within assessor
      records"), and offered raw, the house at 555 Main St, Louisville faced its
      own second row and was refused. The record is at each of its addresses, so
      it carries all of them (``_situs``). Rows of one identifier that disagree in
      anything else are a broken join and are not offered at all.
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        pid = str(row.get(cfg.pid) or "").strip()
        if not pid or cfg.no_home(row):
            continue
        groups.setdefault(pid, []).append(row)
    facts = tuple(f for f in cfg.fields if f not in cfg.address_fields)
    out = []
    for members in groups.values():
        if len({tuple(str(m.get(f)) for f in facts) for m in members}) > 1:
            continue
        parcel = dict(members[0])
        situs, seen = [], set()
        for m in members:
            entry = (cfg.street(m), cfg.unit(m))
            if entry not in seen:
                seen.add(entry)
                situs.append(entry)
        parcel["_situs"] = situs
        out.append(parcel)
    return out


def _units(parcel: dict) -> set:
    """The units a candidate's situs names (None for a situs with no unit)."""
    return {unit for _, unit in parcel.get("_situs") or []}


def _without_implicit_north(street: str | None) -> str | None:
    """Denver's "2701 N WOLFF ST" as the rest of the world writes it: "2701 WOLFF ST".

    Denver's assessor writes the "N" of every north-half street; the Census
    matcher (and the Postal Service) omit it, and write "S" for the south half.
    Returned only where something remains to be a street name after the N, which
    ``address_key`` checks.
    """
    tokens = str(street or "").split()
    if len(tokens) >= 3 and tokens[1].upper() == "N":
        stripped = " ".join([tokens[0], *tokens[2:]])
        return stripped if address_key(stripped) else None
    return None


_PREDIRS = frozenset({"N", "S", "E", "W"})


def _leading_predir(street: str | None) -> bool:
    """Whether a street address's second token is a one-letter directional."""
    tokens = str(street or "").split(",")[0].split()
    return len(tokens) >= 3 and tokens[1].upper() in _PREDIRS


def _agrees(cfg: County, query: str, street: str | None) -> bool:
    """Whether a situs names the query's building, with Denver's one documented
    convention allowed and nothing else relaxed.

    **Denver** writes the implicit "N" of its north-half streets ("2701 N WOLFF
    ST"); the Postal Service and the Census matcher never do ("2701 WOLFF ST"),
    and both write "S" for the south half. Tested on twin addresses: typed "740 S
    PEARL ST" and "740 PEARL ST" came back 2.8 km apart, each on its own half — as
    did 1500 S/N Clarkson and 300 S/N Downing — and typed "1500 N CLARKSON ST"
    came back "1500 CLARKSON ST" at the north twin. So a query with no directional
    names the north half, and only the ROLL's N is set aside, only for a query
    that carries no directional of its own. A roll S, E or W is never ignored,
    and neither is a query's.

    No other directional written on one side only is forgiven, in any county.
    The Census matcher is measured to ignore, drop and swap directionals (Utah:
    typed "571 N 200 W" and "571 S 200 W" came back as the same point; here,
    typed "3569 W 89TH AVE" in Adams came back "3569 89TH AVE"), so "100 W MAIN"
    and "100 E MAIN" can arrive as one point, and a county that writes the house
    with no directional would be confirmed against whichever twin is near. That
    includes Douglas, which writes none on most homes — see the module docstring
    for what refusing costs there.
    """
    if same_address(query, street):
        return True
    if cfg.implicit_north:
        stripped = _without_implicit_north(street)
        if stripped and not _leading_predir(query) and same_address(query, stripped):
            return True
    return False


def _offer(cfg: County, query: str | None) -> Callable[[dict], str | None]:
    """The address accessor ``select_parcel`` compares against.

    A record is offered under whichever of its situs addresses agrees with the
    query, and otherwise under its first, which then fails the comparison exactly
    as it should. In Denver, where the only difference is the roll's implicit
    "N", it is offered under the query's own spelling — the one comparison
    ``select_parcel`` can make. The query must then carry no leading directional
    of its own: "2701 S WOLFF ST" never meets "2701 N WOLFF ST", and a south-half
    address keeps its S on both sides.
    """
    def address_of(parcel: dict) -> str | None:
        streets = [street for street, _ in parcel.get("_situs") or []]
        if query:
            for street in streets:
                if same_address(query, street):
                    return street
            for street in streets:
                if _agrees(cfg, query, street):
                    return query
        return streets[0] if streets else None
    return address_of


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the covered Colorado county this point is in, from TIGERweb.

    Only for a caller that did not say: the registry passes the county it routed
    on to an adapter whose ``lookup`` accepts it, so in the product this request
    is never made.
    """
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "GEOID", "returnGeometry": "false", "f": "json",
    }, deadline, _shared._READ_SLICE_S) or {}
    found = {str((f or {}).get("attributes", {}).get("GEOID") or "").strip()
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


def _parcel_at(lat: float, lon: float, address: str | None, cfg: County,
               *, deadline: float) -> dict | None:
    """The county's record of the parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s; see it for why the nearest
    parcel is never taken. What is local is which rows reach it.
    """
    unit = _norm_unit(unit_of(address)) or None
    key = address_key(address)
    number = key[0] if key else None
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            # The buffered query asks only for rows carrying the query's house
            # number. select_parcel counts a buffered row only if its address
            # agrees with the query's, and an address with another number never
            # does, so the rows left out could not have changed the answer. What
            # they could do is fill the page: 710 S Alton Way, Denver, has more
            # than 2,000 condominium-unit records stacked within 80 m, the page
            # came back truncated, and the lookup failed open. Containment is
            # never filtered — the polygons under the point are all evidence.
            where = (cfg.number_where(number)
                     if distance_m and number and cfg.number_where else None)
            rows = _shared.arcgis_parcels(cfg.url, lat, lon, cfg.out_fields,
                                          distance_m, deadline=deadline,
                                          read_slice=cfg.read_slice, where=where)
            fetched[distance_m] = _candidates(cfg, rows)
        found = fetched[distance_m]
        if unit:
            # A reader who typed a unit cannot live in a record that names only
            # DIFFERENT units. Denver stacks every condominium unit — and its
            # garage and parking spaces — on the building's one polygon, so
            # without this a typed "#606" faces the whole stack and is refused.
            found = [p for p in found if None in _units(p) or unit in _units(p)]
            # And where a record at the query's address names exactly the typed
            # unit, a record there that names no unit is not the reader's: it is
            # the building's own record. Denver files each condominium building
            # once more, with no unit, as the project (2525 S DAYTON WAY carries
            # 148 unit records and one with TOT_UNITS 148), and that row made
            # every unit in it ambiguous.
            exact = [p for p in found if unit in _units(p)
                     and any(_agrees(cfg, address, s) for s, u in p["_situs"]
                             if u == unit)]
            return exact or found
        if distance_m == 0 and address:
            # A unit's polygon is not evidence of which unit the reader is in:
            # Denver gives all of them the building's outline. With an address
            # and no unit, records naming only units are left out of the
            # containment answer, so the buffer (which contains the point) must
            # hold exactly one record whose address agrees — and a stack of
            # units never does.
            return [p for p in found if None in _units(p)]
        return found

    return select_parcel(fetch, address, _offer(cfg, address))


_KEY_RE = re.compile(r"^[A-Za-z0-9.\-]{1,40}$")


def _buildings(cfg: County, parcel: dict, *, deadline: float) -> list[dict] | None:
    """The second hop: the chosen record's rows in the county's characteristics
    table, or None where the record carries no usable key."""
    spec = cfg.buildings
    key = str(parcel.get(spec.key) or "").strip()
    # The key goes into a where clause, so it must look like a key and nothing
    # else (parcel numbers and account numbers are letters, digits, dots, dashes).
    if not _KEY_RE.match(key):
        return None
    body = _shared.get_json(spec.url, {
        "where": f"{spec.column}='{key}'", "outFields": ",".join(spec.fields),
        "returnGeometry": "false", "f": "json",
    }, deadline, cfg.read_slice) or {}
    return [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips in COUNTY_FIPS:
        deadline = deadline_from(None, COUNTIES[fips].timeout)
    else:
        deadline = deadline_from(None, LOOKUP_TIMEOUT)
        fips = _county_at(lat, lon, deadline=deadline)
        if fips is None:
            return None
    cfg = COUNTIES[fips]
    parcel = _parcel_at(lat, lon, address, cfg, deadline=deadline)
    if parcel is None:
        return None
    buildings = None
    if cfg.buildings is not None:
        buildings = _buildings(cfg, parcel, deadline=deadline)
        if buildings is None:
            return None
    facts = cfg.read(parcel, buildings)
    if facts.empty():
        return None
    return AssessorRecord(
        source=cfg.attribution,
        data_vintage=cfg.vintage(parcel, buildings),
        parcel_id=str(parcel.get(cfg.pid) or "").strip() or None,
        year_built=facts.year_built,
        sqft=facts.sqft,
        construction=facts.construction,
        condition=facts.condition,
        # No county here publishes a story count the label can read without a
        # guess, or a foundation type; see the module docstring.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher, not another's."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is the county the registry routed on; without it the
    county is looked up from the point (one extra request).

    Fails open on everything — a timeout, a 500, a truncated page
    (``_shared.TruncatedResponse``), a renamed column, a moved service. The caller
    then keeps whatever it had, which is the behavior that existed before this
    adapter.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Colorado assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
