#!/usr/bin/env python3
"""HTTP API exposing the housing nutrition label for any US address.

A thin wrapper around the CLI simulator so a static site (e.g. the examples page
on housinglabel.dev) can fetch a real, all-dimension label for a typed address.
It reuses the exact same scoring path as `housing-simulate` (no model drift).

Install + run::

    pip install -e ".[api]"
    # All 9 dimensions score with no API keys — health, socioeconomic, and
    # walkability are bundled national references.
    # optional: better address autocomplete (else keyless Photon is used).
    # Priority: Google Places → Geoapify → Photon.
    export GOOGLE_PLACES_API_KEY=...   # best US business/landmark coverage
    export GEOAPIFY_API_KEY=...        # sharper US ranking, no billing
    housing-api                      # uvicorn on :8000 (PORT overrides)
    # or: uvicorn housing_label.api:app --host 0.0.0.0 --port 8000

Endpoints::

    GET /healthz                     liveness probe
    GET /suggest?q=<text>            US address / place-name typeahead
    GET /place?place_id=<id>         resolve a Google place_id → {label, lat, lon, residential}
    GET /label?address=<addr>        full label JSON for the address
    GET /label?lat=<y>&lon=<x>       …or by coordinates
        optional: preset, construction, year_built, foundation, condition,
                  value, units, sqft, lot_acres, flood_zone,
                  allow_non_residential (score a detected non-residential building)
        → 422 when the address is a positively-detected non-residential building
          (workplace/store/…): the label rates homes only. Bypass with a preset,
          units>1, or allow_non_residential=true.
    GET /density?address=<addr>      compare 1–4 dwelling units on the same parcel
        optional: units=1,2,4 (counts), per_unit_value, + all /label house params

CORS is restricted to https://housinglabel.dev by default; set the
ALLOWED_ORIGINS env var (comma-separated) to allow other origins or local dev.

Operational env vars::

    RATE_LIMIT         per-IP limit on every endpoint except /healthz
                       (default "30/minute"; "" or "0" disables it)
    LABEL_CACHE_SIZE   max cached label results (default 512; 0 disables)
    LABEL_CACHE_TTL    cache entry lifetime in seconds (default 21600 = 6 h)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from housing_label.config import (
    HEADERS, PHOTON_URL, GEOAPIFY_URL, GEOAPIFY_API_KEY,
    GOOGLE_PLACES_AUTOCOMPLETE_URL, GOOGLE_PLACES_DETAILS_URL, GOOGLE_PLACES_API_KEY,
)
from housing_label.simulate.house import (
    build_label_parts, label_payload, density_comparison, cost_flows,
    NonResidentialProperty, _NON_RESIDENTIAL_MESSAGE,
    PRESETS, CONSTRUCTION_FACTOR, FOUNDATION_FACTOR, CONDITION_FACTOR,
    BONUS_FLAGS, ELEVATION_FLAGS,
)

log = logging.getLogger("housing_label.api")

# Allowed query-param vocabularies (mirror the CLI's argparse choices).
_CHOICES = {
    "preset": set(PRESETS),
    "construction": set(CONSTRUCTION_FACTOR),
    "foundation": set(FOUNDATION_FACTOR),
    "condition": set(CONDITION_FACTOR),
    "flood_zone": {"X", "X500", "AE"},
}


def _validate(name: str, value: str | None) -> None:
    allowed = _CHOICES[name]
    if value is not None and value not in allowed:
        raise HTTPException(
            400, f"invalid {name}={value!r}; choose one of: {', '.join(sorted(allowed))}")


def _validate_request(*, address, lat, lon, preset, construction, foundation,
                      condition, flood_zone, bldg_material, stories, upgrades):
    """Shared input validation for /label and /density (identical rules).

    Returns ``(bldg_material, upgrade_list)`` — the normalized material and the
    deduped+sorted upgrade flags — or raises HTTPException(400) on any bad field.
    """
    if not address and (lat is None or lon is None):
        raise HTTPException(400, "Provide ?address= or both ?lat= and ?lon=")
    for name, val in (("preset", preset), ("construction", construction),
                      ("foundation", foundation), ("condition", condition),
                      ("flood_zone", flood_zone)):
        _validate(name, val)
    if bldg_material is not None:
        bldg_material = bldg_material.strip().lower()   # normalize once, then validate + forward
        if bldg_material not in ("wood", "masonry", "concrete", "steel"):
            raise HTTPException(400, "bldg_material must be one of: wood, masonry, concrete, steel")
    if stories is not None and stories < 1:
        raise HTTPException(400, "stories must be a positive integer")

    # Deduplicate + sort once: a repeated flag (e.g. upgrades=solar,solar) must not
    # double-count in the elevation check below, nor split the cache into distinct
    # keys for semantically identical requests.
    upgrade_list = sorted({u.strip() for u in upgrades.split(",") if u.strip()}) if upgrades else []
    bad = [u for u in upgrade_list if u not in BONUS_FLAGS]
    if bad:
        raise HTTPException(400, f"unknown upgrade(s): {', '.join(bad)}; "
                                 f"choose from: {', '.join(BONUS_FLAGS)}")
    if sum(u in ELEVATION_FLAGS for u in upgrade_list) > 1:
        raise HTTPException(400, "at most one flood elevation tier may be selected")
    return bldg_material, upgrade_list


# CORS: lock to the production site by default. Override with ALLOWED_ORIGINS
# (comma-separated) for local dev or extra origins, e.g.
#   ALLOWED_ORIGINS="https://housinglabel.dev,http://localhost:8000"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "https://housinglabel.dev").split(",")
    if o.strip()
]

app = FastAPI(title="Housing Nutrition Label API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Rate limiting ────────────────────────────────────────────────────────────────
# Every scoring request fans out to several live upstreams — the optional keyed
# geocoder (Geoapify) and several free government APIs that throttle. Without
# a limit, one unauthenticated caller can drive cost and get the free endpoints
# blocked for everyone. A per-IP token bucket (default 30/min, override with the
# RATE_LIMIT env var; set it to "" / "0" to disable) fronts every endpoint via
# SlowAPIMiddleware; /healthz is exempted so probes are never throttled.
RATE_LIMIT = os.environ.get("RATE_LIMIT", "30/minute").strip()
_default_limits = [RATE_LIMIT] if RATE_LIMIT and RATE_LIMIT.lower() not in ("0", "off", "none") else []
limiter = Limiter(key_func=get_remote_address, default_limits=_default_limits)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# ── Result cache ─────────────────────────────────────────────────────────────────
# A scored label is stable for a location over a day (health/socio/walk/climate
# don't move intra-day), yet each request re-geocodes and re-scores end to end —
# and /label scores a second (baseline) pass on top. A bounded TTL+LRU cache of
# the finished payloads, keyed by the normalized request params, collapses repeat
# lookups (a shared address, a page reload, the same preset grid) to one fan-out.
# Bounded so it can't grow unbounded on the 512 MB host (see render.yaml).
def _env_num(name: str, default, cast):
    """Read a numeric operational knob from the environment, falling back to the
    default (with a warning) on a malformed value — a bad env var must never
    crash API startup."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        log.warning("Invalid %s=%r; using default %r.", name, raw, default)
        return default


_CACHE_MAXSIZE = _env_num("LABEL_CACHE_SIZE", 512, int)
_CACHE_TTL = _env_num("LABEL_CACHE_TTL", 21600.0, float)   # seconds (6 h)


class _TTLCache:
    """A small thread-safe bounded LRU cache with per-entry TTL. Disabled (always
    a miss) when maxsize or ttl is non-positive, so caching can be turned off with
    LABEL_CACHE_SIZE=0 or LABEL_CACHE_TTL=0."""

    def __init__(self, maxsize: int, ttl: float):
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._maxsize > 0 and self._ttl > 0

    def get(self, key):
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            ts, value = hit
            if now - ts > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    def put(self, key, value) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)   # evict least-recently-used

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_result_cache = _TTLCache(_CACHE_MAXSIZE, _CACHE_TTL)


@app.get("/healthz")
@limiter.exempt
def healthz() -> dict:
    return {"ok": True}


# ── Address autocomplete (Geoapify when keyed, else Photon) ──────────────────────

_SUGGEST_MIN_CHARS = 3
_SUGGEST_MAX_CHARS = 200
_SUGGEST_LIMIT = 5
_SUGGEST_TIMEOUT = 4          # seconds — interactive typeahead: fail fast, no retries


def _suggest_get(url: str, params: dict) -> dict | None:
    """Single short-timeout GET for the typeahead (no retries) → JSON or None.

    Unlike the pipeline's _get, this never retries — a slow/4xx upstream (e.g. a
    bad API key) must fail fast so the page falls back quickly, not after minutes.
    """
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=_SUGGEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001 — any failure → quietly fall back / empty
        return None


def _coord(v) -> float | None:
    """Parse a coordinate to float, or None if it isn't numeric."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Residential vs non-residential POI classification ────────────────────────────
# The geocoder knows what a place *is* (a stadium, an office tower, a store) via
# OSM tags — a signal the NSI-at-coordinate screen can't recover, because a
# non-residential address in a dense downtown sits amid residential towers and the
# neighborhood scan reads "residential". So we classify the suggestion here and
# carry the verdict to /label, which refuses to score a positively non-residential
# place. Returns True (a dwelling), False (positively non-residential), or None
# (unknown — a plain street address / untagged result, left for the NSI screen).
_RESIDENTIAL_BUILDING_VALUES = frozenset({
    "residential", "apartments", "house", "detached", "semidetached_house",
    "terrace", "dormitory", "bungalow", "cabin", "static_caravan", "houseboat",
    "duplex", "manufactured", "hut", "farm",
})
_NONRES_OSM_KEYS = frozenset({
    "shop", "office", "amenity", "leisure", "tourism", "aeroway", "railway",
    "industrial", "military", "man_made", "healthcare", "historic", "craft",
    "club", "emergency", "power", "aerialway", "public_transport", "sport",
})
_NONRES_BUILDING_VALUES = frozenset({
    "commercial", "office", "retail", "industrial", "warehouse", "stadium",
    "hospital", "school", "university", "college", "church", "cathedral",
    "chapel", "mosque", "temple", "synagogue", "hotel", "motel", "supermarket",
    "civic", "government", "public", "train_station", "transportation",
    "kindergarten", "sports_centre", "sports_hall", "grandstand", "hangar",
    "parking", "garage", "garages", "fire_station", "hospital",
})


def _residential_hint(osm_key, osm_value) -> bool | None:
    """Coarse residential verdict from a Photon feature's OSM tags."""
    k = (osm_key or "").strip().lower()
    v = (osm_value or "").strip().lower()
    if k == "building":
        if v in _RESIDENTIAL_BUILDING_VALUES:
            return True
        if v in _NONRES_BUILDING_VALUES:
            return False
        return None                       # building=yes / other → defer to NSI screen
    if k in _NONRES_OSM_KEYS:
        return False
    return None                           # place / highway / boundary → unknown


def _photon_label(props: dict) -> str:
    """Build a one-line US label from a Photon feature's properties.

    A plain address renders as "<house> <street>, city, state, postcode".
    A *named* feature — a business, campus, or landmark, where Photon puts the
    name in `name` — leads with the name and then appends its street address, so
    searching by place or company name shows the address it resolves to (e.g.
    "Acme Corp, 500 Oak Ave, Memphis, TN"). Named features with no street data
    still fall back to just the name + city/state.
    """
    def _clean(v):
        return v.strip() if isinstance(v, str) else v

    # Strip upstream fields before comparing/composing so trivial formatting
    # differences (e.g. a trailing space in `street`) don't defeat the name-vs-
    # street de-dup and produce a doubled "Main St, Main St, …" label.
    house = _clean(props.get("housenumber"))
    street = _clean(props.get("street"))
    name = _clean(props.get("name"))
    if house and street:
        addr_line = f"{house} {street}"
    elif street:
        addr_line = street
    else:
        addr_line = ""
    # Lead with the POI name (when it isn't just the street name repeated), then
    # its street address — otherwise the label is the plain street address.
    if name and name != street:
        line1 = f"{name}, {addr_line}" if addr_line else name
    else:
        line1 = addr_line or name or ""
    parts = [_clean(p) for p in (line1, props.get("city"), props.get("state"), props.get("postcode"))]
    return ", ".join(p for p in parts if p)


def _photon_features_to_suggestions(features: list, limit: int) -> list[dict]:
    """Slim US-only [{label, lat, lon}] from a Photon GeoJSON feature list."""
    out: list[dict] = []
    for f in features or []:
        props = f.get("properties") or {}
        cc = props.get("countrycode") or ""           # US-only (the scorer is US-only)
        if cc.upper() != "US":                         # case-insensitive: Photon uses "US",
            continue                                   # but self-hosted instances may differ
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) != 2:                          # Photon coords are [lon, lat]
            continue
        lat, lon = _coord(coords[1]), _coord(coords[0])
        if lat is None or lon is None:
            continue
        label = _photon_label(props)
        if not label:
            continue
        out.append({"label": label, "lat": lat, "lon": lon,
                    "residential": _residential_hint(props.get("osm_key"), props.get("osm_value"))})
        if len(out) >= limit:
            break
    return out


def _geoapify_label(r: dict) -> str:
    """One-line US address label from a Geoapify autocomplete result."""
    region = " ".join(x for x in (r.get("state_code") or r.get("state"), r.get("postcode")) if x)
    parts = [p for p in (r.get("address_line1") or r.get("name"), r.get("city"), region) if p]
    if parts:
        return ", ".join(parts)
    # fallback: Geoapify's pre-formatted string, minus the country suffix
    f = r.get("formatted") or ""
    for suffix in (", United States of America", ", United States"):
        if f.endswith(suffix):
            return f[: -len(suffix)]
    return f


def _geoapify_residential(r: dict) -> bool | None:
    """Coarse residential verdict from a Geoapify result's category/result_type."""
    cat = (r.get("category") or "").strip().lower()
    if cat.startswith("building.residential") or cat.startswith("accommodation.apartment"):
        return True
    nonres_prefixes = ("commercial", "catering", "office", "leisure", "tourism",
                       "building.commercial", "building.office", "building.retail",
                       "building.industrial", "education", "healthcare", "industrial",
                       "service", "entertainment", "sport", "religion")
    if any(cat.startswith(p) for p in nonres_prefixes):
        return False
    return None


def _geoapify_results_to_suggestions(results: list, limit: int) -> list[dict]:
    """Slim US-only [{label, lat, lon, residential}] from Geoapify autocomplete results."""
    out: list[dict] = []
    for r in results or []:
        if (r.get("country_code") or "").lower() != "us":   # US-only (the scorer is US-only)
            continue
        lat, lon = _coord(r.get("lat")), _coord(r.get("lon"))
        if lat is None or lon is None:
            continue
        label = _geoapify_label(r)
        if not label:
            continue
        out.append({"label": label, "lat": lat, "lon": lon,
                    "residential": _geoapify_residential(r)})
        if len(out) >= limit:
            break
    return out


# ── Google Places Autocomplete (New) — best US business/landmark coverage ────────
# Photon/Geoapify miss many US company HQs (e.g. "Unum" resolves to a village in
# Yemen on Photon). Google Autocomplete finds them and, being the typeahead-native
# API, ranks canonical entities well. Predictions carry the place `types` (drive
# the same residential screen) and a place_id resolved to coords via /place. The
# key is server-side only. Highest priority when configured.
_GOOGLE_NONRES_TYPES = frozenset({
    "stadium", "arena", "bank", "atm", "store", "shopping_mall", "supermarket",
    "department_store", "clothing_store", "school", "university", "primary_school",
    "secondary_school", "hospital", "doctor", "pharmacy", "airport", "train_station",
    "transit_station", "bus_station", "subway_station", "light_rail_station",
    "church", "mosque", "synagogue", "hindu_temple", "place_of_worship", "restaurant",
    "cafe", "bar", "gym", "stadium", "museum", "library", "city_hall",
    "local_government_office", "courthouse", "police", "fire_station", "post_office",
    "warehouse", "storage", "car_dealer", "car_repair", "gas_station", "parking",
    "corporate_office", "insurance_agency", "accounting", "lawyer", "real_estate_agency",
    "finance", "tourist_attraction", "amusement_park", "zoo", "movie_theater",
    "night_club", "lodging", "hotel", "motel", "convenience_store", "electronics_store",
    "hardware_store", "furniture_store", "shopping_center", "factory",
})
_GOOGLE_RES_TYPES = frozenset({
    "street_address", "premise", "subpremise", "route", "geocode", "postal_code",
    "neighborhood", "sublocality", "locality", "intersection",
})


def _google_residential(types) -> bool | None:
    """Coarse residential verdict from a Google place's `types`."""
    t = {str(x).lower() for x in (types or [])}
    if t & _GOOGLE_NONRES_TYPES:
        return False
    # A named establishment / point of interest that isn't an address-like type is a
    # business, not a home → non-residential (a home is never an "establishment").
    if ("establishment" in t or "point_of_interest" in t) \
            and not (t & {"premise", "subpremise", "street_address"}):
        return False
    return None                          # plain address / unknown → defer to NSI screen


def _google_label(place: dict) -> str:
    """One-line US label: lead with the business/place name, then its address."""
    disp = ((place.get("displayName") or {}).get("text") or "").strip()
    addr = (place.get("formattedAddress") or "").strip()
    for suffix in (", USA", ", United States"):
        if addr.endswith(suffix):
            addr = addr[: -len(suffix)].strip()
    if disp and addr and not addr.startswith(disp):
        return f"{disp}, {addr}"
    return addr or disp


def _google_prediction_label(pred: dict) -> str:
    """One-line label from an Autocomplete prediction, minus the country suffix."""
    txt = ((pred.get("text") or {}).get("text") or "").strip()
    if not txt:
        sf = pred.get("structuredFormat") or {}
        main = ((sf.get("mainText") or {}).get("text") or "").strip()
        sec = ((sf.get("secondaryText") or {}).get("text") or "").strip()
        txt = ", ".join(p for p in (main, sec) if p)
    for suffix in (", USA", ", United States"):
        if txt.endswith(suffix):
            txt = txt[: -len(suffix)].strip()
    return txt


def _google_predictions_to_suggestions(suggestions: list, limit: int) -> list[dict]:
    """Slim [{label, place_id, residential}] from Autocomplete predictions. These
    carry a place_id but NO coordinates — the frontend resolves the picked one's
    lat/lon via /place (Place Details) so the pair is one billed session."""
    out: list[dict] = []
    for s in suggestions or []:
        pred = s.get("placePrediction") or {}
        pid = pred.get("placeId")
        if not pid:
            continue                          # query predictions (no place) → skip
        label = _google_prediction_label(pred)
        if not label:
            continue
        out.append({"label": label, "place_id": pid,
                    "residential": _google_residential(pred.get("types"))})
        if len(out) >= limit:
            break
    return out


def _google_detail_to_result(place: dict) -> dict | None:
    """{label, lat, lon, residential} from a Place Details response, or None."""
    loc = place.get("location") or {}
    lat, lon = _coord(loc.get("latitude")), _coord(loc.get("longitude"))
    if lat is None or lon is None:
        return None
    label = _google_label(place)
    if not label:
        return None
    return {"label": label, "lat": lat, "lon": lon,
            "residential": _google_residential(place.get("types"))}


_GOOGLE_AC_FIELD_MASK = ("suggestions.placePrediction.placeId,suggestions.placePrediction.text,"
                         "suggestions.placePrediction.structuredFormat,"
                         "suggestions.placePrediction.types")
_GOOGLE_DETAILS_FIELD_MASK = "location,formattedAddress,displayName,types"


def _google_autocomplete_request(text: str, session: str | None):
    """POST the Autocomplete query; returns the requests.Response (may raise)."""
    body = {"input": text, "includedRegionCodes": ["us"], "languageCode": "en"}
    if session:
        body["sessionToken"] = session
    return requests.post(
        GOOGLE_PLACES_AUTOCOMPLETE_URL, json=body,
        headers={
            **HEADERS, "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": _GOOGLE_AC_FIELD_MASK,
        },
        timeout=_SUGGEST_TIMEOUT,
    )


def _google_details_request(place_id: str, session: str | None):
    """GET Place Details for a place_id; returns the requests.Response (may raise)."""
    params = {"sessionToken": session} if session else None
    return requests.get(
        GOOGLE_PLACES_DETAILS_URL.rstrip("/") + "/" + place_id, params=params,
        headers={
            **HEADERS,
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": _GOOGLE_DETAILS_FIELD_MASK,
        },
        timeout=_SUGGEST_TIMEOUT,
    )


def _google_json(r, what: str) -> dict | None:
    """Response → JSON, or None with a WARNING (so a misconfigured key surfaces in
    the server logs). The error body names the exact cause; never the key."""
    if not r.ok:
        log.warning("Google Places %s HTTP %s: %s", what, r.status_code, (r.text or "")[:300])
        return None
    try:
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Google Places %s returned non-JSON: %s", what, exc)
        return None


def _google_suggest(text: str, session: str | None) -> dict | None:
    """Autocomplete → JSON or None (quiet fallback to the next provider)."""
    try:
        r = _google_autocomplete_request(text, session)
    except Exception as exc:  # noqa: BLE001 — network/timeout
        log.warning("Google Places autocomplete failed (network): %s", exc)
        return None
    return _google_json(r, "autocomplete")


def _google_probe(text: str, session: str | None = None) -> dict:
    """Diagnose the Google Autocomplete path for /suggest?debug=1 — the HTTP status
    and Google's own error message (never the key)."""
    try:
        r = _google_autocomplete_request(text, session)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"request failed: {exc}"}
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"raw": (r.text or "")[:300]}
    if r.ok:
        return {"ok": True, "http_status": r.status_code,
                "results": len(body.get("suggestions") or [])}
    err = (body or {}).get("error") or {}
    return {"ok": False, "http_status": r.status_code,
            "google_status": err.get("status"),
            "message": err.get("message") or body}


_SESSION_MAX_CHARS = 128            # a client UUID session token; bound the input


@app.get("/suggest")
def suggest(q: str | None = None, session: str | None = None, debug: bool = False):
    """US address / place-name typeahead. Resolves business, campus, and landmark
    names as well as street addresses, so typing a company or place name surfaces
    the address it sits at, plus a `residential` verdict per result (used by the
    residential screen). Back-end priority: Google Places (best US business/landmark
    coverage) when `GOOGLE_PLACES_API_KEY` is set, else Geoapify when
    `GEOAPIFY_API_KEY` is set (sharper US ranking), else keyless Photon — each
    falling back to the next if unreachable. Degrades to [] — never breaks the page.

    Google Autocomplete results carry a `place_id` (no coordinates); the caller
    resolves the picked one's lat/lon via GET /place. Geoapify/Photon results carry
    `lat`/`lon` directly. `session` is a client-generated token that bundles a
    typeahead's autocomplete calls + its one /place lookup into a single billed
    Google session (ignored by Geoapify/Photon).

    `?debug=1` returns which providers are configured and, when a Google key is
    set, a live probe of the Google call (HTTP status + Google's error message,
    never the key) so a misconfigured key can be diagnosed without server logs."""
    text = (q or "").strip()
    session = (session or "").strip()[:_SESSION_MAX_CHARS] or None
    if debug:
        info = {"query": text, "configured": {
            "google": bool(GOOGLE_PLACES_API_KEY),
            "geoapify": bool(GEOAPIFY_API_KEY),
            "photon": True,
        }}
        if GOOGLE_PLACES_API_KEY and len(text) >= _SUGGEST_MIN_CHARS:
            info["google_probe"] = _google_probe(text[:_SUGGEST_MAX_CHARS], session)
        return info
    if len(text) < _SUGGEST_MIN_CHARS:
        return []                                     # too short — empty, not an error
    text = text[:_SUGGEST_MAX_CHARS]

    if GOOGLE_PLACES_API_KEY:
        data = _google_suggest(text, session)
        if data is not None:                          # only fall through if unreachable
            return _google_predictions_to_suggestions(data.get("suggestions") or [], _SUGGEST_LIMIT)

    if GEOAPIFY_API_KEY:
        data = _suggest_get(GEOAPIFY_URL, {
            "text": text, "apiKey": GEOAPIFY_API_KEY,
            "filter": "countrycode:us", "limit": _SUGGEST_LIMIT,
            "format": "json", "lang": "en",
        })
        if data is not None:                          # only fall back to Photon if unreachable
            return _geoapify_results_to_suggestions(data.get("results") or [], _SUGGEST_LIMIT)

    data = _suggest_get(PHOTON_URL, {
        "q": text,
        "limit": _SUGGEST_LIMIT * 3,                  # over-fetch so the US filter isn't starved
        "lang": "en",
    })
    if not data:                                      # upstream down/timeout → quietly empty
        return []
    return _photon_features_to_suggestions(data.get("features") or [], _SUGGEST_LIMIT)


@app.get("/place")
def place(place_id: str | None = None, session: str | None = None) -> dict:
    """Resolve a Google Autocomplete `place_id` to `{label, lat, lon, residential}`
    via Place Details, closing the `session` started by /suggest (so the pair bills
    as one Google session). Only meaningful with a Google key; returns 404 when the
    place can't be resolved and 503 when Places isn't configured/unreachable. The
    key is proxied server-side and never returned."""
    pid = (place_id or "").strip()
    if not pid:
        raise HTTPException(400, "place_id is required")
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(503, "Place lookup is unavailable (no Google Places key configured).")
    session = (session or "").strip()[:_SESSION_MAX_CHARS] or None
    try:
        r = _google_details_request(pid, session)
    except Exception as exc:  # noqa: BLE001 — network/timeout
        log.warning("Google Places details failed (network): %s", exc)
        raise HTTPException(503, "Place lookup is temporarily unavailable.")
    data = _google_json(r, "details")
    result = _google_detail_to_result(data) if data else None
    if result is None:
        raise HTTPException(404, "Could not resolve that place.")
    return result


@app.get("/label")
def label(
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    preset: str | None = None,
    construction: str | None = None,
    year_built: int | None = None,
    foundation: str | None = None,
    condition: str | None = None,
    value: float | None = None,
    units: int | None = None,
    sqft: float | None = None,
    lot_acres: float | None = None,
    flood_zone: str | None = None,
    bldg_material: str | None = None,
    stories: int | None = None,
    upgrades: str | None = None,
    allow_non_residential: bool = False,
    nonresidential: bool = False,
) -> dict:
    """Return the full nutrition-label payload for an address or lat/lon.

    `upgrades` is a comma-separated list of resilience-upgrade flags (see
    BONUS_FLAGS), e.g. ``upgrades=solar,fortified_roof,hurricane_straps``.
    `bldg_material` (wood|masonry|concrete|steel) and `stories` describe a
    multi-unit building's shell for Resilience/Durability when NSI didn't detect it.

    A real address (no `preset`) is refused with **422** — the label rates
    residential dwellings only — when it is positively non-residential: NSI or the
    USA Structures footprint occupancy class identifies it as such, OR the caller
    passes `nonresidential=true` (set by the frontend when the picked geocoder
    suggestion was a non-residential POI, e.g. a stadium or office tower — a signal
    the coordinate alone can't recover downtown). Pass `allow_non_residential=true`
    to score it anyway.
    """
    bldg_material, upgrade_list = _validate_request(
        address=address, lat=lat, lon=lon, preset=preset, construction=construction,
        foundation=foundation, condition=condition, flood_zone=flood_zone,
        bldg_material=bldg_material, stories=stories, upgrades=upgrades)

    # Geocoder-sourced non-residential screen: the picked suggestion was a
    # positively non-residential POI (stadium, office, store — classified from OSM
    # tags in /suggest). Refuse it up front, since the NSI-at-coordinate screen
    # can't see it in a residential-dense downtown. A hypothetical `preset` isn't a
    # real address, and `allow_non_residential` is the explicit override.
    if nonresidential and not allow_non_residential and preset is None:
        raise HTTPException(422, _NON_RESIDENTIAL_MESSAGE)

    cache_key = ("label", address, lat, lon, preset, construction, year_built,
                 foundation, condition, value, units, sqft, lot_acres, flood_zone,
                 bldg_material, stories, tuple(upgrade_list),   # already sorted + unique
                 allow_non_residential)
    cached = _result_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        cfg, r, lbl = build_label_parts(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            upgrades=upgrade_list,
            allow_network=True, allow_non_residential=allow_non_residential,
            year_built=year_built, construction=construction, foundation=foundation,
            condition=condition, value=value, units=units, sqft=sqft, lot_acres=lot_acres,
            bldg_material=bldg_material, stories=stories,
        )
    except NonResidentialProperty as exc:
        # Not bad input — a deliberate residential-only screen. 422 (Unprocessable
        # Content) lets the frontend distinguish "we won't score this" from a 400
        # validation error or a 502 upstream failure, and show the guidance verbatim.
        raise HTTPException(422, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — don't leak internals; log server-side
        log.exception("scoring failed (address=%r lat=%r lon=%r)", address, lat, lon)
        raise HTTPException(502, "scoring failed")
    payload = label_payload(cfg, r, lbl)
    # When the scored home IS its own baseline comparable, the delta is 0 by
    # definition — reuse the already-computed house cost instead of a redundant
    # (network-hitting) second scoring pass. See _is_self_baseline.
    is_self_baseline = _is_self_baseline(
        preset, year_built=year_built, construction=construction,
        foundation=foundation, condition=condition, bldg_material=bldg_material,
        upgrade_list=upgrade_list,
    )
    _attach_baseline_cost(payload, lbl, cfg, self_baseline=is_self_baseline)
    _attach_detached_cost(payload, r, cfg)   # multi-unit → density-dividend line
    # Don't cache a degraded label. When NSI structure detection was unavailable
    # (a transient upstream outage), the building falls back to generic defaults —
    # caching that would pin a wrong "single-family / defaults" label onto this
    # exact coordinate for the whole TTL, poisoning a bookmarked or shared URL.
    # Skip the cache so the next request re-detects the real building.
    if not getattr(lbl.get("location"), "structure_unavailable", False):
        _result_cache.put(cache_key, payload)
    return payload


_BASELINE_LABEL = "a same-size 2000-era frame home"

# Subject attributes the baseline comparable inherits so the cost delta isolates
# construction QUALITY, not size or exposure. Energy scales with sqft and expected
# loss scales with value/units and flood exposure, so a baseline fixed at 2,000 sqft
# / $160k / zone X would make any large, valuable, or flood-exposed home look
# expensive regardless of build. We copy only these size/exposure fields; the
# baseline keeps the preset's typical-2000-frame construction (year built, material,
# condition, foundation). flood_zone is handled separately (explicit kwarg below)
# because the preset hard-codes it to "X" and would otherwise never match the
# subject's real, location-derived zone.
_BASELINE_SIZE_FIELDS = ("sqft", "value", "units", "stories", "lot_acres")


def _is_self_baseline(preset, *, year_built, construction, foundation, condition,
                      bldg_material, upgrade_list) -> bool:
    """True when a scored home already IS its own baseline comparable, so the cost
    delta is 0 and the second scoring pass can be skipped.

    Only ``preset="baseline"`` homes qualify. The comparable inherits the subject's
    size / value / flood exposure (see ``_attach_baseline_cost``), so those never
    matter here. A construction arg counts as a real difference only when it
    *differs from the baseline preset's own default* — passing the default value
    (e.g. ``year_built=2000`` or ``construction=frame``) is a no-op that still
    describes the baseline build. Comparisons are explicit (``== default`` / ``is
    None``), not truthiness, so a falsy-but-real value like ``year_built=0`` (not
    range-validated upstream) is correctly treated as a difference.
    """
    if preset != "baseline":
        return False
    b = PRESETS["baseline"]
    return (
        (year_built is None or year_built == b["year_built"])
        and (construction is None or construction == b["construction"])
        and (foundation is None or foundation == b["foundation"])
        and (condition is None or condition == b["condition"])
        and bldg_material is None            # baseline is single-family (no material)
        and not upgrade_list
    )


def _attach_baseline_cost(payload: dict, lbl: dict, cfg: dict,
                          self_baseline: bool = False) -> None:
    """Score a same-size 2000-era frame comparable at the SAME resolved location
    and attach its cost flows, so the frontend can present the lifetime cost as a
    delta vs. an equivalent typical home (research/lifetime-cost-research.md).

    The comparable matches the subject home's size/value/exposure and differs only
    in construction, so the delta reflects build quality rather than square footage.

    Best-effort: the cost strip is optional and must never break the label. The
    already-fetched location dimensions are reused as overrides so the baseline
    pass does not re-hit the health/socio/walk APIs — it only needs the
    construction-driven energy + expected-loss flows.

    When the scored home already *is* the baseline (``self_baseline``), skip the
    second scoring pass and reuse the house's own cost flows (delta 0).
    """
    # Self-baseline delta is 0 and reuses the already-computed house cost, so it
    # needs no location — attach it before the location guard so a failed geocode
    # doesn't drop the strip in this case.
    if self_baseline:
        flows = dict(payload.get("cost") or {})
        flows["label"] = _BASELINE_LABEL
        payload["baseline_cost"] = flows
        return
    loc = lbl.get("location")
    if loc is None:
        return
    main = {d["key"]: d.get("score") for d in lbl.get("dimensions", [])}
    overrides = {k: main.get(k) for k in ("health", "socioeconomic", "walkability")}
    size_fields = {k: cfg.get(k) for k in _BASELINE_SIZE_FIELDS if cfg.get(k) is not None}
    # Match the subject's resolved flood zone (build_label_parts always sets it,
    # auto-derived from the location when not supplied). Passed as the explicit
    # kwarg so it overrides the baseline preset's hard-coded "X".
    flood_zone = cfg.get("flood_zone")
    try:
        _bcfg, _br, _blbl = build_label_parts(
            preset="baseline", location=loc, allow_network=True, overrides=overrides,
            flood_zone=flood_zone, **size_fields,
        )
    except Exception:  # noqa: BLE001 — never fail the label over the cost strip
        log.exception("baseline cost scoring failed")
        return
    flows = cost_flows(_br, _blbl)
    flows["label"] = _BASELINE_LABEL
    payload["baseline_cost"] = flows


_DETACHED_LABEL = "the same home standing alone"


def _attach_detached_cost(payload: dict, r: dict, cfg: dict) -> None:
    """For a MULTI-UNIT building, attach the run-and-insure cost of *the same home
    standing alone* — same size, value, and build quality, detached instead of
    stacked — so the frontend can show the density dividend in dollars.

    This isolates DENSITY, holding everything else fixed: the only two things a
    party wall changes are (1) heating/cooling energy — the same home is scored off
    a different ResStock building-type EUI benchmark when detached, so the ratio of
    the two benchmarks (``energy_detached_ratio``, surfaced by the energy model)
    reprices its energy — and (2) flood exposure — only a building's lowest floors
    flood (``flood_floor``). Reversing exactly those two factors off the unit's own
    already-scored flows gives the detached comparable without a second scoring pass,
    and without letting any material/BRM/size difference leak in (that would be
    quality, not density — the same-size headline's job). The shared-*infrastructure*
    side of density shows separately in Infrastructure Burden.

    Best-effort and only for units > 1; single-family homes skip it entirely.
    """
    # Use the *effective* unit count the energy model actually scored — the
    # detected-or-entered ``structure.num_units``, NOT ``cfg["units"]``. An
    # NSI-detected building leaves cfg["units"] at its default of 1, so gating on it
    # would skip the line for exactly the towers this is meant to serve.
    struct = payload.get("structure") or {}
    try:
        units = int(struct.get("num_units") or cfg.get("units") or 1)
    except (TypeError, ValueError):   # best-effort: a malformed count must not break the label
        return
    if units <= 1:
        return
    house = payload.get("cost")
    if not house:
        return
    detached = dict(house)
    # (1) Reprice energy at the detached benchmark. energy_detached_ratio =
    #     detached-base-EUI / this-building-type-base-EUI (the within-cell and
    #     feature factors cancel). >1 → detached costs more (density helped);
    #     <1 → detached costs less (small MF is less efficient per sqft).
    ratio = (payload.get("metrics") or {}).get("energy_detached_ratio")
    if house.get("annualEnergyCost") is not None and ratio is not None:
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):   # best-effort: never break label rendering
            ratio = 0.0
        if ratio > 0:
            detached["annualEnergyCost"] = round(house["annualEnergyCost"] * ratio)
    # (2) Undo the floor-aware flood reduction → full ground-floor exposure. Only
    #     the flood peril moves; the other perils' losses are unchanged.
    flood_floor = r.get("flood_floor") or 1.0
    if house.get("expectedAnnualLoss") is not None and 0 < flood_floor < 1:
        extra_flood = (r.get("flood_loss") or 0.0) * (1.0 / flood_floor - 1.0)
        base_loss = r.get("total_loss")   # explicit None check: a real 0.0 loss must survive
        if base_loss is None:
            base_loss = house["expectedAnnualLoss"]
        detached["expectedAnnualLoss"] = round(base_loss + extra_flood)
    detached["label"] = _DETACHED_LABEL
    payload["detached_cost"] = detached


# The construction profiles shown on the Label page, scored side by side at one
# location. (name, preset, description) — mirrors the old sample-data generator.
_WEBSITE_PRESETS = [
    ("Worst Case",     "worst-case",     "1945 wood frame, AE flood zone, poor condition"),
    ("Baseline",       "baseline",       "2000 wood frame, X flood zone, average condition"),
    ("Premium",        "premium",        "2026 brick, X flood zone, excellent condition"),
    ("FORTIFIED Gold", "fortified-gold", "2026 frame with FORTIFIED Gold roof system"),
    ("ICF Passive",    "icf-passive",    "2026 ICF, solar, passive-house envelope, all resilience upgrades"),
]
# The Label page anchors on the walkable Cooper-Young neighborhood in Memphis.
_PRESETS_DEFAULT_LAT, _PRESETS_DEFAULT_LON = 35.13, -89.99


@app.get("/presets")
def presets(
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Score the standard construction presets at one location in a single
    response — feeds the Label page without one /label call per preset.

    The location is resolved once (first preset) and reused for the rest, and
    the location-driven dimensions (health/socio/walkability) are fetched once
    and passed as overrides, so this is one geocode + one location fetch total
    regardless of preset count. No per-preset baseline is attached: the Baseline
    profile is in the set, so the frontend computes cost deltas client-side.
    """
    if not address:
        if lat is None and lon is None:
            lat, lon = _PRESETS_DEFAULT_LAT, _PRESETS_DEFAULT_LON   # Label-page default
        elif lat is None or lon is None:
            raise HTTPException(400, "Provide both ?lat= and ?lon= (or ?address=, or neither)")

    cache_key = ("presets", address, lat, lon)
    cached = _result_cache.get(cache_key)
    if cached is not None:
        return cached

    out = []
    resolved = None
    loc_overrides = None
    for name, preset, desc in _WEBSITE_PRESETS:
        kwargs = {"preset": preset, "allow_network": True}
        if resolved is not None:
            kwargs["location"] = resolved
            kwargs["overrides"] = loc_overrides
        elif address:
            kwargs["address"] = address
        else:
            kwargs["lat"], kwargs["lon"] = lat, lon
        try:
            cfg, r, lbl = build_label_parts(**kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception:  # noqa: BLE001 — don't leak internals; log server-side
            log.exception("preset scoring failed (preset=%r)", preset)
            raise HTTPException(502, "scoring failed")
        if resolved is None:                       # capture location + its dims once
            resolved = lbl.get("location")
            main = {d["key"]: d.get("score") for d in lbl.get("dimensions", [])}
            loc_overrides = {k: main.get(k) for k in ("health", "socioeconomic", "walkability")}
        entry = label_payload(cfg, r, lbl, include_building=False)
        entry["name"] = name
        entry["preset"] = preset
        entry["description"] = desc
        out.append(entry)
    result = {"location": out[0].get("location") if out else None, "presets": out}
    _result_cache.put(cache_key, result)
    return result


# Cap how many density scenarios one request can fan out into (each is a full
# scoring pass): the website only ever asks for 1–4.
_DENSITY_MAX_SCENARIOS = 6


@app.get("/density")
def density(
    address: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    preset: str | None = None,
    construction: str | None = None,
    year_built: int | None = None,
    foundation: str | None = None,
    condition: str | None = None,
    value: float | None = None,
    per_unit_value: float | None = None,
    sqft: float | None = None,
    lot_acres: float | None = None,
    flood_zone: str | None = None,
    units: str | None = None,
    bldg_material: str | None = None,
    stories: int | None = None,
    upgrades: str | None = None,
) -> dict:
    """Compare this parcel at several densities (fixed lot, vary dwelling units).

    Same inputs as ``/label`` (minus a single ``units``), plus:
      • ``units``          comma-separated unit counts to compare (default 1,2,3,4)
      • ``per_unit_value`` hold this per-unit value constant across scenarios
                           (else an explicit ``value`` is used as the per-unit
                           value, else the county median is auto-filled).
    """
    bldg_material, upgrade_list = _validate_request(
        address=address, lat=lat, lon=lon, preset=preset, construction=construction,
        foundation=foundation, condition=condition, flood_zone=flood_zone,
        bldg_material=bldg_material, stories=stories, upgrades=upgrades)

    unit_counts = None
    if units:
        try:
            unit_counts = [int(x) for x in units.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "units must be comma-separated integers, e.g. 1,2,4")
        unit_counts = sorted({n for n in unit_counts if n >= 1})
        if not unit_counts:
            raise HTTPException(400, "units must contain at least one positive integer")
        if len(unit_counts) > _DENSITY_MAX_SCENARIOS:
            raise HTTPException(400, f"at most {_DENSITY_MAX_SCENARIOS} unit counts "
                                     "may be compared at once")

    cache_key = ("density", address, lat, lon, preset, construction, year_built,
                 foundation, condition, value, per_unit_value, sqft, lot_acres,
                 flood_zone, bldg_material, stories, tuple(upgrade_list),   # sorted + unique
                 tuple(unit_counts) if unit_counts is not None else None)
    cached = _result_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        result = density_comparison(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            upgrades=upgrade_list, allow_network=True, unit_counts=unit_counts,
            per_unit_value=per_unit_value,
            year_built=year_built, construction=construction, foundation=foundation,
            condition=condition, value=value, sqft=sqft, lot_acres=lot_acres,
            bldg_material=bldg_material, stories=stories,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — don't leak internals; log server-side
        log.exception("density failed (address=%r lat=%r lon=%r)", address, lat, lon)
        raise HTTPException(502, "density comparison failed")
    _result_cache.put(cache_key, result)
    return result


def serve() -> None:
    """Console entry point: run the API with uvicorn (PORT env var, default 8000)."""
    import uvicorn
    uvicorn.run("housing_label.api:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    serve()
