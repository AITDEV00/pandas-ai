# Strategy Plan: Fixing Struct Column Inconsistencies

**Date**: 2025-05-19  
**Based on**: [ROOT_CAUSE_ANALYSIS.md](./ROOT_CAUSE_ANALYSIS.md)  
**Status**: ✅ **ALL STRATEGIES IMPLEMENTED AND VERIFIED**

---

## Goal

Address all 4 inconsistencies with the least amount of code changes, in a clean and maintainable way.

---

## Design Principles

1. **SINGLE SOURCE OF TRUTH**: The struct field keys in the `samples` dict must always match the actual DuckDB struct field names (the flat keys from the data). This is the ground truth — everything else must align with it.

2. **FIX AT THE SOURCE, NOT THE SYMPTOMS**: The root cause is that `_extract_struct_vocabulary()` calls `get_matching_schema_columns()` with flat data keys against a schema that only has the squashed column. Fix the enrichment function to NOT rely on schema matching for `duckdb_key` — the `duckdb_key` IS the flat key from the data, by definition.

3. **MINIMAL CHANGES**: Each strategy targets exactly one inconsistency with the smallest possible code change. No refactoring of existing working code.

4. **ORDER MATTERS**: Strategies are ordered by dependency. Strategy A fixes the root cause (Inconsistency 2+3). Strategy B fixes the downstream effect (Inconsistency 4). Strategy C fixes the schema design (Inconsistency 1).

---

## Strategy A: Fix `_extract_struct_vocabulary` to use flat keys as `duckdb_key`

**TARGET**: Inconsistency 2 + Inconsistency 3 (root cause)  
**FILE**: `pandasai/helpers/column_enrichment.py`, `_extract_struct_vocabulary()`  
**CHANGE**: 1 function, ~10 lines modified  
**STATUS**: ✅ IMPLEMENTED AND VERIFIED

### Current Behavior (BUGGY)

For each `inner_col` (flat key from data), it calls `get_matching_schema_columns()` to find a `schema_key`, then derives `duckdb_key` by stripping outer brackets.

**Problem**: When the schema only has the squashed column, the first flat key `"Employee Leave Details[Leave Type]"` falsely matches the squashed parent column via Strategy 2b. This produces:
```
schema_key = "[Employee Leave Details[Leave Type][Leave Duration (Days)]...]"
duckdb_key = "Employee Leave Details[Leave Type][Leave Duration (Days)]..."
```
← WRONG

### Proposed Fix

The `duckdb_key` is ALWAYS the flat key from the data. It should NOT be derived from the schema — it comes directly from the struct dict keys that DuckDB uses as field names. The schema matching should only be used for:
1. Finding the canonical `schema_key` (for samples dict key naming)
2. Getting the description and type from the semantic model

Change the logic to:
- a. `duckdb_key = inner_col` (the flat key from the data) — ALWAYS
- b. `schema_key = schema_matches[0].name if schema_matches else inner_col`
- c. Skip schema matches that return `list[struct]` type (these are false positives — the parent squashed column, not an inner field)

### Code Change

**BEFORE** (lines ~120-135):
```python
schema_matches = get_matching_schema_columns(inner_col, df_schema)
schema_key = schema_matches[0].name if schema_matches else inner_col
details = match_column_details_to_schema(inner_col, df_schema)
inner_type = details["type"]
inner_desc = details["description"]

if not inner_type or inner_type == "unknown" or inner_type == "list[struct]":
    inner_type = determine_series_type(inner_series)

...

if inner_samples:
    duckdb_key = schema_key[1:-1] if schema_key.startswith("[") and schema_key.endswith("]") else schema_key
```

**AFTER**:
```python
schema_matches = get_matching_schema_columns(inner_col, df_schema)

# Filter out false-positive matches: an inner field of a struct cannot
# itself be list[struct]. If a schema match returns list[struct], it
# matched the parent squashed column, not an actual inner field.
schema_matches = [
    m for m in schema_matches
    if getattr(m, 'type', None) != 'list[struct]'
]

schema_key = schema_matches[0].name if schema_matches else inner_col
details = match_column_details_to_schema(inner_col, df_schema)
inner_type = details["type"]
inner_desc = details["description"]

if not inner_type or inner_type == "unknown" or inner_type == "list[struct]":
    inner_type = determine_series_type(inner_series)

...

if inner_samples:
    # duckdb_key: ALWAYS the flat key from the data (inner_col)
    duckdb_key = inner_col
```

### Impact

- The samples dict keys will now consistently use `schema_key` (canonical name from semantic model, or flat key if no match)
- `duckdb_key` will ALWAYS be the flat key from the data — CORRECT
- All 5 fields will be present (the first field won't consume the squashed match anymore)

### Verification

After this fix, the samples dict should be:

| Key | duckdb_key | Correct? |
|-----|-----------|----------|
| `Employee Leave Details[Leave Type]` | `Employee Leave Details[Leave Type]` | ✅ |
| `Employee Leave Details[Leave Duration (Days)]` | `Employee Leave Details[Leave Duration (Days)]` | ✅ |
| `Employee Leave Details[Approval Status]` | `Employee Leave Details[Approval Status]` | ✅ |
| `Employee Leave Details[Leave Start Date]` | `Employee Leave Details[Leave Start Date]` | ✅ |
| `Employee Leave Details[Leave End Date]` | `Employee Leave Details[Leave End Date]` | ✅ |

---

## Strategy B: Fix column selector samples filtering to match flat keys

**TARGET**: Inconsistency 4  
**FILE**: `pandasai/core/column_selector.py`, `build_trimmed_dataframe()`  
**CHANGE**: 1 function, ~15 lines modified  
**STATUS**: ✅ IMPLEMENTED AND VERIFIED

### Current Behavior (BUGGY)

The column selector filters samples by `inner_fields`, which are canonical schema column names like `"[Employee Leave Details[Leave Type]]"`. But the samples dict keys are now flat keys like `"Employee Leave Details[Leave Type]"` (after Strategy A fix). None match → `filtered_samples = {}` → `samples = None` → LLM gets no field info.

### Proposed Fix

Add a normalization step that converts both the samples dict keys and the `inner_fields` to a common format for comparison. The simplest approach: strip outer brackets from `inner_fields` and compare against the samples keys.

### Code Change

**BEFORE**:
```python
if inner_fields is not None and col.type == "list[struct]":
    trimmed_col = col.model_copy(deep=True)
    if isinstance(trimmed_col.samples, dict):
        trimmed_col.samples = {
            k: v
            for k, v in trimmed_col.samples.items()
            if k in inner_fields
        }
```

**AFTER**:
```python
if inner_fields is not None and col.type == "list[struct]":
    trimmed_col = col.model_copy(deep=True)
    if isinstance(trimmed_col.samples, dict):
        # Normalize inner_fields for comparison:
        # - Strip outer brackets: "[Parent[Field]]" → "Parent[Field]"
        # - This matches the flat keys used in the samples dict
        normalized_fields = set()
        for f in inner_fields:
            if f.startswith("[") and f.endswith("]"):
                normalized_fields.add(f[1:-1])
            else:
                normalized_fields.add(f)
        # Also keep original names for backward compatibility
        all_fields = set(inner_fields) | normalized_fields
        trimmed_col.samples = {
            k: v
            for k, v in trimmed_col.samples.items()
            if k in all_fields
        }
```

### Verification

After this fix, when `inner_fields = ['[Employee Leave Details[Leave Type]]']`:
- `normalized_fields = {'Employee Leave Details[Leave Type]'}`
- `all_fields = {'[Employee Leave Details[Leave Type]]', 'Employee Leave Details[Leave Type]'}`
- Samples key `"Employee Leave Details[Leave Type]"` IS in `all_fields` → KEPT ✅

---

## Strategy C: Keep individual inner-field columns in the schema alongside squashed

**TARGET**: Inconsistency 1  
**STATUS**: ⏭️ NO CODE CHANGE NEEDED

### Analysis

The register handler removes individual inner-field columns from the schema, leaving only the squashed column. This was originally considered problematic because:
- The LLM sees only the confusing squashed column name
- `_extract_struct_vocabulary` can't find schema matches for flat keys
- The column selector can't resolve inner fields from the schema

However, with Strategy A's fix (using `inner_col` as `duckdb_key`), we don't NEED schema matching for the `duckdb_key`. For the `schema_key` (canonical name) and description, we can fall back to the flat key if no match is found — which is exactly what the current code does.

### Decision

**No code change needed for Inconsistency 1.** Strategy A fixes the downstream impact. The register handler's current behavior is correct — it prevents the LLM from seeing duplicate flat columns.

---

## Strategy D (OPTIONAL): Tighten `get_matching_schema_columns` Strategy 2b

**TARGET**: Inconsistency 3 (defense in depth)  
**STATUS**: ⏭️ NO CODE CHANGE NEEDED

### Analysis

Strategy 2b checks: `f"[{col_name}" in schema_col.name`. This is too loose — it matches any schema column that starts with the same bracket group, even if the rest of the name is completely different.

However, changing this could break other callers. The guard in Strategy A (filtering out `list[struct]` matches) is a more targeted fix.

### Decision

**Don't change `get_matching_schema_columns`.** Strategy A already fixes the problem by not using the false-positive match for `duckdb_key`. Defense-in-depth can be added later if needed.

---

## Final Strategy Summary

| Strategy | Description | Target | Changes | Status |
|----------|-------------|--------|---------|--------|
| A | Fix `_extract_struct_vocabulary` to use flat keys as `duckdb_key`, filter out `list[struct]` false-positive matches | Inc. 2+3 (root) | ~10 lines | ✅ Done |
| B | Fix column selector samples filtering to normalize `inner_fields` for comparison with flat sample keys (strip outer brackets) | Inc. 4 | ~15 lines | ✅ Done |
| C | No change needed — Strategy A fixes the downstream impact of schema column removal | Inc. 1 | 0 lines | ⏭️ Skipped |
| D | No change needed — Strategy A's guard is more targeted than tightening the matcher | Inc. 3 (defense) | 0 lines | ⏭️ Skipped |

**TOTAL CODE CHANGES**: 2 files, ~25 lines

---

## Implementation Results (2025-05-19)

### Strategy A: ✅ IMPLEMENTED AND VERIFIED
**File**: `pandasai/helpers/column_enrichment.py`

Changes made:
1. Added import of `decompose_squashed_name`
2. Added filter to remove false-positive schema matches:
   - `list[struct]` type matches (parent squashed column)
   - Squashed column matches (`decompose_squashed_name` > 1 fields)
3. Changed `duckdb_key` derivation from `schema_key` to `inner_col`

Verification: All 5 Leave fields now present with correct `duckdb_keys`. API verification: `/register/file` returns correct struct samples.

### Strategy B: ✅ IMPLEMENTED AND VERIFIED
**File**: `pandasai/core/column_selector.py`

Changes made:
1. Added normalization of `inner_fields` (strip outer brackets)
2. Combined original + normalized fields for backward-compatible comparison

Verification: Column selector can now match flat sample keys.

### End-to-End Test: ✅ PASSED
**Query**: "what is the percentage by different leave types did Ayesha take?"  
**LLM generated**: `rec['Employee Leave Details[Leave Type]']` ← CORRECT  
**DuckDB query**: SUCCEEDED (no `BinderException`)  
**Result**: Ayesha's leave distribution correctly calculated:
- Remote Work: 42.4%
- Non-Mandatory Leave: 31.8%
- Wellbeing: 21.2%
- Training Leave: 4.5%

---

## Risk Assessment

### Strategy A (`column_enrichment.py`): Risk LOW
- Only changes `_extract_struct_vocabulary`, which is only called for `list[struct]` columns
- The guard (filter out `list[struct]` matches) is safe — inner fields cannot be `list[struct]`
- Using `inner_col` as `duckdb_key` is correct by definition (it IS the struct field name)
- Backward compatible: if schema matches are correct, `schema_key` is still used for the samples dict key

### Strategy B (`column_selector.py`): Risk LOW
- Only adds normalization to the comparison, doesn't change the filtering logic
- Keeps original `inner_fields` in the comparison set for backward compatibility
- The normalization (strip outer brackets) is a well-defined, reversible operation

### Strategies C & D: Risk NONE
- No code changes
