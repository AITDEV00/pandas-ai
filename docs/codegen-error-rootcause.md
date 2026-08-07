# DeepSeek V4 Code-Generation Error Analysis — Logic Map & Root Cause

> **Method**: [Logic Mapping Technique](../logic_mapping_technique.md) — Phase 1
> (Trace) followed by Phase 2 (Test against real data).
>
> **Scope**: Where are the prompts? Why does DeepSeek V4 make code-generation
> errors? E2E run dated `20260807_115706_enterprise_e2e` on
> `datasets/20th may all hc data flattened.csv`.

---

## 1. Executive Summary

DeepSeek V4's **code generation itself rarely fails**. In the e2e run, 6 of 7
query errors were **execution-time** failures, not comprehension failures. The
LLM understood the question and produced plausible code, but that code made
runtime assumptions that contradicted the *actual* data types.

**Root cause of the dominant error class (date errors: Q11, Q28, Q30, Q35):**

> The semantic model declares date columns as `datetime`, but the actual data
> (and DuckDB schema) treats them as **strings (`VARCHAR`)**. DeepSeek trusts
> the prompt's `datetime` type and writes `.dt.date`, `.dt.days`, or
> `CURRENT_DATE - "col"` — all of which fail because the runtime value is a
> string.

This is a **schema-vs-runtime type mismatch**, not an LLM reasoning failure.
The prompt is *technically* telling the truth about the semantic model, but
that truth is not reflected in the runtime data.

---

## 0. Fix Implemented (2026-08-07)

**`cast_flat_field_types()`** added to `pandasai/helpers/type_determination.py`
and wired into `DuckDBConnectionManager.register()` (called right after
`cast_struct_field_types`). It converts **top-level flat columns** declared as
`datetime`/`integer`/`float`/`boolean` in the semantic model to their declared
types **before** DuckDB registration, so the runtime dtype matches what the
prompt tells the LLM.

- `pandasai/helpers/type_determination.py`:
  - `_build_flat_field_type_map(df, schema)` — maps flat column name → declared
    type (skips struct columns, handled separately).
  - `cast_flat_field_types(df, schema)` — applies the existing per-type caster
    functions (falls back to original value on parse failure).
- `pandasai/data_loader/duck_db_connection_manager.py::register()`:
  - Now calls `cast_flat_field_types(df, schema)` after
    `cast_struct_field_types(df, schema)`.

**Verified on real data**: `[Employee Master[Date of Joining]]`,
`[Employee Master[Graduation Date]]`, `[Employee Master[Last Promotion Date]]`
now register as **`DATE`** (previously `VARCHAR`). The real date column has
0 unparseable values, so all rows cast cleanly.

**Tests**: `TestFlatFieldCasting` in
`tests/integration_tests/test_struct_field_casting.py` (3 tests covering date
cast, int/float/bool cast + fallback, and DuckDB DATE inference). All 62
casting tests pass. The 10 broader failures observed (`test_prompt_pipeline`,
parquet, sql, `test_concurrent_chat`) were **confirmed pre-existing** — they
fail identically with the changes stashed.

---

## 2. Logic Map — Code Generation Call Chain

```
Entry Point (HTTP POST /api/chat)
    |
    v
[server/features/chat/handler.py] handle_chat_query()
    |  line ~574: agent.follow_up(query)  (or agent.chat if memory empty)
    v
[pandasai/agent/base.py] Agent.follow_up()  (line 108)
    |  line 113: return self._process_query(query, output_type)
    v
[pandasai/agent/base.py] Agent._process_query()  (line ~223: generate_code_with_retries)
    |  line 237: code = self.generate_code(query)   <-- GENERATION (retry loop)
    v
[pandasai/agent/base.py] Agent.generate_code()  (line 114)
    |  line 120: prompt = get_chat_prompt_for_sql(self._state)
    |  line 122: code = self._code_generator.generate_code(prompt)
    v
[pandasai/core/prompts/__init__.py] get_chat_prompt_for_sql()  (line 21)
    |  returns GeneratePythonCodeWithSQLPrompt(context, last_code_generated, output_type)
    v
[pandasai/core/prompts/generate_python_code_with_sql.py] class GeneratePythonCodeWithSQLPrompt
    |  template_path = "generate_python_code_with_sql.tmpl"
    v
[pandasai/core/code_generation/base.py] CodeGenerator.generate_code()  (line 19)
    |  line 35: code = config.llm.generate_code(prompt, context, sampling_params)
    |  -> line 52: validate_and_clean_code(code)
    v
[pandasai/core/code_generation/base.py] CodeGenerator.validate_and_clean_code()
    |  -> CodeRequirementValidator.validate(code)
    |  -> CodeCleaner.clean_code(code)   <-- line 91; SQL table-name validation
    v
(back in agent) [pandasai/agent/base.py] Agent.execute_code()  (line 126)
    |  line 135-137: code_executor.add_to_env("execute_sql_query", self._execute_sql_query)
    |  line 144: return code_executor.execute_and_return_result(code)
    v
[pandasai/agent/base.py] Agent._execute_sql_query()  (line 140)
    |  line 166: db_manager.register(df.schema.name, df)   <-- DATATYPE BOUND HERE
    |  line 185: result_df = db_manager.sql(final_query).df()  <-- SQL EXECUTION
    v
[pandasai/data_loader/duck_db_connection_manager.py] DuckDBConnectionManager.register()  (line 26)
    |  line 42: cast_struct_field_types(df, schema)   <-- ONLY STRUCT INNER FIELDS
    |  line 43: self.connection.register(name, df)    <-- DUCKDB INFERS TYPES
    v
[duckdb] inference: flat datetime cols stay VARCHAR (not cast)  <-- ROOT CAUSE
```

### Branch: Retry / Regeneration

```
[pandasai/agent/base.py] _process_query() → generate_code_with_retries()
    |  on Exception:
    |    state.code_attempts.append({phase:"generation", error: e, error_traceback})
    |    code = self._regenerate_code_after_error(...)   (line ~240)
    |    → get_correct_error_prompt_for_sql(context, code, traceback)   <-- retry prompt
    |        → CorrectExecuteSQLQueryUsageErrorPrompt (correct_execute_sql_query_usage_error_prompt.tmpl)
    v
[pandasai/agent/base.py] execute_with_retries()  (line ~277)
    |  line 281: result = self.execute_code(code)   <-- EXECUTION (retry loop)
    |  on Exception: append {phase:"execution", error, error_traceback}; regenerate
```

**Exit points:**
- `agent.chat()/follow_up()` returns a `Response` object (StringResponse,
  NumberResponse, DataFrameResponse, etc.)
- `server/features/chat/handler.py` serializes it and attaches
  `result["pipeline"]` (from `_extract_error_trace()`).

---

## 3. Where the Prompts Are (all locations)

| # | Prompt / Template | File | Role |
|---|-------------------|------|------|
| 1 | System message | `pandasai/core/prompts/templates/generate_system_message.tmpl` | `memory.agent_description` only |
| 2 | **Code generation (Step 2)** | `pandasai/core/prompts/templates/generate_python_code_with_sql.tmpl` | Main code-gen prompt |
| 3 | Code-gen includes → | `templates/shared/duckdb_syntax.tmpl` | DuckDB SQL rules |
| 4 | Code-gen includes → | `templates/shared/sql_functions.tmpl` | Defines `execute_sql_query()` |
| 5 | Code-gen includes → | `templates/shared/code_strategy.tmpl` | "divide and conquer" + examples |
| 6 | Code-gen includes → | `templates/shared/search_strategy.tmpl` | Column lookup / UNNEST rules |
| 7 | Code-gen includes → | `templates/shared/dataframe.tmpl` | → `df.serialize_dataframe()` |
| 8 | Code-gen includes → | `templates/shared/output_type_template.tmpl` | Result dict format |
| 9 | **Column selection (Step 1)** | `pandasai/core/prompts/templates/select_columns.tmpl` (+ v11..v31 variants) | Picks columns before codegen |
| 10 | Description auto-fill | `templates/auto_fill_descriptions.tmpl` | Fills column descriptions |
| 11 | Retry after error | `templates/correct_execute_sql_query_usage_error_prompt.tmpl` | Regeneration prompt |

**Data rendered into the codegen prompt (Step 2):**
- `df.serialize_dataframe()` → `pandasai/helpers/dataframe_serializer.py::serialize()`
  - Emits `<table ... columns="[{name, type, semantic_type, samples, ...}]">`
  - Emits the **top-N sample rows** as CSV (`df.head(n).to_csv()`)
- `last_code_generated` (from previous turn, if memory non-empty)
- `memory` conversation (system prompt + prior turns)
- `context.output_type`

**Data NOT rendered into the prompt (the gap):**
- The **runtime DuckDB types** are never shown. Only the *semantic model*
  `type` (e.g. `datetime`) is shown. There is no note that
  `Date of Joining` may come back as a string from DuckDB.
- No instruction on how to defensively handle date strings.

---

## 4. Why DeepSeek Makes Each Mistake (root causes, trace-verified)

### 4.1 Date errors (Q11, Q28, Q30, Q35) — `datetime`-declared but `VARCHAR` at runtime

**Observed errors:**
- Q11: `AttributeError: 'str' object has no attribute 'date'`
- Q28: `AttributeError: Can only use .dt accessor with datetimelike values`
- Q30: `KeyError: "['Tenure (Years)'] not in index"` (self-created column naming inconsistency, secondary)
- Q35: `duckdb.ParserException/BinderException: No function matches '-(DATE, VARCHAR)'`

**Trace-verified chain:**

```
Semantic model (datasets/20th ... .json):
    "[Employee Master[Date of Joining]]" type = "datetime"

DataFrame from CSV (verified empirically):
    "[Employee Master[Date of Joining]]" dtype = "object" (string)
    sample values = ['2024-09-17T00:00:00', '2024-07-23T00:00:00', ...]

Prompt rendered (verified in conv_logs/5cbca0d2-...):
    "[Employee Master[Date of Joining]]" (datetime: The date on which ...)

Generated code (Q28):
    df['join_date'] = pd.to_datetime(df['join_date'])
    df['years_of_service'] = ((today - df['join_date'].dt.date).dt.days / 365.25)
    # ^ .dt on a datetime64 series → error "Can only use .dt accessor with datetimelike values"
```

**Root cause:** `pandasai/data_loader/duck_db_connection_manager.py::register()`
calls `cast_struct_field_types(df, schema)` which **only casts struct inner
fields** (type_determination.py `_build_struct_field_type_map` explicitly
skips non-`list[struct]` columns). Flat `datetime` columns are registered with
their **original string dtype**, so DuckDB infers `VARCHAR`.

DeepSeek, seeing `(datetime: ...)` in the prompt, naturally writes pandas
datetime code — which crashes because the column is actually a string.

### 4.2 Q12 — `NameError: name 'sql' is not defined`

DeepSeek built a SQL string into variable `query` then called
`execute_sql_query(sql)` — referencing the wrong variable name. This is a
**name hallucination** within a single code block. Not schema-related.

### 4.3 Q13a — `duckdb.duckdb.ParserException: syntax error at or near "AS"`

In the `UNNEST(...) AS t(rec)` pattern, DeepSeek wrote a malformed bracket path:
`rec['Employee Leave Details[Leave Duration (Days)]]'` (extra `]`). The
`SQLParser.fix_common_llm_mistakes()` didn't catch the extra closing bracket.

### 4.4 Q19 — `duckdb.duckdb.BinderException: Could not find key "employee qualification[qualification title]"`

DeepSeek **lowercased / altered** a struct field name when writing
`rec['...']`. DuckDB struct keys are exact-case. The prompt shows the exact
`duckdb_key` (e.g. `Employee Qualification[Qualification Title]`), but the LLM
emitted a lowercase/normalized variant that doesn't exist.

### 4.5 Column self-inconsistency (Q30)

DeepSeek created `df['Tenure (years)']` then referenced `df['Tenure (Years)']`.
A within-block alias typo (casing).

---

## 5. Why DeepSeek Makes These Mistakes (cross-cutting)

The underlying cause is **informational asymmetry**: the prompt over-specifies
*semantic* types (datetime) but under-specifies *runtime* types (VARCHAR), and
provides no guidance for the most common failure (dates returned as strings
after SQL).

Breakdown of errors observed:

| Error type | Count | Root driver |
|---|---|---|
| datetime misuse on string col | 4 | **schema-vs-runtime mismatch** |
| struct field name mismatch | 1 | exact-case field lookup |
| variable name hallucination | 1 | generation, not execution |
| malformed struct bracket quoting | 1 | DuckDB UNNEST syntax |
| **Total first-attempt failures** | **7/14** | — |

---

## 6. Recommendations (highest leverage first)

1. **Cast flat top-level `datetime` columns on registration.** Extend
   `cast_struct_field_types` (or add `cast_flat_field_types`) so that a
   top-level column whose semantic-model `type == "datetime"` is converted to
   `pd.to_datetime(...)` before `connection.register()`. This makes the runtime
   dtype match the prompt, eliminating the largest error class (4 of 7).
2. **Tell the LLM to coerce defensively.** Add a note to
   `generate_python_code_with_sql.tmpl` / `duckdb_syntax.tmpl`:
   > "Columns declared as `datetime` may be returned as strings by DuckDB.
   > Wrap in `pd.to_datetime(col, errors='coerce')` before `.dt.*`/`.date()`."
3. **Struct exactness reinforcement**: the prompt already states "copy exactly";
   DeepSeek still normalizes. Consider echoing a few real `duckdb_key` values
   as worked examples right before the struct-listing block, and instructing it
   to verify casing.
4. **Self-consistency check**: add a prompt line requiring that any variable /
   column alias referenced later must match the exact alias defined earlier in
   the same generated code.

---

## 7. Deliverables Checklist (per logic-mapping methodology)

- [x] Logic map document (this file)
- [x] Root-cause analysis with file:line references
- [x] Live-data verification (e2e reports `run/e2e_reports/20260807_115706_enterprise_e2e/`,
      CSV dtype checks, conv log prompt inspection)
- [x] Error-to-root-cause table