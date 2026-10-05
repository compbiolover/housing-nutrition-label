"""Los Angeles County: homes drawn from the county eGIS parcel layer.

Parcels the roll classifies ``UseType = 'Residential'`` — the class the adapter
reads as a home — drawn uniformly at random. The address is the situs from its
parts (number, fraction, direction, street), the situs unit where the roll names
one, and the roll's own situs city and ZIP; the layer carries no owner or mailing
column among those read.
"""

from __future__ import annotations

import re

from housing_label.enrich.assessor import la
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "la"
ASSESSMENT_YEAR = "2026"     # Roll_Year on the layer's rows (2026-10-04)

_FIPS = {"06037": "Los Angeles"}
_WHERE = "UseType='Residential'"
_FIELDS = ("OBJECTID,AIN,SitusHouseNo,SitusFraction,SitusDirection,SitusStreet,"
           "SitusUnit,SitusCity,SitusZIP")
# SitusCity carries the state: "LOS ANGELES CA".
_STATE_TAIL = re.compile(r"\s+CA$")



def _street(a: dict) -> str:
    """The situs as the roll writes it, from its parts; "" when it has none.

    Not ``la._address_of``, which respells lettered avenues for its comparison
    ("AVENUE L8" joined into one token) — a resident types the avenue as written.
    House number 0 is the roll's "no situs".
    """
    number = str(a.get("SitusHouseNo") or "").strip()
    street = " ".join(str(a.get("SitusStreet") or "").split())
    if not (number.isdigit() and int(number) > 0 and street):
        return ""
    parts = [number, str(a.get("SitusFraction") or "").strip(),
             str(a.get("SitusDirection") or "").strip(), street]
    return " ".join(p for p in parts if p)


def _unit(raw) -> str:
    key = la._unit_key(raw)
    return f" #{key}" if key else ""


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = arcgis_random(la.PARCEL_URL, _WHERE, _FIELDS, n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            street = _street(a)
            if not street:
                out.append({"fips": fips, "lat": pt[0], "lon": pt[1], "address": "",
                            "source_id": a.get("AIN")})
                continue
            city = _STATE_TAIL.sub("", " ".join(str(a.get("SitusCity") or "").split()))
            zip5 = str(a.get("SitusZIP") or "").strip()[:5]
            if not (len(zip5) == 5 and zip5.isdigit()):
                zip5 = zip_at(*pt)
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street + _unit(a.get("SitusUnit")),
                                         city or None, "CA", zip5),
                        "source_id": a.get("AIN")})
    return out, attempted
