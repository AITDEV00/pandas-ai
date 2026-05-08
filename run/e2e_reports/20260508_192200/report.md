# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 19:46:46
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_192200`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `33da0e4c-ad5e-4af8-aaf6-49df843289d0`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 76 |
| Successful | 76 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 55 |
| Multi-turn queries | 21 |
| Avg LLM calls per query | 2.7 |
| Max LLM calls per query | 5 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 41 | 53.9% |
| no_code_delimiter | 35 | 46.1% |

**Key finding:** The `marker` format (`---\nCode:`) in the LLM output would trigger `NoCodeFoundError` 
without the fallback extractor. The `fence` format (triple backticks) is the expected format.

## 3. Root Cause: Assistant Message Format in Conversation History

**Multi-turn conversations where `---\nCode:` marker appeared in assistant messages:** 0/6

The `_store_assistant_message()` method in `pandasai/agent/base.py` stores responses as:
```
f"{response_text}\n\n---\nCode:\n{working_code}"
```

This format is sent back to the LLM on follow-up turns, potentially teaching it to mimic 
the `---\nCode:` format instead of using code fences.

## 4. Results by Category

| Category | Total | Success | Fail | Success Rate |
|----------|-------|---------|------|--------------|
| ambiguous_ref | 6 | 6 | 0 | 100% |
| column_omission | 7 | 7 | 0 | 100% |
| compound_aggregation | 6 | 6 | 0 | 100% |
| cross_struct_deep | 6 | 6 | 0 | 100% |
| extreme_single | 6 | 6 | 0 | 100% |
| implicit_dep | 6 | 6 | 0 | 100% |
| multi_struct_unnest | 6 | 6 | 0 | 100% |
| negation_edge | 6 | 6 | 0 | 100% |
| temporal_cross | 6 | 6 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| extreme | 34 | 34 | 0 | 100% |
| hard | 18 | 18 | 0 | 100% |
| medium | 3 | 3 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| CO-001 | What is the Etihad Allowance for each em... | column_omission | hard | ✅ | fence | 2 |
| CO-002 | Which employees receive a Technical Spec... | column_omission | hard | ✅ | fence | 2 |
| CO-003 | List employees who have a Family Book Nu... | column_omission | hard | ✅ | no_code_delimiter | 2 |
| CO-004 | What is the Supplementary Allowance as a... | column_omission | hard | ✅ | no_code_delimiter | 2 |
| CO-005 | Which employees have a Special Contract ... | column_omission | hard | ✅ | no_code_delimiter | 3 |
| CO-006 | What is the total Cost of Living Allowan... | column_omission | medium | ✅ | fence | 2 |
| CO-007 | Show me the Child Allowance for employee... | column_omission | hard | ✅ | fence | 2 |
| CS-001 | For each employee with a Master's degree... | cross_struct_deep | extreme | ✅ | no_code_delimiter | 3 |
| CS-002 | Which employees have both CV work experi... | cross_struct_deep | extreme | ✅ | no_code_delimiter | 2 |
| CS-003 | For employees who have been promoted, sh... | cross_struct_deep | extreme | ✅ | no_code_delimiter | 2 |
| CS-004 | List employees who have previous employe... | cross_struct_deep | extreme | ✅ | no_code_delimiter | 3 |
| CS-005 | For each employee, show: their current j... | cross_struct_deep | extreme | ✅ | fence | 4 |
| CS-006 | Compare the educational institute from E... | cross_struct_deep | extreme | ✅ | fence | 4 |
| AR-001 | What is the difference between an employ... | ambiguous_ref | hard | ✅ | no_code_delimiter | 4 |
| AR-002 | Compare the Position Title from Employee... | ambiguous_ref | hard | ✅ | fence | 3 |
| AR-003 | What is the difference between the Degre... | ambiguous_ref | hard | ✅ | no_code_delimiter | 2 |
| AR-004 | Show me the Job Title and the CV Job Tit... | ambiguous_ref | hard | ✅ | fence | 2 |
| AR-005 | Compare the Educational Institute from E... | ambiguous_ref | extreme | ✅ | no_code_delimiter | 3 |
| AR-006 | What is the relationship between an empl... | ambiguous_ref | medium | ✅ | fence | 2 |
| ID-001 | Which employees have used more than 80% ... | implicit_dep | hard | ✅ | fence | 2 |
| ID-002 | Calculate the leave utilization rate for... | implicit_dep | extreme | ✅ | no_code_delimiter | 3 |
| ID-003 | Which employees have a Time Since Last P... | implicit_dep | hard | ✅ | fence | 2 |
| ID-004 | For each employee, calculate the total c... | implicit_dep | extreme | ✅ | fence | 2 |
| ID-005 | Which employees have a Graduation Date t... | implicit_dep | hard | ✅ | fence | 2 |
| ID-006 | Find employees whose Sick Leave Taken ex... | implicit_dep | hard | ✅ | fence | 2 |
| MU-001 | For each leave type, show the employee n... | multi_struct_unnest | extreme | ✅ | no_code_delimiter | 4 |
| MU-002 | List employees who have objectives with ... | multi_struct_unnest | extreme | ✅ | fence | 2 |
| MU-003 | Show each employee's CV work experience ... | multi_struct_unnest | extreme | ✅ | no_code_delimiter | 3 |
| MU-004 | For each employee, list their qualificat... | multi_struct_unnest | extreme | ✅ | fence | 3 |
| MU-005 | Show each employee's assignment history ... | multi_struct_unnest | extreme | ✅ | fence | 4 |
| MU-006 | For Ayesha Al Qubaisi, list all her leav... | multi_struct_unnest | extreme | ✅ | fence | 2 |
| NE-001 | Which employees have NO leave records at... | negation_edge | hard | ✅ | no_code_delimiter | 2 |
| NE-002 | Which employees have no competency ratin... | negation_edge | hard | ✅ | no_code_delimiter | 3 |
| NE-003 | Are there any employees with no objectiv... | negation_edge | hard | ✅ | fence | 3 |
| NE-004 | Which employees have no previous employe... | negation_edge | extreme | ✅ | no_code_delimiter | 2 |
| NE-005 | Find employees who have never been promo... | negation_edge | medium | ✅ | fence | 2 |
| NE-006 | Which employees have no qualifications l... | negation_edge | extreme | ✅ | no_code_delimiter | 3 |
| CA-001 | For each department, calculate: the aver... | compound_aggregation | extreme | ✅ | no_code_delimiter | 2 |
| CA-002 | Calculate a 'retention risk score' for e... | compound_aggregation | extreme | ✅ | no_code_delimiter | 5 |
| CA-003 | For each sector, show: the number of emp... | compound_aggregation | extreme | ✅ | no_code_delimiter | 5 |
| CA-004 | Which department has the highest ratio o... | compound_aggregation | extreme | ✅ | fence | 2 |
| CA-005 | For each employee grade, calculate the a... | compound_aggregation | extreme | ✅ | no_code_delimiter | 3 |
| CA-006 | Create a 'performance index' for each em... | compound_aggregation | extreme | ✅ | fence | 3 |
| TC-001 | Which employees took leave within 30 day... | temporal_cross | extreme | ✅ | fence | 4 |
| TC-002 | Are there any employees whose assignment... | temporal_cross | extreme | ✅ | fence | 2 |
| TC-003 | For employees with previous employer rec... | temporal_cross | extreme | ✅ | no_code_delimiter | 5 |
| TC-004 | Which employees have CV education end da... | temporal_cross | extreme | ✅ | no_code_delimiter | 2 |
| TC-005 | Show the complete career timeline for Ei... | temporal_cross | extreme | ✅ | fence | 2 |
| TC-006 | For each employee, calculate the total t... | temporal_cross | extreme | ✅ | fence | 5 |
| ES-001 | Create a comprehensive employee dashboar... | extreme_single | extreme | ✅ | fence | 5 |
| ES-002 | For each employee, compute a 'total comp... | extreme_single | extreme | ✅ | fence | 2 |
| ES-003 | Identify employees who have: (1) a Maste... | extreme_single | extreme | ✅ | fence | 2 |
| ES-004 | Show a cross-tabulation of Gender × Degr... | extreme_single | hard | ✅ | fence | 2 |
| ES-005 | For each sector, rank employees by their... | extreme_single | extreme | ✅ | no_code_delimiter | 3 |
| ES-006 | What is the correlation between the numb... | extreme_single | extreme | ✅ | fence | 3 |

## 7. Multi-Turn Conversation Details

### AMT-001: Allowance deep dive

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the total entitlement amount for... | ✅ | fence | 0 | N/A | 2 |
| 2 | Now break down that total into each indi... | ✅ | fence | 0 | fence | 2 |
| 3 | Which employees have a non-zero Etihad A... | ✅ | fence | 2 | fence | 3 |

### AMT-002: Career timeline reconstruction

**Turns:** 4 | **Successful:** 4 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Who are the most senior employees by ADE... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | For those senior employees, what previou... | ✅ | no_code_delimiter | 0 | fence | 2 |
| 3 | What about their assignment history at A... | ✅ | no_code_delimiter | 2 | fence | 3 |
| 4 | Do any of their previous employer dates ... | ✅ | fence | 4 | fence | 3 |

### AMT-003: Leave entitlement trap

**Turns:** 3 | **Successful:** 3 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | How many leave days has each employee ta... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | What is their leave entitlement for each... | ✅ | no_code_delimiter | 0 | fence | 2 |
| 3 | Calculate the utilization rate: approved... | ✅ | fence | 2 | fence | 2 |

### AMT-004: Competency-qualification correlation

**Turns:** 3 | **Successful:** 3 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What are the average competency ratings ... | ✅ | no_code_delimiter | 0 | N/A | 4 |
| 2 | What is the highest degree held by emplo... | ✅ | fence | 0 | fence | 2 |
| 3 | Is there a correlation between education... | ✅ | no_code_delimiter | 2 | fence | 3 |

### AMT-005: Struct absence discovery

**Turns:** 4 | **Successful:** 4 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | List all employees and their current job... | ✅ | fence | 0 | N/A | 2 |
| 2 | Which of these employees have no leave r... | ✅ | fence | 0 | fence | 2 |
| 3 | And which ones have no competency rating... | ✅ | no_code_delimiter | 2 | fence | 2 |
| 4 | Are there any employees with neither lea... | ✅ | no_code_delimiter | 4 | fence | 4 |

### AMT-006: Salary component audit

**Turns:** 4 | **Successful:** 4 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the average total entitlement am... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | What are the individual components that ... | ✅ | fence | 0 | fence | 2 |
| 3 | For employees with a Special Contract Ba... | ✅ | fence | 2 | fence | 2 |
| 4 | Calculate a corrected total entitlement ... | ✅ | no_code_delimiter | 4 | fence | 2 |

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
