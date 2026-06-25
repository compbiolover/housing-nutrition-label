#!/usr/bin/env python3
"""Build the bundled county FIPS → climate-projection crosswalk.

Writes ``src/housing_label/data/climate_projections.csv`` — the offline lookup
that lets ``data/climate_projections.py`` return real downscaled climate-hazard
projections for any US county instead of a uniform placeholder.

Source (fully keyless, government-sourced)
------------------------------------------
NOAA / DOI **Climate Mapping for Resilience and Adaptation (CMRA)** screening
dataset, served as a public ArcGIS FeatureServer. CMRA aggregates LOCA-downscaled
CMIP5 projections (the NCA4 downscaling) to county polygons as 30-year means for
historical, early-, mid-, and late-century windows under two emissions pathways,
RCP4.5 (lower) and RCP8.5 (higher). RCP4.5/RCP8.5 are the standard low/high
analogs of SSP2-4.5 / SSP5-8.5.

We pull the **mid-century (≈2050) ensemble-mean** for each county under both
pathways, plus the historical baseline, for five hazard metrics:

  • TMAX95F     — annual days with max temperature > 95 °F      (extreme heat)
  • TMAX100F    — annual days with max temperature > 100 °F     (extreme heat)
  • PR1IN       — annual days with > 1 inch precipitation       (heavy precip)
  • PRMAX5DAY   — annual highest 5-day precipitation total [in] (flood)
  • CONSECDD    — annual max consecutive dry days               (drought)

Caveats (documented in data/climate_projections.py too): CMRA is a ~6 km
downscaled grid aggregated to counties — a county aggregate, never parcel-scale
precision. CMIP5/RCP (not CMIP6/SSP); RCP4.5/8.5 are treated as low/high analogs
of SSP2-4.5/5-8.5. CMRA carries no native Fire Weather Index, so the drought leg
(consecutive dry days) stands in for the fire/drought hazard until a 12 km ClimRR
FWI layer is added.

Service
-------
  https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/CMRA_Screening_Data/FeatureServer/0

Run:  python scripts/build_climate_projections.py
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import statistics
import sys
import time

import requests

OUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "housing_label" / "data" / "climate_projections.csv"
)

SERVICE = (
    "https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/"
    "CMRA_Screening_Data/FeatureServer/0"
)
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (climate crosswalk build)"}

# Hazard metric → output column stem. The CMRA fields follow the pattern
# {PERIOD}_MEAN_{METRIC}, where PERIOD ∈ {HISTORIC, RCP45MID, RCP85MID}.
METRICS = {
    "TMAX95F": "heat_days95",
    "TMAX100F": "heat_days100",
    "PR1IN": "precip_days1in",
    "PRMAX5DAY": "precip_max5day",
    "CONSECDD": "drought_consecdd",
}
# (period prefix, output band suffix)
BANDS = [("HISTORIC", "hist"), ("RCP45MID", "low"), ("RCP85MID", "high")]


def _cmra_fields() -> list[str]:
    fields = ["GEOID", "CountyName", "StateAbbr"]
    for metric in METRICS:
        for period, _ in BANDS:
            fields.append(f"{period}_MEAN_{metric}")
    return fields


def _out_columns() -> list[str]:
    cols = ["geoid", "geo_level", "county_name", "state"]
    for stem in METRICS.values():
        for _, band in BANDS:
            cols.append(f"{stem}_{band}")
    return cols


def _layer_max_record_count(service: str, default: int = 2000) -> int:
    """The layer's server-enforced maxRecordCount (default if metadata fails)."""
    try:
        r = requests.get(service, params={"f": "json"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return int(r.json().get("maxRecordCount") or default)
    except (requests.RequestException, ValueError, TypeError):
        return default


def fetch_counties(service: str) -> list[dict]:
    """Page through every county feature, newest ArcGIS pagination."""
    fields = ",".join(_cmra_fields())
    rows: list[dict] = []
    # Cap the page size at the layer's maxRecordCount so the server can't
    # silently return fewer rows than requested.
    page = min(2000, _layer_max_record_count(service))
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "returnGeometry": "false",
            "orderByFields": "GEOID",
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
        rows.extend(f["attributes"] for f in feats)
        if not data.get("exceededTransferLimit"):
            break
        # Advance by the number actually returned (the server may cap a page
        # below the requested size), never by the requested page size.
        offset += len(feats)
    return rows


def to_output_row(attrs: dict) -> dict | None:
    geoid = str(attrs.get("GEOID") or "").strip().zfill(5)
    if not geoid or len(geoid) != 5:
        return None
    out = {
        "geoid": geoid,
        "geo_level": "county",
        "county_name": (attrs.get("CountyName") or "").strip(),
        "state": (attrs.get("StateAbbr") or "").strip(),
    }
    for metric, stem in METRICS.items():
        for period, band in BANDS:
            val = attrs.get(f"{period}_MEAN_{metric}")
            out[f"{stem}_{band}"] = "" if val is None else round(float(val), 3)
    return out


def _print_quantiles(rows: list[dict]) -> None:
    """Print national quantiles of the low/high bands to anchor score breakpoints."""
    qs = [0.05, 0.25, 0.50, 0.75, 0.90, 0.95]
    print("\nNational quantiles (anchors for scoring breakpoints):", file=sys.stderr)
    for stem in METRICS.values():
        for band in ("low", "high"):
            vals = sorted(float(r[f"{stem}_{band}"]) for r in rows
                          if r[f"{stem}_{band}"] != "")
            if not vals:
                continue
            quants = statistics.quantiles(vals, n=100)
            picks = [quants[int(q * 100) - 1] for q in qs]
            joined = "  ".join(f"p{int(q*100)}={v:.1f}" for q, v in zip(qs, picks))
            print(f"  {stem+'_'+band:<26} {joined}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--service", default=SERVICE, help="CMRA FeatureServer layer URL")
    ap.add_argument("--out", default=str(OUT), help="output CSV path")
    args = ap.parse_args()

    print(f"Fetching counties from {args.service} …", file=sys.stderr)
    attrs = fetch_counties(args.service)
    rows = [r for r in (to_output_row(a) for a in attrs) if r]
    rows.sort(key=lambda r: r["geoid"])
    if len(rows) < 3000:
        print(f"WARNING: only {len(rows)} counties fetched (expected ~3233).",
              file=sys.stderr)

    out_path = pathlib.Path(args.out)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_out_columns())
        w.writeheader()
        w.writerows(rows)

    _print_quantiles(rows)
    print(f"\nWrote {len(rows)} counties → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
