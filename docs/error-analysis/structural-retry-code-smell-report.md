# Code Smell Report — Structural Retry Cap + Error Propagation Implementation

> **Method**: 4-layer Code Smell Detection Technique (L1 automated tools → L2
> per-file checklist → L3 cross-reference → L4 recheck).
> **Scope**: The implemented changes for the structural pre-catch retry cap and
> the meaningful HTTP error responses. Only NEW smells introduced by this
> implementation were fixed; pre-existing smells are flagged but left alone.

---

## Files Reviewed

| File | Why |
|---|---|
| `pandasai/config.py` | Added `max_structural_retries` field |
| `pandasai/agent/base.py` | Retry loop, `_is_structural_failure`, `_handle_exception` |
| `pandasai/core/code_generation/base.py` | `_run_structural_self_review` |
| `pandasai/exceptions.py` | New exception class |
| `server/features/chat/handler.py` | HTTP status code + message surfacing |
| `deployments/dep-icarus-pandasai-server.yaml` | `MAX_STRUCTURAL_RETRIES` env |

---

## L1 — Automated Tool Baseline

Tools: pyflakes, vulture, ruff (actionable rules only).

### Findings attributable to THIS implementation

| Rule | Location | Severity | Smell |
|---|---|---|---|
| B904 | `server/features/chat/handler.py:750` | High | `raise HTTPException(...)` inside `except` without `from e` — masks the original exception chain |

### Pre-existing findings (flagged, fixed in a separate cleanup pass)

| Rule | Location | Status |
|---|---|---|
| F401 | `handler.py:1` | ✅ Fixed — module `json` import removed, then hoisted to top-level with local imports consolidated |
| F541 | `handler.py:74` | ✅ Fixed — removed `f` prefix from `f"**Status:** ❌ ERROR\n\n"` |
| F811 | `handler.py:526` | ✅ Fixed — local `import json` removed (top-level import now used) |
| PLC0415 | `handler.py:426,525` | ✅ Fixed — local `import json`/`import json as _json` replaced by top-level `json` |
| F401 | `exceptions.py:7` | ✅ Fixed — unused `PANDABI_SETUP_MESSAGE` import removed |
| — | `dep-icarus-pandasai-server.yaml` | ✅ Fixed — added `resources` block (requests 500m/1Gi, limits 2/4Gi) |

### No findings
- vulture: no dead code in the reviewed files.
- ruff `F`/`E9`/`B`/`SIM`: no new actionable issues after fixes.

---

## L2 — Per-File Semantic Checklist

### `pandasai/agent/base.py`
- [x] **Stale docstring (FIXED)**: `generate_code_with_retries` docstring said
      "default 2 = initial + 1 regeneration" but the config default is now 3.
      Updated to "default 3 = initial + 2 regenerations".
- [x] `except Exception` uses `logger.log` with the message — acceptable here
      (the retry loop logs each attempt deliberately, not an error path).
- [x] New methods have docstrings.

### `server/features/chat/handler.py`
- [x] **B904 (FIXED)**: added `from e` to the `raise HTTPException` in the
      `except Exception` block to preserve the exception chain.

### `pandasai/core/code_generation/base.py`
- [x] `_run_structural_self_review` docstring updated to reflect the new
      exception type (was "Raises a ValueError", now `StructuralValidationError`).

---

## L3 — Cross-Reference Analysis (the important one)

### Smell found: fragile magic-string coupling

**Before:**
```python
# pandasai/agent/base.py
def _is_structural_failure(self, error):
    msg = str(error)
    return (isinstance(error, ValueError)
            and msg.startswith("Deterministic code self-review found:"))
```
The prefix string `"Deterministic code self-review found:"` is defined in
`structural_validator.py:903` (`format_problems`). **If that message format
ever changed, the structural-failure detection in the agent would silently
break** — the retry loop would stop applying the structural cap and fall back
to the full (expensive) retry budget, and the meaningful error message would
never be produced. This is a definition↔usage coupling that L3 exists to catch.

**Fix:** introduced a dedicated exception type:
```python
# pandasai/exceptions.py
class StructuralValidationError(ValueError):
    """Raised when the deterministic structural self-review rejects code..."""
```
- `_run_structural_self_review` now raises `StructuralValidationError(msg)`.
- `_is_structural_failure` now matches `isinstance(error, StructuralValidationError)`.
- Subclassing `ValueError` preserves compatibility with any generic `except ValueError`
  handling elsewhere; the retry prompt still receives the same message text.

### Cross-check: is `StructuralValidationError` wired everywhere it should be?

| Consumer | Wired? |
|---|---|
| `code_generation/base.py` raise | ✅ yes |
| `agent/base.py` `_is_structural_failure` | ✅ yes |
| `agent/base.py` import | ✅ yes |

### Cross-check: `max_structural_retries` config → usage

| Consumer | Wired? |
|---|---|
| `config.py` definition (reads `MAX_STRUCTURAL_RETRIES`, default 3) | ✅ |
| `agent/base.py` `generate_code_with_retries` reads it | ✅ |
| `agent/base.py` config_snapshot logs it | ✅ |
| `deployments/dep-icarus-pandasai-server.yaml` sets `"3"` | ✅ |
| docstring mentions "default 3" | ✅ (after L2 fix) |

---

## L4 — Fix-Then-Recheck Loop

| Step | Result |
|---|---|
| 1. L1 baseline | Recorded (B904 + pre-existing) |
| 2. L2 checklist | Stale docstring found |
| 3. L3 cross-reference | Magic-string coupling found |
| 4. Applied fixes | `StructuralValidationError` class + raise + type-match + docstring + `from e` |
| 5. Re-run L1 | ✅ No new findings; `agent/base.py`, `exceptions.py`, `code_generation/base.py` clean |
| 6. Import/circular check | ✅ `CodeGenerator` + `Agent` both import; `StructuralValidationError` is a `ValueError` subclass |
| 7. Smoke | Manual code inspection — behavior preserved (retry prompt still gets message) |

---

## What Changed

### New
- `pandasai/exceptions.py`: `StructuralValidationError(ValueError)`

### Modified
- `pandasai/core/code_generation/base.py`: raise `StructuralValidationError` instead of bare `ValueError`
- `pandasai/agent/base.py`: `_is_structural_failure` matches by type; stale docstring corrected
- `server/features/chat/handler.py`: `raise ... from e`

### Deliberately NOT touched (pre-existing)
- handler.py `json` import issues, `exceptions.py` `PANDABI_SETUP_MESSAGE`, YAML `resources`

### Cleanup-pass changes (second pass)
- `server/features/chat/handler.py`: removed unused module `json` import, fixed F541
  empty f-string, removed redundant local `import json` / `import json as _json`,
  hoisted `json` back to top level.
- `pandasai/exceptions.py`: removed unused `PANDABI_SETUP_MESSAGE` import.
- `deployments/dep-icarus-pandasai-server.yaml`: added container `resources` block.
- `docs/error-analysis/structural-retry-code-smell-report.md`: marked those rows fixed.

### Modernization changes (third agent)
- `UP006/UP007/UP035/UP045`: `typing.List/Dict/Tuple/Optional/Union` →
  `list`/`dict`/`tuple` and `X | None` across `agent/base.py`, `config.py`,
  `handler.py`. Auto-fixed (63) + trimmed now-unused `typing` imports to
  `from typing import Any`.
- `RET503`: added explicit unreachable `raise exception` after the retry loops in
  `generate_code_with_retries` / `execute_with_retries` (tracks last error).
- `B905`: `zip(original_dfs, self._state.dfs, strict=True)` — both lists always
  same length, so `strict=True` is safe.
- `tests/unit_tests/agent/test_agent.py`: `test_process_query_execution_error`
  now asserts `_handle_exception("invalid_code", ANY)` (matches current
  root-cause-message signature).

### Remaining ruff findings (intentional, left as-is)
- ~~`PLC0415`: function-local imports in `agent/base.py:567,757,859`
  (`ColumnSelector`, `concept_registry`) — deliberate to avoid circular imports.~~

### Circular-import investigation (fourth pass, 2026-08-13)
The three `PLC0415` function-local imports were investigated and found to be an
**unnecessary workaround — there is NO actual circular import**:
- `pandasai/core/response/string.py` → `response/base` → `helpers/json_encoder`
- `pandasai/core/column_selector.py` → `agent/state`, `helpers/concept_registry`,
  `helpers/semantic_matching`
- `pandasai/helpers/concept_registry.py` → `yaml`, stdlib only
- The only back-reference (`dataframe/base.py` importing `agent.base`) is under
  `TYPE_CHECKING`, so it's not evaluated at runtime.

All three imports were hoisted to module top-level in `agent/base.py`. ruff +
pyflakes are now **100% clean (0 remaining findings)**. Import verified,
46 agent tests pass (only pre-existing `test_code_only_stored_when_no_text` fails).
Verified: `test_process_query_execution_error` passes; only pre-existing
`test_code_only_stored_when_no_text` still fails (fails on clean checkout too).