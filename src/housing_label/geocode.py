"""Bulk address → coordinates + census tract, via the Census batch geocoder.

Removes the one prerequisite bulk scoring could not meet on its own. Supplying a
tract per row makes a portfolio score with no network at all (see
``housing_label.batch``) — but a city, an assessor's office or a smaller shop
often holds only addresses, and for them that advantage evaporated.

The Census batch endpoint takes up to 10,000 addresses per POST and returns, for
each, the matched coordinates **and** the state/county/tract. That is exactly the
geography bulk scoring wants, so one pre-pass over a book of addresses turns it
into a book that scores offline. Roughly two calls per 10,000 parcels, against
one call per parcel for the per-address geocoder.

Three properties of the response the code has to respect, each of which is a
silent wrong answer if missed:

* **Coordinates are returned longitude-first** (``"-77.035,38.898"``). Reading
  them in the order they appear puts every parcel on the wrong side of the
  planet, and nothing downstream would complain — a tract still resolves, a
  score still comes out.
* **Row order is not guaranteed**, so results are joined back by id, never by
  position. Zipping the two lists would quietly attach each parcel's geography
  to a different parcel.
* **Unmatched rows are short.** A match returns twelve fields; a ``No_Match``
  returns three. Indexing blind raises on the misses, which are the rows most
  likely to exist in real data.

Non-matches are reported, never guessed at. An address the Census cannot place
comes back with ``matched=False`` and its status, and the caller decides — a
fabricated coordinate would score a real parcel against the wrong neighbourhood.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from typing import Iterable, Iterator

from housing_label.config import TIMEOUT
from housing_label.simulate.location import BENCHMARK, VINTAGE

log = logging.getLogger(__name__)

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

# The endpoint's documented ceiling. Chunks are capped here rather than at some
# smaller "safe" number: fewer, larger requests is the entire point.
MAX_BATCH = 10_000

# A batch of 10,000 is a minutes-long request, not a seconds-long one, so it gets
# its own timeout instead of the per-call HTTP_TIMEOUT tuned for single lookups.
BATCH_TIMEOUT = max(TIMEOUT * 10, 600)

# Column positions in a matched response row (no header is returned).
_C_ID, _C_INPUT, _C_STATUS, _C_MATCHTYPE = 0, 1, 2, 3
_C_MATCHED_ADDR, _C_COORDS = 4, 5
_C_STATE, _C_COUNTY, _C_TRACT = 8, 9, 10
_MATCHED_WIDTH = 11          # a matched row has at least this many fields


@dataclass(frozen=True)
class GeocodeResult:
    """One address's outcome. ``matched`` False means the Census could not place
    it — the geography fields are then None rather than a guess."""

    id: str
    matched: bool
    status: str                      # Match | No_Match | Tie | (transport error)
    lat: float | None = None
    lon: float | None = None
    tract: str | None = None         # 11-digit GEOID
    county_fips: str | None = None   # 5-digit
    state_fips: str | None = None    # 2-digit
    matched_address: str | None = None


def split_address(address: str) -> tuple[str, str, str, str]:
    """Best-effort split of a one-line address into street/city/state/zip.

    The batch endpoint wants the four parts separately; a customer export often
    has them already (use the ``street``/``city``/``state``/``zip`` columns when
    so). This is the fallback for a single ``address`` column, and it is
    deliberately simple: split on commas, and read a trailing "ST 12345" or
    "12345" off the end. A freeform address that does not fit that shape is
    passed through as street-only, which the Census will usually still match on
    but less precisely — better than dropping the row, and visible in the match
    type it comes back with.
    """
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if not parts:
        return "", "", "", ""
    street, rest = parts[0], parts[1:]
    zipc = state = ""

    # Work from the END, because that is the part with a recognisable shape. The
    # ZIP may be its own comma field ("…, DC, 20500") or ride along with the state
    # ("…, DC 20500"); both are common in real exports, and an earlier version of
    # this that only handled the second silently dropped the state from the first.
    if rest:
        tail = rest[-1].split()
        if tail and tail[-1].replace("-", "").isdigit():
            zipc = tail[-1]
            tail = tail[:-1]
            if tail:
                rest[-1] = " ".join(tail)
            else:
                rest.pop()
    if rest and len(rest[-1]) == 2 and rest[-1].isalpha():
        state = rest.pop().upper()

    city = rest[-1] if rest else ""
    return street, city, state, zipc


def _request_chunk(payload: str, session=None) -> str:
    """POST one chunk's CSV and return the response body."""
    import requests

    files = {"addressFile": ("addresses.csv", payload, "text/csv")}
    data = {"benchmark": BENCHMARK, "vintage": VINTAGE}
    poster = session.post if session is not None else requests.post
    resp = poster(CENSUS_BATCH_URL, files=files, data=data, timeout=BATCH_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_response(body: str) -> dict[str, GeocodeResult]:
    """Parse a batch response body into ``{id: GeocodeResult}``.

    Keyed by id, never by position — the endpoint does not promise to return rows
    in the order they were sent.
    """
    out: dict[str, GeocodeResult] = {}
    for row in csv.reader(io.StringIO(body)):
        if not row:
            continue
        rid = row[_C_ID].strip()
        status = row[_C_STATUS].strip() if len(row) > _C_STATUS else "No_Match"
        # A No_Match row is three fields wide; only a match carries geography.
        if status != "Match" or len(row) <= _MATCHED_WIDTH:
            out[rid] = GeocodeResult(id=rid, matched=False, status=status or "No_Match")
            continue
        try:
            # "lon,lat" — longitude FIRST. Reversing this is undetectable
            # downstream: the parcel still resolves to a tract, just the wrong one.
            lon_s, lat_s = row[_C_COORDS].split(",", 1)
            lat, lon = float(lat_s), float(lon_s)
            state = row[_C_STATE].strip().zfill(2)
            county = row[_C_COUNTY].strip().zfill(3)
            tract = row[_C_TRACT].strip().zfill(6)
        except (ValueError, IndexError) as exc:
            out[rid] = GeocodeResult(id=rid, matched=False,
                                     status=f"unparseable match ({exc})")
            continue
        out[rid] = GeocodeResult(
            id=rid, matched=True, status=status, lat=lat, lon=lon,
            tract=f"{state}{county}{tract}", county_fips=f"{state}{county}",
            state_fips=state, matched_address=row[_C_MATCHED_ADDR].strip() or None)
    return out


def geocode_chunk(addresses: list[tuple[str, str, str, str, str]],
                  session=None) -> dict[str, GeocodeResult]:
    """Geocode up to ``MAX_BATCH`` ``(id, street, city, state, zip)`` tuples."""
    if len(addresses) > MAX_BATCH:
        raise ValueError(f"chunk of {len(addresses)} exceeds the endpoint's "
                         f"{MAX_BATCH}-record limit")
    if not addresses:
        return {}
    buf = io.StringIO()
    w = csv.writer(buf)
    for rec in addresses:
        w.writerow(rec)
    results = parse_response(_request_chunk(buf.getvalue(), session=session))
    # An id the endpoint dropped entirely must not silently vanish from the run.
    for rid, *_ in addresses:
        results.setdefault(rid, GeocodeResult(id=rid, matched=False,
                                              status="not returned by the geocoder"))
    return results


def geocode_rows(rows: Iterable[dict], *, chunk_size: int = MAX_BATCH,
                 session=None, cache=None,
                 max_miss_age_days: float | None = None) -> Iterator[GeocodeResult]:
    """Geocode input rows, yielding one result per row **in input order**.

    Each row needs an ``id`` plus either ``street``/``city``/``state``/``zip`` or
    a single ``address``. A whole chunk that fails in transport yields per-row
    failures rather than raising: one bad chunk out of forty should cost forty
    rows' worth of geography, not the entire run.

    ``cache`` is an optional ``geocode_cache.GeocodeCache``. Rows it can answer
    never reach the endpoint. Order is preserved even when only some rows hit:
    yielding hits the moment they are found would reorder the stream against the
    input, and a caller zipping the two lists would mismatch every parcel after
    the first hit — silently, and only when caching happened to be on.
    """
    from dataclasses import replace

    chunk_size = max(1, min(int(chunk_size), MAX_BATCH))

    def cache_key(rec):
        from housing_label.geocode_cache import address_key
        return address_key(rec[1], rec[2], rec[3], rec[4])

    # Input order, each entry either a resolved result or a record still to send.
    pending: list[tuple[str, object]] = []
    batch: list[tuple[str, str, str, str, str]] = []

    def flush():
        nonlocal pending, batch
        found = {}
        if batch:
            try:
                found = geocode_chunk(batch, session=session)
            except Exception as exc:  # noqa: BLE001
                log.warning("geocode chunk of %d failed: %s", len(batch), exc)
                found = {rid: GeocodeResult(id=rid, matched=False,
                                            status=f"geocoder error: {exc}")
                         for rid, *_ in batch}
            if cache is not None:
                # Per chunk, not at the end, so a run that dies keeps what it had
                # already resolved. Transport failures are deliberately NOT
                # cached: they say nothing about the address, and persisting one
                # would poison that entry until the file was cleared by hand.
                cache.put_many([(cache_key(rec), found[rec[0]]) for rec in batch
                                if not found[rec[0]].status.startswith(
                                    "geocoder error")])
        out = [payload if kind == "hit" else found[payload[0]]
               for kind, payload in pending]
        pending, batch = [], []
        return out

    for i, row in enumerate(rows):
        rid = str(row.get("id") or i)
        street = (row.get("street") or "").strip()
        if street:
            rec = (rid, street, (row.get("city") or "").strip(),
                   (row.get("state") or "").strip(), (row.get("zip") or "").strip())
        else:
            rec = (rid, *split_address(row.get("address") or ""))

        hit = None
        if cache is not None:
            hit = cache.get(cache_key(rec), max_age_days=max_miss_age_days)
        if hit is not None:
            # A cached row is keyed on the address, so it carries no id of its
            # own — reattach this row's or the caller cannot join it back.
            pending.append(("hit", replace(hit, id=rid)))
        else:
            pending.append(("todo", rec))
            batch.append(rec)

        # Bound memory on both axes: a book that is entirely cache hits would
        # otherwise grow `pending` without ever filling `batch`.
        if len(batch) >= chunk_size or len(pending) >= chunk_size:
            yield from flush()

    yield from flush()
