"""Bundled reference datasets for national generalization.

Small, keyless, offline lookup tables keyed on county FIPS so the label can be
generated for any US location without per-call external data dependencies:

  • climate.py  — county → IECC climate zone (DOE/PNNL table)
  • egrid.py    — county → eGRID2023 Rev 2 subregion grid CO2 factor (with a
                  national-average fallback for unmapped counties)
  • climate_projections.py — county → downscaled climate-hazard projection
                  sub-score (CMRA/NCA4, RCP4.5–8.5 mid-century; national-average
                  fallback for unmapped counties)
"""
