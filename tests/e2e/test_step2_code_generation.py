"""Step 2 Code Generation E2E Test — Single-Shot on Trimmed Schema

Tests ONLY the Step 2 code-generation pipeline in isolation, after Step 1
column selection has produced a trimmed DataFrame/schema.

For each test question, this script:
  1. Registers a fresh Agent with the enterprise HC dataset + semantic model
     (exactly like test_step1_column_selection.py, using the v33 template /
     DeepSeek non-thinking structured LLM for column selection)
  2. Runs Step 1 column selection to get a trimmed DataFrame
  3. Runs Step 2 code generation ONCE (single-shot, no retries) against the
     trimmed DataFrame
  4. Validates the generated code:
       - CodeRequirementValidator (execute_sql_query must be used)
       - StructuralCodeValidator (no fabricated struct names/fields, no placeholders)
       - CodeCleaner output
       - Actual execution succeeds and returns a typed `result` dict

This isolates Step 2 quality: how often the coding LLM produces valid,
schema-correct, runnable code on the FIRST attempt given a good trimmed schema.

Prerequisites:
  - .env file configured with LLM credentials
  - Enterprise HC dataset files in datasets/

Usage:
  poetry run python tests/e2e/test_step2_code_generation.py

  # Custom output directory
  OUTPUT_DIR=/tmp/step2_results poetry run python tests/e2e/test_step2_code_generation.py
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

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
PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
    # ONLY temperature=0.0 for deterministic output; rest use model defaults.
    "column_selection_temperature": 0.0,
    "column_selection_json_mode": True,
    "code_generation_temperature": 0.0,
}


# ---------------------------------------------------------------------------
# Test Questions
# ---------------------------------------------------------------------------

# Reuses the same questions as the Step 1 test so the two stages are aligned.
# For Step 2 we focus on questions that produce concrete, executable results:
#   - code_ok: the "type" the final result dict should have (string/number/dataframe)
TEST_QUESTIONS: List[Dict] = [
    {
        "num": "13a",
        "test_question": "How many sick leaves did employee 1136 take in 2025?",
        "pandasai_input": (
            "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) "
            "in the year 2025. Count total number of sick leave days taken, list each "
            "leave record with start date, end date, and duration. Also include employee "
            "name and department if available."
        ),
        "expected_result_type": "number",
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
        "expected_result_type": "number",
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
        "expected_result_type": "string",
    },
]


# ---------------------------------------------------------------------------
# Registration (mirrors server/features/register/handler.py)
# ---------------------------------------------------------------------------

def _register_agent_with_data():
    """Register an Agent with the enterprise HC dataset.

    Mirrors the server's create_agent_from_file_path() logic and the Step 1
    test. Also injects:
      - structured_llm: the model used for Step 1 column selection (v33, non-thinking)
      - llm: the model used for Step 2 code generation
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
    # uses the model under test (DeepSeek non-thinking via v33) rather than the
    # main code-generation LLM.
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
# Step 2 Code Generation Test
# ---------------------------------------------------------------------------

def _apply_column_selection(agent, query: str) -> Dict[str, Any]:
    """Run Step 1 column selection, returning trimmed-DF info + matched columns.

    Mirrors _apply_column_selection() in agent/base.py but does NOT run Step 2.
    The agent's _state.dfs is left with the trimmed DataFrame.
    """
    from pandasai.core.column_selector import ColumnSelector

    state = agent._state
    selector = ColumnSelector(state)

    t_start = time.time()
    selected_names = selector.select(query)
    elapsed = time.time() - t_start

    df = state.dfs[0]
    matched = selector.match_names_to_schema(selected_names, df)
    matched = selector.ensure_essential_columns(matched, df, query)
    trimmed_df = selector.build_trimmed_dataframe(df, matched)

    # Swap trimmed DF into state (exactly what _apply_column_selection does)
    trimmed_dfs = [trimmed_df if i == 0 else d for i, d in enumerate(state.dfs)]
    state.dfs = trimmed_dfs

    thinking_trace = getattr(state, 'column_selection_thinking_trace', None)

    return {
        "selected_names": selected_names,
        "matched_columns": {k: v for k, v in matched.items()},
        "trimmed_df_columns": list(trimmed_df.columns),
        "trimmed_df_column_count": len(trimmed_df.columns),
        "elapsed_seconds": round(elapsed, 2),
        "thinking_trace": thinking_trace,
    }


def _run_single_step2(agent, query: str, expected_type: str) -> Dict[str, Any]:
    """Run Step 2 code generation ONCE on the current (trimmed) state.

    Returns a dict with the generated code, raw response, thinking trace,
    validation results, and (if it executes) the parsed result.
    """
    from pandasai.core.prompts import get_chat_prompt_for_sql
    from pandasai.core.code_generation.base import CodeGenerator

    state = agent._state

    # Add the query to memory so the prompt includes it (mirrors generate_code)
    state.memory.add(query, is_user=True)

    prompt = get_chat_prompt_for_sql(state)
    state.last_prompt_used = prompt

    codegen = CodeGenerator(state)

    result = {
        "expected_result_type": expected_type,
        "prompt": prompt.to_string(),
        "code": None,
        "cleaned_code": None,
        "thinking_trace": None,
        "raw_response": None,
        "validators_passed": None,
        "validation_error": None,
        "executed": False,
        "execution_error": None,
        "executed_result": None,
        "elapsed_seconds": None,
        "trimmed_df_column_count": len(state.dfs[0].columns) if state.dfs else 0,
    }

    t_start = time.time()
    try:
        code = codegen.generate_code(prompt)
        result["code"] = code
        result["cleaned_code"] = code
        result["raw_response"] = getattr(state, 'code_generation_raw_llm_response', None)
        result["thinking_trace"] = getattr(state, 'code_generation_thinking_trace', None)
        result["elapsed_seconds"] = round(time.time() - t_start, 2)
        result["validators_passed"] = True
        # Note: CodeGenerator.generate_code already ran requirement +
        # structural validators + cleaner internally. Reaching here means they
        # all passed.
    except Exception as e:
        result["code"] = getattr(state, 'last_code_generated', None)
        result["validation_error"] = str(e)
        result["thinking_trace"] = getattr(state, 'code_generation_thinking_trace', None)
        result["elapsed_seconds"] = round(time.time() - t_start, 2)
        result["validators_passed"] = False
        result["error_traceback"] = traceback.format_exc()
        return result

    # Now try to actually execute the cleaned code against the trimmed schema.
    try:
        exec_result = agent.execute_code(result["cleaned_code"])
        result["executed"] = True
        result["executed_result"] = _serialize_exec_result(exec_result)
    except Exception as e:
        result["execution_error"] = str(e)
        result["execution_traceback"] = traceback.format_exc()

    return result


def _serialize_exec_result(exec_result) -> Any:
    """Best-effort serialize an execution result for JSON output."""
    if exec_result is None:
        return None
    if isinstance(exec_result, dict):
        return {
            k: (str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v)
            for k, v in exec_result.items()
        }
    if hasattr(exec_result, "to_dict"):
        return exec_result.to_dict()
    return str(exec_result)


def _print_step2(q: Dict, result: Dict):
    """Pretty-print a single Step 2 test result."""
    num = q["num"]
    print(f"\n{'─' * 60}")
    print(f"Q{num}: {q['test_question'][:70]}...")
    print(f"  Expected result type: {q['expected_result_type']}")
    print(f"  Trimmed columns: {result['trimmed_df_column_count']}")
    print(f"  Validators passed: {'✅' if result['validators_passed'] else '❌'}  ({result['elapsed_seconds']}s)")

    if result["code"]:
        print(f"  Generated code ({len(result['code'])} chars):")
        for line in result["code"].splitlines()[:15]:
            print(f"    {line}")
        if len(result["code"].splitlines()) > 15:
            print(f"    ... ({len(result['code'].splitlines()) - 15} more lines)")

    if result.get("executed"):
        print(f"  Executed: ✅")
        print(f"  Result: {result['executed_result']}")
    elif result.get("execution_error"):
        print(f"  Executed: ❌  ({result['execution_error'][:120]})")


def _write_markdown_report(run_dir: Path, results: List[Dict], timestamp: str):
    """Write a human-readable Markdown report."""
    report_path = run_dir / "step2_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Step 2 Code Generation E2E Report\n\n")
        f.write(f"**Date:** {timestamp}\n")
        f.write(f"**CSV:** `{CSV_FILE.name}`\n")
        f.write(f"**Semantic Model:** `{SEMANTIC_MODEL_FILE.name}`\n\n")

        f.write("## Summary\n\n")
        f.write("| # | Question | Validators | Executed | Result | Time |\n")
        f.write("|---|----------|------------|----------|--------|------|\n")
        for q, result in zip(TEST_QUESTIONS, results):
            v_ok = "✅" if result.get("validators_passed") else "❌"
            e_ok = "✅" if result.get("executed") else "❌"
            f.write(
                f"| {q['num']} | {q['test_question'][:40]}... | {v_ok} | {e_ok} | "
                f"{result.get('execution_error') or 'ok'} | {result.get('elapsed_seconds')}s |\n"
            )
        f.write("\n")

        f.write("## Detailed Results\n\n")
        for q, result in zip(TEST_QUESTIONS, results):
            f.write(f"### Q{q['num']}: {q['test_question']}\n\n")
            f.write(f"- **Expected result type:** `{q['expected_result_type']}`\n")
            f.write(f"- **Trimmed columns ({result.get('trimmed_df_column_count')}):**\n")
            for col in result.get("trimmed_df_columns", []):
                f.write(f"  - `{col}`\n")
            f.write(f"- **Validators passed:** {result.get('validators_passed')}\n")
            f.write(f"- **Generated code:**\n```python\n{result.get('code') or 'N/A'}\n```\n\n")
            if result.get("execution_error"):
                f.write(f"- **Execution error:** {result['execution_error']}\n")
            if result.get("executed_result"):
                f.write(f"- **Executed result:**\n```\n{result['executed_result']}\n```\n\n")
            trace = result.get("thinking_trace")
            if trace:
                f.write(f"- **Thinking trace:**\n```\n{trace}\n```\n\n")


def _save_results(run_dir: Path, results: List[Dict], timestamp: str):
    for q, result in zip(TEST_QUESTIONS, results):
        outfile = run_dir / f"Q{q['num']}_step2.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    summary = {
        "timestamp": timestamp,
        "test_type": "step2_code_generation",
        "config": {
            "csv_file": str(CSV_FILE),
            "semantic_model_file": str(SEMANTIC_MODEL_FILE),
            "column_selection_threshold": COLUMN_SELECTION_THRESHOLD,
            "column_values_budget_ratio": COLUMN_VALUES_BUDGET_RATIO,
            "pandasai_config": PANDASAI_CONFIG,
        },
        "results": results,
    }
    with open(run_dir / "step2_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    _write_markdown_report(run_dir, results, timestamp)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{timestamp}_step2_code_generation"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Step 2 Code Generation E2E Test (Single-Shot)")
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

    # Run Step 1 + Step 2 for each question (fresh agent per question so the
    # trimmed schema and conversation memory are isolated).
    results = []
    for i, q in enumerate(TEST_QUESTIONS):
        num = q["num"]
        print(f"\n{'═' * 60}")
        print(f"Q{num}/{len(TEST_QUESTIONS)}: {q['test_question'][:60]}...")
        print(f"  Query: {q['pandasai_input'][:80]}...")

        try:
            # Fresh agent per question to isolate state.
            q_agent = _register_agent_with_data()
            q_state = q_agent._state

            # Cache-buster: avoid prompt-keyed inference cache for the 
            # column selection call.
            cache_buster = os.environ.get("COLUMN_SELECTION_CACHE_BUSTER", "").strip()
            run_query = q["pandasai_input"]
            if cache_buster:
                run_query = f"{run_query}\n<!-- run:{cache_buster} -->"

            # Step 1: column selection (trims q_state.dfs)
            step1 = _apply_column_selection(q_agent, run_query)

            # Step 2: single-shot code generation + validation
            result = _run_single_step2(q_agent, run_query, q["expected_result_type"])
            result.update({
                "step1": step1,
                "test_question": q["test_question"],
            })
            result["trimmed_df_columns"] = step1["trimmed_df_columns"]
            result["trimmed_df_column_count"] = step1["trimmed_df_column_count"]

            _print_step2(q, result)
            results.append(result)

        except Exception as e:
            print(f"  ❌ Error: {e}")
            traceback.print_exc()
            results.append({
                "query": q["pandasai_input"],
                "test_question": q["test_question"],
                "expected_result_type": q["expected_result_type"],
                "error": str(e),
                "validators_passed": False,
                "executed": False,
                "code": None,
            })

    # Save results
    _save_results(run_dir, results, timestamp)

    # Print final summary
    validators_ok = sum(1 for r in results if r.get("validators_passed"))
    executed_ok = sum(1 for r in results if r.get("executed"))
    errors = sum(1 for r in results if "error" in r)
    print(f"\n{'=' * 70}")
    print(f"Step 2 Code Generation Results (Single-Shot)")
    print(f"{'=' * 70}")
    print(f"  Validators passed: {validators_ok}/{len(TEST_QUESTIONS)}")
    print(f"  Executed ok:       {executed_ok}/{len(TEST_QUESTIONS)}")
    print(f"  Errors:            {errors}/{len(TEST_QUESTIONS)}")
    print(f"  Output:            {run_dir}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()