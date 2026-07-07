# Contributing

## Commit / PR conventions

This repo uses **[Conventional Commits](https://www.conventionalcommits.org/)** to drive
automated versioning and the changelog. Because we **squash-merge**, the **pull-request
title** becomes the single commit on `main`, so the PR title must follow the convention:

```
<type>[optional scope]: <summary>
```

A workflow (`.github/workflows/pr-title.yml`) lints every PR title. Allowed types:

| Type | Use for | Release effect (pre-1.0) |
|------|---------|--------------------------|
| `feat` | a new capability | patch bump (minor once ≥ 1.0) |
| `fix` | a bug fix | patch bump |
| `feat!` / `fix!` or a `BREAKING CHANGE:` footer | a breaking change | **minor** bump (major once ≥ 1.0) |
| `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert` | everything else | changelog-only; no release on its own |

Examples: `feat(climate): add ClimRR fire-weather leg` · `fix: handle 0–360 longitude grids`
· `docs: expand methodology caveats`. Keep the summary lowercase and imperative.

## Releases (automated)

Releases are handled by **[release-please](https://github.com/googleapis/release-please)** —
you do not bump versions or edit `CHANGELOG.md` by hand:

1. Merge feature/fix PRs to `main` as usual (squash).
2. release-please keeps an open **"release PR"** that accumulates the next version and the
   changelog. Review/edit it like any PR.
3. **Merging the release PR** bumps `pyproject.toml`, updates `CHANGELOG.md`, creates the
   `vX.Y.Z` git tag, and publishes the GitHub Release.

The version source of truth is `[project].version` in `pyproject.toml`; the current released
version is tracked in `.release-please-manifest.json`.

## Tests

```bash
pip install -e ".[api,dev]"            # editable install + FastAPI + pytest/ruff/httpx
pytest                                 # run the whole suite
ruff check .                           # lint (pyflakes: unused imports/vars, undefined names)
```

The `[api]` extra lets the API tests run (they self-skip when FastAPI is absent);
`[dev]` pulls in pytest, ruff, and httpx (which Starlette's `TestClient` needs.)
Every test file also keeps a `_run_all()` runner, so an individual stage stays
runnable as a plain script (`python tests/test_dimensions.py`) with no pytest.

**CI** (`.github/workflows/ci.yml`) runs `ruff check` + `pytest` on every push and
pull request across Python 3.10 and 3.12, so regressions are caught before merge.

Regenerating the bundled climate data needs the build extra (`pip install -e ".[build]"`,
heavy: `xarray`/`netCDF4`) and is documented in `scripts/build_climate_projections.py`.
