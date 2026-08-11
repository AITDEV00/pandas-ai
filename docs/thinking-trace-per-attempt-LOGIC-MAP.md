# Logic Map — Per-Attempt LLM Thinking Trace Capture

> **Goal**: Capture the LLM thinking/reasoning trace (`reasoning_content`) for
> **EVERY** code-generation attempt — including the FIRST one and each retry —
> and render each attempt's trace alongside its code in the conversation log.
>
> **Current gap**: `code_generation_thinking_trace` is a single state field that
> gets **overwritten** by the *last* generation call. Per-attempt sections in
> the log (`Generation Attempt 1/2/3`) show each code, but the thinking trace
> shown belongs only to the final call. The buggy first-call reasoning is lost.

---

## Phase 1 — Trace: Full Call Chain (entry → exit)

### Entry point
`server/features/chat/handler.py` — POST `/api/chat` → `_extract_pipeline_log()` writes the Markdown log.

### Call chain

```
Agent._process_query()  [pandasai/agent/base.py]
  │
  ├─► generate_code_with_retries(query)        [agent/base.py:223]
  │     │  loop `attempt in range(1 + max_retries)`
  │     ├─ attempt 0 ─► generate_code(query)               [agent/base.py:114]
  │     │                  └─► _code_generator.generate_code(prompt)  [core/code_generation/base.py:16]
  │     │                       ├─► llm.generate_code(prompt, context, sampling_params)
  │     │                       │     └─► LLM.call() → LiteLLM.call()  [extensions/llms/litellm/litellm.py]
  │     │                       │           ├─ sets self._last_thinking_trace = reasoning_content
  │     │                       │           └─ returns content
  │     │                       ├─► code_generation_thinking_trace = _last_thinking_trace   ← OVERWRITES
  │     │                       └─► validate_and_clean_code()
  │     │
  │     ├─ attempt > 0 ─► _regenerate_code_after_error(last_code, exception)  [agent/base.py:540]
  │     │                  └─► _code_generator.generate_code(prompt)  (same as above → overwrites again)
  │     │
  │     └─► appends to code_attempts[]  {phase, attempt, code, error}   ← NO thinking_trace here
  │
  ├─► execute_with_retries(code)              [agent/base.py:275]
  │    └─ on error ─► _regenerate_code_after_error(code, e)  (regenerates → overwrites trace)
  │
  └─► returns response

** → _write_readable_log()  [server/features/chat/handler.py]
      ├─ "Code Generation Attempts" section reads code_attempts[]   ← renders per-attempt code
      └─ "Code Generation — LLM Thinking Trace" reads code_generation_thinking_trace  ← LAST trace only
```

### Data contracts

| Function | Input | Output / side effect |
|---|---|---|
| `LiteLLM.call()` | messages | `content` string; sets `self._last_thinking_trace` |
| `CodeGenerator.generate_code()` | prompt | cleaned code; **writes** `context.code_generation_thinking_trace` |
| `Agent.generate_code_with_retries()` | query | code; **appends** `code_attempts[]` entry |
| `Agent._regenerate_code_after_error()` | code, error | new code; **overwrites** `code_generation_thinking_trace` |
| `_write_readable_log()` | payload dict | writes `.md` log |

### Root cause
`code_attempts[]` entries carry `code` + `error` but **not** `thinking_trace`.
Since `code_generation_thinking_trace` is a scalar overwritten on each call, the
only trace available at log time is the LAST one. The first/any buggy attempt's
reasoning is discarded.

---

## Phase 3 — Build Plan (Vertical Slice / targeted edits)

1. **`pandasai/agent/base.py`** — `generate_code_with_retries()`:
   - In the success branch, add `"thinking_trace": self._state.code_generation_thinking_trace` to the appended `code_attempts` entry.
   - In the exception branch, add `"thinking_trace": self._state.code_generation_thinking_trace` to the appended entry.
   - This captures the trace produced by the *just-executed* generation call.

2. **`pandasai/agent/base.py`** — `execute_with_retries()`:
   - Add `"thinking_trace": self._state.code_generation_thinking_trace` to both success and exception `code_attempts` entries (the trace that produced the code being executed).

3. **`server/features/chat/handler.py`** — `_write_readable_log()`:
   - In the generation-attempts renderer and execution-attempts renderer, when an entry has `thinking_trace`, render it in a `<details>` block under that attempt (after the code).

### Why this captures the FIRST attempt
- `CodeGenerator.generate_code()` sets `code_generation_thinking_trace` on **every** call.
- `generate_code_with_retries()` reads it immediately after `self.generate_code()` / `_regenerate_code_after_error()` and snapshots it into that attempt's `code_attempts` entry **before** any later call can overwrite it.
- Since the first attempt (attempt 0) appends its entry with the trace at that moment, the first call's reasoning is preserved.

---

## Phase 3 — Build: DONE ✅ (verified)

Implemented per the plan:

- **`pandasai/agent/base.py`**
  - `generate_code_with_retries()`: both success and exception branches now append
    `"thinking_trace": self._state.code_generation_thinking_trace` into the
    `code_attempts[]` entry — snapshotted immediately after the generation call,
    BEFORE a later retry can overwrite the scalar.
  - `execute_with_retries()`: both branches append the same `thinking_trace` into
    the execution attempt entry.
- **`server/features/chat/handler.py`**
  - Generation Attempt renderer: after each code block, renders the entry's
    `thinking_trace` in a `<details>LLM Thinking Trace (this attempt)</details>`.
  - Execution Attempt renderer: same, `<details>LLM Thinking (this attempt)</details>`.
- `code_generation_thinking_trace` scalar still holds the final trace
  (backward-compatible with the standalone "Code Generation — LLM Thinking Trace" section).

Unit tests: `tests/unit_tests/agent/test_agent.py` → **38 passed**.

## Phase 4 — Verify: DONE ✅

E2E run `tests/e2e/run_stability.py --question Q19 --runs 2 --no-cache` produced
conv log `4499025d`. Structure confirmed:

| Attempt | Line | Per-attempt trace | Notes |
|---|---|---|---|
| Generation Attempt 1 | 690 | ✅ (778) | Initial reasoning (schema + SQL plan) |
| Execution Attempt 1 (❌) | 1026 | ✅ (1155) | Reasoning behind the code that failed |
| Execution Attempt 2 (✅) | 1401 | ✅ (1491) | Retry fix reasoning — caught `1173` vs `1177` typo + struct access fix |

Each attempt carries its **own** trace; the first (buggy) reasoning is no longer
overwritten. Unit tests: `tests/unit_tests/agent/test_agent.py` → 38 passed.

**Bonus finding**: the Execution Attempt 2 trace revealed the model self-diagnosing
a `1173` vs `1177` employee-ID typo and a struct-alias (`q[...]` → `rec[...]`)
bug — more evidence of the "LLM hallucinates identifiers within a code block"
class, now visible per-attempt.