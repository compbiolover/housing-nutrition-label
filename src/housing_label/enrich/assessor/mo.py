#!/usr/bin/env python3
"""Missouri — Jackson County (Kansas City), from the county's own Parcel Viewer services.

Missouri has no statewide year built, so every answer has to come from a county.
Three were researched for this module; one is registered.

Which counties, and why only this one
-------------------------------------
Measured 2026-10-04. ACS housing units from this repository's own county table.

  ===================  =====  =======  ==============================================
  county               FIPS    units   verdict
  ===================  =====  =======  ==============================================
  Jackson              29095  336,288  **registered** — Assessment Department's Parcel
                                       Viewer parcels and CAMA table, keyless
  St. Louis County     29189  446,192  held for its terms (below)
  St. Louis City       29510  174,111  held for its terms (below)
  ===================  =====  =======  ==============================================

**St. Louis County** publishes everything an adapter wants on one keyless layer
(``maps.stlouisco.com/hosting/rest/services/OpenData/OpenData/MapServer/7``:
``YEARBLT`` on 324,686 of its 324,690 single-family parcels, ``RESQFT``,
``LIVUNIT``, ``TAXYR``), and is not used. The county's own catalog entry for the
parcels (ArcGIS item ``fd4893ca99244279adb2ffa206e09ec7``, the "Parcels" dataset of
its Geospatial Data Center) ends "Copyright 2019 St. Louis County. All rights
reserved.", the Data Center site itself says "Copyright 2026 St. Louis County. All
rights reserved.", and the county's published metadata for the same parcel data
says "Data, or portions thereof, may not be shared without the consent of the St.
Louis County GIS Service Center." The county's website terms are more relaxed about
API use, and the service's own FGDC record says "Use Constraints: None", but the
dataset's license is the binding text here, and "all rights reserved" is the
phrase this project holds Cobb County, Georgia back for.

**St. Louis City** publishes ``FirstYearBuilt``/``LastYearBuilt`` on its live
parcels (``maps6.stlouis-mo.gov/arcgis/rest/services/St_Louis_Parcels/MapServer/0``;
67,012 of 67,034 single-family parcels). The City's GIS terms of use
(stlouis-mo.gov/government/departments/planning/mapping-graphics/terms.cfm) say
"No information may be sold or redistributed in any manner unless written
permission is received from the City of St. Louis." That is the restriction class
this project holds Gwinnett County, Georgia back for.

Both are recorded so the next person does not redo the research. Enabling either
needs a product decision on its terms first, and then its own layer and field
mapping here (both are single-request layers, simpler than Jackson's join).

The source: two layers of one service, joined on the property id
-----------------------------------------------------------------
Jackson County's public Parcel Viewer (jcgis.jacksongov.org/parcelviewer) reads
one map service, ``ParcelViewer/ParcelsAscendRelate``, with two parts:

1. layer 1, **Parcels** — the parcel fabric's polygons, carrying ``PropertyID``
   (and ``Name``, the dashed parcel number) and no address and no facts;
2. table 2, **Ascend_GisInfo** — the assessor's record per property ("Ascend" is
   the county's CAMA system), carrying ``situs_address``, ``landuse_cd``,
   ``year_built``, ``num_stories``, ``num_families`` and ``tot_sqf_l_area``.

So a lookup is two requests per search distance: which parcels are at the point,
then their records by ``property_id IN (...)``. The record carries the street
address that confirms the parcel, so the shared ``select_parcel`` decides on the
joined rows exactly as it does for a one-layer county.

Fill, measured over the whole table (300,626 records, 0 property ids repeated):

  ======================  =======  ==========  =====
  land use                records  year built  share
  ======================  =======  ==========  =====
  1110 SF RESIDENCE       209,731     209,421  99.9%
  1112 SF CONDO             8,419       8,384  99.6%
  1111 SF TOWNHOUSE         6,895       6,874  99.7%
  1120 DUPLEX               6,268       6,221  99.3%
  4120 AG HOMESITE          3,538       3,367  95.2%
  1150 CONV. HOUSE TO MF    1,285       1,283  99.8%
  1140 FOURPLEX             1,071       1,065  99.4%
  ======================  =======  ==========  =====

Apartment complexes (2120-2199) mostly carry no residential year (their buildings
are dated in a commercial section this module does not read), so they are simply
not answered. The rows above hold 237,000 dated homes, against the county's 336,288
housing units; most of the difference is apartments.

**The table is a snapshot.** Every record says ``tax_year`` 2024, and the newest
year built anywhere in it is 2022 (93 rows; 891 in 2021, 1,461 in 2020; one 2029,
which fails nothing but is shown by its own row). The polygons are live; the
records are the 2024 roll's. A house built since is either absent from the table
(no record, so no candidate) or carries ``year_built`` 0 (refused as "not
recorded"), which fails safe. Each record's vintage names its tax year, so a reader
can date the value.

What is reported
----------------
* **Year built** — ``year_built``, the dwelling's actual year. The table also has
  ``year_built_csect`` (a commercial section's year) and ``eff_yr_built_csect``
  (an effective year); neither is requested. 0 is "not recorded". The year is
  reported only where the land-use code names a dwelling (``_DWELLING``), or where
  the row states no land use at all (silence is not a refusal).
* **Floor area and stories** — ``tot_sqf_l_area`` (total living area) and
  ``num_stories``, only on a single-family house, townhouse or farm homesite
  (1110, 1111, 4120) whose record counts exactly one family and whose address names
  no unit. Never on a condominium unit, a duplex or anything larger; nothing is
  divided by a unit count. ``total_sqft`` is the LOT and is never read. A story
  count above four on a single-family record is a keying error and is refused.
* Nothing else. The table has no wall, foundation or condition column.

Rows that can never be an answer are dropped before the parcel is chosen, so they
cannot make a real home ambiguous: a polygon with no ``PropertyID`` (the fabric's
"Pending" parcels), a property with no record, records with no parcel number, and
records whose land-use code says the parcel is not a home (vacant land, common
areas, condominium parking, detached garages, outbuildings, pools, and every
commercial, industrial and exempt use). The fabric also repeats one property's
polygon many times (a condominium master parcel came back as 103 polygons), so ids
are de-duplicated before the second request.

**Condominiums.** A unit with its own polygon (some do) is a record coded 1112
whose situs names its unit ("1111 W 46TH ST UNIT 53"). Units of one building share
a street address, so with an address in hand they are left out of the containment
answer and found by address in the buffer, and a typed unit removes every unit that
names a different one — Ohio's rule (``oh.py``), for Ohio's reason. Units without
their own polygon sit under a complex parcel whose record is a common area; those
are not reachable from a point and are not answered.

Timing
------
Measured 2026-10-04 at 45 sampled rooftops, both hops (parcels, then records):

  ==========================  ======  ======  ======  ======
  request                     median     p90     p95     max
  ==========================  ======  ======  ======  ======
  containment, parcels         0.08 s  0.09 s  0.10 s  0.35 s
  containment, records         0.09 s  0.09 s  0.09 s  0.10 s
  80 m buffer, parcels         0.09 s  0.10 s  0.11 s  0.37 s
  80 m buffer, records         0.09 s  0.10 s  0.10 s  0.37 s
  containment pair             0.17 s  0.18 s  0.19 s  0.44 s
  buffer pair                  0.18 s  0.20 s  0.21 s  0.46 s
  ==========================  ======  ======  ======  ======

At most 54 parcels and 13 KB in any response, far under the 2,000-row limit. The
shared clock fits with room to spare: no request came near the one-second read
slice, and the worst lookup (all four requests) is under a second of the
four-second budget. A test pins that budget under ``config.UPSTREAM_HOST_BUDGET``.

What the adapter is worth, end to end
-------------------------------------
160 homes drawn at random from the source (random parcel-polygon
object ids joined to their records, keeping dwellings with a year and an address),
typed as street, city, state and ZIP, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up:

  ========  ========  ========  =====  ==========  ===========
  sample    geocoded  resolved  wrong  year exact  sqft exact
  ========  ========  ========  =====  ==========  ===========
       160       158       134      0     134/134      128/128
  ========  ========  ========  =====  ==========  ===========

Every geocode routed to 29095. 85% of geocoded homes resolved, **none to the wrong
parcel**, and every year and floor area reported equals the sampled record's;
stories came back on 128. A lookup took a median of 0.27 s (p95 0.36 s, slowest
0.79 s). A first run of the same sample resolved 133: one lookup spent the whole
four-second budget on a single stalled request and failed open, and resolved at
0.36-0.70 s when repeated — a transient, which is what failing open is for.

The 24 that did not resolve: 19 geocodes more than 80 m from their own parcel (95
to 254 m for most; two Lake Lotawana addresses, whose roll writes "24 B LAKE SHORE
DR", landed 1.2 and 2.2 km away, and one rural Oak Grove address 2.4 km away), so
no record in the buffer agreed with the address; 4 where the Census matcher dropped
or added a directional ("3826 SUMMIT RIDGE DR" for the roll's "3826 S SUMMIT RIDGE
DR", "6520 E EDGEVALE RD" for "6520 EDGEVALE RD") — not forgiven, for Utah's and
Ohio's reason: the matcher's directional is not trustworthy enough to wave
through; and 1 where it shortened the street's name ("712 CLEAVER II BLVD" for
"712 E EMANUEL CLEAVER II BLVD"). Two typed addresses did not geocode at all.

License and terms
-----------------
The Parcel Viewer's services carry the county's disclaimer (on
``Cadastral/LotsAndDimensions``, the same viewer's layer): the data is accepted
"as-is", the county "expressly disclaims any representation or warranty as to the
completeness or accuracy of the data", and the requestor "expressly releases and
agrees to hold the County ... harmless". The Assessment Department sells bulk
parcel extracts (jacksongov.org/Government/Departments/Assessment/
Assessment-Mapping), which is a price for a copy, not a license on the public
service; no text restricting reproduction, redistribution or commercial use was
found on the services, the viewer or the department's pages. These are Missouri
public records (RSMo 610.010). The posture is every adapter's: query live, cache in
process, bundle nothing, never fetch owner data.

What is never read
------------------
The record table carries mortgage-company names and mailing addresses
(``mtgco_*``) and a dozen assessed-value columns for this year and the last; the
parcel layer carries the fabric's editing history. Each request names its columns
(``_PARCEL_FIELDS``, ``_RECORD_FIELDS``) and the shared helper refuses ``*``.
Nothing from this source is written into the repository.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

#: Jackson County only. St. Louis County (29189) and St. Louis City (29510) are
#: held for their terms — see the module docstring — and are deliberately absent.
COUNTY_FIPS = frozenset({"29095"})
HELD_FOR_TERMS = frozenset({"29189", "29510"})

NAME = "Jackson County (MO) Assessment Department"
ATTRIBUTION = ("Jackson County, Missouri Assessment Department parcel records "
               "(Parcel Viewer, keyless)")
DATA_VINTAGE = "Jackson County, MO Assessment Department record"

_BASE = ("https://jcgis.jacksongov.org/arcgis/rest/services"
         "/ParcelViewer/ParcelsAscendRelate/MapServer")
#: The parcel fabric's polygons: ``PropertyID`` and nothing else that is read.
PARCEL_URL = f"{_BASE}/1/query"
#: The assessor's record per property (``Ascend_GisInfo``), joined on property id.
RECORD_URL = f"{_BASE}/2/query"

#: Measured: every request well under the shared one-second slice and the pair of
#: hops at each distance under half a second. See "Timing" in the docstring.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

_PARCEL_FIELDS = "PropertyID"
_RECORD_FIELDS = ("property_id,parcel_number,situs_address,landuse_cd,year_built,"
                  "num_stories,num_families,tot_sqf_l_area,tax_year")
#: The columns that are facts about the building; two records of one property id
#: must agree on all of them, or the join is broken and neither is offered.
_FACTS = ("situs_address", "landuse_cd", "year_built", "num_stories",
          "num_families", "tot_sqf_l_area")

# ── the county's land-use codes ───────────────────────────────────────────────
#
# Read off the table's own ``landuse_cd_descr`` column. Every code that names a
# dwelling, from a single-family house to a mobile-home park:
_DWELLING = frozenset({
    "1108",  # MOBILE HOME
    "1109",  # PP MOBILE HOME RES
    "1110",  # SF RESIDENCE
    "1111",  # SF TOWNHOUSE
    "1112",  # SF CONDO
    "1120",  # DUPLEX
    "1130",  # TRIPLEX
    "1140",  # FOURPLEX
    "1149",  # MULTI BLDG-1000NBHD
    "1150",  # CONV. HOUSE TO MF
    "1160",  # RES. CO-OP
    "1200",  # RES&COM RES PREDOM
    "4120",  # AG HOMESITE
    "4150",  # AG W/ PER. PROP. MH
    "2120",  # COMM MULTI-FAM @19%
    "2130",  # SECTION 8 HOUSING
    "2140",  # SECTION 42 HOUSING
    "2150", "2160", "2170", "2180",  # APARTMENT 5 / 6 / 7 / 8 UT
    "2190",  # GARDEN APTS >8 UT
    "2191",  # LOWRISE APTS >8 UT
    "2192",  # HIGHRISE APTS >8 UT
    "2193",  # COMM CO-OP
    "2194",  # RETIREMENT HOME 19%
    "2195",  # GROUP HOMES
    "2199",  # MOBILE HOME PARK
})
# Everything else is a statement that the parcel is not somebody's home: 1101
# VACANT RES LAND, 1102 RES VACANT C/A, 1103 RES IMPROVED C/A (common areas), 1113
# SF CONDO PARKING, 1114/1115 SF CONDO VACANT/IMPR. C/A, 1190 DET. GARAGE, 1191
# OUTBUILDING, 1192 SWIMMING POOL, 1193 TENNIS COURT, 1199 MISC RES IMPROVEMENT,
# 4100 VACANT AG LAND, 4130 AG/FARM OUTBUILDING, 4140, 4444 URBAN GARDEN, and every
# commercial (2xxx outside the dwellings above), industrial (3xxx) and exempt use.
# Their rows are dropped before the parcel is chosen (see _candidates): they can
# never be an answer, and as candidates they could make the home beside them
# ambiguous.

#: The codes that positively say ONE home on its own parcel: a detached house, a
#: townhouse on its own lot, a farm homesite. Area and stories need one of these.
_ONE_HOME = frozenset({"1110", "1111", "4120"})
#: A condominium unit, whose polygon (where it has one) may be the building's.
_CONDO = frozenset({"1112"})

#: A single-family record with more floors than this is a keying error.
_MAX_STORIES = 4


def _code(row: dict) -> str:
    return str(row.get("landuse_cd") or "").strip()


def _is_a_home(row: dict) -> bool:
    """Whether the record may describe somebody's home: a dwelling code, or none.

    A blank code is silence, not a refusal; 5,319 records have one, and none of
    them carries a year, so in practice it costs nothing either way.
    """
    code = _code(row)
    return not code or code in _DWELLING


def _year(row: dict) -> int | None:
    year = num(row.get("year_built"))
    if not year or not float(year).is_integer():
        return None                      # 0 is "not recorded", not the year zero
    if not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 or not _is_a_home(row):
        return None
    return int(year)


def _one_home(row: dict) -> bool:
    """Whether the record says it is ONE dwelling on its own parcel.

    The single-family land-use codes, a family count of exactly one, and a situs
    that names no unit. A condominium unit never qualifies: its living area is one
    apartment's and its story count may be the building's.
    """
    return (_code(row) in _ONE_HOME and num(row.get("num_families")) == 1
            and not unit_of(row.get("situs_address")))


def _area(row: dict) -> float | None:
    area = num(row.get("tot_sqf_l_area"))
    if area is None or area <= 0 or not _one_home(row):
        return None
    return area


def _stories(row: dict) -> int | None:
    floors = num(row.get("num_stories"))
    if floors is None or not float(floors).is_integer():
        return None
    if not 1 <= floors <= _MAX_STORIES or not _one_home(row):
        return None
    return int(floors)


def _vintage(row: dict) -> str:
    """The record's tax year, read off the row; see "The table is a snapshot"."""
    year = num(row.get("tax_year"))
    if year and 1990 <= year <= 2100 and float(year).is_integer():
        return f"{DATA_VINTAGE}, tax year {int(year)}"
    return DATA_VINTAGE


def _pid(row: dict) -> str | None:
    pid = str(row.get("parcel_number") or "").strip()
    return pid or None


# ── the candidates ─────────────────────────────────────────────────────────────


def _property_ids(rows: list[dict]) -> list[int]:
    """The distinct property ids on these polygons, as integers.

    Integers on purpose: they go into the record request's ``IN (...)`` list, and
    a value that is not a plain number never reaches the query string. Polygons
    with no id (the fabric's "Pending" parcels) are records of nothing.
    """
    ids = set()
    for row in rows:
        value = num(row.get("PropertyID"))
        if value and value > 0 and float(value).is_integer():
            ids.add(int(value))
    return sorted(ids)


def _records(ids: list[int], *, deadline: float) -> list[dict]:
    """The assessor's records for these property ids (the second hop)."""
    if not ids:
        return []
    body = _shared.get_json(RECORD_URL, {
        "where": f"property_id IN ({','.join(str(i) for i in ids)})",
        "outFields": _RECORD_FIELDS, "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    return [(f or {}).get("attributes") or {} for f in (body.get("features") or [])]


def _candidates(records: list[dict]) -> list[dict]:
    """Records that could be the answer, one per property.

    Dropped: records with no parcel number or no property id, and records whose
    land use says no home stands there. Records sharing a property id are merged
    when they agree on every fact and refused when they do not (none repeat today;
    a repeat would be a broken join, and offering both would make the property
    ambiguous with itself).
    """
    groups: dict[int, list[dict]] = {}
    for row in records:
        pid = num(row.get("property_id"))
        if not pid or _pid(row) is None or not _is_a_home(row):
            continue
        groups.setdefault(int(pid), []).append(row)
    out = []
    for members in groups.values():
        if len({tuple(m.get(c) for c in _FACTS) for m in members}) > 1:
            continue
        out.append(members[0])
    return out


def _norm_unit(unit: str | None) -> str:
    return str(unit or "").strip().lstrip("#").casefold()


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The assessor's record of the parcel this point belongs to, or None.

    The choice is ``_shared.select_parcel``'s; see it for why the nearest parcel is
    never taken. Each search distance is two requests sharing one clock.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    typed_unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            polygons = _shared.arcgis_parcels(PARCEL_URL, lat, lon, _PARCEL_FIELDS,
                                              distance_m, deadline=deadline,
                                              read_slice=READ_SLICE_S)
            fetched[distance_m] = _candidates(
                _records(_property_ids(polygons), deadline=deadline))
        found = fetched[distance_m]
        if distance_m == 0 and address:
            # A condominium unit's polygon may be its building's, so the point can
            # be "inside" several units at once. With an address in hand the unit
            # is found by address in the buffer instead (see the docstring).
            found = [r for r in found if _code(r) not in _CONDO]
        if typed_unit:
            # A reader who typed a unit cannot live in a record naming another.
            found = [r for r in found
                     if not unit_of(r.get("situs_address"))
                     or _norm_unit(unit_of(r.get("situs_address")))
                     == _norm_unit(typed_unit)]
        return found

    return select_parcel(fetch, address, lambda r: r.get("situs_address"))


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year_built = _year(row)
    sqft = _area(row)
    stories = _stories(row)
    if year_built is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_pid(row),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        # The record carries no wall, foundation or condition column.
    )


def url_for(county_fips: str) -> str | None:
    """The layer that answers for this county, or None if none does — so a dropped
    lookup is named after the county's own publisher."""
    return PARCEL_URL if str(county_fips).strip().zfill(5) in COUNTY_FIPS else None


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Jackson County's assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address (with any typed unit), used only
    to confirm the parcel. Fails open on everything — a timeout, a 500, a truncated
    page (``_shared.TruncatedResponse``), a renamed column — and the caller keeps
    what it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Missouri assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None

