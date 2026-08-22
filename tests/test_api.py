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
    # Named POI with a street address leads with the name, then the address, so a
    # search by company/place name shows where it resolves to.
    assert _photon_label({
        "name": "Acme Corp", "housenumber": "500", "street": "Oak Ave",
        "city": "Memphis", "state": "TN",
    }) == "Acme Corp, 500 Oak Ave, Memphis, TN"
    # A named feature whose name just repeats the street isn't duplicated —
    # including when the upstream fields differ only by trailing whitespace.
    assert _photon_label({"name": "Main St", "street": "Main St", "city": "Reno"}) \
        == "Main St, Reno"
    assert _photon_label({"name": "Main St", "street": "Main St ", "city": " Reno "}) \
        == "Main St, Reno"

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
        {"label": "A, X, CA", "lat": 34.0, "lon": -118.0, "residential": None},
        {"label": "B, Y, TX", "lat": 30.0, "lon": -97.0, "residential": None},
    ]
    # limit is respected
    many = [{"properties": {"countrycode": "US", "name": str(i)},
             "geometry": {"coordinates": [float(i), 1.0]}} for i in range(10)]
    assert len(_photon_features_to_suggestions(many, 3)) == 3


def test_residential_hint():
    """OSM-tag → residential verdict, so the scorer can refuse a non-residential
    POI the NSI-at-coordinate screen can't see. Skip if FastAPI absent."""
    try:
        import fastapi  # noqa: F401 — housing_label.api needs it at import time
    except ImportError:
        print("  skip test_residential_hint (fastapi not installed)")
        return
    from housing_label.api import _residential_hint, _photon_features_to_suggestions
    # Positively non-residential (the exact tags Photon returns for "Bank of America").
    assert _residential_hint("leisure", "stadium") is False
    assert _residential_hint("office", "company") is False
    assert _residential_hint("amenity", "bank") is False
    assert _residential_hint("building", "commercial") is False
    assert _residential_hint("building", "office") is False
    # Dwellings.
    assert _residential_hint("building", "residential") is True
    assert _residential_hint("building", "apartments") is True
    assert _residential_hint("building", "house") is True
    # Unknown → deferred to the NSI screen (a plain street / untagged / place name).
    assert _residential_hint("highway", "residential") is None
    assert _residential_hint("building", "yes") is None
    assert _residential_hint("place", "city") is None
    assert _residential_hint(None, None) is None
    # The verdict rides along on each suggestion.
    feats = [{"properties": {"countrycode": "US", "name": "BofA Stadium", "city": "Charlotte",
                             "state": "NC", "osm_key": "leisure", "osm_value": "stadium"},
              "geometry": {"coordinates": [-80.85, 35.22]}}]
    assert _photon_features_to_suggestions(feats, 5)[0]["residential"] is False


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
        {"label": "1234 Scott St, San Francisco, CA 94115", "lat": 37.7811,
         "lon": -122.4373, "residential": None},
    ]
    # Geoapify category → residential verdict.
    from housing_label.api import _geoapify_residential
    assert _geoapify_residential({"category": "building.residential"}) is True
    assert _geoapify_residential({"category": "commercial.supermarket"}) is False
    assert _geoapify_residential({"category": "leisure.stadium"}) is False
    assert _geoapify_residential({"category": ""}) is None


def test_google_autocomplete_and_details():
    """Google Places Autocomplete (predictions → suggestions) and Place Details
    (→ scored result) parsing/classification — no network/key. Skip if FastAPI
    absent."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  skip test_google_autocomplete_and_details (fastapi not installed)")
        return
    from housing_label.api import (
        _google_residential,
        _google_predictions_to_suggestions, _google_detail_to_result,
    )
    # ── Autocomplete: predictions carry a place_id + residential verdict, no coords.
    suggestions = [
        {"placePrediction": {
            "placeId": "ChIJstadium",
            "text": {"text": "Bank of America Stadium, South Mint Street, Charlotte, NC, USA"},
            "types": ["stadium", "establishment"]}},
        {"placePrediction": {
            "placeId": "ChIJunum",
            "structuredFormat": {"mainText": {"text": "Unum"},
                                 "secondaryText": {"text": "Fountain Square, Chattanooga, TN, USA"}},
            "types": ["insurance_agency", "establishment"]}},
        {"placePrediction": {
            "placeId": "ChIJhome",
            "text": {"text": "123 Main St, Memphis, TN, USA"},
            "types": ["street_address"]}},
        {"queryPrediction": {"text": {"text": "pizza near me"}}},   # no placeId → skipped
    ]
    assert _google_predictions_to_suggestions(suggestions, 5) == [
        {"label": "Bank of America Stadium, South Mint Street, Charlotte, NC",
         "place_id": "ChIJstadium", "residential": False},
        {"label": "Unum, Fountain Square, Chattanooga, TN",
         "place_id": "ChIJunum", "residential": False},
        {"label": "123 Main St, Memphis, TN", "place_id": "ChIJhome", "residential": None},
    ]

    # ── Residential classifier (shared by autocomplete + details `types`).
    assert _google_residential(["stadium", "establishment"]) is False
    assert _google_residential(["insurance_agency", "establishment"]) is False    # Unum HQ
    assert _google_residential(["establishment", "point_of_interest"]) is False   # generic business
    assert _google_residential(["street_address"]) is None                        # a home → NSI decides
    assert _google_residential(["premise", "establishment"]) is None              # address-like wins

    # ── Place Details → {label, lat, lon, residential}. Label leads with the name,
    # then the address (country suffix stripped, no duplication for a plain address).
    assert _google_detail_to_result({
        "formattedAddress": "800 S Mint St, Charlotte, NC 28202, USA",
        "location": {"latitude": 35.2258, "longitude": -80.8528},
        "displayName": {"text": "Bank of America Stadium"},
        "types": ["stadium", "establishment"],
    }) == {"label": "Bank of America Stadium, 800 S Mint St, Charlotte, NC 28202",
           "lat": 35.2258, "lon": -80.8528, "residential": False}
    assert _google_detail_to_result({
        "formattedAddress": "123 Main St, Memphis, TN 38104, USA",
        "location": {"latitude": 35.13, "longitude": -89.99},
        "displayName": {"text": "123 Main St"}, "types": ["street_address"],
    }) == {"label": "123 Main St, Memphis, TN 38104",
           "lat": 35.13, "lon": -89.99, "residential": None}
    # No coordinates → unresolvable.
    assert _google_detail_to_result({"formattedAddress": "X", "displayName": {"text": "X"}}) is None


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
    # ?debug=1 reports which providers are configured (no key set in the test env,
    # so no live Google probe runs — stays network-free).
    dbg = client.get("/suggest", params={"q": "Unum", "debug": "true"}).json()
    assert dbg["configured"] == {"google": False, "geoapify": False, "photon": True}
    assert "google_probe" not in dbg


def test_place_endpoint_validation():
    """The /place endpoint validates before any network call: 400 without a
    place_id, and 503 when no Google key is configured (the test env has none)."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_place_endpoint_validation (fastapi not installed)")
        return
    import housing_label.api as api
    client = TestClient(api.app)
    assert client.get("/place").status_code == 400                       # missing place_id
    assert client.get("/place", params={"place_id": ""}).status_code == 400
    # With a place_id but no key configured → 503 (no network attempted).
    assert not api.GOOGLE_PLACES_API_KEY                                  # guard: test env has no key
    assert client.get("/place", params={"place_id": "ChIJabc"}).status_code == 503


def test_label_nonresidential_flag_screens():
    """?nonresidential=1 (the geocoder said this is a stadium/office/store) refuses
    with 422 before any network call, and allow_non_residential overrides it."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_label_nonresidential_flag_screens (fastapi not installed)")
        return
    from housing_label.api import app
    client = TestClient(app)
    # Bank of America Stadium coords — refused up front (no scoring, no network).
    r = client.get("/label", params={"lat": 35.2258, "lon": -80.8528, "nonresidential": "true"})
    assert r.status_code == 422
    assert "residential" in r.json().get("detail", "").lower()
    # Without the flag, the same coords are NOT screened up front (they'd proceed to
    # scoring — not asserted here to keep this test network-free).


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


def test_timeline_endpoint_validation():
    """The /timeline endpoint validates inputs before any network call.

    The scored payload shape is covered offline in tests/test_trajectory.py; like
    /label and /density, /timeline is always-online in production, so the API
    test stays on the no-network validation paths.
    """
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_timeline_endpoint_validation (fastapi not installed)")
        return
    from housing_label.api import app, _TIMELINE_MAX_POINTS
    client = TestClient(app)
    loc = {"lat": 35.15, "lon": -89.85}
    # Missing both address and lat/lon → 400, no network.
    assert client.get("/timeline").status_code == 400
    # Bad year list → 400, no network.
    assert client.get("/timeline", params={**loc, "years": "abc"}).status_code == 400
    assert client.get("/timeline", params={**loc, "years": ","}).status_code == 400
    # More points than the cap → 400 rather than a silent truncation, so a
    # caller asking for ten years is told it got three rather than assuming it
    # got ten.
    too_many = ",".join(str(2000 + i) for i in range(_TIMELINE_MAX_POINTS + 1))
    assert client.get("/timeline", params={**loc, "years": too_many}).status_code == 400
    # Shares /label's field validation (one _validate_request, one rule set).
    assert client.get("/timeline", params={**loc,
                                           "construction": "adobe"}).status_code == 400
    assert client.get("/timeline", params={**loc,
                                           "upgrades": "teleporter"}).status_code == 400


def test_warmup_is_gated_by_env_and_starts_at_boot():
    """The dataset decode happens at boot, unless WARMUP says otherwise.

    Without this the first request after every deploy pays it inside the
    visitor's own request. It has to stay switchable from the dashboard, so the
    env gate is part of the contract, not a convenience.
    """
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_warmup_is_gated_by_env_and_starts_at_boot (fastapi not installed)")
        return
    import os as _os, time as _time
    from housing_label import api

    calls = []
    real, prior = api._warmup, _os.environ.get("WARMUP")
    api._warmup = lambda: calls.append(1)
    try:
        _os.environ["WARMUP"] = "0"
        with TestClient(api.app):          # entering the context runs the lifespan
            pass
        _time.sleep(0.05)                  # a thread started in error would land by now
        assert calls == [], "WARMUP=0 must not warm"

        _os.environ.pop("WARMUP")          # default is on
        with TestClient(api.app):
            pass
        for _ in range(200):               # it runs off-thread, so wait for it
            if calls:
                break
            _time.sleep(0.01)
        assert calls == [1], "default must warm exactly once"
    finally:
        api._warmup = real
        if prior is None:
            _os.environ.pop("WARMUP", None)
        else:
            _os.environ["WARMUP"] = prior


def test_warmup_actually_decodes_the_tract_tables():
    """The warm-up's entire job, asserted directly.

    Offline, `resolve_location` skips the Census geocode, so a Location built
    from bare lat/lon carries no county and no tract — and every tract-keyed
    loader short-circuits before touching its file. A warm-up in that shape logs
    "complete" having decoded none of the eight biggest tables, and the first
    real request still pays for all of them. Only supplying a Census geography
    makes the warm-up real, so assert the tables are genuinely resident
    afterwards rather than trusting that a pass through the scorer touched them.
    """
    from housing_label import api
    from housing_label.data import health, socioeconomic, walkability, noise

    loaders = [health._tract_table, socioeconomic._tract_table,
               walkability._tract_table, noise._tract_table]
    for f in loaders:
        f.cache_clear()
    assert all(f.cache_info().currsize == 0 for f in loaders)
    api._warmup()
    for f in loaders:
        assert f.cache_info().currsize == 1, (
            f"{f.__module__}.{f.__name__} not decoded — the warm-up isn't warming")


def test_warmup_failure_never_reaches_the_app():
    """A warm-up that blows up must not take the API down with it — it is an
    optimization, and the datasets still load lazily on first use."""
    import logging as _logging
    from housing_label import api

    def boom(**_kwargs):
        raise RuntimeError("simulated dataset failure")

    real = api.build_label_parts
    logger = _logging.getLogger("housing_label.api")
    prior_level = logger.level
    api.build_label_parts = boom
    logger.setLevel(_logging.CRITICAL)     # the failure is logged; don't spam the run
    try:
        api._warmup()                      # must return, not raise
    finally:
        api.build_label_parts = real
        logger.setLevel(prior_level)


def test_preset_profiles_is_the_roster_without_scoring():
    """/preset-profiles names the construction profiles and scores nothing.

    The website's profile picker only needs the names; asking /presets for them
    costs five full scoring passes. This must stay a constant-time echo of
    _WEBSITE_PRESETS, in the same order, so an index into one is an index into
    the other — and cacheable for a day.
    """
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_preset_profiles_is_the_roster_without_scoring (fastapi not installed)")
        return
    from housing_label.api import app, _WEBSITE_PRESETS
    client = TestClient(app)
    r = client.get("/preset-profiles")
    assert r.status_code == 200
    assert r.json()["profiles"] == [
        {"name": n, "preset": p, "description": d} for n, p, d in _WEBSITE_PRESETS]
    # Long-lived cache header: the roster is a constant, not a scored result.
    assert "max-age=86400" in (r.headers.get("cache-control") or "")


def test_scoring_responses_are_cacheable():
    """Deterministic scored endpoints carry Cache-Control so a repeat view is free.

    Checked on a 400 path too: only 200s may be cached — an error or a rate-limit
    refusal must stay re-askable. (A scored 200 needs network, so it isn't
    exercised here; the middleware keys off the path, not the payload.)"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_scoring_responses_are_cacheable (fastapi not installed)")
        return
    from housing_label.api import app, _SCORE_CACHE_CONTROL, _CACHE_CONTROL_BY_PATH
    client = TestClient(app)
    assert client.get("/healthz").headers.get("cache-control") is None
    r = client.get("/density")          # 400: missing address/coords
    assert r.status_code == 400
    assert r.headers.get("cache-control") is None
    # A scored URL carries the address someone typed — usually their own home —
    # so it is cacheable by that reader's browser and by nothing in between.
    assert _SCORE_CACHE_CONTROL.startswith("private")
    assert "s-maxage" not in _SCORE_CACHE_CONTROL
    for path in ("/label", "/presets", "/density"):
        assert _CACHE_CONTROL_BY_PATH[path] == _SCORE_CACHE_CONTROL
    # The roster is a constant with nothing personal in the URL.
    assert _CACHE_CONTROL_BY_PATH["/preset-profiles"].startswith("public")


def test_cache_keys_ignore_address_case_and_spacing():
    """'123 Main St' and '123  main st ' are one house, so they're one cache entry."""
    from housing_label.api import _key_addr, _key_coord
    assert _key_addr("123 Main St") == _key_addr("123  main st ") == "123 main st"
    assert _key_addr(None) is None and _key_addr("   ") is None
    assert _key_coord(35.130000004) == _key_coord(35.13) == 35.13
    assert _key_coord(None) is None


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


def test_owner_occupied_is_part_of_the_cache_key():
    """A tenure-differing request must not be served another request's cached answer.

    The /label cache key is a hand-maintained tuple, so every scoring-relevant param has
    to be added to it by hand. Omitting one is silent: the second request simply gets the
    first's result. Tenure changes the property-tax leg in split-roll states, so it
    belongs in the key — and nothing else in the suite would notice if it were dropped.
    """
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_owner_occupied_is_part_of_the_cache_key (fastapi not installed)")
        return
    import housing_label.api as api

    if not api._result_cache.enabled:
        print("  skip test_owner_occupied_is_part_of_the_cache_key (result cache disabled)")
        return

    seen = []
    real = api.build_label_parts

    def recording(**kw):
        seen.append(kw.get("owner_occupied"))
        kw["allow_network"] = False
        return real(**kw)

    api._result_cache.clear()
    api.build_label_parts = recording
    try:
        client = TestClient(api.app)
        base = {"lat": 35.13, "lon": -89.99, "units": 4}
        client.get("/label", params={**base, "owner_occupied": "true"})
        client.get("/label", params={**base, "owner_occupied": "false"})
        # Each request also builds a baseline-construction comparable, which inherits
        # only _BASELINE_SIZE_FIELDS — tenure is not a construction attribute, so that
        # inner call correctly carries None. The subject runs are the non-None ones.
        subject_runs = [t for t in seen if t is not None]
        assert subject_runs == [True, False], f"cache collided across tenure: {seen}"
        # An identical repeat IS served from cache — no further scoring at all.
        before = len(seen)
        client.get("/label", params={**base, "owner_occupied": "false"})
        assert len(seen) == before, f"identical repeat was rescored: {seen}"
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


# ── API keys, plans and metering ─────────────────────────────────────────────────
# Every test below scores offline: `_offline` forces allow_network=False into the
# real scoring path, so these exercise the genuine endpoints (and prove the score
# doesn't move with the plan) without touching an upstream.

import contextlib as _contextlib


@_contextlib.contextmanager
def _keys(spec=None, anon_daily=None, plans=None):
    """Configure HOUSING_LABEL_KEYS / ANON_DAILY_SCORES for one test.

    `plans` overrides entries in entitlements.PLANS before the registry is
    parsed — the shipped allowances are in the thousands, and a test that had to
    spend 5,000 scores to reach a 429 would be a bad test.
    """
    import os as _os
    from housing_label import entitlements as ent

    env = {"HOUSING_LABEL_KEYS": spec, "ANON_DAILY_SCORES": anon_daily}
    prior_env = {k: _os.environ.get(k) for k in env}
    prior_plans = dict(ent.PLANS)
    try:
        for k, v in env.items():
            _os.environ.pop(k, None) if v is None else _os.environ.__setitem__(k, v)
        if plans:
            ent.PLANS.update(plans)
        ent.reload()
        ent.ledger.clear()
        yield ent
    finally:
        for k, v in prior_env.items():
            _os.environ.pop(k, None) if v is None else _os.environ.__setitem__(k, v)
        ent.PLANS.clear()
        ent.PLANS.update(prior_plans)
        ent.reload()
        ent.ledger.clear()


@_contextlib.contextmanager
def _offline():
    """Force the scoring path offline for the duration, and start from a cold cache."""
    import housing_label.api as api

    real_label, real_density, real_timeline = (
        api.build_label_parts, api.density_comparison, api.timeline_comparison)

    def off(fn):
        def wrapped(**kw):
            kw["allow_network"] = False
            return fn(**kw)
        return wrapped

    api.build_label_parts = off(real_label)
    api.density_comparison = off(real_density)
    api.timeline_comparison = off(real_timeline)
    api._result_cache.clear()
    try:
        yield api
    finally:
        (api.build_label_parts, api.density_comparison,
         api.timeline_comparison) = real_label, real_density, real_timeline
        api._result_cache.clear()


_OFFLINE_PARAMS = {"lat": 35.13, "lon": -89.99, "preset": "baseline"}


def test_no_keys_configured_leaves_the_api_exactly_as_it_was():
    """The self-hosting contract. README's licence section invites you to run
    this yourself; an instance with no keys must not be a metered version of the
    one that existed before plans did — no quota ceiling, no quota headers, and
    /usage answering honestly rather than demanding credentials."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_no_keys_configured_leaves_the_api_exactly_as_it_was (fastapi not installed)")
        return
    with _keys(), _offline() as api:
        client = TestClient(api.app)
        r = client.get("/label", params=_OFFLINE_PARAMS)
        assert r.status_code == 200
        assert r.headers.get("X-Plan") == "anonymous"
        for h in ("X-Quota-Limit", "X-Quota-Remaining", "X-Quota-Used"):
            assert h not in r.headers, f"{h} must not appear for an unmetered caller"
        u = client.get("/usage")
        assert u.headers.get("Cache-Control") == "no-store", "a live counter must not cache"
        u = u.json()
        assert u["plan"] == "anonymous" and u["anonymous"] is True
        assert u["daily_scores"] is None and u["remaining_today"] is None
        # No amount of asking exhausts anything.
        for _ in range(5):
            assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200


def test_unknown_key_is_refused_and_anonymity_still_is_not():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_unknown_key_is_refused_and_anonymity_still_is_not (fastapi not installed)")
        return
    with _keys("pro:k_good"), _offline() as api:
        client = TestClient(api.app)
        for send in ({"headers": {"X-API-Key": "k_bad"}},
                     {"params": {**_OFFLINE_PARAMS, "key": "k_bad"}}):
            params = send.pop("params", _OFFLINE_PARAMS)
            r = client.get("/label", params=params, **send)
            assert r.status_code == 401, r.status_code
            assert "unknown API key" in r.json()["detail"]
        # Sending nothing is still fine — the free tier is not behind a key.
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200


def test_a_url_carrying_a_key_is_never_cached():
    """`?key=` puts a credential in the URL. It still has to work — an <img> or
    iframe badge embed cannot set a header — but the reply must not be written
    into a disk cache under a key-bearing URL to be found later. The access-log
    and history leak is not fixable here; the disk cache is."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_a_url_carrying_a_key_is_never_cached (fastapi not installed)")
        return
    with _keys("pro:k_url"), _offline() as api:
        client = TestClient(api.app)
        header = client.get("/label", params=_OFFLINE_PARAMS, headers={"X-API-Key": "k_url"})
        query = client.get("/label", params={**_OFFLINE_PARAMS, "key": "k_url"})
        assert header.status_code == query.status_code == 200
        assert header.headers["Cache-Control"] == "private, max-age=600"
        assert query.headers["Cache-Control"] == "no-store"
        # Same caller either way — the URL is a worse channel, not a different key.
        assert query.headers["X-Plan"] == header.headers["X-Plan"] == "pro"
        assert query.json() == header.json()


def test_the_score_does_not_depend_on_the_plan():
    """A paid caller and a free one must get the same numbers for the same
    address. The plan governs how much you may ask for, never what you are told."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_the_score_does_not_depend_on_the_plan (fastapi not installed)")
        return
    with _keys("pro:k_good"), _offline() as api:
        client = TestClient(api.app)
        anon = client.get("/label", params=_OFFLINE_PARAMS)
        keyed = client.get("/label", params=_OFFLINE_PARAMS,
                           headers={"X-API-Key": "k_good"})
        assert anon.status_code == keyed.status_code == 200
        assert anon.json() == keyed.json()


def test_a_metered_caller_is_charged_and_then_refused():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_a_metered_caller_is_charged_and_then_refused (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("basic:k_small", plans={"basic": Plan("basic", 3)}), _offline() as api:
        client = TestClient(api.app)
        hdr = {"X-API-Key": "k_small"}
        seen = []
        for _ in range(3):
            r = client.get("/label", params=_OFFLINE_PARAMS, headers=hdr)
            assert r.status_code == 200
            seen.append(r.headers["X-Quota-Remaining"])
        assert seen == ["2", "1", "0"], seen
        # A cache hit still charges: whether the answer was already in this
        # process's memory is an accident of who asked first.
        r = client.get("/label", params=_OFFLINE_PARAMS, headers=hdr)
        assert r.status_code == 429
        assert "resets at 00:00 UTC" in r.json()["detail"]
        assert r.headers["X-Quota-Remaining"] == "0"
        assert r.headers["X-Plan"] == "basic"
        # The refusal is the caller's, not the service's: anonymous still works.
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200


def test_metering_counts_scoring_passes_not_requests():
    """/presets is five labels and a default /timeline is three points. Charging
    per request would price a dropdown the same as a portfolio row."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_metering_counts_scoring_passes_not_requests (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    from housing_label.simulate.house import DENSITY_UNIT_COUNTS, default_timeline_years
    with _keys("pro:k_meter", plans={"pro": Plan("pro", 10_000)}), _offline() as api:
        client = TestClient(api.app)
        hdr = {"X-API-Key": "k_meter"}
        expected = [
            ("/label", {}, 1),
            ("/presets", {}, len(api._WEBSITE_PRESETS)),
            ("/density", {}, len(DENSITY_UNIT_COUNTS)),
            ("/density", {"units": "1,4"}, 2),
            ("/timeline", {}, len(default_timeline_years())),
            ("/timeline", {"years": "2000,2010,2020,2026"}, 4),
        ]
        for path, extra, cost in expected:
            before = client.get("/usage", headers=hdr).json()["used_today"]
            r = client.get(path, params={**_OFFLINE_PARAMS, **extra}, headers=hdr)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
            after = client.get("/usage", headers=hdr).json()["used_today"]
            assert after - before == cost, f"{path} {extra} charged {after - before}, want {cost}"


def test_a_rejected_request_is_never_charged():
    """Validation runs before metering, so a 400 costs nothing — otherwise a
    caller could burn their day on requests that were never going to score."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_a_rejected_request_is_never_charged (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("basic:k_v", plans={"basic": Plan("basic", 50)}), _offline() as api:
        client = TestClient(api.app)
        hdr = {"X-API-Key": "k_v"}
        for path, params in (("/label", {}),                       # no location
                             ("/label", {**_OFFLINE_PARAMS, "condition": "sublime"}),
                             ("/density", {**_OFFLINE_PARAMS, "units": "1,2,3,4,5,6,7"}),
                             ("/timeline", {**_OFFLINE_PARAMS, "years": "nope"})):
            assert client.get(path, params=params, headers=hdr).status_code == 400
        assert client.get("/usage", headers=hdr).json()["used_today"] == 0


def test_usage_reports_the_calling_key_and_no_other():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_usage_reports_the_calling_key_and_no_other (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("basic:k_a, pro:k_b",
               plans={"basic": Plan("basic", 20), "pro": Plan("pro", 99)}), _offline() as api:
        client = TestClient(api.app)
        client.get("/label", params=_OFFLINE_PARAMS, headers={"X-API-Key": "k_a"})
        a = client.get("/usage", headers={"X-API-Key": "k_a"}).json()
        b = client.get("/usage", headers={"X-API-Key": "k_b"}).json()
        assert a["plan"] == "basic" and a["used_today"] == 1 and a["remaining_today"] == 19
        assert b["plan"] == "pro" and b["used_today"] == 0, "k_b must not see k_a's spend"
        # `?key=` authenticates the caller, it does not name whose row to report:
        # identity comes from the same dependency the scoring endpoints use, and
        # the header wins when both are sent. There is no way to ask about
        # somebody else.
        both = client.get("/usage", params={"key": "k_a"}, headers={"X-API-Key": "k_b"})
        assert both.json()["plan"] == "pro" and both.json()["used_today"] == 0
        assert client.get("/usage", params={"key": "k_a"}).json()["used_today"] == 1
        assert "k_a" not in str(a) and "k_b" not in str(b), "no reply may echo a key"


def test_anonymous_callers_can_be_metered_when_the_operator_asks():
    """The knob that turns this into a service. Off by default; when set, a key
    is what lifts a named caller back above it."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_anonymous_callers_can_be_metered_when_the_operator_asks (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("pro:k_lift", anon_daily="2", plans={"pro": Plan("pro", 100)}), _offline() as api:
        client = TestClient(api.app)
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 429
        # The key lifts the same caller straight back over it.
        r = client.get("/label", params=_OFFLINE_PARAMS, headers={"X-API-Key": "k_lift"})
        assert r.status_code == 200 and r.headers["X-Plan"] == "pro"


def test_healthz_and_the_roster_need_no_key_and_cost_nothing():
    """A probe must never be refused for want of credentials, and a constant
    that scores nothing must never be charged as if it did."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_healthz_and_the_roster_need_no_key_and_cost_nothing (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("basic:k_h", plans={"basic": Plan("basic", 1)}), _offline() as api:
        client = TestClient(api.app)
        hdr = {"X-API-Key": "k_h"}
        for _ in range(4):
            assert client.get("/healthz", headers=hdr).json() == {"ok": True}
            assert client.get("/preset-profiles", headers=hdr).status_code == 200
        assert client.get("/usage", headers=hdr).json()["used_today"] == 0
        # A bad key doesn't lock anyone out of the probe either.
        assert client.get("/healthz", headers={"X-API-Key": "k_bad"}).json() == {"ok": True}


def test_the_badge_is_served_as_an_embeddable_image():
    """It has to work in a plain <img> on someone else's page: right media type,
    publicly cacheable, and typed firmly enough that a proxy can't re-decide."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_the_badge_is_served_as_an_embeddable_image (fastapi not installed)")
        return
    import xml.etree.ElementTree as ET
    with _keys(), _offline() as api:
        client = TestClient(api.app)
        r = client.get("/badge", params=_OFFLINE_PARAMS)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.headers["Cache-Control"] == "public, max-age=3600"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        ET.fromstring(r.text)
        # A badge and the label page must never disagree about a house.
        lbl = client.get("/label", params=_OFFLINE_PARAMS).json()
        assert lbl["construction_national_grade"] in r.text
        assert lbl["location_national_grade"] in r.text
        # Bad enum values are refused rather than silently defaulted.
        for bad in ({"style": "enormous"}, {"theme": "drak"}, {"preset": "nope"}):
            assert client.get("/badge", params={**_OFFLINE_PARAMS, **bad}).status_code == 400
        assert client.get("/badge").status_code == 400, "a badge needs a location"


def test_a_badge_costs_one_pass_and_a_key_bearing_badge_url_is_not_cached():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_a_badge_costs_one_pass_and_a_key_bearing_badge_url_is_not_cached (fastapi not installed)")
        return
    from housing_label.entitlements import Plan
    with _keys("pro:k_badge", plans={"pro": Plan("pro", 100)}), _offline() as api:
        client = TestClient(api.app)
        hdr = {"X-API-Key": "k_badge"}
        before = client.get("/usage", headers=hdr).json()["used_today"]
        client.get("/badge", params=_OFFLINE_PARAMS, headers=hdr)
        assert client.get("/usage", headers=hdr).json()["used_today"] - before == 1
        # `?key=` still wins over `public, max-age=3600` — a credential in a URL
        # must not be written into a shared cache, badge or not.
        keyed = client.get("/badge", params={**_OFFLINE_PARAMS, "key": "k_badge"})
        assert keyed.status_code == 200
        assert keyed.headers["Cache-Control"] == "no-store"


def test_anonymous_callers_are_metered_per_site_then_per_address():
    """A badge's caller is the site embedding it, not each reader who loads the
    page — "free below N a day" is a sentence about the embedder. And anonymous
    callers get a row each rather than sharing one global pool, which is what
    ANON_DAILY_SCORES has to mean to be worth setting."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_anonymous_callers_are_metered_per_site_then_per_address (fastapi not installed)")
        return
    with _keys(anon_daily="2"), _offline() as api:
        client = TestClient(api.app)
        one = {"Referer": "https://one.example/homes/123"}
        two = {"Referer": "https://two.example/listing"}
        assert client.get("/badge", params=_OFFLINE_PARAMS, headers=one).status_code == 200
        assert client.get("/badge", params=_OFFLINE_PARAMS, headers=one).status_code == 200
        assert client.get("/badge", params=_OFFLINE_PARAMS, headers=one).status_code == 429
        # A different embedder is a different row, not a share of the first's day.
        assert client.get("/badge", params=_OFFLINE_PARAMS, headers=two).status_code == 200
        # Every path on one host shares that host's allowance — the site is the
        # unit, not the page.
        deep = {"Referer": "https://one.example/somewhere/else"}
        assert client.get("/badge", params=_OFFLINE_PARAMS, headers=deep).status_code == 429
        # With no Referer at all the address is the row, and it is still its own.
        assert client.get("/label", params=_OFFLINE_PARAMS).status_code == 200
        assert client.get("/usage").json()["used_today"] == 1


def test_one_site_is_one_ledger_row_whatever_its_referer_looks_like():
    """The scheme, port and any userinfo are not part of who is embedding. Left
    in, they split an honest embedder's allowance for reasons they cannot see,
    and hand a dishonest one a fresh allowance per port."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  skip test_one_site_is_one_ledger_row_whatever_its_referer_looks_like (fastapi not installed)")
        return
    from starlette.requests import Request
    from housing_label import api

    def ident(referrer=None):
        headers = [(b"referer", referrer.encode())] if referrer else []
        return api._anon_ident(Request({
            "type": "http", "method": "GET", "path": "/badge", "query_string": b"",
            "headers": headers, "client": ("203.0.113.9", 1234),
            "scheme": "http", "server": ("test", 80)}))

    same = {ident(r) for r in (
        "https://example.com/homes/1", "https://example.com:443/homes/1",
        "http://example.com:80/other", "https://user:pw@example.com/x",
        "https://EXAMPLE.COM/shouty",
    )}
    assert same == {"site:example.com"}, same
    # Distinctions that are real stay real.
    assert ident("https://blog.example.com/x") == "site:blog.example.com"
    assert ident("https://other.example/x") == "site:other.example"
    # No usable Referer falls back to the address, and junk never raises.
    assert ident() == "ip:203.0.113.9"
    for junk in ("", "not a url", "://", "https://", "javascript:alert(1)"):
        assert ident(junk) == "ip:203.0.113.9", junk


def test_a_recognised_key_gets_its_own_rate_limit_bucket():
    """What a key actually changes about rate limiting today: who you share the
    bucket with. Two callers behind one address stop competing; an unrecognised
    key falls back to the address rather than minting a bucket per guess."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        print("  skip test_a_recognised_key_gets_its_own_rate_limit_bucket (fastapi not installed)")
        return
    from starlette.requests import Request
    from housing_label import api
    from housing_label.entitlements import key_id

    def req(headers=None, query=b""):
        scope = {"type": "http", "method": "GET", "path": "/label", "query_string": query,
                 "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                 "client": ("203.0.113.7", 1234), "scheme": "http", "server": ("test", 80)}
        return Request(scope)

    with _keys("pro:k_bucket"):
        assert api._bucket(req({"X-API-Key": "k_bucket"})) == key_id("k_bucket")
        assert api._bucket(req(query=b"key=k_bucket")) == key_id("k_bucket")
        assert api._bucket(req({"X-API-Key": "k_bad"})) == "203.0.113.7"
        assert api._bucket(req()) == "203.0.113.7"


def test_label_sheet_is_an_svg_scored_like_the_label():
    """/label.svg is the printable sheet. It must come back as an image with a
    filename, score through the same path as /label (so a printed sheet cannot
    disagree with the label it was printed from), and refuse a bad theme rather
    than quietly rendering the default."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  skip test_label_sheet_is_an_svg_scored_like_the_label (fastapi not installed)")
        return
    import housing_label.api as api

    real = api.build_label_parts
    calls = {"n": 0}
    def offline(**kw):
        calls["n"] += 1
        kw["allow_network"] = False       # deterministic, no network in the test
        return real(**kw)

    api._result_cache.clear()
    api.build_label_parts = offline
    try:
        client = TestClient(api.app)
        params = {"lat": 35.13, "lon": -89.99, "preset": "baseline"}
        r = client.get("/label.svg", params={**params, "label_text": "123 Main St",
                                             "scored": "2026-08-22"})
        assert r.status_code == 200, r.text[:200]
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-disposition"].startswith("inline; filename=")
        assert "123-main-st" in r.headers["content-disposition"]
        assert r.text.startswith("<svg") and "123 Main St" in r.text

        # download=1 is the only difference the browser needs to save it.
        d = client.get("/label.svg", params={**params, "download": 1})
        assert d.headers["content-disposition"].startswith("attachment; filename=")

        # The same numbers as /label, from the same scoring pass.
        payload = client.get("/label", params=params).json()
        assert f'{payload["composite_score"]:.1f}' in d.text

        # Scored, not cosmetic: a bad theme is a 400, and no location is a 400.
        assert client.get("/label.svg", params={**params, "theme": "drak"}).status_code == 400
        assert client.get("/label.svg").status_code == 400

        # And the 400 costs nothing. The endpoint is metered like /label, so a
        # typo in a cosmetic parameter must be refused before the scoring pass —
        # the API's own rule is that an invalid request is never charged.
        api._result_cache.clear()
        before = calls["n"]
        assert client.get("/label.svg", params={"lat": 34.05, "lon": -118.24,
                                                "preset": "baseline",
                                                "theme": "drak"}).status_code == 400
        assert calls["n"] == before, "a bad theme scored a label before refusing it"
    finally:
        api.build_label_parts = real
        api._result_cache.clear()


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
