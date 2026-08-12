"""Analyze run_stability_agent.py output and produce a markdown report.

Reads a run directory (default: most recent under OUTPUT_DIR, or
STABILITY_RUN_DIR env) and writes STABILITY_AGENT_REPORT.md listing, per
question across runs:

  - total runs / success / failed / retried
  - average / min / max latency (elapsed_total)
  - per-phase timing averages (column_selection, code_generation,
    code_execution)
  - a table of every run that had to retry (gen>1 or exec>1)

Usage:
  OUTPUT_DIR=/tmp/stab_full_p python tests/e2e/analyze_stability_agent.py
"""
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from run_step2_all import OUTPUT_DIR  # noqa: E402


def _load_results(run_dir):
    summary = Path(run_dir) / "summary.json"
    if summary.exists():
        return json.loads(summary.read_text(encoding="utf-8"))
    results = []
    for f in sorted(Path(run_dir).glob("*_r*.json")):
        results.append(json.loads(f.read_text(encoding="utf-8")))
    return results


def _fmt(s):
    return f"{s:.1f}s" if s is not None else "-"


def _avg(vals):
    return sum(vals) / len(vals) if vals else 0.0


def main():
    env_dir = os.environ.get("STABILITY_RUN_DIR", "").strip()
    if env_dir:
        run_dir = env_dir
    else:
        dirs = sorted(glob.glob(str(OUTPUT_DIR / "*_stability_agent")))
        if not dirs:
            raise SystemExit(f"No stability_agent run dirs under {OUTPUT_DIR}")
        run_dir = dirs[-1]

    results = _load_results(run_dir)
    print(f"Analyzing {len(results)} runs from {run_dir}\n")

    by_q = {}
    for o in results:
        by_q.setdefault(o["question"], []).append(o)

    n_runs = len(next(iter(by_q.values())))
    n_total = len(results)
    n_ok = sum(1 for o in results if o["executed"])
    n_fail = n_total - n_ok
    n_retry = sum(1 for o in results if o.get("retried"))

    L = []
    L.append("# Stability Agent Report (production agent.chat path)")
    L.append("")
    L.append(f"- **Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- **Source dir**: `{run_dir}`")
    L.append(f"- **Runs per question**: {n_runs}")
    L.append(f"- **Cache buster**: per-run unique marker (ON)")
    L.append("")

    L.append("## Overall")
    L.append("")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Total runs | {n_total} |")
    L.append(f"| Success | {n_ok}/{n_total} |")
    L.append(f"| Failed | {n_fail}/{n_total} |")
    L.append(f"| Runs needing a retry | {n_retry}/{n_total} |")
    L.append("")

    L.append("## Per-question (across runs)")
    L.append("")
    L.append("| Question | Success | Failed | Retried | Avg lat | Min lat | Max lat | Avg sel | Avg codegen | Avg exec |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for qid in sorted(by_q):
        q = by_q[qid]
        qn = len(q)
        ok = sum(1 for o in q if o["executed"])
        fail = qn - ok
        ret = sum(1 for o in q if o.get("retried"))
        times = [o.get("elapsed_total") or 0 for o in q]
        sel = [(o.get("timings") or {}).get("column_selection") or 0 for o in q]
        cg = [(o.get("timings") or {}).get("code_generation") or 0 for o in q]
        ex = [(o.get("timings") or {}).get("code_execution") or 0 for o in q]
        L.append(
            f"| {qid} | {ok}/{qn} | {fail} | {ret} | {_fmt(_avg(times))} | "
            f"{_fmt(min(times))} | {_fmt(max(times))} | {_fmt(_avg(sel))} | "
            f"{_fmt(_avg(cg))} | {_fmt(_avg(ex))} |"
        )
    L.append("")

    failed = [o for o in results if not o["executed"]]
    if failed:
        L.append("## Failed Runs")
        L.append("")
        L.append("| Run | Stage | Error |")
        L.append("|---|---|---|")
        for o in failed:
            L.append(
                f"| {o['question']} r{o['run']} | {o.get('failure_stage')} | "
                f"{str(o.get('error'))[:140]} |"
            )
        L.append("")

    retried = [o for o in results if o.get("retried")]
    if retried:
        L.append("## Runs that required a retry")
        L.append("")
        L.append("| Run | Gen attempts | Exec attempts | Latency | Final type |")
        L.append("|---|---|---|---|---|")
        for o in retried:
            L.append(
                f"| {o['question']} r{o['run']} | {o.get('gen_attempts')} | "
                f"{o.get('exec_attempts')} | {_fmt(o.get('elapsed_total'))} | "
                f"{o.get('response_type')} |"
            )
        L.append("")

    report = "\n".join(L)
    report_path = Path(run_dir) / "STABILITY_AGENT_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport written: {report_path}")


if __name__ == "__main__":
    main()