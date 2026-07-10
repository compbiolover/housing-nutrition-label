#!/usr/bin/env python3
"""Tests for the USA Structures footprint lookup (enrich/footprint.py).

Pure/offline — the geodesic helpers are exercised directly and the network path is
only checked for its graceful fallbacks (no live call). Run directly or via pytest.
"""

from __future__ import annotations

from housing_label.enrich import footprint as fp


def test_haversine_one_degree_latitude():
    # 1° of latitude ≈ 111 km anywhere.
    assert 110_000 < fp._haversine_m(0, 0, 0, 1) < 112_000


def test_ring_perimeter_square_near_equator():
    # A 0.01° square near the equator has ~1.11 km sides → ~4.44 km perimeter.
    ring = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]
    assert 4_300 < fp._ring_perimeter_m(ring) < 4_500


def test_ring_perimeter_closes_an_unclosed_ring():
    closed = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]
    unclosed = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01]]
    assert abs(fp._ring_perimeter_m(closed) - fp._ring_perimeter_m(unclosed)) < 1.0


def test_ring_area_ranks_outer_boundary_over_hole():
    outer = [[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]
    hole = [[0.005, 0.005], [0.006, 0.005], [0.006, 0.006], [0.005, 0.006], [0.005, 0.005]]
    assert fp._ring_area_deg2(outer) > fp._ring_area_deg2(hole)


def test_offline_returns_none():
    assert fp.footprint_for_point(38.9, -77.0, allow_network=False) is None


def test_bad_coords_return_none():
    assert fp.footprint_for_point(None, None) is None
    assert fp.footprint_for_point(float("nan"), -77.0) is None
    assert fp.footprint_for_point(float("inf"), -77.0) is None


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
