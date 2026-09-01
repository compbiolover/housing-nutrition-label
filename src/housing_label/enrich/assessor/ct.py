#!/usr/bin/env python3
"""Connecticut — all 169 municipalities from one statewide layer, in a single request.

The fourth adapter, and the second that covers a whole state. It exists for the
same reason Florida does: Connecticut has already solved, at the state level, the
per-town fragmentation that makes this work slow everywhere else.

Assessment in Connecticut is municipal — 169 towns and cities, each with its own
assessor and its own CAMA vendor, and no counties in between, because Connecticut
abolished county government in 1960. What the state does have is a statute
(C.G.S. §7-100l, with §4d-90–92) requiring every municipality to file its parcel
map *and* its CAMA extract, which the Councils of Governments collect and the CT
GIS Office joins and republishes as one layer. So a single keyless endpoint
answers for the whole state.

  ``Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0`` — 1,285,005 parcels,
  1,029,326 of them residential with a year built. Keyless, verified live.

One request, like Florida
-------------------------
Cook County and the District split the *shape* of a parcel from the *facts* about
it, so those adapters look the parcel up, get an identifier, and look the
identifier up again. Connecticut's layer carries the geometry and the CAMA record
on the same feature, so the whole lookup is one question: *which parcel is this
point inside, and what does its record say?*

What this source carries, and what it does not
----------------------------------------------
Two fields reach the label: ``AYB`` (the actual year built) and ``Living_Area``.
Neither an exterior wall nor a foundation type nor a storey count is in the
statewide schema at all, so those stay empty and NSI's estimate stands for them.

``Condition`` is in the schema, and is deliberately not read. It looks like
exactly what the label's ``condition`` field wants and it cannot be used: the
column is whatever each town's CAMA vendor writes, and across the state that is
more than forty distinct values on at least four incompatible scales — ``A``
(340,460 rows), ``G`` (215,340), ``7`` (131,088), ``5`` (80,524), ``AV``,
``VG``, ``A+``, ``4.0``, ``33``, ``RB``. No code table travels with the service.
Deciding that ``A`` means "average" in one town and that ``7`` means the same in
another would be a guess wearing the ``observed`` tag, which is the one thing an
adapter must never produce. Same reasoning, and the same verdict, as Florida's
``IMP_QUAL``.

``EYB`` is the effective year built, which towns move forward when a property is
improved. It describes condition, not when the building went up. ``AYB`` is what
the label asks for, and the two genuinely differ across most of this stock. It is
not requested at all, so a later edit cannot read it by mistake.

Two address columns, and why both are read
------------------------------------------
The layer carries the street address twice, because it is a join of two filings:
``Location`` comes from the town's parcel map and ``Location_CAMA``
(``Location_1``) from its CAMA extract. Neither alone is enough:

* ``Location`` is null for 231,524 of the 1,029,326 residential parcels — whole
  towns file none of it. Manchester, Enfield, Hartford, Rocky Hill, Wethersfield,
  Woodstock, Killingly and Stamford are all blank in it, and New Haven writes the
  bare string ``"93"``.
* ``Location_CAMA`` is present on 1,029,217 of them — all but 109 — but Greenwich
  writes it inverted, street first and the number zero-padded last:
  ``"OLD MILL ROAD 0200"``. That is not an address any comparison can anchor on,
  and Greenwich's ``Location`` has the ordinary form.

So the adapter takes whichever column *parses* as an address, preferring the
near-universal one. That is one rule rather than a per-town table, and it is
checked with the same ``address_key`` the comparison itself uses, so a column that
would not have matched anything is never offered as the parcel's address.

Condominiums, and the floor area that has to be refused
-------------------------------------------------------
Florida files a condominium *building* as one parcel. Connecticut files each
*unit* as its own parcel, with the unit written into the address —
``"25 ELLSWORTH ST #01"`` — and ``Occupancy`` of 1, because one unit is one home.

That makes a condo stack many overlapping records at one coordinate, which
``_shared.select_parcel`` already refuses as ambiguous. But the roll is worse than
ambiguous here, and this is the part worth spelling out: on a condominium record
the two address columns can disagree *with each other* about which home the row
describes. Parcel ``116-2`` in Bridgeport carries ``Location`` of
``"350 GROVERS AV #01A"`` and ``Location_CAMA`` of ``"350 GROVERS AV #11C"``;
parcel ``106-35K`` carries ``"120 BEACHVIEW AV #244"`` against
``"110 BEACHVIEW AV #202"`` — not merely a different unit, a different building.

So where the roll's own address carries a unit designator, the floor area is not
reported. ``Occupancy == 1`` is true of every condominium record in the state and
does not catch them; this does. The year built still comes through, because the
year the building went up is the same for every unit inside it — the same split
Florida makes for the opposite reason.

26,101 of the 1,029,326 residential records carry a unit designator.

Which county code routes here
-----------------------------
Connecticut is the one state where this question has a wrong answer that looks
right. The Census Bureau retired Connecticut's eight legacy counties as
county-equivalents and adopted the state's nine **Planning Regions** in their
place, and the live geocoder returns the new codes: an address in West Hartford
resolves to ``09110`` (Capitol Planning Region), not to ``09003`` (Hartford
County). An adapter registered on the legacy eight would therefore never be
reached — for the whole state, silently, in exactly the way a missing registry
entry fails.

Both sets are registered. Not as a hedge: this repository's own bundled county
tables are split down the middle between them — ``health_county.csv``,
``socio_county.csv`` and seven others are keyed on planning regions, while
``climate_zones.csv``, ``water_county.csv`` and seven others are still keyed on
the legacy eight — so both code sets are live in this codebase today, and either
one names exactly Connecticut. No other adapter claims a ``09`` code, so covering
both cannot collide with one.

Why this service needs its own clock
------------------------------------
Measured over 86 requests to real Connecticut rooftops drawn at random from the
state roll, spread across all nine planning regions:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which parcel is this dot inside?"   0.38 s  0.53 s  0.56 s  1.65 s
  "what is within 80 m of this dot?"   0.41 s  2.74 s  2.86 s  3.40 s
  ==================================  ======  ======  ======  ======

The containment query is quick and the buffered one is not, which is the shape
Florida found too: the buffer is where the service actually searches. Under the
shared one-second read slice — how long an upstream may go quiet before the
silence is read as a stall — 6 of the 39 buffered queries are cut off, and a
cut-off does not look like a timeout to anyone reading the label. It looks like a
town with no records.

So ``READ_SLICE_S`` is 3.5 seconds, which clears every one of the 86 measured
requests, and ``LOOKUP_TIMEOUT`` is 5 seconds, which covers the p90 of both
requests together (0.53 + 2.74) with room to spare and exceeds the shared
four-second budget that the worst observed pair (1.65 + 3.40 = 5.05 s) does not
fit inside. Neither is what a typical lookup costs: a ceiling is not a cost, and
the measured typical is containment plus buffer, around 0.8 seconds.

The two halves of a socket timeout add up, so the number that has to fit the
host's allowance is the budget spent connecting plus one read slice:
5 + 3.5 = 8.5 s, inside the 12 s the host allows any one service on a single
score (``config.UPSTREAM_HOST_BUDGET``). A test pins that sum against the
constant rather than against a literal.

What the adapter is worth, end to end
-------------------------------------
103 Connecticut homes drawn at random from the state roll, geocoded through the
Census matcher exactly as the product does, then looked up: 64 resolved and **0
matched to the wrong parcel**. The 39 that did not resolve are addresses the
geocoder placed off their own lot whose street address then matched no nearby
parcel, plus a handful where two parcels contain the point — the shared
parcel-choosing rule declining to guess, which is the behaviour that keeps a
neighbour's house from being reported as observed fact.

Privacy, and why the field list is short
----------------------------------------
This layer has 55 columns, among them ``Owner``, ``Co_Owner``,
``Mailing_Address``, ``Mailing_City``, ``Sale_Price``, ``Sale_Date`` and every
assessed and appraised value. None of it is an input to any dimension of the
label. Seven columns are requested by name and the other 48 are never fetched —
the shared helper refuses ``*`` for precisely this reason. Nothing from this
source is written into the repository.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from housing_label.enrich.assessor._shared import (
    address_key, arcgis_parcels, cache_bucket, deadline_from, num, select_parcel,
    unit_of,
)
from housing_label.enrich.assessor.base import AssessorRecord

log = logging.getLogger(__name__)

# Connecticut, under both of the code sets that name it. See "Which county code
# routes here" in the module docstring for why both are registered rather than
# just the one the geocoder happens to return today.
_PLANNING_REGIONS = frozenset({
    "09110",   # Capitol
    "09120",   # Greater Bridgeport
    "09130",   # Lower Connecticut River Valley
    "09140",   # Naugatuck Valley
    "09150",   # Northeastern Connecticut
    "09160",   # Northwest Hills
    "09170",   # South Central Connecticut
    "09180",   # Southeastern Connecticut
    "09190",   # Western Connecticut
})
_LEGACY_COUNTIES = frozenset({
    "09001",   # Fairfield
    "09003",   # Hartford
    "09005",   # Litchfield
    "09007",   # Middlesex
    "09009",   # New Haven
    "09011",   # New London
    "09013",   # Tolland
    "09015",   # Windham
})
COUNTY_FIPS = _PLANNING_REGIONS | _LEGACY_COUNTIES

NAME = "Connecticut GIS Office"
ATTRIBUTION = ("Connecticut municipal assessors via the CT GIS Office "
               "(statewide CAMA and parcel layer, keyless)")
DATA_VINTAGE = ("Connecticut statewide CAMA and parcel layer, filed by all 169 "
                "municipalities under C.G.S. §7-100l")

PARCEL_URL = ("https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services"
              "/Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0/query")

#: How long this service may go quiet before the silence is treated as a stall,
#: and the budget for a whole Connecticut lookup. Both are measured rather than
#: chosen — see "Why this service needs its own clock" in the module docstring.
#:
#: Named LOOKUP_TIMEOUT rather than TIMEOUT so it cannot be mistaken for, or
#: collide with, the shared four-second budget of the same name — Florida names
#: its own deviation the same way, and the District names its CONDO_TIMEOUT.
READ_SLICE_S = 3.5
LOOKUP_TIMEOUT = 5.0

# Only what the label scores, plus the dwelling count that decides whether the
# floor area describes one home and the year the roll was collected. See "Privacy"
# in the module docstring for what the other 48 columns hold and why none of them
# is fetched — and note that EYB, the effective year built, is not among these on
# purpose.
_FIELDS = "Parcel_ID,Location,Location_1,AYB,Living_Area,Occupancy,Collection_year"

# The two columns the street address can arrive in, in the order they are tried.
# Location_CAMA first because it is present on all but 109 of the state's
# residential parcels where the parcel-map column is blank for whole towns.
_ADDRESS_COLUMNS = ("Location_1", "Location")


def _parcel_id(attrs: dict) -> str | None:
    """The town's identifier for this parcel, or None if it filed none.

    Null on roughly a fifth of the state's residential parcels. That is not a
    reason to drop the record: the parcel id is what lets a reader trace a value
    back to the town's own roll, but the year built and the floor area are facts
    with or without it, and ``AssessorRecord.parcel_id`` is optional for exactly
    this case.
    """
    pid = str(attrs.get("Parcel_ID") or "").strip()
    return pid or None


def _address_of(attrs: dict) -> str | None:
    """The parcel's street address, from whichever column carries a usable one.

    Checked with ``address_key`` — the same parse the comparison itself runs — so
    a column holding something that could never match is skipped rather than
    offered. That is what rescues Greenwich, whose Location_CAMA is written
    inverted ("OLD MILL ROAD 0200") and does not parse, and New Haven, whose
    parcel-map column holds the bare string "93".
    """
    for column in _ADDRESS_COLUMNS:
        raw = (attrs.get(column) or "").strip()
        if address_key(raw):
            return raw
    return None


def _is_a_unit_record(attrs: dict) -> bool:
    """Whether this row describes one condominium unit rather than a building.

    Both columns are consulted, not just the one ``_address_of`` chose, because
    the disagreement between them is the whole problem: a row can name unit 01A in
    one and unit 11C in the other, and either spelling is enough to know that the
    row's floor area belongs to *a* unit rather than to the home being scored.
    """
    return any(unit_of(attrs.get(column)) for column in _ADDRESS_COLUMNS)


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Parcel records at (or within ``distance_m`` of) a point."""
    return arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline, read_slice=READ_SLICE_S)


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the parcel this point belongs to, or None.

    Deciding *which* parcel an address means is the dangerous part of any adapter
    — name the wrong one and the label reports a neighbour's house as observed
    fact — so the policy lives in ``_shared.select_parcel`` and is shared by every
    jurisdiction. See that function for why it refuses to take the nearest parcel.

    No locality trim is needed. Washington's parcel layer runs the whole mailing
    address into one field, so the comparison has to be told where the street
    stops; Connecticut keeps the town in its own ``Property_City`` column, leaving
    both address columns as just the street address.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline), address, _address_of)


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row itself where possible.

    The GIS Office reruns the collection annually and republishes under an
    unchanged URL, so a hard-coded year would go stale silently — presenting old
    data at the same confidence as fresh data. 1,217,852 parcels carry 2025 and
    57,231 still carry 2024, so the year is genuinely per-record rather than a
    property of the layer.
    """
    year = str(row.get("Collection_year") or "").strip()
    return f"{DATA_VINTAGE}, {year} collection" if year.isdigit() and len(year) == 4 \
        else DATA_VINTAGE


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the roll records at least one dwelling on this parcel.

    ``Occupancy`` is the town's count of dwelling units. A recorded **0** is a
    statement — a shop, a warehouse, a town garage — and the label is scoring
    somebody's home, so a year built taken from that parcel would describe a
    building nobody lives in while carrying the ``observed`` tag.

    A *missing* count is not the same thing and is allowed through: an explicit
    zero is the town saying "no dwelling here", an absent field is the town saying
    nothing, and refusing on silence would cost whole towns their coverage. The
    column is null on 180,410 of the state's parcels and zero on 60,363, so the
    two cases are separately populated and the distinction is doing real work.
    """
    homes = num(row.get("Occupancy"))
    return homes is None or homes >= 1


def _area_of_one_home(row: dict) -> float | None:
    """``Living_Area`` when it describes the home being scored, otherwise None.

    Two refusals, and they catch different rows:

    * More than one dwelling on the parcel, so the area covers all of them. A
      duplex reports the pair.
    * A condominium unit record, which reports ``Occupancy`` of 1 and passes the
      first test — but whose address the roll itself spells two different ways,
      sometimes naming two different buildings. See the module docstring.

    The year built survives both, because the building went up when it went up.
    """
    area = num(row.get("Living_Area"))
    if area is None or area <= 0:
        return None
    if num(row.get("Occupancy")) != 1 or _is_a_unit_record(row):
        return None
    return area


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None

    year = num(row.get("AYB"))
    # A year of 0 is the town's "not recorded", not the year zero — 86,360 parcels
    # carry it — and without this it would reach the scorer as a fact and age the
    # building by two thousand years. The dwelling check is the same rule the floor
    # area applies; see _says_a_home_is_here.
    year_built = int(year) if (year and 1800 <= year <= 2100
                               and _says_a_home_is_here(row)) else None
    sqft = _area_of_one_home(row)
    # A parcel that matched but recorded neither fact contributed nothing. Saying
    # so here keeps a fact-free record out of the cache; the registry drops it
    # either way, so behaviour is unchanged.
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
        # The statewide schema carries no wall material, storey count or
        # foundation, and its condition column is not readable across 169
        # vendors — see the module docstring. Left empty on purpose, which lets
        # the label fall back to its modelled estimate for those rather than to a
        # guess dressed up as an observation.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Connecticut's municipal rolls say is standing at this point, or None.

    ``address`` is the geocoder's matched address. It is used only to confirm the
    parcel, and the lookup still works without one wherever the coordinate lands
    inside a boundary.

    Fails open on everything — a timeout, a 500, a renamed column, a parcel the
    state has no record for. The caller then keeps whatever it had, which is the
    behaviour that existed before this adapter.
    """
    try:
        # Round before the cache so two clicks on the same rooftop share an entry.
        # 5 dp is ~1 m — finer than a parcel, coarse enough to be a useful key.
        return _lookup_cached(round(float(lat), 5), round(float(lon), 5), address,
                              cache_bucket())
    except Exception as exc:  # noqa: BLE001
        log.debug("Connecticut assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
