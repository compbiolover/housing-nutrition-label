# Housing Nutrition Label™

[![License: PolyForm Shield 1.0.0](https://img.shields.io/badge/License-PolyForm%20Shield%201.0.0-blue.svg)](LICENSE)
[![Site](https://img.shields.io/badge/live-housinglabel.dev-2e7d32)](https://housinglabel.dev/label.html)
[![Status](https://img.shields.io/badge/phase%201-complete-brightgreen)](#current-status)

A source-available platform that scores residential properties across multiple dimensions (disaster resilience, energy efficiency, durability, environmental footprint, infrastructure burden, health impact, air quality, transportation noise, socioeconomic context, walkability, climate projections, rooftop solar potential, and drinking-water quality) and presents them in a clear, standardized format, **like a nutrition label for housing**.

The goal: give homebuyers, renters, insurers, and policymakers an at-a-glance understanding of a property's true risk and quality profile, beyond what typical listings or appraisals reveal.

**➡️ See a live label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html)**

> **Informational purposes only.** A label is a modeled estimate from public data — not an
> inspection, appraisal, or insurance quote, and not legal, financial, insurance,
> engineering, or real estate advice. See [Disclaimer](#disclaimer).

<details>
<summary><strong>📖 Table of contents</strong></summary>

- [Current Status](#current-status)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Scored Dimensions](#scored-dimensions)
- [Scoring System](#scoring-system)
- [Data Sources](#data-sources)
- [House Simulator](#house-simulator)
- [Bulk scoring](#bulk-scoring)
- [Address-search API](#address-search-api)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Roadmap](#roadmap)
- [License](#license)
- [Trademarks](#trademarks)
- [Disclaimer](#disclaimer)

</details>

## Current Status

> **Phase 1 complete: Shelby County, TN (Memphis) pilot, now generalized nationwide across 13 scored dimensions.**

Enter any U.S. residential address (or lat/lon) and it scores thirteen dimensions plus a rolled-up composite, each with a national (absolute) letter grade and a national percentile, from bundled offline reference data plus a few keyless government APIs. An **interactive nutrition label visualization** is live on the project site ([housinglabel.dev/label.html](https://housinglabel.dev/label.html)), backed by the same scoring API.

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
(geocode +            (climate zone, grid,   (13 dimensions, 0–100      (national grade +
 bundled county/       hazards, structure)    scores + composite)       percentile, API/CLI)
 tract lookups)
```

The thirteen dimensions are scored per address on demand using the shared `enrich/` model libraries: the five construction-driven ones from the house configuration, and the eight location-driven ones from the resolved location. There is no separate offline scoring engine: the CLI simulator, the address-search API, and [bulk scoring](#bulk-scoring) all run the same models over the same code path, so a parcel scored three ways returns one answer.

## Scored Dimensions

Each parcel is scored on **thirteen dimensions**, each 0–100 (higher is better). Expand any dimension for its methodology.

<!-- BEGIN AUTOGEN:dimensions (managed by scripts/sync_readme.py — edits here are overwritten; run `python scripts/sync_readme.py --write`) -->
The engine scores **thirteen dimensions** (0–100, higher is better) plus a rolled-up composite. This roster is generated from the code, so it never drifts from what actually ships:

| # | Dimension | Driven by |
|---|---|---|
| 1 | Disaster Resilience | Location + construction |
| 2 | Energy Efficiency | Construction |
| 3 | Durability | Construction |
| 4 | Environmental Footprint | Construction |
| 5 | Infrastructure Burden | Location |
| 6 | Health Impact | Neighborhood context |
| 7 | Air Quality | Location |
| 8 | Noise | Location |
| 9 | Socioeconomic | Neighborhood context |
| 10 | Walkability | Location |
| 11 | Climate Projections | Location |
| 12 | Solar Potential | Location |
| 13 | Water Quality | Location |
<!-- END AUTOGEN:dimensions -->

Expand any dimension below for its full methodology.

<details>
<summary><strong>🛡️ Disaster Resilience</strong>: flood + tornado + seismic + fire EAL</summary>

Expected Annual Loss (EAL) model combining flood, tornado, seismic, and fire hazards, weighted by a construction-quality modifier (year built, construction type, roof shape, foundation, condition). The fire peril blends a national-average structural/electrical fire baseline with the location's FEMA National Risk Index **wildfire** EAL, so it is genuinely location-aware (near-zero in Memphis, materially higher in the fire-prone West).

</details>

<details>
<summary><strong>⚡ Energy Efficiency</strong>: modeled Energy Use Intensity</summary>

Energy Use Intensity (EUI) from NREL ResStock 2024 simulation medians by building type (single-family, multi-family, mobile/manufactured), climate zone, and vintage, adjusted for the home's size, construction, and (ResStock-derived) foundation/heating-system factors.

</details>

<details>
<summary><strong>🏗️ Durability</strong>: component-lifespan / effective-age model</summary>

Component-lifespan / effective-age model blending the remaining service life of eight major building systems (structural shell, roof, HVAC, plumbing, electrical, windows, interior finishes, water heater) with the assessor's condition rating (CDU/COND), then adjusted for exterior-wall material and construction grade. Unscored for vacant / non-residential parcels with no building data.

</details>

<details>
<summary><strong>🌱 Environmental Footprint</strong>: operational + embodied carbon + water</summary>

Three components blended 0.50 operational / 0.30 embodied / 0.20 water: operational CO₂e from modeled energy use × EPA eGRID2023 Rev 2 grid **average** + natural-gas factors, with solar/efficiency-avoided kWh credited at the NREL Cambium 2023 LRMER **marginal** rate (what actually turns off long-run; CONUS only); embodied carbon from material/size (calibrated to the ~39–121 kgCO₂e/m² US single-family band) amortized over a 60-yr study period; and water use from EPA WaterSense benchmarks (with the Memphis Sand aquifer's low embedded-energy advantage). See [research/environmental-footprint-research.md](research/environmental-footprint-research.md). Unscored for vacant / non-residential parcels.

</details>

<details>
<summary><strong>🏙️ Infrastructure Burden</strong>: density-based municipal fiscal ratio</summary>

Density-based municipal cost model producing a per-parcel fiscal ratio (revenue vs. infrastructure cost) by density and distance to the urban core. The per-function cost levels are calibrated to each county's actual local-government spending (Census of Governments per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), so the estimate reflects local fiscal reality rather than reusing the Memphis pilot everywhere. Both sides of the ratio cover the same services: the revenue side counts property tax **plus** modeled user-fee income (water, sewer, trash), since the cost side includes services residents pay for by bill rather than by tax. The score is a **national percentile** — the typical US home covers ~⅔ of its cost — not a pass/fail against 1.0. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary><strong>❤️ Health Impact</strong>: CDC PLACES chronic-disease prevalence</summary>

CDC PLACES census-tract chronic-disease prevalence (7 measures) scored against the **full national distribution of US census tracts** (population-weighted), not ranked within the local county, so a health score means the same thing in Memphis and in Denver. Bundled offline and keyless ([`data/health.py`](src/housing_label/data/health.py), built by [`scripts/build_health_ref.py`](scripts/build_health_ref.py)); resolves tract → county → national.

</details>

<details>
<summary><strong>🌫️ Air Quality</strong>: PM2.5 + ozone (CDC Tracking) + EPA radon zone</summary>

Tract-level ambient air quality: annual **PM2.5** and daily-max-8-hour **ozone** from the CDC Environmental Public Health Tracking downscaler model at the **census tract** (~84k US tracts, full coverage incl. unmonitored areas), plus the **EPA Map of Radon Zones** class (a county-level dataset with no finer public source, broadcast to the tract's county). Each layer maps to a national-percentile sub-score against the distribution of US **tracts** and blends (PM2.5 0.45, ozone 0.25, radon 0.30; radon's weight redistributed for the ~0.2% of counties with no EPA zone). PM2.5/ozone resolve tract → county fallback. Bundled offline and keyless ([`data/air_quality.py`](src/housing_label/data/air_quality.py), built by [`scripts/build_air_quality.py`](scripts/build_air_quality.py)).

</details>

<details>
<summary><strong>🔇 Noise</strong>: transportation-noise exposure (US DOT BTS)</summary>

Tract-level transportation-noise exposure from the **US DOT BTS National Transportation Noise Map** (via the census-tract National Transportation Noise Exposure Map, Seto & Huang 2023): combined aviation + road + rail noise. The metric is the **share of a tract's residents exposed to LAeq ≥ 60 dB**, mapped to a national-percentile score against the distribution of US tracts (more exposure → lower score; higher = quieter), with a tract → county-mean fallback. Bundled offline and keyless, read from the map's per-state shapefile `.dbf` attribute tables with a pure-Python dBASE reader (no GIS dependency) ([`data/noise.py`](src/housing_label/data/noise.py), built by [`scripts/build_noise.py`](scripts/build_noise.py)).

</details>

<details>
<summary><strong>👥 Socioeconomic</strong>: Census ACS income / poverty / housing-cost burden</summary>

Census ACS poverty, income, and housing-cost-burden indicators scored against the **full national distribution of US census tracts** (household-weighted), not ranked within the local county. Bundled offline from the keyless ACS 5-year Summary File ([`data/socioeconomic.py`](src/housing_label/data/socioeconomic.py), built by [`scripts/build_socio_ref.py`](scripts/build_socio_ref.py)); the live scoring path no longer needs a Census API key.

</details>

<details>
<summary><strong>🚶 Walkability</strong>: EPA National Walkability Index</summary>

**EPA National Walkability Index**: public-domain, national (every US census block group), keyless, and freely storable. Its 1–20 index (intersection density + transit proximity + land-use mix) is scaled to 0–100 and aggregated to census tracts ([`data/walkability.py`](src/housing_label/data/walkability.py), built by [`scripts/build_walkability.py`](scripts/build_walkability.py)). This replaces the Walk Score API, whose Terms of Use prohibit storing scores and whose free tier caps at ~5,000 calls/day.

</details>

<details>
<summary><strong>🌡️ Climate Projections</strong>: sub-county downscaled hazard band (heat / precip / drought / fire)</summary>

Sub-county downscaled climate-hazard projection from the USGS [CMIP6-LOCA2](https://doi.org/10.5066/P13OV6GY) Weighted Multi-Model Mean (~6 km grid, sampled at each census tract's internal point; county = the mean of its tracts). Blends four hazard legs into a 0–100 score: extreme heat (days > 95 °F / 100 °F), heavy precipitation & flood (days > 1″, annual max 5-day total), drought (max consecutive dry days), and **wildfire (Fire Weather Index)**. The score is reported as a low/high band from SSP2-4.5 → SSP5-8.5 at mid-century (2040–2069), with the SSP2-4.5 value as the headline.

The fire leg is Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km 95th-percentile **Fire Weather Index** (RCP8.5), spatially joined to census geography by parsing the ClimRR grid shapefile and sampling the nearest cell at each tract's internal point; because ClimRR publishes a single RCP8.5 pathway, its mid-century FWI drives both bands (no scenario spread). Fire only *enriches* the composite where covered (the LOCA2 heat/precip/drought legs stay the required backbone), so every CONUS place carries all four legs, while a place outside the CONUS grid (Alaska, Hawaii, Puerto Rico lack the core legs too) falls back to a coarser geography rather than being scored on fire alone. This is a tract internal-point sample (not parcel-resolution) but a real, composite-included value, with tract → county → national-average fallback. See [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

<details>
<summary><strong>☀️ Solar Potential</strong>: rooftop specific yield (PVGIS on NREL NSRDB)</summary>

County rooftop-solar **specific yield** (the annual energy a standard 1 kWp array makes, in kWh per kW installed per year), modeled by the EU JRC's **PVGIS v5.2** on the **PVGIS-NSRDB** satellite database (the same NREL NSRDB resource PVWatts uses), for a building-mounted array at optimal tilt facing south with 14% losses, queried at each county's Census-gazetteer internal point. Mapped to a national-percentile score against the distribution of US counties (sunny Southwest ~1,700+ ≈ 2× cloudy Pacific NW ~950). The drill-down scales the yield to a representative 6 kW system: annual production, bill savings at the local EIA electricity rate, and CO₂ avoided at the **marginal** grid rate (Cambium LRMER; eGRID average fallback), reusing the Energy/Environmental rate and grid factors. Bundled offline and keyless ([`data/solar.py`](src/housing_label/data/solar.py), built by [`scripts/build_solar.py`](scripts/build_solar.py)). PVGIS-NSRDB covers CONUS + Hawai'i + Puerto Rico; far-north Alaska is outside coverage and left unscored.

</details>

<details>
<summary><strong>🚰 Water Quality</strong>: community drinking-water compliance (EPA SDWIS)</summary>

County drinking-water safety from the EPA **Safe Drinking Water Information System (SDWIS)** federal reporting. The metric is the **share of the county's community-water-system-served population** (residents on an active CWS, not all county residents, so private wells are out of scope) **that is on a system with a health-based drinking-water violation** (a contaminant exceedance or treatment-technique failure, not a monitoring/paperwork lapse) whose non-compliance period began within the trailing 5-year window. Because the exposure share is **zero-inflated** (~28% of counties, ~27% of the CWS population, sit at exactly 0%, a genuine and common optimum), it is scored with a **hurdle (two-part) model**: a **spotless county scores 100** (no recent health-based violation is the best achievable outcome), and an **exposed county is scored by its conditional national percentile among the counties that have any recent exposure** (the share of that exposed-county community-water-system population, weighted by each county's total CWS population rather than its violating population, living in a county whose exposure is worse than this one's; less exposure → higher score). This is continuous with the clean class (the least-exposed county ≈ 100) and monotone down to 0 at full exposure. It replaces an earlier single population-weighted percentile whose **mid-rank** tie-breaking capped a spotless county at ~86.5 (the tie-adjusted rank of the zero mass) and dropped off a cliff at the first sign of any exposure. Bundled offline and keyless ([`data/water.py`](src/housing_label/data/water.py), built by [`scripts/build_water.py`](scripts/build_water.py)). Reflects reported community-water-system compliance, not private wells or in-home plumbing.

</details>

## Scoring System

- **0–100 score per dimension**, higher is better.
- **Dual grading** for every dimension:
  - **National (absolute):** A ≥ 80, B ≥ 60, C ≥ 40, D ≥ 20, F < 20.
  - **Local (percentile-based):** ranked within the dataset: A = top 10%, B = next 25%, C = middle 30%, D = next 25%, F = bottom 10%.
- **Composite score**: the mean of the scored dimensions, itself carrying a national grade, a local grade, and a percentile rank.

The national/local thresholds are identical across all dimensions, so a grade means exactly the same thing whether it's read from the resilience dimension, the composite, or any other.

> **Nationally-anchored scores.** The location-driven dimensions (health, socioeconomic, walkability, air quality, noise, and water) plus infrastructure and climate are scored against **national reference distributions** (bundled, versioned, and reproducible from the `scripts/build_*` builders), so a dimension's 0–100 score and its **absolute national grade are comparable across locations**. This replaces the earlier within-county percentile for health/socioeconomic, which re-baselined every county to a ~50 median and was not comparable place-to-place. The optional *local* percentile grade remains a rank within whatever dataset is loaded and is labelled with its reference population and vintage, never presented as a national percentile.
>
> **National percentile per dimension ("vs US homes").** Each dimension also shows where the home stands nationally, e.g. *"72nd US"*. The construction-driven dimensions (energy, durability, environmental, resilience) map their score through a bundled national distribution built by [`scripts/calibrate_construction_percentiles.py`](scripts/calibrate_construction_percentiles.py) (a household-weighted panel of every US county × documented building archetypes, scored with the real models); walkability maps through the EPA-NWI crosswalk distribution; health/socioeconomic already are national percentiles; climate/infrastructure/air quality track national quantiles. These construction/walkability references are **modeled** distributions, so the percentile is an honest, versioned *estimate* (labelled as such on the label).

## Accuracy

Every score is inferred from public data. Whether that inference describes the
house actually standing there is measured, not asserted:
[`scripts/measure_accuracy.py`](scripts/measure_accuracy.py) scores a sample of
addresses from the address alone and compares the result against the assessing
authority's own record for the same parcel. The headline number is the
**grade-impact rate** — how often the letter a reader sees differs from the one
the true attributes produce — because a year-built error that moves no grade is
not a defect anyone can see, and a small one that crosses a code-era boundary is.

Published at [housinglabel.dev/accuracy.html](https://housinglabel.dev/accuracy.html)
and regenerated from a committed measurement run, which CI verifies the page still
matches. Two of the three jurisdictions with an adapter are measured — **Cook County,
Illinois** and **Washington, DC** — each against its own assessor. They are real
measurements of two housing stocks, not a national accuracy figure, and they are not
comparable to each other: different stock, different record-keeping, different sample.

**Florida is served but not yet measured.** The statewide adapter covers all 67
counties and is the widest in the registry, and serving a jurisdiction is not the
same as having measured it — so it carries no published figure until it is drawn and
scored the same way the other two were.

DC's figures cover **non-condominium homes only**. Condominium units are about a
third of its assessor's residential stock and live in a separate table keyed by
unit; a unit-level identifier never appears in the parcel geometry, so no coordinate
can pick one unit out of a building. The adapter returns nothing for a condo rather
than guessing, and the page says so where the numbers are.

The measurement feeds back into the label rather than only being published. Where a
dimension's grade was measured as sensitive to construction provenance — durability
differs from the assessor's answer 37.3% of the time in Cook and 50.5% in DC when
the profile is a neighbourhood typical, and energy 37.3% and 32.6% — its confidence
tier is now capped at Moderate until the building's own details are known. Resilience is deliberately exempt: it moved on 2.8% of the
Cook sample and 8.7% of the DC one — separate samples, not a paired comparison — so
the vintage reaches its letter only at the margin, and capping it would understate a
signal the measurement says is strong.

The benchmarks are fetched on demand and deliberately **not committed**: neither
source grants an explicit right to redistribute a dataset, so only the measurements
taken from them live in this repository.

## Data Sources

<details>
<summary><strong>All sources & API-key requirements</strong> (21 datasets, all free)</summary>

| Source | Provides | API key |
|---|---|---|
| [Shelby County Assessor ArcGIS](https://www.shelbycountytn.gov/) | Parcel boundaries + CAMA building data | Free, no key |
| [FEMA NFHL](https://msc.fema.gov/portal/home) | Flood zone designations | Free, no key |
| [NOAA Climate Normals](https://www.ncdc.noaa.gov/cdo-web/) | Temperature, heating/cooling degree days (1991–2020) | Free, no key |
| [USGS CMIP6-LOCA2](https://doi.org/10.5066/P13OV6GY) | Sub-county climate-hazard projections (CMIP6-LOCA2 WMMM ~6 km, SSP2-4.5–5-8.5) | Free, no key |
| [Argonne ClimRR](https://www.anl.gov/ccrds/climrr) | Projected Fire Weather Index (12 km, RCP8.5), the Climate Projections fire leg | Free, no key (bulk CSVs) |
| [SPC Historical Tornadoes](https://www.spc.noaa.gov/) | Historical tornado tracks / frequency | Free, no key |
| [USGS NSHM](https://earthquake.usgs.gov/hazards/interactive/) | Seismic hazard (peak ground acceleration), reference data | Free, no key |
| [FEMA National Risk Index](https://hazards.fema.gov/nri/) | Wildfire expected-annual-loss (the location-based fire peril) | Free, no key |
| [Census of Governments](https://www.census.gov/programs-surveys/cog.html) + [Population Estimates](https://www.census.gov/programs-surveys/popest.html) | Per-county local-government spending by function (Infrastructure Burden cost calibration) | Free, no key (bulk files) |
| [Census ACS 5-yr Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Per-county effective property-tax rate (Infrastructure Burden revenue calibration) | Free, no key (bulk table file) |
| [DOE/EIA ResStock](https://resstock.nrel.gov/) | Residential energy use intensity benchmarks, reference data | Free, no key |
| [CDC PLACES](https://www.cdc.gov/places/) | Census-tract health metrics (national Health Impact reference) | Free, no key (bundled) |
| [CDC EPH Tracking](https://ephtracking.cdc.gov/) + [EPA Map of Radon Zones](https://www.epa.gov/radon/epa-map-radon-zones) | County PM2.5, ozone & radon zone (Air Quality) | Free, no key (bundled) |
| [US DOT BTS National Transportation Noise Map](https://www.bts.gov/geospatial/national-transportation-noise-map) | Tract transportation-noise exposure (Noise) | Free, no key (bundled) |
| [PVGIS](https://re.jrc.ec.europa.eu/) (EU JRC) on NREL NSRDB | County rooftop solar specific yield (Solar Potential) | Free, no key (bundled) |
| [EPA SDWIS](https://www.epa.gov/ground-water-and-drinking-water/safe-drinking-water-information-system-sdwis-federal-reporting) | County community-water-system health-based violations (Water Quality) | Free, no key (bundled) |
| [Census ACS 5-yr Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Socioeconomic indicators (poverty, income, housing-cost burden), national reference | Free, no key (bundled; the live scoring path needs no key) |
| [Census ACS 5-yr Summary File](https://www.census.gov/programs-surveys/acs/data/summary-file.html) | Tract year-built distribution — B25034 quartiles + B25035 median (the vintage stand-in and its spread, when nobody supplies the real year) | Free, no key (bundled) |
| [Cook County Assessor](https://datacatalog.cookcountyil.gov/) (Open Data) | **Observed** parcel construction: year built, living area, exterior wall, basement type, condition, stories — Cook County, IL only, queried live and never bundled | Free, no key (off unless `ASSESSOR_ADAPTERS=1`) |
| [DC Office of Tax and Revenue](https://opendata.dc.gov/) (Open Data DC) | **Observed** parcel construction: year built, gross floor area, stories, exterior wall, condition — Washington, DC only, queried live and never bundled | Free, no key (off unless `ASSESSOR_ADAPTERS=1`) |
| [Florida Dept. of Revenue](https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer) (statewide cadastral) | **Observed** parcel construction: year built, and living area where the parcel holds a single home — all **67 Florida counties**, queried live and never bundled | Free, no key (off unless `ASSESSOR_ADAPTERS=1`) |
| [EPA National Walkability Index](https://www.epa.gov/smartgrowth/national-walkability-index-user-guide-and-methodology) | Walkability (block-group index, aggregated to tract) | Free, public domain (bundled) |

> Tract geocoding for the health and socioeconomic joins uses the free [FCC Area API](https://geo.fcc.gov/api/census/) (no key).

</details>

## House Simulator

`src/housing_label/simulate/house.py` models a hypothetical house and reports a **full nutrition label across all thirteen dimensions**, letting you see how construction decisions move the needle. It supports 20+ above-code construction features (hurricane straps, sealed roof deck, metal/hip roof, tornado safe room, FORTIFIED Gold, flood elevation, ICF walls, etc.). Once the package is installed (`pip install -e .`) it's also available as the `housing-simulate` command.

```bash
python src/housing_label/simulate/house.py --preset icf-passive --lat 35.15 --lon -89.85
# or, after `pip install -e .`:
housing-simulate --preset icf-passive --lat 35.15 --lon -89.85
```

<details>
<summary><strong>Available presets</strong></summary>

- `baseline`: typical 2000s suburban tract home
- `premium`: high-end new build (solid brick, excellent condition, post-IBC)
- `icf-passive`: ICF passive house with the full resilience package
- `worst-case`: pre-1950 wood frame, full basement, AE flood zone, poor condition
- `fortified-gold`: 2026 frame build with IBHS FORTIFIED Gold + metal roof + sealed deck
- `duplex`: 2026 brick duplex (2 units × 1,200 sqft, 0.15 ac, excellent condition)
- `quadplex`: 2026 brick quadplex (4 units × 900 sqft, 0.20 ac, excellent condition)
- `icf-quadplex`: 2026 ICF quadplex (4 units × 1,000 sqft, 0.20 ac) with solar, passive house, hurricane straps + hip roof

All preset fields can be overridden from the CLI (e.g. `--year-built`, `--construction`, `--flood-zone`, `--value`, `--units`, `--sqft`, `--lot-acres`). Run `python src/housing_label/simulate/house.py --help` for the full flag list.

</details>

<details>
<summary><strong>Scoring model: construction-driven vs. location-driven dimensions</strong></summary>

The five **construction-driven** dimensions (resilience, energy efficiency, durability, environmental footprint, and infrastructure burden) are modeled offline from the house configuration using the `enrich/` model libraries. The eight **location-driven** dimensions depend on where the house sits: health, socioeconomic, walkability, air quality, and noise are bundled national references (CDC PLACES, Census ACS, the EPA National Walkability Index, CDC Tracking PM2.5/ozone + EPA radon zone, and the US DOT BTS transportation-noise map) resolved by the house's census tract (air quality's radon layer is county-level); climate projections come from the bundled CMIP6-LOCA2 tract/county crosswalk (tract → county → national-average fallback); solar potential is a bundled per-county PVGIS rooftop-yield lookup; and water quality is a bundled per-county EPA SDWIS drinking-water-compliance lookup, all keyless. When a location can't be resolved (e.g. offline, so no census tract), the affected dimension is reported as `N/A` and **excluded from the composite rather than filled with a placeholder**, so a strong build isn't penalized for a missing input.

</details>

<details>
<summary><strong>Full-label flags & any-location support</strong></summary>

Full-label flags:

- `--address "<US address>"`: score a house at **any US address** (geocoded via the keyless
  Census geocoder to lat/lon + county + census tract). `--lat/--lon` also work anywhere.
- `--json`: emit the complete nutrition label (all dimensions, composite, metrics) as JSON.
- `--no-fetch`: skip the live location lookups; leave health/socioeconomic/walkability unscored.
- `--health-index` / `--socioeconomic-index` / `--walk-score`: supply a location dimension directly instead of fetching it.

**Any-location support:** the resolved location drives the location-dependent dimensions:
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
to credit solar/efficiency-avoided kWh at the marginal rate (CONUS only, with the average used elsewhere).

</details>

The website nutrition label at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) is scored live by the HTTP API (this simulator behind `/label` and `/presets`) and rendered by the shared [`docs/label-core.js`](docs/label-core.js), the same renderer the home-page address search uses, so there is no static snapshot to regenerate.

## Bulk scoring

Score a whole portfolio in one pass — a lender's book, an assessor's roll, a city's
parcels — with `housing-batch`. CSV in, CSV out, one row per parcel:

```bash
housing-batch --input book.csv --output scored.csv --portfolio-grades
```

**Supply a census tract per row and the entire run needs no network at all**, scoring
all thirteen dimensions at roughly 580 parcels/sec on one core — about 11 minutes for
400,000. (Add a one-off ~1.5 s at startup while the bundled reference tables decode, so a
50-row test measures far slower than a real run; the rate above is steady state.)
That works because only one upstream call is ever load-bearing — the Census geocode that
turns a point into a county and tract — and every crosswalk keyed off them is bundled. A
caller who already holds the tract (lenders, insurers and assessors generally do; anyone
else can join it from a Census bulk file) skips it entirely.

| Input column | What it does |
|---|---|
| `id` | passed through untouched — your key for joining results back |
| `lat`, `lon` | **required** — unless you give an `address` and add `--geocode` (see below), which fills these in and keeps the scoring pass offline |
| `tract` / `county_fips` | **required for the eight location dimensions**; `tract` alone implies county and state |
| `year_built`, `sqft`, `construction`, `foundation`, `condition`, `flood_zone` | **strongly recommended** — these are what the Building axis is made of. See below |
| `street`, `city`, `state`, `zip` | used by `--geocode` (or a single `address`) |
| `units`, `stories`, `value`, `lot_acres`, … | any other house field the simulator accepts |
| `upgrades`, `preset` | optional |

Unknown columns are ignored, so a customer export can be fed in unmodified.

Output carries every dimension's score, national grade and national percentile, the
composite, both headline axes, `n_scored`, and `building_source` / `defaulted_inputs`.
Rows that can't be scored keep their `id` and carry an `error` — a bad parcel never ends
the run, and never silently vanishes from a book you're reconciling.

`--portfolio-grades` adds a second, clearly separate ranking: where each parcel falls
**within this batch**. A national grade answers "how does this compare to US housing";
a portfolio grade answers "which tenth of my book is worst". Both are reported, never
merged.

### What happens if you don't supply the building attributes

A row that carries only a position and a tract still scores all thirteen dimensions —
but the five construction-driven ones are scored against a **typical house**: a
wood-frame slab-on-grade 2,000 sqft build of the tract's typical vintage, and offline
every parcel in the country defaults to flood zone X (minimal). Measured on one
Memphis tract (47157003100, whose homes are typically from 1950):

| | nothing supplied | 1948 frame/crawl/poor, zone AE |
|---|---|---|
| Building axis | **22.4 (D)** | **10.7 (F)** |
| Site axis | 42.0 | 42.4 *(this half is real either way)* |
| `n_scored` | 13 | 13 |

The default year built used to be a flat 2024, which graded **92.9 (A)** on that same
tract — a book of century-old housing read as new construction. It is now the tract's
ACS median year built ([`data/year_built.py`](src/housing_label/data/year_built.py),
bundled, so it resolves offline here too), which follows the neighbourhood instead of
flattering it: the same attribute-free row grades **19 in a 1950s Memphis tract and 84
in a 2010s one**.

The remaining defaults are still not neutral — a minimal flood zone and an average
condition both sit toward the optimistic end — so on a whole book there is still a
systematic bias, not noise that averages out, and `n_scored` doesn't catch it because
thirteen dimensions really were scored. What changed is that the largest single source
of that bias is gone.

So every scored row reports where its building inputs came from:

| Column | Value |
|---|---|
| `building_source` | `supplied` (nothing assumed) · `partial` (some assumed) · `defaulted` (every building input assumed) |
| `defaulted_inputs` | the field names that were assumed, e.g. `construction,foundation,condition,flood_zone` |

and a run logs a warning naming the count — separately for the two, because a
partial row's Building grade does describe this house, just less precisely.
Nothing is refused:
scoring the Site half for a customer who holds no building data is a legitimate use —
the point is only that a defaulted A can never be mistaken for a measured one.

### Long runs

`--resume` continues an interrupted run: it counts the rows the output file already
covers, skips that many input rows and appends, producing a file byte-identical to an
uninterrupted run. It refuses if that file was written with different columns (a
`--portfolio-grades` flag flipped between runs would line the CSV up while making every
appended cell mean something else), and it can't be combined with `--portfolio-grades`,
which writes nothing until the end and so leaves nothing partial to resume from.

```bash
housing-batch -i book.csv -o scored.csv --resume     # safe on the first run too
```

`--jobs N` scores N rows concurrently. It only helps when the run is making upstream
calls, and is **refused without `--fetch`**: measured on offline scoring, four threads
ran at 0.89× of serial — pure GIL contention, since nothing releases it. Keep it modest;
the constraint on a `--fetch` run is politeness to free government endpoints, not cores.
Output order is unchanged either way.

### Only have addresses?

`--geocode` runs a pre-pass through the **Census batch geocoder**, which takes 10,000
addresses per request and returns coordinates *and* the census tract — about two requests
per 10,000 parcels, against one per parcel for the per-address geocoder. That turns a book
of addresses into one that scores offline:

```bash
housing-batch --input addresses.csv --output scored.csv --geocode
```

Rows that already carry a tract are left alone rather than re-looked-up. An address the
Census can't place is reported with the reason it gave (`geocode: No_Match`) instead of
being guessed at — a fabricated coordinate would score a real parcel against the wrong
neighborhood.

Add `--geocode-cache geo.sqlite` and a re-run asks the Census only about addresses it
hasn't seen before:

```bash
housing-batch -i addresses.csv -o scored.csv --geocode --geocode-cache geo.sqlite
```

Results are committed per chunk, so a run that dies at row 380,000 keeps everything it had
already resolved — which is what makes a multi-hour geocode restartable. Non-matches are
cached too (otherwise a book with 5% bad addresses re-requests that 5% every run);
`--retry-misses-after DAYS` re-looks-up stale ones, since the Census does add addresses.
Matches never expire — an address doesn't move.

The cache key includes the Census **benchmark and vintage**, not just the address. Those
pins move and TIGER redraws tracts, so a cache keyed on the address alone would keep
serving the old tract after a benchmark change, with every downstream score computed
against the wrong geography and nothing reporting a problem.

Omit the geography columns and skip `--geocode`, and the run still works, but it carries no
tract and the eight location dimensions come back unscored — visible in `n_scored`, never
filled with a placeholder.

## Address-search API

The static site can score **any US address** via a small HTTP wrapper around the simulator
(same scoring path, no model drift):

```bash
pip install -e ".[api]"               # FastAPI + uvicorn
housing-api                            # no API keys required; GET /label?address=... (or ?lat=&lon=), GET /suggest?q=..., GET /healthz
                                       # also: /presets (all profiles scored here), /preset-profiles (their names only), /density (same lot, 1-4 homes)
```

<details>
<summary><strong>Autocomplete & deployment details</strong></summary>

The search bar also has **address & place-name autocomplete**: `GET /suggest?q=...` returns US
`[{label, lat, lon, residential}]`, proxied server-side (visitors' keystrokes never reach a third
party directly). Typing a business, campus, or landmark name resolves it to the street address it
sits at, so you don't have to know the address to score a place; the `residential` field flags a
non-residential POI (a stadium, office, or store) so the scorer refuses to grade it as a home.
Back-end priority: **Google Places** (`GOOGLE_PLACES_API_KEY`, best US business/landmark coverage,
enable "Places API (New)") → **Geoapify** (`GEOAPIFY_API_KEY`, [free tier](https://www.geoapify.com),
EU/GDPR, sharper US ranking) → keyless [**Photon**](https://photon.komoot.io) (`PHOTON_URL` to
self-host), each falling back to the next if unreachable. Keys stay server-side.

Deploy it anywhere that runs Python (GitHub Pages can't host it). The repo ships a
[`render.yaml`](render.yaml) Blueprint and a [`Dockerfile`](Dockerfile) (Fly / Cloud Run /
Railway / any container host). CORS is locked to `https://housinglabel.dev` by default.
Override it via the `ALLOWED_ORIGINS` env var. Then point the Examples-page search bar at the
deployed URL with `?api=https://your-api-host` or `window.HOUSING_LABEL_API`. See
[`docs/setup.html`](docs/setup.html) → *Address-search API*.

</details>

<details>
<summary><strong>Embeddable badge</strong></summary>

`GET /badge?address=...` returns the label as a standalone **SVG**, for putting on a page
that isn't ours:

```html
<a href="https://housinglabel.dev/label.html">
  <img src="https://your-api-host/badge?address=123%20Main%20St,%20Memphis,%20TN"
       width="360" height="116"
       alt="Housing Nutrition Label — the building and the site, graded.
            Modeled estimate, for information only; not advice.">
</a>
```

It renders inside a plain `<img>`: no script, no CORS, no build step on the host page.
`style=full|compact`, `theme=auto|light|dark` (auto follows the reader's own setting, via a
media query that browsers honour even inside an `<img>`), and `label_text=` overrides the
caption for a caller who has already formatted the address.

**It shows two grades, not one** — the building and the site, the same split the label page
leads with and the one [`research/building-vs-location-subscores.md`](research/building-vs-location-subscores.md)
argues for. A single letter would travel further and would be the wrong number: the two
axes disagreeing is the information. An axis that couldn't be scored reads *not scored*
rather than being rounded down to an F.

Two things follow from the `<img>` constraint and are worth knowing before you embed.
Browsers disable links inside an `<img>`-loaded SVG, so the badge can't click through on
its own — wrap it in an anchor as above, and the wordmark is drawn into the image so
attribution survives if you don't. And there are no web fonts, so text falls back to the
reader's system stack; the layout is positioned rather than fitted, and long addresses
truncate.

The badge carries the trademark, which is licensed separately from the code — see
[TRADEMARKS.md](TRADEMARKS.md). Displaying it unmodified, with attribution, is referential
use and needs no permission.

It also carries the [disclaimer](#disclaimer), drawn into the image next to the wordmark
(`informational only, not advice`; `NOT ADVICE` on the compact style) with the full text in
the SVG's `<desc>`. That is deliberate and is not something to crop out: the badge is the
one copy of the label that is read with none of our own pages, and none of our own fine
print, anywhere near it.

</details>

<details>
<summary><strong>Print it, or save it as an SVG</strong></summary>

A label that matters gets taken out of the browser — into the folder with the inspection
report, into a listing packet, across a kitchen table. There are two ways out, because
they are two different artifacts.

**Print** (the *Print label* button, or ⌘/Ctrl-P). The page prints what is on screen,
including the rows you expanded and excluding everything that only exists to be clicked.
The printed sheet carries a colophon the screen doesn't need — where it came from and what
day it was printed — because a page of grades with no source and no date is the copy that
gets misread a year later.

Both buttons sit in the search form's own action row, beside *Use my location* and *Start
over*, rather than under the card: a label runs several phone screens, and a control at its
foot is a control nobody scrolls to. They start disabled — there is nothing to take away
until something has been scored — and switch on with the label.

**Save as SVG** (`GET /label.svg?address=...`). The whole label redrawn as **one US Letter
page of vector**: both headline grades, all thirteen dimensions, the running-cost line, and
the disclaimer in full.

```
GET /label.svg?address=123%20Main%20St,%20Memphis,%20TN&theme=light&download=1
```

It takes every `/label` house parameter and is scored through the same path, so a saved
sheet cannot disagree with the label it was saved from — including any detail you corrected
in *Refine building details*. Beyond those: `theme=light|dark|auto` (**light** by default,
where the badge defaults to `auto` — this artifact exists to be printed, and paper has no
dark mode), `download=1` for a `Content-Disposition: attachment`, `label_text=` to caption
it with an address you have already formatted, and `scored=` to stamp a date in the footer.

Three things it does differently from the web card, all of them because paper is not a
screen:

- **It has an edge.** The layout is budgeted against the page, so a thirteen-dimension
  label lands on one sheet instead of breaking across two wherever the browser chose. The
  per-row detail panels are the one thing left off; printing all thirteen would be a
  booklet, not a label.
- **Colour is never the only channel.** Every grade is a letter *and* a bar length *and* a
  number, so a grayscale printer, a fax, or a photocopy of a photocopy loses nothing.
- **The text is still text.** Real `<text>` elements, not outlines — searchable,
  selectable, and editable in Illustrator or Inkscape. Which is also why there are no web
  fonts and nothing is fitted: like the badge, every element is positioned absolutely and
  long strings are wrapped or truncated against an estimate that deliberately runs wide.

</details>

<details>
<summary><strong>API keys &amp; usage limits</strong></summary>

**No key is needed, and on your own instance none exists.** Every caller is anonymous
unless the operator has issued keys, and an anonymous caller is unmetered — which is what
callers have always had, and what keeps `pip install` → `housing-api` the same program the
licence invites you to self-host.

Where the operator *has* issued keys, sending one as an `X-API-Key` header buys two
things: a rate-limit bucket of your own instead of one shared with everybody behind the
same address, and your plan's daily allowance of scoring passes. It does not buy different
numbers — a scored address returns the same label on every plan, and it always will.

Anonymous callers are counted too, one row each: a badge is attributed to the **site
embedding it** (the `Referer`'s host, so a thousand readers of one page are one embedder),
and everything else to the calling address. Scheme, port and userinfo are not part of who
is embedding, so `example.com` and `example.com:443` are one row; subdomains stay distinct.
That is attribution, not authentication — a `Referer` is trivially forged, and it counts
cooperative callers correctly without stopping an uncooperative one.

`?key=` also works and is **not** equivalent. A query string is part of the request line,
so it lands in the server's access log, any proxy in front of it, browser history, and the
`Referer` sent to third parties — none of which this code can unwrite. Use the header
wherever you can set one; `?key=` is there for callers that genuinely can't (an `<img>` or
iframe embed, a quick curl), and a key that has travelled that way is one to rotate.
Requests carrying it are answered `no-store` so the URL at least stays out of the disk
cache.

Metering counts **scoring passes, not requests**: `/label` is one, `/presets` is five,
a four-scenario `/density` is four. `GET /usage` reports the calling key's plan, what it
has spent today and when that resets; metered replies also carry `X-Quota-Limit`,
`X-Quota-Remaining` and `X-Quota-Used`. Exhausting the day returns **429**, and a request
rejected as invalid is never charged.

Operators: `HOUSING_LABEL_KEYS` issues keys as comma-separated `plan:key` entries (keys are
SHA-256 hashed at parse, and only the digest is kept), and `ANON_DAILY_SCORES` sets the
ceiling for callers without one — unset, meaning unmetered. Counters live in the serving
process and reset on deploy: enough to enforce a daily ceiling, not an invoice. See
[`src/housing_label/entitlements.py`](src/housing_label/entitlements.py).

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
- [`requests`](https://requests.readthedocs.io/): HTTP calls to ArcGIS, FEMA, NOAA, USGS, SPC, CDC, FCC, and Census APIs
- [`pandas`](https://pandas.pydata.org/) (+ `numpy`): data processing, enrichment joins, and scoring

## Roadmap

The board below is the at-a-glance view; expand the sections under it for details. It's a plain Markdown table, so it renders everywhere (GitHub web **and** the mobile app, PyPI, any viewer), and moving an item between columns is a one-line edit here in the README. The code-derived facts (the scored-dimension roster under [Scored Dimensions](#scored-dimensions), and its count) are regenerated by [`scripts/sync_readme.py`](scripts/sync_readme.py) and verified in CI, so the shipped list can't silently drift from the engine.

| ✅ Shipped | 🚧 Next up | 🔭 Exploring |
|---|---|---|
| 13-dimension nationwide scoring pipeline + dual national / local grades | Methodology "show-your-math" drill-down | Rust scoring engine |
| Nationwide coverage (generalized past the Shelby County pilot) | Parcel-level (sub-tract) resolution | Automatic roadmap-column sync from commit history |
| Air Quality, Noise, Solar Potential & Water Quality dimensions | | |
| Live scoring API + unified label renderer | | |
| Address search + autocomplete on every page | | |
| Residential-only screening (non-residential addresses refused) | | |
| Per-dimension confidence display | | |
| Lifetime-cost strip + A/B compare | | |
| Sub-county climate + Fire Weather Index | | |
| Locally-calibrated Infrastructure Burden | | |
| Wildfire hazard in Disaster Resilience | | |
| Historical / time-series labels (`/timeline`) | | |

<details>
<summary><strong>🚧 Next up & 🔭 Exploring</strong>: what each planned card means</summary>

**Next up**

- **Methodology "show-your-math" drill-down**: expandable per-dimension provenance on the label (sources, the EAL/BRM breakdown, the exact eGRID subregion, the calibrating county's spending), so a curious user can trace any score to its inputs.
- **Parcel-level (sub-tract) resolution**: push the location-driven dimensions below the census tract to the individual parcel where finer public data exists.

**Exploring**

- **Rust scoring engine**: port the hot scoring path for performance at scale.
- **Automatic roadmap-column sync from commit history**: extend [`scripts/sync_readme.py`](scripts/sync_readme.py) to propose Shipped/Next-up moves from merged `feat:` commits, so the qualitative columns self-update too (today it keeps the code-derived dimension roster in sync).

</details>

<details>
<summary><strong>✅ Shipped</strong>: completed roadmap items with methodology notes</summary>

<details>
<summary>Historical / time-series labels (<code>/timeline</code>)</summary>

"Over time" turned out to be three different questions wearing one roadmap line, and the main risk in shipping it was letting a reader mistake one for another. They are now separated structurally — every series carries a `basis`, and the word appears on screen:

- **`projection`** — where the place is heading. The bundled CMIP6-LOCA2 tables already carried a `<metric>_hist` column (the 1991–2020 climatology) alongside the mid-century bands, and [`_band_score`](src/housing_label/data/climate_projections.py) was already generic over the band suffix, so this needed no new data at all. Across the 83,739 tracts that score in both, the mean climate score runs **64.8 → 58.7**, and 81,334 of them worsen.
- **`aging`** — how *this house's* grade moves as it gets older. `REFERENCE_YEAR` in [`enrich/durability.py`](src/housing_label/enrich/durability.py) was the only thing pinning the building to now; it is now a parameter, so the component-lifespan basket can be re-evaluated at any as-of year. Nothing was measured or forecast here, which is why the series says so in its own caveat.
- **`observed`** — how the place has actually changed. None yet: this is the one that needs genuinely new multi-vintage tables, and every dimension awaiting it says so in `point_in_time` rather than rendering as silence.

Two decisions carry the feature:

**The yardstick is fixed.** Every point is scored through *today's* breakpoints and percentile curves; [`data/national_percentile.py`](src/housing_label/data/national_percentile.py) is not recalibrated per vintage. Re-deriving the national distribution at each point answers "how did this place *rank* back then", and that erases the largest true signal in the data — a nationwide improvement shows as a flat line at every address in the country, because everyone moved together. It is also the defect this codebase has already fixed twice ([`_sub()`](src/housing_label/simulate/dimensions.py), [`BUILDING_XS`](src/housing_label/data/national_percentile.py)): two numbers that look alike and answer different questions.

**Percentiles do not travel.** Climate's breakpoints are household-weighted tract quantiles taken under SSP2-4.5 *mid-century*, so running the recent-past band through `national_percentile()` would yield "this place's 1991–2020 climate beats N% of US homes' *projected* climate" — well-defined and useless. A rank is surfaced only at the point its reference distribution was calibrated for; elsewhere the point carries a score and no rank.

Supporting pieces: [`data/vintages.py`](src/housing_label/data/vintages.py) is the registry and holds the reader-facing sentence for every dimension with no series — a test pins `TRAJECTORY ∪ POINT_IN_TIME` against the dimension roster, so a new dimension is unmergeable until someone writes that sentence. `band_trajectory` scores both endpoints over the *intersection* of their populated legs, so a future rebuild can't make the delta partly a change in what was averaged. And `/timeline` runs exactly one scoring pass however many years it is asked for — every point is read from data already resident — which is what a test asserts, and why there is no whole-label `as_of` parameter.

</details>

<details>
<summary>Reconcile the fiscal ratio's revenue scope (user fees + rental tax classification)</summary>

Two revenue-side errors, both understating exactly the dense housing the cost model treats most favorably. Found by asking why a 157-unit downtown Memphis building scored an **A** while showing a fiscal ratio of **0.60** under copy reading "a ratio above ~1 means it pays its own way."

**(1) User fees now count.** The cost side included water, sewer, and trash; the revenue side counted only property tax — but residents pay for those by utility bill and monthly fee. [`scripts/build_govfinance.py`](scripts/build_govfinance.py) now also parses **current-charges revenue** (object code `A`: A44 highways, A80 sewerage, A91 water utility, A81 solid waste, A61 parks) from the same Census of Governments file and writes a per-county **fee-recovery ratio** = charges ÷ expenditure. Nationally water/sewer recovers ~100% of its cost and solid waste ~75%, while **fire and police recover 0% — no current-charge code exists for either**, which is why property tax alone must cover them and why the typical home still doesn't reach 1.0. Recovery is capped at 100% so a surplus-running utility (Memphis's MLGW) is credited at break-even, never above.

**(2) Rental housing isn't assessed as residential in Tennessee.** Tenn. Const. art. II, § 28 assesses residential property at 25% "provided that residential property containing two (2) or more **rental** units is hereby defined as industrial and commercial property" — assessed at **40%** (Tenn. Code Ann. § 67-5-501(11), § 67-5-801). The count is rental units, not dwelling units: a rented single-family home and an owner-occupied duplex both stay residential (Tenn. Att'y Gen. Op. No. 25-016, Aug. 25, 2025). So a Memphis apartment building generates **1.6×** the tax the flat ratio credited it. New [`data/assessment.py`](src/housing_label/data/assessment.py) encodes it, returning the commercial ratio *or nothing* so the correction is strictly additive and never overrides a caller's own assessment basis. Unknown tenure defaults to rental for multi-unit buildings (ACS 2024 B25032: 86% of units in 2+ unit structures are renter-occupied).

With both sides covering the same services the national median fiscal ratio moves **0.31 → 0.67**, ~18% of homes clear 1.0 (was ~none), and `INFRA_XS` was re-anchored. The label copy now states what the dimension actually measures — a **national percentile rank**, where an A can coexist with not fully paying your way. **Coverage:** 49 of 51 scorable jurisdictions (50 states + DC), 99.4% of the US population &mdash; all nine Census divisions worked through, with the District of Columbia and Hawaii the only two left out. Eight carry a correction (AL and WV 2.0&times;, New York City 1.81&times; at 11+ units, TN 1.6&times;, MS and SC 1.5&times;, MN 1.25&times; and ND 1.11&times; at 4+ units); thirty-nine more are researched as uniform, including California, Texas, Illinois, Ohio, Arizona, Colorado, Pennsylvania and Louisiana, and two (Rhode Island and Connecticut) classify rental housing per municipality in states whose counties are not governmental units, so the rule is real but not resolvable here. Four findings worth the detour: Louisiana and Ohio both have a real two-class split that keys on *use* rather than tenure, so an apartment is taxed like a house in both; Cook County's classification ordinance assesses houses and 7+ unit rentals at the same 10%, so Illinois needed no sub-state rule after all; New York City's naive statutory multiplier of 4.70&times; would over-correct by 2.6&times;, because the city's own commission shows that ratio is an artifact of valuing rentals on assessor rather than sales-based values; and four Mountain states' headline owner-occupied preferences turn out to key on *occupancy* rather than tenure &mdash; Utah's covers tenants resident 183+ days &mdash; so they target second homes, not landlords. The two remaining jurisdictions are **deferrals, not gaps in the reading**: DC's post-2025 class structure is genuinely ambiguous for multifamily rentals, and Hawaii's counties classify rental housing so heavily (implied 1.97&times;&ndash;3.56&times;) that two of four breach the correction ceiling and Honolulu's is a value-tiered bracket rather than a class ratio &mdash; so it is under-corrected on purpose rather than encoded from an unmodelled schedule. See [research/property-tax-classification-rollout.md](research/property-tax-classification-rollout.md) and `python scripts/report_classification_coverage.py`. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

**(3) The school netting no longer mixes two populations — in Texas.** Netting schools off the revenue side multiplied an ACS effective rate measured over **owner-occupied homes** by a school share measured over **all property**. Where a state gives owner-occupied homes school-*specific* relief the ACS rate has already lost most of its school component, so netting the share removed it twice &mdash; understating municipal revenue, and the score, for every home in that state, owner and rental alike. [`data/school_millage.py`](src/housing_label/data/school_millage.py) replaces the estimate with a measurement wherever per-county school rates are bundled: compute what the owner actually pays in school tax at the county median value and **subtract** it, so both terms cover the same population. Counties without millage keep the old path byte-for-byte. Texas ships first &mdash; 9.2% of the population, all 254 counties from the Comptroller's ISD rates file &mdash; lifting the municipal rate **+34%** population-weighted; `INFRA_XS` re-anchored and no golden case changed grade. One finding worth the detour: secondary sources say confidently that the $100,000 school homestead exemption covers operating tax but not debt service, while the Comptroller's own file shows the two taxable bases *equal* in 87% of district rows, which could not happen if the exemption skipped the debt levy &mdash; so the exemption's reach is measured per county rather than assumed. Michigan, Arizona, South Carolina, South Dakota and Vermont carry the same distortion for a further 7.4% and still use the estimate; each needs a different state source, and MI/SC exempt a whole operating levy rather than a slice of value, so they need an operating-versus-debt split rather than the Texas shape.

</details>

<details>
<summary>Residential-only screening (refuse non-residential addresses)</summary>

Scoring a **workplace, store, or warehouse** used to return a meaningless "home" label. The engine now screens a typed address against the **USACE National Structure Inventory** building it resolves to: when NSI *positively* classifies the structure as non-residential (a Hazus `COM*`/`IND*`/`AGR*`/`GOV*` occupancy), scoring is refused rather than dressed up as a house. The check lives in the shared `build_label_parts` ([`src/housing_label/simulate/house.py`](src/housing_label/simulate/house.py)) so the CLI and the API behave identically; the API returns **HTTP 422** with a plain-language explanation (distinct from a 400 validation error or a 502 upstream failure) and the site shows it as a neutral notice, not a scary "couldn't load" error. It fails *open*: an unknown building (NSI unavailable or no match) is never blocked, so a transient outage can't refuse a real home. Deliberate hypotheticals bypass it: a construction **preset** ("what if you built here"), an entered **unit count > 1** (asserting a residence), or an explicit `allow_non_residential=true` (CLI `--allow-non-residential`).

</details>

<details>
<summary>Air Quality, Noise, Solar Potential & Water Quality dimensions</summary>

Four location-driven dimensions added since the original nine, each a bundled, keyless national reference resolved at the census tract or county (see their entries under [Scored Dimensions](#scored-dimensions)): **Air Quality** (CDC Tracking PM2.5 + ozone at the tract, EPA radon zone), **Noise** (US DOT BTS transportation-noise exposure), **Solar Potential** (PVGIS-on-NSRDB county rooftop yield → production/savings/CO₂ drill-down), and **Water Quality** (EPA SDWIS community-water-system health-based violations). Each maps to a national-percentile score against the distribution of US tracts/counties so its grade means the same thing everywhere.

</details>

<details>
<summary>Nationwide coverage + a self-syncing README (past the Shelby County pilot)</summary>

The pipeline was generalized from the Memphis/Shelby County pilot to **any U.S. residential address**: every location-driven dimension resolves from bundled national reference data (keyed on county/tract) rather than the pilot's hard-coded defaults, and the construction-driven dimensions are scored against national distributions, so a grade is comparable place-to-place. To keep the docs honest as the engine grows, [`scripts/sync_readme.py`](scripts/sync_readme.py) regenerates the code-derived **scored-dimension roster** (count + table) in this README directly from `housing_label.simulate.dimensions.DIMENSIONS`, and CI runs it in `--check` mode so a dimension added in code fails the build until the README is regenerated (`python scripts/sync_readme.py --write`).

</details>

<details>
<summary>Address input on the label page</summary>

The Label page ([`docs/label.html`](docs/label.html)) now lets a visitor **score any U.S. address** (or their **current location**) instead of only the fixed Cooper-Young presets: the page geocodes the typed address (or uses a picked autocomplete suggestion's coordinates) and scores the standard construction profiles there via `GET /presets?address=…` / `?lat=&lon=`, reusing the shared [`docs/addr-suggest.js`](docs/addr-suggest.js) typeahead. The scored location is mirrored into the page URL (`history.replaceState`, preserving any `?api=` override) so results are **bookmarkable and shareable**, remembered across visits via `localStorage` (precedence URL > last visit > default), and cleared by Reset. A **"Use my location"** button scores the visitor's current position via the browser geolocation API, with a graceful message when permission is denied or unavailable.

</details>

<details>
<summary>Unified label renderer fed by the live API</summary>

The three bespoke label implementations (the React + D3 `label.html` reading a static `sample-parcels.json`, plus the plain-JS renderers duplicated across `index.html` and `examples.html`) are replaced by **one dependency-free renderer, [`docs/label-core.js`](docs/label-core.js) + [`docs/label-core.css`](docs/label-core.css)**, used by every page. All pages are now scored **live by the same HTTP API**: the home page and examples use `/label`, and the Label page fetches a new **`GET /presets`** endpoint that scores the standard construction profiles at one location in a single response (one geocode + one location fetch total). The confidence rubric stays the single Python source of truth in [`src/housing_label/confidence.py`](src/housing_label/confidence.py); `label-core.js` only renders it. `label.html` dropped its React/D3 + Babel CDN dependencies (plain JS now), and the static `docs/data/sample-parcels.json` snapshot and its `generate_label_data.py` generator were removed. There is no snapshot to drift.

</details>

<details>
<summary>Per-dimension uncertainty / confidence display</summary>

Surfaced the uncertainty the models already carry as a neutral **confidence dot** (High/Moderate/Low) per dimension, a coverage-penalized **composite confidence** line, and an honest **climate scenario-band whisker**, on a channel kept deliberately separate from the grade. See [research/uncertainty-confidence-research.md](research/uncertainty-confidence-research.md).

</details>

<details>
<summary>"Cost over a mortgage" (lifetime cost of ownership) + comparison mode</summary>

The label now present-values the two dollar-defensible flows (modeled **energy cost** and **expected annual disaster loss**) over a 30-year mortgage and shows the result as a **comparative delta vs. a typical comparable** at the same location (never an absolute "total cost"), mirroring the EPA fuel-economy sticker's "you save $X over 5 years" construction. Constant (real) dollars, no real escalation, discounted at ~4% real (homeowner mortgage opportunity cost) with an OMB ~2% social-rate band; the headline is rounded to 2 significant figures. A new **Compare (A/B)** mode puts two profiles side by side with a per-dimension delta table. The strip is fed by numeric `cost` fields in the label payload; no scoring/model change was required. Full methodology, discount-rate/escalation citations, and the dollarizable-vs-qualitative dimension audit: [research/lifetime-cost-research.md](research/lifetime-cost-research.md).

</details>

<details>
<summary>True Fire Weather Index (Argonne ClimRR) for the Climate Projections fire leg</summary>

The **Climate Projections** dimension now carries a genuine **wildfire (Fire Weather Index)** leg from Argonne National Laboratory's [ClimRR](https://www.anl.gov/ccrds/climrr) 12 km dynamically-downscaled projections (95th-percentile FWI, RCP8.5, mid-century), replacing the consecutive-dry-days stand-in for fire. The keyless ClimRR CSVs (grid keyed by `Crossmodel` cell id) are joined to census geography by parsing the companion grid **shapefile** in pure stdlib (bbox centre → Web Mercator → WGS84, the same formula as `utils.webmercator_to_wgs84`) and sampling the nearest cell at each tract's internal point (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source fwi`](scripts/build_climate_projections.py), which augments the existing crosswalks in place with `fire_fwi_{hist,low,high}`. ClimRR publishes a single RCP8.5 pathway, so the mid-century FWI drives both bands (no scenario spread). Fire is an *optional enrichment* on top of the required LOCA2 core (heat/precip/drought): where present it adds a fourth leg (every CONUS place), and where a CONUS place lacks it the composite is the mean of the core legs. But a place outside the CONUS LOCA2 grid (Alaska/Hawaii/Puerto Rico) lacks the core legs too and falls back to a coarser geography rather than being scored on fire alone. This is the forward-looking climate-fire signal; the *present-day* wildfire hazard ships separately in Disaster Resilience. See [research/climate-projections-research.md](research/climate-projections-research.md).

</details>

<details>
<summary>Locally calibrated Infrastructure Burden (replace the Memphis-everywhere cost model)</summary>

The per-function cost levels are now calibrated to each county's **actual local-government spending** from the **Census of Governments** (2022 Individual Unit File, the most recent full count: per-capita direct expenditure on roads, water/sewer, fire, police, sanitation, parks), normalized to the Shelby pilot so the pilot is unchanged while every other county scales by its real spending ratio (e.g. LA County ~2.0× roads, ~2.6× water/sewer). Bundled national crosswalk (`govfinance_county.csv`, built by [`scripts/build_govfinance.py`](scripts/build_govfinance.py)); county → national-average fallback via [`data/govfinance.py`](src/housing_label/data/govfinance.py). Phase 1 of the locally-calibrated-infrastructure roadmap (parcel→special-district mapping remains). See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary>Auto-fill home value + reconcile school scope in Infrastructure Burden</summary>

Two fiscal-ratio accuracy fixes. **(1) Auto-fill value:** when no home value is supplied, it now defaults to the **county median** (Census ACS) instead of the construction profile's flat default, so the revenue side (and dollar EALs) reflect the local market. For example, a Manhattan address no longer scores as if the home were worth $250k. **(2) School-scope reconciliation:** the revenue side now **nets out the school-district share** of property tax (Census of Governments; ~41% nationally, with a national-average fallback for dependent-school counties that fund schools through general government), so it's like-for-like with the school-excluded cost side. Both sides are now non-school; the national median fiscal ratio drops to ~0.31 and the breakpoints were re-calibrated accordingly. This corrects places like high-property-tax suburbs that looked municipally self-sustaining only because their (school-heavy) taxes were counted in full.

</details>

<details>
<summary>Re-anchor the Infrastructure Burden score breakpoints to a national distribution</summary>

Once cost and revenue were localized per county, the fiscal-ratio→score breakpoints (which had been anchored to the Shelby pilot) were re-anchored to the **national distribution** of fiscal ratios, a population-weighted reference over U.S. counties × residential-density archetypes ([`scripts/calibrate_infra_breakpoints.py`](scripts/calibrate_infra_breakpoints.py)), so a score now tracks national percentile rank (A = top ~20% … F = bottom ~20%). The density gradient (sprawl scores worse) is preserved; the thresholds are just nationally meaningful now.

</details>

<details>
<summary>Locally calibrate the Infrastructure Burden revenue side (per-county property-tax rate)</summary>

The fiscal ratio's revenue side now uses each county's **effective property-tax rate** (median real-estate taxes ÷ median home value) from the **Census ACS** 2022 5-year table-based Summary File, replacing the single national rate applied everywhere. Effective rates vary ~10× nationally (~0.3%–3%). Keyless bundled crosswalk (`property_tax_county.csv`, built by [`scripts/build_property_tax.py`](scripts/build_property_tax.py)); county → national-average fallback via [`data/propertytax.py`](src/housing_label/data/propertytax.py). Phase 2 of the roadmap; sub-county/per-jurisdiction millage (state DOR tables) remains a future precision refinement. See [research/infrastructure-burden-research.md](research/infrastructure-burden-research.md).

</details>

<details>
<summary>Add the "fire" hazard to the Disaster Resilience EAL pipeline</summary>

"fire" is now a real, **location-based** summed hazard alongside flood/tornado/seismic. It combines a national-average structural/electrical fire baseline with the **FEMA National Risk Index wildfire** EAL rate (`WFIR_AFREQ × WFIR_HLRB`), resolved tract → county → national from a bundled national crosswalk (`nri_wildfire.csv` + `nri_wildfire_tracts.csv.gz`, built by [`scripts/build_nri_wildfire.py`](scripts/build_nri_wildfire.py)). The label reads it through [`data/wildfire.py`](src/housing_label/data/wildfire.py) via the resolved location and folds it into the EAL model in [`score/resilience.py`](src/housing_label/score/resilience.py); a fire-specific Building Resilience Modifier (wiring era × wall-material combustibility × condition) adjusts it. Previously fire existed only as a flat national constant in the CLI simulator and was absent from the parcel pipeline entirely.

</details>

<details>
<summary>Finer climate resolution (sub-county / census tract)</summary>

The **Climate Projections** dimension now carries real **sub-county (census-tract)** values from the USGS **CMIP6-LOCA2** Weighted Multi-Model Mean (~6 km), sampled at each tract's internal point and bundled as `climate_projections_tracts.csv.gz` (county = the mean of its tracts). Built by [`scripts/build_climate_projections.py --source loca2`](scripts/build_climate_projections.py) (SSP2-4.5/5-8.5 mid-century 2040–2069); breakpoints re-anchored to the CMIP6 national distribution. Tracts within a large county now genuinely differ, the inverse of CMRA's tract layer, which broadcast the county value. Live point sampling was ruled out (no keyless LOCA2 point API; single-model point samples aren't defensible), so the signal comes from an offline ensemble-mean grid build.

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
<summary>Frontend visualization: React + D3 nutrition label UI</summary>

An initial version is live at [housinglabel.dev/label.html](https://housinglabel.dev/label.html) ([`docs/label.html`](docs/label.html)). It renders the scored dimensions as an at-a-glance label with a switchable set of construction profiles, served statically with no build step. *(Since superseded by the dependency-free shared renderer, see above.)*

</details>

</details>

## License

**[PolyForm Shield 1.0.0](LICENSE)** — source-available, not OSI open source.

Read it, run it, modify it, self-host it, build on it, and contribute back. The one
thing it does not permit is using it to provide a product or service that competes
with Housing Nutrition Label. Commercial licenses for competing use are available —
open an issue or get in touch.

Two things worth being explicit about:

- **Releases through v0.1.82 were published under the MIT License and remain MIT
  permanently** ([LICENSE-MIT-HISTORICAL](LICENSE-MIT-HISTORICAL)). Relicensing is
  not retroactive and this project does not pretend otherwise. This license governs
  releases after v0.1.82.
- **The underlying data is not licensed here, because it isn't ours to license.**
  The Census, FEMA, EPA, NREL, USGS, NOAA and CDC inputs are US federal works in the
  public domain. This license covers the scoring engine, the models, and the derived
  crosswalks — not the public facts they are built from.

### Commercial use

Most commercial use needs nothing from anyone. Scoring your own portfolio, running the
engine inside your own product, publishing what you find — all of that is ordinary
permitted use under the license above, paid or not. The line the license draws is
narrow: you may not use this to offer a *competing* housing-label product or service.
Commercial licenses for exactly that are available — open an issue or get in touch.

Two things the license does **not** decide, and which are worth asking about before
building on this commercially:

- **Displaying the label off-site is a trademark question, not a code question.** The
  mark is what a right-to-display would be granted under, and it is licensed separately
  ([TRADEMARKS.md](TRADEMARKS.md)). There is no badge or embed endpoint yet; when there
  is, referential use will stay free and syndication at scale will be the thing that
  needs a license.
- **Certification is not on offer.** TRADEMARKS.md reserves "offering a certification
  bearing the marks", and that reservation is deliberate: a label paid for by the party
  being rated has an incentive problem that no disclaimer fixes. The scoring path holds
  Health and Socioeconomic out of both headline axes for a related reason — see
  [`research/monetization-research.md`](research/monetization-research.md) for the
  evidence behind both calls.

## Trademarks

**Housing Nutrition Label™** and **HousingLabel.dev** are trademarks of Andrew Willems,
and are **not** covered by the software license above — see [TRADEMARKS.md](TRADEMARKS.md).

A license to the code is not a license to the name, and the two have different reach:
the MIT-era releases (through v0.1.82) can be forked by anyone forever, but a fork still
may not *call itself* Housing Nutrition Label. Referential use — saying your project
builds on it, writing about it, citing it — needs no permission and never will.

## Disclaimer

**The label is for informational purposes only.** It is a modeled estimate built from
public data. It is **not** an inspection, appraisal, survey, or insurance quote, and it is
**not** legal, financial, insurance, engineering, or real estate advice. It describes what
the model expects of a home *like* this one at this location; it cannot tell you the
condition, safety, value, or insurability of any particular property. Verify anything you
would act on with a qualified professional. Everything here is provided as is, without
warranty of any kind (see [LICENSE](LICENSE)).

That gap between "a home like this one" and "this home" is the reason the notice travels
*with* the label rather than living on a terms page. The wording is a single constant in
[`src/housing_label/legal.py`](src/housing_label/legal.py), and every surface reads it from
there:

| Surface | How it shows up |
| --- | --- |
| JSON payload (`--json`, `GET /label`, `/presets`, `/density`, `/timeline`) | `disclaimer` field |
| Web label (`docs/label-core.js`) | fine print inside the card, on every view |
| Embeddable SVG badge | drawn on the badge; full text in `<desc>` |
| Printable sheet (`GET /label.svg`) | drawn in full on the page, plus `<desc>` |
| A printed page | the card's own notice, plus a colophon naming the source and date |
| CLI (`housing-simulate`) | printed in the label box |
| Bulk scoring (`housing-batch`) | logged once per run — a 400,000-row CSV can't carry a paragraph per row |
| This README and every page on the site | footer |

Consumers of the API are expected to keep it with the numbers. If you render the payload
yourself, render `disclaimer` too — and if the field is missing (an older or cached
response), fall back to the text above rather than showing a score with nothing attached.

Two related lines this project holds, for the same reason:

- **No certification.** [TRADEMARKS.md](TRADEMARKS.md) reserves offering a certification
  bearing the marks — a label paid for by the party being rated has an incentive problem
  that no disclaimer fixes.
- **Data quality is reported, not implied.** Every dimension carries a confidence tier and
  the composite says how many dimensions it could actually score, so "we don't know" never
  renders as a number ([`src/housing_label/confidence.py`](src/housing_label/confidence.py)).
