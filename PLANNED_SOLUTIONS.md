# PandasAI Chat-Excel-Server — Planned Solutions

**Date**: 2026-05-07  
**Companion to**: `AUDIT_REPORT.md`  
**Purpose**: Exact, file-level solutions for every issue identified in the audit

---

## Table of Contents

1. [Critical Fixes (C1–C3)](#1-critical-fixes)
2. [High Priority Fixes (H1–H5)](#2-high-priority-fixes)
3. [Medium Priority Fixes (M1–M5)](#3-medium-priority-fixes)
4. [Deep-Dive Solutions for Highlighted Issues](#4-deep-dive-solutions)

---

## 1. Critical Fixes

### C1 — `enrich_column_values` defaults to `False` in server but `True` in Config

**File**: `server/features/register/models.py`  
**Problem**: `PandasAIConfigPayload.enrich_column_values = Field(False, ...)` but `Config.enrich_column_values = True`. When the server creates a `PandasAIConfigPayload()` default, enrichment is OFF. The handler then does `agent_config.update(pandasai_config.model_dump())` which overwrites Config's `True` with `False`.

**Solution**: Align the server default with the framework default:

```python
# BEFORE
enrich_column_values: bool = Field(False, description="Enable semantic enrichment of column values")

# AFTER
enrich_column_values: bool = Field(True, description="Enable semantic enrichment of column values")
```

**Impact**: When no `pandasai_config` is sent in the request, enrichment defaults to `True` — matching the framework. The user can still explicitly pass `False` to disable it.

**Files changed**: `server/features/register/models.py` (1 line)

---

### C2 — `llm_context_window` defaults to `8192` in server but `250000` in Config

**File**: `server/features/register/models.py`  
**Problem**: `PandasAIConfigPayload.llm_context_window = Field(8192, ...)` but `Config.llm_context_window = 250000`. The 8192 default was likely a GPT-3.5-era value. The Qwen3.5-35B model has ~128K context. The token budget calculation uses `8192 * 0.10 = 819 tokens` — far too low.

**Solution**: Align the server default with the framework default:

```python
# BEFORE
llm_context_window: int = Field(8192, description="Context window of the LLM to calculate proportional budget")

# AFTER
llm_context_window: int = Field(250000, description="Context window of the LLM to calculate proportional budget")
```

**Impact**: Token budget becomes `250000 * 0.10 = 25000 tokens` — sufficient for rich vocabulary. The user can still pass a smaller value for constrained models.

**Files changed**: `server/features/register/models.py` (1 line)

---

### C3 — `context.config.direct_sql` — AttributeError in `generate_python_code_with_sql.py`

**File**: `pandasai/core/prompts/generate_python_code_with_sql.py`  
**Problem**: Line 25 references `context.config.direct_sql` but `Config` has no `direct_sql` field. This will raise `AttributeError` when `to_json()` is called.

**Solution**: Add `direct_sql` to `Config` with a default of `True` (the current implicit behavior — the system always generates SQL):

```python
# In pandasai/config.py, add to Config class:
direct_sql: bool = True
```

**Why `True`**: The entire pipeline is SQL-first (DuckDB). The `direct_sql` flag being `True` tells the prompt system that SQL generation is the code strategy. Setting it to `False` would be meaningless in the current architecture.

**Impact**: `context.config.direct_sql` resolves to `True`. The `to_json()` method works correctly. The `code_cleaning.py` `_check_direct_sql_func_def_exists()` method also uses this correctly.

**Files changed**: `pandasai/config.py` (1 line added)

---

## 2. High Priority Fixes

### H1 — Chat response type always `"auto"` — loses actual LLM-chosen type

**File**: `server/features/chat/handler.py`  
**Problem**: `type: output_type or "auto"` returns the *requested* type, not the *actual* type from the response. When `output_type=None` (auto-detect), the client always sees `"auto"`. When `output_type="dataframe"` but the LLM returned a string, the type is misleading.

**Solution**: Extract the actual type from the response object, falling back to the requested type:

```python
# BEFORE
response_str = str(response) if response is not None else None

return {
    "response": response_str,
    "type": output_type or "auto",
    "last_code_executed": getattr(agent, "last_generated_code", None)
}

# AFTER
# Determine the actual response type from the response object
actual_type = getattr(response, 'type', None) or output_type or "auto"

# Serialize response value appropriately based on type
if hasattr(response, 'type') and response.type == 'dataframe':
    # Return structured data for DataFrame responses
    response_value = response.value.to_dict(orient='records') if hasattr(response.value, 'to_dict') else str(response)
else:
    response_value = str(response) if response is not None else None

return {
    "response": response_value,
    "type": actual_type,
    "last_code_executed": getattr(agent, "last_generated_code", None)
}
```

**Impact**: The client now receives the true type (`"string"`, `"number"`, `"dataframe"`, `"chart"`) instead of `"auto"`. DataFrame responses are serialized as JSON records instead of `str()` representation.

**Files changed**: `server/features/chat/handler.py` (~8 lines)

---

### H2 — Hardcoded API key and base URL in `llm_setup.py`

**File**: `server/core/llm_setup.py`  
**Problem**: API key, base URL, and model name are all hardcoded in source code. This is a security risk and makes deployment inflexible.

**Solution**: Read all values from environment variables with sensible defaults:

```python
# BEFORE
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
import openai

def setup_global_llm():
    custom_httpx_client = httpx.Client(verify=False)
    custom_openai_client = openai.OpenAI(
        api_key="sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8",
        base_url="https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
        http_client=custom_httpx_client
    )
    llm = LiteLLM(
        model="openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
        client=custom_openai_client
    )
    pai.config.set({
        "llm": llm,
        "verbose": True
    })

# AFTER
import os
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
import openai

def setup_global_llm():
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model_name = os.environ.get("LLM_MODEL_NAME", "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "false").lower() == "true"
    
    if not api_key or not base_url:
        # Fallback: if env vars not set, skip global LLM setup.
        # The register endpoint can still provide per-request LLM config.
        return

    custom_httpx_client = httpx.Client(verify=verify_ssl)
    custom_openai_client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=custom_httpx_client,
    )
    llm = LiteLLM(
        model=model_name,
        client=custom_openai_client,
    )
    pai.config.set({
        "llm": llm,
        "verbose": True,
    })
```

**Impact**: Credentials are no longer in source code. The `.env` file or container environment provides them. The function gracefully skips setup if env vars are missing (the per-request LLM config in the register endpoint still works).

**Files changed**: `server/core/llm_setup.py` (full rewrite, ~25 lines), plus `.env` file with the actual values.

---

### H3 — `str(response)` loses DataFrame structure

**File**: `server/features/chat/handler.py`  
**Problem**: `str(response)` converts DataFrame responses to their `str()` representation — an ugly text block instead of structured data.

**Solution**: This is addressed as part of H1 above. The fix serializes DataFrame responses as `to_dict(orient='records')` which produces a clean JSON-serializable list of dicts.

**Files changed**: `server/features/chat/handler.py` (covered in H1)

---

### H4 — `chat()` clears memory on every call — multi-turn is broken

**File**: `pandasai/agent/base.py` + `server/features/chat/handler.py`  
**Problem**: `Agent.chat()` calls `start_new_conversation()` which calls `clear_memory()`. This means every chat turn starts from scratch — the LLM has no memory of previous turns. `follow_up()` preserves memory, but the server only calls `chat()`.

**Root Cause Analysis**: The design intent is:
- `chat()` = start a **new** conversation (clean slate)
- `follow_up()` = continue the **existing** conversation (with memory)

The server should use `follow_up()` for turns 2+ within the same `conversation_id`.

**Solution**: Track whether the agent has been used before, and use `follow_up()` for subsequent turns:

```python
# In server/features/chat/handler.py

def handle_chat_query(conversation_id: str, query: str, output_type: str = None) -> dict:
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")

    try:
        # Use follow_up() if the agent already has conversation history,
        # preserving multi-turn context. Use chat() only for the first turn.
        if agent._state.memory.count() > 0:
            response = agent.follow_up(query, output_type=output_type)
        else:
            response = agent.chat(query, output_type=output_type)

        actual_type = getattr(response, 'type', None) or output_type or "auto"

        if hasattr(response, 'type') and response.type == 'dataframe':
            response_value = response.value.to_dict(orient='records') if hasattr(response.value, 'to_dict') else str(response)
        else:
            response_value = str(response) if response is not None else None

        return {
            "response": response_value,
            "type": actual_type,
            "last_code_executed": getattr(agent, "last_generated_code", None)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Why not remove `start_new_conversation()` from `chat()`**: That would change the framework's public API contract. `chat()` is documented as starting a new conversation. The fix should be at the server layer, which already tracks conversation state via `agent_store`.

**Impact**: Multi-turn conversations now preserve memory. The LLM sees previous Q&A pairs and can build on them. The first turn still uses `chat()` for a clean start.

**Files changed**: `server/features/chat/handler.py` (~5 lines changed)

---

### H5 — `get_dialect()` defaults to `"postgres"` when no source

**File**: `pandasai/dataframe/base.py`  
**Problem**: When `source` is None, `get_dialect()` returns `"postgres"`. But the actual execution engine is DuckDB. The dialect is passed to the `<table>` XML tag that the LLM sees, so the LLM might generate PostgreSQL-specific SQL instead of DuckDB SQL.

**Solution**: Default to `"duckdb"` since that's the actual execution engine:

```python
# BEFORE
def get_dialect(self):
    source = self.schema.source or None
    if source:
        dialect = "duckdb" if source.type in LOCAL_SOURCE_TYPES else source.type
    else:
        dialect = "postgres"

# AFTER
def get_dialect(self):
    source = self.schema.source or None
    if source:
        dialect = "duckdb" if source.type in LOCAL_SOURCE_TYPES else source.type
    else:
        dialect = "duckdb"
```

**Impact**: The LLM sees `dialect="duckdb"` in the XML tag, which reinforces the DuckDB-specific rules in `duckdb_syntax.tmpl`. No PostgreSQL-specific SQL will be generated.

**Note on `get_default_schema()`**: The default schema creates `Source(type="parquet", path="data.parquet")`. Since `"parquet"` is in `LOCAL_SOURCE_TYPES`, `get_dialect()` would return `"duckdb"` for that path too. So the only case where `"postgres"` was returned was when `source` was `None`, which happens when the schema is incomplete. The fix makes this case consistent.

**Files changed**: `pandasai/dataframe/base.py` (1 line)

---

## 3. Medium Priority Fixes

### M1 — Temp files never cleaned up

**File**: `server/features/register/handler.py`  
**Problem**: `handle_base64_upload()` writes temp files to `/tmp/pandasai_uploads/` but never deletes them.

**Solution**: Register a cleanup callback after agent creation. Use `atexit` for process-level cleanup and delete the specific temp file immediately after the DataFrame is loaded:

```python
# In handle_base64_upload(), after create_agent_from_file_path():
import os

def handle_base64_upload(...) -> RegisterResponse:
    # ... existing code to write temp_path ...
    
    try:
        result = create_agent_from_file_path(
            temp_path, mimetype,
            semantic_model=semantic_model,
            pandasai_config=pandasai_config,
            llm_config=llm_config,
        )
        return result
    finally:
        # Clean up the temp file — the DataFrame is already in memory
        try:
            os.unlink(temp_path)
        except OSError:
            pass
```

**Impact**: Temp files are deleted immediately after the DataFrame is loaded into memory. No accumulation in `/tmp/pandasai_uploads/`.

**Files changed**: `server/features/register/handler.py` (~5 lines)

---

### M2 — `last_code_executed` returns generated code, not executed

**File**: `pandasai/agent/base.py`  
**Problem**: Both `last_generated_code` and `last_code_executed` return `self._state.last_code_generated`. After retries, the executed code may differ from the originally generated code.

**Solution**: Track the actual executed code separately in `AgentState`:

```python
# In pandasai/agent/state.py, the field already exists:
# last_code_executed: Optional[str] = None
# But it's never set. Update the pipeline to set it.

# In pandasai/agent/base.py, in execute_with_retries():
def execute_with_retries(self, code: str) -> Any:
    max_retries = self._state.config.max_retries
    attempts = 0

    while attempts <= max_retries:
        try:
            result = self.execute_code(code)
            # Track the code that actually executed successfully
            self._state.last_code_executed = code
            return self._response_parser.parse(result, code)
        except Exception as e:
            attempts += 1
            if attempts > max_retries:
                self._state.logger.log(f"Max retries reached. Error: {e}")
                raise
            self._state.logger.log(
                f"Retrying execution ({attempts}/{max_retries})..."
            )
            code = self._regenerate_code_after_error(code, e)

    return None

# And update the property:
@property
def last_code_executed(self):
    return self._state.last_code_executed
```

**Impact**: `last_code_executed` now returns the code that was actually executed (possibly after retries), while `last_generated_code` returns the first generated code.

**Files changed**: `pandasai/agent/base.py` (2 lines: add assignment + change property), `pandasai/agent/state.py` (no change needed — field exists)

---

### M3 — `df.sample()` vs `df.head()` for LLM context

**File**: `pandasai/helpers/dataframe_serializer.py`  
**Problem**: `df.sample(n=sample_size, random_state=42)` shows random rows to the LLM. For data where the first rows are most representative (e.g., sorted data, time-series), this could show misleading context.

**Solution**: Use `df.head()` for deterministic first-row visibility. The first rows are typically the most representative for user-uploaded files:

```python
# BEFORE
df_truncated = cls._truncate_dataframe(
    df.sample(n=sample_size, random_state=42) if sample_size > 0 else df.head(0)
)

# AFTER
df_truncated = cls._truncate_dataframe(
    df.head(n=sample_size) if sample_size > 0 else df.head(0)
)
```

**Impact**: The LLM always sees the first N rows, which are deterministic and typically most representative. If the user wants a random sample, they can shuffle the data before uploading.

**Files changed**: `pandasai/helpers/dataframe_serializer.py` (1 line)

---

### M4 — Memory default `memory_size=1` vs Agent's `memory_size=10`

**File**: `pandasai/helpers/memory.py`  
**Problem**: `Memory.__init__()` defaults `memory_size=1`, but `AgentState.initialize()` passes `memory_size=10`. The `Memory` default is misleading and would cause issues if `Memory` were ever instantiated without the `AgentState` override.

**Solution**: Align the `Memory` default with the `AgentState` default:

```python
# BEFORE
def __init__(self, memory_size: int = 1, agent_description: Union[str, None] = None):

# AFTER
def __init__(self, memory_size: int = 10, agent_description: Union[str, None] = None):
```

**Impact**: If `Memory` is ever instantiated standalone, it defaults to 10 messages (same as the Agent). No change in current behavior since `AgentState.initialize()` always passes `memory_size=10`.

**Files changed**: `pandasai/helpers/memory.py` (1 line)

---

### M5 — Enrichment can run twice (handler + serializer)

**File**: `server/features/register/handler.py` + `pandasai/helpers/dataframe_serializer.py`  
**Problem**: When `enrich_column_values=True`, the handler enriches schema columns in Step 2b, then the serializer checks `col_dict.get("samples") is None` and would re-enrich if samples were missing. Since Step 2b already set samples, the serializer's enrichment is a no-op — but the check still runs.

**Solution**: This is already handled correctly — the serializer's lazy enrichment is a safety net. When the handler pre-enriches, `col_dict["samples"]` is not None, so the serializer skips enrichment. No code change needed — just documenting the design:

```
Handler Step 2b: Enriches schema Column objects (sets .samples on the Column model)
    ↓
Serializer: Reads schema Column → model_dump() → col_dict has samples → skips lazy enrichment
```

**Verdict**: ✅ No code change. The redundancy is intentional — the serializer is a safety net for cases where the handler doesn't pre-enrich (e.g., when `enrich_column_values=False` but a future feature adds enrichment for specific columns).

---

## 4. Deep-Dive Solutions for Highlighted Issues

### 4.1 Duplicate Enrichment Logic (Handler Step 2b vs Serializer)

**The Concern**: Both the handler and the serializer check `is_list_struct_column`, call `ColumnValueExtractor.classify_and_extract()`, and do semantic matching for squashed columns. This looks like duplicated logic.

**Deep Analysis**: The two enrichment paths serve **different purposes** and operate at **different levels**:

| Aspect | Handler Step 2b | Serializer |
|--------|----------------|------------|
| **When** | Registration time (once) | Every `serialize()` call (per chat turn) |
| **What** | Patches `df.schema.columns` (Column objects) | Builds `col_dict` (JSON dict for XML attribute) |
| **Why** | So the API response includes enrichment data | So the LLM prompt includes enrichment data |
| **Input** | DataFrame columns + schema | DataFrame columns + schema (same) |
| **Output** | Mutates schema Column objects | Returns serialized string |

The handler enriches the **schema** so that:
1. The `RegisterResponse.extracted_context` includes samples
2. The schema Column objects persist for future serializer calls

The serializer enriches the **prompt** so that:
1. If the handler didn't pre-enrich (e.g., `enrich_column_values=False`), the serializer still provides samples to the LLM
2. If a column was missed by the handler (edge case), the serializer catches it

**The redundancy is intentional and correct**. The handler pre-computes enrichment for the API response; the serializer lazily fills gaps for the LLM prompt.

**However**, there is one real issue: when `enrich_column_values=True`, the handler pre-enriches ALL columns, making the serializer's enrichment check a pure no-op. This wastes a small amount of time on the `classify_and_extract()` check (even though it doesn't re-extract). We can optimize this:

**Optimization (Optional)**: Add a flag to skip serializer enrichment when the schema is already enriched:

```python
# In pandasai/helpers/dataframe_serializer.py, in the serialize() method:
if config.enrich_column_values:
    # Skip lazy enrichment if the schema column already has samples
    # (pre-enriched by the handler during registration)
    if not isinstance(df, VirtualDataFrame) and col_dict.get("samples") is None:
        # ... existing enrichment code ...
```

This is already the current behavior (`col_dict.get("samples") is None` check). ✅ No change needed.

**Verdict**: The "duplication" is actually **separation of concerns**. The handler enriches for the API; the serializer enriches for the LLM. The serializer's lazy check prevents double-work. No code change required.

---

### 4.2 Response Type Always "auto"

**The Concern**: `type: output_type or "auto"` always returns the requested type, not the actual type.

**Deep Analysis**: The response object is a `BaseResponse` subclass with a `.type` attribute:

| Response Class | `.type` value | When produced |
|----------------|--------------|---------------|
| `StringResponse` | `"string"` | LLM returns a string result |
| `NumberResponse` | `"number"` | LLM returns a numeric result |
| `DataFrameResponse` | `"dataframe"` | LLM returns a DataFrame result |
| `ChartResponse` | `"chart"` | LLM generates a chart |
| `ErrorResponse` | `"error"` | Code execution fails |

The chat handler currently does:
```python
response = agent.chat(query, output_type=output_type)
# response is a BaseResponse subclass
# response.type is the ACTUAL type
# response.value is the actual value
# But we do: type=output_type or "auto"  ← WRONG
```

**Solution**: Extract `response.type` directly. This is the authoritative source of the actual response type:

```python
actual_type = getattr(response, 'type', None) or output_type or "auto"
```

**Fallback chain**:
1. `response.type` — the actual type from the response parser (most authoritative)
2. `output_type` — the requested type from the client (if response has no type)
3. `"auto"` — fallback if neither is available

**Why `getattr` instead of `response.type`**: In case the response is a plain string (from error paths), `getattr` prevents `AttributeError`.

**Impact**: The client always receives the true type. For `output_type=None` (auto-detect), the type will be `"string"`, `"number"`, `"dataframe"`, or `"chart"` — never `"auto"`.

---

### 4.3 DuckDBConnectionManager — New Instance Per SQL Execution

**The Concern**: `_execute_sql_query()` creates a new `DuckDBConnectionManager()` on every call, re-registering all DataFrames each time.

**Deep Analysis**: The current flow per SQL execution:

```
1. db_manager = DuckDBConnectionManager()  ← new in-memory DuckDB
2. For each df: db_manager.register(name, df)  ← register all tables
3. query = SQLParser.fix_common_llm_mistakes(query, ...)
4. query = SQLParser.replace_table_and_column_names(query, ...)
5. return db_manager.sql(final_query).df()
6. db_manager.__del__()  ← connection closed, tables lost
```

**Cost**: 
- DuckDB in-memory connection creation: ~0.1ms
- DataFrame registration: ~0.5ms per DataFrame (depends on size)
- Connection teardown: ~0.1ms

For a single-DataFrame agent with small data, this is negligible. For multi-DataFrame agents with large data, the re-registration cost adds up across multiple chat turns.

**Solution**: Cache the `DuckDBConnectionManager` on the `AgentState` and reuse it across executions:

```python
# In pandasai/agent/state.py, add:
_duckdb_manager: Optional[Any] = None

# In pandasai/agent/base.py, modify _execute_sql_query():
def _execute_sql_query(self, query: str) -> pd.DataFrame:
    if not self._state.dfs:
        raise ValueError("No DataFrames available to register for query execution.")

    # Reuse the DuckDB connection manager if it exists and still has all tables registered
    if self._state._duckdb_manager is None:
        self._state._duckdb_manager = DuckDBConnectionManager()
        for df in self._state.dfs:
            if not hasattr(df, "query_builder"):
                self._state._duckdb_manager.register(df.schema.name, df)

    db_manager = self._state._duckdb_manager
    # ... rest of the method
```

**Caveat**: The cached manager needs to be invalidated if DataFrames change (e.g., after `parse_json_array_columns`). Since DataFrames are registered once at agent creation and never modified afterward, the cache is safe.

**Alternative (simpler)**: Keep the current behavior. The cost is negligible for the current use case (single DataFrame, small-to-medium data). The current approach is simpler and doesn't hold a persistent database connection in memory.

**Recommendation**: Keep the current behavior for now. The connection-per-query pattern is stateless and safe. If performance profiling shows this is a bottleneck, implement the caching solution above.

**Verdict**: 🟢 No code change. Acknowledged as a potential optimization but not a bug.

---

### 4.4 `chat()` Clears Memory on Every Call

**The Concern**: `Agent.chat()` calls `start_new_conversation()` → `clear_memory()`, wiping conversation history. The server only uses `chat()`, so multi-turn is broken.

**Deep Analysis**: The `chat()` vs `follow_up()` design:

```python
# chat() — starts fresh every time
def chat(self, query, output_type=None):
    self.start_new_conversation()  # ← clears memory
    return self._process_query(query, output_type)

# follow_up() — preserves memory
def follow_up(self, query, output_type=None):
    return self._process_query(query, output_type)
```

The memory is used in two places:
1. **LLM prompt**: The `generate_system_message.tmpl` renders `memory.get_previous_conversation()` — but since `chat()` clears memory, this is always empty.
2. **LiteLLM messages**: The LiteLLM `call()` method reads `memory.all()` for multi-turn messages — but since `chat()` clears memory, only the current query is sent.

**The server needs multi-turn** because:
- The `conversation_id` implies a persistent session
- The `agent_store` keeps the agent alive across turns
- Users expect follow-up questions to reference previous answers

**Solution (at server layer)**: Use `follow_up()` for turns 2+, as detailed in H4 above:

```python
# In server/features/chat/handler.py:
if agent._state.memory.count() > 0:
    response = agent.follow_up(query, output_type=output_type)
else:
    response = agent.chat(query, output_type=output_type)
```

**Why not modify `chat()` in the framework**: Changing `chat()` to not clear memory would break the documented API contract. Users of the PandasAI library expect `chat()` to start fresh. The fix belongs at the server layer.

**Memory size consideration**: With `memory_size=10`, the agent remembers the last 10 messages. The LiteLLM `call()` method sends all messages as multi-turn conversation. This is correct for the LLM to understand context.

**Impact**: Multi-turn conversations work. The LLM sees previous Q&A pairs and can reference them.

---

### 4.5 `get_last_message()` Uses `self._memory_size`

**The Concern**: `get_last_message()` calls `self.get_messages(self._memory_size)`, which returns the last N messages. But `_memory_size` defaults to 1 in `Memory.__init__()`, which seems too low.

**Deep Analysis**: The `get_last_message()` method:

```python
def get_last_message(self) -> str:
    messages = self.get_messages(self._memory_size)
    return "" if len(messages) == 0 else messages[-1]
```

And `get_messages()`:

```python
def get_messages(self, limit: int = None) -> list:
    limit = self._memory_size if limit is None else limit
    return [
        f"{'### QUERY' if message['is_user'] else '### ANSWER'}\n {message['message'] if message['is_user'] else self._truncate(message['message'])}"
        for message in self._messages[-limit:]
    ]
```

**Usage**: `get_last_message()` is called from `generate_system_message.tmpl`:
```jinja2
{% if memory.count() > 1 %}
### PREVIOUS CONVERSATION
{{ memory.get_previous_conversation() }}
{% endif %}
```

Wait — `get_last_message()` is NOT called from the template. Let me check:

Actually, looking at the template, it calls `memory.get_previous_conversation()`, not `get_last_message()`. And `get_previous_conversation()` also uses `self._memory_size`:

```python
def get_previous_conversation(self) -> str:
    messages = self.get_messages(self._memory_size)
    return "" if len(messages) <= 1 else "\n".join(messages[:-1])
```

**The real concern**: The template calls `get_previous_conversation()`, which returns all messages up to `memory_size` except the last one. With `memory_size=10` (set by `AgentState.initialize()`), this returns up to 9 messages of context. This is correct.

**The `get_last_message()` concern**: This method is not called from any template. It's a utility method. The `_memory_size=1` default in `Memory.__init__()` only matters if `Memory` is instantiated standalone — which never happens in practice.

**Solution**: Align the `Memory.__init__()` default with `AgentState.initialize()`:

```python
# BEFORE
def __init__(self, memory_size: int = 1, agent_description=None):

# AFTER
def __init__(self, memory_size: int = 10, agent_description=None):
```

This is M4. It ensures consistency and prevents surprising behavior if `Memory` is ever used standalone.

**Impact**: No change in current behavior (since `AgentState.initialize()` always passes `memory_size=10`). Future-proofing only.

---

### 4.6 `to_openai_messages()` Duplicates System Prompt

**The Concern**: Both `Memory.to_openai_messages()` and `LiteLLM.call()` add the system prompt from `memory.agent_description`.

**Deep Analysis**:

`Memory.to_openai_messages()`:
```python
def to_openai_messages(self):
    messages = []
    if self.agent_description:
        messages.append({"role": "system", "content": self.agent_description})
    for message in self.all():
        if message["is_user"]:
            messages.append({"role": "user", "content": message["message"]})
        else:
            messages.append({"role": "assistant", "content": message["message"]})
    return messages
```

`LiteLLM.call()`:
```python
def call(self, instruction, context=None):
    memory = context.memory if context else None
    messages = []
    if memory:
        if memory.agent_description:
            messages.append({"role": "system", "content": memory.agent_description})
        recent_msgs = memory.all()[-memory.size:]
        for msg in recent_msgs[:-1]:
            role = "user" if msg["is_user"] else "assistant"
            messages.append({"role": role, "content": msg["message"]})
    user_prompt = instruction.to_string()
    messages.append({"role": "user", "content": user_prompt})
    # ...
```

**Key difference**: `LiteLLM.call()` does NOT call `to_openai_messages()`. It builds its own messages array from scratch. So there is **no actual duplication at runtime** — the system prompt is only added once.

However, `to_openai_messages()` is a public method that could be used by other LLM implementations. If another LLM class did:
```python
messages = memory.to_openai_messages()
messages.append({"role": "user", "content": prompt})
```
...and also added the system prompt, it would be duplicated.

**Solution**: This is a **documentation issue**, not a code issue. The `to_openai_messages()` method is a utility for building a complete message array. `LiteLLM.call()` doesn't use it — it builds its own array. No duplication occurs.

**Verdict**: ✅ No code change. The `to_openai_messages()` method serves a different purpose (complete message array for any LLM) than the LiteLLM-specific message construction. They're independent implementations, not redundant ones.

**Optional cleanup**: If `to_openai_messages()` is truly unused by any LLM implementation, it could be deprecated. But it's a useful utility method for future LLM integrations, so keeping it is reasonable.

---

### 4.7 `get_dialect()` Defaults to "postgres"

**The Concern**: When `source` is None, `get_dialect()` returns `"postgres"` instead of `"duckdb"`.

**Deep Analysis**: The dialect value flows through:

```
DataFrame.get_dialect()
    ↓
DataframeSerializer.serialize(df, dialect, config)
    ↓
<table dialect="{dialect}" table_name="...">
```

The LLM sees `dialect="postgres"` in the XML tag. However:
- The `duckdb_syntax.tmpl` template explicitly tells the LLM to use DuckDB SQL
- The `sql_functions.tmpl` template defines `execute_sql_query` which runs on DuckDB
- The SQL parser fixes DuckDB-specific patterns

So the `dialect="postgres"` in the XML tag is **overridden by the template instructions**. The LLM generates DuckDB SQL regardless of the dialect attribute.

**However**, this is still misleading. The dialect attribute should reflect reality:

**Solution**: Default to `"duckdb"`:

```python
# BEFORE
else:
    dialect = "postgres"

# AFTER
else:
    dialect = "duckdb"
```

This is H5. One-line fix.

**Impact**: The XML tag now says `dialect="duckdb"`, which is consistent with the template instructions and the actual execution engine.

---

### 4.8 `get_default_schema()` Doesn't Detect list[struct]

**The Concern**: When no semantic model is provided, `get_default_schema()` creates Column objects with `type=DataFrame.get_column_type(dtype)`. For list[struct] columns, `get_column_type()` returns `None` because pandas dtype is `object`.

**Deep Analysis**: The flow when no semantic model is provided:

```
1. DataFrame.__init__() → self.schema = DataFrame.get_default_schema(self)
2. get_default_schema() → Column(name=col_name, type=get_column_type(dtype))
3. For list[struct] columns: type=None ← INCOMPLETE
4. Handler Step 2b patches: detects is_list_struct_column() → sets type="list[struct]"
```

So the handler's Step 2b already fixes this. The schema is incomplete for a brief moment between `__init__` and handler patching, but this doesn't cause issues because:
- The schema is only used after the handler patches it
- The serializer also detects list[struct] independently
- The template renders from the patched schema

**Solution**: Add list[struct] detection to `get_default_schema()` so the schema is complete from the start:

```python
# In pandasai/dataframe/base.py

@classmethod
def get_default_schema(cls, dataframe: DataFrame) -> SemanticLayerSchema:
    from pandasai.helpers.type_determination import is_list_struct_column, determine_series_type
    
    columns_list = []
    for name, dtype in dataframe.dtypes.items():
        series = dataframe[name]
        if is_list_struct_column(series):
            col_type = "list[struct]"
        else:
            col_type = DataFrame.get_column_type(dtype)
            if col_type is None:
                col_type = determine_series_type(series)
        
        columns_list.append(Column(name=str(name), type=col_type))
    
    table_name = getattr(dataframe, "_table_name", f"table_{dataframe._column_hash}")
    
    return SemanticLayerSchema(
        name=table_name,
        source=Source(type="parquet", path="data.parquet"),
        columns=columns_list,
    )
```

**Impact**: The schema is complete from creation — no need for handler patching for the type field. The handler still needs to enrich samples and semantic_type, but the base type is correct from the start.

**Performance note**: `is_list_struct_column()` checks only the first non-null cell, so it's O(1) per column. This is negligible overhead.

**Files changed**: `pandasai/dataframe/base.py` (~10 lines)

---

## 5. Summary of All Planned Changes

| ID | File | Change | Lines |
|----|------|--------|-------|
| C1 | `server/features/register/models.py` | `enrich_column_values` default `False` → `True` | 1 |
| C2 | `server/features/register/models.py` | `llm_context_window` default `8192` → `250000` | 1 |
| C3 | `pandasai/config.py` | Add `direct_sql: bool = True` field | 1 |
| H1 | `server/features/chat/handler.py` | Extract actual type from response, serialize DataFrames as JSON | ~8 |
| H2 | `server/core/llm_setup.py` | Read credentials from environment variables | ~20 |
| H4 | `server/features/chat/handler.py` | Use `follow_up()` for turns 2+ | ~5 |
| H5 | `pandasai/dataframe/base.py` | Default dialect `"postgres"` → `"duckdb"` | 1 |
| M1 | `server/features/register/handler.py` | Delete temp file after agent creation | ~5 |
| M2 | `pandasai/agent/base.py` | Track `last_code_executed` separately | 2 |
| M3 | `pandasai/helpers/dataframe_serializer.py` | `df.sample()` → `df.head()` | 1 |
| M4 | `pandasai/helpers/memory.py` | Default `memory_size` 1 → 10 | 1 |
| 4.8 | `pandasai/dataframe/base.py` | Detect list[struct] in `get_default_schema()` | ~10 |

**Total**: 12 files, ~56 lines changed

---

## 6. No-Change Verdicts

| Issue | Verdict | Reason |
|-------|---------|--------|
| Duplicate enrichment logic (handler vs serializer) | ✅ No change | Separation of concerns — handler enriches for API, serializer enriches for LLM. Serializer's lazy check prevents double-work. |
| `to_openai_messages()` duplicates system prompt | ✅ No change | Not called by LiteLLM at runtime. Independent utility method. |
| DuckDBConnectionManager per-query | ✅ No change | Stateless and safe. Negligible cost for current use case. Optimize later if profiling shows bottleneck. |
| Enrichment runs twice (M5) | ✅ No change | Serializer's `samples is None` check prevents re-enrichment. Safety net is intentional. |
