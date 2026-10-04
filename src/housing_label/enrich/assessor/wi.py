#!/usr/bin/env python3
"""Wisconsin — the City of Milwaukee's and the City of Madison's assessment rolls.

Configured, measured and verified for both cities, and **held**: neither county
is registered (``_HELD_FOR_COVERAGE``), because in Wisconsin the assessor is the
municipality, not the county, and each of these sources covers only its own city.
Registering a county is a claim the label makes to a reader — that an observed
year built is available there — and these two sources make it for 61% of
Milwaukee County's homes and 51% of Dane County's. Whether that is enough is a
product decision; if it is, enabling a county is deleting its line from
``_HELD_FOR_COVERAGE``.

Why only the two cities
-----------------------
Wisconsin assesses property by city, village and town — about 1,850 of them —
and nobody above them collects the building records. Measured 2026-10-04:

* **The statewide parcel layer** (the State Cartographer's Office
  ``Wisconsin_Statewide_Parcels_DB``, "V12", the 2026 edition that succeeded
  V11) carries the parcel id, the site address, the assessed values and the
  property class, and no year built, floor area or story count; its schema is
  the document at sco.wisc.edu/parcels.
* **Milwaukee County** (its Land Information Office's ``lio.milwaukeecountywi.gov``
  folders and its ArcGIS Online organization's 160 services, every layer's
  fields read) publishes county-wide parcels with owner, address, class and
  values, and a dwelling count, but no year built anywhere. The suburbs' own
  assessors publish none either: Oak Creek's parcel layer carries the county's
  columns and no more, and no public parcel service with building data was
  found for West Allis, Wauwatosa, Greenfield, Franklin or any smaller suburb.
* **Dane County**'s tax-parcel services (``dcimapapps.danecounty.gov``) carry
  owner, address and values, and no building data.

So the observed data is city data. 2020 Census housing units (TIGERweb):

  ===========  =====  ==========  ===================  ======
  county       FIPS   all homes   homes in the city     share
  ===========  =====  ==========  ===================  ======
  Milwaukee    55079     424,191  Milwaukee  257,723    60.8%
  Dane         55025     248,795  Madison    126,070    50.7%
  ===========  =====  ==========  ===================  ======

The next five municipalities of Milwaukee County (West Allis 29,015, Wauwatosa
23,148, Greenfield 18,035, Oak Creek 15,620, Franklin 14,771) would take it to
85%; none publishes a year.

A lookup outside the city fails safe: the city's layer has no parcel there, the
containment and buffered queries both come back empty (two requests, about
0.8 s in Milwaukee, 0.2 s in Madison), and the lookup answers None.

The two sources
---------------
**Milwaukee: ``property/parcels_mprop/MapServer/2``**, "Parcels - MPROP_full":
the City's parcel polygons carrying every column of its Master Property file
(MPROP), the assessor's record of every property in the city since 1975,
refreshed daily — 159,949 parcels, one per tax key, condominium units stacked
one polygon per unit. Measured over its 140,756 home parcels (land uses 8810,
8811, 8820, 8830): a year built on 140,564 (99.9%), a floor area on 140,496.
The roll year is on each row (``YR_ASSMT``, 2026).

**Madison: ``Public/OPEN_DATA2/FeatureServer/0``**, "Tax Parcels (Assessor
Property Information)": the City Assessor's parcels, refreshed daily — 82,423
parcels. A year built on 49,708 of 49,738 single-family parcels, 3,776 of 3,777
two- and three-unit parcels, all 2,190 apartment parcels, and 11,974 of 16,949
condominium records (the other 4,975 carry no dwelling: parking and storage
units, and see below).

What each record says, and what the label takes
-----------------------------------------------
Milwaukee (MPROP data dictionary, Fall 2024 edition, on data.milwaukee.gov):

* ``YR_BUILT`` — "the year of construction of the structure on the property.
  For properties with more than one structure, the year built of the most
  prominent structure is used. This field is only maintained for residential
  parcels." So the year is read only where the land use says a home stands
  (8810 single family, 8811 condominium, 8820 two-family, 8830 multi-family,
  8899 mixed residential/commercial) and ``NR_UNITS`` is not zero; a shop's year
  is never read, and neither is a vacant lot's (8880, 8885).
* ``BLDG_AREA`` — "the total useable floor area of the structure", the WHOLE
  building, so it is reported only on a single-family parcel (8810) with one
  dwelling unit and one street address. A duplex's two flats are one area.
* ``NR_STORIES`` — "above grade ... does not include basement", written "1",
  "1.5", "2.0". Half stories have no whole-number reading (Cook's call for "1.5
  Story", Ohio's) and are left empty, as is anything above 4 on a house; same
  one-dwelling rule as the area.
* ``BASEMENT`` is documented as Full / None / Partial / Crawl, but the layer
  holds only ``Y`` and ``N`` (120,489 and 13,861 of the single-family,
  condominium and two-family parcels). "Has a basement" does not
  say full or partial, and "no basement" does not say slab or crawl, so it is
  not read. MPROP carries no wall material or condition.

Madison:

* ``YearBuilt``, read where ``TotalDwellingUnits`` is at least one — the roll's
  own count of homes, which turns away offices and shops (whose ``YearBuilt`` is
  filled too) and the 0-unit condominium records.
* ``TotalLivingArea`` — the sum of the dwelling's floors (``FirstFloor`` +
  ``SecondFloor`` + ... + ``FinishedAttic``, checked on sampled rows), reported
  only for a "Single family" parcel with ``TotalDwellingUnits`` of 1.
  ``MoreThanOneBuild`` is YES on 12,222 of those 49,738 parcels; the area does
  not include the second building (it is the floors of one dwelling, and the
  roll still counts one home), so it is not used to refuse — it is overwhelmingly
  a detached garage.
* ``ExteriorWall1`` — see ``_MADISON_WALL`` for what is translated and what is
  not. Read only where ``ExteriorWall2`` is blank or says the same: a house
  recorded as "Aluminum/Vinyl" with "Masonry Facing" (12,068 single-family to
  three-unit parcels) is a frame house with a brick or stone front, and the
  label's ``brick-frame`` is a different claim.
* No story count (the floor areas are not one), no foundation type, no
  condition grade.

Effective years are not requested anywhere. Madison's ``MaxConstructionYear``
is not the year built (it is 0 on every single-family row) and is not read.

The traps
---------
**Milwaukee's duplex ranges.** 16,077 of 33,874 two-family parcels are filed
under a range, ``HOUSE_NR_LO`` 9371 to ``HOUSE_NR_HI`` 9373 — one building,
two doors — and the Census matcher returns whichever door was typed. So a
parcel is offered under both END numbers of its range, never the numbers in
between. ``HOUSE_NR_SFX`` ("A", "-A": a second door, 2,113 home parcels) is not
part of the comparable number; the address check still needs everything else to
agree, and two parcels that differ only by the suffix (6918 and 6918A) are two
candidates for one address, which ``select_parcel`` refuses.

**Milwaukee's street types** are the City's own two-letter codes (MPROP
Appendix I, "City of Milwaukee Official Street Types"): AV, BL, CR, CT, DR, LA,
PK, PL, RD, ST, TR, WA. In ``STTYPE`` — a column holding nothing else — BL is
Boulevard, CR Circle, LA Lane, PK Parkway, TR Terrace and WA Way by the City's
own definition, so ``_MKE_TYPES`` respells them (2,402, 401, 455, 324, 512 and
115 home parcels) before the shared comparison. The shared table does not take
them because elsewhere CR is also Creek and PK also Park.

**Street names the matcher spells differently.** Geocoding one home on every
multi-word street name in MPROP, and one of every street type in Madison's
roll, found five Milwaukee names ("MC KINLEY" for the matcher's "MCKINLEY",
``_MKE_NAMES``) and four Madison types plus a "Crest" form ("Waban Hl" for
"WABAN HILL", ``_MSN_TYPES``). A parcel is offered under BOTH spellings, the
matcher's and the roll's: the product asks with the geocoder's address where
it agrees with what the reader typed, but with the reader's own words where
the two differ in the street's name (``location.assessor_address``), so a
reader who types the roll's spelling arrives with it. Two spellings of one
street cannot match a different one.

**Condominiums, both cities.** A unit is filed as its own parcel and given the
whole building's or complex's polygon — Madison's 1 Cherokee Cir units each
carry an 801,733 sq ft complex — so containment cannot pick one; Madison also
lays a "Condominium-Notation" record over each complex (``Unit`` "CDM", no
year, no dwelling), dropped as a record of nothing. Three rules, Ohio's and
Washington's:

* With an address in hand, condominium records are left out of the containment
  answer, and the buffer must find exactly one candidate whose address agrees.
* Units at one street address (and, in Madison, one complex, ``XRefParcel``)
  that agree on the year are ONE candidate — the building — carrying only that
  year. A reader at "1 Cherokee Cir" lives in a building whose units all say
  2002, whichever unit is theirs. Units that disagree are not offered at all.
* A typed unit ("#104") excludes every record naming a different unit first.

No floor area or story count is ever reported for a condominium: the area is
one unit's, the floors the building's, and which unit is the reader's is the
part the address does not reliably carry.

**Explicit zeros.** 184 Milwaukee home parcels record ``NR_UNITS`` of 0, and
198 Madison single-family parcels a ``TotalDwellingUnits`` of 0; those records
say no home stands there and are dropped. A missing count is not a zero.

What is never read
------------------
Both layers carry owner names, owner mailing addresses, and assessed values
(Milwaukee also conveyance dates and fees; Madison taxes and owner-occupancy).
Each city's field list is explicit and short (fourteen and thirteen columns), and
the shared helper refuses ``*``. Nothing from either source is written into the
repository.

Timing
------
Measured over 40 sampled rooftops per city, through the product's HTTP session,
with each city's own field list (2026-10-04):

  ==========  =================================  =================================
  city        contain  median / p90 / p95 / max  buffer   median / p90 / p95 / max
  ==========  =================================  =================================
  Milwaukee   0.47 / 0.51 / 0.53 / 1.02 s        0.48 / 0.50 / 0.52 / 0.52 s
  Madison     0.09 / 0.11 / 0.13 / 0.48 s        0.10 / 0.13 / 0.15 / 0.32 s
  ==========  =================================  =================================

A second Milwaukee set of 100 rooftops: containment 0.41 / 0.45 / 0.48 / 0.79 s,
buffered 0.43 / 0.46 / 0.49 / 0.52 s. A second Madison set of 150: containment
0.09 / 0.10 / 0.12 / 0.49 s, buffered 0.10 / 0.12 / 0.13 / 0.77 s. Responses
are at most 254 KB and 880 rows (a Madison condominium complex, every unit
sharing one outline), under both layers' transfer limits (200,000 and 2,000).

Milwaukee's map server thinks for half a second before it answers, every time,
and the tail is longer than the body: one containment took 1.02 s, and in the
first verification run one was cut off at a 2-second slice — which does not
read as a timeout to anyone, it reads as "no parcel here". Madison's server
answers in a tenth of a second but twice in that run went quiet past the shared
one-second slice. So the slices are 3 seconds for Milwaukee (budget 5) and 2
for Madison (budget the shared 4); neither cut anything in the final run. The
worst case a socket can hold, the budget spent connecting plus one slice, is
5 + 3 = 8 s, inside the host's 12 s (``config.UPSTREAM_HOST_BUDGET``); a test
pins each city's pair.

End to end
----------
170 homes drawn at random from the two layers themselves (random object ids
among home parcels with a year: in Milwaukee 61 single-family, 33 two-family,
8 condominium units and 8 multi-family; in Madison 47 single-family, 10
condominium units and 3 two-unit), typed as street, unit, city, state (and ZIP
in Milwaukee), geocoded through the Census matcher and ``assessor_address``
exactly as the product does, then looked up with the hold lifted:

  ==========  ======  ========  ========  =====  ==========  ==========  ========
  city        sample  geocoded  resolved  wrong  year exact  sqft exact  more
  ==========  ======  ========  ========  =====  ==========  ==========  ========
  Milwaukee      110       110       108      0     108/108       55/55  43 stor.
  Madison         60        50        45      0       45/45       35/35  30 walls
  **both**     **170**   **160**   **153**  **0**  **153/153**  **90/90**
  ==========  ======  ========  ========  =====  ==========  ==========  ========

Every geocode routed to the sampled county. 96% of geocoded homes resolved,
**none to the wrong parcel**, and every year and floor area reported equals the
sampled row's. The run's requests: containment median 0.35 s, p95 0.40, max
0.71; buffered 0.41 / 0.46 / 0.51 s; a whole lookup median 0.78 s (Milwaukee's
two half-second answers), max 1.17 s.

Not resolved: 5 Madison geocodes 99 to 116 m from their parcel; a Milwaukee
condominium tower (1660 N Prospect Ave, 271 units, all 1990) 156 m from its
geocode; and "923 S 10TH ST" typed without the roll's suffix — 923 and 923A
are two parcels and both answer to "923", so the lookup declines. The 10 Madison
geocode failures are new west-side streets the Census matcher does not yet
know. The first run, before the street-name respellings, the both-spellings
rule and the final read slices, resolved 151 with the same zero wrong.

License and terms
-----------------
* **Milwaukee** — MPROP and the parcel outlines are published on the City's
  open-data portal under **Creative Commons Attribution** (data.milwaukee.gov,
  datasets ``mprop`` and ``parcel-outlines``: license ``cc-by``). The map
  service's own item says "This map is for general reference only. It is not
  for legal, engineering, or surveying use." Each record's ``source`` names the
  City of Milwaukee Assessor's MPROP, which is the attribution CC BY asks for.
* **Madison** — the item's license is the City of Madison Data Policy
  (cityofmadison.com/policy/data): data "provided for informational purposes",
  no warranty, no liability; the City reserves intellectual-property claims but
  says a page will "so indicate" where it makes one, and the layer's item makes
  none. No restriction on querying, caching or commercial use.

The posture is every adapter's: query live, cache in process, bundle nothing,
never fetch owner data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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

NAME = "Wisconsin city assessors"
ATTRIBUTION = ("City of Milwaukee Assessor (MPROP) and City of Madison Assessor "
               "parcel records (keyless)")
DATA_VINTAGE = "Wisconsin city assessment rolls"

MILWAUKEE_URL = ("https://milwaukeemaps.milwaukee.gov/arcgis/rest/services"
                 "/property/parcels_mprop/MapServer/2/query")
MADISON_URL = ("https://maps.cityofmadison.com/arcgis/rest/services"
               "/Public/OPEN_DATA2/FeatureServer/0/query")
#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (a direct call). The registry always says.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services"
              "/TIGERweb/State_County/MapServer/1/query")


# ── reading a Milwaukee MPROP row ──────────────────────────────────────────────

#: MPROP land uses (Appendix G) on which a home stands: single family, condominium,
#: two-family, multi-family, mixed residential/commercial. Every other code —
#: 8880/8885 vacant lots, 8850 under construction, 8860-8871 parks, every
#: commercial and industrial code — is a parcel whose ``YR_BUILT`` the City does
#: not maintain ("only maintained for residential parcels") or that has no home.
_MKE_HOMES = frozenset({8810, 8811, 8820, 8830, 8899})
_MKE_SINGLE_FAMILY = 8810
_MKE_CONDO = 8811

#: The City's own street-type codes (MPROP Appendix I) that the shared table does
#: not read the same way. AV, CT, DR, PL, RD and ST it already knows.
_MKE_TYPES = {"BL": "BLVD", "CR": "CIR", "LA": "LN", "PK": "PKWY", "TR": "TER",
              "WA": "WAY"}


#: Street names MPROP spells differently from the Census matcher, found by
#: geocoding one home on every multi-word street name in the roll (57 names) and
#: comparing: "W MC KINLEY AV" comes back "W MCKINLEY AVE", and so on. The home
#: parcels on each, of 140,756: MC KINLEY 164, BLUE MOUND 86, MARTIN L KING JR 56,
#: KEEFE AVENUE (a parkway named for the avenue) 43, COLD SPRING 18. Three more
#: (DR WILLIAM FINLAYSON, VEL R PHILLIPS, DR LESTER CARTER — streets renamed in
#: recent years) the matcher does not know at all, so nothing here can help them.
_MKE_NAMES = {"MC KINLEY": "MCKINLEY", "BLUE MOUND": "BLUEMOUND",
              "MARTIN L KING JR": "DR MARTIN LUTHER KING", "KEEFE AVENUE": "KEEFE AVE",
              "COLD SPRING": "COLDSPRING"}


def _mke_street(row: dict, number, respell: bool = True) -> str | None:
    """One street address of a Milwaukee parcel, at house number ``number``,
    with the name as the matcher spells it (``respell``) or as the roll does."""
    n = num(number)
    name = " ".join(str(row.get("STREET") or "").split())
    if respell:
        name = _MKE_NAMES.get(name.upper(), name)
    if not n or n <= 0 or not float(n).is_integer() or not name:
        return None
    sttype = str(row.get("STTYPE") or "").strip().upper()
    parts = [str(int(n)), str(row.get("SDIR") or "").strip(), name,
             _MKE_TYPES.get(sttype, sttype)]
    return " ".join(p for p in parts if p)


def _distinct(addresses) -> list[str]:
    """Usable addresses, first spelling of each kept, in order."""
    out, seen = [], set()
    for a in addresses:
        k = address_key(a) if a else None
        if k is not None and k not in seen:
            seen.add(k)
            out.append(a)
    return out


def _mke_addresses(row: dict) -> list[str]:
    """The parcel's street addresses: the low end of its range, and the high end
    when there is one — never the numbers in between — each under the matcher's
    spelling of the name and the roll's.

    Both spellings, because the product asks with whichever the reader's words
    produce: the geocoder's canonical address where it agrees with what was typed
    ("W MCKINLEY AVE" for a reader who typed McKinley), but the reader's own words
    where the two differ in the street's name (``location.assessor_address``),
    which a reader who typed the roll's "Mc Kinley" makes them do. They are two
    spellings of one street, so offering the parcel under both cannot match a
    different one."""
    lo, hi = num(row.get("HOUSE_NR_LO")), num(row.get("HOUSE_NR_HI"))
    numbers = [lo] + ([hi] if hi and lo and hi > lo else [])
    return _distinct(_mke_street(row, n, respell) for n in numbers
                     for respell in (True, False))


def _mke_land_use(row: dict) -> int | None:
    use = num(row.get("LAND_USE"))
    return int(use) if use is not None else None


def _mke_no_home(row: dict) -> bool:
    """The row says no home stands here: a land use that is not a home, or a
    recorded zero dwelling units. A missing unit count is silence, not zero."""
    if _mke_land_use(row) not in _MKE_HOMES:
        return True
    units = num(row.get("NR_UNITS"))
    return units is not None and units <= 0


def _mke_one_dwelling(row: dict) -> bool:
    """A single-family parcel, one dwelling unit, one door: BLDG_AREA and
    NR_STORIES then describe the reader's house."""
    lo, hi = num(row.get("HOUSE_NR_LO")), num(row.get("HOUSE_NR_HI"))
    return (_mke_land_use(row) == _MKE_SINGLE_FAMILY
            and num(row.get("NR_UNITS")) == 1
            and not (hi and lo and hi > lo)
            and not str(row.get("HOUSE_NR_SFX") or "").strip())


def _mke_stories(row: dict) -> int | None:
    floors = num(row.get("NR_STORIES"))
    if floors is None or not float(floors).is_integer() or not 1 <= floors <= _MAX_STORIES:
        return None
    return int(floors) if _mke_one_dwelling(row) else None


def _mke_vintage(row: dict) -> str:
    year = num(row.get("YR_ASSMT"))
    base = "City of Milwaukee Master Property file (MPROP)"
    if year and 1990 <= year <= 2100:
        return f"{base}, {int(year)} assessment"
    return base


# ── reading a Madison row ──────────────────────────────────────────────────────

_MSN_SINGLE_FAMILY = "Single family"
_MSN_CONDO = "Condominium"

# Madison's ExteriorWall1 -> the label's vocabulary. Measured over the 53,515
# single-family, two- and three-unit parcels: Aluminum/Vinyl 45,472 (with the
# condominiums' share); Wood 12,680; blank 5,023; Brick 3,327; Stucco 1,352;
# Composition 924; Cement/Smart 776; Masonry Facing 749; Stone 175; Wd 2; RStl 1.
_MADISON_WALL = {
    # Siding on a framed wall, whatever the siding is made of: aluminum or vinyl
    # (Ohio's and Utah's reading), wood, composition shingle (DC's "Shingle"),
    # fiber-cement or engineered-wood lap ("Cement/Smart").
    "ALUMINUM/VINYL": "frame",
    "WOOD": "frame",
    "WD": "frame",
    "COMPOSITION": "frame",
    "CEMENT/SMART": "frame",
    # A wall recorded as brick — solid or veneer the roll does not say; the same
    # knowingly lossy reading Cook's "Masonry" and Ohio's "BRICK" make, paid for
    # in confidence (base.TRANSLATED).
    "BRICK": "brick",
    "STONE": "stone",
}
# Deliberately unmapped:
#   STUCCO          stucco on frame or on block; the structure is not named
#   MASONRY FACING  a masonry face of unnamed material, on an unnamed structure
#   RSTL            one row; not a documented code


#: Four of Madison's street-type abbreviations that the Census matcher spells
#: out — typed "901 Waban Hl" comes back "901 WABAN HILL" — found by geocoding one
#: home of every street type in the roll. Home parcels, condominiums included:
#: HL 65, Bnd 52, Rdg 58, IS 19. In ``StreetType``, a column holding nothing else,
#: each has one meaning.
_MSN_TYPES = {"HL": "HILL", "BND": "BEND", "RDG": "RIDGE", "IS": "ISLAND"}


def _msn_street(row: dict, respell: bool = True) -> str | None:
    """The parcel's street address, as the matcher spells it (``respell``) or as
    the roll does."""
    n = num(row.get("HouseNbr"))
    name = " ".join(str(row.get("StreetName") or "").split())
    if not n or n <= 0 or not float(n).is_integer() or not name:
        return None
    sttype = str(row.get("StreetType") or "").strip()
    if respell:
        if not sttype and name.upper().endswith(" CREST"):
            # "Council Crest", "Lucia Crest", "Laurel Crest", "Heather Crest"
            # are filed with the type inside the name and none in StreetType;
            # the matcher writes them "COUNCIL CRST".
            name = name[:-len("CREST")] + "CRST"
        sttype = _MSN_TYPES.get(sttype.upper(), sttype)
    parts = [str(int(n)), str(row.get("StreetDir") or "").strip(), name, sttype]
    return " ".join(p for p in parts if p)


def _msn_addresses(row: dict) -> list[str]:
    """Both spellings, for the reason ``_mke_addresses`` gives."""
    return _distinct(_msn_street(row, respell) for respell in (True, False))


def _msn_unit(row: dict) -> str | None:
    """Madison's ``Unit`` column — "104", "# CDM" — as a bare designator."""
    raw = str(row.get("Unit") or "").replace("#", " ").split()
    return raw[0] if raw else None


def _msn_no_home(row: dict) -> bool:
    """A recorded zero dwellings, a vacant parcel, or a condominium notation (the
    complex's own outline, carrying nothing). Silence is not zero."""
    use = str(row.get("PropertyUse") or "").strip()
    if use in ("Vacant", "Condominium-Notation"):
        return True
    units = num(row.get("TotalDwellingUnits"))
    return units is not None and units <= 0


def _msn_one_dwelling(row: dict) -> bool:
    return (str(row.get("PropertyUse") or "").strip() == _MSN_SINGLE_FAMILY
            and num(row.get("TotalDwellingUnits")) == 1)


def _msn_wall(row: dict) -> str | None:
    def norm(v):
        return " ".join(str(v or "").split()).upper()
    first, second = norm(row.get("ExteriorWall1")), norm(row.get("ExteriorWall2"))
    wall = _MADISON_WALL.get(first)
    if wall is None:
        return None
    if second and _MADISON_WALL.get(second) != wall:
        return None
    return wall


# ── per-city configuration ─────────────────────────────────────────────────────

#: A house's story count, as a whole number. Above four is a keying error on a
#: single-family parcel (Milwaukee records 9 to 42 on five of them).
_MAX_STORIES = 4


@dataclass(frozen=True)
class City:
    """Everything that is a fact about one city's layer. See the docstring."""

    name: str
    county: str
    url: str
    #: The explicit outFields list. Both layers also carry owner names and
    #: mailing addresses; none of them is ever listed here.
    fields: tuple[str, ...]
    pid: str
    year: str
    attribution: str
    addresses: Callable[[dict], list[str]]
    unit: Callable[[dict], str | None]
    no_home: Callable[[dict], bool]
    is_condo: Callable[[dict], bool]
    one_dwelling: Callable[[dict], bool]
    area: str
    vintage: Callable[[dict], str]
    stories: Callable[[dict], int | None] = field(default=lambda row: None)
    wall: Callable[[dict], str | None] = field(default=lambda row: None)
    #: The column naming a condominium unit's complex, which units of one building
    #: must share to be merged (Madison's XRefParcel). None: the address alone.
    complex_id: str | None = None
    read_slice: float = _shared._READ_SLICE_S
    timeout: float = _shared.TIMEOUT

    @property
    def out_fields(self) -> str:
        return ",".join(self.fields)


CITIES: dict[str, City] = {
    "55079": City(
        name="Milwaukee",
        county="Milwaukee County",
        url=MILWAUKEE_URL,
        fields=("TAXKEY", "HOUSE_NR_LO", "HOUSE_NR_HI", "HOUSE_NR_SFX", "SDIR",
                "STREET", "STTYPE", "UNIT", "LAND_USE", "NR_UNITS", "YR_BUILT",
                "BLDG_AREA", "NR_STORIES", "YR_ASSMT"),
        pid="TAXKEY", year="YR_BUILT", area="BLDG_AREA",
        addresses=_mke_addresses,
        unit=lambda row: str(row.get("UNIT") or "").strip() or None,
        no_home=_mke_no_home,
        is_condo=lambda row: _mke_land_use(row) == _MKE_CONDO,
        one_dwelling=_mke_one_dwelling,
        stories=_mke_stories,
        vintage=_mke_vintage,
        attribution="City of Milwaukee Assessor, Master Property file (MPROP), keyless",
        read_slice=3.0, timeout=5.0,
    ),
    "55025": City(
        name="Madison",
        county="Dane County",
        url=MADISON_URL,
        fields=("Parcel", "XRefParcel", "HouseNbr", "StreetDir", "StreetName",
                "StreetType", "Unit", "PropertyUse", "TotalDwellingUnits",
                "YearBuilt", "TotalLivingArea", "ExteriorWall1", "ExteriorWall2"),
        pid="Parcel", year="YearBuilt", area="TotalLivingArea",
        addresses=_msn_addresses,
        unit=_msn_unit,
        no_home=_msn_no_home,
        is_condo=lambda row: str(row.get("PropertyUse") or "").strip() == _MSN_CONDO,
        one_dwelling=_msn_one_dwelling,
        wall=_msn_wall,
        complex_id="XRefParcel",
        vintage=lambda row: "City of Madison Assessor tax parcels, queried live",
        attribution="City of Madison Assessor's Office tax parcels (keyless)",
        read_slice=2.0, timeout=_shared.TIMEOUT,
    ),
}

#: Configured and verified, not registered: each city's roll covers only that
#: city, which is 60.8% of Milwaukee County's homes and 50.7% of Dane County's.
#: See the module docstring. Deleting a county here registers it.
_HELD_FOR_COVERAGE = frozenset({"55079", "55025"})

COUNTY_FIPS = frozenset(CITIES) - _HELD_FOR_COVERAGE

#: The module's own clock: the largest any city is given, which is what a lookup
#: that must first ask which county it is in starts with. Each city's requests
#: run on that city's pair; a test pins every pair under the host budget.
READ_SLICE_S = max(c.read_slice for c in CITIES.values())
LOOKUP_TIMEOUT = max(c.timeout for c in CITIES.values())


# ── candidates ─────────────────────────────────────────────────────────────────


def _pid(cfg: City, row: dict) -> str | None:
    pid = str(row.get(cfg.pid) or "").strip()
    return pid or None


def _year(cfg: City, row: dict) -> int | None:
    """The actual year built, where the row says a home stands. 0 is "not
    recorded"; the range is the label's plausibility window."""
    year = num(row.get(cfg.year))
    if not year or not float(year).is_integer():
        return None
    if not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 or cfg.no_home(row):
        return None
    return int(year)


def _area(cfg: City, row: dict) -> float | None:
    area = num(row.get(cfg.area))
    if area is None or area <= 0 or cfg.is_condo(row) or not cfg.one_dwelling(row):
        return None
    return area


def _norm_unit(unit: str | None) -> str:
    return str(unit or "").strip().lstrip("#").strip().casefold()


def _candidates(cfg: City, rows: list[dict], unit: str | None) -> list[dict]:
    """The parcels that could be the answer, from raw rows.

    * Rows with no id, rows that say no home stands there (``no_home``), and rows
      with no usable street address are dropped: none can contribute a fact, and
      each would make a real home beside it ambiguous. Removing rows that cannot
      be the answer only turns "ambiguous" into "one"; the address check is
      untouched.
    * A typed unit drops every condominium record that names a different unit.
    * Rows sharing an id are one candidate, and are not offered at all if they
      disagree about a fact (a broken join).
    * Condominium records at one street address (and one complex, where the
      city names it) are ONE candidate when they agree on the year — the
      building — and are not offered when they disagree. See the docstring.
    """
    singles: dict[str, list[dict]] = {}
    condos: dict[tuple, list[dict]] = {}
    for row in rows:
        pid = _pid(cfg, row)
        streets = cfg.addresses(row)
        if pid is None or cfg.no_home(row) or not any(address_key(s) for s in streets):
            continue
        if cfg.is_condo(row):
            row_unit = cfg.unit(row)
            if unit and row_unit and _norm_unit(row_unit) != _norm_unit(unit):
                continue
            key = address_key(streets[0])
            group = str(row.get(cfg.complex_id) or "").strip() if cfg.complex_id else ""
            condos.setdefault((key, group), []).append(row)
        else:
            singles.setdefault(pid, []).append(row)

    out = []
    for pid, members in singles.items():
        facts = {(_year(cfg, m), _area(cfg, m), cfg.stories(m), cfg.wall(m))
                 for m in members}
        if len(facts) > 1:
            continue
        row = members[0]
        out.append({"_pid": pid, "_condo": False, "_addresses": cfg.addresses(row),
                    "_row": row, "year": _year(cfg, row), "sqft": _area(cfg, row),
                    "stories": cfg.stories(row), "construction": cfg.wall(row)})
    for (_key, group), members in condos.items():
        years = {_year(cfg, m) for m in members}
        if len(years) != 1:
            continue
        pids = {_pid(cfg, m) for m in members}
        out.append({"_pid": pids.pop() if len(pids) == 1 else (group or None),
                    "_condo": True, "_addresses": cfg.addresses(members[0]),
                    "_row": members[0], "year": years.pop(), "sqft": None,
                    "stories": None, "construction": None})
    return out


def _address_for(query: str | None):
    """The accessor ``select_parcel`` compares with: a candidate with two street
    addresses (a Milwaukee duplex range) is offered under whichever agrees."""
    def address_of(cand: dict) -> str | None:
        addresses = cand["_addresses"]
        if query:
            for a in addresses:
                if same_address(query, a):
                    return a
        return addresses[0] if addresses else None
    return address_of


# ── which county ───────────────────────────────────────────────────────────────


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the registered county this point is in, from TIGERweb.

    Only for a caller that did not say: the registry passes the county it routed
    on, so in the product this request is never made.
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
               *, deadline: float | None = None) -> tuple[City, dict] | None:
    """The city's record of the parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s; see it for why the nearest
    parcel is never taken. A county passed explicitly but not registered is
    answered with None, not re-routed.
    """
    if county_fips:
        fips = str(county_fips).strip().zfill(5)
        if fips not in COUNTY_FIPS:
            return None
        deadline = deadline_from(deadline, CITIES[fips].timeout)
    else:
        deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
        fips = _county_at(lat, lon, deadline=deadline)
        if fips is None:
            return None
    cfg = CITIES[fips]
    unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            rows = _shared.arcgis_parcels(cfg.url, lat, lon, cfg.out_fields,
                                          distance_m, deadline=deadline,
                                          read_slice=cfg.read_slice)
            fetched[distance_m] = _candidates(cfg, rows, unit)
        found = fetched[distance_m]
        if distance_m == 0 and address:
            # A condominium unit's polygon is its building's or its complex's, so
            # the point is "inside" every unit of it. With an address in hand the
            # building is found by address in the buffer instead.
            found = [c for c in found if not c["_condo"]]
        return found

    chosen = select_parcel(fetch, address, _address_for(address))
    return (cfg, chosen) if chosen is not None else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    found = _parcel_at(lat, lon, address, county_fips)
    if not found:
        return None
    cfg, cand = found
    facts = {k: cand[k] for k in ("year", "sqft", "stories", "construction")}
    if all(v is None for v in facts.values()):
        return None
    return AssessorRecord(
        source=cfg.attribution,
        data_vintage=cfg.vintage(cand["_row"]),
        parcel_id=cand["_pid"],
        year_built=facts["year"],
        sqft=facts["sqft"],
        stories=facts["stories"],
        construction=facts["construction"],
        # Neither roll publishes a foundation type or a condition grade that maps.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the city's own publisher, not another's."""
    city = CITIES.get(county_fips)
    return city.url if city else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the city assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address (with the reader's typed unit,
    via ``_shared.with_unit``), used only to confirm the parcel. ``county_fips``
    is the county the registry routed on.

    Fails open on everything — a timeout, a 500, a truncated page
    (``_shared.TruncatedResponse``), a renamed column. The caller then keeps
    whatever it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Wisconsin assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
