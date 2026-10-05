"""New York State: homes drawn from the NYS public tax parcel layer (GeoHub).

Residential (ORPTS class 2xx) parcels in the 33 counties outside New York City that
the adapter serves, allocated by housing units. Not filtered on a year built: in
Suffolk and Westchester many towns file no residential inventory, and a home
there that the roll gives no year is exactly what a visitor would meet, so it is
counted as ``no_home_record`` rather than drawn around.

The address is the roll's location number and street (plus its unit, the way a
condominium owner would type it), the municipality the roll names for the site,
and the roll's own location ZIP — or the ZCTA at the parcel where it has none.
The MAIL_* columns are the OWNER's mailing address and are never read.
"""

from __future__ import annotations

import random
import re

from housing_label.enrich.assessor import nys
from scripts.benchmark_samplers import allocate, get, interior_point, typed, zip_at

ADAPTER = "nys"
ASSESSMENT_YEAR = "2025"     # ROLL_YR on the layer's residential rows (2026-10-03)

# COUNTY_NAME as the layer spells it (no spaces: "StLawrence").
_FIPS = {
    "36001": "Albany", "36007": "Broome", "36011": "Cayuga", "36013": "Chautauqua",
    "36023": "Cortland", "36029": "Erie", "36037": "Genesee", "36039": "Greene",
    "36041": "Hamilton", "36049": "Lewis", "36051": "Livingston",
    "36057": "Montgomery", "36065": "Oneida", "36067": "Onondaga",
    "36069": "Ontario", "36071": "Orange", "36075": "Oswego", "36077": "Otsego",
    "36079": "Putnam", "36083": "Rensselaer", "36087": "Rockland",
    "36089": "StLawrence", "36097": "Schuyler", "36101": "Steuben",
    "36103": "Suffolk", "36105": "Sullivan", "36107": "Tioga", "36109": "Tompkins",
    "36111": "Ulster", "36113": "Warren", "36117": "Wayne", "36119": "Westchester",
    "36121": "Wyoming",
}

_FIELDS = "OBJECTID,MUNI_NAME,CITYTOWN_NAME,LOC_ST_NBR,LOC_STREET,LOC_UNIT,LOC_ZIP,PARCEL_ADDR"
_UNIT_MARKER = re.compile(r"^(?:UNIT|APT|STE|SUITE|#)\.?\s*", re.I)
# MUNI_NAME tags the kind of municipality after a comma ("Bergen, Village",
# "Amsterdam, City", "Ithaca, Town"); a resident types the bare name.
_MUNI_KIND = re.compile(r",\s*(?:Village|City|Town)\s*$", re.I)


def _street(a: dict) -> str:
    number = str(a.get("LOC_ST_NBR") or "").strip()
    # The Town of Clarkstown runs the hamlet into its street column ("TAMAR DRIVE
    # VALLEY COTTAG"); nobody types that, so the tail is cut with the adapter's
    # own rule (which cuts only those exact phrases after a street type).
    street = " ".join(nys._base_tokens(str(a.get("LOC_STREET") or "").strip()))
    base = f"{number} {street}" if number and street else str(a.get("PARCEL_ADDR") or "")
    unit = _UNIT_MARKER.sub("", str(a.get("LOC_UNIT") or "").strip())
    if unit and number and street:
        base = f"{base} #{unit.replace(' ', '')}"
    return base


def _zip(a: dict, pt) -> str | None:
    z = str(a.get("LOC_ZIP") or "").strip()[:5]
    return z if z.isdigit() and len(z) == 5 and z != "00000" else zip_at(*pt)


def _random_features(where: str, n: int, seed: int) -> tuple[list[dict], int]:
    """``n`` features drawn uniformly from those matching ``where``.

    GeoHub answers an ordered ``resultOffset`` query over a county's few hundred
    thousand rows in 3 to 15 s and resets connections under load, so the shared
    one-request-per-offset draw took most of an hour here. The same uniform
    draw in two requests per county: every matching object id
    (``returnIdsOnly``), a seeded sample of them, then those features by id.
    """
    body = get(nys.PARCEL_URL, {"where": where, "returnIdsOnly": "true", "f": "json"})
    ids = sorted((body or {}).get("objectIds") or [])
    if not ids:
        # A failed id list is n failed draws, not a county with nothing in it.
        return [], n
    picked = sorted(random.Random(seed).sample(ids, min(n, len(ids))))
    body = get(nys.PARCEL_URL, {"where": f"OBJECTID IN ({','.join(map(str, picked))})",
                                "outFields": _FIELDS, "returnGeometry": "true",
                                "outSR": 4326, "f": "json"})
    return (body or {}).get("features") or [], len(picked)


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = _random_features(
            f"COUNTY_NAME='{_FIPS[fips]}' AND PROP_CLASS LIKE '2%'", n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            city = _MUNI_KIND.sub("", str(a.get("MUNI_NAME") or a.get("CITYTOWN_NAME") or ""))
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(_street(a), city, "NY", _zip(a, pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
