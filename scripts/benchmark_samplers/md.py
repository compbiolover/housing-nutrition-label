"""Maryland: homes drawn from MD iMAP's SDAT parcel polygons.

Polygons the Department of Planning classes as residential (``RESITYP`` SF, TH,
CN, AP or MH) with a premise address (``ADDRTYP = 'P'``) and a recorded year
built, allocated across the 23 counties and Baltimore City by housing units.
``ADDRTYP = 'O'`` rows are excluded because their ``ADDRESS`` is the owner's
mailing address, and the OWNADD*/OWNCITY/OWNERZIP columns are never requested.

The address is the premise address, with the unit when the roll records one
unambiguously (as the adapter reads it — a condominium resident types the unit,
and the adapter uses it to pick the unit's own record), the premise city
``PREMCITY`` and the premise ZIP ``PREMZIP`` (the ZCTA at the parcel if blank).

Condominium units that exist only as account points — about 150,000 homes,
mostly in Montgomery, Prince George's and Baltimore — have no polygon and are
outside this draw (see the adapter's "Accounts with no polygon").
"""

from __future__ import annotations

from housing_label.enrich.assessor import md
from scripts.benchmark_samplers import allocate, arcgis_random, interior_point, typed, zip_at

ADAPTER = "md"
ASSESSMENT_YEAR = "2026"     # SDATDATE on the layer's rows ("2026MAY")

_FIPS = {
    "24001": "ALLE", "24003": "ANNE", "24005": "BACO", "24009": "CALV",
    "24011": "CARO", "24013": "CARR", "24015": "CECI", "24017": "CHAR",
    "24019": "DORC", "24021": "FRED", "24023": "GARR", "24025": "HARF",
    "24027": "HOWA", "24029": "KENT", "24031": "MONT", "24033": "PRIN",
    "24035": "QUEE", "24037": "STMA", "24039": "SOME", "24041": "TALB",
    "24043": "WASH", "24045": "WICO", "24047": "WORC", "24510": "BACI",
}
_WHERE = ("JURSCODE='{}' AND RESITYP IS NOT NULL AND ADDRTYP='P' "
          "AND YEARBLT IS NOT NULL AND YEARBLT<>'0000'")


def draw(rows: int, seed: int):
    out, attempted = [], 0
    for i, (fips, n) in enumerate(sorted(allocate(rows, _FIPS, seed).items())):
        feats, tried = arcgis_random(
            md.PARCEL_URL, _WHERE.format(_FIPS[fips]),
            "OBJECTID,ADDRESS,STRTUNT,PREMCITY,PREMZIP", n, seed + i)
        attempted += tried
        for f in feats:
            pt = interior_point(f.get("geometry"))
            if pt is None:
                continue
            a = f["attributes"]
            street = " ".join(str(a.get("ADDRESS") or "").split())
            unit = md._row_unit(a)
            if street and unit:
                street = f"{street} UNIT {unit}"
            zip5 = str(a.get("PREMZIP") or "").strip()[:5]
            out.append({"fips": fips, "lat": pt[0], "lon": pt[1],
                        "address": typed(street, a.get("PREMCITY"), "MD",
                                         zip5 if zip5.isdigit() and len(zip5) == 5
                                         else zip_at(*pt)),
                        "source_id": a.get("OBJECTID")})
    return out, attempted
