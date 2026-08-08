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
    "resilience": "Parcel-level flood zone + seismic; wildfire resolves at county level here; every construction and above-code feature credit is calibrated to published FEMA, IBHS, NFPA, NIST or PEER-CEA data, and features with no measured effect on these four perils carry no credit rather than an estimated one.",
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
    "water": "County share of community-water-system population with a recent health-based drinking-water violation (EPA SDWIS), scored as a national percentile (bundled, keyless).",
}
CONFIDENCE_LEGEND = (
    "Confidence reflects data quality (source, resolution, completeness) — not "
    "whether the score is good. A parcel can be confidently an F."
)


# Bases whose points are not measurements of the world at each point in time, and
# so can never carry the top tier however good the underlying data is. A projection
# is a model of a future that has not happened; an aging curve is arithmetic on a
# component basket that nobody looked at. Both are legitimate and both are capped.
_UNMEASURED_BASES = frozenset({"projection", "aging"})


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


def confidence_for_trajectory(label: dict, series: dict) -> dict:
    """Map each dimension WITH a series to a confidence tier for that series.

    Kept here rather than in ``data/vintages.py`` so there is still exactly one
    rubric in the codebase — the reason this module exists.

    A trajectory is never MORE trustworthy than the snapshot it is drawn from, so
    this starts at the dimension's snapshot tier and only ever caps it downward, on
    two grounds:

    * the basis is not a measurement at each point (projection / aging), or
    * the series spans a geography revision, so part of any movement is the boundary
      moving rather than the place changing (``SeriesSpec.boundary_basis`` records
      how the join was made).

    Both are pedigree judgements about fitness for use, exactly like the snapshot
    tiers — not statistical statements, and never drawn as an interval.
    """
    order = ("low", "moderate", "high")
    snapshot = confidence_for_label(label)
    out = {}
    for key, spec in series.items():
        tier = snapshot.get(key, "low")
        if getattr(spec, "basis", None) in _UNMEASURED_BASES:
            tier = "moderate" if tier == "high" else tier
        if getattr(spec, "boundary_basis", None):
            tier = order[max(0, order.index(tier) - 1)]
        out[key] = tier
    return out


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
