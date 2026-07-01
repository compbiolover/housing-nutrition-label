#!/usr/bin/env python3
"""Build the bundled climate-projection crosswalk(s).

Writes the offline lookups that let ``data/climate_projections.py`` return real
downscaled climate-hazard projections: ``climate_projections.csv`` (county) and,
for the LOCA2 source, ``climate_projections_tracts.csv.gz`` (genuinely sub-county).

Three sources
-------------
``--source loca2`` (default) — **genuinely sub-county.** USGS CMIP6-LOCA2 threshold
metrics, Weighted Multi-Model Mean (WMMM), annual 1/16° (~6 km) CONUS grid on
ScienceBase (DOI 10.5066/P13OV6GY, keyless). We download one NetCDF per SSP
(~2.6 GB each — needs the project's ``[build]`` extra: xarray/netCDF4), cut a
historical (1991–2020) and a mid-century (2040–2069) 30-yr window, and sample the
nearest grid cell at each census tract's internal point (Census Gazetteer). The
county value is the mean of its tracts, so tract→county is coherent. ssp245→low,
ssp585→high. Unlike CMRA's tract layer, this yields real intra-county variation.

``--source cmra`` — the original county aggregate (CMIP5/RCP). NOAA/DOI CMRA
ArcGIS FeatureServer; ``--geo-level tract`` exists but is not bundled (that layer
broadcasts the county value — no sub-county signal). Retained for history.

``--source fwi`` — the **fire leg.** Argonne ClimRR 12 km Fire Weather Index
(RCP8.5, keyless CSVs on Box) joined to census geography by a pure-stdlib
shapefile parse + nearest-cell sample, then appended to the existing crosswalks as
fire_fwi_{hist,low,high}. Small download (~12 MB); run it after a base build.

CMRA source (fully keyless, government-sourced)
-----------------------------------------------
NOAA / DOI **Climate Mapping for Resilience and Adaptation (CMRA)** screening
dataset, served as a public ArcGIS FeatureServer. CMRA aggregates LOCA-downscaled
CMIP5 projections (the NCA4 downscaling) to county polygons as 30-year means for
historical, early-, mid-, and late-century windows under two emissions pathways,
RCP4.5 (lower) and RCP8.5 (higher). RCP4.5/RCP8.5 are the standard low/high
analogs of SSP2-4.5 / SSP5-8.5.

We pull the **mid-century (≈2050) ensemble-mean** for each county under both
pathways, plus the historical baseline, for five hazard metrics:

  • TMAX95F     — annual days with max temperature > 95 °F      (extreme heat)
  • TMAX100F    — annual days with max temperature > 100 °F     (extreme heat)
  • PR1IN       — annual days with > 1 inch precipitation       (heavy precip)
  • PRMAX5DAY   — annual highest 5-day precipitation total [in] (flood)
  • CONSECDD    — annual max consecutive dry days               (drought)

Caveats (documented in data/climate_projections.py too): CMRA is a ~6 km
downscaled grid aggregated to counties — a county aggregate, never parcel-scale
precision. CMIP5/RCP (not CMIP6/SSP); RCP4.5/8.5 are treated as low/high analogs
of SSP2-4.5/5-8.5. CMRA carries no native Fire Weather Index, so the drought leg
(consecutive dry days) stands in for the fire/drought hazard until a 12 km ClimRR
FWI layer is added.

Geo level (county vs tract)
---------------------------
``--geo-level county`` (default) builds the bundled county crosswalk. ``--geo-level
tract`` builds a tract crosswalk from CMRA's Tracts layer — but **we do not bundle
it**, because that layer carries **no sub-county signal**: it broadcasts the county
value onto every tract polygon (verified — hundreds of tracts across San Bernardino
/ LA / Maricopa report a single value equal to the county figure). The tract mode
exists for reproducibility and as a drop-in slot; the data module loads a tract
crosswalk if one is present. Genuinely finer resolution requires sampling the LOCA2
~6 km grid at the parcel lat/lon — a separate, network-gated build, not this offline
aggregate crosswalk.

Service
-------
  https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/CMRA_Screening_Data/FeatureServer
  layer 0 = Counties, layer 1 = Census Tracts

Run:  python scripts/build_climate_projections.py                    # LOCA2 county+tract (default)
      python scripts/build_climate_projections.py --sample-state 06  # LOCA2, one state (pilot)
      python scripts/build_climate_projections.py --source cmra      # CMRA county (original)
      python scripts/build_climate_projections.py --source fwi       # append ClimRR fire leg
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import pathlib
import statistics
import struct
import sys
import time
import zipfile

import numpy as np
import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"

SERVICE_BASE = (
    "https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/"
    "CMRA_Screening_Data/FeatureServer"
)
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (climate crosswalk build)"}

# Per geo level: ArcGIS layer id, the id field, its zero-pad width, the value
# written to the geo_level column, and the default output path. The county layer
# is the bundled crosswalk; the tract layer is opt-in and intentionally not
# bundled (it carries no sub-county signal — see module docstring).
GEO_LEVELS: dict[str, dict] = {
    "county": {
        "layer": 0, "id_field": "GEOID", "width": 5, "geo_level": "county",
        "out": _DATA_DIR / "climate_projections.csv", "expected": 3233,
    },
    "tract": {
        "layer": 1, "id_field": "GEOID", "width": 11, "geo_level": "tract",
        "out": _DATA_DIR / "climate_projections_tracts.csv.gz", "expected": 74000,
    },
}

# Hazard metric → output column stem. The CMRA fields follow the pattern
# {PERIOD}_MEAN_{METRIC}, where PERIOD ∈ {HISTORIC, RCP45MID, RCP85MID}.
METRICS = {
    "TMAX95F": "heat_days95",
    "TMAX100F": "heat_days100",
    "PR1IN": "precip_days1in",
    "PRMAX5DAY": "precip_max5day",
    "CONSECDD": "drought_consecdd",
}
# (period prefix, output band suffix)
BANDS = [("HISTORIC", "hist"), ("RCP45MID", "low"), ("RCP85MID", "high")]

# ── LOCA2 source (genuinely sub-county; ensemble-mean grid sampled at tract points) ──
#
# USGS CMIP6-LOCA2 "threshold and extreme event metric" projections — the
# Weighted Multi-Model Mean (WMMM), annual, 1/16° (~6 km) CONUS grid, served on
# ScienceBase (DOI 10.5066/P13OV6GY, keyless). One NetCDF per SSP holds every
# metric as a (time, lat, lon) variable; we cut a historical and a mid-century
# 30-yr window ourselves. Unlike CMRA's tract layer (which broadcasts the county
# value), sampling this grid at each tract's internal point yields real
# sub-county variation. Reading NetCDF needs xarray/netCDF4 — BUILD-ONLY deps,
# imported lazily inside _open_loca2_var so the CMRA path and runtime stay light.
SCIENCEBASE_ITEM_ID = "65cd1ff2d34ef4b119cb3d07"
SCIENCEBASE_ITEM = f"https://www.sciencebase.gov/catalog/item/{SCIENCEBASE_ITEM_ID}"
# Direct file download is the catalog `file/get?name=` route — the item's
# `downloadUri` (manager/download/<id>) serves an HTML app page, not the file,
# and S3 virtual-host URLs are 403. This route returns application/octet-stream.
SCIENCEBASE_FILE_GET = "https://www.sciencebase.gov/catalog/file/get/{iid}"
LOCA2_BAND_SCENARIO = {"low": "ssp245", "high": "ssp585"}  # hist also cut from ssp245
LOCA2_GRID_SUFFIX = "annual_16thdeg_grid.nc"
# WMMM annual-grid filename per scenario (fallback if item-listing resolution fails).
LOCA2_GRID_NAME = "CMIP6-LOCA2_Thresholds_WeightedMultiModelMean.{scen}_1950-2100_" + LOCA2_GRID_SUFFIX


def _sb_file_url(name: str) -> str:
    """Direct ScienceBase download URL for a file by name within the item."""
    return f"{SCIENCEBASE_FILE_GET.format(iid=SCIENCEBASE_ITEM_ID)}?name={requests.utils.quote(name)}"
# output stem → (NetCDF variable, unit divisor or None). Rx5day is mm; the schema
# and breakpoints are in inches, so divide by 25.4.
LOCA2_VARS: dict[str, tuple[str, float | None]] = {
    "heat_days95": ("TXge95F", None),
    "heat_days100": ("TXge100F", None),
    "precip_days1in": ("R1in", None),
    "precip_max5day": ("Rx5day", 25.4),
    "drought_consecdd": ("CDD", None),
}
# CONUS grid bounds (lat_min, lat_max, lon_min, lon_max), negative-west longitude.
LOCA2_BBOX = (23.875, 53.5, -125.5, -66.0)
GAZ_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{yr}_Gazetteer/"


_NETCDF_MAGIC = (b"CDF\x01", b"CDF\x02", b"\x89HDF")


def _is_netcdf(path: pathlib.Path) -> bool:
    with path.open("rb") as f:
        return f.read(4) in _NETCDF_MAGIC


def _download(url: str, dest: pathlib.Path, *, expect_netcdf: bool = False,
              min_size: int = 1024) -> pathlib.Path:
    """Stream a URL to ``dest`` with retry/back-off; skip if already validly cached.

    Guards against silently caching a bad response (e.g. ScienceBase serving an
    HTML app page instead of the file): a cached or freshly downloaded file must
    clear ``min_size`` and, when ``expect_netcdf``, start with NetCDF/HDF5 magic
    bytes — otherwise it is re-fetched / rejected rather than handed to xarray.
    """
    def _valid(p: pathlib.Path) -> bool:
        return (p.exists() and p.stat().st_size >= min_size
                and (not expect_netcdf or _is_netcdf(p)))

    if _valid(dest):
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.0f} MB)", file=sys.stderr)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            with requests.get(url, headers=HEADERS, timeout=120, stream=True) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                if expect_netcdf and "html" in ctype.lower():
                    raise RuntimeError(
                        f"expected a file but got {ctype!r} from {url} — the URL "
                        "likely points at an HTML page, not the download")
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                if not _valid(tmp):
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"downloaded {dest.name} failed validation "
                        f"(size/{'netcdf' if expect_netcdf else 'min-size'} check) from {url}")
                tmp.replace(dest)
            return dest
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return dest


def _resolve_loca2_urls(scenarios: set[str]) -> dict[str, str]:
    """Map each SSP scenario → its WMMM annual-grid download URL.

    Resolves from the live ScienceBase item listing (the opaque download ids can
    change); falls back to the known ids if the listing can't be read.
    """
    urls: dict[str, str] = {}
    try:
        r = requests.get(SCIENCEBASE_ITEM, params={"format": "json"},
                         headers=HEADERS, timeout=60)
        r.raise_for_status()
        for f in r.json().get("files", []):
            name = f.get("name", "")
            if "WeightedMultiModelMean" not in name or not name.endswith(LOCA2_GRID_SUFFIX):
                continue
            for scen in scenarios:
                if f".{scen}_" in name:
                    urls[scen] = _sb_file_url(name)  # catalog file/get, not downloadUri
    except (requests.RequestException, ValueError):
        pass
    for scen in scenarios:
        urls.setdefault(scen, _sb_file_url(LOCA2_GRID_NAME.format(scen=scen)))
    return urls


def _load_gazetteer(kind: str, year: int, cache_dir: pathlib.Path) -> list[dict]:
    """Census Gazetteer internal points → [{geoid, lat, lon, name, state}].

    ``kind`` ∈ {"tracts", "counties"}. Keyless, tab-delimited zip. The
    ``INTPTLONG`` header often carries leading whitespace, so strip field names.
    """
    fname = f"{year}_Gaz_{kind}_national.zip"
    dest = _download(GAZ_BASE.format(yr=year) + fname, cache_dir / fname)
    with zipfile.ZipFile(dest) as zf:
        member = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(member).decode("latin-1")
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    reader.fieldnames = [c.strip() for c in (reader.fieldnames or [])]
    for r in reader:
        try:
            lat = float(r["INTPTLAT"]); lon = float(r["INTPTLONG"])
        except (KeyError, ValueError):
            continue
        rows.append({
            "geoid": str(r.get("GEOID", "")).strip(),
            "lat": lat, "lon": lon,
            "name": (r.get("NAME") or "").strip(),
            "state": (r.get("USPS") or "").strip(),
        })
    return rows


def _window_mean(data3d: np.ndarray, years: np.ndarray, y0: int, y1: int) -> np.ndarray:
    """NaN-aware mean over the [y0, y1] time slice → 2-D (lat, lon) field."""
    mask = (years >= y0) & (years <= y1)
    return np.nanmean(data3d[mask], axis=0)


def _sample_point(lat: float, lon: float, lat_arr: np.ndarray, lon_arr: np.ndarray,
                  field2d: np.ndarray, max_ring: int = 3) -> float | None:
    """Nearest-cell value at (lat, lon); None if out of grid or no nearby data.

    The grid is regular/rectilinear, so the nearest cell is the per-axis nearest
    index. A coastal internal point can land on a masked (NaN) cell; expand a
    small ring to the nearest valid cell before giving up.
    """
    lo_lat, hi_lat, lo_lon, hi_lon = LOCA2_BBOX
    if not (lo_lat <= lat <= hi_lat and lo_lon <= lon <= hi_lon):
        return None
    i = int(np.abs(lat_arr - lat).argmin())
    j = int(np.abs(lon_arr - lon).argmin())
    v = field2d[i, j]
    if np.isfinite(v):
        return float(v)
    # Masked (NaN) nearest cell — a coastal/edge internal point. Fall back to the
    # NEAREST valid cell in an expanding ring (still nearest-neighbour, not an
    # average, which would bias the value).
    for r in range(1, max_ring + 1):
        i0, i1 = max(0, i - r), min(field2d.shape[0], i + r + 1)
        j0, j1 = max(0, j - r), min(field2d.shape[1], j + r + 1)
        window = field2d[i0:i1, j0:j1]
        finite = np.argwhere(np.isfinite(window))
        if finite.size:
            di = finite[:, 0] + i0 - i
            dj = finite[:, 1] + j0 - j
            nearest = finite[np.argmin(di * di + dj * dj)]
            return float(window[nearest[0], nearest[1]])
    return None


def _row_for(geoid: str, level: str, name: str, state: str,
             values: dict[str, dict[str, float | None]]) -> dict:
    """Assemble one output row in the shared schema from sampled per-metric values."""
    out = {"geoid": geoid, "geo_level": level, "county_name": name, "state": state}
    for stem in METRICS.values():
        for _, band in BANDS:
            v = values.get(stem, {}).get(band)
            out[f"{stem}_{band}"] = "" if v is None else round(float(v), 3)
    return out


def sample_loca2_rows(
    fields: dict[str, dict[str, np.ndarray]],
    lat_arr: np.ndarray,
    lon_arr: np.ndarray,
    tracts: list[dict],
    counties_meta: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """Pure core: sample tract internal points, aggregate counties as tract means.

    ``fields[stem][band]`` is a 2-D (lat, lon) field (NaN = no data), already
    unit-converted. Returns (county_rows, tract_rows) in the shared schema. The
    county value is the mean of its tracts' samples, so tract→county is coherent.
    """
    tract_rows: list[dict] = []
    # county fips → stem → band → list of tract sample values
    buckets: dict[str, dict[str, dict[str, list[float]]]] = {}
    for t in tracts:
        geoid = t["geoid"].zfill(11)
        cfips = geoid[:5]
        vals: dict[str, dict[str, float | None]] = {}
        for stem, bands in fields.items():
            vals[stem] = {}
            for band, field2d in bands.items():
                v = _sample_point(t["lat"], t["lon"], lat_arr, lon_arr, field2d)
                vals[stem][band] = v
                if v is not None:
                    buckets.setdefault(cfips, {}).setdefault(stem, {}) \
                        .setdefault(band, []).append(v)
        meta = counties_meta.get(cfips, {})
        tract_rows.append(_row_for(geoid, "tract", meta.get("name", ""),
                                   meta.get("state", ""), vals))

    county_rows: list[dict] = []
    for cfips, stems in buckets.items():
        vals = {stem: {band: (sum(xs) / len(xs)) for band, xs in bands.items()}
                for stem, bands in stems.items()}
        meta = counties_meta.get(cfips, {})
        county_rows.append(_row_for(cfips, "county", meta.get("name", ""),
                                    meta.get("state", ""), vals))

    tract_rows.sort(key=lambda r: r["geoid"])
    county_rows.sort(key=lambda r: r["geoid"])
    return county_rows, tract_rows


def _loca2_coord(ds, names):
    return next(c for c in names if c in ds.coords or c in ds.variables)


def _to_neg_west(lon: np.ndarray) -> np.ndarray:
    """Normalize a longitude axis to the −180..180 (negative-west) convention.

    LOCA2 stores longitude as 0–360 (CONUS ≈ 234.5..293.5); the tract internal
    points and ``LOCA2_BBOX`` are negative-west, so without this every CONUS
    point's nearest column collapses to the 0-360 western edge (an ocean NaN
    cell) and all samples come back empty. The grid is wholly western-hemisphere,
    so the shift stays monotonic (→ −125.5..−66.5)."""
    return np.where(lon > 180.0, lon - 360.0, lon)


def _read_var_windows(ds, var: str, windows: dict[str, tuple[int, int]]) -> dict:
    """Per-band window means for one variable from an OPEN dataset, computed
    lazily (only the in-window timesteps load — never the full time series)."""
    years = ds["time"].dt.year
    da = ds[var]
    out = {}
    for band, (y0, y1) in windows.items():
        idx = np.nonzero(((years >= y0) & (years <= y1)).values)[0]
        out[band] = da.isel(time=idx).mean("time", skipna=True).values
    return out


def _open_loca2_var(path: pathlib.Path, var: str,
                    windows: dict[str, tuple[int, int]]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Read one variable's window means from a LOCA2 NetCDF. Build-only (xarray).

    A thin single-variable convenience (used by tests). The build uses
    ``compute_loca2_fields``, which opens each scenario file once.
    """
    import xarray as xr  # build-only dependency

    with xr.open_dataset(path, decode_times=True) as ds:
        lat = ds[_loca2_coord(ds, ("lat", "latitude", "y"))].values
        lon = _to_neg_west(ds[_loca2_coord(ds, ("lon", "longitude", "x"))].values)
        out = _read_var_windows(ds, var, windows)
    return lat, lon, out


def compute_loca2_fields(
    cache_dir: pathlib.Path, urls: dict[str, str],
    hist_window: tuple[int, int], mid_window: tuple[int, int],
) -> tuple[dict[str, dict[str, np.ndarray]], np.ndarray, np.ndarray]:
    """Download the WMMM grids and reduce to per-metric {hist, low, high} fields.

    Each scenario NetCDF is opened ONCE; every variable's window means are read
    lazily from that single handle (no per-variable re-open, no loading the full
    ~2.6 GB time series into memory)."""
    import xarray as xr  # build-only dependency

    paths = {scen: _download(url, cache_dir / f"loca2_{scen}_{LOCA2_GRID_SUFFIX}",
                             expect_netcdf=True, min_size=10 << 20)
             for scen, url in urls.items()}
    # hist + low come from ssp245; high from ssp585.
    scen_windows = {
        "ssp245": {"hist": hist_window, "low": mid_window},
        "ssp585": {"high": mid_window},
    }
    fields: dict[str, dict[str, np.ndarray]] = {stem: {} for stem in LOCA2_VARS}
    lat_arr = lon_arr = None
    for scen, windows in scen_windows.items():
        with xr.open_dataset(paths[scen], decode_times=True) as ds:
            if lat_arr is None:
                lat_arr = ds[_loca2_coord(ds, ("lat", "latitude", "y"))].values
                lon_arr = _to_neg_west(ds[_loca2_coord(ds, ("lon", "longitude", "x"))].values)
            for stem, (var, divisor) in LOCA2_VARS.items():
                for band, field2d in _read_var_windows(ds, var, windows).items():
                    fields[stem][band] = field2d if divisor is None else field2d / divisor
    return fields, lat_arr, lon_arr


def build_loca2(
    cache_dir: pathlib.Path, hist_window: tuple[int, int], mid_window: tuple[int, int],
    gaz_year: int, sample_state: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Full LOCA2 build → (county_rows, tract_rows) in the shared schema."""
    tracts = _load_gazetteer("tracts", gaz_year, cache_dir)
    counties = _load_gazetteer("counties", gaz_year, cache_dir)
    counties_meta = {c["geoid"].zfill(5): c for c in counties}
    if sample_state:
        st = sample_state.zfill(2)
        tracts = [t for t in tracts if t["geoid"].zfill(11).startswith(st)]
    urls = _resolve_loca2_urls(set(LOCA2_BAND_SCENARIO.values()))
    fields, lat_arr, lon_arr = compute_loca2_fields(cache_dir, urls, hist_window, mid_window)
    return sample_loca2_rows(fields, lat_arr, lon_arr, tracts, counties_meta)


# ── FWI source (Argonne ClimRR Fire Weather Index; augments the crosswalks) ──
#
# Argonne National Laboratory's Climate Risk & Resilience Portal (ClimRR)
# publishes a 12 km dynamically-downscaled (WRF) Fire Weather Index as keyless
# CSVs on Box. Unlike the CMIP6-LOCA2 legs, ClimRR provides a SINGLE RCP8.5
# pathway with Historical / Mid-Century (2045–2054) / End-Century horizons — no
# RCP4.5 — so the mid-century FWI is applied to BOTH the low and high bands (the
# fire leg contributes no scenario spread; see data/climate_projections.py).
#
# The FWI CSV is keyed by ``Crossmodel`` grid-cell id (R{row}C{col}), not by lat/
# lon or FIPS. The companion GridCellsShapefile gives each cell's polygon in Web
# Mercator (EPSG:3857); we take each cell's bbox centre, convert to WGS84 with the
# same formula as ``housing_label.utils.webmercator_to_wgs84`` (inlined to keep
# this build script decoupled from the runtime package), and join grid cells to
# census geography by sampling the NEAREST cell at each tract's internal point —
# the same nearest-point pattern the LOCA2 source uses, but with a lat/lon spatial
# hash instead of a regular grid (ClimRR's grid is regular only in its native WRF
# projection). County = the mean of its tracts, so tract→county stays coherent.
# Pure stdlib .shp/.dbf parsing — no geospatial dependency.
#
# This source AUGMENTS the existing county/tract crosswalks in place, appending
# fire_fwi_{hist,low,high} columns; run it after a base (loca2/cmra) build.
FWI_SHARED_NAME = "hmkkgkrkzxxocfe9kpgrzk2gfc4gizp8"
FWI_BOX_DL = "https://app.box.com/index.php?rm=box_download_shared_file"
FWI_CSV_FILE_ID = "f_2070164260652"        # Fire Weather Index (FWI) Classes.csv
FWI_GRID_FILE_ID = "f_1055124005369"       # GridCellsShapefile.zip
# ClimRR FWI CSV horizon column → output band. Mid-century (RCP8.5) drives both
# the low and high bands (single-scenario source).
FWI_HORIZON_COL = {"hist": "FWI_Bins_Hist_95", "mid": "FWI_Bins_MidC_95"}
FWI_STEM = "fire_fwi"
FWI_BANDS = [("hist", "hist"), ("mid", "low"), ("mid", "high")]  # (horizon, out band)
_WEBMERC_R = 20037508.342789244


def _fwi_box_url(file_id: str) -> str:
    return f"{FWI_BOX_DL}&shared_name={FWI_SHARED_NAME}&file_id={file_id}"


def _webmerc_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """EPSG:3857 x,y → WGS84 (lon, lat). Mirrors housing_label.utils."""
    import math
    lon = x * 180.0 / _WEBMERC_R
    lat = math.degrees(math.atan(math.exp(y * math.pi / _WEBMERC_R))) * 2.0 - 90.0
    return lon, lat


def _parse_grid_cells(zip_bytes: bytes) -> dict[str, tuple[float, float]]:
    """ClimRR GridCellsShapefile.zip → {Crossmodel: (lat, lon)} cell centres.

    Pure-stdlib .shp (polygon bounding-box centres) + .dbf (Crossmodel) parsing.
    The shapefile is EPSG:3857, so each centre is reprojected to WGS84."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    shp_name = next(n for n in zf.namelist() if n.lower().endswith(".shp"))
    dbf_name = next(n for n in zf.namelist() if n.lower().endswith(".dbf"))
    shp = zf.read(shp_name)
    # .shp: 100-byte header, then records of [big-endian num,len][little-endian body].
    centres: list[tuple[float, float] | None] = []
    pos = 100
    while pos + 8 <= len(shp):
        _num, clen = struct.unpack(">ii", shp[pos:pos + 8])
        pos += 8
        stype = struct.unpack("<i", shp[pos:pos + 4])[0]
        if stype == 5:  # polygon: bbox is 4 doubles after the 4-byte type
            xmin, ymin, xmax, ymax = struct.unpack("<4d", shp[pos + 4:pos + 36])
            lon, lat = _webmerc_to_lonlat((xmin + xmax) / 2, (ymin + ymax) / 2)
            centres.append((lat, lon))
        else:
            centres.append(None)
        pos += clen * 2
    # .dbf: header (record count, header/record length) then field descriptors.
    dbf = zf.read(dbf_name)
    numrec, hdrlen, reclen = struct.unpack("<xxxxIHH", dbf[:12])
    fields, off, o = [], {}, 1
    fpos = 32
    while dbf[fpos:fpos + 1] != b"\r":
        name = dbf[fpos:fpos + 11].split(b"\x00")[0].decode("latin-1")
        flen = dbf[fpos + 16]
        fields.append((name, flen))
        off[name] = (o, flen)
        o += flen
        fpos += 32
    cs, cl = off["Crossmodel"]
    out: dict[str, tuple[float, float]] = {}
    for i in range(numrec):
        base = hdrlen + i * reclen
        cm = dbf[base + cs:base + cs + cl].decode("latin-1").strip()
        centre = centres[i] if i < len(centres) else None
        if cm and centre is not None:
            out[cm] = centre
    return out


def _load_fwi_values(csv_bytes: bytes) -> dict[str, dict[str, float]]:
    """ClimRR FWI Classes CSV → {Crossmodel: {horizon: 95th-pct FWI}}."""
    out: dict[str, dict[str, float]] = {}
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("latin-1")))
    for row in reader:
        cm = (row.get("Crossmodel") or "").strip()
        if not cm:
            continue
        vals: dict[str, float] = {}
        for horizon, col in FWI_HORIZON_COL.items():
            try:
                vals[horizon] = float(row[col])
            except (KeyError, TypeError, ValueError):
                pass
        if vals:
            out[cm] = vals
    return out


class _CellIndex:
    """Nearest-cell lookup over ClimRR grid centres via a 0.5° lat/lon hash."""

    _BIN = 0.5

    def __init__(self, cells: list[tuple[str, float, float]]):
        import math
        self._math = math
        self._cells = cells
        self._grid: dict[tuple[int, int], list[int]] = {}
        for idx, (_cm, lat, lon) in enumerate(cells):
            key = (round(lat / self._BIN), round(lon / self._BIN))
            self._grid.setdefault(key, []).append(idx)

    def nearest(self, lat: float, lon: float, max_ring: int = 6) -> str | None:
        cos = self._math.cos(self._math.radians(lat))
        bi, bj = round(lat / self._BIN), round(lon / self._BIN)
        best, best_d = None, 1e18
        r = 0
        while best is None and r <= max_ring:
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if r > 0 and max(abs(di), abs(dj)) != r:
                        continue  # only the new ring, not the filled interior
                    for idx in self._grid.get((bi + di, bj + dj), ()):
                        _cm, cla, clo = self._cells[idx]
                        d = (cla - lat) ** 2 + ((clo - lon) * cos) ** 2
                        if d < best_d:
                            best_d, best = d, idx
            r += 1
        return self._cells[best][0] if best is not None else None


def sample_fwi_rows(
    cell_ll: dict[str, tuple[float, float]],
    fwi: dict[str, dict[str, float]],
    tracts: list[dict],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Pure core: sample each tract's nearest FWI cell; county = mean of tracts.

    Returns (county_fire, tract_fire), each ``geoid -> {out_band: value}`` in the
    fire_fwi_{hist,low,high} schema (out band via FWI_BANDS)."""
    cells = [(cm, ll[0], ll[1]) for cm, ll in cell_ll.items() if cm in fwi]
    index = _CellIndex(cells)
    tract_fire: dict[str, dict[str, float]] = {}
    buckets: dict[str, dict[str, list[float]]] = {}
    for t in tracts:
        geoid = t["geoid"].zfill(11)
        cm = index.nearest(t["lat"], t["lon"])
        if cm is None:
            continue
        vals = fwi[cm]
        row = {out: vals[hz] for hz, out in FWI_BANDS if hz in vals}
        if not row:
            continue
        tract_fire[geoid] = row
        cbucket = buckets.setdefault(geoid[:5], {})
        for out, v in row.items():
            cbucket.setdefault(out, []).append(v)
    county_fire = {
        cfips: {out: sum(xs) / len(xs) for out, xs in bands.items()}
        for cfips, bands in buckets.items()
    }
    return county_fire, tract_fire


def _augment_with_fire(path: pathlib.Path, fire: dict[str, dict[str, float]],
                       width: int) -> tuple[int, int]:
    """Append fire_fwi_{hist,low,high} columns to an existing crosswalk in place.

    Reads every row of the county/tract CSV (gzip-aware), fills the fire columns
    from ``fire`` keyed by the row's geoid (blank where the ClimRR grid doesn't
    cover it, e.g. HI/PR), and rewrites. Returns (rows, rows_with_fire)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        reader = csv.DictReader(f)
        base_cols = list(reader.fieldnames or [])
        rows = list(reader)
    fire_cols = [f"{FWI_STEM}_{b}" for b in ("hist", "low", "high")]
    cols = base_cols + [c for c in fire_cols if c not in base_cols]
    n_fire = 0
    for row in rows:
        vals = fire.get(str(row["geoid"]).strip().zfill(width))
        if vals:
            n_fire += 1
        for b in ("hist", "low", "high"):
            v = (vals or {}).get(b)
            row[f"{FWI_STEM}_{b}"] = "" if v is None else round(float(v), 3)
    with opener(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows), n_fire


def _print_fwi_quantiles(county_fire: dict[str, dict[str, float]]) -> None:
    """National county quantiles of the mid-century (low band) FWI — the anchors
    for the fire_fwi scoring breakpoints in data/climate_projections.py."""
    vals = sorted(v["low"] for v in county_fire.values() if "low" in v)
    if not vals:
        return
    q = statistics.quantiles(vals, n=100)
    picks = "  ".join(f"p{p}={q[p - 1]:.1f}" for p in (5, 25, 50, 75, 90, 95))
    print(f"\nFire (FWI) national county quantiles [low band, mid-century]:\n"
          f"  n={len(vals)} min={vals[0]:.1f} max={vals[-1]:.1f}  {picks}",
          file=sys.stderr)


def _run_fwi(args) -> int:
    """FWI source: download ClimRR FWI + grid, join to census geography, and
    append the fire leg to the existing county & tract crosswalks."""
    cache_dir = pathlib.Path(
        args.cache_dir or (pathlib.Path(__file__).resolve().parents[1] / ".fwi_cache"))
    county_out = pathlib.Path(args.out) if args.out else GEO_LEVELS["county"]["out"]
    tract_out = pathlib.Path(args.tract_out) if args.tract_out else GEO_LEVELS["tract"]["out"]
    if not county_out.exists() or not tract_out.exists():
        print("ERROR: base crosswalks not found — run a loca2/cmra build first so the\n"
              f"       fire leg has rows to augment ({county_out}, {tract_out}).",
              file=sys.stderr)
        return 1

    print("FWI build (Argonne ClimRR, 12 km RCP8.5). Downloads ~12 MB from Box +\n"
          f"the Census Gazetteer, then augments the crosswalks. Cache: {cache_dir}\n",
          file=sys.stderr)
    csv_path = _download(_fwi_box_url(FWI_CSV_FILE_ID), cache_dir / "climrr_fwi_classes.csv",
                         min_size=1 << 20)
    grid_path = _download(_fwi_box_url(FWI_GRID_FILE_ID), cache_dir / "climrr_gridcells.zip",
                          min_size=1 << 20)
    cell_ll = _parse_grid_cells(grid_path.read_bytes())
    fwi = _load_fwi_values(csv_path.read_bytes())
    print(f"  {len(cell_ll)} grid cells, {len(fwi)} with FWI values", file=sys.stderr)

    tracts = _load_gazetteer("tracts", args.gaz_year, cache_dir)
    if args.sample_state:
        st = args.sample_state.zfill(2)
        tracts = [t for t in tracts if t["geoid"].zfill(11).startswith(st)]
    county_fire, tract_fire = sample_fwi_rows(cell_ll, fwi, tracts)

    c_rows, c_fire = _augment_with_fire(county_out, county_fire, 5)
    t_rows, t_fire = _augment_with_fire(tract_out, tract_fire, 11)
    _print_fwi_quantiles(county_fire)
    print(f"\nAugmented {c_fire}/{c_rows} counties → {county_out}\n"
          f"Augmented {t_fire}/{t_rows} tracts → {tract_out}", file=sys.stderr)
    return 0


def _cmra_fields(id_field: str) -> list[str]:
    fields = [id_field, "CountyName", "StateAbbr"]
    for metric in METRICS:
        for period, _ in BANDS:
            fields.append(f"{period}_MEAN_{metric}")
    return fields


def _out_columns() -> list[str]:
    cols = ["geoid", "geo_level", "county_name", "state"]
    for stem in METRICS.values():
        for _, band in BANDS:
            cols.append(f"{stem}_{band}")
    return cols


def _layer_max_record_count(service: str, default: int = 2000) -> int:
    """The layer's server-enforced maxRecordCount (default if metadata fails)."""
    try:
        r = requests.get(service, params={"f": "json"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        return int(r.json().get("maxRecordCount") or default)
    except (requests.RequestException, ValueError, TypeError):
        return default


def fetch_features(service: str, id_field: str) -> list[dict]:
    """Page through every feature in a layer, newest ArcGIS pagination."""
    fields = ",".join(_cmra_fields(id_field))
    rows: list[dict] = []
    # Cap the page size at the layer's maxRecordCount so the server can't
    # silently return fewer rows than requested.
    page = min(2000, _layer_max_record_count(service))
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "returnGeometry": "false",
            "orderByFields": id_field,
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        for attempt in range(4):
            try:
                r = requests.get(f"{service}/query", params=params,
                                 headers=HEADERS, timeout=90)
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        feats = data.get("features", [])
        if not feats:
            break
        rows.extend(f["attributes"] for f in feats)
        if not data.get("exceededTransferLimit"):
            break
        # Advance by the number actually returned (the server may cap a page
        # below the requested size), never by the requested page size.
        offset += len(feats)
    return rows


def to_output_row(attrs: dict, level: dict) -> dict | None:
    width = level["width"]
    geoid = str(attrs.get(level["id_field"]) or "").strip().zfill(width)
    if not geoid or len(geoid) != width:
        return None
    out = {
        "geoid": geoid,
        "geo_level": level["geo_level"],
        "county_name": (attrs.get("CountyName") or "").strip(),
        "state": (attrs.get("StateAbbr") or "").strip(),
    }
    for metric, stem in METRICS.items():
        for period, band in BANDS:
            val = attrs.get(f"{period}_MEAN_{metric}")
            out[f"{stem}_{band}"] = "" if val is None else round(float(val), 3)
    return out


def _print_quantiles(rows: list[dict]) -> None:
    """Print national quantiles of the low/high bands to anchor score breakpoints."""
    qs = [0.05, 0.25, 0.50, 0.75, 0.90, 0.95]
    print("\nNational quantiles (anchors for scoring breakpoints):", file=sys.stderr)
    for stem in METRICS.values():
        for band in ("low", "high"):
            vals = sorted(float(r[f"{stem}_{band}"]) for r in rows
                          if r[f"{stem}_{band}"] != "")
            if not vals:
                continue
            quants = statistics.quantiles(vals, n=100)
            picks = [quants[int(q * 100) - 1] for q in qs]
            joined = "  ".join(f"p{int(q*100)}={v:.1f}" for q, v in zip(qs, picks))
            print(f"  {stem+'_'+band:<26} {joined}", file=sys.stderr)


def _write_rows(rows: list[dict], out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out_path.suffix == ".gz" else open
    with opener(out_path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_out_columns())
        w.writeheader()
        w.writerows(rows)


def _window(spec: str) -> tuple[int, int]:
    y0, y1 = spec.split("-")
    return int(y0), int(y1)


def _run_loca2(args) -> int:
    """LOCA2 source: sample the WMMM ~6 km grid at tract internal points and
    write BOTH the county and tract crosswalks (county = mean of its tracts)."""
    cache_dir = pathlib.Path(
        args.cache_dir or (pathlib.Path(__file__).resolve().parents[1] / ".loca2_cache"))
    print("LOCA2 build (USGS CMIP6-LOCA2 WMMM). This downloads ~2.6 GB per SSP and\n"
          "needs xarray/netCDF4 (the project's [build] extra) — run on a capable\n"
          f"machine, not a constrained sandbox. Cache: {cache_dir}\n", file=sys.stderr)
    county_rows, tract_rows = build_loca2(
        cache_dir, _window(args.hist_window), _window(args.mid_window),
        args.gaz_year, sample_state=args.sample_state,
    )
    county_out = pathlib.Path(args.out) if args.out else GEO_LEVELS["county"]["out"]
    tract_out = pathlib.Path(args.tract_out) if args.tract_out else GEO_LEVELS["tract"]["out"]
    if not args.sample_state and len(county_rows) < GEO_LEVELS["county"]["expected"] * 0.9:
        print(f"WARNING: only {len(county_rows)} counties (expected ~3233).", file=sys.stderr)
    _write_rows(county_rows, county_out)
    _write_rows(tract_rows, tract_out)
    _print_quantiles(county_rows)
    print(f"\nWrote {len(county_rows)} counties → {county_out}\n"
          f"Wrote {len(tract_rows)} tracts → {tract_out}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("loca2", "cmra", "fwi"), default="loca2",
                    help="loca2 (sub-county, ensemble grid; default), cmra (county "
                         "aggregate), or fwi (ClimRR Fire Weather Index — augments the "
                         "existing crosswalks with the fire leg)")
    ap.add_argument("--geo-level", choices=sorted(GEO_LEVELS), default="county",
                    help="[cmra only] county (bundled) or tract (opt-in, not bundled)")
    ap.add_argument("--service-base", default=SERVICE_BASE,
                    help="[cmra only] CMRA FeatureServer base URL")
    ap.add_argument("--out", default=None, help="county output path (defaults per source)")
    ap.add_argument("--tract-out", default=None, help="[loca2] tract output path")
    ap.add_argument("--cache-dir", default=None, help="[loca2] download cache directory")
    ap.add_argument("--hist-window", default="1991-2020", help="[loca2] baseline window")
    ap.add_argument("--mid-window", default="2040-2069", help="[loca2] mid-century window")
    ap.add_argument("--gaz-year", type=int, default=2023, help="[loca2] Census Gazetteer vintage")
    ap.add_argument("--sample-state", default=None,
                    help="[loca2] build only this 2-digit state FIPS (pilot validation)")
    args = ap.parse_args()

    if args.source == "loca2":
        return _run_loca2(args)
    if args.source == "fwi":
        return _run_fwi(args)

    level = GEO_LEVELS[args.geo_level]
    service = f"{args.service_base}/{level['layer']}"
    out_path = pathlib.Path(args.out) if args.out else level["out"]

    if args.geo_level == "tract":
        print("NOTE: CMRA's Tracts layer carries NO sub-county signal — it broadcasts\n"
              "      the county value onto every tract. This output is intentionally\n"
              "      NOT bundled; it exists only for reproducibility / a drop-in slot.\n"
              "      Genuinely finer resolution needs LOCA2 ~6 km grid sampling.\n",
              file=sys.stderr)

    print(f"Fetching {args.geo_level} features from {service} …", file=sys.stderr)
    attrs = fetch_features(service, level["id_field"])
    rows = [r for r in (to_output_row(a, level) for a in attrs) if r]
    rows.sort(key=lambda r: r["geoid"])
    expected = level["expected"]
    if len(rows) < expected * 0.9:
        print(f"WARNING: only {len(rows)} {args.geo_level} rows fetched "
              f"(expected ~{expected}).", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out_path.suffix == ".gz" else open
    with opener(out_path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_out_columns())
        w.writeheader()
        w.writerows(rows)

    _print_quantiles(rows)
    print(f"\nWrote {len(rows)} {args.geo_level} rows → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
