# Tornado Hazard — FEMA National Risk Index EAL (consolidation)

> **What this backs:** `src/housing_label/data/tornado.py`,
> `src/housing_label/enrich/tornado.py`, and the tornado leg of
> `src/housing_label/score/resilience.py` + `src/housing_label/simulate/house.py`.
> Retires the NOAA SPC touchdown-count tornado model in favour of the FEMA
> National Risk Index tornado EAL rate — the same shape already used for wildfire.
> **Date:** 2026-07-10. Constraint: open / keyless / redistributable.

---

## The problem

Disaster Resilience sums four peril EAL rates — flood + tornado + seismic + fire.
The tornado leg was built from the **NOAA Storm Prediction Center** 1950–2023
tornado database: count touchdowns within 25 miles of a point, divide by the
record length to get an annual frequency, then convert frequency → expected
annual loss with a **fixed EF-magnitude distribution**:

```
EAL = Σ_EF  freq · P(EF) · (path_area_EF / strike_circle) · damage_ratio_EF
```

Two structural flaws:

1. **One regional EF mix applied nationally.** `P(EF)` = `{EF0 .45, EF1 .33,
   EF2 .14, EF3 .06, EF4 .02}` was calibrated to the **TN/Mid-South** (Ashley
   2007). Every US location — Oklahoma, Kansas, coastal California — was scored
   with Mid-South tornado *intensities*. Only the local *count* varied; the
   damage-per-tornado assumption did not.
2. **Operationally fragile.** The model downloaded a ~7.8 MB national CSV at
   runtime and cached it to a repo-root file (`spc_tornadoes_raw.csv`). Offline
   (CI, the bundled simulator) it fell back to a **flat national-average
   frequency of 0.5/yr** — a single number for the entire country — and whether
   the real file happened to be cached made the *offline* score
   **non-deterministic** between environments.

## The fix

Read the tornado **expected-annual-loss rate** straight from the **FEMA National
Risk Index** (NRI) — the same authoritative, keyless, bundled source already used
for wildfire. NRI defines expected annual loss as

```
EAL = Exposure × AnnualizedFrequency × HistoricLossRatio
```

so the dimensionless **EAL rate** (fraction of building value lost per year) is

```
trnd_eal_rate = TRND_AFREQ × TRND_HLRB
```

the same units as the flood / seismic / fire rates. Crucially, the
**HistoricLossRatio is itself local** — it reflects the observed building-loss
experience of that county/tract — so both the frequency *and* the severity now
vary by where the home sits. NRI also carries `TRND_RISKR`, FEMA's qualitative
tornado risk rating, which we surface for display.

### Why this is more honest

| County | NRI tornado EAL rate | FEMA rating | Old SPC model |
|--------|---------------------|-------------|---------------|
| Oklahoma County, OK | 2.38e-4 /yr | Very High | Mid-South EF mix × local count |
| Shelby County, TN (Memphis) | 1.92e-4 /yr | Very High | (home region of the old EF mix) |
| Los Angeles County, CA | 7.6e-6 /yr | Relatively High | Mid-South EF mix × ~0 count |

"Tornado alley" now reads ~**30×** the low-risk West in the raw data — a spread
the old model structurally *could not* express, because it held EF severity
constant and only the touchdown count moved.

## Data & build

`scripts/build_nri_tornado.py` fetches the two public FEMA NRI Esri Feature
Services (same org as the wildfire build) and bundles them offline:

- county : `National_Risk_Index_Counties/FeatureServer/0` — 3,232 counties → `nri_tornado.csv`
- tract  : `National_Risk_Index_Census_Tracts/FeatureServer/0` — 85,154 tracts → `nri_tornado_tracts.csv.gz`

National tract build: **85,154 tracts, 99.6% with a positive rate**; distribution
of positive rates p50=3.75e-5, p90=1.64e-4, p99=2.89e-4, max=6.29e-4 /yr.

`data/tornado.py` is a resolution-aware loader mirroring `data/wildfire.py`:
`tornado_for_tract` resolves **tract → parent county → national average**,
`tornado_for_county` resolves **county → national average**. Every result carries
a `geo_level` (`tract`/`county`/`us`) and `resolved` flag; it always returns a
dict, never None. Loaded through the shared columnar `TractStore` (memory-lean on
the 512 MB instance).

## Wiring (both scoring paths, like wildfire)

- **Path B — live simulator / API** (`simulate/location.py` → `house.py`):
  `location.tornado` resolves tract→county→US; `build_label_parts` passes its
  `eal_rate` into the resilience model as `cfg["tornado_eal_base"]`. No lat/lon
  frequency scan, no download, no EF distribution.
- **Path A — batch parcel pipeline** (`enrich/tornado.py` → `score/resilience.py`):
  `enrich/tornado.py` now mirrors `enrich/fire.py` — resolves each parcel
  tract→county→US and writes `tornado_nri_eal_rate` (+ `tornado_risk_rating`,
  `tornado_geo_level`). `score/resilience.py`'s `calc_tornado_eal` reads that rate
  directly (mirroring `calc_fire_eal`); the EF distribution / path-area / damage-
  ratio constants and the frequency→EAL math are removed. In the Shelby pipeline
  the tornado stage runs before the tract is attached, so every parcel resolves at
  the **county** level (Shelby = 47157) — uniform and correct for a single-county
  batch.

The BRM (Building Resilience Modifier) and all above-code wind/tornado bonuses
(FEMA P-361 safe room, IBHS FORTIFIED, hurricane straps, hip roof, …) are
unchanged — they still multiply the tornado EAL. Only the *hazard input* changed.

## Score impact

Offline scores shift, deterministically, in the honest direction and the golden
snapshot is regenerated to match:

- **Shelby** (baseline / worst-case / icf / fortified): tornado EAL rises (old
  offline used the flat 0.5/yr fallback → ~5e-5; Shelby's true NRI rate is
  1.92e-4), so resilience nudges down a few tenths and expected annual loss up a
  few dollars.
- **Los Angeles**: essentially flat (NRI 7.6e-6 vs the old model's ~0 for a
  near-zero LA touchdown count).

Because NRI is fully bundled and offline, the tornado leg is now **identical
across CI and any local environment** — the old download-cache non-determinism
(the source of a long-standing `baseline_la` golden flake) is gone, and the stray
`spc_tornadoes_raw.csv` cache is deleted.

## Caveats & further work

- NRI is a **present-day baseline**, not a forward climate projection. Tract is
  the finest resolution — a representative sub-county value, not parcel precision.
- HistoricLossRatio can be noisy in low-frequency counties; NRI's own smoothing is
  inherited as-is.
- Path A's tornado stage could be reordered to run after the tract is attached to
  gain tract-level resolution within Shelby, but the intra-county spread is small
  and county-level is correct for a single-county batch.
