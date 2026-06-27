#!/usr/bin/env python3
"""Build the bundled FEMA National Risk Index (NRI) wildfire crosswalk(s).

Writes the offline lookups that let ``data/wildfire.py`` return a real,
location-based wildfire **expected annual loss (EAL) rate** for any US tract or
county: ``nri_wildfire.csv`` (county) and ``nri_wildfire_tracts.csv.gz``
(genuinely sub-county). The Disaster Resilience model treats this as the "fire"
hazard alongside flood, tornado, and seismic — replacing the old national-average
fire constant with a value that actually varies by where the home sits.

Source (keyless, authoritative, reachable)
------------------------------------------
FEMA **National Risk Index** (NRI), the agency's official multi-hazard risk
dataset, published as public Esri-hosted Feature Services under FEMA's ArcGIS
Online org ``FEMA_NationalRiskIndex``:

  county : National_Risk_Index_Counties/FeatureServer/0     (~3,232 counties)
  tract  : National_Risk_Index_Census_Tracts/FeatureServer/0 (~85,154 tracts)

The static bulk ZIPs on ``hazards.fema.gov`` are origin-403 to non-browser
clients; the ArcGIS Online services carry the identical ``WFIR_*`` fields and
page cleanly over HTTP, so we use those.

Wildfire EAL rate
-----------------
NRI defines expected annual loss as ``Exposure × AnnualizedFrequency × HistoricLossRatio``.
The dimensionless **EAL rate** (fraction of exposed building value lost per year)
is therefore::

    wfir_eal_rate = WFIR_AFREQ × WFIR_HLRB

which equals ``WFIR_EALB / WFIR_EXPB`` where building exposure is non-zero. This
drops straight into ``score/resilience.py``'s EAL-rate framework (the same units
as the flood/tornado/seismic rates). We also carry ``WFIR_RISKR`` (FEMA's
qualitative wildfire risk rating, e.g. "Very Low" … "Very High") for display.

Caveats (documented in data/wildfire.py too): NRI is a present-day baseline (not
a forward climate projection), tract-level at finest, and reflects *wildfire*
specifically — structural/electrical fire is modeled separately in the CLI
simulator. Tracts/counties absent from the crosswalk fall back to a coarser
geography or the national average.

Run:  python scripts/build_nri_wildfire.py                 # national county + tract (default)
      python scripts/build_nri_wildfire.py --state 47      # one state FIPS (pilot)
      python scripts/build_nri_wildfire.py --county 47157  # one county (e.g. Shelby, TN)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import pathlib
import statistics
import sys
import time

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

ORG = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services"
# Browser-ish UA: FEMA's static host blocks scripted clients, and the ArcGIS
# services are happy with a normal agent string.
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (NRI wildfire crosswalk build)"}

# Per geo level: feature service, id field, zero-pad width, geo_level value,
# default output path, and the expected national row count (for a sanity check).
GEO_LEVELS: dict[str, dict] = {
    "county": {
        "service": f"{ORG}/National_Risk_Index_Counties/FeatureServer/0",
        "id_field": "STCOFIPS", "width": 5, "geo_level": "county",
        "out": _DATA_DIR / "nri_wildfire.csv", "expected": 3232,
    },
    "tract": {
        "service": f"{ORG}/National_Risk_Index_Census_Tracts/FeatureServer/0",
        "id_field": "TRACTFIPS", "width": 11, "geo_level": "tract",
        "out": _DATA_DIR / "nri_wildfire_tracts.csv.gz", "expected": 85154,
    },
}

# NRI source fields we read. AFREQ × HLRB → the EAL rate; RISKR is the qualitative
# rating; COUNTY/STATE name the place.
SRC_FIELDS = ["WFIR_AFREQ", "WFIR_HLRB", "WFIR_RISKR", "COUNTY", "STATE"]
OUT_COLUMNS = ["geoid", "geo_level", "county_name", "state",
               "wfir_afreq", "wfir_hlrb", "wfir_eal_rate", "wfir_risk_rating"]


def _eal_rate(afreq, hlrb) -> float:
    """Wildfire EAL rate = annualized frequency × historic building loss ratio.

    NRI uses default sentinels (e.g. HLRB=0.1) even where AFREQ is 0/None, so the
    frequency gate is what zeroes a no-hazard tract. Non-numeric → 0.0.
    """
    try:
        a = float(afreq)
        h = float(hlrb)
    except (TypeError, ValueError):
        return 0.0
    if not (a > 0.0):
        return 0.0
    return round(a * h, 9)


def _max_record_count(service: str, default: int = 2000) -> int:
    try:
        r = requests.get(service, params={"f": "json"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return int(r.json().get("maxRecordCount") or default)
    except (requests.RequestException, ValueError, TypeError):
        return default


def fetch_rows(level: dict, where: str) -> list[dict]:
    """Page through every matching feature in a layer and map to output rows."""
    service = level["service"]
    id_field = level["id_field"]
    out_fields = ",".join([id_field] + SRC_FIELDS)
    page = min(2000, _max_record_count(service))
    offset = 0
    rows: list[dict] = []
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "false",
            "orderByFields": id_field,
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        for attempt in range(4):
            try:
                r = requests.get(f"{service}/query", params=params,
                                 headers=HEADERS, timeout=90)
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        feats = data.get("features", [])
        if not feats:
            break
        for f in feats:
            row = _to_output_row(f.get("attributes", {}), level)
            if row:
                rows.append(row)
        if not data.get("exceededTransferLimit"):
            break
        offset += len(feats)
        print(f"  …{len(rows)} rows", file=sys.stderr)
    return rows


def _to_output_row(attrs: dict, level: dict) -> dict | None:
    geoid = str(attrs.get(level["id_field"]) or "").strip().zfill(level["width"])
    if not geoid or len(geoid) != level["width"]:
        return None
    return {
        "geoid": geoid,
        "geo_level": level["geo_level"],
        "county_name": (attrs.get("COUNTY") or "").strip(),
        "state": (attrs.get("STATE") or "").strip(),
        "wfir_afreq": attrs.get("WFIR_AFREQ"),
        "wfir_hlrb": attrs.get("WFIR_HLRB"),
        "wfir_eal_rate": _eal_rate(attrs.get("WFIR_AFREQ"), attrs.get("WFIR_HLRB")),
        "wfir_risk_rating": (attrs.get("WFIR_RISKR") or "").strip(),
    }


def _write_rows(rows: list[dict], out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out_path.suffix == ".gz" else open
    with opener(out_path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _print_quantiles(rows: list[dict]) -> None:
    """National quantiles of the EAL rate — anchors for the resilience breakpoints."""
    vals = sorted(float(r["wfir_eal_rate"]) for r in rows if float(r["wfir_eal_rate"]) > 0)
    if not vals:
        print("\nNo positive wildfire EAL rates in this build.", file=sys.stderr)
        return
    nonzero_pct = 100 * len(vals) / len(rows)
    if len(vals) < 2:
        print(f"\nWildfire EAL rate — {len(vals)}/{len(rows)} rows > 0 "
              f"({nonzero_pct:.1f}%); value={vals[-1]:.2e}", file=sys.stderr)
        return
    qs = [0.50, 0.75, 0.90, 0.95, 0.99]
    quants = statistics.quantiles(vals, n=100)
    picks = "  ".join(f"p{int(q*100)}={quants[int(q*100)-1]:.2e}" for q in qs)
    print(f"\nWildfire EAL rate — {len(vals)}/{len(rows)} rows > 0 ({nonzero_pct:.1f}%); "
          f"of those: {picks}  max={vals[-1]:.2e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default=None,
                    help="Build only this 2-digit state FIPS (pilot validation).")
    ap.add_argument("--county", default=None,
                    help="Build only this 5-digit county FIPS (e.g. 47157 Shelby, TN).")
    ap.add_argument("--county-out", default=None, help="county output path override")
    ap.add_argument("--tract-out", default=None, help="tract output path override")
    args = ap.parse_args()

    scope = "national"
    if args.county:
        scope = f"county {args.county}"
    elif args.state:
        scope = f"state {args.state}"
    print(f"FEMA NRI wildfire build ({scope}). Source: {ORG}", file=sys.stderr)

    for name, level in GEO_LEVELS.items():
        id_field = level["id_field"]
        if args.county:
            where = (f"STCOFIPS='{args.county}'" if name == "tract"
                     else f"{id_field}='{args.county}'")
        elif args.state:
            st = args.state.zfill(2)
            where = (f"STATEFIPS='{st}'" if name == "tract" else f"STATEFIPS='{st}'")
        else:
            where = "1=1"

        print(f"\nFetching {name} features …", file=sys.stderr)
        rows = fetch_rows(level, where)
        rows.sort(key=lambda r: r["geoid"])

        if scope == "national" and len(rows) < level["expected"] * 0.9:
            print(f"WARNING: only {len(rows)} {name} rows (expected ~{level['expected']}).",
                  file=sys.stderr)

        out = pathlib.Path(args.county_out if name == "county" and args.county_out
                           else args.tract_out if name == "tract" and args.tract_out
                           else level["out"])
        _write_rows(rows, out)
        _print_quantiles(rows)
        print(f"Wrote {len(rows)} {name} rows → {out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
