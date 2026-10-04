"""San Francisco: homes drawn from the Assessor-Recorder's secured roll on DataSF.

A Socrata source, so the draw is written here rather than through
``arcgis_random``: uniform random offsets (with the seed) into the latest closed
roll's residential records, one ``$offset`` request each, ordered so an offset
names one row. Residential is the adapter's own rule — use ``SRES`` or ``MRES``,
or class ``AC``/``ACG`` ("Apartment & Commercial Store", filed under ``COMM``).
Condominium units are their own records and are drawn as such.

Each drawn record's lot polygon comes from the parcel layer (``acdm-wktn``,
active lots, by ``blklot``) for a point inside the lot; a condominium unit's lot
is drawn on the building's footprint, so the point is inside the building. The
address is the roll's ``property_location`` read as the adapter reads it (bottom
number of a range, lettered doors kept, the unit with its zero padding dropped),
"San Francisco", and the ZCTA at the lot: the roll publishes no ZIP, and it has
no owner or mailing column at all.
"""

from __future__ import annotations

import logging
import random

from housing_label.enrich.assessor import sf
from scripts.benchmark_samplers import get, interior_point, typed, zip_at

log = logging.getLogger("build_benchmark")

ADAPTER = "sf"
#: The closed roll drawn from. Found at draw time (the dataset gains a year each
#: summer) and rewritten by ``draw``; 2025 was the latest on 2026-10-04.
ASSESSMENT_YEAR = "2025"

_FIPS = {"06075": "San Francisco"}
_HOMES = ("(use_code in ('SRES','MRES') OR property_class_code in ('AC','ACG'))")
_COLUMNS = "parcel_number,property_location"


def _latest_roll() -> int | None:
    body = get(sf.ROLL_URL, {"$select": "max(closed_roll_year) AS latest"})
    try:
        return int(float(body[0]["latest"]))
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _point_in_lot(blklot: str) -> tuple[float, float] | None:
    """A point inside the active lot ``blklot`` (its first polygon), or None."""
    if not sf._PARCEL_NUMBER_RE.match(blklot):
        return None
    body = get(sf.PARCELS_URL, {"$select": "blklot,shape",
                                "$where": f"active AND blklot='{blklot}'",
                                "$limit": "5"})
    for row in body or []:
        shape = (row or {}).get("shape") or {}
        coords = shape.get("coordinates") or []
        polys = coords if shape.get("type") == "MultiPolygon" else [coords]
        for rings in polys:
            pt = interior_point({"rings": rings})
            if pt is not None:
                return pt
    return None


def _street(location) -> str:
    """The roll's address as a resident types the street part; "" when none."""
    parts = sf._parse_location(location)
    if parts is None or parts["low"] <= 0:
        return ""
    if parts["low_suffix"] and not parts["low_suffix"].isalpha():
        return ""
    street = f"{parts['low']}{parts['low_suffix']} {sf._street(parts)}"
    unit = parts["unit"].lstrip("0")
    return f"{street} #{unit}" if unit else street


def draw(rows: int, seed: int):
    global ASSESSMENT_YEAR
    year = _latest_roll()
    if year is None:
        log.warning("  data.sf.gov: could not read the latest closed roll year")
        return [], 0
    ASSESSMENT_YEAR = str(year)
    where = f"closed_roll_year={year} AND {_HOMES}"
    body = get(sf.ROLL_URL, {"$select": "count(*) AS n", "$where": where})
    try:
        total = int(body[0]["n"])
    except (TypeError, ValueError, KeyError, IndexError):
        log.warning("  data.sf.gov: could not size the residential roll")
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(rows, total)))
    out = []
    for off in offsets:
        got = get(sf.ROLL_URL, {"$select": _COLUMNS, "$where": where,
                                "$order": "parcel_number,:id", "$offset": str(off),
                                "$limit": "1"})
        if not got:
            continue
        row = got[0]
        pid = str(row.get("parcel_number") or "").strip().upper()
        pt = _point_in_lot(pid)
        if pt is None:
            continue
        street = _street(row.get("property_location"))
        address = typed(street, "San Francisco", "CA", zip_at(*pt)) if street else ""
        out.append({"fips": "06075", "lat": pt[0], "lon": pt[1], "address": address,
                    "source_id": pid})
    return out, len(offsets)
