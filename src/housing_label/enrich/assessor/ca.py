#!/usr/bin/env python3
"""California — Contra Costa, San Joaquin and Riverside, from each county's own layer.

California has no statewide parcel roll. Each of its 58 county assessors keeps its
own, and what reaches the public is whatever each county's GIS office chose to
publish. So this is one module with a per-county table (``COUNTIES``), the shape
Utah's adapter uses for its 28 layers: each county supplies its endpoints, its
field names and its own vocabulary, and the lookup is shared. Los Angeles has its
own adapter (``la.py``), whose condominium unit matching and "every dwelling
agrees" rule this module follows, and San Francisco is a separate Socrata adapter.

  ==============  =====  =========  ========================================
  county          FIPS   homes      source (all keyless, verified 2026-10-03)
  ==============  =====  =========  ========================================
  Riverside       06065    869,414  RCIT ``OpenData/Assessor`` layers 50
                                    (parcels) and 30 (condominiums), then
                                    table 80 (one row per building)
  Contra Costa    06013    429,260  ``CCMAP/Assessment_Parcels_ArcPro`` layer 0
  San Joaquin     06077    260,151  county AGOL ``Parcels`` layer 0
  ==============  =====  =========  ========================================

About 1.56 million homes (housing units, from ``data/year_built_county.csv``).

Measured and left out
---------------------
Two counties publish usable rows and are excluded pending a product decision:

* **San Bernardino (06071).** Its official parcel dataset carries an actual
  ``CONST_YEAR`` (99.6% filled on single-family parcels), but the county removed
  situs addresses and owner names from it — "redacted in compliance with Assembly
  Bill No. 1785", the owner column reading "Protected Per CA Gov Code 7928.205".
  Re-joining addresses from the county's separate address-point layer would work
  technically and would undo a choice the county made on purpose, so it waits for
  that decision.
* **Ventura (06111).** Full roll attributes, but only on a layer behind a county
  web app (``SDs/MyZoning/MapServer/1``, which also carries owner names), whose
  GIS terms say it exists "solely for the convenience of the County and related
  contract entities".

The others measured publish no usable year built, so there is nothing to adapt:
San Diego's only year is a two-digit *effective* year its own metadata says not
to use for age; Orange's ``YEAR_BUILT`` is a snapshot frozen around 1997 (1998
has 3 parcels, the 2000s decade 59); Santa Clara, Alameda (beyond a Tri-Valley
third-party copy), Sacramento (sales only, effective year), Fresno, Kern and San
Mateo publish none.

One record per parcel (or unit), except in Riverside
----------------------------------------------------
Contra Costa and San Joaquin put the building facts on the parcel polygon, so the
lookup is one question, as in Florida. Riverside splits them: the parcel layer
carries the situs and a class label, and the facts are in a building table keyed
by APN, one row per BUILDING — 1,205,247 rows. That makes three things true there:

* **Two parcel layers are asked, not one.** At a condominium the parcel layer
  returns only the complex's common lot — APN 234052071 at 3738 Harrison St,
  "Vacant Residential Land - Other", no situs, no building — and the units are on
  the condominium layer (APN 234052027, unit 27, 1988, 1,009 sq ft). Asking only
  layer 50 would read every Riverside condominium as vacant land.
* **Garages are buildings.** 3728 Linwood Pl is a 1914 house of 1,428 sq ft and a
  1914 "Residential Garage" of 240. Non-dwellings (garages, commercial,
  miscellaneous and agricultural buildings) are set aside; then, as in Los
  Angeles, the year is reported only where every dwelling agrees, and the area
  and story count only where there is exactly one dwelling of a one-home design.
  A building of unknown kind ("Unknown", "Timeshare") breaks the agreement. On
  the research's random 600 residential parcels, 578 hold one dwelling, 7 several
  that agree and 7 several that disagree (mostly "SFD with Secondary Unit(s)").
* **The table is a hop with its own clock** (see "The clock").

Contra Costa: two year columns, and which one is a house's
----------------------------------------------------------
``YR_HS_BLT`` ("year house built") is filled on 340,143 rows, and on 339,248 of
the 343,508 parcels with a residential use code (98.8%). ``YR_BUILT`` is filled
on 14,765, almost all multifamily, commercial and rural — and the two are never
filled on the same row (measured over the whole layer), so they are two record
types, not two opinions. ``YR_HS_BLT`` is read for every home. ``YR_BUILT`` is
read only for triplexes, fourplexes and apartments (use codes 22, 23, 25–28),
which carry no house year at all and whose whole parcel is housing. It is not
read for condominiums (code 29 includes office and industrial condominiums —
the Moraga Rd suites carry ``YR_BUILT`` 2008 and no house year), nor for rural
parcels, where it may date a barn. ``TLA`` is the total living area; ``BLDG_SQFT``
is the commercial record's and is not read. Missing years read null, "   0" or
"0000".

The layer returns placeholder rows over condominium complexes — APN
``189320xxx``, the last digits written as x's, every other column null — which
are dropped before the parcel is chosen. ``S_FRAC`` is not a fraction here: it
holds the end of a number range ("4889" … "4891"), so it is not read, and an
address written with the range's second number is not confirmed.

**Liveness.** The service describes itself as "Legacy CCMap parcels layer. Will
be replaced with a parcel layer tied to the main table ... It is for
demonstrative purposes only." It answers today; the day it is replaced every
lookup fails open (each failure is recorded as a dropped dataset, so labels are
not cached on it) and this entry needs a new URL and field list.

San Joaquin: two-letter street types, and several houses under one year
-----------------------------------------------------------------------
``SITUSTYPE`` is a two-letter code. Only codes with one reading are spelled out
(CI circle, BL boulevard, TE terrace, TR trail — the county writes TE for its
terraces, so TR is not ambiguous here — LO, GL, PZ, AL, XG, RU); PA, PK, CR, WA,
BN and IS mean two things each and are left as written, so they confirm nothing.
``STORIES`` is per unit (two units of one Peerless Way building read 1 and 2), so
it is reported where the area is. ``VALUE_ROLL_YEAR`` dates the record. Use codes
for two houses on one parcel, a house with a secondary residence, or several
structures refuse the year, as does vacant land or land with only a garage or a
pool; a farm whose description ends "W/RESIDENCE" gives the residence's year.
``NUMBER_UNITS`` is blank on every residential row and is not used.

Condominiums, and the unit that has to pick the record
------------------------------------------------------
In all three counties a condominium unit is its own record with its own unit
designator, and — unlike Los Angeles, which draws every unit on the building's
full footprint — units are not always stacked: a unit can be its own polygon, so
the point lands in ONE unit whichever unit the reader typed (the geocoder puts
every unit of an address on one point). So, before the parcel is chosen, records
naming a unit other than the reader's are dropped (they cannot be the reader's
home; dropping them can only turn "ambiguous" into "one"); a record that names a
unit is never taken for a reader who gave none; and then Los Angeles's two paths
run: the reader's unit picks one record at the address, at the point and then
within the radius, and failing that the building's year is reported if every
record at the address within the radius is a home and agrees on it — no area and
no parcel id, since no record was chosen. A unit's own area is reported only to
the reader who typed that unit. A Riverside unit's story count is never reported:
whether it counts the unit's floors or the building's is not said.

Addresses
---------
Each county's address is built from its situs parts, never from a one-line field.
One respelling is applied to both sides, because the Census matcher abbreviates
three Spanish street words the rolls spell out: CAMINO → CAM and AVENIDA → AVE
leading the name, VISTA → VIS ending it (7 of the first run's 33 refusals, in all
three counties). Riverside's own TR (Trail, 7,102 parcels) and PKY (Parkway) are
put into the matcher's spelling. A stray number keyed into Riverside's
``STREET_SUFFIX`` makes that address unconfirmable rather than guessed around.

The year built
--------------
Actual years only. None of the three layers carries an effective year, and the
California layers measured that do (San Bernardino's ``EFF_YEAR``, Sacramento's
``EFFECTIVE_YEAR_BUILT``, San Diego's ``year_effective``) are not used. Besides
the shared floor and ceiling, a year later than next year is refused: San Joaquin
carries 2047 and 2109, Riverside's table twelve rows past 2026.

What is not read
----------------
No exterior wall, foundation or condition reaches the label. Riverside's
``CONSTRUCTION_TYPE`` is the State Board of Equalization class (Assessors'
Handbook 531): "Wood or Light Steel (D)" covers the label's frame, vinyl and
brick-frame alike — the call ``la.py`` makes for the same code — and "Concrete /
Masonry Bearing Walls (C)" brick, block or stone; ``QUALITY_CODE`` and San
Joaquin's ``QCS`` grade construction quality, not upkeep. None is requested.

The clock
---------
Measured through the product's HTTP session at 206 random residential parcels
(dedicated pairs at parcel points), and again inside 403 end-to-end lookups:

  ======================================  ======  ======  ======  ======
  request                                 median     p90     p95     max
  ======================================  ======  ======  ======  ======
  Contra Costa containment (60)            0.09 s  0.10 s  0.10 s  0.55 s
  Contra Costa 80 m buffer (60)            0.09 s  0.10 s  0.10 s  0.11 s
  San Joaquin containment (49)             0.14 s  0.16 s  0.17 s  0.53 s
  San Joaquin 80 m buffer (49)             0.15 s  0.19 s  0.25 s  0.28 s
  Riverside layer 50, containment (97)     0.16 s  0.17 s  0.18 s  0.58 s
  Riverside layer 50, buffer (97)          0.17 s  0.18 s  0.19 s  0.36 s
  Riverside layer 30, containment (97)     0.16 s  0.17 s  0.18 s  0.21 s
  Riverside layer 30, buffer (97)          0.17 s  0.18 s  0.19 s  0.21 s
  Riverside building table (97)            0.16 s  0.17 s  0.18 s  0.23 s
  end to end: any containment (592)        0.15 s  0.17 s  0.25 s  0.82 s
  end to end: any buffer (573)             0.16 s  0.18 s  0.21 s  0.68 s
  end to end: building table (165)         0.15 s  0.17 s  0.20 s  0.55 s
  end to end: whole lookup (403)           0.34 s  0.83 s  0.95 s  1.95 s
  ======================================  ======  ======  ======  ======

Bodies are a few kilobytes. Nothing measured came near a second, but the
research behind this module saw a 9.8 s outlier on a neighboring county's
service and one first-ever Riverside table call of 19.9 s, so the slice is Los
Angeles's 2 s rather than the shared 1 s — a merely slow answer survives, a hung
one is cut off. ``LOOKUP_TIMEOUT`` is the shared 4 s for all parcel requests of a
lookup together: Riverside's worst case is four of them (two layers, contained
and buffered), measured at 0.8 s typical. The building table gets its own 2.5 s,
started when that hop starts, so a slow parcel phase cannot starve it; a 19.9 s
cold call still fails open, uncached, and the next lookup finds the service warm.
The worst case for one lookup is therefore both phases each overshooting by a
slice: 4 + 2 + 2.5 + 2 = 10.5 s, under the host's 12 s per service
(``config.UPSTREAM_HOST_BUDGET``); a test pins it against the constant.

What the adapter is worth, end to end
-------------------------------------
Two independent random draws from the counties' own layers — residential use
codes with a recorded year, Riverside's also from its condominium layer, 30 of
them condominium units typed with their unit — 414 homes in all, each geocoded
through the Census matcher and ``assessor_address`` exactly as the product does,
then looked up with no county passed (routed by the layers' extents):

  ==========================  =====  =====  =====  =====
                              Riv.   C.C.   S.J.   all
  ==========================  =====  =====  =====  =====
  sampled                       195    120     99    414
  geocoded                      188    119     96    403
  routed to the county          188    118     96    402
  resolved                      163    102     79    344
  **wrong parcel**            **0**  **0**  **0**  **0**
  year = the roll's             163    102     79    344
  area reported / exact     154/154 101/101  76/76  331/331
  stories reported              139      0     76    215
  ==========================  =====  =====  =====  =====

85% of geocoded homes resolve. Six of the 344 are condominium addresses answered
with the building's year and no unit. The first draw was run once before the
Spanish respelling and San Joaquin's TR were added (167 resolved, 0 wrong); the
second was drawn after and run once. The one routing miss is a Kensington
address the geocoder puts in Alameda County, which the registry would never send
here.

The 59 that did not resolve, every one traced: 40 geocodes more than 80 m from
their own parcel (12 of them condominium units in large complexes, 2 where the
matcher substituted a different street); 14 directionals the matcher drops or
adds ("2390 E EUCLID AVE" comes back "2390 EUCLID AVE"), refused because the
shared comparison treats a directional as part of the street; 5 spellings
("WHITE WOOD"/"WHITEWOOD", "MC BRYDE"/"MCBRYDE", "JO ANN"/"JOANN",
"COL"/"COLONEL", and "CAMINO DEL SUR", which the matcher returns as "CAM SUR").

Terms of use
------------
Read 2026-10-03. None restricts querying, caching or commercial use; all three
are warranty disclaimers. The posture is the registry's regardless: query live,
cache in process, bundle nothing, attribute the county assessor.

* **Riverside.** The ArcGIS items behind the three layers (47ad3e55…, f7a19782…,
  9721d1fa…) carry the license "Public Use", credit "Riverside County Assessor,
  RCIT"; the county's hub publishes no further terms.
* **Contra Costa.** The service's item info points to "the Contra Costa County
  Data Disclaimer" (https://gis.cccounty.us/Downloads/Data%20Disclaimer.pdf): the
  data is taken "as is", "County makes absolutely no warranty", and the user
  waives claims against the County. No use restriction.
* **San Joaquin.** The ArcGIS item (03f97b03…, published by the county's Public
  Works) carries **no license or disclaimer text at all**. The county GIS site's
  disclaimer (https://sjmap.org/disclaimer.htm) and the terms for its download
  products (https://sjmap.org/files/SjcGisAgreementP2.pdf) provide the data "as
  is" and ask for indemnity against misuse; neither covers this service by name
  or restricts use. Worth confirming with the county before launch.

Privacy, and why the field lists are short
------------------------------------------
Contra Costa's layer carries the owner's mailing address (the ``N_*`` columns) and
every assessed value; San Joaquin's carries ``CAREOF``, ``DBANAME``,
``MAILSTREET`` and ``MAILING_ADDRESS``; Riverside's carry ``MAIL_STREET`` and
``MAIL_CITY``. None is requested — each county's ``fields`` names only the
situs, the use, the year, the area and the story count — and nothing from these
sources is written into the repository.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SEARCH_RADIUS_M, address_key, cache_bucket, deadline_from, num, same_address,
    select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "California county assessors (Contra Costa, San Joaquin, Riverside)"
ATTRIBUTION = ("California county assessors: Contra Costa (CCMap parcels), San Joaquin "
               "(county parcels) and Riverside (RCIT CREST), keyless")
DATA_VINTAGE = "California county assessor parcel data"

CONTRA_COSTA_URL = ("https://gis.cccounty.us/arcgis/rest/services/CCMAP"
                    "/Assessment_Parcels_ArcPro/MapServer/0/query")
SAN_JOAQUIN_URL = ("https://services2.arcgis.com/GQhSReJEO6f7tsvy/arcgis/rest/services"
                   "/Parcels/FeatureServer/0/query")
_RIVERSIDE = ("https://gis.countyofriverside.us/arcgis_mapping/rest/services/OpenData"
              "/Assessor/MapServer")
RIVERSIDE_PARCEL_URL = _RIVERSIDE + "/50/query"      # PARCELS_CREST
RIVERSIDE_CONDO_URL = _RIVERSIDE + "/30/query"       # CONDOMINIUMS_CREST
RIVERSIDE_BUILDINGS_URL = _RIVERSIDE + "/80/query"   # CREST_PROPERTY_CHAR

#: The clock. See "The clock" in the module docstring for the measurements.
#:
#: ``READ_SLICE_S`` is how long one of these services may go quiet before the
#: silence is read as a stall; ``LOOKUP_TIMEOUT`` bounds every PARCEL request of
#: one lookup together (up to four in Riverside: two layers, each contained and
#: buffered). Riverside's building table is a separate hop with its own budget,
#: ``BUILDINGS_TIMEOUT``, started when that hop starts, so a slow parcel phase
#: cannot leave the table nothing to run in — and a slow table cannot stretch the
#: parcel phase.
READ_SLICE_S = 2.0
LOOKUP_TIMEOUT = 4.0
BUILDINGS_TIMEOUT = 2.5


def _this_year() -> int:
    return date.today().year


def _year(raw) -> int | None:
    """An actual year built, or None.

    The shared floor and ceiling, plus one more: no later than next year. The
    rolls carry a handful of keying errors in the future — San Joaquin has 2047
    and 2109, Riverside's building table twelve rows past 2026 — and a house
    cannot have been built in 2047. Next year, not this one, because a house under
    construction is enrolled with the year it will be finished.
    """
    y = num(str(raw if raw is not None else "").strip())
    if y is None or not float(y).is_integer():
        return None
    y = int(y)
    ok = EARLIEST_PLAUSIBLE_YEAR <= y <= 2100 and y <= _this_year() + 1
    return y if ok else None


def _text(v) -> str:
    return " ".join(str(v if v is not None else "").split())


# Words a roll or a reader puts in front of a unit number.
_UNIT_WORDS = frozenset({"NO", "APT", "UNIT", "STE", "SUITE", "#"})


def _unit_key(raw) -> str | None:
    """A unit designator reduced to what identifies it, or None if there is none.

    The rolls write "27      " (Riverside pads to eight), "B", "201"; a reader
    writes "#27", "Apt B". The marker and punctuation go and case folds; leading
    zeros stay significant, as in the Los Angeles and District adapters, since
    unit 01 and unit 1 can both exist in one building.
    """
    tokens = str(raw or "").upper().replace("#", " # ").split()
    while tokens and tokens[0] in _UNIT_WORDS:
        tokens = tokens[1:]
    key = "".join(ch for ch in "".join(tokens) if ch.isalnum())
    return key or None


# Three Spanish street words the Census matcher abbreviates and the rolls spell
# out: CAMINO as CAM and AVENIDA as AVE where they lead the name ("1402 CAMINO
# PERAL" comes back "1402 CAM PERAL"; "31775 AVENIDA XIMINO", "31775 AVE XIMINO"),
# and VISTA as VIS where it ends it ("472 MONTE VISTA", "472 MONTE VIS"). Measured
# in the end-to-end run: 7 of 33 refusals, in all three counties' rolls, were only
# this. Folded identically on both sides — the reader's address and the roll's —
# so it can make two spellings of one street agree and nothing else: the folded
# words stay name tokens, so "AVE XIMINO" still does not match "XIMINO AVE".
_LEADING_SPANISH_RE = re.compile(
    r"^(?P<head>\d+(?:\s+\d+/\d+)?\s+(?:[NSEW]\s+)?)(?P<word>CAMINO|AVENIDA)\s+(?=\S)")
_TRAILING_VISTA_RE = re.compile(r"\s+VISTA(?=\s*(?:#|\b(?:APT|UNIT|STE)\b|$))")
_SPANISH = {"CAMINO": "CAM", "AVENIDA": "AVE"}


def _canon(text: str | None) -> str | None:
    """``text`` with the street's Spanish words spelled as the matcher spells them.

    Only the street part (before the first comma) is touched, so the unit, city
    and ZIP pass through exactly as given.
    """
    if not text:
        return text
    head, sep, tail = " ".join(str(text).upper().split()).partition(",")
    head = _LEADING_SPANISH_RE.sub(lambda m: m["head"] + _SPANISH[m["word"]] + " ", head)
    head = _TRAILING_VISTA_RE.sub(" VIS", head)
    return f"{head}{sep}{tail}"


def _street(number, parts, type_word: str | None) -> str | None:
    """``number parts... type`` as one string, or None if it is not an address.

    House number 0 or blank is a roll's "no situs", not an address.
    """
    number = _text(number)
    if not (number.isdigit() and int(number) > 0):
        return None
    words = [p for p in (_text(x) for x in parts) if p]
    if not words:
        return None
    text = _canon(" ".join([number] + words + ([type_word] if type_word else [])))
    return text if address_key(text) else None


@dataclass(frozen=True)
class _Facts:
    """What one candidate record says about the home, already in the label's terms.

    ``home`` False is the roll saying nobody lives here (a vacant, commercial or
    government parcel); ``year`` is the year built where it belongs to the home;
    ``sqft`` and ``stories`` are set only where the record is one dwelling in one
    building — the unit check against the reader's unit is applied later, since
    it needs the reader.
    """

    home: bool
    year: int | None
    sqft: float | None = None
    stories: int | None = None


# ── Contra Costa ────────────────────────────────────────────────────────────────

# USE_CODE → what it says. The codes and wording are the county's own
# (``Description`` on the layer); counts are of the 387,936 rows, 2026-10-03.
#
# Homes, and the year may be read: 11 single family (222,802), 12 single family
# on 2+ sites, 14 single family on other land, 16 townhouse/attached PUD/duet,
# 19 single family detached with common area (45,543), 21 duplex, 22 triplex,
# 23 fourplex, 25–28 apartments, 29 condominium (35,606), 61 rural residential
# improved, 88 manufactured home.
_CC_HOMES = frozenset({11, 12, 14, 16, 19, 21, 22, 23, 25, 26, 27, 28, 29, 61, 88})
# Homes on parcels the roll says hold SEVERAL residences — 13 "Single Family, 2 or
# more residences" (2,829) and 24 "Combinations (e.g., Single and a Double)" —
# under one year column. Which residence it dates is not said, and in Riverside,
# where the buildings are listed, the main house and the second unit disagree on
# 5 of 9 sampled such parcels. The Los Angeles rule — a year only where every
# dwelling agrees — cannot be checked here, so the year is refused.
_CC_SEVERAL = frozenset({13, 24})
# One dwelling per record, so TLA is that dwelling's area. A condominium (29) is
# one unit per record, and the unit check then decides.
_CC_ONE_DWELLING = frozenset({11, 12, 14, 16, 19, 29})
# Multifamily codes whose rows carry no residential year at all — YR_HS_BLT is
# filled on none of them — but the commercial-record YR_BUILT. See "Two year
# columns" in the module docstring.
_CC_YR_BUILT_CODES = frozenset({22, 23, 25, 26, 27, 28})


def _cc_is_record(row: dict) -> bool:
    """Whether a row is a parcel record rather than a placeholder.

    Over condominium complexes the layer returns rows like APN ``189320xxx`` —
    an APN with its last digits written as x's — and every other column null. A
    real APN with nothing on it ("510015019") is the same kind of row. They can
    never be an answer and must not make a real one ambiguous.
    """
    apn = _text(row.get("APN"))
    if not apn or not apn.isdigit():
        return False
    return any(row.get(c) not in (None, "") for c in
               ("USE_CODE", "S_STR_NBR", "YR_HS_BLT", "YR_BUILT", "TLA"))


def _cc_address(row: dict) -> str | None:
    """The situs from its parts. ``S_FRAC`` is not a fraction on this layer: it
    holds the END of a number range ("4889" … "4891"), so it is not used, and an
    address written with the range's second number is not confirmed."""
    return _street(row.get("S_STR_NBR"), [row.get("S_STR_NM")],
                   _text(row.get("S_STR_SUF")) or None)


def _cc_facts(row: dict) -> _Facts:
    use = num(row.get("USE_CODE"))
    use = int(use) if use is not None else None
    if use is not None and use not in _CC_HOMES and use not in _CC_SEVERAL:
        return _Facts(home=False, year=None)
    if use in _CC_SEVERAL:
        return _Facts(home=True, year=None)
    year = _year(row.get("YR_HS_BLT"))
    if year is None and use in _CC_YR_BUILT_CODES:
        year = _year(row.get("YR_BUILT"))
    sqft = None
    if use in _CC_ONE_DWELLING:
        area = num(row.get("TLA"))
        sqft = area if area and area > 0 else None
    return _Facts(home=True, year=year, sqft=sqft)


# ── San Joaquin ─────────────────────────────────────────────────────────────────

# USECODE, within CATEGORY RESIDENTIAL (218,978 rows of 252,964). The wording is
# the county's DESCRIPTION column.
#
# Vacant land, or land whose only improvements are a garage or a pool: nobody
# lives here, and a year read off it would be the garage's.
_SJ_NOT_A_HOME = frozenset({"1A", "2A", "3A", "4A", "5A", "6A", "20", "30", "40",
                            "50", "53", "54"})
# Several residences or structures under one year column: 13 SFR with secondary
# residence, 22 two SFDs on one parcel, 32 three units in 2+ structures, 35 four
# units in 2+ structures, 42/44 5–20 units in 2+ buildings, 52 rural with 2+
# residences. The year is refused; see _CC_SEVERAL.
_SJ_SEVERAL = frozenset({"13", "22", "32", "35", "42", "44", "52"})
# One dwelling per record: 10 SFD (179,425), 11 condominium unit, 12 PURD, 15
# zero lot line, 17 single family with common wall (duet, half-plex), 51 rural
# residence with one residence.
_SJ_ONE_DWELLING = frozenset({"10", "11", "12", "15", "17", "51"})

# SITUSTYPE is a two-letter code. These are the ones with a single reading, put
# into the USPS spelling the Census matcher returns: Julie Lynne CI is a circle
# and the county already writes CT for court. AV and WY need nothing (the shared
# table has both). Left as written, so that they confirm nothing: PA (International
# PA in Tracy is a parkway, but "path" is the same code elsewhere), PK (park, pike
# or parkway), CR (circle or crescent — the county also writes CI), WA (walk or
# way), BN, IS. TR is mapped although the shared table leaves it alone (trail or
# terrace elsewhere): this county writes TE for its terraces, and its TR streets
# are trails — Golden Spike, Forty Niner and Ore Claim Trail in Lathrop, Hunter
# Trail in Tracy.
_SJ_TYPES = {"CI": "CIR", "BL": "BLVD", "TE": "TER", "LO": "LOOP", "GL": "GLN",
             "PZ": "PLZ", "AL": "ALY", "XG": "XING", "RU": "RUN", "TR": "TRL"}


def _sj_is_record(row: dict) -> bool:
    return bool(_text(row.get("APN")))


def _sj_address(row: dict) -> str | None:
    t = _text(row.get("SITUSTYPE")).upper()
    return _street(row.get("SITUSNUMBER"),
                   [row.get("SITUSDIRECTION"), row.get("SITUSTREET")],
                   _SJ_TYPES.get(t, t) or None)


def _sj_facts(row: dict) -> _Facts:
    category = _text(row.get("CATEGORY")).upper()
    use = _text(row.get("USECODE")).upper()
    if category == "AGRICULTURAL":
        # "IRRIGATED ORCHARD W/RESIDENCE", "DAIRY W/RESIDENCE": the county's own
        # statement that one residence stands on the farm, and the year is that
        # residence's. A farm without the suffix says nothing of a home.
        home = _text(row.get("DESCRIPTION")).upper().endswith("W/RESIDENCE")
        return _Facts(home=home, year=_year(row.get("YEAR_BUILT")) if home else None)
    if category and category != "RESIDENTIAL":
        return _Facts(home=False, year=None)
    if use in _SJ_NOT_A_HOME:
        return _Facts(home=False, year=None)
    if use in _SJ_SEVERAL:
        return _Facts(home=True, year=None)
    year = _year(row.get("YEAR_BUILT"))
    if use not in _SJ_ONE_DWELLING:
        return _Facts(home=True, year=year)
    area = num(row.get("TOTALLIV_AREA"))
    floors = num(row.get("STORIES"))
    return _Facts(home=True, year=year,
                  sqft=area if area and area > 0 else None,
                  stories=int(floors) if floors and floors > 0
                  and float(floors).is_integer() else None)


# ── Riverside ───────────────────────────────────────────────────────────────────

# The street type, where the roll spells it in a way the shared table does not
# read. TR in Riverside is Trail — Preston Trail and Hawk Hill Trail in Palm
# Desert, Sky Blue Water Trail in Cathedral City, 7,102 parcels — and the Census
# matcher writes TRL; the shared table leaves TR alone because elsewhere it can be
# a terrace. PKY (964 parcels) is the roll's Parkway, PKWY to the matcher.
_RV_TYPES = {"TR": "TRL", "PKY": "PKWY"}
_RV_DIRECTIONS = {"N": "N", "S": "S", "E": "E", "W": "W",
                  "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def _rv_is_record(row: dict) -> bool:
    return _text(row.get("APN")).isdigit()


def _rv_address(row: dict) -> str | None:
    """The situs from its parts. ``STREET_SUFFIX`` is blank on all but 363 of the
    846,554 parcels: "1/2" (86, a half address, kept after the number), a trailing
    directional (11), and otherwise stray numbers keyed into the wrong column —
    which make the address unconfirmable rather than being guessed around."""
    suffix = _text(row.get("STREET_SUFFIX")).upper()
    fraction, trailing = None, None
    if suffix == "1/2":
        fraction = suffix
    elif suffix in _RV_DIRECTIONS:
        trailing = _RV_DIRECTIONS[suffix]
    elif suffix:
        return None
    number = _text(row.get("STREET_NUMBER"))
    if number.endswith(".0"):
        number = number[:-2]
    t = _text(row.get("STREET_TYPE")).upper()
    t = _RV_TYPES.get(t, t)
    parts = [fraction, row.get("STREET_PREDIRECTION"), row.get("STREET_NAME")]
    text = _street(number, parts, t or None)
    if text and trailing:
        text = f"{text} {trailing}"
        return text if address_key(text) else None
    return text


def _rv_class_says_no_home(row: dict) -> bool:
    """Whether CLASS_CODE contradicts a dwelling: vacant land or a common area.

    The building table, not the class, decides whether a home stands here — the
    class is a single label for the parcel ("Single Family Dwelling", "Condo or
    PUD", 267 values in all). But at a condominium the parcel layer returns the
    complex's common lot, classed "Vacant Residential Land - Other" with no situs,
    and a vacant or common-area class beside a dwelling row is a contradiction the
    adapter does not resolve.
    """
    c = _text(row.get("CLASS_CODE")).upper()
    return "VACANT" in c or "COMMON AREA" in c


# DESIGN_TYPE values on the building table that are a dwelling. Counts are of the
# table's 1,205,247 rows, 2026-10-03.
_RV_ONE_DWELLING_DESIGNS = frozenset({
    "Modern Single Family Residence (Post 1990)",        # 360,203
    "Modern Single Family Residence (1950-1990)",        # 261,158
    "Conventional Single Family Residence (Pre-1950)",   # 70,453
    "Conventional Mountain Residence",
    "A-Frame Mountain Residence",
    "Special Type Single Family Residence",
    "Double-Wide Manufactured Home",
    "Triple-Wide Manufactured Home",
    "Single-Wide Manufactured Home",
    "Quadruple-Wide Manufactured Home",
    "Licensed Manufactured Home (ILT)",
    "Manufactured Home",
})
# Dwellings that are not one home, or not the main one: they date the parcel's
# housing like any other dwelling, so they take part in the year agreement, but a
# parcel holding one never reports an area.
_RV_OTHER_DWELLING_DESIGNS = frozenset({
    "Apartment", "Multiple Family Residence", "Multiple Family (2 - 3 Units)",
    "Multiple Family (4 - 9 Units)", "Manufactured Home (5 or more units)",
    "Guesthouse - Modern (Post 1990)", "Guesthouse - Modern (1950-1990)",
    "Guesthouse - Conventional (Pre 1950)",
})
# Buildings that are not anyone's home, and are set aside. Garages are separate
# rows carrying the house's year (3728 Linwood Pl: a 1914 house of 1,428 sq ft and
# a 1914 garage of 240), and counting one as a second dwelling would cost every
# house with a garage its area.
_RV_NOT_DWELLINGS = frozenset({
    "Residential Garage", "Commercial / Industrial", "Miscellaneous Improvement",
    "Agricultural",
})
# Anything else — "Unknown" (595), "Timeshare" (11,789), a value added after
# 2026-10 — is a building of unknown kind, and breaks the year agreement the way
# Los Angeles's "0000" does: it could be a dwelling with any year.

_RV_BUILDING_FIELDS = "PIN,BUILDING_ID,YEAR_BUILT,NUMBER_OF_STORIES,LIVING_AREA,DESIGN_TYPE"
#: The most parcels one building-table request may ask about: the units at one
#: condominium address. The table caps an answer at 2,000 rows; 200 units at one
#: or two rows each stays well inside it, and a response that does not is refused
#: by the shared transport as truncated.
_RV_MAX_PINS = 200


def _rv_buildings(pins: list[str], *, deadline: float) -> dict[str, list[dict]]:
    """The building rows of each of these parcels, keyed by PIN.

    One request for all of them. The table has one row per BUILDING, and a
    parcel with no building returns one row with every field null, which is
    dropped here: it describes nothing.
    """
    clean = sorted({p for p in pins if p.isdigit()})
    if not clean or len(clean) > _RV_MAX_PINS:
        return {}
    where = "PIN IN (%s)" % ",".join(f"'{p}'" for p in clean)
    body = _shared.get_json(RIVERSIDE_BUILDINGS_URL, {
        "where": where, "outFields": _RV_BUILDING_FIELDS,
        "returnGeometry": "false", "f": "json",
    }, deadline, READ_SLICE_S) or {}
    out: dict[str, list[dict]] = {p: [] for p in clean}
    for feat in body.get("features") or []:
        a = (feat or {}).get("attributes") or {}
        pin = _text(a.get("PIN"))
        if pin in out and a.get("BUILDING_ID") is not None:
            out[pin].append(a)
    return out


def _rv_facts_from(row: dict, buildings: list[dict]) -> _Facts:
    """The Riverside rule: set the non-dwellings aside, then require agreement.

    A year where every dwelling on the parcel records the same one; an area and
    a story count where there is exactly one dwelling, of a one-home design, and
    no building of unknown kind beside it.
    """
    if _rv_class_says_no_home(row):
        return _Facts(home=False, year=None)
    dwellings, unknown = [], False
    for b in buildings:
        design = _text(b.get("DESIGN_TYPE"))
        if design in _RV_NOT_DWELLINGS:
            continue
        if design in _RV_ONE_DWELLING_DESIGNS or design in _RV_OTHER_DWELLING_DESIGNS:
            dwellings.append(b)
        else:
            unknown = True
    if not dwellings:
        # No dwelling building at all: a parcel with only a garage, a store, or
        # no building row. That is the roll saying no home stands here.
        return _Facts(home=False, year=None)
    years = {_year(b.get("YEAR_BUILT")) for b in dwellings}
    year = next(iter(years)) if len(years) == 1 and not unknown else None
    sqft = stories = None
    only = dwellings[0]
    if (len(dwellings) == 1 and not unknown
            and _text(only.get("DESIGN_TYPE")) in _RV_ONE_DWELLING_DESIGNS):
        area = num(only.get("LIVING_AREA"))
        sqft = area if area and area > 0 else None
        floors = num(only.get("NUMBER_OF_STORIES"))
        # A condominium unit's story count is not reported: a unit is one home,
        # but whether NUMBER_OF_STORIES counts its floors or its building's is not
        # said, and Salt Lake writes the tower's onto every unit.
        if (floors and floors > 0 and float(floors).is_integer()
                and not _unit_key(row.get("UNIT_NUMBER")) and row.get("_layer") != "condo"):
            stories = int(floors)
    return _Facts(home=True, year=year, sqft=sqft, stories=stories)


# ── the per-county table ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _County:
    """Everything that is a fact about one county; the lookup itself is shared."""

    fips: str
    name: str
    attribution: str
    vintage: str
    #: (layer tag, query URL) — every layer is asked at the same point and its
    #: rows offered together as candidates.
    layers: tuple[tuple[str, str], ...]
    fields: str
    id_field: str
    unit_field: str
    is_record: Callable[[dict], bool]
    address_of: Callable[[dict], str | None]
    #: (lat_min, lat_max, lon_min, lon_max), read off the layer's own extent;
    #: used only to route a direct call that names no county.
    bbox: tuple[float, float, float, float]
    #: The record's facts, from its own row (one-hop counties).
    facts: Callable[[dict], _Facts] | None = None
    #: A roll-year column, where the layer has one.
    roll_year_field: str | None = None


_CONTRA_COSTA = _County(
    fips="06013", name="Contra Costa",
    attribution="Contra Costa County Assessor's Office (CCMap assessment parcels, keyless)",
    vintage="Contra Costa County Assessor parcel layer (CCMap)",
    layers=(("parcel", CONTRA_COSTA_URL),),
    # No owner field exists on this layer; the N_* columns are the owner's MAILING
    # address and are never requested. Nor are the land, improvement and
    # exemption values.
    fields="APN,USE_CODE,S_STR_NBR,S_STR_NM,S_STR_SUF,S_APT_NBR,YR_HS_BLT,YR_BUILT,TLA",
    id_field="APN", unit_field="S_APT_NBR",
    is_record=_cc_is_record, address_of=_cc_address, facts=_cc_facts,
    bbox=(37.711, 38.102, -122.439, -121.533),
)

_SAN_JOAQUIN = _County(
    fips="06077", name="San Joaquin",
    attribution="San Joaquin County Assessor's Office (county parcels, keyless)",
    vintage="San Joaquin County Assessor parcels",
    layers=(("parcel", SAN_JOAQUIN_URL),),
    # The layer carries CAREOF, DBANAME, MAILSTREET, MAILCITY and MAILING_ADDRESS
    # (owner and mailing fields) and every assessed value; none is requested.
    fields=("APN,CATEGORY,USECODE,DESCRIPTION,SITUSNUMBER,SITUSDIRECTION,SITUSTREET,"
            "SITUSTYPE,SITUSUNIT,YEAR_BUILT,STORIES,TOTALLIV_AREA,VALUE_ROLL_YEAR"),
    id_field="APN", unit_field="SITUSUNIT",
    is_record=_sj_is_record, address_of=_sj_address, facts=_sj_facts,
    roll_year_field="VALUE_ROLL_YEAR",
    bbox=(37.480, 38.301, -121.587, -120.919),
)

_RIVERSIDE_COUNTY = _County(
    fips="06065", name="Riverside",
    attribution=("Riverside County Assessor via RCIT (CREST parcels, condominiums and "
                 "property characteristics, keyless)"),
    vintage="Riverside County Assessor CREST property characteristics",
    layers=(("parcel", RIVERSIDE_PARCEL_URL), ("condo", RIVERSIDE_CONDO_URL)),
    # MAIL_STREET and MAIL_CITY (the owner's mailing address) are on both layers
    # and never requested; nor are LAND and STRUCTURES (assessed values).
    fields=("APN,STREET_NUMBER,STREET_PREDIRECTION,STREET_NAME,STREET_TYPE,"
            "STREET_SUFFIX,UNIT_NUMBER,CLASS_CODE"),
    id_field="APN", unit_field="UNIT_NUMBER",
    is_record=_rv_is_record, address_of=_rv_address, facts=None,
    bbox=(33.413, 34.093, -117.680, -114.436),
)

#: County FIPS → its configuration. See the module docstring for the California
#: counties measured and left out, and why.
COUNTIES = {c.fips: c for c in (_CONTRA_COSTA, _SAN_JOAQUIN, _RIVERSIDE_COUNTY)}
COUNTY_FIPS = frozenset(COUNTIES)


# ── the lookup ──────────────────────────────────────────────────────────────────


def _candidates(county: _County, lat: float, lon: float, distance_m: float,
                *, deadline: float) -> list[dict]:
    """Real records at (or within ``distance_m`` of) a point, from every layer.

    Placeholders are dropped before the parcel is chosen, as Florida drops its
    blank polygons. Rows of one APN returned twice (by two layers, or as two parts
    of one parcel) are one parcel; if they disagree about its address the join is
    broken and neither is offered, the call Utah makes for its building rows.
    """
    by_id: dict[str, list[dict]] = {}
    for tag, url in county.layers:
        rows = _shared.arcgis_parcels(url, lat, lon, county.fields, distance_m,
                                      deadline=deadline, read_slice=READ_SLICE_S)
        for row in rows:
            if not county.is_record(row):
                continue
            row = dict(row, _layer=tag)
            by_id.setdefault(_text(row.get(county.id_field)), []).append(row)
    out = []
    for rows in by_id.values():
        keys = {address_key(county.address_of(r)) for r in rows}
        units = {_unit_key(r.get(county.unit_field)) for r in rows}
        if len(keys) > 1 or len(units) > 1:
            continue
        out.append(rows[0])
    return out


def _memo(county: _County, lat: float, lon: float, deadline: float):
    """``fetch(distance_m)`` for one lookup, asking each layer once per distance."""
    seen: dict[float, list[dict]] = {}

    def fetch(distance_m: float) -> list[dict]:
        if distance_m not in seen:
            seen[distance_m] = _candidates(county, lat, lon, distance_m, deadline=deadline)
        return seen[distance_m]
    return fetch


def _for_reader(county: _County, fetch, wanted: str | None):
    """``fetch`` without the records that name a unit other than the reader's.

    A condominium is one record per unit, all sharing the street address the
    comparison reads, and here (unlike Los Angeles) the units are not always
    stacked: a Riverside or Contra Costa unit can be its own footprint, so the
    point lands in ONE unit's polygon whichever unit the reader typed, and
    containment would hand them their neighbor's record. A record naming a
    different unit cannot be the reader's home, and dropping it is the sanctioned
    shape (see ``select_parcel``): it can turn "ambiguous" into "one", never admit
    a record the address check would not.
    """
    if wanted is None:
        return fetch
    return lambda d: [r for r in fetch(d)
                      if _unit_key(r.get(county.unit_field)) in (None, wanted)]


def _unit_row(county: _County, fetch, address: str, wanted: str | None) -> dict | None:
    """The one record at this address whose unit is the reader's, or None.

    The Los Angeles move, reached only when ``select_parcel`` declined: every part
    must agree — the street address by the shared comparison, the unit exactly
    (a reader with no unit matches only a record with none) — in exactly one
    record, at the point first and then within the radius.
    """
    for distance in (0, SEARCH_RADIUS_M):
        hits = [r for r in fetch(distance)
                if same_address(address, county.address_of(r))
                and _unit_key(r.get(county.unit_field)) == wanted]
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


def _facts_of(county: _County, rows: list[dict]) -> dict[str, _Facts]:
    """Facts for each record, keyed by its id — one request for Riverside's."""
    if county.facts is not None:
        return {_text(r.get(county.id_field)): county.facts(r) for r in rows}
    # Riverside: the building table, a hop of its own with its own clock. See
    # BUILDINGS_TIMEOUT.
    pins = [_text(r.get(county.id_field)) for r in rows]
    found = _rv_buildings(pins, deadline=time.monotonic() + BUILDINGS_TIMEOUT)
    if not found:
        return {}
    return {pin: _rv_facts_from(r, found.get(pin, []))
            for pin, r in zip(pins, rows)}


def _vintage(county: _County, row: dict | None) -> str:
    """What the record reflects, dated from the row's roll year where it has one."""
    if county.roll_year_field and row is not None:
        year = _text(row.get(county.roll_year_field))
        if year.isdigit() and len(year) == 4:
            return f"{county.vintage}, {year} roll"
    return county.vintage


def _record_of(county: _County, row: dict, facts: _Facts | None,
               wanted: str | None) -> AssessorRecord | None:
    if facts is None or not facts.home:
        return None
    # The area and stories describe the record's own home, so they are reported
    # only when the unit the reader named is the unit the record names — both
    # absent for a house. A unit typed at an address the roll files as one
    # dwelling is something the record does not know about.
    same_unit = _unit_key(row.get(county.unit_field)) == wanted
    sqft = facts.sqft if same_unit else None
    stories = facts.stories if same_unit else None
    if facts.year is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=county.attribution,
        data_vintage=_vintage(county, row),
        parcel_id=_text(row.get(county.id_field)) or None,
        year_built=facts.year,
        sqft=sqft,
        stories=stories,
        # No exterior wall, foundation or condition reaches the label from any of
        # the three; see "What is not read" in the module docstring.
    )


def _building_year(county: _County, fetch, address: str) -> AssessorRecord | None:
    """The year a building went up, when no single record is the reader's.

    Los Angeles's fallback: a condominium address and no unit the roll recognizes
    — the reader gave none, or one spelled some other way. The year is reported
    where every record at this street address within the radius is a home and
    they all agree on it; nothing else is, since no single record was chosen.
    """
    rows = [r for r in fetch(SEARCH_RADIUS_M) if same_address(address, county.address_of(r))]
    if not rows:
        return None
    facts = _facts_of(county, rows)
    if len(facts) != len({_text(r.get(county.id_field)) for r in rows}):
        return None
    if not all(f.home for f in facts.values()):
        return None
    years = {f.year for f in facts.values()}
    if len(years) != 1 or None in years:
        return None
    return AssessorRecord(source=county.attribution, data_vintage=_vintage(county, rows[0]),
                          parcel_id=None, year_built=next(iter(years)))


def _county_lookup(county: _County, lat: float, lon: float,
                   address: str | None) -> AssessorRecord | None:
    """The parcel, then the unit, then the building — each only if the last declined."""
    address = _canon(address)
    fetch = _memo(county, lat, lon, deadline_from(None, LOOKUP_TIMEOUT))
    wanted = _unit_key(unit_of(address))
    mine = _for_reader(county, fetch, wanted)
    row = select_parcel(mine, address, county.address_of)
    if row is not None and wanted is None and _unit_key(row.get(county.unit_field)):
        # The record is one unit of several and the reader did not say which.
        # Its year is usually the building's and its area never the reader's, so
        # it is not taken as the answer; the building path below decides.
        row = None
    if row is None and address:
        row = _unit_row(county, mine, address, wanted)
    if row is not None:
        facts = _facts_of(county, [row]).get(_text(row.get(county.id_field)))
        return _record_of(county, row, facts, wanted)
    return _building_year(county, fetch, address) if address else None


def _counties_at(lat: float, lon: float, county_fips: str | None) -> list[_County]:
    """Which counties to ask: the one the caller routed on, or — for a direct call
    that names none — every configured county whose extent holds the point. Only
    Contra Costa and San Joaquin's extents overlap, along their shared line."""
    fips = str(county_fips).strip().zfill(5) if county_fips else None
    if fips:
        return [COUNTIES[fips]] if fips in COUNTIES else []
    return [c for c in COUNTIES.values()
            if c.bbox[0] <= lat <= c.bbox[1] and c.bbox[2] <= lon <= c.bbox[3]]


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None = None,
                   _bucket: int = 0) -> AssessorRecord | None:
    try:
        found = [r for r in (_county_lookup(c, lat, lon, address)
                             for c in _counties_at(lat, lon, county_fips))
                 if r is not None]
    except _shared.TruncatedResponse:
        # Deterministic for this point, not a portal glitch: the same query will be
        # truncated the same way next time, so "no answer" is the answer.
        return None
    # Two counties answering one point is not something to choose between.
    return found[0] if len(found) == 1 else None


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher, not another's."""
    county = COUNTIES.get(county_fips)
    return county.layers[0][1] if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address, carrying the reader's unit
    where they gave one (``location.assessor_address``). ``county_fips`` is the
    county the registry routed on; without it the county is chosen from the
    layers' extents.

    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    roll has no record for. The caller then keeps whatever it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              county_fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("California assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
