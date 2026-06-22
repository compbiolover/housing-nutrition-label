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
    GET /label?address=<addr>        full label JSON for the address
    GET /label?lat=<y>&lon=<x>       …or by coordinates
        optional: preset, construction, year_built, foundation, condition,
                  value, units, sqft, lot_acres, flood_zone

CORS is open by default (read-only GETs); narrow `allow_origins` for production.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from housing_label.simulate.house import build_label_parts, label_payload

app = FastAPI(title="Housing Nutrition Label API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # narrow to your site's origin in production
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


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
) -> dict:
    """Return the full nutrition-label payload for an address or lat/lon."""
    if not address and (lat is None or lon is None):
        raise HTTPException(400, "Provide ?address= or both ?lat= and ?lon=")
    try:
        cfg, r, lbl = build_label_parts(
            address=address, lat=lat, lon=lon, preset=preset, flood_zone=flood_zone,
            allow_network=True,
            year_built=year_built, construction=construction, foundation=foundation,
            condition=condition, value=value, units=units, sqft=sqft, lot_acres=lot_acres,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"scoring failed: {exc}")
    return label_payload(cfg, r, lbl)


def serve() -> None:
    """Console entry point: run the API with uvicorn (PORT env var, default 8000)."""
    import uvicorn
    uvicorn.run("housing_label.api:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    serve()
