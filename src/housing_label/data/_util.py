"""Small shared helpers for the bundled-data lookup modules (``data/*``).

These modules each parse a bundled CSV of raw string cells; ``num`` is the one
coercion they all need and previously each copied verbatim.
"""
from __future__ import annotations

import numpy as np


def num(v) -> float | None:
    """Coerce a CSV cell to ``float``; return ``None`` for blank/None/non-numeric."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def interp(x: float, xs, ys) -> float:
    """Piecewise-linear interpolation of ``(xs, ys)`` at ``x``, flat outside the range.

    ``xs`` must be **strictly** increasing. On a repeated anchor numpy resolves to
    the later ``y`` while the hand-rolled loops this replaced resolved to the
    earlier one, so the two are not interchangeable for a curve that repeats an
    anchor — ``data/national_percentile.py`` keeps its own loop for exactly that
    reason (its durability curve is data-derived and does repeat anchors).

    Returns a plain ``float``: ``np.interp`` hands back ``np.float64``, which
    ``json.dumps`` refuses.
    """
    return float(np.interp(x, xs, ys))
