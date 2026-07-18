"""Provenance-driven per-dimension confidence tiers and honest score-space bands.

This is the single source of truth for the label's *data-quality* confidence
channel — a pedigree tier (High / Moderate / Low) kept deliberately separate
from the score, plus the only interval we draw as a whisker (the climate SSP
scenario band). Consumed by the live API payload (`housing_label.simulate.house.label_payload`)
so every page — scored by the same API and rendered by `docs/label-core.js` —
applies exactly one rubric.

Methodology + citations: research/uncertainty-confidence-research.md.

The tier is a NUSAP/pedigree judgement of *fitness for use* (source, geographic
resolution, completeness) — NOT a statistical confidence interval, and never
drawn as one. "Confident" must never read as "good": a parcel can be
confidently an F.
"""

# Dimensions held at Moderate rather than High because a leg is modeled with a
# documented wide/scenario band, even when fully scored: environmental (the
# embodied-carbon leg is now a bottom-up EPD × real-geometry model — much stronger
# than the old order-of-magnitude estimate — but still modeled, and the water leg
# rides a flat national embedded-energy constant); infrastructure (±30% on dollars);
# climate (SSP scenario spread).
WIDE_BAND_DIMS = frozenset({"environmental", "infrastructure", "climate"})

# Plain-language provenance shown on hover of a dimension's confidence dot.
CONFIDENCE_NOTES = {
    "resilience": "Parcel-level flood zone + seismic; wildfire resolves at county level here; BRM feature bonuses are v1 estimates.",
    "energy": "Base EUI from NREL ResStock 2024 building-type×zone×vintage medians × ResStock-derived foundation/HVAC (and size/wall) within-cell factors — no metered data.",
    "durability": "Component-lifespan model from CAMA building attributes + assessor condition.",
    "environmental": "Operational leg strong (consumed kWh × eGRID2023 Rev 2 average, with solar/efficiency-avoided kWh credited at the NREL Cambium 2023 LRMER marginal rate — CONUS only, average elsewhere); embodied-carbon leg is bottom-up from industry-average EPD factors × the home's real footprint (USA Structures) where available — modeled, not metered; water leg uses a national embedded-energy constant.",
    "infrastructure": "Density cost model calibrated to county spending; documented ±30% on absolute dollars.",
    "health": "CDC PLACES model-based tract estimates, scored as a national percentile (bundled, keyless).",
    "air_quality": "Tract-level ambient PM2.5 + ozone (CDC Tracking downscaler model) and county EPA radon zone, scored as a national percentile (bundled, keyless).",
    "noise": "Tract-level transportation-noise exposure (US DOT BTS National Transportation Noise Map — aviation + road + rail), scored as a national percentile (bundled, keyless).",
    "socioeconomic": "Census ACS income/poverty/housing-cost-burden, scored as a national percentile (bundled offline — no API key needed).",
    "walkability": "EPA National Walkability Index (block-group, aggregated to tract; national, public-domain).",
    "climate": "CMIP6-LOCA2 tract-level projection; scenario band SSP2-4.5 → SSP5-8.5 (mid-century).",
    "solar": "County rooftop specific yield modeled by PVGIS on the NSRDB satellite record, scored as a national percentile (bundled, keyless).",
}
CONFIDENCE_LEGEND = (
    "Confidence reflects data quality (source, resolution, completeness) — not "
    "whether the score is good. A parcel can be confidently an F."
)


def _is_unavailable(note: str) -> bool:
    """True when a location note signals a missing-key / unavailable fetch
    (e.g. 'no CENSUS_API_KEY')."""
    note = (note or "").lower()
    return "no " in note and "key" in note


def confidence_for_label(label: dict) -> dict:
    """Map each dimension key to a High / Moderate / Low confidence tier.

    Reads only provenance the pipeline already produces: the per-dimension
    score (null → unscored), and ``location_notes`` (measured vs. unavailable).
    """
    notes = label.get("location_notes", {}) or {}
    tiers = {}
    for d in label.get("dimensions", []):
        key = d.get("key")
        if key is None:
            continue
        score = d.get("score")
        if score is None or _is_unavailable(notes.get(key)):
            tiers[key] = "low"          # unscored / N/A / placeholder
        elif key in WIDE_BAND_DIMS:
            tiers[key] = "moderate"     # documented wide or scenario band
        else:
            tiers[key] = "high"
    return tiers


def bands_for_label(label: dict) -> dict:
    """Real score-space intervals that can honestly be drawn as a whisker.

    Currently only Climate Projections' SSP2-4.5 → SSP5-8.5 band, already
    computed as score_low/score_high and surfaced as a 'Climate band …' metric
    string like '49.6–47.0'. Ordered by magnitude → {'low': 47.0, 'high': 49.6}.
    Infrastructure's ±30% is a *dollar* band (not a score band) and is
    intentionally represented by its Moderate tier, not a whisker.
    """
    out = {}
    for key, val in (label.get("metrics") or {}).items():
        if key.startswith("Climate band") and isinstance(val, str) and "–" in val:
            try:
                lo, hi = (float(x) for x in val.split("–", 1))
            except ValueError:
                continue
            out["climate"] = {"low": min(lo, hi), "high": max(lo, hi)}
    return out
