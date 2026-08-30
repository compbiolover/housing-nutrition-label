#!/usr/bin/env python3
"""One invariant, across every memoized point lookup: a transient upstream
failure must not become a permanent answer.

Each lookup below is wrapped in ``lru_cache`` for the life of the process, and
each used to signal "the service did not answer" with the same value it uses for
"the service answered, and there is nothing here" — a ``None``, or FEMA's
``flood_risk: "unknown"``. That conflation is what made an outage sticky: one bad
minute at FEMA or the Census geocoder pinned a degraded answer onto a coordinate
until the process restarted, defeating ``api._may_cache``, which goes out of its
way not to pin a degraded *label* to a URL for even six hours.

The fix is the one ``enrich/solar_point.py`` already used: raise on the transport
failure, because ``lru_cache`` does not memoize a raise. So every test here is the
same shape — fail the upstream once, succeed the second time, and assert the
second call sees the real answer rather than the memoized failure. Each also
checks the other half: a genuine "nothing here" verdict is still cached, because
that one is an answer.

Runs without network (every upstream is stubbed).
This file alone: ``pytest tests/test_transient_not_cached.py``.
"""

from __future__ import annotations

import pytest


class _Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.ok = status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _flaky(monkeypatch, module, payloads):
    """Patch module.requests.get to walk `payloads`; a RuntimeError entry raises.

    Returns a list that records one entry per call, so a test can assert the
    second call actually re-hit the network rather than being served from a memo.
    """
    calls: list = []
    seq = list(payloads)

    def fake_get(*_a, **_kw):
        calls.append(1)
        nxt = seq.pop(0) if seq else seq_last
        if isinstance(nxt, Exception):
            raise nxt
        return _Resp(nxt)

    seq_last = payloads[-1]
    monkeypatch.setattr(module.utils, "retry_wait", lambda *a, **k: None)
    monkeypatch.setattr(module.requests, "get", fake_get)
    return calls


# ── FEMA flood zone ────────────────────────────────────────────────────────────
_FEMA_AE = {"features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": None}}]}


def test_flood_outage_is_not_memoized(monkeypatch):
    from housing_label.enrich import fema_flood as ff

    ff._flood_zone_at.cache_clear()
    # Every attempt of the first call fails; the retry after that succeeds.
    fails = [RuntimeError("boom")] * ff.MAX_RETRIES
    calls = _flaky(monkeypatch, ff, fails + [_FEMA_AE])

    with pytest.raises(ff.FloodDataUnavailable):
        ff.fetch_flood_zone(35.1, -90.0)
    spent = len(calls)
    assert ff.fetch_flood_zone(35.1, -90.0)["flood_zone"] == "AE"
    assert len(calls) > spent, "second call was served from the memo, not the network"


def test_flood_no_polygon_here_is_memoized(monkeypatch):
    """"Outside the mapped area" is a verdict about the point, so it is kept."""
    from housing_label.enrich import fema_flood as ff

    ff._flood_zone_at.cache_clear()
    calls = _flaky(monkeypatch, ff, [{"features": []}])

    assert ff.fetch_flood_zone(36.2, -91.1)["flood_risk"] == "unknown"
    spent = len(calls)
    assert ff.fetch_flood_zone(36.2, -91.1)["flood_risk"] == "unknown"
    assert len(calls) == spent, "a real verdict should not be re-fetched"


# ── USGS seismic ───────────────────────────────────────────────────────────────
def _nshm(pga_xs, pga_ys):
    return {"response": {"hazardCurves": [{
        "imt": {"value": "PGA"},
        "data": [{"component": "Total", "values": {"xs": pga_xs, "ys": pga_ys}}],
    }]}}


_CURVE = _nshm([0.1, 0.3, 0.6], [0.01, 0.001, 0.0001])


def test_seismic_outage_is_not_memoized(monkeypatch):
    from housing_label.enrich import seismic_lookup as sl

    sl._nshm_hazard_pga.cache_clear()
    sl._usgs_pga.cache_clear()
    fails = [RuntimeError("boom")] * sl.RETRIES
    calls = _flaky(monkeypatch, sl, fails + [_CURVE])

    with pytest.raises(sl.SeismicDataUnavailable):
        sl._nshm_hazard_pga(35.1, -90.0)
    spent = len(calls)
    assert sl._nshm_hazard_pga(35.1, -90.0) is not None
    assert len(calls) > spent, "second call was served from the memo, not the network"


def test_seismic_outside_conus_is_memoized(monkeypatch):
    """A point off the CONUS grid never touches the network, and stays cached."""
    from housing_label.enrich import seismic_lookup as sl

    sl._nshm_hazard_pga.cache_clear()
    calls = _flaky(monkeypatch, sl, [_CURVE])
    assert sl._nshm_hazard_pga(21.3, -157.8) is None      # Honolulu
    assert not calls, "an out-of-CONUS point should not be queried at all"


def test_get_pga_still_falls_through_on_an_outage(monkeypatch):
    """The raise must not escape get_pga: an unreachable NSHM drops to the next
    tier for this call, exactly as a None did before."""
    from housing_label.enrich import seismic_lookup as sl

    sl._nshm_hazard_pga.cache_clear()
    sl._usgs_pga.cache_clear()
    _flaky(monkeypatch, sl, [RuntimeError("boom")] * (sl.RETRIES * 2))
    got = sl.get_pga(35.1, -90.0)                          # falls to the bundled grid
    assert got is None or got[2] == "bundled PGA grid × ratio"


# ── Census geocoder: address and coordinates ───────────────────────────────────
_MATCH = {"result": {"addressMatches": [{
    "coordinates": {"x": -90.0, "y": 35.1},
    "matchedAddress": "1 MAIN ST, MEMPHIS, TN, 38103",
    "geographies": {"Counties": [{"GEOID": "47157", "NAME": "Shelby", "STATE": "47"}]},
}]}}
_GEOS = {"result": {"geographies": {
    "Counties": [{"GEOID": "47157", "NAME": "Shelby", "STATE": "47"}]}}}


def test_geocode_address_outage_is_not_memoized(monkeypatch):
    from housing_label.simulate import location as loc

    loc._geocode_address_cached.cache_clear()
    fails = [RuntimeError("boom")] * loc.RETRIES
    calls = _flaky(monkeypatch, loc, fails + [_MATCH])

    assert loc.geocode_address("1 Main St") is None        # outage → None, uncached
    spent = len(calls)
    assert (loc.geocode_address("1 Main St") or {}).get("county_fips") == "47157"
    assert len(calls) > spent, "second call was served from the memo, not the network"


def test_geocode_no_such_address_is_memoized(monkeypatch):
    """An empty match list is the geocoder answering, so it is kept."""
    from housing_label.simulate import location as loc

    loc._geocode_address_cached.cache_clear()
    calls = _flaky(monkeypatch, loc, [{"result": {"addressMatches": []}}])

    assert loc.geocode_address("nowhere at all") is None
    spent = len(calls)
    assert loc.geocode_address("nowhere at all") is None
    assert len(calls) == spent, "a real 'no match' should not be re-fetched"


def test_geographies_outage_is_not_memoized(monkeypatch):
    """The costliest one: no geography means eight tract-keyed dimensions go
    unscored, and a memoized outage would keep them that way until restart."""
    from housing_label.simulate import location as loc

    loc._geographies_cached.cache_clear()
    fails = [RuntimeError("boom")] * loc.RETRIES
    calls = _flaky(monkeypatch, loc, fails + [_GEOS])

    assert loc.geographies_for_coords(35.1, -90.0) is None
    spent = len(calls)
    assert (loc.geographies_for_coords(35.1, -90.0) or {}).get("county_fips") == "47157"
    assert len(calls) > spent, "second call was served from the memo, not the network"


# ── Census tract geocode (health.py, memoized by dimensions._tract_for) ────────
_TRACT = {"result": {"geographies": {"Census Tracts": [{"GEOID": "47157003100"}]}}}


def test_tract_lookup_outage_is_not_memoized(monkeypatch):
    from housing_label.enrich import health as health_mod
    from housing_label.simulate import dimensions as dim

    dim._tract_for_cached.cache_clear()
    fails = [RuntimeError("boom")] * health_mod.MAX_RETRIES
    calls = _flaky(monkeypatch, health_mod, fails + [_TRACT])

    assert dim._tract_for(35.1, -90.0) is None             # outage → None, uncached
    spent = len(calls)
    assert dim._tract_for(35.1, -90.0) == "47157003100"
    assert len(calls) > spent, "second call was served from the memo, not the network"


def test_tract_lookup_no_tract_here_is_memoized(monkeypatch):
    from housing_label.enrich import health as health_mod
    from housing_label.simulate import dimensions as dim

    dim._tract_for_cached.cache_clear()
    calls = _flaky(monkeypatch, health_mod,
                   [{"result": {"geographies": {"Census Tracts": []}}}])

    assert dim._tract_for(0.0, 0.0) is None
    spent = len(calls)
    assert dim._tract_for(0.0, 0.0) is None
    assert len(calls) == spent, "a real 'no tract' should not be re-fetched"
