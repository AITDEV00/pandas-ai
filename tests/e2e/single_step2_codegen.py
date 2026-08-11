"""Focused single-question Step 2 codegen test (thinking ON).

Runs one question through the full pipeline:
  column select (v33) -> single-shot codegen -> validate -> execute.
Prints the generated code + validation + execution result.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import pandasai as pai
from pandasai import Agent
from pandasai.config import ConfigManager
from server.core.llm_setup import setup_global_llm, setup_structured_llm

CSV_FILE = DATASETS_DIR / "20th may all hc data flattened.csv"
SEMANTIC_MODEL_FILE = DATASETS_DIR / "20th may column descriptions for pandasai.json"

PANDASAI_CONFIG = {
    "enrich_column_values": True,
    "auto_fill_descriptions": False,
    # Column selection mirrors codegen: ONLY temperature + top_p
    "column_selection_temperature": 0.1,
    "column_selection_top_p": 0.9,
    "column_selection_json_mode": True,
    "code_generation_temperature": 0.1,
    "code_generation_top_p": 0.9,
}


def build_agent():
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

    # Patch schema columns
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
    structured_llm = setup_structured_llm()
    if structured_llm is not None:
        agent_config["structured_llm"] = structured_llm
    agent = Agent([df], config=agent_config)
    return agent


def main():
    setup_global_llm()
    question = os.environ.get("STEP2_QUESTION", "Q28")
    QUESTIONS = {
        "Q28": "Average Salary of Senior Specialist in ADEO",
        "Q13a": "How many sick leaves did employee 1136 take in 2025?",
        "Q35": "Who has the longest service in ADEO?",
        "Q3b": "What are the main skills of employee 1137?",
    }
    query = QUESTIONS[question]
    print(f"Running single codegen (thinking per env) for {question}: {query}")

    agent = build_agent()
    state = agent._state

    from pandasai.core.column_selector import ColumnSelector
    sel = ColumnSelector(state)
    cache_buster = os.environ.get("COLUMN_SELECTION_CACHE_BUSTER", "").strip()
    run_query = f"{query}\n<!-- run:{cache_buster} -->" if cache_buster else query
    t0 = time.time()
    selected = sel.select(run_query)
    print(f"\nStep1 column selection: {len(selected)} names in {time.time()-t0:.2f}s")
    print("  SELECTED:", selected[:15], "...")
    print("  THINKING (col-sel):", (getattr(state, 'column_selection_thinking_trace', None) or "N/A")[:500])
    print(f"  THINKING enabled: {os.environ.get('STRUCTURED_LLM_THINKING')}")

    # Apply trimming
    df = state.dfs[0]
    matched = sel.match_names_to_schema(selected, df)
    matched = sel.ensure_essential_columns(matched, df, run_query)
    trimmed = sel.build_trimmed_dataframe(df, matched)
    state.dfs = [trimmed if i == 0 else d for i, d in enumerate(state.dfs)]
    print(f"  Trimmed to {len(trimmed.columns)} columns")

    # Step 2
    from pandasai.core.prompts import get_chat_prompt_for_sql
    from pandasai.core.code_generation.base import CodeGenerator
    state.memory.add(query, is_user=True)
    prompt = get_chat_prompt_for_sql(state)
    codegen = CodeGenerator(state)
    t1 = time.time()
    print(f"\nStep2: generating code (thinking={os.environ.get('CODE_GENERATION_THINKING')})...")
    try:
        code = codegen.generate_code(prompt)
        print(f"  ✅ Codegen OK in {time.time()-t1:.2f}s ({len(code)} chars)")
        print("  thinking (codegen):", (getattr(state, 'code_generation_thinking_trace', None) or "N/A")[:800])
    except Exception as e:
        print(f"  ❌ Codegen failed: {e}")
        print(traceback.format_exc())
        return

    print("\n" + "=" * 60)
    print("GENERATED CODE:")
    print("=" * 60)
    print(code)

    # Execute
    try:
        result = agent.execute_code(code)
        print("\n=== EXECUTION RESULT ===")
        if isinstance(result, dict):
            for k, v in result.items():
                if k == "value":
                    print(f"  value: {str(v)[:800]}")
                else:
                    print(f"  {k}: {v}")
        else:
            print(str(result)[:800])
        print("  ✅ EXECUTION OK")
    except Exception as e:
        print(f"\n  ❌ EXECUTION FAILED: {e}")
        print(traceback.format_exc()[-1200:])


if __name__ == "__main__":
    main()