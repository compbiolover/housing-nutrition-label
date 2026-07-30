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

The same file's **current-charges revenue** (object `A`) for these functions feeds the
fee-recovery ratios added in Phase 5 — see that section for the code mapping.

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
  per-unit value a quadplex yields ~4× the property-tax revenue per acre on the
  same shared infrastructure (the "value per acre" lens).

## Phase 5 (implemented) — revenue-scope reconciliation + rental classification

Phase 3 made both sides of the ratio like-for-like on *schools*. They were still
mismatched on *user fees* and on *tax classification*, and both errors ran the same
direction: understating revenue for exactly the dense housing the cost model treats
most favorably.

### The symptom

A 12-story, 157-unit downtown Memphis building scored an A while showing a fiscal
ratio of 0.60, under label copy reading "a ratio above ~1 means it pays its own way."
Both statements were defensible on their own and incoherent together. Investigating
the gap turned up two real modeling errors rather than a copy problem.

At that building's density the model is already at its cost asymptote: of $2,014/unit
of modeled cost, only ~$163 is density-responsive (roads + water/sewer). The rest is
per-capita or flat (police $840, fire $408, sanitation $302, parks $300). Past
~50 DU/acre, adding density cannot move the ratio further — so if the ratio was wrong
there, it had to be wrong on the revenue side.

### Fix 1 — count user-fee revenue

The cost side counted water, sewer, and trash in full. The revenue side counted only
property tax. But residents pay for those services through utility bills and a monthly
fee, so the ratio was comparing the full cost of service against a revenue stream that
was never meant to cover it.

`scripts/build_govfinance.py` now also parses **current-charges revenue** (object code
`A`) for the same functions from the same Census of Governments file, and writes a
per-county **fee-recovery ratio** = charges ÷ direct expenditure:

| Component | Census revenue code(s) | National recovery |
|---|---|---|
| roads | A44 (regular highways) | 2.9% |
| water_sewer | A80 (sewerage) + A91 (water utility revenue) | 100% (capped; raw 102.7%) |
| fire | *none exists* | 0% |
| police | *none exists* | 0% |
| sanitation | A81 (solid waste management) | 75.2% |
| parks | A61 (parks & recreation) | 22.5% |

`enrich_row` multiplies each modeled cost component by its county's recovery rate and
adds the result to the numerator. Ratios are capped at 1.0 — Shelby's MLGW recovers
more than its own expenditure, but crediting >100% would let a home generate phantom
general-fund revenue on its pipes. (The surplus MLGW actually transfers to the general
fund is real but unmodeled: a conservatism in the same direction as the rest.)

That fire and police recover **0% everywhere** is the substantive finding, not a data
gap: the Census classification has no current-charge code for either, so property tax
really is the only thing paying for them. This is why the typical home still doesn't
reach 1.0 even with fees counted, and why the remaining gap is a genuine result rather
than an accounting artifact.

### Fix 2 — rental housing is not assessed as residential in Tennessee

The model applied a flat 25% assessment ratio to every parcel. Tennessee's
**constitution** says otherwise: Tenn. Const. art. II, § 28 assesses residential
property at 25% "provided that residential property containing two (2) or more rental
units is hereby defined as industrial and commercial property," which § 67-5-801
assesses at **40%**. Codified at Tenn. Code Ann. § 67-5-501(11) and § 67-5-501(4).

The operative count is **rental units, not dwelling units**. Tenn. Att'y Gen. Op. No.
25-016 (Aug. 25, 2025) applies it: a single-family home rented long-term stays
residential, and so does an owner-occupied duplex, since each holds only one rental
unit. There is no bright-line physical test — *Spring Hill, L.P. v. State Bd. of
Equalization*, No. M2001-02683-COA-R3-CV, 2003 WL 23099679, at \*17–\*18 (Tenn. Ct.
App. Dec. 31, 2003) classified 44 detached homes as commercial because they were one
commonly owned rental development.

So a Memphis apartment building generates **1.6×** the property tax the model credited
it. New module `src/housing_label/data/assessment.py` encodes this. Two design choices
matter:

- It returns the commercial ratio **or `None`** — never the residential ratio — so the
  correction is strictly additive and can only move parcels the statute actually
  reclassifies. A caller supplying its own assessment basis is never silently
  overridden. (A test asserts this; an earlier draft that returned the residential
  ratio broke the national path, which passes `assess_ratio=1.0`.)
- Tenure defaults to rental for multi-unit buildings, which ACS 2024 table B25032
  supports for **86.1%** of units in 2+ unit structures and 87.9% in 5+ unit
  structures. Callers can state tenure explicitly for a condo or owner-occupied duplex.

### Re-calibration

With both sides covering the same services, the national median fiscal ratio moves
**0.31 → 0.66** and `INFRA_XS` was re-anchored. Roughly **13%** of US homes now clear
1.0 (p90 ≈ 1.15), versus essentially none before — a distribution that can actually
distinguish "pays its way" from "doesn't."

The 157-unit Memphis building lands at **1.17**: a net contributor. The two fixes
contribute about equally (fees ≈ +$447/unit of revenue; classification ≈ +$638/unit).

### Copy

The label said "a ratio above ~1 means it pays its own way" while the scale graded a
0.31 as average — so the tooltip described an accounting identity the model never
computed. The dimension is a **national percentile rank**, and the copy now says so:
the typical US home covers about two-thirds of its cost, an A can coexist with not
fully paying your way, and the reason is fire and police.

**Limitation (unfixed):** only Tennessee is encoded. Off the pilot path the revenue
side uses an ACS effective rate derived from *owner-occupied* homes (B25103 ÷ B25077),
which already embeds whatever classification those homes fall under — so applying the
uplift there would double-count, and classification is disabled. In any other
split-roll state, a rental building's property tax is still understated. Extending the
table means reading each state's constitution or code individually; it should not be
guessed from a secondary source.

## Future phases (not in this change)

- **Split-roll classification beyond Tennessee**: several states classify multi-unit
  rental housing separately, with different thresholds and ratios. Each needs primary
  sources, and the national path needs a rate that isn't owner-occupied-derived before
  the uplift can be applied without double-counting.

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
