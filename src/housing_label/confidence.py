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


# Construction provenance and what it measurably costs.
#
# Until the accuracy harness existed, every scored dimension carried the same tier
# whatever its construction inputs were made of: a durability grade computed from a
# census-tract median year built was labelled exactly as confidently as one computed
# from the county's record of the building. That was an editorial judgement, and the
# measurement says it was wrong.
#
# From research/accuracy/results.json (217 Cook County and 218 Washington, DC
# addresses, each scored from the address alone and compared against that
# jurisdiction's own assessor record) — how often the letter a reader sees differs
# from the letter the true attributes produce:
#
#                        Cook County            Washington, DC
#                    assumed   observed       assumed   observed
#     durability       37.3%      6.9%          50.5%      5.0%
#     energy           37.3%      7.4%          32.6%      4.1%
#     environmental    26.7%      5.5%          23.4%      3.2%
#     resilience        2.8%      0.5%           8.7%      0.5%
#
# So durability and energy are wrong better than one time in three when the
# construction profile is a stand-in. That is not a High-confidence number by any
# reading of this module's own rubric, and it is now capped.
#
# Resilience is deliberately NOT capped, and this is the judgement most worth
# revisiting. It moved on 2.8% of Cook addresses and 8.7% of DC ones — a third of a
# figure that was quoted alone when only Cook had been measured, and a reminder that
# one city is not a constant. It is still four to six times below durability's
# 37-50% (not the order of magnitude an earlier draft of this comment claimed — the
# ratio is 4.3x against Cook's durability and 5.8x against DC's): the flood zone,
# seismic band and wildfire class do the work there, and the vintage reaches the
# letter only at the margin.
#
# So the exemption rests on a judgement about magnitude, not a bright line. Capping
# resilience would tell readers a genuinely strong signal is weak; leaving it
# uncapped accepts that roughly one DC label in eleven carries a resilience letter a
# real year built would move. If a third jurisdiction lands nearer durability than
# this, the exemption should go rather than be defended.
#
# The fields listed per dimension are its PRIMARY construction drivers, not every
# input it touches: the ones whose provenance the measurement above actually varied.
_PROVENANCE_SENSITIVE = {
    "durability": ("year_built", "condition"),
    "energy": ("year_built", "sqft", "foundation"),
    "environmental": ("sqft", "construction"),
}

# `assumed` is the status the pipeline gives an area typical — a value that
# describes the neighbourhood rather than the building. `estimated` (NSI's record
# of this structure) and `observed` (a county's) are both about the building
# itself, and `confirmed` is the reader's own answer.
_STANDIN_STATUS = "assumed"


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
    building = label.get("building") or {}
    tiers = {}
    for d in label.get("dimensions", []):
        key = d.get("key")
        if key is None:
            continue
        reason = _cap_reason(key, d.get("score"), notes.get(key), building)
        tiers[key] = _TIER_FOR_REASON.get(reason, "high")
    return tiers


# Why a dimension cannot carry the top tier. Ordered: the first that applies is
# the one that actually caps it, and the later ones would be redundant.
_TIER_FOR_REASON = {
    "unscored": "low",        # unscored / N/A / placeholder
    "wide_band": "moderate",  # documented wide or scenario band
    "standin": "moderate",    # measured: the letter is often wrong here
}


def _cap_reason(key: str, score, note, building: dict) -> str | None:
    """Which of the three caps applies to this dimension, or None for High.

    One function rather than a branch in the tier and a separate condition in the
    note, because the two have to agree about *why*. They did not: `environmental`
    is in both WIDE_BAND_DIMS and _PROVENANCE_SENSITIVE, so the tier capped it for
    its band while the note told the reader it was capped for a stand-in and that
    correcting the building details would resolve it. It would not — environmental
    is Moderate whatever the reader enters. A hover note that hands someone an
    action that cannot work is worse than the uncaptioned dot it replaced.
    """
    if score is None or _is_unavailable(note):
        return "unscored"
    if key in WIDE_BAND_DIMS:
        return "wide_band"
    if _rests_on_a_standin(key, building):
        return "standin"
    return None


def _rests_on_a_standin(key: str, building: dict) -> bool:
    """Whether this dimension's grade is being computed from an area typical.

    True only for the dimensions the accuracy harness measured as sensitive, and
    only when a PRIMARY driver carries the `assumed` status. A field the pipeline
    could not produce at all is not treated as a stand-in here: it never reached
    the model, so it is not a wrong input — the dimension's own score being None
    is what reports that, one branch up.
    """
    drivers = _PROVENANCE_SENSITIVE.get(key)
    if not drivers:
        return False
    for field in drivers:
        info = building.get(field)
        if isinstance(info, dict) and info.get("status") == _STANDIN_STATUS:
            return True
    return False


# Appended to a dimension the STAND-IN capped. The dot changing colour without a
# reason is worse than not capping at all: the reader sees a downgrade and cannot
# tell whether the data source is weak in general or weak for THEIR address, and
# the second is fixable by them in the panel directly above.
#
# The rate below spans the dimensions this note can reach — durability and energy,
# the two _PROVENANCE_SENSITIVE dimensions that are not already capped for their
# band. Measured on stand-in inputs: durability 37.3% (Cook) and 50.5% (DC),
# energy 37.3% and 32.6%. So a third to a half is the real envelope, and it must
# be re-read against research/accuracy/results.json when a jurisdiction is added.
# Environmental's 26.7%/23.4% is deliberately NOT in that range: this note never
# reaches it, because its band caps it first.
STANDIN_NOTE = (" Confidence is held at Moderate here because this dimension is "
                "being computed from a neighbourhood typical rather than a record "
                "of this building. Measured against assessor records in the two "
                "places that have been checked, the letter differs between about "
                "a third and about half the time on such inputs. Correcting the "
                "building details above resolves it.")


def confidence_notes_for_label(label: dict) -> dict:
    """The hover notes, with the stand-in caveat added where the cap applied.

    Separate from CONFIDENCE_NOTES so the constant stays a plain description of
    each dimension's sources, and the per-address part is added per address.
    """
    building = label.get("building") or {}
    notes = label.get("location_notes", {}) or {}
    scores = {d.get("key"): d.get("score") for d in label.get("dimensions", [])}
    out = dict(CONFIDENCE_NOTES)
    for key in _PROVENANCE_SENSITIVE:
        # Only where the stand-in is what actually capped it. A dimension capped
        # for its band, or one with no score at all, is Moderate or Low for a
        # different reason and correcting the building details will not move it.
        if key in out and _cap_reason(key, scores.get(key), notes.get(key),
                                      building) == "standin":
            out[key] = out[key] + STANDIN_NOTE
    return out


def year_built_display(building: dict | None) -> str | None:
    """The year built as a reader should see it, or None when there is none.

    The web page carries a sentence explaining that a year built can be a
    neighbourhood typical rather than this home's, and shows the range it was drawn
    from. Every other surface — the terminal card, the printable SVG, the shared
    card — printed the same number bare, which reads as a fact about the building.
    That is the one field in this codebase whose whole difficulty is that it is
    usually NOT a fact about the building, so the surfaces are brought level here
    rather than each inventing its own wording.

    Lives in this module because it is the same question the tiers answer: what may
    honestly be claimed about where a value came from.
    """
    info = (building or {}).get("year_built")
    if not isinstance(info, dict) or info.get("value") is None:
        return None
    year = info["value"]
    if info.get("status") != _STANDIN_STATUS:
        return str(year)                  # about this building — say it plainly
    lo_hi = info.get("typical_range") or []
    if len(lo_hi) == 2 and all(x is not None for x in lo_hi):
        return f"{lo_hi[0]}\u2013{lo_hi[1]} (area typical)"
    return f"~{year} (area typical)"


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
