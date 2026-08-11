"""Run all question-bank stability tests sequentially (1 run each, no-cache)
and produce a compact per-question report: success/failure, retry count, and
latency (chat + registration) per question.

Usage:
    python tests/e2e/run_all_retried.py
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e.run_stability import STABILITY_QUESTIONS  # noqa: E402

QUESTIONS = list(STABILITY_QUESTIONS.keys())

# Matches the run_stability.py per-run line:
#   "  type=string (12.4s, reg 5.0s, 26 cols)"
_PER_RUN_RE = re.compile(r"type=(\S+)\s+\(([0-9.]+)s, reg ([0-9.]+)s")


def _parse_latency(stdout: str) -> tuple:
    """Extract (chat_s, reg_s) from the latest per-run line in stdout."""
    matches = list(_PER_RUN_RE.finditer(stdout))
    if not matches:
        return None, None
    m = matches[-1]
    return float(m.group(2)), float(m.group(3))


def main():
    results = {}
    wall_start = time.time()
    for qid in QUESTIONS:
        print(f"\n{'='*70}\nRunning {qid} ...\n{'='*70}")
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "tests/e2e/run_stability.py",
                 "--question", qid, "--runs", "1", "--no-cache"],
                capture_output=True, text=True, timeout=900, cwd=PROJECT_ROOT,
            )
        except subprocess.TimeoutExpired:
            results[qid] = {
                "returncode": "TIMEOUT",
                "chat_elapsed_seconds": None,
                "register_elapsed_seconds": None,
                "wall_elapsed_seconds": round(time.time() - t0, 1),
            }
            print(f"  ⏰ TIMEOUT ({results[qid]['wall_elapsed_seconds']}s)")
            continue

        chat_s, reg_s = _parse_latency(proc.stdout)
        results[qid] = {
            "returncode": proc.returncode,
            "chat_elapsed_seconds": chat_s,
            "register_elapsed_seconds": reg_s,
            "wall_elapsed_seconds": round(time.time() - t0, 1),
        }
        tail = proc.stdout[-600:]
        print(tail)
        print(f"  -> chat={chat_s}s reg={reg_s}s wall={results[qid]['wall_elapsed_seconds']}s")

    # Save summary
    out = PROJECT_ROOT / "run/e2e_reports/stability/all_retried_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    # Human-readable latency table
    print("\n" + "=" * 72)
    print("LATENCY PER QUESTION (seconds)")
    print("=" * 72)
    total = 0.0
    total_wall = time.time() - wall_start
    for qid in QUESTIONS:
        r = results[qid]
        chat = r.get("chat_elapsed_seconds")
        if chat is None:
            print(f"  {qid:<32} {str(r.get('wall_elapsed_seconds')) + 's (FAIL/TIMEOUT)':<20}")
            continue
        total += chat
        print(f"  {qid:<32} chat={chat:6.1f}s  reg={r['register_elapsed_seconds']:5.1f}s  "
              f"wall={r['wall_elapsed_seconds']:6.1f}s")
    print("-" * 72)
    print(f"  {'TOTAL':<32} chat={total:6.1f}s  wall={total_wall:6.1f}s")
    print(f"  {'AVG per question':<32} chat={total/len(QUESTIONS):6.1f}s")
    print(f"\nSummary saved: {out}")


if __name__ == "__main__":
    main()