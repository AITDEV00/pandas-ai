# Column Selection Isolation Plan — Step 2 Memory Isolation

**Date**: 2026-05-19  
**Status**: Proposed  
**Scope**: `pandasai/agent/base.py` → `_process_query()`  

---

## Problem

When column selection (Step 1) trims a DataFrame to a subset of columns, Step 2 (code generation) can still "see" columns from previous turns through two leak vectors:

| Leak Vector | Source | What Leaks |
|---|---|---|
| `last_code_generated` in prompt template | `generate_python_code_with_sql.tmpl` line 25-27 | Column names from previous turn's code |
| `_store_assistant_message` in memory | All previous turns' code in conversation history | Column names from ALL previous column selections |

The LLM may copy column references from previous code, generating SQL against columns that don't exist in the trimmed DataFrame.

## Design Principle

> **Step 1 (Column Selection) owns the conversation context.**  
> **Step 2 (Code Generation) owns only the trimmed schema + current query.**

Step 1 needs full history to understand ambiguous follow-ups like "now sort by revenue". Step 2 only needs to know what columns are available and what question to answer — the trimmed schema already encodes the result of Step 1's reasoning.

## Proposed Change

### Single file: `pandasai/agent/base.py` — `_process_query()` method

**What**: Before Step 2, swap `self._state.memory` with a fresh empty Memory and blank `last_code_generated`. After Step 2 completes (success or error), **transfer Step 2's messages back into the original memory** and restore it — so Step 1 on future turns retains full context including the code that was just executed.

**How** (pseudocode of the `_process_query` method):

```python
def _process_query(self, query, output_type=None):
    # ... existing setup code (unchanged) ...

    # Step 1: Column Selection (unchanged — uses full memory via build_step1_memory)
    original_dfs = None
    should_select = self._should_select_columns()
    # ... existing Step 1 logic ...

    # === NEW: Isolate Step 2 from conversation history ===
    column_selection_was_applied = original_dfs is not None
    saved_memory = None
    saved_last_code = None
    if column_selection_was_applied:
        # Save the full memory (Step 1 needs it on future turns)
        saved_memory = self._state.memory
        saved_last_code = self._state.last_code_generated

        # Create an empty Memory — only system prompt preserved
        step2_memory = Memory(
            memory_size=1,
            agent_description=saved_memory.agent_description,
        )
        self._state.memory = step2_memory
        self._state.last_code_generated = None
    # === END NEW ===

    # Step 2: Code Generation (unchanged logic, but now runs in isolation)
    code = self.generate_code_with_retries(str(query))

    try:
        result = self.execute_with_retries(code)
        self._store_assistant_message(result, output_type)
        self._state.logger.log("Response generated successfully.")
        return result
    except CodeExecutionError:
        return self._handle_exception(code)
    finally:
        # === NEW: Merge Step 2 messages back into original memory ===
        if saved_memory is not None:
            # Transfer any messages Step 2 added (the user query +
            # assistant response with executed code) back into the
            # saved memory so Step 1 on the NEXT turn has full context.
            for msg in self._state.memory.all():
                saved_memory.add(msg["message"], msg["is_user"])
            self._state.memory = saved_memory
            self._state.last_code_generated = saved_last_code
        # === END NEW ===

        # Existing: ALWAYS restore original DataFrames
        if original_dfs is not None:
            self._state.dfs = original_dfs
```

### Why This Works

1. **`generate_code()` adds the query to memory** — but since Step 2 memory is empty, the only message in it is the current query. The prompt template's `{% if last_code_generated and context.memory.count() > 0 %}` evaluates to `False` because `last_code_generated` is `None`.

2. **`_store_assistant_message()` writes to Step 2 memory** — the executed code is stored in the isolated Step 2 memory. In `finally`, we transfer those messages back into `saved_memory`. This means Step 1 on the NEXT turn sees the full conversation: previous queries + previous code + the current turn's code. Step 2 on the current turn never sees it.

3. **No template changes needed** — the `{% if last_code_generated and context.memory.count() > 0 %}` guard in `generate_python_code_with_sql.tmpl` naturally evaluates to `False` when memory is empty and `last_code_generated` is `None`.

4. **Error retries still work** — `_regenerate_code_after_error()` uses `self._state.last_code_generated` which is `None`, but it receives the failed `code` as a parameter directly, so it can still correct errors. The error-correction prompt (`CorrectExecuteSQLQueryUsageErrorPrompt`) shows the failed code + error — this is fine because the failed code was generated against the trimmed schema.

5. **No change when column selection is NOT applied** — `column_selection_was_applied` is `False`, so the memory/last_code_generated swap is skipped entirely. The existing behavior is preserved for narrow tables.

6. **Step 1 retains full context** — because Step 2's messages (user query + assistant response with executed code) are transferred back to `saved_memory` in `finally`, the next turn's Step 1 has access to the complete conversation history including all previously executed code. This is identical to the current behavior — only Step 2 is isolated.

## Impact Analysis

### Functions Affected

| Function | Change | Impact |
|---|---|---|
| `_process_query()` | Add memory swap before Step 2, restore in `finally` | **Primary change site** |
| `generate_code()` | No code change | Called with empty memory → adds only current query → prompt has no history |
| `generate_code_with_retries()` | No code change | Works as before |
| `_regenerate_code_after_error()` | No code change | Already receives `code` as parameter, doesn't rely on memory |
| `execute_with_retries()` | No code change | Works as before |
| `_store_assistant_message()` | No code change | Writes to Step 2 memory (transferred back to `saved_memory` in `finally`) |
| `_apply_column_selection()` | No code change | Already uses its own temporary memory for Step 1 |
| `build_step1_memory()` | No code change | Still copies full history for Step 1 |
| `_execute_sql_query()` | No code change | Works with trimmed DFs as before |

### Template Files — NO CHANGES

| Template | Impact |
|---|---|
| `generate_python_code_with_sql.tmpl` | No change. The `{% if last_code_generated and context.memory.count() > 0 %}` guard naturally skips the "Last code generated" block when memory is empty and `last_code_generated` is `None`. |
| `shared/dataframe.tmpl` | No change. Renders from `df.schema.columns` which is already trimmed. |
| `shared/search_strategy.tmpl` | No change. Iterates `df.schema.columns` which is already trimmed. |

### Behavioral Changes

| Scenario | Before | After |
|---|---|---|
| **Single turn, column selection ON** | Step 2 has no history (first turn) → no leak possible | Same — no change |
| **Multi-turn, column selection ON** | Step 2 sees previous code + conversation history → potential leak | Step 2 sees only trimmed schema + current query → leak eliminated |
| **Multi-turn, column selection OFF** | Step 2 sees full history → no leak (all columns available anyway) | Same — no change (swap is skipped) |
| **Error retry on Step 2** | Retry prompt includes failed code + error trace | Same — `_regenerate_code_after_error` receives the code directly, doesn't use memory |
| **Step 1 on next turn** | Has full memory including previous assistant messages | Same — Step 2's messages are transferred back to `saved_memory` in `finally`, so Step 1 retains full context including executed code |

### Edge Cases

1. **`chat()` vs `follow_up()`**: Both call `_process_query()`. `chat()` clears memory first (`start_new_conversation()`), so on the first turn there's no history to leak anyway. `follow_up()` preserves memory — this is where the fix matters.

2. **`output_type="dataframe"` or `"plot"`**: `_store_assistant_message()` returns early (only stores for "string"/"number"). So no code is stored in memory for these types. The fix doesn't change this behavior — the Step 2 memory is still isolated, and the `finally` block still transfers whatever messages exist (just the user query, no assistant response).

3. **Multiple DataFrames**: The fix applies to all trimmed DFs equally. Each DF is trimmed independently in `_apply_column_selection()`.

4. **Column selection fails**: If `_apply_column_selection()` throws an exception, it's caught internally and logged. `original_dfs` is set but `self._state.dfs` is unchanged (all columns kept). `column_selection_was_applied` would be `True` but the DFs aren't actually trimmed. **Mitigation**: Check `sum(len(df.columns) for df in self._state.dfs)` after Step 1 to confirm trimming happened, or simply check that the trimmed DFs have fewer columns than the originals.

5. **`generate_code()` adds query to Step 2 memory**: When `generate_code()` calls `self._state.memory.add(str(query), is_user=True)`, it adds the query to the empty Step 2 memory. This is fine — the query is the current question, not history. It's needed for the prompt template to render correctly.

## Step 2's Code IS Preserved for Future Step 1

After Step 2 executes, `_store_assistant_message()` writes the executed code to the isolated Step 2 memory. In `finally`, we **transfer** those messages back into `saved_memory` before restoring it. This is not optional — it's core to the design:

- **Step 2 on Turn N** runs in isolation (no history) → cannot leak columns from previous turns
- **Step 1 on Turn N+1** sees full history (including Turn N's executed code) → can understand context like "the user was looking at budget columns"

The data flow across turns:

```
Turn N:
  Step 1 → uses full memory (queries + code from turns 1..N-1)
  Step 2 → uses empty memory (isolated, no leaks)
  finally → transfers Step 2's messages (query + code) back into saved_memory
           → restores saved_memory as self._state.memory

Turn N+1:
  Step 1 → uses full memory (queries + code from turns 1..N)  ← includes Turn N's code
  Step 2 → uses empty memory (isolated, no leaks)
  finally → transfers Step 2's messages back into saved_memory
```

This gives Step 1 the richest possible context while keeping Step 2 hermetically sealed.

## Summary of Changes

| File | Lines Changed | Description |
|---|---|---|
| `pandasai/agent/base.py` | ~20 lines added to `_process_query()` | Memory swap before Step 2, merge-back + restore in `finally` |
| All other files | 0 | No changes needed |

The fix is **minimal, local, and reversible** — it touches one method in one file, and the logic is straightforward: isolate Step 2's memory when column selection is active, restore it after.
