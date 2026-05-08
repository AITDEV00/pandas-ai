# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 20:27:10
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_201142`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `d2d9ea99-691c-45bd-bd58-24b74a230415`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 53 |
| Successful | 50 (94.3%) |
| Failed | 3 (5.7%) |
| Single-turn queries | 39 |
| Multi-turn queries | 14 |
| Avg LLM calls per query | 2.5 |
| Max LLM calls per query | 5 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 29 | 54.7% |
| no_code_delimiter | 24 | 45.3% |

**Key finding:** The `marker` format (`---\nCode:`) in the LLM output would trigger `NoCodeFoundError` 
without the fallback extractor. The `fence` format (triple backticks) is the expected format.

## 3. Root Cause: Assistant Message Format in Conversation History

**Multi-turn conversations where `---\nCode:` marker appeared in assistant messages:** 0/4

The `_store_assistant_message()` method in `pandasai/agent/base.py` stores responses as:
```
f"{response_text}\n\n---\nCode:\n{working_code}"
```

This format is sent back to the LLM on follow-up turns, potentially teaching it to mimic 
the `---\nCode:` format instead of using code fences.

## 4. Results by Category

| Category | Total | Success | Fail | Success Rate |
|----------|-------|---------|------|--------------|
| allowance_matrix | 11 | 11 | 0 | 100% |
| handoff_sabotage | 8 | 6 | 2 | 75% |
| multi_struct_join | 7 | 7 | 0 | 100% |
| negation_trap | 6 | 6 | 0 | 100% |
| triple_name_collision | 7 | 6 | 1 | 86% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| easy | 2 | 2 | 0 | 100% |
| extreme | 12 | 11 | 1 | 92% |
| hard | 18 | 16 | 2 | 89% |
| medium | 7 | 7 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| HS-001 | What is the exact Etihad Allowance amoun... | handoff_sabotage | extreme | ✅ | no_code_delimiter | 3 |
| HS-002 | Show the Secondment Allowance for each e... | handoff_sabotage | extreme | ✅ | no_code_delimiter | 3 |
| HS-003 | What is the Technical Special Allowance ... | handoff_sabotage | extreme | ✅ | fence | 2 |
| HS-004 | Show the Special Contract Basic Salary f... | handoff_sabotage | hard | ❌ | fence | 3 |
| HS-005 | Compare Phone Allowance and Supplementar... | handoff_sabotage | hard | ❌ | no_code_delimiter | 3 |
| HS-006 | What is the Total Entitlement Amount for... | handoff_sabotage | hard | ✅ | fence | 3 |
| HS-007 | Show me every single allowance column fo... | handoff_sabotage | extreme | ✅ | no_code_delimiter | 2 |
| HS-008 | What is the Time Since Last Promotion fo... | handoff_sabotage | hard | ✅ | fence | 2 |
| TC-001 | Show the Start Date from Employee Assign... | triple_name_collision | extreme | ❌ | fence | 3 |
| TC-002 | Compare the End Date from Employee Assig... | triple_name_collision | extreme | ✅ | fence | 3 |
| TC-003 | Show the Job Title from Employee Master ... | triple_name_collision | extreme | ✅ | fence | 3 |
| TC-004 | What is the Employee Grade from Employee... | triple_name_collision | hard | ✅ | fence | 2 |
| TC-005 | Show the Assignment Name from Employee A... | triple_name_collision | hard | ✅ | no_code_delimiter | 2 |
| TC-006 | List the CV Degree Name from CV Employee... | triple_name_collision | hard | ✅ | fence | 3 |
| TC-007 | Show the CV Company Name from CV Employe... | triple_name_collision | hard | ✅ | no_code_delimiter | 2 |
| AM-001 | What is the Basic Salary for all employe... | allowance_matrix | easy | ✅ | fence | 2 |
| AM-002 | What is the Housing Allowance for all em... | allowance_matrix | easy | ✅ | fence | 2 |
| AM-003 | What is the Cost of Living Allowance for... | allowance_matrix | medium | ✅ | no_code_delimiter | 3 |
| AM-004 | What is the Social Allowance for all emp... | allowance_matrix | medium | ✅ | fence | 2 |
| AM-005 | What is the Child Allowance for all empl... | allowance_matrix | medium | ✅ | no_code_delimiter | 2 |
| AM-006 | What is the Supplementary Allowance for ... | allowance_matrix | medium | ✅ | fence | 2 |
| AM-007 | What is the Phone Allowance for all empl... | allowance_matrix | medium | ✅ | no_code_delimiter | 2 |
| AM-008 | What is the Etihad Allowance for all emp... | allowance_matrix | hard | ✅ | no_code_delimiter | 3 |
| AM-009 | What is the Secondment Allowance for all... | allowance_matrix | hard | ✅ | no_code_delimiter | 2 |
| AM-010 | What is the Technical Special Allowance ... | allowance_matrix | hard | ✅ | fence | 2 |
| AM-011 | What is the Special Contract Basic Salar... | allowance_matrix | hard | ✅ | fence | 2 |
| MJ-001 | For each employee, show their most recen... | multi_struct_join | extreme | ✅ | no_code_delimiter | 4 |
| MJ-002 | Show employees who have both previous em... | multi_struct_join | extreme | ✅ | no_code_delimiter | 5 |
| MJ-003 | For each employee, count: number of comp... | multi_struct_join | extreme | ✅ | no_code_delimiter | 2 |
| MJ-004 | Show the CV education degree alongside t... | multi_struct_join | hard | ✅ | no_code_delimiter | 5 |
| MJ-005 | For each employee, list their CV work ex... | multi_struct_join | extreme | ✅ | fence | 3 |
| MJ-006 | Build a complete career timeline for Eis... | multi_struct_join | extreme | ✅ | fence | 2 |
| MJ-007 | For employees who have both Employee Ach... | multi_struct_join | hard | ✅ | no_code_delimiter | 5 |
| NT-001 | Which employees have a ZERO Etihad Allow... | negation_trap | hard | ✅ | fence | 2 |
| NT-002 | Which employees have NO Secondment Allow... | negation_trap | hard | ✅ | fence | 2 |
| NT-003 | Show employees who do NOT have any leave... | negation_trap | hard | ✅ | no_code_delimiter | 2 |
| NT-004 | Which employees have never been promoted... | negation_trap | medium | ✅ | fence | 2 |
| NT-005 | List employees who have ZERO sick leave ... | negation_trap | medium | ✅ | fence | 2 |
| NT-006 | Which employees have no previous employe... | negation_trap | hard | ✅ | no_code_delimiter | 2 |

## 7. Multi-Turn Conversation Details

### CP-001: Allowance denial cascade

**Turns:** 4 | **Successful:** 4 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Show me the Basic Salary for all employe... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | Now show the Housing Allowance and Cost ... | ✅ | fence | 0 | fence | 2 |
| 3 | Now add the Etihad Allowance. I was told... | ✅ | no_code_delimiter | 2 | fence | 3 |
| 4 | Finally add the Secondment Allowance and... | ✅ | fence | 4 | fence | 2 |

### CP-002: Struct discovery escalation

**Turns:** 3 | **Successful:** 3 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Show me all the leave types that employe... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | Now show the competency names for each e... | ✅ | no_code_delimiter | 0 | fence | 2 |
| 3 | Add the objective names as well. I want ... | ✅ | fence | 2 | fence | 3 |

### CP-003: Grade comparison trap

**Turns:** 3 | **Successful:** 3 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the Employee Grade for each empl... | ✅ | fence | 0 | N/A | 2 |
| 2 | Now show the Grade from the Assignment H... | ✅ | fence | 0 | fence | 3 |
| 3 | For employees where the grades differ be... | ✅ | no_code_delimiter | 2 | fence | 2 |

### CP-004: Career timeline with allowances

**Turns:** 4 | **Successful:** 4 | **Formats:** no_code_delimiter, fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Show the assignment history for Eisa Ram... | ✅ | fence | 0 | N/A | 2 |
| 2 | Add his previous employer records to the... | ✅ | fence | 0 | fence | 2 |
| 3 | Now add his CV work experience to the ti... | ✅ | fence | 2 | fence | 2 |
| 4 | Finally, include his Etihad Allowance an... | ✅ | no_code_delimiter | 4 | fence | 2 |

## 8. Failure Analysis

**Single-turn failures:** 3
- **HS-004** (handoff_sabotage): NoCodeFoundError: No code found in the response
  - Query: _Show the Special Contract Basic Salary for each employee who has one._
  - Format: fence
- **HS-005** (handoff_sabotage): NoCodeFoundError: No code found in the response
  - Query: _Compare Phone Allowance and Supplementary Allowance for all employees. Show both values side by side._
  - Format: no_code_delimiter
- **TC-001** (triple_name_collision): NoCodeFoundError: No code found in the response
  - Query: _Show the Start Date from Employee Assignment History, the Leave Start Date from Employee Leave Details, and the Start Date from Employee Previous Employer for Afra Khalifa Shaheen Alghfeli. These are three different 'Start Date' fields from three different structs._
  - Format: fence

**Multi-turn failures:** 0

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
