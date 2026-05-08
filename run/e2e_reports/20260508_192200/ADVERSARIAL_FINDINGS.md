# Adversarial E2E Findings Report
## Column Selection Break-Attempt Analysis

**Date:** 2026-05-08  
**Run ID:** 20260508_192200  
**Configuration:**
- Bank: adversarial (76 queries)
- Column Selection: **ENABLED** (threshold=30, budget_ratio=0.10)
- LLM: Qwen3.5-35B-A3B-GPTQ-Int4
- Dataset: 16 employees, 104 columns, 9+ structs

---

## Executive Summary

| Metric | Count | Rate |
|--------|-------|------|
| Total Queries | 76 | — |
| No-Crash Success | 76 | 100% |
| **Correct Data Returned** | **33** | **43.4%** |
| **Column Selection Failure** | **7** | **9.2%** |
| **Empty/Zero Results** | **13** | **17.1%** |
| **Error Responses** | **1** | **1.3%** |
| Partial/Unclear | 7 | 9.2% |
| Multi-turn Col Missing | 5/21 turns | 23.8% |

**Key Finding:** Column selection with threshold=30 causes the LLM to receive a drastically reduced schema (often only 2-5 columns instead of 64). The LLM then falls back to `information_schema` introspection, which returns the **DuckDB view columns** (not the struct fields), leading to "column not found" errors. This is a **systemic handoff failure** between the column selection step and the code generation step.

---

## Failure Mode #1: Column Selection → Code Generation Handoff Failure

**Affected Queries:** CO-001, CO-005, AR-001, AR-003, AR-004, CS-002, MU-001

**Mechanism:**
1. Column selection step **correctly identifies** the needed columns (e.g., `[Employee Master[Etihad Allowance]]`)
2. The selected columns are passed to the code generation prompt
3. The code generation LLM **ignores** the selected columns in the prompt
4. Instead, it queries `information_schema.columns` to discover available columns
5. DuckDB returns only the **view-level columns** (Employee Name, Email Address, etc.)
6. The LLM concludes the requested columns "don't exist"

**Evidence from CO-001:**
```
Column Selection Response (Step 1):
  "selected": ["[Employee Master[Employee Name]]", "[Employee Master[Etihad Allowance]]", "[Employee Master[Secondment Allowance]]"]
  ✅ Correct selection!

Code Generation Response (Step 2):
  "No allowance columns found in the dataset. The available columns are only Employee Name and Email Address."
  ❌ Falls back to schema introspection → wrong answer
```

**Impact:** This is the **most critical failure mode**. The column selection works correctly, but the generated code can't use the selected columns because it queries the schema instead of using the column names from the prompt.

---

## Failure Mode #2: Over-Aggressive Column Filtering

**Affected Queries:** AMT-002 Turn 1, AMT-002 Turn 2, AMT-003 Turn 1, AMT-004 Turn 1

**Mechanism:**
1. For queries about "ADEO experience" or "leave days", the column selection step selects only `[Employee Name]` and `[Email Address]`
2. The code generation step then correctly reports that the requested data "is not available"
3. The LLM had no way to know about `[Employee Master[Date of Joining]]` or `[Employee Leave Details[...]]` because they were filtered out

**Evidence from AMT-002 Turn 1:**
```
Query: "Who are the most senior employees by ADEO experience?"
Column Selection: ["[Employee Master[Employee Name]]", "[Employee Master[Email Address]]"]
Response: "ADEO experience data is not available in this dataset."
```

**Impact:** The column selection LLM doesn't understand that "ADEO experience" maps to "Date of Joining" → needs semantic understanding of the domain.

---

## Failure Mode #3: Struct Column Visibility in DuckDB

**Affected Queries:** CS-001, ES-002, ES-003, ID-001, ID-003, ID-005, NE-002, NE-006, TC-001, TC-002, TC-004

**Mechanism:**
1. Column selection provides struct columns (e.g., `[Employee Leave Details[Leave Type][...]]`)
2. The generated SQL uses `SELECT * FROM enterprise_data LIMIT 1` to discover columns
3. DuckDB returns only the top-level struct column, not the inner fields
4. The LLM can't UNNEST properly because it can't see the inner field names

**Evidence from ES-001:**
```
Query: "Create a comprehensive employee dashboard showing: name, department, sector, job title, grade, basic salary, total entitlement, last promotion date, ADEO experience, leave days taken, competency ratings, objectives status"
Column Selection: 11 columns (all flat Employee Master columns)
Missing: Leave details, competency ratings, objectives (all struct columns)
Response: "Unfortunately, I was not able to get your answer. Please try again."
```

---

## Category-by-Category Breakdown

| Category | Total | Correct | Col Missing | Empty | Error | Success Rate |
|----------|-------|---------|-------------|-------|-------|-------------|
| column_omission | 7 | 2 | 2 | 2 | 0 | 28.6% |
| cross_struct_deep | 6 | 4 | 1 | 1 | 0 | 66.7% |
| ambiguous_ref | 6 | 3 | 3 | 0 | 0 | 50.0% |
| implicit_dep | 6 | 3 | 0 | 3 | 0 | 50.0% |
| multi_struct_unnest | 6 | 5 | 1 | 0 | 0 | 83.3% |
| negation_edge | 6 | 4 | 0 | 2 | 0 | 66.7% |
| compound_aggregation | 6 | 6 | 0 | 0 | 0 | **100%** |
| temporal_cross | 6 | 3 | 0 | 3 | 0 | 50.0% |
| extreme_single | 6 | 3 | 0 | 2 | 1 | 50.0% |

**Most Vulnerable Categories:**
1. **column_omission** (28.6%) — directly targets the column selection weakness
2. **ambiguous_ref** (50.0%) — similar column names confuse the selector
3. **implicit_dep** (50.0%) — hidden dependencies not captured by selector
4. **temporal_cross** (50.0%) — time-based queries need columns the selector omits

**Most Resilient Category:**
- **compound_aggregation** (100%) — the selector correctly identifies aggregation columns

---

## Multi-Turn Conversation Results

| Conversation | Turns | Col Missing | OK | Notes |
|-------------|-------|-------------|-----|-------|
| AMT-001: Allowance deep dive | 3 | 1 | 2 | Turn 3 fails: Etihad/Secondment Allowance filtered out |
| AMT-002: Career timeline | 4 | 2 | 2 | Turns 1-2 fail: Date of Joining/Previous Employer filtered |
| AMT-003: Leave entitlement trap | 3 | 0 | 3 | All turns succeed (leave columns selected correctly) |
| AMT-004: Competency-qualification | 3 | 2 | 1 | Turns 1,3 fail: Competency columns filtered out |
| AMT-005: Struct absence discovery | 4 | 0 | 4 | All turns succeed (well-structured progressive queries) |
| AMT-006: Salary component audit | 4 | 0 | 4 | Turn 3: "no Special Contract Basic Salary" (correct, it doesn't exist) |

**Multi-turn Insight:** Conversations that start with simple queries and progressively add complexity (AMT-005, AMT-006) work better because the column selector has more context from previous turns. Conversations that start with obscure columns (AMT-001, AMT-002) fail immediately.

---

## Root Cause Analysis

### Primary Root Cause: Column Selection → Code Generation Disconnect

The column selection step outputs a JSON list of selected columns, but the code generation prompt doesn't strongly enforce using ONLY those columns. The LLM:

1. Sees the selected columns in the prompt header
2. Ignores them and queries `information_schema.columns` instead
3. Gets back a different set of columns (DuckDB view columns vs struct fields)
4. Concludes the requested columns don't exist

### Secondary Root Cause: Semantic Gap in Column Selection

The column selection LLM doesn't understand domain-specific mappings:
- "ADEO experience" → `[Employee Master[Date of Joining]]`
- "leave days taken" → `[Employee Leave Details[Leave Type][Leave Duration (Days)]...]`
- "competency ratings" → `[Employee Competencies Rating[...]]`

### Tertiary Root Cause: Struct Field Visibility

When column selection provides a struct column name (e.g., `[Employee Leave Details[Leave Type][...]...]`), the code generation step can't discover the inner fields through `information_schema` introspection.

---

## Recommendations

1. **Strengthen the code generation prompt** to explicitly state: "Use ONLY the columns listed below. Do NOT query information_schema."
2. **Add column name passthrough** — the selected columns should be injected directly into the SQL template, not just mentioned in the prompt
3. **Improve semantic mapping** — add synonyms/domain terms to the column descriptions in the semantic model
4. **Fallback mechanism** — if column selection filters out columns that the query explicitly mentions, fall back to the full schema
5. **Two-phase validation** — after column selection, validate that the selected columns can actually answer the query before proceeding

---

## Comparison: Standard vs Adversarial (with Column Selection)

| Metric | Standard (no col sel) | Adversarial (col sel) | Delta |
|--------|----------------------|----------------------|-------|
| Total Queries | 58 | 76 | +18 |
| No-Crash Success | 58/58 (100%) | 76/76 (100%) | 0% |
| Correct Data | ~58/58 (100%) | 33/76 (43.4%) | **-56.6%** |
| Col Selection Failures | 0 | 7 | +7 |
| Empty Results | 0 | 13 | +13 |

**Column selection reduces effective accuracy by 56.6 percentage points on adversarial queries.**
