"""Florida: homes drawn from the FDOR statewide cadastral layer.

Residential parcels (DOR use codes 001-008: single-family, mobile home,
multifamily, condominium, cooperative, retirement and miscellaneous residential)
whose roll records at least one residential unit and a plausible actual year
built, allocated across the 67 counties by housing units. The address is the
parcel's physical location (``PHY_ADDR1``, ``PHY_CITY``, ``PHY_ZIPCD``); the
layer's OWN_* and FIDU_* columns are the owner's and fiduciary's mailing
addresses and are never requested. ``PHY_CITY`` is "Unincorporated County" (or
similar) outside a city, and is then left out — the ZIP places the address.

Why not ``arcgis_random``
-------------------------
The layer holds 10.8 million parcels, and the service times out on any count or
offset query filtered by an unindexed column (``DOR_UC = '001'`` alone never
answers). Only ``CO_NO`` and ``OBJECTID`` are cheap. Each county occupies one
contiguous ``OBJECTID`` run (the gaps are the state's ``CO_NO = 0``
placeholders), so a home is drawn by rejection: a uniformly random object id
inside the county's run, kept only if it is a home in that county, else another.
Every home in the county is equally likely, exactly as a filtered offset would
make it. See ``oid_random``.
"""

from __future__ import annotations

import json
import random

from housing_label.enrich.assessor import fl
from housing_label.enrich.durability import EARLIEST_PLAUSIBLE_YEAR
from scripts.benchmark_samplers import allocate, get, interior_point, typed, zip_at

ADAPTER = "fl"
ASSESSMENT_YEAR = "2026"     # ASMNT_YR on the layer's rows (FDOR's current roll)

# DOR county numbers run 11-77 in the alphabetical order the FIPS codes also
# follow, Dade included (it kept its alphabetical slot, FIPS 12025 -> 12086).
_FIPS = {(f"12{n:03d}" if n != 25 else "12086"): 11 + (n - 1) // 2
         for n in range(1, 134, 2)}
_HOME_USES = {f"00{d}" for d in range(1, 9)}
_FIELDS = "OBJECTID,CO_NO,DOR_UC,PHY_ADDR1,PHY_CITY,PHY_ZIPCD,NO_RES_UNT,ACT_YR_BLT"


def oid_ranges(url: str, group_field: str, oid_field: str) -> dict:
    """{group value: (min oid, max oid)} from one statistics query, or {}."""
    stats = [{"statisticType": t, "onStatisticField": oid_field, "outStatisticFieldName": t}
             for t in ("min", "max")]
    body = get(url, {"where": "1=1", "groupByFieldsForStatistics": group_field,
                     "outStatistics": json.dumps(stats), "f": "json"})
    out = {}
    for f in (body or {}).get("features") or []:
        a = f.get("attributes") or {}
        if a.get("min") is not None and a.get("max") is not None:
            out[a.get(group_field)] = (int(a["min"]), int(a["max"]))
    return out


def oid_random(url: str, oid_field: str, lo: int, hi: int, accept, out_fields: str,
               n: int, seed: int) -> tuple[list[dict], int]:
    """``n`` features drawn uniformly at random from those ``accept`` keeps.

    Rejection sampling over a contiguous object-id run: an id drawn uniformly in
    [lo, hi], one request each, kept when a row exists and ``accept`` passes its
    attributes. A request that fails is one failed draw, counted against ``n``
    (conservatively: it might have been a row that would have been rejected).
    Returns (features, attempted), attempted being ``n``.
    """
    rng = random.Random(seed)
    feats, failed, seen = [], 0, set()
    budget = max(200, 60 * n)
    while len(feats) + failed < n and budget > 0 and len(seen) <= hi - lo:
        oid = rng.randint(lo, hi)
        if oid in seen:
            continue
        seen.add(oid)
        budget -= 1
        body = get(url, {"where": f"{oid_field}={oid}", "outFields": out_fields,
                         "returnGeometry": "true", "outSR": 4326, "f": "json"})
        if body is None:
            failed += 1
            continue
        fs = body.get("features") if isinstance(body, dict) else None
        if fs and isinstance(fs[0].get("attributes"), dict) and accept(fs[0]["attributes"]):
            feats.append(fs[0])
    return feats, n


def _is_home(a: dict, co_no: int) -> bool:
    year = a.get("ACT_YR_BLT") or 0
    return (a.get("CO_NO") == co_no and str(a.get("DOR_UC") or "") in _HOME_USES
            and (a.get("NO_RES_UNT") or 0) >= 1
            and EARLIEST_PLAUSIBLE_YEAR <= year <= 2100)


def _city(raw) -> str | None:
    city = " ".join(str(raw or "").split())
    return None if not city or city.upper().startswith("UNINC") else city


def _zip(raw) -> str | None:
    z = str(raw or "").strip().split(".")[0]
    return z.zfill(5) if z.isdigit() and 3 <= len(z) <= 5 else None


def draw(rows: int, seed: int):
    ranges = oid_ranges(fl.PARCEL_URL, "CO_NO", "OBJECTID")
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        co_no = _FIPS[fips]
        if co_no not in ranges:
            attempted += n
            continue
        lo, hi = ranges[co_no]
        feats, tried = oid_random(fl.PARCEL_URL, "OBJECTID", lo, hi,
                                  lambda a, c=co_no: _is_home(a, c), _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            zip5 = _zip(a.get("PHY_ZIPCD")) or zip_at(*pt)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("PHY_ADDR1"), _city(a.get("PHY_CITY")),
                                         "FL", zip5),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
