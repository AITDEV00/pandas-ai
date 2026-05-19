# Root Cause Analysis: Small LLM Generates Wrong SQL for Struct Columns

**Date**: 2025-01-XX  
**Query that triggered the bug**: "what is the percentage by different leave types did Ayesha take?"  
**Error**: DuckDB `BinderException` — Could not find key `"employee leave details[leave type]..."` in struct  
**Status**: ✅ **FIXED AND VERIFIED** (2026-05-19)

---

## Executive Summary

There is a 3-part inconsistency chain between what DuckDB expects and what the LLM is told. The root cause is that `_extract_struct_vocabulary()` produces a corrupted `samples` dict for struct columns, where the first struct field gets a **WRONG** `duckdb_key` (the full squashed column name instead of the flat key).

Additionally, when the column selector is active (which it IS for this dataset with 63 columns ≥ 30 threshold), the samples dict filtering produces an **EMPTY** result, meaning the LLM gets NO struct field information at all.

---

## Part 1: The Data Flow (What DuckDB Expects)

1. **Excel file → pandas DataFrame**
   - Column name: `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]`
   - This is the "squashed" column name — all inner fields merged together

2. **`parse_json_array_columns(df)`** — in-place transformation
   - Each cell in the squashed column becomes a list of dicts
   - The dict keys are FLAT bracket-style:
     - `Employee Leave Details[Leave Type]`
     - `Employee Leave Details[Leave Duration (Days)]`
     - `Employee Leave Details[Approval Status]`
     - `Employee Leave Details[Leave Start Date]`
     - `Employee Leave Details[Leave End Date]`

3. **DuckDB `connection.register(table_name, df)`**
   - DuckDB creates a STRUCT type with the dict keys as field names
   - The struct field names are the FLAT keys from step 2
   - DuckDB type: `STRUCT("Employee Leave Details[Leave Type]" VARCHAR, ...)`
   - ✅ **CORRECT access**: `rec['Employee Leave Details[Leave Type]']`
   - ❌ **WRONG access**: `rec['Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]']`

> **VERIFIED**: The correct query with flat key access SUCCEEDS. The wrong query with squashed key access FAILS with `BinderException`.

---

## Part 2: The Schema Patching (What the Register Handler Does)

**File**: `server/features/register/handler.py`, lines 110–201

The user's semantic model provides INDIVIDUAL inner-field columns:
- `[Employee Leave Details[Leave Type]]`
- `[Employee Leave Details[Leave Duration (Days)]]`
- `[Employee Leave Details[Approval Status]]`
- `[Employee Leave Details[Leave Start Date]]`
- `[Employee Leave Details[Leave End Date]]`

The patching logic (step 2b) does:
1. For each DataFrame column that is `list[struct]`:
   - If no exact schema match → call `get_matching_schema_columns(col_name, schema)`
   - `col_name` = `[Employee Leave Details[Leave Type][Leave Duration (Days)]...]` (squashed)
2. `get_matching_schema_columns` finds ALL individual inner-field columns as matches
   - Strategy 2a (inner column match): `schema_col.name.endswith(f"[{col_name}]]")`
   - Strategy 2b (prefixed inner column match): `f"[{col_name}" in schema_col.name`
3. All matched individual columns are added to `inner_field_names_to_remove`
4. A new squashed column is created with `type="list[struct]"`
5. Individual columns are **REMOVED** from the schema

**RESULT**: The schema ends up with ONLY the squashed column:
```
[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]
type: list[struct]
description: "Leave Type: ... | Leave Duration (Days): ... | Approval Status: ... | Leave Start Date: ... | Leave End Date: ..."
```

---

## Part 3: The Corrupted Samples Dict (The Core Bug)

**File**: `pandasai/helpers/column_enrichment.py`, `_extract_struct_vocabulary()` (line 85)

After schema patching, when `_extract_struct_vocabulary` processes the struct column:

1. It flattens all struct dicts into a temp DataFrame:
   ```
   temp_df = pd.DataFrame(all_structs)
   → columns are the FLAT keys: "Employee Leave Details[Leave Type]", etc.
   ```

2. For each `inner_col` (flat key), it calls `get_matching_schema_columns(inner_col, schema)`
   - The schema now only has the SQUASHED column

3. For `"Employee Leave Details[Leave Type]"` (the FIRST flat key):
   - `get_matching_schema_columns` returns the SQUASHED parent column as a match
   - This is because Strategy 2b checks: `f"[{col_name}" in schema_col.name`
   - `"[Employee Leave Details[Leave Type]"` IS contained in the squashed name
   - **THIS IS A FALSE POSITIVE** — the flat key should NOT match the squashed parent
   - `schema_key = "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]"`
   - `duckdb_key = "Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]"`
   - ← **WRONG!** Should be `"Employee Leave Details[Leave Type]"`

4. For `"Employee Leave Details[Leave Duration (Days)]"` (and other flat keys):
   - `get_matching_schema_columns` returns NO match
   - Because `"[Employee Leave Details[Leave Duration (Days)]"` is NOT a prefix of the squashed name `"[Employee Leave Details[Leave Type][Leave Duration...]"`
   - Falls back to using the raw pandas column name
   - `duckdb_key = "Employee Leave Details[Leave Duration (Days)]"`
   - ← This happens to be **CORRECT**

**RESULT**: The samples dict has MIXED naming conventions:

| Key | duckdb_key | Correct? |
|-----|-----------|----------|
| `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]` | `Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]` | ❌ WRONG |
| `Employee Leave Details[Leave Duration (Days)]` | `Employee Leave Details[Leave Duration (Days)]` | ✅ |
| `Employee Leave Details[Approval Status]` | `Employee Leave Details[Approval Status]` | ✅ |
| `Employee Leave Details[Leave Start Date]` | `Employee Leave Details[Leave Start Date]` | ✅ |
| *(MISSING)* | `Employee Leave Details[Leave End Date]` | ❌ Missing — consumed by first entry's false positive match |

---

## Part 4: What the LLM Sees (The search_strategy Template)

**File**: `pandasai/core/prompts/templates/shared/search_strategy.tmpl`

The template renders struct fields as:
```
rec['{{ display_name }}']
```
where `display_name = field.duckdb_key` (if available) or `field.short_name` or `field_name`

So the LLM sees:

```
STRUCT: "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]" — fields:
  rec['Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]'] (string, id_like)
  rec['Employee Leave Details[Leave Duration (Days)]'] (string, categorical)
    Values: 1, 10, 2, 3, 4, 5, 6, 7
  rec['Employee Leave Details[Approval Status]'] (string, categorical)
    Values: Approved, Denied
  rec['Employee Leave Details[Leave Start Date]'] (string, id_like)
```

**PROBLEMS**:
1. The first field's `duckdb_key` is the FULL SQUASHED NAME — WRONG
2. "Leave End Date" field is MISSING from the output
3. The first field has `semantic_type=id_like` and `type=string` with date range samples — this is because the first entry consumed ALL the data and classified it as the LAST field processed (`short_name="Leave End Date"`)
4. There are TWO different naming conventions in the same output: squashed name for the first field, flat keys for the remaining fields

---

## Part 5: The Column Selector's Impact (Additional Corruption)

**File**: `pandasai/core/column_selector.py`

The DataFrame has 63 columns, which exceeds the `column_selection_threshold` of 30. So the 2-step column selection pipeline IS ACTIVE.

When the column selector runs:

1. **Step 1**: LLM selects relevant columns (e.g., `"[Employee Leave Details[Leave Type]]"`, `"[Employee Master[Employee Name]]"`)

2. **`match_names_to_schema`** maps these to:
   ```python
   matched = {
     'Employee Leave Details': ['[Employee Leave Details[Leave Type]]'],
     'Employee Master': ['[Employee Master[Employee Name]]']
   }
   ```

3. **`build_trimmed_dataframe`** filters the samples dict:
   ```python
   inner_fields = ['[Employee Leave Details[Leave Type]]']
   filtered_samples = {k: v for k, v in samples.items() if k in inner_fields}
   ```
   
   BUT the samples dict keys are:
   - `"[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]"` ← squashed
   - `"Employee Leave Details[Leave Duration (Days)]"` ← flat, no brackets
   - `"Employee Leave Details[Approval Status]"` ← flat, no brackets
   - `"Employee Leave Details[Leave Start Date]"` ← flat, no brackets

   **NONE** of these match `"[Employee Leave Details[Leave Type]]"` (the canonical schema column name from `inner_fields`)!

   **RESULT**: `filtered_samples = {}` → `samples` becomes `None`

4. The LLM gets a struct column with NO field information:
   - Column: `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]`
   - Type: `list[struct]`
   - Samples: `None`

   The LLM has NO IDEA what struct fields exist or how to access them. It must GUESS, and small LLMs guess wrong.

---

## Part 6: The Lowercase Mystery

The `BinderException` error message shows:
```
"Could not find key "employee leave details[leave type][leave duration (days)][approval status][leave start date][leave end date]" in struct"
```

This is ALL LOWERCASE. But the LLM generated mixed-case SQL.

**EXPLANATION**: DuckDB normalizes struct field key lookups to lowercase in its error messages. When you do `rec['SomeKey']`, DuckDB internally lowercases the key for comparison. The actual struct field names are stored as-is (mixed case), but the lookup key is lowercased. So:

- `rec['Employee Leave Details[Leave Type]']` → lookup key: `"employee leave details[leave type]"` → MATCH ✅
- `rec['Employee Leave Details[Leave Type][Leave Duration (Days)]...']` → lookup key: `"employee leave details[leave type][leave duration (days)]..."` → No struct field matches → `BinderException` ❌

So the lowercase in the error message is just DuckDB's internal normalization, not something that happens in the code.

---

## Summary of All Inconsistencies

### Inconsistency 1: Schema column removal destroys inner-field resolution
- **WHERE**: `server/features/register/handler.py`, lines 130–201
- **WHAT**: Individual inner-field columns are removed from the schema, leaving only the squashed column. The LLM prompt shows the squashed column name, not the individual inner fields.
- **IMPACT**: The LLM sees a confusing column name with all fields concatenated, and no way to know the individual field names.

### Inconsistency 2: `_extract_struct_vocabulary` produces wrong `duckdb_key`
- **WHERE**: `pandasai/helpers/column_enrichment.py`, `_extract_struct_vocabulary()`
- **WHAT**: The first flat struct key (`"Employee Leave Details[Leave Type]"`) gets falsely matched to the squashed parent column by `get_matching_schema_columns`. This produces a WRONG `duckdb_key` (the full squashed name) instead of the correct flat key.
- **IMPACT**: The LLM is told to use `rec['Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]']` which is NOT a valid DuckDB struct field key.

### Inconsistency 3: `get_matching_schema_columns` has false positive match
- **WHERE**: `pandasai/helpers/semantic_matching.py`, `get_matching_schema_columns()`
- **WHAT**: Strategy 2b (prefixed inner column match) checks if `f"[{col_name}"` is contained in a schema column name. When `col_name` is a flat key like `"Employee Leave Details[Leave Type]"`, this matches the squashed parent column.
- **IMPACT**: This false positive match is the root cause of Inconsistency 2.

### Inconsistency 4: Column selector samples filtering produces empty result
- **WHERE**: `pandasai/core/column_selector.py`, `build_trimmed_dataframe()`
- **WHAT**: The samples dict keys use MIXED naming conventions. The column selector filters by canonical schema column names, but NONE of the samples keys match these canonical names.
- **IMPACT**: The filtered samples dict is EMPTY. The LLM gets NO struct field information and must guess.

---

## The Full Chain of Events

### 1. `/register/file` endpoint:
- a. Load Excel → `parse_json_array_columns` → DataFrame with squashed column names
- b. Apply semantic model with individual inner-field columns
- c. Patch schema: individual columns removed, squashed column remains
- d. Enrich: `_extract_struct_vocabulary` produces corrupted samples dict
- e. Store Agent with corrupted schema in `agent_store`

### 2. `/chat` endpoint (with column selection):
- a. Retrieve Agent from `agent_store`
- b. Column selection triggered (63 columns ≥ 30 threshold)
- c. Step 1: LLM selects columns (e.g., `"[Employee Leave Details[Leave Type]]"`)
- d. `match_names_to_schema` maps to parent with inner fields
- e. `build_trimmed_dataframe` filters samples → **EMPTY** (no keys match)
- f. LLM prompt has struct column with NO field information
- g. Small LLM guesses struct field access → generates wrong SQL
- h. DuckDB `BinderException`

### 3. Even WITHOUT column selection:
- a. LLM sees the corrupted samples dict with wrong `duckdb_key`
- b. The `search_strategy` template shows the wrong access pattern
- c. If the LLM uses this `duckdb_key` → `BinderException`
- d. If the LLM ignores it and uses the column name from the description → might work

---

## What the LLM Should See vs What It Actually Sees

### ✅ SHOULD SEE (correct):
```
STRUCT: "[Employee Leave Details[...]]" — fields:
  rec['Employee Leave Details[Leave Type]'] (string, categorical) Values: Annual, Sick, etc.
  rec['Employee Leave Details[Leave Duration (Days)]'] (string, categorical) Values: 1, 2, 3, etc.
  rec['Employee Leave Details[Approval Status]'] (string, categorical) Values: Approved, Denied
  rec['Employee Leave Details[Leave Start Date]'] (string, id_like)
  rec['Employee Leave Details[Leave End Date]'] (string, id_like)
```

### ❌ ACTUALLY SEES (without column selection):
```
STRUCT: "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]" — fields:
  rec['Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]'] (string, id_like)
  rec['Employee Leave Details[Leave Duration (Days)]'] (string, categorical) Values: 1, 10, 2, 3, 4, 5, 6, 7
  rec['Employee Leave Details[Approval Status]'] (string, categorical) Values: Approved, Denied
  rec['Employee Leave Details[Leave Start Date]'] (string, id_like)
```

### ❌ ACTUALLY SEES (with column selection — the actual path):
```
STRUCT: "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]" — fields:
  (NO FIELDS SHOWN — samples is None after filtering)
```

---

## Files Involved

1. `server/features/register/handler.py` (lines 110–201) — Schema patching: removes individual inner-field columns, adds squashed struct column
2. `pandasai/helpers/column_enrichment.py` (`_extract_struct_vocabulary`, line 85) — Produces corrupted samples dict with wrong `duckdb_key`
3. `pandasai/helpers/semantic_matching.py` (`get_matching_schema_columns`) — Strategy 2b causes false positive match
4. `pandasai/core/column_selector.py` (`build_trimmed_dataframe`) — Samples filtering produces empty result
5. `pandasai/core/prompts/templates/shared/search_strategy.tmpl` — Renders struct fields using `duckdb_key` from corrupted samples
6. `pandasai/core/prompts/templates/shared/duckdb_syntax.tmpl` — Tells the LLM to use `rec['field_name']` for struct access
7. `pandasai/agent/base.py` (`_execute_sql_query`) — Registers DataFrame with DuckDB using `connection.register()`

---

## Verified Test Results

1. **Correct query** (flat key access): ✅ SUCCEEDS
2. **Wrong query** (squashed key access — what the corrupted samples tell the LLM): ❌ FAILS with `BinderException`
3. **DuckDB struct field names** (verified): `Employee Leave Details[Leave Type]`, `Employee Leave Details[Leave Duration (Days)]`, etc.

---

## Addendum: LLM Bracket Confusion (Discovered 2026-05-19)

After the original fixes (Strategy A: column_enrichment false-positive filtering, Strategy B: column_selector bracket normalization) were applied, the SAME query **STILL** failed. This addendum documents two NEW root causes discovered during post-fix testing.

### New Root Cause A: LLM Misinterprets Brackets in `duckdb_key` as Array Indexing

**SYMPTOM**: The LLM generated SQL with double-escaped single quotes:
```sql
rec[''Employee Leave Details'[Leave Type]']
```
instead of the correct:
```sql
rec['Employee Leave Details[Leave Type]']
```

**EXPLANATION**: The `duckdb_key` format `"Parent[Field]"` is ambiguous for LLMs. When the LLM sees `rec['Employee Leave Details[Leave Type]']`, it interprets the brackets inside the string as array indexing syntax, not as part of the field name. It then "corrects" this by wrapping the parent in its own single quotes.

**FIX APPLIED**: `pandasai/core/prompts/templates/shared/search_strategy.tmpl`
Added a CRITICAL instruction after Rule 3:
> **CRITICAL: Struct field names may contain brackets like `rec['Parent[Field Name]']`. The ENTIRE string inside the single quotes is ONE field name — brackets are part of the name, NOT array indexing. Copy the field name EXACTLY as shown, including any brackets. Do NOT split it into `rec['Parent'][Field Name]` or add extra quotes.**

### New Root Cause B: LLM Returns Column Names with Stray Single Quotes

**SYMPTOM**: When column selection is active, the LLM returns column names with stray single quotes:
```json
"selected": ["'Employee Leave Details'[Leave Type]", ...]
```
instead of the correct:
```json
"selected": ["[Employee Leave Details[Leave Type]]", ...]
```

**EXPLANATION**: Same bracket confusion as Root Cause A, but in the column selection step.

**FIX APPLIED** (3 parts):
1. `pandasai/helpers/column_enrichment.py` — Changed samples dict keys to use bracket-style canonical names (e.g., `[Employee Leave Details[Leave Type]]`) instead of flat keys
2. `pandasai/core/prompts/templates/select_columns.tmpl` — Changed from displaying `duckdb_key` to `field_name` (bracket-style canonical name)
3. `pandasai/core/column_selector.py` — Added `duckdb_key`-style name matching and single-quote sanitization

---

## Verification: End-to-End Test Results (2026-05-19)

**Test query**: "what is the percentage by different leave types did Ayesha take?"  
**Data file**: `run/full data unflattened.xlsx` (63 columns with struct data)

### Before Fixes:
- LLM generated: `rec[''Employee Leave Details'[Leave Type]']` → `ParserException`
- Column selection: LLM returned `"'Employee Leave Details'[Leave Type]"` → no match → struct columns dropped
- Result: "No leave data available" or `ParserException`

### After Fixes:
- Struct samples keys: `[Employee Leave Details[Leave Type]]`, `[Employee Leave Details[Leave Duration (Days)]]`, etc.
- `duckdb_key`: `Employee Leave Details[Leave Type]` (flat key, correct for SQL)
- `select_columns.tmpl` shows: `"[Employee Leave Details[Leave Type]]"` (bracket-style)
- `search_strategy.tmpl` shows: `rec['Employee Leave Details[Leave Type]']` (flat key in SQL)
- Column selection correctly identifies: `[Employee Master[Employee Name]]`, `[Employee Leave Details[Leave Type]]`, `[Employee Leave Details[Leave Duration (Days)]]`
- LLM generates correct SQL: `rec['Employee Leave Details[Leave Type]']`
- Result: "Ayesha's leave breakdown (Total: 66 leaves): Remote Work: 42.42% (28 days), Wellbeing: 21.21% (14 days), Training Leave: 4.55% (3 days), Non-Mandatory Leave: 31.82% (21 days)"

**STATUS**: ✅ ALL FIXES VERIFIED WORKING

---

## Files Modified (Complete List)

1. **`pandasai/helpers/column_enrichment.py`**
   - Strategy A (prior session): Filter false-positive matches, use `inner_col` as `duckdb_key`
   - Bracket key fix (this session): Wrap `schema_key` in brackets when it's a flat key → samples dict keys now use bracket-style canonical names

2. **`pandasai/core/column_selector.py`**
   - Strategy B (prior session): Bracket normalization in `build_trimmed_dataframe`
   - DuckDB key matching (this session): Handle `"Parent[Field]"` format in `match_names_to_schema`
   - Quote sanitization (this session): Strip stray single quotes in `_validate_names`

3. **`pandasai/core/prompts/templates/shared/search_strategy.tmpl`**
   - CRITICAL instruction (this session): Brackets are part of field names, not array indexing

4. **`pandasai/core/prompts/templates/select_columns.tmpl`**
   - Display `field_name` instead of `duckdb_key` (this session)
