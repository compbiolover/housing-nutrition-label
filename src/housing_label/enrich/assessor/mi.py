#!/usr/bin/env python3
"""Southeast Michigan — seven counties from SEMCOG's building inventory, by address.

Michigan assesses at the city and township level, about 1,500 assessing units, and
publishes no statewide parcel or assessor layer. The one source that spans several
counties with a year built on it is a regional council of governments' building
inventory: the Southeast Michigan Council of Governments (SEMCOG) keeps one
footprint per building for its seven counties, and fills each one's year built,
residential floor area, story count and housing units "from local assessing data"
("Updated missing or default square feet and year built from assessing rolls").

  ``gis.semcog.org/server/rest/services/Hosted/Buildings_2024/FeatureServer/2`` —
  1,742,760 footprints, 1,518,081 of them live residential buildings. Keyless,
  layer id **2** (not 0), verified live.

Wayne, Oakland, Macomb, Washtenaw, Livingston, St. Clair and Monroe hold 2,115,386
homes by this repository's own county table — 45.8% of Michigan's. SEMCOG's own
unit totals track that table closely (Wayne 795,951 against 801,083; Oakland
557,186 against 561,348), and the year built is present on 86–96% of residential
units depending on the county (St. Clair lowest, Washtenaw highest).

Three words this file leans on:

* **footprint** — the outline of one building traced from aerial imagery, as
  opposed to a parcel, which is the outline of a piece of land.
* **APN** — the assessor's parcel number, in whatever format the local assessing
  unit uses (Detroit ``22069303.``, Oakland ``88-20-22-354-021``, Wayne suburbs
  ``46 095 05 0031 000``). Several buildings can share one.
* **build type** — SEMCOG's use class: 81 single-family, 82 attached condo
  building, 83 apartment building, 84 mobile home, and 22 non-residential classes
  (11–95) after the NAICS sectors.

A building layer, not a parcel layer, and what that does to the lookup
----------------------------------------------------------------------
Every other adapter asks which *parcel* a point is inside. A parcel runs to the
front lot line, so a rooftop geocode lands in it and even an interpolated one
often does. A footprint is the house itself, set back from the street, and the
Census matcher puts most addresses on the street centerline: containment found a
building in none of roughly 70 research probes, and in 0 of the 337 verification
lookups below. So in practice every answer comes from the buffered,
address-confirmed path of ``_shared.select_parcel`` — the building is accepted
only when its address agrees with the geocoder's, uniquely — and how far that
buffer reaches decides how much of the region resolves.

The shared ``SEARCH_RADIUS_M`` of 80 m is sized for parcels ("wide enough to cross
a road and a front yard"), and is too short for footprints. Measured on the 314
verification homes whose own building agrees with the geocoder's address, the
distance from the Census point to the footprint is 28 m at the median, 95 m at
p90, 162 m at p95, 243 m at p98 and 458 m at worst — farmhouses at the end of
long drives, and points the matcher interpolated along a rural road. Over all 337
geocoded homes, with the shared selection rule and no twin check:

  ======  ===============  =============  =========  ========
  radius  unique, correct  unique, wrong  ambiguous  no match
  ======  ===============  =============  =========  ========
   80 m              272              1          2        62
  150 m              295              2          3        37
  250 m              305              2          3        27
  400 m              308              2          3        24
  600 m              310              1          4        22
  ======  ===============  =============  =========  ========

(the research run found the same curve: 26/40 at 80 m, 32/39 at 150 m, 36/39 at
250 m). So ``fetch`` maps the buffered distance ``select_parcel`` asks for to this
module's own ``BUFFER_RADIUS_M`` of 250 m; ``_shared`` is not changed, and every
other adapter keeps 80 m. 250 m is p98 of the measured distances and 33 homes more
than 80 m (10% of the sample); going to 400 m buys 3 more while more than doubling
the area in which a same-address building that is not the reader's can stand. The
"wrong" column is what the twin check below exists for: both of its rows at 250 m
are refused by it, which is how the shipped adapter reaches zero.

Why widening is safe here, and what keeps it safe
-------------------------------------------------
The radius never decides which building answers; the address does. A building is
accepted only when its street address agrees with the geocoder's in every part —
house number, street name, street type and directional — and only when exactly one
building inside the radius agrees. Widening adds candidates that must still pass
that test, so it can turn "none" into "one" (the coverage gain) and "one" into
"two" (a refusal), and can turn a wrong answer into a right one only by refusing
it. The one way it can name the wrong building is a SECOND building with the very
same address inside the radius while the right one is not — and that is what the
two guards below exist for.

1. **Only the house number's own candidates are fetched.** The buffered query
   carries ``address LIKE '<number> %'`` (and the same after a ``" | "``), so it
   returns only buildings that could pass the address test at all. That keeps a
   250 m circle in dense Detroit — several hundred footprints — to a response of a
   few rows, far under the 2,000-row cap, and changes no decision: a row with a
   different house number could never have matched.
2. **A twin anywhere nearby refuses the answer** (``_has_a_twin``). Once a building
   is chosen, a second query looks ``TWIN_RADIUS_M`` (1 km) around the point for any
   OTHER live dwelling with the same address — or the same address but for a
   directional, which the Census matcher drops — and finding one refuses the
   lookup. This is the case the buffer cannot see by itself, and the verification
   found both kinds: "3678 School Rd", Monroe County, is a 1921 house 85 m from the
   geocode and a 2004 house on its own parcel 420 m away, and the reader's was the
   2004 one; typed "4963 N Capac Rd" came back as "4963 CAPAC RD", a different house
   on a different parcel 90 m from the reader's. Each was one confirmed hit inside
   the buffer and would have been reported as the reader's home.

Several buildings at one address is common enough that it had to be measured
rather than assumed: 3,956 address-and-ZIP combinations are shared by 18,115 live
residential buildings — 0.38% of single-family buildings (a house and a second
dwelling, or one house traced twice) and 21% of condominium and apartment
buildings (complexes filed under one street address). In every such case the
adapter refuses; it never picks one. How far apart such buildings stand is what
sizes ``TWIN_RADIUS_M``: over 400 randomly chosen shared address strings (5,849
pairs of buildings), 5,663 pairs are within 1 km of each other, 18 are 1–10 km
apart, and 168 are more than 10 km apart (the same address in another city). So
1 km catches 99.7% of the twins standing within 10 km; 1.5 km would add about one
pair in 5,849 and measured twice as slow (p95 0.61 s against 0.34 s).

Mobile homes and mixed-use buildings count as candidates but never answer. They are
dwellings — a reader at a mobile-home park's address may well live in one — so
they are fetched (``build_type`` 84, or any building with ``housing_units > 0``)
and can make a match ambiguous or be the match, but a lookup that lands on one
returns nothing:

* **Mobile homes** are 68,000 algorithmic "AUTOMATIC" pseudo-footprints whose years
  spike at 2020 (7,409) and 2024 (5,707) — the inventory's own dates, not
  construction dates — and otherwise look like park-level years.
* **Non-residential classes** (retail with apartments upstairs, 830 buildings;
  offices, 228; …) carry the floor area and year of a building whose use is not a
  home.

Leaving them out of the candidates instead would turn "a manager's house and 300
mobile homes at one park address" into one clean match on the manager's house. For
the same reason a mobile home's lot number — "10885 EDWARDS LN LOT 324", on 17,540
of them — is read as a unit of the park's address (``_addresses``): read as part of
the street name, the lots would match nothing and the house would again match
alone.

What this source carries
------------------------
* ``year_built`` — "Year structure was built. A value of 0 indicates the year built
  is unknown." Never null; 0 on 33,728 live residential buildings. There is no
  effective-year column to confuse it with. In the research run, for 195 random
  Detroit residential parcels joined on APN, SEMCOG's year equalled the City of
  Detroit assessor's own on **195/195**.
* ``res_sqft`` — "Square footage devoted to residential use", whole-building. See
  the condo trap below; and "Square footage evenly divisible by 100 is an estimate,
  based on size and/or type of building, where the true value is unknown", which is
  refused for the reason ``_area_of_one_home`` gives. Against Detroit's
  ``total_floor_area`` on 60 random houses it was equal on 20 and within 10% on 30;
  where they differ Detroit's is almost always the larger (744 against 1,254 on a
  one-story house), consistent with Detroit counting area SEMCOG's figure does not.
  It is reported as SEMCOG's figure, not as Detroit's.
* ``stories`` — "For single-family residential this number is expressed in quarter
  fractions from 1 to 3 stories: 1.00, 1.25, 1.50, etc." The label's field is a
  whole number, and 1.25-, 1.5- and 1.75-story houses (290,000 of them) are not
  rounded into one — the same call the District and Cook make for half stories.
* ``housing_units`` and ``build_type`` — what decides whether the area and the
  year describe one home.

No wall material, foundation or condition is in the layer, so those stay empty and
NSI's estimate stands for them.

The condo trap, and the duplex filed as a house
-----------------------------------------------
One row is one BUILDING. An attached-condo building (82) or an apartment building
(83) carries the units' summed floor area and the building's year, and SEMCOG's
documentation adds that "traditional duplexes where each unit is owned by the same
entity are also classified as single-family housing" — 29,178 live 81 buildings
record ``housing_units`` of 2. So the floor area is reported only for a
single-family building recording exactly one unit, and never divided by a count.

The year built is the building's and is right for every unit in it, so it comes
through for all three residential classes. So does a whole-number story count:
for a multi-unit building the label's ``stories`` is building context in the first
place (``simulate/dimensions.py`` keeps it only for multi-family, and the flood
floor factor divides by it), and SEMCOG's row is that building's own count — not a
tower's floor count stamped onto a unit record, which is the trap Utah's adapter
refuses. A recorded ``housing_units`` of 0 refuses the whole record, as Florida's
dwelling count refuses the year; it occurs once.

Addresses
---------
``address`` is the street address alone ("14209 SUNBURY ST"), with the ZIP in its
own column, so no locality trim is needed. Two shapes are SEMCOG's own:

* A building on two streets carries both, separated by ``" | "`` — "1004 8TH ST |
  742 PINE ST" (1,181 residential buildings). Each part is a real address of that
  building, so the part that agrees with the lookup's address is the one offered
  for confirmation.
* Attached condos and apartments are often filed under a range — "3379-3401
  BURBANK DR" on 59,831 residential rows. ``address_key`` cannot anchor on a range,
  and a reader's "3385 Burbank Dr" names one unit inside it, so these buildings do
  not confirm and the lookup refuses. That is a coverage cost, not a risk, and it
  falls almost entirely on multi-unit buildings, where only the year was ever going
  to be reported.

Timing
------
Measured over the 337 verification lookups, sequentially, through the product's
own HTTP session:

  =========================================  ======  ======  ======  ======
  request                                    median     p90     p95     max
  =========================================  ======  ======  ======  ======
  "which footprint is this dot inside?"      0.08 s  0.09 s  0.10 s  0.47 s
  "this house number within 250 m?"          0.09 s  0.12 s  0.12 s  0.29 s
  "a twin of it within 1 km?"                0.17 s  0.31 s  0.34 s  0.52 s
  whole lookup (all three)                   0.33 s  0.49 s  0.53 s  0.90 s
  =========================================  ======  ======  ======  ======

The house-number filter is what keeps the buffered request fast: the research
run's unfiltered buffered queries took a median 0.20 s and up to 0.46 s. No
single request came near the shared one-second read slice and no lookup near the
shared four-second budget, so this adapter keeps the SHARED clock, as Utah's does;
``READ_SLICE_S`` and ``LOOKUP_TIMEOUT`` are named so every request visibly passes
them, and a test pins their sum under ``config.UPSTREAM_HOST_BUDGET``. A lookup
makes at most three requests — containment, buffer, twin — and the twin search
runs only once a building has been chosen.

License
-------
The item's license field reads: "By using this data, you agree to the SEMCOG
Copyright License Agreement" (https://maps-semcog.opendata.arcgis.com/pages/
copyright-license-agreement, read 2026-10-03). The agreement grants "a perpetual,
non-exclusive, royalty-free license to use, reproduce, modify, distribute, publish,
transmit, display and/or create derivative works of the Works", with no restriction
on commercial use or caching, under Michigan law, with a warranty disclaimer and
an indemnity. Its one operative condition is the notice: "Use of a Work shall
prominently state as follows with the appropriate year inserted: 'Copyright © 2019
SEMCOG. All Rights Reserved. Reproduction or Use Without Permission is
Prohibited.'" — so ``ATTRIBUTION``, which travels with every value onto the label,
carries that notice with the year this inventory was published (the layer was last
edited 2025-06-13). The "without permission" wording does not contradict the use:
the agreement is the permission. The posture is the one every adapter takes
regardless — query live, cache in process, bundle nothing.

What the adapter is worth, end to end
-------------------------------------
350 live residential buildings drawn at random from the layer itself (random
object ids, so in proportion to the stock: 333 single-family, 12 attached-condo
buildings, 5 apartment buildings), stratified by county — Wayne 80, Oakland 60,
Macomb 50, and 40 each in Washtenaw, Livingston, St. Clair and Monroe. Each was
typed as "<address>, <mailing city>, MI <ZIP>", geocoded through the Census matcher
and ``assessor_address`` exactly as the product does, and looked up:

  =====================================  =======
  sampled                                    350
  geocoded                                   337   (13 unknown to Census)
  routed to one of the seven counties        337
  resolved                                   305   (90.5% of those geocoded)
  **matched to the wrong building**        **0**
  year built exact                       296/296   (9 resolved had year 0)
  floor area reported / exact            296/296
  stories reported / exact               246/246
  footprint containing the point           0/337
  =====================================  =======

Per county, resolved of geocoded: Wayne 74/80, Oakland 52/57, Macomb 45/49,
Washtenaw 35/37, Livingston 36/39, St. Clair 34/37, Monroe 29/38.

The 32 that did not resolve: 15 range addresses ("3359-3361 WAVERLY ST"), every
one of them a duplex, condo or apartment building; 6 where the geocoder's address
and SEMCOG's disagree — 4 a directional dropped or added ("6965 ZEEB RD" for
SEMCOG's "6965 S ZEEB RD"), which the shared comparison refuses on purpose, 1 a
street spelled two ways ("SHACKETT" against SEMCOG's "SHACKET"), and 1 typed as
SEMCOG's own two-street string, which no reader would write; 5 footprints more than 250 m from the geocode,
and 1 geocoded 5.3 km from its house; 3 complexes with several buildings at the
address inside the buffer; and the 2 twin refusals above, each of which would
otherwise have been the wrong house. The twin check cost no correct answer in the
sample.

Privacy, and why the field list is short
----------------------------------------
The layer carries ``ref_name`` — "Owner or business name of the building, if
known" — and the editors' user names (``created_user``, ``last_edited_user``).
None is an input to the label and none is requested; neither are the LiDAR height,
group-quarters capacity or the non-residential floor area. Eight columns are
requested by name (two by the twin search) and the shared helper refuses ``*``. Nothing from this source is
written into the repository.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    DIRECTIONS, address_key, arcgis_parcels, cache_bucket, deadline_from, num,
    same_address, select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

# The seven counties SEMCOG's inventory covers, each in full — so no county is
# claimed for a part of it. A test checks them against the repository's own
# county table.
COUNTY_FIPS = frozenset({
    "26163",   # Wayne (Detroit)
    "26125",   # Oakland
    "26099",   # Macomb
    "26161",   # Washtenaw
    "26093",   # Livingston
    "26147",   # St. Clair
    "26115",   # Monroe
})

NAME = "SEMCOG"
#: Carries the copyright notice SEMCOG's license requires on every use; see
#: "License" in the module docstring.
ATTRIBUTION = ("SEMCOG Building Footprints 2024, from local assessing rolls. "
               "Copyright © 2025 SEMCOG. All Rights Reserved. Reproduction or Use "
               "Without Permission is Prohibited.")
DATA_VINTAGE = "SEMCOG building inventory, current as of December 31, 2024"

BUILDINGS_URL = ("https://gis.semcog.org/server/rest/services/Hosted/Buildings_2024"
                 "/FeatureServer/2/query")

#: How far the buffered, address-confirmed search reaches, in meters, in place of
#: the shared 80 m. p98 of the measured distance from a Census geocode to the
#: home's own footprint; see "A building layer, not a parcel layer" in the module
#: docstring for the curve. It is safe to widen only because the answer still
#: needs an exact, unique address match and survives the twin check.
BUFFER_RADIUS_M = 250

#: How far around the point a second live dwelling with the same (or a
#: directional-confusable) address refuses the answer. 99.7% of same-address
#: building pairs within 10 km of each other are within 1 km; see "Why widening is
#: safe here". Must exceed BUFFER_RADIUS_M, or a twin could hide outside it.
TWIN_RADIUS_M = 1000

#: The read slice and whole-lookup budget: the SHARED defaults, kept on purpose and
#: named so every request visibly passes them. Over 337 lookups the slowest request
#: took 0.52 s and the slowest three-request lookup 0.90 s; see "Timing".
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

# Only what the label scores, plus what decides whether a row is a home and whether
# its area describes one. ref_name (owner or business name), the editor user names,
# median_hgt, gqcap and nonres_sqft are deliberately absent.
_FIELDS = ("building_id,apn,address,build_type,year_built,res_sqft,stories,"
           "housing_units")

# Every building someone may live in, and nothing demolished. SEMCOG keeps
# demolished buildings in the inventory with their date ("To view only current
# buildings, you must filter the data layer using the expression, WHERE DEMOLISHED
# IS NULL") — 59,725 of them — so a query without this clause offers a house that
# was torn down as a candidate, and can make the house that replaced it ambiguous
# or, worse, be the only match. Mobile homes (84) and mixed-use buildings are
# candidates but never answers; see the module docstring.
_DWELLINGS = "demolished IS NULL AND (build_type IN (81,82,83,84) OR housing_units > 0)"

#: The build types a record may be reported from: single-family, attached condo
#: building, apartment building.
_ANSWERS = frozenset({81, 82, 83})
_SINGLE_FAMILY = 81

# Two addresses of one building, as SEMCOG writes them.
_SEPARATOR = " | "


def _building_id(attrs: dict) -> int | None:
    """SEMCOG's identifier for this building, or None if it has none."""
    bid = num(attrs.get("building_id"))
    return int(bid) if bid is not None else None


def _parcel_id(attrs: dict) -> str | None:
    """The local assessor's parcel number, which is what a reader can take to the
    city or township's own roll; SEMCOG's building number where it has none.

    "Has none" includes a placeholder: every attached-condo building (30,851 of
    them) carries the literal ``apn`` "CONDO BUILDING", since its units are the
    parcels, and two buildings carry "NOT ASSIGNED YET". A parcel number with no
    digit in it is not one, and printing "parcel CONDO BUILDING" beside an observed
    value would trace it to nothing.
    """
    apn = str(attrs.get("apn") or "").strip()
    if any(c.isdigit() for c in apn):
        return apn
    bid = _building_id(attrs)
    return f"SEMCOG building {bid}" if bid is not None else None


# A mobile-home lot number appended to the park's street address: "10885 EDWARDS
# LN LOT 324" (17,540 of the 68,407 mobile-home rows). Only a TRAILING "LOT" whose
# token carries a digit — "809 LITTLE SCHOOL LOT LAKE RD" is a street name, and 33
# houses stand on it and its neighbor Big School Lot Lake Rd.
_MOBILE_HOME_LOT_RE = re.compile(r"\s+LOT\s+\S*\d\S*$", re.I)


def _addresses(attrs: dict) -> list[str]:
    """Each street address SEMCOG records for this building, as the comparison
    should read it.

    A mobile-home lot number is removed, which is a respelling specific to this
    source, and its purpose is to make MORE candidates collide, not fewer. The
    shared parse does not know "LOT" as a unit marker, so "10885 EDWARDS LN LOT 324"
    would read as a street named "Edwards Ln Lot 324" and match nothing. Then a park
    whose office or manager's house is filed as a single-family building at the
    park's own address would confirm that one house, uniquely, for every reader in
    the park — the Census matcher drops "Lot 324" — and report its year as theirs.
    With the lot read as a unit, the park's homes are candidates at the park's
    address, the match is ambiguous, and the lookup refuses.
    """
    raw = str(attrs.get("address") or "")
    parts = (_MOBILE_HOME_LOT_RE.sub("", p.strip()) for p in raw.split("|"))
    return [p for p in parts if p]


def _address_of(attrs: dict, wanted: str | None) -> str | None:
    """The building's address to confirm against: the part of a two-street address
    that agrees with ``wanted`` where one does, otherwise the first.

    A corner building filed as "1004 8TH ST | 742 PINE ST" is genuinely at both, so
    offering the part the reader named is not a loosening — the comparison that
    follows is the same strict one — while offering the joined string would match
    neither, since ``address_key`` reads "742 PINE ST" as part of the street name.
    """
    parts = _addresses(attrs)
    if not parts:
        return None
    if wanted:
        for part in parts:
            if same_address(wanted, part):
                return part
    return parts[0]


def _number_clause(numbers) -> str:
    """``address`` beginning with one of these house numbers, as either part of a
    two-street address. ``numbers`` are all-digit strings from ``address_key``, so
    there is nothing to quote."""
    terms = []
    for n in sorted(numbers):
        terms += [f"address LIKE '{n} %'", f"address LIKE '%{_SEPARATOR}{n} %'"]
    return " AND (" + " OR ".join(terms) + ")"


def _buildings(lat: float, lon: float, distance_m: float, number: str | None,
               *, deadline: float) -> list[dict]:
    """Live dwelling buildings containing the point, or near it with this number.

    ``distance_m`` is whatever ``select_parcel`` asks for: 0 for containment, and
    ``_shared.SEARCH_RADIUS_M`` for the buffered search, which is read as "search
    the buffer" and answered at ``BUFFER_RADIUS_M`` — see the module docstring for
    why 80 m is too short for footprints.

    The buffered search returns only buildings whose address starts with the house
    number being confirmed, which changes no decision (no other row could match) and
    keeps the response small. Containment is not filtered: a point inside two
    overlapping footprints must stay ambiguous whatever their addresses say, which
    is the rule ``select_parcel`` applies.

    Rows with no building id are dropped as non-records, the shape
    ``select_parcel`` sanctions.
    """
    if distance_m:
        if number is None:
            return []                   # nothing could confirm; skip the request
        rows = arcgis_parcels(BUILDINGS_URL, lat, lon, _FIELDS, BUFFER_RADIUS_M,
                              deadline=deadline, read_slice=READ_SLICE_S,
                              where=_DWELLINGS + _number_clause({number}))
    else:
        rows = arcgis_parcels(BUILDINGS_URL, lat, lon, _FIELDS, 0,
                              deadline=deadline, read_slice=READ_SLICE_S,
                              where=_DWELLINGS)
    return [r for r in rows if _building_id(r) is not None]


def _loose_key(address: str):
    """``address_key`` with the directionals set aside: what is left of an address
    once the one part the Census matcher routinely drops is gone. A name made only
    of directionals ("100 N ST") keeps them, since they are the whole name."""
    key = address_key(address)
    if key is None:
        return None
    name = tuple(t for t in key[1] if t not in DIRECTIONS) or key[1]
    return key[0], name, key[2]


def _confusable(a: str, b: str) -> bool:
    """Whether two addresses could be the same reader's address to the geocoder:
    the same house number and street name once directionals are set aside, and no
    two different street types. Strictly looser than ``same_address``."""
    ka, kb = _loose_key(a), _loose_key(b)
    if ka is None or kb is None or ka[:2] != kb[:2]:
        return False
    return ka[2] is None or kb[2] is None or ka[2] == kb[2]


def _has_a_twin(lat: float, lon: float, row: dict, *, deadline: float) -> bool:
    """Whether another live dwelling within ``TWIN_RADIUS_M`` has an address the
    chosen building's could be confused with. See "Why widening is safe here" in
    the module docstring.

    "Confused with" is deliberately wider than the confirmation test. It includes
    the same address exactly — an apartment complex, a farmhouse with a second
    house down the lane — and the same address with a different or missing
    directional, because the Census matcher drops directionals it cannot place:
    typed "4963 N Capac Rd" (St. Clair County) came back as "4963 CAPAC RD", which
    is a different house of SEMCOG's 90 m away with its own parcel number, and
    confirming it would have reported the neighbor's home.

    Every address of the chosen building is checked, not only the one that
    confirmed it, because a twin of either is a second building a reader at that
    address might mean. A building whose addresses do not parse cannot be
    twin-checked and is not refused for it: it can only have been reached by
    containment, where the point is on the building itself.
    """
    own = [a for a in _addresses(row) if address_key(a)]
    if not own:
        return False
    numbers = {address_key(a)[0] for a in own}
    rows = arcgis_parcels(BUILDINGS_URL, lat, lon, "building_id,address",
                          TWIN_RADIUS_M, deadline=deadline, read_slice=READ_SLICE_S,
                          where=_DWELLINGS + _number_clause(numbers))
    me = _building_id(row)
    return any(_building_id(other) != me
               and any(_confusable(a, b) for a in own for b in _addresses(other))
               for other in rows)


def _building_at(lat: float, lon: float, address: str | None = None,
                 *, deadline: float | None = None) -> dict | None:
    """The residential building this point and address name, or None.

    Which building is the dangerous decision, so it goes through
    ``_shared.select_parcel`` like every adapter's, and then through two refusals
    of this source's own: a candidate that is a mobile home or a non-residential
    building, and a chosen building with a twin.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    key = address_key(address) if address else None
    number = key[0] if key else None
    row = select_parcel(
        lambda d: _buildings(lat, lon, d, number, deadline=deadline),
        address, lambda a: _address_of(a, address))
    if not row or num(row.get("build_type")) not in _ANSWERS:
        return None
    if _has_a_twin(lat, lon, row, deadline=deadline):
        return None
    return row


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the building is recorded as holding at least one dwelling.

    An explicit 0 is SEMCOG saying nobody lives there, and refuses the record — the
    year, as Florida's dwelling count does, and the story count with it; a missing
    count says nothing and is allowed through. Among live residential buildings the
    count is 0 exactly once (121 Washington St, filed single-family) and never
    missing, so this costs nothing and closes the case.
    """
    units = num(row.get("housing_units"))
    return units is None or units >= 1


def _area_of_one_home(row: dict) -> float | None:
    """``res_sqft`` when it is one home's measured area, otherwise None.

    * Only a single-family building recording exactly one housing unit. An
      attached-condo or apartment building's figure is the whole building's, and
      SEMCOG files owner-rented duplexes as single-family with 2 units.
    * Not a multiple of 100: SEMCOG's own documentation says such a value "is an
      estimate, based on size and/or type of building, where the true value is
      unknown". It is 3.9% of single-family rows (57,323 of 1,459,758) against the
      1% a measured area would land on a round hundred by chance, so most of them
      are estimates, and an estimate carrying the ``observed`` tag is the failure
      this layer exists to prevent. The real 1,200-square-foot houses this also
      refuses fall back to the label's model, which costs a little coverage and no
      accuracy.
    """
    area = num(row.get("res_sqft"))
    if area is None or area <= 0 or area % 100 == 0:
        return None
    if num(row.get("build_type")) != _SINGLE_FAMILY or num(row.get("housing_units")) != 1:
        return None
    return area


def _stories(row: dict) -> int | None:
    """A whole-number story count, or None.

    Single-family stories come in quarter steps (1.25, 1.5, 1.75 …), and a fraction
    is not rounded into a whole story — the District's and Cook's rule. For an
    attached-condo or apartment building the count is the building's, which is what
    the label's ``stories`` means for a multi-unit home; see the module docstring.
    """
    v = num(row.get("stories"))
    return int(v) if v is not None and v >= 1 and float(v).is_integer() else None


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _building_at(lat, lon, address)
    # A building recorded as holding no dwelling is not anybody's home, so none of
    # its facts describe the reader's: not the year, and not the story count either.
    if not row or not _says_a_home_is_here(row):
        return None

    year = num(row.get("year_built"))
    # 0 is SEMCOG's "unknown", not the year zero.
    year_built = int(year) if year and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100 else None
    sqft = _area_of_one_home(row)
    stories = _stories(row)
    # A building that matched but recorded nothing contributed nothing; keep it out
    # of the cache. The registry drops it either way.
    if year_built is None and sqft is None and stories is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=DATA_VINTAGE,
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
        stories=stories,
        # The inventory carries no wall material, foundation or condition. Left
        # empty on purpose, so the label falls back to its modeled estimate.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What SEMCOG's building inventory says is standing at this point, or None.

    ``address`` is the geocoder's matched address. Here it is close to required:
    without it only a point that lands on a building's own footprint can answer,
    which a rooftop coordinate does and a Census street geocode almost never does.

    Fails open on everything — a timeout, a 500, a truncated response, a renamed
    column, a building SEMCOG has no record of. The caller then keeps whatever it
    had, which is the behavior that existed before this adapter.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a building, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("SEMCOG assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
