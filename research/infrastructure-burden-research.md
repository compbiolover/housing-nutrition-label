# Locally-Calibrated Infrastructure Burden — Implementation Research

Research backing the roadmap item: *"replace the Memphis-calibrated infrastructure
cost-to-serve model with a locally-calibrated one that works for any U.S. address."*
The `Infrastructure Burden` dimension estimates the annual municipal cost to serve a
residential parcel — roads, water/sewer, fire/EMS, police, sanitation, parks — via a
density-adjusted cost allocation (`src/housing_label/enrich/infrastructure.py`), and a
`fiscal_ratio` = estimated property-tax revenue ÷ estimated cost-to-serve. The cost
curves and the property-tax rate were both calibrated to the **City of Memphis /
Shelby County** pilot, so any address outside Shelby reused Memphis numbers and was
flagged *"national-average, not locally calibrated — treat as an estimate."*

This document records the data + method assessment (a deep multi-source review,
adversarially fact-checked) and the phased plan. **Phase 1 is now implemented.**

---

## Bottom line

There are two halves to localize: the **cost** side (per-jurisdiction service
spending) and the **revenue** side (local property-tax rate). The keyless backbone
for the cost side is the **U.S. Census Bureau Census of Governments / Annual Survey of
State & Local Government Finances**, whose individual-unit file ties
expenditure-by-function to a government unit's FIPS state+county. Per-capita
average-costing (the "per-capita multiplier" fiscal-impact technique) is the
allocation method that generalizes across thousands of jurisdictions. No single
keyless source gives effective property-tax rates for an *arbitrary* address, so the
revenue side needs a tiered fallback. Uniform parcel-level precision is not
achievable nationwide — but a county-level local-finance calibration removes the
single largest error (reusing one city everywhere).

---

## Data sources (all keyless, free, public — bulk files, no API key)

| Component | Source | Notes |
|---|---|---|
| Per-function local spending (cost side) | **Census of Governments 2022, Individual Unit File** | Most recent complete finance census (~90k units; the COG is a full count only in years ending in 2 and 7 — annual surveys in other years are samples). Record ID encodes FIPS state (1–2), gov type (3), FIPS county (4–6); item code (13–15) is object+function; amount (16–27) in $000s. Public-use, redistributable. ~1.5–2 yr lag. The convenience *API* now needs a free key, but the **bulk files stay keyless** — so we ingest bulk. |
| Per-capita denominator | **Census Population Estimates (PEP)** county totals | `POPESTIMATE2022`, keyless CSV. |
| Property-tax effective rate (revenue side) | Lincoln Institute / MCFE **50-State Property Tax Comparison** (≈100–124 cities); **ACS** county effective-rate proxy (~3,129 counties, noisy); **state DOR** millage tables (complete but PDF-only) | No single keyless parcel-level nationwide source — use a tiered fallback. The live path already applies a single national effective rate; per-county localization is future work. |
| Parcel → jurisdiction | Census **TIGER/Line** places + county subdivisions | Maps a parcel to its general-purpose jurisdiction; **special districts** (water/sewer/fire) are the irreducible attribution gap. |

Function → item codes used (direct general expenditure = `E` current ops + `F`
construction + `G` other capital):

| Component | Census function code(s) |
|---|---|
| roads | 44 (regular highways) |
| water_sewer | 80 (sewerage) + 91 (water utilities) |
| fire | 24 (fire protection) |
| police | 62 (police protection) |
| sanitation | 81 (solid waste management) |
| parks | 61 (parks & recreation) |

Local government units only (types 1–4: county / municipal / township / special
district); state (0) and school-district (5) governments are excluded.

---

## Method: per-capita average costing, normalized to the pilot

For every county, sum local direct general expenditure by function, divide by
population → per-capita spend, then express each county relative to **Shelby County
(47157)**:

```
mult[county, function] = per_capita[county, function] / per_capita[Shelby, function]
```

The Memphis-calibrated density curves provide the cost-to-serve **shape** (how cost
falls with density); these multipliers provide the local **level**. Shelby is 1.0 on
every function by construction, so the pilot is unchanged; LA County, for instance,
lands at ~2.0× roads and ~2.6× water/sewer (2022 census). Multipliers are clamped to [0.25, 4.0],
and a county with zero recorded local spend on a function (e.g. water served by a
utility counted elsewhere) falls back to the national-average multiplier rather than
zeroing the modeled cost. Unmapped counties use a national-average row.

This is the FIA "per-capita multiplier" technique — the most generalizable across
thousands of jurisdictions, at the explicit cost of being the least precise (it
reflects spending *level*, not service capacity or capital needs).

---

## Phase 1 (implemented)

- `scripts/build_govfinance.py` — downloads the 2022 COG Individual Unit File + PEP
  population (keyless), aggregates per-county per-function direct expenditure,
  normalizes to Shelby, and bundles `src/housing_label/data/govfinance_county.csv`
  (3,137 counties + a national-average row).
- `src/housing_label/data/govfinance.py` — resolution-aware county → multipliers
  lookup (county → national fallback), clamped, always returns a dict.
- `src/housing_label/enrich/infrastructure.py` — `enrich_row` takes optional
  `cost_multipliers` scaling the six components (default 1.0 = Shelby pilot, so the
  offline Shelby pipeline is unchanged).
- `src/housing_label/simulate/dimensions.py` — the live label resolves the location's
  county multipliers and passes them alongside the existing national property-tax rate
  and urban/rural fire parameterization.
- The Infrastructure caveat now reports county-level local calibration (Census of
  Governments) where the county is in the crosswalk, and the national-average estimate
  otherwise.

## Phase 2 (implemented) — revenue-side property-tax localization

The fiscal ratio's revenue side previously applied one national effective rate to
every non-Shelby location. It now uses each county's **effective property-tax rate**.
The ACS county proxy — not the per-state DOR scrapers — is the right first step:
near-universal county coverage, keyless, and reproducible. (Effective rates vary ~10×
nationally, so even a county-level rate removes the bulk of the revenue error.)

- `scripts/build_property_tax.py` — downloads the ACS 2022 5-year **table-based
  Summary File** tables B25103 (median real-estate taxes) and B25077 (median home
  value), keyless, and bundles `src/housing_label/data/property_tax_county.csv`
  (effective rate = taxes / value, clamped to [0.1%, 5.0%]; 3,208 counties + a
  national-average row). The Census Data **API** needs a key; these bulk table files
  do not.
- `src/housing_label/data/propertytax.py` — resolution-aware county → effective-rate
  lookup (county → national fallback).
- `src/housing_label/simulate/dimensions.py` — the live label now sets the
  infrastructure `tax_rate` from the county's ACS rate (national fallback) instead of
  the single national constant. The caveat names both the cost (CoG) and revenue (ACS)
  calibration.

## Phase 3 (implemented) — value auto-fill + school-scope reconciliation

Two fiscal-ratio accuracy fixes, plus a breakpoint re-calibration.

- **Auto-fill home value**: `data/propertytax.py` exposes the county median home
  value (ACS B25077); `simulate/house.build_label_parts` defaults the home value to
  it when the caller supplies none (explicit value still wins), so the revenue side
  and dollar EALs reflect the local market rather than the construction profile's
  flat default.
- **School-scope reconciliation**: `scripts/build_govfinance.py` now also parses
  property tax (item T01) by government type and writes a per-county
  `school_tax_share` = independent school-district property tax ÷ all local property
  tax (national-average fallback ~41% where the type-5 signal is ~0, i.e. dependent
  school systems). `simulate/dimensions.py` and the calibration tool net that share
  out of the revenue rate, so both sides of the ratio are like-for-like non-school.
- **Re-calibration**: with schools netted out, the national median fiscal ratio
  drops from ~0.61 to ~0.31; `INFRA_XS` was re-anchored to the new non-school
  national distribution.

**Limitation:** the school share is computed from independent school districts;
dependent-school counties (TN, VA, parts of others) fall back to the national
average, and CoG can't attribute a general government's property-tax revenue to its
education function, so in-between cases are approximate.

## Phase 4 (implemented) — density-responsive cost curve + per-acre productivity

Sharpens how the model credits small-scale infill, after testing showed the
density comparison barely moved the needle (1→4 units capped the gain).

- **Continuous, extended cost curve**: `enrich/infrastructure.py` replaced the
  step-function density tiers for roads & water/sewer with `interp_cost` (log-log
  interpolation over anchor points). The anchors are the published Halifax band
  costs at each band's geometric-mean density, **extended past 12 DU/acre** (24,
  48 DU/acre). Previously these floored at 12 DU/acre, so a triplex, quadplex,
  and 16-plex on a normal lot all scored identically; now per-household
  linear-infrastructure cost keeps amortizing with density, so denser infill
  keeps earning credit. A 16+ DU/acre police-efficiency tier was also added.
- **Re-calibration**: with the densest archetype no longer pinned at the floor,
  `INFRA_XS` was re-anchored (national median fiscal ratio ≈ 0.31 unchanged; the
  top anchor rose from ~0.98 to ~1.05).
- **Fiscal productivity per acre**: the per-unit fiscal ratio understates infill
  because the headline gain is on the revenue side. The density comparison now
  also reports revenue/cost/net fiscal *per acre* — on a fixed lot at constant
  per-unit value a quadplex yields ~4× the tax base per acre on the same shared
  infrastructure (the "value per acre" lens).

## Future phases (not in this change)

- **Sub-county / per-jurisdiction property tax**: state DOR millage tables (and
  Lincoln/MCFE city benchmarks) for municipal-level precision — PDF-only, ~50 bespoke
  scrapers, so a precision refinement rather than a coverage gain.
- **Parcel → service-provider mapping**: TIGER/Line places + county subdivisions, with
  special-district attribution flagged as irreducible uncertainty.
- **Validation**: bound the accuracy gain vs published ACFRs for a sample of cities.

---

## Caveats / irreducible uncertainty

- County-area aggregation assigns each local unit to one county; a city or special
  district spanning counties is counted in its home county.
- Census finance data lags ~1.5–2 years and (in non-census years) is a sample; 2022 is
  the most recent full census, hence its use here.
- Per-capita spend captures level, not quality or marginal/capital need.
- The density cost-to-serve *shape* is still the Halifax/Memphis calibration; only the
  per-function level is localized.
