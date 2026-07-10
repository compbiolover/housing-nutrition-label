#!/usr/bin/env python3
"""Build the bundled median-home-value crosswalk (tract + county + national).

Writes ``src/housing_label/data/home_value.csv.gz`` — the Census median
owner-occupied home value (ACS table **B25077**) at three geographies:

  - **tract**    (GEO_ID ``1400000US<11-digit>``) — the neighborhood median
  - **county**   (GEO_ID ``0500000US<5-digit>``)  — county fallback
  - **national** (GEO_ID ``0100000US`` → ``00000``) — last-resort fallback

The label auto-fills a home value when the user doesn't type one (it feeds the
Infrastructure fiscal ratio and the dollar disaster-loss figures). County median
alone reads far too low for a home in an expensive neighborhood, so this adds the
**tract** median: still a neighborhood typical (open Census data, not a per-parcel
AVM), but much closer than the county figure. ``data/home_value.py`` resolves
tract -> county -> national.

Source (keyless, free, public — bulk files, no API key)
-------------------------------------------------------
The ACS table-based **Summary File** publishes one pipe-delimited ``.dat`` per
table, keyless (the Census Data API needs a key; these bulk files do not). We fetch
just ``b25077`` and keep the tract / county / national rows. The estimate is the
``*_E001`` column.

Caveats
-------
B25077 is a *median* owner-occupied value, so it is a neighborhood typical, not a
specific property's value — an all-rental tract has no value and falls back to the
county. ACS 5-year estimates carry a margin of error (largest in small tracts).
A user-entered value always overrides the auto-fill.

Run:  python scripts/build_home_value.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import pathlib
import sys
import time

import requests

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "housing_label" / "data"
HEADERS = {"User-Agent": "housing-nutrition-label/0.1 (home-value crosswalk build)"}

ACS_YEAR = 2023
_SF = (f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_YEAR}"
       "/table-based-SF/data/5YRData")
VALUE_URL = f"{_SF}/acsdt5y{ACS_YEAR}-b25077.dat"   # median home value

TRACT_PREFIX = "1400000US"
COUNTY_PREFIX = "0500000US"
NATION_GEOID = "0100000US"
NATIONAL_OUT = "00000"

OUT_COLUMNS = ["geoid", "geo_level", "median_value"]
OUT_PATH = _DATA_DIR / "home_value.csv.gz"


def _download(url: str, dest: pathlib.Path, *, min_size: int = 1 << 20) -> pathlib.Path:
    """Stream a URL to ``dest`` with retry/back-off; reuse a valid cached file.

    Downloads into a ``.part`` sidecar and atomically renames on success, so an
    interrupted run never leaves a truncated file that looks like a valid cache."""
    if dest.exists() and dest.stat().st_size >= min_size:
        print(f"  cached {dest.name} ({dest.stat().st_size/1e6:.0f} MB)", file=sys.stderr)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(4):
        try:
            with requests.get(url, headers=HEADERS, timeout=300, stream=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)            # atomic: only a complete file becomes the cache
            return dest
        except requests.RequestException as exc:
            print(f"  attempt {attempt+1} failed: {exc}", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return dest


def _parse(path: pathlib.Path) -> dict[str, float]:
    """GEO_ID -> median value for tract / county / national rows; jam values → skipped."""
    keep_prefix = (TRACT_PREFIX, COUNTY_PREFIX)
    out: dict[str, float] = {}
    with path.open(encoding="latin-1") as f:
        header = f.readline().rstrip("\n").split("|")
        est_cols = [h for h in header if h.endswith("_E001")]
        if not est_cols:
            raise SystemExit(f"No *_E001 estimate column in {path.name}")
        vi = header.index(est_cols[0])
        for line in f:
            parts = line.rstrip("\n").split("|")
            geoid = parts[0]
            if not (geoid == NATION_GEOID or geoid.startswith(keep_prefix)):
                continue
            try:
                v = float(parts[vi])
            except (ValueError, IndexError):
                continue
            if v > 0:                       # ACS suppression jams are large negatives
                out[geoid] = v
    return out


def _geo_level(geo_id: str) -> str:
    if geo_id == NATION_GEOID:
        return "us"          # shared national geo_level (matches data/home_value.py)
    return "tract" if geo_id.startswith(TRACT_PREFIX) else "county"


def _norm_geoid(geo_id: str) -> str:
    if geo_id == NATION_GEOID:
        return NATIONAL_OUT
    if geo_id.startswith(TRACT_PREFIX):
        return geo_id[len(TRACT_PREFIX):]
    return geo_id[len(COUNTY_PREFIX):]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=str(_DATA_DIR.parent.parent.parent / ".home_value_cache"),
                    help="download cache dir (default: repo .home_value_cache)")
    args = ap.parse_args()
    cache = pathlib.Path(args.cache)

    print(f"Downloading ACS {ACS_YEAR} B25077 (median home value) …", file=sys.stderr)
    path = _download(VALUE_URL, cache / f"acsdt5y{ACS_YEAR}-b25077.dat")
    values = _parse(path)

    rows = []
    counts = {"tract": 0, "county": 0, "us": 0}
    for geo_id, v in values.items():
        level = _geo_level(geo_id)
        counts[level] += 1
        rows.append({"geoid": _norm_geoid(geo_id), "geo_level": level,
                     "median_value": round(v)})
    # tract, then county, then national — deterministic order
    order = {"tract": 0, "county": 1, "us": 2}
    rows.sort(key=lambda r: (order[r["geo_level"]], r["geoid"]))

    with gzip.open(OUT_PATH, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUT_PATH.relative_to(_DATA_DIR.parent.parent.parent)} — "
          f"{counts['tract']:,} tracts, {counts['county']:,} counties, "
          f"{counts['us']} national ({OUT_PATH.stat().st_size/1e6:.1f} MB)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
