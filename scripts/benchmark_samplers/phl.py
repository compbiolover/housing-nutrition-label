"""Philadelphia: homes drawn from the OPA roll (``opa_properties_public``) on Carto.

OPA accounts whose category the adapter reads as holding a dwelling (1 Single
Family, 2 Multi Family, 3 Mixed Use, 14 Apartments > 4 Units), less the two
condominium account types that are never homes (parking spaces, storage units).
Drawn by uniform random offsets into that filtered set, ordered by
``cartodb_id`` so an offset names one account; one SQL statement per batch of
offsets, every offset counted as attempted.

The point is the account's own coordinate, which OPA places inside its lot: the
adapter finds a home by the Water Department polygon that contains it, so that
coordinate is the parcel's interior by the adapter's own definition. (The 0.6% of
accounts whose point lies in no PWD polygon are unreachable by the adapter and are
counted as ``no_home_record``.)

The address is ``location`` with the account's unit, "Philadelphia, PA" and the
property's own ``zip_code``. A ranged location ("815-37 ARCH ST") is typed by its
low number, as a resident of the building would write it. The ``mailing_*``
columns are the OWNER's and are never selected.
"""

from __future__ import annotations

import random
import re

from housing_label.enrich.assessor import phl
from scripts.benchmark_samplers import get, typed, zip_at

ADAPTER = "phl"
ASSESSMENT_YEAR = "current"   # characteristics refreshed nightly

_FIPS = {"42101": "Philadelphia"}

_WHERE = ("category_code IN ('1','2','3','14') AND the_geom IS NOT NULL "
          "AND coalesce(building_code_description, '') NOT IN "
          "('CONDO PARKING SPACE', 'CONDO STORAGE UNIT')")
_RANGE = re.compile(r"^(\d+)-\d+(\s+\S.*)$")
_BATCH = 100


def _count() -> int:
    body = get(phl.SQL_URL, {"q": f"SELECT count(*) AS n FROM opa_properties_public WHERE {_WHERE}"})
    rows = (body or {}).get("rows") or []
    return int(rows[0]["n"]) if rows else 0


def _rows_at(offsets: list[int]) -> list[dict]:
    """The accounts at these offsets (0-based) of the filtered, ordered set."""
    sql = ("WITH t AS (SELECT cartodb_id, location, unit, zip_code, "
           "ST_Y(the_geom) AS lat, ST_X(the_geom) AS lon, "
           "row_number() OVER (ORDER BY cartodb_id) - 1 AS rn "
           f"FROM opa_properties_public WHERE {_WHERE}) "
           f"SELECT * FROM t WHERE rn IN ({','.join(str(int(o)) for o in offsets)})")
    return (get(phl.SQL_URL, {"q": sql}) or {}).get("rows") or []


def _street(r: dict) -> str:
    loc = " ".join(str(r.get("location") or "").split())
    m = _RANGE.match(loc)
    if m:
        loc = f"{m.group(1)}{m.group(2)}"
    unit = "".join(str(r.get("unit") or "").split())
    return f"{loc} #{unit}" if loc and unit else loc


def draw(rows: int, seed: int):
    total = _count()
    if not total:
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(rows, total)))
    out = []
    for i in range(0, len(offsets), _BATCH):
        for r in _rows_at(offsets[i:i + _BATCH]):
            if r.get("lat") is None or r.get("lon") is None:
                continue
            lat, lon = float(r["lat"]), float(r["lon"])
            z = str(r.get("zip_code") or "").strip()[:5]
            if not (z.isdigit() and len(z) == 5):
                z = zip_at(lat, lon)
            out.append({"fips": "42101", "lat": lat, "lon": lon,
                        "address": typed(_street(r), "Philadelphia", "PA", z),
                        "source_id": r.get("cartodb_id")})
    return out, len(offsets)
