"""Map a dimension's 0-100 score to a NATIONAL percentile ("vs US homes").

Different dimensions reach national comparability differently, so this module
routes each to the right reference:

- **Construction-driven** (energy, durability, environmental, resilience): the
  score is an absolute 0-100 with no built-in percentile meaning, so it is mapped
  through a bundled national distribution — ``construction_percentiles.csv``, the
  weighted score-at-each-percentile curve from
  ``scripts/calibrate_construction_percentiles.py`` (a household-weighted panel of
  US counties x building archetypes scored with the real models).
- **Walkability**: the EPA NWI score isn't a percentile (its national mean is
  ~45), so it is mapped through the household-weighted distribution of the bundled
  walkability crosswalk.
- **Health, socioeconomic**: the score already IS a national percentile (Tier 1),
  so it is returned as-is.
- **Climate, infrastructure, air quality, solar, water**: their breakpoints are
  anchored to national quantiles, so the score already tracks national percentile
  rank — returned as-is.

  How well that stands in for "vs US homes" depends on the geography the quantiles
  were taken over, and it is not uniform:

  * **Solar** is household-weighted (``scripts/calibrate_solar_percentiles.py``).
  * **Climate** is household-weighted at the TRACT, which is also the geography it
    resolves at (``scripts/calibrate_climate_breakpoints.py``).
  * **Water** is population-weighted by each county's community-water-system
    population, inside a hurdle model that scores the spotless class separately
    (see ``data/water.py``).
  * **Infrastructure** is population-weighted over the (county × archetype)
    roster, by ``pop × archetype share × tenure share × utility share``
    (``scripts/calibrate_infra_breakpoints.py``).
  * **Air quality, noise** are the remaining approximations: anchored to
    UNWEIGHTED TRACT quantiles. Census tracts target ~4,000 residents, so an
    unweighted tract distribution is already close to a household-weighted one,
    and the gap is mild — unlike a county distribution, where populations span
    five orders of magnitude.

All dimensions here are "higher is better", so a higher percentile means a better
home than a larger share of US homes. The construction/walkability references are
*modeled* distributions (documented archetypes / block-group index), so a surfaced
percentile is an honest estimate, versioned by its build.
"""

from __future__ import annotations

import csv
import logging
import math
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

log = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).resolve().parent
_CURVE_CSV = _DIR / "construction_percentiles.csv"

CONSTRUCTION_DIMS = frozenset({"energy", "durability", "environmental", "resilience"})
# Scores that already express national standing (no remapping needed), by two
# different routes:
#
#   • Health and Socioeconomic ARE national percentiles as published (Tier 1).
#   • Air Quality, Noise, Solar, Climate, Water and Infrastructure have breakpoints
#     anchored to national quantiles, so the score tracks a percentile rank:
#       - unweighted tract          data/air_quality.py, data/noise.py
#       - household-weighted county data/solar.py
#       - household-weighted tract  data/climate_projections.py
#       - CWS-pop-weighted county   data/water.py
#       - pop-weighted roster       scripts/calibrate_infra_breakpoints.py
#
# Walkability takes a third route (its own remapping curve), so it is in neither
# set. The module docstring explains how closely each stands in for "vs US homes";
# they are not equally good.
#
# tests/test_national_percentile.py asserts these two sets plus walkability cover
# the dimension roster exactly — a dimension in none of them falls off the end of
# national_percentile() and returns None, losing its percentile silently.
IDENTITY_DIMS = frozenset({"health", "air_quality", "noise", "socioeconomic", "climate", "infrastructure", "solar", "water"})

DATA_VINTAGE = "national percentile vs US homes (modeled reference)"

# ── Site & environment sub-score → national percentile ───────────────────────
# The Location axis is the mean of up to eight dimension percentiles, and a mean of
# percentiles will not span 0-100 however good or bad the place is: the SD of a
# mean of k of them is roughly 29/sqrt(k), about 10 at k=8, so it piles up near 50.
#
# Measured over 6,000 household-weighted census tracts scored with a fixed
# reference building (scripts/calibrate_location_percentiles.py), the raw mean runs
# 36.6 at the 1st percentile to 73.9 at the 99th. Against the absolute grade
# thresholds that is not merely compressed — it makes two grades UNREACHABLE. No
# US household could score an A (>= 80) on its location, and none could score an F
# (< 20). The letter could only ever be D, C or B, which is not a grading scale so
# much as a three-position switch.
#
# So the axis is ranked against that distribution instead, exactly as Solar (#257)
# and Climate (#258) were. A location score of 80 now means "this site beats 80% of
# US homes' locations" — the claim this module's first line already makes for
# everything else.
LOCATION_XS = [36.6, 41.0, 43.4, 48.6, 54.2, 60.1, 65.1, 68.6, 73.9]
LOCATION_YS = [1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0, 99.0]


# ── Building sub-score → national percentile ─────────────────────────────────
# Symmetric with LOCATION_XS above, and calibrated the same way — over the
# household-weighted (county x archetype) panel in
# scripts/calibrate_building_percentiles.py, which is the same stock the
# per-dimension construction curves are built from.
#
# The building axis was NOT obviously broken before this: unlike the site axis it
# already spread across the whole A-F range, so nothing looked wrong. But
# "spreads well" is not the claim the label makes. Two headline grades that look
# alike and answer different questions is the defect being fixed — a reader
# comparing "Building B / Site C" has no way to know only one of them was a rank
# against US homes.
# 32,000 simulated homes (every US county x the ACS-weighted archetype grid),
# covering 130.5M households. The raw mean runs 8.2 at p1 to 94.2 at p99 — it
# genuinely uses the scale, which is why nothing looked wrong. What it is not is a
# percentile: a raw 53.8 is the MEDIAN US home and graded C, while a raw 34.5 is
# the 25th and graded D. Ranking keeps the letters honest rather than moving them
# far.
BUILDING_XS = [8.2, 11.8, 17.0, 34.5, 53.8, 71.8, 83.5, 89.8, 94.2]
BUILDING_YS = [1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0, 99.0]


def building_percentile(raw_mean: float | None) -> float | None:
    """Rank a raw Building sub-score against US homes' construction.

    Flat outside the anchors, so a home beyond the sampled range clamps to 1 or 99
    rather than extrapolating a claim the panel cannot support. Falls back to the
    raw mean if the curve is ever empty, so the axis degrades to its previous
    behaviour rather than to None.
    """
    if raw_mean is None:
        return None
    if not BUILDING_XS:
        return round(float(raw_mean), 1)
    return round(_interp(_clamp(float(raw_mean)), BUILDING_XS, BUILDING_YS), 1)


def location_percentile(raw_mean: float | None) -> float | None:
    """Rank a raw Location sub-score against US households' locations.

    ``raw_mean`` is the mean of the member dimensions' national percentiles; the
    return is where that sits nationally. Flat outside the anchors, so a site
    beyond the sampled range clamps to 1 or 99 rather than extrapolating a claim
    the sample cannot support.
    """
    if raw_mean is None:
        return None
    return round(_interp(_clamp(float(raw_mean)), LOCATION_XS, LOCATION_YS), 1)


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 100.0 if x > 100 else x


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolation with flat extrapolation (xs non-decreasing)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


@lru_cache(maxsize=1)
def _construction_curves() -> dict[str, tuple[list[float], list[float]]]:
    """dimension -> (score_at_each_percentile, percentile) for score→percentile interp."""
    out: dict[str, tuple[list[float], list[float]]] = {}
    if not _CURVE_CSV.exists():
        return out
    with _CURVE_CSV.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return out
        pcts = [float(h[1:]) for h in header[1:]]   # "p10" -> 10.0
        for row in reader:
            if not row:
                continue
            dim = row[0]
            scores = [_num(v) for v in row[1:]]
            if len(scores) != len(pcts):
                # zip would truncate to the shorter side and build a curve out of
                # the percentiles that happened to line up — a silently wrong
                # percentile for every score on this dimension. Skip the row; the
                # dimension then falls back to its raw score, which is visible.
                log.warning("%s: %s has %d scores for %d percentile columns; skipping",
                            _CURVE_CSV.name, dim, len(scores), len(pcts))
                continue
            pairs = sorted((s, p) for s, p in zip(scores, pcts) if s is not None)
            if pairs:
                out[dim] = ([s for s, _ in pairs], [p for _, p in pairs])
    return out


@lru_cache(maxsize=1)
def _walkability_curve() -> tuple[list[float], list[float]] | None:
    """(score_at_each_percentile, percentile) from the household-weighted national
    distribution of the bundled walkability crosswalk.

    Reuses ``data/walkability``'s already-cached tract table rather than re-reading
    and re-decompressing the same ``walkability_tracts.csv.gz`` (avoids duplicate
    cold-start I/O)."""
    from housing_label.data import walkability as _walk
    table = _walk._tract_table()
    if not table:
        return None
    pairs: list[tuple[float, float]] = []
    for row in table.values():
        s = _num(row.get("walkability_score"))
        w = _num(row.get("households"))
        if s is not None and w and w > 0:
            pairs.append((s, w))
    if not pairs:
        return None
    pairs.sort()
    total = sum(w for _, w in pairs)
    anchors = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99]
    xs: list[float] = []
    ys: list[float] = []
    cum = 0.0
    targets = {p: total * p / 100.0 for p in anchors}
    remaining = sorted(anchors)
    for score, w in pairs:
        cum += w
        while remaining and cum >= targets[remaining[0]]:
            xs.append(score)
            ys.append(float(remaining.pop(0)))
    while remaining:                       # top tail
        xs.append(pairs[-1][0])
        ys.append(float(remaining.pop(0)))
    # de-duplicate non-increasing xs so _interp stays monotone
    mono_x, mono_y = [xs[0]], [ys[0]]
    for x, y in zip(xs[1:], ys[1:]):
        if x >= mono_x[-1]:
            mono_x.append(x)
            mono_y.append(y)
        else:
            mono_y[-1] = y
    return mono_x, mono_y


def national_percentile(dimension: str, score) -> int | None:
    """Return the national percentile (0-100, higher = better than more US homes)
    for a dimension's 0-100 ``score``, or None when it can't be resolved."""
    if score is None:
        return None
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(s):          # NaN / inf (e.g. from pandas) → unscored
        return None
    s = _clamp(s)
    if dimension in CONSTRUCTION_DIMS:
        curve = _construction_curves().get(dimension)
        return round(_interp(s, curve[0], curve[1])) if curve else None
    if dimension == "walkability":
        curve = _walkability_curve()
        return round(_interp(s, curve[0], curve[1])) if curve else None
    if dimension in IDENTITY_DIMS:
        return round(s)
    return None
