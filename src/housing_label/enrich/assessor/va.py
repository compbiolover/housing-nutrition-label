#!/usr/bin/env python3
"""Virginia — Chesterfield County and the City of Richmond, from each one's own layer.

Virginia assesses by locality: 95 counties and 38 independent cities, and an
independent city is its own county-equivalent with its own FIPS code (Richmond is
51760, wholly separate from Henrico and Chesterfield around it). There is no
statewide roll, so this module is a per-locality table (``COUNTIES``), in the
shape of ``oh.py`` and ``ut.py``.

  ============  =====  =======  ============================================
  locality      FIPS   homes    source (keyless)
  ============  =====  =======  ============================================
  Chesterfield  51041  145,709  ``Cadastral_ProdA/FeatureServer/3``
                                "ParcelsEnriched" — one request
  Richmond      51760  114,293  ``Parcels/FeatureServer/0`` +
                                ``AssessorProVaGPINlImpDataPublish`` — two
                                hops
  ============  =====  =======  ============================================

("Homes" is ACS housing units, ``data/year_built_county.csv``.)

Northern Virginia, which was the target, is not here, and each county's reason is
different. They are worth stating because three of them have the data:

* **Fairfax (51059), held for its terms.** The best source in the state: a
  parcel layer with PIN, and daily tables keyed on it carrying ``YRBLT``,
  ``SFLA``, wall, basement and condition for 340,671 dwellings, condominium units
  included. Every one of those items licenses itself by pointing at the county's
  GIS disclaimer (https://www.fairfaxcounty.gov/maps/disclaimer), which ends
  "Copyright by Fairfax County. Except as provided herein, all rights are
  reserved. Authorization to reproduce material for internal or personal use by
  any user of this information is granted". Internal or personal use only is the
  same class of restriction as Cobb's "All rights reserved" (``ga.py``), so it is
  not built.
* **Arlington (51013), held for its terms.** Its open-data API publishes
  ``propertyYearBuilt`` for every property, but the portal's only "Terms of
  Use" link is the county website's terms
  (https://www.arlingtonva.us/Home/Terms-Conditions): "No person may ... sell,
  distribute, modify, transmit, reuse, repost ... the content of the website in
  whole or part for any purpose without the written permission", and downloads
  are "for non commercial, personal use only". The GIS hub adds "This data is not
  considered in the Public Domain". An older Open Data Public Use Notice ("free
  to share and adapt our data for any purpose") now redirects to the county's A-Z
  index. Not built until someone confirms which terms govern.
* **Prince William (51153) has no year built** in any public layer: its "Parcel
  CAMA Public" carries the situs, use code and above-grade area, and nothing
  else of a building's age. Every folder of its GIS server was scanned.
* **Loudoun (51107) has no assessor year built.** Its parcels carry neither an
  address nor a year. The one year in its GIS is ``LU_DEMOG_YEAR_BUILT`` on a
  Planning build-out project's structure points: undocumented provenance, the
  sentinels 1000 and 1111 on 3,211 homes, and a status of "Existing or
  Permitted" that cannot tell a house from a permit.
* **Alexandria (51510)** publishes year built only on a planning footprint layer
  with no parcel id or address. Joining it to a parcel takes a geometry
  intersect, which on a row of townhouses picks up the neighbors on either side
  of every party wall.

Henrico (51087) and Virginia Beach (51810) run their GIS on servers this
project's egress cannot reach; Virginia Beach's one ArcGIS Online copy with a
year built was last edited in December 2019.

Chesterfield — one request
--------------------------
``ParcelsEnriched`` is the county's parcel polygons joined to its CAMA record, so
the year built, finished area and story count sit on the polygon: 128,625
residential records, every one with a year built from 1700 on and all but 18 with
a finished area. The ``UseCode`` column is the county's residential class
(``SD`` single-family detached, ``TH``/``TN`` townhouse, ``CD``/``CN``
condominium, ``DU`` duplex) and, on other parcels, a three-digit commercial
occupancy code — under which ``100`` is apartments and the rest are banks,
churches, shops and warehouses whose year is not a home's (``home_uses``).

Its construction, foundation and exterior columns are filled — ``WF`` on 126,998
homes, ``BB``/``BR``/``CS``/``CB`` foundations, ``VY``/``WD``/``BR`` finishes —
and are deliberately not read. No code table travels with the service or is
published by the county, and ``BR`` appears in both the foundation and the
exterior column; deciding what each two-letter code means would be a guess
wearing the ``observed`` tag, the verdict Florida reached for ``CONST_CLAS``.

Richmond — two hops, because its parcels carry only a house number
------------------------------------------------------------------
The city's ``Parcels`` layer is current (re-published 2026-10-02) but carries
the situs as a bare house number (``AsrLocationBldgNo``), so it cannot confirm an
address on its own. The assessor's improvement records are a separate layer of
points, each inside its parcel, keyed by ``parcel_id`` (the PIN, space-padded to
26 characters) and carrying ``prop_street``, ``year_built``, ``sfla`` and the
CDU rating. So a containing parcel's PIN is looked up in the improvement layer,
and a buffered search asks the improvement layer directly — its points carry
their own street address, which is what the buffer needs.

That layer is a **snapshot**: the 2025 assessment (``eff_year`` 20250101),
published to the city's ArcGIS Online organization on 2024-10-21 and not edited
since. A year built does not change, so the cost is homes finished after that
date, which find no record and fall back to the modeled value. The vintage says
so on every record.

Condominiums, in both
---------------------
Both localities stack a building's units on one polygon, one record per unit:
Chesterfield on the whole complex's outline (one ``GPIN``, 106 rows at one
point), Richmond as unit PINs whose ``prop_street`` ends in the unit
(``"3510 East Richmond Road U9"`` — Richmond's own spelling; ``_RVA_UNIT_RE``).
Two things follow:

* **A typed unit picks its own record.** A reader who wrote a unit cannot live in
  a record that names a different one, so those rows are dropped before the
  parcel is chosen — the sanctioned shape (``select_parcel``): it can turn
  "ambiguous" into "one", never admit a record the address check would not.
* **Without one, records that share a street address are one building.**
  Chesterfield writes all of a garden building's units under one address with no
  unit at all (eight units at "1111 BRIARS CT", told apart only by ``TaxID``).
  Offered separately they are eight candidates and the shared chooser refuses
  them, correctly. They are merged into one candidate instead, which reports the
  building's year only when every unit record agrees on it, and never an area or
  a story count — those belong to one unit, and which unit is not known. That is
  the rule ``ut.py`` applies to a parcel's identical building rows; the
  difference is that agreement on the year is required rather than assumed.

A unit's own area is reported only when the record is that unit: a Chesterfield
condominium row with its own street address, or a Richmond unit whose
designator matches the one the reader typed.

The clock
---------
Both localities answer quickly, so both run on the shared four-second budget and
one-second read slice. Measured 2026-10-04 at random residential points, 45 per
layer per kind, then again inside the verification run below (172 lookups):

  =======================================  ======  ======  ======  ======
  request                                  median     p90     p95     max
  =======================================  ======  ======  ======  ======
  "which parcel is this dot inside?"        0.12 s  0.14 s  0.16 s  0.59 s
  "what is within 80 m of this dot?"        0.14 s  0.16 s  0.18 s  0.73 s
  Richmond: "which records have this PIN?"  0.17 s  0.25 s  0.26 s  0.26 s
  =======================================  ======  ======  ======  ======

A Richmond lookup that widens makes three requests, about 0.45 s typical.
Responses are under 25 KB; the largest stack under one point was 106 rows,
far under the layers' 2,000-row page.

What the adapter is worth, end to end
-------------------------------------
180 homes drawn at random from the two sources themselves (105 Chesterfield,
75 Richmond; random object-id windows across each layer), typed as street,
city and ZIP, geocoded through the Census matcher exactly as the product does,
passed through ``assessor_address``, then looked up:

  ============  ======  ========  ========  =====  ==========  ===========
  locality      sample  geocoded  resolved  wrong  year exact  area exact
  ============  ======  ========  ========  =====  ==========  ===========
  Chesterfield     105        99        82      0    82 of 82    80 of 80
  Richmond          75        73        67      0    67 of 67    60 of 60
  ============  ======  ========  ========  =====  ==========  ===========

Every geocoded address was routed to the right FIPS. Of the 23 that did not
resolve, 20 are geocodes placed more than the search radius from the home's
lot (Chesterfield's long suburban streets, 107-283 m from the lot's center; two
large Richmond lots; one Richmond condominium 160 m from its geocode), one is
Richmond's "Meadow Bridge Road" against the matcher's "MEADOWBRIDGE RD", and
two are Richmond parcels holding a house and an accessory dwelling of different
years (4508 Leonard Pkwy: 1939 and 2001) — refused on purpose, since neither
year is "the house's" without knowing which one the reader lives in.

A second, condominium-only run (25 unit records per locality, Richmond's typed
with their unit as a reader would) resolved 14 of 25 in Richmond — 13 to the
unit's own record, every area exact — and 11 of the 16 Chesterfield addresses
the matcher could find (6 unit records, 5 garden buildings answered with the
building's year), none wrongly. Eight of Richmond's 11 misses are units of two
towers: 2956 Hathaway Road, whose unit points all sit 145 m from the geocode,
and 301 Virginia St, which the matcher placed in another part of the city.

The verification also found two bugs, both fixed: a 64-unit stack made a 4.8 KB
query string that ArcGIS Online answers with a 404 (``_MAX_EXACT_PINS``), and a
unit found inside its complex's outline was lost when the widened search, which
asks Richmond's points, did not reach them (``_parcel_at`` now carries what the
point is inside into the widened search).

Terms of use
------------
* Chesterfield's layer is in the "Open Data" group of the county's Open GIS Data
  hub (https://opengisdata.chesterfield.gov), whose terms read: "You can copy,
  modify, distribute, and perform analyses on the data, even for commercial
  purposes, all without asking permission." Attribution is requested, not
  required; the ``ATTRIBUTION`` string gives it.
* Richmond's items carry only "No warranty is expressed or implied regarding the
  use of this data, nor does the act of distribution constitute any such
  warranty"; the GeoHub's "Terms of Use" link is a placeholder (``#``). Public
  record, no restriction published — listed with the sources to confirm before
  a commercial launch.

Both are queried live and cached in-process, never bundled, which is every
adapter's posture.

Privacy, and why the field lists are short
------------------------------------------
Chesterfield's layer carries ``OwnerName``, ``OwnerAddress``, ``SalePrice`` and
the assessed values; Richmond's parcels carry ``OwnerName`` and the owner's
mailing address, and its improvement points ``owner1``. None of it is an input
to any dimension of the label. Every request names its columns, ``*`` is never
sent, and nothing from either source is written into the repository.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Virginia local assessors"
ATTRIBUTION = ("Virginia local assessors' records (Chesterfield County Open GIS "
               "Data; City of Richmond Assessor of Real Estate), keyless")
DATA_VINTAGE = "Virginia local assessor records"

# ── the services ───────────────────────────────────────────────────────────────

CHESTERFIELD_URL = ("https://services3.arcgis.com/TsynfzBSE6sXfoLq/arcgis/rest/services"
                    "/Cadastral_ProdA/FeatureServer/3/query")
RICHMOND_PARCEL_URL = ("https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest/services"
                       "/Parcels/FeatureServer/0/query")
#: The assessor's improvement records: points, one or more per parcel, each
#: inside its parcel. A snapshot of the 2025 assessment; see the docstring.
RICHMOND_IMPROVEMENT_URL = ("https://services1.arcgis.com/k3vhq11XkBNeeOfM/arcgis/rest"
                            "/services/AssessorProVaGPINlImpDataPublish/FeatureServer/0"
                            "/query")

_CHESTERFIELD_FIELDS = ("Name,GPIN,TaxID,ParcelType,UseCode,Address,AssessmentYear,"
                        "YearBuilt,FinishedArea,Stories")
_RICHMOND_PARCEL_FIELDS = "PIN"
_RICHMOND_IMPROVEMENT_FIELDS = ("parcel_id,prop_street,property_class,year_built,sfla,"
                                "cdu,eff_year")

# ── one normalized record ──────────────────────────────────────────────────────
#
# Each locality's rows are reduced to the same keys, so choosing the parcel and
# reading its facts is written once:
#
#   pid       the record's own identifier (a unit's, where units are records)
#   parcel    the polygon the record sits on, where that differs (Chesterfield's
#             GPIN, shared by every unit of a complex)
#   address   the street address, unit removed
#   unit      the record's own unit designator, or None
#   use       the locality's class code, as a string
#   year, area, stories, condition   raw values, read through the County's sets


@dataclass(frozen=True)
class County:
    """Everything that is a fact about one locality's source."""

    name: str
    #: The layer named when a lookup here is dropped (``url_for``).
    url: str
    attribution: str
    #: Rows at (or within ``distance_m`` of) a point, normalized as above.
    rows: Callable[["County", float, float, float, float], list[dict]]
    #: Class codes whose record is somebody's home: only these report a year.
    home_uses: frozenset[str]
    #: Class codes whose record is exactly one dwelling: only these report an area.
    one_dwelling_uses: frozenset[str]
    #: Class codes whose story count is a house's (not a unit's or a complex's).
    house_uses: frozenset[str] = frozenset()
    #: Where stories come from the class itself rather than a column.
    stories_by_use: dict | None = None
    #: The locality's condition vocabulary -> the label's, where it has one.
    condition: dict | None = None
    vintage: Callable[[dict], str] = lambda row: DATA_VINTAGE
    read_slice: float = _shared._READ_SLICE_S
    timeout: float = _shared.TIMEOUT


# ── Chesterfield ───────────────────────────────────────────────────────────────

#: Residential classes, measured over the county's 128,625 records carrying them:
#: SD 116,300; TH 4,789; TN 3,081; CD 2,352; CN 1,862; DU 241.
_CHESTERFIELD_RESIDENTIAL = frozenset({"SD", "TH", "TN", "CD", "CN", "DU"})
#: "100" is the commercial occupancy code the county gives apartment complexes
#: (Keswick Apartments, Livingston Apartment Flats, City View); its year is the
#: complex's, which is the year of every apartment in it.
_CHESTERFIELD_APARTMENTS = frozenset({"100"})


def _chesterfield_vintage(row: dict) -> str:
    year = num(row.get("_assessed"))
    base = "Chesterfield County Real Estate Assessment via ParcelsEnriched"
    return f"{base}, {int(year)} assessment" if year and 1900 <= year <= 2100 else base


def _chesterfield_rows(cfg: County, lat: float, lon: float, distance_m: float,
                       deadline: float) -> list[dict]:
    """Chesterfield's records at a point, with the layer's non-records dropped.

    The layer carries "Hole" polygons (the gaps inside a parcel's outline) and a
    county-sized polygon named "0", both with every attribute null — one of them
    lay under a real coordinate in the sample. They can never be an answer, and
    counted as candidates they would make a real parcel ambiguous, so they go here
    (see ``select_parcel``).
    """
    rows = _shared.arcgis_parcels(CHESTERFIELD_URL, lat, lon, _CHESTERFIELD_FIELDS,
                                  distance_m, deadline=deadline,
                                  read_slice=cfg.read_slice)
    out = []
    for r in rows:
        gpin = str(r.get("GPIN") or "").strip()
        if not gpin or str(r.get("ParcelType") or "").strip() == "Hole":
            continue
        tax_id = num(r.get("TaxID"))
        out.append({
            "pid": str(int(tax_id)) if tax_id else (str(r.get("Name") or "").strip()
                                                     or gpin),
            "parcel": gpin,
            "address": " ".join(str(r.get("Address") or "").split()) or None,
            "unit": None,
            "use": str(r.get("UseCode") or "").strip().upper(),
            "year": r.get("YearBuilt"),
            "area": r.get("FinishedArea"),
            "stories": r.get("Stories"),
            "condition": None,
            "_assessed": r.get("AssessmentYear"),
        })
    return out


# ── Richmond ───────────────────────────────────────────────────────────────────

#: Residential property classes (the city's ``PropertyClass`` names): 110 One
#: Story, 115 One Story+, 120 Two Story, 130 Two Story+, 150 Split Level, 155
#: Single Family Converted ELU, 160/161 Two Family, 170/171 Three Family, 180/181
#: Four Family, 195 Res/Comm Mixed Use, 196 LIHTC 1-4 Units, 198 Single Family
#: Miscellaneous, 210-212 Condo Residential, 310-341 Apartments, 396 LIHTC 5+
#: Units, 398 Multi-Family Miscellaneous. Left out: 190 Garage/Outbuilding,
#: 205/206 condo common areas, 220/230 condo parking, 355 assisted living, 360
#: rooming houses, 365 bed and breakfast, and every commercial (4xx/5xx) class.
_RICHMOND_HOMES = frozenset({
    "110", "115", "120", "130", "150", "155", "160", "161", "170", "171", "180",
    "181", "195", "196", "198", "210", "211", "212", "310", "315", "321", "325",
    "330", "335", "341", "396", "398",
})
#: One dwelling per record: the single-family classes, and a condominium unit.
_RICHMOND_ONE_DWELLING = frozenset({"110", "115", "120", "130", "150", "210", "211",
                                    "212"})
#: The two classes whose name IS a whole story count. 115 ("1.25, 1.5, 1.75"),
#: 130 ("2.5, 3.0, 3+") and 150 (split level) name a range or a form, not a count.
_RICHMOND_STORIES = {"110": 1, "120": 2}

# Richmond's CDU rating, measured on 60,685 residential improvement records:
# AV 26,573; G 19,818; VG 7,615; F 4,599; P 1,009; EX 929; VP 140; blank 2.
_RICHMOND_CONDITION = {
    "EX": "excellent",
    "G": "good",
    "AV": "average",
    "F": "fair",
    "P": "poor",
}
# Deliberately unmapped: VG (very good) and VP (very poor) each fall between two
# of the label's grades — the same call oh.py makes for Butler's CDU.

#: Richmond writes a condominium unit as a final "U" token on the street address:
#: "3510 East Richmond Road U9", "1101 Haxall Pt U1002", "507 N Hamilton St UE",
#: "Stuart Cir UPL-D". Measured over all 69,384 improvement records: 3,482 end in
#: such a token, 3,445 of them condominium or condo-common classes, and none of
#: the others is a street name ending in U. ``_shared.address_key`` reads only a
#: digit-bearing token after a street type as a unit, so "UE", and anything after
#: a type it does not know ("PT"), would stay in the street name and no unit
#: address would ever confirm.
_RVA_UNIT_RE = re.compile(r"^(?P<street>\d.*\S)\s+U(?P<unit>[A-Z0-9][A-Z0-9-]{0,6})$",
                          re.I)


def _richmond_street(raw) -> tuple[str | None, str | None]:
    """``(street address, unit)`` from Richmond's padded ``prop_street``."""
    text = " ".join(str(raw or "").split())
    if not text:
        return None, None
    m = _RVA_UNIT_RE.match(text)
    if m:
        return m.group("street"), m.group("unit").upper()
    return text, None


def _richmond_vintage(row: dict) -> str:
    raw = str(row.get("_eff") or "").split(".")[0]
    base = ("City of Richmond Assessor of Real Estate improvement records "
            "(snapshot published 2024-10-21)")
    year = raw[:4]
    return f"{base}, {year} assessment" if len(raw) == 8 and year.isdigit() else base


def _richmond_normalize(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        pid = str(r.get("parcel_id") or "").strip()
        if not pid:
            continue
        street, unit = _richmond_street(r.get("prop_street"))
        cls = num(r.get("property_class"))
        out.append({
            "pid": pid,
            "parcel": pid,
            "address": street,
            "unit": unit,
            "use": str(int(cls)) if cls is not None else "",
            "year": r.get("year_built"),
            "area": r.get("sfla"),
            "stories": None,
            "condition": r.get("cdu"),
            "_eff": r.get("eff_year"),
        })
    return out


#: How many PINs are asked for one by one. A condominium stack puts dozens of
#: unit parcels under one point (64 at 1449 Cargreen Road), and 64 predicates make
#: a 4.8 KB query string, which ArcGIS Online answers with a 404 — found by the
#: verification run, where it read as "no record". Past this many, the PINs are
#: asked for by their map-and-block prefix (the first 8 of 11 characters, which
#: every unit of one building shares) and the rows filtered back to the PINs.
_MAX_EXACT_PINS = 20
_PIN_BLOCK = 8
#: More distinct blocks than this under one point is not a building; it is
#: answered as ambiguous rather than with a very long URL.
_MAX_BLOCKS = 10


#: The shared search radius (``_shared.SEARCH_RADIUS_M``) is a distance to a
#: parcel's EDGE: "within 80 m" means any part of the lot is. Richmond's buffered
#: search asks a layer of points instead, each somewhere inside its lot, so the
#: same question needs the distance from a point to the far side of its own lot
#: added. Measured over 120 random residential records: median 23 m, p90 41 m,
#: p95 50 m (deep lots and condominium complexes are the tail). Without it, 18 of
#: the 73 geocoded verification homes went unresolved even though every one of
#: their lots lay within 80 m of the geocode. The address still decides: a wider
#: circle can only offer more candidates, and one must agree, uniquely.
_RVA_POINT_ALLOWANCE_M = 50


def _richmond_rows(cfg: County, lat: float, lon: float, distance_m: float,
                   deadline: float) -> list[dict]:
    """Richmond's improvement records at, or near, a point.

    At the point: the parcel(s) containing it, then their improvement records by
    PIN. Near it: the improvement points themselves, which carry their own street
    address. A containing parcel with no improvement record (vacant, or built
    after the snapshot) contributes nothing, so the search widens — and the
    widened search still needs the address to agree.
    """
    if distance_m:
        rows = _shared.arcgis_parcels(RICHMOND_IMPROVEMENT_URL, lat, lon,
                                      _RICHMOND_IMPROVEMENT_FIELDS,
                                      distance_m + _RVA_POINT_ALLOWANCE_M,
                                      deadline=deadline, read_slice=cfg.read_slice)
        return _richmond_normalize(rows)
    parcels = _shared.arcgis_parcels(RICHMOND_PARCEL_URL, lat, lon,
                                     _RICHMOND_PARCEL_FIELDS, 0, deadline=deadline,
                                     read_slice=cfg.read_slice)
    # PINs come from the city's own response; anything but letters and digits is
    # dropped all the same, so a malformed record cannot break the predicate.
    pins = sorted({re.sub(r"[^A-Za-z0-9]", "", str(p.get("PIN") or ""))
                   for p in parcels} - {""})
    if not pins:
        return []
    # LIKE rather than "=": parcel_id is space-padded to 26 characters, and every
    # PIN is 11, so a prefix match on the whole PIN is an exact match on it.
    if len(pins) <= _MAX_EXACT_PINS:
        prefixes = pins
    else:
        prefixes = sorted({pin[:_PIN_BLOCK] for pin in pins})
        if len(prefixes) > _MAX_BLOCKS:
            return []
    where = " OR ".join(f"parcel_id LIKE '{p}%'" for p in prefixes)
    body = _shared.get_json(RICHMOND_IMPROVEMENT_URL, {
        "where": where, "outFields": _RICHMOND_IMPROVEMENT_FIELDS,
        "returnGeometry": "false", "f": "json",
    }, deadline, cfg.read_slice)
    rows = [(f or {}).get("attributes") or {} for f in (body or {}).get("features") or []]
    wanted = set(pins)
    return [r for r in _richmond_normalize(rows) if r["pid"] in wanted]


# ── the table ──────────────────────────────────────────────────────────────────

COUNTIES: dict[str, County] = {
    "51041": County(
        name="Chesterfield",
        url=CHESTERFIELD_URL,
        attribution=("Chesterfield County Real Estate Assessment via Chesterfield "
                     "Open GIS Data (keyless)"),
        rows=_chesterfield_rows,
        home_uses=_CHESTERFIELD_RESIDENTIAL | _CHESTERFIELD_APARTMENTS,
        # A duplex's record covers both halves; an apartment complex's, all of it.
        one_dwelling_uses=frozenset({"SD", "TH", "TN", "CD", "CN"}),
        # A condominium row's story count may be the unit's or the building's.
        house_uses=frozenset({"SD", "TH", "TN", "DU"}),
        vintage=_chesterfield_vintage,
    ),
    "51760": County(
        name="Richmond",
        url=RICHMOND_IMPROVEMENT_URL,
        attribution=("City of Richmond Assessor of Real Estate improvement records "
                     "via Richmond GeoHub (keyless)"),
        rows=_richmond_rows,
        home_uses=_RICHMOND_HOMES,
        one_dwelling_uses=_RICHMOND_ONE_DWELLING,
        stories_by_use=_RICHMOND_STORIES,
        condition=_RICHMOND_CONDITION,
        vintage=_richmond_vintage,
    ),
}

COUNTY_FIPS = frozenset(COUNTIES)

#: Localities with the data that are deliberately not answered. Not configured —
#: their terms restrict reuse (see the module docstring), so no lookup is built
#: for them — and listed so a test can pin that they stay out of COUNTY_FIPS.
_HELD_FOR_TERMS = frozenset({"51059", "51013"})       # Fairfax, Arlington
#: Localities searched and found to publish no usable year built.
_NO_PUBLIC_YEAR = frozenset({"51153", "51107", "51510"})  # Prince William, Loudoun,
#                                                          # Alexandria

#: The module's clock: the largest any locality is given. Both run on the shared
#: four-second budget and one-second read slice, which every measured request
#: fit (slowest 0.73 s; see "The clock" in the module docstring). A test pins each
#: pair, and this one, under ``config.UPSTREAM_HOST_BUDGET``.
READ_SLICE_S = max(c.read_slice for c in COUNTIES.values())
LOOKUP_TIMEOUT = max(c.timeout for c in COUNTIES.values())

#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (a direct call). The registry always says.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services"
              "/TIGERweb/State_County/MapServer/1/query")


# ── reading one record ─────────────────────────────────────────────────────────


def _year(cfg: County, row: dict) -> int | None:
    """The actual year built, where the record is somebody's home."""
    if row["use"] not in cfg.home_uses:
        return None
    year = num(row.get("year"))
    if not year or not EARLIEST_PLAUSIBLE_YEAR <= year <= 2100:
        return None
    return int(year)


_MAX_STORIES = 4


def _stories(cfg: County, row: dict) -> int | None:
    """A whole story count of a house, or None.

    A half story is real ("1.5", "1.75" in Chesterfield) and is not rounded into
    a whole one, the same call every adapter makes.
    """
    if cfg.stories_by_use is not None:
        return cfg.stories_by_use.get(row["use"])
    if row["use"] not in cfg.house_uses:
        return None
    floors = num(row.get("stories"))
    if floors is None or not float(floors).is_integer():
        return None
    return int(floors) if 1 <= floors <= _MAX_STORIES else None


def _norm_unit(unit) -> str:
    return "".join(ch for ch in str(unit or "").upper() if ch.isalnum())


def _area(cfg: County, row: dict, typed_unit: str | None) -> float | None:
    """The record's floor area, where the record is the one dwelling being scored.

    A record naming a unit is that unit, so its area is reported only to a reader
    who typed the same unit — anyone else at the address may live in another.
    """
    if row["use"] not in cfg.one_dwelling_uses:
        return None
    if row.get("unit") and _norm_unit(row["unit"]) != _norm_unit(typed_unit):
        return None
    area = num(row.get("area"))
    return area if area and area > 0 else None


def _condition(cfg: County, row: dict) -> str | None:
    if not cfg.condition or row["use"] not in cfg.home_uses:
        return None
    return cfg.condition.get(str(row.get("condition") or "").strip().upper())


# ── the candidates ─────────────────────────────────────────────────────────────


def _candidates(rows: list[dict], typed_unit: str | None) -> list[dict]:
    """Records grouped into the candidates the parcel chooser sees.

    A typed unit first drops every record naming a different unit. Then records
    sharing one street address are one building (see the module docstring); a
    record whose address does not parse stays on its own.

    Within one address, a record naming exactly the typed unit IS the reader's
    home, and the address's unit-less records beside it are the building's —
    Richmond files a condominium's common area (class 205) under the same street
    address as its units. Merging the two would demote a unit the reader named to
    "a building", and lose the unit's own area, so the unit wins there.
    """
    want = _norm_unit(typed_unit)
    if want:
        rows = [r for r in rows if not r.get("unit") or _norm_unit(r["unit"]) == want]
    groups: dict[tuple, list[dict]] = {}
    out = []
    for r in rows:
        key = address_key(r.get("address"))
        if key is None:
            out.append({"address": r.get("address"), "rows": [r]})
        else:
            groups.setdefault(key, []).append(r)
    for group in groups.values():
        named = [r for r in group if want and _norm_unit(r.get("unit")) == want]
        out.append({"address": group[0].get("address"), "rows": named or group})
    return out


def _identity(row: dict) -> tuple:
    """What makes two normalized rows the same record, for de-duplication."""
    return (row.get("pid"), row.get("address"), row.get("unit"), row.get("year"),
            row.get("area"))


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the covered locality this point is in, from TIGERweb.

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


def _parcel_at(lat: float, lon: float, address: str | None = None,
               county_fips: str | None = None,
               *, deadline: float | None = None) -> tuple[County, dict] | None:
    """The locality's candidate for the home at this point, or None.

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
    at_point: list[dict] = []

    def fetch(distance_m):
        rows = cfg.rows(cfg, lat, lon, distance_m, deadline)
        if distance_m == 0:
            at_point[:] = rows
        else:
            # The widened search must include what the point is inside. For a
            # polygon layer it does by geometry; Richmond's widened search asks a
            # layer of points, and a condominium complex's unit points sit on one
            # spot that can be farther away than the complex's outline — 1453
            # Cargreen Road #B was found inside the outline and lost to the buffer
            # at 143 m.
            rows = rows + at_point
        # One record is one candidate however many times it arrives — in both
        # searches, or as two parts of a multipart parcel. A duplicate would be
        # merged as a second unit of one building and cost the record its area.
        unique: dict[tuple, dict] = {}
        for r in rows:
            unique.setdefault(_identity(r), r)
        found = _candidates(list(unique.values()), unit)
        if distance_m == 0 and address and len(found) > 1:
            # Several buildings under one point: a condominium complex's outline
            # with units at different street addresses (Chesterfield's CN
            # villas), or a stack of parcels. The point is "inside" all of them,
            # so containment cannot choose. With an address in hand the buffer
            # (which contains the point) can: it must hold exactly one candidate
            # whose address agrees. Without one nothing changes, and the stack
            # stays ambiguous.
            return []
        return found

    chosen = select_parcel(fetch, address, lambda c: c["address"])
    return (cfg, chosen) if chosen is not None else None


def _record(cfg: County, candidate: dict, typed_unit: str | None) -> AssessorRecord | None:
    rows = candidate["rows"]
    if len(rows) == 1:
        row = rows[0]
        year, sqft = _year(cfg, row), _area(cfg, row, typed_unit)
        stories, condition = _stories(cfg, row), _condition(cfg, row)
        pid = row["pid"]
    else:
        # One building's unit records. Its year is reported only when every
        # home record agrees; nothing that belongs to one unit is reported.
        years = {_year(cfg, r) for r in rows if r["use"] in cfg.home_uses}
        year = years.pop() if len(years) == 1 else None
        sqft = stories = condition = None
        parcels = {r["parcel"] for r in rows}
        pid = parcels.pop() if len(parcels) == 1 else None
        row = rows[0]
    if all(v is None for v in (year, sqft, stories, condition)):
        return None
    return AssessorRecord(
        source=cfg.attribution,
        data_vintage=cfg.vintage(row),
        parcel_id=pid,
        year_built=year,
        sqft=sqft,
        stories=stories,
        condition=condition,
        # Neither locality publishes a foundation type the label can read, and
        # Chesterfield's wall codes have no published table; see the docstring.
    )


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    found = _parcel_at(lat, lon, address, county_fips)
    if not found:
        return None
    cfg, candidate = found
    return _record(cfg, candidate, unit_of(address))


def url_for(county_fips: str) -> str | None:
    """The layer that answers for this locality, or None if none does — so a
    dropped lookup is named after the locality's own publisher, not another's."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the locality's assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address (carrying the reader's unit, if
    they typed one), used only to confirm the record. ``county_fips`` is the
    county the registry routed on; without it the county is looked up from the
    point (one extra request).

    Fails open on everything — a timeout, a 500, a truncated page
    (``_shared.TruncatedResponse``), a renamed column, a moved service.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Virginia assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
