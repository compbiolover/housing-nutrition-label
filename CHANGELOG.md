# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While
pre-1.0 (`0.y.z`), breaking changes bump the **minor** version and everything else the
**patch**. From here on, releases are maintained automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional Commit
PR titles — edit entries by editing the open release PR, not this file directly.

## [0.1.32](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.31...v0.1.32) (2026-07-10)


### Bug Fixes

* score a detected multi-unit building per dwelling unit ([#117](https://github.com/compbiolover/housing-nutrition-label/issues/117)) ([c2c9d9e](https://github.com/compbiolover/housing-nutrition-label/commit/c2c9d9ef50c761dd95a48bfc72b23c5dfb13e9b1))

## [0.1.31](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.30...v0.1.31) (2026-07-10)


### Bug Fixes

* detect downtown high-rises correctly in address auto-fill ([#115](https://github.com/compbiolover/housing-nutrition-label/issues/115)) ([8e8c39f](https://github.com/compbiolover/housing-nutrition-label/commit/8e8c39fd9d7aaa74698bd4307c9efeae0156e519))

## [0.1.30](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.29...v0.1.30) (2026-07-09)


### Features

* address auto-fill + per-dimension national percentiles ([#113](https://github.com/compbiolover/housing-nutrition-label/issues/113)) ([ad885f7](https://github.com/compbiolover/housing-nutrition-label/commit/ad885f75e56ea5f58f321c7935f01eb8ee0ba7b5))
* de-Shelbyfy the batch pipeline + bring auto-fill/percentiles to the Label page ([#114](https://github.com/compbiolover/housing-nutrition-label/issues/114)) ([89f6f9f](https://github.com/compbiolover/housing-nutrition-label/commit/89f6f9fe5d93d196b3b5a9c18de2c307b68729b0))
* score health, socioeconomic & walkability against national distributions ([#111](https://github.com/compbiolover/housing-nutrition-label/issues/111)) ([d25e8f9](https://github.com/compbiolover/housing-nutrition-label/commit/d25e8f9221220d77b4e9dd3e1a3bcf4b7572a8d7))

## [0.1.29](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.28...v0.1.29) (2026-07-08)


### Performance Improvements

* implement the streamlining &amp; performance audit ([#109](https://github.com/compbiolover/housing-nutrition-label/issues/109)) ([c44a7f5](https://github.com/compbiolover/housing-nutrition-label/commit/c44a7f548d8c0448d3cb4e9e905d3a70c8a0c50c))

## [0.1.28](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.27...v0.1.28) (2026-07-07)


### Features

* foundations & hardening — CI test gate, golden regression, dimension coverage, API cache + rate limiting ([#105](https://github.com/compbiolover/housing-nutrition-label/issues/105)) ([e7d55e6](https://github.com/compbiolover/housing-nutrition-label/commit/e7d55e6f983a28949e287378aad65c2809d801f9))

## [0.1.27](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.26...v0.1.27) (2026-07-07)


### Features

* **label:** shareable location URLs, "use my location", and remembered address ([#102](https://github.com/compbiolover/housing-nutrition-label/issues/102)) ([a305ca5](https://github.com/compbiolover/housing-nutrition-label/commit/a305ca5c16b3947a91e56d112412229547ec138a))

## [0.1.26](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.25...v0.1.26) (2026-07-06)


### Bug Fixes

* expandable label rows now open on tap on iOS Safari ([#98](https://github.com/compbiolover/housing-nutrition-label/issues/98)) ([ea3c3f7](https://github.com/compbiolover/housing-nutrition-label/commit/ea3c3f7f9a8575558641d01302fee72184efb65a))

## [0.1.25](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.24...v0.1.25) (2026-07-06)


### Features

* tap/click any label row to reveal what it measures and the numbers behind it ([#96](https://github.com/compbiolover/housing-nutrition-label/issues/96)) ([ac6e4bb](https://github.com/compbiolover/housing-nutrition-label/commit/ac6e4bbc11c7ebe5102d9fa5f7aa1486ca2fe51f))

## [0.1.24](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.23...v0.1.24) (2026-07-06)


### Features

* auto-detect NSI-mislabeled apartment complexes from the address ([#93](https://github.com/compbiolover/housing-nutrition-label/issues/93)) ([62107f5](https://github.com/compbiolover/housing-nutrition-label/commit/62107f511174ee5a8ac294887941036d4e52b00e))

## [0.1.23](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.22...v0.1.23) (2026-07-05)


### Performance Improvements

* load only the two SPC columns the tornado rate needs (~27 MB saved) ([#91](https://github.com/compbiolover/housing-nutrition-label/issues/91)) ([23299ff](https://github.com/compbiolover/housing-nutrition-label/commit/23299ffb05952a27623bd591c3d60c0912719f12))

## [0.1.22](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.21...v0.1.22) (2026-07-05)


### Features

* web-form building-material + stories inputs for multi-unit buildings ([#88](https://github.com/compbiolover/housing-nutrition-label/issues/88)) ([f44833a](https://github.com/compbiolover/housing-nutrition-label/commit/f44833a9d96d67d35ee77108166eea7dbd41cd59))


### Performance Improvements

* curb Render memory growth (glibc trim + memoized tornado scan) ([#89](https://github.com/compbiolover/housing-nutrition-label/issues/89)) ([2899d53](https://github.com/compbiolover/housing-nutrition-label/commit/2899d53050f2a06ade9854076480307f813b94dd))

## [0.1.21](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.20...v0.1.21) (2026-07-05)


### Features

* trust a caller-entered structure when NSI misses multi-family ([#86](https://github.com/compbiolover/housing-nutrition-label/issues/86)) ([25d9c16](https://github.com/compbiolover/housing-nutrition-label/commit/25d9c163c07b7af9b2e585dbb7b5e23f003dc1f6))

## [0.1.20](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.19...v0.1.20) (2026-07-04)


### Features

* value dense housing by value-per-door income estimate — Phase 3b ([#84](https://github.com/compbiolover/housing-nutrition-label/issues/84)) ([ba19ff5](https://github.com/compbiolover/housing-nutrition-label/commit/ba19ff59ccdba2cb2e338d98b46c106c586bbabe))
* value-per-door data + lookup for dense housing — Phase 3a ([#82](https://github.com/compbiolover/housing-nutrition-label/issues/82)) ([6252dc0](https://github.com/compbiolover/housing-nutrition-label/commit/6252dc0b33393e34d998b056050f20fbf894de78))


### Bug Fixes

* put the dollar EAL on the per-unit value — dense-housing Phase 3c ([#85](https://github.com/compbiolover/housing-nutrition-label/issues/85)) ([590a037](https://github.com/compbiolover/housing-nutrition-label/commit/590a037719ba342d5ebfc95b2410045766b2d8c6))

## [0.1.19](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.18...v0.1.19) (2026-07-04)


### Bug Fixes

* stop double-dividing the auto-filled home value across units ([#80](https://github.com/compbiolover/housing-nutrition-label/issues/80)) ([aee850d](https://github.com/compbiolover/housing-nutrition-label/commit/aee850db4ee9071bd4be7fc3486469055f714ce1))

## [0.1.18](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.17...v0.1.18) (2026-07-04)


### Features

* multifamily environmental water — dense-housing Phase 2 (complete) ([#79](https://github.com/compbiolover/housing-nutrition-label/issues/79)) ([edd9771](https://github.com/compbiolover/housing-nutrition-label/commit/edd9771d81ae97bffbb7229b7266f1a6ec7914d0))
* multifamily infrastructure density — dense-housing Phase 2 ([#77](https://github.com/compbiolover/housing-nutrition-label/issues/77)) ([9e11177](https://github.com/compbiolover/housing-nutrition-label/commit/9e1117787226b661cb49b9338d6860d05e557779))

## [0.1.17](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.16...v0.1.17) (2026-07-04)


### Features

* detect building type + unit count from an address (dense-housing Phase 1) ([#73](https://github.com/compbiolover/housing-nutrition-label/issues/73)) ([024b9fb](https://github.com/compbiolover/housing-nutrition-label/commit/024b9fb7e994ea67b7b34e74f8537abbad0cba3c))
* multifamily durability (shared structural shell) — dense-housing Phase 2 ([#76](https://github.com/compbiolover/housing-nutrition-label/issues/76)) ([2da5081](https://github.com/compbiolover/housing-nutrition-label/commit/2da50814908a481a785ebca50fe6f15e15d9ea0e))
* multifamily resilience (material + floor-aware flood) — dense-housing Phase 2 ([#75](https://github.com/compbiolover/housing-nutrition-label/issues/75)) ([7c7a6a5](https://github.com/compbiolover/housing-nutrition-label/commit/7c7a6a5caba3b2d66d1005aef192ca68cf97f9d5))
* shared-wall energy credit for multi-unit homes (dense-housing Phase 2) ([#74](https://github.com/compbiolover/housing-nutrition-label/issues/74)) ([d82f267](https://github.com/compbiolover/housing-nutrition-label/commit/d82f267b5089aed69319a21d1f3eeb08ee8f623c))


### Bug Fixes

* flag multi-unit homes as approximate + dense-housing research (Phase 0) ([#71](https://github.com/compbiolover/housing-nutrition-label/issues/71)) ([e880983](https://github.com/compbiolover/housing-nutrition-label/commit/e8809837f67c996df7af041d67a9210f3173279a))

## [0.1.16](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.15...v0.1.16) (2026-07-03)


### Features

* generalize scoring beyond the Memphis pilot + plain-language pages ([#69](https://github.com/compbiolover/housing-nutrition-label/issues/69)) ([445b875](https://github.com/compbiolover/housing-nutrition-label/commit/445b87529aef24b6a82a343977fe0520b6d40db4))

## [0.1.15](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.14...v0.1.15) (2026-07-03)


### Code Refactoring

* share address autocomplete across all three label pages ([#64](https://github.com/compbiolover/housing-nutrition-label/issues/64)) ([ce6eb6c](https://github.com/compbiolover/housing-nutrition-label/commit/ce6eb6c5fff83d6ace417511b7d67acb9aaa25cb))

## [0.1.14](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.13...v0.1.14) (2026-07-02)


### Features

* address input on the Label page + live Examples comparison ([#62](https://github.com/compbiolover/housing-nutrition-label/issues/62)) ([13a20a4](https://github.com/compbiolover/housing-nutrition-label/commit/13a20a42d4eb906f250c3c89c44b2e0c1cf68c17))

## [0.1.13](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.12...v0.1.13) (2026-07-02)


### Features

* confidence + cost strip on the live label (home page & examples) ([#59](https://github.com/compbiolover/housing-nutrition-label/issues/59)) ([e7a38cb](https://github.com/compbiolover/housing-nutrition-label/commit/e7a38cb88fda35d5ea0b387f9b31aff54441da03))

## [0.1.12](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.11...v0.1.12) (2026-07-02)


### Features

* per-dimension confidence + composite confidence display (with research write-up) ([#57](https://github.com/compbiolover/housing-nutrition-label/issues/57)) ([d07b112](https://github.com/compbiolover/housing-nutrition-label/commit/d07b1122cdfc99c69372f4da9f4bf7a245c82584))

## [0.1.11](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.10...v0.1.11) (2026-07-02)


### Features

* "cost over a mortgage" strip + comparison mode (with research write-up) ([#55](https://github.com/compbiolover/housing-nutrition-label/issues/55)) ([9289034](https://github.com/compbiolover/housing-nutrition-label/commit/92890343b820a79b36432b3eb5ae3d376cb531f2))

## [0.1.10](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.9...v0.1.10) (2026-07-01)


### Features

* **climate:** add Argonne ClimRR Fire Weather Index fire leg ([#53](https://github.com/compbiolover/housing-nutrition-label/issues/53)) ([2737387](https://github.com/compbiolover/housing-nutrition-label/commit/2737387910da09ed6ce071b5b27d248dd1fc0fc7))

## [0.1.9](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.8...v0.1.9) (2026-06-28)


### Features

* credit small-scale infill — density-responsive cost curve + per-acre productivity lens ([#51](https://github.com/compbiolover/housing-nutrition-label/issues/51)) ([b3cb5d1](https://github.com/compbiolover/housing-nutrition-label/commit/b3cb5d154e86ffd2fd82d76e84125d3316c1b39e))

## [0.1.8](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.7...v0.1.8) (2026-06-28)


### Features

* auto-fill home value + reconcile school scope in Infrastructure Burden ([#49](https://github.com/compbiolover/housing-nutrition-label/issues/49)) ([38caf8b](https://github.com/compbiolover/housing-nutrition-label/commit/38caf8bb444cf1b3c1b06dcd61b0455095c44174))
* per-parcel density comparison (duplex/triplex/quadplex on the same lot) ([#50](https://github.com/compbiolover/housing-nutrition-label/issues/50)) ([6f0326f](https://github.com/compbiolover/housing-nutrition-label/commit/6f0326fb84574ae20c85839a1695e88992b3e5e4))
* re-anchor Infrastructure Burden score breakpoints to a national distribution ([#47](https://github.com/compbiolover/housing-nutrition-label/issues/47)) ([4e47d40](https://github.com/compbiolover/housing-nutrition-label/commit/4e47d408b44e2ea434ba437faa5cc7a81f1e6894))

## [0.1.7](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.6...v0.1.7) (2026-06-27)


### Features

* localize Infrastructure Burden revenue side (per-county property-tax rate) ([#45](https://github.com/compbiolover/housing-nutrition-label/issues/45)) ([5ab8919](https://github.com/compbiolover/housing-nutrition-label/commit/5ab89196215431b59956a9052ce45824c10fb1ea))

## [0.1.6](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.5...v0.1.6) (2026-06-27)


### Bug Fixes

* home-screen result caveat unreadable in light mode ([#43](https://github.com/compbiolover/housing-nutrition-label/issues/43)) ([ffddc32](https://github.com/compbiolover/housing-nutrition-label/commit/ffddc320dd276eef32ddac8ac7104d0eaf753d63))

## [0.1.5](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.4...v0.1.5) (2026-06-27)


### Bug Fixes

* home-screen search text invisible in light mode ([#41](https://github.com/compbiolover/housing-nutrition-label/issues/41)) ([a1a3627](https://github.com/compbiolover/housing-nutrition-label/commit/a1a36277d12c4c5f8390a8f5c6b2663d50539b42))

## [0.1.4](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.3...v0.1.4) (2026-06-27)


### Features

* locally calibrate Infrastructure Burden to county government finances ([#39](https://github.com/compbiolover/housing-nutrition-label/issues/39)) ([7c47898](https://github.com/compbiolover/housing-nutrition-label/commit/7c47898636fc222b87a9c9e91ac1121fc8d1124a))

## [0.1.3](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.2...v0.1.3) (2026-06-27)


### Features

* add location-based fire (wildfire) hazard to disaster resilience ([#37](https://github.com/compbiolover/housing-nutrition-label/issues/37)) ([459dbf2](https://github.com/compbiolover/housing-nutrition-label/commit/459dbf23103dfc320796673ba471bcf865efe827))

## [0.1.2](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.1...v0.1.2) (2026-06-27)


### Features

* make home-screen search match the examples page ([#35](https://github.com/compbiolover/housing-nutrition-label/issues/35)) ([8ad6719](https://github.com/compbiolover/housing-nutrition-label/commit/8ad6719f2dc5d02b9b6d49777f2bb470cf759d3e))

## [0.1.1](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.0...v0.1.1) (2026-06-26)


### Documentation

* complete methodology + label for all 9 dimensions ([#33](https://github.com/compbiolover/housing-nutrition-label/issues/33)) ([69bcf9c](https://github.com/compbiolover/housing-nutrition-label/commit/69bcf9c6fdf7082f83531088c4deb98062de27cf))
* refresh homepage (9 dimensions, address search, CMIP6-LOCA2) ([#32](https://github.com/compbiolover/housing-nutrition-label/issues/32)) ([bdf106e](https://github.com/compbiolover/housing-nutrition-label/commit/bdf106e4c50cb30d9c1fbbdcb0dd3976177941ef))

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
