# Housing Nutrition Label

An open-source platform for scoring residential properties across multiple dimensions — disaster resilience, energy efficiency, durability, environmental footprint, infrastructure burden, health impact, socioeconomic context, and walkability — and presenting them in a clear, standardized format, like a nutrition label for housing. The goal is to give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

## Current Status

**Phase 1 complete — Shelby County, TN (Memphis) pilot with 9 scored dimensions.**

The full data ingestion → enrichment → multi-dimension scoring pipeline is operational end to end. Every Shelby County parcel in the pilot dataset carries nine scored dimensions plus a rolled-up composite score, each with both a national (absolute) and a local (percentile) letter grade. An initial **React + D3 nutrition label visualization** is now live on the project site — [housinglabel.dev/label.html](https://housinglabel.dev/label.html). Future phases will extend coverage to additional counties.

## Architecture

```
data ingestion  →  enrichment pipeline  →  multi-dimension scoring  →  CLI simulator
(ArcGIS parcels    (flood, climate, tornado,   (per-dimension 0–100        (model a hypothetical
 + CAMA building    seismic, energy, infra,     scores, dual grades,        house and see how
 attributes)        health, socio, walkability) composite roll-up)          choices change scores)
```

Each enrichment stage consumes the previous stage's output, so the final scored CSV carries **every** dimension on a single row per parcel. The pipeline is a linear, reproducible chain orchestrated by a single runner.

## Data Sources

| Source | Provides | API key |
|---|---|---|
| [Shelby County Assessor ArcGIS](https://www.shelbycountytn.gov/) | Parcel boundaries + CAMA building data | Free — no key |
| [FEMA NFHL](https://msc.fema.gov/portal/home) | Flood zone designations | Free — no key |
| [NOAA Climate Normals](https://www.ncdc.noaa.gov/cdo-web/) | Temperature, heating/cooling degree days (1991–2020) | Free — no key |
| [NOAA/DOI CMRA](https://resilience.climate.gov/) | County climate-hazard projections (LOCA/NCA4, RCP4.5–8.5) | Free — no key |
| [SPC Historical Tornadoes](https://www.spc.noaa.gov/) | Historical tornado tracks / frequency | Free — no key |
| [USGS NSHM](https://earthquake.usgs.gov/hazards/interactive/) | Seismic hazard (peak ground acceleration) — reference data | Free — no key |
| [DOE/EIA ResStock](https://resstock.nrel.gov/) | Residential energy use intensity benchmarks — reference data | Free — no key |
| [CDC PLACES](https://www.cdc.gov/places/) | Census-tract health metrics | Free — no key |
| [Census ACS](https://www.census.gov/programs-surveys/acs/) | Socioeconomic indicators (income, poverty, education) | **Requires key** ([census.gov](https://api.census.gov/data/key_signup.html)) |
| [Walk Score API](https://www.walkscore.com/professional/api.php) | Walk / transit / bike scores | **Requires key** — *active* |

> Tract geocoding for the health and socioeconomic joins uses the free [FCC Area API](https://geo.fcc.gov/api/census/) (no key).

## Scored Dimensions

Each parcel is scored on nine dimensions:

- **Disaster Resilience** — Expected Annual Loss (EAL) model combining flood, tornado, and seismic hazards, weighted by a construction-quality modifier (year built, construction type, roof shape, foundation, condition).
- **Energy Efficiency** — Energy Use Intensity (EUI) modeled from ResStock archetypes, adjusted for building vintage and construction type.
- **Durability** — component-lifespan / effective-age model blending the remaining service life of eight major building systems (structural shell, roof, HVAC, plumbing, electrical, windows, interior finishes, water heater) with the assessor's condition rating (CDU/COND), then adjusted for exterior-wall material and construction grade. Unscored for vacant / non-residential parcels with no building data.
- **Environmental Footprint** — three components blended 0.50 operational / 0.30 embodied / 0.20 water: operational CO₂e from modeled energy use × EPA eGRID2022 SRTV grid + natural-gas factors; embodied carbon from material/size (calibrated to the ~39–121 kgCO₂e/m² US single-family band) amortized over a 60-yr study period; and water use from EPA WaterSense benchmarks (with the Memphis Sand aquifer's low embedded-energy advantage). See [research/environmental-footprint-research.md](research/environmental-footprint-research.md). Unscored for vacant / non-residential parcels.
- **Infrastructure Burden** — density-based municipal cost model producing a per-parcel fiscal ratio (revenue vs. infrastructure cost) by density and distance to the urban core.
- **Health Impact** — CDC PLACES census-tract chronic-disease prevalence rolled into a 0–100 composite health index.
- **Socioeconomic** — Census ACS income, poverty, and education indicators combined into a 0–100 composite index. Falls back to a uniform placeholder when no ACS data (or API key) is available.
- **Walkability** — Walk Score API. The 0–100 Walk Score is used directly; where transit and bike scores are also available, a composite is taken (60% walk + 25% transit + 15% bike), weighted toward walkability since it matters most for daily life.
- **Climate Projections** — per-county downscaled climate-hazard projection from the NOAA/DOI [CMRA](https://resilience.climate.gov/) screening dataset (LOCA-downscaled CMIP5 / NCA4). Blends three hazard legs — extreme heat (days > 95 °F / 100 °F), heavy precipitation & flood (days > 1″, annual max 5-day total), and drought (max consecutive dry days) — into a 0–100 score, reported as a low/high band from RCP4.5 → RCP8.5 at mid-century (~2050), with the RCP4.5 value as the headline. A county aggregate (not parcel-resolution); county-uniform within the single-county pilot but a real, composite-included value, with a national-average fallback for unmapped counties. See [research/climate-projections-research.md](research/climate-projections-research.md).

## Scoring System

- **0–100 score per dimension** — higher is better.
- **Dual grading** for every dimension:
  - **National (absolute):** A ≥ 80, B ≥ 60, C ≥ 40, D ≥ 20, F < 20.
  - **Local (percentile-based):** ranked within the dataset — A = top 10%, B = next 25%, C = middle 30%, D = next 25%, F = bottom 10%.
- **Composite score** — the mean of the scored dimensions, itself carrying a national grade, a local grade, and a percentile rank.

The national/local thresholds are identical across all dimensions, so a grade means exactly the same thing whether it's read from the resilience dimension, the composite, or any other.

## Project Structure

```
housing-nutrition-label/
├── src/housing_label/          # Installable package
│   ├── config.py               # Shared constants (URLs, HTTP defaults, geo reference points)
│   ├── utils.py                # Shared helpers (HTTP, haversine, Web Mercator → WGS84)
│   ├── ingest/                 # shelby_parcels.py, clean.py
│   ├── enrich/                 # fema_flood, noaa_climate, tornado, seismic, energy,
│   │                           #   infrastructure, health, socioeconomic, walkscore
│   ├── score/                  # resilience.py, all_dimensions.py
│   └── simulate/               # house.py (CLI simulator)
├── scripts/run_pipeline.py     # Pipeline orchestrator
├── research/                   # Methodology & data-exploration write-ups
├── docs/                       # GitHub Pages site (housinglabel.dev)
│   ├── label.html              #   React + D3 interactive nutrition label
│   └── data/sample-parcels.json#   Sample data feeding the label visualization
├── tests/
├── pyproject.toml / setup.py   # Packaging
└── requirements.txt
```

Every stage script is also runnable on its own as a plain file (it resolves the
data CSVs at the repo root), so the move to a package layout doesn't change how
you invoke an individual stage.

## Pipeline

Stages run in dependency order, each consuming the previous stage's output:

```
ingest/shelby_parcels.py → ingest/clean.py → enrich/fema_flood.py → enrich/noaa_climate.py →
enrich/tornado.py → enrich/seismic.py → enrich/energy.py → enrich/infrastructure.py →
enrich/health.py → enrich/socioeconomic.py → enrich/durability.py → enrich/environmental.py → score/resilience.py → score/all_dimensions.py
```

Run the entire pipeline with the orchestrator:

```bash
python scripts/run_pipeline.py            # full run, skips stages whose outputs are fresh
python scripts/run_pipeline.py --force    # re-run everything, ignoring cached outputs
python scripts/run_pipeline.py --step flood       # run a single stage
python scripts/run_pipeline.py --from energy      # run from a stage onward
python scripts/run_pipeline.py --limit 25         # quick subset before a full run
python scripts/run_pipeline.py --dry-run          # preview the execution plan
```

The runner reports per-stage timing and record counts, skips stages whose outputs are already fresh, and supports running an individual stage or everything from a given stage onward. Every stage is also runnable on its own with a consistent CLI (`--input`, `--output`, `--limit`, `--dry-run`).

The final scored output is `shelby_parcels_final.csv` — one row per parcel with every dimension score, both grades, percentiles, and the composite.

**Walk Score enrichment** runs out of band because it is API-gated (needs `WALKSCORE_API_KEY`) and has its own resume support, so it is not re-run on every pipeline pass:

```bash
export WALKSCORE_API_KEY=your_key_here
python src/housing_label/enrich/walkscore.py    # writes shelby_parcels_enriched.csv (resumable)
```

The `score/all_dimensions.py` stage merges its output (walk / transit / bike scores) back in on `PARID`, so re-running `score_all` after enrichment picks up the walkability dimension.

## House Simulator

`src/housing_label/simulate/house.py` models a hypothetical house and reports a **full nutrition label across all nine dimensions**, letting you see how construction decisions move the needle. It supports 20+ above-code construction features (hurricane straps, sealed roof deck, metal/hip roof, tornado safe room, FORTIFIED Gold, flood elevation, ICF walls, etc.). Once the package is installed (`pip install -e .`) it's also available as the `housing-simulate` command.

The five **construction-driven** dimensions — resilience, energy efficiency, durability, environmental footprint, and infrastructure burden — are modeled offline from the house configuration (reusing the same `enrich/` models the pipeline uses). The four **location-driven** dimensions depend on where the house sits: health, socioeconomic, and walkability are fetched live for the house's lat/lon (CDC PLACES, Census ACS, and Walk Score respectively), while climate projections come from the bundled per-county CMRA crosswalk (offline, with a national-average fallback). When a live source is unavailable (no network, or no `CENSUS_API_KEY` / `WALKSCORE_API_KEY`), that dimension is reported as `N/A` and **excluded from the composite rather than filled with a placeholder**, so a strong build isn't penalized for a missing input.

```bash
python src/housing_label/simulate/house.py --preset icf-passive --lat 35.15 --lon -89.85
# or, after `pip install -e .`:
housing-simulate --preset icf-passive --lat 35.15 --lon -89.85
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

All preset fields can be overridden from the CLI (e.g. `--year-built`, `--construction`, `--flood-zone`, `--value`, `--units`, `--sqft`, `--lot-acres`). Run `python src/housing_label/simulate/house.py --help` for the full flag list.

Full-label flags:

- `--address "<US address>"` — score a house at **any US address** (geocoded via the keyless
  Census geocoder to lat/lon + county + census tract). `--lat/--lon` also work anywhere.
- `--json` — emit the complete nutrition label (all dimensions, composite, metrics) as JSON.
- `--no-fetch` — skip the live location lookups; leave health/socioeconomic/walkability unscored.
- `--health-index` / `--socioeconomic-index` / `--walk-score` — supply a location dimension directly instead of fetching it.

**Any-location support:** the resolved location drives the location-dependent dimensions —
health & socioeconomic are ranked within the address's *own county*; energy is scaled by the
location's IECC climate zone; the flood zone is auto-derived from FEMA NFHL; **Disaster
Resilience uses live USGS seismic hazard** (2%/50yr PGA, with a bundled national fallback grid)
and the **national SPC tornado record** within 25 mi of the point. Infrastructure Burden uses a
national-average cost model outside Shelby (flagged as an estimate), and Environmental uses the
location's **eGRID2022 subregion** grid-carbon factor (a bundled county→subregion crosswalk;
counties that can't be mapped fall back to the US-average factor).

The website nutrition label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) is generated from this simulator — regenerate its data with `python scripts/generate_label_data.py` (writes [`docs/data/sample-parcels.json`](docs/data/sample-parcels.json)).

## Quick Start

```bash
git clone https://github.com/compbiolover/housing-nutrition-label.git
cd housing-nutrition-label
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                   # optional: installs the housing_label package + console scripts
python scripts/run_pipeline.py
```

## Address-search API

The static site can score **any US address** via a small HTTP wrapper around the simulator
(same scoring path, no model drift):

```bash
pip install -e ".[api]"               # FastAPI + uvicorn
export CENSUS_API_KEY=... WALKSCORE_API_KEY=...   # optional, for the full 8 dimensions
housing-api                            # GET /label?address=... (or ?lat=&lon=), GET /suggest?q=..., GET /healthz
```

The search bar also has **address autocomplete**: `GET /suggest?q=...` returns US
`[{label, lat, lon}]`, proxied server-side (visitors' keystrokes never reach a third party
directly). By default it uses the keyless [Photon](https://photon.komoot.io) geocoder
(`PHOTON_URL` to self-host); set `GEOAPIFY_API_KEY` ([free tier](https://www.geoapify.com),
EU/GDPR) for sharper US ranking, with automatic Photon fallback. Keys stay server-side.

Deploy it anywhere that runs Python (GitHub Pages can't host it). The repo ships a
[`render.yaml`](render.yaml) Blueprint and a [`Dockerfile`](Dockerfile) (Fly / Cloud Run /
Railway / any container host). CORS is locked to `https://housinglabel.dev` by default —
override via the `ALLOWED_ORIGINS` env var. Then point the Examples-page search bar at the
deployed URL with `?api=https://your-api-host` or `window.HOUSING_LABEL_API`. See
[`docs/setup.html`](docs/setup.html) → *Address-search API*.

## Tech Stack

- **Python 3.x**
- [`requests`](https://requests.readthedocs.io/) — HTTP calls to ArcGIS, FEMA, NOAA, USGS, SPC, CDC, FCC, and Census APIs
- [`pandas`](https://pandas.pydata.org/) (+ `numpy`) — data processing, enrichment joins, and scoring

## Roadmap

- **Rust scoring engine** — port the hot scoring path for performance at scale
- **API layer** — serve scores and grades over HTTP for third-party integration
- **Finer climate resolution (sub-county)** — sample the LOCA2 ~6 km grid at the parcel lat/lon as a network-gated live refresh. The climate lookup is already resolution-aware (tract → county → national, drop-in for a finer crosswalk), but CMRA's *tract* layer was found to carry no sub-county signal — it just broadcasts the county value — so genuinely finer data must come from grid sampling, not that layer.
- **True Fire Weather Index** — add the Argonne ClimRR FWI (12 km) for the fire/drought leg, replacing the consecutive-dry-days stand-in (needs a spatial join + a reachable, keyless source)

**Shipped:**
- ~~Extend the climate layer to census tracts (CMRA tract layer)~~ → the climate lookup is now **resolution-aware** (`climate_projection_for_tract`: tract → county → national average, each result tagged with its `geo_level`), with a reproducible opt-in tract build. CMRA's tract layer was empirically found to broadcast the county value onto every tract (no sub-county signal), so it is deliberately **not bundled** — the plumbing is ready for a genuinely finer dataset instead. See [research/climate-projections-research.md](research/climate-projections-research.md).
- ~~Per-parcel climate projections — replace the uniform climate placeholder with downscaled climate-projection data~~ → the **Climate Projections** dimension is now a real per-county score from CMRA (LOCA/NCA4) downscaled projections, with an RCP4.5→8.5 mid-century band and a reproducible build script ([`scripts/build_climate_projections.py`](scripts/build_climate_projections.py)). Design notes in [research/climate-projections-research.md](research/climate-projections-research.md).
- ~~Frontend visualization — React + D3 nutrition label UI~~ → an initial version is live at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) ([`docs/label.html`](docs/label.html)). It renders the scored dimensions as an at-a-glance label with a switchable set of construction profiles, served statically with no build step (React + D3 loaded from CDN).

## License

MIT — see [LICENSE](LICENSE)
