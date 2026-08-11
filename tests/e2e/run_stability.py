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

    # Bypass server-side response caching: append a subtle punctuation variant
    # to each run's query so the LLM sees a (slightly) different prompt and can't
    # return a cached identical response.  The variation is word/meaning-neutral.
    python tests/e2e/run_stability.py --question Q19 --runs 5 --no-cache

Prerequisites:
    - Server running locally (make -f Makefile.build run-local)
    - .env configured
"""

# Tiny punctuation suffixes to defeat prompt-level response caching without
# changing the query's meaning.  Each run gets a different suffix.
_CACHE_BUST_SUFFIXES = [
    "",
    ".",
    "  ",
    ":",
    " .",
    "  .",
]

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
    "Q13b": (
        "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar "
        "Asad) in the year 2025. Count total number of sick leave days taken, "
        "list each leave record with start date, end date, and duration. Also "
        "include employee name and department if available."
    ),
    "Q13c": (
        "Count total sick leave days taken by employee 1136 (Dr. Rahila Babar "
        "Asad) in 2025. Also list individual leave records showing leave type, "
        "start date, end date, and duration in days for any sick leaves in 2025. "
        "Include employee name if available."
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
    # Additional question types that historically required retries
    "R1_leave_explore": (
        "Check what leave-related columns exist in the dataset by listing "
        "distinct columns that contain 'Leave' in their name or show sample "
        "records with leave information for any employee. Then search for sick "
        "leave records specifically for employee 1136 in year 2025, counting "
        "total days and listing individual leave dates if available."
    ),
    "R2_human_capital": (
        "List all employees working in the Human Capital Department. For each "
        "employee, show: Employee Name, Employee ID, Organizational "
        "Unit/Section, Grade, Date of Joining, Years of Service/Tenure, and "
        "Division. Sort by employee ID ascending. Include total count at the "
        "end."
    ),
    "R3_senior_specialist_sorted": (
        "Find all employees who have \"Senior Specialist\" in their job title "
        "or position. For each employee, show: Employee Name, Employee ID, "
        "Grade, Position, Department, Division, Organizational Unit, Years of "
        "Service, and any salary-related fields available in the system (such "
        "as Salary Amount, Basic Salary, Total Compensation, Salary Band, Pay "
        "Grade, or similar compensation data). Calculate the average salary "
        "across all Senior Specialists if salary data exists. Sort by years of "
        "service descending."
    ),
    "R4_longest_tenure": (
        "Find the employee(s) with the longest years of service/tenure at ADEO. "
        "Return Employee Name, Employee ID, Position, Grade, Department, "
        "Division, Organizational Unit, Date of Joining, Years of Service/Tenure "
        "(calculated), and Gender. Sort by tenure descending and show top 20 "
        "employees. Include the maximum tenure value found."
    ),
    "R5_chinese_ai": (
        "Find all employees who have BOTH Chinese language skills AND any "
        "AI-related competency (including Artificial Intelligence, AI "
        "Implementation, AI Integration, Machine Learning, Deep Learning, "
        "Python, or similar AI/ML skills). For each employee show: Employee "
        "Name, Employee ID, Organizational Unit/Section, Department, Grade, "
        "Date of Joining, Years of Service, and list all their Chinese "
        "language skills and AI-related competencies."
    ),
    "R6_emp1137_skills": (
        "Find employee with ID 1137. Return their name, employee ID, and all "
        "their technical competencies/skills from the CV data. List each skill "
        "name."
    ),
    "R7_ec_committees": (
        "Find all employees working in the EC and Committees Affairs "
        "Department. For each employee, show: Employee Name, Employee ID, "
        "Organizational Unit/Section, Grade, Date of Joining, Years of "
        "Service/Tenure, and Gender. Sort by employee ID ascending. Include "
        "total count at the end with breakdown by gender if available."
    ),
    "R8_director_general": (
        "Find all employees who have the role of Director General (DG) in "
        "Strategic Affairs Division. Search for any position/title containing "
        "\"Director General\", \"DG\", or \"Strategic Affairs\" that indicates "
        "leadership of the Strategic Affairs Division. For each employee show: "
        "Employee Name, Employee ID, Position, Grade, Organizational "
        "Unit/Division, Department, Date of Joining, Years of Service/Tenure, "
        "and Reporting Line if available. Sort by grade seniority."
    ),
    "R9_emp982_1177_skills": (
        "Find employees with IDs '0982' and '1177'. For each employee, return "
        "their name, employee ID, organizational unit, department, grade, and "
        "ALL their technical competencies/skills with competency ratings if "
        "available. Compare their skill sets side by side and identify any "
        "common skills they share."
    ),
    "R10_leadership_positions": (
        "Find all employees with leadership positions including Chairman, "
        "Secretary General, Director General, DG, Executive Director, ED, "
        "Director, Head of Section, or any senior management title. For each "
        "employee show: Employee Name, Employee ID, Position, Grade, "
        "Organizational Unit, Department, Division, Reporting Line "
        "(Supervisor), Date of Joining, Years of Service/Tenure, and Gender. "
        "Sort by grade seniority (highest leadership first). Count total "
        "leadership roles found."
    ),
    "R11_projects_982_1177": (
        "Find all project information for Employee ID 982 and Employee ID 1177. "
        "For each employee, show their name, employee ID, organizational "
        "unit/department, grade, and list ALL projects they have been involved "
        "in including project name, project role, start date, end date, and "
        "project status/description if available. Compare their project "
        "portfolios side by side."
    ),
    "R12_compare_edu_0982_1177": (
        "Compare the education background of employees 0982 and 1177."
    ),
    "R13_sick_1136": (
        "How many sick leave days did employee 1136 take in 2025?"
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


def run_stability(
    query: str,
    runs: int = 5,
    question_id: Optional[str] = None,
    no_cache: bool = False,
) -> None:
    if not query and question_id not in STABILITY_QUESTIONS:
        print(f"❌ Unknown question {question_id}. Choose from {list(STABILITY_QUESTIONS)}")
        return

    label = question_id or "custom"
    base_query = query or STABILITY_QUESTIONS[question_id]

    semantic_model = _load_semantic_model(SEMANTIC_MODEL_FILE)
    print(f"Server: {BASE_URL}")
    print(f"Question: {label}")
    print(f"Runs: {runs}")
    print(f"Cache-bypass: {'ON' if no_cache else 'OFF'}")
    print(f"Query: {base_query[:120]}...")
    print("=" * 70)

    results = []
    types = {}
    with httpx.Client(timeout=300) as client:
        for i in range(1, runs + 1):
            # If cache-bypass is on, append a distinct punctuation suffix to
            # each run so the prompt differs slightly and the backend can't
            # return a cached identical response.  Meaning-neutral.
            if no_cache:
                suffix = _CACHE_BUST_SUFFIXES[(i - 1) % len(_CACHE_BUST_SUFFIXES)]
                query = base_query + suffix
            else:
                query = base_query
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
                    "cache_bust_suffix": suffix if no_cache else None,
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
    parser.add_argument("--no-cache", action="store_true", help="Append punctuation variant to bypass server-side response caching")
    args = parser.parse_args()
    run_stability(args.query, args.runs, args.question, no_cache=args.no_cache)