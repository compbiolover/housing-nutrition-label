#!/usr/bin/env python3
"""Offline tests for the all-dimension house simulation.

Runs without network access (location dimensions are skipped) and without
pytest — execute directly:  python tests/test_dimensions.py
(pytest will also collect the test_* functions if it is installed.)
"""

from argparse import Namespace

from housing_label.simulate.house import resolve_config, simulate
from housing_label.simulate.dimensions import (
    build_parcel_row, compute_construction_dimensions, simulate_all_dimensions,
    EXTWALL_CODE, COND_CODE, CONSTRUCTION_DRIVEN, LOCATION_DRIVEN,
)

_FIELDS = ["flood_zone", "year_built", "construction", "foundation",
           "condition", "value", "units", "sqft", "lot_acres"]


def _cfg(preset):
    args = Namespace(preset=preset, lat=35.15, lon=-89.85,
                     **{f: None for f in _FIELDS})
    return resolve_config(args)


def test_parcel_row_mapping():
    """Config vocabulary maps to the expected CAMA codes (incl. per-unit split)."""
    cfg = _cfg("icf-quadplex")          # 4 units, icf, excellent, 0.20 ac, $600k
    row = build_parcel_row(cfg)
    assert row["EXTWALL"] == EXTWALL_CODE["icf"]      # icf → block/concrete proxy
    assert row["COND"] == COND_CODE["excellent"]      # excellent → 5
    # Per-unit framing: lot acres and value divided by the 4 units.
    assert abs(row["CALC_ACRE"] - 0.20 / 4) < 1e-9
    assert abs(row["RTOTAPR"] - 600_000 / 4) < 1e-6


def test_construction_dimensions_scored():
    """All four construction-driven dimensions score in range for a real house."""
    dims = compute_construction_dimensions(_cfg("baseline"))
    for key in ("energy", "durability", "environmental", "infrastructure"):
        assert dims[key] is not None, f"{key} should be scored"
        assert 0.0 <= dims[key] <= 100.0
    assert dims["_metrics"]["eui_kbtu_sqft_yr"] > 0


def test_better_build_scores_higher():
    """An ICF passive house out-scores the worst-case build on every
    construction-driven dimension (sanity check the models respond to config)."""
    worst = compute_construction_dimensions(_cfg("worst-case"))
    icf = compute_construction_dimensions(_cfg("icf-passive"))
    for key in ("energy", "durability", "environmental", "infrastructure"):
        assert icf[key] > worst[key], f"icf should beat worst-case on {key}"


def test_location_dims_excluded_offline():
    """With network off, location dimensions are None and the composite is the
    mean of only the scored (construction + resilience) dimensions."""
    cfg = _cfg("icf-passive")
    r = simulate(cfg)
    label = simulate_all_dimensions(cfg, r["total_score"], allow_network=False)

    by_key = {d["key"]: d for d in label["dimensions"]}
    for key in LOCATION_DRIVEN:
        assert by_key[key]["score"] is None
        assert by_key[key]["national_grade"] == "—"
    for key in CONSTRUCTION_DRIVEN | {"resilience"}:
        assert by_key[key]["score"] is not None

    assert label["n_scored"] == 5
    scored = [by_key[k]["score"] for k in CONSTRUCTION_DRIVEN | {"resilience"}]
    expected = round(sum(scored) / len(scored), 1)
    assert abs(label["composite_score"] - expected) < 0.05


def test_override_includes_location_dim():
    """A manual override supplies a location dimension without any network call."""
    cfg = _cfg("baseline")
    r = simulate(cfg)
    label = simulate_all_dimensions(
        cfg, r["total_score"], allow_network=False,
        overrides={"walkability": 79.6},
    )
    by_key = {d["key"]: d for d in label["dimensions"]}
    assert by_key["walkability"]["score"] == 79.6
    assert by_key["walkability"]["national_grade"] == "B"
    assert label["n_scored"] == 6


def test_embodied_amortized_over_service_life():
    """Embodied carbon is amortized over the shell's service life: a frame shell
    is 60 yr (its embodied sub-score is unchanged from the flat-period model),
    while a concrete/ICF shell is 100 yr and so its embodied sub-score is no
    longer near-zero despite the shell's high upfront embodied intensity."""
    import pandas as pd
    from housing_label.enrich.environmental import (
        service_life_years, model_parcel_environment,
    )
    assert service_life_years(7) == 60.0    # frame
    assert service_life_years(3) == 100.0   # block/concrete (ICF maps here)

    base = dict(SFLA=2000, GRADE=45, est_annual_kwh=3000, est_annual_therms=10,
                RMBED=3, FIXBATH=2, STORIES=1, CALC_ACRE=0.2, acre_outlier=False)
    frame = model_parcel_environment(pd.Series({**base, "EXTWALL": 7}))
    icf = model_parcel_environment(pd.Series({**base, "EXTWALL": 3}))

    assert frame["env_service_life_yr"] == 60
    assert icf["env_service_life_yr"] == 100
    assert frame["env_embodied_subscore"] > 80           # low-carbon wood, ~93
    # Concrete's high upfront carbon, amortized over 100 yr, is no longer ~0 as
    # it was under flat 60-yr amortization (was ~1.4).
    assert icf["env_embodied_subscore"] > 40


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
