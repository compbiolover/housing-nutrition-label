#!/usr/bin/env python3
"""Indiana — Vanderburgh County (Evansville), and why not Marion County.

Named ``ind`` because ``in`` is a Python keyword.

This adapter was asked for Marion County (Indianapolis, 441,040 homes), and
Marion County is not in it. Its assessor publishes no current year built that a
lookup can query, and the one year-built table the city's GIS still serves is a
2009 snapshot whose age shows: measured against today's property record cards,
it names a demolished house's year on a rebuilt one. What Indiana does yield is
Vanderburgh County, whose assessor publishes the dwelling record on every
parcel, refreshed nightly. The module is a per-county table (``COUNTIES``) so
the next Indiana county is one entry.

What was looked for, measured 2026-10-04
----------------------------------------
* **IndianaMap's statewide parcels** (``Parcel_Boundaries_of_Indiana_Current``,
  the Indiana Geographic Information Office's annual harvest from all 92
  counties) carry the state parcel number, the situs address and the DLGF
  property-class code — no year built, area or story count. ``Parcels_2023``
  carries less. The state's richer layer, ``CountyParcels_DLGF_RESTRICTED``, is
  restricted by name. The Department of Local Government Finance publishes its
  statewide roll only as downloadable files, which a point lookup cannot query
  and this project does not bundle. So there is no statewide route.
* **Marion County.** Every layer of the city-county's two ArcGIS servers was
  read (237 services on ``gis.indy.gov``, 25 on ``xmaps.indy.gov``): the parcels
  (``MapIndy/MapIndyProperty`` layer 10, ``sde_Parcel``) carry the address, the
  property class and ``ESTSQFT`` — the LOT's area, not the house's — and no
  year. The assessor's property record cards are PDFs rendered per parcel by a
  report server, not data. The one year-built table is ``CAMA_063009`` in
  ``MapIndy/IndyBrownfields`` (361,474 rows): the assessor's CAMA extract of
  2009-06-30, whose newest year is 2008. Measured against today's cards on 120
  current single-family parcels drawn at random: 21 are not in it at all (built
  or re-platted since), 7 were vacant lots then, 91 agree with today's card, and
  1 does not — 1902 Milburn St, which the table dates 1920 and today's card
  dates 2024: a house torn down and rebuilt on the same parcel. Today's
  property class cannot catch that (it still says single-family), so about 1 in
  90 answers would be a stranger's house tagged ``observed``. Not built.
* **Hamilton County** (144,746 homes) publishes ``year_built``, ``sq_ft_res``
  and ``num_floors`` on its ``HamCoParcelsPublic`` layer, filled on 107,234 of
  107,361 single-family parcels — and describes the service as "Hamilton County
  parcel boundaries (internal use only)" (the service's description and
  document info, gis1.hamiltoncounty.in.gov). Not built, for its terms.
* **Lake, Allen, St. Joseph** and the rest of the larger counties: Lake's
  open-data parcels carry no building data; Allen's and St. Joseph's GIS hosts
  could not be reached through this environment's proxy; most others publish
  through vendor portals with no query service. Tippecanoe's year-built layers
  are sales and commercial-income samples (2,493 rows), not a roll.

The source
----------
``ASSESSOR/PARCEL_DATA/MapServer/0`` on ``maps.evansvillegis.com``, "Tax
Parcels", the joint City of Evansville/Vanderburgh County GIS service, described
as "Current Tax Parcels for Vanderburgh County, Indiana. The information is
updated nightly with recent sales, assessment, and dwelling information. This
data is maintained by the Vanderburgh County Assessor's office." 79,408
parcels. Single-family parcels (510-515) carry a year on 56,578 of 56,590; the
county has 85,319 homes (ACS, this repository's county table).

Indiana files each parcel under the DLGF's three-digit property class, whose
5xx block reads like Ohio's: 500-509 vacant residential land, 510-515 one
family by acreage, 520-525 two family, 530-535 three family, 540-545 a mobile
or manufactured home, 550 a condominium, 599 other residential structures
(garages, sheds); 401-403 apartments; 1xx agricultural.

What the record says, and what the label takes
----------------------------------------------
* ``YearBuilt``, where the class says a home stands: 510-515, 520-525,
  530-535, 540-545, 550, 401-403, and an agricultural parcel whose dwelling
  record is a single-family occupancy (``occupancy`` 1: a farmhouse). The
  layer fills ``YearBuilt`` on shops, offices and churches too (420, 447, 685
  ...), which is why the class is required; vacant land (500-509) and 599
  structures never carry a home's year.
* ``SquareFootage``, ``StoryHeight`` and ``condition`` only on a single-family
  class (510-515) whose dwelling record is occupancy 1 — never a condominium,
  a duplex or an apartment. ``StoryHeight`` 1.5 and 1.75 have no whole-number
  reading and are left empty (Cook's, Ohio's and Milwaukee's call).
* ``condition`` is Indiana's residential condition rating; see ``_CONDITION``.
* ``grade`` (construction quality, "C-1", "D+2") is not a condition and is not
  read. No wall material or foundation type is published.

Rows whose class says no home stands there are dropped before the parcel is
chosen: they can never contribute a fact, and as candidates they would make a
home beside them ambiguous (the sanctioned shape; see ``_shared.select_parcel``).

What is never read
------------------
The layer carries ``NAME``, ``OWNER1``, ``OWNER2``, ``OwnerName``, the owner's
mailing address, ``LastSaleDate``, ``LastSalePrice`` and every valuation. Eight
columns are requested by name and the shared helper refuses ``*``. Nothing from
this source is written into the repository.

Timing
------
Measured over 50 sampled rooftops through the product's HTTP session
(2026-10-04): containment median 0.08 s, p90 0.09, p95 0.11, max 0.50;
buffered 0.09 / 0.10 / 0.12 / 0.30 s; responses at most 10 KB and 49 rows
against a 2,500-row transfer limit. The service once reset a connection during
research, and the Wisconsin cities' servers each stalled past one second once
in a few hundred requests, so the read slice is 2 seconds rather than the shared
one — still a quick cut-off for a hung connection — and the budget the shared
four seconds. See "End to end" for the verification run's timings.

End to end
----------
110 Vanderburgh homes drawn at random from the layer itself (random object ids
among home classes with a year: 86 class 510, 15 class 511, 3 two-family, 2
three-family, a 512, a 513, a condominium and an apartment building), typed as
street, city, state and ZIP, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up:

  ======  ========  ========  =====  ==========  ===========  =======
  sample  geocoded  resolved  wrong  year exact  sqft exact   stories
  ======  ========  ========  =====  ==========  ===========  =======
     110       108        98      0       98/98        92/92       73
  ======  ========  ========  =====  ==========  ===========  =======

Every geocode routed to 18163. 91% of geocoded homes resolved, **none to the
wrong parcel**, and every year and floor area equals the sampled row's. The
verification run's requests: containment median 0.08 s, p95 0.10, max 0.39;
buffered 0.09 / 0.10 / 0.13 s; a whole lookup median 0.17 s, max 0.48 s.

No Census geocode landed inside its own parcel — every one fell in the street,
so every lookup is decided by the address in the 80 m buffer. The 10 that did
not resolve: 9 geocodes 87 to 439 m from their parcel (mostly rural 511 lots,
whose points the matcher interpolates along long frontages), and 1 directional
the matcher added ("2308 POWELL AVE" came back "2308 E POWELL AVE") — not
forgiven, for Utah's and Ohio's reason.

License and terms
-----------------
The item's license (ArcGIS Online item ``c7a569f162094612a9bf455b8ac00127``,
"Parcel Data") and the service's description: "The information provided on
this site is for convenience only and is compiled from public records and
data ... not intended to replace any official source", provided "as is" with no
warranties, and no liability for its use. No restriction on querying, caching,
redistribution or commercial use. The posture is every adapter's: query live,
cache in process, bundle nothing, never fetch owner data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Indiana county assessors"
ATTRIBUTION = "Vanderburgh County Assessor parcel and dwelling data (keyless)"
DATA_VINTAGE = "Vanderburgh County Assessor tax parcels, updated nightly"

VANDERBURGH_URL = ("https://maps.evansvillegis.com/arcgis_server/rest/services"
                   "/ASSESSOR/PARCEL_DATA/MapServer/0/query")

# ── Indiana's property classes ─────────────────────────────────────────────────

#: Classes on which a home stands. 510-515 one family, 520-525 two family,
#: 530-535 three family, 540-545 a mobile or manufactured home, 550 a
#: condominium unit, 401-403 apartment buildings.
_HOMES = frozenset(
    {f"{n}" for n in range(510, 516)} | {f"{n}" for n in range(520, 526)}
    | {f"{n}" for n in range(530, 536)} | {f"{n}" for n in range(540, 546)}
    | {"550", "401", "402", "403"})
#: The only classes that positively say ONE home: one family, by acreage.
_ONE_FAMILY = frozenset(f"{n}" for n in range(510, 516))
#: The dwelling record's occupancy code for a single-family dwelling (the
#: property record card's "Occupancy: 1 Single Family, 2 Duplex, 3 Triplex ...").
_SINGLE_FAMILY_OCCUPANCY = "1"

# Indiana's residential condition rating. Measured over the county's 67,335
# residential rows: A 52,579; F 4,712; G 1,336; P 669; VP 345; Ex 50; blank
# 7,644 (vacant land and structures).
_CONDITION = {
    "EX": "excellent",
    "G": "good",
    "A": "average",
    "F": "fair",
    "P": "poor",
}
# Deliberately unmapped: VP (very poor) falls between the label's poor and
# unsound, and choosing either neighbor would be a guess (Ohio's call for
# Butler's VP).

#: A house's story count, as a whole number; above four is a keying error on a
#: single-family parcel.
_MAX_STORIES = 4


@dataclass(frozen=True)
class County:
    """Everything that is a fact about one county's layer."""

    name: str
    url: str
    #: The explicit outFields list. The layer also carries owner names, mailing
    #: addresses and sale prices; none of them is ever listed here.
    fields: tuple[str, ...]
    attribution: str
    vintage: str
    read_slice: float = _shared._READ_SLICE_S
    timeout: float = _shared.TIMEOUT

    @property
    def out_fields(self) -> str:
        return ",".join(self.fields)


COUNTIES: dict[str, County] = {
    "18163": County(
        name="Vanderburgh",
        url=VANDERBURGH_URL,
        fields=("PARCELID", "PROPSTREET", "PROPERTYCLASS", "occupancy",
                "YearBuilt", "SquareFootage", "StoryHeight", "condition"),
        attribution=ATTRIBUTION,
        vintage=DATA_VINTAGE,
        read_slice=2.0, timeout=_shared.TIMEOUT,
    ),
}

COUNTY_FIPS = frozenset(COUNTIES)

#: The module's clock: the largest any county is given. A test pins each pair
#: under the host budget.
READ_SLICE_S = max(c.read_slice for c in COUNTIES.values())
LOOKUP_TIMEOUT = max(c.timeout for c in COUNTIES.values())


# ── reading one row ────────────────────────────────────────────────────────────


def _class(row: dict) -> str:
    return str(row.get("PROPERTYCLASS") or "").strip()


def _occupancy(row: dict) -> str:
    return str(row.get("occupancy") or "").strip()


def _is_a_home(row: dict) -> bool:
    """The class says a home stands here, or it is a farm whose dwelling record
    is a single-family house."""
    cls = _class(row)
    if cls in _HOMES:
        return True
    return cls.startswith("1") and _occupancy(row) == _SINGLE_FAMILY_OCCUPANCY


def _one_dwelling(row: dict) -> bool:
    """A one-family class AND a single-family dwelling record, and no unit in
    the address: the area, stories and condition then describe the house."""
    return (_class(row) in _ONE_FAMILY
            and _occupancy(row) == _SINGLE_FAMILY_OCCUPANCY
            and not unit_of(row.get("PROPSTREET")))


def _pid(row: dict) -> str | None:
    pid = str(row.get("PARCELID") or "").strip()
    return pid or None


def _year(row: dict) -> int | None:
    year = num(row.get("YearBuilt"))
    if not year or not float(year).is_integer():
        return None
    if not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 or not _is_a_home(row):
        return None
    return int(year)


def _area(row: dict) -> float | None:
    area = num(row.get("SquareFootage"))
    if area is None or area <= 0 or not _one_dwelling(row):
        return None
    return area


def _stories(row: dict) -> int | None:
    floors = num(row.get("StoryHeight"))
    if floors is None or not float(floors).is_integer():
        return None
    if not 1 <= floors <= _MAX_STORIES or not _one_dwelling(row):
        return None
    return int(floors)


def _condition(row: dict) -> str | None:
    if not _one_dwelling(row):
        return None
    return _CONDITION.get(str(row.get("condition") or "").strip().upper())


def _candidates(rows: list[dict]) -> list[dict]:
    """Rows that could be the answer: an id, a usable street address, and a
    class that says a home stands there. Rows of one id are one candidate, and
    none if they disagree about a fact."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        pid = _pid(row)
        if pid is None or not _is_a_home(row) or not address_key(row.get("PROPSTREET")):
            continue
        groups.setdefault(pid, []).append(row)
    out = []
    for members in groups.values():
        facts = {(_year(m), _area(m), _stories(m), _condition(m)) for m in members}
        if len(facts) == 1:
            out.append(members[0])
    return out


# ── the lookup ─────────────────────────────────────────────────────────────────


def _parcel_at(lat: float, lon: float, address: str | None, county_fips: str,
               *, deadline: float | None = None) -> tuple[County, dict] | None:
    """The county's record of the parcel this point belongs to, or None. The
    choice is ``_shared.select_parcel``'s; see it for why the nearest parcel is
    never taken. PROPSTREET is the street address alone ("2205 W BUENA VISTA
    RD"; the city and ZIP are their own columns), so no locality trim."""
    cfg = COUNTIES[county_fips]
    deadline = deadline_from(deadline, cfg.timeout)

    def fetch(distance_m):
        rows = _shared.arcgis_parcels(cfg.url, lat, lon, cfg.out_fields, distance_m,
                                      deadline=deadline, read_slice=cfg.read_slice)
        return _candidates(rows)

    chosen = select_parcel(fetch, address, lambda row: row.get("PROPSTREET"))
    return (cfg, chosen) if chosen is not None else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str, _bucket: int = 0) -> AssessorRecord | None:
    found = _parcel_at(lat, lon, address, county_fips)
    if not found:
        return None
    cfg, row = found
    year_built, sqft = _year(row), _area(row)
    stories, condition = _stories(row), _condition(row)
    if all(v is None for v in (year_built, sqft, stories, condition)):
        return None
    return AssessorRecord(
        source=cfg.attribution,
        data_vintage=cfg.vintage,
        parcel_id=_pid(row),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        condition=condition,
        # No wall material or foundation type is published.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is the county the registry routed on; with only one
    county configured, a direct call without it means Vanderburgh, and a county
    passed explicitly but not configured is answered with None.

    Fails open on everything — a timeout, a 500, a truncated page
    (``_shared.TruncatedResponse``), a renamed column.
    """
    try:
        fips = str(county_fips).strip().zfill(5) if county_fips else "18163"
        if fips not in COUNTY_FIPS:
            return None
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Indiana assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
