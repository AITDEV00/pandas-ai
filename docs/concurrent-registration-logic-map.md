# Concurrent Registration & LLM Rate-Limit — Logic Map

> **Method**: [Logic Mapping Technique](../logic_mapping_technique.md) — Phase 1
> (Trace) followed by Phase 2 (verify with real load).
>
> **Question**: Can multiple files be registered concurrently? If so, where is
> the bottleneck that caused ~181s registration timeouts?

---

## 1. Executive Summary

**YES — multiple files CAN be registered concurrently.** Each registration is
fully isolated (own temp file, own DataFrame, own LiteLLM client, own DuckDB
connection). The `AgentStore` is thread-safe. There is **no lock or semaphore**
that serializes registrations.

The **bottleneck is unbounded concurrent LLM calls**. With N simultaneous
registrations, each calling the LLM (description auto-fill + column selection
during chat), the requests pile up against the single httpx connection pool
and the remote LiteLLM/backend rate limits. This produces the observed ~181s
parallel timeouts, even though each individual registration is fast in
isolation.

---

## 2. Concurrency Trace — Registration Path

```
HTTP POST /api/register/base64
  │
  ├─ [server/features/register/router.py] register_base64()
  │     │  await asyncio.to_thread(handle_base64_upload, ...)
  │     │  ── CORO → THREAD POOL (default ThreadPoolExecutor max_workers=32)
  │     ▼
  │  [server/features/register/handler.py] handle_base64_upload()
  │     ├─ mkstemp() → unique temp file per call          ← ISOLATED
  │     ├─ create_dataframe_from_file(...)                ← ISOLATED df
  │     ├─ parse_json_array_columns(...)                  ← per-df
  │     ├─ apply_schema / cast_struct_field_types          ← per-df
  │     ├─ ColumnValueExtractor.extract(...)               ← per-df
  │     ├─ setup_structured_llm(...) / create_litellm()    ← NEW httpx.Client+openai per call
  │     ├─ fill_missing_descriptions(df, llm)              ← LLM CALL(s)
  │     ├─ create_litellm(api_key, base_url, model_name)   ← custom LLM client
  │     └─ create_agent(...) → AgentStore.set(conv_id, agent)
  │
  ├─ [server/core/agent_store.py] AgentStore
  │     └─ threading.Lock() guards _agents dict           ← THREAD-SAFE
  │
  └─ [pandasai/data_loader/duck_db_connection_manager.py] DuckDBConnectionManager
        └─ created fresh per SQL query inside _execute_sql_query()  ← per-query, not shared
```

**Parallelism facts (trace-verified):**
- `asyncio.to_thread` frees the event loop; 32 worker threads can run
  registrations simultaneously (default ThreadPoolExecutor in `asyncio`).
- No `asyncio.Semaphore` around LLM calls anywhere in the register path.
- Single uvicorn worker (`--reload`, no `--workers N` in Makefile.build /
  Dockerfile), so everything runs in ONE process — good for sharing AgentStore,
  but it also means all concurrent LLM calls share one process's connection pool.

---

## 3. The Bottleneck (why parallel timeouts)

| Layer | Limit | Effect under N concurrent |
|---|---|---|
| `httpx.Client` | default max_connections=100, but LiteLLM uses its own pooled client (~10 per pool) | Threads block waiting for a free connection |
| Remote LLM (litellm.adeoaiengine.ecouncil.ae) | server-side rate limit / queue | Requests queue; each LLM call takes longer |
| uvicorn single worker | 1 event loop | All `to_thread` results funnel back through it |
| Retry/timeout | `MAX_RETRIES` + httpx timeout | Nested retries × N concurrent = multiplicative delay |

**Consequence:** With 15 concurrent registrations, the LLM call that normally
takes ~2s under load takes ~15–30s (queueing), and the 181s client timeout
fires before all threads drain. This is a **resource-contention / rate-limit
problem**, not a correctness problem.

---

## 4. Recommendations

1. **Add an `asyncio.Semaphore`** around the LLM-bound sections of
   `handle_base64_upload` (description auto-fill) and the chat codegen, with a
   reasonable concurrency (e.g. 4–8). This prevents unbounded queueing against
   the LLM backend.
2. **Optionally raise httpx limits** on the LLM clients in
   `server/core/llm_setup.py::create_litellm()` (or configure LiteLLM pooling)
   to match the intended concurrency.
3. **Raise the HTTP timeout** on the register route (from 180s) OR return a
   202 + poll, so long registrations don't look like failures.
4. **Increase uvicorn workers** only if LLM concurrency is capped; otherwise
   more workers = more parallel LLM calls = more queueing.

---

## 5. Verification

See the running stability harness `tests/e2e/run_stability.py` — it registers +
chats the same query sequentially and measures timing per run. For a true
concurrency stress test, fire many `/register` calls concurrently and observe
latency/error distribution; the semaphore change should flatten the tail.