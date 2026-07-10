#!/usr/bin/env python3
"""Tests for the geometry-aware embodied-carbon model (data/embodied_carbon.py).

Pure functions over codes + geometry — no network, no CSV. Execute directly
(``python tests/test_embodied_carbon.py``) or via pytest.
"""

from __future__ import annotations

from housing_label.data import embodied_carbon as ec

_M2 = 0.092903  # sqft → m²


def _home(sqft, wall=7, bsmt=1, stories=1, basement_depth_m=None):
    return ec.embodied_intensity_kgm2(wall, bsmt, sqft * _M2, stories, basement_depth_m)


def test_smaller_home_has_higher_intensity():
    # Envelope + roof + foundation grow faster than floor area as a home shrinks,
    # so kgCO2e/m² rises for smaller homes (Rauf et al. 2025).
    big = _home(4000)
    mid = _home(2000)
    small = _home(1000)
    assert small > mid > big


def test_more_stories_lowers_intensity():
    # A 2-story home spreads less foundation + roof over the same floor area.
    one = _home(2000, stories=1)
    two = _home(2000, stories=2)
    assert two < one


def test_foundation_ordered_and_dominant():
    slab = _home(2000, bsmt=1)
    partial = _home(2000, bsmt=2)
    full = _home(2000, bsmt=3)
    assert slab < partial < full
    # Full basement vs slab is a large swing (the dominant driver, Jungclaus 2024).
    assert full - slab > 25.0


def test_actual_basement_depth_overrides_default():
    shallow = _home(2000, bsmt=3, basement_depth_m=2.0)
    deep = _home(2000, bsmt=3, basement_depth_m=3.5)
    assert deep > shallow


def test_wall_type_ordered_light_to_heavy():
    # At fixed size/foundation: frame < stucco < block < brick veneer < stone <
    # solid brick (clay brick veneer is heavier than concrete block).
    order = [_home(2000, wall=w) for w in (7, 8, 3, 9, 4, 1)]
    assert order == sorted(order)


def test_real_footprint_overrides_shape_factor_estimate():
    m2 = 2000 * _M2
    est = ec.embodied_intensity_kgm2(7, 1, m2, None)   # shape-factor + 1-story default
    # A real compact footprint (multi-story building) embodies less foundation + roof
    # per m² of floor than the 1-story shape-factor estimate assumes.
    real = ec.embodied_intensity_kgm2(7, 1, m2, None,
                                      footprint_area_m2=100, footprint_perimeter_m=42)
    assert real != est
    assert real < est


def test_partial_footprint_falls_back_to_estimate():
    # Area without perimeter (or vice versa) is unusable → estimate, not a crash.
    m2 = 2000 * _M2
    est = ec.embodied_intensity_kgm2(7, 1, m2, None)
    assert ec.embodied_intensity_kgm2(7, 1, m2, None, footprint_area_m2=100) == est
    assert ec.embodied_intensity_kgm2(7, 1, m2, None, footprint_perimeter_m=42) == est


def test_unknown_inputs_fall_back_without_crashing():
    assert ec.embodied_intensity_kgm2(None, None) == ec.EC_INTENSITY_DEFAULT
    assert ec.embodied_intensity_kgm2("x", "y", "z", None, None) == ec.EC_INTENSITY_DEFAULT
    assert ec.embodied_intensity_kgm2(9999, 9999, -5, 0) == ec.EC_INTENSITY_DEFAULT


def test_all_typical_combos_land_in_empirical_band():
    # Every wall × foundation × plausible size/story combo must sit inside the
    # published A1–A3 single-family span (~38 low-end Jungclaus to ~260 for a small
    # masonry home over a full basement), so a bad constant can't silently push a
    # home off the real distribution.
    for w in list(ec._ENV_KG_PER_M2WALL) + [None]:
        for b in (1, 2, 3, None):
            for sqft in (900, 2000, 4500):
                for st in (1, 2):
                    v = ec.embodied_intensity_kgm2(w, b, sqft * _M2, st)
                    assert 38.0 <= v <= 260.0, (w, b, sqft, st, v)


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
