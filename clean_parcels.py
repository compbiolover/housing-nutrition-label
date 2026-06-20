"""Clean raw Shelby County parcels data to a production-ready CSV.

Input:  shelby_parcels_sample.csv  (raw parcels export)
Output: shelby_parcels_clean.csv   (cleaned parcels)

Cleaning operations (Task 1):
  1. Drop mostly-empty columns (>80% null).
  2. Drop zero-information (constant-value) columns.
  3. Fix ZIP codes: float-string -> zero-padded 5-digit string (ZIP1, ZIP2).
  4. Strip whitespace from PARCELID.
  5. Replace "." placeholders in NOTE1 / NOTE2 with NaN.
  6. Flag acreage outliers (CALC_ACRE > 1000) in a new `acre_outlier` column.

This script intentionally PRESERVES all CAMA columns (YRBLT, EFFYR, STORIES,
EXTWALL, BSMT, SFLA, GRADE, COND, CDU, STYLE, RMBED, FIXBATH, HEAT, FUEL,
RTOTAPR, APRLAND, APRBLDG) because downstream energy/infra/health steps depend
on them.

It also runs Task 2: a property-address investigation report comparing the
property-location fields (CITY/ZIP2) against the owner-mailing fields
(CITYNAME/ZIP1) and demonstrating geocodable address construction.
"""

import argparse
import logging
import pathlib
import sys

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

# ── Cleaning configuration ──────────────────────────────────────────────────────
# Mostly-empty columns (>80% null as specified).
DROP_EMPTY = [
    "PARCELID2", "created_user", "created_date",
    "OWN2", "ADRDIR", "ADRSUF2", "UNITNO", "UNITDESC",
    "ADDR2", "ADDR3",
]
# Zero-information columns (constant value).
DROP_CONST = ["PARCEL_TYPE"]
# Shelby County is always TN.
STATE = "TN"


# ── Helpers ─────────────────────────────────────────────────────────────────────
def fix_zip(series: pd.Series) -> pd.Series:
    """Convert float-string ZIP values to zero-padded 5-digit strings."""
    def _fix(val: object) -> object:
        if pd.isna(val) or str(val).strip() in ("", "nan"):
            return np.nan
        try:
            return str(int(float(val))).zfill(5)
        except (ValueError, OverflowError):
            return val
    return series.apply(_fix)


def build_address(row: pd.Series) -> str | None:
    """Build a geocodable property-address string from a parcel row."""
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
    locality = f"{city}, {STATE} {zip2}".strip(", ")
    if street and locality:
        return f"{street}, {locality}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw Shelby County parcels data.")
    parser.add_argument("--input", default="shelby_parcels_sample.csv",
                        help="Input CSV path (default: shelby_parcels_sample.csv)")
    parser.add_argument("--output", default="shelby_parcels_clean.csv",
                        help="Output CSV path (default: shelby_parcels_clean.csv)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run cleaning in memory without writing the output file.")
    args = parser.parse_args()

    input_path = pathlib.Path(args.input)
    if not input_path.is_absolute():
        input_path = SCRIPT_DIR / input_path
    output_path = pathlib.Path(args.output)
    if not output_path.is_absolute():
        output_path = SCRIPT_DIR / output_path

    # ── Input validation ─────────────────────────────────────────────────────────
    if not input_path.exists():
        log.error("Input file does not exist: %s", input_path)
        sys.exit(1)

    # ── Load ─────────────────────────────────────────────────────────────────────
    df = pd.read_csv(input_path, dtype=str, low_memory=False)
    rows_before, cols_before = df.shape
    log.info("Loaded: %d rows × %d cols", rows_before, cols_before)

    if "PARCELID" not in df.columns:
        log.error("Required column missing: PARCELID")
        sys.exit(1)

    # ── Task 1: Data cleanup ─────────────────────────────────────────────────────

    # 1. Drop mostly-empty columns (>80% null as specified)
    drop_empty = [c for c in DROP_EMPTY if c in df.columns]
    df.drop(columns=drop_empty, inplace=True)
    log.info("Dropped mostly-empty columns (%d): %s", len(drop_empty), drop_empty)

    # 2. Drop zero-information columns (constant value)
    drop_const = [c for c in DROP_CONST if c in df.columns]
    df.drop(columns=drop_const, inplace=True)
    log.info("Dropped constant columns (%d): %s", len(drop_const), drop_const)

    # 3. Fix ZIP codes: float string → zero-padded 5-digit string
    for col in ["ZIP1", "ZIP2"]:
        if col in df.columns:
            zip_before = df[col].head(3).tolist()
            df[col] = fix_zip(df[col])
            log.info("Fixed %s (sample before → after):", col)
            for b, a in zip(zip_before, df[col].head(3).tolist()):
                log.info("  %r → %r", b, a)

    # 4. Strip whitespace from PARCELID
    sample_before = df["PARCELID"].head(3).tolist()
    df["PARCELID"] = df["PARCELID"].str.strip()
    sample_after = df["PARCELID"].head(3).tolist()
    log.info("Stripped PARCELID whitespace (sample before → after):")
    for b, a in zip(sample_before, sample_after):
        log.info("  %r → %r", b, a)

    # 5. Replace "." placeholder in NOTE1 and NOTE2 with NaN
    for col in ["NOTE1", "NOTE2"]:
        if col in df.columns:
            mask = df[col].str.strip() == "."
            n_replaced = mask.sum()
            df.loc[mask, col] = np.nan
            log.info("Replaced %d '.' placeholders in %s with NaN", n_replaced, col)

    # 6. Flag acreage outliers
    if "CALC_ACRE" in df.columns:
        df["CALC_ACRE"] = pd.to_numeric(df["CALC_ACRE"], errors="coerce")
        df["acre_outlier"] = df["CALC_ACRE"] > 1000
        n_outliers = df["acre_outlier"].sum()
        log.info("Flagged %d acre outlier(s) (CALC_ACRE > 1000)", n_outliers)
        if n_outliers > 0:
            log.info("\n%s", df[df["acre_outlier"]][["PARCELID", "CALC_ACRE"]].to_string(index=False))

    # ── Save ─────────────────────────────────────────────────────────────────────
    rows_after, cols_after = df.shape
    if args.dry_run:
        log.info("[dry-run] Would write %d rows × %d cols to %s", rows_after, cols_after, output_path)
    else:
        df.to_csv(output_path, index=False)
        log.info("wrote %d rows × %d cols to %s", rows_after, cols_after, output_path)
        if rows_after != rows_before:
            log.warning("Output row count (%d) != input row count (%d)", rows_after, rows_before)

    print(f"\n{'─'*60}")
    print(f"SUMMARY")
    print(f"  Rows:    {rows_before} → {rows_after}  (Δ {rows_after - rows_before})")
    print(f"  Columns: {cols_before} → {cols_after}  (Δ {cols_after - cols_before})")
    print(f"  Saved:   {output_path}" + ("  (dry-run, not written)" if args.dry_run else ""))
    print(f"{'─'*60}")

    # ── Task 2: Property address investigation ───────────────────────────────────
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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception:
        log.error("Unhandled error", exc_info=True)
        sys.exit(1)
