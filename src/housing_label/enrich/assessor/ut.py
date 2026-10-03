#!/usr/bin/env python3
"""Utah — 28 of the state's 29 counties, from UGRC's per-county LIR parcel layers.

A statewide adapter in the sense Florida's and Connecticut's are, though
"statewide" is doing more work here. Utah's 29 county assessors each
send their year-end tax roll to the Utah Geospatial Resource Center (UGRC), which
joins it to the county's parcel map and publishes it as a Land Information Records
(LIR) layer — one per county, all from one template, all in one keyless ArcGIS
Online organisation:

  ``services1.arcgis.com/99lidPhWCzftIe9K/.../Parcels_<County>_LIR/FeatureServer/0``

The organisation's services directory holds exactly 29 such services, one per
county (``COUNTY_SERVICES``). About 1.04 million parcels carry a year built.

Twenty-eight are claimed, not 29. **Juab** publishes a layer whose 15,259 rows
carry no year built and no wall material at all, and whose floor areas come with
no evidence that they describe one home; a lookup there could only spend part of
the label's budget to return nothing, so 49023 is left out of ``COUNTY_FIPS``
(``_NOTHING_TO_SAY``) until its rows start carrying ``BUILT_YR``.

Three words this file leans on:

* **LIR** — "Land Information Records", the 2016 state work group's name for a
  tax-year parcel layer carrying assessor attributes beside the boundary.
* **residential card** — the appraiser's record of one dwelling building, as
  opposed to the record of a shed, garage, barn or commercial structure.
* **grid address** — Utah numbers its streets as coordinates: "325 E 300 N" is
  325 units east on the street 300 units north of the city's origin.

One request per county, and one to find the county
--------------------------------------------------
Like Florida, each layer carries the parcel shape and the assessor's facts on one
record, so the lookup is a point query. Unlike Florida there are 29 layers, and the
registry hands an adapter a coordinate and an address but not the county it routed
on. So ``lookup`` accepts an optional ``county_fips`` and, without one, asks UGRC's
own 29-polygon county boundaries layer first (``COUNTY_URL``, median 0.12 s). If the
registry ever passes the county it already knows, that request disappears.

One row per building, not per parcel
------------------------------------
This is the fact everything else follows from. 1.85 million rows describe 1.47
million parcels: a house with two sheds and a detached garage is four rows under
one coordinate, each with its own year, area and wall type. 924 E 100 N in Provo is
a 1920 house, two 1920 sheds and a 1996 garage. Weber has one parcel with 527 rows.

Two consequences:

* **The rows are grouped by ``PARCEL_ID`` before the parcel is chosen.** Offered
  raw, four rows of one parcel are four candidates, which ``select_parcel``
  correctly calls ambiguous — and the most ordinary house in the state is refused.
  Grouping is the sanctioned shape (see ``select_parcel``): rows sharing an id are
  one tax parcel, so it can only turn "ambiguous" into "one". A group whose rows
  disagree about the parcel's own address or class is a broken join and is not
  offered at all. Identical building rows are one building repeated per polygon
  part of a multipart parcel, and are collapsed.
* **The home has to be picked out of the buildings** (``_the_dwelling``), and
  getting it wrong reports the garage's year as observed fact. The twenty counties
  on the common CAMA system write a residential card's wall as
  ``"<structure>: <cladding>"`` — "Frame:  Metal Vinyl Siding", "Masonry:  Common
  Brick", "2 X 4: Lap Siding" for a manufactured home — and every other building
  with a bare construction class ("Wood Framed", "Steel Framed", "Pole Framed").
  Measured in Utah County, which also publishes each building's style: every
  "one_story", "two_story", "split_level", "duplex", townhouse and cabin carries
  the colon form; every "shed:_wood", "detached" garage, barn, carport, office and
  warehouse carries a bare class. So the home is the parcel's ONE residential card;
  two (a house and a second dwelling) or none (sheds only) is refused. Where a
  county writes no such vocabulary — Salt Lake's codes, Washington's, the counties
  with no material — the parcel must hold exactly one building; measured where
  those counties list a second, it is a second house (235 E Hubbard Ave, Salt Lake:
  a 1918 brick house and a 2021 frame cottage), not a shed.

The column that is not what it says
-----------------------------------
``HOUSE_CNT`` is "Number of Housing Units" in UGRC's schema. In every county that
fills it, it counts the parcel's BUILDING ROWS: the Provo house above reads 4, a
house with a shed reads 2, and a duplex and every condominium unit read 1 (sampled
in Salt Lake, Weber, Washington, Davis, Cache and Utah County). It cannot carry the
one-dwelling rule, and it is not requested, so a later edit cannot read it as one.

The one-dwelling rule, and the condo trap
-----------------------------------------
The label's ``sqft`` and ``stories`` mean one home. Salt Lake writes the TOWER's
floor count onto each condominium unit — 27 for every unit of 48 W 300 S, 30 for
99 W South Temple — and a duplex's floor area is both homes. With ``HOUSE_CNT``
unusable, only two things in the layer positively say "one home":

* Utah County's building style (it writes the style into ``BLDG_SQFT_INFO``):
  one/two-storey, split level, bi-level, townhouse end/interior unit, cabin,
  manufactured section — and not "duplex", "triplex", "fourplex", "<n>_unit_building"
  or "multiple_residence".
* Carbon County's ``PROP_CLASS`` of "Single Family".

So area and storeys are reported only with that evidence, only where the roll's
own address carries no unit designator ("# 1706N", "UNIT 301", "APT 2"), and only
on a parcel whose class does not say it is not a home. Everywhere else the year
and the wall type still come through — the building went up when it went up — and
the area and storeys are left to the label's model. That is a deliberate coverage
cost: "Residential" in the other counties covers duplexes, and nothing in their
rows can tell one from a house. It was checked rather than assumed: in Utah County
the duplexes, triplexes and fourplexes are classed "Unknown", which would have made
the class look like a usable proxy if only that county had been examined; it is a
fact about one county's coding, not about the layer.

Storeys are read only where Utah County's style and ``FLOORS_CNT`` agree: it records
7,123 "one_story" buildings with ``FLOORS_CNT`` of 2 against 63,615 with 1. Split
levels and bi-levels have no whole-number reading (Cook's call for "Split Level").
A condominium unit, stacked with its neighbours on one footprint, is refused by
``select_parcel`` as ambiguous; a reader who typed the unit is matched to that
unit's own parcel (``fetch`` drops parcels naming a DIFFERENT unit), and gets the
building's year with the unit's area still refused.

The year built
--------------
``BUILT_YR``, the actual year. ``EFFBUILT_YR`` is moved forward when a property is
improved — 3913 S 2200 W's 1946 house reads 1992 — so it describes condition, and
is not requested. 0 is "not recorded". The zero-dwelling refusal is ``PROP_CLASS``:
the layer's only statement about whether anyone lives there. An explicit
"Commercial", "Vacant", "Tax Exempt", "Industrial", "Land" or "Centrally Assessed"
refuses the year; "Unknown", a blank, "Greenbelt", "Agricultural", "Mixed Use",
"Commercial - Apartment & Condo" and a mobile home filed as personal property do
not — Utah County files its whole multi-unit stock as "Unknown" (117,386 rows), and
a farmhouse stands on a greenbelt parcel. Refusing on silence is the error
Florida's dwelling count was written to avoid.

Construction, and the code table that does not exist
----------------------------------------------------
UGRC's schema defines ``CONST_MATERIAL`` only as "Construction Material Types,
Values for this field are expected to vary greatly by county" (Expanded Parcel Data
Sharing Implementation Guidelines, 2016, linked from
https://gis.utah.gov/products/sgid/cadastre/parcels/). There is no statewide code
table, and four vocabularies are in use: the common CAMA system's colon form,
Washington and Box Elder's "Frame Syn Plaster" form, Wasatch's single "Wood Frame"
for every building it has, and Salt Lake's two-letter codes. ``_CONSTRUCTION``
translates only wordings that name their own structure; the comment beneath it
lists every dropped value and why — masonry veneer (brick OR stone face), log,
manufactured-home walls, cast concrete.

Salt Lake's codes (SO, BR, AL, FR, SC, BL, CN, MT, AS, ML, …) are all left
unmapped. The only table the county publishes is the Assessor's commercial-record
field descriptions (https://apps.saltlakecounty.gov/assessor/new/FieldDescriptions/
commercialRecord.html: AB, FR, BR, ST, AL, ML, MG, CN, BL, CU, SO, OT), and the
residential rows carry four codes it does not list — SC, MT, AS, CP — so it is not
the table those rows were written against. Its "BR - Brick" would not separate solid
brick from brick veneer even if it were.

Addresses, and the geocoder that cannot read the grid
-----------------------------------------------------
``PARCEL_ADD`` is the street address alone ("3854 S 800 W"), with the city in its
own column, so no locality trim is needed. Two Utah spellings are reconciled on
both sides of the comparison (``_grid_form``): "175 E 100 SOUTH ST" from the Census
matcher is the roll's "175 E 100 S", and "COUNTRY CREEK COVE" is the roll's
"COUNTRY CREEK CV".

The commonest mismatch measured is NOT reconciled here: Census returns "1526
DOWNINGTON AVE" for a roll's "1526 E DOWNINGTON AVE", dropping the leading
directional — 60 of 277 sampled homes, before the shared fix below. The adapter
must not forgive it, because the matcher ignores that directional outright: typed
"571 N 200 W" and "571 S 200 W" come back as the same point, 0 m apart, on all 12
addresses tried. The point cannot say which twin is meant, and accepting the
directionless form would confirm whichever twin happens to be near. What does
recover those homes is ``location.assessor_address``, which now hands an adapter
the reader's own typed address whenever the matched street name differs from it:
"1526 E DOWNINGTON AVE" then agrees with exactly one roll address, and the twin on
the other side of the grid does not.

The same blindness produced the one wrong parcel the first end-to-end run found,
before that shared change. Typed "325 E 300 N, Kanab", the matcher returned "325 N
300 E": a different, real house 45 m from the point, with the reader's house 55 m
away, and the adapter, handed only the matched address, confirmed it. So after a
parcel is chosen, the 80 m neighbourhood is checked for a *confusable twin* —
another parcel with the same house number and street once directionals are set
aside, order and side included (``_has_a_confusable_twin``) — and its presence
refuses the answer. It is kept even though the shared change now catches that
case upstream, because an adapter is not always handed the typed address (a label
scored from coordinates has only the matched one), and it is cheap: one extra
request on lookups that containment answered, and in the final run one refusal
of 277 — Kanab itself, where the typed address would now have confirmed the right
house. It cannot catch a swap whose twin is more than 80 m away.

Timing
------
Measured over 277 real rooftops drawn at random from the layers themselves, spread
across 26 counties in proportion to their residential parcels, through the
product's own HTTP session:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which county is this dot in?"       0.12 s  0.13 s  0.14 s  0.21 s
  "which parcel is this dot inside?"   0.13 s  0.15 s  0.16 s  0.52 s
  "what is within 80 m of this dot?"   0.14 s  0.18 s  0.22 s  0.61 s
  ==================================  ======  ======  ======  ======

A cold connection, TLS handshake included, took 0.47–0.73 s (26 layers, one fresh
session each) — and the connect half of the timeout has the whole budget anyway.
The responses are 4–25 KB. So Utah keeps the SHARED clock: a one-second read slice
none of the 831 requests came near, and a four-second budget against a worst
observed lookup of three requests summing to 1.4 s. ``READ_SLICE_S`` and
``LOOKUP_TIMEOUT`` are named only so every request visibly passes them; a test pins
their sum under ``config.UPSTREAM_HOST_BUDGET``. End to end, a lookup took a median
of 0.40 s (p95 0.52 s, slowest 1.15 s), county request included.

What the adapter is worth, end to end
-------------------------------------
277 homes drawn at random from the layers themselves (residential class, a
recorded year), in proportion to each county's residential rows, geocoded through
the Census matcher and ``assessor_address`` exactly as the product does, then
looked up with no county passed:

  =====================================  =====
  sampled                                  277
  geocoded                                 254   (23 unknown to Census)
  routed to the sampled county             248   (6 city-less addresses that
                                                  Census placed elsewhere)
  resolved                                 210   (83% of those geocoded)
  **matched to the wrong parcel**          **0**
  year built = the dwelling's year     210/210
  floor area reported / exact            28/28
  storeys reported                          22
  wall type translated                      94
  =====================================  =====

"The dwelling's year" was adjudicated, not assumed: against a naive truth — the
year of the parcel's LARGEST building — 205 of 210 agree, and in each of the five
that do not, the larger building is a garage or shop (one is style-confirmed as
"detached" in Utah County) while the adapter took the sole residential card. Two
of the 28 floor areas differ from that naive truth for the same reason.

The 44 that did not resolve: 28 geocodes more than 80 m from their parcel or at a
different address; 7 condominium stacks with no unit typed, refused as ambiguous
by design; 3 parcels with no single dwelling building; 3 transient upstream errors
(a 503 or a read timeout during the run — each resolved on re-query, and none is
cached); 1 refused by the confusable-twin guard; and 2 spellings the shared
comparison does not fold ("SAINT"/"ST", "SECOND"/"2ND").

Privacy, and why the field list is short
----------------------------------------
The LIR layers carry no owner name or mailing address — the 2016 recommendations
kept them out — but they do carry ``TOTAL_MKT_VALUE``, ``LAND_MKT_VALUE``,
``TAXEXEMPT_TYPE``, ``PRIMARY_RES`` (whether the owner lives there) and
``SERIAL_NUM``. None is an input to the label. Nine columns are requested by name;
the shared helper refuses ``*``. Nothing from this source is written into the
repository.

Licence
-------
UGRC's dataset page (https://gis.utah.gov/products/sgid/cadastre/parcels/) states:
"There are no constraints or warranties with regard to the use of this dataset.
Users are encouraged to attribute content to: State of Utah, SGID." Each row's
``DISCLAIMER`` points to https://www.utah.gov/support/disclaimer.html, which
provides the State's information "as is", without warranty, and the 2016 guidelines
add a no-liability release. Nothing restricts querying, caching or commercial use;
``ATTRIBUTION`` carries the requested credit. The posture is the one every adapter
takes regardless — query live, cache in process, bundle nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

_ORG = "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services"

#: County FIPS → the UGRC service holding that county's LIR parcels. Read off the
#: organisation's services directory, where exactly these 29 ``Parcels_*_LIR``
#: services exist — one per Utah county, so no county is missing. Utah's county
#: codes are the odd numbers 49001–49057 in alphabetical order, which is also the
#: order of UGRC's own ``COUNTY_ID`` (Beaver = 1 … Weber = 29), so the table can be
#: checked against two independent orderings; a test does both.
COUNTY_SERVICES = {
    "49001": "Parcels_Beaver_LIR",
    "49003": "Parcels_BoxElder_LIR",
    "49005": "Parcels_Cache_LIR",
    "49007": "Parcels_Carbon_LIR",
    "49009": "Parcels_Daggett_LIR",
    "49011": "Parcels_Davis_LIR",
    "49013": "Parcels_Duchesne_LIR",
    "49015": "Parcels_Emery_LIR",
    "49017": "Parcels_Garfield_LIR",
    "49019": "Parcels_Grand_LIR",
    "49021": "Parcels_Iron_LIR",
    "49023": "Parcels_Juab_LIR",
    "49025": "Parcels_Kane_LIR",
    "49027": "Parcels_Millard_LIR",
    "49029": "Parcels_Morgan_LIR",
    "49031": "Parcels_Piute_LIR",
    "49033": "Parcels_Rich_LIR",
    "49035": "Parcels_SaltLake_LIR",
    "49037": "Parcels_SanJuan_LIR",
    "49039": "Parcels_Sanpete_LIR",
    "49041": "Parcels_Sevier_LIR",
    "49043": "Parcels_Summit_LIR",
    "49045": "Parcels_Tooele_LIR",
    "49047": "Parcels_Uintah_LIR",
    "49049": "Parcels_Utah_LIR",
    "49051": "Parcels_Wasatch_LIR",
    "49053": "Parcels_Washington_LIR",
    "49055": "Parcels_Wayne_LIR",
    "49057": "Parcels_Weber_LIR",
}
#: Counties whose layer exists but carries nothing this adapter could report.
#: Juab's 15,259 rows have no year built and no wall material at all, and its
#: floor areas come with no one-dwelling evidence — so a lookup there could only
#: spend a second of the label's budget to return nothing. Measured 2026-10-03;
#: drop it from this set the day Juab's rows start carrying BUILT_YR.
_NOTHING_TO_SAY = frozenset({"49023"})
COUNTY_FIPS = frozenset(COUNTY_SERVICES) - _NOTHING_TO_SAY

NAME = "Utah Geospatial Resource Center"
ATTRIBUTION = ("Utah county assessors via UGRC Land Information Records parcels "
               "(State of Utah, SGID; keyless)")
DATA_VINTAGE = "UGRC LIR parcels (county tax-roll attributes)"

#: A template, not a URL: ``{service}`` is the county's entry in COUNTY_SERVICES.
PARCEL_URL = _ORG + "/{service}/FeatureServer/0/query"
#: UGRC's county boundaries, used only when the caller did not say which county
#: the point is in. See ``_county_at``.
COUNTY_URL = _ORG + "/UtahCountyBoundaries/FeatureServer/0/query"

#: How long the service may go quiet before the silence is a stall, and the budget
#: for a whole Utah lookup. Both are the SHARED defaults, kept on purpose and named
#: here only so every request visibly passes them: measured over 277 random homes
#: (see "Timing" in the module docstring) the slowest of all 831 requests took
#: 0.61 s, and the slowest county + containment + buffer triple 1.4 s, so neither
#: Florida's nor Connecticut's longer clock is warranted. Raising them would only
#: let a genuinely hung portal hold the label longer.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

# Only what the label scores, plus what decides which building is the home and
# whether its area describes one dwelling. EFFBUILT_YR (effective year), HOUSE_CNT
# (a building count despite its name — see the module docstring), PRIMARY_RES
# (owner-occupancy) and every market value are deliberately absent.
_FIELDS = ("PARCEL_ID,PARCEL_ADD,PROP_CLASS,BUILT_YR,BLDG_SQFT,BLDG_SQFT_INFO,"
           "FLOORS_CNT,CONST_MATERIAL,CURRENT_ASOF")

# The columns that describe one BUILDING, as opposed to the parcel. Two rows of
# one parcel that agree on all of them are the same building repeated — once per
# polygon part of a multipart parcel — not two buildings.
_BUILDING_COLUMNS = ("BUILT_YR", "BLDG_SQFT", "BLDG_SQFT_INFO", "FLOORS_CNT",
                     "CONST_MATERIAL")


def _norm(value) -> str:
    """Case- and whitespace-insensitive form of a county's free-text category."""
    return " ".join(str(value or "").split()).lower()


# ── which building is the home ─────────────────────────────────────────────────

# The building vocabulary shared by the 20 counties on the common CAMA system
# (Beaver, Cache, Carbon, Daggett, Duchesne, Emery, Garfield, Grand, Iron, Kane,
# Millard, Morgan, Piute, Sanpete, Sevier, Tooele, Uintah, Utah, Wayne, Weber).
# A RESIDENTIAL building card carries an exterior-wall type written
# "<structure>: <cladding>" — "Frame:  Metal Vinyl Siding", "Masonry:  Common
# Brick", and for manufactured homes "2 X 4: Lap Siding". Every other building on a
# parcel carries a bare construction class instead.
#
# Measured in Utah County, the one county that also publishes each building's
# style (in BLDG_SQFT_INFO): every "one_story", "two_story", "split_level",
# "duplex", townhouse and cabin card carries the colon form; every "shed:_wood",
# "detached" (garage), barn, carport, office and warehouse carries a bare class.
_RESIDENTIAL_CARD_PREFIXES = ("frame:", "masonry:", "2 x 4:", "2 x 6:",
                              "wood stresskin panels:")
_NON_DWELLING_CLASSES = frozenset({
    "wood framed", "wood", "steel framed", "steel", "pole framed", "hoop",
    "structural steel", "aluminum", "concrete column-beam", "masonry",
    "wood framed, veneer", "wood slant wall",
})


def _is_residential_card(building: dict) -> bool:
    return _norm(building.get("CONST_MATERIAL")).startswith(_RESIDENTIAL_CARD_PREFIXES)


def _is_non_dwelling_class(building: dict) -> bool:
    return _norm(building.get("CONST_MATERIAL")) in _NON_DWELLING_CLASSES


def _the_dwelling(buildings: list[dict]) -> dict | None:
    """The one building on this parcel that is the home, or None.

    The layer has one row per BUILDING, not per parcel, so a house with a shed and
    a detached garage is three rows. Which of them is the home decides the year
    built, and getting it wrong reports the shed's year as observed fact.

    * Where the county writes residential cards, exactly one must be present: two
      is a house with a second dwelling (an accessory apartment, a cottage), and
      naming either would be a guess; none means the parcel's buildings are all
      sheds, garages or commercial structures as far as the roll says.
    * Elsewhere — Salt Lake's two-letter codes, Washington's vocabulary, the six
      counties that publish no material at all — the parcel must hold exactly one
      building. Measured where those counties do list a second one, it is a second
      house (Salt Lake: a 1918 brick house beside a 2021 frame cottage), not a shed.
    """
    cards = [b for b in buildings if _is_residential_card(b)]
    if cards:
        return cards[0] if len(cards) == 1 else None
    if len(buildings) == 1 and not _is_non_dwelling_class(buildings[0]):
        return buildings[0]
    return None


# ── the parcel-level statements ────────────────────────────────────────────────

# PROP_CLASS values that state the parcel is not anybody's home. A denylist, not
# an allowlist, for the reason Florida's dwelling count is read as it is: an
# explicit "Vacant" or "Commercial - Retail" is the county saying no one lives
# here, while "Unknown", a blank, "Greenbelt" or "Agricultural" says nothing of
# the kind — a farmhouse sits on a greenbelt parcel — and refusing on silence
# would cost Utah County 117,386 "Unknown" rows, its whole multi-unit stock.
_NOT_A_HOME_PREFIXES = ("vacant", "tax exempt", "exempt", "industrial",
                        "centrally assessed", "undeveloped")


def _says_no_home(prop_class) -> bool:
    """Whether PROP_CLASS explicitly says no dwelling stands on this parcel."""
    pc = _norm(prop_class)
    if not pc:
        return False
    if pc.startswith(_NOT_A_HOME_PREFIXES) or pc == "land":
        return True
    # "Commercial - Apartment & Condo" is housing, and so is a mobile home filed as
    # personal property; every other commercial or personal-property class is not.
    if pc.startswith("commercial") and "apartment" not in pc:
        return True
    return pc.startswith("personal property") and "mobile home" not in pc


# Building styles that are one dwelling, as Utah County writes them into
# BLDG_SQFT_INFO. The townhouse styles ("end:", "int:") are one unit on its own
# parcel. Deliberately absent: "duplex", "triplex", "fourplex:_two_story",
# "<n>_unit_building", "multiple_residence" — each is a building with more than
# one home in it, and its floor area is all of them.
_ONE_DWELLING_STYLES = frozenset({
    "one_story", "two_story", "split_level", "bi-level", "one_and_one_half",
    "two_and_one_half", "a-frame", "basement_home", "cabin",
    "end:_one_story", "end:_two_story", "end:_split_level",
    "int:_one_story", "int:_two_story", "int:_split_level",
})
_MANUFACTURED_STYLE_PREFIXES = ("one-section_", "two-section_", "three-section_")

# Stories are read only where the style and FLOORS_CNT agree. Utah County records
# 7,123 "one_story" buildings with FLOORS_CNT of 2 against 63,615 with 1, so
# either column alone is wrong often enough to matter. Split levels, bi-levels and
# half storeys have no whole-number reading — the call Cook makes for "Split
# Level" and "1.5 Story".
_STYLE_STORIES = {
    "one_story": 1, "end:_one_story": 1, "int:_one_story": 1,
    "two_story": 2, "end:_two_story": 2, "int:_two_story": 2,
}


def _one_dwelling_evidence(parcel: dict, building: dict) -> bool:
    """Whether the roll positively says this building is ONE home.

    Two sources say so, and nothing else in the layer does:

    * Utah County's building style (BLDG_SQFT_INFO), and
    * Carbon County's PROP_CLASS "Single Family".

    ``HOUSE_CNT`` — "Number of Housing Units" in the schema — is NOT such a source:
    measured in every county that fills it, it counts the parcel's building rows.
    A house with a shed reads 2; a duplex reads 1. See the module docstring.
    """
    style = _norm(building.get("BLDG_SQFT_INFO"))
    if style in _ONE_DWELLING_STYLES or style.startswith(_MANUFACTURED_STYLE_PREFIXES):
        return True
    return _norm(parcel.get("PROP_CLASS")) == "single family"


def _is_one_home(parcel: dict, building: dict) -> bool:
    """Whether the building's area and storey count describe the reader's home."""
    return (_one_dwelling_evidence(parcel, building)
            and not unit_of(parcel.get("PARCEL_ADD"))
            and not _says_no_home(parcel.get("PROP_CLASS")))


def _area(parcel: dict, building: dict) -> float | None:
    area = num(building.get("BLDG_SQFT"))
    if area is None or area <= 0 or not _is_one_home(parcel, building):
        return None
    return area


def _stories(parcel: dict, building: dict) -> int | None:
    if not _is_one_home(parcel, building):
        return None
    floors = num(building.get("FLOORS_CNT"))
    if floors is None or floors <= 0 or not float(floors).is_integer():
        return None
    style = _norm(building.get("BLDG_SQFT_INFO"))
    if style:
        # A style is published: it and the floor count must agree, and a style
        # with no whole-number reading (split level, bi-level) yields nothing.
        return int(floors) if _STYLE_STORIES.get(style) == int(floors) else None
    return int(floors)


# ── construction ───────────────────────────────────────────────────────────────

# County wording → the label's vocabulary, keyed on the normalised string. The
# UGRC schema says only that values "are expected to vary greatly by county", and
# publishes no code table (gis.utah.gov/products/sgid/cadastre/parcels/, and the
# LIR Implementation Guidelines linked there), so every entry is a wording that
# names its own structure. Anything absent is dropped; see the comment below.
_CONSTRUCTION = {
    # The common CAMA vocabulary: "<structure>: <cladding>".
    "frame: metal vinyl siding": "frame",       # metal OR vinyl: frame either way
    "frame: stucco or cement fiber siding": "frame",
    "frame: synth plaster (eifs)": "frame",
    "frame: wood siding": "frame",
    "frame: plywood hardboard": "frame",
    "frame: wood shingles or shake": "frame",
    "frame: brick veneer": "brick-frame",
    "masonry: common brick": "brick",
    "masonry: concrete block": "block",
    "masonry: stucco on block": "block",
    # Washington and Box Elder: "<structure> <cladding>", no colon.
    "frame syn plaster": "frame",
    "frame stucco": "frame",
    "frame siding": "frame",
    "frame hardboard": "frame",
    "frame aluminum": "frame",
    "frame plywood": "frame",
    "frame shingle": "frame",
    "frame vinyl": "vinyl",
    "frame brick veneer": "brick-frame",
    "masonry common brick": "brick",
    "masonry face brick": "brick",
    "masonry concrete block": "block",
    "masonry stucco block": "block",
    "masonry stone": "stone",
}
# Deliberately unmapped, each for a reason rather than by omission:
#
#   Frame: Masonry Veneer,      a framed wall with a brick OR stone face. The
#   Frame Masonry Veneer        label has brick-frame and no stone-frame, so the
#                               face material is a guess (DC's "Stone Veneer" call)
#   Frame: Stone Veneer         no stone-frame value; `stone` asserts solid masonry
#   Masonry: Face Brick Or      brick or stone, and the two are different values
#     Stone
#   Masonry: Poured Concrete,   cast concrete is not concrete block, the only
#     8" / 6" Concrete          concrete value the label has
#   Frame: Rustic Log, log      no log value in the label's vocabulary
#     diameters, Pine cabins,
#     Log, Finished Cottage
#   Frame: Other                the structure is named, the cladding is not, and
#                               the label's frame/vinyl/brick-frame split is the
#                               cladding
#   2 X 4: / 2 X 6: / Wood      manufactured-home walls. Stud-framed, but `frame`
#     Stresskin Panels: …       would score a manufactured home as a site-built
#                               frame house; the label has no manufactured value
#   Hardboard Sheet, Lap        Washington's walls with no structure named
#     Siding, Metal Siding,
#     Ribbed Aluminum, Cement
#     Fiber Sheet, Stucco
#   Wood Frame (Wasatch)        the county's single value for every building it
#                               has, so it is a default rather than an observation
#   Salt Lake's two-letter      the only published table (the Assessor's
#     codes (SO, BR, AL, …)     commercial-record field descriptions) lacks four of
#                               the codes residential rows carry — SC, MT, AS, CP —
#                               so it is not the table these rows were written
#                               against; and its BR ("Brick") would not say solid
#                               brick from brick veneer even if it were
#   the bare classes (Wood      the construction class of a shed, garage or
#     Framed, Steel Framed, …)  commercial building, never of a residential card


def _construction(building: dict) -> str | None:
    return _CONSTRUCTION.get(_norm(building.get("CONST_MATERIAL")))


# ── the parcel ─────────────────────────────────────────────────────────────────


def _parcel_id(row: dict) -> str | None:
    pid = str(row.get("PARCEL_ID") or "").strip()
    return pid or None


def _parcel_of(pid: str, rows: list[dict]) -> dict | None:
    """One candidate parcel from all the building rows that carry its id, or None.

    Each row repeats the parcel's own fields (address, class, vintage) beside one
    building's. A parcel whose rows disagree about the parcel-level facts — two
    different street addresses, two different property classes — is a join the
    roll got wrong somewhere, and confirming it against an address it may not have
    is the wrong-house failure Connecticut's contradictory rows taught; so it is
    not offered at all.
    """
    keys = {address_key(r.get("PARCEL_ADD")) for r in rows}
    keys.discard(None)
    classes = {_norm(r.get("PROP_CLASS")) for r in rows}
    if len(keys) > 1 or len(classes) > 1:
        return None
    address = next((r.get("PARCEL_ADD") for r in rows
                    if address_key(r.get("PARCEL_ADD"))), None)
    buildings, seen = [], set()
    for r in rows:
        key = tuple(r.get(c) for c in _BUILDING_COLUMNS)
        if key not in seen:
            seen.add(key)
            buildings.append({c: r.get(c) for c in _BUILDING_COLUMNS})
    asof = [v for v in (num(r.get("CURRENT_ASOF")) for r in rows) if v]
    return {"PARCEL_ID": pid, "PARCEL_ADD": address,
            "PROP_CLASS": rows[0].get("PROP_CLASS"),
            "CURRENT_ASOF": max(asof) if asof else None,
            "buildings": buildings}


def _parcels(url: str, lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Candidate parcels at (or within ``distance_m`` of) a point.

    Rows are grouped by PARCEL_ID before the parcel is chosen. Without it a house
    with a shed is two rows under one coordinate, which ``select_parcel``
    correctly calls ambiguous — and refuses the most ordinary house in the state.
    Grouping is the sanctioned shape for this, the same as dropping a placeholder
    (see ``select_parcel``): it can only turn "ambiguous" into "one real parcel",
    since rows carrying one PARCEL_ID are one tax parcel, and the address check
    that follows is untouched. Rows with no id are records of nothing and dropped.
    """
    by_id: dict[str, list[dict]] = {}
    # The shared helper refuses a truncated page (``exceededTransferLimit``) by
    # raising ``_shared.TruncatedResponse``. That matters more here than for most
    # layers: rows are per building per polygon part, the cap is 2,000, and Weber
    # has one parcel with 527 building rows — so a dense 80 m buffer can be cut
    # short, and a cut-short list that drops the second of two parcels sharing an
    # address would make the survivor look unique.
    rows = _shared.arcgis_parcels(url, lat, lon, _FIELDS, distance_m,
                                  deadline=deadline, read_slice=READ_SLICE_S)
    for row in rows:
        pid = _parcel_id(row)
        if pid is not None:
            by_id.setdefault(pid, []).append(row)
    parcels = (_parcel_of(pid, rows) for pid, rows in by_id.items())
    return [p for p in parcels if p is not None]


_GRID_WORDS = {"north": "n", "south": "s", "east": "e", "west": "w"}


def _grid_form(address: str | None) -> str | None:
    """``address`` with Utah's two respellings undone, and nothing else changed.

    Utah numbers its streets on a grid, and one street has two spellings: the
    rolls write "175 E 100 S" where the Census matcher returns "175 E 100 SOUTH
    ST". Those parse as different streets, so the parcel is refused. The direction
    word is abbreviated only where it directly follows a number — "100 SOUTH" is
    the grid street 100 S — and never elsewhere, so "1820 E SOUTH WEBER DR" keeps
    its name. A terminal "COVE" becomes "CV" for the same reason (below). Applied
    identically to both sides of the comparison, so it can only make two spellings
    of one street equal.

    What this deliberately does NOT do is forgive a missing LEADING directional,
    though that is the commonest mismatch measured here ("1526 E DOWNINGTON AVE"
    on the roll, "1526 DOWNINGTON AVE" from Census). The Census matcher ignores
    that directional outright: "571 N 200 W" and "571 S 200 W" come back as the
    same point, 0 m apart, so the point cannot say which side of the grid the home
    is on, and accepting "571 S 200 W" for it would confirm whichever twin happens
    to be near. See the module docstring.
    """
    if not address:
        return address
    head, sep, tail = str(address).partition(",")
    tokens = head.split()
    for i in range(1, len(tokens)):
        word = tokens[i].lower().strip(".")
        if word in _GRID_WORDS and tokens[i - 1].isdigit():
            tokens[i] = _GRID_WORDS[word].upper()
    # "Cove" is Utah's commonest cul-de-sac type, and the shared suffix table does
    # not know it, so the roll's "COUNTRY CREEK CV" and Census's "COUNTRY CREEK
    # COVE" parse as different streets. Only a TERMINAL "COVE" is a street type.
    if len(tokens) > 2 and tokens[-1].lower() == "cove":
        tokens[-1] = "CV"
    return " ".join(tokens) + sep + tail


def _directionless(address: str | None):
    """(house number, street tokens minus directionals), or None if unparseable."""
    key = address_key(_grid_form(address))
    if key is None:
        return None
    return key[0], tuple(sorted(t for t in key[1] if t not in _GRID_LETTERS))


_GRID_LETTERS = frozenset({"n", "s", "e", "w"})


def _has_a_confusable_twin(query: str, chosen: dict, nearby: list[dict]) -> bool:
    """Whether a parcel near the point differs from the query only in directionals.

    Utah's grid addresses come in near-twins the Census matcher is measured to
    confuse. Typed "325 E 300 N, Kanab", it returned "325 N 300 E" — a different,
    real house 45 m from the point, while the house the reader meant stood 55 m
    away. Every step after the geocoder then worked as designed and named the
    wrong home: the matched address agreed with exactly one parcel. The same run
    turned "333 S 300 E" into "333 E 300 S", "1652 S 1100 W" into "1652 N 1100 E",
    and dropped leading directionals outright (see _grid_form).

    The adapter is handed only the matched address, so it cannot see the swap.
    What it can see is whether the confusion is POSSIBLE here: another parcel in
    the 80 m neighbourhood with the same house number and the same street once
    directionals are set aside — order and side included — but a different full
    address. Where one exists the answer is refused, because which of the two
    the reader meant is exactly what the geocoder has shown it cannot be trusted
    to say. Where none exists nearby, a swapped geocode would have nothing to
    land on but the reader's own street, and the ordinary rules stand.
    """
    want = _directionless(query)
    if want is None:
        return False
    for other in nearby:
        if other.get("PARCEL_ID") == chosen.get("PARCEL_ID"):
            continue
        add = other.get("PARCEL_ADD")
        if _directionless(add) == want and not _shared.same_address(
                query, _grid_form(add)):
            return True
    return False


def _same_unit_or_none(parcel: dict, unit: str) -> bool:
    """Whether this parcel could be the typed unit's: it names that unit, or none."""
    own = unit_of(parcel.get("PARCEL_ADD"))
    return own is None or own.lower() == unit.lower()


def _county_at(lat: float, lon: float, *, deadline: float) -> str | None:
    """The FIPS of the Utah county this point is in, from UGRC's boundaries.

    Needed because the registry hands an adapter a coordinate and an address but
    not the county it routed on, and Utah's records are 29 separate services. One
    small request against a 29-polygon layer; skipped entirely when the caller
    passes the county.
    """
    body = _shared.get_json(COUNTY_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FIPS_STR", "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    found = {str((f or {}).get("attributes", {}).get("FIPS_STR") or "").strip()
             for f in (body.get("features") or [])}
    found &= COUNTY_FIPS
    return found.pop() if len(found) == 1 else None


def _parcel_at(lat: float, lon: float, address: str | None = None,
               county_fips: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s; see it for why the nearest
    parcel is never taken. No locality trim is needed: PARCEL_ADD is the street
    address alone ("3854 S 800 W"), with the city in its own column.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips not in COUNTY_FIPS:
        fips = _county_at(lat, lon, deadline=deadline)
    if fips is None:
        return None
    url = PARCEL_URL.format(service=COUNTY_SERVICES[fips])
    unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            fetched[distance_m] = _parcels(url, lat, lon, distance_m, deadline=deadline)
        found = fetched[distance_m]
        # A reader who typed a unit cannot live in a parcel that names a DIFFERENT
        # unit. Condominium units are separate parcels stacked on one footprint, all
        # sharing the street address the comparison reads, so without this a
        # typed "#1" faces six "947 CANYON RD APT n" candidates and is refused.
        # Dropping rows that cannot be the answer is the sanctioned shape (see
        # select_parcel): it can turn "ambiguous" into "one", never admit a parcel
        # the address check would not.
        return [p for p in found if _same_unit_or_none(p, unit)] if unit else found

    query = _grid_form(address)
    chosen = select_parcel(fetch, query, lambda p: _grid_form(p.get("PARCEL_ADD")))
    if chosen is None or not address:
        return chosen
    # The confusable-twin guard; see _has_a_confusable_twin. It needs the 80 m
    # neighbourhood even when containment already answered, which costs one more
    # request (measured median 0.14 s) on exactly those lookups.
    if _has_a_confusable_twin(query, chosen, fetch(_shared.SEARCH_RADIUS_M)):
        return None
    return chosen


def _vintage(parcel: dict) -> str:
    """What this record reflects, dated from the row's own CURRENT_ASOF.

    The counties deliver on their own schedules and the date is genuinely per
    county: Salt Lake's rows are current as of 2026, most counties' as of late
    2025, and Box Elder's as of July 2020. A hard-coded year would present a
    six-year-old roll at the confidence of this year's.
    """
    ms = num(parcel.get("CURRENT_ASOF"))
    if ms:
        try:
            day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return DATA_VINTAGE
        if 1990 <= day.year <= 2100:
            return f"{DATA_VINTAGE}, current as of {day.isoformat()}"
    return DATA_VINTAGE


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    parcel = _parcel_at(lat, lon, address, county_fips)
    if not parcel:
        return None
    building = _the_dwelling(parcel["buildings"])
    if building is None:
        return None

    year = num(building.get("BUILT_YR"))
    # 0 is the county's "not recorded", not the year zero. And a parcel whose class
    # says no one lives there reports no year: a shop's year built is not the year
    # the reader's home went up.
    year_built = int(year) if (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                               and not _says_no_home(parcel.get("PROP_CLASS"))) else None
    sqft = _area(parcel, building)
    stories = _stories(parcel, building)
    construction = (_construction(building)
                    if not _says_no_home(parcel.get("PROP_CLASS")) else None)
    if year_built is None and sqft is None and stories is None and construction is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(parcel),
        parcel_id=parcel["PARCEL_ID"],
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        construction=construction,
        # No foundation or condition column exists in the LIR schema.
    )


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What Utah's county rolls say is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is optional: the registry does not pass it today, and
    without it the county is looked up from the point (one extra request).

    Fails open on everything. The caller then keeps whatever it had, which is the
    behaviour that existed before this adapter.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Utah assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
