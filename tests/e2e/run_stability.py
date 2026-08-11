"""
Stability test — run the same query N times against the running server to
check answer correctness / determinism.

This is useful for verifying whether the retried queries (Q13a/Q19/Q28/Q30)
produce correct, stable answers, and whether enabling thinking-trace logging
helped reveal why the LLM generated buggy code.

Usage:
    python tests/e2e/run_stability.py --query "..." --runs 5

    # Use the curated enterprise questions (imports helpers from test_enterprise_data)
    python tests/e2e/run_stability.py --question Q19 --runs 5

Prerequisites:
    - Server running locally (make -f Makefile.build run-local)
    - .env configured
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e.test_enterprise_data import (  # noqa: E402
    BASE_URL,
    CSV_FILE,
    SEMANTIC_MODEL_FILE,
    PANDASAI_CONFIG,
    _load_csv_as_base64,
    _load_semantic_model,
)

# The retried queries from the last run — mapping ID -> pandasai_input.
# (Q13a/Q13b/Q13c are three attempts of the same sick-leave question.)
STABILITY_QUESTIONS: Dict[str, str] = {
    "Q13a": (
        "How many sick leaves did employee 1136 take in 2025? "
        "Count total sick leave days and list each record with dates."
    ),
    "Q19": (
        "Find education details for employees with IDs '0982' and '1177'. "
        "For each employee, return name, employee ID, organizational unit, "
        "department, grade, and ALL education information including "
        "degree/certification name, field of study, institution, start date, "
        "end date. Compare their education backgrounds side by side."
    ),
    "Q28": (
        "Find all employees who have 'Senior Specialist' in their job title "
        "or position. For each employee, show Employee Name, Employee ID, "
        "Grade, Position Title, Department, Division, Organizational Unit, "
        "Years of Service, and any salary-related fields. Calculate the "
        "average salary of these employees."
    ),
    "Q30": (
        "What are the leadership roles in ADEO? Find employees with "
        "management/leadership titles and list their roles."
    ),
}


def _register(client: httpx.Client, semantic_model: dict) -> str:
    payload = {
        "base64_data": _load_csv_as_base64(CSV_FILE),
        "mimetype": "text/csv",
        "semantic_model": semantic_model,
        "pandasai_config": PANDASAI_CONFIG,
    }
    resp = client.post(f"{BASE_URL}/api/register/base64", json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()["conversation_id"]


def _chat(client: httpx.Client, conversation_id: str, query: str) -> dict:
    payload = {
        "conversation_id": conversation_id,
        "query": query,
        "output_type": "string",
        "column_selection_enabled": True,
        "column_selection_threshold": 30,
        "column_values_budget_ratio": 0.10,
    }
    resp = client.post(f"{BASE_URL}/api/chat", json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()


def run_stability(query: str, runs: int = 5, question_id: Optional[str] = None) -> None:
    if not query and question_id not in STABILITY_QUESTIONS:
        print(f"❌ Unknown question {question_id}. Choose from {list(STABILITY_QUESTIONS)}")
        return

    label = question_id or "custom"
    query = query or STABILITY_QUESTIONS[question_id]

    semantic_model = _load_semantic_model(SEMANTIC_MODEL_FILE)
    print(f"Server: {BASE_URL}")
    print(f"Question: {label}")
    print(f"Runs: {runs}")
    print(f"Query: {query[:120]}...")
    print("=" * 70)

    results = []
    types = {}
    with httpx.Client(timeout=300) as client:
        for i in range(1, runs + 1):
            print(f"\n--- Run {i}/{runs} ---")
            try:
                t0 = time.time()
                conv_id = _register(client, semantic_model)
                reg_s = round(time.time() - t0, 1)
                t0 = time.time()
                resp = _chat(client, conv_id, query)
                chat_s = round(time.time() - t0, 1)
                rtype = resp.get("type")
                rval = resp.get("response")
                sel = resp.get("selected_columns")
                types[rtype] = types.get(rtype, 0) + 1
                print(f"  type={rtype} ({chat_s}s, reg {reg_s}s, {len(sel) if sel else 0} cols)")
                print(f"  response: {str(rval)[:200]}")
                results.append({
                    "run": i,
                    "status": "completed",
                    "type": rtype,
                    "response": str(rval)[:500] if rval else None,
                    "selected_columns": sel,
                    "chat_elapsed_seconds": chat_s,
                    "register_elapsed_seconds": reg_s,
                })
            except Exception as e:
                print(f"  ❌ failed: {e}")
                results.append({"run": i, "status": "failed", "error": str(e)})

    print("\n" + "=" * 70)
    print(f"STABILITY SUMMARY — {label} ({runs} runs)")
    print("=" * 70)
    print(f"Type distribution: {types}")
    ok = [r for r in results if r.get("status") == "completed"]
    print(f"Completed: {len(ok)}/{runs}")
    # Detect answer variance
    answers = [r.get("response") for r in ok if r.get("response")]
    unique = set(answers)
    print(f"Unique responses: {len(unique)}/{len(answers)}")

    out_dir = PROJECT_ROOT / "run" / "e2e_reports" / "stability"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{label}_{runs}x.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"question": label, "query": query, "runs": runs, "results": results}, f, indent=2, default=str)
    print(f"\nSaved: {out_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--question", help="One of Q13a/Q19/Q28/Q30")
    parser.add_argument("--query", help="Custom query string")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    run_stability(args.query, args.runs, args.question)