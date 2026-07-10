# Strengthening the Data-Source Methodology (Beyond Shelby, Open-Data Only)

> **Deliverable:** research memo — no code changes in this document.
> **Date:** 2026-07-10
> **Constraint honored throughout:** open, keyless, redistributable, national-coverage
> data only. No commercial parcel data (Regrid / ATTOM / CoreLogic). No
> license-restricted APIs that forbid caching/storage (e.g. Walk Score).
> **Method:** a fresh per-dimension inventory of the *current* live product (Path B
> simulator/API), followed by a fan-out, adversarially-verified web-research pass
> (109 sub-agents, 26 primary sources fetched, 25 falsifiable claims verified by
> 3-vote majority; 24 confirmed, 1 refuted).

---

## TL;DR — what to change, in priority order

| # | Dimension | Change | Resolution gain | Effort | License |
|---|-----------|--------|-----------------|--------|---------|
| 1 | **Disaster Resilience (seismic)** | Replace the constant `0.43` 10%/50yr ratio with true return-period values from the **2023 USGS NSHM hazard curves** | site-level curves | Medium (new bulk ingest) | Public domain |
| 2 | **Infrastructure Burden** | Swap county-aggregate finance for the **2022 Census of Governments Individual Unit File** (per-government-unit records) | sub-county (per local government) | High (unit→geography crosswalk) | Public domain |
| 3 | **Energy Efficiency** | Add a **DOE/NREL LEAD 2022** census-tract crosswalk; refresh archetype benchmarks from **NREL End-Use Load Profiles (ResStock 2025)** | tract (LEAD) / county (ResStock) | Low–Medium (crosswalk swap) | Public domain / Apache-2.0 |
| 4 | **Environmental Footprint** | Add **NREL Cambium 2023 LRMER** marginal grid-emissions signal alongside eGRID average | 18 GEA regions | Low (crosswalk add) | CC BY 4.0 (attribution) |
| 5 | **Disaster Resilience (tornado/wildfire)** | Consolidate onto **FEMA NRI Dec-2025 v1.20** ready-made EAL layers; adopt **NRI Future Risk** (CMIP6/SSP) for the fire projection leg | tract | Low (drop-in crosswalk) | Public domain |
| 6 | **Environmental (embodied carbon)** | Do **NOT** adopt EC3 — account-gated, non-redistributable. Keep the Jungclaus band; seek a redistributable LCA source (open question). | — | — | ⚠️ license trap |

Health, Socioeconomic, Walkability, and Climate Projections are already the
strong, tract-native, national-percentile links and need no source change — only
the rigor upgrades in §C.

---

## Part 0 — Current methodology inventory (baseline being improved)

The live product (`src/housing_label/simulate/` + `api.py`) scores 9 dimensions.
Grading everywhere: **national grade** = absolute thresholds (A≥80 / B≥60 / C≥40 /
D≥20 / F<20); **local grade** = within-dataset percentile bands (only meaningful in
the Shelby batch path). Ranked from strongest to weakest data footing:

**Strong (tract-native, national-percentile, 2021–2023 vintage) — leave the source alone:**
- **Health Impact** — CDC PLACES 2023 (BRFSS, 7 chronic-disease measures), tract → county → US.
- **Socioeconomic** — Census ACS 5-yr 2023 (poverty B17001, income B19013, cost-burden B25106), tract.
- **Walkability** — EPA National Walkability Index / Smart Location DB v3 2021, block-group native.
- **Climate Projections** — USGS CMIP6-LOCA2 mid-century 2040-69 SSP2-4.5/SSP5-8.5 (~6 km, tract) + Argonne ClimRR Fire Weather Index (12 km, RCP8.5).

**Weak links (the target of this memo):**
- **Infrastructure Burden** *(weakest)* — county-only on both sides (Census of Governments 2022 cost level; ACS 2022 property-tax revenue); cost-curve *shape* still **Memphis FY2026-calibrated**; ±30% self-declared uncertainty; single-dwelling-unit assumption.
- **Environmental Footprint** — operational grid factor eGRID2022 at **county** resolution; embodied-carbon leg (Jungclaus et al. 2024 by wall type) **flagged LOW CONFIDENCE** in code; water embedded-energy is a flat national `8 kWh/kgal` constant.
- **Energy Efficiency** — fully **modeled** EUI, no measured signal; only geographic inputs are IECC zone (county) + state utility rates (electricity 2020).
- **Disaster Resilience — seismic leg** — 10%/50yr PGA derived from a **constant national `0.43` ratio** off the 2%/50yr value.
- **Durability** — no geographic data source at all; a pure config/CAMA lifespan model (InterNACHI + NAHB/BofA 2007 + Fannie Mae schedules).

**Oldest vintages:** DOE Building America HSP 2014, EIA RECS 2020 / electricity rates 2020, NAHB/BofA component-life 2007, Halifax "Cost of Sprawl" 2004, Ashley 2007 tornado EF calibration; eGRID2022 / CoG 2022 / ACS 2022 are one cycle behind the 2023 ACS used by Health/Socio.

---

## Part A — Stronger sources for the weak dimensions (verified)

### A1. Disaster Resilience — seismic: kill the `0.43` constant ✅ *(highest-rigor win)*

**Source: 2023 USGS National Seismic Hazard Model (NSHM) + USGS ASCE 7-22 Design Ground Motions web service.**
- **Publisher / license:** USGS — **public domain**.
- **What it fixes:** the NSHM publishes **full hazard curves at hundreds of thousands of sites**, "best defined for return periods between about 475 and 10,000 years" (Petersen et al. 2024, *Earthquake Spectra*). Both target exceedance levels — true 10%/50yr (~475 yr) and 2%/50yr (~2,475 yr) — can be **read directly** off the curve instead of derived from a fixed `0.43` ratio.
- **Access:** two options with different effort/precision tradeoffs —
  - *Keyless API (drop-in, but design values):* USGS Design Ground Motions portal — verified live 2026-07-10, `/ws/building-codes/asce7-22/calculate` returned HTTP 200 JSON, no key (the old `/ws/designmaps` path 301-redirects). **Caveat:** it returns *risk-targeted MCE design parameters*, not raw 10%/50yr exceedance values.
  - *Bulk hazard-curve data release (heavier, but exact):* the NSHM ScienceBase/data.gov release gives gridded hazard curves at 21 spectral periods × 8 site classes — the correct source for a true return-period read-off.
- **⚠️ Coverage caveat (a claim the research *refuted*):** do **not** assume the "50-state" model's CONUS bounds cover Alaska + Hawaii + territories in one file. The 0-3 refuted claim was exactly an over-broad "national bounds" statement — the 50-state model is delivered as **separate regional releases** (CONUS, Alaska, Hawaii, territorial NSHMs). Plan the ingest per-region, and keep a national fallback for any point that misses.
- **Effort:** Medium (bulk-curve ingest → new tract/point crosswalk) for the exact path; Low if you accept design-parameter values from the keyless API.

### A2. Infrastructure Burden — sub-county municipal finance ✅ *(fixes the weakest link)*

**Source: 2022 Census of Governments — Individual Unit File.**
- **Publisher / license:** U.S. Census Bureau — **public domain**, bulk download.
- **What it fixes:** the current pipeline uses only **county aggregates**. The Individual Unit File ships **per-government-unit finance records** ("government unit code, item code and amount for all respondent records"), i.e. finance at the level of **individual cities, townships, special districts, and school districts** — the sub-county signal the dimension entirely lacks today. Each unit code maps to a specific government via the Census government directory, allowing place/county assignment.
- **Effort:** High. Records are per-government-unit, **not per-parcel**, so they require crosswalking government units → service areas/geographies. This fixes the finance **level** and revenue side; it does **not** by itself fix the cost-curve **shape** (still Memphis FY2026-calibrated — see open questions).
- **Complementary source (context, not a bundle):** the Lincoln Institute **Fiscally Standardized Cities (FiSC)** database standardizes overlapping-government finances for ~150 large cities — useful for *validating* a national method, though its coverage is limited to major cities.

### A3. Energy Efficiency — add real geographic signal ✅

Two complementary federal products, both cleanly licensed:

**(a) DOE/NREL LEAD Tool — 2022 Update** *(the finest geography)*
- **Publisher / license:** DOE/NREL — **public domain** (data.gov / OpenEI / Zenodo).
- **Resolution / coverage:** **census tract** (also cities, counties, tribal areas), **50 states + PR + DC** — territories covered, unlike ResStock.
- **What it adds:** estimated household **income, energy expenditures, fuel type, housing type** per tract; built on 2022 ACS 5-yr PUMS calibrated to 2022 EIA Form-861/Form-176 utility data. This is the **strongest available sub-county energy signal**. *Modeled/estimated, not metered* — keep labeling it as modeled.
- **Effort:** Low (tract crosswalk swap).

**(b) NREL End-Use Load Profiles (ResStock / ComStock) — 2025 Release 1** *(fresher archetype benchmarks)*
- **Publisher / license:** NREL/DOE — **Apache-2.0** (redistributable, attribution, no share-alike/caching trap).
- **Access:** **keyless** anonymous S3 — `aws s3 ls --no-sign-request s3://oedi-data-lake/nrel-pds-building-stock/` (us-west-2, "No AWS account required").
- **What it adds:** calibrated, **validated 15-minute** load profiles from a bottom-up EnergyPlus physics model, validated against utility load-research / AMI / submetered end-use data. A far more current and better-validated replacement for the **RECS 2020** archetype medians the EUI model uses today.
- **Resolution caveat:** finest published geography is the **county** (~3,100 counties) — **no sub-county gain** over what the energy model already keys on (IECC zone ≈ county). Excludes PR/Guam. So this is a **currency + validation** upgrade, not a resolution upgrade.
- **Effort:** Low–Medium (refresh benchmark tables).

### A4. Environmental Footprint — marginal grid emissions ✅ + an embodied-carbon trap ⚠️

**(a) ADD — NREL Cambium 2023 Long-Run Marginal Emission Rates (LRMER).**
- **Publisher / license:** NREL/DOE — **CC BY 4.0** (redistributable **with attribution**; no share-alike).
- **What it adds:** **marginal** (induced/avoided) emissions — "the rate of emissions that would be either induced or avoided by a change in electric demand," accounting for grid operations *and* infrastructure. eGRID's **average** rates structurally cannot represent this. LRMER is the right factor for "what does one more/less kWh here actually cost the grid," which is the more decision-relevant signal for an efficiency-linked footprint.
- **Resolution:** **18 GEA regions** (CONUS only) with bundled ZIP/county crosswalks — **coarser** than county-level eGRID, so Cambium **supplements** (adds a marginal leg) rather than replaces eGRID. Bulk workbook download, no API.
- **Effort:** Low (add a region crosswalk + a second emissions leg).

**(b) DO NOT ADOPT — EC3 (Building Transparency) for embodied carbon.** ⚠️ **License trap.**
- EC3 is described as "the only free and open-access global embodied carbon accounting tool" (150k+ EPDs), but **"free" ≠ keyless**: all core functionality is gated behind **Login/Sign Up**, and even the EPD API needs a **bearer token**. It provides **no bulk redistributable export**. It therefore **fails both the keyless and redistributable constraints** and cannot go in the live product.
- **Consequence:** keep the current Jungclaus et al. 2024 band (LOW CONFIDENCE) for now; the real fix is a *redistributable* LCA dataset — see open questions.

### A5. Disaster Resilience — tornado + wildfire consolidation ✅

**Source: FEMA National Risk Index (NRI) — December 2025, v1.20.**
- **Publisher / license:** FEMA — **public domain**; bulk CSV / Shapefile / Geodatabase at **county *and* census-tract** level.
- **What it offers:** ready-made **Expected Annual Loss** layers for **18 hazards including tornado, earthquake, and wildfire**. Adopting the NRI tornado + wildfire EAL layers would:
  - Replace the bespoke **NOAA SPC 25-mile-count** tornado model whose EF distribution is calibrated to the **Mid-South (Ashley 2007)** and applied nationally — a known national-honesty weakness.
  - Give a consistent, FEMA-modeled, tract-level loss basis across hazards (drop-in crosswalk).
- **Future fire leg — NRI Future Risk (Dec 2024):** uses **NASA-NEX statistically-downscaled CMIP6** Fire Weather Index under **SSP2-4.5 / SSP5-8.5** at 30-arcsec, published at county + tract. This is a **newer pathway** (CMIP6/SSP) than the current Argonne **ClimRR RCP8.5 12 km** fire leg — a candidate upgrade for the Climate Projections fire leg. *(The tract-level future-fire availability was the one 2-1 claim — verify the exact file before committing.)*
- **⚠️ Hard boundary:** NRI Future Risk **explicitly excludes earthquake** ("no direct climatological correlation"). **There is no future-seismic product** — seismic must stay on USGS NSHM (§A1). Don't try to source seismic from NRI.
- **Effort:** Low (drop-in tract crosswalks). **Tradeoff:** NRI EAL are FEMA-modeled composites — adopting them trades your bespoke per-hazard models for consistency + currency + national honesty; label as modeled.

---

## Part B — New authoritative datasets worth considering

- **USFS "Wildfire Risk to Communities" (Pyrologix, May 2024 + May 2025 refresh)** — national burn-probability + intensity layers; a finer, present-day wildfire complement to NRI's wildfire EAL for the fire leg.
- **NASA NEX-GDDP-CMIP6 v2** — keyless anonymous S3 (`registry.opendata.aws/nex-gddp-cmip6/`); the downscaled climate base layer behind NRI Future Risk. Only worth the lift if you want to compute custom climate metrics beyond the USGS LOCA2 set already bundled.
- **FEMA USA Structures** (FEMA + ORNL + USGS; ~125M+ footprints >450 sqft with occupancy type) and **Microsoft US Building Footprints** — structure-level, keyless/redistributable footprint layers. Not a scoring dimension themselves, but they can *de-risk the Durability and Infrastructure single-dwelling-unit assumptions* by supplying building count/footprint per parcel. *(Note: the FEMA hub page fetched as unreliable/403 in this run — verify the current download endpoint before relying on it.)*
- **Durability** remains the one dimension with **no authoritative geographic source found** in this pass. There is no national open dataset of roof/HVAC/re-pipe ages. The realistic upgrade path stays what the code already flags: open **building-permit** records (highly heterogeneous, per-jurisdiction) — a Path-A-style effort, deferred.

---

## Part C — Methodology-rigor best practices (peer open indices)

Sources fetched: EPA EJScreen Tech Doc v2.3 (2024), CDC PLACES methodology, FEMA NRI
methodology, an SVI/small-area methods paper. *(Caveat: this leg was referenced more
than deeply verified — treat as directional, confirm against the primary PDFs before
coding.)*

1. **Percentile calibration — match the reference population to the claim.** EJScreen
   converts raw indicator values to 0–100 **national *and* state** percentiles and
   always names which. The label already does national percentiles for the strong
   dimensions; the rigor step is to **name the reference population and its vintage on
   every percentile shown** and never mix a within-Shelby percentile with national
   language.
2. **Housing-unit vs tract weighting.** Peer indices weight by the *unit of interest*.
   For a *housing* label, a "share of US **homes** below this value" (housing-unit- or
   household-weighted) is more honest than "share of **tracts**." The codebase already
   does household/housing-unit weighting for Health/Socio/Walkability — extend the same
   weighting to any new percentile (e.g. an infrastructure percentile).
3. **Small-area uncertainty.** ACS/PLACES tract estimates are **modeled** with real
   margins of error, largest in small tracts. Best practice (SVI, EJScreen): **suppress
   or widen** estimates below a reliability threshold rather than showing a false-precise
   point. The socio loader already leaves too-sparse tracts unscored — generalize that to
   a documented reliability rule and, where possible, **surface a confidence band**, not
   just a point score.
4. **Modeled-vs-measured honesty (non-negotiable).** *Every* recommended source here —
   ResStock, LEAD, Cambium LRMER, NRI EAL, NSHM curves — is **modeled/estimated**, not
   metered. Keep the label's existing modeled-value captions and apply them to each new
   leg. This is the same guardrail that kept the project out of the "Zillow pulled the
   climate scores" failure mode.

---

## Part D — Integration effort & license summary

| Source | Redistributable? | Keyless? | License trap | Effort |
|--------|------------------|----------|--------------|--------|
| USGS 2023 NSHM / ASCE 7-22 service | ✅ public domain | ✅ (API) / bulk | Regional files, not one national file; API returns *design* not *exceedance* values | Med (bulk) / Low (API) |
| 2022 CoG Individual Unit File | ✅ public domain | n/a (bulk) | Per-unit, needs government→geography crosswalk | High |
| NREL LEAD 2022 | ✅ public domain | n/a (bulk) | LMI-focused; modeled | Low |
| NREL ResStock 2025 (EULP) | ✅ Apache-2.0 | ✅ anon S3 | Attribution; county-only; no PR/Guam | Low–Med |
| NREL Cambium 2023 LRMER | ✅ CC BY 4.0 | n/a (bulk) | **Attribution required**; 18-region CONUS-only; supplements not replaces eGRID | Low |
| FEMA NRI v1.20 + Future Risk | ✅ public domain | n/a (bulk) | Modeled composites; **no future seismic**; verify tract future-fire file | Low |
| **EC3 (embodied carbon)** | ❌ | ❌ token-gated | **Fails both constraints — do not use** | — |

**Attribution obligations to honor if adopted:** ResStock (Apache-2.0) and Cambium
(CC BY 4.0) both require attribution — add them to the methodology page's data-credits.
USGS, FEMA NRI, LEAD, and Census of Governments are federal public domain (no
attribution obligation, though crediting is good practice).

---

## Open questions (carry into implementation)

1. **Embodied carbon without EC3:** what *redistributable, keyless* LCA dataset (e.g.
   NIST BEES, the Quartz Project open data, or a bulk EPD export) can replace the
   LOW-CONFIDENCE Jungclaus band?
2. **Energy below county:** ResStock notes tracts are "tracked internally" but 2020 codes
   aren't published — is there an obtainable ResStock tract crosswalk to push energy below
   county, or does LEAD remain the only tract-level energy signal?
3. **Infrastructure cost-curve shape:** the CoG Individual Unit File fixes the finance
   *level/revenue* but not the per-parcel *cost-to-serve curve* (still Memphis-calibrated).
   What is the defensible **national** basis for the curve shape?
4. **Rigor specifics:** which exact small-area uncertainty-quantification and
   housing-unit-weighting formulas from EJScreen / SVI / First Street should the label
   adopt for confidence intervals on modeled tract estimates? (Part C needs a
   primary-source deep read before coding.)

---

## Suggested sequencing

1. **Seismic `0.43` → NSHM** (A1) — highest rigor-per-effort; removes an indefensible constant.
2. **NRI tornado/wildfire consolidation** (A5) — low effort, drop-in, removes the Mid-South-calibrated tornado national-honesty problem.
3. **Energy: LEAD tract crosswalk + ResStock benchmark refresh** (A3) — low effort, adds real sub-county energy signal + currency.
4. **Environmental: Cambium marginal leg** (A4a) — low effort, adds a decision-relevant emissions signal.
5. **Infrastructure: CoG Individual Unit File** (A2) — highest value on the weakest dimension, but the biggest lift; schedule deliberately.
6. **Durability + embodied carbon** — leave as-is with honest modeled captions until a redistributable source appears (open questions 1 & the permit-records path).

---

### Sources (primary, verified)

- NREL End-Use Load Profiles — <https://registry.opendata.aws/nrel-pds-building-stock/> · ResStock 2025 Technical Reference Guide (OEDI S3)
- DOE/NREL LEAD 2022 — <https://www.osti.gov/dataexplorer/biblio/dataset/2504170> · <https://data.openei.org/submissions/6219>
- NREL Cambium 2023 LRMER — <https://data.openei.org/submissions/8279> · <https://www.osti.gov/biblio/2305481>
- EC3 (license trap) — <https://www.buildingtransparency.org/tools/ec3/>
- USGS 2023 NSHM — <https://www.usgs.gov/publications/2023-us-50-state-national-seismic-hazard-model-overview-and-implications> · <https://catalog.data.gov/dataset/data-release-for-the-2023-u-s-50-state-national-seismic-hazard-model-overview>
- USGS Design Ground Motions Portal — <https://www.usgs.gov/programs/earthquake-hazards/design-ground-motions-portal>
- FEMA NRI — <https://www.fema.gov/about/openfema/data-sets/national-risk-index-data> · NRI Future Risk Technical Doc — <https://eelp.law.harvard.edu/wp-content/uploads/2025/03/NRI_Future_Risk_Technical_Document.pdf>
- 2022 Census of Governments (Individual Unit File) — <https://www.census.gov/data/datasets/2022/econ/local/public-use-datasets.html>
- EJScreen Tech Doc v2.3 — <https://www.epa.gov/system/files/documents/2024-07/ejscreen-tech-doc-version-2-3.pdf>
- CDC PLACES methodology — <https://www.cdc.gov/places/methodology/index.html>
- USFS Wildfire Risk to Communities — <https://www.fs.usda.gov/managing-land/fire/wildfirerisk>
- NASA NEX-GDDP-CMIP6 — <https://registry.opendata.aws/nex-gddp-cmip6/>

*Verification: 25 falsifiable claims put through 3-vote adversarial checking; 24
confirmed, 1 refuted (the over-broad USGS "national bounds" claim — see §A1 caveat).
Parts A, B, and D are strongly evidenced; Part C is directional and should be confirmed
against the primary methodology PDFs before implementation.*
