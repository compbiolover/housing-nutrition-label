#!/usr/bin/env python3
"""New Jersey — all 21 counties from one statewide layer, in a single request.

New Jersey assesses property municipally: 564 tax assessors, one per
municipality. Every one of them keeps its roll in the same state system, MOD-IV,
which the Division of Taxation prescribes field by field in its MOD-IV User
Manual. The NJ Office of GIS (NJOGIS) joins that roll to the counties' parcel
maps once a year and publishes the result as one keyless layer:

  ``Parcels_Composite_NJ_WM/FeatureServer/0`` — "Parcels and MOD-IV Composite
  of NJ", 3,481,240 parcels, 2,542,604 of them class 2 (residential, four
  families or fewer). Verified live 2026-10-04.

So the per-municipality fragmentation is already solved here, the same way
Florida's and Connecticut's are solved, and a lookup is one question: *which
parcel is this point inside, and what does its MOD-IV record say?*

Two copies of the layer, and why this one
-----------------------------------------
The same table is also served by the state's own ArcGIS Server as
``maps.nj.gov/arcgis/rest/services/Framework/Cadastral/MapServer/0``. The two
were identical when checked (2,542,604 class-2 parcels each, 5,482 of them built
in 2024 in each, the same latest county publication date). Measured over 60
parcel centroids drawn at random across all 21 counties, alternating which host
was asked first:

  ===============================  ======  ======  ======  ======
  request                          median     p90     p95     max
  ===============================  ======  ======  ======  ======
  ArcGIS Online, containment        142 ms  160 ms  180 ms  515 ms
  ArcGIS Online, 80 m buffer        149 ms  186 ms  200 ms  610 ms
  maps.nj.gov, containment          103 ms  301 ms  373 ms  579 ms
  maps.nj.gov, 80 m buffer          114 ms  215 ms  236 ms  582 ms
  ===============================  ======  ======  ======  ======

The ArcGIS Online copy is used. Its median is 40 ms slower and its tail is half
as long, which is the number that decides whether a lookup finishes inside its
budget. It returns up to 2,000 rows a page against maps.nj.gov's 1,000, which
matters in exactly one place — an 80 m buffer in a block of condominium towers,
where every unit is its own row (below) — because a truncated page is refused
(``_shared.TruncatedResponse``). And it is the copy NJOGIS documents as "the
latest statewide parcels", with the license and the update log attached to the
item.

Which counties
--------------
All 21. Class-2 parcels carrying a ``YR_CONSTR`` after 1700 and not after 2026,
measured over the whole layer (2026-10-04):

  ==========  ========  ========  =====   ==========  ========  ========  =====
  county      class 2   a year    share   county      class 2   a year    share
  ==========  ========  ========  =====   ==========  ========  ========  =====
  Bergen       252,657   250,902  99.3%   Passaic      105,443    91,556  86.8%
  Ocean        249,719   248,838  99.6%   Somerset     102,979   102,269  99.3%
  Middlesex    212,754   197,549  92.9%   Atlantic      97,113    96,370  99.2%
  Monmouth     212,073   210,573  99.3%   Gloucester    91,516    91,108  99.6%
  Camden       155,865   154,836  99.3%   Cape May      78,324    77,608  99.1%
  Morris       152,289   149,747  98.3%   Sussex        55,007    52,506  95.5%
  Essex        147,983   147,439  99.6%   Cumberland    41,592    40,857  98.2%
  Burlington   144,853   144,272  99.6%   Hunterdon     40,862    40,668  99.5%
  Union        129,249   124,975  96.7%   Warren        34,644    34,397  99.3%
  Hudson       110,667   107,945  97.5%   Salem         20,211    19,851  98.2%
  Mercer       106,804   106,089  99.3%
  ==========  ========  ========  =====   ==========  ========  ========  =====

The lowest is Passaic, where Paterson leaves 13,377 homes without a year; the
county as a whole is still 87% filled, so there is no line to draw. Statewide,
2,490,374 of 2,542,604 class-2 parcels (97.9%) carry a year.

What MOD-IV says each field means
---------------------------------
Read from the Division of Taxation's MOD-IV User Manual (rev. October 2018,
``nj.gov/treasury/taxation/pdf/lpt/modIVmanual.pdf``) and NJOGIS's attribute
definitions:

* ``YR_CONSTR`` — "Construction Year Field (19) - Four numeric characters";
  NJOGIS: "Year of building construction." The actual year, not an effective
  one; MOD-IV has no effective-year field at all.
* ``PROP_CLASS`` — the statutory property class: 1 vacant land, 2 residential
  (four families or less), 3A farm (regular), 3B farm (qualified; "land only is
  assessed"), 4A commercial, 4B industrial, 4C apartment, 5A/5B railroad, 6A/6B
  utility personal property, 15A–15F exempt (schools, public, church and
  charitable, cemeteries, other).
* ``DWELL`` — "Dwelling Units Field (23) ... The number of dwelling units on
  the property", mandatory on a class 2 or 3A line.
* ``PCLQCODE`` — the qualifier that makes a line unique within its block and
  lot: ``CXXXX`` a condominium unit, ``PXXXX`` a parking-space unit, ``DXXXX`` a
  distinct unit, ``MXXXX`` a mobile home, ``X`` the exempt portion of a ratable,
  and a few zone and sector codes.
* ``BLDG_DESC`` — fifteen characters, "listed in the following order: stories,
  exterior structural material, style, number of stalls, and type of garage",
  with a code table — and the caveat "The listed codes may be supplemented
  according to need." See below for the one part of it this adapter reads.
* ``BLDG_CLASS`` — the building class from the Appraisal Manual for New Jersey
  Assessors: a cost-and-quality grade ("17", "16.5", "37"), not a wall material
  and not a condition. Not requested.
* ``LAST_YR_TX`` — the *tax bill* for the prior year, in dollars, not a year.
  Not requested; it cannot date anything.

The year: which records answer
------------------------------
**The class is the dwelling statement here, not the dwelling count.** The rule
every adapter follows — refuse a year built where the record says nobody lives
there — would normally read ``DWELL == 0`` as that statement, as Florida reads
``NO_RES_UNT``. In New Jersey it is not one: Upper Township writes 0 on 4,925 of
its class-2 homes, Delran on 4,356 and Secaucus on 1,688, and Westfield's 0s are
ordinary new colonials ("2S-F-L-AG", built 2019). 16,836 class-2 parcels carry
it. Refusing on it would cost three whole towns to turn away a line that is,
on the class-2 rows read, a house every time.

What does say "no home here" is the class, which every line must carry and the
assessor must keep right because the tax rate follows it. So a year is reported
for class 2 and 4C (apartments: the building's year is every apartment's); for
3A, the farm class that holds the farmhouse, unless ``DWELL`` is an explicit 0;
and for 4A (commercial) only where ``DWELL`` records at least one dwelling — the
apartment over a shop, 35,429 such parcels with a year. Everything else is
refused: class 1 (vacant land — 13,326 of them carry a year anyway, a shed's or
a demolished house's), 3B (qualified farmland, "land only is assessed"), 4B
industrial, 5 and 6, and the 15s, where a year is a school's, a church's or a
condominium's common elements.

The year values that are not years
----------------------------------
* **0 and blank** — "not recorded", on 51,197 class-2 parcels.
* **1700** — a placeholder in some rolls. Union City writes it on 207 homes and
  Elizabeth on 173, with nothing between 1700 and the 1770s in either; Hopatcong
  (29) and Weehawken (14) are the same. Hunterdon's colonial townships also
  carry a few 1700s — round numbers for genuinely old farmhouses, with 1709,
  1735, 1740 beside them — but no rule tells one town's 1700 from another's, and
  the whole value covers 597 class-2 parcels statewide (0.02%). It is refused
  everywhere; the tract's distribution stands in, which for an 18th-century
  farmhouse is no worse a guess than a rounded 1700.
* **Below the scorer's floor** — 1, 2, 3, 4, 18, 194, 1089 (402 parcels):
  keying slips, already refused by ``EARLIEST_PLAUSIBLE_YEAR``. The 34 between
  1600 and 1699 are kept; New Jersey has houses that old.
* **In the future** — 2028, 2032, 2082, 2100, 3005, 9999 (19 parcels after
  2026). A year beyond next year is not when anything went up; the bound is
  next year rather than the 2100 other adapters use, because this roll has
  four values in between.

Condominiums: unit lines on dummy polygons
------------------------------------------
New Jersey files each condominium unit as its own MOD-IV line — the mother
lot's block and lot plus a ``C`` qualifier ("0901_159_18_C0001") — and 272,649
class-2 lines are condo units. The composite draws each unit as a small
dummy polygon inside the mother lot, cut out of it, so the
layer stays a planar coverage: no point is inside two parcels, and a unit's
"parcel" is a 15–150 m² sliver that says nothing about where the unit is.
Verified live in Bayonne, Hoboken, Fort Lee, Jersey City, Barnegat Light and
Cranbury.

The mother lot around the slivers is the common element. Of 120 condo units
drawn at random, the mother lot was a class 15F line ("COMMON ELEMENTS") in 41,
an unmatched polygon with no attributes in 38, class 1 open space in 14, absent
in 25 — and carried a year in 4. So a geocode on a condominium building
usually lands in a polygon that cannot answer.

That is handled by two things, both inside ``_candidates`` and neither touching
the shared parcel choice:

1. **A row that cannot contribute a fact is not a candidate.** The common
   element, the unmatched polygon and the open space have no year this adapter
   would report. Left in, the common element is the sole containing parcel,
   confirms against "25 RIVER ROAD", and answers nothing; dropped, the lookup
   widens to the 80 m buffer, which accepts only a parcel whose address agrees.
   Dropping a non-answer can only turn "nothing" or "ambiguous" into "one real
   record"; the address confirmation is untouched.
2. **Unit lines of one lot that agree are one answer.** In the buffer, a
   92-unit building at "25 RIVER ROAD C-1" … "C-92" is 92 rows with one street
   address, which the shared chooser rightly calls ambiguous — and which agree
   on the one fact reported, because the building went up once. Qualified rows
   of the same municipality, block and lot, with the same street address and
   the same year, are collapsed into one, under the lot's own PIN. Rows that
   differ in year are left apart (a complex built in phases, a mobile-home park
   where each ``M`` line is its own home), and stay ambiguous.

A unit line never reports a story count (below), and there is no floor area in
the layer, so the condominium trap — a building's size reported as a unit's —
cannot arise.

Stories, from the one documented part of the building description
-----------------------------------------------------------------
``BLDG_DESC`` is free text in practice: "1 FAMILY" (Elizabeth), "HAMPTON" and
"TH YARDLEY" (model names), "1805 2BR 25BT 5" (Fort Lee's square feet and
bedrooms), "1970 SF" (square feet), "106A1SWS1G1F". But the manual's first
element is documented and widely followed — "S: Prefix S with number of
stories", "1.5SSTL2AG means: 1 1/2 story stone colonial with a 2 car attached
garage" — and in a 17,868-row sample 10,517 class-2 descriptions open with it
("1SF", "2S-F-L-AG", "1.5 SF", "2SFRDWG").

So the story count is read only from a description that *opens* with a single
digit (optionally a decimal) and an S — "1970 SF" and "1805 2BR" cannot match
— and only where the record is one home in one building: class 2, ``DWELL ==
1``, no qualifier, no unit in the address, no CONDO in the description. Half
stories (1.5, 1.75, 2.5) have no whole-number reading and are dropped, as Cook
and the District drop them; above four is refused, as Ohio refuses it on a
single-family lot ("5SF4UG").

The rest of the description is not translated. The structure codes look like
the label's ``construction``, and they cannot be read safely: ``S`` is both the
stories prefix and stucco, ``ST`` is stone, so "2SST" is two-story stucco twin
or two-story stone; towns supplement freely ("VS", "H", "BT", "VL" are in the
rolls and not in the manual); and ``AL`` (aluminum siding) and ``W`` (wood)
describe a cladding, not the structure the label's vocabulary names. Reading
any of it would be a guess wearing the ``observed`` tag.

Where the street address lives
------------------------------
``PROP_LOC`` — "the physical location of the property", 25 characters, the
street address alone (the town is in its own column). ``ST_ADDRESS`` and
``CITY_STATE`` are the *owner's mailing* address and are never requested.

Two spellings are specific to these rolls and are rewritten on the roll's side
only:

* a unit glued to the street type with a hyphen — "1919 BAY BLVD-UNIT B37",
  "321 ELM ST - UNIT A" — which would otherwise read as a street type the
  comparison has never heard of;
* a house-number range — "65-67 WESTFIELD AVE", "3509-11 CENTRAL AVE" — offered
  under the reader's own number when it falls inside the range on the same side
  of the street, and under its low number otherwise. The same rule
  Philadelphia's and Allegheny's adapters apply.

And four are differences of spelling between the roll and the Census matcher,
so both strings are rewritten alike before the shared comparison sees them
(``_comparable``): "NO." / "SO." for North / South ("85 NO. GROVE ST"), a
detached "MC" ("235 MC ELROY AVE"), a single-letter directional written after
the street type ("61 TULANE STREET N" for the matcher's "61 N TULANE ST"), and
terminal LA and TR for lane and trail. Each failed at least once in the first
end-to-end run, and each is common in the rolls (counts beside the code). A
directional present on only one side is never forgiven.

Vintage
-------
MOD-IV books close in the fall; the Division of Taxation releases the statewide
extract the following spring; NJOGIS then rejoins. The layer's update log says
its current MOD-IV join is "for the 2024 tax year" (process step of 2025-09-09;
5,482 class-2 homes built in 2024 against 114 in 2025 bear that out). No row carries
the tax year, so it is not hard-coded into the record, where it would go stale
silently on the next join. What a row does carry is ``PCL_PBDATE``, the date
NJOGIS last published that county's parcel file (from 2023-10-03 for Union to
2026-06-04 for Ocean), and that is what each record is dated with.

Why this service does NOT need its own clock
--------------------------------------------
The measurement above, and the timing of every request made in the end-to-end
run below (860 requests, slowest 649 ms; the slowest containment and the
slowest buffer together 1.05 s), put
nothing near the shared one-second read slice or the four-second budget, so
this adapter takes both shared defaults, like North Carolina's. The
shared worst case — the 4 s budget spent connecting plus one 1 s slice, 5 s — is
inside the 12 s the host allows one service (``config.UPSTREAM_HOST_BUDGET``); a
test pins that sum against the constant.

What the adapter is worth, end to end
-------------------------------------
465 class-2 homes drawn at random from the layer itself, spread over all 21
counties (40 each in Bergen, Essex, Hudson, Middlesex, Ocean and Monmouth, 15 in
each of the others), each with a year this adapter would report. Each was typed
as its ``PROP_LOC``, its municipality and the ZIP (2020 ZCTA) it sits in —
a range typed by its low number, a unit as the roll writes it — geocoded through
the Census matcher exactly as the product does, passed through
``assessor_address`` and looked up:

* 442 geocoded, and all 442 routed to the county the parcel is filed in.
* **348 resolved, and 0 matched to the wrong parcel.** All 348 years are exact.
  164 of them also carry a story count. Every county resolved at least 8 of
  its sample (Hunterdon, Morris); the six largest resolved 26 to 35 of 40.
* Of the 40 condominium unit lines in the sample, 36 geocoded and 22 resolved;
  13 of those were answered by the collapse of agreeing unit lines, under the
  lot's PIN, and would otherwise have been refused as ambiguous.
* 94 did not resolve. 84 are geocodes the Census matcher placed beyond the
  shared 80 m search — interpolated along the street, median 165 m from the
  parcel's center. 8 are spellings the two sources genuinely disagree on: a
  directional on one side only ("439 S WILLOW AVE" against "439 WILLOW AVE",
  twice in Galloway), "LUHMAN" against "LUHMANN", "GLENN" against "GLEN",
  "HARDENBERG" against "HARDENBERGH", a lettered house number ("619A", which the
  shared parse does not take), and two strings with something glued on ("3
  SOMERSET LN-GLASS HOUSE", "41 SO CHESTNUT AVE SEC 70"). 2 are condominium
  addresses whose unit lines disagree on the year, which the shared chooser
  declines.

The respellings in ``_comparable`` were added because of an earlier run of the
same sample typed without ZIPs (343 geocoded, 261 resolved, also 0 wrong), in
which they accounted for 13 of the unresolved.

The requests themselves, timed as the adapter made them in this run:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which parcel is this dot inside?"   136 ms  152 ms  163 ms  403 ms
  "what is within 80 m of this dot?"   144 ms  168 ms  181 ms  649 ms
  ==================================  ======  ======  ======  ======

442 containment and 418 buffered requests — the buffer runs on nearly every
lookup, because the matcher's point rarely lands inside the right lot. The
largest response carried 199 rows (a buffer over condominium slivers), far
under the 2,000-row page.

Terms of use
------------
The item's license (ArcGIS Online item ``533599bbfbaa4748bf39faf1375a8a9c``)
disclaims every warranty, says the parcels are not survey data, and asks one
thing: "Acknowledgement of the service provider, NJ Office of Information
Technology, Office of GIS (NJOGIS), is requested for maps, data or other
products derived from this service." It defers otherwise to the State's Legal
Statement (``https://www.nj.gov/nj/legal.shtml``), whose Section F reads: "The
State of New Jersey has made the content of these pages available to the public
and anyone may view, copy or distribute State information found here without
obligation to the State, unless otherwise stated." Nothing on the item states
otherwise. ``ATTRIBUTION`` names NJOGIS as asked. This adapter queries live and
caches in-process only, and nothing from the service is written into the
repository — the posture every adapter here takes (``base.py``). Verdict:
permitted, with the acknowledgement.

Privacy, and why the field list is short
----------------------------------------
The layer has 45 columns. ``OWNER_NAME`` is redacted under Daniel's Law
(P.L. 2020, c. 125), and is never requested regardless; neither are
``ST_ADDRESS``, ``CITY_STATE``, ``ZIP_CODE``, ``ZIP5`` and ``ZIP_PLUS4`` (the
owner's mailing address), ``DEED_BOOK``, ``DEED_PAGE``, ``DEED_DATE``,
``SALE_PRICE``, ``SALES_CODE`` or any assessed value. Eleven columns are
requested by name — the shared helper refuses ``*`` for precisely this reason.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, arcgis_parcels, cache_bucket, deadline_from, num, select_parcel,
    unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# All 21 New Jersey counties: the odd codes 34001 to 34041. Written as a rule
# because every county clears the bar (see "Which counties" in the module
# docstring); a test checks the result against the county table this repository
# ships.
COUNTY_FIPS = frozenset(f"34{n:03d}" for n in range(1, 42, 2))

NAME = "NJOGIS"
ATTRIBUTION = ("New Jersey municipal tax assessors (MOD-IV) via NJ Office of "
               "Information Technology, Office of GIS (NJOGIS) — Parcels and "
               "MOD-IV Composite of NJ (keyless)")
DATA_VINTAGE = "NJOGIS Parcels and MOD-IV Composite of NJ"

PARCEL_URL = ("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services"
              "/Parcels_Composite_NJ_WM/FeatureServer/0/query")

#: The shared defaults, named so the budget test reads the same constants the
#: requests do. See "Why this service does NOT need its own clock".
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

# Only what the label scores, what confirms the parcel, what decides whether the
# record describes a home, and what dates it. See "Privacy" in the module
# docstring for the 34 columns that are never fetched.
_FIELDS = ("PAMS_PIN,PCL_MUN,PCLBLOCK,PCLLOT,PCLQCODE,PROP_CLASS,PROP_LOC,"
           "YR_CONSTR,DWELL,BLDG_DESC,PCL_PBDATE")


def url_for(county_fips: str) -> str | None:
    """The layer that answers for this county, or None if none does — so a
    dropped lookup is named after the right publisher. One layer for the state."""
    return PARCEL_URL if county_fips in COUNTY_FIPS else None


# --- what the record says ------------------------------------------------------

#: Classes whose year is a home's whatever the dwelling count says.
_HOME_CLASSES = frozenset({"2", "4C"})

#: Year values that are a roll's placeholder rather than a year. See "The year
#: values that are not years" in the module docstring.
_PLACEHOLDER_YEARS = frozenset({1700})


def _text(value) -> str:
    return " ".join(str(value or "").split()).upper()


def _qualifier(row: dict) -> str:
    return _text(row.get("PCLQCODE"))


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the record's class says a dwelling stands on this parcel.

    See "The year: which records answer" in the module docstring: the class is
    the statement, and ``DWELL`` only decides the two mixed classes.
    """
    cls = _text(row.get("PROP_CLASS"))
    if cls in _HOME_CLASSES:
        return True
    dwell = num(row.get("DWELL"))
    if cls == "3A":
        return dwell is None or dwell >= 1
    if cls == "4A":
        return dwell is not None and dwell >= 1
    return False


def _year(row: dict) -> int | None:
    """``YR_CONSTR`` when it is a year somebody's home went up, otherwise None."""
    year = num(row.get("YR_CONSTR"))
    if not year or year != int(year):
        return None
    year = int(year)
    if year in _PLACEHOLDER_YEARS:
        return None
    if not EARLIEST_PLAUSIBLE_YEAR <= year <= date.today().year + 1:
        return None
    return year if _says_a_home_is_here(row) else None


# "1SF", "2S-F-L-AG", "1.5 SF", "2SFRDWG": a single digit, an optional decimal,
# at most one space, then S. Anchored and single-digit so "1970 SF" (square feet)
# and "1805 2BR" (Fort Lee's area and bedrooms) cannot match.
_STORIES_RE = re.compile(r"^([1-9](?:\.\d+)?) ?S")
_MAX_STORIES = 4


def _stories(row: dict) -> int | None:
    """The documented story prefix of ``BLDG_DESC``, where the record is one home
    in one building and the count is whole. See "Stories" in the module docstring."""
    desc = _text(row.get("BLDG_DESC"))
    m = _STORIES_RE.match(desc)
    if not m:
        return None
    if _text(row.get("PROP_CLASS")) != "2" or num(row.get("DWELL")) != 1:
        return None
    if _qualifier(row) or unit_of(_street_of(row)) or "CONDO" in desc:
        return None
    floors = float(m.group(1))
    if not floors.is_integer() or not 1 <= floors <= _MAX_STORIES:
        return None
    return int(floors)


# --- the address ---------------------------------------------------------------

# "1919 BAY BLVD-UNIT B37", "321 ELM ST - UNIT A": a unit glued on with a hyphen.
_GLUED_UNIT_RE = re.compile(r"\s*-\s*(UNIT|APT)\b")
# "65-67 WESTFIELD AVE", "3509-11 CENTRAL AVE": a house-number range.
_RANGE_RE = re.compile(r"^(\d+)-(\d+)(\s+\S.*)$")
_MAX_RANGE_SPAN = 200


def _street_of(row: dict) -> str:
    """``PROP_LOC`` with the glued unit separated; see "Where the street address
    lives" in the module docstring."""
    return _GLUED_UNIT_RE.sub(r" \1", _text(row.get("PROP_LOC")))


def _range_high(low: str, ext: str) -> int | None:
    """The top of a "3509-11" range, or None if the range is malformed."""
    lo = int(low)
    high = int(ext) if len(ext) >= len(low) else int(low[:-len(ext)] + ext)
    if high <= lo or high - lo > _MAX_RANGE_SPAN:
        return None
    return high


def _address_of(row: dict, asked: str | None = None) -> str | None:
    """The record's street address as the comparison should see it.

    A ranged location is offered under the reader's own number when that number
    is inside the range on the same side of the street, and under its low number
    otherwise — never under a number the roll does not name.
    """
    street = _street_of(row)
    if not street:
        return None
    m = _RANGE_RE.match(street)
    if not m:
        return street
    low, ext, rest = m.groups()
    high = _range_high(low, ext)
    key = address_key(asked) if asked else None
    if high is not None and key:
        n, lo = int(key[0]), int(low)
        if lo <= n <= high and (n - lo) % 2 == 0:
            return f"{n}{rest}"
    return f"{low}{rest}"


# --- the candidates ------------------------------------------------------------


def _lot_pin(row: dict) -> str | None:
    parts = [_text(row.get(c)) for c in ("PCL_MUN", "PCLBLOCK", "PCLLOT")]
    return "_".join(parts) if all(parts) else None


def _candidates(rows: list[dict]) -> list[dict]:
    """The rows that could be an answer, with agreeing unit lines made one.

    See "Condominiums: unit lines on dummy polygons" in the module docstring for
    both steps and why each is safe. Rows identical in every requested field (one
    record drawn as several polygons) are also one.
    """
    out, groups, seen = [], {}, set()
    for row in rows:
        if _year(row) is None and _stories(row) is None:
            continue
        exact = tuple(sorted((k, str(v)) for k, v in row.items()))
        if exact in seen:
            continue
        seen.add(exact)
        lot = _lot_pin(row)
        if not _qualifier(row) or lot is None:
            out.append(row)
            continue
        key = (lot, address_key(_address_of(row)), _year(row))
        if key in groups:
            groups[key]["_lines"] += 1
            continue
        merged = dict(row, _lines=1, _lot=lot)
        groups[key] = merged
        out.append(merged)
    return out


# --- spelling, applied to BOTH sides of the comparison --------------------------
#
# Four ways these rolls and the Census matcher spell one street differently, each
# seen in the end-to-end run and each counted statewide over class-2 parcels.
# See "Where the street address lives" in the module docstring.
_ABBREVIATED_DIRECTION = {"NO": "N", "SO": "S"}
_SINGLE_DIRECTIONS = frozenset({"N", "S", "E", "W"})
# Terminal only. LA is the roll's lane ("4 LANCELOT LA"; 12,838 parcels); TR is
# its trail (Medford Lakes, Hopatcong, Pemberton; 5,830 parcels) — Moorestown
# writes TR for terrace, and those simply fail to match TER, never match
# something else.
_EXTRA_TYPES = {"LA": "LN", "TR": "TRL"}


def _comparable(address: str | None) -> str | None:
    """``address`` respelled so the roll's conventions and the matcher's compare
    equal. Rewrites only the street part (before the first comma); anything it
    does not recognize passes through untouched, so the worst it can do is leave
    a pair unmatched.

    * "NO." / "SO." after the house number — "85 NO. GROVE ST" (East Orange,
      Manville, Kenilworth, Montclair; about 16,000 parcels) — is N / S;
    * "MC ELROY" is "MCELROY" (3,334 parcels with a detached MC);
    * a single-letter directional after the street type — "61 TULANE STREET N",
      "561 GRANT AVE E" (about 15,000 parcels) — is written before the name,
      where the matcher puts it ("61 N TULANE ST");
    * terminal LA and TR, above.

    The risk would be two different buildings rewritten into one string, and
    none of these can do that within one 80 m search: 100 Main St N and 100 N
    Main St are the same house on North Main Street wherever both spellings
    occur. A directional present on only one side ("439 S WILLOW AVE" against
    the roll's "439 WILLOW AVE") is NOT forgiven — 100 N Main and 100 S Main
    are different houses.
    """
    if not address:
        return address
    head, sep, tail = str(address).partition(",")
    words = [w.upper().strip(".") for w in head.split()]
    words = [w for w in words if w]
    if len(words) < 3 or not words[0][:1].isdigit():
        return address
    if words[1] in _ABBREVIATED_DIRECTION and len(words) >= 4:
        words[1] = _ABBREVIATED_DIRECTION[words[1]]
    joined = []
    for w in words:
        if joined and joined[-1] == "MC" and len(joined) >= 2 and w.isalpha():
            joined[-1] = "MC" + w
        else:
            joined.append(w)
    words = joined

    def is_type(word: str) -> bool:
        return word.lower() in _shared.SUFFIXES or word in _EXTRA_TYPES

    if (len(words) >= 4 and words[-1] in _SINGLE_DIRECTIONS and is_type(words[-2])
            and words[1] not in _SINGLE_DIRECTIONS):
        words = [words[0], words[-1]] + words[1:-1]
    if words[-1] in _EXTRA_TYPES and len(words) >= 3:
        words[-1] = _EXTRA_TYPES[words[-1]]
    return " ".join(words) + sep + tail


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline, read_slice=READ_SLICE_S)
    return _candidates(rows)


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the parcel this point belongs to, or None.

    The choice itself is ``_shared.select_parcel``'s, shared by every
    jurisdiction; see that function for why it never takes the nearest parcel.
    No locality set is needed: the town is in its own column. Both the asked
    address and every candidate's go through ``_comparable`` first.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        _comparable(address), lambda row: _comparable(_address_of(row, address)))


def _parcel_id(row: dict) -> str | None:
    """The PAMS PIN (municipality_block_lot[_qualifier]); the lot's own PIN where
    several unit lines were collapsed into one answer."""
    if row.get("_lines", 1) > 1:
        return row.get("_lot")
    pid = _text(row.get("PAMS_PIN"))
    return pid or _lot_pin(row)


def _vintage(row: dict) -> str:
    """Dated from the row: the day NJOGIS last published this county's parcels.
    See "Vintage" in the module docstring for why the tax year is not here."""
    ms = num(row.get("PCL_PBDATE"))
    if ms and ms > 0:
        try:
            day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return DATA_VINTAGE
        if 2000 <= day.year <= 2100:
            return f"{DATA_VINTAGE}, county parcels published {day.isoformat()}"
    return DATA_VINTAGE


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year_built, stories = _year(row), _stories(row)
    if year_built is None and stories is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        stories=stories,
        # The layer carries no floor area, foundation or condition, and its wall
        # codes are not readable — see "Stories, from the one documented part of
        # the building description". Left empty on purpose, so the label falls
        # back to its modeled estimate rather than to a guess.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What New Jersey's MOD-IV roll says is standing at this point, or None.

    ``address`` is the geocoder's matched address (carrying the reader's unit,
    which is ignored: every unit line of a building agrees on its year). It
    confirms the parcel, and the lookup still works without one wherever the
    coordinate lands inside a parcel that can answer.

    Fails open on everything — a timeout, a 500, a truncated page, a renamed
    column. The caller then keeps whatever it had.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("New Jersey assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
