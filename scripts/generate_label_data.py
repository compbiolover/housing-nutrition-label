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


def _cost(result_r: dict, label: dict) -> dict:
    """Numeric dollar flows the lifetime-cost strip discounts (see
    research/lifetime-cost-research.md). These are the annual $ figures behind
    the display strings in ``_metrics`` — surfaced as raw numbers so the
    frontend never has to parse formatted strings. Only the two dollar-defensible
    flows (energy + expected annual loss) are emitted; property tax / maintenance
    are intentionally left out of the shipped core."""
    m = label["metrics"]
    out = {"expectedAnnualLoss": round(result_r["total_loss"])}
    if m.get("est_monthly_energy_cost") is not None:
        # energy.py surfaces monthly $; the annual $ is monthly × 12.
        out["annualEnergyCost"] = round(m["est_monthly_energy_cost"] * 12)
    return out


# Per-dimension provenance/pedigree confidence tiers (see
# research/uncertainty-confidence-research.md §3). This is the data-quality
# confidence — source, geographic resolution, completeness — kept SEPARATE from
# the score, never a statistical confidence interval. The rubric there scores
# four criteria; this first version encodes its §3.3 outcome directly from the
# provenance the label already exposes (scored vs. null/placeholder, and the
# dimensions carrying a documented wide/scenario band).
_WIDE_BAND_DIMS = {"environmental", "infrastructure", "climate"}  # → at most Moderate


def _confidence(label: dict, scores: dict) -> dict:
    """Map each dimension to a High / Moderate / Low confidence tier."""
    notes = label.get("location_notes", {})
    tiers = {}
    for key, _lbl in DIMENSIONS:
        score = scores.get(key)
        note = (notes.get(key) or "").lower()
        if score is None or "no " in note and "key" in note:
            # N/A (no API key) or excluded/placeholder → Low.
            tiers[key] = "low"
        elif key in _WIDE_BAND_DIMS:
            # Documented wide band (env embodied leg, infra ±30%) or scenario
            # spread (climate SSPs) → hold at Moderate.
            tiers[key] = "moderate"
        else:
            tiers[key] = "high"
    return tiers


def _bands(label: dict) -> dict:
    """Real score-space intervals that can honestly be drawn as a whisker.
    Currently only Climate Projections (the SSP2-4.5 → SSP5-8.5 scenario band,
    already computed as score_low/score_high and surfaced as a 'Climate band …'
    metric). Infrastructure's ±30% is a *dollar* band, not a score band, so it
    is represented by its Moderate tier — not a whisker — until propagated into
    score space."""
    out = {}
    for k, v in label.get("metrics", {}).items():
        if k.startswith("Climate band") and isinstance(v, str) and "–" in v:
            try:
                lo, hi = (float(x) for x in v.split("–", 1))
                out["climate"] = {"low": min(lo, hi), "high": max(lo, hi)}
            except ValueError:
                pass
    return out


# Plain-language provenance shown on hover of a dimension's confidence dot.
CONFIDENCE_NOTES = {
    "resilience": "Parcel-level flood zone + seismic; wildfire resolves at county level here; BRM feature bonuses are v1 estimates.",
    "energy": "Modeled EUI from ResStock archetypes × vintage × construction — no metered data.",
    "durability": "Component-lifespan model from CAMA building attributes + assessor condition.",
    "environmental": "Operational leg strong (metered-equivalent × eGRID2022); embodied-carbon leg flagged low confidence (order-of-magnitude).",
    "infrastructure": "Density cost model calibrated to county spending; documented ±30% on absolute dollars.",
    "health": "CDC PLACES model-based estimates.",
    "socioeconomic": "Census ACS income/poverty/education (uniform placeholder + excluded from composite when no API key).",
    "walkability": "Walk Score API (unavailable without an API key).",
    "climate": "CMIP6-LOCA2 tract-level projection; scenario band SSP2-4.5 → SSP5-8.5 (mid-century).",
}
CONFIDENCE_LEGEND = (
    "Confidence reflects data quality (source, resolution, completeness) — not "
    "whether the score is good. A parcel can be confidently an F."
)


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

    # In --reuse-location mode the per-dimension fetches are skipped (scores come
    # from the prior file), but we still resolve the location *online* once — a
    # keyless Census geocode — so the construction dimensions use the location's
    # real IECC climate zone and eGRID subregion grid factor instead of the
    # offline pilot/US-average fallback. --no-fetch keeps it fully offline.
    shared_location = None
    if args.reuse_location and not args.no_fetch:
        from housing_label.simulate.location import resolve_location
        try:
            shared_location = resolve_location(lat=LAT, lon=LON, allow_network=True)
            if shared_location is not None and shared_location.egrid_subregion:
                print(f"  location: {shared_location.label}  "
                      f"(grid {shared_location.egrid_factor} kgCO2e/kWh, "
                      f"{shared_location.egrid_subregion})")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: online location resolve failed ({exc}); "
                  "construction dims use offline fallbacks.")

    for name, preset, description in WEBSITE_PRESETS:
        cfg = _cfg_for(preset)
        # Gate the live seismic/tornado lookups in simulate() (offline by default).
        cfg["allow_network"] = not args.no_fetch
        r = simulate(cfg)
        label = simulate_all_dimensions(
            cfg, r["total_score"],
            location=shared_location,
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
            "cost": _cost(r, label),
            "confidence": _confidence(label, scores),
            "bands": _bands(label),
            "scores": scores,
            "composite": label["composite_score"],
        })
        comp = label["composite_score"]
        print(f"  {name:<16} composite={comp}  "
              f"({label['n_scored']}/{len(label['dimensions'])} scored)")

    # When reusing, carry the original tract/notes from the prior fetch.
    if args.reuse_location:
        tract = prev_meta.get("census_tract", tract)
        notes = prev_meta.get("location_notes", notes)

    note = (
        "Generated by the CLI simulator (scripts/generate_label_data.py) for each "
        "construction preset at the same Memphis location. The five construction-driven "
        "dimensions (resilience, energy, durability, environmental, infrastructure) are "
        "modeled from the house config. Location-driven dimensions: "
        f"Health from CDC PLACES (census tract {tract}); Socioeconomic (Census ACS) and "
        "Walkability (Walk Score) are fetched live and require API keys (null/excluded from "
        "the composite when unavailable rather than fabricated); Climate Projections is a "
        "sub-county downscaled hazard score sampled at this tract (USGS CMIP6-LOCA2 heat/"
        "precip/drought, SSP2-4.5 to SSP5-8.5 mid-century, plus an Argonne ClimRR 12 km "
        "Fire Weather Index fire leg). Location dimensions are identical across presets by "
        "design. Local (percentile) grades require the full county dataset."
    )

    data = {
        "meta": {
            "location": {"label": "Cooper-Young, Memphis, TN", "lat": LAT, "lon": LON},
            "gradeThresholds": {"A": 80, "B": 60, "C": 40, "D": 20, "F": 0},
            "census_tract": tract,
            "location_notes": notes,
            "confidenceNotes": CONFIDENCE_NOTES,
            "confidenceLegend": CONFIDENCE_LEGEND,
            "note": note,
        },
        "dimensions": [{"key": k, "label": lbl} for k, lbl in DIMENSIONS],
        "parcels": parcels,
    }

    OUT_FILE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\nWrote {OUT_FILE.relative_to(REPO_ROOT)}  ({len(parcels)} parcels)")


if __name__ == "__main__":
    main()
