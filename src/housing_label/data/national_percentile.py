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
- **Climate, infrastructure**: their breakpoints are anchored to national
  quantiles, so the score already tracks national percentile rank — returned as-is.

All dimensions here are "higher is better", so a higher percentile means a better
home than a larger share of US homes. The construction/walkability references are
*modeled* distributions (documented archetypes / block-group index), so a surfaced
percentile is an honest estimate, versioned by its build.
"""

from __future__ import annotations

import csv
import gzip
import pathlib
from functools import lru_cache

from housing_label.data._util import num as _num

_DIR = pathlib.Path(__file__).resolve().parent
_CURVE_CSV = _DIR / "construction_percentiles.csv"
_WALK_TRACTS = _DIR / "walkability_tracts.csv.gz"

CONSTRUCTION_DIMS = frozenset({"energy", "durability", "environmental", "resilience"})
# Scores that already express national standing (no remapping needed).
IDENTITY_DIMS = frozenset({"health", "socioeconomic", "climate", "infrastructure"})

DATA_VINTAGE = "national percentile vs US homes (modeled reference)"


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
            pairs = sorted((s, p) for s, p in zip(scores, pcts) if s is not None)
            if pairs:
                out[dim] = ([s for s, _ in pairs], [p for _, p in pairs])
    return out


@lru_cache(maxsize=1)
def _walkability_curve() -> tuple[list[float], list[float]] | None:
    """(score_at_each_percentile, percentile) from the household-weighted national
    distribution of the bundled walkability crosswalk."""
    if not _WALK_TRACTS.exists():
        return None
    pairs: list[tuple[float, float]] = []
    with gzip.open(_WALK_TRACTS, "rt", newline="") as f:
        for row in csv.DictReader(f):
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
    s = _clamp(float(score))
    if dimension in CONSTRUCTION_DIMS:
        curve = _construction_curves().get(dimension)
        return round(_interp(s, curve[0], curve[1])) if curve else None
    if dimension == "walkability":
        curve = _walkability_curve()
        return round(_interp(s, curve[0], curve[1])) if curve else None
    if dimension in IDENTITY_DIMS:
        return round(s)
    return None
