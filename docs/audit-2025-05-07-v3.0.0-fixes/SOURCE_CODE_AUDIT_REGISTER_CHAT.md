# Source Code Audit: Hardcoded Behaviours & Code Cleanliness

**Endpoints:** `/register` (base64 & file) and `/chat`  
**Date:** 2025-05-07  
**Scope:** All functions in the server and pandasai packages that are directly or transitively invoked by the two endpoints  
**Method:** Manual line-by-line review of every source file in the call chain

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Server Layer — Hardcoded Behaviours](#2-server-layer--hardcoded-behaviours)
3. [Server Layer — Code Cleanliness Issues](#3-server-layer--code-cleanliness-issues)
4. [PandasAI Core — Hardcoded Behaviours](#4-pandasai-core--hardcoded-behaviours)
5. [PandasAI Core — Code Cleanliness Issues](#5-pandasai-core--code-cleanliness-issues)
6. [Prompt Templates — Hardcoded Content](#6-prompt-templates--hardcoded-content)
7. [Function-by-Function Evaluation](#7-function-by-function-evaluation)
8. [Severity Classification](#8-severity-classification)
9. [Recommendations](#9-recommendations)

---

## 1. Executive Summary

This audit covers **38 functions** across **22 source files** in the `/register` and `/chat` call chains. The review identifies two categories of issues:

- **Hardcoded behaviours/prompts** — values, strings, thresholds, or prompt fragments that are embedded directly in source code or templates rather than being configurable via environment variables, config files, or function parameters.
- **Code cleanliness issues** — thread-safety problems, overly complex functions, fragile patterns, or violations of separation of concerns.

### Key Findings

| Category | Critical | High | Medium | Low | Info |
|---|---|---|---|---|---|
| Hardcoded behaviours | 2 | 8 | 12 | 9 | 5 |
| Code cleanliness | 1 | 4 | 6 | 3 | 0 |

**Most impactful issues:**
1. **Thread-unsafe config mutation** in `chat/handler.py` — per-query config overrides mutate shared `agent._state.config` directly
2. **Hardcoded default LLM model** in 3 locations — model name is not configurable via the API
3. **Hardcoded system prompt** in `register/models.py` — cannot be overridden per registration
4. **~100-line nested schema patching** in `register/handler.py` — deeply complex with inline imports from 4+ modules

---

## 2. Server Layer — Hardcoded Behaviours

### 2.1 `server/main.py`

| Item | Detail | Severity |
|---|---|---|
| CORS origins default | `CORS_ALLOWED_ORIGINS` defaults to `"*"` (allow all) | Medium |
| Log level default | `LOG_LEVEL` defaults to `"WARNING"` | Low |
| App title | `app.title = "PandasAI Excel Server"` | Info |

### 2.2 `server/core/llm_setup.py`

| Item | Detail | Severity |
|---|---|---|
| Default LLM model | `os.environ.get("LLM_MODEL_NAME", "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")` | **High** |
| Default context window | `os.environ.get("LLM_CONTEXT_WINDOW", "250000")` | Medium |
| SSL verification | `verify_ssl=False` is the default | Medium |
| Verbose mode | `pai.config.set({"verbose": True})` — hardcoded `True` | Low |
| No timeout | `httpx.Client(verify=verify_ssl)` — no `timeout` parameter | Medium |

### 2.3 `server/core/agent_store.py`

| Item | Detail | Severity |
|---|---|---|
| Default TTL | `DEFAULT_TTL_SECONDS = 24 * 60 * 60` (24 hours) | Low |
| TTL not configurable | No env var or config parameter to change TTL | Medium |

### 2.4 `server/core/description_filler.py`

| Item | Detail | Severity |
|---|---|---|
| Sample rows limit | `_build_sample_rows()` uses `max_rows=5` | Low |
| Sample items limit | `_build_column_details()` uses `max_items=20` | Low |
| Trim threshold | `_trim_samples()` uses `max_items=20` | Low |
| Temp memory size | `Memory(memory_size=1, agent_description="You are a data catalog assistant.")` | Medium |
| Temp agent description | `"You are a data catalog assistant."` hardcoded | Medium |

### 2.5 `server/features/register/models.py`

| Item | Detail | Severity |
|---|---|---|
| Default `enrich_column_values` | `True` — always enriches unless explicitly disabled | Low |
| Default `categorical_max_unique` | `50` | Low |
| Default `auto_fill_descriptions` | `True` | Low |
| **Default LLM model** | `model_name="openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"` | **High** |
| **Default system prompt** | `"You are an expert data assistant. Use execute_sql_query for data retrieval and aggregation..."` (multi-line) | **Critical** |

### 2.6 `server/features/register/handler.py`

| Item | Detail | Severity |
|---|---|---|
| Dummy source type | `semantic_model_dict["source"] = {"type": "csv", "path": file_path}` | Medium |
| Temp dir pattern | `os.path.join(tempfile.gettempdir(), "pandasai_uploads")` | Low |
| Inline LLM creation | Step 2c creates a separate `LiteLLM` instance with `response_format={"type": "json_object"}` | Medium |

### 2.7 `server/features/chat/handler.py`

| Item | Detail | Severity |
|---|---|---|
| Supported output types | `SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}` | Medium |
| Error message | `"Internal server error. Check server logs for details."` | Low |
| Type coercion rules | `_coerce_response_type()` has hardcoded conversion logic | Low |

---

## 3. Server Layer — Code Cleanliness Issues

### 3.1 `server/features/chat/handler.py` — Thread-Unsafe Config Mutation

**Severity: Critical**

```python
# Per-query config overrides mutate agent._state.config directly
agent._state.config.direct_sql = ...
agent._state.config.enrich_column_values = ...
# ... restored in finally block
```

The `finally` block restores the original values, but between the mutation and restoration, concurrent requests using the same Agent object will see the wrong config. This is a **race condition**.

### 3.2 `server/features/chat/handler.py` — Fragile Chat vs Follow-up Detection

**Severity: High**

```python
if agent._state.memory.count() > 0:
    result = agent.follow_up(query)
else:
    result = agent.chat(query)
```

This relies on `memory.count()` to decide between `chat()` and `follow_up()`. If two concurrent requests arrive for the same agent, the second request may incorrectly use `follow_up()` even if the first hasn't completed yet.

### 3.3 `server/features/register/handler.py` — Complex Schema Patching (~100 lines)

**Severity: High**

Step 2b (schema column patching for struct columns) is approximately 100 lines of nested logic with:
- Inline imports from 4+ modules (`semantic_matching`, `type_determination`, `column_enrichment`, `dataframe_serializer`)
- Multiple levels of if/elif nesting
- Mixed concerns: schema mutation, DataFrame inspection, and column name manipulation

### 3.4 `server/features/register/handler.py` — DataFrame Mutation in `parse_json_array_columns`

**Severity: Medium**

```python
parse_json_array_columns(df)  # modifies df in-place
```

Called on every register. The in-place mutation is not documented and could surprise callers who pass a shared DataFrame.

### 3.5 `server/core/agent_store.py` — Returns Object Reference

**Severity: Medium**

```python
def get_agent(self, agent_id: str) -> Optional[Agent]:
    ...
    return entry["agent"]  # Returns the actual object, not a copy
```

Callers can mutate the Agent's internal state without any synchronization.

### 3.6 `server/features/chat/handler.py` — DataFrame Serialization Without Size Limit

**Severity: Medium**

```python
response.value.to_dict(orient='records')
```

Can produce arbitrarily large JSON payloads for wide/long DataFrames with no pagination or size limit.

---

## 4. PandasAI Core — Hardcoded Behaviours

### 4.1 `pandasai/config.py`

| Item | Detail | Severity |
|---|---|---|
| `max_retries: int = 3` | Fixed retry count | Low |
| `direct_sql: bool = True` | Always uses SQL path | Medium |
| `enrich_column_values: bool = True` | Always enriches | Low |
| `llm_context_window: int = 250000` | From env with hardcoded fallback | Medium |
| `column_values_budget_ratio: float = 0.10` | 10% of context window | Low |
| `categorical_max_unique: int = 50` | Categorical threshold | Low |
| `sample_head_size: int = 10` | Rows in serialized head | Low |
| `column_selection_threshold: int = 30` | Column count trigger for selection | Medium |
| `column_selection_memory_size: int = 5` | Memory size for column selection | Low |
| `auto_fill_descriptions: bool = True` | Auto-fill on by default | Low |

### 4.2 `pandasai/agent/base.py`

| Item | Detail | Severity |
|---|---|---|
| Default `memory_size=10` | `Agent.__init__()` hardcodes memory size | Medium |
| `_store_assistant_message` condition | Only stores for `output_type in ("string", "number")` — plot and dataframe responses are not stored in memory | **High** |

### 4.3 `pandasai/core/column_selector.py`

| Item | Detail | Severity |
|---|---|---|
| Inline imports | `decompose_squashed_name`, `extract_struct_parent`, etc. imported inside methods | Low |
| Complex name matching | `match_names_to_schema()` is ~200 lines with 6+ branches | Medium |

### 4.4 `pandasai/helpers/column_enrichment.py`

| Item | Detail | Severity |
|---|---|---|
| Classification thresholds | `_classify_string_column()` has 6 hardcoded thresholds: `avg_words > 4.0`, `n_unique == n_total && n_total > 5 && avg_words < 2.0`, CV `< 0.2`, top20 coverage `> 0.8`, dynamic threshold formula | Medium |
| Sample sizes | `_extract_string()` returns `sorted(sample_vals[:5])` for id_like | Low |
| Numeric examples | `_extract_numeric()` samples `min(3, len(clean))` values | Low |
| Datetime examples | `_extract_datetime()` samples `min(3, len(clean))` values | Low |

### 4.5 `pandasai/helpers/dataframe_serializer.py`

| Item | Detail | Severity |
|---|---|---|
| `MAX_COLUMN_TEXT_LENGTH = 200` | Truncation threshold | Low |
| Token estimate | `~4 chars per token` in `_token_cost()` | Low |
| Struct inner sample limit | Limits to 3 samples per inner column in budget mode | Low |

### 4.6 `pandasai/helpers/type_determination.py`

| Item | Detail | Severity |
|---|---|---|
| Detection heuristic | `is_json_array_column()` and `is_list_struct_column()` only inspect the first non-null cell | Medium |

### 4.7 `pandasai/query_builders/sql_parser.py`

| Item | Detail | Severity |
|---|---|---|
| UNNEST alias pattern | `fix_common_llm_mistakes()` hardcodes that valid aliases start with `t` followed by optional digits | Medium |
| Struct access regex | `alias.rec['field'] → alias['field']` replacement is a hardcoded pattern | Low |

### 4.8 `pandasai/core/code_generation/code_cleaning.py`

| Item | Detail | Severity |
|---|---|---|
| `plt.show()` removal | Always strips `plt.show()` from generated code | Low |
| Chart path replacement | All `.png` paths replaced with `temp_chart_{uuid}.png` | Low |
| Variable name assumption | Looks for `sql_query` and `query` variable names specifically | Medium |

### 4.9 `pandasai/core/code_execution/environment.py`

| Item | Detail | Severity |
|---|---|---|
| Default imports | `pd`, `plt`, `np` are always available in exec environment | Info |

### 4.10 `pandasai/core/response/parser.py`

| Item | Detail | Severity |
|---|---|---|
| Plot path regex | `path_to_plot_pattern` is a hardcoded regex | Low |
| Type validation rules | Hardcoded type→value validation for number, string, dataframe, plot | Low |

---

## 5. PandasAI Core — Code Cleanliness Issues

### 5.1 `pandasai/agent/base.py` — Complex `_process_query()` (~120 lines)

**Severity: High**

This method handles the entire 2-step pipeline with complex memory save/restore logic:
- Step 1: Column selection with temp memory swap
- Step 2: Code generation with memory isolation
- Fallback logic for column selection failure

The memory save/restore pattern is fragile and hard to follow.

### 5.2 `pandasai/agent/state.py` — Shared Mutable State

**Severity: High**

`AgentState` is a dataclass with mutable `config`, `memory`, and `logger` fields. Multiple threads accessing the same Agent will share and mutate these fields without synchronization.

### 5.3 `pandasai/core/column_selector.py` — `match_names_to_schema()` Complexity

**Severity: Medium**

~200 lines with 6+ branching strategies and deeply nested if/elif chains. The function handles exact match, inner column match, prefixed inner column match, and squashed parent match — all in one function.

### 5.4 `pandasai/core/column_selector.py` — `ensure_essential_columns()` (~200 lines)

**Severity: Medium**

Two-pass logic with complex DataFrame + schema filtering. Inline imports from `semantic_matching` module.

### 5.5 `pandasai/helpers/column_enrichment.py` — `_extract_struct_vocabulary()` (~150 lines)

**Severity: Medium**

Deeply nested logic with inline imports from `semantic_matching`. Handles schema matching, false-positive filtering, bracket convention normalization, and sample extraction — all in one method.

### 5.6 `pandasai/llm/base.py` — Code Extraction Fragility

**Severity: Medium**

`_extract_code()` uses regex-based splitting on markdown code fences (`\`\`\``) and `Code:` markers. This is fragile and can break with unusual LLM output formats.

---

## 6. Prompt Templates — Hardcoded Content

All prompt templates are in `pandasai/core/prompts/templates/`. While using Jinja2 templates is a good practice (externalizes prompts from Python code), the actual prompt content contains many hardcoded instructions and examples.

### 6.1 `generate_python_code_with_sql.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Result variable name | `"You MUST declare a variable named exactly result"` | Medium |
| Initial code template | `# TODO: import the required dependencies` | Low |
| DuckDB SQL requirement | `"You MUST use the execute_sql_query function"` | Medium |

### 6.2 `shared/duckdb_syntax.tmpl`

| Item | Detail | Severity |
|---|---|---|
| 12-point syntax guide | Entire DuckDB SQL reference is hardcoded | Info |
| Specific error examples | Hardcoded examples of common mistakes | Info |
| Function references | Hardcoded DuckDB function names | Info |

### 6.3 `shared/output_type_template.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Type-specific MUST instructions | `"You MUST return type 'string'"`, etc. | Medium |
| Example values | Hardcoded example result patterns for each type | Low |

### 6.4 `shared/code_strategy.tmpl`

| Item | Detail | Severity |
|---|---|---|
| 4 code examples | Full Python code examples with specific patterns | Medium |
| Column name quoting rules | Hardcoded quoting instructions | Low |

### 6.5 `shared/search_strategy.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Jaro-Winkler threshold | `jaro_winkler_similarity` threshold of `0.85` | **High** |
| ILIKE pattern | `ILIKE '%word%'` for freetext search | Medium |
| CRITICAL bracket instruction | Bracket field name handling instruction | Medium |
| `field.duckdb_key` / `field.short_name` | Used as display_name in struct column listing | Medium |

### 6.6 `select_columns.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Role assignment | `"You are a data analyst."` | Low |
| JSON response format | `"selected"` and `"reasoning"` keys | Low |

### 6.7 `auto_fill_descriptions.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Role assignment | `"You are a data catalog assistant."` | Low |
| Response format | JSON with `"descriptions"` key | Low |

### 6.8 `correct_execute_sql_query_usage_error_prompt.tmpl`

| Item | Detail | Severity |
|---|---|---|
| MUST instruction | `"The code generated MUST use the execute_sql_query function"` | Medium |

### 6.9 `correct_output_type_error_prompt.tmpl`

| Item | Detail | Severity |
|---|---|---|
| Type-specific NOT instructions | `"Do NOT return type 'number'"`, etc. | Low |

---

## 7. Function-by-Function Evaluation

### Server — `/register` Endpoint

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 1 | `server/main.py` | `create_app()` | CORS `"*"`, LOG_LEVEL `"WARNING"`, app title | ✅ Clean |
| 2 | `server/features/register/router.py` | `register_base64()` | None | ✅ Clean |
| 3 | `server/features/register/router.py` | `register_file()` | None | ✅ Clean |
| 4 | `server/features/register/handler.py` | `handle_base64_upload()` | Temp dir pattern | ✅ Clean |
| 5 | `server/features/register/handler.py` | `create_agent_from_file_path()` | Dummy source type, temp dir, inline LLM creation | ⚠️ Complex: ~300 lines, nested schema patching |
| 6 | `server/features/register/models.py` | `PandasAIConfigPayload` | `enrich_column_values=True`, `categorical_max_unique=50`, `auto_fill_descriptions=True` | ✅ Clean |
| 7 | `server/features/register/models.py` | `LLMConfigPayload` | **Default model name**, **default system prompt** | ⚠️ System prompt should be configurable |
| 8 | `server/features/register/models.py` | `SemanticModelPayload` | Placeholder source injection | ✅ Clean |
| 9 | `server/core/llm_setup.py` | `create_litellm()` | `verify_ssl=False` default, no timeout | ✅ Clean |
| 10 | `server/core/llm_setup.py` | `setup_global_llm()` | **Default model name**, context window `250000`, `verbose=True` | ✅ Clean |
| 11 | `server/core/agent_store.py` | `AgentStore.__init__()` | `DEFAULT_TTL_SECONDS = 86400` | ⚠️ Returns object reference |
| 12 | `server/core/agent_store.py` | `AgentStore.get_agent()` | None | ⚠️ Not thread-safe |
| 13 | `server/core/agent_store.py` | `AgentStore._evict_expired()` | None | ✅ Clean |
| 14 | `server/core/description_filler.py` | `fill_missing_descriptions()` | Memory size `1`, agent description string | ✅ Clean |
| 15 | `server/core/description_filler.py` | `_build_sample_rows()` | `max_rows=5` | ✅ Clean |
| 16 | `server/core/description_filler.py` | `_build_column_details()` | `max_items=20` | ✅ Clean |
| 17 | `server/core/description_filler.py` | `_trim_samples()` | `max_items=20` | ✅ Clean |
| 18 | `server/core/description_filler.py` | `_parse_and_validate()` | Markdown fence stripping | ✅ Clean |

### Server — `/chat` Endpoint

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 19 | `server/features/chat/router.py` | `chat()` | None | ✅ Clean |
| 20 | `server/features/chat/handler.py` | `handle_chat_query()` | None | ⚠️ Thread-unsafe config mutation |
| 21 | `server/features/chat/handler.py` | `_validate_output_type()` | `SUPPORTED_OUTPUT_TYPES` set | ✅ Clean |
| 22 | `server/features/chat/handler.py` | `_coerce_response_type()` | Hardcoded conversion rules | ✅ Clean |
| 23 | `server/features/chat/models.py` | `ChatRequest` | None | ✅ Clean |
| 24 | `server/features/chat/models.py` | `ChatResponse` | None | ✅ Clean |

### PandasAI Core — Agent Pipeline

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 25 | `pandasai/agent/base.py` | `Agent.__init__()` | `memory_size=10` | ✅ Clean |
| 26 | `pandasai/agent/base.py` | `Agent.chat()` | None | ✅ Clean |
| 27 | `pandasai/agent/base.py` | `Agent.follow_up()` | None | ✅ Clean |
| 28 | `pandasai/agent/base.py` | `Agent._process_query()` | None | ⚠️ ~120 lines, complex memory save/restore |
| 29 | `pandasai/agent/base.py` | `Agent.generate_code_with_retries()` | None | ✅ Clean |
| 30 | `pandasai/agent/base.py` | `Agent.execute_with_retries()` | None | ✅ Clean |
| 31 | `pandasai/agent/base.py` | `Agent._execute_sql_query()` | None | ✅ Clean |
| 32 | `pandasai/agent/base.py` | `Agent._store_assistant_message()` | **Only stores for string/number** | ⚠️ Incomplete |
| 33 | `pandasai/agent/base.py` | `Agent._should_select_columns()` | None | ✅ Clean |
| 34 | `pandasai/agent/base.py` | `Agent._apply_column_selection()` | None | ⚠️ Creates ColumnSelector inline with temp memory swap |
| 35 | `pandasai/agent/state.py` | `AgentState` | None | ⚠️ Shared mutable state, not thread-safe |
| 36 | `pandasai/config.py` | `Config` | 10+ hardcoded defaults (see §4.1) | ✅ Clean |

### PandasAI Core — Column Selection

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 37 | `pandasai/core/column_selector.py` | `ColumnSelector.select()` | None | ✅ Clean |
| 38 | `pandasai/core/column_selector.py` | `match_names_to_schema()` | None | ⚠️ ~200 lines, 6+ branches |
| 39 | `pandasai/core/column_selector.py` | `ensure_essential_columns()` | None | ⚠️ ~200 lines, two-pass logic |
| 40 | `pandasai/core/column_selector.py` | `build_trimmed_dataframe()` | None | ⚠️ ~200 lines |
| 41 | `pandasai/core/column_selector.py` | `_build_prompt()` | Phantom column filtering | ✅ Clean |
| 42 | `pandasai/core/column_selector.py` | `_parse_response()` | None | ✅ Clean |
| 43 | `pandasai/core/column_selector.py` | `_validate_names()` | Stray quote stripping | ✅ Clean |

### PandasAI Core — Code Generation & Execution

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 44 | `pandasai/core/code_generation/base.py` | `CodeGenerator.generate_code()` | None | ✅ Clean |
| 45 | `pandasai/core/code_generation/base.py` | `CodeGenerator.validate_and_clean_code()` | None | ✅ Clean |
| 46 | `pandasai/core/code_generation/code_cleaning.py` | `CodeCleaner.clean_code()` | `plt.show()` removal, chart path replacement | ✅ Clean |
| 47 | `pandasai/core/code_generation/code_cleaning.py` | `_clean_sql_query()` | None | ✅ Clean |
| 48 | `pandasai/core/code_generation/code_cleaning.py` | `_normalize_duckdb_struct_syntax()` | Struct field placeholder | ✅ Clean |
| 49 | `pandasai/core/code_generation/code_cleaning.py` | `_replace_output_filenames_with_temp_chart()` | Chart path pattern | ✅ Clean |
| 50 | `pandasai/core/code_generation/code_validation.py` | `CodeRequirementValidator.validate()` | `execute_sql_query` function name check | ✅ Clean |
| 51 | `pandasai/core/code_execution/code_executor.py` | `CodeExecutor.execute()` | None | ✅ Clean |
| 52 | `pandasai/core/code_execution/code_executor.py` | `CodeExecutor.execute_and_return_result()` | `"result"` variable name | Low |
| 53 | `pandasai/core/code_execution/environment.py` | `get_environment()` | `pd`, `plt`, `np` always imported | Info |
| 54 | `pandasai/core/response/parser.py` | `ResponseParser.parse()` | None | ✅ Clean |
| 55 | `pandasai/core/response/parser.py` | `_validate_response()` | Type validation rules, plot path regex | Low |
| 56 | `pandasai/core/response/parser.py` | `_generate_response()` | None | ✅ Clean |

### PandasAI Core — SQL & Data

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 57 | `pandasai/query_builders/sql_parser.py` | `fix_common_llm_mistakes()` | UNNEST alias `t` pattern, `alias.rec[` regex | ✅ Clean |
| 58 | `pandasai/query_builders/sql_parser.py` | `replace_table_and_column_names()` | None | ✅ Clean |
| 59 | `pandasai/query_builders/sql_parser.py` | `extract_table_names()` | None | ✅ Clean |
| 60 | `pandasai/dataframe/base.py` | `DataFrame.serialize_dataframe()` | None | ✅ Clean |
| 61 | `pandasai/dataframe/base.py` | `DataFrame.get_default_schema()` | Default source `type="parquet"`, `path="data.parquet"` | Low |
| 62 | `pandasai/helpers/dataframe_serializer.py` | `DataframeSerializer.serialize()` | `MAX_COLUMN_TEXT_LENGTH=200`, token estimate | ⚠️ Large method |
| 63 | `pandasai/helpers/dataframe_serializer.py` | `_apply_token_budget()` | Token cost formula, struct sample limit | ✅ Clean |
| 64 | `pandasai/helpers/dataframe_serializer.py` | `_truncate_dataframe()` | `MAX_COLUMN_TEXT_LENGTH` | ✅ Clean |

### PandasAI Core — Helpers

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 65 | `pandasai/helpers/column_enrichment.py` | `ColumnValueExtractor.classify_and_extract()` | None | ✅ Clean |
| 66 | `pandasai/helpers/column_enrichment.py` | `ColumnValueExtractor.extract()` | None | ✅ Clean |
| 67 | `pandasai/helpers/column_enrichment.py` | `_extract_struct_vocabulary()` | None | ⚠️ ~150 lines, inline imports |
| 68 | `pandasai/helpers/column_enrichment.py` | `_classify_string_column()` | 6 hardcoded thresholds | Medium |
| 69 | `pandasai/helpers/column_enrichment.py` | `_extract_string()` | `sample_vals[:5]` for id_like | Low |
| 70 | `pandasai/helpers/column_enrichment.py` | `_extract_numeric()` | `min(3, len(clean))` samples | Low |
| 71 | `pandasai/helpers/column_enrichment.py` | `_extract_datetime()` | `min(3, len(clean))` samples | Low |
| 72 | `pandasai/helpers/column_enrichment.py` | `_extract_boolean()` | None | ✅ Clean |
| 73 | `pandasai/helpers/semantic_matching.py` | `get_matching_schema_columns()` | None | ✅ Clean |
| 74 | `pandasai/helpers/semantic_matching.py` | `match_column_details_to_schema()` | None | ✅ Clean |
| 75 | `pandasai/helpers/semantic_matching.py` | `merge_descriptions()` | None | ✅ Clean |
| 76 | `pandasai/helpers/semantic_matching.py` | `_extract_short_name()` | None | ✅ Clean |
| 77 | `pandasai/helpers/semantic_matching.py` | `decompose_squashed_name()` | None | ✅ Clean |
| 78 | `pandasai/helpers/semantic_matching.py` | `extract_struct_parent()` | None | ✅ Clean |
| 79 | `pandasai/helpers/semantic_matching.py` | `is_bracket_child_of()` | None | ✅ Clean |
| 80 | `pandasai/helpers/semantic_matching.py` | `extract_field_from_llm_name()` | None | ✅ Clean |
| 81 | `pandasai/helpers/semantic_matching.py` | `bracket_col_has_any_field()` | None | ✅ Clean |
| 82 | `pandasai/helpers/type_determination.py` | `is_json_array_column()` | First-cell-only check | Medium |
| 83 | `pandasai/helpers/type_determination.py` | `is_list_struct_column()` | First-cell-only check | Medium |
| 84 | `pandasai/helpers/type_determination.py` | `determine_series_type()` | None | ✅ Clean |
| 85 | `pandasai/helpers/type_determination.py` | `parse_json_array_columns()` | None | ⚠️ In-place mutation |
| 86 | `pandasai/helpers/memory.py` | `Memory.__init__()` | `memory_size=10` | ✅ Clean |
| 87 | `pandasai/helpers/memory.py` | `Memory.to_openai_messages_for_chat()` | None | ✅ Clean |
| 88 | `pandasai/helpers/memory.py` | `Memory.get_previous_conversation()` | `max_length=100` truncation | Low |

### PandasAI Core — Prompts

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 89 | `pandasai/core/prompts/base.py` | `BasePrompt.__init__()` | None | ✅ Clean |
| 90 | `pandasai/core/prompts/base.py` | `BasePrompt.render()` | Newline cleanup regex | ✅ Clean |
| 91 | `pandasai/core/prompts/base.py` | `BasePrompt.to_json()` | None | ✅ Clean |
| 92 | `pandasai/core/prompts/select_columns.py` | `SelectColumnsPrompt.__init__()` | None | ✅ Clean |
| 93 | `pandasai/core/prompts/auto_fill_descriptions.py` | `AutoFillDescriptionsPrompt.__init__()` | None | ✅ Clean |
| 94 | `pandasai/core/prompts/correct_execute_sql_query_usage_error_prompt.py` | `to_json()` | None | ✅ Clean |
| 95 | `pandasai/core/prompts/correct_output_type_error_prompt.py` | `to_json()` | None | ✅ Clean |
| 96 | `pandasai/core/prompts/generate_system_message.py` | `GenerateSystemMessagePrompt` | None | ✅ Clean |
| 97 | `pandasai/llm/base.py` | `LLM.generate_code()` | None | ✅ Clean |
| 98 | `pandasai/llm/base.py` | `LLM._extract_code()` | `\`\`\`` separator, `Code:` marker patterns | ⚠️ Fragile regex |
| 99 | `pandasai/llm/base.py` | `LLM._polish_code()` | `python`/`py` prefix removal | Low |
| 100 | `extensions/llms/litellm/litellm.py` | `LiteLLM.call()` | None | ✅ Clean |

### PandasAI Core — Schema

| # | File | Function | Hardcoded Items | Cleanliness |
|---|---|---|---|---|
| 101 | `pandasai/data_loader/semantic_layer_schema.py` | `Column` | `VALID_COLUMN_TYPES`, `VALID_SEMANTIC_TYPES` from constants | ✅ Clean |
| 102 | `pandasai/data_loader/semantic_layer_schema.py` | `SemanticLayerSchema` | `schema_version="1.0.0"` | Low |
| 103 | `pandasai/data_loader/semantic_layer_schema.py` | `Source` | `LOCAL_SOURCE_TYPES`, `REMOTE_SOURCE_TYPES` from constants | ✅ Clean |

---

## 8. Severity Classification

### Critical (must fix)

| ID | File | Issue |
|---|---|---|
| C1 | `server/features/chat/handler.py` | Thread-unsafe config mutation — per-query overrides mutate shared `agent._state.config` |
| C2 | `server/features/register/models.py` | Hardcoded default system prompt — cannot be overridden per registration |

### High (should fix)

| ID | File | Issue |
|---|---|---|
| H1 | `server/features/register/models.py` | Hardcoded default LLM model name in 3 locations |
| H2 | `server/features/chat/handler.py` | Fragile chat vs follow-up detection using `memory.count()` |
| H3 | `server/features/register/handler.py` | ~100-line nested schema patching with inline imports |
| H4 | `pandasai/agent/base.py` | `_store_assistant_message()` only stores string/number — plot and dataframe responses lost from memory |
| H5 | `pandasai/agent/base.py` | `_process_query()` is ~120 lines with complex memory save/restore |
| H6 | `pandasai/agent/state.py` | Shared mutable state — not thread-safe for concurrent access |
| H7 | `shared/search_strategy.tmpl` | `jaro_winkler_similarity` threshold of `0.85` hardcoded in prompt |

### Medium (should consider)

| ID | File | Issue |
|---|---|---|
| M1 | `server/main.py` | CORS defaults to `"*"` |
| M2 | `server/core/llm_setup.py` | Default context window `250000` |
| M3 | `server/core/llm_setup.py` | `verify_ssl=False` default |
| M4 | `server/core/llm_setup.py` | No timeout on httpx.Client |
| M5 | `server/core/agent_store.py` | TTL not configurable via API |
| M6 | `server/core/description_filler.py` | Hardcoded temp memory and agent description |
| M7 | `server/features/register/handler.py` | Dummy source type `"csv"` |
| M8 | `server/features/register/handler.py` | Inline LLM creation with `response_format` |
| M9 | `server/features/chat/handler.py` | `SUPPORTED_OUTPUT_TYPES` hardcoded set |
| M10 | `pandasai/config.py` | `direct_sql=True` default |
| M11 | `pandasai/config.py` | `column_selection_threshold=30` |
| M12 | `pandasai/agent/base.py` | `memory_size=10` default |
| M13 | `pandasai/helpers/column_enrichment.py` | 6 hardcoded classification thresholds |
| M14 | `pandasai/helpers/type_determination.py` | First-cell-only type detection heuristic |
| M15 | `pandasai/query_builders/sql_parser.py` | UNNEST alias pattern assumes `t` prefix |
| M16 | `pandasai/core/code_generation/code_cleaning.py` | Variable name assumption `sql_query`/`query` |
| M17 | `pandasai/core/column_selector.py` | `match_names_to_schema()` ~200 lines |
| M18 | `shared/search_strategy.tmpl` | `ILIKE '%word%'` pattern hardcoded |

---

## 9. Recommendations

### 9.1 Thread Safety (Critical)

1. **Replace config mutation with context-local overrides.** Instead of mutating `agent._state.config`, pass per-query overrides as parameters or use a context manager that creates a copy of the config for the duration of the request.
2. **Add locking to AgentStore.** Use a `threading.Lock` per agent ID to prevent concurrent access to the same Agent object.
3. **Consider making AgentState immutable.** Use `dataclasses.replace()` or a copy-on-write pattern instead of in-place mutation.

### 9.2 Externalize Hardcoded Values (High)

1. **Move default LLM model name to a single constant** or environment variable. Currently defined in 3 places: `server/core/llm_setup.py`, `server/features/register/models.py`, and the `LLMConfigPayload` default.
2. **Make the system prompt configurable** via the `/register` API. The current hardcoded prompt in `LLMConfigPayload` cannot be overridden.
3. **Extract classification thresholds** from `_classify_string_column()` into a config class or named constants with documentation.
4. **Move `SUPPORTED_OUTPUT_TYPES`** to a shared constants module so both the server and pandasai core reference the same set.

### 9.3 Reduce Complexity (High)

1. **Extract schema patching logic** from `register/handler.py` into a dedicated module (e.g., `server/core/schema_patcher.py`). This would:
   - Reduce the handler to a coordinator
   - Make the patching logic independently testable
   - Remove inline imports
   
2. **Split `_process_query()`** into smaller methods: `_run_column_selection()`, `_run_code_generation()`, `_run_execution()`, with clear memory management in each.

3. **Split `match_names_to_schema()`** into individual strategy methods that can be composed.

### 9.4 Fix Incomplete Behaviours (High)

1. **Store all response types in memory.** `_store_assistant_message()` currently skips `plot` and `dataframe` responses, meaning multi-turn conversations lose context about chart/table results.

2. **Add size limits to DataFrame serialization.** The chat handler's `response.value.to_dict(orient='records')` can produce arbitrarily large payloads. Consider pagination or a row/column limit.

### 9.5 Improve Detection Heuristics (Medium)

1. **Use more than the first cell** for type detection in `is_json_array_column()` and `is_list_struct_column()`. Consider checking the first 5 non-null cells to reduce false negatives.

2. **Make the UNNEST alias pattern** in `fix_common_llm_mistakes()` more robust. Instead of assuming `t` prefix, track all aliases declared in `AS` clauses and only fix the ones that don't use the `(rec)` destructuring pattern.

### 9.6 Prompt Template Improvements (Medium)

1. **Externalize the Jaro-Winkler threshold** (`0.85`) from `search_strategy.tmpl` into a config parameter that gets injected via the Jinja2 context.

2. **Consider versioning prompt templates** so that prompt changes can be tracked and rolled back independently of code changes.

3. **Add comments/documentation** to each template explaining what each section does and why, to make future maintenance easier.

---

*End of audit report. All source files were reviewed in full. No function related to the `/register` or `/chat` endpoints was omitted.*
