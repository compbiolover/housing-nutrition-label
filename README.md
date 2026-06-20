# Housing Nutrition Label

An open-source platform for scoring residential properties across multiple dimensions — disaster resilience, energy efficiency, infrastructure burden, health impact, and socioeconomic context — and presenting them in a clear, standardized format, like a nutrition label for housing. The goal is to give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

## Current Status

**Phase 1 complete — Shelby County, TN (Memphis) pilot with 5 scored dimensions.**

The full data ingestion → enrichment → multi-dimension scoring pipeline is operational end to end. Every Shelby County parcel in the pilot dataset carries five scored dimensions plus a rolled-up composite score, each with both a national (absolute) and a local (percentile) letter grade. Future phases will extend coverage to additional counties, add remaining dimensions (durability, environmental footprint, walkability), and deliver a React + D3 nutrition label visualization.

## Architecture

```
data ingestion  →  enrichment pipeline  →  multi-dimension scoring  →  CLI simulator
(ArcGIS parcels    (flood, climate, tornado,   (per-dimension 0–100        (model a hypothetical
 + CAMA building    seismic, energy, infra,     scores, dual grades,        house and see how
 attributes)        health, socioeconomic)      composite roll-up)          choices change scores)
```

Each enrichment stage consumes the previous stage's output, so the final scored CSV carries **every** dimension on a single row per parcel. The pipeline is a linear, reproducible chain orchestrated by a single runner.

## Data Sources

| Source | Provides | API key |
|---|---|---|
| [Shelby County Assessor ArcGIS](https://www.shelbycountytn.gov/) | Parcel boundaries + CAMA building data | Free — no key |
| [FEMA NFHL](https://msc.fema.gov/portal/home) | Flood zone designations | Free — no key |
| [NOAA Climate Normals](https://www.ncdc.noaa.gov/cdo-web/) | Temperature, heating/cooling degree days (1991–2020) | Free — no key |
| [SPC Historical Tornadoes](https://www.spc.noaa.gov/) | Historical tornado tracks / frequency | Free — no key |
| [USGS NSHM](https://earthquake.usgs.gov/hazards/interactive/) | Seismic hazard (peak ground acceleration) — reference data | Free — no key |
| [DOE/EIA ResStock](https://resstock.nrel.gov/) | Residential energy use intensity benchmarks — reference data | Free — no key |
| [CDC PLACES](https://www.cdc.gov/places/) | Census-tract health metrics | Free — no key |
| [Census ACS](https://www.census.gov/programs-surveys/acs/) | Socioeconomic indicators (income, poverty, education) | **Requires key** ([census.gov](https://api.census.gov/data/key_signup.html)) |
| [Walk Score API](https://www.walkscore.com/professional/api.php) | Walkability score | **Requires key** — script ready, *not yet integrated* |

> Tract geocoding for the health and socioeconomic joins uses the free [FCC Area API](https://geo.fcc.gov/api/census/) (no key).

## Scored Dimensions

Each parcel is scored on five dimensions (plus a climate placeholder):

- **Disaster Resilience** — Expected Annual Loss (EAL) model combining flood, tornado, and seismic hazards, weighted by a construction-quality modifier (year built, construction type, roof shape, foundation, condition).
- **Energy Efficiency** — Energy Use Intensity (EUI) modeled from ResStock archetypes, adjusted for building vintage and construction type.
- **Infrastructure Burden** — density-based municipal cost model producing a per-parcel fiscal ratio (revenue vs. infrastructure cost) by density and distance to the urban core.
- **Health Impact** — CDC PLACES census-tract chronic-disease prevalence rolled into a 0–100 composite health index.
- **Socioeconomic** — Census ACS income, poverty, and education indicators combined into a 0–100 composite index. Falls back to a uniform placeholder when no ACS data (or API key) is available.
- **Climate Projections** *(placeholder)* — uniform across the single-county pilot; excluded from the composite until multi-region data is available.

## Scoring System

- **0–100 score per dimension** — higher is better.
- **Dual grading** for every dimension:
  - **National (absolute):** A ≥ 80, B ≥ 60, C ≥ 40, D ≥ 20, F < 20.
  - **Local (percentile-based):** ranked within the dataset — A = top 10%, B = next 25%, C = middle 30%, D = next 25%, F = bottom 10%.
- **Composite score** — the mean of the scored dimensions (excluding the climate placeholder), itself carrying a national grade, a local grade, and a percentile rank.

The national/local thresholds are identical across all dimensions, so a grade means exactly the same thing whether it's read from the resilience dimension, the composite, or any other.

## Pipeline

Stages run in dependency order, each consuming the previous stage's output:

```
shelby_ingest.py → clean_parcels.py → enrich_fema_flood.py → enrich_noaa_climate.py →
enrich_tornado.py → enrich_seismic.py → enrich_energy.py → enrich_infrastructure.py →
enrich_health.py → enrich_socioeconomic.py → score_resilience.py → score_all_dimensions.py
```

Run the entire pipeline with the orchestrator:

```bash
python run_pipeline.py            # full run, skips stages whose outputs are fresh
python run_pipeline.py --force    # re-run everything, ignoring cached outputs
python run_pipeline.py --step flood       # run a single stage
python run_pipeline.py --from energy      # run from a stage onward
python run_pipeline.py --limit 25         # quick subset before a full run
python run_pipeline.py --dry-run          # preview the execution plan
```

The runner reports per-stage timing and record counts, skips stages whose outputs are already fresh, and supports running an individual stage or everything from a given stage onward. Every stage is also runnable on its own with a consistent CLI (`--input`, `--output`, `--limit`, `--dry-run`).

The final scored output is `shelby_parcels_final.csv` — one row per parcel with every dimension score, both grades, percentiles, and the composite.

## House Simulator

`simulate_house.py` models a hypothetical house and reports its resilience score, letting you see how construction decisions move the needle. It supports 20+ above-code construction features (hurricane straps, sealed roof deck, metal/hip roof, tornado safe room, FORTIFIED Gold, flood elevation, ICF walls, etc.).

```bash
python simulate_house.py --preset icf-passive --lat 35.15 --lon -89.85
```

Available presets:

- `baseline` — typical 2000s suburban tract home
- `premium` — high-end new build (solid brick, excellent condition, post-IBC)
- `icf-passive` — ICF passive house with the full resilience package
- `worst-case` — pre-1950 wood frame, full basement, AE flood zone, poor condition
- `fortified-gold` — 2026 frame build with IBHS FORTIFIED Gold + metal roof + sealed deck
- `duplex` — 2026 brick duplex (2 units × 1,200 sqft, 0.15 ac, excellent condition)
- `quadplex` — 2026 brick quadplex (4 units × 900 sqft, 0.20 ac, excellent condition)
- `icf-quadplex` — 2026 ICF quadplex (4 units × 1,000 sqft, 0.20 ac) with solar, passive house, hurricane straps + hip roof

All preset fields can be overridden from the CLI (e.g. `--year-built`, `--construction`, `--flood-zone`, `--value`, `--units`, `--sqft`, `--lot-acres`). Run `python simulate_house.py --help` for the full flag list.

## Quick Start

```bash
git clone https://github.com/compbiolover/housing-nutrition-label.git
cd housing-nutrition-label
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_pipeline.py
```

## Tech Stack

- **Python 3.x**
- [`requests`](https://requests.readthedocs.io/) — HTTP calls to ArcGIS, FEMA, NOAA, USGS, SPC, CDC, FCC, and Census APIs
- [`pandas`](https://pandas.pydata.org/) (+ `numpy`) — data processing, enrichment joins, and scoring

## Roadmap

- **Walk Score integration** — wire the existing `enrich_walkscore.py` into the pipeline (requires API key)
- **Durability dimension** — material lifespan, maintenance burden, expected component replacement
- **Environmental footprint** — embodied carbon, operational emissions, water use
- **Frontend visualization** — React + D3 nutrition label UI
- **Rust scoring engine** — port the hot scoring path for performance at scale
- **API layer** — serve scores and grades over HTTP for third-party integration

## License

MIT — see [LICENSE](LICENSE)
