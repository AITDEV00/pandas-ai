"""Step 1 Column Selection E2E Test — NEW QUERIES (v24 vs v31g comparison)

This script uses the same parallel execution infrastructure as test_step1_parallel.py
but with 8 BRAND NEW test queries that neither v24 nor v31g has seen before.

The queries are designed to stress-test:
1. Struct column selection reliability (the main weakness)
2. Different query phrasings for common concepts
3. Edge cases in the schema (leave details, performance, previous employer)
4. Mixed flat + struct requirements

Usage:
  source .venv/bin/activate

  # With current template (whatever select_columns_v31.tmpl points to):
  COLUMN_SELECTION_TEMPERATURE=0.6 python tests/e2e/test_step1_new_queries.py

  # To compare: swap template in select_columns.py, re-run
"""

import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "run" / "e2e_reports")))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"

COLUMN_SELECTION_THRESHOLD = 30
COLUMN_VALUES_BUDGET_RATIO = 0.10

PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
    # Column selection sampling ONLY temperature 0.0 (others default)
    "column_selection_temperature": 0.0,
    "column_selection_json_mode": True,
}

MAX_WORKERS = int(os.environ.get("STEP1_PARALLEL_WORKERS", "10"))

# ---------------------------------------------------------------------------
# NEW Test Questions — Never seen by v24 or v31g
# ---------------------------------------------------------------------------

NEW_TEST_QUESTIONS: List[Dict] = [
    {
        "num": "N1",
        "test_question": "Show me the complete career history of employee 2451",
        "pandasai_input": (
            "Show me the complete career history of employee 2451. "
            "Include their name, current position and grade, department and organization unit, "
            "date of joining, all past assignments with position titles and dates, "
            "previous employers with job titles and dates, and their CV work experience "
            "with company names, job titles, and responsibilities."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Employee Number", "Employee Name", "Employee Assignment History",
                        "Employee Previous Employer", "CV Employee Work Experience"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Position Title", "Employee Grade",
            "Department", "Organization Unit", "Date of Joining",
            "Employee Assignment History", "Employee Previous Employer",
            "CV Employee Work Experience",
        ],
        "rationale": "Career history = assignments + previous employers + CV work experience. All three struct groups needed.",
    },
    {
        "num": "N2",
        "test_question": "What are the qualifications and certifications held by employees in the IT department?",
        "pandasai_input": (
            "List all employees in the IT or Data and Digital Innovation Department. "
            "For each employee, show their name, employee ID, grade, and ALL their "
            "qualifications including degree titles, educational institutions, GPA, "
            "and study dates. Also include their CV education entries with institution "
            "names, degree names, and dates. Include their flat education fields "
            "(degree, major, educational institute, graduation date) as well."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Department", "Employee Number", "Employee Name",
                        "Employee Qualification", "CV Employee Education"],
        "expected_columns": [
            "Department", "Employee Number", "Employee Name", "Employee Grade",
            "Degree", "Major (Education)", "Educational Institute", "Graduation Date",
            "Employee Qualification", "CV Employee Education",
        ],
        "rationale": "Qualifications = Employee Qualification struct + CV Education struct + flat education fields. Tests education-related struct selection.",
    },
    {
        "num": "N3",
        "test_question": "Compare the performance of employees 982 and 1177",
        "pandasai_input": (
            "Compare the performance of employees with IDs 982 and 1177. "
            "For each employee, show their name, employee ID, department, grade, "
            "and ALL performance-related data including: performance review ratings, "
            "objectives with their status and weighting, achievements with manager "
            "and employee comments, and competency ratings with both employee and "
            "supervisor scores."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Employee Number", "Employee Name", "Employee Performance",
                        "Employee Objectives", "Employee Achievements",
                        "Employee Competencies Rating"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Department", "Employee Grade",
            "Employee Performance", "Employee Objectives", "Employee Achievements",
            "Employee Competencies Rating",
        ],
        "rationale": "Performance = Employee Performance struct + Objectives struct + Achievements struct + Competency Ratings struct. 4 struct groups needed — heavy struct test.",
    },
    {
        "num": "N4",
        "test_question": "Which employees have taken leave this month?",
        "pandasai_input": (
            "Find all employees who have taken any type of leave in the current month. "
            "For each employee, show their name, employee ID, department, organization unit, "
            "and ALL leave details including leave type, duration, approval status, "
            "start date, and end date."
        ),
        "expected_breadth": "moderate",
        "key_columns": ["Employee Number", "Employee Name", "Employee Leave Details"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Department", "Organization Unit",
            "Employee Leave Details",
        ],
        "rationale": "Leave query — only 1 struct group needed (Employee Leave Details). Should be easy but tests whether LLM includes the struct at all.",
    },
    {
        "num": "N5",
        "test_question": "Give me a full profile of employee 1333",
        "pandasai_input": (
            "Provide a comprehensive profile of employee ID 1333. Include their name, "
            "employee ID, department, division, organization unit, grade, position title, "
            "date of joining, assignment status, and ALL available details about their: "
            "skills and competencies (including ratings), work experience and responsibilities, "
            "education and qualifications, objectives and goals, achievements and awards, "
            "and professional summary."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Employee Number", "Employee Name", "CV Employee Competencies",
                        "CV Employee Work Experience", "CV Employee Education",
                        "Employee Objectives", "Employee Achievements",
                        "CV Employee Summary"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Department", "Division",
            "Organization Unit", "Employee Grade", "Position Title", "Date of Joining",
            "Assignment Status", "CV Employee Competencies", "Employee Competencies Rating",
            "CV Employee Work Experience", "CV Employee Education",
            "Employee Qualification", "Employee Objectives", "Employee Achievements",
            "CV Employee Achievements and Awards", "CV Employee Summary",
        ],
        "rationale": "Full profile = nearly ALL struct groups. The broadest possible query. Tests whether the LLM includes everything when told to be comprehensive.",
    },
    {
        "num": "N6",
        "test_question": "List employees who have worked at more than one company before joining ADEO",
        "pandasai_input": (
            "Find all employees who have had previous employment before joining ADEO. "
            "For each employee, show their name, employee ID, current department, "
            "date of joining ADEO, and ALL previous employer details including "
            "company name, job title, start date, and end date. Also include their "
            "CV work experience entries for additional context."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Employee Number", "Employee Name", "Employee Previous Employer",
                        "CV Employee Work Experience"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Department", "Date of Joining",
            "Employee Previous Employer", "CV Employee Work Experience",
        ],
        "rationale": "Previous employment = Employee Previous Employer struct + CV Employee Work Experience struct. Two related but different struct groups.",
    },
    {
        "num": "N7",
        "test_question": "What objectives and goals have been set for employee 1137?",
        "pandasai_input": (
            "Show all objectives and goals for employee ID 1137. Include their name, "
            "employee ID, department, grade, and ALL objective details including "
            "objective name, goal plan name, objective description, goal weighting, "
            "goal status, objective status, and workflow state."
        ),
        "expected_breadth": "moderate",
        "key_columns": ["Employee Number", "Employee Name", "Employee Objectives"],
        "expected_columns": [
            "Employee Number", "Employee Name", "Department", "Employee Grade",
            "Employee Objectives",
        ],
        "rationale": "Objectives query — only 1 struct group needed. Tests whether the LLM includes Employee Objectives struct when explicitly asked.",
    },
    {
        "num": "N8",
        "test_question": "Show me the total compensation breakdown for senior employees",
        "pandasai_input": (
            "Find all employees with 'Senior' in their position title or grade. "
            "For each, show their name, employee ID, department, position title, grade, "
            "date of joining, and ALL salary and compensation data available including "
            "basic salary, total entitlement amount, and any other compensation fields. "
            "Also show their assignment status. Calculate the average total compensation."
        ),
        "expected_breadth": "moderate",
        "key_columns": ["Employee Name", "Employee Number", "Basic Salary",
                        "Total Entitlement Amount", "Assignment Status"],
        "expected_columns": [
            "Employee Name", "Employee Number", "Department", "Position Title",
            "Employee Grade", "Grade", "Date of Joining", "Basic Salary",
            "Total Entitlement Amount", "Assignment Status",
        ],
        "rationale": "Compensation query — mostly flat columns. Tests Rule 11 (redundant breakdowns). Should select Total Entitlement Amount and Basic Salary but NOT individual allowance breakdowns.",
    },
]


# ---------------------------------------------------------------------------
# Registration (copied from test_step1_parallel.py)
# ---------------------------------------------------------------------------

def _register_agent_with_data():
    """Register an Agent with the enterprise HC dataset."""
    import pandasai as pai
    from pandasai import Agent
    from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
    from pandasai.helpers.type_determination import (
        parse_json_array_columns,
        is_list_struct_column,
    )
    from pandasai.helpers.semantic_matching import (
        get_matching_schema_columns,
        merge_descriptions,
    )
    from pandasai.data_loader.semantic_layer_schema import Column as SchemaColumn
    from pandasai.config import ConfigManager

    print(f"  📂 Reading CSV: {CSV_FILE.name}")
    df = pai.read_csv(str(CSV_FILE))

    parse_json_array_columns(df)

    print(f"  📋 Applying semantic model: {SEMANTIC_MODEL_FILE.name}")
    with open(SEMANTIC_MODEL_FILE, "r", encoding="utf-8") as f:
        semantic_model_dict = json.load(f)

    if "name" not in semantic_model_dict:
        semantic_model_dict["name"] = getattr(df, "_table_name", "uploaded_table")
    if "source" not in semantic_model_dict and "view" not in semantic_model_dict:
        semantic_model_dict["source"] = {"type": "csv", "path": str(CSV_FILE)}

    from pydantic import ValidationError
    try:
        validated_schema = SemanticLayerSchema(**semantic_model_dict)
        df.schema = validated_schema
    except ValidationError as e:
        print(f"  ❌ Semantic model validation failed: {e}")
        sys.exit(1)

    print("  🔧 Patching schema columns...")
    if df.schema and df.schema.columns:
        schema_by_name = {col.name: col for col in df.schema.columns}
        new_schema_columns = []
        inner_field_names_to_remove: set = set()

        for col_name in df.columns:
            series = df[col_name]
            is_struct = is_list_struct_column(series)
            exact_match = schema_by_name.get(col_name)

            if is_struct:
                if exact_match is not None:
                    if exact_match.type != "list[struct]":
                        exact_match.type = "list[struct]"
                        exact_match.semantic_type = "struct"
                    if PANDASAI_CONFIG["enrich_column_values"] and exact_match.samples is None:
                        from pandasai.helpers.column_enrichment import ColumnValueExtractor
                        result = ColumnValueExtractor.classify_and_extract(
                            series, "list[struct]",
                            PANDASAI_CONFIG.get("categorical_max_unique", 10),
                            df.schema,
                        )
                        if result["samples"] is not None:
                            exact_match.samples = result["samples"]
                        if result["semantic_type"] is not None and exact_match.semantic_type is None:
                            exact_match.semantic_type = result["semantic_type"]
                else:
                    matches = get_matching_schema_columns(col_name, df.schema)
                    merged_desc = merge_descriptions(matches) if matches else None
                    for m in matches:
                        inner_field_names_to_remove.add(m.name)

                    samples = None
                    if PANDASAI_CONFIG["enrich_column_values"]:
                        from pandasai.helpers.column_enrichment import ColumnValueExtractor
                        result = ColumnValueExtractor.classify_and_extract(
                            series, "list[struct]",
                            PANDASAI_CONFIG.get("categorical_max_unique", 10),
                            df.schema,
                        )
                        samples = result.get("samples")

                    new_col = SchemaColumn(
                        name=col_name,
                        type="list[struct]",
                        semantic_type="struct",
                        samples=samples,
                        description=merged_desc,
                    )
                    new_schema_columns.append(new_col)
            else:
                if PANDASAI_CONFIG["enrich_column_values"] and exact_match is not None and exact_match.samples is None:
                    from pandasai.helpers.column_enrichment import ColumnValueExtractor
                    result = ColumnValueExtractor.classify_and_extract(
                        series, exact_match.type,
                        PANDASAI_CONFIG.get("categorical_max_unique", 10),
                        df.schema,
                    )
                    if result["samples"] is not None:
                        exact_match.samples = result["samples"]
                    if result["semantic_type"] is not None and exact_match.semantic_type is None:
                        exact_match.semantic_type = result["semantic_type"]

        if new_schema_columns or inner_field_names_to_remove:
            filtered = []
            for col in list(df.schema.columns) + new_schema_columns:
                if col.name in inner_field_names_to_remove:
                    continue
                filtered.append(col)
            df.schema.columns = filtered

    print("  🤖 Creating Agent...")
    global_config_obj = ConfigManager.get()
    agent_config = global_config_obj.model_dump()
    agent_config["llm"] = global_config_obj.llm
    agent_config.update(PANDASAI_CONFIG)

    agent = Agent([df], config=agent_config)
    print(f"  ✅ Agent created. DataFrame has {len(df.columns)} columns, {len(df)} rows")
    return agent


# ---------------------------------------------------------------------------
# Column Selection Runner (same as test_step1_parallel.py)
# ---------------------------------------------------------------------------

def _run_single_column_selection(agent, q: Dict) -> Dict[str, Any]:
    """Run column selection for a single question."""
    from pandasai.core.column_selector import ColumnSelector

    state = agent._state
    query = q["pandasai_input"]

    selector = ColumnSelector(state)
    prompt_obj = selector._build_prompt(query)
    prompt_text = str(prompt_obj)
    sampling_params = selector._get_sampling_params()

    t_start = time.time()
    response = state.config.llm.call(prompt_obj, state, sampling_params=sampling_params)
    elapsed = time.time() - t_start

    raw_response = response
    selected_names = selector._parse_response(response)
    selected_names = selector._validate_names(selected_names)

    df = state.dfs[0]
    matched = selector.match_names_to_schema(selected_names, df)
    matched = selector.ensure_essential_columns(matched, df, query)

    trimmed_df = selector.build_trimmed_dataframe(df, matched)

    trimmed_serialized = ""
    if trimmed_df is not None:
        try:
            trimmed_serialized = trimmed_df.serialize_dataframe(state.config)
        except Exception as e:
            trimmed_serialized = f"(serialization error: {e})"

    full_serialized = ""
    try:
        full_serialized = df.serialize_dataframe(state.config)
    except Exception as e:
        full_serialized = f"(serialization error: {e})"

    return {
        "num": q["num"],
        "test_question": q["test_question"],
        "query": query,
        "expected_breadth": q["expected_breadth"],
        "key_columns": q["key_columns"],
        "expected_columns": q.get("expected_columns", []),
        "rationale": q.get("rationale", ""),

        "prompt_text": prompt_text,
        "sampling_params": sampling_params,

        "raw_llm_response": raw_response,
        "elapsed_seconds": round(elapsed, 2),

        "selected_names": selected_names,
        "selected_count": len(selected_names),

        "matched_columns": {k: v for k, v in matched.items()},
        "matched_count": len(matched),

        "trimmed_df_columns": list(trimmed_df.columns) if trimmed_df is not None else [],
        "trimmed_df_column_count": len(trimmed_df.columns) if trimmed_df is not None else 0,

        "trimmed_serialized_preview": trimmed_serialized[:3000] if trimmed_serialized else "",
        "trimmed_serialized_length": len(trimmed_serialized),
        "full_serialized_length": len(full_serialized),
        "token_saving_pct": round(
            (1 - len(trimmed_serialized) / max(len(full_serialized), 1)) * 100, 1
        ) if full_serialized and trimmed_serialized else None,
    }


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
# Report Generation with Expected Column Comparison
# ---------------------------------------------------------------------------

def _write_analysis_report(run_dir: Path, results: List[Dict], timestamp: str,
                           total_wall_time: float, total_sequential_time: float,
                           template_name: str):
    """Write the comprehensive analysis report with expected column comparison."""
    report_path = run_dir / "step1_new_queries_report.md"

    # ---- Compute expected column recall ----
    total_expected = 0
    total_found = 0
    total_selected = 0
    per_question = []

    for r in results:
        if "error" in r:
            per_question.append({"num": r["num"], "found": 0, "expected": 0, "selected": 0, "missing": []})
            continue

        expected = set(r.get("expected_columns", []))
        # Extract base names from trimmed columns (strip bracket notation)
        selected_set = set()
        for col_name in r.get("selected_names", []):
            # Normalize: strip brackets, extract the meaningful name
            name = str(col_name)
            # e.g. "[Employee Master[Employee Number]]" → "Employee Number"
            # e.g. "[CV Employee Competencies[Technical Competency Name]]" → "CV Employee Competencies"
            if "[" in name:
                # Extract the struct group name (first part after outer [)
                parts = name.strip("[]").split("[")
                if len(parts) >= 2:
                    group_name = parts[0].strip()
                    selected_set.add(group_name)
                else:
                    selected_set.add(name.strip("[]"))
            else:
                selected_set.add(name)

        found = expected & selected_set
        missing = expected - selected_set

        per_question.append({
            "num": r["num"],
            "found": len(found),
            "expected": len(expected),
            "selected": len(r.get("selected_names", [])),
            "missing": sorted(missing),
            "pct": len(found) / max(len(expected), 1) * 100,
        })
        total_expected += len(expected)
        total_found += len(found)
        total_selected += len(r.get("selected_names", []))

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Step 1 Column Selection — NEW QUERIES ({template_name})\n\n")
        f.write(f"**Date:** {timestamp}\n")
        f.write(f"**Template:** {template_name}\n")
        f.write(f"**CSV:** `{CSV_FILE.name}`\n")
        f.write(f"**Questions:** {len(NEW_TEST_QUESTIONS)} (all new, never seen before)\n")
        f.write(f"**Total Wall Time:** {total_wall_time:.1f}s\n\n")

        # ================================================================
        # SUMMARY TABLE
        # ================================================================
        f.write("---\n\n")
        f.write("## 1. Summary\n\n")
        f.write(f"**Overall Recall: {total_found}/{total_expected} ({total_found/max(total_expected,1)*100:.1f}%)**\n")
        f.write(f"**Avg selected names per question:** {total_selected/max(len(results),1):.1f}\n")
        f.write(f"**Over-selection ratio:** {total_selected/max(total_expected,1):.1f}x\n\n")

        f.write("| # | Question | Recall | Expected | Selected Names | Missing |\n")
        f.write("|---|----------|--------|----------|----------------|---------|\n")
        for pq in per_question:
            icon = "✅" if len(pq["missing"]) == 0 else "⚠️"
            missing_str = ", ".join(pq["missing"][:3]) + ("..." if len(pq["missing"]) > 3 else "")
            f.write(
                f"| {pq['num']} | {icon} | {pq['found']}/{pq['expected']} "
                f"({pq['pct']:.0f}%) | {pq['expected']} | {pq['selected']} | "
                f"{missing_str or '—'} |\n"
            )
        f.write("\n")

        # ================================================================
        # PER-QUERY DETAIL
        # ================================================================
        f.write("---\n\n")
        f.write("## 2. Per-Query Detail\n\n")

        for r in results:
            if "error" in r:
                f.write(f"### Q{r['num']}: {r['test_question']} — ERROR\n\n")
                f.write(f"```\n{r['error']}\n```\n\n")
                continue

            f.write(f"### Q{r['num']}: {r['test_question']}\n\n")
            f.write(f"**Query:** {r['query'][:300]}\n\n")
            f.write(f"**Rationale:** {r.get('rationale', 'N/A')}\n\n")
            f.write(f"**Expected columns ({len(r.get('expected_columns', []))}):**\n")
            for col in r.get("expected_columns", []):
                f.write(f"  - `{col}`\n")
            f.write(f"\n**Selected names ({r['selected_count']}):**\n")
            for name in r["selected_names"]:
                f.write(f"  - `{name}`\n")
            f.write(f"\n**Trimmed columns ({r['trimmed_df_column_count']}):**\n")
            for col in r["trimmed_df_columns"]:
                f.write(f"  - `{col}`\n")

            # Missing expected columns
            expected = set(r.get("expected_columns", []))
            selected_set = set()
            for col_name in r.get("selected_names", []):
                name = str(col_name)
                if "[" in name:
                    parts = name.strip("[]").split("[")
                    if len(parts) >= 2:
                        selected_set.add(parts[0].strip())
                    else:
                        selected_set.add(name.strip("[]"))
                else:
                    selected_set.add(name)
            missing = expected - selected_set
            if missing:
                f.write(f"\n**⚠️ Missing expected columns:** {', '.join(f'`{m}`' for m in sorted(missing))}\n")
            else:
                f.write(f"\n**✅ All expected columns found!**\n")
            f.write("\n")

    print(f"\n📄 Report saved: {report_path}")
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{timestamp}_new_queries_analysis"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Detect which template is active
    from pandasai.core.prompts.select_columns import SelectColumnsPrompt
    template_name = getattr(SelectColumnsPrompt, 'template_path', 'unknown')

    print("=" * 70)
    print("Step 1 Column Selection — NEW QUERIES (Never Seen Before)")
    print("=" * 70)
    print(f"Template:  {template_name}")
    print(f"CSV:       {CSV_FILE}")
    print(f"Model:     {SEMANTIC_MODEL_FILE}")
    print(f"Output:    {run_dir}")
    print(f"Questions: {len(NEW_TEST_QUESTIONS)}")
    print(f"Workers:   {MAX_WORKERS}")
    print()

    # Verify files exist
    for f in [CSV_FILE, SEMANTIC_MODEL_FILE]:
        if not f.exists():
            print(f"❌ File not found: {f}")
            sys.exit(1)
        print(f"✅ Found: {f.name}")

    # Verify LLM is configured
    from pandasai.config import ConfigManager
    config = ConfigManager.get()
    if not config.llm:
        from server.core.llm_setup import setup_global_llm
        print("  ⚙️ Setting up global LLM from .env...")
        setup_global_llm()
        config = ConfigManager.get()

    if not config.llm:
        print("❌ No LLM configured. Set LLM_API_KEY and LLM_BASE_URL in .env")
        sys.exit(1)
    print(f"✅ LLM configured: {type(config.llm).__name__}")

    # Register agent (shared across all questions)
    print("\n📋 Registering agent with enterprise data...")
    t_reg_start = time.time()
    agent = _register_agent_with_data()
    reg_elapsed = time.time() - t_reg_start
    print(f"✅ Agent registered ({reg_elapsed:.1f}s)\n")

    # ---- RUN ALL QUERIES IN PARALLEL ----
    print(f"🚀 Launching {len(NEW_TEST_QUESTIONS)} column selection queries in parallel...\n")

    results = [None] * len(NEW_TEST_QUESTIONS)
    total_sequential_time = 0.0
    t_wall_start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {}
        for i, q in enumerate(NEW_TEST_QUESTIONS):
            future = executor.submit(_run_single_column_selection, agent, q)
            future_to_idx[future] = i

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            q = NEW_TEST_QUESTIONS[idx]
            try:
                result = future.result()
                results[idx] = result
                total_sequential_time += result["elapsed_seconds"]

                # Quick expected column check
                expected = set(q.get("expected_columns", []))
                selected_set = set()
                for col_name in result.get("selected_names", []):
                    name = str(col_name)
                    if "[" in name:
                        parts = name.strip("[]").split("[")
                        if len(parts) >= 2:
                            selected_set.add(parts[0].strip())
                        else:
                            selected_set.add(name.strip("[]"))
                    else:
                        selected_set.add(name)
                found = expected & selected_set
                missing = expected - selected_set
                icon = "✅" if not missing else "⚠️"
                print(
                    f"  {icon} Q{q['num']}: {len(found)}/{len(expected)} expected | "
                    f"{result['selected_count']} names → {result['trimmed_df_column_count']} cols "
                    f"({result['elapsed_seconds']}s)"
                    f"{' [missing: ' + ', '.join(sorted(missing)[:3]) + ']' if missing else ''}"
                )

            except Exception as e:
                import traceback
                print(f"  ❌ Q{q['num']}: Error — {e}")
                traceback.print_exc()
                results[idx] = {
                    "num": q["num"],
                    "test_question": q["test_question"],
                    "query": q["pandasai_input"],
                    "expected_breadth": q["expected_breadth"],
                    "key_columns": q["key_columns"],
                    "expected_columns": q.get("expected_columns", []),
                    "rationale": q.get("rationale", ""),
                    "error": str(e),
                    "selected_names": [],
                    "selected_count": 0,
                    "matched_columns": {},
                    "matched_count": 0,
                    "trimmed_df_columns": [],
                    "trimmed_df_column_count": 0,
                    "raw_llm_response": None,
                    "elapsed_seconds": 0,
                    "prompt_text": "",
                    "sampling_params": None,
                    "trimmed_serialized_preview": "",
                    "trimmed_serialized_length": 0,
                    "full_serialized_length": 0,
                    "token_saving_pct": None,
                }

    t_wall_end = time.time()
    total_wall_time = t_wall_end - t_wall_start

    # ---- SAVE INDIVIDUAL JSON RESULTS ----
    for result in results:
        outfile = run_dir / f"Q{result['num']}_step1.json"
        with open(outfile, "w", encoding="utf-8") as f:
            save_result = {k: v for k, v in result.items() if k != "prompt_text"}
            json.dump(save_result, f, indent=2, ensure_ascii=False, default=str)

    # ---- COMPUTE FINAL RECALL ----
    total_expected = 0
    total_found = 0
    total_selected = 0

    for r in results:
        if "error" in r:
            continue
        expected = set(r.get("expected_columns", []))
        selected_set = set()
        for col_name in r.get("selected_names", []):
            name = str(col_name)
            if "[" in name:
                parts = name.strip("[]").split("[")
                if len(parts) >= 2:
                    selected_set.add(parts[0].strip())
                else:
                    selected_set.add(name.strip("[]"))
            else:
                selected_set.add(name)
        found = expected & selected_set
        total_expected += len(expected)
        total_found += len(found)
        total_selected += len(r.get("selected_names", []))

    # ---- WRITE REPORT ----
    _write_analysis_report(run_dir, results, timestamp, total_wall_time, total_sequential_time, template_name)

    # ---- PRINT SUMMARY ----
    print("\n" + "=" * 70)
    print(f"Step 1 Column Selection — NEW QUERIES ({template_name})")
    print("=" * 70)
    print(f"  Recall:          {total_found}/{total_expected} ({total_found/max(total_expected,1)*100:.1f}%)")
    print(f"  Avg selected:    {total_selected/max(len(results),1):.1f} names")
    print(f"  Over-selection:  {total_selected/max(total_expected,1):.1f}x")
    print(f"  Wall time:       {total_wall_time:.1f}s (sequential: {total_sequential_time:.1f}s)")
    print(f"  Speedup:         {total_sequential_time/max(total_wall_time,0.1):.1f}x")
    print(f"  Errors:          {sum(1 for r in results if 'error' in r)}/{len(results)}")
    print(f"  Output:          {run_dir}")
    print("=" * 70)

    # Save summary JSON for easy comparison
    summary = {
        "timestamp": timestamp,
        "template": template_name,
        "test_type": "new_queries",
        "recall": f"{total_found}/{total_expected} ({total_found/max(total_expected,1)*100:.1f}%)",
        "total_found": total_found,
        "total_expected": total_expected,
        "avg_selected": round(total_selected / max(len(results), 1), 1),
        "over_selection": round(total_selected / max(total_expected, 1), 1),
        "wall_time_seconds": round(total_wall_time, 1),
        "errors": sum(1 for r in results if "error" in r),
        "results": [{k: v for k, v in r.items() if k not in ("prompt_text",)} for r in results],
    }
    with open(run_dir / "new_queries_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
