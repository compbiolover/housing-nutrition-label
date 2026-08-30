"""Which dimensions carry a time series, what kind of time it is, and why the rest don't.

This is the single source of truth for the label's *trajectory* channel — the
answer to "is this place getting better or worse", kept deliberately separate from
the snapshot score the rest of the label is about.

Consumed by ``housing_label.simulate.house.timeline_comparison`` (the ``/timeline``
endpoint) so every surface applies exactly one rubric, the way ``confidence.py``
already does for the data-quality channel.

Three kinds of time, and they are not interchangeable
-----------------------------------------------------
The roadmap item reads as one feature but is three, and a reader who cannot tell
which one they are looking at has been misled rather than informed. So the kind is
a FIELD (``SeriesSpec.basis``), never a caption:

``observed``
    The place actually changed and somebody measured it at each point. Air Quality
    (CDC's county PM2.5/ozone series) is the archetype.
``projection``
    A model says where the place is heading. Climate Projections is the only one
    today. Note that a projection series can still OPEN on a measured point — the
    CMIP6-LOCA2 ``hist`` band is a real 1991-2020 climatology — which is why
    ``PointSpec.kind`` is tracked per point and not inherited from the series.
``aging``
    Nothing was measured and nothing was projected: the number moves because the
    building got older and a component-lifespan model says what that does.
    Durability. This is the series a reader will over-read, because it sits beside
    the other two and looks identical.

The fixed yardstick
-------------------
Every point on every series is scored through TODAY's breakpoints and TODAY's
percentile curves. ``data/national_percentile.py`` is not consulted per vintage and
is not recalibrated.

The alternative — re-deriving the national distribution at each vintage — answers
"how did this place RANK back then", and it erases the most important true fact in
the data: a nationwide improvement (US PM2.5 fell by roughly a third between 2001
and 2022) would render as a flat line at every address in the country, because
everyone moved together. It would also repeat a defect this codebase has fixed
twice already — see the ``_sub()`` docstring in ``simulate/dimensions.py`` and the
``BUILDING_XS`` note in ``data/national_percentile.py``, both of which exist because
two numbers that look alike and answer different questions is a defect.

A moving-yardstick reading is admissible later as an explicitly-labelled SECOND
series. It is never a replacement.

Percentiles do not travel
-------------------------
A dimension's national percentile is only meaningful at the vintage its reference
distribution was calibrated on. Climate's breakpoints, for instance, are
household-weighted tract quantiles taken under SSP2-4.5 MID-CENTURY, so running the
1991-2020 band through ``national_percentile()`` yields "this place's recent-past
climate beats N% of US homes' PROJECTED climate" — well-defined and useless.
``PointSpec.percentile_ok`` marks the one point per series where the percentile may
be surfaced; everywhere else the trajectory carries a score and no rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The three kinds of time. See the module docstring — these are not interchangeable
# and the distinction is the feature, not bookkeeping.
BASES = frozenset({"observed", "projection", "aging"})

# What an individual point IS, which can differ from the series it belongs to: a
# projection series opens on a measured point.
KINDS = frozenset({"observed", "projected", "modeled"})

TRAJECTORY_LEGEND = (
    "Every point is scored on today's scale, so a change is a change in the place "
    "— not in how it ranks against a moving national average. Percentiles are only "
    "shown at the point they were calibrated for."
)


@dataclass(frozen=True)
class PointSpec:
    """One point on a series.

    ``t`` is deliberately a string rather than an int: several of these are WINDOWS,
    not years (the climate bands are 30-year climatologies, ACS is a 5-year rolling
    estimate), and rendering "1991-2020" as 1991 would overstate the precision by
    three decades.
    """

    t: str                       # "1991-2020", "2001", "2040-2069"
    label: str                   # plain-language, shown to a reader
    kind: str                    # observed | projected | modeled
    percentile_ok: bool = False  # may national_percentile be surfaced at this point?


@dataclass(frozen=True)
class SeriesSpec:
    """How one dimension moves through time."""

    basis: str                        # observed | projection | aging
    points: tuple[PointSpec, ...]     # ordered, oldest → newest
    source: str                       # provenance sentence, shown to a reader
    percentile_basis: str | None = None   # what the calibration vintage actually is
    boundary_basis: str | None = None     # how geographies were joined across time
    caveat: str | None = None             # the thing a reader would otherwise over-read
    legs: tuple[str, ...] = field(default_factory=tuple)   # sub-legs that actually move


# ── The registry ─────────────────────────────────────────────────────────────
# A dimension appears in exactly one of TRAJECTORY or POINT_IN_TIME. Nothing may be
# in both and nothing may be in neither — tests/test_trajectory.py pins that against
# the DIMENSIONS roster, mirroring the coverage assertion in
# tests/test_national_percentile.py. The point of that test is that a new dimension
# is UNMERGEABLE until someone writes the sentence below explaining why it has no
# history, so "we never got round to it" can never render as silence.

TRAJECTORY: dict[str, SeriesSpec] = {
    "climate": SeriesSpec(
        basis="projection",
        points=(
            PointSpec("1991-2020", "Recent past (30-yr normal)", "observed"),
            PointSpec("2040-2069", "Mid-century (SSP2-4.5)", "projected",
                      percentile_ok=True),
        ),
        source="USGS CMIP6-LOCA2 (~6 km, WMMM multi-model mean), sampled at the "
               "tract's internal point; fire weather from Argonne ClimRR.",
        percentile_basis="household-weighted tract quantiles under SSP2-4.5, "
                         "mid-century",
        caveat="Both points are 30-year climatologies, not single years, so this "
               "compares a climate to a climate rather than a year to a year.",
    ),
    "durability": SeriesSpec(
        basis="aging",
        points=(),   # generated per-request from the as-of years (see house.py)
        source="Component-lifespan basket (InterNACHI / NAHB / Fannie Mae service "
               "lives) re-evaluated at each as-of year.",
        caveat="Nothing here was measured or forecast. The score moves because the "
               "building got older and the component model says what that does — it "
               "cannot see a roof you replace next year, and the assessor's "
               "condition rating is held at its present value throughout.",
    ),
}

# Why a dimension has no series. These are SENTENCES, not booleans, mirroring
# `location_notes` in simulate/dimensions.py — this repo's existing convention for
# "here is why this isn't what you'd hope". They are rendered to the reader verbatim,
# so they are written for a reader and not for us.
POINT_IN_TIME: dict[str, str] = {
    "resilience": "Point-in-time only — FEMA's National Risk Index publishes a "
                  "present-day baseline rather than a back series, and a parcel's "
                  "flood zone changes by map revision rather than on a schedule.",
    "energy": "Point-in-time only — the ResStock benchmark is keyed to the home's "
              "construction era, so it moves when the building changes, not when "
              "the calendar does.",
    "environmental": "Point-in-time only — the grid-intensity factors (eGRID, "
                     "Cambium) are bundled at a single vintage, and the "
                     "embodied-carbon leg is fixed at the moment the home was built.",
    "infrastructure": "Point-in-time only — the Census of Governments runs on a "
                      "five-year cycle, so there is no annual spending series to "
                      "track a county's cost-to-serve against.",
    "health": "Point-in-time only — CDC PLACES restates its model with each release, "
              "so successive vintages differ by method as well as by health, and "
              "differencing them would report the method change as a trend.",
    "air_quality": "Point-in-time only for now — CDC's county PM2.5 and ozone series "
                   "runs 2001-2022 and is a genuine back series, but only the "
                   "single-vintage tract layer is bundled today.",
    "noise": "Point-in-time only — the BTS National Transportation Noise Map is "
             "published as a single national snapshot with no comparable earlier "
             "vintage bundled.",
    "socioeconomic": "Point-in-time only — ACS 5-year estimates overlap (2016-2020 "
                     "and 2020-2024 share a year), so consecutive vintages are not "
                     "independent observations and their difference is not a trend.",
    "walkability": "Point-in-time only — EPA's Smart Location Database v3 (2021) is "
                   "the only bundled vintage.",
    "solar": "Point-in-time only — rooftop yield is modeled on a multi-decade "
             "satellite record, so it is a climatological constant rather than a "
             "quantity with a year attached.",
    "water": "Point-in-time only — the bundled figure is already a trailing "
             "five-year violation window, and the per-year detail is collapsed to a "
             "count when the reference table is built.",
}
