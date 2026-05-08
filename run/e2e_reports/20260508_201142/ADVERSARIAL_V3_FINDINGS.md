# Adversarial V3 Findings Report

**Run Date**: 2026-05-08 20:11:42  
**Bank**: `query_bank_adversarial_v3.py`  
**Total Queries**: 53 (39 single-turn + 14 multi-turn across 4 conversations)  
**Successful Execution**: 50/53 (94.3%)  
**Hard Failures**: 3/53 (5.7%) — NoCodeFoundError  

---

## Summary Statistics

| Metric | Count | Percentage |
|--------|-------|-----------|
| Correct Data | 29 | 54.7% |
| Column Missing | 5 | 9.4% |
| Hard Failure (NoCodeFoundError) | 3 | 5.7% |
| Error Response | 1 | 1.9% |
| Partial Data | 4 | 7.5% |
| Multi-turn turns (total) | 14 | — |
| Multi-turn COL_MISSING turns | 4 | 28.6% |

---

## Category Breakdown (Single-Turn)

| Category | Total | Correct | Col Missing | Hard Fail | Error | Accuracy |
|----------|-------|---------|-------------|-----------|-------|----------|
| ALLOWANCE_MATRIX | 11 | 11 | 0 | 0 | 0 | **100%** |
| NEGATION_TRAP | 6 | 6 | 0 | 0 | 0 | **100%** |
| MULTI_STRUCT_JOIN | 7 | 5 | 0 | 0 | 1 | **71.4%** |
| HANDOFF_SABOTAGE | 8 | 3 | 2 | 2 | 0 | **37.5%** |
| TRIPLE_NAME_COLLISION | 7 | 3 | 3 | 1 | 0 | **42.9%** |

---

## Key Findings

### Finding 1: Etihad & Secondment Allowance — Persistent Column Selection Failure

**Queries**: HS-001, HS-002  
**Status**: COL_MISSING  

The column selector correctly identifies `Employee Master[Etihad Allowance]` and `Employee Master[Secondment Allowance]` for inclusion in the prompt, but the code generation step IGNORES the selected columns and falls back to `information_schema` introspection. DuckDB's `information_schema` only returns top-level columns visible in the current query context, not all 64 columns from the semantic model. The code generator then concludes "column not available."

**HS-001 Response**: *"The 'Etihad Allowance' column does not exist in the available schema. The system only contains employee name and email address columns."*

**HS-002 Response**: *"The column 'Employee Master[Secondment Allowance]' does not exist in the available schema. The system only contains the following columns: [Employee Master[Employee Name]] and [Employee Master[Email Address]]."*

**Root Cause**: Column selection handoff failure — selected columns are not reliably passed to the code generation step. The LLM uses `information_schema` as ground truth instead of the column selection results.

### Finding 2: Special Contract Basic Salary — BinderException → NoCodeFoundError

**Query**: HS-004  
**Status**: HARD FAILURE  

The LLM generates code referencing `Special Contract Basic Salary` but a BinderException occurs during execution (likely a DuckDB column resolution error). After the BinderException, the retry mechanism also fails, leading to NoCodeFoundError.

### Finding 3: Phone/Supplementary Allowance Comparison — TypeError → NoCodeFoundError

**Query**: HS-005  
**Status**: HARD FAILURE  

A TypeError occurs during code execution (likely from comparing incompatible data types or accessing struct fields incorrectly). The retry mechanism fails to recover.

### Finding 4: Triple Start Date Collision — Inconsistent Behavior

**Query**: TC-001  
**Status**: HARD FAILURE (BinderException → NoCodeFoundError)  

Three structs share a `Start Date` field: Employee Assignment History, Employee Previous Employer, and CV Employee Work Experience. The LLM generates code with ambiguous column references, causing a BinderException. However, TC-002 (triple End Date) succeeds, showing inconsistent handling.

### Finding 5: Name Collision Queries Return Data But With "Column Does Not Exist"

**Queries**: TC-003, TC-004, TC-006  
**Status**: COL_MISSING (partial data returned)  

These queries actually return tabular data but include "Column does not exist" in some cells. For example, TC-004 shows `Assignment History Grade: Column does not exist` — the LLM found the comparison partially but couldn't resolve the struct inner field.

### Finding 6: Negation Traps — 100% Success Rate

**Queries**: NT-001 through NT-006  
**Status**: All SUCCESS  

Negation queries (asking for employees WITHOUT a certain allowance, or with zero values) succeed 100% of the time. Notably, NT-001 (Etihad Allowance == 0) and NT-002 (Secondment Allowance == 0) SUCCEED where HS-001 and HS-002 fail. The LLM discovers a `SELECT * LIMIT 1` workaround that exposes all columns, including Etihad and Secondment.

### Finding 7: Allowance Matrix — 100% Success Rate

**Queries**: AM-001 through AM-011  
**Status**: All SUCCESS  

Systematic testing of each individual allowance column succeeds 100%. This confirms the column data IS accessible — the failure is specifically in the column selection handoff, not in data availability.

### Finding 8: Multi-Turn Column Selection Degradation

**Conversations**: CP-001 through CP-004  

| Conversation | Total Turns | COL_MISSING Turns | Degradation |
|-------------|-------------|-------------------|-------------|
| CP-001 (Allowance cascade) | 4 | 1 (Turn 2: Etihad) | 25% |
| CP-002 (Struct discovery) | 3 | 2 (Turns 1-2: competency+leave) | 67% |
| CP-003 (Grade comparison) | 3 | 2 (Turns 1-2: Assignment History Grade) | 67% |
| CP-004 (Career timeline) | 4 | 2 (Turns 0, 3: Assignment/Etihad) | 50% |

**Key observations**:
- CP-001 Turn 2: Etihad Allowance denied despite user explicitly stating "I'm sure it's there"
- CP-002 Turns 1-2: "No competency or leave data found" — column selection fails for struct arrays
- CP-003 Turn 2: "Assignment History Grade: Not Available in this table" — struct inner field blindness
- CP-004 Turn 0: Assignment History not available on first try (but succeeds on Turn 1)

### Finding 9: Technical Special Allowance — Success With Workaround

**Query**: HS-003  
**Status**: PARTIAL (correct data returned)  

The LLM found Technical Special Allowance and returned correct data (all values are 0.0). This suggests some allowance columns are discoverable depending on how the LLM phrases the query.

---

## Failure Mode Taxonomy

### FM-1: Column Selection Handoff Failure (CHRONIC)
- **Manifestation**: Column selector picks correct columns → code generator ignores them → uses `information_schema` → concludes "not available"
- **Affected columns**: Etihad Allowance, Secondment Allowance, Special Contract Basic Salary
- **Workaround**: `SELECT * LIMIT 1` introspection (discovered by LLM in negation queries)
- **Frequency**: 5/53 queries (9.4%)

### FM-2: Struct Inner Field Blindness (MODERATE)
- **Manifestation**: LLM can access top-level struct columns but cannot reference inner fields like `Grade`, `Start Date`, `Position Title` inside struct arrays
- **Affected queries**: TC-001, TC-003, TC-004, TC-006, CP-003
- **Frequency**: 5/53 queries (9.4%)

### FM-3: Multi-Turn Degradation (SIGNIFICANT)
- **Manifestation**: Column selection degrades over conversation turns; struct columns become inaccessible
- **Affected conversations**: CP-002 (67%), CP-003 (67%), CP-004 (50%)
- **Frequency**: 4/14 multi-turn turns (28.6%)

### FM-4: BinderException Recovery Failure (LOW)
- **Manifestation**: DuckDB BinderException during code execution → retry also fails → NoCodeFoundError
- **Affected queries**: HS-004, TC-001
- **Frequency**: 2/53 queries (3.8%)

---

## Comparison with V2 Results

| Category | V2 Accuracy | V3 Accuracy | Delta |
|----------|------------|------------|-------|
| Column Selection Handoff | 28.6% (2/7) | 37.5% (3/8) | +8.9% |
| Name Collision | 33.3% (2/6) | 42.9% (3/7) | +9.6% |
| Allowance queries | N/A | 100% (11/11) | NEW |
| Negation queries | N/A | 100% (6/6) | NEW |
| Multi-struct join | N/A | 71.4% (5/7) | NEW |
| Overall single-turn | 70.3% | 67.4% | -2.9% |

**Note**: V3 overall accuracy is slightly lower because the bank was designed to be harder (targeting known failure modes with more precise queries). The new categories (allowance_matrix, negation_trap) show 100% accuracy, confirming the LLM CAN access these columns when the right code path is used.

---

## Recommendations for V4 Bank

1. **MULTI-TURN ESCALATION**: Create longer conversations (6-8 turns) that progressively request harder-to-find columns. The degradation pattern suggests column selection gets worse with more history.

2. **SELECT_STAR_CIRCUMVENT**: Design queries where `SELECT * LIMIT 1` won't help — e.g., struct inner fields that require explicit field access, or aggregate queries that need specific column names.

3. **CONVERSATION CONTEXT POISONING**: Inject misleading context in early turns that makes later turns fail. E.g., Turn 1 asks about a non-existent column → LLM narrows schema → Turn 2 asks about a real column that now appears "missing."

4. **STRUCT DEEP ACCESS**: Queries requiring 3+ levels of struct nesting (struct containing struct containing field).

5. **AMBIGUOUS FIELD RESOLUTION**: Queries where the same field name exists in 4+ structs and the LLM must pick the correct one based on semantic context alone.
