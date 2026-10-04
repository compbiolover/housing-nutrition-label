"""Portland metro: homes drawn from Oregon Metro's RLIS taxlots.

Taxlots whose RLIS land use is residential (SFR, MFR, RUR), allocated across
Multnomah, Washington and Clackamas by housing units. Left out: commercial and
industrial property classes (2xx, 3xx — RLIS labels commercial condominium suites
"MFR"), and accounts with no site address, which are condominium parking spaces
and storage units rather than homes. Condominium units are drawn: each is its own
taxlot, a small stand-in polygon, and its site address names the unit.

The address is SITEADDR, SITECITY and SITEZIP — the property's own; Metro strips
owner names and mailing addresses before publishing.

Why not ``arcgis_random``: RLIS is an ArcGIS Online layer with a per-minute quota
of request units. One ordered ``resultOffset`` query per home into a 650,000-row
table spent it within the first minute (HTTP 429 on most draws), and so did
asking for a county's 235,000 matching object ids. So this draw walks a seeded
random permutation of the layer's object ids (1 to the layer's maximum) and asks
for them a batch at a time, keeping those that are homes in the county, until it
has the county's share. The first ``n`` matches of a uniform random order are a
uniform random sample without replacement of the matching taxlots, so this is
the same draw, at a few requests per county. A batch the service will not
answer is retried after its quota window; if it still fails, the county's
unfilled share is counted as attempted and missing, never silently shrunk.
"""

from __future__ import annotations

import random
import time

from housing_label.enrich.assessor import pdx
from scripts.benchmark_samplers import allocate, get, interior_point, typed

ADAPTER = "pdx"
ASSESSMENT_YEAR = "2026"      # the July 2026 quarterly RLIS refresh (2025-26 rolls)

_FIPS = dict(pdx.COUNTIES)    # county FIPS -> RLIS's one-letter COUNTY code
_HOMES = ("LANDUSE IN ('SFR','MFR','RUR') AND PROP_CODE NOT LIKE '2%' "
          "AND PROP_CODE NOT LIKE '3%' AND SITEADDR IS NOT NULL AND SITEADDR <> ''")
_BATCH = 100        # 200 ids made a URL ArcGIS Online answered with 404
_QUOTA_WAIT_S = 65     # ArcGIS Online's quota window is one minute


def _max_oid() -> int | None:
    body = get(pdx.TAXLOT_URL, {"where": "1=1", "f": "json", "outStatistics": (
        '[{"statisticType":"max","onStatisticField":"FID","outStatisticFieldName":"mx"}]')})
    feats = (body or {}).get("features") or []
    return int(feats[0]["attributes"]["mx"]) if feats else None


def _random_taxlots(where: str, n: int, seed: int, max_oid: int) -> tuple[list[dict], int]:
    order = random.Random(seed).sample(range(1, max_oid + 1), max_oid)
    feats = []
    for i in range(0, len(order), _BATCH):
        if len(feats) >= n:
            break
        chunk = order[i:i + _BATCH]
        params = {"where": where, "objectIds": ",".join(map(str, chunk)),
                  "outFields": "FID,SITEADDR,SITECITY,SITEZIP",
                  "returnGeometry": "true", "outSR": 4326, "f": "json"}
        got = get(pdx.TAXLOT_URL, params)
        if got is None:
            time.sleep(_QUOTA_WAIT_S)
            got = get(pdx.TAXLOT_URL, params)
        if got is None:
            break                       # counted below as attempted, not drawn
        # Keep the permutation's order, so "the first n" means the random order.
        by_id = {f["attributes"]["FID"]: f for f in got.get("features") or []}
        feats += [by_id[oid] for oid in chunk if oid in by_id]
    return feats[:n], n


def draw(rows: int, seed: int):
    out, attempted = [], 0
    max_oid = _max_oid()
    if max_oid is None:
        return [], rows
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = _random_taxlots(f"{_HOMES} AND COUNTY='{_FIPS[fips]}'", n,
                                       seed + i, max_oid)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            zip5 = str(a.get("SITEZIP") or "").strip()[:5] or None
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(a.get("SITEADDR"), a.get("SITECITY"), "OR", zip5),
                        "source_id": a.get("FID")})
    return out, attempted
