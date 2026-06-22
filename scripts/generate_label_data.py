#!/usr/bin/env python3
"""Regenerate docs/data/sample-parcels.json from real CLI-simulator output.

Runs the all-dimension simulator for each website construction preset at a fixed
Memphis location and writes the nutrition-label data the docs site consumes. The
five construction-driven dimensions are modeled from the house config; the three
location-driven dimensions (health, socioeconomic, walkability) are fetched live
once for the location and shared across presets (construction can't change where
a house sits). Sources that need an API key (Census ACS, Walk Score) fall back to
``null`` and are excluded from the composite rather than fabricated.

Usage
-----
  python scripts/generate_label_data.py                 # fetch location dims live
  python scripts/generate_label_data.py --no-fetch      # offline; location dims null
"""

import argparse
import json
import pathlib
from argparse import Namespace

from housing_label.simulate.house import resolve_config, simulate
from housing_label.simulate.dimensions import DIMENSIONS, simulate_all_dimensions

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "docs" / "data" / "sample-parcels.json"

LAT, LON = 35.13, -89.99   # Cooper-Young, Memphis — walkable Midtown neighborhood

# Display name + simulator preset + human description for each website parcel.
WEBSITE_PRESETS = [
    ("Worst Case",     "worst-case",     "1945 wood frame, AE flood zone, poor condition"),
    ("Baseline",       "baseline",       "2000 wood frame, X flood zone, average condition"),
    ("Premium",        "premium",        "2026 brick, X flood zone, excellent condition"),
    ("FORTIFIED Gold", "fortified-gold", "2026 frame with FORTIFIED Gold roof system"),
    ("ICF Passive",    "icf-passive",    "2026 ICF, solar, passive-house envelope, all resilience upgrades"),
]

# Fields resolve_config reads off the args namespace (None → use preset/default).
_CONFIG_FIELDS = [
    "flood_zone", "year_built", "construction", "foundation", "condition",
    "value", "units", "sqft", "lot_acres",
]


def _cfg_for(preset: str) -> dict:
    """Build a resolved house config for a named simulator preset at LAT/LON."""
    args = Namespace(preset=preset, lat=LAT, lon=LON,
                     **{f: None for f in _CONFIG_FIELDS})
    return resolve_config(args)


def _metrics(result_r: dict, label: dict) -> dict:
    """Headline metric strings shown under each label."""
    m = label["metrics"]
    out = {"Expected Annual Loss": f"${result_r['total_loss']:,.0f}/yr"}
    if m.get("eui_kbtu_sqft_yr") is not None:
        out["EUI"] = f"{m['eui_kbtu_sqft_yr']:.1f} kBTU/sqft/yr"
    if m.get("est_monthly_energy_cost") is not None:
        out["Monthly Energy"] = f"${m['est_monthly_energy_cost']:,.0f}"
    if m.get("fiscal_ratio") is not None:
        out["Fiscal Ratio"] = f"{m['fiscal_ratio']:.2f}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true",
                    help="Skip live location-dimension fetches (health/socio/walk → null).")
    ap.add_argument("--reuse-location", action="store_true",
                    help="Reuse the health/socioeconomic/walkability scores already in "
                         "sample-parcels.json (offline) and only re-derive the construction "
                         "dimensions — for refreshing scores without API keys.")
    args = ap.parse_args()

    # Optionally reuse the previously fetched location scores (offline refresh).
    reuse_loc, prev_meta = {}, {}
    if args.reuse_location:
        if not OUT_FILE.exists():
            raise SystemExit(
                f"--reuse-location requires an existing {OUT_FILE.relative_to(REPO_ROOT)} "
                "to read location scores from; run once without --reuse-location "
                "(a live fetch) first."
            )
        prev = json.loads(OUT_FILE.read_text())
        prev_meta = prev.get("meta", {})
        for p in prev.get("parcels", []):
            s = p.get("scores", {})
            reuse_loc[p["name"]] = {k: s.get(k) for k in ("health", "socioeconomic", "walkability")}

    parcels = []
    tract = None
    notes = {}
    for name, preset, description in WEBSITE_PRESETS:
        cfg = _cfg_for(preset)
        # Gate the live seismic/tornado lookups in simulate() (offline by default).
        cfg["allow_network"] = not args.no_fetch
        r = simulate(cfg)
        label = simulate_all_dimensions(
            cfg, r["total_score"],
            allow_network=not (args.no_fetch or args.reuse_location),
            overrides=reuse_loc.get(name),
        )
        tract = tract or label.get("census_tract")
        notes = label.get("location_notes", notes)
        scores = {d["key"]: d["score"] for d in label["dimensions"]}
        parcels.append({
            "name": name,
            "description": description,
            "metrics": _metrics(r, label),
            "scores": scores,
            "composite": label["composite_score"],
        })
        comp = label["composite_score"]
        print(f"  {name:<16} composite={comp}  "
              f"({label['n_scored']}/8 scored)")

    # When reusing, carry the original tract/notes from the prior fetch.
    if args.reuse_location:
        tract = prev_meta.get("census_tract", tract)
        notes = prev_meta.get("location_notes", notes)

    note = (
        "Generated by the CLI simulator (scripts/generate_label_data.py) for each "
        "construction preset at the same Memphis location. The five construction-driven "
        "dimensions (resilience, energy, durability, environmental, infrastructure) are "
        "modeled from the house config. Location-driven dimensions are fetched live: "
        f"Health from CDC PLACES (census tract {tract}); Socioeconomic (Census ACS) and "
        "Walkability (Walk Score) require API keys and are null/excluded from the composite "
        "when unavailable rather than fabricated. Location dimensions are identical across "
        "presets by design. Local (percentile) grades require the full county dataset."
    )

    data = {
        "meta": {
            "location": {"label": "Cooper-Young, Memphis, TN", "lat": LAT, "lon": LON},
            "gradeThresholds": {"A": 80, "B": 60, "C": 40, "D": 20, "F": 0},
            "census_tract": tract,
            "location_notes": notes,
            "note": note,
        },
        "dimensions": [{"key": k, "label": lbl} for k, lbl in DIMENSIONS],
        "parcels": parcels,
    }

    OUT_FILE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\nWrote {OUT_FILE.relative_to(REPO_ROOT)}  ({len(parcels)} parcels)")


if __name__ == "__main__":
    main()
