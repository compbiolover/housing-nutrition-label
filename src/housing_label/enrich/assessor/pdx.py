#!/usr/bin/env python3
"""Portland, Oregon metro — Multnomah, Washington and Clackamas from Metro's RLIS taxlots.

Oregon has no statewide year built that anyone publishes as a service, but the
Portland region has something close to Florida's arrangement. Metro, the elected
regional government, runs the Regional Land Information System (RLIS): every
quarter it takes the three county assessors' parcel maps and rolls, standardizes a
selection of their columns into one schema, strips the owner names, and publishes
the result as one keyless layer:

  ``Taxlots_(Public)/FeatureServer/3`` — "Taxlots (Public)", 647,192 taxlots in
  Clackamas, Multnomah and Washington counties, last refreshed 2026-07-17,
  verified live 2026-10-04.

One request, like Florida: the polygon and the assessor's record are one feature.
Three words this file cannot avoid:

* **taxlot** — Oregon's word for a parcel: one polygon on the county's map, keyed
  by its map-and-lot number (``TLID``, "1S1E04AD  -60062").
* **tax account** — the assessor's record on that taxlot (``PRIMACCNUM``: the
  R-number in Multnomah and Washington, the account number in Clackamas).
* **property class** — the Department of Revenue's three-digit code each county
  assigns to every account (OAR 150-308-0310): first digit the use (1 residential,
  2 commercial, 3 industrial, 4 tract, 5 farm, 6 forest, 7 multi-family of five or
  more homes, 8 recreation, 9 exempt, 0 miscellaneous), second the zoning, third
  the improvement (0 vacant, 1 improved, 2 condominium, 9 manufactured structure).

Coverage: all of all three counties
-----------------------------------
Metro's planning region stops at the urban growth boundary, so it was worth
checking that RLIS does not. It does not: the metadata's spatial domain is the
three counties, and measured, each county's taxlots fill that county's whole
Census footprint — the layer's extent per county agrees with TIGERweb's county
extent to within 0.02° on every side, out to Government Camp on Mount Hood (752
taxlots), Rhododendron, Corbett, Banks and Gaston. Clackamas County's own CMap
taxlot layer holds 163,927 taxlots; RLIS holds 163,936 for Clackamas. So no
county is partly covered, the share of housing outside RLIS is nil, and
``COUNTY_FIPS`` is the three counties outright: 788,780 homes (ACS, this
repository's ``year_built_county.csv``) — Multnomah 371,179, Washington 243,278,
Clackamas 174,323.

The year built: filled, and the actual year
-------------------------------------------
``YEARBUILT``, "Year structure was built" in Metro's attribute definitions.
Measured over the whole layer, the share of residential taxlots carrying one:

  ==========  =====================  =====================  ===================
  county      single-family (SFR)    multi-family (MFR)     rural res. (RUR)
  ==========  =====================  =====================  ===================
  Multnomah   197,302 / 197,706 100%  43,443 / 46,147  94%   1,467 / 1,899  77%
  Washington  146,428 / 146,888 100%  12,463 / 14,508  86%   3,370 / 3,502  96%
  Clackamas   105,588 / 111,562  95%   4,927 /  6,421  77%   7,276 / 9,487  77%
  ==========  =====================  =====================  ===================

It is the actual year, not an effective one: Multnomah's single-family years heap
on 1925, 1926 and 1910 and put 63,000 houses before 1940, which is Portland's
streetcar-era stock, not a condition score; and on 120 Clackamas houses drawn at
random, RLIS's year equals the county's own ``YEARBLT`` (CMap) on all 120. Against
the City of Portland's building inventory (whose own figures are partly modeled)
it agrees on 106 of 110 single-family taxlots; the four that differ were not
adjudicated.

Two values are not years. **1800** is Multnomah's placeholder — five records, then
nothing until 1846, the year after Portland was platted — and is refused by value,
as North Carolina refuses Wilkes County's 1600. **9999** (675 Multnomah records)
falls outside the plausible range. Multnomah also writes **2027** on lots still
under construction; every one is a vacant-class lot, which is refused below.

The floor area, and when it is one home's
-----------------------------------------
``BLDGSQFT`` is "Square footage of building(s)". On a house it is the house's
living area: on the 120 Clackamas houses it equals the county's ``LIVING_AREA`` on
all 120, and in Multnomah it agrees with the city inventory's building area
(median ratio 1.00). Washington publishes no independent area to compare against;
its single-family distribution (median 1,882 sq ft, 5th–95th 1,104–3,503) sits
between the other two. The plural in the definition is the warning, so the area
is reported only where the record says it is ONE home:

* **Class 1x1 with land use SFR** — residential, improved, by itself on its
  taxlot. Class 1 includes two-to-four-unit buildings, which Multnomah files
  under a house-number range ("2405-2411 SE CORA ST"); a range address, a unit
  designator in the site address, or a taxlot holding several accounts refuses
  the area. In the city inventory, 106 of 110 sampled single-family taxlots
  hold one residential unit; the two exceptions inspected are range addresses
  ("4130-4136 N WILLIS BLVD").
* **A condominium unit (class 1x2) whose own site address names the unit the
  reader typed** — see below.

Farm, forest and tract records (classes 4, 5, 6), apartment buildings (7),
manufactured structures (x9) and everything else keep their year and lose their
area: "building(s)" on a farm can be a house and a barn.

Condominiums: each unit is its own taxlot
-----------------------------------------
Measured, not assumed, because it is the opposite of Florida. Every condominium
unit is a separate tax account on a separate taxlot — a stand-in polygon of about
20 square feet, laid out in a grid on the building's site: the 143 units of 1500
SW 11th Ave are 143 polygons, each with ``BLDGSQFT`` the unit's own area (603 sq
ft for #1006). Parking spaces and storage units are accounts too, with a blank
site address.

So a reader who typed a unit is matched to that unit's own taxlot — any taxlot
naming a different unit is dropped, and so are the unit-less accounts filed under
the bare street address (the building's commercial spaces and common elements),
once some taxlot names the reader's unit — and gets the building's year and the
unit's own area. A reader who typed none faces every unit at one address, which
``select_parcel`` correctly calls ambiguous. **Washington County writes no unit
into a condominium's site address** (0 of 13,500 condo accounts; Clackamas 2,051
of 5,465, Multnomah 18,530 of 42,038), so there the units cannot be told apart by
address at all: a geocode landing inside one unit's polygon gets the building's
year — the same for every unit of an address on 99% of Washington's condo
addresses — and never an area.

Class 2x2 is a **commercial** condominium, and RLIS labels it "MFR" anyway:
measured live, office suites of 5,000-plus square feet at 13339 NE Airport Way. So
the property class is read beside Metro's land use, not instead of it.

Taxlot Additional Records, and why it is not queried
----------------------------------------------------
Metro publishes a second layer (``Taxlot_additional_records_public``) holding
the extra accounts of taxlots that carry more than one — flagged on the taxlot by
``HAS_MANY``. It is not where condominiums live (above), and it is small: 3,470
records on 2,758 taxlots (0.4%), mostly commercial and public. On a residential
one, the polygon usually carries the land account with year 0 and the dwelling
sits in the extra record (9015 N Drummond Ave; a manufactured home on its own
account). Which account the reader means is then not something the address can
say, so a ``HAS_MANY`` taxlot answers nothing — at most 1,129 taxlots with a year,
for the price of a second service never asked.

Which taxlots say nobody lives there
------------------------------------
Metro's ``LANDUSE`` (derived from the class; its metadata warns it is "not
considered reliable for parcel specific applications", which is why it is used
only to refuse, never to translate) and the class itself are the only statements.
An explicit COM, IND, VAC or PUB land use refuses the year, and so does a class
whose use is commercial (2) or industrial (3), whose improvement digit is vacant
(0) — Washington writes 2025 on 1,438 class-100 lots finished after the
assessment date — or which is miscellaneous (0: utilities, machinery) other than a
manufactured structure. A blank land use, or one of the few Clackamas codes
written without the leading zero ("81", "15"), is silence and refuses nothing.

Addresses
---------
``SITEADDR`` is the street address alone, city in its own column; no locality
trim is needed. Two spellings are local:

* **Hyphens.** RLIS writes "7280 SW BEAVERTON-HILLSDALE HWY" on some taxlots and
  "10090 SW BEAVERTON HILLSDALE HWY" on others (also Tualatin-Sherwood and
  Scholls-Sherwood, about 500 taxlots), and the Census matcher returns the
  hyphenated form; a hyphen between two letters is read as a space on both sides
  (``_unhyphenated``).
* **Relative locators.** Multnomah files a lot beside a house under the house's
  number with a locator — "5655 S/ SE HARNEY DR" (south of), "1610 WI/ NE 66TH
  AVE" (within). The locator is a name token to the shared comparison, so such a
  lot can never be confirmed as the named house; the reader means the house.

The buffered search asks only for taxlots whose address starts with the house
number (``SITEADDR LIKE '<number> %'``). Downtown, 80 m around a tower reaches the
stand-in polygons of every unit and parking space nearby: 1,603 taxlots at 1500 SW
11th Ave, and the full 2,000-row cap — a truncated page, refused — at 1001 NW
Lovejoy St, where the filter returns 125. A taxlot whose address does not begin
with the number can never be confirmed, so the filter changes no answer.
Containment is never filtered: two overlapping taxlots must stay visible as two.

Timing
------
Measured over 40 random residential taxlots (16 Multnomah, 12 Washington, 12
Clackamas), through one warm session:

  ==========================================  ======  ======  ======  ======
  request                                     median     p90     p95     max
  ==========================================  ======  ======  ======  ======
  "which taxlot is this dot inside?"           0.15 s  0.16 s  0.16 s  0.30 s
  "what is within 80 m?" (number-filtered)     0.18 s  0.20 s  0.21 s  0.40 s
  ==========================================  ======  ======  ======  ======

The densest point found (1001 NW Lovejoy, filtered) answered in 0.69 s. So this
adapter keeps the SHARED clock — a one-second read slice and a four-second budget —
and ``READ_SLICE_S`` / ``LOOKUP_TIMEOUT`` are named only so every request visibly
passes them; a test pins their sum under ``config.UPSTREAM_HOST_BUDGET``. End to
end, a lookup took a median of 0.29 s (p95 0.31 s, slowest 0.77 s).

What the adapter is worth, end to end
-------------------------------------
214 residential taxlots (SFR, MFR or RUR, carrying a year and a site address)
drawn at random from the layer itself — 80 Multnomah, 67 Washington, 67 Clackamas —
typed as "<SITEADDR>, <SITECITY>, OR <SITEZIP>", geocoded through the Census
matcher and ``assessor_address`` exactly as the product does, then looked up:

  ===============================  ===========  ==========  ==========  ======
                                   Multnomah    Washington  Clackamas   all
  ===============================  ===========  ==========  ==========  ======
  sampled                                 80          67          67     214
  geocoded (all routed in-county)         77          64          63     204
  resolved                                67          59          55     181
  **wrong parcel**                     **0**       **0**       **0**   **0**
  year built exact                     65/65       59/59       55/55  179/179
  floor area reported / exact          63/63       57/57       51/51  171/171
  ===============================  ===========  ==========  ==========  ======

Two further Multnomah draws are left out of that table, and why is itself a
finding: they were relative-locator lots ("5655 S/ SE HARNEY DR", "8631 W/ NE
HOLLADAY ST"), typed literally. The matcher drops the locator, and the adapter
returned the house that address names (5655 SE Harney Dr, 1952) — the right
answer for a reader, and a "different parcel" only against the lot that was
drawn. Neither lot carries a building (BLDGSQFT 0; one has year 9999).

The 23 that did not resolve: 13 geocodes more than 80 m from their taxlot
(rural roads, large lots, and four condominiums whose stand-in polygons sit
away from where the matcher puts the street address); 4 two-to-four-unit buildings filed under a house-number range;
3 where the matcher added or dropped a directional ("16484 SIRI LOOP" for SE Siri
Loop) — refused on purpose, since a directional names a different street in a
quadrant city; 1 Washington condominium with no unit to pick; 1 address carried
by two taxlots; and 1 commercial condominium, refused by class.

Privacy, and why the field list is short
----------------------------------------
Metro removes owner names and mailing addresses before publishing. What remains
that the label has no use for — ``SALEPRICE``, ``SALEDATE``, four value columns,
``OWNERTYPE`` and ``PUBLIC_OWN`` — is never requested: eight columns are named,
and the shared helper refuses ``*``. Nothing from this source is written into the
repository.

License
-------
The layer's item page and metadata (``use-constraints``) place it under the "RLIS
Open Database End User License Agreement"
(https://rlisdiscovery.oregonmetro.gov/pages/open-database-license, revised
February 2023). It grants "a limited, worldwide, royalty-free, non-exclusive,
revocable license to: Copy, publish, distribute, and share the Data; Extract,
modify, and adapt the Data; and Combine it with other data, or include it in your
own product or application", on condition of the attribution statement
"Regional Land Information System data are a product of Metro and made publicly
available according to the license agreement found in
https://rlisdiscovery.oregonmetro.gov/pages/open-database-license ." — which
``ATTRIBUTION`` carries verbatim, so it travels with every value. It excludes
"Any personal data in the Data", which this adapter does not request; prohibits
sublicensing and implying Metro's endorsement; and states compatibility with CC BY
4.0 and ODC-By. Nothing restricts commercial use. The posture is the one every
adapter takes regardless — query live, cache in process, bundle nothing.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from housing_label.enrich.assessor import _shared
from housing_label.enrich.assessor._shared import (
    address_key, cache_bucket, deadline_from, num, select_parcel, unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR

log = logging.getLogger(__name__)

#: The three counties RLIS compiles, each in full (see "Coverage" above).
#: County FIPS → the one-letter code RLIS writes in its own ``COUNTY`` column.
COUNTIES = {
    "41005": "C",   # Clackamas
    "41051": "M",   # Multnomah
    "41067": "W",   # Washington
}
COUNTY_FIPS = frozenset(COUNTIES)

NAME = "Oregon Metro Regional Land Information System (RLIS)"
#: The second sentence is the attribution statement the RLIS license requires,
#: verbatim, link included; see "License" in the module docstring.
ATTRIBUTION = ("Clackamas, Multnomah and Washington County assessors via Oregon Metro "
               "RLIS Taxlots (Public), keyless. Regional Land Information System data "
               "are a product of Metro and made publicly available according to the "
               "license agreement found in "
               "https://rlisdiscovery.oregonmetro.gov/pages/open-database-license .")
DATA_VINTAGE = ("Oregon Metro RLIS taxlots, compiled quarterly from the Clackamas, "
                "Multnomah and Washington County assessment rolls")

TAXLOT_URL = ("https://services2.arcgis.com/McQ0OlIABe29rJJy/arcgis/rest/services"
              "/Taxlots_(Public)/FeatureServer/3/query")

#: The shared clock, kept on purpose and named so every request visibly passes it.
#: See "Timing" in the module docstring.
READ_SLICE_S = _shared._READ_SLICE_S
LOOKUP_TIMEOUT = _shared.TIMEOUT

# Only what the label scores and what decides whether a record is somebody's one
# home. Deliberately absent: SALEPRICE and SALEDATE (sale facts), every value
# column (LANDVAL, BLDGVAL, TOTALVAL, ASSESSVAL), OWNERTYPE and PUBLIC_OWN (owner
# classifications), TAXCODE and ALTACCNUM. The layer carries no owner name or
# mailing address at all — Metro strips them before publishing.
_FIELDS = "TLID,PRIMACCNUM,SITEADDR,YEARBUILT,BLDGSQFT,PROP_CODE,LANDUSE,HAS_MANY"

# Year values that are not years. 1800 is Multnomah's placeholder: five records,
# then nothing until 1846, the year after Portland was platted. 9999 (675 Multnomah
# records) is already outside the plausible range.
_PLACEHOLDER_YEARS = frozenset({1800})

# RLIS's own standardized land-use categories that state nobody lives here.
_NOT_A_HOME_LANDUSE = frozenset({"COM", "IND", "VAC", "PUB"})


def url_for(county_fips: str) -> str | None:
    """The layer that answers for this county, or None — one layer for all three."""
    return TAXLOT_URL if county_fips in COUNTY_FIPS else None


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _account(row: dict) -> str | None:
    """The county's tax account on this taxlot, or None for a record of nothing."""
    return _text(row.get("PRIMACCNUM")) or None


def _parcel_id(row: dict) -> str | None:
    """The taxlot id exactly as published ("1S1E04AD  -60062"), ends trimmed."""
    return str(row.get("TLID") or "").strip() or None


def _property_class(row: dict) -> str | None:
    """The Department of Revenue's three-digit property class, or None.

    Clackamas writes a handful of records with the leading zero dropped ("81",
    "3", "25"); those are not read as a statement at all, rather than guessed at.
    """
    code = _text(row.get("PROP_CODE"))
    return code if len(code) == 3 and code.isdigit() else None


def _says_no_home(row: dict) -> bool:
    """Whether the roll explicitly says no dwelling stands on this taxlot."""
    if _text(row.get("LANDUSE")).upper() in _NOT_A_HOME_LANDUSE:
        return True
    pc = _property_class(row)
    if pc is None:
        return False
    use, status = pc[0], pc[2]
    if use in "23":                       # commercial or industrial use
        return True
    if status == "0":                     # vacant
        return True
    # Miscellaneous (utilities, machinery and equipment) — except a manufactured
    # structure, which is somebody's home.
    return use == "0" and status != "9"


def _single_house_number(address: str | None) -> bool:
    head = _text(address).split(" ", 1)[0]
    return head.isdigit()


def _norm_unit(unit: str | None) -> str:
    """Case and punctuation folded ("#C-1" = "c1"); leading zeros kept."""
    return "".join(ch for ch in str(unit or "").upper() if ch.isalnum())


def _area(row: dict, typed_unit: str | None) -> float | None:
    """``BLDGSQFT`` when it is one home's floor area, otherwise None."""
    area = num(row.get("BLDGSQFT"))
    if area is None or area <= 0 or num(row.get("HAS_MANY")):
        return None
    pc = _property_class(row)
    if pc is None or pc[0] != "1" or _says_no_home(row):
        return None
    address = row.get("SITEADDR")
    own_unit = unit_of(address)
    if pc[2] == "1":
        return (area if _text(row.get("LANDUSE")).upper() == "SFR"
                and own_unit is None and _single_house_number(address) else None)
    if pc[2] == "2":
        return (area if own_unit and typed_unit
                and _norm_unit(own_unit) == _norm_unit(typed_unit) else None)
    return None


def _year(row: dict) -> int | None:
    year = num(row.get("YEARBUILT"))
    if not year or not (EARLIEST_PLAUSIBLE_YEAR <= year <= 2100):
        return None
    if int(year) in _PLACEHOLDER_YEARS or num(row.get("HAS_MANY")) or _says_no_home(row):
        return None
    return int(year)


def _parcels(lat: float, lon: float, distance_m: float = 0, *, deadline: float,
             house_number: str | None = None) -> list[dict]:
    """Taxlots that carry a tax account, at (or within ``distance_m`` of) a point."""
    where = None
    if distance_m and house_number and house_number.isdigit():
        where = f"SITEADDR LIKE '{house_number} %'"
    rows = _shared.arcgis_parcels(TAXLOT_URL, lat, lon, _FIELDS, distance_m,
                                  deadline=deadline, read_slice=READ_SLICE_S, where=where)
    return [r for r in rows if _account(r) is not None]


def _for_unit(rows: list[dict], unit: str) -> list[dict]:
    """The candidates that could be the typed unit's home.

    A taxlot naming a DIFFERENT unit never can. And where some taxlot names THIS
    unit, a taxlot naming no unit at all is not the reader's either: at 1025 NW
    Couch St the unit's own account sits beside three unit-less accounts at the
    same street address — the commercial spaces and common elements of the
    building — and leaving them in made the reader's own unit "ambiguous". Where
    no taxlot names the unit (Washington County writes none), the unit-less ones
    are all there is, and the address check decides as usual.
    """
    want = _norm_unit(unit)
    named = [r for r in rows if _norm_unit(unit_of(r.get("SITEADDR"))) == want]
    return named or [r for r in rows if unit_of(r.get("SITEADDR")) is None]


# A hyphen between two letters is a space. RLIS writes the same road both ways —
# "7280 SW BEAVERTON-HILLSDALE HWY" and "10090 SW BEAVERTON HILLSDALE HWY", likewise
# TUALATIN-SHERWOOD and SCHOLLS-SHERWOOD — and the Census matcher returns the
# hyphenated form, which the shared comparison reads as one word. A hyphen beside
# a digit is left alone: "2405-2411" is a house-number range and "#C-1" a unit.
_LETTER_HYPHEN_RE = re.compile(r"(?<=[A-Za-z])-(?=[A-Za-z])")


def _unhyphenated(address: str | None) -> str | None:
    return _LETTER_HYPHEN_RE.sub(" ", address) if address else address


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The taxlot this point belongs to, or None; see ``_shared.select_parcel``."""
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    key = address_key(address)
    number = key[0] if key else None
    unit = unit_of(address)
    fetched: dict[float, list[dict]] = {}

    def fetch(distance_m):
        if distance_m not in fetched:
            fetched[distance_m] = _parcels(lat, lon, distance_m, deadline=deadline,
                                           house_number=number)
        found = fetched[distance_m]
        return _for_unit(found, unit) if unit else found

    chosen = select_parcel(fetch, _unhyphenated(address),
                           lambda r: _unhyphenated(r.get("SITEADDR")))
    if chosen is None or not address:
        return chosen
    if number and number.isdigit():
        companions = _shared.arcgis_parcels(
            TAXLOT_URL, lat, lon, _FIELDS, COMPANION_RADIUS_M, deadline=deadline,
            read_slice=READ_SLICE_S, where=f"SITEADDR LIKE '{number} WI/%'")
        if any(_a_built_companion_of(chosen, r) for r in companions):
            return None
    return chosen


# Multnomah writes a second taxlot that shares a house's address as "7815 WI/ N
# WABASH AVE" — "with" 7815. 5,805 RLIS taxlots carry it (0.9%), most of them
# vacant side lots, which change nothing. But some hold their own building: at
# 7815 N Wabash Ave the "WI/" lot has a 1951 house of 800 sq ft beside the 1927
# house filed under the plain address. Its resident types "7815 N Wabash Ave" too,
# and was shown the 1927 house — measured in the 2026-10-04 benchmark. With two
# buildings answering to one address there is no telling which home was asked
# about, so the lookup declines.
#
# Searched for by address, not within the usual 80 m: the 7815 Wabash pair sit
# 110 m apart along the street, so the companion was outside the neighborhood the
# choice itself looks at. The query is filtered to "WI/" lots with this house
# number, so it returns almost nothing and costs one fast request.
COMPANION_RADIUS_M = 400
_WITH_RE = re.compile(r"\bWI/\s*", re.IGNORECASE)


def _a_built_companion_of(chosen: dict, row: dict) -> bool:
    """Whether ``row`` is a "WI/" taxlot at ``chosen``'s address with a building."""
    site = row.get("SITEADDR") or ""
    if row is chosen or not _WITH_RE.search(site):
        return False
    same = (address_key(_unhyphenated(_WITH_RE.sub("", site)))
            == address_key(_unhyphenated(chosen.get("SITEADDR"))))
    return same and bool(_year(row) or num(row.get("BLDGSQFT")))


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None
    year_built = _year(row)
    sqft = _area(row, unit_of(address))
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=DATA_VINTAGE,
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What the three county rolls, via RLIS, say is standing at this point, or None.

    Fails open on everything; the caller then keeps whatever it had.
    """
    try:
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Portland-metro assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
