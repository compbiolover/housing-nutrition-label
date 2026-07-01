# Per-Parcel Climate Projections — Implementation Research

Research backing the roadmap item: *"replace the uniform climate placeholder with
downscaled climate-projection data."* The current `Climate Projections` dimension is a
hard-coded placeholder (`CLIMATE_PLACEHOLDER = 50.0` in
`src/housing_label/score/all_dimensions.py`, `composite=False`, excluded from the composite). This document identifies the
authoritative, license-clean data sources and a concrete build plan to make it real.

Scope chosen (most comprehensive on every axis):
- **Hazards:** extreme heat, precipitation & inland flooding, drought & wildfire, plus a
  blended composite hazard index.
- **Scenarios/horizon:** a low/high band from **SSP2-4.5 → SSP5-8.5**, anchored at
  **mid-century (~2050)**, extendable to late-century (~2080–2090).
- **Delivery:** hybrid — a bundled offline county/tract crosswalk (keyless, reproducible,
  like the eGRID/seismic crosswalks) **plus** an optional live high-resolution refresh.

---

## Bottom line

Build the bundled crosswalk from **CMRA / CRIS** (LOCA2 pre-aggregated to **county and
census-tract** geography — see Q1 — the official 5th National Climate Assessment
downscaling), and use **NASA NEX-GDDP-CMIP6**
(keyless CC0 on AWS S3 + NCCS THREDDS) for the optional live refresh and any custom index
derivation. Both are CC0 / US-government public domain, so both can be bundled and
redistributed. Every source is a 6–25 km **downscaled grid** — values must be surfaced as
**county/tract aggregates with a low/high band, never as parcel-resolution precision.**

---

## Source comparison

| Source | Variables | Scenarios | Horizons | Native res | Aggregation | License / access | Role |
|---|---|---|---|---|---|---|---|
| **CMRA / CRIS** (`resilience.climate.gov`) | 25 LOCA-derived vars (heat, drought, wildfire, flooding, coastal) — pre-summarized | SSP2-4.5, SSP5-8.5 | historic, early, **mid (~2050)**, late (30-yr means) | LOCA2 ~6 km, pre-aggregated to **county, census-tract, AND tribal** | NOAA NCEI TSU → ArcGIS FeatureServer | Public, **keyless ArcGIS FeatureServer** (see Q1) | **Primary: bundled crosswalk** |
| **NASA NEX-GDDP-CMIP6** | tasmax, tasmin, tas, pr, hurs, huss, rlds, rsds, sfcWind (daily) → derive days>95/100°F, CDD, extreme-precip return periods | All 4 Tier-1 SSPs (1-2.6, 2-4.5, 3-7.0, 5-8.5) | 1950–2100 (daily) | ~25 km (0.25°) daily, BCSD | Point-sample or area-mean to county/tract | **CC0** (since Sep 2022), keyless. AWS S3 `s3://nex-gddp-cmip6/` (bulk) + NCCS THREDDS subset/OPeNDAP/WMS (live) | **Primary: live refresh + custom indices** |
| **LOCA2 native** (USGS ScienceBase) | Temp/precip + water-balance | ssp245 / ssp370 / ssp585 | 1950–2100 | ~6 km | Roll your own Zonal Statistics | **CC0 1.0** (DOI 10.5066/P9DWN1XL) | Supplementary: custom 6 km aggregation if CMRA insufficient |
| **Argonne ClimRR** | 60+ incl. **Fire Weather Index**, heat index, CDD/HDD | RCP4.5, RCP8.5 (CMIP5) | hist 1995-2004, mid 2045-2054, end 2085-2094 | **12 km** dynamical (WRF) | Portal / bulk | Public (federal lab) | Supplementary: **fire-weather + heat-index** component |
| **FEMA National Risk Index** | 18 hazards composite (incl. heat wave, drought, riverine flood, wildfire) | **present-day only** (no SSP/RCP projection) | current climatology | county + census-tract | Already tract/county | Free, keyless, OpenFEMA bulk | Composite *baseline* only — **not future-projected** (resolved in Q2: present-day only; FEMA's Future Risk Index was removed Feb 2025) |
| **CEJST** (Justice40 screening tool) | Tract climate-burden indicators (incl. some projected: flood/wildfire risk to properties) | mixed | mixed | census-tract | Already tract | Keyless bulk (.csv/.xlsx/shapefile) | Supplementary: ready-made **tract** layer |
| **First Street** | Flood/heat/fire/wind property risk | proprietary | 30-yr forward | property/parcel | n/a | **Commercial/paid API**, license-restricted | Not bundleable; out of scope for keyless build |

---

## Recommended hazard variables (standard, ETCCDI / heat-stress conventions)

- **Extreme heat** — annual days with Tmax > 95 °F and > 100 °F; cooling degree days (CDD);
  warm-spell duration. Derivable from NEX-GDDP daily `tasmax`/`tas`; CMRA serves
  pre-summarized heat metrics.
- **Precipitation & inland flooding** — extreme-precip return periods (GEV/GPD fit to daily
  `pr`); days > 1"/2"/4"; max 1-day & 5-day precip (Rx1day/Rx5day). NEX-GDDP daily `pr`;
  CMRA flooding metric.
- **Drought & wildfire** — SPEI / aridity; Fire Weather Index. **ClimRR** provides FWI and
  heat index directly (12 km). Per Q3, MACAv2-METDATA (~4 km, CMIP5/RCP) supplies the input
  met variables but no pre-derived indices; compute fire/drought indices ourselves from
  NEX-GDDP (CMIP6/SSP) via the NCAR `fire-indices` method for scenario consistency.
- **Composite** — FEMA NRI gives a present-day blended baseline; the forward-looking
  composite is best built by normalizing the per-hazard projected variables ourselves
  (see methodology) rather than relying on a single ready-made projected index.

---

## Proposed implementation (mirrors the eGRID/seismic pattern)

1. **`data/climate_projections.csv`** — bundled crosswalk keyed by geography id
   (`geoid` — county FIPS for v1, with a `geo_level` column so census-tract rows can be added
   later since CMRA exposes a tract layer; see Q1) plus `scenario {low,high},
   horizon {mid,late}, heat_*, precip_*, drought_*, fire_*`. Built from CMRA/CRIS county (and
   optionally tract) summaries — or rolled up ourselves from LOCA2 + ClimRR where CMRA lacks a
   variable. **v1 scope: county-level**; tract is a drop-in extension, not a schema change.
2. **`scripts/build_climate_projections.py`** — reproducible generator (like
   `build_egrid_crosswalk.py`): pulls the source grids/summaries, runs zonal aggregation,
   writes the CSV byte-for-byte. Documents source URLs + vintage.
3. **`data/climate_projections.py`** — `climate_projection_for_county(fips) -> dict` (v1) with
   a national-average fallback for unmapped counties (same shape as `egrid_for_county`), plus a
   parallel `climate_projection_for_tract(tract_geoid) -> dict` when the tract layer is added
   (falls back to the parent county). Lat/lon resolves to a geoid upstream, as for other
   dimensions.
4. **Optional live refresh** — NEX-GDDP via NCCS THREDDS subset for a lat/lon, gated on
   network like the other live enrichers; falls back to the bundled crosswalk offline.
5. **Scoring** — replace `score_climate`: normalize each hazard variable to 0–100 (percentile
   rank across all US counties, or distance from a fixed threshold), blend per-hazard scores
   (equal-weight or documented weights), and report a **low band (SSP2-4.5)** and **high band
   (SSP5-8.5)**. Flip the dimension to `composite=True` so it finally counts.

### Normalization / band methodology
- Per hazard: compute the projected metric at the county for each scenario, normalize to
  0–100 via national percentile rank (robust, distribution-aware) — higher projected hazard →
  lower score.
- Composite climate score = mean (or documented weights) of the per-hazard scores.
- Report **two numbers**: low band from SSP2-4.5, high band from SSP5-8.5 — the spread *is*
  the scenario-uncertainty signal. The headline score can be the SSP2-4.5 (mid) value with
  the SSP5-8.5 value shown as the downside.

---

## Scientific caveats (must be documented in the dimension)

- **Resolution / false precision.** Sources are 6–25 km grids (NEX-GDDP ~25 km, LOCA2/CMRA
  ~6 km, ClimRR 12 km). None resolves a parcel. Surface as county/tract aggregates; the name
  "per-parcel" must not imply parcel-scale accuracy.
- **Scenario heterogeneity.** NEX-GDDP / LOCA2 / CMRA are CMIP6/SSP; ClimRR is CMIP5/RCP.
  Treating RCP4.5/8.5 as analogs of SSP2-4.5/5-8.5 is defensible for a coarse 0–100 index but
  not exact — keep fire/heat-from-ClimRR clearly labeled.
- **Composite baseline ≠ projection.** FEMA NRI is present-day; do not present it as a future
  projection.
- **Licensing nuance.** NEX-GDDP CC0 still carries a citation request and a per-file
  `cmip6_license` attribute to check; LOCA2-USGS and CMRA/CRIS are cleaner federal public
  domain. First Street is commercial — not bundleable.

---

## Open questions — RESOLVED (focused follow-up run)

A second deep-research run (105 agents, 23 sources, 25 claims under 3-vote adversarial
verification — 19 confirmed, 6 killed) resolved all five. Net effect: the **core plan stands
and gets simpler** — CMRA serves the data directly as a keyless API with tract-level support.

### Q1 — CMRA/CRIS access: ✅ keyless ArcGIS FeatureServer, tract-level included
CMRA Screening Data is a **public, keyless ArcGIS FeatureServer** (no key, anonymous
Query/Extract):
`https://services3.arcgis.com/0Fs3HcaFfvzXvm7w/arcgis/rest/services/CMRA_Screening_Data/FeatureServer`
with **three aggregation layers — Counties (0), Census Tracts (1), Tribal/AIAN-NHPI areas
(2)**. So tract-level *is* available (the earlier "county/tribal only" assumption was
refuted). Backed by LOCA2 (NOAA NCEI TSU), **25 LOCA-derived variables**, 4 periods × 2
scenarios (SSP2-4.5 / SSP5-8.5) as 30-yr means. **Caveat (verified):** the precise bulk-query
mechanics (`?f=pjson`, `maxRecordCount` pagination) could *not* be confirmed (that specific
claim was killed 0-3) — it's a standard FeatureServer so `Query` + `resultOffset` paging
should work, but the build script must verify endpoint behavior and rate limits at runtime.
**Clean CC0 fallback:** USGS published a CMIP6-LOCA2 **county-level** aggregation linkable by
`GEOID` (2023 TIGER/Line) if the CMRA service is unstable.

### Q2 — FEMA "Future Risk Index": ✅ it existed, but was REMOVED — don't depend on it
Base NRI is present-day/historical climatology. FEMA *did* build a forward-looking
**Future Risk Index** (adds a climate-change "Hazard Multiplier" to NRI, 4 scenarios),
launched as a prototype **Dec 12, 2024** — but it was **taken offline ~Feb 2025** (live only
mid-Dec 2024 → mid-Feb 2025) after the Jan 2025 executive-order rollback (Harvard EELP
tracker; archived technical doc survives). **Recommendation:** treat present-day NRI as a
composite *baseline* only; do **not** depend on the Future Risk Index (removed/unstable).
Build the forward-looking composite ourselves from LOCA2/NEX-GDDP.

### Q3 — MACAv2 / fire-drought: ✅ compute indices ourselves; prefer CMIP6 for scenario consistency
MACAv2-METDATA is ~4 km (1/24°; MACAv2-LIVNEH ~6 km), 20 CMIP5 GCMs under RCP4.5/8.5,
1950-2099. It provides **9 surface met variables** (tasmax, tasmin, rhsmax, rhsmin, huss, pr,
rsds, uas, vas) but **no pre-derived fire/drought indices** — those must be computed.
**gridMET** defines the standard *observational* fire-danger/fuel-moisture indices (ERC, BI,
etc., ~4 km, keyless) but is present-day, not projections. The **NCAR `fire-indices`** repo
computes SPI3, KBDI, Canadian FWI, mFFWI, FM100/FM1000, ERC, BI from downscaled inputs — a
ready Python reference. **Recommendation:** for scenario consistency with the heat/precip
legs, compute the drought/fire indices from **NEX-GDDP-CMIP6 (SSP)** using the NCAR method,
with MACAv2 as a finer-resolution (but CMIP5/RCP) supplement. Cal-Adapt (AWS `cadcat`,
keyless) and USGS GDP are workable access paths; verify per-endpoint (blanket keyless claim
was downgraded 1-2).

### Q4 — CEJST: ⚠️ not suitable as primary crosswalk
CEJST was **taken offline ~Jan 22, 2025** (EO rescission); only an **unofficial archived
mirror** (Public Environmental Data Partners / EDGI) remains, with keyless bulk downloads
(.csv ~42 MB, .xlsx, shapefile; tract `GEOID`). Its Climate-Change category has 5 tract
indicators but only **2 are forward-looking** (First Street projected flood & wildfire risk,
30-yr) and those are **binary ≥90th-percentile flags** derived from a **proprietary** upstream
(First Street). **Recommendation:** not usable as the primary tract crosswalk (removed,
binary, proprietary upstream) — at most an optional cross-check.

### Q5 — Normalization & weighting: ✅ percentile-rank + equal-weight + scenario band
Authoritative reference is the **OECD/JRC Handbook on Constructing Composite Indicators**
(z-score lets extremes dominate; min-max is outlier-sensitive). Impact-Chain risk uses
min-max with clipped min/max thresholds; ND-GAIN and FEMA NRI use min-max with adjustments.
**Recommendation for the sub-score:** normalize each hazard via **national percentile-rank
across all US counties** (robust, distribution-aware, and consistent with how the project
already reports local percentile grades), **equal-weight** the hazard legs as the transparent
OECD-endorsed default (document the weights, leave room for region-aware weighting later), and
report **SSP2-4.5 (low) and SSP5-8.5 (high)** — the spread *is* the uncertainty band, shown
rather than averaged away.

---

## Implementation note — "finer climate resolution" (tract layer ≠ finer signal)

When the tract extension (research plan #1/#3) was implemented, an empirical check of CMRA's
ArcGIS **Tracts** layer (layer 1) overturned its premise. The layer carries **no sub-county
signal** — it broadcasts the parent county's value onto every tract polygon. Verified by
querying all tracts in three large, climatically diverse counties: the projected-hazard
metrics had **zero spread** across tracts, each equal to the bundled county figure:

| County | Tracts | `heat_days95` (RCP4.5 mid) tract min…max | county value |
|---|---|---|---|
| San Bernardino, CA (06071) | 369 | 111.2 … 111.2 | 111.165 |
| Los Angeles, CA (06037) | 2000 | 42.5 … 42.5 | 42.541 |
| Maricopa, AZ (04013) | 916 | 154.2 … 154.2 | 154.244 |

So bundling CMRA's 74,133-tract layer would add ~9&nbsp;MB (gzip ~2.5&nbsp;MB) of redundant data
and a "tract-level" label that does **not** reflect finer accuracy — exactly the false
precision this dimension's caveats forbid. **Decision:** ship the *plumbing* for finer
resolution without the cosmetic data:

- `data/climate_projections.py` is now resolution-aware — `climate_projection_for_tract(geoid)`
  resolves tract&nbsp;→&nbsp;parent county&nbsp;→&nbsp;national average, every result tagged with a
  `geo_level`. It loads `climate_projections_tracts.csv[.gz]` if present; **none is bundled**,
  so tracts resolve at the parent county today.
- `build_climate_projections.py --geo-level tract` reproducibly generates that crosswalk (with
  a loud "no sub-county signal" warning) as a drop-in slot, but its output is intentionally not
  committed.
- `score_climate` and `resolve_location` prefer a tract id when one is available.

**Genuinely finer resolution** requires sampling the LOCA2 ~6&nbsp;km grid (or NEX-GDDP, ClimRR)
at the parcel lat/lon and re-deriving the indices — a separate, network-gated live-refresh
build (research plan #4), not this offline aggregate crosswalk. The roadmap line has been
redirected accordingly.

---

## Implementation note — the ClimRR Fire Weather Index leg (SHIPPED)

The **true Fire Weather Index** leg (Argonne ClimRR, 12&nbsp;km) is now bundled. The earlier
blocker — "the portal is Cloudflare-gated and a 12&nbsp;km FWI grid needs a spatial join, which
the minimal dependency set (requests/pandas/numpy) has no geospatial library for" — was
resolved two ways:

- **Reachable, keyless source.** ClimRR publishes its layers as bulk CSVs on a public Box
  folder (`anl.app.box.com/s/hmkkgkrkzxxocfe9kpgrzk2gfc4gizp8`), reachable via Box's
  unauthenticated shared-file download endpoint — no portal/Cloudflare gate. We use
  *Fire Weather Index (FWI) Classes.csv* (95th-percentile FWI per grid cell, for Historical,
  Mid-Century 2045–2054, and End-Century horizons) plus the companion *GridCellsShapefile.zip*.
- **Spatial join without a geospatial library.** The FWI CSV is keyed by `Crossmodel` grid-cell
  id (`R{row}C{col}`), not lat/lon. The grid shapefile is **EPSG:3857 (Web Mercator)** — which
  the project already converts in `utils.webmercator_to_wgs84`. So a **pure-stdlib** `.shp`/`.dbf`
  parser reads each cell's polygon bounding-box centre, reprojects it to WGS84, and a 0.5° lat/lon
  spatial hash finds the nearest cell at each census tract's internal point (county = the mean of
  its tracts, coherent with the LOCA2 build). No GeoPandas / Shapely / Fiona.

**Band mapping.** ClimRR is CMIP5-era and provides a **single RCP8.5 pathway** (no RCP4.5), so
the mid-century (2045–2054) FWI is applied to *both* the low (SSP2-4.5) and high (SSP5-8.5) bands
— the fire leg contributes no scenario spread. This is defensible because mid-century fire weather
is dominated by the regional baseline fire climatology, not the emissions scenario (e.g. San
Bernardino's FWI is ~47 in both Historical and Mid-Century); the RCP4.5↔SSP2-4.5 / RCP8.5↔SSP5-8.5
analogy is the same coarse mapping the CMRA source used, kept clearly labeled.

**Scoring.** `fire_fwi` becomes a fourth equal-weight leg (`fire`) in `data/climate_projections.py`,
with breakpoints anchored to the national **county** quantiles of the mid-century FWI
(p5=6.3 … p95=37.7; higher FWI → lower score). Fire-prone desert counties (San Bernardino,
Maricopa) now score ~0 on the fire leg while humid eastern counties (Memphis, Chicago) score ~60.

**Coverage / graceful degradation.** ClimRR's grid covers CONUS + Alaska but **not Hawaii /
Puerto Rico**; `_band_score` skips a leg with no data rather than nulling the whole score, so
those geographies score from the remaining three legs. Built by
`scripts/build_climate_projections.py --source fwi`, which augments the existing county/tract
crosswalks in place with `fire_fwi_{hist,low,high}` (small ~12&nbsp;MB download, no `[build]` extra).

---

## Implementation note — LOCA2 sub-county build (the genuinely finer path)

A follow-up build (`scripts/build_climate_projections.py --source loca2`) implements the real
sub-county resolution the CMRA tract layer couldn't provide. Two findings shaped it:

- **No keyless LOCA2 point API.** A live per-lat/lon refresh isn't viable: the only keyless,
  requests-only CONUS point services are historical (USGS GDP pygeoapi, gridMET) or coarser
  (NEX-GDDP ~25 km via awkward OPeNDAP); native LOCA2 (~6 km) is bulk NetCDF needing xarray.
- **Single-model point samples aren't defensible.** Regional internal variability dominates;
  a defensible value needs a multi-model **ensemble mean** (why CMRA uses one).

So the chosen vehicle is an **offline build → bundled tract crosswalk** using a pre-derived
ensemble mean, sampled at build time.

**Verified source (keyless):** USGS *CMIP6-LOCA2 threshold/extreme-event metric projections*
(DOI [10.5066/P13OV6GY](https://doi.org/10.5066/P13OV6GY), ScienceBase `65cd1ff2…`). The
**Weighted Multi-Model Mean (WMMM)** annual 1/16° (~6 km) CONUS grid, one NetCDF per SSP
(**~2.6 GB each** — the 171 MB files are county-aggregated, no sub-county signal). Variable map
(units from the FGDC metadata): `TXge95F`, `TXge100F`, `R1in`, `Rx5day` (mm → ÷25.4 to inches),
`CDD`. Grid 944×474, negative-west longitude. There is **no SSP-labeled mid-century gridded
*climatology*** (those are MMM, historical/GWL only), so we cut windows from the WMMM time
series ourselves: `hist` = 1991–2020, `low` = ssp245 2040–2069, `high` = ssp585 2040–2069.

**Pipeline:** download the two WMMM grids + the Census Gazetteer tract/county internal points
(keyless), nearest-cell sample each tract's internal point (numpy; bbox guard + NaN ring
fallback for coastal cells), and set each county value to the **mean of its tracts** (so
tract→county is coherent). Writes both `climate_projections.csv` and
`climate_projections_tracts.csv.gz` in the existing schema. xarray/netCDF4 are imported only
inside the loca2 branch and declared under the `[build]` extra — runtime stays
requests/pandas/numpy and offline.

**Validated** (`tests/test_build_loca2.py` + an in-session synthetic-grid run): the pure
sampling/aggregation core (intra-county spread now *exists* — the inverse of the CMRA finding —
plus tract→county coherence, schema, bbox/NaN handling), the xarray reader against a synthetic
NetCDF, and the Gazetteer loader + ScienceBase URL resolver against live endpoints.

**Completed (national build run):** the full build was run on a capable machine
(~5.2 GB download + the `[build]` extra), producing **3,109 counties** and **85,396 tracts**
(the ~120 missing counties are non-CONUS / all-water and fall back to the national average).
Two build bugs surfaced and were fixed during the run: the ScienceBase download URL (the
`manager/download/<id>` route served an HTML page — switched to `catalog/file/get?name=`, with a
validation guard) and the **0–360 longitude convention** (the grid stores lon as 234.5…293.5,
so every CONUS point collapsed to the western ocean edge → all-blank output; normalized to
negative-west at read time). The bundled crosswalks are now CMIP6-LOCA2, the `_BREAKPOINTS` are
re-anchored to the printed SSP2-4.5 national quantiles, and `DATA_VINTAGE` is CMIP6/SSP. San
Bernardino tracts show real intra-county spread, confirming genuine sub-county signal.

---

## Verification provenance

Deep-research run: 5 search angles → 25 sources fetched → 89 claims extracted → 25 verified
under 3-vote adversarial check (24 confirmed, 1 refuted — a false CC-BY-SA license claim was
killed; CC0 confirmed). Key primary sources:

- NASA NEX-GDDP-CMIP6 — AWS Open Data registry; Thrasher et al. 2022, *Nature Sci. Data*
  (s41597-022-01393-4); NCCS data collection page.
- CMRA / CRIS data-sources page (`resilience.climate.gov/pages/data-sources`).
- USGS CMIP6-LOCA2 release (DOI 10.5066/P9DWN1XL, CC0).
- Argonne ClimRR (`anl.gov/ccrds/ClimRR`).
- NOAA Digital Coast CMRA tool; CEJST downloads.
