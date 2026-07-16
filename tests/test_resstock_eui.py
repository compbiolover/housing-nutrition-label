#!/usr/bin/env python3
"""Tests for the ResStock benchmarks (data/resstock_eui.py) and their use as the
Energy dimension's base site-EUI + within-cell factors (enrich/energy).

Runs offline against the bundled resstock_eui.csv / resstock_factors.csv.
"""

from __future__ import annotations

import csv
import pathlib
import re

from housing_label.data import resstock_eui as R
from housing_label.enrich.energy import base_eui, climate_zone_factor, _foundation_factor


BUILDING_TYPES = {"sf_detached", "sf_attached", "mf_2_4", "mf_5plus", "mobile_home"}
VBINS = {"pre_1950", "1950_1979", "1980_1999", "2000_2009", "2010_plus", "unknown"}


def _rows(name):
    path = pathlib.Path(R.__file__).resolve().parent / name
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_eui_table_loads_and_is_wellformed():
    """Every bundled cell is (known building type, valid zone key, known bin, +EUI)."""
    zone_re = re.compile(r"^[1-8][ABC]?$")
    rows = _rows("resstock_eui.csv")
    assert len(rows) > 300
    for r in rows:
        assert r["building_type"] in BUILDING_TYPES, r
        assert zone_re.match(r["climate_zone"]), r
        assert r["vintage_bin"] in VBINS, r
        assert float(r["eui_kbtu_sqft_yr"]) > 0, r
    # All five building types are present.
    assert {r["building_type"] for r in rows} == BUILDING_TYPES


def test_factors_table_loads_and_is_wellformed():
    rows = _rows("resstock_factors.csv")
    axes = {r["axis"] for r in rows}
    assert axes == {"foundation", "hvac"}
    for r in rows:
        assert float(r["factor"]) > 0, r
    # Heat pump sits below the cell median (it is the efficient default).
    assert R.resstock_factor("hvac", "heat_pump") < 1.0
    # Gas furnace burns more site energy than the heat-pump default.
    assert R.resstock_factor("hvac", "gas_furnace") > R.resstock_factor("hvac", "heat_pump")
    # A missing (axis, key) returns None, not a crash.
    assert R.resstock_factor("foundation", "not_a_key") is None


def test_building_type_lookup_and_fallback():
    # Each building type resolves its own EUI, and they are not all identical.
    euis = {bt: R.resstock_base_eui("4A", "2000_2009", bt) for bt in BUILDING_TYPES}
    assert all(v is not None for v in euis.values())
    assert len(set(euis.values())) > 1                      # types genuinely differ
    # The loader is building-type-EXACT: an unknown type returns None (base_eui owns
    # the detached fallback, tested in test_base_eui_prefers_resstock_and_falls_back).
    assert R.resstock_base_eui("4A", "2000_2009", "not_a_type") is None
    # Default building type is detached.
    assert R.resstock_base_eui("4A", "2000_2009") == euis["sf_detached"]
    # base_eui walks the chain → an unknown type resolves to the detached value.
    assert base_eui("4A", "2000_2009", "not_a_type") == euis["sf_detached"]


def test_thin_cell_drops_and_falls_back_within_building_type():
    """A dropped thin cell (pre-1950 mobile home — 1-2 samples) is absent from the
    table, and base_eui falls back to that building type's all-vintage median (a
    real mobile-home EUI), NOT the garbage thin median and NOT the detached curve."""
    # The specific flagged cells were dropped at build time.
    assert R.resstock_base_eui("2B", "pre_1950", "mobile_home") is None
    # base_eui resolves it to the mobile-home all-vintage median for that zone/digit
    # — a plausible mobile-home intensity, not the ~8.5 thin-sample artifact.
    got = base_eui("2B", "pre_1950", "mobile_home")
    assert got == R.resstock_base_eui("2B", "unknown", "mobile_home")
    assert got > 20                                          # sane, not the artifact
    # Every bundled EUI is plausible (thin-sample artifacts are gone).
    for r in _rows("resstock_eui.csv"):
        assert 15 <= float(r["eui_kbtu_sqft_yr"]) <= 200, r


def test_zone_lookup_digit_and_moisture():
    # Exact full zone resolves; digit fallback resolves; lowercase matches the full row.
    assert R.resstock_base_eui("4A", "2000_2009", "mf_5plus") is not None
    assert R.resstock_base_eui("7", "1950_1979", "mobile_home") is not None
    assert R.resstock_base_eui("4Z", "2000_2009") == R.resstock_base_eui("4", "2000_2009")
    assert R.resstock_base_eui("4a", "2000_2009") == R.resstock_base_eui("4A", "2000_2009")
    # A moisture regime differs from its dry counterpart within a zone number.
    a = R.resstock_base_eui("3A", "pre_1950")
    b = R.resstock_base_eui("3B", "pre_1950")
    assert a is not None and b is not None and a != b
    # No zone → None (caller keeps its own fallback).
    assert R.resstock_base_eui(None, "2000_2009", "mf_5plus") is None


def test_base_eui_prefers_resstock_and_falls_back():
    # Covered zone → the ResStock value for that building type.
    assert base_eui("4A", "2000_2009", "mf_5plus") == R.resstock_base_eui("4A", "2000_2009", "mf_5plus")
    # Zone 8 (interior Alaska) isn't in ResStock → prior fallback curve (building
    # type does not matter there).
    assert R.resstock_base_eui("8", "2000_2009", "mf_5plus") is None
    assert base_eui("8", "2000_2009", "mf_5plus") == 35.0 * climate_zone_factor("8")
    # Unexpected vintage bin on an UNCOVERED zone (8) → legacy "unknown" curve.
    assert base_eui("8", "not_a_bin") == 50.0 * climate_zone_factor("8")
    # Unexpected vintage bin on a COVERED zone → that zone's ResStock all-vintage median.
    assert base_eui("4A", "not_a_bin", "mf_2_4") == R.resstock_base_eui("4A", "unknown", "mf_2_4")


def test_foundation_factor_uses_resstock():
    """The foundation factor is the ResStock-derived within-cell multiplier."""
    # BSMT 3 = heated (full) basement — ResStock says lower per-sqft EUI (< 1).
    label, factor = _foundation_factor(3)
    assert label == "full_basement"
    assert factor == R.resstock_factor("foundation", "full_basement")
    assert factor < 1.0
    # Unknown foundation → neutral 1.0.
    assert _foundation_factor(float("nan")) == ("unknown", 1.00)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
