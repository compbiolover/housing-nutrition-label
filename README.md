# Housing Nutrition Label

An open-source platform for scoring residential properties across multiple dimensions — disaster resilience, energy efficiency, walkability, and more — presented in a clear, standardized format, like a nutrition label for housing. The goal is to give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

## Current Status

**Phase 1 — Shelby County, TN (Memphis) pilot: disaster resilience dimension complete.**

The data ingestion pipeline and EAL-based scoring engine are fully operational for Shelby County parcels. Future phases will extend coverage to additional counties, add remaining dimensions (energy, walkability, school quality, etc.), and deliver a React + D3 nutrition label visualization.

## What's Built

A reproducible, single-command data pipeline that ingests Shelby County parcels and enriches them through a linear chain of dimensions, where each stage consumes the previous stage's output so the final scored file carries **every** dimension (132 columns across 1,000 parcels):

- **Data ingestion** — pulls parcel and CAMA building data from the Shelby County ArcGIS REST API
- **Parcel cleaning** — normalizes ZIP/parcel IDs, drops empty/constant columns, flags acreage outliers (CAMA building attributes preserved for downstream stages)
- **FEMA flood enrichment** — queries FEMA NFHL flood zone API per parcel centroid
- **NOAA climate enrichment** — applies Memphis/Shelby County 1991–2020 climate normals (IECC zone 4A)
- **SPC tornado enrichment** — processes Storm Prediction Center historical tornado tracks with spatial intersection
- **USGS seismic hazard enrichment** — New Madrid Seismic Zone peak ground acceleration (PGA) modeling
- **Energy enrichment** — modeled residential EUI, electricity/gas use, and monthly cost from DOE/NREL ResStock archetypes + CAMA attributes
- **Infrastructure enrichment** — per-parcel infrastructure cost burden and municipal fiscal balance by density and distance-to-core
- **Health enrichment** — CDC PLACES tract-level chronic-disease prevalence joined via census-tract geocoding, with a 0–100 composite health index
- **EAL-based resilience scoring** — Expected Annual Loss model combining flood, wind, tornado, and seismic hazards, weighted by construction quality modifiers (year built, construction type, roof shape, etc.)
- **Dual grading** — national percentile grade and local (county-relative) percentile grade, A–F scale
- **Pipeline orchestrator** — `run_pipeline.py` runs all stages in dependency order with freshness-based skipping, per-stage timing/record-count reporting, individual-stage execution, and error handling
- **CLI house simulator** — interactive simulator with 20+ above-code construction features to model how building decisions affect a property's resilience score

Standalone (not part of the core scoring chain): **Census ACS socioeconomic enrichment** (`enrich_socioeconomic.py`) — tract poverty rate, median household income, and housing cost burden with a 0–100 composite index.

> **Note:** This repo is the data ingestion and scoring engine. The frontend (React + D3 nutrition label visualization) is planned for a later phase.

## Tech Stack

- Python 3.12+
- `requests` — HTTP calls to ArcGIS, FEMA, NOAA, USGS, and SPC APIs
- `pandas` — data processing and enrichment joins

## Quick Start

```bash
# Clone
git clone https://github.com/andrewwillems/housing-nutrition-label.git
cd housing-nutrition-label

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the entire pipeline end to end (ingest → clean → enrich → score)
python run_pipeline.py

# Re-run everything fresh, ignoring cached outputs
python run_pipeline.py --force

# Run a single stage, or everything from a stage onward
python run_pipeline.py --step flood
python run_pipeline.py --from energy

# Quick subset test (e.g. 25 parcels) before a full run
python run_pipeline.py --limit 25

# Preview the execution plan without running anything
python run_pipeline.py --dry-run
```

Every stage is also runnable on its own with a consistent CLI (`--input`, `--output`, `--limit`, `--dry-run`):

```bash
python shelby_ingest.py                      # → shelby_parcels_sample.csv
python clean_parcels.py                      # → shelby_parcels_clean.csv
python enrich_fema_flood.py                  # → shelby_parcels_flood.csv
python enrich_noaa_climate.py                # → shelby_parcels_climate.csv
python enrich_tornado.py                     # → shelby_parcels_tornado.csv
python enrich_seismic.py                     # → shelby_parcels_seismic.csv
python enrich_energy.py                      # → shelby_parcels_energy.csv
python enrich_infrastructure.py              # → shelby_parcels_infrastructure.csv
python enrich_health.py                      # → shelby_parcels_health.csv
python score_resilience.py                   # → shelby_parcels_scored.csv

# Standalone neighborhood context (not in the scoring chain)
python enrich_socioeconomic.py

# Interactive CLI house simulator
python simulate_house.py
```

## Data Sources

| Source | Data |
|---|---|
| [Shelby County ArcGIS](https://www.shelbycountytn.gov/) | Parcel boundaries, CAMA building attributes |
| [FEMA NFHL](https://msc.fema.gov/portal/home) | Flood zone designations |
| [NOAA Climate Data Online](https://www.ncdc.noaa.gov/cdo-web/) | Historical extreme weather events |
| [NOAA Storm Prediction Center](https://www.spc.noaa.gov/) | Historical tornado tracks |
| [USGS Unified Hazard Tool](https://earthquake.usgs.gov/hazards/interactive/) | Peak ground acceleration (seismic hazard) |
| [DOE/NREL ResStock](https://resstock.nrel.gov/) | Residential energy archetypes & EUI benchmarks |
| [CDC PLACES](https://www.cdc.gov/places/) | Tract-level chronic-disease prevalence (health index) |
| [FCC Area API](https://geo.fcc.gov/api/census/) | Lat/lon → census tract geocoding |
| [Census ACS 5-Year](https://www.census.gov/programs-surveys/acs/) | Tract poverty rate, median household income, housing cost burden |

## License

MIT — see [LICENSE](LICENSE)
