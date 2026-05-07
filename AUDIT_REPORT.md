# PandasAI Chat-Excel-Server — Comprehensive Codebase Audit

**Date**: 2026-05-07  
**Scope**: Server layer (FastAPI endpoints) → PandasAI framework (agent, prompts, helpers, query builders, data loader)  
**Goal**: Identify redundant functions, hardcoded values, logic gaps, default incoherences, and file-format fragility

---

## Executive Summary

The codebase is **functional and well-structured** using Vertical Slice Architecture. The core data flow (register → agent store → chat → LLM → SQL → response) is sound. However, the audit uncovered **3 critical bugs**, **5 high-priority issues**, and **8 medium-priority improvements**. The most impactful findings are:

1. **`Config.direct_sql` AttributeError** — referenced but doesn't exist
2. **Default incoherence** — `enrich_column_values` is `True` in Config but `False` in server payload; `llm_context_window` is 250000 vs 8192
3. **Chat handler loses actual response type** — always reports `"auto"` or the requested type, never the actual LLM-chosen type

---

## 1. Server Layer

### 1.1 `server/main.py` — ✅ CLEAN

- Clean FastAPI app factory pattern
- CORS middleware with wildcard origins (acceptable for internal service)
- Health check endpoint
- No issues

### 1.2 `server/core/llm_setup.py` — ⚠️ HARDCODED CREDENTIALS

| Finding | Severity | Detail |
|---------|----------|--------|
| Hardcoded API key | 🔴 Critical | `api_key="sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8"` is in source code |
| Hardcoded base URL | 🟡 Medium | `https://inference.adeoaiengine.ecouncil.ae/...` is hardcoded |
| Hardcoded model name | 🟡 Medium | `openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4` is hardcoded |

**Recommendation**: Move all credentials to environment variables. The `LLMConfigPayload` already supports `api_key`, `base_url`, `model_name` — `setup_global_llm()` should read from `os.environ` with fallback defaults.

### 1.3 `server/core/agent_store.py` — ✅ CLEAN

- Thread-safe singleton with `threading.Lock`
- Simple UUID → Agent mapping
- No memory leak protection (agents never evicted) — acceptable for current scope

### 1.4 `server/features/register/models.py` — 🔴 DEFAULT INCOHERENCE

| Field | `PandasAIConfigPayload` default | `Config` default | Verdict |
|-------|--------------------------------|------------------|---------|
| `enrich_column_values` | `False` | `True` | **MISMATCH** |
| `llm_context_window` | `8192` | `250000` | **MISMATCH** |
| `categorical_max_unique` | `50` | `50` | ✅ Match |

**Impact of `enrich_column_values=False`**: When the server creates a `PandasAIConfigPayload()` with default values, enrichment is disabled. The handler then does `agent_config.update(pandasai_config.model_dump())`, which overrides the global Config's `True` with `False`. This means **context extraction defaults to OFF when using the server** — contradicting the user's requirement that "context extraction is default to true throughout."

**Impact of `llm_context_window=8192`**: The token budget calculation in `DataframeSerializer._apply_token_budget()` uses `8192 * 0.10 = 819 tokens` instead of `250000 * 0.10 = 25000 tokens`. This severely truncates the vocabulary passed to the LLM.

**Fix**: Align `PandasAIConfigPayload` defaults with `Config`:
```python
enrich_column_values: bool = Field(True, ...)
llm_context_window: int = Field(250000, ...)
```

### 1.5 `server/features/register/handler.py` — 🟡 ISSUES

| Finding | Severity | Detail |
|---------|----------|--------|
| Duplicate enrichment logic | 🟡 Medium | Steps 2b and 3 both check `pandasai_config.enrich_column_values` and iterate over schema columns. Step 2b enriches and patches the schema; Step 3 just reads the already-enriched schema. If Step 2b were removed, Step 3 would need to do the enrichment — but currently Step 3 is dead code when enrichment is enabled (it just reads what 2b already wrote). This is logically correct but confusing. |
| Temp file cleanup | 🟡 Medium | `handle_base64_upload()` and `register_file()` write temp files but never clean them up. Over time, `/tmp/pandasai_uploads/` accumulates. |
| `parse_json_array_columns` side effect | 🟢 Low | Called on the DataFrame in-place. This mutates the data before schema validation, which is correct but undocumented. |

**Comment on enrichment flow**: The handler's Step 2b (schema patching + enrichment) and the serializer's lazy enrichment (`DataframeSerializer.serialize()` line ~87) are **both capable of enriching columns**. When `enrich_column_values=True`:
- Step 2b enriches schema columns during registration
- The serializer checks `col_dict.get("samples") is None` and re-enriches if missing

This means enrichment can happen **twice** for columns that Step 2b already enriched (because the serializer doesn't know the schema was pre-enriched). However, the second call is a no-op because `schema_col.samples` is already set, so `col_dict["samples"]` is not None. **Functionally correct, but wasteful.**

### 1.6 `server/features/register/router.py` — ✅ CLEAN

- Two endpoints (base64, file) both delegate to handler
- JSON parsing with validation
- Error handling is appropriate

### 1.7 `server/features/chat/handler.py` — 🔴 TYPE INFORMATION LOSS

| Finding | Severity | Detail |
|---------|----------|--------|
| Response type always "auto" | 🔴 Critical | `type: output_type or "auto"` reports the *requested* type, not the *actual* type. If `output_type=None` (auto), the response always says `"auto"`. If `output_type="dataframe"` but the LLM returned a string, the response incorrectly says `"dataframe"`. |
| `str(response)` loses DataFrame structure | 🟡 Medium | `response_str = str(response)` converts everything to string. For DataFrame responses, this gives an ugly `str()` representation instead of structured data. |

**Fix for type**: Extract the actual type from the response object:
```python
actual_type = getattr(response, 'type', output_type or 'auto')
return {
    "response": response_str,
    "type": actual_type,
    "last_code_executed": getattr(agent, "last_generated_code", None)
}
```

**Fix for DataFrame**: For dataframe type responses, serialize as JSON:
```python
if hasattr(response, 'type') and response.type == 'dataframe':
    response_data = response.value.to_dict(orient='records') if hasattr(response.value, 'to_dict') else str(response)
else:
    response_data = str(response) if response is not None else None
```

### 1.8 `server/features/chat/models.py` — ✅ CLEAN

- Simple request/response models
- `output_type` is Optional — correct for auto-detection

---

## 2. PandasAI Agent Layer

### 2.1 `pandasai/agent/base.py` — 🟡 ISSUES

| Finding | Severity | Detail |
|---------|----------|--------|
| `start_new_conversation()` clears memory on every `chat()` | 🟡 Medium | `chat()` calls `start_new_conversation()` which calls `clear_memory()`. This means **every chat turn starts from scratch** — no multi-turn memory. `follow_up()` doesn't clear memory, but the server only uses `chat()`. If multi-turn is desired, the server should use `follow_up()` for subsequent turns. |
| `last_generated_code` vs `last_code_executed` | 🟢 Low | Both properties return `self._state.last_code_generated`. The `last_code_executed` property is misleading — it returns the generated code, not the code that was actually executed (which could differ after retries). |
| `_execute_sql_query` creates new `DuckDBConnectionManager` per call | 🟢 Low | Each SQL execution creates a fresh `DuckDBConnectionManager()` and re-registers all DataFrames. This is safe but slightly wasteful. For a chat session with multiple queries, a persistent connection manager would be more efficient. |
| `generate_code_with_retries` catches exception then retries | 🟡 Medium | The first `generate_code()` call is outside the while loop. If it fails, the exception is caught and the while loop starts. But the while loop calls `_regenerate_code_after_error()` which can also fail. The retry counting is correct but the flow is confusing — the first attempt is special-cased. |

### 2.2 `pandasai/agent/state.py` — ✅ MOSTLY CLEAN

| Finding | Severity | Detail |
|---------|----------|--------|
| `_config` dataclass default | 🟢 Low | `_config: Union[Config, dict] = field(default_factory=dict)` — the `__post_init__` converts dict to Config, but the default is an empty dict which becomes `Config()` (all defaults). This works but is indirect. |

---

## 3. Core Prompts & Templates

### 3.1 `pandasai/core/prompts/base.py` — ✅ CLEAN

- Jinja2 Environment without `trim_blocks`/`lstrip_blocks` — consistent with `{%-` whitespace control in templates
- 3+ newline collapse to 2 — good for LLM readability
- `to_json()` correctly extracts system_prompt from `memory.agent_description`

### 3.2 `pandasai/core/prompts/generate_python_code_with_sql.py` — 🔴 BROKEN ATTRIBUTE

| Finding | Severity | Detail |
|---------|----------|--------|
| `context.config.direct_sql` | 🔴 Critical | Line 25 references `context.config.direct_sql` but `Config` has no `direct_sql` field. This will raise `AttributeError` when `to_json()` is called. |

**Impact**: The `to_json()` method is used for logging/debugging, not for the LLM call itself. The LLM call uses `instruction.to_string()` which calls `render()`. So this bug only manifests if someone calls `to_json()` — but it's still a runtime error waiting to happen.

**Fix**: Either add `direct_sql: bool = True` to `Config`, or remove the `direct_sql` key from `to_json()`.

### 3.3 Template Files

| Template | Status | Notes |
|----------|--------|-------|
| `generate_python_code_with_sql.tmpl` | ✅ | Includes duckdb_syntax, sql_functions, code_strategy, output_type_template, search_strategy, dataframe, vectordb_docs |
| `correct_execute_sql_query_usage_error_prompt.tmpl` | ✅ | Includes code_strategy — good for error recovery |
| `correct_output_type_error_prompt.tmpl` | ✅ | Includes code_strategy — good for error recovery |
| `shared/duckdb_syntax.tmpl` | ✅ | 12 rules, Rule 3 now correct (pp['field'] ✅, pp.rec['field'] ❌) |
| `shared/code_strategy.tmpl` | ✅ | No hardcoded column names, generic placeholders |
| `shared/sql_functions.tmpl` | ✅ | Declares `execute_sql_query` function |
| `shared/output_type_template.tmpl` | ✅ | Conditional output type based on `output_type` variable |
| `shared/search_strategy.tmpl` | ✅ | Dynamic rendering with struct fields, freetext, categorical, id_like |
| `shared/vectordb_docs.tmpl` | ✅ | Conditional on vectorstore |
| `shared/dataframe.tmpl` | ✅ | Delegates to serializer |

### 3.4 `pandasai/core/prompts/__init__.py` — ✅ CLEAN

- Three factory functions for the three prompt types
- Correct parameter passing

---

## 4. Helpers

### 4.1 `pandasai/helpers/dataframe_serializer.py` — 🟡 ISSUES

| Finding | Severity | Detail |
|---------|----------|--------|
| `df.sample(n=sample_size, random_state=42)` | 🟡 Medium | Uses `sample()` instead of `head()` for row display. This means the LLM sees random rows, not the first rows. For data where the first rows are most representative (e.g., sorted data), this could be misleading. The `random_state=42` makes it deterministic but still random. |
| Token budget calculation | 🟢 Low | Uses `len(json.dumps(...)) // 4` as rough token estimate. This is reasonable but could over/under-count for non-ASCII text (Arabic, etc.) where token ratios differ. |
| `_apply_token_budget` complexity | 🟢 Low | The budget allocation logic (under/over split, proportional distribution) is correct but complex. Consider simplifying if not needed. |

### 4.2 `pandasai/helpers/column_enrichment.py` — ✅ CLEAN

- `classify_and_extract()` is the single entry point — no redundant classification
- `_classify_string_column()` uses 6 signals (paragraph, id_like, absolute cap, frequency, log-ratio, fallback) — robust
- `_extract_struct_vocabulary()` flattens all structs into a temp DataFrame — correct approach
- `extract()` is the legacy entry point still used by `_extract_struct_vocabulary` for inner columns — not redundant, just two levels of dispatch

### 4.3 `pandasai/helpers/memory.py` — 🟡 ISSUE

| Finding | Severity | Detail |
|---------|----------|--------|
| `get_last_message()` uses `self._memory_size` | 🟡 Medium | `get_last_message()` calls `get_messages(self._memory_size)` which returns the last N messages. But `_memory_size` defaults to 1 in `Memory.__init__()` and is set to 10 in `AgentState.initialize()`. The template calls `{{ context.memory.get_last_message() }}` — this returns only the last message from the window, which is correct. But if `memory_size=1`, it returns only 1 message. The default `memory_size=1` in `Memory.__init__()` seems too low. |
| `to_openai_messages()` duplicates system prompt | 🟢 Low | Both `to_openai_messages()` and the LiteLLM `call()` method add the system prompt. LiteLLM checks `memory.agent_description` and adds it. But `to_openai_messages()` is not actually used by LiteLLM — it's a utility method. No actual duplication at runtime. |

### 4.4 `pandasai/helpers/semantic_matching.py` — ✅ CLEAN

- Four matching strategies (exact, inner, prefixed inner, squashed parent)
- `merge_descriptions()` correctly combines descriptions from multiple matches
- No hardcoded column names

### 4.5 `pandasai/helpers/type_determination.py` — ✅ CLEAN

- `is_list_struct_column()` — cheap first-cell check
- `is_json_array_column()` — cheap first-cell check with JSON parse
- `parse_json_array_columns()` — in-place transformation
- `determine_series_type()` — maps pandas dtypes to semantic types
- All functions are used, none are redundant

---

## 5. Query Builders

### 5.1 `pandasai/query_builders/sql_parser.py` — ✅ CLEAN

| Fix | Status | Notes |
|-----|--------|-------|
| Fix 1: Schema-driven column name correction | ✅ | Only fixes bracket-enclosed names |
| Fix 2: Wrong UNNEST alias pattern | ✅ | Replaces non-t aliases with t(rec) |
| Fix 3: alias.rec['field'] → alias['field'] | ✅ | New fix, catches pp.rec['field'] |

| Finding | Severity | Detail |
|---------|----------|--------|
| Fix 2 overwrites all non-t aliases | 🟢 Low | If the LLM writes `AS pe`, Fix 2 renames it to `AS t(rec)`. This works for single-UNNEST queries but could collide if there are multiple UNNESTs with non-t aliases (both become `t(rec)`). However, this is extremely rare and Fix 3 handles the common case. |
| `replace_table_and_column_names` uses sqlglot | 🟢 Low | Falls back gracefully when sqlglot can't parse DuckDB syntax. The bypass is correct. |

---

## 6. Data Loader & DataFrame

### 6.1 `pandasai/dataframe/base.py` — ✅ MOSTLY CLEAN

| Finding | Severity | Detail |
|---------|----------|--------|
| `get_dialect()` defaults to `"postgres"` | 🟡 Medium | When `source` is None, the dialect defaults to `"postgres"`. But the actual execution engine is DuckDB. This dialect is used by `DataframeSerializer.serialize()` and passed to the `<table>` XML tag. The LLM sees `dialect="postgres"` but the actual SQL is DuckDB. This is a minor inconsistency — the `duckdb_syntax.tmpl` template overrides the dialect hint, so the LLM still generates DuckDB SQL. But it's misleading. |
| `get_default_schema()` doesn't detect list[struct] | 🟢 Low | When no semantic model is provided, `get_default_schema()` creates Column objects with `type=DataFrame.get_column_type(dtype)`. For list[struct] columns, `get_column_type()` returns `None` because pandas dtype is `object`. The handler patches this in Step 2b, so it's not a bug — but it means the default schema is incomplete until patched. |

### 6.2 `pandasai/data_loader/semantic_layer_schema.py` — ✅ CLEAN

- Comprehensive validation (column types, semantic types, expressions, source types)
- `Column` model supports `samples` and `semantic_type` — used by enrichment
- `Source` model validates local vs remote requirements

---

## 7. Config, Constants & Defaults Coherence

### 7.1 Default Values Matrix

| Parameter | `Config` | `PandasAIConfigPayload` | `setup_global_llm` | Verdict |
|-----------|----------|------------------------|---------------------|---------|
| `enrich_column_values` | `True` | `False` | N/A | 🔴 **MISMATCH** |
| `llm_context_window` | `250000` | `8192` | N/A | 🔴 **MISMATCH** |
| `column_values_budget_ratio` | `0.10` | N/A | N/A | Only in Config |
| `column_values_token_budget` | `None` | `None` | N/A | ✅ Match |
| `categorical_max_unique` | `50` | `50` | N/A | ✅ Match |
| `sample_head_size` | `10` | N/A | N/A | Only in Config |
| `max_retries` | `3` | N/A | N/A | Only in Config |
| `verbose` | `False` | N/A | `True` | 🟡 Config overridden by setup |
| `model_name` | N/A | `openai//Qwen3.5-35B...` | Same hardcoded | 🟡 Duplicated |

### 7.2 `pandasai/constants.py` — ✅ CLEAN

- `VALID_COLUMN_TYPES` includes `"list[struct]"` — correct
- `VALID_SEMANTIC_TYPES` includes `"categorical"`, `"freetext"`, `"id_like"`, `"struct"` — correct
- `LOCAL_SOURCE_TYPES` = `["csv", "parquet"]` — correct

---

## 8. LLM Layer

### 8.1 `pandasai/llm/base.py` — ✅ CLEAN

- `_extract_code()` handles markdown code blocks
- `_polish_code()` strips leading `python`/`py` markers
- `generate_code()` calls `call()` then `_extract_code()`

### 8.2 `extensions/llms/litellm/litellm.py` — ✅ CLEAN

- Uses `completion()` with messages array
- System prompt from `memory.agent_description`
- Previous conversation as multi-turn messages (excluding last — it's in the template)
- Final user message is the rendered template
- `**self.params` passes through sampling parameters

---

## 9. Code Execution & Response

### 9.1 `pandasai/core/code_execution/code_executor.py` — ✅ CLEAN

- `exec()` with environment dict
- `add_to_env()` for injecting `execute_sql_query`
- `execute_and_return_result()` reads `result` from environment

### 9.2 `pandasai/core/code_generation/code_cleaning.py` — ✅ CLEAN

- AST-based code cleaning
- Removes `execute_sql_query` redefinitions
- Replaces chart paths with temp paths
- Validates table names via sqlglot (with fallback for DuckDB-specific syntax)

### 9.3 `pandasai/core/code_generation/code_validation.py` — ✅ CLEAN

- Validates that `execute_sql_query` is called
- AST visitor pattern for function call collection

### 9.4 `pandasai/core/response/parser.py` — ✅ CLEAN

- Validates result dict has `type` and `value`
- Type-specific validation (number → int/float, string → str, etc.)
- Returns typed response objects

---

## 10. File-Format Agnosticism Assessment

The codebase handles CSV and Excel files through two entry points:

| Path | CSV | Excel | Verdict |
|------|-----|-------|---------|
| `pai.read_csv()` | ✅ | ❌ | Used for CSV |
| `pai.read_excel()` | ❌ | ✅ | Used for Excel |
| `parse_json_array_columns()` | ✅ | ✅ | Works on any DataFrame |
| `is_list_struct_column()` | ✅ | ✅ | Checks first non-null cell |
| `ColumnValueExtractor` | ✅ | ✅ | Works on any Series |
| `DataframeSerializer` | ✅ | ✅ | Works on any DataFrame |
| `search_strategy.tmpl` | ✅ | ✅ | Dynamic rendering from schema |
| `duckdb_syntax.tmpl` | ✅ | ✅ | No file-format-specific rules |

**Verdict**: The codebase is **fully agnostic** to the input file format. The only file-format-specific code is in `handler.py` which chooses `read_csv` vs `read_excel` based on mimetype. All downstream processing is format-agnostic.

**Edge case**: If an Excel file has multiple sheets, `pai.read_excel()` reads only the first sheet. This is a pandas default and is acceptable for the current scope.

---

## 11. Summary of Action Items

### 🔴 Critical (Must Fix)

| # | File | Issue | Fix |
|---|------|-------|-----|
| C1 | `server/features/register/models.py` | `enrich_column_values=False` contradicts Config default `True` | Change to `Field(True, ...)` |
| C2 | `server/features/register/models.py` | `llm_context_window=8192` contradicts Config default `250000` | Change to `Field(250000, ...)` |
| C3 | `pandasai/core/prompts/generate_python_code_with_sql.py` | `context.config.direct_sql` — AttributeError | Add `direct_sql: bool = True` to `Config` or remove from `to_json()` |

### 🟡 High Priority (Should Fix)

| # | File | Issue | Fix |
|---|------|-------|-----|
| H1 | `server/features/chat/handler.py` | Response type always `"auto"` — loses actual type | Use `getattr(response, 'type', ...)` |
| H2 | `server/core/llm_setup.py` | Hardcoded API key and base URL | Read from environment variables |
| H3 | `server/features/chat/handler.py` | `str(response)` loses DataFrame structure | Serialize DataFrames as JSON records |
| H4 | `pandasai/agent/base.py` | `chat()` clears memory — no multi-turn | Server should use `follow_up()` for turns 2+, or don't clear memory on `chat()` |
| H5 | `pandasai/dataframe/base.py` | `get_dialect()` returns `"postgres"` when no source | Default to `"duckdb"` since that's the actual engine |

### 🟢 Medium Priority (Nice to Have)

| # | File | Issue | Fix |
|---|------|-------|-----|
| M1 | `server/features/register/handler.py` | Temp files never cleaned up | Add cleanup after agent creation or periodic sweep |
| M2 | `pandasai/agent/base.py` | `last_code_executed` returns generated code, not executed | Rename or track separately |
| M3 | `pandasai/helpers/dataframe_serializer.py` | `df.sample()` vs `df.head()` for LLM context | Consider `head()` for deterministic first-row visibility |
| M4 | `pandasai/helpers/memory.py` | `Memory.__init__` default `memory_size=1` | Align with `AgentState.initialize()` default of 10 |
| M5 | `server/features/register/handler.py` | Enrichment can run twice (handler + serializer) | Add flag to skip serializer enrichment when schema is pre-enriched |

---

## 12. Redundancy Check

| Function/Method | Used By | Redundant? |
|-----------------|---------|------------|
| `ColumnValueExtractor.extract()` | `_extract_struct_vocabulary()` for inner columns | No — legacy entry point, still needed |
| `ColumnValueExtractor.classify_and_extract()` | Handler Step 2b, serializer | No — preferred entry point with single-pass classification |
| `Memory.to_openai_messages()` | Not used by LiteLLM (it builds its own) | ⚠️ Potentially dead code — LiteLLM builds messages manually |
| `BasePrompt.to_string()` vs `__str__()` | Both return cached render | Minimal — to_string caches, __str__ delegates to to_string |
| `Agent.last_generated_code` vs `Agent.last_code_executed` | Both return same state | ⚠️ Misleading duplicate — see H2 |
| `GenerateSystemMessagePrompt` | `LLM.get_system_prompt()` | ⚠️ Not used by LiteLLM — it reads `memory.agent_description` directly |

---

## 13. Robustness Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **SQL auto-fix** | ✅ Strong | 3 fixes (brackets, UNNEST alias, .rec pattern) + sqlglot bypass |
| **Type detection** | ✅ Strong | `is_list_struct_column()`, `is_json_array_column()`, `determine_series_type()` |
| **Column enrichment** | ✅ Strong | 6-signal classifier, struct vocabulary extraction, token budget |
| **Error recovery** | ✅ Strong | Retry loop with error-specific prompts (output type vs execution error) |
| **File format agnostic** | ✅ Strong | All processing is DataFrame-based, no format-specific logic |
| **Default coherence** | 🔴 Weak | `enrich_column_values` and `llm_context_window` mismatch between server and framework |
| **Multi-turn conversation** | 🟡 Weak | `chat()` clears memory every time; server doesn't use `follow_up()` |
| **Response fidelity** | 🟡 Weak | Type info lost, DataFrames stringified |
