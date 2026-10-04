#!/usr/bin/env python3
"""Minnesota — the seven-county Twin Cities metro, from one regional parcel service.

Assessment in Minnesota is done by each county assessor, and the seven metro
counties (Anoka, Carver, Dakota, Hennepin, Ramsey, Scott, Washington; about 1.33
million homes) each keep their own CAMA system. What makes one adapter possible
is **MetroGIS**, the region's data collaborative: every quarter the Metropolitan
Council collects all seven counties' tax-parcel layers, maps their attributes
onto the **Minnesota Parcel Data Transfer Standard** (in force since 2019-01-01)
and republishes them as the *Metro Regional Parcel Dataset* — one service, one
schema, one layer per county:

  ``arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcels/FeatureServer/<n>``
  — "Metropolitan 7-County Parcel Polygons", the current quarter. Layers 0-6 are
  Anoka, Carver, Dakota, Hennepin, Ramsey, Scott and Washington. 1,142,436
  polygons, keyless, verified live 2026-10-04.

The older per-county services (``ds1/.../GISParcels/Parcels20xx<County>``) answer
"Service not started" and are not used. The same server keeps dated snapshots
(``Parcels_2021`` ... ``Parcels_2025``); the undated ``Parcels`` service is the
current quarter — its rows were exported 2026-06-27 to 2026-07-13, the 2025
snapshot's a year earlier — and is the one this adapter reads.

One request, like Florida
-------------------------
The standard's attributes sit on the polygon, so a lookup is a containment query,
plus an 80 m buffered query only when the geocode landed off every parcel or on
the wrong one. The county decides which layer: the registry passes the county it
routed on, and only a direct call without one asks Census TIGERweb which county
the point is in (``COUNTY_URL``).

How full it is, measured
------------------------
Year built on single-unit residential parcels (each county's own "residential
single unit" class; Dakota's "Residential"/"Residential-townhouse"; Hennepin's
"Residential", "Townhouse" and "Residential Lake Shore"; Washington's class 100),
by count query, 2026-10-04:

  ===========  =========  ==========  ===========  =========================
  county        homes      year built  finished ft  vintage (rows)
  ===========  =========  ==========  ===========  =========================
  Anoka         120,989    97.0%       97.0%        2025 assessment, pay 2026
  Carver         37,578    98.3%       98.3%        exported 2026-06-27
  Dakota        131,187    95.1%       95.1%        2026 assessment, pay 2027
  Hennepin      312,157    99.9%       none         exported 2026-07-13
  Ramsey        142,411    98.4%       98.2%        2025 assessment, pay 2026
  Scott          49,714    98.1%       98.1%        2026 assessment, pay 2027
  Washington     98,522    96.5%       95.6%        2026 assessment, pay 2027
  ===========  =========  ==========  ===========  =========================

All seven clear the bar the North Carolina adapter set (most homes carry a year),
so all seven are claimed. Hennepin, the largest, sends the year and nothing else:
its finished area, dwelling type, home style and unit count reach the regional
layer empty or zeroed (``NUM_UNITS`` is 0 on all 447,044 rows). Carver and
Hennepin send no tax or assessment year either, so their records are dated by the
row's export date instead — see ``_vintage``.

Condominiums and townhomes: stacked polygons
--------------------------------------------
Minnesota taxes each condominium unit as its own parcel, and Hennepin, Ramsey and
Washington draw each unit as its own polygon — **the same polygon, repeated**.
730 4th St N in Minneapolis is 241 identical polygons: 110 condominium units and
131 garage stalls ("Condo - Garage/Miscellaneous"). A Woodbury eight-plex is eight
polygons at 8741 Quarry Ridge Ln, units A-H; a Vadnais Heights building is six,
each unit at its own house number (1014-1024 Pondview Ct). Condominium records on
the polygon layer, by count query: Hennepin 47,264, Ramsey 11,540, Washington
7,225, Anoka 5,285, Scott 400, Dakota 137, Carver none. The regional dataset's
own description says some counties publish condominiums only in its companion
*points* layer, which this adapter does not read; there a condominium resolves
to its association's parcel or not at all.

``_shared.select_parcel`` correctly refuses more than one containing record, so a
stacked point would always be refused. This adapter therefore groups records **by
polygon** before the shared chooser sees them, the Massachusetts design:

* The layer has no polygon identifier, so a polygon is recognized by its own
  area and perimeter (``Shape__Area``, ``Shape__Length``), compared exactly as the
  service serializes them. Repeated copies of one polygon are bit-identical
  (all 241 at 730 4th St N); two different lots matching to the last digit of
  both is the one way this could merge distinct parcels, and even then the
  address checks below still apply.
* The chooser decides *which polygon*, with its rules untouched. Inside the
  chosen polygon, *which record* is decided by the address and the unit, never by
  position: records that rule a home out (garages, storage, common area) are set
  aside, then only records whose own address agrees with the geocoded one are
  kept, and a unit the reader typed must match exactly one of them.
* Where several records remain and no unit singles one out, the polygon's **year**
  is reported only if every remaining record agrees on it — true of every unit in
  a condominium building — and nothing else is, with no parcel id, because no
  single parcel was identified.
* A typed unit also removes every record that names a *different* unit, and a
  polygon left with none is not a candidate. Anoka draws a quadplex as four
  polygons at one address (12162 Waconia St NE, units A-D), so without this a
  typed "#C" faces four agreeing polygons and is refused; with it, one remains.
  It can only turn "ambiguous" into "one" — the shape ``select_parcel`` allows.

A townhome is usually its own polygon at its own number and resolves like a
house; where several share a polygon (Ramsey's TICO townhomes) the house number
picks the record, as at Vadnais Heights.

Which records hold a home
-------------------------
Every county writes its own class vocabulary into the standard's ``USECLASS1``
(Anoka "1a RESIDENTIAL SINGLE UNIT", Dakota "Residential-townhouse", Hennepin
"Condominium (also Market Rate Cooperative)", Scott "201 1A/4BB(1) RESIDENTIAL
SINGLE UNIT", Washington a bare "100") and its own ``DWELL_TYPE``. A record is
read as **holding no home** only where one of those two says so in words no
county uses for a dwelling (``_NO_HOME_WORDS``): a garage, storage, common area,
vacant or unimproved land, detached structures only, commercial, industrial, a
railroad, a non-tax outlot. A year read from those would describe a building
nobody lives in while carrying the ``observed`` tag, so it is refused. Anything
else lets the year through.

``NUM_UNITS`` cannot do that job. Hennepin zeroes it everywhere, Anoka, Carver and
Scott leave it empty, and where it is filled a zero does not mean "no dwelling":
measured, Dakota files 814 houses and 541 townhouses with 0 units and a year,
most of them 2025 new construction, and Ramsey files ordinary 1960s houses the
same way. A zero is never read as "no home". A value of 2 or more still refuses
the floor area, because it positively says the record covers more than one unit.

The floor area, and when it describes one home
----------------------------------------------
``FIN_SQ_FT`` is the standard's finished square footage. It is reported only
where the record says it is one dwelling: ``NUM_UNITS`` is 1, or the class or
dwelling type positively says single unit / single family (Anoka, Carver and
Scott leave the count empty and say "RESIDENTIAL SINGLE UNIT"; Dakota files new
houses with 0 units and "S.fam.res") — and nothing on the record says two-family,
duplex, triplex, apartment, double bungalow or accessory unit. A condominium unit
record is one dwelling (its own ``NUM_UNITS`` is 1 and its area is the unit's —
875 and 1,015 ft² side by side at Vadnais Heights), so its area is reported when
that record was picked out by its own house number, or by the unit the reader
typed. A record that names a unit the reader did not type — another one, or
none at all — keeps its year and loses its area and stories, because a geocode
inside unit C's polygon confirms the building for a reader in unit A just as
well (``_speaks_for_the_reader``). Never divided by a unit count, for the reason
``fl.py`` gives.

Stories and wall material: read off the home style
--------------------------------------------------
``HOME_STYLE`` is free text per county, and only two readings of it are
unambiguous:

* **A whole story count**, where the style is exactly that — "One Story", "TWO
  STORY", "2 Story Frame", "TOWNHOUSE, 2 STORY", "Detached Townhome - 1 story",
  "3 Story" — or "Rambler", Minnesota's word for a one-story house. Reported only
  on a one-dwelling record. Not read: half and quarter stories ("1 1/2 Story",
  "1-3/4 Stry"; never rounded, the rule Cook and the District set), split levels,
  bi-levels and split entries (their story count is not a whole number of
  floors), Scott's "1-2 Story" (one or two), "Two+ Story", "Modified two story",
  "Bungalow", and every condominium style — "CONDO-APT STYLE-3RD FLR" is the
  floor the unit is on, not the building's height.
* **Wood frame**, where Carver's and Washington's style names its construction:
  "1 Story Frame", "Split Foyer Frame" — 38,000 and 85,000 homes. Mapped to
  ``frame``. "Brick" in the same table is not mapped: it does not say whether the
  wall is solid brick or a veneer over frame (``brick`` vs ``brick-frame``), the
  ambiguity Utah's adapter documents. "Metal Post Frame" (a pole building),
  "A-Frame" (a shape, not a material), log and earth-sheltered styles are left
  empty too.

What is not read
----------------
``BASEMENT`` says only whether there is one ("Yes"/"No"/"Unknown"), which is not
the label's foundation vocabulary — a "Yes" can be full or partial, a "No" a slab
or a crawlspace — so it is not requested. ``HEATING`` and ``COOLING`` have no slot
in ``AssessorRecord``. There is no condition grade in the standard.

Addresses
---------
The standard splits the situs into parts — number, prefix directional, prefix
type ("Highway" 169), name, suffix type, suffix directional — spelled out in full:
"730" "4th" "Street" "North". ``_street`` reassembles them, and three things
about that spelling have to be reconciled with the matcher's, each measured:

* **Directionals are abbreviated** ("Northwest" → "NW"), from the directional
  columns only, so the word is never a street's name. ``address_key`` knows a
  trailing quadrant only abbreviated, and Anoka, Scott and northern Ramsey
  address by quadrant: unabbreviated, 34 of 39 sampled Anoka homes failed.
* **The same directionals in another place.** The matcher moves St Paul's
  trailing directional to the front ("1478 Minnehaha Avenue West" → "1478 W
  MINNEHAHA AVE"). ``_agrees`` sets directionals aside and compares what is
  left, and accepts the pair only where both sides name exactly the same
  directionals — in whatever position, spelled or abbreviated.
* **A directional on one side only is never forgiven**, nor two that differ.
  The matcher also adds one the roll does not write ("1938 Jefferson Avenue" →
  "1938 W JEFFERSON AVE"), drops one it does ("2281 Pond Avenue East" → "2281
  POND AVE"; Plymouth's and Savage's "Lane North" / "Avenue South" → "LN" /
  "AVE"), and on Utah's grid it was measured swapping and dropping them outright
  (see ``ut.py``). 1478 Minnehaha Ave W and 1478 Minnehaha Ave E are different
  houses about 3 km apart, so a matcher that dropped the "E" and placed the
  point at the W house would have that house confirmed by a forgiving rule —
  and no check within ``SEARCH_RADIUS_M`` could see the twin. An earlier
  revision forgave a one-sided directional where no twin stood within 80 m; it
  was removed for exactly that reason, the rule ``nc.py`` and ``ut.py`` keep.
  The cost, measured on the verification sample below: 21 of 303 geocoded
  homes no longer resolve — Ramsey 42 → 32 of 44 (St Paul's E/W streets),
  Hennepin 64 → 58, Scott 35 → 31, Carver 26 → 25. Where the reader typed the
  directional the matcher dropped, ``location.assessor_address`` does not
  restore it (it treats a missing directional as "saying less", not a
  contradiction), so those homes stay unresolved rather than risk a twin.
* **Street types** the shared table does not know are written in their USPS
  Publication 28 form on both sides ("Curve" → "CURV", "Ridge" → "RDG";
  ``_LOCAL_TYPES``), since the matcher returns "LODGE POLE PT" in one place and
  "WILDS RIDGE NW" or "FALLS CURVE" in another; and "County Road" is written
  "Co Rd" as the matcher writes it. A county road's number then has to appear
  in the query word for word (``_names_its_number``): the shared comparison
  reads a number after a street type as a unit, which would make "15525 CO RD
  33" and "15525 CO RD 10" the same address.

A house number with a letter suffix ("123A") is not offered at all, because the
matcher writes it run together and a bare "123" would name the other half of
the duplex.

Terms of use
------------
The item's license field, on ArcGIS Online (item
``136b28bd0d874076b702ca55b9aafffc``, owner ``commons_etl_user``, the Minnesota
Geospatial Commons): "None. This dataset is public domain under the Minnesota
Government Data Practices Act (Minnesota Statutes Chapter 13)." Its description:
"This dataset includes all 7 metro counties that have made their parcel data
freely available without a license or fees." No use restriction, attribution
requirement or redistribution limit appears on the item or the service.
Verdict: clear for live query and cache. The query-and-cache-live posture is kept anyway, as every adapter
keeps it, and the credit (MetroGIS / Metropolitan Council and the county) travels
in each record's ``source``.

Why the shared clock is enough
------------------------------
Measured from this environment over 60 random homes across all seven counties
(keep-alive session, the module's own field list), plus six points in downtown
Minneapolis and Saint Paul beside stacked condominium towers:

  ===================================  ======  ======  ======  ======
  request                              median     p90     p95     max
  ===================================  ======  ======  ======  ======
  "which parcel is this dot inside?"    0.12 s  0.14 s  0.15 s  0.61 s
  "what is within 80 m of this dot?"    0.13 s  0.15 s  0.15 s  0.56 s
  ===================================  ======  ======  ======  ======

So this adapter runs on the shared four-second budget and one-second read slice
(``LOOKUP_TIMEOUT`` and ``READ_SLICE_S`` restate them, and a test pins their sum
under ``config.UPSTREAM_HOST_BUDGET``). The largest body, a buffer beside
downtown condominium towers, was 229 KB and 471 records — far under the layer's
2,000-record cap; a response flagged ``exceededTransferLimit`` is refused by
``_shared.get_json`` (``TruncatedResponse``) rather than read.

What the adapter is worth, end to end
-------------------------------------
325 homes drawn at random from the layers themselves (random object-id offsets;
Hennepin 75, Ramsey and Dakota 45 each, the other four 40 each), typed as the
roll spells them — with the unit where the record has one — geocoded through the
Census matcher exactly as the product does, then looked up with the geocoder's
county:

* 303 geocoded, all 303 routed to one of the seven county codes.
* **251 resolved (83% of geocoded), 0 naming a different parcel**: every one of
  the 251 with the exact year built, and all 191 floor areas reported equal to
  the record's. 120 also carry a story count and 50 (Carver and Washington) a
  wall material. Per county, resolved of geocoded: Hennepin 58/72, Ramsey 32/44,
  Dakota 38/41, Anoka 35/39, Washington 32/34, Scott 31/38, Carver 25/35.
* The 52 that did not resolve: 28 where the geocoder put the point more than
  80 m from the home's parcel (98-551 m from its centroid — large suburban and
  rural lots, and interpolated points); 21 where the matcher added or dropped a
  directional, refused on purpose (see "Addresses"); 2 where several polygons
  carry the address (two at 919 W Church St, Belle Plaine; forty townhome
  polygons sharing 3110 N Chestnut St, Chaska) — the shared chooser declining
  to guess; and 1 matcher substitution ("7541 CANYON Curve" came back "7541
  CANYON CT", a different street, correctly refused). 22 addresses the Census
  matcher could not geocode at all.

The address work above is what those numbers rest on. Before directionals were
abbreviated, 5 of 39 Anoka homes resolved (35 now). The earlier revision that
forgave one-sided directionals resolved 272 of the same 303, also with 0 wrong
— but its failure mode (a dropped directional landing on a far-away twin) is
not one a sample of this size would be expected to show.

A second, targeted sample of 60 condominium units (Hennepin 25, Ramsey 15,
Washington 12, Anoka 8 — every one on a stacked polygon or a unit-per-polygon
building), typed with the unit: 56 geocoded, **42 resolved, 0 wrong**, 40 to the
unit's own record and 2 to the building's year; all 24 unit areas reported (none
in Hennepin, which sends none) equal the unit's. The same 60 with the unit left
off: 34 resolved, 0 wrong, 13 of them to the building's year with no parcel id.

End to end, a lookup cost a median 0.24 s (p95 0.33 s, max 0.87 s).

Privacy, and why the field list is short
----------------------------------------
This layer has 96 columns, among them ``OWNER_NAME``, ``OWNER_MORE``, four owner
address lines, ``TAX_NAME`` and four taxpayer address lines, the last sale's date
and price, the homestead flag, and every estimated market value and tax amount.
None of it is an input to any dimension of the label. The columns in ``_FIELDS``
are requested by name and nothing else is fetched. Nothing from this source is
written into the repository.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, cache_bucket, deadline_from, num, same_address,
    select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "MetroGIS / Metropolitan Council"
ATTRIBUTION = ("Twin Cities metro county assessors via the MetroGIS Regional Parcel "
               "Dataset (Metropolitan Council), keyless")
DATA_VINTAGE = "MetroGIS Regional Parcel Dataset, current quarter"

#: The regional service; one layer per county (``COUNTIES``).
SERVICE_URL = ("https://arcgis.metc.state.mn.us/data1/rest/services/parcels"
               "/Parcels/FeatureServer")
PARCEL_URL = SERVICE_URL + "/{layer}/query"
#: Census TIGERweb counties, asked only when the caller did not say which county
#: the point is in (a direct call). The registry always says.
COUNTY_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services"
              "/TIGERweb/State_County/MapServer/1/query")

#: The shared budget and read slice, restated so the budget test has something to
#: pin; see "Why the shared clock is enough" in the module docstring.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT


@dataclass(frozen=True)
class County:
    name: str
    layer: int

    @property
    def url(self) -> str:
        return PARCEL_URL.format(layer=self.layer)


#: County FIPS → its layer in the regional service, in the service's own order.
COUNTIES = {
    "27003": County("Anoka", 0),
    "27019": County("Carver", 1),
    "27037": County("Dakota", 2),
    "27053": County("Hennepin", 3),
    "27123": County("Ramsey", 4),
    "27139": County("Scott", 5),
    "27163": County("Washington", 6),
}
COUNTY_FIPS = frozenset(COUNTIES)

# What the label scores, plus what decides which record (address parts, unit,
# polygon area and perimeter) and whether it is one home (class, dwelling type,
# unit count), plus the dates. Never owner, taxpayer, sale, value or homestead
# columns, and not BASEMENT/HEATING/COOLING — see the module docstring.
_FIELDS = ("COUNTY_PIN,ANUMBER,ANUMBERSUF,ST_PRE_MOD,ST_PRE_DIR,ST_PRE_TYP,"
           "ST_PRE_SEP,ST_NAME,ST_POS_TYP,ST_POS_DIR,ST_POS_MOD,SUB_ID1,"
           "USECLASS1,DWELL_TYPE,HOME_STYLE,FIN_SQ_FT,YEAR_BUILT,NUM_UNITS,"
           "TAX_YEAR,MKT_YEAR,EXP_DATE,Shape__Area,Shape__Length")


# --- which records hold a home ---------------------------------------------------

#: Words in ``USECLASS1`` or ``DWELL_TYPE`` that rule a dwelling out, whatever the
#: county. Each is taken from the classes measured on the layer: Hennepin's
#: "Condo - Garage/Miscellaneous" and "Common Area (No Value)", Ramsey's "CONDO
#: GARAGE", "CONDO STORAGE UNIT", "TOWNHOME - GARAGE ONLY" and "TOWNHOME -
#: NON-TAX OUTLOT", the "4BB NON-COMM CONDO STORAGE" class three counties use,
#: "Vacant Land - Residential" / "4B4 UNIMPROVED RESIDENTIAL LAND", Washington's
#: "Detached Structures Only", and the commercial, industrial ("INDUSTIAL" is
#: Anoka's spelling) and railroad classes. Church, exempt and tax-forfeit classes
#: are NOT here: "CHURCH-RESIDENTIAL" is a parsonage and a forfeited house is still
#: a house.
_NO_HOME_WORDS = ("GARAGE", "STORAGE", "COMMON AREA", "VACANT", "UNIMPROVED",
                  "DETACHED STRUCTURES ONLY", "NON-TAX OUTLOT", "COMMERCIAL",
                  "INDUSTRIAL", "INDUSTIAL", "RAILROAD")

#: Positive statements of one dwelling, for counties that leave ``NUM_UNITS``
#: empty or zero on a house.
_ONE_HOME_WORDS = ("SINGLE UNIT", "SINGLE FAMILY", "SINGLE-FAMILY", "S.FAM.RES")

#: Statements of more than one dwelling, which veto the floor area whatever the
#: unit count says.
_SEVERAL_HOMES_WORDS = ("TWO FAMILY", "TWO-FAMILY", "THREE FAMILY", "THREE-FAMILY",
                        "DUPLEX", "TRIPLEX", "APARTMENT", "DOUBLE BUNGALOW",
                        "ACCESSORY", "TWO RESIDENCES", "1-3 UNITS", "1 TO 3 UNITS",
                        "MULTIPLE", "4 OR MORE")


def _text(row: dict, *columns: str) -> str:
    return " ".join(" ".join(str(row.get(c) or "").split()).upper() for c in columns)


def _says_no_home(row: dict) -> bool:
    """Whether the class or dwelling type rules a dwelling out; see above."""
    text = _text(row, "USECLASS1", "DWELL_TYPE")
    return any(w in text for w in _NO_HOME_WORDS)


def _one_dwelling(row: dict) -> bool:
    """Whether the record positively says it is one dwelling; see the docstring."""
    text = _text(row, "USECLASS1", "DWELL_TYPE", "HOME_STYLE")
    if any(w in text for w in _SEVERAL_HOMES_WORDS):
        return False
    units = num(row.get("NUM_UNITS"))
    if units is not None and units >= 2:
        return False
    return units == 1 or any(w in text for w in _ONE_HOME_WORDS)


# --- addresses -------------------------------------------------------------------

#: Street types the standard spells out and the shared table does not know, in the
#: USPS Publication 28 abbreviation. Every key is a suffix type measured on the
#: layer's home records (Curve 4,190; Ridge 1,291; Point 1,104; Crossing 621 ...).
#: The Census matcher is not consistent about them — it returned "7201 LODGE POLE
#: PT" but "3762 WILDS RIDGE NW" and "1050 FALLS CURVE" in one verification run —
#: so the rewrite is applied to BOTH sides of the comparison (``_fold_types``),
#: at the type's position only. Types without a Publication 28 abbreviation
#: (Pass, Run, Bay, Alcove, Entry, Chase) stay as written.
_LOCAL_TYPES = {
    "curve": "curv", "ridge": "rdg", "point": "pt", "crossing": "xing",
    "hill": "hl", "knoll": "knl", "knolls": "knls", "bend": "bnd",
    "extension": "ext", "green": "grn", "crest": "crst", "gardens": "gdns",
    "view": "vw", "creek": "crk", "crossroad": "xrd", "glen": "gln",
    "hollow": "holw", "landing": "lndg", "heights": "hts", "beach": "bch",
    "shores": "shrs", "manor": "mnr", "vista": "vis", "bluff": "blf",
    "grove": "grv", "junction": "jct", "estate": "est", "route": "rte",
}

#: The one prefix type the matcher abbreviates: "15525 COUNTY ROAD 33" comes back
#: "15525 CO RD 33".
_PREFIX_TYPES = {"county road": "Co Rd"}

_DIRECTIONS = _shared.DIRECTIONS
_SPELLED = _shared.SPELLED_DIRECTIONS


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _type(word: str) -> str:
    """A suffix type in the form the comparison uses."""
    w = word.lower()
    return SUFFIXES.get(w) or _LOCAL_TYPES.get(w) or word


def _direction(word: str) -> str:
    """A directional field, abbreviated: "Northwest" → "NW".

    Only the standard's directional COLUMNS pass through here, so the word is a
    directional by the county's own statement and never a street's name. It has
    to be abbreviated before the shared comparison sees it: ``address_key``
    recognizes a trailing quadrant ("ST NW") only in its abbreviated form, so
    "14544 Crane Street Northwest" would otherwise keep "st" inside the name and
    never join the matcher's "14544 CRANE ST NW" — measured, 34 of 39 sampled
    Anoka homes.
    """
    return (_SPELLED.get(word.lower()) or word).upper()


def _street(row: dict) -> str | None:
    """The record's situs street address, reassembled from the standard's parts.

    None where there is no house number, or where the number carries a letter
    suffix (see "Addresses" in the module docstring). A "1/2" suffix is kept as
    its own token, which is how the matcher writes it.
    """
    number = num(row.get("ANUMBER"))
    if not number or number <= 0 or not float(number).is_integer():
        return None
    parts = [str(int(number))]
    suffix = _clean(row.get("ANUMBERSUF"))
    if suffix:
        if suffix != "1/2":
            return None
        parts.append(suffix)
    pre_dir, pos_dir = _clean(row.get("ST_PRE_DIR")), _clean(row.get("ST_POS_DIR"))
    pre_type = _clean(row.get("ST_PRE_TYP"))
    for value in (_clean(row.get("ST_PRE_MOD")),
                  _direction(pre_dir) if pre_dir else "",
                  pre_type,
                  _clean(row.get("ST_PRE_SEP")), _clean(row.get("ST_NAME"))):
        if value:
            parts.append(value)
    if _clean(row.get("ST_POS_TYP")):
        parts.append(_type(_clean(row.get("ST_POS_TYP"))))
    if pos_dir:
        parts.append(_direction(pos_dir))
    if _clean(row.get("ST_POS_MOD")):
        parts.append(_clean(row.get("ST_POS_MOD")))
    # Carver writes "COUNTY ROAD 33" into the name column rather than the prefix
    # type, so the prefix fold is applied to the whole reassembled street.
    street = _fold_prefix_types(" ".join(parts))
    return street if address_key(street) else None


def _fold_types(address: str) -> str:
    """The address's street part with a spelled-out type rewritten as the roll's
    reassembly writes it (``_LOCAL_TYPES``, ``_PREFIX_TYPES``); see above.

    Only the type's own position is touched — the last word, or the word before a
    trailing directional — so "Point Douglas Rd" keeps its name.
    """
    head, sep, tail = str(address or "").partition(",")
    tokens = head.split()
    i = len(tokens) - 1
    if i > 1 and (_SPELLED.get(tokens[i].lower()) or tokens[i].lower()) in _DIRECTIONS:
        i -= 1
    if i > 1 and tokens[i].lower() in _LOCAL_TYPES:
        tokens[i] = _LOCAL_TYPES[tokens[i].lower()]
    return _fold_prefix_types(" ".join(tokens)) + sep + tail


def _fold_prefix_types(text: str) -> str:
    """``text`` with "County Road" written "Co Rd", as the matcher writes it."""
    for long, short in _PREFIX_TYPES.items():
        text = re.sub(rf"(?i)(?<=\s){long}(?=\s)", short, text)
    return text


def _parts(address: str | None):
    """``(address_key without directionals, the directionals named)``, or None.

    Directionals are the abbreviated letters or their spelled forms anywhere in
    the street part. What is left must still parse — "100 N ST" (a street named
    N) leaves "100 ST", which does not, so a name made of a directional can never
    be compared this way.
    """
    head = _shared.strip_unit(address).split(",")[0]
    tokens = [t.strip(".").lower() for t in head.split() if t.strip(".")]
    if len(tokens) < 2 or not tokens[0].isdigit():
        return None
    named = {_SPELLED.get(t, t) for t in tokens[1:]} & _DIRECTIONS
    rest = [t for t in tokens[1:] if _SPELLED.get(t, t) not in _DIRECTIONS]
    key = address_key(" ".join([tokens[0], *rest]))
    return (key, frozenset(named)) if key else None


def _names_its_number(query: str, row: dict, street: str) -> bool:
    """Whether a numbered road's number appears in the query.

    ``address_key`` reads a digit-bearing word after a street type as a unit
    ("234 W STATION ST B12"), so "15525 CO RD 33" and "15525 CO RD 10" compare
    equal there — a shared rule that is right for a unit and wrong for a county
    road. So wherever the roll gives a prefix type (County Road, Highway), or the
    record's street ends that way (a trailing directional aside), the road's
    name must appear word for word in the query.
    """
    words = set(_shared.strip_unit(query).split(",")[0].lower().split())
    if _clean(row.get("ST_PRE_TYP")):
        if not all(w in words for w in _clean(row.get("ST_NAME")).lower().split()):
            return False
    tokens = [t.lower() for t in street.split()[1:]]
    while tokens and (_SPELLED.get(tokens[-1]) or tokens[-1]) in _DIRECTIONS:
        tokens.pop()
    if (len(tokens) >= 2 and tokens[-2] in SUFFIXES
            and any(c.isdigit() for c in tokens[-1])):
        return tokens[-1] in words
    return True


def _agrees(query: str | None, row: dict) -> bool:
    """Whether this record's address names the query's building.

    The shared comparison, after the type fold — or, where it fails only because
    the two sources put the SAME directionals in different places ("1478
    MINNEHAHA AVE W" in the roll, "1478 W MINNEHAHA AVE" from the matcher), the
    same address once the directionals are set aside, both sides naming exactly
    the same ones.

    A directional written on one side only never agrees, and neither do two
    that differ; see "Addresses" in the module docstring for why, and for what
    it costs.
    """
    street = _street(row)
    if not query or street is None or not _names_its_number(query, row, street):
        return False
    folded = _fold_types(query)
    if same_address(folded, street):
        return True
    q, r = _parts(folded), _parts(street)
    if q is None or r is None:
        return False
    (qk, qd), (rk, rd) = q, r
    if qk[0] != rk[0] or qk[1] != rk[1]:
        return False
    if not (qk[2] is None or rk[2] is None or qk[2] == rk[2]):
        return False
    return qd == rd


def _row_unit(row: dict) -> str | None:
    return _clean(row.get("SUB_ID1")) or None


def _norm_unit(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def _same_unit(a, b) -> bool:
    """Case and punctuation aside, the same unit. Leading zeros stay significant —
    unit 01 and unit 1 can both exist — the District's rule."""
    return bool(_norm_unit(a)) and _norm_unit(a) == _norm_unit(b)


# --- fetching and grouping -------------------------------------------------------


def _pid(row: dict) -> str | None:
    return _clean(row.get("COUNTY_PIN")) or None


def _polygon_key(row: dict):
    """What identifies this record's polygon; see "Condominiums and townhomes"."""
    area, length = row.get("Shape__Area"), row.get("Shape__Length")
    if area is None or length is None:
        return ("pin", _pid(row))
    return ("shape", repr(area), repr(length))


def _parcels(cfg: County, lat: float, lon: float, distance_m: float = 0,
             address: str | None = None, *, deadline: float) -> list[dict]:
    """One candidate per polygon, each carrying the records stacked on it.

    A record with no ``COUNTY_PIN`` is a polygon with no parcel behind it — Dakota
    ships 5,738, Carver 247 — and is dropped before the choice, the placeholder
    rule Florida set: it can only turn "ambiguous" into "one real parcel".

    Within a polygon carrying several records, records that rule a home out are
    set aside where anything else is left, and, with an address in hand, only
    records whose own address agrees are kept, unless none does — then the whole
    group stays, offers no address, and fails confirmation as it should.
    Polygons are never merged here, and are dropped only when a typed unit rules
    out every record on them, so the number of candidates the shared chooser
    counts is the number of distinct polygons that could be the reader's.
    """
    rows = _shared.arcgis_parcels(cfg.url, lat, lon, _FIELDS, distance_m,
                                  deadline=deadline, read_slice=READ_SLICE_S)
    groups: dict = {}
    for row in rows:
        if _pid(row) is None:
            continue
        groups.setdefault(_polygon_key(row), []).append(row)

    unit = unit_of(address)
    candidates = []
    for key, rows in groups.items():
        members = rows
        if len(rows) > 1:
            members = [r for r in rows if not _says_no_home(r)] or rows
        if unit:
            # A reader who typed a unit cannot live in a record that names a
            # DIFFERENT unit, and a polygon left with no record that could be
            # theirs is not a candidate. The units of a Blaine quadplex are four
            # polygons at one street address (12162 Waconia St NE, A-D), so
            # without this a typed "#C" faces four agreeing polygons and is
            # refused. It can only turn "ambiguous" into "one"; the address check
            # that follows is untouched (the shape select_parcel sanctions).
            members = [r for r in members
                       if not _row_unit(r) or _same_unit(unit, _row_unit(r))]
            if not members:
                continue
        if len(rows) > 1 and address:
            agreeing = [r for r in members if _agrees(address, r)]
            members = agreeing or members
        candidates.append({"key": key, "members": members, "all": rows})
    return candidates


def _address_for(query: str | None):
    """The address accessor ``select_parcel`` compares a candidate by.

    Where every record left on the candidate agrees with the query under
    ``_agrees``, the candidate is offered under the query's own spelling — the
    one comparison ``select_parcel`` can make. Otherwise it offers no address at
    all, rather than its own spelling: ``select_parcel`` would compare that with
    the shared rule alone, which is the comparison ``_agrees`` deliberately
    tightens (``_names_its_number``) — offered "15525 CO RD 33", a query for
    "15525 CO RD 10" would pass. ``select_parcel`` asks only when it holds an
    address.
    """
    def address_of(candidate: dict) -> str | None:
        members = candidate["members"]
        if not query or not members:
            return None
        return query if all(_agrees(query, r) for r in members) else None
    return address_of


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the metro county this point is in, from TIGERweb.

    Only for a caller that did not say: the registry passes the county it routed
    on to an adapter whose ``lookup`` accepts it, so in the product this request
    is never made.
    """
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "GEOID", "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    found = {str(((f or {}).get("attributes") or {}).get("GEOID") or "").strip()
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


def _candidate_at(lat: float, lon: float, address: str | None = None,
                  county_fips: str | None = None,
                  *, deadline: float | None = None) -> tuple[County, dict] | None:
    """The county and the polygon this point belongs to, chosen by the shared
    policy — see ``_shared.select_parcel`` for why the nearest parcel is never
    taken."""
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips not in COUNTY_FIPS:
        fips = _county_at(lat, lon, deadline=deadline)
        if fips is None:
            return None
    cfg = COUNTIES[fips]
    chosen = select_parcel(
        lambda d: _parcels(cfg, lat, lon, d, address, deadline=deadline),
        address, _address_for(address))
    return (cfg, chosen) if chosen is not None else None


# --- reading a record ------------------------------------------------------------


def _year(row: dict) -> int | None:
    year = num(row.get("YEAR_BUILT"))
    # 0 is the county's "not recorded", not the year zero.
    return int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None


_STORY_WORDS = {"one": 1, "two": 2, "three": 3, "1": 1, "2": 2, "3": 3}
#: Exactly a whole story count, optionally after a townhouse prefix and before a
#: construction or townhouse word; see "Stories and wall material".
_STORIES_RE = re.compile(
    r"^(?:(?:townhouse|detached townhome)\W+)?(one|two|three|1|2|3) story"
    r"(?: (?:frame|brick|townhouse|townhome))?$")
#: Carver's and Washington's wood-frame styles: the word ends the style, and is
#: not part of "A-Frame" or "Metal Post Frame".
_FRAME_RE = re.compile(r"(?<![-\w])(?<!post )frame$")


def _style(row: dict) -> str:
    return " ".join(str(row.get("HOME_STYLE") or "").split()).lower()


def _stories(row: dict, *, unit_matched: bool) -> int | None:
    """A whole story count off ``HOME_STYLE`` for a one-dwelling record, or None."""
    style = _style(row)
    if (not style or "condo" in style or not _one_dwelling(row)
            or not _speaks_for_the_reader(row, unit_matched)):
        return None
    if style == "rambler":
        return 1
    m = _STORIES_RE.match(style)
    return _STORY_WORDS[m.group(1)] if m else None


def _construction(row: dict) -> str | None:
    """``frame`` where the home style names wood-frame construction, else None."""
    style = _style(row)
    return "frame" if style and _FRAME_RE.search(style) else None


def _speaks_for_the_reader(row: dict, unit_matched: bool) -> bool:
    """Whether a one-dwelling record's own facts are the reader's home's.

    A record that names a unit describes that unit only. It is the reader's when
    the unit they typed matched it; otherwise — they typed another, or none — it
    may be a neighbor's. The units of one Blaine quadplex are four polygons at one
    street address, so a geocode that lands inside unit C's polygon confirms "the
    building" for a reader in unit A just as well, and unit C's area must not be
    reported as theirs. The year is the building's and survives.
    """
    return not _row_unit(row) or unit_matched


def _area(row: dict, *, unit_matched: bool) -> float | None:
    """``FIN_SQ_FT`` where it is one dwelling's area; see the module docstring."""
    area = num(row.get("FIN_SQ_FT"))
    if area is None or area <= 0 or not _one_dwelling(row):
        return None
    return area if _speaks_for_the_reader(row, unit_matched) else None


def _vintage(cfg: County, rows: list[dict]) -> str:
    """Dated from the records, which is the only honest date for a quarterly copy.

    Where the county sends them, ``MKT_YEAR`` (the assessment's valuation year)
    and ``TAX_YEAR`` (the year the tax is payable) — Dakota, Scott and Washington
    are on the 2026 assessment, Anoka and Ramsey still on 2025's. Carver and
    Hennepin send neither, so their records carry the date the county exported
    them to the region (``EXP_DATE``). Stated only where every record agrees.
    """
    years = {(num(r.get("MKT_YEAR")), num(r.get("TAX_YEAR"))) for r in rows}
    if len(years) == 1:
        market, tax = years.pop()
        if market and tax and 1900 <= market <= 2100 and 1900 <= tax <= 2100:
            return (f"{DATA_VINTAGE}, {cfg.name} County {int(market)} assessment "
                    f"(taxes payable {int(tax)})")
    dates = set()
    for r in rows:
        ms = num(r.get("EXP_DATE"))
        if ms:
            dates.add(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
    if len(dates) == 1:
        return f"{DATA_VINTAGE}, {cfg.name} County export of {dates.pop().isoformat()}"
    return f"{DATA_VINTAGE}, {cfg.name} County"


def _source(cfg: County) -> str:
    return (f"{cfg.name} County assessor via the MetroGIS Regional Parcel Dataset "
            f"(Metropolitan Council), keyless")


def _row_record(cfg: County, row: dict, *, unit_matched: bool) -> AssessorRecord | None:
    if _says_no_home(row):
        return None
    year_built = _year(row)
    sqft = _area(row, unit_matched=unit_matched)
    stories = _stories(row, unit_matched=unit_matched)
    construction = _construction(row)
    if all(v is None for v in (year_built, sqft, stories, construction)):
        return None
    return AssessorRecord(
        source=_source(cfg),
        data_vintage=_vintage(cfg, [row]),
        parcel_id=_pid(row),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        construction=construction,
        # BASEMENT is presence only and the standard has no condition grade.
    )


def _building_record(cfg: County, candidate: dict) -> AssessorRecord | None:
    """The polygon's year, when every record left on it agrees, and nothing else.

    No parcel id: several parcels share the polygon and none was singled out.
    """
    members = [r for r in candidate["members"] if not _says_no_home(r)]
    if not members:
        return None
    years = {_year(r) for r in members}
    if len(years) != 1 or None in years:
        return None
    return AssessorRecord(
        source=_source(cfg),
        data_vintage=_vintage(cfg, members),
        year_built=years.pop(),
    )


def _resolve(cfg: County, candidate: dict, address: str | None) -> AssessorRecord | None:
    """Which record on the chosen polygon is the reader's home."""
    members = candidate["members"]
    unit = unit_of(address)
    if len(members) == 1:
        row = members[0]
        return _row_record(cfg, row,
                           unit_matched=bool(unit) and _same_unit(unit, _row_unit(row)))
    if unit:
        hits = [r for r in members if _same_unit(unit, _row_unit(r))]
        if len(hits) == 1:
            return _row_record(cfg, hits[0], unit_matched=True)
    return _building_record(cfg, candidate)


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    found = _candidate_at(lat, lon, address, county_fips)
    if not found:
        return None
    cfg, candidate = found
    return _resolve(cfg, candidate, address)


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the right publisher. All seven are one host."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the metro county assessor says is standing at this point, or None.

    ``address`` is the geocoder's matched address, carrying the reader's unit
    where they typed one (``_shared.with_unit``). It confirms the parcel, and the
    unit picks the record on a stacked condominium polygon. ``county_fips`` is the
    county the registry routed on; without it the county is looked up from the
    point (one extra request).

    Fails open on everything — a timeout, a 500, a truncated response, a renamed
    column, a parcel with no record.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Minnesota assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
