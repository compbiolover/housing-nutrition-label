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
| [USGS CMIP6-LOCA2](https://doi.org/10.5066/P13OV6GY) | Sub-county climate-hazard projections (CMIP6-LOCA2 WMMM ~6 km, SSP2-4.5–5-8.5) | Free — no key |
| [Argonne ClimRR](https://www.anl.gov/ccrds/climrr) | Projected Fire Weather Index (12 km, RCP8.5) — the Climate Projections fire leg | Free — no key (bulk CSVs) |
| [SPC Historical Tornadoes](https://www.spc.noaa.gov/) | Historical tornado tracks / frequency | Free — no key |
| [USGS NSHM](https://earthquake.usgs.gov/hazards/interactive/) | Seismic hazard (peak ground acceleration) — reference data | Free — no key |
| [FEMA National Risk Index](https://hazards.fema.gov/nri/) | Wildfire expected-annual-loss (the location-based fire peril) | Free — no key |
| [Census of Governments](https://www.census.gov/programs-surveys/cog.html) + [Population Estimates](https://www.census.gov/programs-surveys/popest.html) | Per-county local-government spending by function (Infrastructure Burden cost calibration) | Free — no key (bulk files) |
| [Census ACS 5-yr Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Per-county effective property-tax rate (Infrastructure Burden revenue calibration) | Free — no key (bulk table file) |
| [DOE/EIA ResStock](https://resstock.nrel.gov/) | Residential energy use intensity benchmarks — reference data | Free — no key |
| [CDC PLACES](https://www.cdc.gov/places/) | Census-tract health metrics | Free — no key |
| [Census ACS](https://www.census.gov/programs-surveys/acs/) | Socioeconomic indicators (income, poverty, education) | **Requires key** ([census.gov](https://api.census.gov/data/key_signup.html)) |
| [Walk Score API](https://www.walkscore.com/professional/api.php) | Walk / transit / bike scores | **Requires key** — *active* |

> Tract geocoding for the health and socioeconomic joins uses the free [FCC Area API](https://geo.fcc.gov/api/census/) (no key).

## Scored Dimensions

Each parcel is scored on nine dimensions:

- **Disaster Resilience** — Expected Annual Loss (EAL) model combining flood, tornado, seismic, and fire hazards, weighted by a construction-quality modifier (year built, construction type, roof shape, foundation, condition). The fire peril blends a national-average structural/electrical fire baseline with the location's FEMA National Risk Index **wildfire** EAL, so it is genuinely location-aware (near-zero in Memphis, materially higher in the fire-prone West).
- **Energy Efficiency** — Energy Use Intensity (EUI) modeled from ResStock archetypes, adjusted for building vintage and construction type.
- **Durability** — component-lifespan / effective-age model blending the remaining service life of eight major building systems (structural shell, roof, HVAC, plumbing, electrical, windows, interior finishes, water heater) with the assessor's condition rating (CDU/COND), then adjusted for exterior-wall material and construction grade. Unscored for vacant / non-residential parcels with no building data.
- **Environmental Footprint** — three components blended 0.50 operational / 0.30 embodied / 0.20 water: operational CO₂e from modeled energy use × EPA eGRID2022 SRTV grid + natural-gas factors; embodied carbon from material/size (calibrated to the ~39–121 kgCO₂e/m² US single-family band) amortized over a 60-yr study period; and water use from EPA WaterSense benchmarks (with the Memphis Sand aquifer's low embedded-energy advantage). See [research/environmental-footprint-research.md](research/environmental-footprint-research.md). Unscored for vacant / non-residential parcels.
- **Infrastructure Burden** — density-based municipal cost model producing a per-parcel fiscal ratio (revenue vs. infrastructure cost) by density and distance to the urban core. The per-function cost levels are calibrated to each county's actual local-government spending (Census of Governments per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), so the estimate reflects local fiscal reality rather than reusing the Memphis pilot everywhere. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).
- **Health Impact** — CDC PLACES census-tract chronic-disease prevalence rolled into a 0–100 composite health index.
- **Socioeconomic** — Census ACS income, poverty, and education indicators combined into a 0–100 composite index. Falls back to a uniform placeholder when no ACS data (or API key) is available.
- **Walkability** — Walk Score API. The 0–100 Walk Score is used directly; where transit and bike scores are also available, a composite is taken (60% walk + 25% transit + 15% bike), weighted toward walkability since it matters most for daily life.
- **Climate Projections** — sub-county downscaled climate-hazard projection from the USGS [CMIP6-LOCA2](https://doi.org/10.5066/P13OV6GY) Weighted Multi-Model Mean (~6 km grid, sampled at each census tract's internal point; county = the mean of its tracts). Blends four hazard legs — extreme heat (days > 95 °F / 100 °F), heavy precipitation & flood (days > 1″, annual max 5-day total), drought (max consecutive dry days), and **wildfire (Fire Weather Index)** — into a 0–100 score, reported as a low/high band from SSP2-4.5 → SSP5-8.5 at mid-century (2040–2069), with the SSP2-4.5 value as the headline. The fire leg is Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km 95th-percentile **Fire Weather Index** (RCP8.5), spatially joined to census geography by parsing the ClimRR grid shapefile and sampling the nearest cell at each tract's internal point; because ClimRR publishes a single RCP8.5 pathway, its mid-century FWI drives both bands (no scenario spread). Fire only *enriches* the composite where covered — the LOCA2 heat/precip/drought legs stay the required backbone — so every CONUS place carries all four legs, while a place outside the CONUS grid (Alaska, Hawaii, Puerto Rico lack the core legs too) falls back to a coarser geography rather than being scored on fire alone. A tract internal-point sample (not parcel-resolution) but a real, composite-included value, with tract → county → national-average fallback. See [research/climate-projections-research.md](research/climate-projections-research.md).

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
│   ├── label-core.js           #   Shared label renderer (used by all pages)
│   ├── label-core.css          #   Shared label styles
│   ├── index.html              #   Home page — address search (live API)
│   ├── label.html              #   Construction-profile label (live API /presets)
│   └── examples.html           #   Preset examples + address search
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

The five **construction-driven** dimensions — resilience, energy efficiency, durability, environmental footprint, and infrastructure burden — are modeled offline from the house configuration (reusing the same `enrich/` models the pipeline uses). The four **location-driven** dimensions depend on where the house sits: health, socioeconomic, and walkability are fetched live for the house's lat/lon (CDC PLACES, Census ACS, and Walk Score respectively), while climate projections come from the bundled CMIP6-LOCA2 tract/county crosswalk (offline, with a tract → county → national-average fallback). When a live source is unavailable (no network, or no `CENSUS_API_KEY` / `WALKSCORE_API_KEY`), that dimension is reported as `N/A` and **excluded from the composite rather than filled with a placeholder**, so a strong build isn't penalized for a missing input.

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
Resilience uses live USGS seismic hazard** (2%/50yr PGA, with a bundled national fallback grid),
the **national SPC tornado record** within 25 mi of the point, and the location's **FEMA National
Risk Index wildfire** EAL (a bundled national tract/county crosswalk) for the fire peril. Infrastructure Burden
calibrates its cost curves to the location's county local-government spending (a bundled Census of Governments
crosswalk) and its property-tax revenue to the county's effective rate (a bundled Census ACS crosswalk), each
with a national-average fallback for unmapped counties, and Environmental uses the
location's **eGRID2022 subregion** grid-carbon factor (a bundled county→subregion crosswalk;
counties that can't be mapped fall back to the US-average factor).

The website nutrition label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) is scored live by the HTTP API (this simulator behind `/label` and `/presets`) and rendered by the shared [`docs/label-core.js`](docs/label-core.js) — the same renderer the home-page address search uses, so there is no static snapshot to regenerate.

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

- **Methodology "show-your-math" drill-down** — expandable per-dimension provenance on the label (sources, the EAL/BRM breakdown, the exact eGRID subregion, the calibrating county's spending), so a curious user can trace any score to its inputs.
- **Address input on the label page** — the Label page renderer is now API-fed and `/presets` already accepts an `address=`/`lat,lon`, so letting a visitor score their own address on that page (instead of the fixed Cooper-Young presets) is a small remaining UI step.
- **Rust scoring engine** — port the hot scoring path for performance at scale

**Shipped:**
- ~~Unify the label renderers behind one shared module, fed by the live API~~ → the three bespoke label implementations (the React + D3 `label.html` reading a static `sample-parcels.json`, plus the plain-JS renderers duplicated across `index.html` and `examples.html`) are replaced by **one dependency-free renderer, [`docs/label-core.js`](docs/label-core.js) + [`docs/label-core.css`](docs/label-core.css)**, used by every page. All pages are now scored **live by the same HTTP API**: the home page and examples use `/label`, and the Label page fetches a new **`GET /presets`** endpoint that scores the standard construction profiles at one location in a single response (one geocode + one location fetch total). The confidence rubric stays the single Python source of truth in [`src/housing_label/confidence.py`](src/housing_label/confidence.py); `label-core.js` only renders it. `label.html` dropped its React/D3 + Babel CDN dependencies (plain JS now), and the static `docs/data/sample-parcels.json` snapshot and its `generate_label_data.py` generator were removed — there is no snapshot to drift.
- **Per-dimension uncertainty / confidence display** — surfaced the uncertainty the models already carry as a neutral **confidence dot** (High/Moderate/Low) per dimension, a coverage-penalized **composite confidence** line, and an honest **climate scenario-band whisker**, on a channel kept deliberately separate from the grade. See [research/uncertainty-confidence-research.md](research/uncertainty-confidence-research.md).
- ~~"Cost over a mortgage" (lifetime cost of ownership) + comparison mode~~ → the label now present-values the two dollar-defensible flows — modeled **energy cost** and **expected annual disaster loss** — over a 30-year mortgage and shows the result as a **comparative delta vs. a typical comparable** at the same location (never an absolute "total cost"), mirroring the EPA fuel-economy sticker's "you save $X over 5 years" construction. Constant (real) dollars, no real escalation, discounted at ~4% real (homeowner mortgage opportunity cost) with an OMB ~2% social-rate band; the headline is rounded to 2 significant figures. A new **Compare (A/B)** mode puts two profiles side by side with a per-dimension delta table. The strip is fed by numeric `cost` fields in the label payload; no scoring/model change was required. Full methodology, discount-rate/escalation citations, and the dollarizable-vs-qualitative dimension audit: [research/lifetime-cost-research.md](research/lifetime-cost-research.md).
- ~~True Fire Weather Index — add the Argonne ClimRR FWI (12 km) for the *Climate Projections* fire leg, replacing the consecutive-dry-days stand-in for fire~~ → the **Climate Projections** dimension now carries a genuine **wildfire (Fire Weather Index)** leg from Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km dynamically-downscaled projections (95th-percentile FWI, RCP8.5, mid-century). The keyless ClimRR CSVs (grid keyed by `Crossmodel` cell id) are joined to census geography by parsing the companion grid **shapefile** in pure stdlib — bbox centre → Web Mercator → WGS84 (same formula as `utils.webmercator_to_wgs84`) — and sampling the nearest cell at each tract's internal point (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source fwi`](scripts/build_climate_projections.py), which augments the existing crosswalks in place with `fire_fwi_{hist,low,high}`. ClimRR publishes a single RCP8.5 pathway, so the mid-century FWI drives both bands (no scenario spread). Fire is an *optional enrichment* on top of the required LOCA2 core (heat/precip/drought): where present it adds a fourth leg (every CONUS place), and where a CONUS place lacks it the composite is the mean of the core legs — but a place outside the CONUS LOCA2 grid (Alaska/Hawaii/Puerto Rico) lacks the core legs too and falls back to a coarser geography rather than being scored on fire alone. This is the forward-looking climate-fire signal; the *present-day* wildfire hazard ships separately in Disaster Resilience (below). The earlier "spatial-join needs a geospatial library / the portal isn't reachable from CI" blocker was resolved by the stdlib shapefile parse over the Box-hosted CSVs. See [research/climate-projections-research.md](research/climate-projections-research.md).
- ~~Locally calibrate Infrastructure Burden (replace the Memphis-everywhere cost model)~~ → the per-function cost levels are now calibrated to each county's **actual local-government spending** from the **Census of Governments** (2022 Individual Unit File — the most recent full count: per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), normalized to the Shelby pilot so the pilot is unchanged while every other county scales by its real spending ratio (e.g. LA County ~2.0× roads, ~2.6× water/sewer). Bundled national crosswalk (`govfinance_county.csv`, built by [`scripts/build_govfinance.py`](scripts/build_govfinance.py)); county → national-average fallback via [`data/govfinance.py`](src/housing_label/data/govfinance.py). Phase 1 of the locally-calibrated-infrastructure roadmap (parcel→special-district mapping remains). See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).
- ~~Auto-fill home value + reconcile school scope in Infrastructure Burden~~ → two fiscal-ratio accuracy fixes. **(1) Auto-fill value:** when no home value is supplied, it now defaults to the **county median** (Census ACS) instead of the construction profile's flat default, so the revenue side (and dollar EALs) reflect the local market — e.g. a Manhattan address no longer scores as if the home were worth $250k. **(2) School-scope reconciliation:** the revenue side now **nets out the school-district share** of property tax (Census of Governments; ~41% nationally, with a national-average fallback for dependent-school counties that fund schools through general government), so it's like-for-like with the school-excluded cost side. Both sides are now non-school; the national median fiscal ratio drops to ~0.31 and the breakpoints were re-calibrated accordingly. This corrects places like high-property-tax suburbs that looked municipally self-sustaining only because their (school-heavy) taxes were counted in full.
- ~~Re-anchor the Infrastructure Burden score breakpoints to a national distribution~~ → once cost and revenue were localized per county, the fiscal-ratio→score breakpoints (which had been anchored to the Shelby pilot) were re-anchored to the **national distribution** of fiscal ratios — a population-weighted reference over U.S. counties × residential-density archetypes ([`scripts/calibrate_infra_breakpoints.py`](scripts/calibrate_infra_breakpoints.py)) — so a score now tracks national percentile rank (A = top ~20% … F = bottom ~20%). The density gradient (sprawl scores worse) is preserved; the thresholds are just nationally meaningful now.
- ~~Locally calibrate the Infrastructure Burden revenue side (per-county property-tax rate)~~ → the fiscal ratio's revenue side now uses each county's **effective property-tax rate** (median real-estate taxes ÷ median home value) from the **Census ACS** 2022 5-year table-based Summary File, replacing the single national rate applied everywhere — effective rates vary ~10× nationally (~0.3%–3%). Keyless bundled crosswalk (`property_tax_county.csv`, built by [`scripts/build_property_tax.py`](scripts/build_property_tax.py)); county → national-average fallback via [`data/propertytax.py`](src/housing_label/data/propertytax.py). Phase 2 of the roadmap; sub-county/per-jurisdiction millage (state DOR tables) remains a future precision refinement. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).
- ~~Add the "fire" hazard to the Disaster Resilience EAL pipeline~~ → "fire" is now a real, **location-based** summed hazard alongside flood/tornado/seismic. It combines a national-average structural/electrical fire baseline with the **FEMA National Risk Index wildfire** EAL rate (`WFIR_AFREQ × WFIR_HLRB`), resolved tract → county → national from a bundled national crosswalk (`nri_wildfire.csv` + `nri_wildfire_tracts.csv.gz`, built by [`scripts/build_nri_wildfire.py`](scripts/build_nri_wildfire.py)). Both the offline Shelby pipeline ([`enrich/fire.py`](src/housing_label/enrich/fire.py) + [`score/resilience.py`](src/housing_label/score/resilience.py)) and the live API ([`data/wildfire.py`](src/housing_label/data/wildfire.py) via the resolved location) share one fire model; a fire-specific Building Resilience Modifier (wiring era × wall-material combustibility × condition) adjusts it. Previously fire existed only as a flat national constant in the CLI simulator and was absent from the parcel pipeline entirely.
- ~~Finer climate resolution (sub-county)~~ → the **Climate Projections** dimension now carries real **sub-county (census-tract)** values from the USGS **CMIP6-LOCA2** Weighted Multi-Model Mean (~6 km), sampled at each tract's internal point and bundled as `climate_projections_tracts.csv.gz` (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source loca2`](scripts/build_climate_projections.py) (SSP2-4.5/5-8.5 mid-century 2040–2069); breakpoints re-anchored to the CMIP6 national distribution. Tracts within a large county now genuinely differ — the inverse of CMRA's tract layer, which broadcast the county value. Live point sampling was ruled out (no keyless LOCA2 point API; single-model point samples aren't defensible), so the signal comes from an offline ensemble-mean grid build.
- ~~Extend the climate layer to census tracts (CMRA tract layer)~~ → the climate lookup was made **resolution-aware** (`climate_projection_for_tract`: tract → county → national average, each result tagged with its `geo_level`). CMRA's tract layer was empirically found to broadcast the county value onto every tract (no sub-county signal), so the genuinely finer signal was sourced from CMIP6-LOCA2 instead (above). See [research/climate-projections-research.md](research/climate-projections-research.md).
- ~~Per-parcel climate projections — replace the uniform climate placeholder with downscaled climate-projection data~~ → the **Climate Projections** dimension is now a real per-county score from CMRA (LOCA/NCA4) downscaled projections, with an RCP4.5→8.5 mid-century band and a reproducible build script ([`scripts/build_climate_projections.py`](scripts/build_climate_projections.py)). Design notes in [research/climate-projections-research.md](research/climate-projections-research.md).
- ~~Frontend visualization — React + D3 nutrition label UI~~ → an initial version is live at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) ([`docs/label.html`](docs/label.html)). It renders the scored dimensions as an at-a-glance label with a switchable set of construction profiles, served statically with no build step (React + D3 loaded from CDN).

## License

MIT — see [LICENSE](LICENSE)
