#!/usr/bin/env python3
"""New York City — all five boroughs from the City Planning tax-lot layer, in one request.

3.7 million homes in one city, the densest housing stock in the country, and five
county FIPS codes: the Bronx (36005), Brooklyn (Kings, 36047), Manhattan (New York,
36061), Queens (36081) and Staten Island (Richmond, 36085). Each borough is a
county, but assessment is citywide — the Department of Finance values every tax
lot in the city — so one source answers for all five.

That source is PLUTO, the Department of City Planning's "Primary Land Use Tax Lot
Output": DCP takes Finance's property-tax and mass-appraisal records, one row per
tax lot, adds planning fields, and publishes it quarterly. MapPLUTO is the same
table joined to Finance's Digital Tax Map, so every row carries its lot boundary.

  ``MAPPLUTO/FeatureServer/0`` on DCP's own ArcGIS Online organisation
  (``services5.arcgis.com/GfwWNkhOj9bNBqoJ``, owner ``DCP_GIS``) — 856,687 lots,
  release 26v2, keyless, verified live.

One request, not two
--------------------
The research memo planned this as two hops — a point-to-lot lookup on MapPLUTO to
get a BBL (borough-block-lot, the city's parcel id), then the PLUTO row for that BBL
from NYC Open Data's Socrata copy (``64uk-42ks``). That second hop is unnecessary.
The MapPLUTO layer carries every PLUTO column on the polygon itself, from the same
26v2 release the Socrata table serves (858,284 rows there; the 1,597 extra are lots
Finance has not yet drawn on its tax map, which no coordinate could reach anyway).
So the lookup is Florida's shape: *which lot is this point inside, and what does
its record say?* ``_shared.arcgis_parcels`` does it, and ``_shared.select_parcel``
decides which lot an address means, exactly as for every other adapter.

The Socrata endpoint is not used. Its ``geom`` column is a text field rather than
a Socrata point or polygon type, so ``within_circle`` cannot run against it; its
``latitude``/``longitude`` are a single interior point per lot, and "nearest lot
point" is the nearest-parcel rule ``select_parcel`` exists to refuse.

Four things in this city's addresses that the shared comparison cannot read
--------------------------------------------------------------------------
``_shared.same_address`` is strict on purpose, and PLUTO and the Census matcher
spell New York addresses differently in four systematic ways. Without
reconciling them almost nothing confirms; ``_street_form`` rewrites BOTH sides
into one spelling before the shared comparison runs, so every rule that
comparison enforces — the house number, every street-name token, the street type —
still applies unchanged.

* **Queens house numbers are hyphenated.** "84-74 257 STREET" — the part before
  the hyphen names the cross street, the part after is the house. The data
  dictionary: "Most house numbers in Queens contain a hyphen." ``address_key``
  anchors on a token that is all digits and returns None for "84-74", so without
  this not one Queens address — 910,000 homes — could ever be confirmed. The
  hyphen is removed on both sides (see ``_house_number``), because the two sources
  disagree about where it goes even for one house: PLUTO writes the Rockaways
  plain and the Census matcher hyphenates them.
* **PLUTO drops ordinals and spells out directions; the Census matcher does the
  opposite.** "203 WEST 131 STREET" against "203 W 131ST ST"; "1870 3 AVENUE"
  against "1870 3RD AVE"; "29 PROSPECT PARK WEST" against "29 PROSPECT PARK W".
  Manhattan's own records are not even consistent with Brooklyn's: 350 East 18th
  Street is "350 EAST 18TH STREET" in one borough and "350 EAST 18 STREET" in the
  other.
* **PTS splits the Gaelic prefixes.** "MAC DOUGAL STREET", "MC KINLEY AVENUE"
  against "MACDOUGAL ST" — about 2,000 lots.
* **Street types sit in the middle of names.** "AVENUE J", "BEACH 116 STREET",
  "FT WASHINGTON AVENUE" against "FORT WASHINGTON AVE", and PTS's own truncation of
  the 28-character address field: "451 FATHER CAPODANNO BL" for BLVD.

Brooklyn's lettered half-lots ("770A GREENE AVENUE") are the same problem as the
hyphen, with one difference: 770A and 770 are different lots, often adjacent, so
the letter is kept rather than dropped.

The condo trap, which is severe here
------------------------------------
A Manhattan condominium is hundreds of unit lots (lot numbers 1001–6999) under one
billing lot (7501–7599). PLUTO aggregates the units onto the billing lot and
MapPLUTO draws only the billing lot, so a coordinate inside a condominium tower
lands on one record describing the whole tower: 20 West 64th Street is one lot with
655 residential units. ``BldgArea`` is "the total gross area" of every structure on
the lot, so on that record it is the tower.

So the floor area and the storey count are reported only where the record is one
home in one building, and the building is a one-family dwelling — **all** of:

* ``UnitsRes == 1`` — one residential unit;
* ``NumBldgs == 1`` — one building; 110,561 one-family lots carry 2, almost always
  a detached garage, and ``BldgArea`` then covers both;
* ``BldgClass`` starting ``A`` — Finance's one-family-dwelling classes. This is
  stricter than the unit count and is the point: 7,810 one-unit, one-building lots
  in the PLUTO table are something else — ``S`` (a house with a store), ``K`` (a
  store building with a flat above), ``O`` (offices) — whose gross area includes
  the shop. And the table holds 2,907 unit-numbered lots (1001–6999) that PLUTO
  could not yet roll up to a billing lot; one like lot 1163 at 350 East 18th
  Street (class ``R4``, ``UnitsRes`` 1, 2,287 sq ft) would otherwise pass the
  count test with one unit's area. Most of those have no polygon on the tax map
  yet, but the rule does not depend on that;
* ``AreaSource`` of 2 or 7 — the area was recorded by Finance (PTS or CAMA), not
  computed by DCP from the primary building's dimensions times its floor count.
  On one-family lots that is 200,749 of 200,749, so it costs nothing today and
  keeps an estimate from being tagged ``observed`` the day it is not.

Dividing a tower's area by its unit count was rejected for the reason Florida gives:
it turns a measurement into an average and tags the average ``observed``. The year
built survives all of this, because the tower went up when it went up.

``BldgArea`` is gross area measured to the exterior walls, including attached
garages and an above-grade finished basement — the same kind of number DC's
``GBA`` is, rather than Florida's heated living area. It is the city's own figure
for the house, so it is reported, and this paragraph is where a reader comparing
a New York square footage with a listing's finds out why it runs high.

What else is read, and what is not
----------------------------------
* ``YearBuilt`` — "the year construction of the building was completed", from
  Finance. DCP's own caveat: "In general, YEAR BUILT is accurate for the decade,
  but not necessarily for the specific year. Between 1910 and 1985, the majority of
  YEAR BUILT values are in years ending in 5 or 0." That is still a statement about
  this building rather than a tract quantile. 0 is "unknown" (465 lots with homes).
* ``YearAlter1`` / ``YearAlter2`` are the years of the two most recent alterations
  and are **never** read as a year built — nor requested, so a later edit cannot
  read them by mistake.
* ``BsmtCode`` → ``foundation``, from the PLUTO Data Dictionary (26v2, "BASEMENT
  TYPE/GRADE"): 1 above-grade full and 2 below-grade full → ``full-basement``;
  3 above-grade partial and 4 below-grade partial → ``partial-basement``. Dropped:
  **0** "None/No Basement", which is a slab or a crawlspace and the code does not
  say which; **5** "Unknown". The dictionary adds that the code "is available for
  one, two or three family structures" and that elsewhere "the data is not
  verified by DOF", so it is read only for those classes — ``A``, ``B``, ``C0`` —
  and only on a one-building lot, where "the building's basement" names one
  building.
* ``NumFloors`` — "full and partial floors … for the tallest building on the tax
  lot". Behind the same one-home gate as the area, and whole numbers only: a
  2.5-storey house is not rounded into a third storey, the call Cook and DC make.
* Nothing for ``construction`` or ``condition``: PLUTO carries neither a wall
  material nor a condition grade.

A zero-dwelling lot reports no year
-----------------------------------
``UnitsRes`` is "the sum of residential units in all buildings on the tax lot",
and "if there are no residential units … this field will be zero". A recorded 0 is
a statement — a shop, a garage, a hotel, which the dictionary says has none — so
its year is not the year anybody's home went up. A *missing* count is allowed
through, as in Florida: in 26v2 it is null on 170 mapped lots, every one a newly
declared condominium billing lot (169 ``R0``, one ``RM``) whose units Finance has
not yet counted, and whose year is that of a residential building.

Placeholder polygons
--------------------
462 polygons in the layer are on Finance's tax map but not in PLUTO
(``PLUTOMapID`` 3): DCP's "mapping lots" — street malls, traffic islands, built
streets through parks — with a BBL and nothing else. They can never contribute a
fact, and one overlapping a real lot would make the real one ambiguous, so they
are dropped in ``_parcels`` before the lot is chosen, the sanctioned fix
``select_parcel`` describes.

Why the shared clock is enough
------------------------------
Measured over 504 requests of each kind at real residential addresses drawn at
random from the city's own records (the two samples below), each geocoded through
the Census matcher first:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which lot is this dot inside?"      0.13 s  0.15 s  0.16 s  0.54 s
  "what is within 80 m of this dot?"   0.14 s  0.15 s  0.16 s  0.98 s
  ==================================  ======  ======  ======  ======

Not one of the 1,008 requests exceeded the shared one-second read slice, and the
worst pair (1.5 s) fits the shared four-second budget with room, so this adapter
takes both defaults rather than defining its own — unlike Florida and
Connecticut, whose services think for seconds. Responses are 0.1 to 26 KB; the
largest is an 80 m buffer in Manhattan, where fifty lots fit in a block.

What the adapter is worth, end to end
-------------------------------------
Two random samples, each geocoded through the Census matcher exactly as the
product does (``geocode_address``, then ``assessor_address``), then looked up:

* **130 lots drawn from MapPLUTO itself** (random object ids, 26 per borough),
  typed as PLUTO's own address: 129 geocoded, 127 resolved, **0 wrong lots**,
  year built exact on all 127 and floor area exact on all 37 eligible.
* **377 random city address points** (NYC Open Data ``uf93-f8nk``) — any address
  a building answers to, not PLUTO's one address per lot, so this is the harder
  and more honest test — joined to their lot through the building footprints'
  BBL: 375 geocoded, 325 resolved, year built exact on 323, floor area exact on all
  89 eligible.

The two records in the second sample that disagree with the truth are not this
adapter choosing the wrong lot for the address it was given. One is the Census
matcher answering "123 FINLAY ST, 10307" with a different street, "123 FINLAY
AVE, 10309", whose lot this adapter then found correctly — a geocoder
substitution no adapter can see, since it receives only the matched address. The
other is two of the city's own datasets disagreeing: the footprint data puts 3410
Glenwood Road's building on lot 44, while Finance gives lot 43 the address 3410 and
lot 44 3412 — twin houses, both built in 2003, so the year is right either way.

Of the 52 geocoded addresses that did not resolve, 48 do not agree with PLUTO's
single address for the lot — a corner lot typed on its side street, an address
range where PLUTO keeps "the low number when there is a range", a large complex
(Co-op City answers to dozens of addresses), a lettered number on one side only
("1764A" against "1764"), or a spelling no rule should bridge ("HUMPHREYS" against
"HUMPHREY"). The other 4 are geocodes more than 80 m from their own lot. All of it
is the shared parcel-choosing rule declining to guess.

Licence
-------
NYC Open Data's own FAQ (``nyc.gov/opendata/get-started/FAQs``): "Open Data
belongs to all New Yorkers. There are no restrictions on the use of Open Data." —
the Open Data Law (Local Law 11 of 2012) requires public datasets to be published
without "restrictions on their use". DCP's licence text on the MapPLUTO item and
the data dictionary's disclaimer provide it "for informational purposes only" with
no warranty of completeness, accuracy or fitness, and assert no restriction. So
this adapter is clear to run; it still takes the posture every adapter takes —
queried live, cached in-process, never bundled — and carries DCP's attribution.

Privacy, and why the field list is short
----------------------------------------
The layer has 103 columns, among them ``OwnerName``, ``OwnerType``, and the
assessed and exempt values. None of it is an input to any dimension of the label.
Twelve columns are requested by name and the other 91 are never fetched — the
shared helper refuses ``*`` for precisely this reason. Nothing from this source is
written into the repository.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor._shared import (
    SUFFIXES, arcgis_parcels, cache_bucket, deadline_from, num, select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# The five boroughs, each its own county. Listed rather than computed: five codes
# with no pattern between them, and a test checks them against the county table
# this repository ships.
COUNTY_FIPS = frozenset({
    "36005",   # Bronx County — the Bronx
    "36047",   # Kings County — Brooklyn
    "36061",   # New York County — Manhattan
    "36081",   # Queens County — Queens
    "36085",   # Richmond County — Staten Island
})

NAME = "NYC Department of City Planning"
ATTRIBUTION = ("NYC Department of Finance records via NYC Department of City "
               "Planning MapPLUTO (keyless)")
DATA_VINTAGE = "NYC DCP MapPLUTO (Department of Finance tax lot records)"

PARCEL_URL = ("https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services"
              "/MAPPLUTO/FeatureServer/0/query")

# Only what the label scores, the counts and classes that decide whether a number
# describes one home, the release that dates the record, and the flag that marks a
# placeholder polygon. See "Privacy" in the module docstring for the other 91, and
# note that YearAlter1/YearAlter2 are not among these on purpose.
_FIELDS = ("BBL,Address,YearBuilt,NumFloors,BldgArea,AreaSource,UnitsRes,NumBldgs,"
           "BsmtCode,BldgClass,Version,PLUTOMapID")

# PLUTO Data Dictionary 26v2, "TOTAL BUILDING FLOOR AREA SOURCE CODE": 2 is
# Finance's Property Tax System and 7 its mass-appraisal system — both a recorded
# gross area. 5 is DCP's own calculation from the primary building's dimensions
# times its floor count, 0 not available, 4 a vacant lot.
_RECORDED_AREA_SOURCES = frozenset({"2", "7"})

# PLUTO Data Dictionary 26v2, "BASEMENT TYPE/GRADE (BsmtCode)". Above- and
# below-grade differ in how exposed the walls are, not in whether there is a
# basement, so both halves of each pair land on the same label value.
#
# Deliberately unmapped:
#   0  "None/No Basement" — a slab or a crawlspace, and the code does not say
#      which; the label has a value for each, so either would be a guess.
#   5  "Unknown".
_BASEMENT = {
    "1": "full-basement",      # above grade full basement
    "2": "full-basement",      # below grade full basement
    "3": "partial-basement",   # above grade partial basement
    "4": "partial-basement",   # below grade partial basement
}

# --- addresses ----------------------------------------------------------------
#
# See "Four things in this city's addresses" in the module docstring. Everything
# here is applied to BOTH the reader's address and PLUTO's before the shared
# comparison runs, so it can only make two spellings of one address equal; it
# cannot relax what that comparison requires of them.

_HYPHENATED = re.compile(r"^(\d{1,4})-(\d{1,3})$")
_LETTERED = re.compile(r"^(\d{1,5})([A-Z])$")
_ORDINAL = re.compile(r"^(\d+)(?:ST|ND|RD|TH)$")

# Words the two sources spell differently and that name the same thing. The
# directions are rewritten wherever they stand: leading ("WEST 131 STREET"),
# trailing ("PROSPECT PARK WEST") and inside a name ("WEST END AVENUE") alike,
# which is safe only because both sides are rewritten the same way.
_SPELLINGS = {
    "EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S",
    "FT": "FORT", "SAINT": "ST",
    # PTS truncates its 28-character address field, and writes BL for BLVD.
    "BL": "BLVD",
    # Street types the shared table does not know. Census follows USPS
    # Publication 28; PLUTO spells them out.
    "CRESCENT": "CRES", "EXPRESSWAY": "EXPY", "EXPWY": "EXPY", "TURNPIKE": "TPKE",
    "PLAZA": "PLZ", "SQUARE": "SQ", "ALLEY": "ALY",
}


def _house_number(token: str) -> str:
    """A house number in a form ``address_key`` can anchor on, or the token as-is.

    ``address_key`` needs an all-digit first token, and New York writes two kinds of
    house number that are not: Queens' hyphenated "84-74" and Brooklyn's lettered
    half-lots, "770A".

    **The hyphen is removed, and the part after it padded to two digits:**
    ``84-74`` → ``8474``, ``84-7`` → ``8407``. Removed rather than encoded because
    the two sources do not agree on where it goes, even for one house. PLUTO writes
    the Rockaways plain and the Census matcher hyphenates them ("432 BEACH 48
    STREET" against "4-32 BEACH 48TH ST"); Ridgewood the other way round ("18-75
    STANHOPE STREET" against "1875 STANHOPE ST"); and PLUTO has at least one
    Cambria Heights lot hyphenated in the wrong place ("1141-06 230 STREET" against
    "114-106 230TH ST"). Every one of those is the same house, and digit-for-digit
    the same number once the hyphen is gone. Two different houses that collide —
    "1-234" and "12-34" on one street inside one 80 m buffer — do not exist in a
    city where a street's numbers are either all hyphenated or all plain. Padding
    is what keeps 84-7 (that is, 84-07) apart from the plain 847.

    **A lettered half-lot keeps its letter:** ``770A`` → ``2`` + ``00770`` +
    ``01`` = ``20077001``. 770 and 770A are separate lots, often adjacent, so the
    letter cannot simply be dropped. Eight digits starting with 2 cannot equal any
    other number this produces: plain and de-hyphenated numbers run to seven
    digits at most.

    The rewritten form only ever exists inside the comparison; nothing displays it.
    """
    m = _HYPHENATED.match(token)
    if m:
        return f"{m.group(1)}{m.group(2).zfill(2)}"
    m = _LETTERED.match(token)
    if m:
        return f"2{m.group(1).zfill(5)}{ord(m.group(2)) - ord('A') + 1:02d}"
    return token


def _join_prefixes(tokens: list[str]) -> list[str]:
    """``MAC DOUGAL`` → ``MACDOUGAL``, ``MC KINLEY`` → ``MCKINLEY``.

    PTS writes the Gaelic prefixes as separate words — 613 lots on "MAC DONOUGH
    STREET", 284 on "MAC DOUGAL STREET", hundreds more on "MC KINLEY", "MC CLEAN",
    "MC LAUGHLIN" — and the Census matcher writes them closed up ("MACDOUGAL ST").
    Joined on both sides, as everything here is.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] in ("MAC", "MC") and i + 1 < len(tokens):
            out.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def _street_form(raw: str | None) -> str | None:
    """``raw`` rewritten into the one spelling both sources can be compared in.

    Only the part before the first comma — the street address — is rewritten; the
    locality tail is carried through untouched for ``address_key`` to discard as it
    always does. A unit marker ("#5A", "APT 3") is left exactly where it is so the
    shared parse still recognises and drops it.
    """
    text = " ".join(str(raw or "").split()).upper()
    if not text:
        return None
    head, sep, tail = text.partition(",")
    tokens = head.split()
    if not tokens:
        return None
    out = [_house_number(tokens[0])]
    rest = _join_prefixes(tokens[1:])
    for token in rest:
        m = _ORDINAL.match(token)
        if m:
            token = m.group(1)
        token = _SPELLINGS.get(token, token)
        # A street type in the middle of a name ("AVENUE J", "BEACH 116 STREET")
        # is canonicalised as well as a terminal one: address_key only looks at the
        # last token, so "AVENUE J" and "AVE J" would otherwise be different names.
        canonical = SUFFIXES.get(token.lower())
        out.append(canonical.upper() if canonical else token)
    return " ".join(out) + sep + tail


def _address_of(row: dict) -> str | None:
    return _street_form(row.get("Address"))


# --- the lot --------------------------------------------------------------------


def _parcel_id(row: dict) -> str | None:
    """The BBL as the city writes it — ten digits — or None.

    ArcGIS serves it as a double (4087860046.0), so it is cast through int rather
    than stringified, which would leave a trailing ``.0`` on every id.
    """
    bbl = num(row.get("BBL"))
    return str(int(bbl)) if bbl and bbl > 0 else None


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Real tax-lot records at (or within ``distance_m`` of) a point.

    DCP's mapping lots — on Finance's tax map, absent from PLUTO, ``PLUTOMapID``
    3 — are dropped here, before the lot is chosen, along with anything with no
    BBL. See "Placeholder polygons" in the module docstring: removing rows that
    could never be an answer can only turn "ambiguous" into "one real lot", never
    let a wrong lot through, because the address check that follows is untouched.
    """
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline)
    return [r for r in rows
            if _parcel_id(r) is not None
            and str(r.get("PLUTOMapID") or "").strip() != "3"]


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the tax lot this point belongs to, or None.

    The policy is ``_shared.select_parcel``'s; this adapter supplies only the
    rewrite that lets New York's two spellings of an address be compared at all.
    The reader's address is rewritten once here and PLUTO's on every candidate, by
    the same function. No locality set is needed: PLUTO keeps the borough out of
    ``Address``, and the Census matcher separates its city with a comma.
    """
    deadline = deadline_from(deadline)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        _street_form(address), _address_of)


# --- the record -----------------------------------------------------------------


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row's own release number.

    DCP republishes quarterly under an unchanged URL, so a hard-coded release
    would go stale silently and present old data at the same confidence as fresh.
    "26v2" is the second release of 2026.
    """
    version = str(row.get("Version") or "").strip()
    return (f"{DATA_VINTAGE}, release {version}"
            if re.fullmatch(r"\d{2}v\d+(\.\d+)?", version) else DATA_VINTAGE)


def _building_class(row: dict) -> str:
    return str(row.get("BldgClass") or "").strip().upper()


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the lot's record counts at least one dwelling.

    A recorded 0 is Finance saying "no residential units here" — a shop, a garage,
    a hotel. A missing count is allowed through: in 26v2 it is null only on newly
    declared condominium billing lots awaiting their unit count. See "A
    zero-dwelling lot reports no year" in the module docstring.
    """
    homes = num(row.get("UnitsRes"))
    return homes is None or homes >= 1


def _is_one_house(row: dict) -> bool:
    """One residential unit, in one building, of a one-family class.

    The gate on the floor area and the storey count, both of which PLUTO records
    for the whole lot. See "The condo trap" in the module docstring for what each
    of the three tests catches that the others do not.
    """
    return (num(row.get("UnitsRes")) == 1
            and num(row.get("NumBldgs")) == 1
            and _building_class(row).startswith("A"))


def _area_of_one_home(row: dict) -> float | None:
    """``BldgArea`` where it is one house's recorded gross area, otherwise None."""
    if not _is_one_house(row):
        return None
    if str(row.get("AreaSource") or "").strip() not in _RECORDED_AREA_SOURCES:
        return None
    area = num(row.get("BldgArea"))
    return area if area and area > 0 else None


def _stories_of_one_home(row: dict) -> int | None:
    """``NumFloors`` for a one-house lot, as a whole number, otherwise None.

    It is the tallest building's floor count, which on a one-building lot is the
    house's. A half storey (1.5, 2.5 — common here) is not rounded into a whole
    one, the same call the Cook and District adapters make.
    """
    if not _is_one_house(row):
        return None
    floors = num(row.get("NumFloors"))
    if floors is None or floors <= 0 or not float(floors).is_integer():
        return None
    return int(floors)


def _foundation(row: dict) -> str | None:
    """The basement code, in the label's vocabulary, where DOF vouches for it.

    Only for the one-, two- and three-family classes the data dictionary says the
    code is maintained for — ``A``, ``B`` and ``C0`` — and only on a one-building
    lot, so "the building's basement" names one building.
    """
    cls = _building_class(row)
    if not (cls[:1] in ("A", "B") or cls == "C0"):
        return None
    if num(row.get("NumBldgs")) != 1:
        return None
    return _BASEMENT.get(str(row.get("BsmtCode") or "").strip())


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None

    year = num(row.get("YearBuilt"))
    # 0 is Finance's "unknown", not the year zero; the dwelling check is the same
    # rule the area applies — see _says_a_home_is_here.
    year_built = int(year) if (year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100
                               and _says_a_home_is_here(row)) else None
    record = AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=_area_of_one_home(row),
        stories=_stories_of_one_home(row),
        foundation=_foundation(row) if _says_a_home_is_here(row) else None,
        # PLUTO carries no wall material and no condition grade. Left empty on
        # purpose, which lets the label fall back to its modelled estimate.
    )
    # A lot that matched but recorded no fact contributed nothing. The registry
    # drops it either way; returning None here keeps it out of the cache.
    return record if record.fields() else None


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What New York City's tax-lot records say is standing at this point, or None.

    ``address`` is the geocoder's matched address. It is used only to confirm the
    lot, and the lookup still works without one wherever the coordinate lands
    inside a boundary.

    Fails open on everything — a timeout, a 500, a renamed column, a lot the city
    has no record for. The caller then keeps whatever it had, which is the
    behaviour that existed before this adapter.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a lot, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("NYC assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
