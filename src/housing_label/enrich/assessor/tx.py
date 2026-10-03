#!/usr/bin/env python3
"""Texas — the seven largest counties, each from its own appraisal district's roll.

Texas has no county assessor. Each county has an appraisal district (a CAD), and
each CAD keeps and publishes its own roll; there is no state-collected roll of
the kind Florida's Department of Revenue publishes. So this adapter is a table of
seven services (``COUNTIES``), one per county, routed by the county FIPS the
registry already resolved. It answers for Harris, Dallas, Tarrant, Bexar, Travis,
Fort Bend and Montgomery: 5.84 million of the state's 12.13 million housing units
(48%, ACS).

Why not the statewide layer
---------------------------
TxGIO's StratMap Land Parcels layer
(``feature.geographic.texas.gov/.../stratmap_land_parcels_48_most_recent``) holds
every county's parcels, CC0-licensed, and it is NOT used, for a reason this
codebase treats as absolute. Its ``query`` operation is switched off — every form
tried (point, ``where``, ``objectIds``, statistics, POST, GeoJSON) answers
"Requested operation is not supported", although the layer advertises Query —
and the only operation that works, ``identify``, returns every column on every
row, including ``owner_name``, ``name_care`` and the whole mailing address, with
no field list and no way to leave them out (a ``dynamicLayers`` field list is
silently ignored). This package never fetches owner names, so it cannot use a
source that sends them unasked. If TxGIO re-enables ``query`` with an explicit
``outFields``, StratMap would add about 92 further counties with a usable year
built (measured: 94 counties at 40% or better fill, two of them Harris and
Tarrant, already here) — a second adapter, not a change to this one.

The services
------------
All keyless ArcGIS REST, ``query`` enabled, explicit ``outFields`` honored, read
2026-10-03:

  ==========  ===============================================  =======  ==========  ==================
  county      service                                          rows     year built  roll
  ==========  ===============================================  =======  ==========  ==================
  Harris      City of Houston, Parcels_Current layer 4         1.52 M   85.8%       HCAD 2025
  Fort Bend   FBCAD, Hosted/FBCADPublicData                    386 k    76.4%       current (to 2026)
  Montgomery  City of Houston, Parcels_Current layer 3         330 k    68.8%       MCAD 2026
  Dallas      DCAD, Property/ParcelQuery layer 4               845 k    76.7%       2026 (live)
  Tarrant     TAD, OD_TAD/OD_ParcelView                        759 k    84.7%       TAD 2025
  Bexar       Bexar County, Parcels layer 0                    711 k    86.6%       BCAD, about 2025
  Travis      Travis County TNR, Parcels layer 0               374 k    85.0%       TCAD, about 2023
  ==========  ===============================================  =======  ==========  ==================

Each county's vintage is stated as honestly as its layer allows, on every record:

* **Harris** is the City of Houston's republication of the HCAD roll, and it lags
  the CAD: every row says ``Tax_Year`` 2025, the layer's own text says it was
  last updated 2024-09-19 (the service was republished 2025-04-16). HCAD's own
  GIS (``gis.hctx.net``, HCAD/Parcels) carries no year built at all, so the city's
  copy is the only keyless source of it.
* **Fort Bend** was researched as the city's copy too (layer 5), and that copy is
  a year staler: no tax-year column, newest year built 2024, last updated
  2024-09-17. FBCAD publishes its own layer, which carries years to 2026,
  295,008 recorded years against the copy's 284,771, the improvement's own state
  code, and the unit in its own column, so this adapter reads FBCAD directly.
  Both were measured end to end on the same 40 homes: 33 of 39 geocoded resolved
  through each, with no wrong parcel through either; the CAD's own layer is
  kept for being current and for being the CAD's.
* **Montgomery** is the city's copy of the MCAD roll and is current: ``TAX_YEAR``
  2026 on 329,043 of 329,989 rows, years built to 2026. MCAD's own GIS host
  serves a web application, not a REST directory.
* **Dallas** is DCAD's live service (``LASTUPDATE`` 2026-10-02 on the newest
  row). Its ``REVALYR`` is the year the row was last revalued (2024–2026 by row),
  not a roll year, and the record says exactly that.
* **Tarrant**: TAD has two layers. The hosted ``Hosted/TADMap`` is a year fresher
  (tax year 2026) and is NOT used: it idles out. Probed after 0, 5, 10, 20, 40 and
  60 s without traffic, it answered in 0.44–0.48 s up to 20 s and in 5.13 and
  5.22 s at 40 and 60 s; probed every five minutes, 3 of 4 requests took
  5.11–5.14 s; and in the first verification run the first four Tarrant lookups
  failed open on exactly that. A label service that
  sees a Tarrant address every few minutes would pay five seconds or lose the
  answer nearly every time. ``OD_ParcelView`` on the same host, the 2025 roll
  (its ``Appraisal_`` column), answered the same idle pattern in 0.42–0.53 s.
* **Bexar** publishes no tax year, and its metadata is stale text ("Last update:
  October 2021 ... Next update: September/October 2023"). The data is newer:
  12,813 parcels carry a 2024 year built and one carries 2025, so it is about the
  2025 roll. The record says "newest year built in the layer 2024, as measured".
  BCAD's own map service (``maps.bcad.org``) carries no year built.
* **Travis** publishes no tax year, and it is the stalest: the newest year built
  in the layer is 2023, on 123 parcels, against 6,549 in 2022 — the 2023 roll,
  three years old. A house built since is a vacant lot in it (class C1, which
  answers nothing), and a house rebuilt since still carries the old house's year:
  the one way this county can be wrong that no parcel check can catch. The record
  carries the measured newest year, so a reader can date it.

Travis's year column, and what it means
---------------------------------------
``F1year_imprv`` is labeled "First year 1st Floor Improvement". TCAD records a
house as improvement segments, each with its own year — the first-floor main area
("1ST"), a second floor, an addition — and this column is the first-floor main
area's year: the year the original house went up, not the year of a later
addition, which is a different segment. Checked against Austin landmarks with
documented dates: the Neill-Cochran House (2310 San Gabriel St, built 1855) and
Westhill (1703 West Ave, 1855) read 1855; the Walter and John Bremond houses of
the Bremond Block (700 Guadalupe St and 402 W 7th St, 1886–87) read 1900, the
round year CADs write for an undocumented nineteenth-century house — and earlier
than any addition to them. None read a year after 1900. Both
1855 houses are filed F5 (commercial residence conversion: museums and offices),
so the adapter itself reports neither; they are evidence about the column.

What a row says about homes
---------------------------
Every CAD files each account under the Comptroller's state property category
(Texas Property Tax Assistance Property Classification Guide, publication
96-313): A single-family residential — houses, townhouses AND condominiums ("Do
not classify condominiums or townhomes as Category B ... They are Category A") —,
B multifamily, C vacant, D open-space land, E rural land and its improvements,
F commercial and industrial, J utilities, L business personal property, M mobile
homes, O residential inventory, S special inventory, X exempt. The CADs add
suffixes and local codes, so each county's reader maps its own column onto five
readings (``ONE_HOME``, ``CONDO``, ``MULTI``, ``SILENT``, ``NOT_A_HOME``):

* **Floor area and stories need an explicit single-family code** (A1, or a
  mobile home on its own land), because A also holds condominiums — plus the
  county's own one-building evidence where it has one: Harris's ``BUILDCOUNT`` of
  1 and a single residential building type, Bexar's one ``Houses`` and a main
  building area equal to the parcel's total. Nothing is ever divided.
* **Condominium units** — Harris's own Z1–Z5 (63,491 rows, all but 6 typed
  "Residential Condo"), DCAD's "SFR - CONDOMINIUMS", the other A sub-codes — report the year
  and nothing else. A unit's floor area is not what the label means by the home.
* **No year from a record that says no one lives there**: vacant land, open-space
  land, commercial and industrial (including Travis's F5 conversions), utilities,
  minerals, inventory; and Bexar's explicit zero ``Houses`` on any record that
  is not multifamily (an apartment complex writes 0 houses). An exempt class,
  E, O and a blank are silence, not refusal: X is an exemption, not a use.
* **Business personal property is not a parcel.** DCAD files 80,394 "COMMERCIAL
  BPP" accounts on the polygon, and under the address, of the parcel they sit in,
  and TAD does the same with L1; offered as candidates, one would make the house
  beneath it ambiguous. They are dropped as non-records.
* DCAD's ``CLASSCD`` is DCAD's own numbering, read off its 32 values; TAD's
  ``Property_C`` and the rest are the Comptroller's. Montgomery appends an
  exemption flag ("A1XV", 331 houses) that is stripped before reading.

Stacks, and the address two accounts share
------------------------------------------
``select_parcel`` refuses more than one candidate under the point, and Texas
produces that two ways that are not ambiguity about which building:

* **Condominium stacks.** 2200 Willowick Rd, Houston is 115 unit rows on one
  footprint; Dallas files a complex's units on the complex's polygon. Rows at one
  street address (unit set aside) are offered as ONE candidate when every row
  agrees on the year built and every row is a home; that candidate carries the
  year alone, and no parcel id unless all rows share one. Rows that disagree (6108
  Abrams Rd, Dallas: units recorded as 1984, 2005, 2019 and 2021) are offered
  as they are and refused. A reader who typed a unit gets that unit's row (Harris
  writes it bare, "829 YALE ST 504"), with the year and still no floor area.
* **One address, two accounts.** Typed "16417 Hubenak Rd, Needville" landed in an
  86-acre farm whose 1930 farmhouse has that address; so does the 1-acre homesite
  cut out of it, a 1984 house more than 80 m away, which was the home sampled.
  Containment confirmed by address chose the farmhouse — the one wrong parcel the
  first verification run found. So every confirmed answer is checked against a
  second search: the rows within ``TWIN_RADIUS_M`` (1 km) whose address carries
  the same house number, an attribute filter that keeps the answer to a handful
  of rows. The address must name exactly one candidate there, or the lookup is
  refused (or answered with the year alone, where the twins agree on it).

Addresses
---------
Every service keeps the street address in one column. Harris, Dallas, Tarrant
and Bexar write the street alone; Fort Bend and Montgomery append the city after
a comma, which the shared comparison already sets aside. Bexar often omits the
street type ("509 KING WILLIAM"), which the shared comparison tolerates. Two
spellings are genuinely local and handled here, each with a test: TAD writes
Trail as "TR" (and Terrace as "TERR", so in this roll TR is only Trail;
``_tarrant_address``), and Travis writes "W 1316 6 ST   TX 78701" — the
directional before the number, the city optional — which ``_travis_address``
rebuilds as "1316 W 6 ST". A Travis city it does not know stays in the string,
and the address then matches nothing: a refusal, never a wrong match.

Not carried
-----------
No requested column holds an exterior wall, a foundation or a condition grade the
label can read, so those stay empty. Effective years and remodel years
(``yr_remodel`` in Harris) are not requested.

Timing
------
Measured through the product's own HTTP session over the verification run below
(307 geocoded homes, all seven services):

  ==========================================  ======  ======  ======  ======
  request                                     median     p90     p95     max
  ==========================================  ======  ======  ======  ======
  "which parcel is this dot inside?"           0.09 s  0.12 s  0.16 s  1.24 s
  "what is within 80 m of this dot?"           0.10 s  0.15 s  0.16 s  0.42 s
  "who else has this house number nearby?"     0.11 s  0.15 s  0.16 s  0.43 s
  whole lookup (up to three requests)          0.29 s  0.42 s  0.48 s  1.44 s
  ==========================================  ======  ======  ======  ======

DCAD is the slowest host (buffer median 0.15 s). Every maximum above 0.6 s is a
host's first request of the run, which opened the connection: a fresh TLS
connection took 0.39–0.81 s across the seven hosts in probes five minutes apart,
and the connect half of the timeout has the whole budget anyway. So Texas keeps
the SHARED clock — a one-second read slice that no read among the 869 requests
came near, and a four-second budget against a worst lookup of 1.44 s (the run's
very first, connection included). ``READ_SLICE_S`` and
``LOOKUP_TIMEOUT`` are named so every request visibly passes them, and a test
pins their sum under ``config.UPSTREAM_HOST_BUDGET``.

What the adapter is worth, end to end
-------------------------------------
315 homes drawn at random from the services themselves (random object ids across
each layer; residential class, a single recorded year, a house number), weighted
toward the big counties, geocoded through the Census matcher and
``assessor_address`` exactly as the product does, then looked up with the
geocoder's county:

  ==========  ======  ========  ========  ==========  =========  ==========
  county      drawn   geocoded  resolved  wrong       year       floor area
                                          parcel      exact      exact
  ==========  ======  ========  ========  ==========  =========  ==========
  Harris          60        58        53           0      53/53       51/51
  Dallas          45        44        39           0      39/39       37/37
  Tarrant         45        44        38           0      38/38       38/38
  Bexar           45        45        42           0      42/42       38/38
  Travis          40        39        34           0      34/34         —
  Fort Bend       40        39        33           0      33/33       31/31
  Montgomery      40        38        29           0      29/29       29/29
  **all**      **315**   **307**   **268**      **0**  **268/268**  **224/224**
  ==========  ======  ========  ========  ==========  =========  ==========

Every geocode was routed to its own county. 268 of 307 geocoded homes resolved
(87%); 71 also got a story count (Dallas and Bexar). Montgomery is the weakest
(29 of 38) because its rural addresses geocode farthest from their parcels; it
is kept, since the misses are refusals, not wrong answers. One answer (Travis,
3900 Threadgill St) came from two agreeing accounts at one address, reported as
the year alone.

The 39 that did not resolve: 34 geocodes more than 80 m from their parcel or
spelled differently from the roll (the Census matcher's "CHESTALYNN CT" for TAD's
"CHESTALYN CT", "ROUND OAK LN" for MCAD's "ROUND OAKS LN", "APRIL WATERS W" with
the roll's "DR" dropped); 3 addresses two accounts share within 80 m (1310 Winston
Dr, Richmond: a 1953 house and a second account built 1990); 1 Dallas condominium
complex (4279 Madera Rd, Irving) whose 301 unit rows, each with its own street
address, sit on one polygon, refused as ambiguous under the point; and the
Hubenak farm, refused by the same-address search. 8 addresses the Census
matcher did not find.

Privacy, and why the field lists are short
------------------------------------------
Every one of these layers carries owner names, and most carry mailing addresses,
deed references and values: ``OWNER``/``OWNER_ADD`` (Houston), ``ownername``/
``oaddr1`` (FBCAD), ``OWNERNME1``/``PSTLADDRESS`` (DCAD), ``Owner_Name``
(TAD), ``Owner``/``AddrLn1`` (Bexar), ``py_owner_name`` and ``deed_date``
(Travis). None is an input to the label, and Tax Code §25.025 makes the pairing
of certain people's names with their home addresses confidential in these very
records — one more reason a field list never asks for a name. Six to eight
columns are requested by name per county; the shared helper refuses ``*``.
Nothing from these services is written into the repository.

License and public status
-------------------------
No license text was found for any of the seven services: ``licenseInfo`` is
empty on the Houston, DCAD, Bexar and Travis services; TAD's item carries only a
disclaimer ("for informational purposes only and may not have been prepared for
or be suitable for legal, engineering, or surveying purposes"); DCAD's GIS page
(https://www.dallascad.org/GISDataProducts.aspx) carries the same disclaimer and
offers the same data as free downloads; Travis County's site disclaimer
(https://www.traviscountytx.gov/disclaimer) provides its information "as is";
Bexar's service credits BCAD and states no terms; FBCAD's states none. Nothing
read restricts querying, caching or commercial use. Appraisal records are public
information in Texas: information an appraisal district collects or maintains in
its official business is "public information" (Government Code §552.002(a)),
available to the public (§552.021), with the exceptions that touch these rolls —
rendition and other private data (Tax Code §22.27) and the name-to-home-address
confidentiality of §25.025 — falling on columns this adapter does not request.
Public status is not an open license, and a CAD can assert rights in its
compilation, so the posture is the one every adapter takes: query live, cache
in process, bundle nothing; a legal read before a commercial launch is prudent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    SUFFIXES, address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

NAME = "Texas county appraisal districts"
ATTRIBUTION = ("Texas county appraisal districts (Harris, Fort Bend, Montgomery, "
               "Dallas, Tarrant, Bexar, Travis) via their public parcel services, "
               "keyless")
DATA_VINTAGE = "Texas appraisal district rolls, one service per county"

_HOUSTON = ("https://geohwp.houstontx.gov/arcgis/rest/services/03_BaseData_External"
            "/Parcels_Current/MapServer")
#: Harris County: the City of Houston's republication of the HCAD roll.
HARRIS_URL = f"{_HOUSTON}/4/query"
#: Montgomery County: the City of Houston's republication of the MCAD roll.
MONTGOMERY_URL = f"{_HOUSTON}/3/query"
#: Fort Bend County: FBCAD's own public parcel layer. The City of Houston's copy
#: (``_HOUSTON`` layer 5) was measured and replaced; see "Fort Bend" above.
FORT_BEND_URL = ("https://gisweb.fbcad.org/arcgis/rest/services/Hosted"
                 "/FBCADPublicData/FeatureServer/0/query")
#: Dallas County: DCAD's own parcel-query layer ("ParcelPublishing").
DALLAS_URL = ("https://maps.dcad.org/prdwa/rest/services/Property/ParcelQuery"
              "/MapServer/4/query")
#: Tarrant County: TAD's own parcel map service ("ParcelView").
TARRANT_URL = ("https://tad.newedgeservices.com/arcgis/rest/services/OD_TAD"
               "/OD_ParcelView/MapServer/0/query")
#: Bexar County: the county's parcel layer, joined to the BCAD roll.
BEXAR_URL = "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0/query"
#: Travis County: the county's (TNR) tax-map layer, joined to the TCAD roll.
TRAVIS_URL = ("https://taxmaps.traviscountytx.gov/arcgis/rest/services/Parcels"
              "/MapServer/0/query")

#: How long a service may go quiet before the silence is a stall, and the budget
#: for a whole lookup. See "Timing" in the module docstring.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT


# ── what a row says about homes ────────────────────────────────────────────────
#
# Every appraisal district files each account under the Comptroller's state
# property category (Property Classification Guide, 96-313): A single-family
# residential (condominiums and townhomes included), B multifamily, C vacant lots,
# D qualified open-space land, E rural land and its improvements, F commercial and
# industrial, G minerals, J utilities, L business personal property, M mobile
# homes, O residential inventory, S special inventory, X totally exempt. The CADs
# add numeric suffixes (A1, B2, F1H) and some add local codes, so each county's
# reader maps its own column onto one of these five readings:

#: One dwelling in one building, as the roll states it: a single-family house, a
#: townhouse on its own lot, a mobile home. Year, floor area and stories.
ONE_HOME = "one home"
#: A unit, or a building of units. The year is the building's and is reported;
#: the floor area and stories are a unit's or the building's, never "the home".
CONDO = "condominium"
#: Multifamily (duplex and up). The year is reported; the area is all the homes.
MULTI = "multifamily"
#: The class says nothing either way: rural land with improvements (E), builder
#: inventory (O), totally exempt (X: an exemption, not a use — a 100% disabled
#: veteran's homestead is totally exempt under Tax Code §11.131, and Fort Bend's
#: XV rows include ordinary houses beside churches), a blank. The year is
#: reported, the area is not.
SILENT = "silent"
#: The class says no one lives here: vacant land, open-space land, commercial or
#: industrial, minerals, utilities, inventory. Nothing is reported.
NOT_A_HOME = "not a home"
#: Not a parcel at all: a business-personal-property account (category L — a
#: shop's fixtures, an aircraft) filed on the polygon of the parcel it sits on,
#: under that parcel's address. A record of nothing about a building, and left in
#: it would make the real parcel beneath look ambiguous, so the row is dropped as
#: a non-record, the sanctioned shape (see ``select_parcel``).
PERSONAL_PROPERTY = "personal property"

#: Comptroller category letter → reading, for the part every CAD shares. A
#: county's reader refines A (which is houses AND condominiums) itself.
_CATEGORY = {
    "A": CONDO,          # refined per county: only an explicit single-family code
                         # is ONE_HOME, because A also holds condominiums
    "B": MULTI,
    "C": NOT_A_HOME,
    "D": NOT_A_HOME,     # D1 open-space land, D2 farm and ranch improvements on it
    "E": SILENT,
    "F": NOT_A_HOME,
    "G": NOT_A_HOME,
    "J": NOT_A_HOME,
    "L": PERSONAL_PROPERTY,
    "M": ONE_HOME,
    "N": NOT_A_HOME,
    "O": SILENT,
    "S": NOT_A_HOME,
    "X": SILENT,
}

# A trailing exemption flag on Montgomery's codes: "A1XV" is an A1 house with a
# total exemption (331 houses carry it), "C1XV" an exempt vacant lot.
_EXEMPTION_FLAG = re.compile(r"^([A-WYZ]\d?)X[A-Z]$")
# A leading digit on Harris's open-space code: "1D1" (4,206 rows) is D1.
_LEADING_DIGIT = re.compile(r"^\d([A-Z]\d?)$")


def _state_code(raw) -> str:
    """The Comptroller code in a CAD's column, upper-cased and stripped of the
    space padding Tarrant and Dallas carry, of Montgomery's exemption flag and of
    Harris's leading digit."""
    code = " ".join(str(raw or "").split()).upper()
    m = _EXEMPTION_FLAG.match(code) or _LEADING_DIGIT.match(code)
    return m.group(1) if m else code


def _reading(code: str, one_home_codes: frozenset[str]) -> str:
    """The reading of a Comptroller state code; see the constants above."""
    if not code or code == "NULL":
        return SILENT
    if code in one_home_codes:
        return ONE_HOME
    return _CATEGORY.get(code[0], SILENT)


# ── small parsers ──────────────────────────────────────────────────────────────


def _year(raw) -> int | None:
    """An actual year built, or None.

    Accepts a number or a numeric string. ``0``, blank and Bexar's literal string
    ``'NULL'`` are "not recorded". Harris writes every building on a parcel into
    one comma-separated string ("1968,2004,2007"): the year is reported only when
    every building agrees, because which of them is the home is not recorded.
    """
    if raw is None:
        return None
    parts = {p.strip() for p in str(raw).split(",")} - {""}
    years = set()
    for p in parts:
        y = num(p)
        if y is None or not y or not float(y).is_integer():
            return None
        years.add(int(y))
    if len(years) != 1:
        return None
    y = years.pop()
    return y if EARLIEST_PLAUSIBLE_YEAR <= y <= 2100 else None


def _area(raw) -> float | None:
    """A positive floor area, or None. A comma list (Harris, several buildings)
    is the sum of buildings and is never one home's area."""
    if raw is None or "," in str(raw):
        return None
    area = num(str(raw).strip())
    return area if area is not None and area > 0 else None


_STORY_WORDS = {"ONE STORY": 1, "TWO STORIES": 2, "THREE STORIES": 3}


def _stories(raw) -> int | None:
    """A whole story count from Dallas's wording or Bexar's number. Half stories
    ("ONE AND ONE HALF STORIES", "1.5") have no whole-number reading."""
    text = " ".join(str(raw or "").split()).upper()
    if text in _STORY_WORDS:
        return _STORY_WORDS[text]
    n = num(text)
    if n is not None and float(n).is_integer() and 1 <= n <= 4:
        return int(n)
    return None


def _clean(raw) -> str:
    return " ".join(str(raw or "").split())


def _unmarked_unit(address: str) -> str | None:
    """A unit written with no marker after the street type, or None.

    Harris writes a condominium unit bare: "829 YALE ST 504", "2200 WILLOWICK RD
    16J". ``address_key`` already drops such a token for comparison (a trailing
    digit-bearing token right after a street type); this names it, so the row can
    be recognized as a unit record and a typed unit can be matched against it.
    """
    tokens = address.split(",")[0].lower().split()
    if len(tokens) >= 3 and tokens[-2] in SUFFIXES and any(c.isdigit() for c in tokens[-1]):
        return tokens[-1]
    return None


def _unit(address: str, explicit=None) -> str | None:
    """The unit a row names: its own unit column where it has one, else what its
    address carries, marked ("# B") or bare ("ST 504")."""
    own = _clean(explicit)
    if own:
        return own.lower()
    marked = unit_of(address)
    if marked:
        return marked.lower()
    return _unmarked_unit(address)


# ── the counties ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _County:
    """One county's service and how to read its rows."""

    name: str
    url: str
    fields: str
    source: str
    read: Callable[[dict], dict | None]
    #: The column the street address is in, for the same-address search.
    address_field: str


def _candidate(pid, address, *, unit=None, year=None, reading=SILENT, sqft=None,
               stories=None, vintage=None) -> dict | None:
    """The normalized shape every county's reader returns, or None for a row that
    is a record of nothing (no identifier)."""
    pid = _clean(pid)
    if not pid or reading == PERSONAL_PROPERTY:
        return None
    address = _clean(address)
    unit = _unit(address, unit)
    one = reading == ONE_HOME and not unit
    return {
        "pid": pid, "address": address or None, "unit": unit, "reading": reading,
        "year": year if reading != NOT_A_HOME else None,
        # Area and stories only where the row is one home in one building and
        # names no unit. A reader passes them already gated on its own evidence.
        "sqft": sqft if one else None,
        "stories": stories if one else None,
        "vintage": vintage,
    }


# Harris — the City of Houston's "Current HCAD Parcels".
#
# HCAD codes condominium units Z1–Z5 (63,491 rows, all but 6 typed "Residential
# Condo"), so a Z is a unit. A1 is single-family, A2 a mobile home on its own land. A third
# piece of evidence is required for floor area, because HCAD aggregates every
# building on a parcel into one row: BUILDCOUNT must be 1 and the building type a
# single residential type (not "Residential Duplex,Residential Single Family").
_HARRIS_ONE = frozenset({"A1", "A2"})
_HARRIS_ONE_TYPES = frozenset({"residential single family", "residential townhome",
                               "residential mobile homes"})


def _read_harris(r: dict) -> dict | None:
    code = _state_code(r.get("STATECLASS"))
    reading = CONDO if code.startswith("Z") else _reading(code, _HARRIS_ONE)
    one_building = (num(r.get("BUILDCOUNT")) == 1
                    and _clean(r.get("BLDTYPE_DS")).lower() in _HARRIS_ONE_TYPES)
    if reading == ONE_HOME and not one_building:
        reading = SILENT
    roll = _year(r.get("TAX_YEAR"))
    return _candidate(
        r.get("PARCEL_ID"), r.get("ADDRESS"), year=_year(r.get("YEAR_BUILT")),
        reading=reading, sqft=_area(r.get("IMPR_SQ_FT")),
        vintage=(f"HCAD {roll} appraisal roll, as republished by the City of Houston"
                 if roll else "HCAD appraisal roll, as republished by the City of "
                 "Houston"))


# Fort Bend — FBCAD's own public parcel layer. ``building_sptb_code`` is the
# Comptroller code of the improvement, ``land_state_code`` that of the land; the
# improvement's is the statement about the building, and the land's is read only
# where the improvement carries none.
_FORT_BEND_ONE = frozenset({"A1", "A2"})


def _read_fort_bend(r: dict) -> dict | None:
    code = _state_code(r.get("BUILDING_SPTB_CODE")) or _state_code(r.get("LAND_STATE_CODE"))
    return _candidate(
        r.get("QUICKREFID") or r.get("PROPNUMBER"), r.get("SITUS"),
        unit=r.get("SITUSAPT"), year=_year(r.get("YEARBUILT")),
        reading=_reading(code, _FORT_BEND_ONE), sqft=_area(r.get("TOTSQFTLVG")),
        vintage=("FBCAD public parcel data (no tax year published; newest year "
                 "built in the layer 2026, as measured 2026-10-03)"))


# Montgomery — the City of Houston's "Current MCAD Parcels".
_MONTGOMERY_ONE = frozenset({"A1", "A2"})


def _read_montgomery(r: dict) -> dict | None:
    roll = _year(r.get("TAX_YEAR"))
    return _candidate(
        r.get("PARCEL_ID"), r.get("ADDRESS"), year=_year(r.get("YEAR_BUILT")),
        reading=_reading(_state_code(r.get("STATECLASS")), _MONTGOMERY_ONE),
        sqft=_area(r.get("IMPR_SQ_FT")),
        vintage=(f"MCAD {roll} appraisal roll, as republished by the City of Houston"
                 if roll else "MCAD appraisal roll, as republished by the City of "
                 "Houston"))


# Dallas — DCAD's ParcelQuery layer. CLASSCD is DCAD's own code, not the
# Comptroller's, and its description travels in CLASSDSCRP; read off the layer's
# 32 values (2026-10-03):
_DALLAS_CLASS = {
    "1": ONE_HOME,       # SINGLE FAMILY RESIDENCES
    "2": ONE_HOME,       # SFR - TOWNHOUSES
    "3": CONDO,          # SFR - CONDOMINIUMS
    "4": ONE_HOME,       # MOBILE HOME ON OWNERS LAND
    "35": ONE_HOME,      # MOBILE HOMES ON LEASED SPACES
    "5": MULTI,          # MFR - APARTMENTS
    "6": MULTI,          # MFR - DUPLEXES
    "15": SILENT,        # RURAL LAND AND IMPROVEMENTS NON QUALIFIED
    "40": SILENT,        # RESIDENTIAL - IMPROVEMENTS AS INVENTORY
    "0": SILENT,         # UNASSIGNED
}
# Everything else is a statement that no one lives there — vacant lots and tracts
# (7, 8, 9, 10, 39), open-space land (11), commercial and industrial improvements
# (17, 18), utilities and railroads (22–29, 49), minerals (41), special inventory
# (46) — except the personal-property accounts (31 COMMERCIAL BPP, 32 INDUSTRIAL
# BPP, 33 WATERCRAFT, 34 AIRCRAFT), which are not parcels at all: 80,394 business
# accounts filed on the polygon, and under the address, of the parcel they sit in.
for _code in ("31", "32", "33", "34"):
    _DALLAS_CLASS[_code] = PERSONAL_PROPERTY


def _read_dallas(r: dict) -> dict | None:
    code = _clean(r.get("CLASSCD"))
    revalued = _year(r.get("REVALYR"))
    return _candidate(
        r.get("PARCELID"), r.get("SITEADDRESS"), unit=r.get("UNIT"),
        year=_year(r.get("RESYRBLT")), reading=_DALLAS_CLASS.get(code, NOT_A_HOME),
        sqft=_area(r.get("RESFLRAREA")), stories=_stories(r.get("RESSTRTYP")),
        vintage=(f"DCAD appraisal records (ParcelQuery), last revalued {revalued}"
                 if revalued else "DCAD appraisal records (ParcelQuery)"))


# Tarrant — TAD's "ParcelView" map service: TAD's parcel polygons joined to its
# published PropertyData-FullSet. ``Property_C`` is the Comptroller code (A1
# single-family, A2 mobile home on its land, A3 condominium and townhouse units,
# B multifamily, L1 business personal property, ...), ``Year_Built`` and
# ``Living_Are`` space-padded strings, ``Appraisal_`` the roll year. TAD's newer
# hosted layer (Hosted/TADMap, a year fresher) was measured and not used; see
# "Tarrant" in the module docstring.
_TARRANT_ONE = frozenset({"A1", "A2"})


def _tarrant_address(raw) -> str:
    """TAD's situs address with its one source-specific spelling made standard.

    TAD writes Trail as "TR" ("2828 CONCHO TR"), where the Census matcher writes
    "TRL"; the shared table leaves "TR" out on purpose, because elsewhere it can
    mean Terrace — but TAD spells Terrace "TERR" ("1509 CARSWELL TERR"), so in
    this roll "TR" is only ever Trail. Without this, 2 of 44 geocoded Tarrant homes
    in the verification run were refused.
    """
    tokens = _clean(raw).split()
    if len(tokens) >= 3 and tokens[-1].upper() == "TR":
        tokens[-1] = "TRL"
    return " ".join(tokens)


def _read_tarrant(r: dict) -> dict | None:
    roll = _year(r.get("APPRAISAL_"))
    return _candidate(
        r.get("TAXPIN"), _tarrant_address(r.get("SITUS_ADDR")),
        year=_year(r.get("YEAR_BUILT")),
        reading=_reading(_state_code(r.get("PROPERTY_C")), _TARRANT_ONE),
        sqft=_area(r.get("LIVING_ARE")),
        vintage=f"TAD {roll} appraisal roll" if roll else "TAD appraisal roll")


# Bexar — the county's parcel layer. ``Houses`` counts the parcel's houses, which
# is the one-dwelling evidence; ``GBA`` is the main building's area and
# ``TOT_GBA`` all of them, so the two must agree as well.
_BEXAR_ONE = frozenset({"A1", "A2"})
# Neither the Bexar nor the Travis layer carries a tax year, and both describe
# themselves out of date, so the newest year built either holds is stated with the
# date it was measured: a reader can then date the roll rather than trust it.
_BEXAR_VINTAGE = ("BCAD roll via Bexar County GIS (no tax year published; newest "
                  "year built in the layer 2024, as measured 2026-10-03)")


def _read_bexar(r: dict) -> dict | None:
    pid = r.get("PROPID")
    pid = str(int(pid)) if isinstance(pid, (int, float)) and pid else pid
    code = _state_code(r.get("STATE_CD"))
    reading = _reading(code, _BEXAR_ONE)
    houses = num(r.get("HOUSES"))
    # An explicit zero houses on a record that is not multifamily is the roll
    # saying no dwelling stands there (an apartment complex records its buildings
    # elsewhere and reads 0). The same rule as Florida's dwelling count.
    if houses == 0 and reading != MULTI:
        reading = NOT_A_HOME
    gba, total = _area(r.get("GBA")), _area(r.get("TOT_GBA"))
    one = houses == 1 and gba is not None and gba == total
    if reading == ONE_HOME and not one:
        reading = SILENT
    return _candidate(
        pid, r.get("SITUS"), year=_year(r.get("YRBLT")), reading=reading,
        sqft=gba, stories=_stories(r.get("STORIES")),
        vintage=_BEXAR_VINTAGE)


# Travis — the county's tax-map layer. ``situs_address`` is written "<predir>
# <number> <street> [<city>] TX <zip>", with the leading directional BEFORE the
# number ("W 1316 6 ST   TX 78701" is 1316 W 6th St), and ``situs_street`` holds
# "TX" on every row sampled, so the address is rebuilt from the one column.
_TRAVIS_ONE = frozenset({"A1", "A2"})
_TRAVIS_VINTAGE = ("TCAD roll via Travis County tax maps (no tax year published; "
                   "newest year built in the layer 2023, as measured 2026-10-03)")
_TRAVIS_CITIES = tuple(sorted((tuple(c.split()) for c in (
    "AUSTIN", "PFLUGERVILLE", "MANOR", "LAKEWAY", "LAGO VISTA", "WEST LAKE HILLS",
    "ROLLINGWOOD", "SUNSET VALLEY", "BEE CAVE", "BRIARCLIFF", "CREEDMOOR",
    "JONESTOWN", "MUSTANG RIDGE", "POINT VENTURE", "SAN LEANNA", "THE HILLS",
    "VOLENTE", "WEBBERVILLE", "ELGIN", "DEL VALLE", "LEANDER", "CEDAR PARK",
    "ROUND ROCK", "SPICEWOOD", "DRIPPING SPRINGS", "DRIPPING SPGS", "MANCHACA",
    "BUDA", "KYLE", "COUPLAND", "HUTTO", "BASTROP", "CEDAR CREEK")),
    key=len, reverse=True))
_LEADING_DIRECTIONS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
_ZIP = re.compile(r"^\d{5}(-\d{4})?$")


def _travis_address(raw) -> str:
    """Travis's situs string as an ordinary street address.

    "W 1316 6 ST   TX 78701" → "1316 W 6 ST"; "  1707 BAY HILL DR AUSTIN TX
    78746" → "1707 BAY HILL DR". A city this table does not know stays in the
    string, where it makes the address fail to match anything — a refusal, never
    a wrong match. A city is removed only when a number and a name would remain,
    so a street that is itself named after a city survives.
    """
    tokens = _clean(raw).upper().split()
    if tokens and _ZIP.match(tokens[-1]):
        tokens.pop()
    if tokens and tokens[-1] == "TX":
        tokens.pop()
    for city in _TRAVIS_CITIES:
        n = len(city)
        if len(tokens) > n + 1 and tuple(tokens[-n:]) == city:
            tokens = tokens[:-n]
            break
    if len(tokens) >= 3 and tokens[0] in _LEADING_DIRECTIONS and tokens[1].isdigit():
        tokens[0], tokens[1] = tokens[1], tokens[0]
    return " ".join(tokens)


def _read_travis(r: dict) -> dict | None:
    return _candidate(
        r.get("PROP_ID"), _travis_address(r.get("SITUS_ADDRESS")),
        year=_year(r.get("F1YEAR_IMPRV")),
        reading=_reading(_state_code(r.get("LAND_STATE_CD")), _TRAVIS_ONE),
        vintage=_TRAVIS_VINTAGE)


#: County FIPS → its service. Field lists are explicit and carry no owner name,
#: mailing address, deed, sale or value column; see "Privacy" in the docstring.
COUNTIES = {
    "48201": _County(
        "Harris", HARRIS_URL,
        "PARCEL_ID,ADDRESS,TAX_YEAR,STATECLASS,YEAR_BUILT,IMPR_SQ_FT,BLDTYPE_DS,"
        "BUILDCOUNT",
        "Harris Central Appraisal District, via City of Houston GIS (keyless)",
        _read_harris, "ADDRESS"),
    "48157": _County(
        "Fort Bend", FORT_BEND_URL,
        "propnumber,quickrefid,situs,situsapt,yearbuilt,totsqftlvg,"
        "building_sptb_code,land_state_code",
        "Fort Bend Central Appraisal District public parcel data (keyless)",
        _read_fort_bend, "situs"),
    "48339": _County(
        "Montgomery", MONTGOMERY_URL,
        "PARCEL_ID,ADDRESS,TAX_YEAR,STATECLASS,YEAR_BUILT,IMPR_SQ_FT",
        "Montgomery Central Appraisal District, via City of Houston GIS (keyless)",
        _read_montgomery, "ADDRESS"),
    "48113": _County(
        "Dallas", DALLAS_URL,
        "PARCELID,SITEADDRESS,UNIT,CLASSCD,RESYRBLT,RESFLRAREA,RESSTRTYP,REVALYR",
        "Dallas Central Appraisal District ParcelQuery (keyless)",
        _read_dallas, "SITEADDRESS"),
    "48439": _County(
        "Tarrant", TARRANT_URL,
        "TAXPIN,Situs_Addr,Property_C,Year_Built,Living_Are,Appraisal_",
        "Tarrant Appraisal District ParcelView (keyless)",
        _read_tarrant, "Situs_Addr"),
    "48029": _County(
        "Bexar", BEXAR_URL,
        "PropID,Situs,YrBlt,GBA,TOT_GBA,Stories,State_cd,Houses",
        "Bexar Appraisal District roll, via Bexar County GIS (keyless)",
        _read_bexar, "Situs"),
    "48453": _County(
        "Travis", TRAVIS_URL,
        "PROP_ID,situs_address,F1year_imprv,land_state_cd",
        "Travis Central Appraisal District roll, via Travis County GIS (keyless)",
        _read_travis, "situs_address"),
}
COUNTY_FIPS = frozenset(COUNTIES)


# ── choosing the parcel ────────────────────────────────────────────────────────


def _rows(county: _County, lat: float, lon: float, distance_m: float,
          *, deadline: float, where: str | None = None) -> list[dict]:
    """Normalized candidate rows at (or within ``distance_m`` of) a point.

    Column names are upper-cased first: the Houston services answer
    ``TAX_YEAR`` and ``Year_Built`` for columns their own metadata spells
    ``Tax_Year`` and ``YEAR_BUILT``. Rows that are records of nothing (no
    identifier, a personal-property account) are dropped, and a row repeated
    verbatim — one parcel per polygon part — is kept once.
    """
    raw = _shared.arcgis_parcels(county.url, lat, lon, county.fields, distance_m,
                                 deadline=deadline, read_slice=READ_SLICE_S,
                                 where=where)
    out, seen = [], set()
    for row in raw:
        cand = county.read({str(k).upper(): v for k, v in row.items()})
        if cand is None:
            continue
        key = tuple(sorted(cand.items()))
        if key not in seen:
            seen.add(key)
            out.append(cand)
    return out


def _collapse(cands: list[dict]) -> list[dict]:
    """One candidate per street address where every row at it agrees.

    A condominium stack is many unit rows on one footprint (115 at 2200 Willowick
    Rd, Houston), and Dallas files a condominium's units as rows on the complex's
    polygon. Offered raw they are many candidates, and ``select_parcel`` refuses —
    so no condominium would ever answer. Picking one unit would be the confident
    guess this layer exists to refuse. So rows sharing a street address (unit set
    aside) are offered as ONE candidate only when they agree on the year built
    and every one of them is somebody's home; that candidate carries the year and
    nothing else — no floor area, no stories, since those belong to one unit, and
    no parcel id unless all rows share it. Rows that disagree (6108 Abrams Rd,
    Dallas: units of 1984, 2005, 2019 and 2021) are offered as they are, and the
    ambiguity is refused downstream, exactly as before.
    """
    groups: dict = {}
    order = []
    for c in cands:
        key = address_key(c["address"])
        key = key if key is not None else ("pid", c["pid"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)
    out = []
    for key in order:
        rows = groups[key]
        years = {r["year"] for r in rows}
        if (len(rows) == 1 or len(years) != 1 or None in years
                or any(r["reading"] == NOT_A_HOME for r in rows)):
            out.extend(rows)
            continue
        pids = {r["pid"] for r in rows}
        vintages = {r["vintage"] for r in rows}
        out.append({
            "pid": pids.pop() if len(pids) == 1 else None,
            "address": rows[0]["address"], "unit": None, "reading": CONDO,
            "year": years.pop(), "sqft": None, "stories": None,
            "vintage": vintages.pop() if len(vintages) == 1 else None,
            "stack": len(rows),
        })
    return out


def _same_unit(cand: dict, unit: str) -> bool:
    own = cand.get("unit")
    return own is not None and own.lower().lstrip("#") == unit.lower().lstrip("#")


def _for_unit(rows: list[dict], unit: str) -> list[dict]:
    """The rows that could be the typed unit's.

    A row naming a DIFFERENT unit cannot be. And where some row names the typed
    unit itself, the rows naming no unit at all — a condominium's master record,
    its common element — are not the reader's either: Fort Bend files "2710
    Grants Lake Blvd #M1" beside two unit-less records at 2710 Grants Lake Blvd,
    and offered together the three were refused.
    """
    if any(_same_unit(r, unit) for r in rows):
        return [r for r in rows if _same_unit(r, unit)]
    return [r for r in rows if r.get("unit") is None]


#: How far the same-address search looks. A shared address sits on one road; a
#: kilometer covers the farm in the case that taught this (see
#: ``_shares_its_address``) with room to spare, and because the search asks only
#: for rows carrying the same house number its answer stays a handful of rows.
TWIN_RADIUS_M = 1000


def _parcel_at(county: _County, lat: float, lon: float, address: str | None,
               *, deadline: float | None = None) -> dict | None:
    """The candidate this point and address name, or None.

    The choice is ``_shared.select_parcel``'s; see it for why the nearest parcel
    is never taken. Before it sees the rows, two things happen in ``fetch`` —
    both the sanctioned "drop what cannot be an answer" shape, so both can only
    turn "ambiguous" into "one", never admit a parcel the address check would not:

    * a reader who typed a unit cannot live in a row naming a different unit
      (``_for_unit``), and
    * agreeing rows at one street address become one candidate (``_collapse``).

    After it, one check of our own: the address must not belong to a second
    parcel nearby (``_shares_its_address``).
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    unit = unit_of(address)

    def prepared(rows):
        return _collapse(_for_unit(rows, unit) if unit else rows)

    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            fetched[distance_m] = prepared(
                _rows(county, lat, lon, distance_m, deadline=deadline))
        return fetched[distance_m]

    chosen = select_parcel(fetch, address, lambda c: c["address"])
    if chosen is None or not address:
        return chosen
    number = address_key(address)[0]      # digits only: address_key insists
    field = county.address_field
    same_number = prepared(_rows(
        county, lat, lon, TWIN_RADIUS_M, deadline=deadline,
        where=f"{field} LIKE '{number} %' OR {field} LIKE '% {number} %'"))
    return _shares_its_address(chosen, address, same_number)


def _shares_its_address(chosen: dict, address: str,
                        same_number: list[dict]) -> dict | None:
    """``chosen``, unless another parcel within a kilometer has its address.

    Containment confirmed by address is ``select_parcel``'s strongest answer, and
    in Texas it is not enough on its own, because an appraisal district can give
    one street address to several accounts. In the verification run, typed
    "16417 Hubenak Rd, Needville" landed inside an 86-acre farm whose 1930
    farmhouse carries that address — and so does the 1-acre homesite cut out of
    it, a 1984 house, which was the home sampled. Containment named the
    farmhouse, and the adapter reported 1930 for a 1984 house. The homesite was
    more than 80 m from the point, so the ordinary buffer could not see it.

    So once a parcel is chosen, the service is asked for every row carrying the
    same house number within ``TWIN_RADIUS_M`` (an attribute filter on the
    address column, so the answer is a handful of rows), read with the same rules
    (unit filter, agreeing rows collapsed), and the address must name exactly one
    candidate among them. Two or more is the ambiguity ``select_parcel`` refuses
    in its buffer, and is refused here. One that is a collapsed group — the chosen
    row and a twin that agree on the year — is answered as the group: the year,
    and no floor area, since which of the two the reader lives in is unknown.

    It costs one more request on every confirmed lookup (measured median about
    0.1 s; see "Timing").
    """
    hits = [c for c in same_number if _shared.same_address(address, c["address"])]
    if len(hits) != 1:
        # Two or more: shared. None: the search did not even find the chosen
        # parcel, so it has not looked, and its silence is not evidence.
        return None
    if hits[0].get("stack"):
        return hits[0]
    # Exactly one, and it must be the parcel already chosen. Anything else means
    # another parcel has the address and this one is missing from the search.
    return chosen if hits[0]["pid"] == chosen["pid"] else None


# ── the record ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   county_fips: str | None, _bucket: int = 0) -> AssessorRecord | None:
    county = COUNTIES.get(county_fips or "")
    if county is None:
        return None
    cand = _parcel_at(county, lat, lon, address)
    if cand is None or cand["reading"] == NOT_A_HOME:
        return None
    year, sqft, stories = cand["year"], cand["sqft"], cand["stories"]
    if year is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=county.source,
        data_vintage=cand["vintage"] or DATA_VINTAGE,
        parcel_id=cand["pid"],
        year_built=year,
        sqft=sqft,
        stories=stories,
        # None of these services carries an exterior wall, foundation or condition
        # column in a vocabulary the label can read; see the module docstring.
    )


def url_for(county_fips: str) -> str | None:
    """The parcel layer that answers for this county, or None if none does — so a
    dropped lookup is named after the county's own publisher, not another's."""
    county = COUNTIES.get(county_fips)
    return county.url if county else None


def lookup(lat: float, lon: float, address: str | None = None,
           county_fips: str | None = None) -> AssessorRecord | None:
    """What the county appraisal district says is standing at this point, or None.

    ``address`` is the geocoder's matched address, used only to confirm the
    parcel. ``county_fips`` is the county the registry routed on, which it passes
    to adapters that accept it; it picks the county's service. Without one the
    lookup answers None rather than guess which of seven services to ask.

    Fails open on everything. The caller then keeps whatever it had, which is the
    behavior that existed before this adapter.
    """
    try:
        fips = str(county_fips).strip().zfill(5) if county_fips else None
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              fips, cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Texas assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
