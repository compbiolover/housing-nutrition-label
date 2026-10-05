"""Allegheny County: homes drawn from the county roll on WPRDC's CKAN datastore.

Records whose ``USEDESC`` the adapter reads as holding a dwelling
(``allegheny._DWELLING_USES``: single family, townhouse, rowhouse, condominium
unit, two to four family, apartments, flats over a store, farms, ...). Drawn by
uniform random offsets into that filtered set with ``datastore_search``
(``filters`` + ``offset``, sorted on ``_id`` so an offset names one row) — WPRDC's
firewall refuses ``datastore_search_sql`` with a WHERE, so the structured search is
the only way in. Each record's parcel is then fetched from the county's ArcGIS
parcel layer by its ``PIN`` (the same 16 characters as ``PARID``), and the point is
inside that polygon; a condominium unit's point is inside its own unit tile.

The address is the roll's site columns: house number (a range typed by its low
number), any other fraction, street, unit, ``PROPERTYCITY`` and ``PROPERTYZIP``.
The CHANGENOTICEADDRESS* columns are the tax bill's mailing address and are never
requested.
"""

from __future__ import annotations

import json
import random

from housing_label.enrich.assessor import allegheny
from scripts.benchmark_samplers import get, interior_point, typed, zip_at

ADAPTER = "allegheny"
ASSESSMENT_YEAR = "2026"      # TAXYEAR on the roll (as of 2026-09-30)

_FIPS = {"42003": "Allegheny"}

_FIELDS = ("_id,PARID,PROPERTYHOUSENUM,PROPERTYFRACTION,PROPERTYADDRESS,PROPERTYUNIT,"
           "PROPERTYCITY,PROPERTYZIP")
_FILTERS = json.dumps({"USEDESC": sorted(allegheny._DWELLING_USES)}, separators=(",", ":"))


def _search(**params) -> dict | None:
    body = get(allegheny.ASSESSMENT_URL, {"resource_id": allegheny.ASSESSMENT_RESOURCE,
                                          "filters": _FILTERS, **params})
    if not isinstance(body, dict) or body.get("success") is not True:
        return None
    return body.get("result") or {}


def _parcel_point(pin: str):
    body = get(allegheny.PARCEL_URL, {"where": f"PIN='{pin}'", "outFields": "PIN",
                                      "returnGeometry": "true", "outSR": 4326,
                                      "f": "json"})
    feats = (body or {}).get("features") or []
    return interior_point(feats[0].get("geometry")) if len(feats) == 1 else None


def _street(r: dict) -> str:
    number = r.get("PROPERTYHOUSENUM")
    street = " ".join(str(r.get("PROPERTYADDRESS") or "").split())
    try:
        number = int(float(number))
    except (TypeError, ValueError):
        number = 0
    if number <= 0 or not street:
        return ""
    fraction = " ".join(str(r.get("PROPERTYFRACTION") or "").split())
    base = f"{number} {street}" if not fraction or fraction.startswith("-") \
        else f"{number} {fraction} {street}"
    tokens = str(r.get("PROPERTYUNIT") or "").upper().split()
    if len(tokens) > 1 and tokens[0] in allegheny._UNIT_MARKERS:
        tokens = tokens[1:]
    unit = "".join(tokens)
    return f"{base} #{unit}" if unit else base


def draw(rows: int, seed: int):
    sized = _search(limit=0)
    total = int((sized or {}).get("total") or 0)
    if not total:
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(rows, total)))
    out = []
    for off in offsets:
        res = _search(fields=_FIELDS, sort="_id", offset=off, limit=1)
        recs = (res or {}).get("records") or []
        if not recs:
            continue
        r = recs[0]
        pin = str(r.get("PARID") or "").strip().upper()
        if not allegheny._PIN_RE.match(pin):
            continue
        pt = _parcel_point(pin)
        if pt is None:
            continue
        z = str(r.get("PROPERTYZIP") or "").strip()[:5]
        if not (z.isdigit() and len(z) == 5):
            z = zip_at(*pt)
        out.append({"fips": "42003", "lat": pt[0], "lon": pt[1],
                    "address": typed(_street(r), r.get("PROPERTYCITY"), "PA", z),
                    "source_id": pin})
    return out, len(offsets)
