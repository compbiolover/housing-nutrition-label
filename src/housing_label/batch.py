"""Bulk scoring — score a portfolio of parcels through the live label path.

Answers "score my whole book", which is what every institutional user of this
engine actually asks for. The per-address API is the wrong shape for that: a
lender with 400,000 loans does not want 400,000 HTTP requests.

Why this drives the LIVE path rather than reviving score/all_dimensions.py
-------------------------------------------------------------------------
``score/all_dimensions.py`` looks like the batch scorer and is not one. It is a
*grading* stage: it reads a CSV whose per-dimension metrics were already computed
by a Shelby-County enrichment pipeline that no longer exists, and it knows nine
dimensions — it predates Air Quality, Noise, Solar and Water. Generalising it
would mean rebuilding that pipeline and then maintaining two scoring paths that
must agree forever.

So this drives ``build_label_parts`` / ``label_payload`` instead: the same code
the API and CLI use. A row scored here and the same parcel scored through
``GET /label`` return the same numbers by construction, not by convention — which
matters the first time a customer diffs one against the other.

The one thing worth keeping from the old module is its idea of a **portfolio-
relative grade**, which the live path has no notion of. See below.

The network is the whole problem, and geography is the whole answer
------------------------------------------------------------------
Scoring a parcel touches up to seven upstream services (geocoder, NSI, USA
Structures, FEMA, TIGERweb, PVGIS, EPA). At portfolio scale that is millions of
calls against free government endpoints — not slow so much as antisocial, and it
would be rate-limited long before it finished.

But only ONE of those calls is load-bearing: the Census geocode that turns a point
into a county and tract. Every crosswalk keyed off them is bundled. So a caller
who supplies the tract — which lenders, insurers and assessors already hold, and
anyone else can get from a Census bulk file — scores all thirteen dimensions with
**no network at all**, at roughly 600 parcels/sec on one core.

Supply ``lat``/``lon`` without geography and an offline run still works, but it
carries no tract, and the eight location dimensions come back unscored. That is
reported per row (``n_scored``) rather than hidden, because a label with five of
thirteen dimensions is a different product from one with thirteen.

Input
-----
One row per parcel. Everything is optional except a position:

  id                     passed through untouched — your key for joining back
  lat, lon               required (or ``address``, which needs the network)
  address                geocoded; mutually exclusive with the geography columns
  tract, county_fips,    pre-joined Census geography. ``tract`` alone is enough:
  state_fips, …          county and state are derived from it.
  year_built, sqft, …    any of build_label_parts' house fields
  upgrades               comma-separated resilience upgrades
  preset, flood_zone

Unknown columns are ignored rather than rejected: a customer's export carries
their own columns and should not have to be stripped first.
"""

from __future__ import annotations

import csv
import logging
import sys
from typing import Iterable, Iterator

from housing_label.simulate.dimensions import DIMENSIONS
from housing_label.simulate.house import (
    _HOUSE_FIELDS, build_label_parts, label_payload, NonResidentialProperty,
)
from housing_label.score.all_dimensions import percentile_to_local_grade

log = logging.getLogger(__name__)

# Census geography a caller can pre-join, matching resolve_location(geography=).
GEOGRAPHY_FIELDS = frozenset({
    "county_fips", "tract", "state_fips", "county_name",
    "in_urban_area", "incorporated", "place_label", "place_geoid",
})

_TRUTHY = {"1", "true", "t", "yes", "y"}
_FALSY = {"0", "false", "f", "no", "n"}
_FLOAT_FIELDS = frozenset({"value", "sqft", "lot_acres"})
_INT_FIELDS = frozenset({"year_built", "units", "stories"})
_BOOL_FIELDS = frozenset({"owner_occupied", "in_urban_area", "incorporated"})


def _clean(v):
    """CSV cell → None when blank. Everything arrives as a string from csv."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _coerce(key: str, raw):
    """Type a single input cell, or raise ValueError naming the offending column."""
    v = _clean(raw)
    if v is None:
        return None
    try:
        if key in _INT_FIELDS:
            return int(float(v))          # tolerate "1995.0" from spreadsheet exports
        if key in _FLOAT_FIELDS or key in ("lat", "lon"):
            return float(v)
        if key in _BOOL_FIELDS:
            low = v.lower()
            if low in _TRUTHY:
                return True
            if low in _FALSY:
                return False
            raise ValueError(f"expected a boolean, got {v!r}")
    except ValueError as exc:
        raise ValueError(f"column {key!r}: {exc}") from None
    return v


def parse_row(row: dict) -> dict:
    """Split one input row into the kwargs build_label_parts wants.

    Returns ``{"id", "lat", "lon", "address", "preset", "flood_zone", "upgrades",
    "geography", "fields"}``. Raises ValueError on a row that cannot be scored at
    all, so the caller can record it and move on.
    """
    out = {"id": _clean(row.get("id")), "preset": _clean(row.get("preset")),
           "flood_zone": _clean(row.get("flood_zone")),
           "address": _clean(row.get("address"))}

    ups = _clean(row.get("upgrades"))
    out["upgrades"] = [u.strip() for u in ups.split(",") if u.strip()] if ups else None

    out["lat"] = _coerce("lat", row.get("lat"))
    out["lon"] = _coerce("lon", row.get("lon"))
    if out["address"] is None and (out["lat"] is None or out["lon"] is None):
        raise ValueError("need lat and lon (or an address)")

    geo = {k: _coerce(k, row.get(k)) for k in GEOGRAPHY_FIELDS if _clean(row.get(k))}
    # A tract GEOID already contains its state and county, so requiring the caller
    # to repeat them would be busywork — and a mismatch between the two would be a
    # silent wrong answer rather than an error.
    tract = geo.get("tract")
    if tract:
        tract = str(tract).strip().zfill(11)
        geo["tract"] = tract
        geo.setdefault("county_fips", tract[:5])
        geo.setdefault("state_fips", tract[:2])
    elif geo.get("county_fips"):
        geo["county_fips"] = str(geo["county_fips"]).strip().zfill(5)
        geo.setdefault("state_fips", geo["county_fips"][:2])
    out["geography"] = geo or None

    if out["address"] and out["geography"]:
        raise ValueError(
            "pass either address or the geography columns, not both — geography "
            "says the county/tract are known, address says to look them up")

    out["fields"] = {k: _coerce(k, row.get(k)) for k in _HOUSE_FIELDS
                     if _clean(row.get(k)) is not None}
    return out


# Output column order: identity, then per dimension, then the rolled-up numbers.
DIM_KEYS = [k for k, _ in DIMENSIONS]


def output_fieldnames(portfolio: bool = False) -> list[str]:
    cols = ["id", "lat", "lon", "tract", "county_fips"]
    for key in DIM_KEYS:
        cols += [f"{key}_score", f"{key}_national_grade", f"{key}_percentile"]
    cols += ["composite_score", "composite_national_grade",
             "building_score", "building_national_grade",
             "site_score", "site_national_grade",
             "n_scored", "error"]
    if portfolio:
        for key in DIM_KEYS + ["composite"]:
            cols += [f"{key}_portfolio_pct", f"{key}_portfolio_grade"]
    return cols


def _record(parsed: dict, payload: dict | None, error: str | None) -> dict:
    """One flat output row. Errors keep their identity columns so a failed parcel
    is still joinable back to the customer's book rather than vanishing."""
    rec = {c: None for c in output_fieldnames()}
    rec["id"] = parsed.get("id")
    rec["lat"] = parsed.get("lat")
    rec["lon"] = parsed.get("lon")
    geo = parsed.get("geography") or {}
    rec["tract"] = geo.get("tract")
    rec["county_fips"] = geo.get("county_fips")
    rec["error"] = error
    if payload is None:
        return rec

    loc = payload.get("location") or {}
    rec["tract"] = rec["tract"] or loc.get("census_tract") or payload.get("census_tract")
    rec["county_fips"] = rec["county_fips"] or loc.get("county_fips")
    for d in payload.get("dimensions", []):
        k = d.get("key")
        if k is None:
            continue
        rec[f"{k}_score"] = d.get("score")
        rec[f"{k}_national_grade"] = d.get("national_grade")
        rec[f"{k}_percentile"] = d.get("national_percentile")
    rec["composite_score"] = payload.get("composite_score")
    rec["composite_national_grade"] = payload.get("composite_national_grade")
    rec["building_score"] = payload.get("construction_score")
    rec["building_national_grade"] = payload.get("construction_national_grade")
    rec["site_score"] = payload.get("location_score")
    rec["site_national_grade"] = payload.get("location_national_grade")
    rec["n_scored"] = payload.get("n_scored")
    return rec


def score_rows(rows: Iterable[dict], *, allow_network: bool = False) -> Iterator[dict]:
    """Score an iterable of input rows, yielding one flat record each.

    A row that cannot be scored yields a record carrying its identity columns and
    an ``error`` string rather than raising. That is the difference between a
    400,000-row job that reports 12 bad addresses and one that dies on row 39,000
    — and the bad rows are exactly what the customer needs handed back.
    """
    for i, row in enumerate(rows):
        # Identity is captured from the RAW row before anything can fail, so a row
        # that dies in parsing still comes back joinable. Recovering it from
        # `parsed` would lose exactly the rows that need it most: parse_row raises
        # before it returns, so the id would be gone for every malformed row.
        ident = {"id": _clean(row.get("id")),
                 "lat": _clean(row.get("lat")), "lon": _clean(row.get("lon"))}
        parsed = None
        try:
            parsed = parse_row(row)
            cfg, r, label = build_label_parts(
                address=parsed["address"],
                lat=parsed["lat"], lon=parsed["lon"],
                preset=parsed["preset"], flood_zone=parsed["flood_zone"],
                upgrades=parsed["upgrades"], geography=parsed["geography"],
                allow_network=allow_network,
                # Bulk input is an assertion that these are the parcels to score;
                # screening them out one at a time would drop rows from a book the
                # customer says is residential. Non-residential parcels still score
                # honestly — they simply aren't refused.
                allow_non_residential=True,
                **parsed["fields"])
            yield _record(parsed, label_payload(cfg, r, label), None)
        except NonResidentialProperty as exc:
            yield _record(parsed or ident, None, f"non-residential: {exc}")
        except (ValueError, TypeError) as exc:
            yield _record(parsed or ident, None, str(exc))
        except Exception as exc:  # noqa: BLE001 — one bad parcel must not end the run
            log.warning("row %d failed: %s", i, exc, exc_info=True)
            yield _record(parsed or ident, None, f"{type(exc).__name__}: {exc}")


# ── Portfolio-relative grades ────────────────────────────────────────────────
# The one idea worth keeping from score/all_dimensions.py. A national grade
# answers "how does this house compare to US housing"; a portfolio grade answers
# "which tenth of MY book is worst", which is the question an owner of 400,000
# parcels is actually asking. Both are reported, never merged: they are different
# claims and a reader must be able to tell which one they are looking at.

def portfolio_grades(records: list[dict]) -> list[dict]:
    """Add ``*_portfolio_pct`` / ``*_portfolio_grade`` columns, ranking within the batch.

    Percentile is the share of scored rows at or below this row's score, so 100
    means "best in this book". Rows that failed, or that are unscored on a given
    dimension, are excluded from that dimension's ranking rather than treated as
    zero — a missing input must never rank as the worst parcel.
    """
    import bisect

    for key in DIM_KEYS + ["composite"]:
        col = f"{key}_score"
        vals = sorted(r[col] for r in records if isinstance(r.get(col), (int, float)))
        n = len(vals)
        for r in records:
            v = r.get(col)
            if not isinstance(v, (int, float)) or n == 0:
                r[f"{key}_portfolio_pct"] = None
                r[f"{key}_portfolio_grade"] = None
                continue
            pct = round(bisect.bisect_right(vals, v) / n * 100, 1)
            r[f"{key}_portfolio_pct"] = pct
            r[f"{key}_portfolio_grade"] = percentile_to_local_grade(pct)
    return records


def run_batch(inp, out, *, allow_network: bool = False, portfolio: bool = False,
              progress_every: int = 0) -> dict:
    """Score ``inp`` (an open CSV reader source) into ``out``. Returns a summary.

    Streams when ``portfolio`` is off, so memory stays flat regardless of row
    count. Portfolio ranking needs every score before it can rank any of them, so
    that mode necessarily holds the records in memory — stated here rather than
    discovered at 400,000 rows.
    """
    reader = csv.DictReader(inp)
    if reader.fieldnames is None:
        raise ValueError("input CSV has no header row")

    writer = csv.DictWriter(out, fieldnames=output_fieldnames(portfolio),
                            extrasaction="ignore")
    writer.writeheader()

    total = failed = 0
    held: list[dict] = []
    for rec in score_rows(reader, allow_network=allow_network):
        total += 1
        if rec.get("error"):
            failed += 1
        if portfolio:
            held.append(rec)
        else:
            writer.writerow(rec)
        if progress_every and total % progress_every == 0:
            log.info("scored %d rows (%d failed)", total, failed)

    if portfolio:
        for rec in portfolio_grades(held):
            writer.writerow(rec)

    return {"rows": total, "failed": failed, "scored": total - failed}


def main() -> None:
    """Console entry point: ``housing-batch``."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    p = argparse.ArgumentParser(
        prog="housing-batch",
        description="Score a portfolio of parcels (CSV in, CSV out). Supply a "
                    "tract or county FIPS per row to score all thirteen "
                    "dimensions with no network calls at all.")
    p.add_argument("--input", "-i", required=True,
                   help="Input CSV ('-' for stdin). Needs lat/lon (or address); "
                        "tract/county_fips and house fields optional.")
    p.add_argument("--output", "-o", required=True, help="Output CSV ('-' for stdout).")
    p.add_argument("--fetch", action="store_true",
                   help="Allow upstream lookups (geocoding, structure detection, "
                        "PVGIS…). Off by default: at portfolio scale that is "
                        "millions of calls against free government endpoints.")
    p.add_argument("--portfolio-grades", action="store_true",
                   help="Also rank each parcel within this batch (adds "
                        "*_portfolio_pct / *_portfolio_grade). Holds the results "
                        "in memory, since ranking needs every score first.")
    p.add_argument("--progress", type=int, default=1000, metavar="N",
                   help="Log progress every N rows (0 to disable).")
    args = p.parse_args()

    fin = sys.stdin if args.input == "-" else open(args.input, newline="")
    fout = sys.stdout if args.output == "-" else open(args.output, "w", newline="")
    try:
        summary = run_batch(fin, fout, allow_network=args.fetch,
                            portfolio=args.portfolio_grades,
                            progress_every=args.progress)
    finally:
        if fin is not sys.stdin:
            fin.close()
        if fout is not sys.stdout:
            fout.close()

    log.info("done: %d rows, %d scored, %d failed",
             summary["rows"], summary["scored"], summary["failed"])
    if summary["failed"]:
        log.info("failed rows kept their id/lat/lon and carry an 'error' column")


if __name__ == "__main__":
    main()
