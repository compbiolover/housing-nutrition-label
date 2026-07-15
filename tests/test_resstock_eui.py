#!/usr/bin/env python3
"""Tests for the ResStock base-EUI benchmark (data/resstock_eui.py) and its use
as the Energy dimension's base site-EUI (enrich/energy.base_eui).

Runs offline against the bundled resstock_eui.csv.
"""

from __future__ import annotations

import csv
import pathlib
import re

from housing_label.data import resstock_eui as R
from housing_label.enrich.energy import base_eui, climate_zone_factor


def test_table_loads_and_is_wellformed():
    """Every bundled cell is (valid zone key, known vintage bin, positive EUI)."""
    path = pathlib.Path(R.__file__).resolve().parent / "resstock_eui.csv"
    zone_re = re.compile(r"^[1-8][ABC]?$")
    vbins = {"pre_1950", "1950_1979", "1980_1999", "2000_2009", "2010_plus", "unknown"}
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 50
    for r in rows:
        assert zone_re.match(r["climate_zone"]), r
        assert r["vintage_bin"] in vbins, r
        assert float(r["eui_kbtu_sqft_yr"]) > 0, r


def test_full_zone_lookup_and_digit_fallback():
    # Exact full zone resolves.
    assert R.resstock_base_eui("4A", "2000_2009") is not None
    # A bare-digit bundled zone (e.g. "7") resolves via the digit fallback row.
    assert R.resstock_base_eui("7", "1950_1979") is not None
    # A moisture regime ResStock doesn't sample still resolves by leading digit.
    assert R.resstock_base_eui("4Z", "2000_2009") == R.resstock_base_eui("4", "2000_2009")
    # No zone → None (caller keeps its own fallback).
    assert R.resstock_base_eui(None, "2000_2009") is None


def test_moisture_regime_is_distinguished():
    """The whole point of ResStock here: humid vs dry within a zone number differ,
    which the old leading-digit-only scalar could not capture."""
    a = R.resstock_base_eui("3A", "pre_1950")   # humid (e.g. Atlanta)
    b = R.resstock_base_eui("3B", "pre_1950")   # dry (e.g. inland CA)
    assert a is not None and b is not None and a != b


def test_base_eui_prefers_resstock_and_falls_back():
    # Covered zone → the ResStock value (not the old scaled curve).
    assert base_eui("4A", "2000_2009") == R.resstock_base_eui("4A", "2000_2009")
    # Zone 8 (interior Alaska) isn't in ResStock → prior fallback curve.
    fallback = R.resstock_base_eui("8", "2000_2009")
    assert fallback is None
    assert base_eui("8", "2000_2009") == 35.0 * climate_zone_factor("8")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
