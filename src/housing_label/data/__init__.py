"""Bundled reference datasets for national generalization.

Small, keyless, offline lookup tables keyed on county FIPS so the label can be
generated for any US location without per-call external data dependencies:

  • climate.py  — county → IECC climate zone (DOE/PNNL table)
  • egrid.py    — grid CO2 emission factor (national-average v1; subregion later)
"""
