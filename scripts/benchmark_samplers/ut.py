"""Utah: homes drawn from UGRC's per-county LIR parcel layers, one draw per parcel.

The layers hold one row per BUILDING (see ``ut``'s docstring): a house with two
sheds is three rows under one parcel id. Offsets into the rows would draw that
parcel three times as often as a house alone, so each drawn row is kept with
probability 1 / (the parcel's matching rows) — rejection sampling, which leaves
every parcel equally likely. A rejection is part of the method, not a failed
draw, and is not counted as one.

A home is a parcel with a recorded year built (``BUILT_YR`` > 0; 0 is "not
recorded") filed under a residential class. The class column is the county's
own vocabulary, so the clause is per county:

* "Residential" everywhere it is used, and "Commercial - Apartment & Condo"
  (housing, which the adapter reads);
* Carbon writes "Single Family", "Multi-Family", "Apartments", "Subsidized
  Housing" and "PERSONAL PROPERTY MOBILE HOME" instead;
* Utah County files its whole multi-unit stock (townhouses, condominium
  buildings) as "Unknown", and Davis 47,723 built parcels — ordinary houses,
  sampled — with no class at all; both are included there;
* Emery and San Juan write "Unknown" on every row, so that is their class.

Agricultural and greenbelt parcels (a farmhouse can stand on one) are left out:
in these layers they are mostly barns and sheds, and drawing them would spend
the sample on outbuildings.

The address is the roll's ``PARCEL_ADD`` (street only) with the site's own
``PARCEL_CITY`` where filled — about one built parcel in seven has none — and
the ZCTA at the parcel; the layers carry no owner or mailing columns.
"""

from __future__ import annotations

import logging
import random

from housing_label.enrich.assessor import ut
from scripts.benchmark_samplers import allocate, arcgis_count, get, interior_point, typed, zip_at

log = logging.getLogger("build_benchmark")

ADAPTER = "ut"
#: UGRC's LIR layers are each county's year-end tax roll; ``CURRENT_ASOF`` reads
#: October-November 2025 across the layers (measured 2026-10-04).
ASSESSMENT_YEAR = "2025"

_RESIDENTIAL = "PROP_CLASS IN ('Residential', 'Commercial - Apartment & Condo')"
_CLASS = {
    "49007": ("PROP_CLASS IN ('Single Family', 'Multi-Family', 'Apartments', "
              "'Subsidized Housing', 'PERSONAL PROPERTY MOBILE HOME')"),
    "49011": f"({_RESIDENTIAL} OR PROP_CLASS IS NULL)",
    "49015": "PROP_CLASS = 'Unknown'",
    "49037": "PROP_CLASS = 'Unknown'",
    "49049": "PROP_CLASS IN ('Residential', 'Unknown')",
}
_FIPS = {fips: (ut.PARCEL_URL.format(service=ut.COUNTY_SERVICES[fips]),
                f"BUILT_YR > 0 AND {_CLASS.get(fips, _RESIDENTIAL)}")
         for fips in sorted(ut.COUNTY_FIPS)}

_FIELDS = "OBJECTID,PARCEL_ID,PARCEL_ADD,PARCEL_CITY"
#: Offsets to try before giving up on a county: rejection keeps a row with
#: probability 1/k. The layers' mean k is well under 2, but a small rural county
#: asked for one home can meet several barns-and-sheds parcels in a row (the first
#: build fell one home short that way), hence the fixed allowance on top.
_MAX_TRIES_PER_HOME = 8
_EXTRA_TRIES = 40


def _one_per_parcel(url: str, where: str, n: int, seed: int) -> tuple[list[dict], int]:
    """``n`` parcels drawn uniformly at random from those with rows matching
    ``where``. Returns (features, attempted)."""
    total = arcgis_count(url, where)
    if not total:
        log.warning("  %s: no rows match %r", url, where)
        return [], 0
    rng = random.Random(seed)
    offsets = rng.sample(range(total), min(total, n * _MAX_TRIES_PER_HOME + _EXTRA_TRIES))
    feats, attempted, seen = [], 0, set()
    for off in offsets:
        if attempted >= n:
            break
        body = get(url, {"where": where, "outFields": _FIELDS, "orderByFields": "OBJECTID",
                         "resultOffset": off, "resultRecordCount": 1,
                         "returnGeometry": "true", "outSR": 4326, "f": "json"})
        fs = (body or {}).get("features") or []
        if not fs:
            attempted += 1          # a failed read is a failed draw
            continue
        pid = str(fs[0]["attributes"].get("PARCEL_ID") or "").strip()
        k = 1
        if pid:
            if pid in seen:
                continue
            quoted = pid.replace("'", "''")
            k = arcgis_count(url, f"{where} AND PARCEL_ID = '{quoted}'") or 1
        if rng.random() >= 1 / k:
            continue                # rejected by design: a multi-building parcel
        seen.add(pid)
        attempted += 1
        feats.append(fs[0])
    if attempted < n:
        log.warning("  %s: %d of %d homes drawn before the offsets ran out", url,
                    attempted, n)
    return feats, attempted


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        url, where = _FIPS[fips]
        feats, tried = _one_per_parcel(url, where, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("PARCEL_ADD"), a.get("PARCEL_CITY"), "UT",
                                         zip_at(*pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
