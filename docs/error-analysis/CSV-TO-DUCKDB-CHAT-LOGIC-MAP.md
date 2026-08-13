# CSV → DuckDB Table → Chat Query: Complete Logic Map

> **Method**: Logic Mapping Technique (Phase 1 — Trace).
> **Purpose**: Single source of truth for the full call chain that turns a CSV
> file into a registered DuckDB-backed DataFrame and then answers a natural
> language query via LLM-generated SQL.
> **Conventions**: `[file:line]` references. `→` = direct call. `⇢` = async/thread.
> Struct columns are `list[struct]` (JSON-array strings) parsed to list-of-dicts.

---

## 0. Big Picture (one diagram)

```
                         ┌──────────────────────────── REGISTER PATH ────────────────────────────┐
   HTTP POST /api/register                                                             
        │                                                                             
        ▼                                                                             
 [register/router.py] register_base64 / register_file                                 
        │  ⇢ asyncio.to_thread / create_agent_from_file_path                        
        ▼                                                                            
 [register/handler.py] create_agent_from_file_path                                  
        │                                                                            
        ├─► (1) pai.read_csv(file) ──► pd.read_csv + parse_json_array_columns ──► pai DataFrame (schema auto)
        ├─► (2) apply SemanticModel / cast_struct_field_types / patch schema / fill descriptions
        ├─► (2) Agent([df], config) ──► AgentState + CodeGenerator + ResponseParser
        └─► (3) agent_store.register_agent(agent) ──► conversation_id
                                                                                            
                                                                                            
                         ┌────────────────────────────── CHAT PATH ─────────────────────────────┐
 HTTP POST /api/chat  →  [chat/router.py] → [chat/handler.py] → agent.chat(query)               
                                                                      │                          
                                                                      ▼                          
                                                              [agent/base.py] _process_query     
                                                                      │                          
                                          ┌───────────────────────────┼───────────────────────┐  
                                          │ STEP 1: Column Selection  │                       │  
                                          │ _should_select_columns()  │  (SKIP if <threshold) │  
                                          │   │ ColumnSelector.select() (LLM)                  │  
                                          │   │ → trim df+schema         │                       │  
                                          └───────────────────────────┼───────────────────────┘  
                                                                      │                          
                                                                      ▼                          
                                          ┌───────────────────────────┼───────────────────────┐  
                                          │ STEP 2: Code Generation    │                       │  
                                          │ generate_code_with_retries │                       │  
                                          │   │ GeneratePythonCodeWithSQLPrompt  (schema → LLM)│  
                                          │   │ → generate_code → validate_and_clean_code     │  
                                          │   │     → StructuralCodeValidator (self-review)   │  
                                          │   │ → (retry × max_retries=3)                      │  
                                          └───────────────────────────┼───────────────────────┘  
                                          ┌───────────────────────────┼───────────────────────┐  
                                          │ STEP 2b: Execution         │                       │  
                                          │ execute_with_retries → execute_code                │  
                                          │   │ CodeExecutor.run()     │                       │  
                                          │   │ → _execute_sql_query   │                       │  
                                          │       │ DuckDBConnectionManager.register           │  
                                          │       │ → SQLParser.fix_common_llm_mistakes        │  
                                          │       │ → SQLParser.replace_table_and_column_names │  
                                          │       │ → db_manager.sql()   │                       │  
                                          └───────────────────────────┼───────────────────────┘  
                                                                      ▼                          
                                                          ResponseParser → HTTP Response        
```

---

## 1. ENTRY: HTTP Registration Path

### Entry points (server/features/register/router.py)
```
POST /api/register/base64      → register_base64(payload: Base64UploadRequest)
POST /api/register/file        → register_file(file, semantic_model, pandasai_config, llm_config)
```
Both are thin wrappers that push work off the event loop with `asyncio.to_thread`.

| Function | File:Line | Calls | Notes |
|---|---|---|---|
| `register_base64` | `server/features/register/router.py:38` | ⇢ `asyncio.to_thread(handle_base64_upload, ...)` | Decodes base64 in handler |
| `register_file` | `server/features/register/router.py:71` | ⇢ `asyncio.to_thread(create_agent_from_file_path, temp_path, ...)` | Temp file from upload |

---

## 3. Handler: create_agent_from_file_path (the CSV→DataFrame→Agent pipeline)

**File**: `server/features/register/handler.py` — `create_agent_from_file_path(file_path, mimetype, semantic_model, pandas_config, llm_config)`

```
handle_base64_upload(base64_data, mimetype, ...)          [handler.py]
   │  b64decode → write temp file
   ▼
create_agent_from_file_path(file_path, ...)               [handler.py]
   │
   ├─ Step 0  Pre-validate semantic model (pydantic SemanticLayerSchema)
   │
   ├─ Step 1  READ + PARSE
   │     │  mimetype == csv ?
   │     ├─ YES → pai.read_csv(file_path)          [pandasai/__init__.py:295]
   │     │          └─ pd.read_csv(file_path, encoding="utf-8-sig")
   │     │             └─ parse_json_array_columns(df)   [helpers/type_determination.py]
   │     │                 └─ JSON-array strings → list[struct] columns (list-of-dicts)
   │     │
   │     └─ NO  → pai.read_excel(file_path)
   │
   ├─ Step 2  SEMANTIC LAYER
   │     ├─ Apply SemanticModel schema → df.schema  (SemanticLayerSchema)
   │     ├─ cast_struct_field_types(df, schema)      [helpers/type_determination.py]
   │     │     └─ per-field dtype coercion on list[struct] columns
   │     ├─ patch schema columns
   │     │     └─ struct column → squash inner fields; remove inner-field columns
   │     └─ fill_missing_descriptions(df, structured_llm)  (if auto_fill_descriptions)
   │
   ├─ Step 2' — BUILD AGENT
   │     │  agent_config = ConfigManager.get().model_dump()
   │     │  inject custom `llm` + `structured_llm` (from llm_setup)
   │     └─ Agent([df], config=agent_config, description=llm_config.system_prompt)
   │             [pandasai/agent/base.py:43]
   │                ├─ transition pd.DataFrame → pai DataFrame
   │                ├─ AgentState().initialize(...)
   │                ├─ CodeGenerator(self._state)
   │                └─ ResponseParser()
   │
   └─ Step 3  REGISTER STATE
         │  conversation_id = agent_store.register_agent(agent)   [server/core/agent_store.py]
         └─ RegisterResponse(conversation_id, extracted_context)
```

### The CSV read (pandasai/__init__.py)
```
read_csv(filepath)                [pandasai/__init__.py:295]
  │  data = pd.read_csv(filepath, encoding="utf-8-sig")
  ▼
DataFrame(data, name=get_table_name_from_path(filepath))
  [pandasai/dataframe/base.py:51]  -- subclass of pd.DataFrame
  │   pops schema / path / _table_name kwargs
  │   schema = get_default_schema(cls, data)   [dataframe/base.py:176]
  │      └─ SemanticLayerSchema(name=..., source=Source(type="parquet", path="data.parquet"),
  │              columns=[...])  -- built via is_list_struct_column / determine_series_type
  ▼
pai DataFrame with .schema
```

---

## 4. CHAT PATH: agent.chat → _process_query

**File**: `pandasai/agent/base.py`

```
agent.chat(query)                 [agent/base.py: (public entry)]
   │  start_new_conversation()
   ▼
_process_query(query, output_type)  [agent/base.py:394]
   │  query = UserQuery(query)
   │
   │  RESET per-query state:
   │    last_selected_names, code_attempts, column_selection_log,
   │    column_selection_raw_llm_response, sql_queries, last_error_traceback,
   │    raw_execution_result, trimmed_df_info, retrieval_mode*, llm_call_log
   │  config_snapshot captured (for debugging)
   │  assign_prompt_id(); timings = {}
   │
   ├─ STEP 1 — COLUMN SELECTION  (only if _should_select_columns())
   │     │  should_select = _should_select_columns()
   │     │      True if column_selection_enabled is True
   │     │         or total_cols >= column_selection_threshold
   │     ├─ YES (wide tables) → [branch A]
   │     └─ NO  (narrow)       → [branch B: skip, use full schema]
   │
   ├─ STEP 1 MEMORY ISOLATION
   │     │  if column selection ran → swap in fresh Memory(size=1) for Step 2
   │     │  (so Step 2 never sees Step-1-trimmed column refs in history)
   │
   ├─ STEP1_ONLY escape hatch (env STEP1_ONLY / step1_only)
   │     └─ returns StringResponse("[STEP1_ONLY] ...") before codegen
   │
   ├─ STEP 2 — CODE GENERATION
   │     │  code = generate_code_with_retries(query)   [agent/base.py:224]
   │     │
   │     ├─ STEP 2b — EXECUTION
   │     │     result = execute_with_retries(code)     [agent/base.py:283]
   │     │
   │     ├─ _store_assistant_message(result, output_type)   (multi-turn memory)
   │     │
   │     └─ return result
   │
   └─ finally:  MERGE Step-2 memory back into original memory
        │         (only if column selection ran)
        └─ restore original dfs (undo trimming for next turn)
```

### Branch A — Column Selection (Step 1)
```
_should_select_columns() == True
   ▼
_apply_column_selection(query)        [agent/base.py:681]
   │  from pandasai.core.column_selector import ColumnSelector
   │  selector = ColumnSelector(self._state)
   │     column_selection_prompt = str(selector._build_prompt(query))
   │     self._state.memory = selector.build_step1_memory()   (reduced size)
   │  selected_names = selector.select(query)          [LLM call — the ~135s/400s hotspot]
   │
   │  if empty → fallback: use ALL columns
   │
   ▼
   match selected_names → trim df.columns + df.schema to selected subset
   ▼
   self._state.dfs = [trimmed_df]   (original dfs kept in `original_dfs`)
```

### Branch B — Column Selection Skipped
```
total_cols < column_selection_threshold
   ▼
use FULL schema in Step 2 prompt (no trimming)
```

---

## 5. STEP 2 — Code Generation detail

```
generate_code_with_retries(query)             [agent/base.py:224]
   │  max_retries = config.max_retries   (default 3)
   │  for attempt in range(1 + max_retries):   // 1 + 3 = 4 total
   │      attempt 0 → generate_code(query)
   │      attempt >0 → _regenerate_code_after_error(last_code, exception)
   │         on success → return code
   │         on Exception → store traceback, retry; raise after max
   │
   └─ generate_code(query)  [agent/base.py]
        │  self._state.memory.add(query, is_user=True)
        ▼
        get_chat_prompt_for_sql(self._state)   [core/prompts/__init__.py:21]
        │  = GeneratePythonCodeWithSQLPrompt(context, last_code_generated, output_type)
        ▼
        _code_generator.generate_code(prompt)
        │  = CodeGenerator.generate_code(prompt)   [core/code_generation/base.py]
        │       ├─ prompt.to_string()  → render template
        │       ├─ validate_and_clean_code(...)
        │       │     └─ StructuralCodeValidator(schema_columns)   [structural_validator.py]
        │       │            _check_placeholders
        │       │            _check_unnest_columns
        │       │            _check_struct_field_keys      (the UNNEST nesting-level check)
        │       │            _check_unnest_access_level
        │       │            _check_alias_consistency
        │       │            _check_unknown_sql_functions
        │       │            _check_bare_aggregates
        │       └─ (on structural failure → self-review/regenerate loop)
        ▼
        stores last_prompt_used / last_code_generated
```

### Prompt rendering (what the LLM actually sees)
```
GeneratePythonCodeWithSQLPrompt.to_json()    [core/prompts/generate_python_code_with_sql.py]
   │  datasets = [df.to_json() for df in context.dfs]      <-- the schema!
   │  conversation = memory.to_json()
   │  system_prompt = memory.agent_description
   ▼
templates/generate_python_code_with_sql.tmpl
   │  includes shared/duckdb_syntax.tmpl, sql_functions.tmpl, code_strategy.tmpl
   │  <tables> → shared/dataframe.tmpl  → {{ df.serialize_dataframe(config) }}
   │       └─ dataframe_serializer.serialize_dataframe()
   │            → per-column dict incl. samples (enriched values)
   │            → token budget trimming
   │  <result_format> result = {"type": ..., "value": ...}
   ▼
   final code wrapped in triple backticks
```

---

## 6. STEP 2b — Execution path

```
execute_with_retries(code)                 [agent/base.py:283]
   │  (analogous retry loop: execute → on SQL error → _regenerate_code_after_error)
   ▼
execute_code(code)                          [agent/base.py]
   │  code_executor = CodeExecutor()
   │  add_to_env("execute_sql_query", self._execute_sql_query)
   │  add skills
   ▼
CodeExecutor.run(code)                  [pandasai/core/code_executor/...]
   │  # generated code may call execute_sql_query(...) or df.chat()
   ▼
_execute_sql_query(query)               [agent/base.py:124]
   │  db_manager = DuckDBConnectionManager()
   │  table_mapping = {}
   │  for df in self._context.dfs:
   │      column_names += df.columns
   │      if df.query_builder._get_table_expression():
   │          table_mapping[df.schema.name] = df.query_builder._get_table_expression()
   │      else:
   │          db_manager.register(df.schema.name, df)    # inline register → actual table
   │
   │  query = SQLParser.fix_common_llm_mistakes(query, column_names)
   │  query = SQLParser.replace_table_and_column_names(query, table_mapping)
   │  result = db_manager.sql(query).df()
   │  convert ndarray cells → lists
```

### DuckDB register + connection
```
DuckDBConnectionManager.__init__       [data_loader/duck_db_connection_manager.py]
   │  conn = duckdb.connect()
   │  _create_helper_macros(conn)
   ▼
register(name, df)
   │  cast_struct_field_types(df, schema)      [helpers/type_determination.py]
   │  cast_flat_field_types(df, schema)
   ▼
   conn.register(name, df)   # materialize pandas df as DuckDB table
```

### SQLParser auto-fixes (the hallucination-defense layer)
**File**: `query_builders/sql_parser.py`

| Fix | Line | What it does |
|---|---|---|
| `fix_common_llm_mistakes` | :14 | (1) schema-driven column-name correction: `"inner"` → `"[inner]"`; (2) enforce `UNNEST(...) AS t(rec)` alias pattern; (3) `alias.rec['field']` → `alias['field']` |
| `replace_table_and_column_names` | :134 | swap LLM table/col names with real names from `table_mapping` |
| `transpile_sql_dialect` | :189 | dialect conversion (if needed) |

---

## 7. Exit Points

| Path | Exit |
|---|---|
| Registration | `RegisterResponse(conversation_id, extracted_context)` → JSON 200 |
| Chat success | `ResponseParser` → `StringResponse`/`DataframeResponse` → JSON 200 |
| Chat failure | `_handle_exception(code)` / `CodeExecutionError` → `error_result` → HTTP (often 500) |

---

## 8. Data Contracts (schema shape entering each stage)

| Stage | Data shape |
|---|---|
| CSV read | raw `pd.DataFrame` with JSON-array-strings in some cells |
| after `parse_json_array_columns` | list columns of type `list[struct]` (list-of-dicts) |
| after semantic layer | `DataFrame` with `.schema: SemanticLayerSchema`, struct columns patched (squashed) |
| AgentState.dfs | list of pai DataFrames |
| Step 1 prompt | column names + schema (small, reduced memory) |
| Step 2 prompt | `serialize_dataframe()` → full column dicts + samples + CSV head |
| SQL execution | DuckDB table via `conn.register` OR table expression from query_builder |

---

## 9. Hotspots / Weak Points (from stability investigation)

1. **Step 1 ColumnSelector.select() LLM call** — the 135s/400s timeout hotspot
   (`column_selection_llm` timing split out in `_apply_column_selection`).
2. **Structural validator UNNEST nesting-level bug** — `outer['key']` vs
   `outer.inner['key']`/`inner['key']` → "Could not find key ... Candidate Entries: t".
   (DuckDB struct lookup is case-insensitive; the level, not case, is the cause.)
3. **`max_retries=3`** ⇒ up to 16 LLM calls/query (colsel 1 + gen 1+3 + exec 1+3),
   each 5-25s → 5-15× latency amplification.
4. **Schema typo trap**: `[Employee Competencies Rating[Competancy Name]]`
   (misspelled). Model writes correct `Competency Name` → validator rejects →
   endless retry.
5. **Extra-bracket struct access**: `rec['Parent[Field]]']` (double `]`) vs
   `rec['Parent[Field]']` → ParserException near `[`/`AS`.
6. **Struct-key hallucination/abbreviation**: LLM invents keys.

---

## 10. Call-chain quick reference (flat list)

```
POST /api/register/base  → register/router.py:38  register_base64
POST /api/register/file  → register/router.py:71  register_file
  → asyncio.to_thread(handle_base64_upload / create_agent_from_file_path)
  → register/handler.py  create_agent_from_file_path
       → pai.read_csv  pandasai/__init__.py:295  (→ pd.read_csv utf-8-sig)
       → parse_json_array_columns  helpers/type_determination.py
       → DataFrame(data, name=...)  dataframe/base.py:51  (schema auto-built :176)
       → cast_struct_field_types / patch schema / fill_missing_descriptions
       → Agent([df], config, description)  agent/base.py:43
            AgentState.initialize, CodeGenerator, ResponseParser
       → agent_store.register_agent → conversation_id

POST /api/chat  → agent.chat → _process_query  agent/base.py:394
       → _should_select_columns() → _apply_column_selection (ColumnSelector.select)  :681
       → generate_code_with_retries  :224
            → generate_code → get_chat_prompt_for_sql  core/prompts/__init__.py:21
                 → GeneratePythonCodeWithSQLPrompt → render template
                      → df.serialize_dataframe  helpers/dataframe_serializer.py
                 → CodeGenerator.generate_code → validate_and_clean_code
                      → StructuralCodeValidator  core/code_generation/structural_validator.py
       → execute_with_retries  :283
            → execute_code → CodeExecutor.run
            → _execute_sql_query  :124
                 → DuckDBConnectionManager.register  data_loader/duck_db_connection_manager.py
                 → SQLParser.fix_common_llm_mistakes  query_builders/sql_parser.py:14
                 → SQLParser.replace_table_and_column_names  sql_parser.py:134
                 → db.sql(query).df()
       → _handle_exception / ResponseParser → HTTP response
```

---

## Status / TODO (Phase 2 & 3 not yet executed)

- [x] **Phase 1 Trace** — complete logic map above
- [ ] **Phase 2 Test** — verify each step against live data (scrape schema,
      prompt, generated SQL, execution results)
- [ ] **Phase 3 Build** — apply struct-reduction (flatten to long-form) + typo
      normalizer recommendations at the registration boundary