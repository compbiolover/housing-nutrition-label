"""Bundled reference datasets for national generalization.

Small, keyless, offline lookup tables keyed on county FIPS so the label can be
generated for any US location without per-call external data dependencies:

  • climate.py  — county → IECC climate zone (DOE/PNNL table)
  • egrid.py    — county → eGRID2023 Rev 2 subregion grid CO2e factor, the grid
                  AVERAGE (with a national-average fallback for unmapped counties)
  • cambium.py  — county → NREL Cambium 2023 LRMER long-run MARGINAL grid CO2e
                  factor, used to credit solar/efficiency-avoided kWh (CONUS-only;
                  returns None elsewhere so the model falls back to the average)
  • climate_projections.py — county → downscaled climate-hazard projection
                  sub-score (CMRA/NCA4, RCP4.5–8.5 mid-century; national-average
                  fallback for unmapped counties)
  • resstock_eui.py — building type × climate zone × vintage → base residential
                  site-EUI benchmark, plus ResStock-derived foundation/HVAC
                  within-cell factors (NREL ResStock 2024 medians; drives Energy)
"""
