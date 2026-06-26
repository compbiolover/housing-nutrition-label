#!/usr/bin/env python3
"""Tests for the LOCA2 build pipeline's logic (no network, no multi-GB download).

The pure sampling/aggregation core is tested with synthetic numpy fields and
always runs. The xarray-backed NetCDF reader is tested against a tiny synthetic
file and is skipped when the build-only dependency (xarray) is absent — the same
graceful-skip pattern as test_api.py with fastapi.

Run directly:  python tests/test_build_loca2.py
"""

import pathlib
import tempfile

import numpy as np

import scripts.build_climate_projections as b


def _grid():
    """A small CONUS-interior grid (inside LOCA2_BBOX) with a spatial gradient."""
    lat = np.linspace(34.0, 36.0, 5)
    lon = np.linspace(-91.0, -89.0, 5)
    ii, jj = np.meshgrid(np.arange(5), np.arange(5), indexing="ij")
    heat = 20.0 + 5.0 * ii + 2.0 * jj          # varies across the grid
    fields = {
        "heat_days95": {"hist": heat * 0.5, "low": heat, "high": heat * 1.2},
        "heat_days100": {"hist": heat * 0.2, "low": heat * 0.4, "high": heat * 0.5},
        "precip_days1in": {"hist": jj + 5.0, "low": jj + 6.0, "high": jj + 7.0},
        "precip_max5day": {"hist": ii + 3.0, "low": ii + 4.0, "high": ii + 5.0},
        "drought_consecdd": {"hist": jj + 10.0, "low": jj + 12.0, "high": jj + 14.0},
    }
    return lat, lon, fields


def test_sample_point_bbox_and_ring_fallback():
    lat, lon, fields = _grid()
    f = fields["heat_days95"]["low"]
    # In-grid point returns the nearest cell value.
    assert b._sample_point(34.0, -91.0, lat, lon, f) == f[0, 0]
    # Outside the CONUS bbox → None (e.g. an Alaska point).
    assert b._sample_point(64.0, -150.0, lat, lon, f) is None
    # A masked (NaN) nearest cell falls back to the NEAREST valid cell — not the
    # mean of the ring (which would bias the value).
    i = int(np.abs(lat - 35.0).argmin())
    j = int(np.abs(lon + 90.0).argmin())
    fn = np.full_like(f, np.nan)
    fn[i, j] = np.nan                 # nearest cell masked
    fn[i, j + 1] = 7.0                # immediate neighbour (distance 1)
    fn[i, j + 2] = 99.0               # farther cell (distance 2)
    assert b._sample_point(35.0, -90.0, lat, lon, fn) == 7.0


def test_window_mean():
    years = np.arange(1990, 2071)
    # value == year, so the [2040, 2069] mean is the midpoint 2054.5.
    data = years.astype(float)[:, None, None] * np.ones((1, 2, 2))
    out = b._window_mean(data, years, 2040, 2069)
    assert out.shape == (2, 2) and np.allclose(out, 2054.5)


def test_sample_rows_variation_coherence_and_schema():
    lat, lon, fields = _grid()
    # Two tracts of county 47001 at different cells (must vary); one out-of-grid.
    tracts = [
        {"geoid": "47001000100", "lat": 34.0, "lon": -91.0},
        {"geoid": "47001000200", "lat": 36.0, "lon": -89.0},
        {"geoid": "02001000100", "lat": 64.0, "lon": -150.0},  # outside grid
    ]
    meta = {"47001": {"name": "Alpha", "state": "TN"}}
    county_rows, tract_rows = b.sample_loca2_rows(fields, lat, lon, tracts, meta)

    # Schema: every row carries the full shared column set.
    assert set(tract_rows[0]) == set(b._out_columns())
    # Out-of-grid tract present but blank (runtime then resolves to parent county).
    ak = next(r for r in tract_rows if r["geoid"].startswith("02"))
    assert ak["heat_days95_low"] == "" and ak["geo_level"] == "tract"
    # Intra-county variation exists — the inverse of CMRA's broadcast behavior.
    vals = sorted(r["heat_days95_low"] for r in tract_rows if r["geoid"].startswith("47001"))
    assert vals[-1] - vals[0] > 5
    # County == mean of its (in-grid) tracts → tract→county coherence.
    c = next(r for r in county_rows if r["geoid"] == "47001")
    assert np.isclose(c["heat_days95_low"], round(float(np.mean(vals)), 3), atol=0.01)
    assert c["county_name"] == "Alpha" and c["geo_level"] == "county"


def test_loca2_var_mapping_and_conversion_config():
    # The five output stems map to the documented LOCA2 variables; only Rx5day
    # (mm) carries a unit divisor (→ inches).
    assert b.LOCA2_VARS["precip_max5day"] == ("Rx5day", 25.4)
    assert b.LOCA2_VARS["heat_days95"] == ("TXge95F", None)
    assert {s for s, _ in b.LOCA2_VARS.values()} == {
        "TXge95F", "TXge100F", "R1in", "Rx5day", "CDD"}


def test_open_loca2_var_reads_windows():
    """xarray-backed reader against a tiny synthetic NetCDF (skips without the
    build deps — xarray AND a NetCDF engine, both needed to write/read the file)."""
    try:
        import xarray as xr  # noqa: F401
        import netCDF4  # noqa: F401  # writer/reader backend for ds.to_netcdf
    except ImportError:
        print("  skip test_open_loca2_var_reads_windows (xarray/netCDF4 not installed)")
        return
    lat = np.linspace(34.0, 36.0, 4)
    lon = np.linspace(-91.0, -89.0, 4)
    years = np.arange(1990, 2071)
    time = np.array([np.datetime64(f"{y}-07-01") for y in years])
    trend = (years - 1990).astype(float)
    data = 10.0 + trend[:, None, None] * np.ones((1, 4, 4))
    ds = xr.Dataset({"TXge95F": (("time", "lat", "lon"), data)},
                    coords={"time": time, "lat": lat, "lon": lon})
    nc = pathlib.Path(tempfile.mkdtemp()) / "syn.nc"
    ds.to_netcdf(nc)
    la, lo, got = b._open_loca2_var(nc, "TXge95F", {"hist": (1991, 2020), "low": (2040, 2069)})
    assert la.shape == (4,) and lo.shape == (4,)
    # Upward trend → mid-century mean exceeds the historical mean everywhere.
    assert (got["low"] > got["hist"]).all()
    mask = (years >= 1991) & (years <= 2020)
    assert np.isclose(got["hist"][0, 0], data[mask, 0, 0].mean())


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
