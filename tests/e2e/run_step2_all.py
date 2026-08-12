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
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    # Structured (Step-1) selection: temp 0 + instructor (validated Pydantic).
    "column_selection_temperature": 0.0,
    "column_selection_json_mode": True,
    "column_selection_use_instructor": True,
    # Codegen (Step-2): temp 0.2 + thinking OFF (kills the reasoning loop).
    # The 0731 build loops its thinking chain when thinking is on; see .env.
    "code_generation_temperature": 0.2,
    # Structured codegen: request a bounded reasoning_trace + double_check + code
    # response validated by instructor. Middle ground between thinking-on (loops)
    # and thinking-off (quality collapse). Toggle via CODE_GENERATION_USE_INSTRUCTOR.
    "code_generation_use_instructor": (
        os.environ.get("CODE_GENERATION_USE_INSTRUCTOR", "true").lower() == "true"
    ),
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
        "llm_calls": [],          # NEW: per-LLM-call records
        "validators_passed": None,
        "validation_error": None,
        "executed": False,
        "execution_time": None,   # NEW: execution phase duration
        "execution_error": None,
        "executed_result": None,
        "failure_stage": None,
    }

    agent = build_agent()
    state = agent._state

    # NEW: wrap the state logger so we can capture every log line (which now
    # includes the per-LLM-call records) for inspection.
    captured_logs = []
    orig_logger = state.logger

    class _CaptureLogger:
        def log(self, msg):
            captured_logs.append(str(msg))
            if orig_logger is not None:
                orig_logger.log(msg)

    state.logger = _CaptureLogger()

    def _extract_llm_calls():
        """Pull [LLM-CALL] records and timing lines from captured logs."""
        calls = []
        for line in captured_logs:
            if line.startswith("[LLM-CALL]") or line.startswith("[ATTEMPT]"):
                calls.append(line)
        return calls

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

    # Step 2 (code generation)
    # Bust the codegen response cache by injecting a unique marker into the
    # question that is stored in memory and therefore embedded in the codegen
    # prompt (the prompt renders context.memory.last().get('message')). Set
    # CODEGEN_CACHE_BUSTER to a fresh value per run so an identical LLM prompt
    # is NOT served from the provider's response cache (which would replay the
    # previous run's code/timing). This is independent of the column-selection
    # buster (which uses run_query above).
    codegen_cache_buster = os.environ.get("CODEGEN_CACHE_BUSTER", "").strip()
    codegen_query = (
        f"{query}\n<!-- codegen_run:{codegen_cache_buster} -->"
        if codegen_cache_buster
        else query
    )
    state.memory.add(codegen_query, is_user=True)
    prompt = get_chat_prompt_for_sql(state)
    codegen = CodeGenerator(state)
    t1 = time.time()
    _cg_calls_before = len(_extract_llm_calls())
    # Optional production-style retry loop. Single-shot by default (isolates
    # first-try accuracy); set CODEGEN_RETRY=1 to measure the full
    # generate_code_with_retries loop (1 + max_retries attempts).
    _retry = os.environ.get("CODEGEN_RETRY", "").strip() == "1"
    try:
        if _retry:
            code = agent.generate_code_with_retries(query)
        else:
            code = codegen.generate_code(prompt)
        out["code"] = code
        out["codegen_time"] = round(time.time() - t1, 2)
        out["codegen_step_timings"] = getattr(
            state, 'code_generation_step_timings', None)
        out["codegen_thinking"] = getattr(state, 'code_generation_thinking_trace', None)
        out["codegen_structured_reasoning"] = getattr(
            state, 'code_generation_structured_reasoning', None)
        out["codegen_structured_double_check"] = getattr(
            state, 'code_generation_structured_double_check', None)
        out["codegen_structured_verification_checks"] = getattr(
            state, 'code_generation_structured_verification_checks', None)
        out["codegen_step_timings"] = getattr(
            state, 'code_generation_step_timings', None)
        out["validators_passed"] = True
    except Exception as e:
        out["code"] = getattr(state, 'last_code_generated', None)
        out["codegen_time"] = round(time.time() - t1, 2)
        out["codegen_step_timings"] = getattr(
            state, 'code_generation_step_timings', None)
        out["codegen_thinking"] = getattr(state, 'code_generation_thinking_trace', None)
        out["codegen_structured_reasoning"] = getattr(
            state, 'code_generation_structured_reasoning', None)
        out["codegen_structured_double_check"] = getattr(
            state, 'code_generation_structured_double_check', None)
        out["codegen_structured_verification_checks"] = getattr(
            state, 'code_generation_structured_verification_checks', None)
        out["validators_passed"] = False
        out["validation_error"] = str(e)
        out["failure_stage"] = "codegen"
        out["error_traceback"] = traceback.format_exc()
        out["codegen_llm_calls"] = _extract_llm_calls()[_cg_calls_before:]
        # restore real logger for the outer callers
        state.logger = orig_logger
        return out
    out["codegen_llm_calls"] = _extract_llm_calls()[_cg_calls_before:]

    # Execute (code execution is a separate phase — no LLM call, just sandbox run)
    t_exec = time.time()
    try:
        exec_result = agent.execute_code(out["code"])
        out["executed"] = True
        out["execution_time"] = round(time.time() - t_exec, 2)
        if isinstance(exec_result, dict):
            out["executed_result"] = {
                k: (str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v)
                for k, v in exec_result.items()
            }
        else:
            out["executed_result"] = str(exec_result)
    except Exception as e:
        out["execution_time"] = round(time.time() - t_exec, 2)
        out["execution_error"] = str(e)
        out["execution_traceback"] = traceback.format_exc()
        out["failure_stage"] = "execution"
    out["llm_calls"] = _extract_llm_calls()
    # restore real logger for outer callers
    state.logger = orig_logger
    return out


def _run_one_worker(q: dict) -> dict:
    """Module-level worker for process pools.

    Each question is self-contained (run_one builds its own agent/DataFrame),
    so we can run many in parallel. In a forked process each worker gets its own
    module-level _ATTEMPTS / captured_logs, so the per-LLM-call logging stays
    isolated. Also snapshot the global LLM setup so fork/spawn workers that
    don't inherit it still function.
    """
    try:
        from server.core.llm_setup import setup_global_llm
        setup_global_llm()
    except Exception:
        pass
    t_start = time.time()
    try:
        out = run_one(q)
    except Exception as e:
        out = {
            "num": q["num"], "test_question": q["test_question"],
            "error": str(e), "error_traceback": traceback.format_exc(),
            "failure_stage": "script_error", "executed": False,
        }
    out["elapsed_total"] = round(time.time() - t_start, 2)
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

    # Optional question filter: QUESTIONS=28,35 runs only those questions
    filter_env = os.environ.get("QUESTIONS", "").strip()
    if filter_env:
        filter_set = {p.strip().lstrip("Q").lower() for p in filter_env.split(",") if p.strip()}
        QUESTIONS_TO_RUN = [q for q in QUESTIONS if str(q["num"]).lower() in filter_set]
        print(f"QUESTIONS filter active: running only {[q['num'] for q in QUESTIONS_TO_RUN]}\n")
    else:
        QUESTIONS_TO_RUN = QUESTIONS

    failures = []
    all_results = []
    # Questions not yet done (skip ones with an existing per-question JSON).
    pending = []
    for q in QUESTIONS_TO_RUN:
        num = q["num"]
        existing_path = run_dir / f"Q{num}_gen.json"
        if existing_path.exists():
            print(f"Q{num}: {q['test_question'][:50]}... SKIP (already done)", flush=True)
            out = json.loads(existing_path.read_text(encoding="utf-8"))
            all_results.append(out)
            if not out.get("executed") or not out.get("validators_passed"):
                failures.append(out)
        else:
            pending.append(q)

    if pending:
        # Run the remaining questions concurrently. Each worker is a separate
        # forked process (isolated LLM/attempt logging) so N questions run in
        # parallel instead of serially.
        max_workers = int(os.environ.get("CODEGEN_CONCURRENCY", "4"))
        print(f"Running {len(pending)} questions concurrently (workers={max_workers})...", flush=True)
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            # preserve question order in results
            futs = {ex.submit(_run_one_worker, q): q for q in pending}
            for fut in as_completed(futs):
                q = futs[fut]
                num = q["num"]
                try:
                    out = fut.result()
                except Exception as e:
                    out = {
                        "num": num, "test_question": q["test_question"],
                        "error": str(e), "error_traceback": traceback.format_exc(),
                        "failure_stage": "worker_error", "executed": False,
                    }
                all_results.append(out)

                with open(run_dir / f"Q{num}_gen.json", "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
                _write_md(run_dir / f"Q{num}_gen.md", out)

                is_fail = not out.get("executed") or not out.get("validators_passed")
                status = "❌ FAIL" if is_fail else "✅ OK"
                print(f"    {status}  ({out.get('elapsed_total')}s)  "
                      f"trimmed={out.get('trimmed_cols')} "
                      f"validators={out.get('validators_passed')} "
                      f"exec={out.get('executed')} "
                      f"stage={out.get('failure_stage')}", flush=True)
                if is_fail:
                    failures.append(out)

                _write_progress(run_dir, failures)
        # restore input order for the summary
        order = {str(q["num"]): i for i, q in enumerate(QUESTIONS_TO_RUN)}
        all_results.sort(key=lambda o: order.get(str(o.get("num")), 999))

    # Final summary
    ok_exec = sum(1 for o in all_results if o.get("executed"))
    ok_val = sum(1 for o in all_results if o.get("validators_passed"))
    total_n = len(QUESTIONS_TO_RUN)
    print("\n" + "=" * 70)
    print(f"THINKING-ON CODEGEN RESULTS ({total_n} questions)")
    print("=" * 70)
    print(f"  Validators passed: {ok_val}/{total_n}")
    print(f"  Executed ok:       {ok_exec}/{total_n}")
    print(f"  Failures:          {len(failures)}")
    print(f"  Output:            {run_dir}")
    print("=" * 70)
    for o in all_results:
        timings = (o.get("codegen_step_timings") or [])
        tstr = ""
        if timings:
            t = timings[0]
            tstr = (f" llm={t.get('llm_call_s')}s req={t.get('code_validation_s')}s "
                    f"struct={t.get('structural_review_s')}s clean={t.get('cleaning_s')}s")
        print(f"  Q{o.get('num'):>3}  validators={'✅' if o.get('validators_passed') else '❌'} "
              f"exec={'✅' if o.get('executed') else '❌'}  "
              f"stage={o.get('failure_stage') or '-'}  "
              f"trimmed={o.get('trimmed_cols')}  {o.get('elapsed_total')}s{tstr}")
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
    lines.append(f"- **col-sel time**: {out.get('col_sel_time')}s | **codegen time**: {out.get('codegen_time')}s | **exec time**: {out.get('execution_time')}s")
    lines.append(f"- **validators passed**: {out.get('validators_passed')}")
    lines.append(f"- **executed**: {out.get('executed')}")

    # Per-LLM-call breakdown
    llm_calls = out.get("llm_calls") or out.get("codegen_llm_calls") or []
    if llm_calls:
        lines.append(f"\n## LLM calls ({len(llm_calls)})\n")
        for c in llm_calls:
            lines.append(f"    `{c}`")

    if out.get("executed_result"):
        lines.append(f"- **result**: `{out.get('executed_result')}`")
    if out.get("validation_error"):
        lines.append(f"- **validation/error**: {out.get('validation_error')}")
    if out.get("execution_error"):
        lines.append(f"- **execution error**: {out.get('execution_error')}")
    lines.append(f"\n## Generated code\n```python\n{out.get('code') or 'N/A'}\n```")
    ct = out.get("codegen_thinking")
    if ct:
        lines.append(f"\n## Codegen thinking trace\n```\n{ct}\n```")
    sr = out.get("codegen_structured_reasoning")
    if sr:
        lines.append(f"\n## Structured reasoning trace (Plan-and-Solve)\n```\n{sr}\n```")
    svc = out.get("codegen_structured_verification_checks")
    if svc:
        lines.append(f"\n## Verification checks (CoVe)\n```\n{svc}\n```")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_progress(run_dir: Path, failures: list):
    """Write a failures file + a short progress summary as questions complete."""
    with open(run_dir / "failures.json", "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()