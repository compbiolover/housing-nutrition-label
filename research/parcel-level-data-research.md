# Parcel-Level Property Facts — How Far Can Auto-Detection Actually Go?

> **Deliverable:** research memo — no code changes in this document.
> **Date:** 2026-08-03
> **Question this answers:** today most construction inputs are either county/tract
> averages presented as if they described a house, or modeled national datasets (USACE
> NSI, FEMA/ORNL USA Structures) that are frequently wrong for an individual parcel.
> Zillow shows an exact year built and a heating system, so the data exists somewhere.
> **How far can we get toward true parcel/address-level facts by auto-detection, at
> national scale, without breaking the project's constraints?**
> **Constraints being tested throughout:** MIT-licensed open-source repo, free public
> website, results are **cached and bundled offline**, national coverage, keyless where
> possible. A source that forbids caching, redistribution, or derivative works is close
> to useless here — so licensing is treated as the primary axis, not an afterthought.
> **Method:** primary-source verification. Vendor marketing pages were not accepted as
> evidence of terms; the actual license agreements were fetched and quoted. Coverage
> claims were checked against machine-readable coverage reports and live API probes
> (all probes run 2026-08-03 and noted inline).

---

## TL;DR

**The ceiling on auto-detection is set by county assessors, and it is lower than Zillow
makes it look.** Zillow's year-built and heating-system fields come from ~3,000 county
CAMA systems purchased in bulk under contracts the project cannot match and cannot
comply with. The best commercial aggregate of those same records — Regrid, 160.6M
parcels, 100% of counties — carries **year built for only 67% of US parcels, living
area for 65%, bedrooms for 47%, and the actual annual tax bill for 15%** (verified
against Regrid's own published coverage report, below). And **no national aggregator
carries exterior wall, roof material, foundation type, or heating fuel at all** —
those fields exist in county CAMA extracts but are not standardized into any national
schema.

So the honest answer splits three ways:

| Tier | Attributes | Realistic national auto-detection |
|---|---|---|
| **Solved, free, today** | incorporated-municipality status, parcel↔building footprint & footprint area, water-system service area (municipal vs. likely-well), sewershed (sewer vs. likely-septic), electric utility provider, well proximity | **~95–100%**, public domain / permissive, keyless, cacheable |
| **Solved but paid or per-county** | year built, living area, stories, beds/baths, lot acreage, assessed & market value | **~65–87%** nationally via Regrid; **~100%** in the specific states/counties that publish CAMA openly (FL, CT, MA, WI, NC, DC, Cook County IL, NYC, TX CADs) |
| **Not solved at any price nationally** | exterior wall, foundation type, roof material, **roof age**, heating/cooling type & fuel, actual tax paid, permit history (free), actual utility consumption | **irreducibly user-supplied** outside a hand-built list of open-CAMA counties |

**The single highest-value action is free and takes an afternoon:** stop using NSI
`med_yr_blt` as a year built (its own documentation calls it *"the median year built of
structures within the Census tract"*), and wire up four public-domain point-in-polygon
lookups that answer real parcel questions the project currently answers with county
averages — Census Places (incorporated?), EPA CWS Service Area Boundaries (on a
community water system?), EPA National Sewersheds (on sewer?), and HIFLD/NREL (which
utility?).

**The single highest-value *uncertain* action is Regrid's "Data With Purpose"
program**, which offers a **free one-time nationwide Standard-schema bulk snapshot** to
non-business research/nonprofit projects. That would deliver year built + living area +
value + exact lot geometry nationally at zero cost. ⚠️ **Its license terms are not
published** and the standard Data Store license would forbid bundling the result into
the public MIT repo. Verify before building on it. See §5.

---

## Part 0 — What is wrong today, restated precisely

The four failures named in the brief are all the same failure: **an area statistic
wearing a parcel's clothes.** Worth separating them because the fixes differ.

| Observed failure | Actual cause | Fixable by auto-detection? |
|---|---|---|
| NSI types a rural farmhouse as agricultural | NSI occupancy is *modeled* from parcel data where available, otherwise "estimated from regional distributions, Census data, and rule-based assignments" (NSI technical documentation) | **Partly.** Assessor use-code is the ground truth and is 71% populated nationally in Regrid (`usecode_pct`). Free in open-CAMA states. |
| NSI `med_yr_blt` presented as year built | It is documented as *"the median year built of structures within the Census tract"* — a tract median, never a structure fact | **Yes, where assessor year built exists (67% of parcels).** Elsewhere the honest output is "unknown", not a median. |
| County CWS compliance shown for a house on a private well | SDWIS is system-level; the project has no parcel→system link | **Yes, ~99% of CWS-served population.** EPA's Service Area Boundaries layer is exactly this join. See §3.1. |
| County-average local-government spending drives a parcel's infrastructure burden | Census of Governments is per-government-unit, not per-parcel | **Partly.** The incorporated/unincorporated question is fully solvable and free (§3.4); the actual tax bill is not (15% national coverage). |

A structural recommendation before any data changes: **every attribute the label
consumes should carry a provenance tag** — `observed(assessor)` / `modeled(NSI)` /
`area-average(tract|county)` / `user-supplied` / `unknown` — and the existing
per-dimension confidence machinery should read it. Most of the damage above is not that
a modeled value was used, but that a modeled value was displayed as a fact.

---

## Part 1 — Per-attribute verdict table

Read this as: *what can be known about a specific US house, by automated lookup.*

| # | Attribute | Best FREE source | Best PAID source | Genuinely unobtainable |
|---|---|---|---|---|
| 1 | **Year built (exact)** | Open state/county CAMA (FL DOR NAL statewide; CT, MA, WI, NC, NY-36, DC, Cook Co, NYC PLUTO, TX CADs) — 100% where published | Regrid `yearbuilt` — **67% of US parcels**, median **87%** in the 100 largest counties | The ~33% of parcels in counties that publish no year built (508 counties at 0%; PR, IL, ND, WI, LA, MI, AK worst) |
| 2 | **Living area / sq ft** | Same open CAMA sources; footprint area from MS/Overture footprints as a weak proxy | Regrid `area_building` — **65%**; `ll_bldg_footprint_sqft` (premium) — 77% | Finished vs. unfinished basement, conditioned floor area, ceiling height |
| 3 | **Exterior wall / construction type** | **Only** county CAMA in the minority of counties that publish it (Cook Co `char_ext_wall`, DC CAMA, TX CADs) | **None.** Not in Regrid's schema; not in ATTOM/CoreLogic standard national feeds in a usable normalized form | Nationally: yes, unobtainable. **User input.** |
| 4 | **Foundation type** | County CAMA (`char_bsmt` in Cook Co); NSI `found_type` as a modeled fallback (explicitly imputed from EIA/AHS/HAZUS where parcel data absent) | **None national** | Nationally: yes. **User input**, with an NSI/ResStock regional prior. |
| 5 | **Roof material** | County CAMA (Cook Co `char_roof_cnst`, TX CADs, FL county rolls) | Cape Analytics / EagleView / Verisk — CV over aerial imagery, 110–200M structures | Nationally free: yes. |
| 5b | **Roof age** | **Nothing.** Permit history is the only inferential path | Cape Analytics "Roof Age" (200M+ structures, API); Shovels/permit reroof records | Effectively **user input**. The industry itself treats roof age as hard: Cape's own marketing is built around it being unavailable. |
| 6 | **Heating / cooling type & fuel** | County CAMA (Cook Co `char_heat`/`char_air`, DC CAMA heat type); ACS **B25040** house-heating-fuel is *tract-level*, an area average — do not present as a parcel fact | **None national** in aggregator schemas | Nationally: yes. **User input**, with a ResStock/RECS archetype prior. |
| 7 | **Stories / beds / baths** | Open CAMA counties | Regrid: `numstories` **60%**, `num_bath` **56%**, `num_bedrooms` **47%**, `numrooms` 32% | Half of US parcels have no published bedroom count. |
| 8 | **Lot size & parcel geometry** | County/state GIS parcel layers (free in ~15–20 states statewide); Regrid computes it universally | Regrid `ll_gisacre` / `ll_gissqft` — **100%** (Regrid-calculated from geometry, not county-reported); county-reported `gisacre` 70%, `deeded_acres` 8% | Nothing — this is the best-covered attribute in the entire stack. |
| 9 | **Assessed / market value** | Open CAMA counties; state DOR rolls (FL NAL) | Regrid `parval` **87%**, `landval` 80%, `improvval` 76% | Meaning is not comparable across counties (assessment ratios, caps, exemptions differ) — a known trap already documented in `property-tax-classification-research.md`. |
| 10 | **Actual property tax paid** | Essentially nothing at scale — county treasurer sites, per-county scraping | Regrid `taxamt` — **15%** of parcels; **median 0%** in the 100 largest counties | **Yes — treat as unobtainable.** Keep the ACS county effective-rate model already shipping, and label it as modeled. |
| 11 | **Water source (municipal vs. well)** | **EPA Public Water System Service Areas v3** (44k+ CWS, 99% of CWS-served population, all 50 states + DC + territories + tribal) + **USGWD** 14.2M well records (CC BY) + FL FLWMI parcel-level | — | Definitive per-parcel confirmation. EPA explicitly says use it "as a first step". |
| 11b | **Sewer vs. septic** | **EPA National Sewersheds** (~17,000 POTWs, ~78% of 2020 census population); state layers (MassDEP sewer service areas, DE, FL FLWMI, King Co WA) | — | The ~22% outside a mapped sewershed is *ambiguous* (unmapped vs. septic), not proof of septic. |
| 12 | **Inside an incorporated municipality?** | **Census TIGER/Line PLACE + Census Geocoder / TIGERweb** — keyless, public domain, definitive | — | **Nothing. This one is fully solved.** See §3.4. |
| 13 | **Permit history (roof, HVAC, addition, solar)** | Large-city/large-county open data portals only (NYC DOB, Chicago, LA, Austin, SF…); **Census Building Permits Survey is aggregate-only** (state/CBSA/county/place — no addresses) | Shovels.ai — 2,450+ jurisdictions, ~85% of US population, ~$599/mo entry; BuildZoom; PermitStack | Free national permit history: **does not exist**. |
| 14 | **Utility provider** | **HIFLD Electric Retail Service Territories** (polygons, usa.gov government-works license) + **NREL "U.S. Electric Utility Companies and Rates: Look-up by Zip Code"** (public domain, keyless) | — | Nothing significant. |
| 14b | **Actual utility consumption** | **None.** Green Button *Connect My Data* requires the homeowner to OAuth-authorize, and is only implemented by the CA IOUs and ComEd | UtilityAPI (still requires homeowner authorization) | **Irreducibly user-supplied and consent-gated.** No lawful path to another household's meter data. |

---

## Part 2 — The hard number: what national parcel coverage actually looks like

Regrid publishes a machine-readable coverage report. It is the single most useful
document in this whole research area, because it converts "we have 100% national
coverage" (true, for geometry) into per-field truth (much worse). Downloaded and parsed
2026-08-03 from the sheet linked off every county store page:

`https://docs.google.com/spreadsheets/d/1rvRYv6_ppZlwbmyi2kbzemot6FOEm2EEPdHPyENTQPE/`
(CSV export works keylessly; 1.7 MB; 3,231 county rows + a nationwide summary row.)

**Nationwide dataset, 160,583,756 parcels:**

| Field | National fill | Counties ≥80% | Counties at 0% | Median in 100 largest counties |
|---|---|---|---|---|
| `ll_gisacre` / `ll_gissqft` (Regrid-computed lot area) | **100%** | — | 0 | 100% |
| `parval` (total parcel value) | 87% | 2,454 | 661 | — |
| `landval` | 80% | — | — | — |
| `saledate` | 80% | — | — | — |
| `improvval` | 76% | — | — | — |
| `ll_bldg_footprint_sqft` (premium) | 77% | — | — | — |
| `usecode` | 71% | — | — | — |
| **`yearbuilt`** | **67%** | 363 | **380** | **87%** |
| **`area_building`** | **65%** | 290 | 421 | **84%** |
| `numstories` | 60% | 372 | 709 | — |
| `num_bath` | 56% | — | — | — |
| **`num_bedrooms`** | **47%** | 151 | **1,049** | — |
| `taxyear` | 46% | — | — | — |
| `recrdareano` | 37% | — | — | — |
| `numrooms` | 32% | — | — | — |
| **`taxamt` (annual tax bill)** | **15%** | 502 | **2,686** | **0%** |
| `deeded_acres` | 8% | — | — | — |
| exterior wall / roof / foundation / heating | **field does not exist in the schema** | — | — | — |

Year-built coverage distribution across 3,231 counties (count of counties by decile):

```
  0–9%   508   ██████████████████████
 10–19%  129   █████
 20–29%  186   ████████
 30–39%  317   ██████████████
 40–49%  446   ███████████████████
 50–59%  446   ███████████████████
 60–69%  457   ████████████████████
 70–79%  379   ████████████████
 80–89%  280   ████████████
 90–99%   82   ███
   100%    1
```

States with the most counties at 0% year built: **PR (78), IL (43), ND (42), WI (41),
LA (31), MI (27), AK (20), SD (14), VA (14)**.

**Three conclusions that should shape the roadmap:**

1. **Lot geometry is free-ish and complete; building attributes are not.** The 100%
   figures are all *geometry-derived* (Regrid computes acreage from the polygon). The
   county-*reported* fields are the ones with holes.
2. **Coverage is strongly population-weighted in our favour.** Median year-built
   coverage in the 100 largest counties is 87%, versus 67% nationally. A
   population-prioritised build reaches most *people* long before it reaches most
   *counties*.
3. **Actual tax paid is a dead end.** 15% nationally, and a **median of 0% across the
   100 largest counties** — the big counties specifically do not publish it. The
   project's existing ACS effective-rate model is not a stopgap; it is the ceiling.

Verified per-county example (Shelby County, TN — the pilot county), from the Regrid
store page, 353,116 parcels, refreshed 2026-06-09: Year Built 91%, Number of Stories
91%, Building Area 91%, Baths 83%, Bedrooms 83%, Improvement/Land/Total Value 100%,
**Annual Tax Bill 0%**, County-Provided Acres 99%.

---

## Part 3 — The free wins (public domain / permissive, keyless, cacheable)

These all pass the project's constraints outright. Recommended for immediate adoption.

### 3.1 Water source — EPA Public Water System Service Areas ✅ *(replaces the county-SDWIS-on-a-well bug)*

- **Operator / URL:** US EPA Office of Research and Development —
  <https://www.epa.gov/ground-water-and-drinking-water/community-water-system-service-area-boundaries>
- **Coverage:** **over 44,000 community water systems**, all 50 states + DC +
  territories + tribal systems, covering **~99% of the population served by community
  water systems**. Plus **78,000+ non-community** system areas (84% of ~93,500 systems).
- **Provenance (important for honesty labelling):** ~60% of CWS boundaries come from
  authoritative state/utility sources; **~40% are EPA-modeled** from building
  footprints, population density and service-connection counts. Non-community areas are
  nearly all EPA-delineated.
- **Version / freshness:** **Version 3, March 2026**. CWS layer built on SDWIS
  submission-year 2023 Q4; non-community on 2025 Q3. EPA states it will be updated "as
  new or improved service area boundary data are provided" — irregular, not a fixed
  cadence.
- **Licensing:** US federal government work; the model repo is `USEPA/ORD_SAB_Model` on
  GitHub. ⚠️ **Could not programmatically confirm the repo's SPDX license file** (GitHub
  API call was blocked from this environment; a search result asserts MIT but that is
  second-hand). Treat the *data* as US-government public domain and **verify the repo
  license before vendoring code**.
- **Access:** direct ZIP —
  `https://github.com/USEPA/ORD_SAB_Model/raw/refs/heads/main/Version_History/PWS_Boundaries_Latest.zip`
  — plus an ArcGIS FeatureServer
  (`https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Water_System_Boundaries/FeatureServer`).
  Bulk download fits the project's offline-bundle model.
- **Caveat EPA states explicitly:** the layer *"cannot definitively determine if a
  specific address is served"* — use it "as a first step". So the correct label output
  is a three-state value: `on CWS <PWSID>` / `likely private well (outside all mapped
  CWS)` / `unknown`. Not a boolean.
- **What it fixes:** the water-quality dimension can join a parcel to a **specific
  PWSID**, then read that system's SDWIS violations — instead of broadcasting a county
  aggregate onto a house that may be on a well. This is the single largest honesty
  upgrade available for free.

### 3.2 Sewer vs. septic — EPA National Sewersheds ✅

- **Operator / URL:** US EPA — <https://www.epa.gov/cwns/sewersheds>
- **Coverage:** **~17,000 publicly owned treatment works**, covering **~78% of the 2020
  census population**.
- **Method:** POTW locations/populations from permit records and the **2022 Clean
  Watersheds Needs Survey** (state-self-reported); boundaries predicted by an ML model
  from Census, land use, topography and building footprints. **Modeled, not surveyed.**
- **Licensing:** US federal government work, public domain.
- **Honest read:** inside a sewershed → sewer is likely. *Outside* → **ambiguous**
  (could be septic, could be an unmapped small system). Do not score "septic" from
  absence alone.
- **Better where it exists:** **Florida Water Management Inventory (FLWMI)** publishes
  drinking-water source *and* wastewater method **per parcel polygon for all 67 Florida
  counties** (FL DOH/DEP; ArcGIS services at `gis.floridahealth.gov`). Massachusetts
  (MassDEP estimated sewer service areas), Delaware (permitted septic systems on the
  state open-data portal, keyed to tax parcel), Rhode Island, Oregon (3 counties), and
  King County WA publish parcel-level or near-parcel septic layers. There is **no
  national septic permit registry** — septic permitting is a county health-department
  function and stays there.

### 3.3 Private wells — USGWD + EPA well density ✅

- **USGWD (US Groundwater Well Database):** **14.2M+ well records**, 1763–2023, with
  well **purpose** (domestic vs. monitoring), location, depth, capacity; assembled from
  50 state-wide extracts. Lin *et al.*, *Scientific Data* 11:335 (2024).
  **License: CC BY 4.0** — redistributable with attribution, no share-alike. Hosted on
  HydroShare (`doi:10.4211/hs.8b02895f02c14dd1a749bcc5584a5c55`) and mirrored as a
  Google Earth Engine feature collection.
  ⚠️ Records without coordinates were dropped, and per-state completeness is uneven —
  the paper does not claim uniform national completeness. Use as **corroboration**
  (a domestic well within ~50 m of the parcel), never as the sole determinant.
- **EPA Estimated Private Domestic Wells (2020):** well *density* by census block —
  an area statistic, useful only as a prior. ArcGIS MapServer under `geodata.epa.gov`.

### 3.4 Incorporated municipality — Census TIGER/Line PLACE ✅ *(fully solved, confirmed live)*

This is the easy one the brief suspected, and it is even easier than expected: **no
bulk download is required at all** — the Census geocoder answers it keylessly.

**Product:** TIGER/Line Shapefiles, `PLACE` layer (annual, boundaries current as of
Jan 1; 2025 vintage released 2025-09-23). Bulk at
`https://www2.census.gov/geo/tiger/TIGER2025/PLACE/`. Census Bureau products are US
government works — **public domain, freely redistributable**.

**Two keyless point-in-polygon endpoints, both verified working 2026-08-03:**

```
# Census Geocoder (simplest — returns full place attributes)
https://geocoding.geo.census.gov/geocoder/geographies/coordinates
  ?x=-89.85&y=35.15&benchmark=Public_AR_Current&vintage=Current_Current
  &layers=Incorporated%20Places,Census%20Designated%20Places&format=json

# TIGERweb ArcGIS REST (layer 28 = Incorporated Places)
https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/
  MapServer/28/query?geometry=-89.85,35.15&geometryType=esriGeometryPoint
  &inSR=4326&outFields=NAME,GEOID,LSADC&returnGeometry=false&f=json
```

**Verified results:**

| Test point | Result | `MTFCC` | `FUNCSTAT` | `PLACECC` | Interpretation |
|---|---|---|---|---|---|
| −89.85, 35.15 (Memphis) | `Memphis city`, GEOID 4748000 | `G4110` | `A` | `C1` | **Incorporated**, active government |
| −77.026, 38.996 (Silver Spring MD) | `Silver Spring CDP` | `G4210` | `S` | `U1` | **Not incorporated** — statistical CDP |
| −89.55, 35.35 (rural Shelby Co) | `"geographies": {}` — empty | — | — | — | **Unincorporated**, outside any place |

**The discriminator to encode:** `MTFCC == "G4110"` (Incorporated Place) **and**
`FUNCSTAT == "A"` (active general-purpose government). `G4210`/`FUNCSTAT S` is a CDP —
a statistical convenience with no government. An empty response means unincorporated
county territory. Do **not** use "has a place name" as the test; that is precisely the
CDP trap.

**Why it matters here:** the Infrastructure Burden dimension currently allocates
county-average local-government spending to every parcel. A parcel outside any
incorporated place receives no municipal services and pays no municipal millage — the
county is its general-purpose government. Also encode the **consolidated
city-county** exceptions (Nashville-Davidson, Indianapolis-Marion, Louisville-Jefferson,
Philadelphia, SF, Denver…) where the distinction collapses. TIGER's
`CONCITY`/`COUSUB` layers carry those.

### 3.5 Utility provider ✅

- **HIFLD Electric Retail Service Territories** — retail electric service polygons,
  publisher DHS/HIFLD, **license `https://www.usa.gov/government-works`** (confirmed on
  the data.gov catalog record). ⚠️ The data.gov record's last-updated date is
  **2022-10-24** and HIFLD Open's ArcGIS hub has been unstable — the canonical
  `hifld-geoplatform.opendata.arcgis.com` "about" page returned **404** when fetched
  2026-08-03. Mirrors exist at the **Data Rescue Project portal** and **ICPSR/DataLumos**
  (distribution date 2025-10-28) and on NASA's `maps.nccs.nasa.gov` HIFLD mirror.
  **Treat HIFLD as an at-risk source: mirror the file into the repo's build artifacts
  rather than fetching it live.**
- **NREL "U.S. Electric Utility Companies and Rates: Look-up by Zip Code (2024)"** —
  zip → utility (IOU and non-IOU) + average residential/commercial/industrial rate,
  built from EIA-861. Published by NREL Nov 2025, on OEDI/data.gov, public domain,
  keyless bulk CSV. This is the more robust of the two and is a natural companion to the
  EIA state rates the Energy dimension already uses. Zip-level, so it is an area
  statistic — but *utility identity* is much more stable within a zip than a rate is.

### 3.6 Building footprints (living-area proxy) ⚠️ *license trap*

- **Microsoft US Building Footprints** — 129,591,852 CV-derived footprints,
  <https://github.com/microsoft/USBuildingFootprints>. **License: ODbL.**
- **Overture Maps Foundation** — `buildings` theme is **ODbL** (because it ingests OSM);
  the `addresses` theme is **CDLA-Permissive-2.0** (from OpenAddresses/government
  sources, no OSM).
- **OpenAddresses** — metadata/source list is **CC0**, but *"the datasets indexed by
  OpenAddresses are licensed under many different terms by their publishers"*. You must
  license-audit per source; it is not a blanket-free national address file.
- **US DOT National Address Database (NAD)** — ~80M records, **a US federal government
  work, public domain**, on data.gov. The cleanest address-point source available. Note
  DOT's own disclaimer: *"not every state that provides data to the NAD has complete
  coverage."*

⚠️ **ODbL is a real problem for this project, not a formality.** ODbL's share-alike
attaches to *Derivative Databases*. If footprint geometry is joined into the bundled
national reference tables, a defensible reading is that those tables become a Derivative
Database and must themselves be published under ODbL — which conflicts with the repo's
blanket MIT statement. Two safe patterns: (a) use footprints only to compute a
**Produced Work** (a rendered number on a label) and not to build a bundled derived
database; or (b) prefer **CDLA-Permissive** Overture addresses and public-domain NAD/
USA Structures over ODbL footprints wherever a substitute exists. Get this decided
before ingest, not after.

### 3.7 What the existing modeled sources are actually good for

- **USACE NSI** — keep it for what it is designed for: *hazard consequence modeling in
  aggregate*. Its `found_type` is documented as mapped from parcel data **when
  available**, otherwise assigned from **EIA / AHS / HAZUS / USACE survey regional
  assumptions**. Its `med_yr_blt` is a tract median. Both are legitimate **priors**;
  neither is a parcel fact. Public domain, keyless — no licensing problem, only a
  labelling problem.
- **FEMA/ORNL USA Structures** — every structure >450 sq ft, with occupancy and primary
  occupancy type. Built from Census housing-unit data, HIFLD, **LightBox parcel data**,
  and a modeled approach. Useful as a footprint + occupancy prior. Public access;
  note that it is derived in part from a *commercial* parcel source, which is worth
  flagging if the project ever needs a clean provenance chain.
- **NREL ResStock / DOE LEAD** — already in the stack, Apache-2.0 / public domain.
  These are the correct home for foundation/heating **priors** when the user does not
  supply the real value. Keep them explicitly labelled as archetype distributions.

---

## Part 4 — Open government CAMA: the free path to real construction facts

This is the only free route to exterior wall, roof material, foundation and heating
type. It is per-county work, it does not scale to 3,143 counties, and it is worth doing
anyway because it is population-weighted.

**Verified live 2026-08-03 — Cook County, IL Assessor, "Single and Multi-Family
Improvement Characteristics"** (`datacatalog.cookcountyil.gov/.../x54s-btds`, Socrata,
keyless JSON/CSV API, rows updated 2026-08-01). 44 columns including:

```
char_yrblt        year_built                char_ext_wall    ext_wall_material
char_bldg_sf      building_sqft             char_roof_cnst   roof_material
char_land_sf      land_sqft                 char_heat        central_heating
char_beds         num_bedrooms              char_air         central_air
char_fbath/hbath  full/half baths           char_bsmt        basement_type
char_cnst_qlty    construction_quality      char_attic_type  attic_type
char_gar1_*       garage size/att/material  char_frpl        num_fireplaces
```

That is, essentially the entire construction-driven half of the nutrition label,
free, for ~1.9M Cook County parcels, updated continuously, with a maintained
open-source pipeline at `github.com/ccao-data`.

**The open-CAMA shortlist worth harvesting, in rough population order:**

| Jurisdiction | What's published | Notes |
|---|---|---|
| **Florida (statewide)** | FL DOR **NAL** assessment roll, all 67 counties + statewide GIS parcels | **Free, no registration**, `floridarevenue.com/property` data portal. NAL refreshed **3×/yr** (Jul 1 preliminary, Oct initial-final, post-VAB final); GIS shapefiles annually by Apr 1. Includes year built and living area. ~10M parcels. Roof/wall live in county rolls, not the state NAL. |
| **Cook County, IL** | Full CAMA characteristics (above) | Socrata API, keyless |
| **Texas CADs** (Harris, Tarrant, Bexar, Travis, Dallas…) | Full appraisal exports incl. improvement detail — exterior wall, foundation, HVAC | Free tab-delimited bulk (`hcad.org/pdata`, `tad.org/resources/data-downloads`). **Per-district**, no state aggregation. Large files. |
| **Connecticut (statewide)** | **Parcel + CAMA**, standardized, via OPM/COGs | One of only two states publishing a standardized statewide *CAMA* layer, not just geometry. `portal.ct.gov/datapolicy/gis-office/parcel-and-cama` |
| **Massachusetts** | MassGIS standardized assessors' parcels + assessor DB | Refreshed 2×/yr (Jan 1, Jul 1), shapefile/FGDB |
| **Wisconsin** | **V10/V11 Statewide Parcel Map**, 3.56M parcels, ownership + assessment + zoning | Free county and statewide FGDB (~1.6 GB). Note: 41 WI counties are at 0% year built in Regrid, so the state file may beat the commercial aggregate here. |
| **North Carolina** | NC OneMap statewide parcels, all 100 counties standardized | `nconemap.gov` |
| **New York** | 36 counties in a common schema | `gis.ny.gov/parcels` |
| **Washington DC** | CAMA-Residential / Condominium / Commercial on Open Data DC | Includes heat type, AC, exterior wall, roof type, stories, rooms |
| **New York City** | PLUTO / MapPLUTO | Exact year built, lot area, building area, stories, land use |

⚠️ **Do not assume "open data portal" means "permissive licence".** Terms vary and some
are hostile:
- Whitman County WA grants a *revocable* license and forbids making data available to
  third parties "in any format revealing Whitman County as the source of the data."
- Washington State law (RCW 42.56.070(8)) restricts use of **lists of individuals** for
  commercial purposes — relevant because assessor extracts carry owner names.
- New York State supplies parcels "as is" with no warranty and no fitness guarantee.

**Practical mitigation that also solves the privacy problem:** the label needs
*structure* facts, not *people* facts. **Drop owner name, mailing address and sale
party fields at ingest.** That removes the single most commonly restricted class of
field from almost every county's terms, and removes a PII liability from a public repo.

---

## Part 5 — Commercial parcel aggregators: licensing first, then price

### 5.1 The verdict up front

| Vendor | Redistribute? | Cache/store? | Public display? | Compatible with a bundled MIT repo? |
|---|---|---|---|---|
| **Regrid / Loveland** | ❌ no resale, sublicense, or "otherwise making the Data available to third parties" | ✅ explicitly permitted into Postgres/Elasticsearch for internal tools | ✅ permitted, incl. "analysis of areas or coordinates… whether a neighborhood is residential, buildings are multi-story, or home value is low or high" | ❌ for bundling; ✅ **for a server-side scoring lookup** |
| **ATTOM** | ❌ | ❌ **"caching or otherwise storing the ATTOM Content provided through the ATTOM API for a period of greater than twenty-four (24) hours"** is prohibited | ❌ prohibited "publishing of any portion" | ❌❌ **disqualifying** |
| **ReportAll** | ❌ "You are not permitted to distribute, sell, or resell any of the Data" | ⚠️ ToS silent on caching | ⚠️ silent | ❌ for bundling; caching status **unverified** |
| **Realie.ai** | ❌ prohibits "aggregating, repackaging, or reselling" | ⚠️ bulk delivery to your own S3/GCS/Azure implies storage is fine | ❌ "No part of the Services and no Content… may be… publicly displayed… for any commercial purpose" without written permission | ❌ for bundling; public-display clause is ambiguous for a free site |
| **CoreLogic / Cotality**, **First American / DataTree**, **LightBox** | ❌ negotiated contracts | contract-specific | contract-specific | ❌ practically — enterprise contracts, no public terms |
| **Zillow / Redfin / Realtor.com** | ❌ | ❌ | ❌ | ❌❌ see §6 |

### 5.2 Regrid — the only realistic commercial option, quoted verbatim

Regrid's Data Store License Agreement (fetched in full 2026-08-03,
<https://app.regrid.com/store/license>) is unusually explicit, and unusually favourable
to *scoring* use. The relevant clauses:

> "LICENSEE shall not, and shall not permit any third party to, use the Data for the
> purposes of: (a) creating, offering, or selling a website, product, or service that
> may compete with any of Loveland's products or services; (b) reselling the Data to
> third parties; (c) sublicensing the Data to third parties; or (d) **otherwise making
> the Data available to third parties**."

> "In addition, LICENSEE may not upload the Data to, or use any Data with, any public
> artificial intelligence ("AI") large language model ("LLM") or other public or third
> party AI product or service… Notwithstanding the foregoing, LICENSEE is permitted to
> upload the Data to, and use the Data with, LICENSEE's own proprietary AI instance."

> "For avoidance of doubt, in the context of the LICENSEE's software, LICENSEE may:
> … Load the data and associated attributes into databases or search servers such as
> postgresql, solr, elasticsearch, and others **for use in internal tools that may
> display the data**. … **Use the data for analysis of areas or coordinates, such as
> whether a neighborhood is residential, buildings are multi-story, or home value is low
> or high.** … Render high resolution parcel polygons on maps viewable by Licensee's
> customers, **but in a manner that reasonably prevents the customers from obtaining a
> copy of a substantial portion of the parcel geometries**."

> "LICENSEE will credit LOVELAND Technologies as a Data Source **with a link to
> regrid.com on each public facing webpage** that uses this data or any written work,
> private or published."

> "The Term… will continue in effect until the one year anniversary… **Upon expiration
> of the Term the LICENSEE will promptly either cease all use of the data or delete the
> data entirely.**"

> "Loveland will provide LICENSEE with a **one time export** of the selected data, with
> no further data updates."

**How to read this for the Housing Nutrition Label:**

- ✅ Computing a score from Regrid attributes and publishing the score is squarely
  within "analysis of areas or coordinates". This is the licensed use.
- ✅ Caching into the project's own Postgres/SQLite is explicitly allowed.
- ❌ **Committing a Regrid-derived parcel table into the public MIT repo is
  "making the Data available to third parties."** The bundle-it-offline architecture is
  the incompatibility, not the caching.
- ❌ The **1-year term with a delete obligation** is incompatible with a reproducible,
  versioned, permanently-bundled reference artifact.
- ⚠️ The **no-public-LLM clause** matters for an AI-assisted open-source project: do not
  paste parcel extracts into hosted models.
- ⚠️ "may compete with any of Loveland's products or services" is broad. Regrid sells
  property data products. A free public property-information site is arguably adjacent.
  **Get written confirmation** rather than relying on a reading.

**Verified pricing** (extracted from the Shelby County, TN store page's embedded product
JSON, 2026-08-03 — Regrid does not publish a rate card, so these are the live per-county
figures the checkout uses):

| Product | Price (per county) |
|---|---|
| CSV Standard (tabular, standard attributes) | **$150** |
| CSV Premium (+ vacancy, RDI, building footprint attrs) | **$250** |
| Standard Parcel Data (all formats, incl. geometry: FileGDB/GeoJSON/GeoPackage/Shapefile/SQL/Parquet) | **$300** |
| Premium Parcel Data (all formats) | **$500** |
| Add-on: Matched Secondary Addresses | +$100 |
| Add-on: Matched Building Footprints | +$300 |
| Add-on: Building Footprints **with height** | +$700 |
| Add-on: Standardized Zoning | +$650 |
| Statewide / nationwide bulk, API | **quote only** — `parcels@regrid.com` |

Scale: 3,231 counties × $300 ≈ **$970k at list**, so per-county purchasing is only
sensible for a targeted top-N. Nationwide bulk is negotiated and undisclosed; the
public data points for peers are CoreLogic at a **median ~$12,000/yr** (PriceLevel
buyer-reported) and First American Data & Analytics at **~$30,500/yr average**
(Vendr). Assume national parcel data is a five-figure annual commitment.

**Refresh cadence:** "on average 94% of our parcels have been refreshed in the last 12
months"; 500+ high-growth counties quarterly, 200–400 more monthly. Shelby County's
last refresh was 2026-06-09; TN counties on the store page ranged from 2023-02-14
(Chester) to 2026-07-23. **County-level staleness of 1–3 years is normal and should be
surfaced** — Regrid ships `last_refresh` per county and the label should show it.

### 5.3 Regrid "Data With Purpose" — the highest-leverage unknown ⚠️

- **What it is:** a nonprofit/academic program offering a **free one-time bulk snapshot
  of the current data in Standard Schema, for any geography — county, state, or
  nationwide.** Premium schema (monthly updates, API/Feature Service delivery, zoning,
  vacancy) is "pay what you can". <https://regrid.com/purpose>
- **Eligibility:** "researchers, academics, and nonprofit organizations using parcel
  data to create positive change — **not for business purposes**." Official 501(c)(3)
  status is **not** required; researchers, academics, governments and community
  organizations qualify. An open-source, free, non-commercial public-interest housing
  project is a plausible fit.
- **Why it matters:** a free nationwide Standard snapshot delivers year built (67%),
  living area (65%), stories, beds/baths, assessed/market value (87%), exact parcel
  geometry (100%) and use codes — i.e. **every attribute in rows 1, 2, 7, 8, 9 of the
  verdict table** — at zero cost.
- ⚠️ **Terms are not published.** Neither the program page nor the announcement blog
  post states the license, redistribution rules, or term. The blog notes only that the
  program covers **parcel data only — not matched building footprints or secondary
  addresses**, and that applicants submit a use case and a budget. **This is the single
  most important thing in this memo to verify before designing around it.** The specific
  questions to ask Regrid in writing:
  1. May a derived, non-reconstructable artifact (e.g. per-parcel *scores*, or binned
     model inputs) be published publicly under MIT?
  2. Does the Data Store License's **1-year delete obligation** apply to a DWP snapshot?
  3. Does a free public website that displays per-address scores count as
     "competing with Loveland's products or services"?
  4. Is the attribution link on every public-facing page sufficient?

---

## Part 6 — Zillow, Redfin, Realtor.com: state plainly, no

**Zillow.** The consumer-facing Zillow Web Services API (`GetSearchResults`,
`GetDeepSearchResults`, ZWSID keys) was **retired 30 September 2021** and has not
reopened. The successor is **Bridge Interactive** (Zillow Group), a **RESO Web API for
MLS-affiliated partners** — brokerages, IDX vendors, approved partners. The **Bridge
Public Records API** (parcel, assessment and transactional county data, ~15 years) is
**invite-only**: you must file a request describing your application and be approved,
and it is explicitly aimed at "commercial business applications". The Zillow API Terms
of Use state that *"third parties are permitted to retrieve data from the site only
through the API"* and that *"any reverse engineering, spiders, or other techniques used
to directly pull data without using the Bridge API is a violation of the Terms of Use."*
The Zestimate is not exposed via Bridge.

⚠️ I was unable to retrieve the full verbatim text of `bridgedataoutput.com/zillowterms`
— the page rendered as a JS shell. The quotes above are from secondary sources.
**Do not rely on this section as a legal opinion; it is a "do not build on it" signal.**

**ZTRAX** — Zillow's Transaction and Assessment Database, ~150M parcels, 20+ years of
deeds/mortgages/foreclosures plus property characteristics — was **discontinued October
2023** and now lives **exclusively at ICPSR** (study 39652), refreshed twice yearly by
Zillow. It is **restricted-use**: free to users at ICPSR member institutions, others may
apply, and access requires an **Agreement for the Use of Confidential Data**, a stated
research purpose, and **IRB approval or exemption**. That is a research-access channel,
not a product-data channel — derived public web output is not what the agreement
contemplates. Not usable here.

**Redfin** grants only "a limited, personal, non-exclusive, non-transferable,
non-sublicensable, revocable license to access, view, and use the Services", and
explicitly prohibits "screen and database scraping, spiders, robots, crawlers and any
other automated activity" without prior written permission. The Redfin **Data Center**
publishes *market aggregates* (by metro/zip/neighborhood) — never parcel attributes.

**Realtor.com** offers no public listing API and prohibits automated extraction.

**On the scraping case law**, because it comes up: *hiQ v. LinkedIn* (9th Cir. 2019)
held the **CFAA** does not reach scraping of publicly accessible data — but the case
ended in **November 2022** with a finding that hiQ had **breached LinkedIn's User
Agreement**, and a consent judgment. *Meta v. Bright Data* (N.D. Cal., Jan 2024) held
Bright Data was not in breach for scraping **logged-out** public pages, because the
platform's terms bind account holders, not anonymous visitors; Meta dropped the suit a
month later. The rule that emerges is narrow: **logged-out public scraping survives
CFAA, but contract, copyright and trespass claims remain live**, and both cases turned
on facts a housing project would not enjoy. Layer on top of that: MLS listing content is
licensed from ~500 MLSs under IDX agreements, and the aggregate compilation is
protectable. **The legal exposure is real and the reputational exposure for an MIT
public-interest project is worse than the data is worth.** Do not scrape listing sites.

---

## Part 7 — Licensing: what this project can and cannot use

The project's three commitments — **MIT-licensed code, a free public website, and
cached/bundled data** — interact in a way worth naming explicitly, because it is the
*third* one that does almost all the excluding.

**The distinction that actually matters is: are we redistributing the data, or
publishing a work derived from it?**

- Every commercial parcel license forbids **redistributing the records**.
- **None** of them forbid **publishing a score computed from the records** — Regrid's
  license affirmatively permits exactly that ("analysis of areas or coordinates").
- The project's current architecture — `scripts/build_*.py` producing versioned CSVs
  committed to a public repo — is **redistribution by construction**. That is the
  incompatibility.

**Therefore, three tiers of source, and three architectures:**

| Tier | Examples | Architecture that works |
|---|---|---|
| **Public domain / CC0 / CC BY / Apache / CDLA-Permissive** | Census (TIGER, ACS, geocoder), EPA (SAB, sewersheds, SDWIS, walkability), NREL/DOE (ResStock, LEAD, Cambium, utility-rate zip file), USGS, HIFLD (usa.gov gov-works), FEMA (NRI, USA Structures), DOT NAD, USGWD (CC BY), Overture `addresses` (CDLA-Permissive-2.0) | **Bundle it.** This is the existing model and it stays. Attribution where required. |
| **Copyleft-ish (ODbL)** | Microsoft building footprints, Overture `buildings`, OpenStreetMap | **Produced Work only.** Use to render a number; do **not** merge into a bundled derived database committed under MIT. If a bundled join is unavoidable, that artifact must ship under ODbL and the repo needs a per-artifact license map. |
| **Commercial (all of them)** | Regrid, ATTOM, ReportAll, Realie, CoreLogic, First American, LightBox | **Runtime lookup, server-side, never committed.** Cache in a local DB the repo does not ship; publish scores, not records; honour term limits and attribution. |

**Blunt exclusions:**

- **ATTOM is out.** A 24-hour cache ceiling is fundamentally incompatible with a
  project whose whole design is offline-cacheable reference data. This is not a
  negotiable detail; it is the product.
- **Anything requiring an API key that an individual cannot obtain is out** by the
  project's own existing constraint. Bridge Public Records (invite-only), DOE Home
  Energy Score API (requires DOE written authorization as an approved "Software
  Partner", and access restricted to DOE-approved Qualified Assessors), and enterprise
  contracts (CoreLogic/First American/LightBox) all fail here.
- **Scraping listing sites is out** on both legal and reputational grounds (§6).
- **County open data still needs a per-source license audit.** "It's on an open data
  portal" is not a license. Several counties grant revocable licenses, forbid onward
  distribution, or sit in states restricting commercial use of owner-name lists.

**Sources where I could not verify terms and am flagging rather than guessing:**

1. **Regrid Data With Purpose** — no published license, term, or redistribution rule.
   *(Highest priority to resolve; §5.3.)*
2. **`USEPA/ORD_SAB_Model` repo license** — the GitHub API call was blocked from this
   environment. Data is a federal work; the *code* license is asserted-MIT by a
   secondary source only.
3. **ReportAll caching/storage** — the ToS prohibits distribution and resale but is
   **silent on caching and on public display**. The binding document is the "Production
   API Agreement", which is not public. Pricing is likewise not published (metered vs.
   unlimited packages, 1-year expiry).
4. **Zillow / Bridge terms verbatim** — page did not render; §6 relies on secondary
   sources.
5. **Realie.ai's public-display clause** — the ToS forbids public display "for any
   commercial purpose whatsoever." Whether a free public-interest website is a
   "commercial purpose" is genuinely ambiguous and would need their answer.
6. **ATTOM pricing** — reported anywhere from $95/mo to $500/mo entry by third-party
   blogs; ATTOM publishes none. Moot given the caching clause.
7. **Estated** — acquired by ATTOM; API being migrated onto ATTOM infrastructure with
   docs deprecating during 2026. Existing keys stay valid. **Assume ATTOM terms apply**
   — i.e. assume it is out. Could not retrieve the pricing sheet (PDF did not parse).
8. **HIFLD ERST current canonical home** — the primary hub URL 404s; data.gov record
   last updated 2022-10-24. License (`usa.gov/government-works`) is confirmed;
   *availability* is not.

---

## Part 8 — Ranked, costed recommendation

### Tier 0 — Free, this sprint, no license risk (do all of these)

| # | Action | Source | Effort | Fixes |
|---|---|---|---|---|
| 1 | **Stop presenting NSI `med_yr_blt` as a year built.** Relabel as a tract prior or drop it; add an `unknown` state | — | Trivial | The single most misleading field on the label |
| 2 | Add **provenance + confidence tags per attribute** (`observed`/`modeled`/`area-average`/`user`/`unknown`) and surface them | — | Low | Makes every subsequent honesty claim mechanical rather than editorial |
| 3 | **Incorporated-municipality flag** via Census geocoder / TIGERweb layer 28 (`MTFCC=G4110 & FUNCSTAT=A`); handle CDPs and consolidated city-counties | Census, public domain, keyless | Low | Infrastructure Burden's biggest structural error |
| 4 | **Water source**: join parcel → PWSID via **EPA CWS Service Area Boundaries v3**; score that system's SDWIS record; return `well/unknown` outside all boundaries | EPA, public domain, bulk ZIP | Medium | The private-well bug, exactly |
| 5 | **Sewer vs. septic**: **EPA National Sewersheds**; three-state output | EPA, public domain | Medium | New signal for Infrastructure Burden |
| 6 | **Utility provider**: NREL zip→utility+rate (public domain) as primary, HIFLD ERST polygons as refinement — **mirror HIFLD, don't fetch it live** | NREL/HIFLD | Low | Energy + Environmental provenance |
| 7 | **Well corroboration**: USGWD domestic wells within ~50 m (CC BY, attribution) | HydroShare | Medium | Raises confidence on #4 |

**Cost: $0. Coverage: national. All bundleable under the existing architecture.**

### Tier 1 — Free, higher effort, population-weighted (do next)

| # | Action | Effort | Payoff |
|---|---|---|---|
| 8 | **Open-CAMA harvester** with a per-source license manifest, starting with **Florida statewide NAL** (~10M parcels, free, 3×/yr) and **Cook County** (full construction characteristics incl. wall/roof/heat) | High | The only free route to rows 3–6 of the verdict table |
| 9 | Extend to **CT, MA, WI, NC, NY-36, DC, NYC, TX CADs** | High | Adds ~15–20% of US households with real year-built/living-area, and real construction detail where the county publishes it |
| 10 | **Drop owner-name/mailing/party fields at ingest**; document it | Low | Removes the most-restricted field class from nearly every county's terms, and the PII liability |
| 11 | Footprint area from **Overture/MS** — but decide the **ODbL question first** (§3.6) | Medium | Living-area proxy where CAMA is absent |

**Cost: $0. Coverage: partial but population-weighted. License risk: per-source, manageable.**

### Tier 2 — The one paid decision worth making

| Option | Cost | What it buys | Verdict |
|---|---|---|---|
| **Regrid Data With Purpose** (free nationwide Standard snapshot) | **$0**, application required | Year built 67%, living area 65%, stories 60%, beds/baths, value 87%, exact lot geometry 100%, use codes 71% — nationally | **Apply first.** Blocked only on the unpublished terms (§5.3). Highest expected value in this memo. |
| **Regrid per-county CSV Standard @ $150** | $1,500 for 10 counties / $3,000 for 20 | Targeted fill of the largest gaps not covered by open CAMA | Reasonable if DWP is declined. Note the **1-year delete obligation**. |
| **Regrid per-county all-format @ $300** | $3,000 for 10 | Adds parcel geometry in GeoJSON/Parquet | Only if geometry is needed beyond what state portals give free |
| **Regrid nationwide bulk / API** | quote only; peers at **$12k–$30k/yr** | Everything above, refreshed | Out of reach for a volunteer project unless a sponsor appears |
| **Shovels.ai permits** | **~$599/mo** (~$7.2k/yr) | 2,450+ jurisdictions, ~85% of US population — reroof/HVAC/solar/addition history | The **only** viable path to roof age and equipment age at scale. Defer until there is a funded use. |
| **Cape Analytics / EagleView roof** | enterprise, unpublished | Roof age + condition + material, 110–200M structures | Out of reach and out of license compatibility |
| **ATTOM / CoreLogic / First American / LightBox** | $12k–$30k/yr | — | **No.** Terms fail before price does. |

**A defensible budget statement:** *$0 gets Tier 0 and Tier 1, which is most of the
honest gain. ~$1,500–$3,000 one-off buys targeted per-county fill. ~$7,200/yr is the
first price point that unlocks a genuinely new attribute class (permits → roof/HVAC
age). Everything above that is enterprise territory and should wait for a sponsor.*

### Tier 3 — Keep as user-supplied input, permanently

These are not roadmap items. They are the honest boundary of auto-detection, and the
label should ask for them rather than pretend:

- **Roof age** and **roof material** (outside open-CAMA counties)
- **Heating/cooling system type, fuel, and age**
- **Exterior wall assembly** and **foundation type** (outside open-CAMA counties)
- **Insulation levels, window type, air sealing**
- **Actual utility consumption** — consent-gated by design; Green Button CMD exists only
  at the CA IOUs and ComEd, and requires the homeowner's OAuth grant
- **Actual property tax paid** — 15% national coverage, 0% median in the largest
  counties
- **Recent renovations** not captured by a permit
- **Confirmation of well/septic** — the EPA layers give a strong prior, never proof

**Design implication:** the simulator already takes a house configuration. The right
product move is a **progressive-disclosure form** where auto-detected facts arrive
pre-filled and labelled `from county assessor` / `estimated`, the user can correct any
of them, and each correction visibly raises that dimension's confidence. That converts
the irreducible gap from a weakness into the interaction model.

---

## Open questions

1. **Regrid Data With Purpose terms** — the four written questions in §5.3. Everything
   in Tier 2 hinges on this.
2. **The ODbL decision.** Does the project accept a mixed-license bundle (some
   artifacts ODbL, code MIT), or does it hold the line on permissive-only and forgo
   Microsoft/Overture building footprints? This needs a maintainer decision before any
   footprint ingest, not after.
3. **How many counties is "enough" for the open-CAMA harvester?** Suggest measuring in
   *housing units covered*, not counties, and setting an explicit target (e.g. 35% of
   US housing units with observed year-built) so the work has a stopping condition.
4. **Does the project want per-parcel caching at all?** A per-address, server-side,
   TTL'd cache with no bundled artifact is compatible with the Regrid license and
   incompatible with nothing else. It is a different architecture from the current
   bundle-everything model and may be the right one for commercial-sourced fields
   specifically — a two-tier design: public-domain data bundled, licensed data cached.
5. **EPA SAB `USEPA/ORD_SAB_Model` code license** — verify before vendoring any of the
   model code (data itself is fine).
6. **Confidence calibration**: once attributes carry provenance, the existing
   `uncertainty-confidence` machinery should be re-tuned so an `observed(assessor)`
   year built genuinely moves the needle versus a `modeled(NSI)` one. That is a
   follow-on research task, not covered here.

---

## Source index

**Free / public domain / permissive**
- Census TIGER/Line + PLACE — <https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html>
- Census Geocoder (geographies) — <https://geocoding.geo.census.gov/geocoder/> · TIGERweb REST — <https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/28>
- EPA CWS Service Area Boundaries v3 — <https://www.epa.gov/ground-water-and-drinking-water/community-water-system-service-area-boundaries> · repo <https://github.com/USEPA/ORD_SAB_Model>
- EPA National Sewersheds — <https://www.epa.gov/cwns/sewersheds>
- EPA Estimated Private Domestic Wells (2020) — <https://cfpub.epa.gov/si/si_public_record_Report.cfm?dirEntryId=359961>
- USGWD, Lin et al. 2024, *Sci Data* 11:335, CC BY 4.0 — <https://www.nature.com/articles/s41597-024-03186-3>
- HIFLD Electric Retail Service Territories — <https://catalog.data.gov/dataset/electric-retail-service-territories>
- NREL US Electric Utility Companies and Rates by Zip (2024) — <https://data.openei.org/submissions/8563>
- US DOT National Address Database — <https://www.transportation.gov/mission/open/gis/national-address-database>
- OpenAddresses — <https://openaddresses.io/> · Overture attribution/licensing — <https://docs.overturemaps.org/attribution/>
- Microsoft US Building Footprints (ODbL) — <https://github.com/microsoft/USBuildingFootprints>
- USACE NSI technical documentation — <https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/latest/technical-documentation>
- FEMA/ORNL USA Structures — <https://catalog.data.gov/dataset/usa-structures-4749e>
- Census Building Permits Survey — <https://www.census.gov/construction/bps/about.html>
- LBNL Tracking the Sun 2025 (~3.3M PV systems, zip-level, no addresses) — <https://emp.lbl.gov/tracking-the-sun>

**Open state / county CAMA**
- Florida DOR assessment rolls + GIS — <https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx>
- Florida Water Management Inventory — <https://www.floridahealth.gov/environmental-health/drinking-water/flwmi/details.html>
- Cook County Assessor improvement characteristics — <https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Single-and-Multi-Family-Improvement-Chara/x54s-btds> · <https://github.com/ccao-data>
- Connecticut Parcel & CAMA — <https://portal.ct.gov/datapolicy/gis-office/parcel-and-cama>
- MassGIS property tax parcels — <https://www.mass.gov/info-details/massgis-data-property-tax-parcels>
- Wisconsin Statewide Parcel Map — <https://www.sco.wisc.edu/parcels/data>
- NC OneMap — <https://www.nconemap.gov/> · NY parcels — <https://gis.ny.gov/parcels>
- Open Data DC CAMA-Residential — <https://opendata.dc.gov/datasets/DCGIS::computer-assisted-mass-appraisal-residential/about>
- HCAD data downloads — <https://hcad.org/pdata/pdata-property-downloads.html> · TAD — <https://www.tad.org/resources/data-downloads>

**Commercial**
- Regrid Data Store License Agreement — <https://app.regrid.com/store/license>
- Regrid coverage report (CSV export works) — <https://docs.google.com/spreadsheets/d/1rvRYv6_ppZlwbmyi2kbzemot6FOEm2EEPdHPyENTQPE/>
- Regrid Data With Purpose — <https://regrid.com/purpose>
- Regrid schema — <https://support.regrid.com/parcel-data/schema>
- ATTOM API legal terms (24-hour cache limit) — <https://api.developer.attomdata.com/legal>
- ReportAll ToS — <https://reportallusa.com/terms-of-service>
- Realie.ai terms / pricing — <https://www.realie.ai/terms> · <https://www.realie.ai/pricing>
- Shovels.ai coverage — <https://www.shovels.ai/coverage>
- Zillow Bridge Public Records API — <https://www.zillowgroup.com/developers/api/public-data/public-records-api/>
- ZTRAX at ICPSR (study 39652) — <https://www.icpsr.umich.edu/web/ICPSR/studies/39652>
- Redfin Terms of Use — <https://www.redfin.com/about/terms-of-use>
- *Meta v. Bright Data* analysis — <https://www.fbm.com/publications/major-decision-affects-law-of-scraping-and-online-data-collection-meta-platforms-v-bright-data/>
