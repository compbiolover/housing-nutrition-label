#!/usr/bin/env python3
"""Offline tests for the geocode cache (no network, no pytest).

This file alone:  pytest tests/test_geocode_cache.py
"""

import tempfile
import time
from pathlib import Path

from housing_label import geocode as G
from housing_label import geocode_cache as GC
from housing_label.geocode import GeocodeResult

HIT = GeocodeResult(id="", matched=True, status="Match", lat=35.15, lon=-89.85,
                    tract="47157003100", county_fips="47157", state_fips="47",
                    matched_address="1 MAIN ST")
MISS = GeocodeResult(id="", matched=False, status="No_Match")


def _tmp():
    return Path(tempfile.mkdtemp()) / "geo.sqlite"


# ── The staleness guard ──────────────────────────────────────────────────────
def test_key_includes_benchmark_and_vintage():
    """The point of the whole key design.

    The Census benchmark and vintage pins move, and TIGER redraws tracts. A cache
    keyed on the address alone would keep serving the old tract after a benchmark
    change — every score downstream computed against the wrong geography, with
    nothing reporting a problem. Changing either pin simply stops the old rows
    matching.
    """
    same = ("1 Main St", "Memphis", "TN", "38104")
    a = GC.address_key(*same)
    assert GC.address_key(*same) == a                       # stable
    assert GC.address_key(*same, benchmark="Public_AR_2020") != a
    assert GC.address_key(*same, vintage="Census2020_Current") != a


def test_a_benchmark_change_misses_rather_than_serving_a_stale_tract():
    path = _tmp()
    with GC.GeocodeCache(path) as c:
        c.put(GC.address_key("1 Main St", "Memphis", "TN", "38104"), HIT)
    with GC.GeocodeCache(path) as c:
        assert c.get(GC.address_key("1 Main St", "Memphis", "TN", "38104")) is not None
        stale = GC.address_key("1 Main St", "Memphis", "TN", "38104",
                               benchmark="Public_AR_2020")
        assert c.get(stale) is None


def test_key_normalises_case_and_whitespace_but_nothing_riskier():
    """A book re-exported from another system should not miss on every line. But
    normalising further — St/Street, punctuation — could merge two genuinely
    different addresses, and a wrong hit is worse than a miss."""
    a = GC.address_key("123  main   st ", "MEMPHIS", "tn", "38104")
    b = GC.address_key("123 Main St", "Memphis", "TN", "38104")
    assert a == b
    assert GC.address_key("123 Main Street", "Memphis", "TN", "38104") != b


# ── Round trip ───────────────────────────────────────────────────────────────
def test_round_trip_preserves_every_field():
    path = _tmp()
    key = GC.address_key("1 Main St", "Memphis", "TN", "38104")
    with GC.GeocodeCache(path) as c:
        c.put(key, HIT)
    with GC.GeocodeCache(path) as c:          # survives reopening
        got = c.get(key)
    assert got.matched and got.status == "Match"
    assert got.lat == 35.15 and got.lon == -89.85
    assert got.tract == "47157003100" and got.county_fips == "47157"
    assert got.matched_address == "1 MAIN ST"


def test_misses_are_cached_too():
    """A book with 5% bad addresses would otherwise re-request that 5% on every
    run, forever — the case where re-requesting helps least."""
    path = _tmp()
    key = GC.address_key("nowhere", "", "", "")
    with GC.GeocodeCache(path) as c:
        c.put(key, MISS)
        got = c.get(key)
    assert got is not None and got.matched is False


def test_only_misses_expire():
    """A match is a fact about where an address is; a miss is a fact about what
    the Census knew that day, and it does add addresses over time."""
    path = _tmp()
    hk = GC.address_key("hit", "", "", "")
    mk = GC.address_key("miss", "", "", "")
    with GC.GeocodeCache(path) as c:
        c.put(hk, HIT)
        c.put(mk, MISS)
        # Backdate both by 30 days.
        old = time.time() - 30 * 86400
        c._db.execute("UPDATE geocode SET cached_at = ?", (old,))
        c._db.commit()
        assert c.get(mk, max_age_days=7) is None          # miss expired
        assert c.get(hk, max_age_days=7) is not None      # match did not


def test_schema_version_mismatch_is_refused_not_guessed_at():
    """The cache is reconstructible by definition — deleting it costs requests,
    not data — so a clear error beats reading columns that may have moved."""
    path = _tmp()
    with GC.GeocodeCache(path) as c:
        c._db.execute("UPDATE meta SET v = '999' WHERE k = 'schema_version'")
        c._db.commit()
    try:
        GC.GeocodeCache(path)
    except ValueError as exc:
        assert "999" in str(exc) and "Delete" in str(exc)
    else:
        raise AssertionError("a foreign schema version should be refused")


def test_the_refusal_releases_the_file_it_tells_you_to_delete():
    """The error says "delete the file". Raising with the connection still open
    holds a lock on exactly that file — on Windows the delete then fails, so the
    message would be telling the reader to do something it had just prevented."""
    import os
    path = _tmp()
    with GC.GeocodeCache(path) as c:
        c._db.execute("UPDATE meta SET v = '999' WHERE k = 'schema_version'")
        c._db.commit()
    try:
        GC.GeocodeCache(path)
    except ValueError:
        pass
    os.remove(path)          # would raise PermissionError on a locked handle
    assert not path.exists()


def test_a_corrupted_version_is_refused_readably():
    """int('zzz') would raise ValueError too, but with a message about parsing
    rather than about the cache — and from a line that never closed the file."""
    path = _tmp()
    with GC.GeocodeCache(path) as c:
        c._db.execute("UPDATE meta SET v = 'zzz' WHERE k = 'schema_version'")
        c._db.commit()
    try:
        GC.GeocodeCache(path)
    except ValueError as exc:
        assert "unreadable version" in str(exc) and "Delete" in str(exc)
    else:
        raise AssertionError("a corrupted schema version should be refused")


# ── Integration with geocode_rows ────────────────────────────────────────────
def _counting_transport(mapping, calls):
    def fake(payload, session=None):
        import csv as _csv
        import io as _io
        out = []
        for row in _csv.reader(_io.StringIO(payload)):
            calls.append(row[0])
            hit = mapping.get(row[1].upper())
            if hit is None:
                out.append(f'"{row[0]}","in","No_Match"')
                continue
            lat, lon, tract = hit
            out.append(f'"{row[0]}","in","Match","Exact","m","{lon},{lat}",'
                       f'"0","L","{tract[:2]}","{tract[2:5]}","{tract[5:]}","0"')
        return "\n".join(out) + "\n"
    return fake


def test_second_run_makes_no_requests():
    path = _tmp()
    rows = [{"id": "A", "street": "1 Main St", "city": "Memphis", "state": "TN"}]
    calls: list[str] = []
    real = G._request_chunk
    G._request_chunk = _counting_transport({"1 MAIN ST": (35.15, -89.85,
                                                          "47157003100")}, calls)
    try:
        with GC.GeocodeCache(path) as c:
            first = list(G.geocode_rows(rows, cache=c))
        assert len(calls) == 1 and first[0].tract == "47157003100"
        calls.clear()
        with GC.GeocodeCache(path) as c:
            second = list(G.geocode_rows(rows, cache=c))
        assert calls == [], "second run must not reach the endpoint"
        assert second[0].tract == "47157003100"
        assert second[0].id == "A", "a cached hit must carry THIS row's id"
    finally:
        G._request_chunk = real


def test_partial_cache_hits_preserve_input_order():
    """The trap in caching a streamed generator: yielding hits the moment they are
    found reorders the stream against the input, so a caller zipping the two
    lists mismatches every parcel after the first hit — silently, and only when
    caching happened to be on."""
    path = _tmp()
    mapping = {"1 MAIN ST": (35.1, -89.1, "47157003100"),
               "2 MAIN ST": (35.2, -89.2, "47157003200"),
               "3 MAIN ST": (35.3, -89.3, "47157003300")}
    rows = [{"id": str(i), "street": f"{i} Main St", "city": "M", "state": "TN"}
            for i in (1, 2, 3)]
    calls: list[str] = []
    real = G._request_chunk
    G._request_chunk = _counting_transport(mapping, calls)
    try:
        # Seed only the MIDDLE row, so the run is a hit sandwiched by misses.
        with GC.GeocodeCache(path) as c:
            c.put(GC.address_key("2 Main St", "M", "TN", ""),
                  GeocodeResult(id="", matched=True, status="Match", lat=35.2,
                                lon=-89.2, tract="47157003200",
                                county_fips="47157", state_fips="47"))
            out = list(G.geocode_rows(rows, cache=c))
    finally:
        G._request_chunk = real
    assert [r.id for r in out] == ["1", "2", "3"]
    assert [r.tract for r in out] == ["47157003100", "47157003200", "47157003300"]


def test_transport_failures_are_not_cached():
    """A connection reset says nothing about the address. Persisting it would
    poison that entry until someone cleared the file by hand."""
    path = _tmp()
    rows = [{"id": "A", "street": "1 Main St", "city": "M", "state": "TN"}]
    real = G._request_chunk

    def boom(payload, session=None):
        raise RuntimeError("connection reset")

    G._request_chunk = boom
    try:
        with GC.GeocodeCache(path) as c:
            out = list(G.geocode_rows(rows, cache=c))
            assert out[0].matched is False
            assert c.get(GC.address_key("1 Main St", "M", "TN", "")) is None
    finally:
        G._request_chunk = real


def test_results_are_committed_per_chunk_so_a_dead_run_keeps_them():
    """What makes a multi-hour geocode restartable."""
    path = _tmp()
    rows = [{"id": str(i), "street": f"{i} Main St", "city": "M", "state": "TN"}
            for i in range(4)]
    mapping = {f"{i} MAIN ST": (35.0 + i, -89.0, "47157003100") for i in range(4)}
    calls: list[str] = []
    real = G._request_chunk
    G._request_chunk = _counting_transport(mapping, calls)
    try:
        with GC.GeocodeCache(path) as c:
            # chunk_size 2 → two flushes; stop consuming after the first.
            gen = G.geocode_rows(rows, chunk_size=2, cache=c)
            next(gen)
            gen.close()
        # A separate connection sees the first chunk already durable on disk.
        with GC.GeocodeCache(path) as c:
            assert c.stats()["rows"] == 2
    finally:
        G._request_chunk = real
