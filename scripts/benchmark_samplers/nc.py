"""North Carolina: homes drawn from the NC OneMap statewide parcel layer.

The 46 counties the adapter serves (those that fill ``structyear``), allocated by
housing units. A drawn parcel counts as a home exactly when the adapter would
take its year as a home's: a plausible ``structyear`` (not Wilkes's 1600
placeholder) and a use description that does not say "vacant", "common" or
non-residential — the adapter's own ``_year_built`` decides, so the sampler and
the adapter cannot disagree about what a home is.

The address is the parcel's site address as the adapter reads it (``siteadd``,
or its components, with any city/state/ZIP tail a county ran into it trimmed),
the site city ``scity`` where the county filled it (less the "City" and
"County" markers some counties add), and the site ZIP ``szip``
where filled, else the ZCTA at the parcel. ``mailadd``, ``mcity`` and ``mzip``
are the owner's mailing address and are never requested.

Drawn by object id, like Florida: offset queries filtered on ``structyear`` take
about six seconds each on this 5.9-million-row layer, while every county
occupies one dense ``objectid`` run, so a uniformly random id in the county's
run, kept only if it is a home there, draws every home with equal chance at a
fraction of the cost. See ``fl.oid_random``.
"""

from __future__ import annotations

from housing_label.enrich.assessor import nc
from scripts.benchmark_samplers import allocate, interior_point, typed, zip_at
from scripts.benchmark_samplers.fl import oid_random, oid_ranges

ADAPTER = "nc"
# Per-county snapshots (``transfdate``) running from mid-2025 to 2026, so no one
# roll year describes the layer.
ASSESSMENT_YEAR = "current"

_FIPS = {f: f for f in sorted(nc.COUNTY_FIPS)}
_FIELDS = ("objectid,parno,siteadd,saddno,saddpref,saddstr,saddsttyp,saddstsuf,"
           "scity,szip,structyear,parusedesc,stcntyfips")


def _is_home(a: dict, fips: str) -> bool:
    return str(a.get("stcntyfips") or "") == fips and nc._year_built(a) is not None


# Towns whose name really ends in "City". Elsewhere a trailing "City" is how
# some counties mark a municipality ("Burlington City", "Mount Holly City"), and
# "<Name> County" is how they mark unincorporated land; neither is typed.
_REAL_CITIES = frozenset({"BRYSON CITY", "ELIZABETH CITY", "MOREHEAD CITY", "SILER CITY"})


def _city(raw) -> str | None:
    city = " ".join(str(raw or "").split())
    if not city or city.upper().endswith(" COUNTY"):
        return None
    if city.upper().endswith(" CITY") and city.upper() not in _REAL_CITIES:
        return city[:-5]
    return city


def _zip(raw) -> str | None:
    z = str(raw or "").strip()[:5]
    return z if len(z) == 5 and z.isdigit() else None


def draw(rows: int, seed: int):
    ranges = oid_ranges(nc.PARCEL_URL, "stcntyfips", "objectid")
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        if fips not in ranges:
            attempted += n
            continue
        lo, hi = ranges[fips]
        feats, tried = oid_random(nc.PARCEL_URL, "objectid", lo, hi,
                                  lambda a, f=fips: _is_home(a, f), _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            street, city = nc._address_of(a) or "", _city(a.get("scity"))
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street, city, "NC",
                                         _zip(a.get("szip")) or zip_at(*pt)),
                        "source_id": a.get("objectid")})
    return out, attempted
