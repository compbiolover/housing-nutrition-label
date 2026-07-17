#!/usr/bin/env python3
"""Offline tests for the HTTP API (skipped if FastAPI isn't installed).

Run directly:  python tests/test_api.py
"""


def test_api_healthz_and_validation():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        # Skip only when FastAPI/TestClient is genuinely unavailable.
        print("  skip test_api_healthz_and_validation (fastapi not installed)")
        return
    # Imported outside the guard so a real import error in housing_label.api
    # (e.g. a broken import/rename) fails the test instead of being skipped.
    from housing_label.api import app
    client = TestClient(app)
    assert client.get("/healthz").json() == {"ok": True}
    # Missing both address and lat/lon → 400, no network involved.
    assert client.get("/label").status_code == 400


def test_cors_default_allowlist():
    """CORS must echo Access-Control-Allow-Origin for the configured origin and
    omit it for others — guards against regressing back to a wildcard."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_cors_default_allowlist (fastapi not installed)")
        return
    import os
    from housing_label.api import app, ALLOWED_ORIGINS
    # With no override, the default must lock to the production site (not "*").
    if not os.environ.get("ALLOWED_ORIGINS"):
        assert ALLOWED_ORIGINS == ["https://housinglabel.dev"], ALLOWED_ORIGINS
    assert "*" not in ALLOWED_ORIGINS, "CORS must not be a wildcard"
    client = TestClient(app)

    ok_origin = ALLOWED_ORIGINS[0]
    allowed = client.get("/healthz", headers={"Origin": ok_origin})
    assert allowed.headers.get("access-control-allow-origin") == ok_origin

    blocked = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert blocked.headers.get("access-control-allow-origin") is None


def test_photon_label_formatter():
    """Pure helpers — no network. Importing housing_label.api needs FastAPI, so
    skip (like the other tests) when it isn't installed."""
    try:
        import fastapi  # noqa: F401 — housing_label.api needs it at import time
    except ImportError:
        print("  skip test_photon_label_formatter (fastapi not installed)")
        return
    # Imported outside the guard so a real import error in housing_label.api fails the test.
    from housing_label.api import _photon_label, _photon_features_to_suggestions
    assert _photon_label({
        "housenumber": "123", "street": "Main St", "city": "Memphis",
        "state": "TN", "postcode": "38104",
    }) == "123 Main St, Memphis, TN, 38104"
    # POI with a name but no street/housenumber falls back to the name.
    assert _photon_label({"name": "Griffith Observatory", "city": "Los Angeles"}) \
        == "Griffith Observatory, Los Angeles"

    feats = [
        {"properties": {"countrycode": "US", "name": "A", "city": "X", "state": "CA"},
         "geometry": {"coordinates": [-118.0, 34.0]}},                 # keep ([lon,lat])
        {"properties": {"countrycode": "us", "name": "B", "city": "Y", "state": "TX"},
         "geometry": {"coordinates": [-97.0, 30.0]}},                  # keep: case-insensitive
        {"properties": {"countrycode": "DE", "name": "C"},
         "geometry": {"coordinates": [13.4, 52.5]}},                   # drop: non-US
        {"properties": {"countrycode": "US", "name": "D"},
         "geometry": {"coordinates": []}},                             # drop: bad coords
    ]
    out = _photon_features_to_suggestions(feats, 5)
    assert out == [                                                    # note lon/lat swap
        {"label": "A, X, CA", "lat": 34.0, "lon": -118.0},
        {"label": "B, Y, TX", "lat": 30.0, "lon": -97.0},
    ]
    # limit is respected
    many = [{"properties": {"countrycode": "US", "name": str(i)},
             "geometry": {"coordinates": [float(i), 1.0]}} for i in range(10)]
    assert len(_photon_features_to_suggestions(many, 3)) == 3


def test_geoapify_formatter():
    """Pure Geoapify parsing helpers — no network/key. Skip if FastAPI absent."""
    try:
        import fastapi  # noqa: F401 — housing_label.api needs it at import time
    except ImportError:
        print("  skip test_geoapify_formatter (fastapi not installed)")
        return
    # Imported outside the guard so a real import error in housing_label.api fails the test.
    from housing_label.api import _geoapify_label, _geoapify_results_to_suggestions
    assert _geoapify_label({
        "address_line1": "1234 Scott St", "city": "San Francisco",
        "state_code": "CA", "postcode": "94115",
    }) == "1234 Scott St, San Francisco, CA 94115"
    # Falls back to `formatted`, stripping the country suffix.
    assert _geoapify_label({
        "formatted": "350 5th Ave, New York, NY 10118, United States of America",
    }) == "350 5th Ave, New York, NY 10118"

    results = [
        {"country_code": "us", "address_line1": "1234 Scott St", "city": "San Francisco",
         "state_code": "CA", "postcode": "94115", "lat": 37.7811, "lon": -122.4373},
        {"country_code": "de", "address_line1": "X", "lat": 52.5, "lon": 13.4},   # drop non-US
        {"country_code": "us", "address_line1": "Y", "lat": None, "lon": 1.0},    # drop bad coords
    ]
    assert _geoapify_results_to_suggestions(results, 5) == [
        {"label": "1234 Scott St, San Francisco, CA 94115", "lat": 37.7811, "lon": -122.4373},
    ]


def test_suggest_short_query():
    """Short/empty q short-circuits to [] before any network call."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_suggest_short_query (fastapi not installed)")
        return
    from housing_label.api import app
    client = TestClient(app)
    assert client.get("/suggest").status_code == 200
    assert client.get("/suggest").json() == []
    assert client.get("/suggest", params={"q": "ab"}).json() == []


def test_density_endpoint_validation():
    """The /density endpoint validates inputs before any network call. (The
    scored scenario shape is covered offline in tests/test_density.py; like the
    /label endpoint, /density is always-online in production, so the API test
    stays on the no-network validation paths.)"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_density_endpoint_validation (fastapi not installed)")
        return
    from housing_label.api import app
    client = TestClient(app)
    # Missing both address and lat/lon → 400, no network.
    assert client.get("/density").status_code == 400
    # Bad unit list → 400, no network.
    assert client.get("/density", params={"lat": 35.15, "lon": -89.85,
                                          "units": "abc"}).status_code == 400
    assert client.get("/density", params={"lat": 35.15, "lon": -89.85,
                                          "units": "0,-1"}).status_code == 400
    # Invalid construction choice → 400 before scoring.
    assert client.get("/density", params={"lat": 35.15, "lon": -89.85,
                                          "construction": "adobe"}).status_code == 400
    # Unknown upgrade → 400 before scoring.
    assert client.get("/density", params={"lat": 35.15, "lon": -89.85,
                                          "upgrades": "teleporter"}).status_code == 400


def test_presets_coord_validation():
    """/presets defaults to the Label-page location when no coords are given,
    but must reject a single coordinate (both required) — before any scoring."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_presets_coord_validation (fastapi not installed)")
        return
    from housing_label.api import app
    client = TestClient(app)
    # Only one of lat/lon → 400, no network involved (validated before scoring).
    assert client.get("/presets", params={"lat": 40}).status_code == 400
    assert client.get("/presets", params={"lon": -75}).status_code == 400


def test_label_result_is_cached():
    """A repeated identical /label request is served from the cache — the
    expensive scoring fan-out runs once, not twice."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_label_result_is_cached (fastapi not installed)")
        return
    import housing_label.api as api

    if not api._result_cache.enabled:
        # Caching can be turned off (LABEL_CACHE_SIZE/TTL <= 0); this test asserts
        # cache behavior, so it's not meaningful in that configuration.
        print("  skip test_label_result_is_cached (result cache disabled)")
        return

    calls = {"n": 0}
    real = api.build_label_parts

    def counting(**kw):
        calls["n"] += 1
        kw["allow_network"] = False        # offline → deterministic, no network in the test
        return real(**kw)

    api._result_cache.clear()
    api.build_label_parts = counting
    try:
        client = TestClient(api.app)
        params = {"lat": 35.13, "lon": -89.99, "preset": "baseline"}
        r1 = client.get("/label", params=params)
        r2 = client.get("/label", params=params)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json() == r2.json()
        assert calls["n"] == 1, f"expected one scoring pass, got {calls['n']}"
        # A different location is a distinct key → a fresh scoring pass.
        client.get("/label", params={**params, "lat": 34.05, "lon": -118.24})
        assert calls["n"] == 2
    finally:
        api.build_label_parts = real
        api._result_cache.clear()


def test_degraded_detection_is_not_cached():
    """When NSI structure detection was unavailable (a transient outage), the label
    falls back to generic building defaults and must NOT be cached — otherwise a
    bookmarked/shared coordinate would serve a wrong single-family label for the
    whole TTL (the cache-poisoning bug this guards against)."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_degraded_detection_is_not_cached (fastapi not installed)")
        return
    import housing_label.api as api

    if not api._result_cache.enabled:
        print("  skip test_degraded_detection_is_not_cached (result cache disabled)")
        return

    calls = {"n": 0}
    real = api.build_label_parts

    def degraded(**kw):
        calls["n"] += 1
        kw["allow_network"] = False        # offline → deterministic, no real network
        cfg, r, lbl = real(**kw)
        loc = lbl.get("location")
        if loc is not None:                # simulate the NSI outage this pass
            loc.structure_unavailable = True
        return cfg, r, lbl

    api._result_cache.clear()
    api.build_label_parts = degraded
    try:
        client = TestClient(api.app)
        params = {"lat": 35.13, "lon": -89.99, "preset": "baseline"}
        assert client.get("/label", params=params).status_code == 200
        assert client.get("/label", params=params).status_code == 200
        # Not cached → the second identical request re-scores rather than replaying
        # the degraded result.
        assert calls["n"] == 2, (
            f"degraded (NSI-unavailable) label must not be cached; got {calls['n']} passes")
    finally:
        api.build_label_parts = real
        api._result_cache.clear()


def test_rate_limit_returns_429():
    """Past the configured per-IP limit, scoring endpoints return 429 while the
    exempt health probe keeps answering 200."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_rate_limit_returns_429 (fastapi not installed)")
        return
    import importlib
    import os
    import housing_label.api as api

    prev = os.environ.get("RATE_LIMIT")
    os.environ["RATE_LIMIT"] = "3/minute"
    try:
        importlib.reload(api)                 # rebuild app + limiter at the low limit
        client = TestClient(api.app)
        # /label with no args is a 400 before any network, but each request still
        # counts against the limit — so the 4th trips 429.
        codes = [client.get("/label").status_code for _ in range(5)]
        assert 429 in codes, codes
        assert codes.index(429) == 3, codes         # first three allowed, 4th blocked
        # /healthz is exempt: still 200 even after the limit is exhausted.
        assert client.get("/healthz").status_code == 200
    finally:
        if prev is None:
            os.environ.pop("RATE_LIMIT", None)
        else:
            os.environ["RATE_LIMIT"] = prev
        importlib.reload(api)                 # restore the default-limit module state


def test_baseline_cost_matches_subject_size():
    """The cost-strip baseline inherits the subject home's size/value so the 30-yr
    delta reflects construction quality, not square footage — a large or valuable
    home must not read as expensive purely for being large. Guards against the
    old behavior where the comparable was fixed at 2,000 sqft / $160k."""
    try:
        import fastapi  # noqa: F401 — api.py imports it at module load
    except ImportError:
        print("  skip test_baseline_cost_matches_subject_size (fastapi not installed)")
        return
    import housing_label.api as api

    captured = {}

    class _Loc:
        lat, lon = 35.93, -83.98

    def _fake_build(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return {}, {"total_loss": 100.0}, {"metrics": {"est_monthly_energy_cost": 200.0}}

    def _fake_flows(_r, _lbl):
        return {"expectedAnnualLoss": 100, "annualEnergyCost": 2400}

    orig_build, orig_flows = api.build_label_parts, api.cost_flows
    api.build_label_parts, api.cost_flows = _fake_build, _fake_flows
    try:
        payload = {"cost": {"expectedAnnualLoss": 300, "annualEnergyCost": 4800}}
        lbl = {"location": _Loc(), "dimensions": [
            {"key": "health", "score": 70},
            {"key": "socioeconomic", "score": 80},
            {"key": "walkability", "score": 40}]}
        cfg = {"sqft": 4371, "value": 450_000, "units": 1, "stories": None,
               "lot_acres": 0.3, "flood_zone": "AE"}
        api._attach_baseline_cost(payload, lbl, cfg, self_baseline=False)
    finally:
        api.build_label_parts, api.cost_flows = orig_build, orig_flows

    # Subject size/value forwarded so the baseline is size-matched; None fields dropped.
    assert captured["sqft"] == 4371
    assert captured["value"] == 450_000
    assert captured["units"] == 1
    assert captured["lot_acres"] == 0.3
    assert "stories" not in captured                 # None → omitted, uses default
    # Flood exposure matched too, overriding the preset's hard-coded "X" so the EAL
    # delta isn't skewed by a mismatched flood zone.
    assert captured["flood_zone"] == "AE"
    assert captured["preset"] == "baseline"          # keeps typical 2000-frame construction
    assert payload["baseline_cost"]["label"] == api._BASELINE_LABEL
    assert payload["baseline_cost"]["annualEnergyCost"] == 2400


def test_baseline_cost_self_baseline_reuses_cost():
    """When the scored home already is the baseline, reuse its own flows (delta 0)
    without a second scoring pass."""
    try:
        import fastapi  # noqa: F401 — api.py imports it at module load
    except ImportError:
        print("  skip test_baseline_cost_self_baseline_reuses_cost (fastapi not installed)")
        return
    import housing_label.api as api

    # location is None (e.g. geocode failed): self-baseline still attaches, since
    # the delta is 0 and needs no comparable scoring.
    payload = {"cost": {"expectedAnnualLoss": 150, "annualEnergyCost": 2100}}
    lbl = {"location": None, "dimensions": []}
    api._attach_baseline_cost(payload, lbl, {"sqft": 2000}, self_baseline=True)
    assert payload["baseline_cost"]["label"] == api._BASELINE_LABEL
    assert payload["baseline_cost"]["annualEnergyCost"] == 2100   # reused verbatim


def test_detached_cost_only_for_multiunit():
    """The density-dividend line (vs. the same home standing alone) is attached only
    for multi-unit buildings, and it isolates DENSITY: it reprices energy at the
    detached ResStock benchmark (``energy_detached_ratio``) and restores full
    ground-floor flood exposure, holding size/value/quality fixed."""
    try:
        import fastapi  # noqa: F401 — api.py imports it at module load
    except ImportError:
        print("  skip test_detached_cost_only_for_multiunit (fastapi not installed)")
        return
    import housing_label.api as api

    # Single-family: no detached line at all.
    p1 = {"cost": {"annualEnergyCost": 1800, "expectedAnnualLoss": 900}}
    api._attach_detached_cost(p1, {"flood_floor": 0.25, "flood_loss": 40.0}, {"units": 1})
    assert "detached_cost" not in p1

    # Multi-unit (MF 5+): detached benchmark is higher EUI → ratio > 1 → detached
    # energy costs more. metrics carries the model-computed ratio.
    house = {"annualEnergyCost": 1800, "expectedAnnualLoss": 900}
    r = {"flood_floor": 0.25, "flood_loss": 40.0, "total_loss": 900.0}
    ratio = 1.08   # detached / mf_5plus base-EUI
    p2 = {"cost": dict(house), "metrics": {"energy_detached_ratio": ratio}}
    api._attach_detached_cost(p2, r, {"units": 157})
    d = p2["detached_cost"]
    assert d["label"] == api._DETACHED_LABEL
    # Energy: repriced by the ratio → higher detached bill for a 5+ unit building.
    assert d["annualEnergyCost"] == round(1800 * ratio) and d["annualEnergyCost"] > 1800
    # Flood: full ground-floor exposure restored (40 / 0.25 = 160, i.e. +120).
    assert d["expectedAnnualLoss"] == round(900 + 40.0 * (1 / 0.25 - 1)) == 1020
    # The house's own flows are not mutated in place.
    assert p2["cost"] == house

    # Small MF (2-4 units): detached benchmark is LOWER EUI → ratio < 1 → detached
    # energy costs less. The line honestly shows density can raise per-sqft energy.
    p2c = {"cost": dict(house), "metrics": {"energy_detached_ratio": 0.89}}
    api._attach_detached_cost(p2c, r, {"units": 3})
    assert p2c["detached_cost"]["annualEnergyCost"] == round(1800 * 0.89) < 1800

    # NSI-detected count drives it even when cfg["units"] is still the default 1:
    # the effective structure.num_units is what the energy model scored, so the line
    # must appear for a detected tower the caller never typed a count for.
    p2b = {"cost": dict(house), "structure": {"num_units": 157},
           "metrics": {"energy_detached_ratio": ratio}}
    api._attach_detached_cost(p2b, r, {"units": 1})
    assert p2b["detached_cost"]["annualEnergyCost"] == round(1800 * ratio)

    # units=1 short-circuits before any work (no detached line).
    p3 = {"cost": dict(house)}
    api._attach_detached_cost(p3, {"flood_floor": 1.0, "flood_loss": 0.0}, {"units": 1})
    assert "detached_cost" not in p3

    # Multi-unit but no ratio in metrics → energy left unchanged (only flood moves).
    p3b = {"cost": dict(house)}
    api._attach_detached_cost(p3b, r, {"units": 157})
    assert p3b["detached_cost"]["annualEnergyCost"] == 1800

    # Best-effort: a malformed unit count must not raise (the label must still render).
    p4 = {"cost": dict(house)}
    api._attach_detached_cost(p4, r, {"units": "not-a-number"})
    assert "detached_cost" not in p4

    # A legitimate zero total loss survives (no falsy fallback to the house value).
    p5 = {"cost": {"annualEnergyCost": 1800, "expectedAnnualLoss": 0},
          "metrics": {"energy_detached_ratio": ratio}}
    api._attach_detached_cost(p5, {"flood_floor": 0.25, "flood_loss": 0.0, "total_loss": 0.0},
                              {"units": 157})
    assert p5["detached_cost"]["expectedAnnualLoss"] == 0


def test_is_self_baseline_only_construction_breaks_it():
    """A preset=baseline home is its own comparable unless a CONSTRUCTION attribute
    is overridden to something OTHER than the baseline default. Size/value/exposure
    are inherited by the comparable, so they aren't even inputs here."""
    try:
        import fastapi  # noqa: F401 — api.py imports it at module load
    except ImportError:
        print("  skip test_is_self_baseline_only_construction_breaks_it (fastapi not installed)")
        return
    from housing_label.api import _is_self_baseline, PRESETS

    none = dict(year_built=None, construction=None, foundation=None, condition=None,
                bldg_material=None, upgrade_list=[])
    # Plain baseline (no overrides) is self-baseline; a non-baseline preset never is.
    assert _is_self_baseline("baseline", **none) is True
    assert _is_self_baseline(None, **none) is False
    assert _is_self_baseline("worst-case", **none) is False
    # Explicitly passing the baseline's OWN defaults is a no-op — still self-baseline
    # (no redundant second pass).
    b = PRESETS["baseline"]
    assert _is_self_baseline("baseline", **{**none,
        "year_built": b["year_built"], "construction": b["construction"],
        "foundation": b["foundation"], "condition": b["condition"]}) is True
    # Each override to a NON-default value breaks the short-circuit — including
    # falsy-but-real values like year_built=0 (guards a truthiness misclassification).
    for field, val in (("year_built", 1990), ("year_built", 0), ("construction", "brick"),
                       ("foundation", "full-basement"), ("condition", "poor"),
                       ("bldg_material", "concrete"), ("upgrade_list", ["solar"])):
        assert _is_self_baseline("baseline", **{**none, field: val}) is False, field


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
