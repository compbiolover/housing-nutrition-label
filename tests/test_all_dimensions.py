#!/usr/bin/env python3
"""Tests for the batch scorer's dimension activation (score/all_dimensions.py).

Focus: a missing source column must never become a fabricated score. This file alone: ``pytest tests/test_all_dimensions.py``.
"""

from __future__ import annotations

import pandas as pd

from housing_label.score import all_dimensions as A


def test_socioeconomic_missing_is_unscored_not_placeholder():
    """With no socioeconomic_index column (no ACS / no Census key), the dimension
    is kept but honestly unscored and excluded from the composite — NOT filled
    with the old uniform 50, matching the live API path."""
    cols = ["resilience_score", "durability_score"]   # note: no socioeconomic_index
    active = A.resolve_active_dimensions(cols)
    socio = next(d for d in active if d.key == "socioeconomic")
    assert socio.composite is False

    df = pd.DataFrame({"resilience_score": [70.0, 40.0], "durability_score": [55.0, 30.0]})
    A.add_dimension_columns(df, socio)
    # Score is NaN (not 50.0) and the grade is the unscored dash.
    assert df["socioeconomic_score"].isna().all()
    assert (df["socioeconomic_national_grade"] == "—").all()


def test_composite_excludes_unscored_socioeconomic():
    """The composite is the mean of the *scored* composite dimensions only — an
    unscored socioeconomic must not drag it toward 50."""
    cols = ["resilience_score"]
    active = A.resolve_active_dimensions(cols)
    df = pd.DataFrame({"resilience_score": [80.0]})
    # Score just the two dimensions under test (resilience present; socioeconomic
    # re-pointed to the unscored scorer). Other dims are irrelevant here.
    scored = {d.key: d for d in active if d.key in ("resilience", "socioeconomic")}
    for dim in scored.values():
        A.add_dimension_columns(df, dim)
    composite_keys = [k for k, d in scored.items() if d.composite]
    A.add_composite(df, composite_keys)
    assert "socioeconomic" not in composite_keys
    # Composite equals the lone scored dimension, untouched by the missing socio.
    assert df["composite_score"].iloc[0] == 80.0


def test_present_socioeconomic_feeds_composite():
    """When the ACS column IS present, socioeconomic is a normal composite dim."""
    cols = ["resilience_score", "socioeconomic_index"]
    active = A.resolve_active_dimensions(cols)
    socio = next(d for d in active if d.key == "socioeconomic")
    assert socio.composite is True and socio.requires == "socioeconomic_index"
