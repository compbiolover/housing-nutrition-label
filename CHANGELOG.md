# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While
pre-1.0 (`0.y.z`), breaking changes bump the **minor** version and everything else the
**patch**. From here on, releases are maintained automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional Commit
PR titles — edit entries by editing the open release PR, not this file directly.

## [0.1.0] - 2026-06-26

Initial baseline.

### Added
- Multi-dimensional housing "nutrition label" scoring across nine dimensions
  (resilience, energy efficiency, durability, environmental footprint, infrastructure
  burden, health, socioeconomic, walkability, and climate).
- **Climate Projections** with genuinely sub-county resolution from the USGS
  CMIP6-LOCA2 ensemble mean (~6 km), sampled at each census tract's internal point
  (county = the mean of its tracts), with a tract → county → national fallback.
- Reproducible, keyless data builds under `scripts/` (climate, eGRID, seismic) and a
  static label UI at [housinglabel.dev](https://housinglabel.dev).

[0.1.0]: https://github.com/compbiolover/housing-nutrition-label/releases/tag/v0.1.0
