# Shelby County Parcels — Data Exploration Report

**Source file:** `shelby_parcels_sample.csv`
**Report generated:** 2026-04-01
**Dataset shape:** 1,000 rows × 39 columns

---

## Table of Contents

1. [Dataset Overview](#1-dataset-overview)
2. [Field Coverage](#2-field-coverage)
3. [Value Distributions — Numeric Fields](#3-value-distributions--numeric-fields)
4. [Value Distributions — Categorical Fields](#4-value-distributions--categorical-fields)
5. [Address Completeness & Geocodability](#5-address-completeness--geocodability)
6. [Data Quality Issues](#6-data-quality-issues)
7. [Housing Nutrition Label — Dimension Mapping](#7-housing-nutrition-label--dimension-mapping)

---

## 1. Dataset Overview

This is a sample of 1,000 parcels from the Shelby County, Tennessee GIS parcel database. The data is a join between two GIS layers:

- **`GISWEB.GISADMIN.Parcels`** — the spatial/geographic parcel record (geometry, parcel IDs, map references, land codes, acreage, administrative geography)
- **`GISWEB.VIEWER.ParcelOwnDetails`** — the ownership and mailing address record linked to each parcel

The 39 columns cover: parcel identifiers, administrative geography codes, land use codes, acreage, ownership names, property address, mailing address, edit audit fields, and free-text notes.

### Complete Column List

| # | Column | Description (inferred) |
|---|--------|------------------------|
| 1 | `GISWEB.GISADMIN.Parcels.OBJECTID` | Internal GIS row ID (parcel layer) |
| 2 | `PARCEL_TYPE` | Type code — all values = 1 in this sample |
| 3 | `MAP` | Assessor map sheet reference (e.g. "193F") |
| 4 | `PARCELID` | Primary human-readable parcel identifier |
| 5 | `PARCELID2` | Secondary parcel ID — nearly entirely empty |
| 6 | `CITY` | Single-letter or numeric city code (e.g. "D" = District, "0" = unincorporated) |
| 7 | `DISTRICT` | Tax district number (1 or 2) |
| 8 | `WARD` | City ward number |
| 9 | `D_BLOCK` | District block number |
| 10 | `C_BLOCK` | City block number |
| 11 | `D_INSERT` | District insert code (two-letter pairs) |
| 12 | `C_INSERT` | City insert code (single letter) |
| 13 | `PARCEL` | Parcel sub-number within a block |
| 14 | `CODE` | Land use / property class code |
| 15 | `created_user` | GIS user who created the record |
| 16 | `created_date` | Creation timestamp (Unix ms) |
| 17 | `last_edited_user` | GIS user who last edited the record |
| 18 | `last_edited_date` | Last-edit timestamp (Unix ms) |
| 19 | `CALC_ACRE` | Calculated area in acres |
| 20 | `GISWEB.VIEWER.ParcelOwnDetails.OBJECTID` | Internal GIS row ID (ownership layer) |
| 21 | `PARID` | Parcel ID from the ownership table (mirrors PARCELID) |
| 22 | `OWN1` | Owner name line 1 |
| 23 | `OWN2` | Owner name line 2 (overflow) |
| 24 | `ADRNO` | Property street number |
| 25 | `ADRDIR` | Street direction prefix (N/S/E/W) |
| 26 | `ADRSTR` | Street name |
| 27 | `ADRSUF` | Street type suffix (RD, DR, AVE, etc.) |
| 28 | `ADRSUF2` | Post-directional suffix (E/W/N/S) |
| 29 | `CITYNAME` | Full city name (property location) |
| 30 | `STATECODE` | State abbreviation |
| 31 | `UNITNO` | Unit/suite number |
| 32 | `UNITDESC` | Unit descriptor (STE, APT, UNIT, etc.) |
| 33 | `ADDR1` | Mailing address line 1 (alternate/overflow) |
| 34 | `ADDR2` | Mailing address line 2 (c/o, agent name) |
| 35 | `ADDR3` | Mailing address line 3 — nearly entirely empty |
| 36 | `ZIP1` | 5-digit ZIP code |
| 37 | `ZIP2` | ZIP+4 extension |
| 38 | `NOTE1` | Free-text note 1 (admin change log) |
| 39 | `NOTE2` | Free-text note 2 (parcel history — splits/combines) |

---

## 2. Field Coverage

**Legend:** "Filled %" = rows with a non-null, non-empty, non-whitespace value. Columns flagged `MOSTLY EMPTY` have >80% null/blank values.

| Column | Filled % | Unique Values | Dtype | Flag |
|--------|----------|--------------|-------|------|
| `GISWEB.GISADMIN.Parcels.OBJECTID` | 100.0% | 1,000 | int64 | |
| `PARCEL_TYPE` | 100.0% | 1 | int64 | |
| `MAP` | 100.0% | 297 | str | |
| `PARCELID` | 100.0% | 1,000 | str | |
| `PARCELID2` | 0.0% | 2 | str | **MOSTLY EMPTY** |
| `CITY` | 100.0% | 8 | str | |
| `DISTRICT` | 59.1% | 2 | float64 | |
| `WARD` | 41.5% | 64 | float64 | |
| `D_BLOCK` | 59.1% | 46 | float64 | |
| `C_BLOCK` | 41.5% | 85 | float64 | |
| `D_INSERT` | 52.1% | 98 | str | |
| `C_INSERT` | 25.8% | 14 | str | |
| `PARCEL` | 100.0% | 324 | str | |
| `CODE` | 88.1% | 3 | float64 | |
| `created_user` | 0.5% | 3 | str | **MOSTLY EMPTY** |
| `created_date` | 0.5% | 5 | float64 | **MOSTLY EMPTY** |
| `last_edited_user` | 100.0% | 2 | str | |
| `last_edited_date` | 100.0% | 9 | int64 | |
| `CALC_ACRE` | 100.0% | 996 | float64 | |
| `GISWEB.VIEWER.ParcelOwnDetails.OBJECTID` | 100.0% | 1,000 | int64 | |
| `PARID` | 100.0% | 1,000 | str | |
| `OWN1` | 100.0% | 853 | str | |
| `OWN2` | 7.1% | 38 | str | **MOSTLY EMPTY** |
| `ADRNO` | 93.4% | 732 | float64 | |
| `ADRDIR` | 9.8% | 5 | str | **MOSTLY EMPTY** |
| `ADRSTR` | 99.9% | 520 | str | |
| `ADRSUF` | 89.1% | 23 | str | |
| `ADRSUF2` | 6.2% | 5 | str | **MOSTLY EMPTY** |
| `CITYNAME` | 99.9% | 90 | str | |
| `STATECODE` | 99.9% | 29 | str | |
| `UNITNO` | 9.7% | 52 | str | **MOSTLY EMPTY** |
| `UNITDESC` | 9.5% | 6 | str | **MOSTLY EMPTY** |
| `ADDR1` | 0.1% | 1 | str | **MOSTLY EMPTY** |
| `ADDR2` | 10.4% | 70 | str | **MOSTLY EMPTY** |
| `ADDR3` | 0.1% | 1 | str | **MOSTLY EMPTY** |
| `ZIP1` | 99.9% | 137 | float64 | |
| `ZIP2` | 57.8% | 412 | float64 | |
| `NOTE1` | 33.8% | 222 | str | |
| `NOTE2` | 54.7% | 219 | str | |

### Summary: Columns Flagged as Mostly Empty (>80% null)

| Column | Filled % | Notes |
|--------|----------|-------|
| `PARCELID2` | 0.0% | Appears unused; 2 non-null values are blank strings |
| `created_user` | 0.5% | Audit field — only 5 records have a create user |
| `created_date` | 0.5% | Only 5 rows have a creation timestamp |
| `OWN2` | 7.1% | Overflow for long owner names |
| `ADRDIR` | 9.8% | Pre-directional only needed for some streets |
| `ADRSUF2` | 6.2% | Post-directional only needed for some streets |
| `UNITNO` | 9.7% | Only commercial/multi-unit parcels have units |
| `UNITDESC` | 9.5% | Paired with UNITNO |
| `ADDR1` | 0.1% | Single row (foreign mailing address) |
| `ADDR2` | 10.4% | c/o name or agent — mostly empty |
| `ADDR3` | 0.1% | Single row (Japanese address) |

---

## 3. Value Distributions — Numeric Fields

The following 14 columns were automatically detected as numeric by pandas type inference.

### `GISWEB.GISADMIN.Parcels.OBJECTID`
- Sequential row ID, 1–1000. No analytical value.
- count=1,000 | min=1 | max=1,000 | mean=500.50 | median=500.5 | std=288.82

### `PARCEL_TYPE`
- **All 1,000 values = 1.** Zero variance. This column is constant in the sample and carries no information for analysis.

### `DISTRICT`
- Tax district: only 2 possible values (1 or 2).
- count=591 | min=1.0 | max=2.0 | mean=1.64 | median=2.0 | std=0.48
- District 2: 378 records (64%) | District 1: 213 records (36%)
- 409 records (40.9%) have no district assigned (likely unincorporated / city parcels)

### `WARD`
- City ward number, ranges 1–96.
- count=415 | min=1.0 | max=96.0 | mean=61.72 | median=74.0 | std=26.76
- 585 records (58.5%) have no ward assigned (unincorporated or county parcels)

### `D_BLOCK`
- District block number.
- count=591 | min=4.0 | max=65.0 | mean=32.04 | median=32.0 | std=17.90

### `C_BLOCK`
- City block number — wider range, higher variance.
- count=415 | min=1.0 | max=622.0 | mean=95.26 | median=72.0 | std=125.24
- High std relative to mean suggests a long-tailed, non-uniform distribution.

### `CODE` — Land Use / Property Class Code
- Only 3 distinct values in this sample:
  - **604**: 853 records (96.8% of those with a code) — primary residential/agricultural use
  - **717**: 27 records (3.1%) — likely exempt/public property
  - **673**: 1 record (0.1%)
- count=881 | min=604 | max=717 | mean=607.54 | median=604.0 | std=19.61
- 119 records (11.9%) have no CODE assigned.

### `created_date`
- Unix timestamp in milliseconds. Only 5 records populated.
- Values cluster in 2014–2015 (Unix ms ~1.40–1.43 × 10¹²).
- Not reliable for analysis due to near-complete absence.

### `last_edited_date`
- Unix timestamp in milliseconds. All 1,000 records populated.
- Most values cluster in a very narrow band (1517524895000–1517524899000), which converts to approximately **February 1–2, 2018** — suggesting a bulk data migration or re-export event for 991 of 1,000 records.
- 9 distinct values total; 6 records have a later edit date (February 13–14, 2018).

### `CALC_ACRE` — Parcel Size in Acres
- count=1,000 | min=0.00517 | max=3,245.33 | mean=7.58 | median=0.242 | std=136.51
- The median of 0.24 acres (~10,450 sq ft) indicates most parcels are residential-scale.
- The mean of 7.58 acres is heavily skewed by 2 very large parcels (3,245 and 2,848 acres).
- **Top 10 largest parcels:** 3,245.3 | 2,847.8 | 85.6 | 53.4 | 51.4 | 46.7 | 45.7 | 39.3 | 29.4 | 27.9 acres
- 0 parcels have zero or negative acreage (no impossible values detected).

### `GISWEB.VIEWER.ParcelOwnDetails.OBJECTID`
- Internal ownership table row ID, ranges 697–351,609. Non-sequential; reflects the original full database order.

### `ADRNO` — Street Number
- count=934 | min=4.0 | max=34,332.0 | mean=4,094.27 | median=2,675.5 | std=3,961.84
- 66 records (6.6%) have no street number.
- The maximum of 34,332 is consistent with Shelby County's extended street numbering on rural roads east of Memphis.

### `ZIP1` — 5-digit ZIP Code
- count=999 | min=820.0 | max=96,816.0 | mean=40,457.94 | median=38,109.0 | std=11,411.48
- **Warning:** min=820 and values below 38000 indicate out-of-area mailing addresses (this is the owner's mailing ZIP, not the property ZIP). ZIP 38xxx is the Memphis/Shelby County range.
- ZIP 96816 is Honolulu, Hawaii — confirming out-of-state owner addresses are present.
- **Length distribution:** 996 values are 5 digits; 2 are 4 digits (leading zero dropped); 1 is 3 digits — all represent truncated ZIP codes due to numeric storage (e.g., 01234 stored as 1234). This is a data quality issue.

### `ZIP2` — ZIP+4 Extension
- count=578 | min=1.0 | max=9,999.0 | mean=4,824.41 | median=4,486.0 | std=2,659.36
- Only 57.8% of records have a ZIP+4.
- **Length distribution:** 537 are 4-digit (correct), 39 are 3-digit, 1 is 2-digit, 1 is 1-digit — leading zeros stripped by numeric storage.

---

## 4. Value Distributions — Categorical Fields

### `MAP` — Assessor Map Sheet Reference
- 297 unique map sheet codes across 1,000 parcels.
- Format: numeric or alphanumeric (e.g., "193F", "81", "138L").
- Top 5: 193F (60), 138L (29), 153K (26), 120J (25), 81 (24)
- High count for "193F" (6% of sample) suggests this map sheet covers a densely subdivided area.

### `PARCELID` / `PARID`
- Both columns are identical (PARID mirrors PARCELID from the ownership join).
- All 1,000 values are unique — confirmed primary key.
- Format is inconsistent: some use numeric prefixes (`096200  00178C`), others use letter prefixes (`D0222K A00027`). The letter prefix appears to indicate a specific subdivision or district type. Whitespace padding is used as a field delimiter within the string.

### `PARCELID2`
- 899 blank strings, 77 NaN, 24 blank after strip. Effectively 0% populated. Should be dropped or ignored.

### `CITY` — City Code (Single Character / Number)
- 8 unique values, all short codes:
  - `0`: 415 (41.5%) — unincorporated Shelby County
  - `D`: 285 (28.5%) — likely a district designation
  - `A`: 70 (7.0%)
  - `G`: 67 (6.7%)
  - `L`: 60 (6.0%)
  - `C`: 53 (5.3%)
  - `B`: 44 (4.4%)
  - `M`: 6 (0.6%)
- **Note:** This is a coded field, not a full city name. `CITYNAME` is the human-readable equivalent. The numeric "0" is mixed with letter codes — flagged as a mixed-type field.

### `DISTRICT`
- See numeric section above. Values: 1 (District 1), 2 (District 2), or missing.

### `D_INSERT` and `C_INSERT`
- Internal geographic sub-division codes used within the assessor system.
- `D_INSERT` uses two-letter pairs (e.g., "B A", "F B"); 48% null.
- `C_INSERT` uses single letters (A–T); 74.2% null.
- Likely used for fine-grained map indexing.

### `PARCEL`
- Sub-parcel number within a block (e.g., "8", "11", "6"). Values are small integers as strings.
- 324 unique values, heavily reused (676 duplicates expected since these are only unique within a block+map combination).

### `CODE` — Land Use / Property Class
- See numeric section. Three values: 604, 717, 673.

### `created_user` / `last_edited_user`
- `created_user`: Nearly empty (0.5%). Three users: HOLYFIEM (2), SDE (2), REDICKD (1).
- `last_edited_user`: All 1,000 populated. SDE: 994 (99.4%), BROOKSR: 6 (0.6%). "SDE" is the default ArcSDE service account — likely a system/batch account.

### `OWN1` — Owner Name
- 1,000 filled, 853 unique — 147 records share an owner name with at least one other record (institutional/corporate owners holding multiple parcels).
- Top owner: **LAKEVIEW ROAD LP** with 48 parcels (4.8% of sample) — a large land partnership.
- Other notable institutional owners: LEVI LIMITED PARTNERSHIP (15), HEALTH EDUCATIONAL AND HOUSING FACILITY (10), NORMANDY PARK HOMEOWNERS ASSOC INC (9), MEMPHIS HOUSING AUTHORITY (8).

### `OWN2` — Owner Name Line 2
- 92.9% null. When present, captures overflow text like "BOARD OF THE CITY OF MEMPHIS TENNESSEE", "ASSOCIATION INC", "TRUST", or partial ownership fractions ("KIRCHER CONSTRUCTION CO LLC (40%)").

### `ADRDIR` — Street Direction Prefix
- 90.2% null (streets without a directional prefix).
- When present: S (37), N (36), E (13), W (11), SW (1).

### `ADRSTR` — Street Name
- 99.9% filled, 520 unique street names.
- Top streets: LEVI (69), CENTRE OAK (15), POPLAR (14), MAIN (13), WHEELIS (12), PORTER (11).
- The high count for "LEVI" aligns with the LAKEVIEW ROAD LP / LEVI LIMITED PARTNERSHIP institutional ownership cluster.

### `ADRSUF` — Street Type Suffix
- 89.1% filled, 23 unique suffixes.
- Top: RD (192, 19.2%), DR (192, 19.2%), CV (141, 14.1%), ST (71, 7.1%), AVE (68, 6.8%), LN (64, 6.4%), CIR (41, 4.1%), WAY (40, 4.0%)
- "CV" (cove) is notably prevalent — typical of suburban Memphis residential street patterns.

### `ADRSUF2` — Post-Directional Suffix
- 6.2% filled. When present: E (21), W (20), N (12), S (8), NE (1).

### `CITYNAME` — City Name (Property Location)
- 99.9% filled, 90 unique values.
- This field is the **mailing city name**, not strictly the property location city — it includes out-of-area owner mailing addresses.
- **Tennessee localities in sample:** MEMPHIS (422, 42.2%), CORDOVA (158, 15.8%), GERMANTOWN (91, 9.1%), ARLINGTON (79, 7.9%), COLLIERVILLE (55, 5.5%), LAKELAND (35, 3.5%), EADS (18, 1.8%), MILLINGTON (17, 1.7%), BARTLETT (16, 1.6%)
- **Out-of-state addresses (owner mailing):** SAN DIEGO (4), ATOKA (3), DYERSBURG (3), CHARLOTTE (3), HOUSTON (3), SAN MARCOS (3), SAINT LOUIS (3), NASHVILLE (2), CHICAGO (2), etc.

### `STATECODE` — State Abbreviation
- 99.9% filled, 29 unique state codes.
- TN: 908 (90.8%), CA: 32 (3.2%), MS: 8, IL: 7, FL: 6, TX: 6 — confirms the majority are Tennessee-addressed owners with a notable California contingent.
- 1 null value.

### `UNITNO` / `UNITDESC`
- Both ~9.5–9.7% filled; present only for parcels with a specific unit.
- UNITDESC values: STE (72), APT (9), UNIT (6), # (3), FLOOR (3), BLDG (2).
- UNITNO: numeric values like 300, 3210, 100, 113 — mixed numeric strings.

### `ADDR1` / `ADDR2` / `ADDR3`
- `ADDR1`: 1 value — a Japanese address ("1-8-21-1103 NISHIJIN, SAWARA"), likely an international owner.
- `ADDR2`: 10.4% filled; used for c/o names, property managers, agents (e.g., "MEMPHIS LAND BANK INC", "KEITH S COLLINS CO LLC").
- `ADDR3`: 1 value — continuation of the Japanese address ("FUKUOKA, FUKUOKA").

### `ZIP1` / `ZIP2`
- See numeric section for statistical details.
- ZIP1 distribution confirms most parcels are in the 38xxx (Memphis/Shelby County) range.

### `NOTE1` — Administrative Note
- 33.8% filled. Common values indicate data maintenance events:
  - "SPLIT PER PB 218 PG 57" (19) — parcel split with plat book reference
  - "SEE AA 14" / "SEE AA-14" — references to an action/amendment form
  - "SEE RE-14" — references to a re-entry form
  - "CONSOL PER 05141268" — parcel consolidation
  - Address change notations
- Period-only values ("." — 15 occurrences) appear to be placeholder entries with no actual content.

### `NOTE2` — Parcel History Note
- 54.7% filled. Predominantly records parcel genealogy:
  - "CHILD OF SPLIT FROM [PARCELID]" — the dominant pattern
  - "SPLIT FROM [PARCELID]" — predecessor reference
  - Period-only values ("." — 16) are placeholder entries

---

## 5. Address Completeness & Geocodability

### Address Component Fill Rates

| Component | Column(s) | Filled % | Notes |
|-----------|-----------|----------|-------|
| Street number | `ADRNO` | 93.4% | 66 missing; likely vacant/unaddressed land |
| Street direction prefix | `ADRDIR` | 9.8% | Optional; only needed for directional streets |
| Street name | `ADRSTR` | 99.9% | 1 missing value |
| Street type suffix | `ADRSUF` | 89.1% | Some streets have no standard suffix |
| Post-directional | `ADRSUF2` | 6.2% | Optional |
| City name | `CITYNAME` | 99.9% | Mailing city — may differ from property jurisdiction |
| State | `STATECODE` | 99.9% | |
| Unit | `UNITNO` + `UNITDESC` | ~9.7% | Present only for multi-unit/commercial |
| ZIP (5-digit) | `ZIP1` | 99.9% | |
| ZIP+4 | `ZIP2` | 57.8% | Useful for precision geocoding |

### Geocodability Assessment

A row is considered geocodable if it has: **street number + street name + (city name OR ZIP code)**.

- **Geocodable rows: 934 / 1,000 (93.4%)**
- The 6.6% non-geocodable records lack a street number (`ADRNO`), which likely represent undivided/unaddressed land parcels, rights-of-way, or acreage tracts.

### Constructing a Full Address String

A full address string can be assembled as:

```
[ADRNO] [ADRDIR] [ADRSTR] [ADRSUF] [ADRSUF2] [UNITDESC] [UNITNO], [CITYNAME], [STATECODE] [ZIP1]-[ZIP2]
```

Example from row 0: `2845 N HOUSTON LEVEE RD STE 103, CORDOVA, TN 38016-0179`

### Important Caveat

`CITYNAME`, `STATECODE`, and `ZIP1`/`ZIP2` reflect the **owner's mailing address**, not necessarily the physical property location. For parcels where the owner lives out of state (9.2% of records), the mailing address ZIP/city will not match the property location. The property location is always in Shelby County, TN. For accurate property-location geocoding, the `ADRSTR`, `ADRNO`, and `ADRSUF` fields (which are the property address) should be combined with a known Shelby County city/ZIP lookup rather than blindly using `CITYNAME`/`ZIP1`.

---

## 6. Data Quality Issues

### 6.1 Duplicate Records

| Check | Result |
|-------|--------|
| Fully duplicate rows | 0 |
| Duplicate `PARCELID` | 0 |
| Duplicate `PARID` | 0 |
| Duplicate `GISWEB.GISADMIN.Parcels.OBJECTID` | 0 |
| Duplicate `GISWEB.VIEWER.ParcelOwnDetails.OBJECTID` | 0 |
| Duplicate `PARCEL` (expected — sub-number within block) | 676 |

**No true duplicate records detected.** PARCEL duplicates are expected by design.

### 6.2 ZIP Code Leading-Zero Truncation

Both `ZIP1` and `ZIP2` are stored as float64 (numeric), which silently drops leading zeros:
- **ZIP1:** 2 values are 4 digits, 1 is 3 digits — these are ZIP codes that begin with 0 (New England / Eastern states) and have been truncated.
- **ZIP2:** 39 values are 3 digits, 1 is 2 digits, 1 is 1 digit — leading zeros stripped from ZIP+4 extensions.
- **Fix:** Cast to string and left-pad with zeros to 5/4 digits respectively before use.

### 6.3 CITY Column — Mixed Type (Codes + Numbers)

The `CITY` column mixes single-letter city codes (`D`, `A`, `G`, `L`, `C`, `B`, `M`) with the numeric code `0` for unincorporated parcels. Pandas infers this as string, but `0` is semantically a numeric sentinel value. This should be documented and treated consistently — ideally mapping `0` to "Unincorporated" explicitly.

### 6.4 PARCELID Inconsistent Format

`PARCELID` (and `PARID`) contains two distinct format patterns:
- **Numeric prefix:** e.g., `096200  00178C` — appears to be older legacy numeric parcel IDs
- **Letter prefix:** e.g., `D0222K A00027` — newer format with area prefix letter
- Internal whitespace padding is used as a field separator within the ID string. Parsing requires careful handling.

### 6.5 Timestamp Encoding

`created_date` and `last_edited_date` are stored as Unix millisecond timestamps (integers), not human-readable dates. Conversion needed: divide by 1,000 and apply `datetime.fromtimestamp()`.

- `created_date` cluster: ~2014–2015
- `last_edited_date` cluster: ~February 1–2, 2018 (bulk migration event), with a handful edited February 13–14, 2018.

### 6.6 Nearly-Empty / Vestigial Columns

These columns can be dropped for most analytical purposes:

| Column | Recommendation |
|--------|----------------|
| `PARCELID2` | Drop — 0% useful data |
| `created_user` | Drop or retain for audit only — 0.5% filled |
| `created_date` | Drop or retain for audit only — 0.5% filled |
| `ADDR1` | Drop — 1 row (foreign address) |
| `ADDR3` | Drop — 1 row (Japanese address continuation) |
| `PARCEL_TYPE` | Drop — constant value (all = 1) |

### 6.7 CALC_ACRE Outliers

Two extreme outliers in parcel size:
- **3,245.33 acres** (~5.1 sq miles)
- **2,847.82 acres** (~4.5 sq miles)

These are likely large institutional, airport, or conservation parcels (consistent with `OWN1` values like "MEMPHIS SHELBY COUNTY AIRPORT AUTHORITY"). They are valid values, not errors, but will heavily skew any mean-based calculations and should be flagged in size-stratified analyses.

### 6.8 Out-of-Area / International Mailing Addresses

The mailing address fields (`CITYNAME`, `STATECODE`, `ZIP1`) reflect owner mailing addresses, not property locations. Notable anomalies:
- 1 Japanese address (FUKUOKA, Japan)
- California owners: 32 records with CA state code (ZIP range 90000–96999)
- Hawaii owner: 1 record with ZIP 96816 (Honolulu)
- Multiple out-of-state city names (Chicago, Houston, Charlotte, San Diego, etc.)

These are valid data points representing absentee/out-of-state property owners, but they make the `CITYNAME`/`ZIP1` fields unreliable as property location indicators.

### 6.9 NOTE Fields — Placeholder Periods

Both `NOTE1` and `NOTE2` contain values that are just a period (`.`) — 15 and 16 occurrences respectively. These appear to be placeholder entries indicating "no substantive note" or a data entry convention. They should be treated as null equivalents in text analysis.

### 6.10 STATECODE — One Null Value

One record has a null `STATECODE`. This may indicate an incomplete mailing address record.

### 6.11 OWN2 as Overflow Field

`OWN2` captures overflow text from owner name entries. Its values are not always standalone owner names — some are fragments of legal entity names ("ASSOCIATION INC", "TRUST") that complete a name started in `OWN1`. Concatenation logic (`OWN1 + " " + OWN2`) is needed for full legal names.

### 6.12 No Encoding Issues

No non-ASCII characters detected in any string columns. The single Japanese address in `ADDR1`/`ADDR3` uses romanized ASCII transliteration.

---

## 7. Housing Nutrition Label — Dimension Mapping

This section maps available dataset columns to the 9 scoring dimensions of the Housing Nutrition Label framework, noting which dimensions have partial coverage from this dataset and which require external data sources entirely.

---

### Dimension 1: Energy

**What it measures:** Energy consumption of the property; heating/cooling costs; solar potential; energy efficiency.

**Coverage from this dataset:** PARTIAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `CALC_ACRE` | Parcel size is a very indirect proxy for structure footprint; larger lots may indicate larger buildings |
| `CITYNAME` / `ADRSTR` | Location can be used to join external energy cost data by ZIP or census tract |
| `CODE` | Land use code 604 vs. 717 may indicate residential vs. exempt/commercial — different energy profiles |
| `ADRNO` + `ADRSTR` + `ZIP1` | Full address enables geocoding to join utility grid data, solar irradiance data |

**Missing (needs external data):**
- Building square footage, year built, construction type
- Utility provider and rate data
- Solar panel presence or rooftop solar potential scores
- HERS / Energy Star ratings
- Heating/cooling degree days (climate data)

---

### Dimension 2: Durability

**What it measures:** Structural integrity; building age; material quality; maintenance history.

**Coverage from this dataset:** MINIMAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `NOTE2` | Parcel splits/combinations may indicate subdivision of older structures |
| `CALC_ACRE` | Lot size context; very small lots may indicate infill with newer construction |
| `CODE` | Broad land use classification |
| Address fields | Enable joins to building permit databases, assessor improvement data |

**Missing (needs external data):**
- Year built / year renovated
- Construction material (wood frame, masonry, etc.)
- Building permits and inspection records
- Assessor building condition rating
- Flood claim / insurance loss history

---

### Dimension 3: Disaster Resilience

**What it measures:** Flood risk, fire risk, earthquake/tornado exposure, storm resilience.

**Coverage from this dataset:** PARTIAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `CALC_ACRE` | Parcel size context for flood inundation calculations |
| `CITYNAME` / `ZIP1` | Location enables joining FEMA flood zone maps by address |
| `ADRNO` + `ADRSTR` + `ADRSUF` + `ZIP1` | Geocodable address enables overlay with FEMA NFIP, FEMA flood zone layer, NOAA storm data |
| `NOTE1` / `NOTE2` | May contain parcel reconfiguration events related to flood buyouts or condemnations (anecdotally) |

**Missing (needs external data):**
- FEMA flood zone designation (AE, X, etc.)
- FEMA Base Flood Elevation (BFE)
- Tornado/wind risk zone data
- National Flood Insurance Program (NFIP) claims history
- Tree canopy / wildfire interface data
- Elevation data (DEM/LiDAR)

---

### Dimension 4: Walkability / Transport Cost

**What it measures:** Access to transit; walk score; bike infrastructure; distance to amenities; vehicle dependency.

**Coverage from this dataset:** PARTIAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `ADRNO` + `ADRSTR` + `ADRSUF` + `CITYNAME` + `ZIP1` | Full geocodable address is the core input for all walkability/transit APIs |
| `CITY` | City code distinguishes incorporated (Memphis, Germantown, etc.) vs. unincorporated — strong predictor of transit access |
| `CITYNAME` | Identifies municipality; Memphis proper has MATA bus service; suburbs are car-dependent |
| `WARD` | Ward-level geography can be used to join transit service area data |

**Missing (needs external data):**
- Walk Score / Bike Score / Transit Score (via API)
- GTFS transit stop proximity and frequency data
- Distance to grocery stores, schools, healthcare
- Road network / sidewalk presence
- Vehicle ownership rates (ACS census data by tract)
- Commute time / mode share data

---

### Dimension 5: Infrastructure Burden

**What it measures:** Age and condition of water/sewer/road infrastructure serving the parcel; stormwater burden; cost of future infrastructure replacement.

**Coverage from this dataset:** PARTIAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `CITY` / `CITYNAME` | Municipality determines which utility authority serves the parcel (MLGW for Memphis, separate for suburbs) |
| `CALC_ACRE` | Large parcels may represent infrastructure-sparse rural areas with higher per-unit infrastructure costs |
| `DISTRICT` | Tax district influences which municipal services are funded |
| `WARD` | Ward-level data can be joined to infrastructure age/condition datasets |
| Address fields | Geocoding enables spatial join to infrastructure GIS layers (water main age, sewer condition, etc.) |

**Missing (needs external data):**
- Water/sewer main age and material
- Road pavement condition index (PCI)
- Stormwater infrastructure data
- MLGW / utility service territory
- Municipal capital improvement plan (CIP) data
- Property tax rates and special assessment districts

---

### Dimension 6: Health Impact

**What it measures:** Air quality, noise exposure, proximity to pollution sources, green space access, food access.

**Coverage from this dataset:** MINIMAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| Address fields | Geocoding enables spatial join to EPA AirNow data, TRI facility proximity, noise contour maps |
| `CITYNAME` / `ZIP1` | ZIP-level health outcome data can be joined (CDC PLACES, etc.) |
| `CALC_ACRE` | Large-lot residential may indicate suburban low-density context with lower pollution exposure |
| `CODE` | Land use 717 (exempt/institutional) may indicate proximity to hospitals, schools, or industrial sites |

**Missing (needs external data):**
- EPA Air Quality Index data by location
- EPA Toxic Release Inventory (TRI) facility proximity
- EJSCREEN environmental justice scores
- Noise contour maps (aviation, roadway)
- Food desert designation (USDA Food Access Research Atlas)
- Proximity to parks and green space
- CDC PLACES health outcome indicators by census tract

---

### Dimension 7: Environmental Footprint

**What it measures:** Carbon footprint of the home and its location; impervious surface coverage; urban heat island effect; tree canopy.

**Coverage from this dataset:** PARTIAL / INDIRECT

| Column | How it contributes |
|--------|--------------------|
| `CALC_ACRE` | Parcel size determines maximum impervious surface; large parcels in low-density areas imply higher per-capita emissions from transportation |
| Address fields | Location enables joining to urban heat island raster data, NLCD land cover (impervious surface %), tree canopy data |
| `CITY` / `CITYNAME` | Urban vs. suburban vs. rural location — strong predictor of residential carbon footprint |
| `CODE` | Land use code can distinguish large institutional parcels (airports, industrial) with known high footprints |

**Missing (needs external data):**
- NLCD impervious surface percentage
- Tree canopy cover (NLCD or local LiDAR)
- Urban Heat Island intensity raster
- Vehicle miles traveled (VMT) estimates by location
- Residential energy consumption estimates
- Building-level greenhouse gas emission estimates

---

### Dimension 8: Bonus Features

**What it measures:** Desirable amenities or characteristics — garage, pool, accessory dwelling unit (ADU), proximity to parks, school quality, etc.

**Coverage from this dataset:** MINIMAL

| Column | How it contributes |
|--------|--------------------|
| `UNITDESC` / `UNITNO` | Presence of unit descriptors (APT, UNIT) may indicate multi-unit structures or ADUs |
| `CALC_ACRE` | Lot size context — larger lots allow for accessory structures |
| Address fields | Location joins to school district ratings, park proximity |
| `OWN1` | Homeowners associations (indicated by "HOMEOWNERS ASSOC INC" in name) suggest amenity-rich planned developments |

**Missing (needs external data):**
- Assessor improvement data (garage, pool, decks, outbuildings)
- School district ratings (GreatSchools, state report cards)
- Proximity to parks, libraries, community centers
- HOA details and amenities
- Broadband availability (FCC data)
- Flood insurance cost

---

### Dimension 9: Climate Projections

**What it measures:** Forward-looking climate risk — projected flood frequency, temperature increases, extreme heat days, storm intensity trends through 2050/2100.

**Coverage from this dataset:** NONE DIRECTLY

| Column | How it contributes |
|--------|--------------------|
| Address fields | Geocoding to get lat/lon coordinates, which are then used as inputs to all external climate projection APIs |
| `CITYNAME` / `ZIP1` | Coarse geographic anchor for climate data lookups |
| `CALC_ACRE` | Parcel size context for flood inundation volume estimates |

**Missing (needs external data) — this dimension has zero direct data coverage:**
- NOAA climate projections (temperature, precipitation by location)
- First Street Foundation Flood Factor scores
- First Street Foundation Heat Factor scores
- First Street Foundation Wind Factor / Fire Factor scores
- FEMA Flood Map Service Center future flood risk
- Sea level rise projections (less relevant for Shelby County, but upstream flood risk is relevant)
- Extreme heat day projections (days >95°F, >100°F through 2050)
- Climate Central coastal / inland flood risk scores

---

### Dimension Coverage Summary

| Dimension | Direct Coverage | Indirect / Via Geocode Join | Needs External Data |
|-----------|-----------------|----------------------------|---------------------|
| Energy | None | Low (address for joins) | High |
| Durability | None | Low (address for permits) | High |
| Disaster Resilience | None | Medium (address + FEMA) | High |
| Walkability / Transport Cost | None | High (address + city code) | Medium |
| Infrastructure Burden | None | Medium (district/ward) | High |
| Health Impact | None | Low (address for joins) | High |
| Environmental Footprint | Partial (CALC_ACRE) | Medium (address + land use) | High |
| Bonus Features | Partial (unit/HOA) | Low | High |
| Climate Projections | None | Low (address for lat/lon) | **Critical — 0% direct** |

### Key Insight: The Geocodable Address is the Dataset's Most Valuable Asset

93.4% of records in this dataset can be assembled into a geocodable address. The address is the primary bridge to every external dataset needed for all 9 scoring dimensions. This parcel dataset is therefore best understood as a **geographic anchor** layer — it provides location identity and basic administrative context, but all substantive scoring dimensions require external data joined via geocode or spatial overlay.

### Recommended Priority External Data Sources

| Priority | Data Source | Dimensions Served |
|----------|-------------|-------------------|
| 1 | Shelby County Assessor building/improvement data | Energy, Durability, Bonus Features |
| 2 | FEMA National Flood Hazard Layer (NFHL) | Disaster Resilience, Climate Projections |
| 3 | First Street Foundation (Flood/Heat/Wind Factor) | Disaster Resilience, Climate Projections |
| 4 | Walk Score / GTFS transit data | Walkability / Transport Cost |
| 5 | EPA EJSCREEN | Health Impact, Environmental Footprint |
| 6 | NLCD Land Cover / Tree Canopy | Environmental Footprint |
| 7 | ACS Census data (tract-level) | Health Impact, Infrastructure Burden |
| 8 | NOAA / NASA climate projections | Climate Projections, Energy |
| 9 | School ratings (GreatSchools API) | Bonus Features |
| 10 | FCC Broadband Map | Bonus Features |

---

*End of Report*
