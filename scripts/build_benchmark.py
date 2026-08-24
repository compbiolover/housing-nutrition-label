#!/usr/bin/env python3
"""Fetch the accuracy benchmark: addresses whose true construction facts are known.

Why this exists
---------------
The label has 900+ tests asserting the code does what it says. Not one of them
asserts the *output matches the world*, and every buyer conversation in
``research/monetization-research.md`` opens with that question. This script
assembles the yardstick; ``scripts/measure_accuracy.py`` reads it.

Ground truth comes from the Cook County Assessor, for the same reason the first
adapter does: it is the only free source in the country publishing year built,
floor area, exterior wall, basement type and condition for a real parcel. Each
row is one address the scorer can be pointed at, plus what the county says is
actually standing there.

Why the output is NOT committed
-------------------------------
Cook County's terms provide the data "AS IS" and grant no explicit right to
redistribute a dataset (``cookcountyil.gov/terms-use``), and
``research/parcel-level-data-research.md`` records that assessors commonly assert
rights in the compilation even where the facts are public record. So the
benchmark is fetched on demand into a gitignored directory and never enters the
repository; only the *measurements* taken from it are committed.

That costs exact byte-level reproducibility — the county refreshes bi-weekly, so
a re-run months later is a different sample. The measurement output records the
fetch date, the row count and a digest of the sample so the difference is visible
rather than silent, which is the honest version of the trade.

Sampling
--------
Evenly-spaced offsets through the latest assessment year rather than the first N
rows. PINs are ordered by township, so the first N would all be one corner of the
county and the "national" accuracy number would really be a statement about
Barrington. Even offsets spread the sample across every township in Cook.

Rows without a street address, coordinates, or a usable year built are dropped:
they cannot be scored by address, or there is nothing to be right or wrong about.

Run:  python scripts/build_benchmark.py --rows 200
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import pathlib
import sys
import time
from datetime import date

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("build_benchmark")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_DIR = _ROOT / ".accuracy_cache"
BENCHMARK = CACHE_DIR / "benchmark.csv"

CAMA_URL = "https://datacatalog.cookcountyil.gov/resource/x54s-btds.json"
PARCEL_URL = ("https://gis.cookcountyil.gov/traditional/rest/services"
              "/CookViewer3Parcels/MapServer/0/query")

TIMEOUT = 90
PARCEL_BATCH = 40          # PINs per ArcGIS IN-clause; keeps the URL under limits
CAMA_BATCH = 40            # PINs per Socrata IN-clause, same reason
HEADERS = {"User-Agent": "housing-nutrition-label (accuracy benchmark build)"}

# The columns the label can actually be graded on. Everything else the county
# publishes is not an input to any dimension, so getting it right or wrong would
# not be a fact about the label.
FIELDS = ["year_built", "sqft", "stories", "construction", "foundation", "condition"]


def _fetch(url: str, params: dict, attempts: int = 4):
    """GET with backoff. Returns None once the attempts are spent.

    The sample is built from a few hundred sequential requests against a free
    public portal, so a transient read timeout is expected rather than
    exceptional. Without this one slow response discards every request made
    before it, which is both a waste of the portal's bandwidth and ours.
    """
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if i == attempts - 1:
                log.warning("  giving up on a request after %d attempts: %s",
                            attempts, exc)
                return None
            time.sleep(2 ** i)          # 1s, 2s, 4s
    return None


def _latest_year() -> str:
    got = _fetch(CAMA_URL, {"$select": "max(year)"})
    if got is None:
        raise SystemExit("could not reach the county portal to find the latest "
                         "assessment year; try again later")
    return str((got or [{}])[0].get("max_year", "")).split(".")[0]


def _cama_sample(year: str, rows: int) -> list[dict]:
    """Evenly-spaced rows from the latest assessment year."""
    # Before the network call: an unusable argument should not cost a request.
    if rows < 1:
        raise SystemExit(f"--rows must be at least 1 (got {rows})")
    got = _fetch(CAMA_URL, {"$select": "count(*)", "$where": f"year='{year}'"})
    if got is None:
        raise SystemExit(f"could not reach the county portal to size assessment "
                         f"year {year}; try again later")
    total = int((got or [{}])[0].get("count", 0))
    if total <= 0:
        raise SystemExit(f"no rows for assessment year {year}")
    log.info("Assessment year %s has %d parcels; sampling %d.", year, total, rows)

    step = max(1, total // rows)
    seen: list[str] = []
    dropped = 0
    for i in range(rows):
        got = _fetch(CAMA_URL, {
            "$select": "pin", "$where": f"year='{year}'",
            "$order": "pin", "$limit": "1", "$offset": str(i * step),
        })
        if got is None:
            # One unreachable offset is a missing sample, not a failed build. It
            # is counted and reported rather than silently absorbed, because a
            # sample that quietly shrank is a different sample.
            dropped += 1
        else:
            pin = (got[0].get("pin") if got else None)
            if pin and pin not in seen:
                seen.append(pin)
        if (i + 1) % 25 == 0:
            log.info("  sampled %d/%d", i + 1, rows)
        time.sleep(0.05)          # polite to a free public portal
    if dropped:
        log.warning("  %d of %d sample offsets were unreachable and skipped.",
                    dropped, rows)
    return _primary_cards(year, seen)


def _primary_cards(year: str, pins: list[str]) -> list[dict]:
    """The one card per PIN that the runtime adapter would read.

    Sampling by row offset lands on an arbitrary card, and a PIN can carry several
    (a coach house, a second improvement). The adapter takes ``year DESC, card
    ASC`` — the newest year's lowest-numbered card — so truth has to be drawn the
    same way. Otherwise a multi-card parcel is graded against a card the label was
    never going to read, and the disagreement is scored as the label's error.

    The year is already pinned to the newest by the caller, so ordering by card
    within it and keeping the first per PIN reproduces that rule exactly.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(pins), CAMA_BATCH):
        chunk = pins[i:i + CAMA_BATCH]
        where = (f"year='{year}' AND pin IN ("
                 + ",".join(f"'{p}'" for p in chunk) + ")")
        for row in _fetch(CAMA_URL, {
            "$select": ("pin,card,char_yrblt,char_bldg_sf,char_ext_wall,char_bsmt,"
                        "char_repair_cnd,char_type_resd"),
            "$where": where, "$order": "pin, card", "$limit": "5000",
        }) or []:
            out.setdefault(str(row.get("pin")), row)     # first = lowest card
        log.info("  primary card %d/%d", min(i + CAMA_BATCH, len(pins)), len(pins))
        time.sleep(0.05)
    return [out[p] for p in pins if p in out]


def _parcel_info(pins: list[str]) -> dict[str, dict]:
    """PIN → {street_address, lat, lon} from the parcel layer, in batches."""
    out: dict[str, dict] = {}
    for i in range(0, len(pins), PARCEL_BATCH):
        chunk = pins[i:i + PARCEL_BATCH]
        where = "PIN14 IN (" + ",".join(f"'{p}'" for p in chunk) + ")"
        for f in (_fetch(PARCEL_URL, {
            "where": where,
            "outFields": "PIN14,street_address,city_state_zip,latitude,longitude",
            "returnGeometry": "false", "f": "json",
        }) or {}).get("features") or []:
            a = f.get("attributes") or {}
            pin = str(a.get("PIN14") or "").zfill(14)
            if pin and a.get("latitude") and a.get("longitude") and a.get("street_address"):
                # Full mailing form, so the harness can geocode each row the way a
                # visitor would. Scoring from the parcel centroid instead would put
                # every point inside its own polygon and quietly measure the adapter
                # under ideal geocoding — hiding the interpolation problem that is
                # the single biggest obstacle to it working at all.
                csz = (a.get("city_state_zip") or "").strip()
                out[pin] = {"street_address": a["street_address"],
                            "address": ", ".join(x for x in (a["street_address"], csz) if x),
                            "lat": a["latitude"], "lon": a["longitude"]}
        log.info("  resolved %d/%d parcels", min(i + PARCEL_BATCH, len(pins)), len(pins))
        time.sleep(0.05)
    return out


def _truth(row: dict) -> dict | None:
    """The county's record, in the label's vocabulary. None if ungradeable."""
    # Reuse the adapter's own mapping tables rather than a second copy: a
    # benchmark that translated differently from the thing it grades would be
    # measuring the difference between two translations, not accuracy.
    from housing_label.enrich.assessor import cook_il

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    year = num(row.get("char_yrblt"))
    if not year or not (1800 <= year <= 2100):
        return None               # nothing to be right or wrong about
    sqft = num(row.get("char_bldg_sf"))
    return {
        "year_built": int(year),
        "sqft": sqft if sqft and sqft > 0 else "",
        "stories": cook_il._STORIES.get((row.get("char_type_resd") or "").strip(), ""),
        "construction": cook_il._EXT_WALL.get((row.get("char_ext_wall") or "").strip(), ""),
        "foundation": cook_il._BASEMENT.get((row.get("char_bsmt") or "").strip(), ""),
        "condition": cook_il._CONDITION.get((row.get("char_repair_cnd") or "").strip(), ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=200, help="parcels to sample (default 200)")
    args = ap.parse_args()

    sys.path.insert(0, str(_ROOT / "src"))
    CACHE_DIR.mkdir(exist_ok=True)

    year = _latest_year()
    sample = _cama_sample(year, args.rows)
    log.info("Fetched %d characteristics rows.", len(sample))

    info = _parcel_info([str(r["pin"]).zfill(14) for r in sample])
    log.info("Resolved %d of them to an address + coordinate.", len(info))

    out_rows = []
    for row in sample:
        pin = str(row["pin"]).zfill(14)
        place = info.get(pin)
        truth = _truth(row) if place else None
        if place and truth:
            out_rows.append({"pin": pin, "address": place["address"],
                             "lat": place["lat"], "lon": place["lon"], **truth})

    if not out_rows:
        raise SystemExit("no gradeable rows — refusing to write an empty benchmark")

    with BENCHMARK.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pin", "address", "lat", "lon"] + FIELDS)
        w.writeheader()
        w.writerows(out_rows)

    digest = hashlib.sha256(BENCHMARK.read_bytes()).hexdigest()[:16]
    (CACHE_DIR / "benchmark.meta.json").write_text(json.dumps({
        "source": "Cook County Assessor (Open Data)",
        "assessment_year": year,
        "fetched": date.today().isoformat(),
        "rows": len(out_rows),
        "sha256_16": digest,
    }, indent=2) + "\n")

    log.info("Wrote %s (%d rows, digest %s).", BENCHMARK, len(out_rows), digest)
    log.info("Not committed — see this script's docstring for why.")
    for fld in FIELDS:
        have = sum(1 for r in out_rows if r.get(fld) not in (None, ""))
        log.info("  ground truth %-13s %d/%d", fld, have, len(out_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
