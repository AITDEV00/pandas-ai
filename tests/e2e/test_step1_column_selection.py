"""Step 1 Column Selection E2E Test - Adaptive Breadth

Tests ONLY the Step 1 column selection pipeline (no Step 2 code generation).
For each test question, this script:
  1. Registers a fresh Agent with the enterprise HC dataset + semantic model
  2. Extracts the DataFrame and AgentState from the registered Agent
  3. Creates a ColumnSelector and calls select(query) directly
  4. Captures: selected columns, reasoning, raw LLM response

This validates what the small LLM actually selects for columns and whether
it adapts column breadth based on question complexity.

Prerequisites:
  - .env file configured with LLM credentials (LLM_API_KEY, LLM_BASE_URL, etc.)
  - Enterprise HC dataset files in datasets/

Usage:
  poetry run python tests/e2e/test_step1_column_selection.py

  # Custom output directory
  OUTPUT_DIR=/tmp/step1_results poetry run python tests/e2e/test_step1_column_selection.py
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "run" / "e2e_reports")))

# Load .env BEFORE any PandasAI imports (LLM credentials must be in env)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"

# Column selection config — matches the server's CHAT_PARAMS
COLUMN_SELECTION_THRESHOLD = 30
COLUMN_VALUES_BUDGET_RATIO = 0.10

# PandasAI config — matches the server's registration config
# Column selection sampling mirrors code generation: ONLY temperature set.
PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
    # Column selection sampling — ONLY temperature=0.0 for deterministic output;
    # all other params left unset to use model defaults.
    "column_selection_temperature": 0.0,
    "column_selection_json_mode": True,
}

# ---------------------------------------------------------------------------
# Test Questions
# ---------------------------------------------------------------------------

# Each question has:
#   - num: test identifier
#   - test_question: the original human question
#   - pandasai_input: what gets sent to the column selector (the query)
#   - expected_breadth: how many columns we expect ("minimal", "moderate", "generous")
#   - key_columns: columns we EXPECT to be selected (substring match)
#   - breadth_rationale: why we expect this breadth
TEST_QUESTIONS: List[Dict] = [
    {
        "num": "3b",
        "test_question": "What are the main skills of employee 1137?",
        "pandasai_input": "What are the main skills of employee 1137?",
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # direct skill names
            "Employee Competencies Rating",      # proficiency levels
            "CV Employee Summary",               # professional profile
            "CV Employee Work Experience",       # responsibilities = applied skills
            "Employee Achievements",             # demonstrated skills in comments
        ],
        "breadth_rationale": (
            "Skills/abilities is a multi-struct concept — must include competency names, "
            "ratings, summary, work experience (responsibilities), and achievements. "
            "Selecting only CV Employee Competencies is WRONG."
        ),
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
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # direct skill names
            "Employee Competencies Rating",      # proficiency levels (explicitly requested)
            "CV Employee Summary",               # professional profile
            "CV Employee Work Experience",       # responsibilities = applied skills
            "Employee Achievements",             # demonstrated skills
        ],
        "breadth_rationale": (
            "Detailed entity question — must include all requested attributes. "
            "Competency ratings explicitly requested, plus summary, experience, achievements."
        ),
    },
    {
        "num": "11",
        "test_question": "Give me the list of employees from human capital department",
        "pandasai_input": (
            "List all employees working in the Human Capital Department. For each "
            "employee, show: Employee Name, Employee ID, Organizational Unit/Section, "
            "Grade, Date of Joining, Years of Service/Tenure, and Division. Sort by "
            "employee ID ascending. Include total count at the end."
        ),
        "expected_breadth": "generous",
        "key_columns": ["Employee Name", "Employee Number", "Department", "Grade", "Date of Joining"],
        "breadth_rationale": "List question — should include all requested detail columns",
    },
    {
        "num": "12",
        "test_question": "Give me employees who speak chinese and have experience in AI",
        "pandasai_input": (
            "Find all employees who have BOTH Chinese language skills AND any AI-related "
            "competency (including Artificial Intelligence, AI Implementation, AI Integration, "
            "Machine Learning, Deep Learning, Python, or similar AI/ML skills). For each "
            "employee show: Employee Name, Employee ID, Organizational Unit/Section, "
            "Department, Grade, Date of Joining, Years of Service, and list all their "
            "relevant skills including Chinese language proficiency and AI competencies. "
            "Sort by years of service descending."
        ),
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Name", "Employee Number",
            "CV Employee Competencies",          # skill names (Chinese, AI)
            "Employee Competencies Rating",      # proficiency levels
            "CV Employee Work Experience",       # AI experience in responsibilities
            "CV Employee Summary",               # professional profile mentioning AI
        ],
        "breadth_rationale": (
            "Filter + list question — skills/competencies is a multi-struct concept. "
            "Must include competency names, ratings, work experience, and summary."
        ),
    },
    {
        "num": "13a",
        "test_question": "How many sick leaves did employee 1136 take in 2025?",
        "pandasai_input": (
            "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) "
            "in the year 2025. Count total number of sick leave days taken, list each "
            "leave record with start date, end date, and duration. Also include employee "
            "name and department if available."
        ),
        "expected_breadth": "moderate",
        "key_columns": ["Employee Number", "Employee Leave Details"],
        "breadth_rationale": "Count + records question — needs leave data + employee identity",
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
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Number", "Employee Name",
            "Employee Assignment History",        # project assignments
            "Employee Objectives",               # objective name = project name
            "Employee Achievements",             # comments reference projects
            "CV Employee Work Experience",       # projects in responsibilities
            "CV Employee Achievements and Awards", # project-related achievements
        ],
        "breadth_rationale": (
            "Comparison question — projects is a multi-struct concept. "
            "Must include assignment history, objectives, achievements, work experience."
        ),
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
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Number", "Employee Name",
            "CV Employee Competencies",          # skill names
            "Employee Competencies Rating",      # proficiency levels (explicitly requested)
            "CV Employee Summary",               # professional profile
            "CV Employee Work Experience",       # responsibilities = applied skills
            "Employee Achievements",             # demonstrated skills
        ],
        "breadth_rationale": (
            "Comparison question — skills is a multi-struct concept. "
            "Must include competency names, ratings (explicitly requested), summary, experience."
        ),
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
        "expected_breadth": "generous",
        "key_columns": [
            "Employee Number", "Employee Name",
            "Employee Qualification",            # degree, institute, GPA
            "CV Employee Education",             # CV education records
        ],
        "breadth_rationale": (
            "Comparison question — education is a multi-struct concept. "
            "Must include both qualification and CV education struct groups."
        ),
    },
    {
        "num": "28",
        "test_question": "Average Salary of Senior Specialist in ADEO",
        "pandasai_input": (
            "Find all employees who have \"Senior Specialist\" in their job title or "
            "position. For each employee, show: Employee Name, Employee ID, Grade, "
            "Position Title, Department, Division, Organizational Unit, Years of Service, "
            "and any salary-related fields available in the system (such as Salary Amount, "
            "Basic Salary, Total Compensation, Salary Band, Pay Grade, or similar "
            "compensation data). Calculate the average salary across all Senior Specialists "
            "if salary data exists. Sort by years of service descending."
        ),
        "expected_breadth": "moderate",
        "key_columns": ["Position Title", "Salary"],
        "breadth_rationale": "Aggregation + detail question — needs position + salary columns",
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
        "expected_breadth": "moderate",
        "key_columns": ["Employee Name", "Date of Joining"],
        "breadth_rationale": "Ranking question — needs identity + service/tenure columns",
    },
]


# ---------------------------------------------------------------------------
# Registration (mirrors server/features/register/handler.py)
# ---------------------------------------------------------------------------

def _register_agent_with_data():
    """Register an Agent with the enterprise HC dataset.

    This mirrors the server's create_agent_from_file_path() logic:
    1. Read CSV via pai.read_csv
    2. Apply semantic model to DataFrame schema
    3. Patch schema for list[struct] columns
    4. Enrich column values
    5. Create Agent with config

    Returns the Agent instance.
    """
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

    # 1. Read CSV
    print(f"  📂 Reading CSV: {CSV_FILE.name}")
    df = pai.read_csv(str(CSV_FILE))

    # 2. Parse JSON array columns
    parse_json_array_columns(df)

    # 3. Apply semantic model
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

    # 4. Patch schema columns (same as register handler step 2b)
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

    # 5. Create Agent with config
    print("  🤖 Creating Agent...")
    global_config_obj = ConfigManager.get()
    agent_config = global_config_obj.model_dump()
    agent_config["llm"] = global_config_obj.llm  # Preserve actual object
    agent_config.update(PANDASAI_CONFIG)

    # Inject the dedicated structured LLM (STRUCTURED_LLM_*) so the ColumnSelector
    # uses the model under test (e.g. diffusiongemma, DeepSeek) rather than the
    # main code-generation LLM.  When not configured, falls back to the main LLM.
    try:
        from server.core.llm_setup import setup_structured_llm
        structured_llm = setup_structured_llm()
        if structured_llm is not None:
            agent_config["structured_llm"] = structured_llm
            print(
                f"  ✅ Using structured LLM for column selection: "
                f"{getattr(structured_llm, 'model', 'unknown')}"
            )
    except Exception as e:  # pragma: no cover
        print(f"  ⚠️ Could not set up structured LLM ({e}); column selection will use the main LLM")

    agent = Agent([df], config=agent_config)
    print(f"  ✅ Agent created. DataFrame has {len(df.columns)} columns, {len(df)} rows")
    return agent


# ---------------------------------------------------------------------------
# Step 1 Column Selection Test
# ---------------------------------------------------------------------------

def _run_column_selection(agent, query: str) -> Dict[str, Any]:
    """Run Step 1 column selection directly on the Agent's state.

    This mirrors what _apply_column_selection() does in agent/base.py,
    but only runs Step 1 (column selection) without Step 2 (code generation).
    """
    from pandasai.core.column_selector import ColumnSelector

    # Get the Agent's internal state
    state = agent._state

    # Create ColumnSelector — this is exactly what _apply_column_selection does
    selector = ColumnSelector(state)

    # Run column selection
    t_start = time.time()
    selected_names = selector.select(query)
    elapsed = time.time() - t_start

    # Extract Step 1 results
    raw_response = getattr(selector, '_last_raw_response', None)

    # Extract the model's thinking trace captured during column selection
    thinking_trace = getattr(state, 'column_selection_thinking_trace', None)
    if not thinking_trace:
        # Fall back to the raw response's reasoning_content if present
        thinking_trace = getattr(selector, '_last_thinking_trace', None)

    # Match names to schema (same as _apply_column_selection)
    df = state.dfs[0]
    matched = selector.match_names_to_schema(selected_names, df)
    matched = selector.ensure_essential_columns(matched, df, query)

    # Build the trimmed DataFrame to see what columns actually get included
    trimmed_df = selector.build_trimmed_dataframe(df, matched)

    return {
        "query": query,
        "selected_names": selected_names,
        "matched_columns": {
            k: v for k, v in matched.items()
        },
        "trimmed_df_columns": list(trimmed_df.columns) if trimmed_df is not None else [],
        "trimmed_df_column_count": len(trimmed_df.columns) if trimmed_df is not None else 0,
        "raw_llm_response": raw_response,
        "thinking_trace": thinking_trace,
        "elapsed_seconds": round(elapsed, 2),
    }


def _check_key_columns(selected_names: List[str], key_columns: List[str]) -> Dict[str, bool]:
    """Check if key expected columns appear in the selection (substring match)."""
    results = {}
    combined = " ".join(str(n) for n in selected_names).lower()
    for key_col in key_columns:
        # Substring match (case-insensitive)
        key_lower = key_col.lower()
        found = key_lower in combined
        # Also check individual names for exact/partial match
        if not found:
            for name in selected_names:
                if key_lower in str(name).lower():
                    found = True
                    break
        results[key_col] = found
    return results


def _print_result(q: Dict, result: Dict, key_col_check: Dict[str, bool]):
    """Pretty-print a single test question result."""
    num = q["num"]
    breadth = q["expected_breadth"]
    n_selected = len(result["selected_names"])
    n_trimmed = result["trimmed_df_column_count"]

    print(f"\n{'─' * 60}")
    print(f"Q{num}: {q['test_question'][:70]}...")
    print(f"  Expected breadth: {breadth}  |  Selected: {n_selected} names → {n_trimmed} trimmed columns ({result['elapsed_seconds']}s)")

    # Print selected names
    print(f"  Selected names:")
    for name in result["selected_names"]:
        print(f"    • {name}")

    # Print key column check
    all_found = all(key_col_check.values())
    key_icon = "✅" if all_found else "⚠️"
    print(f"  Key columns {key_icon}:")
    for key_col, found in key_col_check.items():
        icon = "✅" if found else "❌"
        print(f"    {icon} {key_col}")

    # Print matched columns (struct parents + their inner fields)
    if result["matched_columns"]:
        print(f"  Matched to schema:")
        for parent, fields in result["matched_columns"].items():
            if fields is None:
                print(f"    • {parent} (flat)")
            else:
                print(f"    • {parent} → {len(fields)} inner fields")


def _save_results(run_dir: Path, results: List[Dict], timestamp: str):
    """Save all results to JSON files."""
    # Save individual results
    for q, result in zip(TEST_QUESTIONS, results):
        outfile = run_dir / f"Q{q['num']}_step1.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    # Save summary
    summary = {
        "timestamp": timestamp,
        "test_type": "step1_column_selection",
        "config": {
            "csv_file": str(CSV_FILE),
            "semantic_model_file": str(SEMANTIC_MODEL_FILE),
            "column_selection_threshold": COLUMN_SELECTION_THRESHOLD,
            "column_values_budget_ratio": COLUMN_VALUES_BUDGET_RATIO,
            "pandasai_config": PANDASAI_CONFIG,
        },
        "results": results,
    }
    with open(run_dir / "step1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    # Save Markdown report
    _write_markdown_report(run_dir, results, timestamp)


def _write_markdown_report(run_dir: Path, results: List[Dict], timestamp: str):
    """Write a human-readable Markdown report."""
    report_path = run_dir / "step1_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Step 1 Column Selection E2E Report\n\n")
        f.write(f"**Date:** {timestamp}\n")
        f.write(f"**CSV:** `{CSV_FILE.name}`\n")
        f.write(f"**Semantic Model:** `{SEMANTIC_MODEL_FILE.name}`\n\n")

        # Summary table
        f.write("## Summary\n\n")
        f.write("| # | Question | Breadth | Selected | Trimmed Cols | Key Cols | Time |\n")
        f.write("|---|----------|---------|----------|-------------|----------|------|\n")
        for q, result in zip(TEST_QUESTIONS, results):
            key_ok = "✅" if result.get("key_column_check") and all(result["key_column_check"].values()) else "⚠️"
            f.write(
                f"| {q['num']} | {q['test_question'][:50]}... | {q['expected_breadth']} | "
                f"{len(result['selected_names'])} | "
                f"{result['trimmed_df_column_count']} | {key_ok} | {result['elapsed_seconds']}s |\n"
            )
        f.write("\n")

        # Detailed results
        f.write("## Detailed Results\n\n")
        for q, result in zip(TEST_QUESTIONS, results):
            f.write(f"### Q{q['num']}: {q['test_question']}\n\n")
            f.write(f"- **Query sent to LLM:** {result['query'][:200]}...\n")
            f.write(f"- **Expected breadth:** `{q['expected_breadth']}`\n")
            f.write(f"- **Selected names ({len(result['selected_names'])}):**\n")
            for name in result["selected_names"]:
                f.write(f"  - `{name}`\n")
            f.write(f"- **Trimmed DataFrame columns ({result['trimmed_df_column_count']}):**\n")
            for col in result["trimmed_df_columns"]:
                f.write(f"  - `{col}`\n")
            f.write(f"- **Raw LLM response:**\n```\n{result['raw_llm_response'] or 'N/A'}\n```\n\n")

        # Thinking trace (reasoning) — appended after the raw response so the
        # model's chain-of-thought behind its column selection can be audited.
        for q, result in zip(TEST_QUESTIONS, results):
            trace = result.get("thinking_trace")
            if trace:
                f.write(f"### Q{q['num']} Thinking Trace\n\n```\n{trace}\n```\n\n")

    print(f"\n📄 Markdown report saved: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{timestamp}_step1_column_selection"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Step 1 Column Selection E2E Test (Adaptive Breadth)")
    print("=" * 70)
    print(f"CSV:       {CSV_FILE}")
    print(f"Model:     {SEMANTIC_MODEL_FILE}")
    print(f"Output:    {run_dir}")
    print(f"Questions: {len(TEST_QUESTIONS)}")
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
        # Try setting up the global LLM from .env (same as server startup)
        from server.core.llm_setup import setup_global_llm
        print("  ⚙️ Setting up global LLM from .env...")
        setup_global_llm()
        config = ConfigManager.get()

    if not config.llm:
        print("❌ No LLM configured. Set LLM_API_KEY and LLM_BASE_URL in .env")
        sys.exit(1)
    print(f"✅ LLM configured: {type(config.llm).__name__}")

    # Register agent (shared across all questions — same data, same schema)
    print("\n📋 Registering agent with enterprise data...")
    t_reg_start = time.time()
    agent = _register_agent_with_data()
    reg_elapsed = time.time() - t_reg_start
    print(f"✅ Agent registered ({reg_elapsed:.1f}s)\n")

    # Run Step 1 for each question
    results = []
    for i, q in enumerate(TEST_QUESTIONS):
        num = q["num"]
        print(f"\n{'═' * 60}")
        print(f"Q{num}/{len(TEST_QUESTIONS)}: {q['test_question'][:60]}...")
        print(f"  Query: {q['pandasai_input'][:80]}...")
        print(f"  Expected breadth: {q['expected_breadth']}")

        try:
            # Optional cache-buster: the inference engine caches responses keyed
            # on the prompt, so repeated runs (e.g. comparing thinking OFF vs ON)
            # return identical cached answers.  Appending a unique nonce forces a
            # genuine cold LLM call per run.  The nonce is appended inside the
            # prompt only; column selection is not sensitive to a trailing
            # comment, so results remain valid.
            cache_buster = os.environ.get("COLUMN_SELECTION_CACHE_BUSTER", "").strip()
            run_query = q["pandasai_input"]
            if cache_buster:
                run_query = f"{run_query}\n<!-- run:{cache_buster} -->"

            result = _run_column_selection(agent, run_query)

            # Check key columns
            key_col_check = _check_key_columns(
                result["selected_names"], q["key_columns"]
            )
            result["key_column_check"] = key_col_check
            result["expected_breadth"] = q["expected_breadth"]
            result["breadth_rationale"] = q["breadth_rationale"]
            result["test_question"] = q["test_question"]

            _print_result(q, result, key_col_check)
            results.append(result)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "query": q["pandasai_input"],
                "test_question": q["test_question"],
                "expected_breadth": q["expected_breadth"],
                "error": str(e),
                "selected_names": [],
                "trimmed_df_columns": [],
                "trimmed_df_column_count": 0,
            })

    # Save results
    _save_results(run_dir, results, timestamp)

    # Print final summary
    key_col_found = sum(
        1 for r in results
        if r.get("key_column_check") and all(r["key_column_check"].values())
    )
    errors = sum(1 for r in results if "error" in r)
    avg_selected = sum(len(r.get("selected_names", [])) for r in results) / len(results) if results else 0
    avg_trimmed = sum(r.get("trimmed_df_column_count", 0) for r in results) / len(results) if results else 0

    print(f"\n{'=' * 70}")
    print(f"Step 1 Column Selection Results (Adaptive Breadth)")
    print(f"{'=' * 70}")
    print(f"  Key cols found: {key_col_found}/{len(TEST_QUESTIONS)}")
    print(f"  Avg selected:   {avg_selected:.1f} names")
    print(f"  Avg trimmed:    {avg_trimmed:.1f} columns")
    print(f"  Errors:         {errors}/{len(TEST_QUESTIONS)}")
    print(f"  Output:         {run_dir}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
