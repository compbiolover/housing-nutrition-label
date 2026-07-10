#!/usr/bin/env python3
"""Tests for the bottom-up embodied-carbon model (data/embodied_carbon.py).

Pure functions over integer codes — no network, no CSV. Execute directly
(``python tests/test_embodied_carbon.py``) or via pytest.
"""

from __future__ import annotations

from housing_label.data import embodied_carbon as ec


def test_foundation_is_ordered_and_dominant():
    # Foundation carbon rises slab/crawl < partial < full basement (the dominant
    # driver of home-to-home embodied variance).
    slab = ec.embodied_intensity_kgm2(7, 1)
    partial = ec.embodied_intensity_kgm2(7, 2)
    full = ec.embodied_intensity_kgm2(7, 3)
    assert slab < partial < full
    # The slab→basement swing is real (double-digit kgCO2e/m2), not a rounding nudge.
    assert full - slab > 10.0


def test_wall_type_is_ordered_light_to_heavy():
    # At a fixed foundation, a wood frame embodies less than a brick veneer, which
    # embodies less than solid masonry / stone.
    frame = ec.embodied_intensity_kgm2(7, 1)
    veneer = ec.embodied_intensity_kgm2(9, 1)
    masonry = ec.embodied_intensity_kgm2(3, 1)
    stone = ec.embodied_intensity_kgm2(4, 1)
    assert frame < veneer < masonry < stone


def test_unknown_codes_fall_back_to_defaults():
    assert ec.embodied_intensity_kgm2(None, None) == ec.EC_INTENSITY_DEFAULT
    assert ec.embodied_intensity_kgm2(9999, 9999) == ec.EC_INTENSITY_DEFAULT
    # Non-numeric junk is tolerated, not raised.
    assert ec.embodied_intensity_kgm2("x", "y") == ec.EC_INTENSITY_DEFAULT


def test_every_intensity_lands_in_empirical_band():
    # Every wall×foundation combination must sit inside the published A1–A3
    # single-family band (~39 low-end Jungclaus to ~210 empirical as-built), so a
    # bad factor/quantity can't silently push a home off the real distribution.
    for w in list(ec.SHELL_KGM2_BY_WALL) + [None]:
        for b in list(ec.FOUNDATION_KGM2) + [None]:
            v = ec.embodied_intensity_kgm2(w, b)
            assert 39.0 <= v <= 210.0, (w, b, v)


def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
