# Adversarial V2 Findings Report

**Date:** 2026-05-08
**Run Directory:** `run/e2e_reports/20260508_195139/`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4
**Column Selection:** enabled (threshold=30, budget_ratio=0.10)

## Executive Summary

| Metric | V1 Adversarial | V2 Adversarial | Delta |
|--------|---------------|----------------|-------|
| Total queries | 76 | 47 | -29 |
| No-crash rate | 100% | 100% | = |
| Correct data | 43.4% (33/76) | 70.3% (26/37 single-turn) | +26.9% |
| Column missing | 9.2% (7/76) | 16.2% (6/37 single-turn) | +7.0% |
| Empty results | 17.1% (13/76) | 0% (0/37) | -17.1% |

**Key improvement:** V2 eliminated empty result failures entirely and dramatically improved semantic mapping and struct inner field handling.

## V2 Single-Turn Results by Category

| Category | Total | Correct | Col Missing | Partial | Correct Rate |
|----------|-------|---------|-------------|---------|-------------|
| budget_ratio_edge | 6 | 6 | 0 | 0 | **100%** |
| semantic_mapping_gap | 7 | 7 | 0 | 0 | **100%** |
| struct_inner_field_blindness | 7 | 7 | 0 | 0 | **100%** |
| column_name_collision | 6 | 2 | 2 | 2 | **33.3%** |
| column_selection_handoff | 7 | 2 | 4 | 1 | **28.6%** |

## V2 Multi-Turn Results

| Conversation | Turns | Successful | Key Findings |
|-------------|-------|-----------|-------------|
| RT-001: Allowance escalation | 4 | 4 (no crash) | Turn 3: Etihad/Secondment marked "not available in table". Turn 4: Complete breakdown omits Etihad/Secondment/Technical Special |
| RT-002: Employee profile deep dive | 3 | 3 | All turns return correct data including Family Book Number |
| RT-003: Leave to competency pivot | 3 | 3 | Successfully pivots from leave to competency via UNNEST |
| RT-004: Career progression audit | 4 | 4 | Successfully cross-references assignment history with previous employer |

## Root Cause Analysis: Persistent Failures

### Failure Mode 1: Column Selection → Code Generation Handoff (4 failures)

**Affected queries:** CH-001 (Etihad Allowance), CH-002 (Secondment Allowance), CH-005 (Special Contract Basic Salary), CH-007 (Etihad/Secondment/Technical Special/Phone/Supplementary)

**Pattern:**
1. Column selector correctly identifies the needed column (e.g., `[Employee Master[Etihad Allowance]]`)
2. Code generation step IGNORES the selected columns
3. Falls back to `information_schema.columns` introspection
4. DuckDB `information_schema` only returns top-level struct columns, not inner fields
5. LLM concludes "column not available" because it can't find the exact name

**Why it happens:** The code generation prompt doesn't strongly enforce using ONLY the selected columns. When the LLM sees a column name like `[Employee Master[Etihad Allowance]]`, it doesn't recognize this as a valid SQL column name and instead tries to discover columns from the schema.

**Evidence from CH-001:**
> "the current table schema does not contain Etihad Allowance information - it only includes Employee Name and Email Address columns"

The column selector provided `[Employee Master[Etihad Allowance]]` but the code generator only saw `[Employee Master[Employee Name]]` and `[Employee Master[Email Address]]` from its `information_schema` query.

### Failure Mode 2: Column Name Collision (2 failures)

**Affected queries:** CC-001 (Start Date collision), CC-005 (Job Title collision)

**Pattern:**
1. Query asks for a field that exists in multiple structs (e.g., "Start Date" in Assignment History AND Leave Details)
2. Column selector may only pick one struct's version
3. Code generator can't find the "missing" struct's version
4. Returns "columns not available"

**Evidence from CC-001:**
> "The requested columns 'Employee Assignment History' and 'Employee Leave Details' are NOT available in the current database schema"

The LLM treated the struct names as column names rather than recognizing them as struct arrays that need UNNESTing.

### Failure Mode 3: Partial Data (1 case)

**Affected query:** CH-004 (Family Book Number) — returned Family Book Number (32143) but the query also asked for Number of Spouses and Number of Children which were returned as 0 (potentially correct, but the column selection only captured Family Book Number).

## Improvement Analysis: V1 → V2

### Major Improvements

1. **Semantic Mapping Gap (0% → 100%):** V1 had 7 failures where domain terms didn't map to column names. V2 fixed all 7. The LLM now correctly maps:
   - "senior" → `[Employee Master[Date of Joining]]`
   - "sick days" → `[Employee Master[Sick Leave Taken]]`
   - "due for promotion" → `[Employee Master[Last Promotion Date]]`
   - "gender diversity" → `[Employee Master[Gender]]`
   - "highest academic qualification" → `[Employee Qualification[Degree Name]]`

2. **Struct Inner Field Blindness (0% → 100%):** V1 had 7 failures where UNNEST inner fields weren't discoverable. V2 fixed all 7. The LLM now correctly uses:
   - `rec['Employee Leave Details[Leave Type]']`
   - `rec['Employee Competencies Rating[Competency Name]']`
   - `rec['Employee Objectives[Objective Title]']`
   - `rec['Employee Previous Employer[Company Name]']`
   - `rec['Employee Assignment History[Position Title]']`

3. **Budget Ratio Edge (100%):** Even with 21+ columns requested (BR-004), the LLM handles it correctly.

### Persistent Weaknesses

1. **Column Selection Handoff:** The 2-step process (select columns → generate code) has a handoff gap. The code generator doesn't reliably use the columns selected in step 1.

2. **Column Name Collision:** When similarly-named fields exist across structs, the LLM can't disambiguate and falls back to schema introspection which fails.

## Recommendations for V3 Bank

1. **Double down on Column Selection Handoff:** Create queries that specifically test whether the code generator uses the columns from step 1. Use allowance-type columns that are NOT discoverable via `information_schema`.

2. **Target Column Name Collision more aggressively:** Create queries with 3+ struct fields sharing the same name (e.g., "Start Date" in Assignment History, Leave Details, AND Previous Employer).

3. **Test the budget boundary:** Create queries that request exactly 30 columns (the threshold) and 31 columns (just over the threshold) to test the auto-trigger behavior.

4. **Test conversation memory poisoning:** Create multi-turn conversations where earlier turns establish a "column not available" belief that poisons later turns.
