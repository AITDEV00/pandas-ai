# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 21:30:03
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_205908`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `904f2d90-ec03-47f1-9a50-58d89c571006`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 39 |
| Successful | 39 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 39 |
| Multi-turn queries | 0 |
| Avg LLM calls per query | 2.7 |
| Max LLM calls per query | 5 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 23 | 59.0% |
| no_code_delimiter | 16 | 41.0% |

**Key finding:** The `marker` format (`---\nCode:`) in the LLM output would trigger `NoCodeFoundError` 
without the fallback extractor. The `fence` format (triple backticks) is the expected format.

## 3. Root Cause: Assistant Message Format in Conversation History

**Multi-turn conversations where `---\nCode:` marker appeared in assistant messages:** 0/0

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
| handoff_sabotage | 8 | 8 | 0 | 100% |
| multi_struct_join | 7 | 7 | 0 | 100% |
| negation_trap | 6 | 6 | 0 | 100% |
| triple_name_collision | 7 | 7 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| easy | 2 | 2 | 0 | 100% |
| extreme | 12 | 12 | 0 | 100% |
| hard | 18 | 18 | 0 | 100% |
| medium | 7 | 7 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| HS-001 | What is the exact Etihad Allowance amoun... | handoff_sabotage | extreme | ✅ | fence | 3 |
| HS-002 | Show the Secondment Allowance for each e... | handoff_sabotage | extreme | ✅ | fence | 2 |
| HS-003 | What is the Technical Special Allowance ... | handoff_sabotage | extreme | ✅ | no_code_delimiter | 4 |
| HS-004 | Show the Special Contract Basic Salary f... | handoff_sabotage | hard | ✅ | fence | 3 |
| HS-005 | Compare Phone Allowance and Supplementar... | handoff_sabotage | hard | ✅ | no_code_delimiter | 2 |
| HS-006 | What is the Total Entitlement Amount for... | handoff_sabotage | hard | ✅ | fence | 2 |
| HS-007 | Show me every single allowance column fo... | handoff_sabotage | extreme | ✅ | fence | 2 |
| HS-008 | What is the Time Since Last Promotion fo... | handoff_sabotage | hard | ✅ | fence | 2 |
| TC-001 | Show the Start Date from Employee Assign... | triple_name_collision | extreme | ✅ | fence | 2 |
| TC-002 | Compare the End Date from Employee Assig... | triple_name_collision | extreme | ✅ | fence | 5 |
| TC-003 | Show the Job Title from Employee Master ... | triple_name_collision | extreme | ✅ | fence | 4 |
| TC-004 | What is the Employee Grade from Employee... | triple_name_collision | hard | ✅ | no_code_delimiter | 3 |
| TC-005 | Show the Assignment Name from Employee A... | triple_name_collision | hard | ✅ | fence | 5 |
| TC-006 | List the CV Degree Name from CV Employee... | triple_name_collision | hard | ✅ | no_code_delimiter | 3 |
| TC-007 | Show the CV Company Name from CV Employe... | triple_name_collision | hard | ✅ | fence | 2 |
| AM-001 | What is the Basic Salary for all employe... | allowance_matrix | easy | ✅ | fence | 2 |
| AM-002 | What is the Housing Allowance for all em... | allowance_matrix | easy | ✅ | no_code_delimiter | 3 |
| AM-003 | What is the Cost of Living Allowance for... | allowance_matrix | medium | ✅ | fence | 2 |
| AM-004 | What is the Social Allowance for all emp... | allowance_matrix | medium | ✅ | fence | 2 |
| AM-005 | What is the Child Allowance for all empl... | allowance_matrix | medium | ✅ | no_code_delimiter | 3 |
| AM-006 | What is the Supplementary Allowance for ... | allowance_matrix | medium | ✅ | no_code_delimiter | 2 |
| AM-007 | What is the Phone Allowance for all empl... | allowance_matrix | medium | ✅ | fence | 2 |
| AM-008 | What is the Etihad Allowance for all emp... | allowance_matrix | hard | ✅ | no_code_delimiter | 3 |
| AM-009 | What is the Secondment Allowance for all... | allowance_matrix | hard | ✅ | no_code_delimiter | 4 |
| AM-010 | What is the Technical Special Allowance ... | allowance_matrix | hard | ✅ | fence | 2 |
| AM-011 | What is the Special Contract Basic Salar... | allowance_matrix | hard | ✅ | no_code_delimiter | 2 |
| MJ-001 | For each employee, show their most recen... | multi_struct_join | extreme | ✅ | no_code_delimiter | 5 |
| MJ-002 | Show employees who have both previous em... | multi_struct_join | extreme | ✅ | no_code_delimiter | 2 |
| MJ-003 | For each employee, count: number of comp... | multi_struct_join | extreme | ✅ | fence | 3 |
| MJ-004 | Show the CV education degree alongside t... | multi_struct_join | hard | ✅ | no_code_delimiter | 3 |
| MJ-005 | For each employee, list their CV work ex... | multi_struct_join | extreme | ✅ | fence | 2 |
| MJ-006 | Build a complete career timeline for Eis... | multi_struct_join | extreme | ✅ | no_code_delimiter | 2 |
| MJ-007 | For employees who have both Employee Ach... | multi_struct_join | hard | ✅ | no_code_delimiter | 3 |
| NT-001 | Which employees have a ZERO Etihad Allow... | negation_trap | hard | ✅ | fence | 2 |
| NT-002 | Which employees have NO Secondment Allow... | negation_trap | hard | ✅ | fence | 2 |
| NT-003 | Show employees who do NOT have any leave... | negation_trap | hard | ✅ | fence | 3 |
| NT-004 | Which employees have never been promoted... | negation_trap | medium | ✅ | fence | 2 |
| NT-005 | List employees who have ZERO sick leave ... | negation_trap | medium | ✅ | no_code_delimiter | 3 |
| NT-006 | Which employees have no previous employe... | negation_trap | hard | ✅ | fence | 2 |

## 7. Multi-Turn Conversation Details

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
