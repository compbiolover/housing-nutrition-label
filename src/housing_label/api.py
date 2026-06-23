#!/usr/bin/env python3
"""HTTP API exposing the housing nutrition label for any US address.

A thin wrapper around the CLI simulator so a static site (e.g. the examples page
on housinglabel.dev) can fetch a real, all-dimension label for a typed address.
It reuses the exact same scoring path as `housing-simulate` (no model drift).

Install + run::

    pip install -e ".[api]"
    # set keys server-side for the full 8 dimensions (optional):
    export CENSUS_API_KEY=... WALKSCORE_API_KEY=...
    housing-api                      # uvicorn on :8000 (PORT overrides)
    # or: uvicorn housing_label.api:app --host 0.0.0.0 --port 8000

Endpoints::

    GET /healthz                     liveness probe
    GET /suggest?q=<text>            US address typeahead [{label, lat, lon}]
    GET /label?address=<addr>        full label JSON for the address
    GET /label?lat=<y>&lon=<x>       …or by coordinates
        optional: preset, construction, year_built, foundation, condition,
                  value, units, sqft, lot_acres, flood_zone

CORS is restricted to https://housinglabel.dev by default; set the
ALLOWED_ORIGINS env var (comma-separated) to allow other origins or local dev.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from housing_label.config import PHOTON_URL
from housing_label.simulate.house import (
    build_label_parts, label_payload,
    PRESETS, CONSTRUCTION_FACTOR, FOUNDATION_FACTOR, CONDITION_FACTOR,
    BONUS_FLAGS, ELEVATION_FLAGS,
)
from housing_label.simulate.location import _get as _http_get

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


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# ── Address autocomplete (Photon proxy) ──────────────────────────────────────────

_SUGGEST_MIN_CHARS = 3
_SUGGEST_MAX_CHARS = 200
_SUGGEST_LIMIT = 5


def _photon_label(props: dict) -> str:
    """Build a one-line US address label from a Photon feature's properties."""
    house = props.get("housenumber")
    street = props.get("street") or props.get("name")
    line1 = f"{house} {street}".strip() if house and street else (street or props.get("name") or "")
    parts = [p for p in (line1, props.get("city"), props.get("state"), props.get("postcode")) if p]
    return ", ".join(parts)


def _photon_features_to_suggestions(features: list, limit: int) -> list[dict]:
    """Slim US-only [{label, lat, lon}] from a Photon GeoJSON feature list."""
    out: list[dict] = []
    for f in features or []:
        props = f.get("properties") or {}
        if props.get("countrycode") != "US":          # US-only (the scorer is US-only)
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) != 2:                          # Photon coords are [lon, lat]
            continue
        label = _photon_label(props)
        if not label:
            continue
        out.append({"label": label, "lat": float(coords[1]), "lon": float(coords[0])})
        if len(out) >= limit:
            break
    return out


@app.get("/suggest")
def suggest(q: str | None = None) -> list[dict]:
    """US address typeahead via Photon. Degrades to [] — never breaks the page."""
    text = (q or "").strip()
    if len(text) < _SUGGEST_MIN_CHARS:
        return []                                     # too short — empty, not an error
    data = _http_get(PHOTON_URL, {
        "q": text[:_SUGGEST_MAX_CHARS],
        "limit": _SUGGEST_LIMIT * 3,                  # over-fetch so the US filter isn't starved
        "lang": "en",
    })
    if not data:                                      # upstream down/timeout → quietly empty
        return []
    return _photon_features_to_suggestions(data.get("features") or [], _SUGGEST_LIMIT)


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
    upgrades: str | None = None,
) -> dict:
    """Return the full nutrition-label payload for an address or lat/lon.

    `upgrades` is a comma-separated list of resilience-upgrade flags (see
    BONUS_FLAGS), e.g. ``upgrades=solar,fortified_roof,hurricane_straps``.
    """
    if not address and (lat is None or lon is None):
        raise HTTPException(400, "Provide ?address= or both ?lat= and ?lon=")
    for name, val in (("preset", preset), ("construction", construction),
                      ("foundation", foundation), ("condition", condition),
                      ("flood_zone", flood_zone)):
        _validate(name, val)

    upgrade_list = [u.strip() for u in upgrades.split(",") if u.strip()] if upgrades else []
    bad = [u for u in upgrade_list if u not in BONUS_FLAGS]
    if bad:
        raise HTTPException(400, f"unknown upgrade(s): {', '.join(bad)}; "
                                 f"choose from: {', '.join(BONUS_FLAGS)}")
    if sum(u in ELEVATION_FLAGS for u in upgrade_list) > 1:
        raise HTTPException(400, "at most one flood elevation tier may be selected")

    try:
        cfg, r, lbl = build_label_parts(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            upgrades=upgrade_list,
            allow_network=True,
            year_built=year_built, construction=construction, foundation=foundation,
            condition=condition, value=value, units=units, sqft=sqft, lot_acres=lot_acres,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — don't leak internals; log server-side
        log.exception("scoring failed (address=%r lat=%r lon=%r)", address, lat, lon)
        raise HTTPException(502, "scoring failed")
    return label_payload(cfg, r, lbl)


def serve() -> None:
    """Console entry point: run the API with uvicorn (PORT env var, default 8000)."""
    import uvicorn
    uvicorn.run("housing_label.api:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    serve()
