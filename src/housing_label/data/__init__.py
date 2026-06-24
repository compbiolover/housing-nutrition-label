"""Bundled reference datasets for national generalization.

Small, keyless, offline lookup tables keyed on county FIPS so the label can be
generated for any US location without per-call external data dependencies:

  • climate.py  — county → IECC climate zone (DOE/PNNL table)
  • egrid.py    — county → eGRID2022 subregion grid CO2 factor (with a
                  national-average fallback for unmapped counties)
"""
