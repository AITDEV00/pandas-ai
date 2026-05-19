# PandasAI Chat Excel Server — Planning & TODO

---

## TODO-1: Refactor Output Types to 3 Categories (snippet / artifact / mixed)

### Problem
Current output types (`string`, `number`, `dataframe`, `plot`, `auto`) are too granular and don't reflect how clients actually consume responses. Small answers (counts, text) and large answers (200-row tables, chart images) need fundamentally different delivery mechanisms — inline vs. file download.

### Proposed Model

| Type | Description | Delivery |
|------|-------------|----------|
| `snippet` | Small text/number — fits in LLM context window. Merges current `string` + `number`. | Inline JSON |
| `artifact` | Large payload — dataframe rows, plot images, CSV exports. Can be multiple per turn. | URL/link |
| `mixed` | Combination — e.g. "give me a chart AND a summary of the trends". Both snippet + artifact(s). | Inline + URLs |

### Source Code Context

**Current output type validation:**
- `server/features/chat/handler.py:10-11` — `SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}`
- `server/features/chat/handler.py:14-30` — `_validate_output_type()` rejects unknown types with HTTP 400
- `server/features/chat/models.py:4` — `ChatRequest.output_type: Optional[str]` — free-form string field

**Current response type classes (PandasAI core):**
- `pandasai/core/response/` — `StringResponse`, `NumberResponse`, `DataFrameResponse`, `ChartResponse`, `ErrorResponse`
- Each has `.value` and `.type` attributes
- `ResponseParser.parse(result, code)` determines type from LLM output; retries on `InvalidLLMOutputType`

**Current response serialization:**
- `server/features/chat/handler.py:124-145` — `handle_chat_query()` serializes based on `actual_type`:
  - `dataframe` → `response.value.to_dict(orient='records')` (inline — can be huge)
  - `string`/`number`/`plot` → `str(response)` (plots become base64 strings — also huge)
- `server/features/chat/models.py:19-25` — `ChatResponse` returns `response: Any`, `type: str`, `last_code_executed`, `selected_columns`

**Current coercion logic:**
- `server/features/chat/handler.py:33-76` — `_coerce_response_type()` attempts type conversion (e.g. number→string)
- This entire function may become unnecessary if we simplify to 3 types

### Implementation Plan

1. **Add artifact storage layer** — new `server/core/artifact_store.py` to persist generated files (CSV, PNG, etc.)
   - Similar pattern to `AgentStore`: in-memory dict + TTL eviction, but values are file paths
   - Returns a URL like `/api/artifacts/{artifact_id}` for retrieval
   - Add `GET /api/artifacts/{artifact_id}` route for download

2. **Update `ChatRequest` model** — `server/features/chat/models.py`
   - Change `output_type` field to accept `"snippet"`, `"artifact"`, `"mixed"` (keep backward compat for old types)
   - Map old types: `string|number` → `snippet`, `dataframe|plot` → `artifact`

3. **Update `ChatResponse` model** — `server/features/chat/models.py`
   - Add `artifacts: Optional[List[ArtifactRef]]` field where `ArtifactRef = {id, url, type, filename}`
   - `snippet` responses: `response` field has inline value, `artifacts` is null
   - `artifact` responses: `response` has summary/metadata, `artifacts` has download links
   - `mixed` responses: both populated

4. **Update `handle_chat_query()`** — `server/features/chat/handler.py`
   - After PandasAI returns, determine if payload is snippet-sized or artifact-sized
   - For `dataframe` results > threshold rows: write to temp file, store in artifact_store, return URL
   - For `plot` results: already a file in PandasAI sandbox — copy to artifact_store, return URL
   - For `snippet` results: serialize inline as before

5. **Backward compatibility** — accept old types in API, map them internally
   - `"string"` / `"number"` / `"auto"` → treated as `"snippet"`
   - `"dataframe"` / `"plot"` → treated as `"artifact"`

---

## TODO-2: Abort In-Progress Chat on Same Conversation ID

### Problem
When a new chat request arrives for a conversation that already has an in-progress request, both run concurrently on the same `Agent` object. This causes:
- **Race condition** (see TODO-3) — shared `agent._state` is mutated by concurrent threads
- **Wasted LLM calls** — the old request's result is discarded by the user anyway
- **Poor UX** — user can't cancel a slow/hung request

The desired behavior: a new request to the same `conversation_id` should **immediately abort** the current in-progress request and start the new one.

### Source Code Context

**Current request flow (no abort mechanism):**
- `server/features/chat/router.py:8-18` — `chat_endpoint()` is `async def` but calls sync `handle_chat_query()`
  - FastAPI runs sync handlers in threadpool — each request gets its own thread
  - No tracking of which conversation_id has an active request
- `server/features/chat/handler.py:79-155` — `handle_chat_query()` runs `agent.chat()` or `agent.follow_up()`
  - These are **synchronous blocking calls** with no cancellation support
- `pandasai/agent/base.py` — `chat()` / `follow_up()` / `generate_code_with_retries()` / `execute_with_retries()`
  - **No abort/cancellation mechanism exists** — no threading events, no signal handlers, no timeout
  - Once started, runs to completion or error

**AgentStore (no concurrency tracking):**
- `server/core/agent_store.py:12-57` — `AgentStore` maps `conversation_id → (Agent, last_access_time)`
  - Thread-safe for get/set via `threading.Lock()`
  - Does NOT track whether an agent is currently processing a request
  - Does NOT prevent concurrent access to the same Agent

### Implementation Plan

1. **Add per-conversation execution tracking** — `server/core/agent_store.py`
   - Add `_active_requests: Dict[str, threading.Event]` — maps conv_id → "cancel" event
   - When a request starts: create/set the cancel event for that conv_id
   - When a new request arrives for same conv_id: set the existing event (signals old request to abort)
   - When a request completes: clear the event

2. **Add abort checkpoints in PandasAI Agent** — `pandasai/agent/base.py`
   - Add `cancel_event: Optional[threading.Event]` to `AgentState`
   - Check `cancel_event.is_set()` at key points:
     - Before `generate_code()` call
     - Before `execute_code()` call
     - Before each retry iteration
   - If set: raise `OperationCancelledError` (new exception) — caught by handler, returns HTTP 409 or 499

3. **Update `handle_chat_query()`** — `server/features/chat/handler.py`
   - Before calling `agent.chat()`/`agent.follow_up()`:
     - Check if conv_id already has an active request → signal it to abort
     - Set the new cancel event on the agent's state
   - In `finally` block: clear the cancel event
   - Catch `OperationCancelledError`: return HTTP 409 "Request superseded by newer query"

4. **Alternative: async-native approach** (more invasive)
   - Convert handler to truly async using `asyncio.create_task()` + cancellation
   - This would require making PandasAI's LLM calls async (LiteLLM supports it)
   - Better long-term but much larger refactor

---

## TODO-3: Fix Race Condition on Same Conversation ID (CRITICAL)

### Problem
Concurrent requests to the **same** `conversation_id` share a single `Agent` object and mutate its `_state` without isolation. This was **confirmed by testing** — all 5 concurrent requests on the same conv_id showed `gen_retry×1` in the logger, proving shared state corruption.

### Evidence
Test: `tests/llm_behavior/test_concurrent_chat_inproc.py` — race condition test section
- 5 concurrent requests on same conv_id → all 5 showed code gen retries
- Root cause: `agent._state.logger` is shared, so retry logs from one thread appear in all threads
- The `agent._state.config` mutations are also shared — per-query overrides can overwrite each other

### Source Code Context

**Shared mutable state (the problem):**
- `pandasai/agent/state.py` — `AgentState` dataclass holds:
  - `config` — mutated per-query in handler (`column_selection_enabled`, `threshold`, `budget_ratio`)
  - `logger` — shared `Logger` instance, all threads write to same `_logs: List[Log]`
  - `memory` — shared `Memory` instance, `chat()` calls `start_new_conversation()` which CLEARS memory
  - `last_code_generated`, `last_code_executed`, `last_prompt_id`, `last_result`, `last_error` — all overwritten by each thread
  - `output_type` — set per-query, visible to all concurrent threads
  - `last_selected_names` — reset at start of `_process_query()`

**Race condition in handler:**
- `server/features/chat/handler.py:89-107` — Per-query config overrides:
  ```python
  # Thread A sets column_selection_enabled=True
  agent._state.config.column_selection_enabled = column_selection_enabled
  # Thread B can read this value before Thread A restores it in finally block
  ```
- `server/features/chat/handler.py:121-126` — chat vs follow_up decision:
  ```python
  if agent._state.memory.count() > 0:
      response = agent.follow_up(query, output_type=validated_output_type)
  else:
      response = agent.chat(query, output_type=validated_output_type)
  ```
  - `chat()` calls `start_new_conversation()` → CLEARS memory for ALL concurrent threads
  - If Thread A calls `chat()` while Thread B is mid-execution, Thread B's memory is wiped

**AgentStore returns the SAME object:**
- `server/core/agent_store.py:32-38` — `get_agent()` returns the Agent reference (not a copy)
- All threads for the same conv_id get the exact same Python object
- No locking, no copy-on-write, no request-level isolation

### Implementation Plan

**Option A: Per-request Agent cloning (safest, simplest)**
1. In `handle_chat_query()`, after `get_agent()`:
   - Deep-copy the agent's state: `agent_copy = copy.deepcopy(agent)`
   - Run the query on `agent_copy`
   - Merge results back: update `agent._state.memory` with the new conversation turn
   - This isolates each request's config mutations, logger writes, and intermediate state
2. Con: memory merge could have ordering issues; deep copy may be expensive for large dataframes

**Option B: Request-level locking (correct, but serializes same-conv requests)**
1. Add `agent_store.acquire_lock(conversation_id)` / `release_lock(conversation_id)`
2. In handler: acquire lock before accessing agent, release in finally
3. Pro: simple, no state corruption
4. Con: same-conv requests are serialized (but this is actually desired — see TODO-2)

**Option C: Combine with TODO-2 (abort mechanism)**
1. If we implement abort (TODO-2), the race condition is largely mitigated:
   - New request aborts old request → only one request active per conv_id at a time
   - No concurrent state mutation → no race condition
2. This is the recommended approach — TODO-2 and TODO-3 should be implemented together

---

## TODO-4: Fix pandasai_litellm `memory.size` → `memory.memory_size` Bug (UPSTREAM)

### Problem
`pandasai_litellm` v0.0.1 references `memory.size` but PandasAI v3's `Memory` class uses `memory_size`. This causes `AttributeError: 'Memory' object has no attribute 'size'` when the LiteLLM adapter tries to trim conversation history.

### Source Code Context
- `.venv/lib/python3.11/site-packages/pandasai_litellm/litellm.py:78` — patched locally:
  ```python
  # BEFORE (broken):  memory.all()[-memory.size:]
  # AFTER  (fixed):   memory.all()[-memory.memory_size:]
  ```
- This is a **third-party package** installed via Poetry — the fix is local only
- Upstream: `pandasai_litellm` needs to be updated to reference `memory.memory_size`

### Implementation Plan
1. File an issue / PR on the `pandasai_litellm` repository
2. Until upstream fix: pin a patched version in `pyproject.toml` or use a post-install hook
3. Current workaround: manual patch in `.venv` (fragile — lost on `poetry install`)

---

## TODO-5: Investigate LLM API Latency Variability (LOW PRIORITY)

### Problem
Concurrent testing showed that **LLM API endpoint variability** is the primary cause of latency spikes (10s+ outliers), NOT code generation retries. Only 2/75 requests (2.7%) had code gen retries, while the worst outliers all had single-attempt generation (G1 E1).

### Evidence
Test: `tests/llm_behavior/test_concurrent_chat_inproc.py` — code generation trace analysis
- Batch n=5: request #3 at 10,343ms — G1 E1 (no retry, just slow LLM response)
- Batch n=20: request #12 at 11,004ms — G1 E1 (no retry, just slow LLM response)
- Batch n=25: request #5 at 11,288ms — G1 E1 (no retry, just slow LLM response)
- Code variation is cosmetic: `COUNT(*) as cnt` vs `COUNT(*) as total_records` — normal sampling behavior

### Source Code Context
- `server/core/llm_setup.py:39-48` — LLM configured with no timeout or retry settings:
  ```python
  custom_httpx_client = httpx.Client(verify=verify_ssl)  # No timeout
  custom_openai_client = openai.OpenAI(api_key=api_key, base_url=base_url, http_client=custom_httpx_client)
  ```
- `server/features/register/models.py:22-30` — `LLMConfigPayload` supports `temperature`, `top_p`, `seed` but these are per-registration, not per-chat-request
- No request-level timeout configuration exists in the server

### Implementation Plan
1. **Add httpx timeout** — `server/core/llm_setup.py`:
   - `httpx.Client(verify=verify_ssl, timeout=httpx.Timeout(60.0, connect=10.0))`
   - Prevents hung requests from blocking threads indefinitely
2. **Add request-level timeout** — `server/features/chat/handler.py`:
   - Optional `timeout_seconds` parameter in `ChatRequest`
   - Use `asyncio.wait_for()` or `threading.Timer` to enforce per-request deadline
3. **Consider `temperature=0` + `seed`** for determinism if the LLM supports it
4. **Monitor LLM endpoint** — add Prometheus metrics or logging for LLM response times
