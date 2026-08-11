"""Step 1 Column Selection E2E Test — Fully Parallel + LLM Output Analysis

This script:
  1. Registers a single Agent with the enterprise HC dataset
  2. Runs ALL column selection LLM calls in PARALLEL using ThreadPoolExecutor
  3. Captures the FULL raw LLM response, parsed JSON, and intermediate artifacts
  4. Analyzes how Step 2 (code generation) would consume the Step 1 output
  5. Writes a comprehensive report to run/e2e_reports/

Prerequisites:
  - .env file configured with LLM credentials
  - Enterprise HC dataset files in datasets/

Usage:
  source .venv/bin/activate && python tests/e2e/test_step1_parallel.py
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
# Test Questions (same as test_step1_column_selection.py)
# ---------------------------------------------------------------------------

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
    },
]


# ---------------------------------------------------------------------------
# Registration (same as test_step1_column_selection.py)
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
# Parallel Column Selection Runner
# ---------------------------------------------------------------------------

def _run_single_column_selection(agent, q: Dict) -> Dict[str, Any]:
    """Run column selection for a single question.

    This is the worker function executed in parallel threads.
    Each thread gets its own ColumnSelector instance (stateless w.r.t. LLM calls).

    Returns a comprehensive result dict with ALL intermediate artifacts.
    """
    from pandasai.core.column_selector import ColumnSelector

    state = agent._state
    query = q["pandasai_input"]

    # Each thread creates its own ColumnSelector
    selector = ColumnSelector(state)

    # ---- CAPTURE THE PROMPT (before LLM call) ----
    prompt_obj = selector._build_prompt(query)
    prompt_text = str(prompt_obj)

    # ---- CAPTURE THE SAMPLING PARAMS ----
    sampling_params = selector._get_sampling_params()

    # ---- RUN THE LLM CALL ----
    t_start = time.time()
    response = state.config.llm.call(prompt_obj, state, sampling_params=sampling_params)
    elapsed = time.time() - t_start

    # ---- CAPTURE RAW LLM RESPONSE ----
    raw_response = response  # The raw string from the LLM

    # ---- PARSE THE RESPONSE (same as selector.select()) ----
    selected_names = selector._parse_response(response)
    selected_names = selector._validate_names(selected_names)

    # ---- MATCH TO SCHEMA ----
    df = state.dfs[0]
    matched = selector.match_names_to_schema(selected_names, df)
    matched = selector.ensure_essential_columns(matched, df, query)

    # ---- BUILD TRIMMED DATAFRAME ----
    trimmed_df = selector.build_trimmed_dataframe(df, matched)

    # ---- SERIALIZE TRIMMED DATAFRAME (what Step 2 would see) ----
    trimmed_serialized = ""
    if trimmed_df is not None:
        try:
            trimmed_serialized = trimmed_df.serialize_dataframe(state.config)
        except Exception as e:
            trimmed_serialized = f"(serialization error: {e})"

    # ---- SERIALIZE FULL DATAFRAME (what Step 2 would see WITHOUT column selection) ----
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

        # ---- LLM INPUT ----
        "prompt_text": prompt_text,
        "sampling_params": sampling_params,

        # ---- LLM OUTPUT (raw) ----
        "raw_llm_response": raw_response,
        "elapsed_seconds": round(elapsed, 2),

        # ---- PARSED OUTPUT ----
        "selected_names": selected_names,
        "selected_count": len(selected_names),

        # ---- SCHEMA MATCHING ----
        "matched_columns": {k: v for k, v in matched.items()},
        "matched_count": len(matched),

        # ---- TRIMMED DATAFRAME ----
        "trimmed_df_columns": list(trimmed_df.columns) if trimmed_df is not None else [],
        "trimmed_df_column_count": len(trimmed_df.columns) if trimmed_df is not None else 0,

        # ---- WHAT STEP 2 SEES ----
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
# Report Generation
# ---------------------------------------------------------------------------

def _write_analysis_report(run_dir: Path, results: List[Dict], timestamp: str, total_wall_time: float, total_sequential_time: float):
    """Write the comprehensive analysis report."""
    report_path = run_dir / "step1_parallel_analysis_report.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Step 1 Column Selection — Parallel Execution & LLM Output Analysis\n\n")
        f.write(f"**Date:** {timestamp}\n")
        f.write(f"**CSV:** `{CSV_FILE.name}`\n")
        f.write(f"**Semantic Model:** `{SEMANTIC_MODEL_FILE.name}`\n")
        f.write(f"**Max Workers:** {MAX_WORKERS}\n")
        f.write(f"**Total Wall Time:** {total_wall_time:.1f}s (sequential would be ~{total_sequential_time:.1f}s)\n")
        f.write(f"**Speedup:** {total_sequential_time / max(total_wall_time, 0.1):.1f}x\n\n")

        # ================================================================
        # SECTION 1: EXECUTION SUMMARY
        # ================================================================
        f.write("---\n\n")
        f.write("## 1. Execution Summary\n\n")
        f.write("| # | Question | Wall Time | Selected Names | Trimmed Cols | Key Cols | Token Saving |\n")
        f.write("|---|----------|-----------|----------------|-------------|----------|-------------|\n")
        for r in results:
            if "error" in r:
                f.write(f"| {r['num']} | {r['test_question'][:40]}... | ERROR | - | - | - | - |\n")
                continue
            key_ok = "✅" if all(_check_key_columns(r["selected_names"], r["key_columns"]).values()) else "⚠️"
            saving = f"{r.get('token_saving_pct', 'N/A')}%" if r.get('token_saving_pct') is not None else "N/A"
            f.write(
                f"| {r['num']} | {r['test_question'][:40]}... | {r['elapsed_seconds']}s | "
                f"{r['selected_count']} | {r['trimmed_df_column_count']} | {key_ok} | {saving} |\n"
            )
        f.write("\n")

        # ================================================================
        # SECTION 2: WHAT THE LLM GENERATES PER QUERY
        # ================================================================
        f.write("---\n\n")
        f.write("## 2. What the LLM Generates Per Query\n\n")
        f.write("For each query, the LLM receives the V6 prompt template filled with column metadata\n")
        f.write("(name, type, description, sample values) and returns a **JSON object** with two fields:\n\n")
        f.write("```json\n")
        f.write("{\n")
        f.write('  "selected": ["Column Name 1", "Column Name 2", "..."],\n')
        f.write('  "reasoning": "brief explanation of selection"\n')
        f.write("}\n")
        f.write("```\n\n")
        f.write("The `selected` array contains **flat column names** and/or **struct inner field names**.\n")
        f.write("The `reasoning` string explains the selection logic.\n\n")

        for r in results:
            if "error" in r:
                f.write(f"### Q{r['num']}: {r['test_question']} — ERROR\n\n")
                f.write(f"```\n{r['error']}\n```\n\n")
                continue

            f.write(f"### Q{r['num']}: {r['test_question']}\n\n")
            f.write(f"**Query sent to LLM:**\n> {r['query'][:300]}\n\n")
            f.write(f"**Sampling params:** `{json.dumps(r['sampling_params'], indent=2) if r['sampling_params'] else 'None (LLM defaults)'}`\n\n")
            f.write(f"**Raw LLM response:**\n```json\n{r['raw_llm_response'] or 'N/A'}\n```\n\n")
            f.write(f"**Parsed selected names ({r['selected_count']}):**\n")
            for name in r["selected_names"]:
                f.write(f"  - `{name}`\n")
            f.write("\n")

        # ================================================================
        # SECTION 3: OUTPUT FORMAT ANALYSIS
        # ================================================================
        f.write("---\n\n")
        f.write("## 3. LLM Output Format Analysis\n\n")

        # Analyze format patterns across all results
        has_selected_key = 0
        has_reasoning_key = 0
        has_selected_columns_key = 0
        has_dict_format = 0
        total_valid = len([r for r in results if "error" not in r])

        for r in results:
            if "error" in r:
                continue
            raw = r["raw_llm_response"] or ""
            try:
                import re
                json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if "selected" in data:
                        has_selected_key += 1
                    if "reasoning" in data:
                        has_reasoning_key += 1
                    if "selected_columns" in data:
                        has_selected_columns_key += 1
                    if isinstance(data.get("selected"), dict):
                        has_dict_format += 1
            except:
                pass

        f.write(f"Out of {total_valid} valid responses:\n\n")
        f.write(f"| Format Feature | Count | Percentage |\n")
        f.write(f"|---------------|-------|------------|\n")
        f.write(f"| `selected` key present | {has_selected_key} | {has_selected_key/max(total_valid,1)*100:.0f}% |\n")
        f.write(f"| `reasoning` key present | {has_reasoning_key} | {has_reasoning_key/max(total_valid,1)*100:.0f}% |\n")
        f.write(f"| `selected_columns` key (legacy) | {has_selected_columns_key} | {has_selected_columns_key/max(total_valid,1)*100:.0f}% |\n")
        f.write(f"| `selected` is dict (parent→fields) | {has_dict_format} | {has_dict_format/max(total_valid,1)*100:.0f}% |\n")
        f.write("\n")

        f.write("### Supported JSON Formats\n\n")
        f.write("The `_parse_response()` method in `ColumnSelector` handles:\n\n")
        f.write("1. **Standard format** (most common):\n")
        f.write("```json\n")
        f.write('{\n  "selected": ["Column Name 1", "Column Name 2"],\n  "reasoning": "..."\n}\n')
        f.write("```\n\n")
        f.write("2. **Legacy format**:\n")
        f.write("```json\n")
        f.write('{\n  "selected_columns": ["Column Name 1", "Column Name 2"]\n}\n')
        f.write("```\n\n")
        f.write("3. **Dict format** (parent → inner fields):\n")
        f.write("```json\n")
        f.write('{\n  "selected": {"Parent": ["field1", "field2"], "FlatCol": []}\n}\n')
        f.write("```\n\n")

        # ================================================================
        # SECTION 4: HOW STEP 2 USES STEP 1 OUTPUT
        # ================================================================
        f.write("---\n\n")
        f.write("## 4. How Step 2 (Code Generation) Uses Step 1 Output\n\n")

        f.write("### The Pipeline Flow\n\n")
        f.write("```mermaid\n")
        f.write("flowchart TD\n")
        f.write("    A[User Query] --> B[Step 1: Column Selection]\n")
        f.write("    B --> C[LLM returns JSON]\n")
        f.write("    C --> D[Parse 'selected' array]\n")
        f.write("    D --> E[match_names_to_schema]\n")
        f.write("    E --> F[ensure_essential_columns]\n")
        f.write("    F --> G[build_trimmed_dataframe]\n")
        f.write("    G --> H[Replace state.dfs with trimmed DF]\n")
        f.write("    H --> I[Step 2: Code Generation]\n")
        f.write("    I --> J[serialize_dataframe → LLM prompt]\n")
        f.write("    I --> K[LLM generates Python/SQL code]\n")
        f.write("```\n\n")

        f.write("### Key Insight: Step 2 Never Sees the Raw Step 1 Output\n\n")
        f.write("Step 2 (code generation) does **NOT** directly consume the LLM's JSON response from Step 1.\n")
        f.write("Instead, the pipeline transforms the raw output through several stages:\n\n")

        f.write("| Stage | Input | Output | What Happens |\n")
        f.write("|-------|-------|--------|-------------|\n")
        f.write("| 1. LLM call | V6 prompt + query | Raw JSON string | LLM selects columns by name |\n")
        f.write("| 2. Parse | Raw JSON | `List[str]` of names | Extract `selected` array, sanitize quotes |\n")
        f.write("| 3. Schema match | Names + schema | `Dict[str, Optional[List[str]]]` | Map flat names → schema columns |\n")
        f.write("| 4. Essential cols | Matched dict | Updated dict | Add identity/filter columns if missing |\n")
        f.write("| 5. Trim DF | Matched dict + DataFrame | Trimmed DataFrame | Select only matched columns |\n")
        f.write("| 6. **Step 2 sees** | Trimmed DataFrame | Serialized schema | `df.serialize_dataframe()` → prompt text |\n\n")

        f.write("### What Step 2 Actually Receives\n\n")
        f.write("Step 2 receives the **trimmed DataFrame** via `context.dfs`. The code generation prompt\n")
        f.write("(`generate_python_code_with_sql.tmpl`) renders each DataFrame using `df.serialize_dataframe()`,\n")
        f.write("which produces a text representation of the **schema** (column names, types, descriptions, samples)\n")
        f.write("and optionally a few preview rows.\n\n")

        f.write("This means Step 2 sees **only the columns that Step 1 selected** — the LLM never sees\n")
        f.write("the full 63-column schema, only the trimmed subset.\n\n")

        # ================================================================
        # SECTION 5: PER-QUERY TOKEN SAVINGS
        # ================================================================
        f.write("---\n\n")
        f.write("## 5. Per-Query Token Savings (Step 1 → Step 2)\n\n")

        f.write("Column selection reduces the schema sent to the code generation LLM.\n")
        f.write("Below shows the serialized DataFrame size for each query:\n\n")

        f.write("| # | Question | Full Schema | Trimmed Schema | Saving | Trimmed Columns |\n")
        f.write("|---|----------|-------------|----------------|---------|----------------|\n")
        for r in results:
            if "error" in r:
                continue
            full_len = r.get("full_serialized_length", 0)
            trimmed_len = r.get("trimmed_serialized_length", 0)
            saving = r.get("token_saving_pct", 0) or 0
            f.write(
                f"| {r['num']} | {r['test_question'][:35]}... | "
                f"{full_len:,} chars | {trimmed_len:,} chars | {saving}% | "
                f"{r['trimmed_df_column_count']} |\n"
            )
        f.write("\n")

        # ================================================================
        # SECTION 6: TRIMMED DATAFRAME PREVIEW (what Step 2 sees)
        # ================================================================
        f.write("---\n\n")
        f.write("## 6. Trimmed DataFrame Preview (What Step 2 Sees)\n\n")

        for r in results:
            if "error" in r:
                continue
            f.write(f"### Q{r['num']}: {r['test_question']}\n\n")
            f.write(f"**Trimmed columns ({r['trimmed_df_column_count']}):**\n")
            for col in r["trimmed_df_columns"]:
                f.write(f"  - `{col}`\n")
            f.write(f"\n**Serialized preview (first 2000 chars of what Step 2 LLM sees):**\n")
            f.write(f"```\n{r['trimmed_serialized_preview'][:2000]}\n```\n\n")

        # ================================================================
        # SECTION 7: MATCHED COLUMNS DETAIL
        # ================================================================
        f.write("---\n\n")
        f.write("## 7. Schema Matching Detail\n\n")

        f.write("This shows how the LLM's selected names map to the actual DataFrame schema.\n")
        f.write("Each entry is `parent_name → [inner_fields]` or `flat_column → None`.\n\n")

        for r in results:
            if "error" in r:
                continue
            f.write(f"### Q{r['num']}: {r['test_question']}\n\n")
            f.write("| Column | Type | Inner Fields |\n")
            f.write("|--------|------|-------------|\n")
            for parent, fields in r["matched_columns"].items():
                if fields is None:
                    f.write(f"| `{parent}` | flat | — |\n")
                else:
                    f.write(f"| `{parent}` | struct | {len(fields)} fields: {', '.join(f'`{f}`' for f in fields[:5])}{'...' if len(fields) > 5 else ''} |\n")
            f.write("\n")

    print(f"\n📄 Analysis report saved: {report_path}")
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{timestamp}_step1_parallel_analysis"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Step 1 Column Selection — PARALLEL Execution + LLM Output Analysis")
    print("=" * 70)
    print(f"CSV:       {CSV_FILE}")
    print(f"Model:     {SEMANTIC_MODEL_FILE}")
    print(f"Output:    {run_dir}")
    print(f"Questions: {len(TEST_QUESTIONS)}")
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
    print(f"🚀 Launching {len(TEST_QUESTIONS)} column selection queries in parallel (max {MAX_WORKERS} workers)...\n")

    results = [None] * len(TEST_QUESTIONS)  # Pre-allocate to preserve order
    total_sequential_time = 0.0
    t_wall_start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_idx = {}
        for i, q in enumerate(TEST_QUESTIONS):
            future = executor.submit(_run_single_column_selection, agent, q)
            future_to_idx[future] = i

        # Collect results as they complete
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            q = TEST_QUESTIONS[idx]
            try:
                result = future.result()
                results[idx] = result
                total_sequential_time += result["elapsed_seconds"]

                # Print progress
                key_check = _check_key_columns(result["selected_names"], q["key_columns"])
                all_found = all(key_check.values())
                icon = "✅" if all_found else "⚠️"
                print(
                    f"  {icon} Q{q['num']}: {result['selected_count']} names → "
                    f"{result['trimmed_df_column_count']} cols "
                    f"({result['elapsed_seconds']}s) "
                    f"[token saving: {result.get('token_saving_pct', 'N/A')}%]"
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
            # Don't save the full prompt text (too large) to individual JSONs
            save_result = {k: v for k, v in result.items() if k != "prompt_text"}
            json.dump(save_result, f, indent=2, ensure_ascii=False, default=str)

    # Save summary JSON
    summary = {
        "timestamp": timestamp,
        "test_type": "step1_parallel_analysis",
        "max_workers": MAX_WORKERS,
        "total_wall_time_seconds": round(total_wall_time, 2),
        "total_sequential_time_seconds": round(total_sequential_time, 2),
        "speedup_factor": round(total_sequential_time / max(total_wall_time, 0.1), 1),
        "config": {
            "csv_file": str(CSV_FILE),
            "semantic_model_file": str(SEMANTIC_MODEL_FILE),
            "column_selection_threshold": COLUMN_SELECTION_THRESHOLD,
            "pandasai_config": PANDASAI_CONFIG,
        },
        "results": [{k: v for k, v in r.items() if k != "prompt_text"} for r in results],
    }
    with open(run_dir / "step1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    # ---- SAVE PROMPT TEXTS (separate file — they're large) ----
    prompt_texts = {}
    for r in results:
        if r.get("prompt_text"):
            prompt_texts[r["num"]] = r["prompt_text"]
    with open(run_dir / "prompt_texts.json", "w", encoding="utf-8") as f:
        json.dump(prompt_texts, f, indent=2, ensure_ascii=False)

    # ---- WRITE ANALYSIS REPORT ----
    report_path = _write_analysis_report(run_dir, results, timestamp, total_wall_time, total_sequential_time)

    # ---- FINAL SUMMARY ----
    key_col_found = sum(
        1 for r in results
        if "error" not in r and all(_check_key_columns(r["selected_names"], r["key_columns"]).values())
    )
    errors = sum(1 for r in results if "error" in r)
    avg_selected = sum(r.get("selected_count", 0) for r in results) / len(results) if results else 0
    avg_trimmed = sum(r.get("trimmed_df_column_count", 0) for r in results) / len(results) if results else 0
    avg_token_saving = sum(r.get("token_saving_pct", 0) or 0 for r in results if "error" not in r) / max(len([r for r in results if "error" not in r]), 1)

    print(f"\n{'=' * 70}")
    print(f"Step 1 Column Selection — PARALLEL Results")
    print(f"{'=' * 70}")
    print(f"  Key cols found:   {key_col_found}/{len(TEST_QUESTIONS)}")
    print(f"  Avg selected:     {avg_selected:.1f} names")
    print(f"  Avg trimmed:      {avg_trimmed:.1f} columns")
    print(f"  Avg token saving: {avg_token_saving:.1f}%")
    print(f"  Wall time:        {total_wall_time:.1f}s (sequential: {total_sequential_time:.1f}s)")
    print(f"  Speedup:          {total_sequential_time / max(total_wall_time, 0.1):.1f}x")
    print(f"  Errors:           {errors}/{len(TEST_QUESTIONS)}")
    print(f"  Output:           {run_dir}")
    print(f"  Report:           {report_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
