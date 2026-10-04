"""Benchmark samplers for the adapters that read an ArcGIS (or similar) layer.

``scripts/build_benchmark.py`` grew one hand-written sampler per jurisdiction —
Cook's CAMA, DC's two tables — each mapping that assessor's columns onto the
label's fields itself. That is the stronger test, and it does not scale: there
are now some twenty-five adapters, each already holding a careful mapping of its
own source, and writing a second, independent mapping for each would be a second
place for every one of those rules to drift.

So a sampler here does the part only it can do — draw homes at random from the
source and say where each one is and what its address is — and asks the
**adapter itself** what the county records there, at a point inside the parcel and
with the parcel's own address. That record is the reference ("truth") the harness
grades both arms against.

What that measures, and what it does not
----------------------------------------
* It measures what a visitor experiences: typed the address, geocoded, looked up
  — how often the county's record reaches the label, whether it is the right
  record, and how much it moves the grades against the modeled baseline.
* It does NOT test the adapter's field mapping: both the reference and the
  adapter arm read the record through the same code. Each adapter's mapping was
  checked separately against the raw source values (year built and floor area)
  in its own verification run, recorded in its module docstring. The published
  page says so beside these sections, as it already does for the categorical
  fields of Cook and DC.

A drawn home the adapter will not read even at its own parcel — a condominium
stack it cannot separate, a record that says no dwelling — is dropped and counted
as ``no_home_record``, so the page reports it rather than letting the sample
quietly become "homes the adapter handles".

Each jurisdiction module in this package defines ``ADAPTER`` (the adapter module's
key in ``enrich.assessor``) and ``draw(rows, seed) -> (candidates, attempted)``,
where each candidate is ``{"fips", "address", "lat", "lon", "source_id"}``.
"""

from __future__ import annotations

import csv
import importlib
import logging
import os
import pathlib
import random
import time

import requests

log = logging.getLogger("build_benchmark")

_ROOT = pathlib.Path(__file__).resolve().parents[2]
UNITS_CSV = _ROOT / "src" / "housing_label" / "data" / "year_built_county.csv"
HEADERS = {"User-Agent": "housing-nutrition-label (accuracy benchmark build)"}
TIMEOUT = 60

FIELDS = ["year_built", "sqft", "stories", "construction", "foundation", "condition"]


def get(url: str, params: dict, attempts: int = 4):
    """GET JSON with backoff; None once the attempts are spent."""
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            body = r.json()
            if isinstance(body, dict) and body.get("error"):
                raise requests.RequestException(str(body["error"])[:200])
            return body
        except (requests.RequestException, ValueError) as exc:
            if i == attempts - 1:
                log.warning("  giving up after %d attempts: %s", attempts, exc)
                return None
            time.sleep(2 ** i)
    return None


def county_units() -> dict[str, int]:
    """ACS housing units per county FIPS — the weights for a multi-county draw."""
    with UNITS_CSV.open(newline="", encoding="utf-8") as fh:
        return {r["geoid"]: int(float(r["units"] or 0)) for r in csv.DictReader(fh)}


def allocate(rows: int, fips_list, seed: int) -> dict[str, int]:
    """Split ``rows`` across counties in proportion to their housing units.

    Proportional rather than equal, so a module's figure describes its homes, not
    an average of counties in which a small one counts as much as a big one.
    Largest remainders, so the parts sum to ``rows`` exactly; every county gets
    at least one row so none is silently unmeasured.
    """
    units = county_units()
    w = {f: units.get(f, 0) for f in fips_list}
    total = sum(w.values()) or 1
    raw = {f: rows * w[f] / total for f in w}
    out = {f: max(1, int(raw[f])) for f in w}
    rng = random.Random(seed)
    order = sorted(w, key=lambda f: (-(raw[f] - int(raw[f])), rng.random()))
    i = 0
    while sum(out.values()) < rows and order:
        out[order[i % len(order)]] += 1
        i += 1
    return out


def arcgis_count(url: str, where: str) -> int | None:
    body = get(url, {"where": where, "returnCountOnly": "true", "f": "json"})
    return None if body is None else body.get("count")


def arcgis_random(url: str, where: str, out_fields: str, n: int, seed: int,
                  *, oid_field: str = "OBJECTID", geometry: bool = True,
                  out_sr: int = 4326) -> tuple[list[dict], int]:
    """``n`` features drawn uniformly at random from the rows matching ``where``.

    Random offsets into the filtered set, one request each, ordered by the
    object id so an offset names one row. Returns (features, attempted).
    """
    total = arcgis_count(url, where)
    if not total:
        log.warning("  %s: no rows match %r", url, where)
        return [], 0
    offsets = sorted(random.Random(seed).sample(range(total), min(n, total)))
    feats = []
    for off in offsets:
        body = get(url, {"where": where, "outFields": out_fields,
                         "orderByFields": oid_field, "resultOffset": off,
                         "resultRecordCount": 1,
                         "returnGeometry": "true" if geometry else "false",
                         "outSR": out_sr, "f": "json"})
        fs = (body or {}).get("features") or []
        if fs:
            feats.append(fs[0])
    return feats, len(offsets)


def interior_point(geometry: dict) -> tuple[float, float] | None:
    """(lat, lon) of a point inside an ArcGIS polygon (or the point itself).

    The ring's centroid when it falls inside; otherwise the midpoint of the first
    span of a horizontal line through the centroid's latitude, which is inside by
    construction (even-odd rule, holes included). A concave lot's centroid can sit
    on the neighbor's land, and a lookup there would test the wrong parcel.
    """
    if not geometry:
        return None
    if "x" in geometry and "y" in geometry:
        return geometry["y"], geometry["x"]
    rings = geometry.get("rings") or []
    if not rings or not rings[0]:
        return None
    ring = rings[0]
    # Relative to the first vertex: in raw degrees a small lot's shoelace terms
    # are products near 74 x 41 that cancel to an area of ~1e-9, and the lost
    # precision threw the centroid hundreds of meters off the lot (42 of 200 New
    # Jersey draws failed that way before this).
    ox, oy = ring[0][0], ring[0][1]
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        x0, y0, x1, y1 = x0 - ox, y0 - oy, x1 - ox, y1 - oy
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-24:
        x = sum(p[0] for p in ring) / len(ring)
        y = sum(p[1] for p in ring) / len(ring)
    else:
        x, y = cx / (3 * a) + ox, cy / (3 * a) + oy
    if _inside(x, y, rings):
        return y, x
    xs = []
    for r in rings:
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            if (y0 > y) != (y1 > y):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    xs.sort()
    if len(xs) >= 2:
        return y, (xs[0] + xs[1]) / 2
    return None


def _inside(x: float, y: float, rings) -> bool:
    inside = False
    for r in rings:
        for (x0, y0), (x1, y1) in zip(r, r[1:]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def truth_at(adapter_key: str, fips: str, lat: float, lon: float, address: str):
    """The adapter's record for the home at this point and address, or None.

    Through ``assessor_for_point`` — the registry door the label uses — so the
    reference obeys exactly the rules a label's record does, empty-record rule
    included. Returns ``(parcel_id, truth_fields)``.
    """
    os.environ.setdefault("ASSESSOR_ADAPTERS", "1")
    from housing_label.enrich import assessor as reg
    mod = importlib.import_module(f"housing_label.enrich.assessor.{adapter_key}")
    if reg.adapter_for_county(fips) is not mod:
        raise SystemExit(f"{fips} is not served by {adapter_key}; the sampler and "
                         f"the registry disagree about who answers there.")
    # Retried, because None means two things the registry does not distinguish: the
    # adapter's refusal (deterministic, and cached by the adapter, so a retry is
    # free) and a lookup that timed out and failed open (not cached). Counting the
    # second as "not a home" overstated the drops in every build that ran beside
    # another — 22 of 200 in one Texas build, 3 on a quiet rebuild.
    rec = None
    for attempt in range(3):
        rec = reg.assessor_for_point(lat, lon, fips, address)
        if rec is not None:
            break
        time.sleep(1 + attempt)
    if rec is None:
        return None
    fields = rec.fields()
    truth = {f: ("" if fields.get(f) is None else fields[f]) for f in FIELDS}
    if truth["year_built"] == "":
        return None
    return (rec.parcel_id or ""), truth


def build(sampler, rows: int, seed: int):
    """Run a sampler module: draw, then read the reference at each drawn home.

    Returns (out_rows, draw, dropped, assessment_year) in build_benchmark's shape.
    """
    cands, attempted = sampler.draw(rows, seed)
    dropped = {"no_parcel_record": attempted - len(cands), "no_address": 0,
               "no_year_built": 0, "no_home_record": 0}
    out = []
    for c in cands:
        if not (c.get("address") or "").strip():
            dropped["no_address"] += 1
            continue
        got = truth_at(sampler.ADAPTER, c["fips"], c["lat"], c["lon"], c["address"])
        if got is None:
            dropped["no_home_record"] += 1
            continue
        pid, truth = got
        out.append({"parcel_id": pid, "address": c["address"],
                    "lat": round(c["lat"], 6), "lon": round(c["lon"], 6), **truth})
    return out, {"attempted": attempted}, dropped, getattr(sampler, "ASSESSMENT_YEAR",
                                                           "current")


_ZCTA_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
             "PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query")


def zip_at(lat: float, lon: float) -> str | None:
    """The ZIP code tabulation area containing a point — a stand-in for the ZIP a
    resident would type, for sources that publish no site ZIP (several publish
    only the OWNER's mailing ZIP, which must never be used: an absentee owner's
    ZIP would send the geocoder to the wrong city)."""
    body = get(_ZCTA_URL, {"geometry": f"{lon},{lat}",
                           "geometryType": "esriGeometryPoint", "inSR": "4326",
                           "spatialRel": "esriSpatialRelIntersects",
                           "outFields": "ZCTA5", "returnGeometry": "false", "f": "json"})
    feats = (body or {}).get("features") or []
    return feats[0]["attributes"].get("ZCTA5") if feats else None


def typed(street: str, city: str | None, state: str, zip5: str | None) -> str:
    """An address as a resident would type it: "12 MAIN ST, Springfield, NJ 07081"."""
    street = " ".join(str(street or "").split())
    if not street:
        return ""
    parts = [street]
    if city:
        parts.append(" ".join(str(city).split()).title())
    parts.append(f"{state} {zip5}".strip() if zip5 else state)
    return ", ".join(parts)
