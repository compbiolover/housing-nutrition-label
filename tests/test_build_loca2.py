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


def test_sb_download_url_is_file_get_not_manager():
    # The working ScienceBase download is the catalog file/get route — NOT the
    # item's manager/download/<id> (which serves an HTML app page) or an S3
    # virtual-host URL (403). Guards against the regression that cached HTML stubs.
    url = b._sb_file_url(b.LOCA2_GRID_NAME.format(scen="ssp245"))
    assert url.startswith("https://www.sciencebase.gov/catalog/file/get/")
    assert b.SCIENCEBASE_ITEM_ID in url and "manager/download" not in url
    assert "ssp245_1950-2100_annual_16thdeg_grid.nc" in url.replace("%2D", "-")


def test_is_netcdf_distinguishes_magic_from_html_stub():
    d = pathlib.Path(tempfile.mkdtemp())
    nc = d / "good.nc"; nc.write_bytes(b"CDF\x02rest-of-header")
    html = d / "bad.nc"; html.write_bytes(b"<!doctype html><html>nope</html>")
    assert b._is_netcdf(nc) is True
    assert b._is_netcdf(html) is False


def test_to_neg_west_normalizes_0_360_longitude():
    # LOCA2 stores lon as 0–360 (CONUS ≈ 234.5..293.5); normalize to negative-west
    # so it matches the tract points and LOCA2_BBOX. Already-negative lons untouched.
    lon = np.array([234.53125, 269.95, 293.46875])     # ≈ -125.47, -90.05, -66.53
    out = b._to_neg_west(lon)
    assert np.allclose(out, [-125.46875, -90.05, -66.53125])
    assert np.all(np.diff(out) > 0)                    # stays monotonic
    assert np.allclose(b._to_neg_west(np.array([-90.0, -66.0])), [-90.0, -66.0])


def test_open_loca2_var_reads_windows():
    """xarray-backed reader against a tiny synthetic NetCDF (skips without the
    build deps — xarray AND a NetCDF engine, both needed to write/read the file).

    Uses 0–360 longitude like the real LOCA2 grids, so it also guards the
    normalization fix: the reader must return a negative-west lon axis."""
    try:
        import xarray as xr  # noqa: F401
        import netCDF4  # noqa: F401  # writer/reader backend for ds.to_netcdf
    except ImportError:
        print("  skip test_open_loca2_var_reads_windows (xarray/netCDF4 not installed)")
        return
    lat = np.linspace(34.0, 36.0, 4)
    lon = np.linspace(269.0, 271.0, 4)              # 0–360 (≈ -91..-89), like LOCA2
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
    # Longitude normalized to negative-west (would be ~269..271 without the fix).
    assert lo.min() < -88 and lo.max() < 0
    # Upward trend → mid-century mean exceeds the historical mean everywhere.
    assert (got["low"] > got["hist"]).all()
    mask = (years >= 1991) & (years <= 2020)
    assert np.isclose(got["hist"][0, 0], data[mask, 0, 0].mean())


# ───────────────────────── FWI source (ClimRR fire leg) ─────────────────────────

def test_webmerc_to_lonlat_matches_runtime_formula():
    # The inlined EPSG:3857→WGS84 must match housing_label.utils.webmercator_to_wgs84.
    from housing_label.utils import webmercator_to_wgs84
    for x, y in [(0.0, 0.0), (-1.2e7, 5.0e6), (5.0e6, -3.0e6)]:
        assert np.allclose(b._webmerc_to_lonlat(x, y), webmercator_to_wgs84(x, y))
    # Origin maps to (lon=0, lat=0); a mid-CONUS cell resolves to plausible US lat/lon.
    lon, lat = b._webmerc_to_lonlat(0.0, 0.0)
    assert abs(lon) < 1e-9 and abs(lat) < 1e-9


def test_sample_fwi_rows_join_aggregation_and_single_scenario():
    # Two grid cells; tracts snap to the nearest by great-circle-ish distance.
    cell_ll = {"R1C1": (35.0, -90.0), "R1C2": (40.0, -105.0)}
    fwi = {"R1C1": {"hist": 18.0, "mid": 20.0},     # humid east
           "R1C2": {"hist": 44.0, "mid": 46.0}}     # fire-prone west
    tracts = [
        {"geoid": "47001000100", "lat": 35.1, "lon": -90.1},   # → R1C1
        {"geoid": "47001000200", "lat": 34.9, "lon": -89.8},   # → R1C1
        {"geoid": "08001000100", "lat": 39.9, "lon": -105.2},  # → R1C2
    ]
    county_fire, tract_fire = b.sample_fwi_rows(cell_ll, fwi, tracts)
    # Single RCP8.5 pathway: mid-century drives BOTH low and high; hist stays hist.
    assert tract_fire["47001000100"] == {"hist": 18.0, "low": 20.0, "high": 20.0}
    assert tract_fire["08001000100"]["low"] == 46.0
    # County = mean of its tracts (both east tracts on R1C1 → same value).
    assert county_fire["47001"]["low"] == 20.0
    assert county_fire["08001"]["high"] == 46.0
    # The fire-prone county's FWI is far higher than the humid one.
    assert county_fire["08001"]["low"] > county_fire["47001"]["low"]


def test_augment_with_fire_adds_columns_and_blanks_missing():
    import csv as _csv
    d = pathlib.Path(tempfile.mkdtemp())
    path = d / "climate_projections.csv"
    # A minimal base crosswalk (two counties) in the shared schema.
    base_cols = b._out_columns()
    with path.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=base_cols)
        w.writeheader()
        for geoid in ("47157", "15003"):   # Shelby (has fire), Honolulu (no fire)
            w.writerow({c: ("county" if c == "geo_level" else geoid if c == "geoid" else "1")
                        for c in base_cols})
    n, n_fire = b._augment_with_fire(path, {"47157": {"hist": 18.0, "low": 20.0, "high": 20.0}}, 5)
    assert (n, n_fire) == (2, 1)
    rows = {r["geoid"]: r for r in _csv.DictReader(path.open())}
    # New columns appended; the covered county filled, the uncovered one blank.
    assert "fire_fwi_low" in rows["47157"] and rows["47157"]["fire_fwi_low"] == "20.0"
    assert rows["15003"]["fire_fwi_low"] == ""


def test_fwi_band_mapping_is_single_scenario():
    # Mid-century (RCP8.5) feeds BOTH the low and high output bands; hist→hist.
    assert b.FWI_BANDS == [("hist", "hist"), ("mid", "low"), ("mid", "high")]
    assert set(b.FWI_HORIZON_COL) == {"hist", "mid"}


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
