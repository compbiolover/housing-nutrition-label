#!/usr/bin/env python3
"""HTTP API exposing the housing nutrition label for any US address.

A thin wrapper around the CLI simulator so a static site (e.g. the examples page
on housinglabel.dev) can fetch a real, all-dimension label for a typed address.
It reuses the exact same scoring path as `housing-simulate` (no model drift).

Install + run::

    pip install -e ".[api]"
    # set keys server-side for the full 9 dimensions (optional):
    export CENSUS_API_KEY=... WALKSCORE_API_KEY=...
    # optional: sharper address autocomplete (else keyless Photon is used):
    export GEOAPIFY_API_KEY=...
    housing-api                      # uvicorn on :8000 (PORT overrides)
    # or: uvicorn housing_label.api:app --host 0.0.0.0 --port 8000

Endpoints::

    GET /healthz                     liveness probe
    GET /suggest?q=<text>            US address typeahead [{label, lat, lon}]
    GET /label?address=<addr>        full label JSON for the address
    GET /label?lat=<y>&lon=<x>       …or by coordinates
        optional: preset, construction, year_built, foundation, condition,
                  value, units, sqft, lot_acres, flood_zone
    GET /density?address=<addr>      compare 1–4 dwelling units on the same parcel
        optional: units=1,2,4 (counts), per_unit_value, + all /label house params

CORS is restricted to https://housinglabel.dev by default; set the
ALLOWED_ORIGINS env var (comma-separated) to allow other origins or local dev.
"""

from __future__ import annotations

import logging
import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from housing_label.config import HEADERS, PHOTON_URL, GEOAPIFY_URL, GEOAPIFY_API_KEY
from housing_label.simulate.house import (
    build_label_parts, label_payload, density_comparison, cost_flows,
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
        out.append({"label": label, "lat": lat, "lon": lon})
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


def _geoapify_results_to_suggestions(results: list, limit: int) -> list[dict]:
    """Slim US-only [{label, lat, lon}] from Geoapify autocomplete results."""
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
        out.append({"label": label, "lat": float(lat), "lon": float(lon)})
        if len(out) >= limit:
            break
    return out


@app.get("/suggest")
def suggest(q: str | None = None) -> list[dict]:
    """US address typeahead. Uses Geoapify when a key is set (better ranking),
    else keyless Photon. Degrades to [] — never breaks the page."""
    text = (q or "").strip()
    if len(text) < _SUGGEST_MIN_CHARS:
        return []                                     # too short — empty, not an error
    text = text[:_SUGGEST_MAX_CHARS]

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
) -> dict:
    """Return the full nutrition-label payload for an address or lat/lon.

    `upgrades` is a comma-separated list of resilience-upgrade flags (see
    BONUS_FLAGS), e.g. ``upgrades=solar,fortified_roof,hurricane_straps``.
    `bldg_material` (wood|masonry|concrete|steel) and `stories` describe a
    multi-unit building's shell for Resilience/Durability when NSI didn't detect it.
    """
    if not address and (lat is None or lon is None):
        raise HTTPException(400, "Provide ?address= or both ?lat= and ?lon=")
    for name, val in (("preset", preset), ("construction", construction),
                      ("foundation", foundation), ("condition", condition),
                      ("flood_zone", flood_zone)):
        _validate(name, val)
    if bldg_material is not None and bldg_material.lower() not in (
            "wood", "masonry", "concrete", "steel"):
        raise HTTPException(400, "bldg_material must be one of: wood, masonry, concrete, steel")
    if stories is not None and stories < 1:
        raise HTTPException(400, "stories must be a positive integer")

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
            bldg_material=bldg_material, stories=stories,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — don't leak internals; log server-side
        log.exception("scoring failed (address=%r lat=%r lon=%r)", address, lat, lon)
        raise HTTPException(502, "scoring failed")
    payload = label_payload(cfg, r, lbl)
    # When the scored home IS the baseline comparable (preset=baseline with no
    # construction/upgrade overrides), the delta is 0 by definition — reuse the
    # already-computed house cost instead of a redundant second scoring pass.
    is_self_baseline = preset == "baseline" and not any((
        year_built, construction, foundation, condition, value, units, sqft,
        lot_acres, bldg_material, stories, upgrade_list,
    ))
    _attach_baseline_cost(payload, lbl, self_baseline=is_self_baseline)
    return payload


def _attach_baseline_cost(payload: dict, lbl: dict, self_baseline: bool = False) -> None:
    """Score a typical comparable (2000-era frame home) at the SAME resolved
    location and attach its cost flows, so the frontend can present the lifetime
    cost as a delta vs. a typical home here (research/lifetime-cost-research.md).

    Best-effort: the cost strip is optional and must never break the label. The
    already-fetched location dimensions are reused as overrides so the baseline
    pass does not re-hit the health/socio/walk APIs — it only needs the
    construction-driven energy + expected-loss flows.

    When the scored home already *is* the baseline (``self_baseline``), skip the
    second scoring pass and reuse the house's own cost flows (delta 0).
    """
    loc = lbl.get("location")
    if loc is None:
        return
    if self_baseline:
        flows = dict(payload.get("cost") or {})
        flows["label"] = "typical 2000-era frame home here"
        payload["baseline_cost"] = flows
        return
    main = {d["key"]: d.get("score") for d in lbl.get("dimensions", [])}
    overrides = {k: main.get(k) for k in ("health", "socioeconomic", "walkability")}
    try:
        _bcfg, _br, _blbl = build_label_parts(
            preset="baseline", location=loc, allow_network=True, overrides=overrides,
        )
    except Exception:  # noqa: BLE001 — never fail the label over the cost strip
        log.exception("baseline cost scoring failed")
        return
    flows = cost_flows(_br, _blbl)
    flows["label"] = "typical 2000-era frame home here"
    payload["baseline_cost"] = flows


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
        entry = label_payload(cfg, r, lbl)
        entry["name"] = name
        entry["preset"] = preset
        entry["description"] = desc
        out.append(entry)
    return {"location": out[0].get("location") if out else None, "presets": out}


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
    upgrades: str | None = None,
) -> dict:
    """Compare this parcel at several densities (fixed lot, vary dwelling units).

    Same inputs as ``/label`` (minus a single ``units``), plus:
      • ``units``          comma-separated unit counts to compare (default 1,2,3,4)
      • ``per_unit_value`` hold this per-unit value constant across scenarios
                           (else an explicit ``value`` is used as the per-unit
                           value, else the county median is auto-filled).
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

    try:
        return density_comparison(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            upgrades=upgrade_list, allow_network=True, unit_counts=unit_counts,
            per_unit_value=per_unit_value,
            year_built=year_built, construction=construction, foundation=foundation,
            condition=condition, value=value, sqft=sqft, lot_acres=lot_acres,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:  # noqa: BLE001 — don't leak internals; log server-side
        log.exception("density failed (address=%r lat=%r lon=%r)", address, lat, lon)
        raise HTTPException(502, "density comparison failed")


def serve() -> None:
    """Console entry point: run the API with uvicorn (PORT env var, default 8000)."""
    import uvicorn
    uvicorn.run("housing_label.api:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    serve()
