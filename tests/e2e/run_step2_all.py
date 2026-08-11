"""Run thinking-ON codegen for ALL questions, logging each to a file.

- Each question logs its full output (code, thinking trace, validation, exec)
  directly to OUTPUT_DIR/Q<num>_codegen.json (and a readable .md).
- Any FIRST-TRY failure is also appended to OUTPUT_DIR/failures.json with the
  generated code + thinking trace, so failed attempts are easy to inspect.
- A running summary is written to OUTPUT_DIR/progress.jsonl after each question.

Usage:
  STRUCTURED_LLM_THINKING=false CODE_GENERATION_THINKING=true \
  STRUCTURED_LLM_MODEL_NAME="openai/deepseek-ai/DeepSeek-V4-Flash-0731" \
  OUTPUT_DIR=/tmp/codegen_on \
  python tests/e2e/run_step2_all.py
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "run" / "e2e_reports")))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"

PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
    # ONLY temperature=0.0 for deterministic output; all other sampling params
    # left unset to use model defaults.
    "column_selection_temperature": 0.0,
    "column_selection_json_mode": True,
    "code_generation_temperature": 0.0,
}

# All Step-1 questions (same set as test_step1_column_selection.py).
QUESTIONS = [
    {"num": "3b", "test_question": "What are the main skills of employee 1137?",
     "query": "What are the main skills of employee 1137?"},
    {"num": "3", "test_question": "What are this employee's main skills?",
     "query": ("Find employee with ID 1137. Return their name, employee ID, "
               "organizational unit, department/division, grade, years of service, "
               "tenure, and all their technical competencies/skills. Include "
               "competency ratings if available.")},
    {"num": "11", "test_question": "Give me the list of employees from human capital department",
     "query": ("List all employees working in the Human Capital Department. For each "
               "employee, show: Employee Name, Employee ID, Organizational Unit/Section, "
               "Grade, Date of Joining, Years of Service/Tenure, and Division. Sort by "
               "employee ID ascending. Include total count at the end.")},
    {"num": "12", "test_question": "Give me employees who speak chinese and have experience in AI",
     "query": ("Find all employees who have BOTH Chinese language skills AND any AI-related "
               "competency (including Artificial Intelligence, AI Implementation, AI Integration, "
               "Machine Learning, Deep Learning, Python, or similar AI/ML skills). For each "
               "employee show: Employee Name, Employee ID, Organizational Unit/Section, "
               "Department, Grade, Date of Joining, Years of Service, and list all their "
               "relevant skills including Chinese language proficiency and AI competencies. "
               "Sort by years of service descending.")},
    {"num": "13a", "test_question": "How many sick leaves did employee 1136 take in 2025?",
     "query": ("Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) "
               "in the year 2025. Count total number of sick leave days taken, list each "
               "leave record with start date, end date, and duration. Also include employee "
               "name and department if available.")},
    {"num": "15", "test_question": "What projects did Employee 982 work on compared to Employee 1177?",
     "query": ("Find all project information for Employee ID 982 and Employee ID 1177. For "
               "each employee, show their name, employee ID, organizational unit/department, "
               "grade, and list ALL projects they have been involved in including project name, "
               "project role, start date, end date, and project status/description if available. "
               "Compare their project portfolios side by side.")},
    {"num": "16", "test_question": "Which skills do they have in common?",
     "query": ("Find employees with IDs '0982' and '1177'. For each employee, return their "
               "name, employee ID, organizational unit, department, grade, and ALL their "
               "technical competencies/skills with competency ratings if available. Compare "
               "their skill sets side by side and identify any common skills they share.")},
    {"num": "19", "test_question": "Compare their education background.",
     "query": ("Find education details for employees with IDs '0982' and '1177'. For each "
               "employee, return their name, employee ID, organizational unit, department, "
               "grade, and ALL education information including degree/certification name, "
               "field of study, institution/university name, start date, end date/graduation "
               "date, and any additional education-related fields available in the system. "
               "Compare their education backgrounds side by side.")},
    {"num": "28", "test_question": "Average Salary of Senior Specialist in ADEO",
     "query": ("Find all employees who have \"Senior Specialist\" in their job title or "
               "position. For each employee, show: Employee Name, Employee ID, Grade, "
               "Position Title, Department, Division, Organizational Unit, Years of Service, "
               "and any salary-related fields available in the system (such as Salary Amount, "
               "Basic Salary, Total Compensation, Salary Band, Pay Grade, or similar "
               "compensation data). Calculate the average salary across all Senior Specialists "
               "if salary data exists. Sort by years of service descending.")},
    {"num": "35", "test_question": "Who has the longest service in ADEO?",
     "query": ("Find the employee(s) with the longest years of service/tenure at ADEO. "
               "Return Employee Name, Employee ID, Position Title, Grade, Department, "
               "Division, Organizational Unit, Date of Joining, Years of Service/Tenure "
               "(calculated), and Gender. Sort by tenure descending and show top 20 employees. "
               "Include the maximum tenure value found.")},
]


def build_agent():
    import pandasai as pai
    from pandasai import Agent
    from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
    from pandasai.helpers.type_determination import (
        parse_json_array_columns, is_list_struct_column,
    )
    from pandasai.helpers.semantic_matching import (
        get_matching_schema_columns, merge_descriptions,
    )
    from pandasai.data_loader.semantic_layer_schema import Column as SchemaColumn
    from pandasai.config import ConfigManager

    df = pai.read_csv(str(CSV_FILE))
    parse_json_array_columns(df)

    with open(SEMANTIC_MODEL_FILE, "r", encoding="utf-8") as f:
        semantic_model_dict = json.load(f)
    if "name" not in semantic_model_dict:
        semantic_model_dict["name"] = getattr(df, "_table_name", "uploaded_table")
    if "source" not in semantic_model_dict and "view" not in semantic_model_dict:
        semantic_model_dict["source"] = {"type": "csv", "path": str(CSV_FILE)}

    validated_schema = SemanticLayerSchema(**semantic_model_dict)
    df.schema = validated_schema

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
                            series, "list[struct]", 10, df.schema)
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
                            series, "list[struct]", 10, df.schema)
                        samples = result.get("samples")
                    new_col = SchemaColumn(
                        name=col_name, type="list[struct]", semantic_type="struct",
                        samples=samples, description=merged_desc)
                    new_schema_columns.append(new_col)
            else:
                if PANDASAI_CONFIG["enrich_column_values"] and exact_match is not None and exact_match.samples is None:
                    from pandasai.helpers.column_enrichment import ColumnValueExtractor
                    result = ColumnValueExtractor.classify_and_extract(
                        series, exact_match.type, 10, df.schema)
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

    global_config_obj = ConfigManager.get()
    agent_config = global_config_obj.model_dump()
    agent_config["llm"] = global_config_obj.llm
    agent_config.update(PANDASAI_CONFIG)
    structured_llm = None
    try:
        from server.core.llm_setup import setup_structured_llm
        structured_llm = setup_structured_llm()
    except Exception:
        structured_llm = None
    if structured_llm is not None:
        agent_config["structured_llm"] = structured_llm
    agent = Agent([df], config=agent_config)
    return agent


def run_one(q: dict) -> dict:
    """Run Step1 (v33 col-sel) + single-shot Step2 (thinking ON) for one question."""
    from pandasai.core.column_selector import ColumnSelector
    from pandasai.core.prompts import get_chat_prompt_for_sql
    from pandasai.core.code_generation.base import CodeGenerator

    query = q["query"]
    out = {
        "num": q["num"],
        "test_question": q["test_question"],
        "thinking_enabled": {"structured": os.environ.get("STRUCTURED_LLM_THINKING"),
                             "codegen": os.environ.get("CODE_GENERATION_THINKING")},
        "selected_names": [],
        "trimmed_columns": 0,
        "col_sel_thinking": None,
        "col_sel_time": None,
        "code": None,
        "codegen_thinking": None,
        "codegen_time": None,
        "validators_passed": None,
        "validation_error": None,
        "executed": False,
        "execution_error": None,
        "executed_result": None,
        "failure_stage": None,
    }

    agent = build_agent()
    state = agent._state

    # Step 1
    sel = ColumnSelector(state)
    cache_buster = os.environ.get("COLUMN_SELECTION_CACHE_BUSTER", "").strip()
    run_query = f"{query}\n<!-- run:{cache_buster} -->" if cache_buster else query
    t0 = time.time()
    try:
        selected = sel.select(run_query)
        out["selected_names"] = selected
        out["col_sel_time"] = round(time.time() - t0, 2)
        out["col_sel_thinking"] = getattr(state, 'column_selection_thinking_trace', None)
    except Exception as e:
        out["failure_stage"] = "step1"
        out["validation_error"] = f"Step1 col-sel failed: {e}"
        out["col_sel_thinking"] = getattr(state, 'column_selection_thinking_trace', None)
        return out

    # Apply trimming
    df = state.dfs[0]
    matched = sel.match_names_to_schema(selected, df)
    matched = sel.ensure_essential_columns(matched, df, run_query)
    trimmed = sel.build_trimmed_dataframe(df, matched)
    state.dfs = [trimmed if i == 0 else d for i, d in enumerate(state.dfs)]
    out["trimmed_cols"] = len(trimmed.columns)

    # Step 2
    state.memory.add(query, is_user=True)
    prompt = get_chat_prompt_for_sql(state)
    codegen = CodeGenerator(state)
    t1 = time.time()
    try:
        code = codegen.generate_code(prompt)
        out["code"] = code
        out["codegen_time"] = round(time.time() - t1, 2)
        out["codegen_thinking"] = getattr(state, 'code_generation_thinking_trace', None)
        out["validators_passed"] = True
    except Exception as e:
        out["code"] = getattr(state, 'last_code_generated', None)
        out["codegen_time"] = round(time.time() - t1, 2)
        out["codegen_thinking"] = getattr(state, 'code_generation_thinking_trace', None)
        out["validators_passed"] = False
        out["validation_error"] = str(e)
        out["failure_stage"] = "codegen"
        # Capture full traceback
        out["error_traceback"] = traceback.format_exc()
        return out

    # Execute
    try:
        exec_result = agent.execute_code(out["code"])
        out["executed"] = True
        if isinstance(exec_result, dict):
            out["executed_result"] = {
                k: (str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v)
                for k, v in exec_result.items()
            }
        else:
            out["executed_result"] = str(exec_result)
    except Exception as e:
        out["execution_error"] = str(e)
        out["execution_traceback"] = traceback.format_exc()
        out["failure_stage"] = "execution"
    return out


def main():
    from server.core.llm_setup import setup_global_llm
    setup_global_llm()

    run_dir = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_step2_thinking_on"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running thinking-ON codegen for {len(QUESTIONS)} questions")
    print(f"codegen_thinking={os.environ.get('CODE_GENERATION_THINKING')} "
          f"structured_thinking={os.environ.get('STRUCTURED_LLM_THINKING')}")
    print(f"Output: {run_dir}\n")

    failures = []
    all_results = []
    for i, q in enumerate(QUESTIONS):
        num = q["num"]
        print(f"[{i+1}/{len(QUESTIONS)}] Q{num}: {q['test_question'][:50]}... ", flush=True)
        t_start = time.time()
        try:
            out = run_one(q)
        except Exception as e:
            out = {
                "num": num, "test_question": q["test_question"],
                "error": str(e), "error_traceback": traceback.format_exc(),
                "failure_stage": "script_error", "executed": False,
            }
        out["elapsed_total"] = round(time.time() - t_start, 2)
        all_results.append(out)

        # Save per-question full JSON
        with open(run_dir / f"Q{num}_gen.json", "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False, default=str)
        # Save readable .md
        _write_md(run_dir / f"Q{num}_gen.md", out)

        # Track failures
        is_fail = not out.get("executed") or not out.get("validators_passed")
        status = "❌ FAIL" if is_fail else "✅ OK"
        print(f"    {status}  ({out.get('elapsed_total')}s)  "
              f"trimmed={out.get('trimmed_cols')} "
              f"validators={out.get('validators_passed')} "
              f"exec={out.get('executed')} "
              f"stage={out.get('failure_stage')}", flush=True)
        if is_fail:
            failures.append(out)

        # Write incremental progress + failures file
        _write_progress(run_dir, failures)

    # Final summary
    ok_exec = sum(1 for o in all_results if o.get("executed"))
    ok_val = sum(1 for o in all_results if o.get("validators_passed"))
    print("\n" + "=" * 70)
    print(f"THINKING-ON CODEGEN RESULTS ({len(QUESTIONS)} questions)")
    print("=" * 70)
    print(f"  Validators passed: {ok_val}/{len(QUESTIONS)}")
    print(f"  Executed ok:       {ok_exec}/{len(QUESTIONS)}")
    print(f"  Failures:          {len(failures)}")
    print(f"  Output:            {run_dir}")
    print("=" * 70)
    for o in all_results:
        print(f"  Q{o.get('num'):>3}  validators={'✅' if o.get('validators_passed') else '❌'} "
              f"exec={'✅' if o.get('executed') else '❌'}  "
              f"stage={o.get('failure_stage') or '-'}  "
              f"trimmed={o.get('trimmed_cols')}  {o.get('elapsed_total')}s")
    # Write final failures file
    with open(run_dir / "failures.json", "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2, ensure_ascii=False, default=str)
    if failures:
        print(f"\n  ⚠️ {len(failures)} failed first-try attempts saved to {run_dir / 'failures.json'}")


def _write_md(path: Path, out: dict):
    lines = []
    lines.append(f"# Q{out.get('num')}: {out.get('test_question')}\n")
    lines.append(f"- **thinking:** structured={out.get('thinking_enabled',{}).get('structured')} "
                 f"codegen={out.get('thinking_enabled',{}).get('codegen')}")
    lines.append(f"- **selected ({len(out.get('selected_names',[]))})**: {out.get('selected_names')}")
    lines.append(f"- **trimmed cols**: {out.get('trimmed_cols')}")
    lines.append(f"- **col-sel time**: {out.get('col_sel_time')}s | **codegen time**: {out.get('codegen_time')}s")
    lines.append(f"- **validators passed**: {out.get('validators_passed')}")
    lines.append(f"- **executed**: {out.get('executed')}")
    if out.get("executed_result"):
        lines.append(f"- **result**: `{out.get('executed_result')}`")
    if out.get("validation_error"):
        lines.append(f"- **validation/error**: {out.get('validation_error')}")
    lines.append(f"\n## Generated code\n```python\n{out.get('code') or 'N/A'}\n```")
    ct = out.get("codegen_thinking")
    if ct:
        lines.append(f"\n## Codegen thinking trace\n```\n{ct}\n```")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_progress(run_dir: Path, failures: list):
    """Write a failures file + a short progress summary as questions complete."""
    with open(run_dir / "failures.json", "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()