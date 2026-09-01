#!/usr/bin/env python3
"""Florida — all 67 counties from one statewide table, in a single request.

The third adapter, and the first that covers a whole state. Cook County is one
county and Washington is one city; Florida is 9.87 million homes, roughly 7% of
the housing in the United States, reached by adding one file.

That is possible because of how Florida collects its records. Every county in the
state has its own property appraiser, and each one keeps its own database — but
state law requires all 67 of them to send their annual assessment roll to the
Florida Department of Revenue in a common format. The Department joins those rolls
to the counties' parcel maps and publishes the result as one statewide layer. So
the per-county fragmentation that makes national coverage hard everywhere else has
already been solved here, by the state, once a year.

One request, not two
--------------------
The two adapters before this one need at least two requests, because their source
splits the *shape* of a parcel from the *facts* about it: you look up which parcel
a point falls in, get an identifier back, then look the identifier up in a second
table. Cook County calls that identifier a PIN; Washington calls it an SSL.

Florida's layer carries the shape and the facts together — the year built and the
floor area sit on the same record as the boundary. So the whole lookup is one
question: *which parcel is this point inside, and what does its record say?* That
makes this the cheapest adapter in the registry as well as the widest.

  ``Florida_Statewide_Cadastral/FeatureServer/0`` — "FDOR Cadastral 2025",
  10,831,924 parcels, keyless, verified live.

Three words this file cannot avoid, in plain terms:

* **cadastral** — the surveyor's word for a map of land ownership boundaries.
* **parcel** — one piece of land as the county records it, usually a single lot
  with a single tax bill.
* **point-in-polygon** — asking a map "which shape is this dot inside?" It is how
  a street address, once turned into a latitude and longitude, finds its parcel.

Condominiums come free here, and that is unusual
------------------------------------------------
Washington needed an entire second lookup chain for condominiums, because the
District files each unit as its own parcel with its own identifier, and a unit is
not somewhere a map coordinate can land: asking which shape a dot is inside cannot
pick unit 305 out of a stack of forty, because all forty share one footprint.

Florida files the *building* as the parcel. A 269-unit tower in Bal Harbour is one
record: one boundary, one year built, one total floor area for the whole tower.
Verified live. So a condominium address resolves through the ordinary path with no
special handling, and the year it reports — the year the tower went up — is the
correct year for every unit inside it.

The floor area is the part that does not survive, and it is handled below.

The one number that has to be refused
-------------------------------------
``TOT_LVG_AR`` is the total heated living area on the *parcel*. On a single house
that is the house. On the Bal Harbour tower it is 895,557 square feet, which is
not the size of anybody's home.

The label's ``sqft`` means one dwelling. So the area is reported only where the
county's own record says the parcel holds exactly one home in exactly one
building — ``NO_RES_UNT == 1`` and ``NO_BULDNG == 1``. Anything else is left
empty and the label falls back to its modelled estimate.

Dividing the total by the unit count was considered and rejected: it would turn a
measurement into an average, and then tag the average ``observed``, which tells a
reader not to doubt it. Measured on 704 Florida parcels that record a floor area,
the strict rule keeps 87%.

Why this service needs its own clock
------------------------------------
Cook County and the District run on the shared budget: four seconds for a whole
lookup, and at most one second of silence from the portal before that silence is
read as a stall. Both numbers were sized against portals that answer a single
parcel almost instantly, which those two do. (Connecticut, added later, sizes its
own for the same reason this one does.)

Florida's does not. It is searching ten million parcels, and it thinks before it
speaks. Measured over 40 requests to real Florida rooftops spread across eight
counties:

  ==================================  ======  ======  ======  ======
  request                             median     p90     p95     max
  ==================================  ======  ======  ======  ======
  "which parcel is this dot inside?"   1.07 s  2.69 s  3.30 s  3.31 s
  "what is within 80 m of this dot?"   1.86 s  3.49 s  5.07 s  6.70 s
  ==================================  ======  ======  ======  ======

The first runs on every lookup. The second runs only when the first found nothing,
which happens when the geocoder puts the address in the roadway instead of on its
lot — common enough to matter, because the Census matcher estimates a great many
addresses by interpolating along the street.

Under the shared one-second slice that cuts off 21 of 40 containment queries and 25
of 40 buffered ones — and a cut-off does not look like a timeout to anyone reading
the label. It looks like a state with no records, which is the failure this project
has already shipped once: the District's condominium path spent a release reporting
the deadline's answer rather than the District's.

So ``READ_SLICE_S`` is 4 seconds, which clears the containment distribution
entirely and all but 3 of 40 buffered queries, and ``LOOKUP_TIMEOUT`` is 7 seconds, which
covers the p90 of both requests together (2.69 + 3.49) with room to spare. Neither
number is what a typical lookup costs: a ceiling is not a cost, and the measured
typical is containment plus buffer, around 2.9 seconds.

Seven rather than eight because of how the two halves of a socket timeout add up.
The connect half keeps the whole remaining budget on purpose — a slow handshake is
the one wait that cannot be broken into slices — so the true worst case for a
single request is the budget spent connecting *plus* one read slice: 7 + 4 = 11 s,
inside the 12 s the host allows any one service on a single score
(``config.UPSTREAM_HOST_BUDGET``). At a budget of 8 that sum is 12 s exactly,
sitting on the limit rather than under it. A test pins the sum against that
constant rather than against a literal. Raising the slice from 1 s to 4 s is what made this worth
counting: at the shared 1 s it was 5 s and nowhere near anything.

What the clock was worth, end to end: 26 real Florida addresses in three counties,
geocoded through the Census matcher exactly as the product does, then looked up.
Under the shared budget 7 of 26 resolved. Under this one, 21 — with no parcel
matched wrongly in either run, and every one of the 21 exact on both the year built
and the floor area. The other 5 are addresses the geocoder placed off their own
lot and whose street address then matched no nearby parcel — the shared
parcel-choosing rule declining to guess, not this clock cutting anything off.

The responses themselves are 1.3 to 6.9 KB — this is entirely the service thinking,
not bytes moving. That also closes the one way a longer slice could overshoot the
budget: the overshoot case needs a body still streaming when the budget runs out,
and a seven-kilobyte body cannot stream for eight seconds.

What this source does not carry
-------------------------------
The state roll has no exterior wall, no storey count, no foundation type and no
condition grade, so those four stay empty and NSI's estimate stands for them. Two
fields are close enough to be worth explaining why they are *not* used:

* ``EFF_YR_BLT`` — the "effective" year built, which counties move forward when a
  property is improved. It is a statement about condition, not about when the
  building went up. ``ACT_YR_BLT``, the actual year, is what the label asks for,
  and the two genuinely differ: a 1925 house in Orlando carries an effective year
  of 2015.
* ``CONST_CLAS`` and ``IMP_QUAL`` — single-digit construction-class and quality
  codes. They look like exactly what the label's ``construction`` and ``condition``
  fields want, and they are left alone anyway: no code table travels with the
  service, and the codes are entered by 67 separate county appraisers. Deciding
  that "3" means masonry statewide would be a guess wearing the ``observed`` tag,
  which is the one thing an adapter must never produce.

Privacy, and why the field list is short
----------------------------------------
This layer has 121 columns, and among them are ``OWN_NAME``, ``OWN_ADDR1``,
``FIDU_NAME`` (the fiduciary — a trustee or executor), sale prices, and every
assessed and taxable value. The Department's own description of the layer asks
readers to report "the inadvertent release of a confidential record exempt from
disclosure pursuant to Chapter 119, Florida Statutes".

None of that is an input to any dimension of the label. Seven columns are
requested by name and the other 114 are never fetched — the shared helper refuses
``*`` for precisely this reason. Nothing from this source is written into the
repository.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from housing_label.enrich.assessor._shared import (
    arcgis_parcels, cache_bucket, deadline_from, num, select_parcel,
)
from housing_label.enrich.assessor.base import AssessorRecord

log = logging.getLogger(__name__)

# All 67 Florida counties. Florida's county FIPS codes are the odd numbers from
# 12001 to 12133 — with two wrinkles worth spelling out, because both are the kind
# of thing a hand-typed list gets wrong:
#
#   * 12025 is retired. It was Dade County, renamed Miami-Dade in 1997.
#   * 12086 replaced it, and is the only even code in the state.
#
# Written as a rule rather than as 67 literals so it cannot drift; a test checks
# the result against the county table this repository already ships.
COUNTY_FIPS = frozenset(
    f"12{n:03d}" for n in range(1, 134, 2) if n != 25
) | {"12086"}

NAME = "Florida Department of Revenue"
ATTRIBUTION = ("Florida county property appraisers via FL DOR Property Tax "
               "Oversight (statewide cadastral, keyless)")
DATA_VINTAGE = "Florida DOR statewide parcel roll (NAL), joined to county parcel maps"

PARCEL_URL = ("https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services"
              "/Florida_Statewide_Cadastral/FeatureServer/0/query")

#: How long this service may go quiet before the silence is treated as a stall,
#: and the budget for a whole Florida lookup. Both are Florida's own, and both are
#: measured rather than chosen — see "Why this service needs its own clock" in the
#: module docstring for the distribution they come from.
#:
#: A lookup makes at most two requests: the containment query every lookup makes,
#: and the buffered query an off-parcel geocode falls through to.
#:
#: Named LOOKUP_TIMEOUT rather than TIMEOUT so it cannot be mistaken for, or
#: collide with, the shared four-second budget of the same name — the District
#: names its own deviation CONDO_TIMEOUT for the same reason.
READ_SLICE_S = 4.0
LOOKUP_TIMEOUT = 7.0

# Only what the label scores, plus the two counts that decide whether the floor
# area describes one home. See "Privacy" in the module docstring for what the other
# 114 columns hold and why none of them is fetched.
_FIELDS = "PARCEL_ID,PHY_ADDR1,ASMNT_YR,ACT_YR_BLT,TOT_LVG_AR,NO_RES_UNT,NO_BULDNG"


def _parcel_id(attrs: dict) -> str | None:
    """The county's identifier for this parcel, or None if it has none."""
    pid = str(attrs.get("PARCEL_ID") or "").strip()
    return pid or None


def _parcels(lat: float, lon: float, distance_m: float = 0,
             *, deadline: float) -> list[dict]:
    """Real parcel records at (or within ``distance_m`` of) a point.

    The statewide layer contains placeholder polygons — rights-of-way, water,
    unmapped remainders — whose every field is blank or zero, including the parcel
    identifier. They are records of nothing and can never contribute a fact, and
    one of them was the only shape returned at a real Fort Lauderdale coordinate.

    They are dropped here, before the parcel is chosen, rather than after. If a
    blank polygon overlaps a real one, the shared chooser sees two candidates,
    correctly calls that ambiguous, and gives up — losing a real answer to a row
    that was never a candidate. Removing non-answers from the candidate list can
    only turn "ambiguous" into "one real parcel"; it can never let a *wrong* parcel
    through, because the address check that follows is untouched.
    """
    rows = arcgis_parcels(PARCEL_URL, lat, lon, _FIELDS, distance_m,
                          deadline=deadline, read_slice=READ_SLICE_S)
    return [r for r in rows if _parcel_id(r) is not None]


def _parcel_at(lat: float, lon: float, address: str | None = None,
               *, deadline: float | None = None) -> dict | None:
    """The record of the parcel this point belongs to, or None.

    Deciding *which* parcel an address means is the dangerous part of any adapter
    — name the wrong one and the label reports a neighbour's house as observed
    fact — so the policy lives in ``_shared.select_parcel`` and is shared by every
    jurisdiction. See that function for why it refuses to take the nearest parcel.

    No locality trim is needed here. Washington's parcel layer runs the whole
    mailing address into one field ("3401 NEWARK ST NW WASHINGTON DC 20016"), so
    the comparison has to be told where the street stops. Florida keeps the city
    in its own ``PHY_CITY`` column, leaving ``PHY_ADDR1`` as just the street
    address — "740 W SOUTH ST" — which is already the form the comparison wants.
    """
    deadline = deadline_from(deadline, LOOKUP_TIMEOUT)
    return select_parcel(
        lambda d: _parcels(lat, lon, d, deadline=deadline),
        address, lambda a: a.get("PHY_ADDR1"))


def _vintage(row: dict) -> str:
    """What this record reflects, dated from the row itself where possible.

    The Department collects the county rolls each April and republishes the joined
    layer each August, so the assessment year advances underneath an unchanged URL.
    Reading the year off the record keeps a reader able to date an observed value
    instead of trusting it, and means a hard-coded year cannot quietly go stale —
    which would present old data at the same confidence as fresh data.
    """
    year = num(row.get("ASMNT_YR"))
    if year and 1900 <= year <= 2100:
        return f"{DATA_VINTAGE}, {int(year)} assessment roll"
    return DATA_VINTAGE


def _says_a_home_is_here(row: dict) -> bool:
    """Whether the roll records at least one dwelling on this parcel.

    ``NO_RES_UNT`` is the county's count of residential units. A recorded **0** is
    a statement — a shop, a warehouse, a county garage — and the label is scoring
    somebody's home, so a year built taken from that parcel would describe a
    building nobody lives in while carrying the ``observed`` tag. The floor area
    already refuses those; the year has to refuse them for the same reason.

    A *missing* count is not the same thing, and is allowed through. An explicit
    zero is the county saying "no dwelling here"; an absent field is the county
    saying nothing, and refusing on silence would cost a whole county's coverage
    the day one appraiser stopped filling the column. Measured across eight
    counties and 1,321 single-family parcels carrying a year built, the count was
    never zero and never missing — so this turns away commercial parcels without
    costing homes.
    """
    homes = num(row.get("NO_RES_UNT"))
    return homes is None or homes >= 1


def _area_of_one_home(row: dict) -> float | None:
    """``TOT_LVG_AR`` when it describes a single dwelling, otherwise None.

    See "The one number that has to be refused" in the module docstring. Both
    counts must say one: a parcel with two homes in one building and a parcel with
    one home plus a second building both report a total that is larger than the
    home being scored.
    """
    area = num(row.get("TOT_LVG_AR"))
    if area is None or area <= 0:
        return None
    homes = num(row.get("NO_RES_UNT"))
    buildings = num(row.get("NO_BULDNG"))
    if homes != 1 or buildings != 1:
        return None
    return area


@lru_cache(maxsize=4096)
def _lookup_cached(lat: float, lon: float, address: str | None,
                   _bucket: int = 0) -> AssessorRecord | None:
    row = _parcel_at(lat, lon, address)
    if not row:
        return None

    year = num(row.get("ACT_YR_BLT"))
    # A year of 0 is the county's "not recorded", not the year zero; without this
    # it would reach the scorer as a fact and age the building by two thousand
    # years. The dwelling check is the same rule the floor area applies — see
    # _says_a_home_is_here.
    year_is_a_homes = bool(year and 1800 <= year <= 2100
                           and _says_a_home_is_here(row))
    year_built = int(year) if year_is_a_homes else None
    sqft = _area_of_one_home(row)
    # A parcel that matched but recorded neither fact contributed nothing. Saying
    # so here costs one comparison and keeps a fact-free record out of the cache;
    # the registry drops it either way, so behaviour is unchanged.
    if year_built is None and sqft is None:
        return None
    return AssessorRecord(
        source=ATTRIBUTION,
        data_vintage=_vintage(row),
        parcel_id=_parcel_id(row),
        year_built=year_built,
        sqft=sqft,
        # The state roll carries no wall material, storey count, foundation or
        # condition. Left empty on purpose, which lets the label fall back to its
        # modelled estimate for those four rather than to a guess dressed up as an
        # observation.
    )


def lookup(lat: float, lon: float, address: str | None = None) -> AssessorRecord | None:
    """What Florida's county rolls say is standing at this point, or None.

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
        log.debug("Florida assessor lookup failed at %s,%s: %s", lat, lon, exc)
        return None
