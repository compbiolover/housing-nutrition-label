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


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
