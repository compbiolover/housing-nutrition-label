import pandas as pd
import numpy as np

# ── Load ──────────────────────────────────────────────────────────────────────
df = pd.read_csv("shelby_parcels_sample.csv", dtype=str, low_memory=False)
rows_before, cols_before = df.shape
print(f"Loaded: {rows_before} rows × {cols_before} cols")

# ── Task 1: Data cleanup ───────────────────────────────────────────────────────

# 1. Drop mostly-empty columns (>80% null as specified)
drop_empty = [
    "PARCELID2", "created_user", "created_date",
    "OWN2", "ADRDIR", "ADRSUF2", "UNITNO", "UNITDESC",
    "ADDR2", "ADDR3",
]
drop_empty = [c for c in drop_empty if c in df.columns]
df.drop(columns=drop_empty, inplace=True)
print(f"\nDropped mostly-empty columns ({len(drop_empty)}): {drop_empty}")

# 2. Drop zero-information columns (constant value)
drop_const = ["PARCEL_TYPE"]
drop_const = [c for c in drop_const if c in df.columns]
df.drop(columns=drop_const, inplace=True)
print(f"Dropped constant columns ({len(drop_const)}): {drop_const}")

# 3. Fix ZIP codes: float string → zero-padded 5-digit string
def fix_zip(series):
    def _fix(val):
        if pd.isna(val) or str(val).strip() in ("", "nan"):
            return np.nan
        try:
            return str(int(float(val))).zfill(5)
        except (ValueError, OverflowError):
            return val
    return series.apply(_fix)

zip_before_zip1 = df["ZIP1"].head(3).tolist()
zip_before_zip2 = df["ZIP2"].head(3).tolist()
df["ZIP1"] = fix_zip(df["ZIP1"])
df["ZIP2"] = fix_zip(df["ZIP2"])
print(f"\nFixed ZIP1 (sample before → after):")
for b, a in zip(zip_before_zip1, df["ZIP1"].head(3).tolist()):
    print(f"  {repr(b)} → {repr(a)}")
print(f"Fixed ZIP2 (sample before → after):")
for b, a in zip(zip_before_zip2, df["ZIP2"].head(3).tolist()):
    print(f"  {repr(b)} → {repr(a)}")

# 4. Strip whitespace from PARCELID
sample_before = df["PARCELID"].head(3).tolist()
df["PARCELID"] = df["PARCELID"].str.strip()
sample_after = df["PARCELID"].head(3).tolist()
print(f"\nStripped PARCELID whitespace (sample before → after):")
for b, a in zip(sample_before, sample_after):
    print(f"  {repr(b)} → {repr(a)}")

# 5. Replace "." placeholder in NOTE1 and NOTE2 with NaN
for col in ["NOTE1", "NOTE2"]:
    if col in df.columns:
        mask = df[col].str.strip() == "."
        n_replaced = mask.sum()
        df.loc[mask, col] = np.nan
        print(f"\nReplaced {n_replaced} '.' placeholders in {col} with NaN")

# 6. Flag acreage outliers
df["CALC_ACRE"] = pd.to_numeric(df["CALC_ACRE"], errors="coerce")
df["acre_outlier"] = df["CALC_ACRE"] > 1000
n_outliers = df["acre_outlier"].sum()
print(f"\nFlagged {n_outliers} acre outlier(s) (CALC_ACRE > 1000)")
if n_outliers > 0:
    print(df[df["acre_outlier"]][["PARCELID", "CALC_ACRE"]].to_string(index=False))

# ── Save ──────────────────────────────────────────────────────────────────────
df.to_csv("shelby_parcels_clean.csv", index=False)
rows_after, cols_after = df.shape
print(f"\n{'─'*60}")
print(f"SUMMARY")
print(f"  Rows:    {rows_before} → {rows_after}  (Δ {rows_after - rows_before})")
print(f"  Columns: {cols_before} → {cols_after}  (Δ {cols_after - cols_before})")
print(f"  Saved:   shelby_parcels_clean.csv")
print(f"{'─'*60}")

# ── Task 2: Property address investigation ─────────────────────────────────────
print(f"\n{'═'*60}")
print("TASK 2: PROPERTY ADDRESS INVESTIGATION")
print(f"{'═'*60}")

addr_cols = ["ADRNO", "ADRSTR", "ADRSUF", "CITY", "ZIP2"]
owner_cols = ["CITYNAME", "STATECODE", "ZIP1", "ADDR1"]
show_cols = addr_cols + owner_cols

# Show 10–20 sample rows with both sets
print("\n--- Sample rows: property address fields vs owner mailing fields ---")
sample = df[show_cols].dropna(subset=["ADRNO", "ADRSTR"]).head(15)
with pd.option_context("display.max_colwidth", 30, "display.width", 200):
    print(sample.to_string(index=False))

# CITY vs CITYNAME, ZIP2 vs ZIP1 comparison
print("\n--- CITY (property) vs CITYNAME (owner mailing) ---")
city_match = (df["CITY"].str.upper().str.strip() == df["CITYNAME"].str.upper().str.strip())
print(f"  CITY == CITYNAME:  {city_match.sum()} / {city_match.notna().sum()} rows ({100*city_match.mean():.1f}%)")
print(f"  CITY unique values ({df['CITY'].nunique()}): {sorted(df['CITY'].dropna().unique())[:15]}")
print(f"  CITYNAME unique values ({df['CITYNAME'].nunique()}): {sorted(df['CITYNAME'].dropna().unique())[:15]}")

print("\n--- ZIP2 (property) vs ZIP1 (owner mailing) ---")
zip_match = df["ZIP2"] == df["ZIP1"]
print(f"  ZIP2 == ZIP1:  {zip_match.sum()} / {len(df)} rows ({100*zip_match.mean():.1f}%)")
print(f"  ZIP2 unique values: {sorted(df['ZIP2'].dropna().unique())[:10]}")
print(f"  ZIP1 unique values: {sorted(df['ZIP1'].dropna().unique())[:10]}")

# Completeness: what % have a full property address
has_adrno  = df["ADRNO"].notna() & (df["ADRNO"].str.strip() != "")
has_adrstr = df["ADRSTR"].notna() & (df["ADRSTR"].str.strip() != "")
has_city_or_zip = (
    (df["CITY"].notna() & (df["CITY"].str.strip() != "")) |
    (df["ZIP2"].notna() & (df["ZIP2"].str.strip() != ""))
)
complete = has_adrno & has_adrstr & has_city_or_zip
pct = 100 * complete.mean()
print(f"\n--- Address completeness ---")
print(f"  Has ADRNO:          {has_adrno.sum()} ({100*has_adrno.mean():.1f}%)")
print(f"  Has ADRSTR:         {has_adrstr.sum()} ({100*has_adrstr.mean():.1f}%)")
print(f"  Has CITY or ZIP2:   {has_city_or_zip.sum()} ({100*has_city_or_zip.mean():.1f}%)")
print(f"  Complete address:   {complete.sum()} ({pct:.1f}%)")

# Construct geocodable address strings
print("\n--- 5 example constructed addresses ---")
state = "TN"  # Shelby County is always TN

def build_address(row):
    parts = []
    adrno = str(row["ADRNO"]).strip().rstrip(".0") if pd.notna(row["ADRNO"]) else ""
    # Convert float-like "2845.0" → "2845"
    try:
        adrno = str(int(float(adrno))) if adrno else ""
    except (ValueError, TypeError):
        pass
    adrstr = str(row["ADRSTR"]).strip() if pd.notna(row["ADRSTR"]) else ""
    adrsuf = str(row["ADRSUF"]).strip() if pd.notna(row["ADRSUF"]) else ""
    city   = str(row["CITY"]).strip() if pd.notna(row["CITY"]) else ""
    zip2   = str(row["ZIP2"]).strip() if pd.notna(row["ZIP2"]) else ""

    street = " ".join(p for p in [adrno, adrstr, adrsuf] if p)
    locality = f"{city}, {state} {zip2}".strip(", ")
    if street and locality:
        return f"{street}, {locality}"
    return None

sample_complete = df[complete].head(10).copy()
examples = []
for _, row in sample_complete.iterrows():
    addr = build_address(row)
    if addr:
        examples.append(addr)
    if len(examples) == 5:
        break

for i, addr in enumerate(examples, 1):
    print(f"  {i}. {addr}")

print(f"\n{'═'*60}")
print("CONCLUSION")
print("  - CITY / ZIP2 are the *property location* fields (where the parcel is).")
print("  - CITYNAME / ZIP1 are the *owner mailing* fields (where the tax bill goes).")
print(f"  - {pct:.1f}% of records have a complete geocodable property address.")
print("  - A full address string can be built as:")
print('    "{ADRNO} {ADRSTR} {ADRSUF}, {CITY}, TN {ZIP2}"')
print(f"{'═'*60}")
