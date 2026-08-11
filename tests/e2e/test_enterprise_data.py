"""
End-to-end test runner for the /register and /chat endpoints
using the 20th May enterprise HC dataset.

For each question from the demo questions feedback CSV, this script:
  1. Registers a fresh agent (POST /api/register/base64)
  2. Sends the "Question put as input to PandasAI by agent" to /chat
  3. Saves the full response to a per-question JSON file

Prerequisites:
  - Server running locally: make -f Makefile.build run-local
  - .env file configured with LLM credentials

Usage:
  # Start server in one terminal
  make -f Makefile.build run-local

  # Run the e2e suite
  poetry run python tests/e2e/test_enterprise_data.py

  # Custom server URL
  TEST_SERVER_URL=http://localhost:9000 poetry run python tests/e2e/test_enterprise_data.py
"""

import base64
import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
TIMEOUT_SECONDS = int(os.environ.get("TEST_TIMEOUT", "180"))

# Resolve file paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
REPORTS_DIR = PROJECT_ROOT / "run" / "e2e_reports"

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"
DEMO_QUESTIONS_FILE = DATASETS_DIR / "e2e_test_questions.csv"

# Chat request parameters used for every question
CHAT_PARAMS = {
    "output_type": "string",
    "column_selection_enabled": True,
    "column_selection_threshold": 30,
    "column_values_budget_ratio": 0.10,
}

# PandasAI config for registration
# NOTE: enrichment disabled (2026-08-11) to cut registration CPU cost and reduce
# the prompt's struct-vocabulary size during regression latency testing. It can
# be re-enabled by setting enrich_column_values back to True.
PANDASAI_CONFIG = {
    "enrich_column_values": False,
    "auto_fill_descriptions": False,
}

# Additional questions not in the CSV — manually curated for regression testing.
# Each entry mirrors the CSV row format consumed by _run_single_question().
EXTRA_QUESTIONS: List[Dict] = [
    {
        "num": "3b",
        "test_question": "What are the main skills of employee 1137?",
        "pandasai_input": (
            "Find employee with ID 1137. Return their name, employee ID, "
            "and all their technical competencies/skills from the CV data. "
            "List each skill name."
        ),
        "hc_result": "Failed",
        "issue": "no skills found",
        "n8n_observations": "regression test for column selection fix (CV Employee Competencies as list[struct])",
        "phase": "2",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_csv_as_base64(filepath: Path) -> str:
    """Read a CSV file and return a base64-encoded data URI."""
    with open(filepath, "rb") as f:
        raw = f.read()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:text/csv;base64,{encoded}"


def _load_semantic_model(filepath: Path) -> dict:
    """Load the semantic model JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_demo_questions(filepath: Path) -> List[Dict]:
    """Load test questions from the curated e2e CSV.

    The CSV is pre-filtered to only include rows where both
    'n8n obsevations' and 'Question put as input to pandasai by agent'
    are populated.
    """
    questions = []
    # cp1252 handles Windows smart quotes/curly apostrophes common in this CSV
    with open(filepath, "r", encoding="cp1252") as f:
        reader = csv.DictReader(f)
        for row in reader:
            question_num = row.get("#", "").strip()
            pandasai_input = row.get("Question put as input to pandasai by agent", "").strip()
            test_question = row.get("Test Question", "").strip()
            if not pandasai_input:
                continue
            questions.append({
                "num": question_num,
                "test_question": test_question,
                "pandasai_input": pandasai_input,
                "hc_result": row.get("HC test result", "").strip(),
                "issue": row.get("Issue", "").strip(),
                "n8n_observations": row.get("n8n obsevations", "").strip(),
                "phase": row.get("Phase", "").strip(),
            })
    return questions


def _register_agent(
    client: httpx.Client,
    semantic_model: dict,
) -> str:
    """Call POST /api/register/base64 and return the conversation_id."""
    payload = {
        "base64_data": _load_csv_as_base64(CSV_FILE),
        "mimetype": "text/csv",
        "semantic_model": semantic_model,
        "pandasai_config": PANDASAI_CONFIG,
    }
    resp = client.post(
        f"{BASE_URL}/api/register/base64",
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    conv_id = data["conversation_id"]
    if not conv_id:
        raise RuntimeError(f"Registration returned empty conversation_id: {data}")
    return conv_id


def _chat(
    client: httpx.Client,
    conversation_id: str,
    query: str,
) -> Dict[str, Any]:
    """Call POST /api/chat and return the JSON response."""
    payload = {
        "conversation_id": conversation_id,
        "query": query,
        **CHAT_PARAMS,
    }
    resp = client.post(
        f"{BASE_URL}/api/chat",
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


# Global wall-clock origin — set once in run() before threads launch.
# All timestamps in log events are relative to this (seconds since launch).
_T0: float = 0.0


def _run_single_question(
    index: int,
    q: Dict,
    semantic_model: dict,
) -> tuple:
    """Register + chat for a single question, all in its own thread + httpx.Client.

    Returns (result_dict, log_events) where each log event is
    (wall_offset_seconds, message) so the caller can sort chronologically.
    """
    num = q["num"] or str(index + 1)
    test_q = q["test_question"]
    pandasai_q = q["pandasai_input"]  # always populated due to _load_demo_questions filter
    label = f"Q{num}"
    logs: list = []

    def _log(msg: str):
        """Append a timestamped log event AND print it live."""
        offset = time.time() - _T0
        logs.append((offset, msg))
        print(f"  {offset:6.1f}s  {msg}")

    _log(f"🚀 {label} starting: {test_q[:60]}...")

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        # Register
        try:
            t_reg_start = time.time()
            conv_id = _register_agent(client, semantic_model)
            register_elapsed = time.time() - t_reg_start
            _log(f"✅ {label} registered: {conv_id[:8]}... ({register_elapsed:.1f}s)")
        except Exception as e:
            _log(f"❌ {label} register failed: {e}")
            return (
                {
                    "num": num,
                    "test_question": test_q,
                    "pandasai_input": pandasai_q,
                    "status": "register_failed",
                    "error": str(e),
                    "hc_result": q["hc_result"],
                    "issue": q["issue"],
                    "n8n_observations": q["n8n_observations"],
                    "phase": q["phase"],
                },
                logs,
            )

        # Chat
        try:
            t_chat_start = time.time()
            response = _chat(client, conv_id, pandasai_q)
            chat_elapsed = time.time() - t_chat_start
            result = {
                "num": num,
                "test_question": test_q,
                "pandasai_input": pandasai_q,
                "conversation_id": conv_id,
                "status": "completed",
                "response": response.get("response"),
                "type": response.get("type"),
                "last_code_executed": response.get("last_code_executed"),
                "selected_columns": response.get("selected_columns"),
                "chat_elapsed_seconds": round(chat_elapsed, 2),
                "register_elapsed_seconds": round(register_elapsed, 2),
                # Capture code-generation/execution errors + full tracebacks from
                # the server pipeline trace so failures are reproducible from
                # the report alone (without grepping conv_logs).
                "pipeline": response.get("pipeline"),
                "hc_result": q["hc_result"],
                "issue": q["issue"],
                "n8n_observations": q["n8n_observations"],
                "phase": q["phase"],
            }
            sel = response.get("selected_columns")
            sel_info = f", {len(sel)} cols" if sel else ""
            _log(f"✅ {label} type={response.get('type')} ({chat_elapsed:.1f}s{sel_info})")
            return (result, logs)
        except Exception as e:
            chat_elapsed = time.time() - t_chat_start
            _log(f"❌ {label} chat failed ({chat_elapsed:.1f}s): {e}")
            return (
                {
                    "num": num,
                    "test_question": test_q,
                    "pandasai_input": pandasai_q,
                    "conversation_id": conv_id,
                    "status": "chat_failed",
                    "error": str(e),
                    "chat_elapsed_seconds": round(chat_elapsed, 2),
                    "register_elapsed_seconds": round(register_elapsed, 2),
                    "hc_result": q["hc_result"],
                    "issue": q["issue"],
                    "n8n_observations": q["n8n_observations"],
                    "phase": q["phase"],
                },
                logs,
            )


def run():
    """Run the full e2e suite: ALL register+chat fired in parallel, save outputs."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPORTS_DIR / f"{timestamp}_enterprise_e2e"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Enterprise Data E2E Test Runner (FULLY PARALLEL)")
    print("=" * 70)
    print(f"Server:   {BASE_URL}")
    print(f"CSV:      {CSV_FILE}")
    print(f"Model:    {SEMANTIC_MODEL_FILE}")
    print(f"Questions:{DEMO_QUESTIONS_FILE}")
    print(f"Output:   {run_dir}")
    print(f"Chat params: {CHAT_PARAMS}")
    print()

    # Verify files exist
    for f in [CSV_FILE, SEMANTIC_MODEL_FILE, DEMO_QUESTIONS_FILE]:
        if not f.exists():
            print(f"❌ File not found: {f}")
            return
        print(f"✅ Found: {f.name}")

    # Verify server is running
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200
        print(f"✅ Server is healthy: {BASE_URL}")
    except Exception as e:
        print(f"❌ Server not reachable: {e}")
        return

    # Load data
    semantic_model = _load_semantic_model(SEMANTIC_MODEL_FILE)
    questions = _load_demo_questions(DEMO_QUESTIONS_FILE)

    # Append extra inline questions
    if EXTRA_QUESTIONS:
        questions.extend(EXTRA_QUESTIONS)
        print(f"  + {len(EXTRA_QUESTIONS)} extra inline question(s)")

    total = len(questions)
    print(f"\n📝 Loaded {total} questions — firing ALL in parallel")

    # Set the global wall-clock origin so all log timestamps are consistent
    global _T0
    _T0 = time.time()

    # Fire ALL questions at once — each thread does register+chat independently
    results: List[Dict] = [None] * total  # type: ignore
    all_logs: list = []  # (wall_offset_seconds, message) from every thread

    with ThreadPoolExecutor(max_workers=total) as executor:
        future_to_index = {
            executor.submit(_run_single_question, i, q, semantic_model): i
            for i, q in enumerate(questions)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                result, logs = future.result()
                results[idx] = result
                all_logs.extend(logs)
            except Exception as e:
                q = questions[idx]
                results[idx] = {
                    "num": q["num"] or str(idx + 1),
                    "test_question": q["test_question"],
                    "pandasai_input": q["pandasai_input"] or q["test_question"],
                    "status": "unexpected_error",
                    "error": str(e),
                }

    # Print all events sorted by wall-clock time for a true chronological view
    all_logs.sort(key=lambda x: x[0])
    print(f"\n{'─' * 60}")
    print("Chronological event log (wall-clock seconds since launch):")
    print(f"{'─' * 60}")
    for offset, msg in all_logs:
        print(f"  {offset:6.1f}s  {msg}")

    # Save individual results
    for result in results:
        if result:
            label = f"Q{result['num']}"
            _save_question_result(run_dir, label, result)

    # Save summary
    _save_summary(run_dir, results, timestamp)

    # Print summary
    completed = sum(1 for r in results if r and r["status"] == "completed")
    failed = sum(1 for r in results if r and r["status"] != "completed")
    print(f"\n{'=' * 70}")
    print(f"Results: {completed}/{total} completed, {failed} failed")
    print(f"Output:  {run_dir}")
    print(f"{'=' * 70}")


def _save_question_result(run_dir: Path, label: str, result: Dict):
    """Save a single question's result to its own JSON file."""
    outfile = run_dir / f"{label}.json"
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)


def _save_summary(run_dir: Path, results: List[Dict], timestamp: str):
    """Save the full summary JSON."""
    summary = {
        "timestamp": timestamp,
        "test_type": "enterprise_data_e2e",
        "config": {
            "base_url": BASE_URL,
            "csv_file": str(CSV_FILE),
            "semantic_model_file": str(SEMANTIC_MODEL_FILE),
            "chat_params": CHAT_PARAMS,
            "pandasai_config": PANDASAI_CONFIG,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "summary": {
            "total": len(results),
            "completed": sum(1 for r in results if r["status"] == "completed"),
            "register_failed": sum(1 for r in results if r["status"] == "register_failed"),
            "chat_failed": sum(1 for r in results if r["status"] == "chat_failed"),
        },
        "results": results,
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    run()
