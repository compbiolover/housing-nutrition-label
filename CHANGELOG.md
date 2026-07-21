# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While
pre-1.0 (`0.y.z`), breaking changes bump the **minor** version and everything else the
**patch**. From here on, releases are maintained automatically by
[release-please](https://github.com/googleapis/release-please) from Conventional Commit
PR titles — edit entries by editing the open release PR, not this file directly.

## [0.1.59](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.58...v0.1.59) (2026-07-21)


### Features

* **api:** make Google Places key failures diagnosable (debug probe + logging) ([#191](https://github.com/compbiolover/housing-nutrition-label/issues/191)) ([cb382d7](https://github.com/compbiolover/housing-nutrition-label/commit/cb382d74116d341d999383c6fb3b5cd7b7978669))

## [0.1.58](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.57...v0.1.58) (2026-07-21)


### Bug Fixes

* residential-only screen (reject stadiums/offices) + Google Places typeahead ([#189](https://github.com/compbiolover/housing-nutrition-label/issues/189)) ([e9b6a78](https://github.com/compbiolover/housing-nutrition-label/commit/e9b6a78e118ee88c0172fdc7fa1e8666ecdde857))

## [0.1.57](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.56...v0.1.57) (2026-07-21)


### Features

* **web:** methodology page — back-to-top button, compact & icon-anchored cards ([#188](https://github.com/compbiolover/housing-nutrition-label/issues/188)) ([fe59488](https://github.com/compbiolover/housing-nutrition-label/commit/fe59488aeba76fa6314c155a0c3ced7dfbadb8b5))
* **web:** wait for input, clearer view modes, and place-name search ([#186](https://github.com/compbiolover/housing-nutrition-label/issues/186)) ([742271b](https://github.com/compbiolover/housing-nutrition-label/commit/742271b9097156894a81a3c4fc44d74b2af7e046))

## [0.1.56](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.55...v0.1.56) (2026-07-20)


### Features

* **water:** score the zero-inflated exposure with a hurdle model ([#184](https://github.com/compbiolover/housing-nutrition-label/issues/184)) ([ea21b10](https://github.com/compbiolover/housing-nutrition-label/commit/ea21b1062fc5a73c79250f7b77030446ba02e67d))

## [0.1.55](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.54...v0.1.55) (2026-07-20)


### Bug Fixes

* keep the non-residential notice UI-agnostic (drop CLI/override text) ([#182](https://github.com/compbiolover/housing-nutrition-label/issues/182)) ([3e28fbc](https://github.com/compbiolover/housing-nutrition-label/commit/3e28fbcdb9315bebfb39fce4f4f6048cacfd56e4))

## [0.1.54](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.53...v0.1.54) (2026-07-20)


### Features

* screen out non-residential addresses + self-syncing README roadmap ([#180](https://github.com/compbiolover/housing-nutrition-label/issues/180)) ([bf30fd4](https://github.com/compbiolover/housing-nutrition-label/commit/bf30fd4e194bbc45bbbcac1672ef019958600633))

## [0.1.53](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.52...v0.1.53) (2026-07-19)


### Bug Fixes

* **docs:** contain wide tables so pages don't overflow past the sticky nav ([#178](https://github.com/compbiolover/housing-nutrition-label/issues/178)) ([2fc6474](https://github.com/compbiolover/housing-nutrition-label/commit/2fc64749f23fa667cf79121b2d4ff9e0e18c5b65))

## [0.1.52](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.51...v0.1.52) (2026-07-19)


### Bug Fixes

* **docs:** keep grade badge inline with score in comparison tables ([#176](https://github.com/compbiolover/housing-nutrition-label/issues/176)) ([09e3247](https://github.com/compbiolover/housing-nutrition-label/commit/09e32471c5ce37ca8f4cd29332d69671ad14d489))

## [0.1.51](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.50...v0.1.51) (2026-07-18)


### Features

* add Noise dimension (transportation-noise exposure, tract-level) ([#173](https://github.com/compbiolover/housing-nutrition-label/issues/173)) ([30d0824](https://github.com/compbiolover/housing-nutrition-label/commit/30d0824116c1fdb4355e9099c6730ae32acf4d73))
* add Water Quality dimension (EPA SDWIS drinking-water compliance, county-level) ([#174](https://github.com/compbiolover/housing-nutrition-label/issues/174)) ([6edee7a](https://github.com/compbiolover/housing-nutrition-label/commit/6edee7aa7169ca9180ab6c1a6a48378ff73a5cb6))

## [0.1.50](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.49...v0.1.50) (2026-07-18)


### Features

* add Air Quality dimension (PM2.5 + ozone + radon) ([#170](https://github.com/compbiolover/housing-nutrition-label/issues/170)) ([03899b0](https://github.com/compbiolover/housing-nutrition-label/commit/03899b00c42dd713585cffadfdd0afdb32cbd9c3))
* add Solar Potential dimension (rooftop PV yield + savings + CO₂ avoided) ([#172](https://github.com/compbiolover/housing-nutrition-label/issues/172)) ([8e6626b](https://github.com/compbiolover/housing-nutrition-label/commit/8e6626baecd32a645340cff95f4d60dfa9d01544))
* **air-quality:** resolve PM2.5 + ozone at the census tract ([#171](https://github.com/compbiolover/housing-nutrition-label/issues/171)) ([a144be2](https://github.com/compbiolover/housing-nutrition-label/commit/a144be2779bccb290c08d2a9374dc2dd18c4e946))


### Code Refactoring

* consolidate duplicated haversine + _num helpers onto shared modules ([#169](https://github.com/compbiolover/housing-nutrition-label/issues/169)) ([8cc3453](https://github.com/compbiolover/housing-nutrition-label/commit/8cc34533dde9f0f4cec6170f0ab6028690ae918f))
* share resilience score primitives between simulator and batch scorer ([#167](https://github.com/compbiolover/housing-nutrition-label/issues/167)) ([f1af7f6](https://github.com/compbiolover/housing-nutrition-label/commit/f1af7f637afad12212d9b45ed69faa504165d6cb))

## [0.1.49](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.48...v0.1.49) (2026-07-17)


### Code Refactoring

* delete the orphaned enrich/walkscore.py + stale Walk Score docs ([#166](https://github.com/compbiolover/housing-nutrition-label/issues/166)) ([d9e6d6a](https://github.com/compbiolover/housing-nutrition-label/commit/d9e6d6ac8c8d16d7cdda6400175b2e8933f42635))
* remove the Shelby batch pipeline and local-grade machinery ([#164](https://github.com/compbiolover/housing-nutrition-label/issues/164)) ([f1e6710](https://github.com/compbiolover/housing-nutrition-label/commit/f1e671024ed1329d1c3937d769a849391e3b141d))

## [0.1.48](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.47...v0.1.48) (2026-07-17)


### Bug Fixes

* don't cache degraded labels when NSI structure detection is unavailable ([#162](https://github.com/compbiolover/housing-nutrition-label/issues/162)) ([91b9786](https://github.com/compbiolover/housing-nutrition-label/commit/91b978661b68c86e2c16035b96e5b0422bbb94e1))

## [0.1.47](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.46...v0.1.47) (2026-07-16)


### Features

* add NREL Cambium 2023 LRMER marginal grid emissions to Environmental ([#161](https://github.com/compbiolover/housing-nutrition-label/issues/161)) ([9239200](https://github.com/compbiolover/housing-nutrition-label/commit/923920007774b3f038a2eb76d94abb2f16477a04))
* base the Energy EUI on NREL ResStock zone×vintage medians ([#158](https://github.com/compbiolover/housing-nutrition-label/issues/158)) ([b120975](https://github.com/compbiolover/housing-nutrition-label/commit/b120975442a9480cc2cdb9fa2283131d97e9198f))
* key ResStock energy on building type + ResStock foundation/HVAC factors ([#160](https://github.com/compbiolover/housing-nutrition-label/issues/160)) ([4556680](https://github.com/compbiolover/housing-nutrition-label/commit/45566807c3224ae6cf8f398f3ab79eaac217e1d5))

## [0.1.46](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.45...v0.1.46) (2026-07-15)


### Features

* add education and jobs to the Socioeconomic index ([#153](https://github.com/compbiolover/housing-nutrition-label/issues/153)) ([098d510](https://github.com/compbiolover/housing-nutrition-label/commit/098d51030ee09117f824336ecc13a02d257861f8))

## [0.1.45](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.44...v0.1.45) (2026-07-15)


### Bug Fixes

* hide the density-comparison button for detected multi-unit buildings ([#151](https://github.com/compbiolover/housing-nutrition-label/issues/151)) ([06e3802](https://github.com/compbiolover/housing-nutrition-label/commit/06e3802ea1fbbe05a5ae58a642951a81c7e37a9f))

## [0.1.44](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.43...v0.1.44) (2026-07-15)


### Bug Fixes

* show the density cost line for NSI-detected multi-unit buildings ([#149](https://github.com/compbiolover/housing-nutrition-label/issues/149)) ([82e00cb](https://github.com/compbiolover/housing-nutrition-label/commit/82e00cbbd707dd86b3a87865f281728e5ac54537))

## [0.1.43](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.42...v0.1.43) (2026-07-15)


### Bug Fixes

* make the multi-unit density cost line isolate density, not size ([#147](https://github.com/compbiolover/housing-nutrition-label/issues/147)) ([b16441e](https://github.com/compbiolover/housing-nutrition-label/commit/b16441eb960d0503f8a83872ec02601ca9885e03))

## [0.1.42](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.41...v0.1.42) (2026-07-15)


### Features

* capture multi-unit density in infrastructure burden and add a vs-detached cost line ([#145](https://github.com/compbiolover/housing-nutrition-label/issues/145)) ([b31e3af](https://github.com/compbiolover/housing-nutrition-label/commit/b31e3afdc810c9676c8ff6a68def71050dca7813))

## [0.1.41](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.40...v0.1.41) (2026-07-15)


### Code Refactoring

* **web:** unify the scoring UI into one LabelForm widget ([#143](https://github.com/compbiolover/housing-nutrition-label/issues/143)) ([e9cd984](https://github.com/compbiolover/housing-nutrition-label/commit/e9cd984f604aa39d957ab78305a58e5c1e1fa63c))

## [0.1.40](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.39...v0.1.40) (2026-07-15)


### Bug Fixes

* size-match the cost-over-mortgage baseline comparable ([#141](https://github.com/compbiolover/housing-nutrition-label/issues/141)) ([cc76137](https://github.com/compbiolover/housing-nutrition-label/commit/cc761375bf56f1135d991d5d22de50f452e8d9cf))

## [0.1.39](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.38...v0.1.39) (2026-07-15)


### Features

* converge BRM onto one continuous, uncapped model ([#138](https://github.com/compbiolover/housing-nutrition-label/issues/138)) ([81ca12a](https://github.com/compbiolover/housing-nutrition-label/commit/81ca12a6da774d31fef78e808008f1b11334a839))

## [0.1.38](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.37...v0.1.38) (2026-07-11)


### Features

* consolidate tornado hazard onto FEMA NRI, retiring the SPC model ([#136](https://github.com/compbiolover/housing-nutrition-label/issues/136)) ([a386e08](https://github.com/compbiolover/housing-nutrition-label/commit/a386e084d6980764af11be16e95df186a169cd84))
* true seismic return periods from USGS 2023 NSHM hazard curve ([#135](https://github.com/compbiolover/housing-nutrition-label/issues/135)) ([6f2c648](https://github.com/compbiolover/housing-nutrition-label/commit/6f2c648a005a19e0b2260293db1a4dd69b12f0e4))


### Bug Fixes

* activate real footprint for geocoded addresses + refresh embodied confidence copy ([#133](https://github.com/compbiolover/housing-nutrition-label/issues/133)) ([07aec31](https://github.com/compbiolover/housing-nutrition-label/commit/07aec313695920f6c4f326837269bb889cf50753))

## [0.1.37](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.36...v0.1.37) (2026-07-10)


### Features

* bottom-up embodied carbon from industry-average EPD factors ([#129](https://github.com/compbiolover/housing-nutrition-label/issues/129)) ([3b8335c](https://github.com/compbiolover/housing-nutrition-label/commit/3b8335ce3647d51a107100dfa8c47b5779ba152b))
* geometry-aware embodied carbon (per-home takeoffs + basement depth) ([#131](https://github.com/compbiolover/housing-nutrition-label/issues/131)) ([407fc25](https://github.com/compbiolover/housing-nutrition-label/commit/407fc258cde97763ab403cc6466c5b4c9cf48522))
* real building footprint (USA Structures) for embodied carbon ([#132](https://github.com/compbiolover/housing-nutrition-label/issues/132)) ([e18fb8d](https://github.com/compbiolover/housing-nutrition-label/commit/e18fb8dc6a2acc9bc3f126c24e17479515ab7860))

## [0.1.36](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.35...v0.1.36) (2026-07-10)


### Performance Improvements

* store tract crosswalks columnar to cut ~320 MB of RSS ([#126](https://github.com/compbiolover/housing-nutrition-label/issues/126)) ([280d907](https://github.com/compbiolover/housing-nutrition-label/commit/280d9074e088e06784bdd2840bc60ae492a8920a))

## [0.1.35](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.34...v0.1.35) (2026-07-10)


### Features

* auto-fill home value from the census-tract median, not county ([#124](https://github.com/compbiolover/housing-nutrition-label/issues/124)) ([7643aad](https://github.com/compbiolover/housing-nutrition-label/commit/7643aada643e12372c20d875ce19ff7c0f175b92))

## [0.1.34](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.33...v0.1.34) (2026-07-10)


### Features

* realistic cluster unit count + net-of-common-area per-unit sqft ([#121](https://github.com/compbiolover/housing-nutrition-label/issues/121)) ([b332d8d](https://github.com/compbiolover/housing-nutrition-label/commit/b332d8dce774326618ebe63b487b2f904fd45e9c))

## [0.1.33](https://github.com/compbiolover/housing-nutrition-label/compare/v0.1.32...v0.1.33) (2026-07-10)


### Bug Fixes

* report one dwelling's sqft for an NSI apartment cluster ([#119](https://github.com/compbiolover/housing-nutrition-label/issues/119)) ([4c2a9fd](https://github.com/compbiolover/housing-nutrition-label/commit/4c2a9fdcba40803138f8096b8d9a811411599e41))

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
