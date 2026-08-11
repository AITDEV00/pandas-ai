"""Run all retried-question stability tests sequentially (1 run each, no-cache)
and produce a compact per-question report: first-turn success/failure, retry
count, and the key error in the FIRST failed attempt.

Usage:
    python tests/e2e/run_all_retried.py
"""
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e.run_stability import STABILITY_QUESTIONS  # noqa: E402

QUESTIONS = list(STABILITY_QUESTIONS.keys())

def main():
    results = {}
    for qid in QUESTIONS:
        print(f"\n{'='*70}\nRunning {qid} ...\n{'='*70}")
        try:
            proc = subprocess.run(
                [sys.executable, "tests/e2e/run_stability.py",
                 "--question", qid, "--runs", "1", "--no-cache"],
                capture_output=True, text=True, timeout=600, cwd=PROJECT_ROOT,
            )
            results[qid] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout[-1500:],
                "stderr": proc.stderr[-1500:],
            }
        except subprocess.TimeoutExpired:
            results[qid] = {"returncode": "TIMEOUT", "stdout": "", "stderr": ""}
        print(results[qid]["stdout"])

    # Save summary
    out = PROJECT_ROOT / "run/e2e_reports/stability/all_retried_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n\nSummary saved: {out}")


if __name__ == "__main__":
    main()