"""
Step 1 (Column Selection) Only — E2E Test Runner

Runs the /register + /chat pipeline but STOPS after Step 1 column selection.
Returns verbatim LLM reasoning, raw response, prompt text, and selected columns.

This isolates column selection from code generation so we can diagnose whether
column selection issues come from the prompt template or from the source code
pipeline (parsing, schema matching, trimming).

Prerequisites:
  - Server running locally: make -f Makefile.build run-local
  - .env file configured with LLM credentials

Usage:
  # Run all queries sequentially (default)
  poetry run python tests/e2e/test_step1_only.py

  # Run with parallel workers
  STEP1_ONLY_WORKERS=3 poetry run python tests/e2e/test_step1_only.py

  # Custom server URL
  TEST_SERVER_URL=http://localhost:9000 poetry run python tests/e2e/test_step1_only.py

  # Only run specific questions
  STEP1_ONLY_QUESTIONS=3,15,16 poetry run python tests/e2e/test_step1_only.py
"""

import base64
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
MAX_WORKERS = int(os.environ.get("STEP1_ONLY_WORKERS", "1"))

# Filter which questions to run (comma-separated question nums)
QUESTION_FILTER = os.environ.get("STEP1_ONLY_QUESTIONS", "").strip()

# Resolve file paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
REPORTS_DIR = PROJECT_ROOT / "run" / "e2e_reports"

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"

# Chat request parameters — column selection only
CHAT_PARAMS = {
    "output_type": "string",
    "column_selection_enabled": True,
    "column_selection_threshold": 30,
    "column_values_budget_ratio": 0.10,
    "step1_only": True,  # <-- KEY: stop after column selection
}

# PandasAI config for registration
PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
}

# ---------------------------------------------------------------------------
# Test Questions — focused on multi-struct concepts that require 5-path expansion
# ---------------------------------------------------------------------------
TEST_QUESTIONS: List[Dict] = [
    {
        "num": "3b",
        "test_question": "What are the main skills of employee 1137?",
        "pandasai_input": "What are the main skills of employee 1137?",
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # Path 1: direct skill names
            "Employee Competencies Rating",      # Path 2: proficiency levels
            "CV Employee Work Experience",       # Path 3: applied skills
            "Employee Achievements",             # Path 3: demonstrated skills
            "CV Employee Summary",               # Path 4: professional profile
        ],
    },
    {
        "num": "3",
        "test_question": "What are this employee's main skills?",
        "pandasai_input": (
            "Find employee with ID 1137. Return their name, employee ID, "
            "organizational unit, department/division, grade, years of service, "
            "tenure, and all their technical competencies/skills. Include "
            "competency ratings if available."
        ),
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # Path 1: direct skill names
            "Employee Competencies Rating",      # Path 2: proficiency levels
            "CV Employee Work Experience",       # Path 3: applied skills
            "Employee Achievements",             # Path 3: demonstrated skills
            "CV Employee Summary",               # Path 4: professional profile
        ],
    },
    {
        "num": "15",
        "test_question": "What projects did Employee 982 work on compared to Employee 1177?",
        "pandasai_input": (
            "Find all project information for Employee ID 982 and Employee ID 1177. For "
            "each employee, show their name, employee ID, organizational unit/department, "
            "grade, and list ALL projects they have been involved in including project name, "
            "project role, start date, end date, and project status/description if available. "
            "Compare their project portfolios side by side."
        ),
        "key_columns": [
            "Employee Number", "Employee Name",
            "Employee Assignment History",        # project assignments
            "Employee Objectives",               # objective name = project name
            "Employee Achievements",             # comments reference projects
            "CV Employee Work Experience",       # projects in responsibilities
            "CV Employee Achievements and Awards", # project-related achievements
        ],
    },
    {
        "num": "16",
        "test_question": "Which skills do they have in common?",
        "pandasai_input": (
            "Find employees with IDs '0982' and '1177'. For each employee, return their "
            "name, employee ID, organizational unit, department, grade, and ALL their "
            "technical competencies/skills with competency ratings if available. Compare "
            "their skill sets side by side and identify any common skills they share."
        ),
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # Path 1: skill names
            "Employee Competencies Rating",      # Path 2: proficiency levels
            "CV Employee Work Experience",       # Path 3: applied skills
            "Employee Achievements",             # Path 3: demonstrated skills
            "CV Employee Summary",               # Path 4: professional profile
        ],
    },
    {
        "num": "19",
        "test_question": "Compare their education background.",
        "pandasai_input": (
            "Find education details for employees with IDs '0982' and '1177'. For each "
            "employee, return their name, employee ID, organizational unit, department, "
            "grade, and ALL education information including degree/certification name, "
            "field of study, institution/university name, start date, end date/graduation "
            "date, and any additional education-related fields available in the system. "
            "Compare their education backgrounds side by side."
        ),
        "key_columns": [
            "Employee Number", "Employee Name",
            "Employee Qualification",            # Path 1: degree, institute, GPA
            "CV Employee Education",             # Path 1: CV education records
        ],
    },
    {
        "num": "28",
        "test_question": "Average Salary of Senior Specialist in ADEO",
        "pandasai_input": (
            "Find all employees who have \"Senior Specialist\" in their job title or "
            "position. For each employee, show: Employee Name, Employee ID, Grade, "
            "Position Title, Department, Division, Organizational Unit, Years of Service, "
            "and any salary-related fields available in the system. Calculate the average "
            "salary across all Senior Specialists if salary data exists. Sort by years of "
            "service descending."
        ),
        "key_columns": ["Position Title", "Salary"],
    },
    {
        "num": "35",
        "test_question": "Who has the longest service in ADEO?",
        "pandasai_input": (
            "Find the employee(s) with the longest years of service/tenure at ADEO. "
            "Return Employee Name, Employee ID, Position Title, Grade, Department, "
            "Division, Organizational Unit, Date of Joining, Years of Service/Tenure "
            "(calculated), and Gender. Sort by tenure descending and show top 20 employees. "
            "Include the maximum tenure value found."
        ),
        "key_columns": ["Employee Name", "Date of Joining"],
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


def _register_agent(client: httpx.Client, semantic_model: dict) -> str:
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


def _chat_step1_only(
    client: httpx.Client,
    conversation_id: str,
    query: str,
) -> Dict[str, Any]:
    """Call POST /api/chat with step1_only=True and return the JSON response."""
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


def _check_key_columns(selected_names: List[str], key_columns: List[str]) -> Dict[str, bool]:
    """Check if key expected columns appear in the selection."""
    results = {}
    combined = " ".join(str(n) for n in selected_names).lower()
    for key_col in key_columns:
        key_lower = key_col.lower()
        found = key_lower in combined
        if not found:
            for name in selected_names:
                if key_lower in str(name).lower():
                    found = True
                    break
        results[key_col] = found
    return results


# ---------------------------------------------------------------------------
# Single question runner
# ---------------------------------------------------------------------------

_T0: float = 0.0


def _run_single_question(
    index: int,
    q: Dict,
    semantic_model: dict,
) -> Dict:
    """Register + chat (step1_only) for a single question."""
    num = q["num"]
    test_q = q["test_question"]
    pandasai_q = q["pandasai_input"]
    key_columns = q["key_columns"]
    label = f"Q{num}"

    offset = time.time() - _T0
    print(f"  {offset:6.1f}s  🚀 {label} starting: {test_q[:60]}...")

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        # Register
        try:
            t_start = time.time()
            conv_id = _register_agent(client, semantic_model)
            register_elapsed = time.time() - t_start
            offset = time.time() - _T0
            print(f"  {offset:6.1f}s  ✅ {label} registered: {conv_id[:8]}... ({register_elapsed:.1f}s)")
        except Exception as e:
            offset = time.time() - _T0
            print(f"  {offset:6.1f}s  ❌ {label} register failed: {e}")
            return {
                "num": num, "test_question": test_q, "status": "register_failed",
                "error": str(e), "key_columns": key_columns,
            }

        # Chat (step1_only)
        try:
            t_start = time.time()
            response = _chat_step1_only(client, conv_id, pandasai_q)
            chat_elapsed = time.time() - t_start
            sel = response.get("selected_columns") or []
            offset = time.time() - _T0
            print(f"  {offset:6.1f}s  ✅ {label} step1 done ({chat_elapsed:.1f}s, {len(sel)} cols selected)")

            return {
                "num": num,
                "test_question": test_q,
                "pandasai_input": pandasai_q,
                "conversation_id": conv_id,
                "status": "completed",
                "chat_elapsed_seconds": round(chat_elapsed, 2),
                "register_elapsed_seconds": round(register_elapsed, 2),
                "key_columns": key_columns,
                # ── Column selection results (verbatim) ──
                "selected_columns": sel,
                "selected_count": len(sel),
                "retrieval_mode": response.get("retrieval_mode"),
                "retrieval_mode_reasoning": response.get("retrieval_mode_reasoning"),
                # ── Pipeline trace (raw LLM data) ──
                "pipeline": response.get("pipeline", {}),
            }
        except Exception as e:
            chat_elapsed = time.time() - t_start
            offset = time.time() - _T0
            print(f"  {offset:6.1f}s  ❌ {label} chat failed ({chat_elapsed:.1f}s): {e}")
            return {
                "num": num, "test_question": test_q, "conversation_id": conv_id,
                "status": "chat_failed", "error": str(e),
                "chat_elapsed_seconds": round(chat_elapsed, 2),
                "register_elapsed_seconds": round(register_elapsed, 2),
                "key_columns": key_columns,
                "pipeline": {},
            }


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def _write_report(run_dir: Path, results: List[Dict], total_wall_time: float):
    """Write a comprehensive analysis report with verbatim LLM data."""
    report_path = run_dir / "step1_only_report.md"
    summary_path = run_dir / "summary.json"

    # ── Build summary ──
    total_key_cols = 0
    found_key_cols = 0
    for r in results:
        if "error" in r and r.get("status") in ("register_failed", "chat_failed"):
            continue
        key_cols = r.get("key_columns", [])
        selected = r.get("selected_columns") or []
        check = _check_key_columns(selected, key_cols)
        total_key_cols += len(key_cols)
        found_key_cols += sum(1 for v in check.values() if v)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Step 1 Only — Column Selection Analysis Report\n\n")
        f.write(f"**Timestamp:** {datetime.utcnow().isoformat()}Z\n")
        f.write(f"**Total Wall Time:** {total_wall_time:.1f}s\n")
        f.write(f"**Workers:** {MAX_WORKERS}\n")
        f.write(f"**Key Columns Found:** {found_key_cols}/{total_key_cols}\n\n")

        # ── Summary Table ──
        f.write("## Summary Table\n\n")
        f.write("| # | Question | Time | Selected | Key Cols | Status |\n")
        f.write("|---|----------|------|----------|----------|--------|\n")
        for r in results:
            if r.get("status") in ("register_failed", "chat_failed"):
                f.write(f"| {r['num']} | {r['test_question'][:40]}... | - | - | - | ❌ {r['status']} |\n")
                continue
            key_cols = r.get("key_columns", [])
            selected = r.get("selected_columns") or []
            check = _check_key_columns(selected, key_cols)
            key_ok = "✅" if all(check.values()) else "⚠️"
            elapsed = r.get("chat_elapsed_seconds", 0)
            f.write(
                f"| {r['num']} | {r['test_question'][:40]}... | {elapsed}s | "
                f"{len(selected)} | {key_ok} | {'✅' if all(check.values()) else '⚠️'} |\n"
            )
        f.write("\n")

        # ── Detailed Per-Query Analysis ──
        f.write("---\n\n## Detailed Per-Query Analysis\n\n")
        for r in results:
            f.write(f"### Q{r['num']}: {r['test_question']}\n\n")

            if r.get("status") in ("register_failed", "chat_failed"):
                f.write(f"**Status:** ❌ {r['status']}\n\n")
                f.write(f"**Error:** {r.get('error', 'unknown')}\n\n")
                continue

            pipeline = r.get("pipeline", {})
            selected = r.get("selected_columns") or []
            key_cols = r.get("key_columns", [])
            check = _check_key_columns(selected, key_cols)

            # ── Key columns check ──
            f.write("**Key Columns Check:**\n\n")
            for kc, found in check.items():
                icon = "✅" if found else "❌"
                f.write(f"- {icon} `{kc}`\n")
            f.write("\n")

            # ── Selected columns ──
            f.write(f"**Selected Columns** ({len(selected)}):\n\n")
            for col in selected:
                f.write(f"- `{col}`\n")
            f.write("\n")

            # ── Column Selection Prompt (verbatim) ──
            prompt = pipeline.get("column_selection_prompt", "")
            if prompt:
                f.write("<details>\n<summary>📋 Column Selection Prompt (click to expand)</summary>\n\n")
                f.write(f"```\n{prompt}\n```\n\n")
                f.write("</details>\n\n")

            # ── Raw LLM Response (verbatim) ──
            raw_response = pipeline.get("column_selection_raw_llm_response", "")
            if raw_response:
                f.write("<details>\n<summary>🤖 Raw LLM Response (click to expand)</summary>\n\n")
                f.write(f"```json\n{raw_response}\n```\n\n")
                f.write("</details>\n\n")

            # ── Column Selection Log (step-by-step) ──
            col_log = pipeline.get("column_selection_log", [])
            if col_log:
                f.write("**Column Selection Log:**\n\n")
                f.write("| Step | Detail |\n")
                f.write("|------|--------|\n")
                for entry in col_log:
                    step = entry.get("step", "")
                    detail = str(entry.get("detail", ""))
                    if len(detail) > 300:
                        detail = detail[:300] + "..."
                    f.write(f"| {step} | {detail} |\n")
                f.write("\n")

            # ── Trimmed DataFrame Info ──
            trimmed_info = pipeline.get("trimmed_df_info", [])
            if trimmed_info:
                f.write("**Trimmed DataFrame Info:**\n\n")
                for info in trimmed_info:
                    idx = info.get("df_index", "?")
                    orig_schema = info.get("original_schema_names", [])
                    trim_schema = info.get("trimmed_schema_names", [])
                    f.write(f"- DF[{idx}]: {len(orig_schema)} → {len(trim_schema)} schema names\n")
                    f.write(f"  - Trimmed schema: `{trim_schema}`\n\n")

            # ── Retrieval Mode ──
            ret_mode = r.get("retrieval_mode")
            if ret_mode:
                f.write(f"**Retrieval Mode:** `{ret_mode}`\n\n")
                ret_reasoning = r.get("retrieval_mode_reasoning")
                if ret_reasoning:
                    f.write(f"**Retrieval Mode Reasoning:** {ret_reasoning}\n\n")

            f.write("---\n\n")

    # ── Write summary JSON ──
    summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "total_wall_time_seconds": round(total_wall_time, 2),
        "max_workers": MAX_WORKERS,
        "total_key_columns": total_key_cols,
        "found_key_columns": found_key_cols,
        "results": [],
    }
    for r in results:
        entry = {
            "num": r["num"],
            "test_question": r["test_question"],
            "status": r.get("status", "unknown"),
            "selected_columns": r.get("selected_columns"),
            "selected_count": r.get("selected_count", 0),
            "key_columns": r.get("key_columns", []),
            "key_columns_check": _check_key_columns(
                r.get("selected_columns") or [], r.get("key_columns", [])
            ) if r.get("selected_columns") else {},
            "chat_elapsed_seconds": r.get("chat_elapsed_seconds"),
            "retrieval_mode": r.get("retrieval_mode"),
            "retrieval_mode_reasoning": r.get("retrieval_mode_reasoning"),
            "raw_llm_response": r.get("pipeline", {}).get("column_selection_raw_llm_response", ""),
            "column_selection_prompt_lines": len(
                (r.get("pipeline", {}).get("column_selection_prompt", "") or "").splitlines()
            ),
        }
        summary["results"].append(entry)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _T0

    # Apply question filter
    questions = TEST_QUESTIONS[:]
    if QUESTION_FILTER:
        allowed = set(q.strip() for q in QUESTION_FILTER.split(","))
        questions = [q for q in questions if q["num"] in allowed]
        print(f"Filtering to questions: {allowed}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPORTS_DIR / f"{timestamp}_step1_only"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Step 1 Only — Column Selection E2E Test")
    print("=" * 70)
    print(f"Server:   {BASE_URL}")
    print(f"CSV:      {CSV_FILE}")
    print(f"Model:    {SEMANTIC_MODEL_FILE}")
    print(f"Output:   {run_dir}")
    print(f"Workers:  {MAX_WORKERS}")
    print(f"Questions: {len(questions)}")
    print(f"step1_only: True (no code generation)")
    print()

    # Verify files exist
    for f in [CSV_FILE, SEMANTIC_MODEL_FILE]:
        if not f.exists():
            print(f"❌ File not found: {f}")
            return
        print(f"✅ Found: {f.name}")

    # Verify server is running
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=10)
        print(f"✅ Server is running (status {resp.status_code})")
    except Exception as e:
        print(f"❌ Server not reachable at {BASE_URL}: {e}")
        return

    # Load data
    semantic_model = _load_semantic_model(SEMANTIC_MODEL_FILE)

    # Run queries
    _T0 = time.time()
    results: List[Dict] = []

    if MAX_WORKERS <= 1:
        # Sequential execution
        for i, q in enumerate(questions):
            result = _run_single_question(i, q, semantic_model)
            results.append(result)
    else:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for i, q in enumerate(questions):
                future = executor.submit(_run_single_question, i, q, semantic_model)
                futures[future] = q["num"]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)

    total_wall_time = time.time() - _T0

    # Sort results by question number
    def _sort_key(r):
        try:
            return float(r["num"])
        except ValueError:
            return 999
    results.sort(key=_sort_key)

    # Write report
    report_path = _write_report(run_dir, results, total_wall_time)

    # Print summary
    print("\n" + "=" * 70)
    total_key = 0
    found_key = 0
    for r in results:
        if r.get("status") not in ("register_failed", "chat_failed"):
            key_cols = r.get("key_columns", [])
            selected = r.get("selected_columns") or []
            check = _check_key_columns(selected, key_cols)
            total_key += len(key_cols)
            found_key += sum(1 for v in check.values() if v)
            icon = "✅" if all(check.values()) else "⚠️"
            missing = [k for k, v in check.items() if not v]
            missing_str = f" missing: {missing}" if missing else ""
            print(f"  Q{r['num']}: {icon} {len(selected)} cols{missing_str}")

    print(f"\n  Key columns found: {found_key}/{total_key}")
    print(f"  Wall time: {total_wall_time:.1f}s")
    print(f"  Report: {report_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
