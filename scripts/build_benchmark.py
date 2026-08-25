#!/usr/bin/env python3
"""Fetch the accuracy benchmark: addresses whose true construction facts are known.

Why this exists
---------------
The label has 900+ tests asserting the code does what it says. Not one of them
asserts the *output matches the world*, and every buyer conversation in
``research/monetization-research.md`` opens with that question. This script
assembles the yardstick; ``scripts/measure_accuracy.py`` reads it.

Ground truth comes from an assessor that publishes construction characteristics for
a real parcel, free and keyless — the same sources the adapters read. Each row is one
address the scorer can be pointed at, plus what that jurisdiction says is actually
standing there.

Three are supported, selected with ``--jurisdiction``:

  cook      Cook County, IL — Socrata CAMA keyed by PIN, plus the county parcel
            layer.
  dc        Washington, DC — ArcGIS residential CAMA keyed by SSL, plus the
            District's parcel layer. Houses only: a condominium unit's SSL is in
            a different table and in no parcel polygon, so no coordinate reaches
            it.
  dc-condo  Washington, DC — the other table. Condominium CAMA keyed by unit SSL,
            placed through the District's unit index, which holds the only
            keyless address-and-unit edge. Two graded fields rather than six: that
            table records no wall, storey, basement or condition.

DC is two entries rather than one because they are not one population sampled
twice — different tables, different lookups, different fields answered. A single
average would hide which half a number came from.

Each writes its own ``benchmark-<jurisdiction>.csv``, so building one never
replaces another.

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

Rows without a street address or without a usable year built are dropped: there is
nothing to geocode, or nothing to be right or wrong about. Coordinates are NOT
required — nothing in the scoring path reads them, and DC's parcel source has no
coordinate columns at all, so requiring them would drop good rows in one
jurisdiction and describe a different population in the other.

Run:  python scripts/build_benchmark.py --rows 200
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import pathlib
import sys
import tempfile
import time
from datetime import date

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("build_benchmark")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:     # so the shared registry imports
    sys.path.insert(0, str(_ROOT))

from scripts.jurisdictions import JURISDICTIONS  # noqa: E402

CACHE_DIR = _ROOT / ".accuracy_cache"
BENCHMARK = CACHE_DIR / "benchmark.csv"          # legacy single-jurisdiction path

# Each jurisdiction gets its own benchmark file, so building one never silently
# replaces another's — the published page reports both side by side.


def _write_atomic(path: pathlib.Path, data: str | bytes) -> None:
    """Write via a unique temporary file and rename, so no reader sees a partial one.

    The temp name must be UNIQUE, not merely temporary. A fixed `<name>.tmp` is one
    path shared by every concurrent build of the same jurisdiction: two of them
    interleave their bytes into it, or one renames it away while the other is still
    filling it, and the rename that was supposed to make the write atomic delivers
    a torn file instead. Builds are not otherwise serialised — they are long,
    manual, and there is nothing to stop two.

    Same directory as the target, because a rename is only atomic within a
    filesystem.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = pathlib.Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def benchmark_path(juris: str) -> pathlib.Path:
    return CACHE_DIR / f"benchmark-{juris}.csv"


def meta_path(juris: str) -> pathlib.Path:
    return CACHE_DIR / f"benchmark-{juris}.meta.json"

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


def _num(v):
    """A float, or None. The same coercion the adapters use on portal values."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rows_of(body):
    """A list of row mappings from any portal answer, or None if it is not one.

    Every parse point in this file had its own idea of what a response looks like,
    and each one crashed on a shape the others had already learned to reject:
    `(body or {}).get("features")` raises on a JSON list; `got[0]` raises on an
    error object; `isinstance(r, dict)` passes a feature whose `attributes` is a
    string, which then raises one `.get()` later. An incidental traceback where
    the samplers all promise to retry the offset and then fail closed with a
    message about the draw.

    So the shape question is answered once. ArcGIS wraps rows in `features` with
    the payload under `attributes`; Socrata returns the rows directly. Anything
    else — including a well-formed envelope carrying a malformed row — is not an
    answer, and every caller already knows what to do with that.
    """
    if isinstance(body, dict):
        rows = body.get("features")
        if not isinstance(rows, list):
            return None
        # An ArcGIS row is only usable through `attributes`, so a non-mapping there
        # makes the whole response unusable rather than that one row.
        for r in rows:
            if not isinstance(r, dict):
                return None
            if "attributes" in r and not isinstance(r["attributes"], dict):
                return None
        return rows
    if isinstance(body, list):
        return body if all(isinstance(r, dict) for r in body) else None
    return None


def _batch_or_die(url: str, params: dict, what: str, n: int) -> list:
    """The rows of a batch request, or the end of the build.

    A batch that exhausts its retries is not "these parcels have no record" — it
    is the portal being down for one slice of the draw. Returning nothing here
    deletes that slice from an evenly spaced sample, and every count downstream
    then attributes the absence to the assessor's own documentation rather than
    to a request that never landed. Neither the written benchmark nor the
    published page can show the difference: a draw with a batch missing from it
    looks exactly like a smaller clean one.

    That is the same failure the offset sampler above refuses, one layer down. It
    is one function so the two cannot drift apart again, and so a third
    jurisdiction inherits the rule instead of reimplementing it.

    Socrata answers with a list and ArcGIS with a dict carrying ``features`` —
    and ArcGIS reports failure inside a 200 body, so an ``error`` key counts as
    no answer. A batch that comes back short is a different matter and is left
    alone: those parcels really are absent from the layer, which is what the
    drawn-versus-sampled gap is for.
    """
    body = _fetch(url, params)
    rows = _rows_of(body)
    truncated = isinstance(body, dict) and body.get("exceededTransferLimit")
    # The SHAPE is checked, not just the truthiness. `{"features": "oops"}` made
    # `rows` a non-empty string, which passed every guard here and then reached the
    # callers as characters to call .get() on — an AttributeError deep in a join
    # instead of the stated refusal this helper exists to give. A malformed body is
    # a portal that did not answer, which is the case already handled.
    if (body is None or (isinstance(body, dict) and body.get("error"))
            or truncated or not rows):
        # `exceededTransferLimit` is ArcGIS SAYING it truncated, and it rides along
        # with a perfectly well-formed, non-empty feature list. Accepting that as a
        # legitimately short batch is the one truncation case the portal actually
        # announces, so not reading it was the cheapest possible miss.
        #
        # An empty answer is AMBIGUOUS here, and deliberately resolved as failure.
        # A portal returning nothing because it is unwell and a portal returning
        # nothing because an `IN` list genuinely matched no rows are byte-identical
        # — there is no discriminator in the response. Guessing "no rows" makes a
        # silent, invisible bias; guessing "outage" makes a loud, recoverable stop.
        # Only one of those can be noticed, so the message names the ambiguity
        # rather than asserting a cause.
        raise SystemExit(
            f"{what} returned nothing for a batch of {n}. Either the portal is "
            f"unwell or none of those {n} exists in that layer, and the response "
            f"cannot tell the two apart — so this refuses rather than write a "
            f"benchmark that may be missing them invisibly. Retry; if it repeats "
            f"identically, check whether those records are really absent.")
    return rows


def _latest_year() -> str:
    """The newest assessment year, or the end of the build.

    Shape-checked like every other parse point. A 200 error object raised
    KeyError from `[0]`, and an EMPTY list quietly produced `""` — which then
    queried `year=''`, matched nothing, and failed several steps later with a
    message about the sample rather than about the portal.
    """
    rows = _rows_of(_fetch(CAMA_URL, {"$select": "max(year)"}))
    year = str((rows or [{}])[0].get("max_year", "")).split(".")[0] if rows else ""
    if not year.isdigit():
        raise SystemExit(
            "could not read the latest assessment year from the county portal "
            f"(got {year!r}); try again later")
    return year


def _cama_sample(year: str, rows: int) -> tuple[list[dict], dict]:
    """Evenly-spaced rows from the latest assessment year."""
    # Before the network call: an unusable argument should not cost a request.
    if rows < 1:
        raise SystemExit(f"--rows must be at least 1 (got {rows})")
    got = _fetch(CAMA_URL, {"$select": "count(*)", "$where": f"year='{year}'"})
    # Shape first, exactly as the two DC samplers do it. This branch was hardened
    # there and not here: `(got or [{}])[0]` raises KeyError on an empty list —
    # `or` does not catch `[]` from a subscript — and int() raises ValueError on
    # {"count": "oops"}. Both escaped the stated "could not size" refusal for an
    # incidental traceback, which reads as a bug in the builder rather than a
    # portal that changed shape. A rule applied to two of three samplers is the
    # shape this file keeps finding.
    first = got[0] if isinstance(got, list) and got and isinstance(got[0], dict) else None
    count = first.get("count") if first else None
    try:
        total = int(count)
    except (TypeError, ValueError):
        # An unparseable count is the portal changing shape, NOT an empty table.
        # Falling through to `total = 0` reported [{"count": "oops"}] as "no rows
        # for assessment year 2024" — a claim about the county's records made from
        # a response that never said anything about them, and the one diagnosis
        # that sends a reader looking in the wrong place entirely.
        total = None
    if total is None:
        raise SystemExit(f"could not reach the county portal to size assessment "
                         f"year {year}; try again later")
    if total <= 0:
        raise SystemExit(f"no rows for assessment year {year}")
    log.info("Assessment year %s has %d parcels; sampling %d.", year, total, rows)

    # Spread the offsets across [0, total), rather than flooring a stride: with a
    # stride, any request for more than half the population collapses to step 1 and
    # silently reads the first N rows — which, since PINs are township-ordered,
    # turns a "county-wide" sample into one corner of Cook.
    rows = min(rows, total)
    seen: list[str] = []

    def attempt(offsets: list[int]) -> list[int]:
        """Read these offsets; return the ones that did not answer."""
        failed = []
        for n, i in enumerate(offsets, 1):
            got = _fetch(CAMA_URL, {
                "$select": "pin", "$where": f"year='{year}'",
                "$order": "pin", "$limit": "1", "$offset": str(i * total // rows),
            })
            # `got == []` is the portal answering nothing for an offset inside a
            # table it just sized — a failure, not an empty slot. The DC sampler
            # treats it the same way; the two must agree or one jurisdiction's
            # sample silently tolerates what the other rejects.
            got = _rows_of(got)
            pin = got[0].get("pin") if got else None
            if not got or not pin:
                # Two ways for an offset not to answer, and both are the portal:
                # `[]` inside a table it just sized, and a row carrying no PIN,
                # which cannot be looked up so cannot enter the draw. A PIN
                # already seen is different — the table has a row per card, and
                # collapsing duplicates is the point.
                failed.append(i)
            elif pin not in seen:
                seen.append(pin)
            if n % 25 == 0:
                log.info("  sampled %d/%d", n, len(offsets))
            time.sleep(0.05)      # polite to a free public portal
        return failed

    missed = attempt(list(range(rows)))
    if missed:
        # See the DC sampler: a skipped offset shifts an evenly spaced draw toward
        # the offsets that answered, and nothing downstream can see that it did.
        log.warning("  %d offsets did not answer; retrying them.", len(missed))
        missed = attempt(missed)
    if missed:
        raise SystemExit(
            f"{len(missed)} of {rows} sample offsets never answered. Writing the "
            f"benchmark anyway would bias it toward the offsets that worked, "
            f"invisibly. Try again when the portal is healthy.")
    # `attempted` is how many DISTINCT parcels the draw actually asked about, not
    # how many offsets were read. Two offsets can land on one PIN (the table has a
    # row per card), and `seen` collapses them — so counting offsets would make
    # `drawn - sampled` positive for a parcel that was fine, and the page would
    # report a duplicate as a house the assessor never documented.
    return _primary_cards(year, seen), {"attempted": len(seen)}


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
        for row in _batch_or_die(CAMA_URL, {
            "$select": ("pin,card,char_yrblt,char_bldg_sf,char_ext_wall,char_bsmt,"
                        "char_repair_cnd,char_type_resd"),
            "$where": where, "$order": "pin, card", "$limit": "5000",
        }, "card lookup", len(chunk)):
            out.setdefault(str(row.get("pin")), row)     # first = lowest card
        # A SHORT answer is legitimate for the parcel-layer joins — those parcels
        # really can be absent from the layer, which is what a `no_address` drop
        # records. It is NOT legitimate here, and treating the two the same was a
        # rule generalised past its evidence: every PIN in this chunk was returned
        # by THIS table filtered to THIS year moments ago, so each provably has a
        # card. A missing one is a truncated response (a `$limit` cut, a partial
        # page), and it would vanish from the sample and be published as a house
        # the assessor never gave an address for.
        missing = [q for q in chunk if q not in out]
        if missing:
            raise SystemExit(
                f"the card lookup returned no row for {len(missing)} of "
                f"{len(chunk)} PINs that this same table listed for {year} "
                f"(first: {missing[0]}). That is a truncated response, not a gap "
                f"in the county's records, and dropping those parcels would bias "
                f"the draw invisibly. Try again when the portal is healthy.")
        log.info("  primary card %d/%d", min(i + CAMA_BATCH, len(pins)), len(pins))
        time.sleep(0.05)
    return [out[p] for p in pins if p in out]


def _parcel_info(pins: list[str]) -> tuple[dict[str, dict], set[str]]:
    """PIN → {street_address, lat, lon}, and the PINs the layer held a record for.

    The second value exists because "absent from the layer" and "present with no
    address" are different facts about the assessor, and both used to leave the
    same trace: no entry in the returned map. The build reported every addressless
    parcel as one the layer had never heard of — a stronger claim than the evidence
    supports, and the very misattribution the split into separate drop reasons was
    supposed to end. Splitting the REPORT without making the DATA carry the
    distinction just relabelled it.
    """
    out: dict[str, dict] = {}
    present: set[str] = set()
    for i in range(0, len(pins), PARCEL_BATCH):
        chunk = pins[i:i + PARCEL_BATCH]
        wanted = set(chunk)
        where = "PIN14 IN (" + ",".join(f"'{p}'" for p in chunk) + ")"
        for f in _batch_or_die(PARCEL_URL, {
            "where": where,
            "outFields": "PIN14,street_address,city_state_zip,latitude,longitude",
            "returnGeometry": "false", "f": "json",
        }, "parcel lookup", len(chunk)):
            a = f.get("attributes") or {}
            if not (a.get("PIN14") or "").strip():
                # The query is keyed BY PIN14, so a feature that comes back without
                # one cannot be joined to anything. Skipping it makes the parcel
                # vanish and publish as `no_address` — the assessor blamed for a
                # malformed response. Same rule the offset samplers apply: a row
                # with no identifier is the portal failing, not a record.
                raise SystemExit(
                    f"the parcel layer returned a feature with no PIN14 in a batch "
                    f"of {len(chunk)}. It cannot be joined, and continuing would "
                    f"drop a sampled parcel and report it as undocumented.")
            pin = str(a.get("PIN14") or "").zfill(14)
            if pin not in wanted:
                # The query is an IN over `chunk`, so a PIN outside it means the
                # filter was ignored or a stale response was served. Storing it
                # would leave every requested parcel looking absent — a whole
                # batch published as houses with no address on file, from a
                # response that never answered the question asked.
                raise SystemExit(
                    f"the parcel layer returned PIN {pin}, which was not in the "
                    f"batch of {len(chunk)} requested. The response does not "
                    f"answer the query, and continuing would report every parcel "
                    f"in this batch as undocumented.")
            # Coordinates are NOT required. Nothing in the scoring path reads them
            # — the harness geocodes the address exactly as a visitor would, and
            # scoring from the parcel centroid would measure the adapter under
            # ideal geocoding — so they are carried for inspection only. Requiring
            # them dropped rows whose address and year were perfectly good, and the
            # published note then reported those as records the assessor never
            # documented. DC already carried an empty point rather than dropping
            # the row; this is the same rule.
            present.add(pin)
            street = (a.get("street_address") or "").strip()
            if pin and street:
                # Full mailing form, so the harness can geocode each row the way a
                # visitor would. Scoring from the parcel centroid instead would put
                # every point inside its own polygon and quietly measure the adapter
                # under ideal geocoding — hiding the interpolation problem that is
                # the single biggest obstacle to it working at all.
                csz = (a.get("city_state_zip") or "").strip()
                out[pin] = {"street_address": street,
                            "address": ", ".join(x for x in (street, csz) if x),
                            "lat": a.get("latitude") or "", "lon": a.get("longitude") or ""}
        log.info("  resolved %d/%d parcels", min(i + PARCEL_BATCH, len(pins)), len(pins))
        time.sleep(0.05)
    return out, present


# --- Washington, DC ------------------------------------------------------------
#
# A second jurisdiction, so the harness measures the registry rather than one
# county. DC's shape differs from Cook's in three ways that matter here:
#
#   * Its CAMA lives on ArcGIS, not Socrata, and is keyed by SSL (square-suffix-
#     lot) rather than PIN. Row offsets work the same way, so the even-spacing
#     rule carries over unchanged.
#   * Its parcel layer publishes no latitude/longitude columns, so a representative
#     point is computed from the polygon. Nothing in the scoring path uses it — the
#     harness geocodes the address exactly as a visitor would — so it is carried for
#     inspection only.
#   * CONDOMINIUM units live in a SEPARATE CAMA table (61,329 rows against
#     RESIDENTIAL's 109,273 — 36% of DC's CAMA stock). They cannot enter this
#     benchmark: a unit-level SSL does not appear in the parcel polygon layer at
#     all, so there is no way to resolve one to an address, and no coordinate can
#     distinguish one unit from another in the same building. So this measures
#     NON-CONDO DC homes, and the published page says so rather than letting a
#     figure drawn from 64% of the stock read as the whole city.
DC_BASE = ("https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA"
           "/Property_and_Land_WebMercator/MapServer")
DC_CAMA_URL = f"{DC_BASE}/25/query"          # RESIDENTIAL (CAMA)
DC_PARCEL_URL = f"{DC_BASE}/40/query"        # Owner Polygons (Common Ownership)
DC_BATCH = 40

# Only what the benchmark needs. The parcel layer also carries OWNERNAME, owner
# mailing addresses and tax balances; naming the fields keeps them unrequested.
_DC_PARCEL_FIELDS = "SSL,PREMISEADD"
_DC_CAMA_FIELDS = "SSL,AYB,GBA,STORIES,EXTWALL_D,CNDTN_D,NUM_UNITS"


def _dc_sample(rows: int) -> tuple[list[dict], dict]:
    """Evenly-spaced rows from DC's residential CAMA table."""
    if rows < 1:
        raise SystemExit(f"--rows must be at least 1 (got {rows})")
    got = _fetch(DC_CAMA_URL, {"where": "1=1", "returnCountOnly": "true", "f": "json"})
    # Shape first. `{"count": "oops"}` reached int() and raised ValueError, and a
    # plain string body raised AttributeError from .get() — both escaping the
    # stated "could not size" refusal for an incidental traceback. A portal
    # changing shape should fail the same way as a portal not answering.
    count = got.get("count") if isinstance(got, dict) else None
    total = int(count) if isinstance(count, (int, float)) else 0
    if total <= 0:
        raise SystemExit("could not size DC's residential CAMA table; try again later")
    log.info("DC residential CAMA has %d rows; sampling %d.", total, rows)

    rows = min(rows, total)
    out, seen = [], set()

    def attempt(offsets: list[int]) -> list[int]:
        """Read these offsets; return the ones that did not answer."""
        failed = []
        for n, i in enumerate(offsets, 1):
            body = _fetch(DC_CAMA_URL, {
                "where": "1=1", "outFields": _DC_CAMA_FIELDS, "orderByFields": "SSL",
                "resultOffset": str(i * total // rows), "resultRecordCount": "1",
                "returnGeometry": "false", "f": "json",
            })
            feats = _rows_of(body)
            # An ArcGIS failure arrives in a 200 body, and an offset inside a table
            # this size always has a row — so an empty answer is the portal failing
            # quietly. Neither is "no row here".
            a = (feats[0].get("attributes") or {}) if feats else {}
            ssl = (a.get("SSL") or "").strip()
            if (body is None or (isinstance(body, dict) and body.get("error"))
                    or not feats or not ssl):
                # `exceededTransferLimit` is deliberately NOT checked here, and
                # the asymmetry with `_batch_or_die` is the point. The flag means
                # "more records match than were returned". This query asks for
                # ONE row on purpose — it is a paged read of a 109,273-row table —
                # so the flag is set on every healthy response. In the batch
                # lookups no page size is given, the whole matching set is
                # expected, and the same flag really does mean a truncated answer.
                #
                # Adding the check here rejected all six offsets of a live build
                # on the first run, which is how the difference was noticed: one
                # more rule generalised past the evidence for it.
                #
                # A row with no SSL joins the empty and error cases: it cannot be
                # resolved to an address, so it is an offset that did not answer.
                # See the Cook sampler — the two must agree or one jurisdiction
                # quietly tolerates what the other refuses.
                failed.append(i)
            elif ssl not in seen:
                seen.add(ssl)
                out.append(a)
            if n % 25 == 0:
                log.info("  sampled %d/%d", n, len(offsets))
            time.sleep(0.05)
        return failed

    missed = attempt(list(range(rows)))
    if missed:
        # Retried rather than skipped. Dropping an offset shifts the draw toward
        # whichever ones happened to answer, and a benchmark with holes in an
        # evenly spaced sample still looks like a clean one — the bias is
        # invisible in the output. _fetch already backs off four times, so these
        # are offsets that failed repeatedly; one more pass separates a blip from
        # an outage.
        log.warning("  %d offsets did not answer; retrying them.", len(missed))
        missed = attempt(missed)
    if missed:
        raise SystemExit(
            f"{len(missed)} of {rows} sample offsets never answered. Writing the "
            f"benchmark anyway would bias it toward the offsets that worked, "
            f"invisibly. Try again when the portal is healthy.")
    # Distinct parcels, not offsets read — see the Cook sampler for why.
    return out, {"attempted": len(out)}


def _ring_point(geom: dict) -> tuple[float, float] | None:
    """A representative point inside a parcel polygon (mean of its outer ring)."""
    ring = ((geom or {}).get("rings") or [[]])[0]
    pts = [p for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not pts:
        return None
    return (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))


def _dc_place(ssls: list[str]) -> tuple[dict[str, dict], set[str]]:
    """SSL → {address, lat, lon}, and the SSLs the layer held a record for.

    See ``_parcel_info`` for why the second value exists.
    """
    out: dict[str, dict] = {}
    present: set[str] = set()
    for i in range(0, len(ssls), DC_BATCH):
        chunk = ssls[i:i + DC_BATCH]
        wanted = set(chunk)
        where = "SSL IN (" + ",".join("'" + s.replace("'", "''") + "'" for s in chunk) + ")"
        for f in _batch_or_die(DC_PARCEL_URL, {
            "where": where, "outFields": _DC_PARCEL_FIELDS,
            "returnGeometry": "true", "outSR": "4326", "f": "json",
        }, "parcel lookup", len(chunk)):
            a = f.get("attributes") or {}
            ssl, addr = (a.get("SSL") or "").strip(), (a.get("PREMISEADD") or "").strip()
            if not ssl:
                # The join key, missing — see the Cook parcel lookup. A missing
                # ADDRESS below is different and legitimate: that parcel really has
                # none on file, which is what a `no_address` drop records.
                raise SystemExit(
                    f"the parcel layer returned a feature with no SSL in a batch of "
                    f"{len(chunk)}. It cannot be joined, and continuing would drop "
                    f"a sampled parcel and report it as undocumented.")
            if ssl not in wanted:
                # See the Cook parcel lookup: an SSL outside the requested batch
                # means the response is not an answer to this query.
                raise SystemExit(
                    f"the parcel layer returned SSL {ssl!r}, which was not in the "
                    f"batch of {len(chunk)} requested. The response does not "
                    f"answer the query, and continuing would report every parcel "
                    f"in this batch as undocumented.")
            present.add(ssl)
            if not addr:
                continue
            pt = _ring_point(f.get("geometry") or {})
            # PREMISEADD is already the full mailing form ("3401 NEWARK ST NW
            # WASHINGTON DC 20016"), so it is geocoded as a visitor would type it.
            out[ssl] = {"address": addr,
                        "lat": pt[0] if pt else "", "lon": pt[1] if pt else ""}
        log.info("  resolved %d/%d parcels", min(i + DC_BATCH, len(ssls)), len(ssls))
        time.sleep(0.05)
    return out, present


# --- DC condominiums ------------------------------------------------------------
#
# A different table and a different join from the parcel path above, for the
# reason the adapter gives: a condominium unit is not somewhere a coordinate can
# land. Its SSL is in the CONDOMINIUM table and nowhere in the parcel polygons, so
# the sample is drawn from that table and placed through the unit index, which
# holds the only address-to-unit edge the District publishes without a key.
#
# Neither table carries geometry, so the rows have no lat/lon. That costs nothing:
# the scorer geocodes the address, exactly as a visitor's browser does, and never
# reads the coordinate columns. They are written blank rather than omitted so the
# file keeps one schema across jurisdictions.
DC_CONDO_CAMA_URL = f"{DC_BASE}/24/query"    # CONDOMINIUM (CAMA)
DC_UNITS_URL = f"{DC_BASE}/68/query"         # RESIDENTIAL UNITS

# LIVING_GBA is the unit's own area, not the building's — the one field where the
# condominium record is better than the residential one, which has to drop floor
# area on any multi-unit parcel.
_DC_CONDO_FIELDS = "SSL,AYB,LIVING_GBA"
# The unit index also carries MAR_ID, book and page. Naming the three fields the
# join needs keeps the rest unrequested.
_DC_UNITS_FIELDS = "CONDO_SSL,PRIMARY_ADDRESS,UNIT_NUMBER"


def _dc_condo_sample(rows: int) -> tuple[list[dict], dict]:
    """Evenly-spaced rows from DC's condominium CAMA table."""
    if rows < 1:
        raise SystemExit(f"--rows must be at least 1 (got {rows})")
    got = _fetch(DC_CONDO_CAMA_URL,
                 {"where": "1=1", "returnCountOnly": "true", "f": "json"})
    count = got.get("count") if isinstance(got, dict) else None
    total = int(count) if isinstance(count, (int, float)) else 0
    if total <= 0:
        raise SystemExit("could not size DC's condominium CAMA table; try again later")
    log.info("DC condominium CAMA has %d rows; sampling %d.", total, rows)

    rows = min(rows, total)
    out, seen = [], set()

    def attempt(offsets: list[int]) -> list[int]:
        """Read these offsets; return the ones that did not answer."""
        failed = []
        for n, i in enumerate(offsets, 1):
            body = _fetch(DC_CONDO_CAMA_URL, {
                "where": "1=1", "outFields": _DC_CONDO_FIELDS, "orderByFields": "SSL",
                "resultOffset": str(i * total // rows), "resultRecordCount": "1",
                "returnGeometry": "false", "f": "json",
            })
            feats = _rows_of(body)
            a = (feats[0].get("attributes") or {}) if feats else {}
            ssl = (a.get("SSL") or "").strip()
            # Same rule as the residential sampler, and deliberately the same:
            # `exceededTransferLimit` is NOT consulted, because this is a paged
            # one-row read of a 61,329-row table and the flag is set on every
            # healthy response. An empty body, an error object or a row with no
            # SSL is an offset that did not answer.
            if (body is None or (isinstance(body, dict) and body.get("error"))
                    or not feats or not ssl):
                failed.append(i)
            elif ssl not in seen:
                seen.add(ssl)
                out.append(a)
            if n % 25 == 0:
                log.info("  sampled %d/%d", n, len(offsets))
            time.sleep(0.05)
        return failed

    missed = attempt(list(range(rows)))
    if missed:
        # Retried, then refused — the same two steps the other two samplers take,
        # and for the same reason: a benchmark with holes in an evenly spaced draw
        # is biased toward whichever offsets answered, and looks clean.
        log.warning("  %d offsets did not answer; retrying them.", len(missed))
        missed = attempt(missed)
    if missed:
        raise SystemExit(
            f"{len(missed)} of {rows} sample offsets never answered. Writing the "
            f"benchmark anyway would bias it toward the offsets that worked, "
            f"invisibly. Try again when the portal is healthy.")
    # Distinct units, not offsets read. `rows` would over-count whenever two
    # offsets landed on one SSL, and main() asserts that every drawn row is either
    # written or counted under a drop reason — so an inflated total fails the
    # build with an accounting error that has nothing to do with the real cause.
    return out, {"attempted": len(out)}


def _dc_condo_place(ssls: list[str]) -> tuple[dict[str, dict], set[str]]:
    """Condo SSL → {address, lat, lon}, and the SSLs the unit index knew.

    The address is built the way a resident writes it, marker and all, because
    that is the form the scorer feeds the geocoder and the adapter — and the unit
    is the whole point: without it every unit in the building is the same address.

    A single SSL answering to two different addresses is dropped rather than
    resolved. That is the same refusal the adapter makes from the other direction,
    and a benchmark row whose identity is ambiguous cannot grade anything.
    """
    out: dict[str, dict] = {}
    present: set[str] = set()
    conflicting: set[str] = set()
    for i in range(0, len(ssls), DC_BATCH):
        chunk = ssls[i:i + DC_BATCH]
        wanted = set(chunk)
        where = ("CONDO_SSL IN ("
                 + ",".join("'" + s.replace("'", "''") + "'" for s in chunk)
                 + ") AND UNIT_TYPE='CONDO' AND STATUS='ACTIVE'")
        # NOT `_batch_or_die`: that helper refuses a response shorter than the
        # batch, which is right where every key is expected to resolve. Here a
        # condominium SSL legitimately has no ACTIVE unit row — the filter is part
        # of the question — and those are counted as `no_parcel_record`, which is
        # what they are.
        body = _fetch(DC_UNITS_URL, {
            "where": where, "outFields": _DC_UNITS_FIELDS,
            "returnGeometry": "false", "f": "json",
        })
        if body is None or (isinstance(body, dict) and body.get("error")):
            raise SystemExit(
                f"the unit index did not answer for a batch of {len(chunk)} "
                f"condominium SSLs. Continuing would report every one of them as "
                f"undocumented, which is a claim about the District's records "
                f"rather than about this request.")
        for f in _rows_of(body):
            a = f.get("attributes") or {}
            ssl = (a.get("CONDO_SSL") or "").strip()
            if not ssl:
                raise SystemExit(
                    f"the unit index returned a row with no CONDO_SSL in a batch "
                    f"of {len(chunk)}. It cannot be joined, and continuing would "
                    f"drop a sampled unit and report it as undocumented.")
            if ssl not in wanted:
                raise SystemExit(
                    f"the unit index returned CONDO_SSL {ssl!r}, which was not in "
                    f"the batch of {len(chunk)} requested. The response does not "
                    f"answer the query.")
            present.add(ssl)
            addr = (a.get("PRIMARY_ADDRESS") or "").strip()
            unit = (a.get("UNIT_NUMBER") or "").strip()
            if not addr or not unit:
                continue
            full = f"{addr} #{unit}, Washington, DC"
            if ssl in out and out[ssl]["address"] != full:
                # Two live rows, two addresses, one SSL. Picking either would put a
                # confident guess in the yardstick itself.
                conflicting.add(ssl)
                continue
            out[ssl] = {"address": full, "lat": "", "lon": ""}
        log.info("  resolved %d/%d units", min(i + DC_BATCH, len(ssls)), len(ssls))
        time.sleep(0.05)
    for ssl in conflicting:
        out.pop(ssl, None)
    if conflicting:
        log.info("dropped %d SSLs the unit index gave more than one address for",
                 len(conflicting))
    return out, present


def _dc_condo_truth(row: dict) -> dict | None:
    """DC's condominium record, in the label's vocabulary. None if ungradeable.

    Two fields, and four deliberately empty. The condominium table has no exterior
    wall, no storey count, no basement and no condition column, so those are left
    blank rather than borrowed from the building the unit sits in — that is a
    different structure's record, and filling them from it would grade the adapter
    against something the District never said about this home.
    """
    year = _num(row.get("AYB"))
    if not year or not (1800 <= year <= 2100):
        return None
    sqft = _num(row.get("LIVING_GBA"))
    return {
        "year_built": int(year),
        "sqft": sqft if sqft and sqft > 0 else "",
        "stories": "",
        "construction": "",
        "foundation": "",
        "condition": "",
    }


def _dc_truth(row: dict) -> dict | None:
    """DC's record, in the label's vocabulary. None if ungradeable."""
    from housing_label.enrich.assessor import dc

    year = _num(row.get("AYB"))
    if not year or not (1800 <= year <= 2100):
        return None
    sqft = _num(row.get("GBA"))
    units = _num(row.get("NUM_UNITS")) or 1
    return {
        "year_built": int(year),
        # Same rule the adapter applies: GBA is the whole building's, the label's
        # figure is per dwelling, so a multi-unit row contributes no floor area
        # rather than a building total wearing a per-unit label.
        "sqft": sqft if sqft and sqft > 0 and units <= 1 else "",
        "stories": dc._stories(row.get("STORIES")) or "",
        "construction": dc._EXT_WALL.get((row.get("EXTWALL_D") or "").strip(), ""),
        "foundation": "",          # DC's residential CAMA has no basement column
        "condition": dc._CONDITION.get((row.get("CNDTN_D") or "").strip(), ""),
    }


def _truth(row: dict) -> dict | None:
    """The county's record, in the label's vocabulary. None if ungradeable."""
    # Reuse the adapter's own mapping tables rather than a second copy: a
    # benchmark that translated differently from the thing it grades would be
    # measuring the difference between two translations, not accuracy.
    from housing_label.enrich.assessor import cook_il

    year = _num(row.get("char_yrblt"))
    if not year or not (1800 <= year <= 2100):
        return None               # nothing to be right or wrong about
    sqft = _num(row.get("char_bldg_sf"))
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
    ap.add_argument("--jurisdiction", choices=sorted(JURISDICTIONS), default="cook",
                    help="which assessor to build a benchmark from (default cook)")
    args = ap.parse_args()

    sys.path.insert(0, str(_ROOT / "src"))
    CACHE_DIR.mkdir(exist_ok=True)
    juris = args.jurisdiction

    # Before the branch, so it holds for every jurisdiction. `_cama_sample`
    # checked it too, but Cook resolves the assessment year FIRST, so `--rows 0`
    # made a live portal request before being told the argument was unusable —
    # the docstring promised "an unusable argument should not cost a request" and
    # the DC path honoured it while Cook did not.
    if args.rows < 1:
        raise SystemExit(f"--rows must be at least 1 (got {args.rows})")

    if juris == "cook":
        year = _latest_year()
        sample, draw = _cama_sample(year, args.rows)
        keys = [str(r["pin"]).zfill(14) for r in sample]
        info, present = _parcel_info(keys)
        truth_of, key_of = _truth, (lambda r: str(r["pin"]).zfill(14))
    elif juris == "dc":
        year = "current"
        sample, draw = _dc_sample(args.rows)
        keys = [(r.get("SSL") or "").strip() for r in sample]
        info, present = _dc_place([k for k in keys if k])
        truth_of, key_of = _dc_truth, (lambda r: (r.get("SSL") or "").strip())
    elif juris == "dc-condo":
        year = "current"
        sample, draw = _dc_condo_sample(args.rows)
        keys = [(r.get("SSL") or "").strip() for r in sample]
        info, present = _dc_condo_place([k for k in keys if k])
        truth_of, key_of = _dc_condo_truth, (lambda r: (r.get("SSL") or "").strip())
    else:
        # The CLI takes its choices from the registry, so a third entry becomes
        # selectable the moment it is added — before anyone writes its sampler. A
        # bare `else` running DC's would have drawn DC parcels, written them to
        # benchmark-<new>.csv and stamped the new jurisdiction on the metadata: a
        # fabricated benchmark, indistinguishable from a real one downstream. This
        # is the cross-jurisdiction fallback again, reached from the other end.
        raise SystemExit(
            f"{juris} is registered in scripts/jurisdictions.py but has no sampler "
            f"in this script. Add one rather than letting another jurisdiction's "
            f"draw be written under its name.")

    log.info("Fetched %d characteristics rows.", len(sample))
    log.info("Resolved %d of them to an address.", len(info))

    # Counted, not inferred. The published note used to derive the cause of every
    # dropped row from `drawn - sampled`, and review found it naming the wrong one
    # four separate times — each fix reworded a guess. The builder is the only
    # place that KNOWS why a row was dropped, so it records it and the page reports
    # what happened rather than reconstructing it from two totals.
    # Three reasons, not two. `_parcel_info`/`_dc_place` omit a parcel both when
    # the layer holds no feature for it and when the feature it holds carries a
    # blank address, and folding those together let the page say "had no address
    # on file" about a parcel whose record was simply not there — a claim about
    # the assessor's documentation that the build has no evidence for.
    out_rows, dropped = [], {"no_parcel_record": 0, "no_address": 0,
                             "no_year_built": 0}
    for row in sample:
        key = key_of(row)
        place = info.get(key)
        if not place:
            # Which of the two it was is now knowable, so it is stated rather than
            # guessed at: the layer either had no record for this parcel, or had
            # one carrying no address.
            dropped["no_address" if key in present else "no_parcel_record"] += 1
            continue
        truth = truth_of(row)
        if not truth:
            dropped["no_year_built"] += 1
            continue
        out_rows.append({"parcel_id": key, "address": place["address"],
                         "lat": place["lat"], "lon": place["lon"], **truth})

    if not out_rows:
        raise SystemExit("no gradeable rows — refusing to write an empty benchmark")

    # Every drawn parcel is either written or counted under a reason. This has
    # been true since the card lookup stopped accepting a short batch, and it is
    # asserted rather than reasoned about because it has been re-derived by hand in
    # four review rounds and quietly stopped holding in three of them. A future
    # path that drops a row without recording why now fails the build instead of
    # publishing a disclosure that silently under-reports the gap.
    unexplained = draw["attempted"] - len(out_rows) - sum(dropped.values())
    if unexplained:
        raise SystemExit(
            f"{draw['attempted']} parcels drawn, {len(out_rows)} written, "
            f"{sum(dropped.values())} dropped for a recorded reason — "
            f"{unexplained} unaccounted for. The published note reports the "
            f"recorded reasons, so writing this would under-report the gap. This "
            f"is a bug in the builder, not a portal problem.")

    # Built in memory and moved into place, rather than truncating the real file
    # and filling it over several minutes of network. An interrupted build used to
    # leave a half-written CSV beside the PREVIOUS run's metadata, and nothing
    # downstream compared the two — so a partial draw could be scored and published
    # wearing the complete run's row count and digest. The rename is atomic, so the
    # file a reader opens is either wholly the old sample or wholly the new one.
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["parcel_id", "address", "lat", "lon"] + FIELDS)
    w.writeheader()
    w.writerows(out_rows)
    payload = buf.getvalue().encode()
    digest = hashlib.sha256(payload).hexdigest()[:16]

    benchmark = benchmark_path(juris)
    _write_atomic(benchmark, payload)

    # Metadata second, and also atomically. Interrupted between the two, the pair
    # is a new CSV beside stale metadata — which the consumer now REFUSES on the
    # digest rather than scoring. Failing that way round is the point: the only
    # states are "matched" and "refused", never "scored the wrong sample".
    _write_atomic(meta_path(juris), json.dumps({
        "jurisdiction": juris,
        # What was actually asked of the assessor. NOT `args.rows`, which both
        # samplers cap to the table's own size — a --rows larger than the source
        # would otherwise claim a draw bigger than the whole table and report the
        # excess as undocumented rows. And not len(sample), which excludes
        # offsets that failed: that would read a portal outage as a smaller clean
        # sample rather than a gap in a full one.
        "drawn": draw["attempted"],
        # And what reached the benchmark, after rows with no address or no usable
        # year were dropped.
        "sampled": len(out_rows),
        # Why each of the others was dropped, so the page states the cause instead
        # of deducing it from `drawn - sampled`.
        "dropped": dropped,
        "source": JURISDICTIONS[juris]["source"],
        "scope": JURISDICTIONS[juris]["scope"],
        "assessment_year": year,
        "fetched": date.today().isoformat(),
        "rows": len(out_rows),
        "sha256_16": digest,
    }, indent=2) + "\n")

    log.info("Wrote %s (%d rows, digest %s).", benchmark, len(out_rows), digest)
    log.info("Not committed — see this script's docstring for why.")
    for fld in FIELDS:
        have = sum(1 for r in out_rows if r.get(fld) not in (None, ""))
        log.info("  ground truth %-13s %d/%d", fld, have, len(out_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
