#!/usr/bin/env python3
"""Ohio — nine county auditors' parcel layers, one per county, behind one module.

Ohio has no statewide year built. The state's parcel layer (OGRIP's "Ohio
Statewide Parcels", 6.3 million parcels in all 88 counties) carries a parcel id,
a situs and a land-use code, and no year, area, story count or wall. So unlike
Florida, Connecticut or North Carolina there is no one service to ask: every
answer here comes from a county's OWN layer, each with its own schema, and the
module is a per-county table (``COUNTIES``) in the shape Utah's is — one keyless
point query per lookup, the parcel's shape and its auditor's facts on one
feature, no second hop anywhere.

Which counties, and why only these
----------------------------------
Measured 2026-10-03. ACS housing units from this repository's own county table.

  ==========  =====  =========  ==================================================
  county      FIPS     units    source
  ==========  =====  =========  ==================================================
  Franklin    39049    595,469  Franklin County Auditor, ``Parcel_Features``
  Cuyahoga    39035    615,331  Cuyahoga County Fiscal Office, ``Parcel_Fabric_
                                Taxparcels`` (refreshed nightly)
  Summit      39153    247,924  Summit County Fiscal Office, ``Parcels_07162026``
  Montgomery  39113    252,843  Montgomery County Auditor, ``AUDGIS_B1`` layer 7
                                (parcels joined to the nightly CAMA extract)
  Delaware    39041     86,269  Delaware County Auditor, ``Parcel``
  Butler      39017    155,372  Butler County Auditor — a 2024 SNAPSHOT
  Lorain      39093    136,548  Lorain County Auditor — a republished SNAPSHOT
  Fairfield   39045     64,036  via the City of Columbus mirror (copied 2026-09-30)
  Licking     39089     73,273  via the City of Columbus mirror (copied 2024-05-06)
  ==========  =====  =========  ==================================================

2,227,065 of Ohio's 5,292,391 units (42%). The first five are live layers the
auditors themselves maintain; the last four carry their age in the vintage each
record reports, so a stale value is never presented as a fresh one.

**Not coverable**, and so not claimed (954,354 units). **Hamilton** (39061): the
CAGIS parcels carry the auditor's id, address and values but no year, area or
stories, and the county's building-footprint ``YEAR_BUILT`` is null on all
399,110 rows; the year exists only in the auditor's web application. **Lucas**
(39095): the only year column is a 138-row "completion percentage" layer of
parcels under construction; the CAMA is published as a Microsoft Access download,
not a queryable service. **Stark** (39151): the auditor's parcels carry no
building data, and the address points' ``yearBuilt`` is filled on no row.
**Mahoning** (39099): its only year table holds 12,404 commercial buildings and
no dwellings. **Warren** (39165): no public parcel service was found, and the
auditor's former domain has lapsed and now redirects to an unrelated spam
profile, so it must never appear in code. (Lake, 39085, answered "Could not
access any server machines" all day and is unverified.)

The Columbus mirror, and why it is used for exactly two counties
---------------------------------------------------------------
The City of Columbus republishes seven central-Ohio auditors' parcels in
Franklin's schema (``KeyLayers/MapServer/3``), each county stamped with the date
it was copied (``SHP_UPLD_DATE``). Re-measured for this adapter:

* **Fairfield**: copied 2026-09-30, 55,516 rows with a year; 36,135 of its
  36,311 single-family lots. Fit, and used.
* **Licking**: copied **2024-05-06** and never since — no year later than 2024
  anywhere in it. Used all the same, because a year built does not change once a
  house stands, and because every Licking record says "copied 2024-05-06" in its
  vintage. What a two-year-old copy cannot know is a house built since, and that
  fails safe: the new house's lot is vacant land in the copy (refused), or still
  part of the farm it was split from, whose address the new house's does not
  share (refused by the address check). It would mislead only a lookup with no
  address at all landing in a split farm — the same residual risk Butler's
  snapshot carries. If the City resumes copying, the vintage moves on by itself.
* Franklin and Delaware are better served by the auditors' own layers (the
  mirror has no floor area outside Franklin and lags by up to three weeks), and
  Union, Madison and Pickaway carry no year in it at all.

Each Fairfield or Licking request carries ``COUNTY='<name>'``, so a buffer near
a county line never offers a neighbor county's row under this county's vintage.

Ohio's shared land-use codes
----------------------------
What makes nine schemas tractable is that every county files each parcel under
the Department of Taxation's three-digit land-use code, and the 5xx core means
the same thing everywhere it is described (Franklin's, Lorain's, Licking's and
Cuyahoga's own description columns): 500-505 vacant residential land by acreage,
510-515 a single-family dwelling, 520s two-family, 530s three-family, 550 a
condominium unit. Cuyahoga writes them with a fourth digit (5100). Two uses:

* **Is a home here at all?** Vacant-land codes (500-505, and the x00 vacant code
  of the agricultural, industrial and commercial classes) refuse every fact, and
  so do each county's own codes for land laid over or around homes — common
  areas, association lots, rights of way, condominium garages. Outside that core
  the counties diverge (540 is an association lot in Franklin, a house trailer in
  Licking, a four-family house in Lorain), so those codes are per county, read
  off each county's own descriptions. Such rows are dropped before the parcel is
  chosen: they can never be an answer, and as candidates they made real homes
  ambiguous (Montgomery files 6415 Landsend Ct's side lot as 500 under the
  house's own address).
* **Is it ONE home?** Only 510-515 says so. Area and stories are reported only
  there — never on a two- or three-family parcel, never on a condominium unit
  (one apartment's area, the building's floors), never on a Cuyahoga parcel with
  more than one residential building, never on a parcel carrying two street
  addresses (Lorain's "618" and "618 1/2" Dewey Ave). Nothing is divided by a
  unit count.

Silence is never a refusal: a row with no land-use code keeps its year.

Each county's trap
------------------
**Cuyahoga's age columns are years.** ``min_age`` and ``max_age`` are labeled
"Oldest/Newest Residential Building Age" in the county's data dictionary, and
hold years built (1952), not ages. Checked across the whole layer: ``min_age``
<= ``max_age`` on every row (0 rows greater, 987 smaller), so ``min_age`` is the
OLDEST dwelling's year. On the 492,241 parcels where the two agree, that is the
house's year built. On the 988 where they do not — a 1900 front house and a 2003
rear house on one two-family lot — which dwelling the reader lives in is not
something the record says, so no year is reported. Missing is 0. The layer also
repeats whole rows (613,361 rows carry 520,344 distinct parcel ids; 43306050
comes back four times), so rows are merged by parcel id before the choice, and
rows of one id that disagree on any fact are refused as a broken join. Each
condominium complex adds a MULTI footprint with every field null, dropped as a
row with no id.

**Summit's dated service name.** The layer is ``Parcels_07162026`` — created
2026-07-16 — and is being refreshed (data edited 2026-09-28). Its predecessors
``TaxParcels_public``/``_dashboard``/``_Viewer`` stopped at 2024-12-16 *and kept
answering*. So the liveness risk is not only a URL that disappears — which fails
open, uncached, and names the Summit source among the label's dropped datasets on
every Summit lookup, so it cannot go unseen — but a URL that keeps serving while
quietly freezing. The vintage cannot show that (the layer carries no data date),
so the service's ``editingInfo.dataLastEditDate`` should be checked when this
module is next touched, and the organization's services directory
(``services3.arcgis.com/3Ukh5HzAdI6WZ3KP``) searched for a newer ``Parcels_*``.
Summit also lays a homeowners'-association parcel over each condominium complex
with a blank house number ("  LAKE POINTE DR ") and no facts; it is dropped as a
record of nothing.

**Montgomery is a join, and slow.** Parcel polygons joined to the CAMA extract,
so every column is qualified (``SDE.WEB_CAMA.DWEL_YRBLT``) and is sent exactly
so. It is the only county with an exterior wall (``DWEL_EXTWALL``) — see
``_WALL`` for what is translated and what is not — and its buffered query is the
slowest measured; see "Timing".

**Delaware publishes no parcel id**, and its year dates every building. Records
are returned with ``parcel_id`` None and are never merged; ``YRBUILT`` also dates
shops and warehouses (825 Kintner Pkwy, a 2021, 46,200 sq ft building coded 400),
so there the year needs a home's code (agricultural, 401-403 apartments, or 5xx).
Delaware also gives every condominium unit its whole complex's outline — 81
units of Oak Creek Condos share one 222,542 sq ft polygon — so containment
cannot pick a unit. With an address in hand, condominium rows are left out of the
containment answer in every county and the unit is found the way Washington's
are: by exactly one unit in the buffer agreeing with the address. A stack with
no unit typed stays ambiguous; a typed unit picks its own row (``_could_be_unit``).

**Lorain's two land-use columns disagree** — on 4,626 rows about vacant land
versus a house alone — and the rows say which is current: of 3,944 that
``USECD`` calls vacant and ``CLASSCD`` single-family, 3,922 carry a year built —
averaging 2013 — and an area; of 682 the other way round, 18 do. ``CLASSCD`` decides. Lorain's situs also runs into its
city with no comma ("5683   BOXWOOD DR  LORAIN, OH 44053"), trimmed at the last
run of spaces before the comma (``_lorain_street``); the layer writes one row per
street address of a parcel (3235/3237 Grove Ave are one parcel, two rows), merged
by id and confirmable under either; and two ``RESYRBLT`` values exceed 2026 (up
to 5391) and fail the plausibility range.

**Butler is a 2024 reappraisal snapshot**: its value columns stop at
``VALUE24``/``MKTVAL24`` and its newest year built is 2024, and it lives in an
internal-looking "TopographyData" service. It is the only county with a
condition grade (``CDU``; see ``_CONDITION``).

**Fairfield and Licking write a trailing quadrant** ("13113 RUSTIC DR NW") that
the Census matcher drops for Fairfield and adds for Licking. There a quadrant on
one side only is set aside (``_quadrant_free``); two written quadrants must still
agree, and nothing else about the address is relaxed.

What is never read
------------------
Every layer carries owner names and mailing addresses, and most carry sale
prices, tax balances and lender names. Each county's ``fields`` is an explicit,
short list (five to ten columns) and the shared helper refuses ``*``. Effective
and remodel years (Franklin's ``RESYRBLTEFF``, Butler's ``EFFYR``, Delaware's
``YRREMOD``) are not requested, so a later edit cannot read them. Nothing from
these sources is written into the repository. No layer publishes a foundation
type.

Timing
------
Measured over 40 sampled rooftops per county (360 of each request), through the
product's HTTP session, with each county's own field list:

  ==========  =================================  =================================
  county      contain  median / p90 / p95 / max  buffer   median / p90 / p95 / max
  ==========  =================================  =================================
  Franklin    0.07 / 0.09 / 0.10 / 0.40 s        0.09 / 0.10 / 0.11 / 0.28 s
  Cuyahoga    0.09 / 0.10 / 0.11 / 0.22 s        0.10 / 0.11 / 0.12 / 0.17 s
  Summit      0.13 / 0.17 / 0.18 / 0.66 s        0.13 / 0.17 / 0.18 / 0.20 s
  Montgomery  0.27 / 0.33 / 0.46 / 0.98 s        0.55 / 1.21 / 1.94 / 2.04 s
  Delaware    0.13 / 0.14 / 0.15 / 0.48 s        0.18 / 0.23 / 0.37 / 0.60 s
  Butler      0.08 / 0.09 / 0.12 / 0.59 s        0.10 / 0.11 / 0.12 / 0.13 s
  Lorain      0.16 / 0.21 / 0.21 / 0.61 s        0.16 / 0.21 / 0.22 / 0.32 s
  Fairfield   0.10 / 0.11 / 0.12 / 0.27 s        0.10 / 0.11 / 0.11 / 0.12 s
  Licking     0.09 / 0.10 / 0.11 / 0.11 s        0.11 / 0.12 / 0.12 / 0.13 s
  ==========  =================================  =================================

The responses are at most 55 KB and 286 rows, far under every layer's transfer
limit (1,000 for Butler, 2,000-5,000 elsewhere). Seven counties keep the SHARED
clock: a one-second read slice none of their 560 requests came near, and the
four-second budget. **Montgomery** gets its own: a 3-second slice and a 6-second
budget. A second pass of 84 more of each request there put the slowest
containment at 1.07 s and the slowest buffered query at 2.38 s — all of it spent
before the first byte, which is exactly the silence a read slice bounds — so the
slice clears it, and the budget covers the slowest pair (1.07 + 2.38 s) with
room. **Delaware** gets a 2-second slice, because the research run
saw a 1.79 s containment there that this run did not. A direct call that must
first ask TIGERweb for the county (0.06-0.08 s; the registry always passes the
county, so the product never makes it) starts on the largest budget. Each pair,
and the module's, is pinned under ``config.UPSTREAM_HOST_BUDGET`` by a test.

What the adapter is worth, end to end
-------------------------------------
394 homes drawn at random from the layers themselves (random object ids among
residential rows with a year; at least 40 per county, 55 in each of the two
largest), typed as street, state and ZIP, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up with no county
passed (so the TIGERweb request is included):

  ==========  ======  ========  ========  =====  ==========  ===========
  county      sample  geocoded  resolved  wrong  year exact  sqft exact
  ==========  ======  ========  ========  =====  ==========  ===========
  Franklin        55        52        46      0       46/46        39/39
  Cuyahoga        55        53        46      0       46/46        38/38
  Summit          42        41        30      0       30/30        27/27
  Montgomery      42        41        36      0       36/36        35/35
  Delaware        40        37        33      0       33/33        26/26
  Butler          40        38        31      0       31/31        30/30
  Lorain          40        40        37      0       37/37        35/35
  Fairfield       40        36        30      0       30/30            —
  Licking         40        37        30      0       30/30            —
  **all**      **394**   **375**   **319**  **0**   **319/319**  **230/230**
  ==========  ======  ========  ========  =====  ==========  ===========

Every geocode routed to the sampled county. 85% of geocoded homes resolved, **none
to the wrong parcel**, and every year and floor area reported equals the sampled
row's. Stories came back on 137, Montgomery's wall on 28, Butler's condition on
31. A lookup took a median of 0.28 s (p95 1.25 s, slowest 3.84 s — Montgomery,
on a cold connection).

The 56 that did not resolve: 34 geocodes more than 80 m from their own parcel or
on a neighbor's whose address disagrees; 11 where the Census matcher adds or
moves a directional ("125 W OLD WILSON BRIDGE RD" for the roll's "125 OLD WILSON
BRIDGE RD", "300 W NATIONAL DR" for "300 NATIONAL DR W") — not forgiven, for
Utah's reason: the matcher's directional is not trustworthy enough to wave
through; 8 addresses shared by several parcels (seven condominium stacks with no
unit typed, one house beside a factless outbuilding parcel); and 3 rolls'
oddities ("10512 QUEENS WAY NO SUFFIX", "692& 694 CARLYSLE ST", and Lorain's
"33803 UNIT C4 ELECTRIC BLVD", unit before street). The first run, before the
condominium, side-lot, Lorain-column, quadrant and Franklin-abbreviation rules
above, resolved 300 with the same zero wrong; each rule was added for a miss it
explains.

License and terms
-----------------
Every source is a county (or city) GIS service with a public-service, "as is"
disclaimer and no restriction on querying, caching or commercial use found:

* Franklin — auditor.franklincountyohio.gov/Auditor/Disclaimer: "All materials
  maintained on the server are provided "as is" with no warranties of any kind
  ... Franklin County Auditor will not be liable for any damages"; the AGOL item
  adds that "the primary information source should be consulted for
  verification". The auditor also offers a public bulk download.
* Cuyahoga — the GIS data disclaimer (data-cuyahoga.opendata.arcgis.com, and the
  data dictionary item's license): "a free public service on an "as is" basis
  ... not intended to ... constitute an official public record".
* Delaware — the layer's own license: "made available as a public service ...
  for reference purposes only ... on an "AS IS" basis", with a waiver of claims
  and a request to acknowledge Delaware County.
* Montgomery — mcohio.org/Disclaimer: no warranties, no liability, and an
  indemnity for use of the county's website; the service itself carries no text.
* City of Columbus (Fairfield, Licking) — opendata.columbus.gov: "made
  available as a public service and for reference purposes only ... on an "AS
  IS" basis", with a waiver and indemnity.
* Summit, Butler, Lorain — no license text on the items or services, and none
  found on the offices' sites (Summit's Fiscal Office publishes its full CAMA
  tables for free download; Lorain's sites were unreachable). These are Ohio
  public records (R.C. 149.43) served by the offices themselves without a key.

None prohibits this use. The posture is the one every adapter takes regardless —
query live, cache in process, bundle nothing, never fetch owner data — and each
record's ``source`` names its county office.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, cache_bucket, deadline_from, num, same_address,
    select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Ohio county auditors"
ATTRIBUTION = ("Ohio county auditors' parcel records (Franklin, Cuyahoga, Summit, "
               "Montgomery, Delaware, Butler, Lorain; Fairfield and Licking via the "
               "City of Columbus; keyless)")
DATA_VINTAGE = "Ohio county auditor parcel records"

# ── the services ───────────────────────────────────────────────────────────────

FRANKLIN_URL = ("https://gis.franklincountyohio.gov/hosting/rest/services"
                "/ParcelFeatures/Parcel_Features/MapServer/0/query")
CUYAHOGA_URL = ("https://gis.cuyahogacounty.gov/server/rest/services"
                "/CCFO/Parcel_Fabric_Taxparcels/FeatureServer/0/query")
#: The service name carries the date it was created (2026-07-16). See "Summit's
#: dated service name" in the module docstring for what happens when it moves.
SUMMIT_URL = ("https://services3.arcgis.com/3Ukh5HzAdI6WZ3KP/arcgis/rest/services"
              "/Parcels_07162026/FeatureServer/0/query")
MONTGOMERY_URL = ("https://gis.mcohio.org/server/rest/services"
                  "/VantagePoints/AUDGIS_B1/MapServer/7/query")
DELAWARE_URL = ("https://services2.arcgis.com/ziXVKVy3BiopMCCU/arcgis/rest/services"
                "/Parcel/FeatureServer/0/query")
BUTLER_URL = ("https://maps.butlercountyauditor.org/arcgis/rest/services"
              "/TopographyData_no_cache/MapServer/3/query")
LORAIN_URL = ("https://services1.arcgis.com/vGBb7WYV10mOJRNM/arcgis/rest/services"
              "/OwnershipParcels_2025_Public_View/FeatureServer/1/query")
#: The City of Columbus's "Central Ohio Parcels", a republication of seven county
#: auditors' records in Franklin's schema. Used for Fairfield and Licking only.
COLUMBUS_URL = ("https://maps.columbus.gov/arcgis/rest/services"
                "/CityServices/KeyLayers/MapServer/3/query")
#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (a direct call). The registry always says.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services"
              "/TIGERweb/State_County/MapServer/1/query")


# ── Ohio's shared land-use codes ───────────────────────────────────────────────
#
# Every Ohio county files each parcel under the Department of Taxation's
# three-digit land-use code. The first digit is the class (1 agricultural,
# 3 industrial, 4 commercial, 5 residential, 6 exempt) and the shape of the 5xx
# block is the same in every county measured: 500-505 vacant residential land by
# acreage, 510-515 a single-family dwelling by acreage, 520-525 two-family,
# 530-535 three-family, 550 a condominium unit. Cuyahoga writes the same codes
# with a fourth digit (5100, 5500, 5000), so its codes are read by their first
# three. Beyond that core the counties diverge — 540 is a homeowners'
# association lot in Franklin, a house trailer in Licking and a four-family
# dwelling in Lorain; 555 is condominium-association land in Franklin and a
# right of way in Lorain — so every code outside the core is a per-county entry
# below, read off that county's own description column, never a statewide one.

#: Codes stating the parcel is vacant land: the x00 "vacant land" code of the
#: agricultural, industrial and commercial classes (Franklin's own descriptions:
#: "AGRICULTURAL VACANT LAND", "INDUSTRIAL, VACANT LAND", "COMMERCIAL VACANT
#: LAND"; Lorain's "VACANT COMMERCIAL LAND"), and 500-505, vacant residential land
#: by acreage in every county that describes them.
_VACANT = frozenset({"100", "110", "300", "400", "500", "501", "502", "503", "504",
                     "505"})
#: Single-family dwelling, by acreage: 510 on a platted lot, 511-515 unplatted.
#: The only codes that positively say ONE home stands here.
_ONE_FAMILY = frozenset({"510", "511", "512", "513", "514", "515"})
#: Homes, for a county whose year column is not specific to dwellings (Delaware's
#: YRBUILT also dates shops and warehouses): agricultural parcels (farmhouses),
#: apartment buildings, and the residential class.
_APARTMENTS = frozenset({"401", "402", "403"})


def _dte(code) -> str | None:
    """The three-digit land-use code in a column, or None if it holds none.

    Lorain pads its CLASSCD ("510  ") and sometimes appends an abatement code
    after it ("510  710 "); the land use is the first token. Cuyahoga's four-digit
    codes are read by their first three ("5100" -> "510").
    """
    head = str(code or "").split()
    if not head or not head[0][:3].isdigit():
        return None
    return head[0][:3]


# ── per-county configuration ──────────────────────────────────────────────────


@dataclass(frozen=True)
class County:
    """Everything that is a fact about one county's layer. See the docstring."""

    name: str
    url: str
    #: The explicit outFields list. Every one of these layers also carries owner
    #: names and mailing addresses; none of them is ever listed here.
    fields: tuple[str, ...]
    pid: str | None                 # parcel id column; Delaware publishes none
    address: str                    # the situs column
    year: str                       # the ACTUAL year-built column
    attribution: str
    area: str | None = None
    stories: str | None = None
    wall: str | None = None
    condition: str | None = None
    #: Columns carrying a DTE land-use code, in order of authority. Where a county
    #: carries two (Lorain), the first non-blank one is the parcel's land use; see
    #: Lorain's entry for the measurement that decided which comes first.
    land_use: tuple[str, ...] = ()
    #: Raw land-use codes, beyond 550, of condominium units: rows whose polygon
    #: may be the whole building's or complex's rather than the unit's own.
    condo_codes: frozenset[str] = frozenset()
    #: Whether a trailing quadrant (NW/NE/SW/SE) present on only one side of a
    #: comparison may be set aside (Fairfield and Licking; see _quadrant_free).
    quadrant_optional: bool = False
    #: The measured "not recorded" values of the year column, beyond None.
    year_missing: frozenset = frozenset()
    #: Raw land-use codes of rows that are not anybody's parcel of residence and
    #: overlap the homes around them — common areas, association land, rights of
    #: way, condominium garages. Dropped in fetch, before the parcel is chosen.
    placeholder_codes: frozenset[str] = frozenset()
    #: Raw land-use codes, beyond _VACANT, that say the land is vacant.
    vacant_codes: frozenset[str] = frozenset()
    #: Whether the year column dates only dwellings (True) or any building
    #: (False, Delaware), in which case the year needs a home's land-use code.
    year_is_dwellings: bool = True
    #: Cuyahoga: the residential-building count, and the NEWEST building's year,
    #: which must equal the year read for that year to describe "the house".
    building_count: str | None = None
    newest_year: str | None = None
    #: An extra attribute predicate sent with every request (the Columbus mirror
    #: serves seven counties; a county's lookup reads only that county's rows).
    where: str | None = None
    #: How to read the parcel's own unit designator, for a reader who typed one.
    unit_of_row: Callable[[dict], str | None] | None = None
    #: The situs reduced to the street address, where the column runs on.
    clean_address: Callable[[str | None], str | None] | None = None
    vintage: Callable[[dict], str] = field(default=lambda row: DATA_VINTAGE)
    read_slice: float = _shared._READ_SLICE_S
    timeout: float = _shared.TIMEOUT

    @property
    def out_fields(self) -> str:
        return ",".join(self.fields)


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


def _dated(base: str, column: str, wording: str) -> Callable[[dict], str]:
    """A vintage read off the row's own date column, falling back to ``base``."""
    def vintage(row: dict) -> str:
        day = _date_of(row.get(column))
        return f"{base}, {wording} {day}" if day else base
    return vintage


def _trailing_unit(address: str | None) -> str | None:
    """A unit written after the street type with no marker: "1161 WOODBROOK LN 368".

    Franklin writes its condominium units both ways — "2300 N WOODBROOK E CR UNIT
    E" and "1161 WOODBROOK LN 368" — and only the marked form is the shared
    ``unit_of``'s to read. The bare form is taken only where a digit-bearing token
    directly follows a street type, the same narrow rule ``address_key`` uses to
    drop it, so "100 ROUTE 66" keeps its name.
    """
    marked = unit_of(address)
    if marked:
        return marked
    tokens = str(address or "").split()
    if len(tokens) >= 3 and tokens[-2].lower() in SUFFIXES \
            and any(c.isdigit() for c in tokens[-1]):
        return tokens[-1]
    return None


def _summit_unit(row: dict) -> str | None:
    """Summit's ``unit`` column, "UNIT 1465G" -> "1465G"."""
    raw = str(row.get("unit") or "").split()
    while raw and raw[0].upper() in ("UNIT", "APT", "#", "STE", "SUITE"):
        raw = raw[1:]
    return raw[0] if raw else None


#: Franklin's own abbreviations of two street types, which the shared table does
#: not carry because elsewhere they are ambiguous (CR: circle or creek). In
#: Franklin's SITEADDRESS they are not: 2,837 addresses end in "CR" against 131
#: in "CIR" and 1 in "CRK" ("5765 WILLOW CREEK CR" is a circle named for a
#: creek), and 9,767 end in "BL" against 464 in "BLVD". Without the respelling
#: none of those ~12,600 parcels could ever be confirmed against the Census
#: matcher's "CIR" and "BLVD".
_FRANKLIN_TYPES = {"CR": "CIR", "BL": "BLVD"}


def _franklin_street(raw: str | None) -> str | None:
    """Franklin's SITEADDRESS with its CR and BL street types spelled out.

    Only a token after the first word of the name is touched, so a street whose
    NAME is "CR" or "BL" keeps it.
    """
    tokens = str(raw or "").split()
    return " ".join(_FRANKLIN_TYPES.get(t.upper(), t) if i >= 2 else t
                    for i, t in enumerate(tokens)) or None


_CITY_TAIL_RE = re.compile(r"^(?P<street>.*\S)\s{2,}\S.*$")


def _lorain_street(raw: str | None) -> str | None:
    """Lorain's situs with its city, state and ZIP removed.

    The column runs the mailing tail on with no comma before the city —
    "5683   BOXWOOD DR  LORAIN, OH 44053", "1142  W 12TH ST  NORTH RIDGEVILLE, OH
    44039" — and pads its fields with runs of spaces. The city is what follows the
    LAST run of two or more spaces before the comma. Applied only where the
    ", OH" tail is present (all but the 226 null rows of 202,027), so a bare street
    address is never cut. A row the rule cannot read ends up with no usable
    address, which fails closed: it cannot confirm a parcel.
    """
    text = str(raw or "")
    if "," not in text:
        return text or None
    head = text.split(",")[0]
    m = _CITY_TAIL_RE.match(head)
    return " ".join(m.group("street").split()) if m else None


COUNTIES: dict[str, County] = {
    # ── the five live, auditor-published layers ──────────────────────────────
    "39049": County(
        name="Franklin",
        url=FRANKLIN_URL,
        fields=("PARCELID", "SITEADDRESS", "CLASSCD", "RESYRBLT", "RESFLRAREA_AG"),
        pid="PARCELID", address="SITEADDRESS", year="RESYRBLT",
        area="RESFLRAREA_AG", land_use=("CLASSCD",),
        # CLASSDSCRP: 540 "HOMEOWNER ASSOC FOR A SUBDIVISION", 555 "CONDO
        # ASSOCIATION HOLDINGS", 559 "CONDOMINIUM GARAGE FOR UNITS".
        placeholder_codes=frozenset({"540", "555", "559"}),
        # 551-553 "CONDO 4-19 / 20-39 / 40+ RENTAL UNITS".
        condo_codes=frozenset({"551", "552", "553"}),
        clean_address=_franklin_street,
        unit_of_row=lambda row: _trailing_unit(_franklin_street(row.get("SITEADDRESS"))),
        attribution="Franklin County Auditor tax parcels (keyless)",
        vintage=lambda row: ("Franklin County Auditor tax parcels, queried live "
                             "(the layer carries no data date)"),
    ),
    "39035": County(
        name="Cuyahoga",
        url=CUYAHOGA_URL,
        fields=("parcel_id", "par_addr_all", "parcel_unit", "tax_luc",
                "res_bldg_count", "min_age", "max_age", "total_res_liv_area",
                "max_res_heights", "update_date"),
        pid="parcel_id", address="par_addr_all", year="min_age",
        newest_year="max_age", building_count="res_bldg_count",
        area="total_res_liv_area", stories="max_res_heights",
        land_use=("tax_luc",), year_missing=frozenset({0.0}),
        # tax_luc_description: 5800 "COMMON AREA PLATTED", 5799 "LISTED WITH"
        # (a parcel billed with another, carrying nothing of its own).
        placeholder_codes=frozenset({"5800", "5799"}),
        unit_of_row=lambda row: (str(row.get("parcel_unit") or "").strip() or None),
        attribution="Cuyahoga County Fiscal Office tax parcels (keyless)",
        vintage=_dated("Cuyahoga County Fiscal Office tax parcels", "update_date",
                       "updated"),
    ),
    "39153": County(
        name="Summit",
        url=SUMMIT_URL,
        fields=("parcelid", "siteaddress", "unit", "usecd", "resyrblt",
                "resflrarea", "floorcount"),
        pid="parcelid", address="siteaddress", year="resyrblt",
        area="resflrarea", stories="floorcount", land_use=("usecd",),
        unit_of_row=_summit_unit,
        attribution="Summit County Fiscal Office tax parcels (keyless)",
        vintage=lambda row: ("Summit County Fiscal Office tax parcels "
                             "(Parcels_07162026 layer), queried live"),
    ),
    "39113": County(
        name="Montgomery",
        url=MONTGOMERY_URL,
        # A join of the parcel polygons to the auditor's CAMA extract, so every
        # name is qualified and must be sent exactly so.
        fields=("SDE.mc_parcel_polygon.TAXPINNO", "SDE.WEB_CAMA.PARLOC",
                "SDE.WEB_CAMA.LUC", "SDE.WEB_CAMA.DWEL_YRBLT",
                "SDE.WEB_CAMA.DWEL_SFLA", "SDE.WEB_CAMA.DWEL_STORIES",
                "SDE.WEB_CAMA.DWEL_EXTWALL", "SDE.WEB_CAMA.CREATEDATE"),
        pid="SDE.mc_parcel_polygon.TAXPINNO", address="SDE.WEB_CAMA.PARLOC",
        year="SDE.WEB_CAMA.DWEL_YRBLT", area="SDE.WEB_CAMA.DWEL_SFLA",
        stories="SDE.WEB_CAMA.DWEL_STORIES", wall="SDE.WEB_CAMA.DWEL_EXTWALL",
        land_use=("SDE.WEB_CAMA.LUC",), year_missing=frozenset({0.0}),
        attribution="Montgomery County Auditor parcels and CAMA (keyless)",
        vintage=_dated("Montgomery County Auditor parcels and CAMA",
                       "SDE.WEB_CAMA.CREATEDATE", "CAMA extract of"),
        read_slice=3.0, timeout=6.0,
    ),
    "39041": County(
        name="Delaware",
        url=DELAWARE_URL,
        fields=("ADDR1", "CLASS", "YRBUILT", "SQFT", "STORYHGT"),
        pid=None, address="ADDR1", year="YRBUILT", area="SQFT",
        stories="STORYHGT", land_use=("CLASS",), year_missing=frozenset({0.0}),
        year_is_dwellings=False,
        attribution="Delaware County Auditor parcels (keyless)",
        vintage=lambda row: "Delaware County Auditor parcels, queried live",
        read_slice=2.0, timeout=_shared.TIMEOUT,
    ),
    # ── two dated snapshots ──────────────────────────────────────────────────
    "39017": County(
        name="Butler",
        url=BUTLER_URL,
        fields=("PIN", "LOCATION", "LUC", "YRBLT", "SFLA", "STORIES", "CDU"),
        pid="PIN", address="LOCATION", year="YRBLT", area="SFLA",
        stories="STORIES", condition="CDU", land_use=("LUC",),
        year_missing=frozenset({0.0}),
        attribution="Butler County Auditor land-use layer (keyless)",
        vintage=lambda row: ("Butler County Auditor 2024 reappraisal snapshot "
                             "(nothing built after 2024 is in it)"),
    ),
    "39093": County(
        name="Lorain",
        url=LORAIN_URL,
        fields=("PARCELID", "SITEADDRESS", "USECD", "CLASSCD", "RESYRBLT",
                "RESFLRAREA"),
        pid="PARCELID", address="SITEADDRESS", year="RESYRBLT", area="RESFLRAREA",
        # CLASSCD first. The two columns disagree on 4,626 rows about vacant
        # land versus a house alone, and the rows say which is current: of
        # 3,944 that USECD calls vacant (500) and CLASSCD a single-family house
        # (510), 3,922 carry a year built — averaging 2013 —
        # and 3,921 a floor area: houses built on lots USECD still files as they
        # were platted. Of 682 the other way round, 18 carry a year. USECD is read
        # only where CLASSCD is blank (2,857 rows have no CLASSCD).
        land_use=("CLASSCD", "USECD"), year_missing=frozenset({0.0}),
        # CLASSCD descriptions: 553 "H.O.A. COMMON AREA"; USEDSCRP and CLASSDSCRP:
        # 555 "RIGHT OF WAY".
        placeholder_codes=frozenset({"553", "555"}),
        # USEDSCRP 508 "VACANT LAND COST AS C/I".
        vacant_codes=frozenset({"508"}),
        clean_address=_lorain_street,
        attribution="Lorain County Auditor ownership parcels (keyless)",
        vintage=lambda row: ("Lorain County Auditor 'Ownership Parcels 2025' "
                             "public view (a periodically republished snapshot)"),
    ),
    # ── two counties through the City of Columbus's mirror ───────────────────
    "39045": County(
        name="Fairfield",
        url=COLUMBUS_URL,
        fields=("PARCELID", "SITEADDRESS", "CLASSCD", "RESYRBLT", "SHP_UPLD_DATE"),
        pid="PARCELID", address="SITEADDRESS", year="RESYRBLT",
        land_use=("CLASSCD",), year_missing=frozenset({0.0}),
        where="COUNTY='Fairfield'", quadrant_optional=True,
        unit_of_row=lambda row: _trailing_unit(row.get("SITEADDRESS")),
        attribution=("Fairfield County Auditor records via the City of Columbus "
                     "Central Ohio Parcels layer (keyless)"),
        vintage=_dated("Fairfield County Auditor records via the City of Columbus",
                       "SHP_UPLD_DATE", "copied"),
    ),
    "39089": County(
        name="Licking",
        url=COLUMBUS_URL,
        fields=("PARCELID", "SITEADDRESS", "CLASSCD", "RESYRBLT", "SHP_UPLD_DATE"),
        pid="PARCELID", address="SITEADDRESS", year="RESYRBLT",
        land_use=("CLASSCD",), year_missing=frozenset({0.0}),
        # CLASSDSCRP: 552 "Condo or PUD Garage", 559 "Condominium Owner Garage".
        placeholder_codes=frozenset({"552", "559"}),
        where="COUNTY='Licking'", quadrant_optional=True,
        unit_of_row=lambda row: _trailing_unit(row.get("SITEADDRESS")),
        attribution=("Licking County Auditor records via the City of Columbus "
                     "Central Ohio Parcels layer (keyless)"),
        vintage=_dated("Licking County Auditor records via the City of Columbus",
                       "SHP_UPLD_DATE", "copied"),
    ),
}

COUNTY_FIPS = frozenset(COUNTIES)

#: The module's own clock: the largest any county is given, which is what a
#: lookup that must first ask which county it is in starts with. Each county's
#: requests run on that county's ``read_slice`` and ``timeout``; a test pins every
#: pair, and this one, under ``config.UPSTREAM_HOST_BUDGET``.
READ_SLICE_S = max(c.read_slice for c in COUNTIES.values())
LOOKUP_TIMEOUT = max(c.timeout for c in COUNTIES.values())


# ── reading one row ─────────────────────────────────────────────────────────────


def _land_uses(cfg: County, row: dict) -> list[str]:
    """The row's raw land-use code, from the most authoritative non-blank column.

    A list (of at most one) so that "the row states no land use" stays distinct
    from any code. Lorain pads ("510  ") and sometimes appends a second code
    ("510  710 "); the land use is the first token.
    """
    for column in cfg.land_use:
        raw = str(row.get(column) or "").split()
        if raw:
            return [raw[0]]
    return []


def _says_no_home(cfg: County, row: dict) -> bool:
    """Whether the row explicitly says no dwelling stands on this parcel.

    Three statements count, and silence never does:

    * a land-use code for vacant land, or a placeholder code. Franklin carries 35
      rows coded 500-502 with a year — a demolished house's, or a slip — and
      Montgomery files a house's side lot as 500 under the house's own address.
    * a residential-building count of zero, where the county publishes one.
    * for a county whose year dates any building (Delaware), the absence of a
      home's code.
    """
    codes = _land_uses(cfg, row)
    for code in codes:
        if (_dte(code) in _VACANT or code in cfg.vacant_codes
                or code in cfg.placeholder_codes):
            return True
    if cfg.building_count:
        count = num(row.get(cfg.building_count))
        if count is not None and count <= 0:
            return True
    if not cfg.year_is_dwellings:
        if not codes:
            return True
        return not all(_is_a_home_code(_dte(c)) for c in codes)
    return False


def _is_condo(cfg: County, row: dict) -> bool:
    return any(_dte(c) == "550" or c in cfg.condo_codes for c in _land_uses(cfg, row))


def _is_a_home_code(code: str | None) -> bool:
    """Agricultural (a farmhouse), apartments, or residential."""
    return bool(code) and (code[0] in "15" or code in _APARTMENTS)


def _street(cfg: County, row: dict) -> str | None:
    raw = row.get(cfg.address)
    return cfg.clean_address(raw) if cfg.clean_address else raw


def _year(cfg: County, row: dict) -> int | None:
    year = num(row.get(cfg.year))
    if year is None or year in cfg.year_missing:
        return None
    if not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 or not float(year).is_integer():
        return None
    if _says_no_home(cfg, row):
        return None
    if cfg.newest_year:
        # Cuyahoga's min_age/max_age are YEARS despite their names: the oldest
        # and the newest residential building's year built. Where the parcel's
        # dwellings were built in different years — a front house and a rear
        # house — which of them is the reader's is not something the record says.
        if num(row.get(cfg.newest_year)) != year:
            return None
    return int(year)


def _one_dwelling(cfg: County, parcel: dict) -> bool:
    """Whether the record positively says it is ONE home in one building.

    Area and stories mean one dwelling. The only evidence the layers carry is the
    single-family land-use code (510-515), so it is required in every land-use
    column the row has; on top of that a Cuyahoga parcel must count exactly one
    residential building, the parcel must have exactly one street address (Lorain
    lists a double's two addresses as two rows of one parcel), and its address may
    not name a unit. A condominium unit (550) never qualifies: its area is one
    apartment of a building, and its floor count, where recorded, the building's.
    """
    codes = [_dte(c) for c in _land_uses(cfg, parcel)]
    if not codes or not all(c in _ONE_FAMILY for c in codes):
        return False
    if cfg.building_count and num(parcel.get(cfg.building_count)) != 1:
        return False
    if len(parcel["_addresses"]) > 1:
        return False
    return not any(unit_of(a) for a in parcel["_addresses"])


def _area(cfg: County, parcel: dict) -> float | None:
    if not cfg.area:
        return None
    area = num(parcel.get(cfg.area))
    if area is None or area <= 0 or not _one_dwelling(cfg, parcel):
        return None
    if _says_no_home(cfg, parcel):
        return None
    return area


#: A house's story count, as a whole number. Half stories (1.5, 2.5) and
#: Cuyahoga's quarter stories have no whole-number reading — Cook's call for
#: "1.5 Story". Above four is a keying error on a single-family parcel (Delaware
#: records six to nine on eleven of its 56,482 single-family lots).
_MAX_STORIES = 4


def _stories(cfg: County, parcel: dict) -> int | None:
    if not cfg.stories:
        return None
    floors = num(parcel.get(cfg.stories))
    if floors is None or not float(floors).is_integer():
        return None
    if not 1 <= floors <= _MAX_STORIES or not _one_dwelling(cfg, parcel):
        return None
    if _says_no_home(cfg, parcel):
        return None
    return int(floors)


# Montgomery's DWEL_EXTWALL -> the label's vocabulary. Measured over the
# county's 213,216 residential rows: BRICK 70,965; ALUMINUM/VINYL 57,408;
# MASONRY & FRAME 27,543; FRAME 25,126; STUCCO 1,920; ASBESTOS 698; BLOCK 692;
# STONE 406; CONCRETE 79; blank 28,385 (vacant land).
_WALL = {
    "FRAME": "frame",
    # Aluminum OR vinyl siding: frame either way (Utah's "Metal Vinyl Siding").
    "ALUMINUM/VINYL": "frame",
    # Asbestos-cement shingle is siding hung on a framed wall (DC's "Shingle").
    "ASBESTOS": "frame",
    # A wall recorded as brick. Whether it is solid brick or a brick veneer on
    # frame the code does not say — the same knowingly lossy reading Cook makes
    # for its "Masonry", paid for in confidence (base.TRANSLATED), not coverage.
    "BRICK": "brick",
    "BLOCK": "block",
    "STONE": "stone",
}
# Deliberately unmapped:
#   MASONRY & FRAME  part masonry, part frame — and the masonry may be brick or
#                    stone; the label's brick-frame is a brick face on frame
#   STUCCO           stucco on frame or on block; the structure is not named
#   CONCRETE         cast concrete is not concrete block, the label's only
#                    concrete value


def _wall(cfg: County, parcel: dict) -> str | None:
    if not cfg.wall or _says_no_home(cfg, parcel):
        return None
    return _WALL.get(" ".join(str(parcel.get(cfg.wall) or "").split()).upper())


# Butler's CDU — "condition, desirability and usefulness", the iasWorld rating
# appraisers set from a building's physical condition. Measured on 135,950
# residential rows: AV 62,737; GD 39,661; FR 10,043; VG 5,938; PR 1,468; VP 166;
# UN 103; EX 38; blank 15,796.
_CONDITION = {
    "EX": "excellent",
    "GD": "good",
    "AV": "average",
    "FR": "fair",
    "PR": "poor",
    "UN": "unsound",
}
# Deliberately unmapped: VG (very good) and VP (very poor) each fall between two
# of the label's grades, and choosing either neighbor would be a guess.


def _condition(cfg: County, parcel: dict) -> str | None:
    if not cfg.condition or _says_no_home(cfg, parcel):
        return None
    return _CONDITION.get(str(parcel.get(cfg.condition) or "").strip().upper())


# ── the candidates ─────────────────────────────────────────────────────────────

#: The columns that are facts about the building rather than the parcel's
#: identity or address. Two rows of one parcel id must agree on all of them.
def _fact_columns(cfg: County) -> tuple[str, ...]:
    cols = (cfg.year, cfg.area, cfg.stories, cfg.wall, cfg.condition,
            cfg.building_count, cfg.newest_year, *cfg.land_use)
    return tuple(c for c in cols if c)


def _pid(cfg: County, row: dict) -> str | None:
    if not cfg.pid:
        return None
    pid = str(row.get(cfg.pid) or "").strip()
    return pid or None


def _is_a_record_of_nothing(cfg: County, row: dict) -> bool:
    """A row with no street address and no fact at all.

    Summit lays a homeowners'-association parcel over each condominium complex
    with a blank house number ("  SMITH RD ") and no year; Cuyahoga lays a MULTI
    footprint with no parcel id. Neither can ever contribute a fact, and either
    would make the unit under it ambiguous.
    """
    if address_key(_street(cfg, row)):
        return False
    return all(num(row.get(c)) in (None, 0) for c in
               (cfg.year, cfg.area, cfg.stories) if c)


def _parcels(cfg: County, rows: list[dict]) -> list[dict]:
    """Candidate parcels from raw rows: placeholders dropped, duplicates merged.

    * A county with parcel ids must give one: a row with none is a record of
      nothing (Cuyahoga's MULTI footprints). Delaware publishes no id at all, so
      there each row is its own candidate.
    * Rows that say no home stands on them are dropped (``_says_no_home``):
      vacant land, common areas, association land, rights of way, garage
      parcels, a recorded zero dwellings, and in Delaware a shop. Every fact such
      a row could offer is refused anyway, so it can never be an answer — but as
      a candidate it makes the home beside it ambiguous: Montgomery files 6415
      LANDSEND CT's side lot (500) under the house's own address, and Cuyahoga
      lays a factless, dwelling-less parcel beside 2782 RICHMOND RD under the
      same address. Removing rows that cannot be the answer can only turn
      "ambiguous" into "one"; the address confirmation is untouched.
    * Rows sharing a parcel id are ONE candidate. Cuyahoga repeats identical rows
      (613,361 rows carry 520,344 distinct ids; parcel 43306050 has four), and
      Lorain writes one row per street address of a parcel (3235 and 3237 GROVE
      AVE are one parcel, two rows). Offered raw, either is several candidates and
      the most ordinary house reads as ambiguous. Merging can only turn
      "ambiguous" into "one real parcel"; rows of one id that disagree about any
      building fact are a broken join and are not offered at all.
    """
    groups: dict[object, list[dict]] = {}
    for i, row in enumerate(rows):
        if _says_no_home(cfg, row) or _is_a_record_of_nothing(cfg, row):
            continue
        if cfg.pid:
            pid = _pid(cfg, row)
            if pid is None:
                continue
            groups.setdefault(pid, []).append(row)
        else:
            groups[("row", i)] = [row]
    facts = _fact_columns(cfg)
    out = []
    for key, members in groups.items():
        if len({tuple(m.get(c) for c in facts) for m in members}) > 1:
            continue
        parcel = dict(members[0])
        addresses, seen = [], set()
        for m in members:
            street = _street(cfg, m)
            k = address_key(street)
            if k is not None and k not in seen:
                seen.add(k)
                addresses.append(street)
        parcel["_addresses"] = addresses
        parcel["_units"] = {u for u in (cfg.unit_of_row(m) if cfg.unit_of_row
                                        else unit_of(_street(cfg, m))
                                        for m in members) if u}
        out.append(parcel)
    return out


def _norm_unit(unit: str | None) -> str:
    return str(unit or "").strip().lstrip("#").casefold()


def _could_be_unit(parcel: dict, unit: str) -> bool:
    """Whether this parcel could be the typed unit's: it names that unit, or none."""
    units = parcel["_units"]
    return not units or _norm_unit(unit) in {_norm_unit(u) for u in units}


_QUADRANTS = frozenset({"nw", "ne", "sw", "se"})


def _quadrant_free(a: str | None, b: str | None) -> bool:
    """Whether two addresses agree once a trailing quadrant on ONE side is set aside.

    Fairfield and Licking address their townships by quadrant, after the street
    type — "13113 RUSTIC DR NW", "8297 BLACKS RD SW" — and the Census matcher
    writes it on one side and not the other, in both directions: typed "13113
    RUSTIC DR NW" comes back "13113 RUSTIC DR", and typed "8297 BLACKS RD" comes
    back "8297 BLACKS RD SW" against a roll that has no quadrant. Two quadrants
    that are both written and differ still never match, and the rest of the
    address — number, name, type — must agree exactly as ``same_address`` requires.
    A quadrant names a quarter of the county, so the twin this could confuse would
    have to lie within 80 m of the point and across a quadrant axis with the same
    number and street; ``select_parcel`` refuses two matches all the same.
    """
    ka, kb = address_key(a), address_key(b)
    if ka is None or kb is None or ka[0] != kb[0]:
        return False
    if not (ka[2] is None or kb[2] is None or ka[2] == kb[2]):
        return False
    na, nb = list(ka[1]), list(kb[1])
    qa = na[-1] if na and na[-1] in _QUADRANTS else None
    qb = nb[-1] if nb and nb[-1] in _QUADRANTS else None
    if qa and qb:
        return na == nb
    if qa:
        na = na[:-1]
    if qb:
        nb = nb[:-1]
    return bool(na) and na == nb


def _address_for(cfg: County, query: str | None):
    """The address accessor ``select_parcel`` compares against.

    A merged parcel can carry several street addresses (Lorain's 3235/3237 GROVE
    AVE). The parcel IS at each of them, so it is offered under whichever agrees
    with the query; with none agreeing it is offered under its first, which then
    fails the comparison exactly as it should. Where a county's quadrant is
    optional (``_quadrant_free``) and only the quadrant differs, the parcel is
    offered under the query's own spelling, which is the one comparison
    ``select_parcel`` can make.
    """
    def address_of(parcel: dict) -> str | None:
        addresses = parcel["_addresses"]
        if query:
            for a in addresses:
                if same_address(query, a):
                    return a
            if cfg.quadrant_optional:
                for a in addresses:
                    if _quadrant_free(query, a):
                        return query
        return addresses[0] if addresses else None
    return address_of


# ── which county ───────────────────────────────────────────────────────────────


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the covered Ohio county this point is in, from TIGERweb.

    Only for a caller that did not say: the registry passes the county it routed
    on to an adapter whose ``lookup`` accepts it, so in the product this request
    is never made. Measured at nine Ohio points, 0.06-0.08 s warm.
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


def _parcel_at(lat: float, lon: float, address: str | None = None,
               county_fips: str | None = None,
               *, deadline: float | None = None) -> tuple[County, dict] | None:
    """The county's record of the parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s; see it for why the nearest
    parcel is never taken.
    """
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips in COUNTY_FIPS:
        deadline = deadline_from(deadline, COUNTIES[fips].timeout)
    else:
        deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
        fips = _county_at(lat, lon, deadline=deadline)
        if fips is None:
            return None
    cfg = COUNTIES[fips]
    unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            rows = _shared.arcgis_parcels(cfg.url, lat, lon, cfg.out_fields,
                                          distance_m, deadline=deadline,
                                          read_slice=cfg.read_slice,
                                          where=cfg.where)
            fetched[distance_m] = _parcels(cfg, rows)
        found = fetched[distance_m]
        if distance_m == 0 and address:
            # A condominium unit's polygon is not evidence of where the unit is.
            # Delaware gives every unit the whole complex's outline — 81 units of
            # OAK CREEK CONDOS share one 222,542 sq ft polygon — and Franklin
            # stacks a building's units on one footprint, so the point is "inside"
            # all of them and the containment answer is ambiguous by construction.
            # With an address in hand the unit is found the way Washington's are,
            # by address: the buffer (which contains the point) must hold exactly
            # one unit whose address agrees. Without an address nothing changes,
            # and a stack stays ambiguous.
            found = [p for p in found if not _is_condo(cfg, p)]
        # A reader who typed a unit cannot live in a parcel that names a
        # DIFFERENT unit. Stacked condominium units share one street address, so
        # without this a typed "#368" faces every unit of the building and is
        # refused. Dropping rows that cannot be the answer is the sanctioned
        # shape (see select_parcel): it can turn "ambiguous" into "one", never
        # admit a parcel the address check would not.
        return [p for p in found if _could_be_unit(p, unit)] if unit else found

    chosen = select_parcel(fetch, address, _address_for(cfg, address))
    return (cfg, chosen) if chosen is not None else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    found = _parcel_at(lat, lon, address, county_fips)
    if not found:
        return None
    cfg, parcel = found
    year_built = _year(cfg, parcel)
    sqft = _area(cfg, parcel)
    stories = _stories(cfg, parcel)
    construction = _wall(cfg, parcel)
    condition = _condition(cfg, parcel)
    if all(v is None for v in (year_built, sqft, stories, construction, condition)):
        return None
    return AssessorRecord(
        source=cfg.attribution,
        data_vintage=cfg.vintage(parcel),
        parcel_id=_pid(cfg, parcel),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        construction=construction,
        condition=condition,
        # No Ohio layer here publishes a foundation type.
    )


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county auditor says is standing at this point, or None.

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
        log.debug("Ohio assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
