"""Run column selection N times and aggregate accuracy + latency.

For each run it executes the full Step 1 test (10 questions), then reads the
produced ``step1_summary.json`` to compute:
  - key-columns-found per question (accuracy)
  - elapsed seconds per question (latency)

Usage:
  STRUCTURED_LLM_MODEL_NAME=... STRUCTURED_LLM_THINKING=false \
  python tests/e2e/run_step1_latency_accuracy.py --runs 5
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = PROJECT_ROOT / "tests" / "e2e" / "test_step1_column_selection.py"


def aggregate_from_dirs(base_out: Path):
    """Re-aggregate from already-saved run dirs (no re-execution)."""
    rows = []
    total_scores = []
    run_dirs = sorted(base_out.glob("run*"))
    for i, run_dir in enumerate(run_dirs, start=1):
        candidates = sorted(run_dir.rglob("step1_summary.json"))
        if not candidates:
            print(f"[RUN {i}] no summary under {run_dir}")
            continue
        with open(candidates[0]) as f:
            summary = json.load(f)
        run_found = run_total = 0
        run_llm = 0.0
        for r in summary["results"]:
            ck = r.get("key_column_check") or {}
            found = sum(1 for v in ck.values() if v)
            tot = len(ck)
            run_found += found
            run_total += tot
            run_llm += r.get("elapsed_seconds", 0.0)
            rows.append({
                "run": i, "query": r.get("query", "")[:40],
                "found": found, "total": tot,
                "elapsed": r.get("elapsed_seconds", 0.0),
                "misses": [k for k, v in ck.items() if not v],
            })
        total_scores.append(f"{run_found}/{run_total}")
        print(f"[RUN {i}] key_cols_found: {run_found}/{run_total} | "
              f"LLM+match total: {run_llm:.1f}s | avg/q: {run_llm/max(len(summary['results']),1):.1f}s")
    _print_aggregate(rows, total_scores, base_out)


def _print_aggregate(rows, total_scores, base_out):
    by_query: dict = {}
    for row in rows:
        by_query.setdefault(row["query"], []).append(row)

    print("\n" + "═" * 70)
    print("PER-QUESTION ACROSS RUNS")
    print(f"{'question':<42}{'found/total':<14}{'avg_s':>7}{'p95_s':>7}{'min_s':>7}{'max_s':>7}  miss-count")
    print("-" * 100)
    for q, rs in sorted(by_query.items(), key=lambda kv: kv[0]):
        found = sum(r["found"] for r in rs)
        total = sum(r["total"] for r in rs)
        els = sorted(r["elapsed"] for r in rs)
        avg = sum(els) / len(els)
        p95 = els[int(len(els) * 0.95) - 1] if len(els) > 1 else els[-1]
        miss_total = sum(len(r["misses"]) for r in rs)
        print(f"{q[:25]:<26}{found:>6}/{total:<3}{avg:>8.1f}{p95:>9.1f}"
              f"{els[0]:>7.1f}{els[-1]:>7.1f}  {miss_total}")

    print("\n" + "═" * 70)
    total_found = sum(r["found"] for r in rows)
    total_total = sum(r["total"] for r in rows)
    all_els = [r["elapsed"] for r in rows]
    print(f"AGGREGATE ({len(rows)} question-runs):")
    if all_els:
        print(f"  key_cols_found overall : {total_found}/{total_total}")
        print(f"  mean latency /question : {sum(all_els)/len(all_els):.1f}s")
        print(f"  p95   latency /question: {sorted(all_els)[int(len(all_els)*0.95)-1]:.1f}s")
        print(f"  best  run score        : {max(total_scores)}")
        print(f"  per-run scores         : {', '.join(total_scores)}")

        with open(base_out / "aggregate.json", "w") as f:
            json.dump(
                {
                    "runs": len(total_scores),
                    "per_run": total_scores,
                    "per_question": {
                        q: {"found": sum(r["found"] for r in rs),
                            "total": sum(r["total"] for r in rs),
                            "avg_s": sum(r["elapsed"] for r in rs) / len(rs),
                            "misses": [m for r in rs for m in r["misses"]]}
                        for q, rs in sorted(by_query.items(), key=lambda kv: kv[0])
                    },
                },
                f,
                indent=2,
            )
        print(f"\nSaved aggregate → {base_out / 'aggregate.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", default="/tmp/step1_latency_accuracy")
    ap.add_argument("--resume", action="store_true",
                    help="Re-aggregate from saved run dirs instead of re-running.")
    args = ap.parse_args()

    base_out = Path(args.out)
    base_out.mkdir(parents=True, exist_ok=True)

    if args.resume:
        aggregate_from_dirs(base_out)
        return 0

    env = dict(os.environ)

    rows = []  # per-run per-question rows
    total_scores = []

    for i in range(1, args.runs + 1):
        run_dir = base_out / f"run{i}"
        run_dir.mkdir(parents=True, exist_ok=True)
        env["OUTPUT_DIR"] = str(run_dir)
        env["COLUMN_SELECTION_CACHE_BUSTER"] = f"lat_accuracy_run{i}_{int(time.time())}"

        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, str(TEST_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        wall = time.time() - t0

        # The test writes step1_summary.json into a timestamped subdir.
        candidates = sorted(run_dir.rglob("step1_summary.json"))
        summary_file = candidates[0] if candidates else None
        if summary_file is None:
            print(f"[RUN {i}] FAILED to produce summary. rc={proc.returncode}")
            print(proc.stdout[-1500:])
            print(proc.stderr[-1500:])
            continue

        with open(summary_file) as f:
            summary = json.load(f)

        run_found = 0
        run_total = 0
        run_llm = 0.0
        for r in summary["results"]:
            ck = r.get("key_column_check") or {}
            found = sum(1 for v in ck.values() if v)
            tot = len(ck)
            run_found += found
            run_total += tot
            run_llm += r.get("elapsed_seconds", 0.0)
            rows.append(
                {
                    "run": i,
                    "query": r.get("query", "")[:40],
                    "found": found,
                    "total": tot,
                    "elapsed": r.get("elapsed_seconds", 0.0),
                    "misses": [k for k, v in ck.items() if not v],
                }
            )

        score = f"{run_found}/{run_total}"
        total_scores.append(score)
        avg = run_llm / max(len(summary["results"]), 1)
        print(f"[RUN {i}] key_cols_found: {score} | LLM+match total: {run_llm:.1f}s | avg/q: {avg:.1f}s | wall: {wall:.0f}s")

    _print_aggregate(rows, total_scores, base_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())