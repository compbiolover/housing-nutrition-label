"""config.py — shared constants for the Housing Nutrition Label pipeline.

Canonical home for cross-cutting values (data-source URLs, HTTP defaults, and
shared geographic reference points). Individual pipeline stages still define
their own dimension-specific constants (EUI benchmarks, EAL rates, scoring
thresholds, …) next to the logic that uses them; only values shared across
two or more stages belong here.
"""

from __future__ import annotations

import pathlib

# ── Project layout ──────────────────────────────────────────────────────────────
# Repo root, derived from this file's location (src/housing_label/config.py).
# Generated data CSVs live at the repo root.
PROJECT_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR: pathlib.Path = PROJECT_ROOT

# ── HTTP defaults ───────────────────────────────────────────────────────────────
TIMEOUT: int = 60          # seconds per HTTP call
RETRIES: int = 3           # attempts before giving up
BACKOFF: int = 2           # exponential back-off multiplier (BACKOFF ** attempt)

# Several upstream GIS WAFs return 403 for the default requests User-Agent, so we
# present a browser UA on every call.
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HEADERS: dict[str, str] = {"User-Agent": USER_AGENT}

# ── Data-source URLs ────────────────────────────────────────────────────────────
SHELBY_BASEMAP_URL = "https://gis.shelbycountytn.gov/public/rest/services/BaseMap/Assessor/MapServer"
SHELBY_CAMA_URL = "https://gis.shelbycountytn.gov/public/rest/services/Parcel/CertParcel_NOAttrib/MapServer"
FEMA_NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
SPC_TORNADO_URL = "https://www.spc.noaa.gov/wcm/data/1950-2023_actual_tornadoes.csv"

# ── Geographic reference points ─────────────────────────────────────────────────
EARTH_RADIUS_MI: float = 3958.7613   # mean Earth radius, miles (haversine)

# Memphis downtown core (Main St & Beale St) — proxy for high-density urban services.
MEMPHIS_CORE_LAT: float = 35.1495
MEMPHIS_CORE_LON: float = -90.0490

# New Madrid Seismic Zone reference point + NSHM 2023 baselines for Memphis.
NMSZ_LAT: float = 36.5
NMSZ_LON: float = -89.6
PGA_2PCT_BASE: float = 0.48    # g, 2%/50yr baseline
PGA_10PCT_BASE: float = 0.19   # g, 10%/50yr baseline
