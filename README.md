# Housing Nutrition Label

An open-source platform for scoring residential properties across multiple dimensions — disaster resilience, energy efficiency, walkability, and more — presented in a clear, standardized format, like a nutrition label for housing. The goal is to give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

## Current Status

**Phase 1 — Shelby County, TN (Memphis) pilot: disaster resilience dimension complete.**

The data ingestion pipeline and EAL-based scoring engine are fully operational for Shelby County parcels. Future phases will extend coverage to additional counties, add remaining dimensions (energy, walkability, school quality, etc.), and deliver a React + D3 nutrition label visualization.

## What's Built

- **Data ingestion** — pulls parcel and CAMA building data from the Shelby County ArcGIS REST API
- **FEMA flood enrichment** — queries FEMA NFHL flood zone API per parcel centroid
- **NOAA climate enrichment** — fetches historical extreme weather data from the NOAA Climate Data Online API
- **SPC tornado enrichment** — processes Storm Prediction Center historical tornado tracks with spatial intersection
- **USGS seismic hazard enrichment** — pulls peak ground acceleration values from the USGS Unified Hazard Tool API
- **EAL-based resilience scoring** — Expected Annual Loss model combining flood, wind, tornado, and seismic hazards, weighted by construction quality modifiers (year built, construction type, roof shape, etc.)
- **Dual grading** — national percentile grade and local (county-relative) percentile grade, A–F scale
- **CLI house simulator** — interactive simulator with 20+ above-code construction features to model how building decisions affect a property's resilience score

> **Note:** This repo is the data ingestion and scoring engine. The frontend (React + D3 nutrition label visualization) is planned for Phase 4.

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

# Ingest Shelby County parcel data
python shelby_ingest.py

# Enrich with hazard data (run in order)
python enrich_fema_flood.py
python enrich_noaa_climate.py
python enrich_tornado.py
python enrich_seismic.py

# Score parcels
python score_resilience.py

# Run the CLI house simulator
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

## License

MIT — see [LICENSE](LICENSE)
