#!/usr/bin/env python3
"""run_pipeline.py — Housing Nutrition Label end-to-end pipeline orchestrator.

Runs every stage of the Shelby County resilience pipeline in dependency order,
each stage consuming the previous stage's output so the final ``shelby_parcels_scored.csv``
carries every dimension (hazard + energy + infrastructure + health + scores).

Pipeline order
--------------
  1. ingest         shelby_ingest.py            (ArcGIS API) -> shelby_parcels_sample.csv
  2. clean          clean_parcels.py            sample       -> shelby_parcels_clean.csv
  3. flood          enrich_fema_flood.py        clean        -> shelby_parcels_flood.csv
  4. climate        enrich_noaa_climate.py      flood        -> shelby_parcels_climate.csv
  5. tornado        enrich_tornado.py           climate      -> shelby_parcels_tornado.csv
  6. seismic        enrich_seismic.py           tornado      -> shelby_parcels_seismic.csv
  7. energy         enrich_energy.py            seismic      -> shelby_parcels_energy.csv
  8. infrastructure enrich_infrastructure.py    energy       -> shelby_parcels_infrastructure.csv
  9. health         enrich_health.py            infrastructure -> shelby_parcels_health.csv
 10. score          score_resilience.py         health       -> shelby_parcels_scored.csv

Freshness / skipping
--------------------
A stage is re-run when any of the following is true:
  * ``--force`` was passed, or
  * its output file is missing, or
  * its input file is newer than its output (upstream changed), or
  * its own script file is newer than its output (logic changed).
Otherwise the stage is skipped as "fresh".

Usage
-----
  python run_pipeline.py                      # run stale/missing stages
  python run_pipeline.py --force              # re-run everything fresh
  python run_pipeline.py --step flood         # run only the flood stage (forced)
  python run_pipeline.py --from energy        # run energy .. score onward
  python run_pipeline.py --limit 25           # quick test on a subset of parcels
  python run_pipeline.py --continue-on-error  # keep going after a stage fails
  python run_pipeline.py --dry-run            # show the plan without executing stages

Stages are invoked with ``sys.executable`` so the pipeline always uses the same
Python interpreter (and virtualenv) that runs this orchestrator.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("pipeline")

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


# ── Stage definitions ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Stage:
    name: str                       # short key used by --step / --from
    script: str                     # script filename
    output: str                     # output CSV filename (relative to SCRIPT_DIR)
    input: str | None = None        # input CSV filename, or None for the ingest stage
    extra_args: list[str] = field(default_factory=list)  # always-on extra CLI args
    supports_limit: bool = True     # whether the stage honours --limit


STAGES: list[Stage] = [
    Stage("ingest",         "shelby_ingest.py",         "shelby_parcels_sample.csv",         input=None),
    Stage("clean",          "clean_parcels.py",         "shelby_parcels_clean.csv",          input="shelby_parcels_sample.csv",         supports_limit=False),
    Stage("flood",          "enrich_fema_flood.py",     "shelby_parcels_flood.csv",          input="shelby_parcels_clean.csv"),
    Stage("climate",        "enrich_noaa_climate.py",   "shelby_parcels_climate.csv",        input="shelby_parcels_flood.csv"),
    Stage("tornado",        "enrich_tornado.py",        "shelby_parcels_tornado.csv",        input="shelby_parcels_climate.csv"),
    Stage("seismic",        "enrich_seismic.py",        "shelby_parcels_seismic.csv",        input="shelby_parcels_tornado.csv"),
    Stage("energy",         "enrich_energy.py",         "shelby_parcels_energy.csv",         input="shelby_parcels_seismic.csv"),
    Stage("infrastructure", "enrich_infrastructure.py", "shelby_parcels_infrastructure.csv", input="shelby_parcels_energy.csv"),
    Stage("health",         "enrich_health.py",         "shelby_parcels_health.csv",         input="shelby_parcels_infrastructure.csv"),
    Stage("score",          "score_resilience.py",      "shelby_parcels_scored.csv",         input="shelby_parcels_health.csv"),
]

STAGE_BY_NAME = {s.name: s for s in STAGES}


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _path(name: str) -> pathlib.Path:
    return SCRIPT_DIR / name


def _mtime(p: pathlib.Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def _row_count(p: pathlib.Path) -> int:
    """Count data rows (lines minus header) in a CSV without loading it."""
    if not p.exists():
        return 0
    with p.open("rb") as fh:
        lines = sum(1 for _ in fh)
    return max(0, lines - 1)


def _col_count(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        header = fh.readline()
    return header.count(",") + 1 if header else 0


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def is_stale(stage: Stage, force: bool) -> tuple[bool, str]:
    """Return (needs_run, reason)."""
    if force:
        return True, "forced"
    out = _path(stage.output)
    if not out.exists():
        return True, "output missing"
    out_m = _mtime(out)
    if stage.input is not None:
        in_p = _path(stage.input)
        if in_p.exists() and _mtime(in_p) > out_m:
            return True, f"input '{stage.input}' newer than output"
    if _mtime(_path(stage.script)) > out_m:
        return True, f"script '{stage.script}' newer than output"
    return False, "fresh"


def build_command(stage: Stage, limit: int | None) -> list[str]:
    cmd = [sys.executable, str(_path(stage.script))]
    if stage.input is not None:
        cmd += ["--input", stage.input]
    cmd += ["--output", stage.output]
    if limit is not None and stage.supports_limit:
        cmd += ["--limit", str(limit)]
    cmd += stage.extra_args
    return cmd


# ── Stage selection ──────────────────────────────────────────────────────────────
def select_stages(args: argparse.Namespace) -> list[Stage]:
    if args.step:
        if args.step not in STAGE_BY_NAME:
            log.error("Unknown --step '%s'. Valid: %s", args.step, ", ".join(STAGE_BY_NAME))
            sys.exit(2)
        return [STAGE_BY_NAME[args.step]]
    if args.from_stage:
        if args.from_stage not in STAGE_BY_NAME:
            log.error("Unknown --from '%s'. Valid: %s", args.from_stage, ", ".join(STAGE_BY_NAME))
            sys.exit(2)
        start = next(i for i, s in enumerate(STAGES) if s.name == args.from_stage)
        return STAGES[start:]
    return list(STAGES)


# ── Result record ────────────────────────────────────────────────────────────────
@dataclass
class StageResult:
    name: str
    status: str          # ran | skipped | failed
    seconds: float = 0.0
    rows: int = 0
    cols: int = 0
    size: int = 0
    reason: str = ""


def run_stage(stage: Stage, limit: int | None) -> tuple[int, float]:
    """Execute a stage, streaming its output. Returns (returncode, seconds)."""
    cmd = build_command(stage, limit)
    log.info("▶ %-14s : %s", stage.name, " ".join(cmd[1:]))
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    elapsed = time.perf_counter() - start
    return proc.returncode, elapsed


# ── Main ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Housing Nutrition Label data pipeline end to end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-run every selected stage, ignoring freshness checks.")
    parser.add_argument("--step", metavar="NAME",
                        help="Run only this single stage (forced). E.g. --step flood")
    parser.add_argument("--from", dest="from_stage", metavar="NAME",
                        help="Run this stage and all later stages. E.g. --from energy")
    parser.add_argument("--limit", type=int, default=None,
                        help="Pass --limit N to stages that support it (quick subset test).")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="Continue with later stages even if one fails.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the execution plan without running any stage.")
    args = parser.parse_args()

    if args.step and args.from_stage:
        log.error("--step and --from are mutually exclusive.")
        sys.exit(2)

    stages = select_stages(args)
    # An explicit --step is always run; otherwise apply freshness logic.
    force_all = args.force or bool(args.step)

    log.info("=" * 70)
    log.info("Housing Nutrition Label pipeline — %d stage(s) selected", len(stages))
    if args.limit is not None:
        log.info("Subset mode: --limit %d", args.limit)
    log.info("=" * 70)

    results: list[StageResult] = []
    pipeline_start = time.perf_counter()
    aborted = False

    for stage in stages:
        needs_run, reason = is_stale(stage, force_all)
        out_p = _path(stage.output)

        if not needs_run:
            log.info("⏭ %-14s : skipped (%s)", stage.name, reason)
            results.append(StageResult(stage.name, "skipped",
                                       rows=_row_count(out_p), cols=_col_count(out_p),
                                       size=out_p.stat().st_size if out_p.exists() else 0,
                                       reason=reason))
            continue

        if args.dry_run:
            cmd = build_command(stage, args.limit)
            log.info("• %-14s : WOULD RUN (%s) → %s", stage.name, reason, " ".join(cmd[1:]))
            results.append(StageResult(stage.name, "planned", reason=reason))
            continue

        rc, elapsed = run_stage(stage, args.limit)

        if rc != 0:
            log.error("✖ %-14s : FAILED (exit %d) after %.1fs", stage.name, rc, elapsed)
            results.append(StageResult(stage.name, "failed", seconds=elapsed,
                                       reason=f"exit {rc}"))
            if not args.continue_on_error:
                log.error("Stopping pipeline (use --continue-on-error to proceed).")
                aborted = True
                break
            continue

        rows, cols = _row_count(out_p), _col_count(out_p)
        size = out_p.stat().st_size if out_p.exists() else 0
        log.info("✔ %-14s : done in %.1fs → %s (%d rows × %d cols, %s)",
                 stage.name, elapsed, stage.output, rows, cols, _human_size(size))
        results.append(StageResult(stage.name, "ran", seconds=elapsed,
                                   rows=rows, cols=cols, size=size))

    total_elapsed = time.perf_counter() - pipeline_start

    # ── Final summary ──────────────────────────────────────────────────────────
    print("\n" + "═" * 78)
    print("PIPELINE SUMMARY")
    print("═" * 78)
    print(f"{'stage':<16}{'status':<10}{'time':>9}  {'rows':>6}  {'cols':>5}  {'size':>10}")
    print("─" * 78)
    for r in results:
        time_str = f"{r.seconds:.1f}s" if r.seconds else "—"
        rows_str = f"{r.rows:,}" if r.rows else "—"
        cols_str = f"{r.cols}" if r.cols else "—"
        size_str = _human_size(r.size) if r.size else "—"
        print(f"{r.name:<16}{r.status:<10}{time_str:>9}  {rows_str:>6}  {cols_str:>5}  {size_str:>10}")
    print("─" * 78)

    ran = sum(1 for r in results if r.status == "ran")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    print(f"Total: {ran} ran, {skipped} skipped, {failed} failed  |  wall time {total_elapsed:.1f}s")
    print("═" * 78 + "\n")

    if failed or aborted:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        log.error("Fatal: %s", exc, exc_info=True)
        sys.exit(1)
