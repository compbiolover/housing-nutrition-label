# Code Audit — Streamlining & Performance

_Audit date: 2026-07-08 · Scope: `src/housing_label/` (~11,900 LOC)._

A structured audit of the runtime package for two goals: **streamlining** (line
count / function complexity) and **performance** (CPU cycles / memory). Every
finding cites `file:line` and was verified against the code. Findings are ranked
within each section by value = impact × confidence, low-risk first.

Two correctness bugs surfaced incidentally during the sweep; they are listed
first because they are cheap to fix and one changes output.

---

## 0. Correctness bugs found incidentally

| # | Location | Issue | Fix |
|---|----------|-------|-----|
| **B1** | `ingest/clean.py:67` | `str(row["ADRNO"]).strip().rstrip(".0")` strips a *character set* `{'.','0'}`, not a `.0` suffix. Since the CSV is read with `dtype=str`, a plain house number like `"2100"` becomes `"21"` — **any address ending in `0` is mangled**. The following `str(int(float(adrno)))` already handles the `"2100.0"` → `"2100"` case, so the `.rstrip` is both redundant and harmful. | Delete `.rstrip(".0")`. |
| **B2** | `enrich/infrastructure.py:271` `fire_cost` | Dead function (no callers — superseded by `_fire_dist_multiplier` at :298) that also compares a **distance** against a **multiplier** constant: `if dist_mi < FIRE_DIST_MULTIPLIER_INNER` (0.85) instead of `FIRE_INNER_THRESHOLD_MI`. The inline comment "variable name collision guard" flags the author was aware. | Delete the function. |

---

## 1. Performance

### P1 — `SCORED_CSV` re-read on every `simulate()` call · **hot path, highest value**
`simulate/house.py:966`
```python
scored = pd.read_csv(SCORED_CSV, usecols=["resilience_score"], low_memory=False) \
    if (local_compare and SCORED_CSV.exists()) else None
```
`simulate()` re-reads and re-parses the **entire** `shelby_parcels_scored.csv`
(one column of the full county parcel set) on every call for any Shelby
location. `simulate()` runs multiple times per API request: `/presets` scores 5
presets at the Memphis default coord → 5 reads/request; `/label` adds a baseline
pass; `/density` runs up to 6. The file content is invariant.

**Fix:** load the `resilience_score` Series once behind a module-level
`@lru_cache(maxsize=1)` loader keyed on the path (the exact pattern already used
in `data/climate.py`, `data/egrid.py`, etc.), and have `compute_local_percentile`
take the cached array. Also removes the double `.dropna()` (`:968` then again
inside `compute_local_percentile` at `:593`).
**Impact:** eliminates 2–6 full-CSV disk reads + parses per API request.
**Confidence:** high · **Risk:** low (bundled static data; same staleness
assumption as every other `data/*` loader). _Independently found by three
reviewers._

### P2 — Row-wise `df.apply(..., axis=1)` over the full parcel set · batch scorer
`score/resilience.py:737-743`
```python
df["flood_eal_rate_raw"]   = df.apply(calc_flood_eal,   axis=1)
df["tornado_eal_rate_raw"] = df.apply(calc_tornado_eal, axis=1)
df["seismic_eal_rate_raw"] = df.apply(calc_seismic_eal, axis=1)
df["fire_eal_rate_raw"]    = df.apply(calc_fire_eal,    axis=1)
brm_df = df.apply(calc_brm_row, axis=1, result_type="expand")
```
Five Python callbacks invoked once per parcel over the whole table. Most are
trivially vectorizable — verified:
- `calc_flood_eal` (`:75`) is a dict lookup → `df["flood_risk"].map(FLOOD_EAL).fillna(FLOOD_EAL["minimal"])`.
- `calc_tornado_eal` (`:133`) is **exactly `freq × constant`** — every term in the
  EF loop is `freq · ef_frac · (path_area/CIRCLE_AREA) · damage_ratio`, and the
  bracketed sum has no row dependence. Precompute `TORNADO_EAL_PER_FREQ` once at
  module load → single column multiply.
- `calc_seismic_eal` (`:190`) is a step function → `np.select`/`pd.cut` on the two PGA columns.
- `eal_rate_to_score` (5 `.apply` calls at `:766-770`) is log-linear interpolation
  → `np.interp` (the sibling `all_dimensions._loglinear` already does this).
- `calc_brm_row` (`:743`) is the heaviest per-row cost (builds an 8-value dict via
  6+ scalar helpers); vectorize column-wise with `Series.map` on the factor tables
  + `np.clip`, gated by a `has_cama = df["YRBLT"].notna()` mask.

**Impact:** converts ~5 Python passes over the full parcel table into vectorized
numpy — orders of magnitude on the batch scorer. **Confidence:** high (flood/
tornado/seismic), medium (`calc_brm_row` NaN handling) · **Risk:** low → medium.

### P3 — Walk Score (paid API) not process-cached, unlike sibling location dims
`simulate/dimensions.py:521`
```python
s = walk_mod.fetch_scores(api_key, lat, lon, "")
```
`_places_table` (`:410`), `_acs_table` (`:417`) and `_tract_for` (`:425`) are each
`@lru_cache`-wrapped, but the Walk Score call is invoked directly and
`walkscore.fetch_scores` is not memoized. The api.py TTL cache only collapses
byte-identical requests, so two distinct requests for the same coordinate re-hit
the **paid** key within one process. **Fix:** add an `@lru_cache`-wrapped
`_walk_score(round(lat,6), round(lon,6))` mirroring the siblings.
**Impact:** removes redundant paid-API calls for repeat/nearby coords; makes the
caching policy consistent across all three location dimensions.
**Confidence:** medium · **Risk:** low.

### P4 — Nested per-row `apply` haversine inside a per-parcel loop · batch
`enrich/tornado.py:119` (driven by the loop at `:217`)
```python
dists = tornadoes.apply(lambda r: haversine_miles(lat, lon, r["slat"], r["slon"]), axis=1)
```
`enrich_parcel` computes distances with a Python `apply` over all nearby
tornadoes, and it runs once per parcel → O(parcels × tornadoes) interpreted work.
A vectorized numpy haversine already exists in the codebase
(`simulate/house.py:499 _haversine_miles_np`). **Fix:** apply it over
`tornadoes["slat"].to_numpy()` / `["slon"].to_numpy()`.
**Confidence:** high · **Risk:** low.

### P5 — `iterrows()` batch loops + column-by-column assignment · batch enrichers
`enrich/energy.py:390`, `enrich/environmental.py:407`, `enrich/durability.py:386`
```python
results = [model_parcel_energy(row) for _, row in df.iterrows()]
...
for col in COLS: df[col] = enriched[col]   # one column at a time
```
`iterrows()` boxes each row as a `pd.Series` (dtype boxing + index construction) —
the slowest iteration primitive, dominant when enriching a full county pull. The
model fns only use `row.get(...)`, so `for row in df.to_dict("records")` is a
drop-in (absent optional columns still return `None`). Separately, the
column-by-column assignment triggers repeated block-manager consolidation
(pandas fragmentation warnings) → replace with one `pd.concat([df, enriched], axis=1)`.
**Impact:** ~3–10× faster iteration on large pulls, no behavior change.
**Confidence:** high (iteration), medium (concat semantics) · **Risk:** low.

### P6 — Grade columns via `.apply(scalar_fn)` · batch, minor
`score/resilience.py:766-785`, `score/all_dimensions.py:332-346`
~15 `series.apply(score_to_grade)` / `.apply(percentile_to_local_grade)` calls map
a scalar step-function over a column. Replace with `pd.cut(score,
bins=[-inf,20,40,60,80,inf], labels=["F","D","C","B","A"])` (NaN-aware). Bundle
with P2 when touching these files. **Confidence:** medium-high · **Risk:** low-med
(must reproduce the `—`/`N/A` output for NaN).

### P7 — House-path micro-recomputation · minor, low risk
- `simulate/house.py:814` `nmsz_dist = haversine_miles(...)` is stored into `r`
  (`:820`) but **never read back** anywhere — a discarded trig computation per call.
  Delete both.
- `per_unit_home_value(cfg)` computed at `:958` (in `simulate`) and again at `:1469`
  (in `dimension_details`); `effective_structure(cfg, location)` recomputed 3× per
  label (`:1220`, `:1593`, `:1705`). Compute once and thread through.

### P8 — Micro-conversions on lookup paths · negligible
- `data/egrid.py:73` converts lb→kg per `egrid_for_county` call (this fn is **not**
  `lru_cache`'d, unlike its `_crosswalk`); pre-convert the subregion table once at
  module load.
- `enrich/structure.py:173` computes the nearest squared-distance twice
  (`min(..., key=d2)` then `d2(nearest)`); store it.

---

## 2. Streamlining (line count / complexity)

### S1 — Cross-module helper duplication · largest line win (~150–200 lines)
The same small helpers are copy-pasted across modules; centralizing them removes
lines **and** a real maintenance hazard (fixes must currently be applied N times):

| Helper | Duplicated at | Consolidate to |
|--------|---------------|----------------|
| `haversine_miles` (scalar) | `utils.py:91` (canonical), `enrich/seismic.py:88`, `enrich/infrastructure.py:240`, `enrich/tornado.py:71`, `simulate/house.py:396`, near-copy `enrich/seismic_lookup.py:93` | import from `housing_label.utils` |
| `_num()` coercion | `data/{climate_projections:179, wildfire:54, multifamily_value:64, govfinance:51, propertytax:48}` (byte-identical) + variants in `environmental.py:208`, `structure.py:86` | `data/_util.py` |
| geoid→row CSV/`.gz` loader (`_load_rows`) | `data/climate_projections.py:188`, `data/wildfire.py:63`, plus the DictReader variants in `govfinance/propertytax/multifamily_value` | `data/_csvload.py` (parameterized by geoid column + width) |
| `_clean_tract`, `get_census_tract`, `_resolve`, geocoder retry constants | `enrich/health.py` ↔ `enrich/socioeconomic.py` (byte-for-byte) | shared `enrich/_geocode.py` |

**Caveat (verified):** do **not** delete `utils.py` wholesale — `http_get`/
`http_post` are unused, but `webmercator_to_wgs84` is referenced by
`tests/test_build_loca2.py` as a reference oracle, and `shelby_parcels.py:154`
keeps its own inline copy. The right direction is to point the inline copies
(incl. `shelby_parcels._get`/`_post`, which differ only by HTTP verb, `:55`/`:72`)
at `utils`, not to remove `utils`. Some enrich/data modules are designed to run
standalone (`python enrich/seismic.py`) — confirm run mode before consolidating.
**Confidence:** high · **Risk:** low-med.

### S2 — `house.py` printer boilerplate & hand-rolled word-wrap (~25 lines)
- Box-drawing scaffold (`INNER=64`, `TOP/SEP/BOT`, local `def row`/`section`) is
  re-declared identically in `print_scorecard` (`:1053`), `print_label` (`:1338`),
  and `print_density` (`:1899`) → one module-level `_box(inner=64)` helper.
- `_wrap` (`:1322`) reimplements `textwrap.wrap`; replace with
  `textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)`
  (flags preserve current no-break behavior for over-long tokens).
**Confidence:** high · **Risk:** low.

### S3 — Duplicated request validation in `/label` vs `/density` (~30 lines)
`api.py:340-362` vs `:538-560`. The address check, the `_validate` loop over
(preset, construction, foundation, condition, flood_zone), the `bldg_material`
normalize/validate, the `stories` check, and the `upgrade_list` dedupe +
`BONUS_FLAGS`/`ELEVATION_FLAGS` validation are copy-pasted verbatim across both
endpoints → extract `_validate_common(...)` returning the normalized
`(bldg_material, upgrade_list)`. **Confidence:** high · **Risk:** low.

### S4 — Enricher `main()` scaffolds are clones (~150 lines)
`enrich/energy.py:335-402`, `enrich/environmental.py:350-420`,
`enrich/durability.py:325-399`. `_resolve_path` is identical 3×; the argparse
block, input-exists check, `read_csv`, required/optional-column checks, `--limit`,
dry-run plan, enrich loop, `to_csv`, and row-count warning share one shape,
differing only in column list / model fn → a shared `run_enrichment(model_fn,
cols, required, ...)` runner (keep per-module summary printing as a callback).
**Confidence:** medium · **Risk:** medium.

### S5 — `health.py` ↔ `socioeconomic.py` summary + geocode-loop clones (~55 lines)
Near-identical box-summary reporting blocks (`health.py:407-490` /
`socioeconomic.py:472-554`: header, quantile stats, top/bottom-5, 10-row sample)
and the "rows-needing-geocoding → iterrows → checkpoint every N → sleep" loop
(`health.py:358-375` / `socioeconomic.py:425-442`) → factor
`print_enrichment_summary(...)` and `geocode_missing_tracts(...)` (pairs with S1).
Also: `socioeconomic.py:241-244` coerces each ACS column with `pd.to_numeric`
**twice** (the second is wasted — the column is already float); and
`census_tract.dropna()` is materialized twice in the same out-of-county
expression (`:480-485`, twin at `health.py:417-422`).
**Confidence:** medium · **Risk:** low-med.

### S6 — Grade / interp helpers defined in both scoring modules (~35 lines)
`score_to_grade` and `percentile_to_local_grade` exist in both
`score/all_dimensions.py:100-131` and `score/resilience.py:292-353` with the same
thresholds (all_dimensions adds NaN handling); `_loglin` (scalar) and `_loglinear`
(Series) reimplement the same log interpolation. Keep the NaN-aware pair in one
module and import. The walk/transit/bike composite weights are also hardcoded
inline at `dimensions.py:526-530` while `all_dimensions.WALK_WEIGHTS` already
exists — reuse it (divergence is a correctness risk). **Confidence:** high · **Risk:** low.

### S7 — Small dead code / redundant idioms
| Location | Issue | Fix |
|----------|-------|-----|
| `simulate/house.py:153` | `{**{k: v for k, v in CONSTRUCTION_FACTOR.items()}, "icf": 0.45}` — inner comprehension is an identity copy | `{**CONSTRUCTION_FACTOR, "icf": 0.45}` |
| `simulate/house.py:881-934` | ~20 lines of `if cfg.get(flag): x *= CONST`; the flag→factor pairs already exist implicitly in `BONUS_MODIFIER_DESC` (`:1021`) | one `{flag: (factor, hazard)}` table driving both (keep fortified-supersede + elevation-exclusive as explicit special cases) |
| `enrich/energy.py:83` | `CLIMATE_ZONE = "4A"` dead (live one is `DEFAULT_CLIMATE_ZONE` at `:117`) | delete |
| `enrich/infrastructure.py:268` | trailing `return float(anchors[-1][1])` in `interp_cost` is unreachable given the guards at `:260-263` | delete |
| `api.py:280` | `float(lat)`/`float(lon)` re-cast values already returned as `float` by `_coord` (Photon twin at `:248` omits them) | use directly |

---

## 3. Verified already-good (do **not** "fix")

Recorded so effort isn't spent on non-problems:
- **All `data/*` bundled-CSV loaders** (`climate`, `egrid`, `propertytax`,
  `govfinance`, `multifamily_value`, `wildfire`, `climate_projections`) already use
  `@lru_cache(maxsize=1)` singletons — CSV/`.gz` read + decompressed once per
  process. The "CSV re-read per call" hypothesis does **not** apply here; the real
  per-call lever is the `iterrows`/`apply` loops (P2/P4/P5).
- **No import-time work:** `__init__.py` is trivial; every `read_csv`/loader is
  inside a function or lazy cache.
- **Request-path network calls are cached:** `enrich/structure.py:148`,
  `enrich/seismic_lookup.py:41/61`, the health/socio/tract wrappers in
  `simulate/dimensions.py`, and `simulate/house.py:_load_spc` (module singleton).
  Walk Score (P3) is the lone exception.
- `dimensions.py` `lru_cache` tables (`:410-428`) and `density_comparison`'s
  baseline caching are the right approach.

---

## Suggested implementation order

1. **B1, B2** — correctness; tiny diffs. _(fix now)_
2. **P1** — biggest runtime win, low risk, isolated. _(fix now)_
3. **S7 + S2** — safe mechanical line reductions (~40 lines). _(fix now)_
4. **S1** — largest line win (~150–200 lines) but touches many files; do as its own
   PR with the standalone-run caveat in mind.
5. **P2, P4, P5, P6** — batch-path vectorization; guard each with the existing
   pipeline tests, land incrementally.
6. **S3–S6, P3, P7, P8** — medium-value cleanups as capacity allows.

Estimated removable/reducible: **~450–550 lines** via dedup (S1/S3/S4/S5/S6),
plus meaningful complexity reduction in `house.py`/`resilience.py` and the
batch-scorer speedups.

_Note: batch-path items (P2/P4/P5/P6, the enricher/scorer scaffolds) run in the
CLI pipeline, not per API request — high absolute value on full-county pulls,
lower urgency than the P1 request-path fix._
