#!/usr/bin/env python3
"""Tests for per-dimension national percentiles (data/national_percentile.py) and
their surfacing on the label payload.

Runs standalone (``python tests/test_national_percentile.py``) or via pytest.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from housing_label.data import national_percentile as NP  # noqa: E402


def test_construction_curve_monotonic_and_bounded():
    """Higher score → higher (or equal) national percentile, within [0, 100]."""
    for dim in ("energy", "durability", "environmental", "resilience"):
        prev = -1
        for s in range(0, 101, 10):
            p = NP.national_percentile(dim, s)
            assert p is not None, dim
            assert 0 <= p <= 100
            assert p >= prev, f"{dim} not monotonic at {s}"
            prev = p


def test_identity_dims_return_score():
    for dim in ("health", "socioeconomic", "climate", "infrastructure"):
        assert NP.national_percentile(dim, 70) == 70
        assert NP.national_percentile(dim, 12.4) == 12    # rounded


def test_walkability_from_crosswalk():
    lo = NP.national_percentile("walkability", 10)
    hi = NP.national_percentile("walkability", 95)
    assert lo is not None and hi is not None
    assert 0 <= lo < hi <= 100          # more walkable → higher percentile


def test_none_and_clamp():
    assert NP.national_percentile("energy", None) is None
    assert NP.national_percentile("energy", 200) == NP.national_percentile("energy", 100)
    assert NP.national_percentile("nonexistent-dim", 50) is None


def test_interp_helper():
    assert NP._interp(5, [0, 10], [0, 100]) == 50.0
    assert NP._interp(-1, [0, 10], [0, 100]) == 0.0     # flat extrapolation
    assert NP._interp(99, [0, 10], [0, 100]) == 100.0


def test_surfaced_on_label_payload():
    """Each scored dimension in the payload carries a national_percentile."""
    from housing_label.simulate.house import build_label_parts, label_payload
    cfg, r, label = build_label_parts(
        lat=34.05, lon=-118.24, preset=None, allow_network=False,
        year_built=1975, construction="frame", foundation="slab",
        condition="average", sqft=1800)
    dims = {d["key"]: d for d in label_payload(cfg, r, label)["dimensions"]}
    for key in ("energy", "durability", "environmental", "resilience", "infrastructure"):
        d = dims[key]
        if d["score"] is not None:
            assert isinstance(d["national_percentile"], int)
            assert 0 <= d["national_percentile"] <= 100


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
