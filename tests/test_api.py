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
    """Pure helpers — no FastAPI/network needed."""
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
        {"properties": {"countrycode": "DE", "name": "B"},
         "geometry": {"coordinates": [13.4, 52.5]}},                   # drop: non-US
        {"properties": {"countrycode": "US", "name": "C"},
         "geometry": {"coordinates": []}},                             # drop: bad coords
    ]
    out = _photon_features_to_suggestions(feats, 5)
    assert out == [{"label": "A, X, CA", "lat": 34.0, "lon": -118.0}]  # note lon/lat swap
    # limit is respected
    many = [{"properties": {"countrycode": "US", "name": str(i)},
             "geometry": {"coordinates": [float(i), 1.0]}} for i in range(10)]
    assert len(_photon_features_to_suggestions(many, 3)) == 3


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


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()
