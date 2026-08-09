"""A persistent cache for batch geocode results.

Geocoding is the only part of bulk scoring that must go out to the network, and
it is the part you are most likely to repeat: a book gets re-scored when the
reference data is rebuilt, when a construction field is corrected, or simply
because the run died at row 380,000. Re-requesting 400,000 addresses to learn
what was already learned is slow, and it is rude to a free government endpoint.

Keyed on the address AND the geocoder version
---------------------------------------------
The cache key includes the benchmark and vintage the result was obtained under
(``Public_AR_Current`` / ``Current_Current`` today, from ``simulate/location``).
This is not bookkeeping: those pins move, and TIGER redraws tracts. A cache keyed
on the address alone would keep serving the old tract after a benchmark change,
with every score downstream computed against the wrong geography and nothing
anywhere reporting a problem — the same silent-staleness this codebase has now
been bitten by twice. Change the benchmark and the old rows simply stop matching.

Misses are cached too
---------------------
An address the Census cannot place is a result, not an absence. Caching only the
matches means a book with 5% bad addresses re-requests that 5% on every single
run, forever, which is the case where re-requesting helps least. Each row carries
the time it was written, so a caller can expire misses (``max_age_days``) and
retry them later — the Census does add addresses — while matches, which do not
rot the same way, stay indefinitely.

SQLite because it is in the standard library
--------------------------------------------
No new dependency, indexed lookups rather than holding 400,000 rows in memory,
and durable incremental commits, which means a run killed halfway keeps every
address it had already resolved. That last property is what makes a multi-hour
geocode restartable, and it comes for free.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path

from housing_label.geocode import GeocodeResult
from housing_label.simulate.location import BENCHMARK, VINTAGE

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS geocode (
    key        TEXT PRIMARY KEY,
    matched    INTEGER NOT NULL,
    status     TEXT NOT NULL,
    lat        REAL,
    lon        REAL,
    tract      TEXT,
    county_fips TEXT,
    state_fips TEXT,
    matched_address TEXT,
    cached_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

_WS = re.compile(r"\s+")


def address_key(street: str, city: str, state: str, zipc: str,
                *, benchmark: str = BENCHMARK, vintage: str = VINTAGE) -> str:
    """Stable cache key for one address under one geocoder version.

    Normalised so trivial formatting differences ("123 Main St" vs "123  MAIN
    st ") hit the same row — a book re-exported from a different system should
    not miss on every line. Deliberately NOT normalised any further than case and
    whitespace: collapsing "St"/"Street" or dropping punctuation would risk
    merging two genuinely different addresses, and a wrong cache hit is worse
    than a miss.
    """
    parts = [_WS.sub(" ", (p or "").strip()).upper()
             for p in (street, city, state, zipc)]
    return "|".join([benchmark, vintage, *parts])


class GeocodeCache:
    """Address → GeocodeResult, persisted in a SQLite file.

    Usable as a context manager. Safe to point at a path that does not exist yet.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.executescript(_SCHEMA)
        self._check_schema_version()
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def _check_schema_version(self) -> None:
        cur = self._db.execute("SELECT v FROM meta WHERE k = 'schema_version'")
        row = cur.fetchone()
        if row is None:
            self._db.execute("INSERT INTO meta (k, v) VALUES ('schema_version', ?)",
                             (str(SCHEMA_VERSION),))
            self._db.commit()
            return
        if int(row[0]) != SCHEMA_VERSION:
            # Refuse rather than guess at an older layout. The cache is
            # reconstructible by definition — deleting it costs requests, not data
            # — so a clear error beats reading columns that may have moved.
            raise ValueError(
                f"{self.path} was written by geocode cache schema v{row[0]}, this "
                f"is v{SCHEMA_VERSION}. Delete the file to rebuild it.")

    # ── reads ────────────────────────────────────────────────────────────────
    def get(self, key: str, *, max_age_days: float | None = None
            ) -> GeocodeResult | None:
        cur = self._db.execute(
            "SELECT matched, status, lat, lon, tract, county_fips, state_fips, "
            "matched_address, cached_at FROM geocode WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            self.misses += 1
            return None
        matched = bool(row[0])
        # Only misses expire. A match is a fact about where an address is, and
        # re-requesting it buys nothing; a miss is a fact about what the Census
        # knew on the day, and it does add addresses over time.
        if not matched and max_age_days is not None:
            if (time.time() - row[8]) > max_age_days * 86400:
                self.misses += 1
                return None
        self.hits += 1
        return GeocodeResult(
            id="", matched=matched, status=row[1], lat=row[2], lon=row[3],
            tract=row[4], county_fips=row[5], state_fips=row[6],
            matched_address=row[7])

    # ── writes ───────────────────────────────────────────────────────────────
    def put(self, key: str, res: GeocodeResult) -> None:
        self.put_many([(key, res)])

    def put_many(self, items) -> None:
        rows = [(k, int(r.matched), r.status, r.lat, r.lon, r.tract,
                 r.county_fips, r.state_fips, r.matched_address, time.time())
                for k, r in items]
        if not rows:
            return
        self._db.executemany(
            "INSERT OR REPLACE INTO geocode (key, matched, status, lat, lon, "
            "tract, county_fips, state_fips, matched_address, cached_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        # Committed per chunk, not at the end: a run killed at row 380,000 keeps
        # every address it had already resolved, which is what makes a multi-hour
        # geocode restartable.
        self._db.commit()
        self.writes += len(rows)

    # ── housekeeping ─────────────────────────────────────────────────────────
    def stats(self) -> dict:
        n = self._db.execute("SELECT COUNT(*) FROM geocode").fetchone()[0]
        matched = self._db.execute(
            "SELECT COUNT(*) FROM geocode WHERE matched = 1").fetchone()[0]
        return {"rows": n, "matched": matched, "unmatched": n - matched,
                "hits": self.hits, "misses": self.misses, "writes": self.writes}

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
