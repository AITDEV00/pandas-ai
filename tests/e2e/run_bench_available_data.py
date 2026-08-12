"""Run all stability questions against the running pandas-ai server using
run/File (4).xlsx + run/semantic_model.json, at max concurrency 5, with cache
busting enabled. Reports per-question latency and the code-execution answer.

Usage:
    .venv-uv/bin/python tests/e2e/run_bench_available_data.py
"""
import argparse
import base64
import concurrent.futures
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BASE_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
DATA_FILE = PROJECT_ROOT / "run" / "File (4).xlsx"
SEMANTIC_MODEL_FILE = PROJECT_ROOT / "run" / "semantic_model.json"

PANDASAI_CONFIG = {
    "enrich_column_values": False,
    "auto_fill_descriptions": False,
    "column_selection_temperature": 0.0,
    "column_selection_use_instructor": True,
    "column_selection_json_mode": False,
    "code_generation_temperature": float(os.environ.get("CODE_GENERATION_TEMPERATURE", "0.0")),
    "code_generation_max_tokens": int(os.environ.get("CODE_GENERATION_MAX_TOKENS", "10000")),
    "column_selection_max_tokens": int(os.environ.get("COLUMN_SELECTION_MAX_TOKENS", "10000")),
    "code_generation_use_instructor": os.environ.get("CODE_GENERATION_USE_INSTRUCTOR", "true").lower() == "true",
}

# Full 19Q bank (6 Q + 13 R) — same as run_stability.py
STABILITY_QUESTIONS = {
    "Q13a": "How many sick leaves did employee 1136 take in 2025? Count total sick leave days and list each record with dates.",
    "Q13b": "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) in the year 2025. Count total number of sick leave days taken, list each leave record with start date, end date, and duration. Also include employee name and department if available.",
    "Q13c": "Count total sick leave days taken by employee 1136 (Dr. Rahila Babar Asad) in 2025. Also list individual leave records showing leave type, start date, end date, and duration in days for any sick leaves in 2025. Include employee name if available.",
    "Q19": "Find education details for employees with IDs '0982' and '1177'. For each employee, return name, employee ID, organizational unit, department, grade, and ALL education information including degree/certification name, field of study, institution, start date, end date. Compare their education backgrounds side by side.",
    "Q28": "Find all employees who have 'Senior Specialist' in their job title or position. For each employee, show Employee Name, Employee ID, Grade, Position Title, Department, Division, Organizational Unit, Years of Service, and any salary-related fields. Calculate the average salary of these employees.",
    "Q30": "What are the leadership roles in ADEO? Find employees with management/leadership titles and list their roles.",
    "R1_leave_explore": "Check what leave-related columns exist in the dataset by listing distinct columns that contain 'Leave' in their name or show sample records with leave information for any employee. Then search for sick leave records specifically for employee 1136 in year 2025, counting total days and listing individual leave dates if available.",
    "R2_human_capital": "List all employees working in the Human Capital Department. For each employee, show: Employee Name, Employee ID, Organizational Unit/Section, Grade, Date of Joining, Years of Service/Tenure, and Division. Sort by employee ID ascending. Include total count at the end.",
    "R3_senior_specialist_sorted": "Find all employees who have \"Senior Specialist\" in their job title or position. For each employee, show: Employee Name, Employee ID, Grade, Position, Department, Division, Organizational Unit, Years of Service, and any salary-related fields. Calculate the average salary across all Senior Specialists if salary data exists. Sort by years of service descending.",
    "R4_longest_tenure": "Find the employee(s) with the longest years of service/tenure at ADEO. Return Employee Name, Employee ID, Position, Grade, Department, Division, Organizational Unit, Date of Employment, Years of Service/Tenure (calculated), and Gender. Sort by tenure descending and show top 20 employees. Include the maximum tenure value found.",
    "R5_chinese_ai": "Find all employees who have BOTH Chinese language skills AND any AI-related competency (including Artificial Intelligence, AI Implementation, AI Integration, Machine Learning, Deep Learning, Python, or similar AI/ML skills). For each employee show: Employee Name, Employee ID, Organizational Unit/Section, Department, Grade, Date of Employment, Years of Service, and list all their Chinese language skills and AI-related competencies.",
    "R6_emp1137_skills": "Find employee with ID 1137. Return their name, employee ID, and all their technical competencies/skills from the CV data. List each skill name.",
    "R7_ec_committees": "Find all employees working in the EC and Committees Affairs Department. For each employee, show: Employee Name, Employee ID, Organizational Unit/Section, Grade, Date of Employment, Years of Service/Tenure, and Gender. Sort by employee ID ascending. Include total count at the end with breakdown by gender if available.",
    "R8_director_general": "Find all employees who have the role of Director General (DG) in Strategic Affairs Division. Search for any position/title containing \"Director General\", \"DG\", or \"Strategic Affairs\" that indicates leadership of the Strategic Affairs Division. For each employee show: Employee Name, Employee ID, Position, Grade, Organizational Unit/Division, Department, Date of Employment, Years of Service/Tenure, and Reporting Line if available. Sort by grade seniority.",
    "R9_emp982_1177_skills": "Find employees with IDs '0982' and '1177'. For each employee, return their name, employee ID, organizational unit, department, grade, and ALL their technical competencies/skills with competency ratings if available. Compare their skill sets side by side and identify any common skills they share.",
    "R10_leadership_positions": "Find all employees with leadership positions including Chairman, Secretary General, Director General, DG, Executive Director, ED, Director, Head of Section, or any senior management title. For each employee show: Employee Name, Employee ID, Position, Grade, Organizational Unit, Department, Division, Reporting Line (Supervisor), Date of Employment, Years of Service/Tenure, and Gender. Sort by grade seniority (highest leadership first). Count total leadership roles found.",
    "R11_projects_982_1177": "Find all project information for Employee ID 982 and Employee ID 1177. For each employee, show their name, employee ID, organizational unit/department, grade, and list ALL projects they have been involved in including project name, project role, start date, end date, and project status/description if available. Compare their project portfolios side by side.",
    "R12_compare_edu_0982_1177": "Compare the education background of employees 0982 and 1177.",
    "R13_sick_1136": "How many sick leave days did employee 1136 take in 2025?",
}

# Punctuation suffixes to bust server-side response caching per run (meaning-neutral).
_CACHE_BUST = ["", ".", "  ", ":", " .", "  ."]


def _load_xlsx_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + base64.b64encode(f.read()).decode()


def _register(client, semantic_model):
    payload = {
        "base64_data": _load_xlsx_base64(DATA_FILE),
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "semantic_model": semantic_model,
        "pandasai_config": PANDASAI_CONFIG,
    }
    r = client.post(f"{BASE_URL}/api/register/base64", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()["conversation_id"]


def _chat(client, conv_id, query):
    payload = {
        "conversation_id": conv_id,
        "query": query,
        "output_type": "string",
        "column_selection_enabled": True,
        "column_selection_threshold": 30,
        "column_values_budget_ratio": 0.10,
    }
    r = client.post(f"{BASE_URL}/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


def run_one(qid, query, semantic_model):
    out = {"question": qid, "query": query}
    cache_buster = os.environ.get("CODEGEN_CACHE_BUSTER", "")
    q = f"{query}\n<!-- stability:{cache_buster} -->" if cache_buster else query
    with httpx.Client(timeout=600) as client:
        t0 = time.time()
        try:
            conv_id = _register(client, semantic_model)
            reg_s = round(time.time() - t0, 1)
            t1 = time.time()
            resp = _chat(client, conv_id, q)
            chat_s = round(time.time() - t1, 1)
            out.update({
                "status": "completed",
                "register_s": reg_s,
                "chat_s": chat_s,
                "total_s": round(time.time() - t0, 1),
                "type": resp.get("type"),
                "response": str(resp.get("response"))[:3000] if resp.get("response") else None,
                "selected_columns_count": len(resp.get("selected_columns") or []),
                "error": resp.get("error"),
            })
        except Exception as e:
            out.update({"status": "failed", "total_s": round(time.time() - t0, 1), "error": str(e)})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--questions", default="", help="comma list to filter, e.g. Q13,R6")
    args = parser.parse_args()

    semantic_model = json.load(open(SEMANTIC_MODEL_FILE, encoding="utf-8"))
    # Drop model columns not present in the Excel to avoid schema/source mismatch.
    import pandas as pd
    df = pd.read_excel(DATA_FILE)
    excel_cols = set(df.columns)
    semantic_model["columns"] = [c for c in semantic_model["columns"] if c["name"] in excel_cols]
    # The server only supports csv/parquet source types; the data is uploaded
    # directly (base64), so source is informational. Use csv to match the schema.
    semantic_model["source"] = {"type": "csv", "path": str(DATA_FILE)}

    if args.questions:
        filt = {p.strip() for p in args.questions.split(",") if p.strip()}
        # Allow matching by exact key OR short prefix (e.g. "R6" matches R6_emp1137_skills)
        qs = {k: v for k, v in STABILITY_QUESTIONS.items() if k in filt or any(k.startswith(p) for p in filt)}
    else:
        qs = dict(STABILITY_QUESTIONS)

    out_dir = PROJECT_ROOT / "run" / "e2e_reports" / "bench_available_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = out_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Server: {BASE_URL}")
    print(f"Data: {DATA_FILE} ({len(excel_cols)} cols) + {len(semantic_model['columns'])} schema cols")
    print(f"Questions: {len(qs)} | concurrency: {args.concurrency}")
    print(f"Cache buster: {'ON' if os.environ.get('CODEGEN_CACHE_BUSTER') else 'OFF'}")
    print(f"Output: {run_dir}\n")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        fut = {ex.submit(run_one, qid, q, semantic_model): qid for qid, q in qs.items()}
        for f in concurrent.futures.as_completed(fut):
            r = f.result()
            results.append(r)
            print(f"  [{r['question']:>24}] {r['status']:9} type={r.get('type')} total={r.get('total_s')}s  {str(r.get('response'))[:90]}", flush=True)

    results.sort(key=lambda r: r["question"])
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    ok = [r for r in results if r["status"] == "completed"]
    print("\n" + "=" * 90)
    print(f"SUMMARY — {len(ok)}/{len(results)} completed")
    print("=" * 90)
    if ok:
        tot = [r["total_s"] for r in ok]
        print(f"Latency:  min={min(tot)}s  avg={round(sum(tot)/len(tot),1)}s  max={max(tot)}s")
    print(f"Output:   {run_dir}")


if __name__ == "__main__":
    main()