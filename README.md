# Housing Nutrition Label

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Site](https://img.shields.io/badge/live-housinglabel.dev-2e7d32)](https://housinglabel.dev/label.html)
[![Status](https://img.shields.io/badge/phase%201-complete-brightgreen)](#current-status)

An open-source platform for scoring residential properties across multiple dimensions — disaster resilience, energy efficiency, durability, environmental footprint, infrastructure burden, health impact, socioeconomic context, walkability, and climate projections — and presenting them in a clear, standardized format, **like a nutrition label for housing**.

The goal: give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

**➡️ See a live label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html)**

<details>
<summary><strong>📖 Table of contents</strong></summary>

- [Current Status](#current-status)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Scored Dimensions](#scored-dimensions)
- [Scoring System](#scoring-system)
- [Data Sources](#data-sources)
- [House Simulator](#house-simulator)
- [Address-search API](#address-search-api)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Roadmap](#roadmap)
- [License](#license)

</details>

## Current Status

> **Phase 1 complete — Shelby County, TN (Memphis) pilot with 9 scored dimensions.**

Enter any U.S. residential address (or lat/lon) and it scores nine dimensions plus a rolled-up composite, each with a national (absolute) letter grade and a national percentile, from bundled offline reference data plus a few keyless government APIs. An **interactive nutrition label visualization** is live on the project site — [housinglabel.dev/label.html](https://housinglabel.dev/label.html) — backed by the same scoring API.

## Quick Start

```bash
git clone https://github.com/compbiolover/housing-nutrition-label.git
cd housing-nutrition-label
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                   # installs the housing_label package + console scripts
housing-simulate --preset icf-passive --lat 35.15 --lon -89.85   # score a house at a location
```

## Architecture

```
address / lat-lon  →  location resolve   →  per-dimension models   →  nutrition label
(geocode +            (climate zone, grid,   (9 dimensions, 0–100      (national grade +
 bundled county/       hazards, structure)    scores + composite)       percentile, API/CLI)
 tract lookups)
```

The nine dimensions are scored per address on demand — the five construction-driven ones from the house configuration and the four location-driven ones from the resolved location — using the shared `enrich/` model libraries. There is no offline batch step: the same models back both the CLI simulator and the address-search API.

## Scored Dimensions

Each parcel is scored on **nine dimensions**, each 0–100 (higher is better). Expand any dimension for its methodology.

<details>
<summary><strong>🛡️ Disaster Resilience</strong> — flood + tornado + seismic + fire EAL</summary>

Expected Annual Loss (EAL) model combining flood, tornado, seismic, and fire hazards, weighted by a construction-quality modifier (year built, construction type, roof shape, foundation, condition). The fire peril blends a national-average structural/electrical fire baseline with the location's FEMA National Risk Index **wildfire** EAL, so it is genuinely location-aware (near-zero in Memphis, materially higher in the fire-prone West).

</details>

<details>
<summary><strong>⚡ Energy Efficiency</strong> — modeled Energy Use Intensity</summary>

Energy Use Intensity (EUI) from NREL ResStock 2024 simulation medians by building type (single-family, multi-family, mobile/manufactured), climate zone, and vintage, adjusted for the home's size, construction, and (ResStock-derived) foundation/heating-system factors.

</details>

<details>
<summary><strong>🏗️ Durability</strong> — component-lifespan / effective-age model</summary>

Component-lifespan / effective-age model blending the remaining service life of eight major building systems (structural shell, roof, HVAC, plumbing, electrical, windows, interior finishes, water heater) with the assessor's condition rating (CDU/COND), then adjusted for exterior-wall material and construction grade. Unscored for vacant / non-residential parcels with no building data.

</details>

<details>
<summary><strong>🌱 Environmental Footprint</strong> — operational + embodied carbon + water</summary>

Three components blended 0.50 operational / 0.30 embodied / 0.20 water: operational CO₂e from modeled energy use × EPA eGRID2023 Rev 2 grid **average** + natural-gas factors, with solar/efficiency-avoided kWh credited at the NREL Cambium 2023 LRMER **marginal** rate (what actually turns off long-run; CONUS only); embodied carbon from material/size (calibrated to the ~39–121 kgCO₂e/m² US single-family band) amortized over a 60-yr study period; and water use from EPA WaterSense benchmarks (with the Memphis Sand aquifer's low embedded-energy advantage). See [research/environmental-footprint-research.md](research/environmental-footprint-research.md). Unscored for vacant / non-residential parcels.

</details>

<details>
<summary><strong>🏙️ Infrastructure Burden</strong> — density-based municipal fiscal ratio</summary>

Density-based municipal cost model producing a per-parcel fiscal ratio (revenue vs. infrastructure cost) by density and distance to the urban core. The per-function cost levels are calibrated to each county's actual local-government spending (Census of Governments per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), so the estimate reflects local fiscal reality rather than reusing the Memphis pilot everywhere. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary><strong>❤️ Health Impact</strong> — CDC PLACES chronic-disease prevalence</summary>

CDC PLACES census-tract chronic-disease prevalence (7 measures) scored against the **full national distribution of US census tracts** (population-weighted), not ranked within the local county — so a health score means the same thing in Memphis and in Denver. Bundled offline and keyless ([`data/health.py`](src/housing_label/data/health.py), built by [`scripts/build_health_ref.py`](scripts/build_health_ref.py)); resolves tract → county → national.

</details>

<details>
<summary><strong>👥 Socioeconomic</strong> — Census ACS income / poverty / housing-cost burden</summary>

Census ACS poverty, income, and housing-cost-burden indicators scored against the **full national distribution of US census tracts** (household-weighted), not ranked within the local county. Bundled offline from the keyless ACS 5-year Summary File ([`data/socioeconomic.py`](src/housing_label/data/socioeconomic.py), built by [`scripts/build_socio_ref.py`](scripts/build_socio_ref.py)) — the live scoring path no longer needs a Census API key.

</details>

<details>
<summary><strong>🚶 Walkability</strong> — EPA National Walkability Index</summary>

**EPA National Walkability Index** — public-domain, national (every US census block group), keyless, and freely storable. Its 1–20 index (intersection density + transit proximity + land-use mix) is scaled to 0–100 and aggregated to census tracts ([`data/walkability.py`](src/housing_label/data/walkability.py), built by [`scripts/build_walkability.py`](scripts/build_walkability.py)). This replaces the Walk Score API, whose Terms of Use prohibit storing scores and whose free tier caps at ~5,000 calls/day; an optional Walk Score enrichment is still honoured when present (60% walk + 25% transit + 15% bike).

</details>

<details>
<summary><strong>🌡️ Climate Projections</strong> — sub-county downscaled hazard band (heat / precip / drought / fire)</summary>

Sub-county downscaled climate-hazard projection from the USGS [CMIP6-LOCA2](https://doi.org/10.5066/P13OV6GY) Weighted Multi-Model Mean (~6 km grid, sampled at each census tract's internal point; county = the mean of its tracts). Blends four hazard legs — extreme heat (days > 95 °F / 100 °F), heavy precipitation & flood (days > 1″, annual max 5-day total), drought (max consecutive dry days), and **wildfire (Fire Weather Index)** — into a 0–100 score, reported as a low/high band from SSP2-4.5 → SSP5-8.5 at mid-century (2040–2069), with the SSP2-4.5 value as the headline.

The fire leg is Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km 95th-percentile **Fire Weather Index** (RCP8.5), spatially joined to census geography by parsing the ClimRR grid shapefile and sampling the nearest cell at each tract's internal point; because ClimRR publishes a single RCP8.5 pathway, its mid-century FWI drives both bands (no scenario spread). Fire only *enriches* the composite where covered — the LOCA2 heat/precip/drought legs stay the required backbone — so every CONUS place carries all four legs, while a place outside the CONUS grid (Alaska, Hawaii, Puerto Rico lack the core legs too) falls back to a coarser geography rather than being scored on fire alone. A tract internal-point sample (not parcel-resolution) but a real, composite-included value, with tract → county → national-average fallback. See [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

## Scoring System

- **0–100 score per dimension** — higher is better.
- **Dual grading** for every dimension:
  - **National (absolute):** A ≥ 80, B ≥ 60, C ≥ 40, D ≥ 20, F < 20.
  - **Local (percentile-based):** ranked within the dataset — A = top 10%, B = next 25%, C = middle 30%, D = next 25%, F = bottom 10%.
- **Composite score** — the mean of the scored dimensions, itself carrying a national grade, a local grade, and a percentile rank.

The national/local thresholds are identical across all dimensions, so a grade means exactly the same thing whether it's read from the resilience dimension, the composite, or any other.

> **Nationally-anchored scores.** The location-driven dimensions — health, socioeconomic, and walkability — plus infrastructure and climate are scored against **national reference distributions** (bundled, versioned, and reproducible from the `scripts/build_*` builders), so a dimension's 0–100 score and its **absolute national grade are comparable across locations**. This replaces the earlier within-county percentile for health/socioeconomic, which re-baselined every county to a ~50 median and was not comparable place-to-place. The optional *local* percentile grade remains a rank within whatever dataset is loaded and is labelled with its reference population and vintage — never presented as a national percentile.
>
> **National percentile per dimension ("vs US homes").** Each dimension also shows where the home stands nationally — e.g. *"72nd US"*. The construction-driven dimensions (energy, durability, environmental, resilience) map their score through a bundled national distribution built by [`scripts/calibrate_construction_percentiles.py`](scripts/calibrate_construction_percentiles.py) (a household-weighted panel of every US county × documented building archetypes, scored with the real models); walkability maps through the EPA-NWI crosswalk distribution; health/socioeconomic already are national percentiles; climate/infrastructure track national quantiles. These construction/walkability references are **modeled** distributions, so the percentile is an honest, versioned *estimate* (labelled as such on the label).

## Data Sources

<details>
<summary><strong>All sources & API-key requirements</strong> (13 datasets, all free)</summary>

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
| [CDC PLACES](https://www.cdc.gov/places/) | Census-tract health metrics (national Health Impact reference) | Free — no key (bundled) |
| [Census ACS 5-yr Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Socioeconomic indicators (poverty, income, housing-cost burden) — national reference | Free — no key (bundled; the live scoring path needs no key) |
| [EPA National Walkability Index](https://www.epa.gov/smartgrowth/national-walkability-index-user-guide-and-methodology) | Walkability (block-group index, aggregated to tract) | Free — public domain (bundled) |
| [Walk Score API](https://www.walkscore.com/professional/api.php) | Walk / transit / bike scores — *optional*, opt-in only | **Optional key** (its Terms of Use prohibit storing scores) |

> Tract geocoding for the health and socioeconomic joins uses the free [FCC Area API](https://geo.fcc.gov/api/census/) (no key).

</details>

## House Simulator

`src/housing_label/simulate/house.py` models a hypothetical house and reports a **full nutrition label across all nine dimensions**, letting you see how construction decisions move the needle. It supports 20+ above-code construction features (hurricane straps, sealed roof deck, metal/hip roof, tornado safe room, FORTIFIED Gold, flood elevation, ICF walls, etc.). Once the package is installed (`pip install -e .`) it's also available as the `housing-simulate` command.

```bash
python src/housing_label/simulate/house.py --preset icf-passive --lat 35.15 --lon -89.85
# or, after `pip install -e .`:
housing-simulate --preset icf-passive --lat 35.15 --lon -89.85
```

<details>
<summary><strong>Available presets</strong></summary>

- `baseline` — typical 2000s suburban tract home
- `premium` — high-end new build (solid brick, excellent condition, post-IBC)
- `icf-passive` — ICF passive house with the full resilience package
- `worst-case` — pre-1950 wood frame, full basement, AE flood zone, poor condition
- `fortified-gold` — 2026 frame build with IBHS FORTIFIED Gold + metal roof + sealed deck
- `duplex` — 2026 brick duplex (2 units × 1,200 sqft, 0.15 ac, excellent condition)
- `quadplex` — 2026 brick quadplex (4 units × 900 sqft, 0.20 ac, excellent condition)
- `icf-quadplex` — 2026 ICF quadplex (4 units × 1,000 sqft, 0.20 ac) with solar, passive house, hurricane straps + hip roof

All preset fields can be overridden from the CLI (e.g. `--year-built`, `--construction`, `--flood-zone`, `--value`, `--units`, `--sqft`, `--lot-acres`). Run `python src/housing_label/simulate/house.py --help` for the full flag list.

</details>

<details>
<summary><strong>Scoring model — construction-driven vs. location-driven dimensions</strong></summary>

The five **construction-driven** dimensions — resilience, energy efficiency, durability, environmental footprint, and infrastructure burden — are modeled offline from the house configuration (reusing the same `enrich/` models the pipeline uses). The four **location-driven** dimensions depend on where the house sits: health, socioeconomic, and walkability are fetched live for the house's lat/lon (CDC PLACES, Census ACS, and Walk Score respectively), while climate projections come from the bundled CMIP6-LOCA2 tract/county crosswalk (offline, with a tract → county → national-average fallback). When a live source is unavailable (no network, or no `CENSUS_API_KEY` / `WALKSCORE_API_KEY`), that dimension is reported as `N/A` and **excluded from the composite rather than filled with a placeholder**, so a strong build isn't penalized for a missing input.

</details>

<details>
<summary><strong>Full-label flags & any-location support</strong></summary>

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
location's **eGRID2023 Rev 2 subregion** grid-carbon factor as the grid **average** (a bundled
county→subregion crosswalk; counties that can't be mapped fall back to the US-average factor) plus the
county's **NREL Cambium 2023 LRMER** long-run **marginal** factor (a bundled county→GEA-region crosswalk)
to credit solar/efficiency-avoided kWh at the marginal rate — CONUS only, with the average used elsewhere.

</details>

The website nutrition label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) is scored live by the HTTP API (this simulator behind `/label` and `/presets`) and rendered by the shared [`docs/label-core.js`](docs/label-core.js) — the same renderer the home-page address search uses, so there is no static snapshot to regenerate.

## Address-search API

The static site can score **any US address** via a small HTTP wrapper around the simulator
(same scoring path, no model drift):

```bash
pip install -e ".[api]"               # FastAPI + uvicorn
export CENSUS_API_KEY=... WALKSCORE_API_KEY=...   # optional, for the full 8 dimensions
housing-api                            # GET /label?address=... (or ?lat=&lon=), GET /suggest?q=..., GET /healthz
```

<details>
<summary><strong>Autocomplete & deployment details</strong></summary>

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

</details>

## Project Structure

<details>
<summary><strong>Repository layout</strong></summary>

```
housing-nutrition-label/
├── src/housing_label/          # Installable package
│   ├── config.py               # Shared constants (URLs, HTTP defaults, geo reference points)
│   ├── utils.py                # Shared helpers (HTTP, haversine, Web Mercator → WGS84)
│   ├── enrich/                 # per-dimension model libraries (energy, durability,
│   │                           #   environmental, infrastructure, health, structure, …)
│   ├── score/                  # resilience.py, all_dimensions.py (scoring helpers)
│   ├── data/                   # bundled offline reference lookups (keyed on county/tract)
│   ├── simulate/               # house.py (CLI simulator) + dimensions / location glue
│   └── api.py                  # address-search scoring API
├── scripts/                    # build_*.py reference-data builders
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

</details>

## Tech Stack

- **Python 3.x**
- [`requests`](https://requests.readthedocs.io/) — HTTP calls to ArcGIS, FEMA, NOAA, USGS, SPC, CDC, FCC, and Census APIs
- [`pandas`](https://pandas.pydata.org/) (+ `numpy`) — data processing, enrichment joins, and scoring

## Roadmap

The board below is the at-a-glance view; expand the sections under it for details. It's a plain Markdown table, so it renders everywhere — GitHub web **and** the mobile app, PyPI, any viewer — and moving an item between columns is a one-line edit here in the README.

| ✅ Shipped | 🚧 Next up | 🔭 Exploring |
|---|---|---|
| 9-dimension scoring pipeline + dual national / local grades | Methodology "show-your-math" drill-down | Rust scoring engine |
| Live scoring API + unified label renderer | | Scale beyond Shelby County |
| Per-dimension confidence display | | |
| Lifetime-cost strip + A/B compare | | |
| Sub-county climate + Fire Weather Index | | |
| Locally-calibrated Infrastructure Burden | | |
| Wildfire hazard in Disaster Resilience | | |
| Address input on the label page | | |

<details>
<summary><strong>🚧 Next up & 🔭 Exploring</strong> — what each planned card means</summary>

**Next up**

- **Methodology "show-your-math" drill-down** — expandable per-dimension provenance on the label (sources, the EAL/BRM breakdown, the exact eGRID subregion, the calibrating county's spending), so a curious user can trace any score to its inputs.

**Exploring**

- **Rust scoring engine** — port the hot scoring path for performance at scale.
- **Scale beyond Shelby County** — parameterize the pipeline to extend coverage past the Memphis pilot to additional US counties.

</details>

<details>
<summary><strong>✅ Shipped</strong> — completed roadmap items with methodology notes</summary>

<details>
<summary>Address input on the label page</summary>

The Label page ([`docs/label.html`](docs/label.html)) now lets a visitor **score any U.S. address** (or their **current location**) instead of only the fixed Cooper-Young presets: the page geocodes the typed address — or uses a picked autocomplete suggestion's coordinates — and scores the standard construction profiles there via `GET /presets?address=…` / `?lat=&lon=`, reusing the shared [`docs/addr-suggest.js`](docs/addr-suggest.js) typeahead. The scored location is mirrored into the page URL (`history.replaceState`, preserving any `?api=` override) so results are **bookmarkable and shareable**, remembered across visits via `localStorage` (precedence URL > last visit > default), and cleared by Reset. A **"Use my location"** button scores the visitor's current position via the browser geolocation API, with a graceful message when permission is denied or unavailable.

</details>

<details>
<summary>Unified label renderer fed by the live API</summary>

The three bespoke label implementations (the React + D3 `label.html` reading a static `sample-parcels.json`, plus the plain-JS renderers duplicated across `index.html` and `examples.html`) are replaced by **one dependency-free renderer, [`docs/label-core.js`](docs/label-core.js) + [`docs/label-core.css`](docs/label-core.css)**, used by every page. All pages are now scored **live by the same HTTP API**: the home page and examples use `/label`, and the Label page fetches a new **`GET /presets`** endpoint that scores the standard construction profiles at one location in a single response (one geocode + one location fetch total). The confidence rubric stays the single Python source of truth in [`src/housing_label/confidence.py`](src/housing_label/confidence.py); `label-core.js` only renders it. `label.html` dropped its React/D3 + Babel CDN dependencies (plain JS now), and the static `docs/data/sample-parcels.json` snapshot and its `generate_label_data.py` generator were removed — there is no snapshot to drift.

</details>

<details>
<summary>Per-dimension uncertainty / confidence display</summary>

Surfaced the uncertainty the models already carry as a neutral **confidence dot** (High/Moderate/Low) per dimension, a coverage-penalized **composite confidence** line, and an honest **climate scenario-band whisker**, on a channel kept deliberately separate from the grade. See [research/uncertainty-confidence-research.md](research/uncertainty-confidence-research.md).

</details>

<details>
<summary>"Cost over a mortgage" (lifetime cost of ownership) + comparison mode</summary>

The label now present-values the two dollar-defensible flows — modeled **energy cost** and **expected annual disaster loss** — over a 30-year mortgage and shows the result as a **comparative delta vs. a typical comparable** at the same location (never an absolute "total cost"), mirroring the EPA fuel-economy sticker's "you save $X over 5 years" construction. Constant (real) dollars, no real escalation, discounted at ~4% real (homeowner mortgage opportunity cost) with an OMB ~2% social-rate band; the headline is rounded to 2 significant figures. A new **Compare (A/B)** mode puts two profiles side by side with a per-dimension delta table. The strip is fed by numeric `cost` fields in the label payload; no scoring/model change was required. Full methodology, discount-rate/escalation citations, and the dollarizable-vs-qualitative dimension audit: [research/lifetime-cost-research.md](research/lifetime-cost-research.md).

</details>

<details>
<summary>True Fire Weather Index (Argonne ClimRR) for the Climate Projections fire leg</summary>

The **Climate Projections** dimension now carries a genuine **wildfire (Fire Weather Index)** leg from Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km dynamically-downscaled projections (95th-percentile FWI, RCP8.5, mid-century), replacing the consecutive-dry-days stand-in for fire. The keyless ClimRR CSVs (grid keyed by `Crossmodel` cell id) are joined to census geography by parsing the companion grid **shapefile** in pure stdlib — bbox centre → Web Mercator → WGS84 (same formula as `utils.webmercator_to_wgs84`) — and sampling the nearest cell at each tract's internal point (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source fwi`](scripts/build_climate_projections.py), which augments the existing crosswalks in place with `fire_fwi_{hist,low,high}`. ClimRR publishes a single RCP8.5 pathway, so the mid-century FWI drives both bands (no scenario spread). Fire is an *optional enrichment* on top of the required LOCA2 core (heat/precip/drought): where present it adds a fourth leg (every CONUS place), and where a CONUS place lacks it the composite is the mean of the core legs — but a place outside the CONUS LOCA2 grid (Alaska/Hawaii/Puerto Rico) lacks the core legs too and falls back to a coarser geography rather than being scored on fire alone. This is the forward-looking climate-fire signal; the *present-day* wildfire hazard ships separately in Disaster Resilience. See [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

<details>
<summary>Locally calibrated Infrastructure Burden (replace the Memphis-everywhere cost model)</summary>

The per-function cost levels are now calibrated to each county's **actual local-government spending** from the **Census of Governments** (2022 Individual Unit File — the most recent full count: per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), normalized to the Shelby pilot so the pilot is unchanged while every other county scales by its real spending ratio (e.g. LA County ~2.0× roads, ~2.6× water/sewer). Bundled national crosswalk (`govfinance_county.csv`, built by [`scripts/build_govfinance.py`](scripts/build_govfinance.py)); county → national-average fallback via [`data/govfinance.py`](src/housing_label/data/govfinance.py). Phase 1 of the locally-calibrated-infrastructure roadmap (parcel→special-district mapping remains). See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary>Auto-fill home value + reconcile school scope in Infrastructure Burden</summary>

Two fiscal-ratio accuracy fixes. **(1) Auto-fill value:** when no home value is supplied, it now defaults to the **county median** (Census ACS) instead of the construction profile's flat default, so the revenue side (and dollar EALs) reflect the local market — e.g. a Manhattan address no longer scores as if the home were worth $250k. **(2) School-scope reconciliation:** the revenue side now **nets out the school-district share** of property tax (Census of Governments; ~41% nationally, with a national-average fallback for dependent-school counties that fund schools through general government), so it's like-for-like with the school-excluded cost side. Both sides are now non-school; the national median fiscal ratio drops to ~0.31 and the breakpoints were re-calibrated accordingly. This corrects places like high-property-tax suburbs that looked municipally self-sustaining only because their (school-heavy) taxes were counted in full.

</details>

<details>
<summary>Re-anchor the Infrastructure Burden score breakpoints to a national distribution</summary>

Once cost and revenue were localized per county, the fiscal-ratio→score breakpoints (which had been anchored to the Shelby pilot) were re-anchored to the **national distribution** of fiscal ratios — a population-weighted reference over U.S. counties × residential-density archetypes ([`scripts/calibrate_infra_breakpoints.py`](scripts/calibrate_infra_breakpoints.py)) — so a score now tracks national percentile rank (A = top ~20% … F = bottom ~20%). The density gradient (sprawl scores worse) is preserved; the thresholds are just nationally meaningful now.

</details>

<details>
<summary>Locally calibrate the Infrastructure Burden revenue side (per-county property-tax rate)</summary>

The fiscal ratio's revenue side now uses each county's **effective property-tax rate** (median real-estate taxes ÷ median home value) from the **Census ACS** 2022 5-year table-based Summary File, replacing the single national rate applied everywhere — effective rates vary ~10× nationally (~0.3%–3%). Keyless bundled crosswalk (`property_tax_county.csv`, built by [`scripts/build_property_tax.py`](scripts/build_property_tax.py)); county → national-average fallback via [`data/propertytax.py`](src/housing_label/data/propertytax.py). Phase 2 of the roadmap; sub-county/per-jurisdiction millage (state DOR tables) remains a future precision refinement. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary>Add the "fire" hazard to the Disaster Resilience EAL pipeline</summary>

"fire" is now a real, **location-based** summed hazard alongside flood/tornado/seismic. It combines a national-average structural/electrical fire baseline with the **FEMA National Risk Index wildfire** EAL rate (`WFIR_AFREQ × WFIR_HLRB`), resolved tract → county → national from a bundled national crosswalk (`nri_wildfire.csv` + `nri_wildfire_tracts.csv.gz`, built by [`scripts/build_nri_wildfire.py`](scripts/build_nri_wildfire.py)). Both the offline Shelby pipeline ([`enrich/fire.py`](src/housing_label/enrich/fire.py) + [`score/resilience.py`](src/housing_label/score/resilience.py)) and the live API ([`data/wildfire.py`](src/housing_label/data/wildfire.py) via the resolved location) share one fire model; a fire-specific Building Resilience Modifier (wiring era × wall-material combustibility × condition) adjusts it. Previously fire existed only as a flat national constant in the CLI simulator and was absent from the parcel pipeline entirely.

</details>

<details>
<summary>Finer climate resolution (sub-county / census tract)</summary>

The **Climate Projections** dimension now carries real **sub-county (census-tract)** values from the USGS **CMIP6-LOCA2** Weighted Multi-Model Mean (~6 km), sampled at each tract's internal point and bundled as `climate_projections_tracts.csv.gz` (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source loca2`](scripts/build_climate_projections.py) (SSP2-4.5/5-8.5 mid-century 2040–2069); breakpoints re-anchored to the CMIP6 national distribution. Tracts within a large county now genuinely differ — the inverse of CMRA's tract layer, which broadcast the county value. Live point sampling was ruled out (no keyless LOCA2 point API; single-model point samples aren't defensible), so the signal comes from an offline ensemble-mean grid build.

</details>

<details>
<summary>Extend the climate layer to census tracts (CMRA tract layer)</summary>

The climate lookup was made **resolution-aware** (`climate_projection_for_tract`: tract → county → national average, each result tagged with its `geo_level`). CMRA's tract layer was empirically found to broadcast the county value onto every tract (no sub-county signal), so the genuinely finer signal was sourced from CMIP6-LOCA2 instead (above). See [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

<details>
<summary>Per-parcel climate projections (replace the uniform placeholder)</summary>

The **Climate Projections** dimension is now a real per-county score from CMRA (LOCA/NCA4) downscaled projections, with an RCP4.5→8.5 mid-century band and a reproducible build script ([`scripts/build_climate_projections.py`](scripts/build_climate_projections.py)). Design notes in [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

<details>
<summary>Frontend visualization — React + D3 nutrition label UI</summary>

An initial version is live at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) ([`docs/label.html`](docs/label.html)). It renders the scored dimensions as an at-a-glance label with a switchable set of construction profiles, served statically with no build step. *(Since superseded by the dependency-free shared renderer — see above.)*

</details>

</details>

## License

MIT — see [LICENSE](LICENSE)
