# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 20:08:15
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_195139`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `bd041abd-bc93-4e30-b1c3-8707e36748ee`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 47 |
| Successful | 47 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 33 |
| Multi-turn queries | 14 |
| Avg LLM calls per query | 2.3 |
| Max LLM calls per query | 4 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 28 | 59.6% |
| no_code_delimiter | 19 | 40.4% |

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
| budget_ratio_edge | 6 | 6 | 0 | 100% |
| column_name_collision | 6 | 6 | 0 | 100% |
| column_selection_handoff | 7 | 7 | 0 | 100% |
| semantic_mapping_gap | 7 | 7 | 0 | 100% |
| struct_inner_field_blindness | 7 | 7 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| extreme | 11 | 11 | 0 | 100% |
| hard | 21 | 21 | 0 | 100% |
| medium | 1 | 1 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| CH-001 | What is the Etihad Allowance for Shamma ... | column_selection_handoff | hard | ✅ | no_code_delimiter | 2 |
| CH-002 | List all employees who have a non-zero S... | column_selection_handoff | hard | ✅ | no_code_delimiter | 2 |
| CH-003 | Compare the Social Allowance and Child A... | column_selection_handoff | hard | ✅ | fence | 2 |
| CH-004 | What is the Family Book Number for Eisa ... | column_selection_handoff | hard | ✅ | fence | 2 |
| CH-005 | Show me the Special Contract Basic Salar... | column_selection_handoff | extreme | ✅ | no_code_delimiter | 2 |
| CH-006 | What is the Phone Allowance for each emp... | column_selection_handoff | hard | ✅ | no_code_delimiter | 2 |
| CH-007 | For each employee, show: Employee Name, ... | column_selection_handoff | extreme | ✅ | fence | 2 |
| SM-001 | Who are the most senior employees at ADE... | semantic_mapping_gap | hard | ✅ | no_code_delimiter | 2 |
| SM-002 | Which employees have been with ADEO the ... | semantic_mapping_gap | hard | ✅ | fence | 2 |
| SM-003 | How many sick days has each employee use... | semantic_mapping_gap | hard | ✅ | fence | 2 |
| SM-004 | Which employees are due for promotion ba... | semantic_mapping_gap | extreme | ✅ | fence | 2 |
| SM-005 | Show the organizational hierarchy: secto... | semantic_mapping_gap | medium | ✅ | no_code_delimiter | 2 |
| SM-006 | What is the gender diversity ratio in ea... | semantic_mapping_gap | hard | ✅ | fence | 2 |
| SM-007 | Which employees have the highest academi... | semantic_mapping_gap | hard | ✅ | no_code_delimiter | 2 |
| SB-001 | List all leave records with their leave ... | struct_inner_field_blindness | hard | ✅ | fence | 2 |
| SB-002 | Show all competency ratings with the com... | struct_inner_field_blindness | hard | ✅ | fence | 3 |
| SB-003 | What are the objectives set for each emp... | struct_inner_field_blindness | hard | ✅ | fence | 2 |
| SB-004 | List all previous employers with company... | struct_inner_field_blindness | hard | ✅ | fence | 2 |
| SB-005 | Show the assignment history for all empl... | struct_inner_field_blindness | hard | ✅ | fence | 2 |
| SB-006 | What CV education records exist? Show in... | struct_inner_field_blindness | hard | ✅ | fence | 2 |
| SB-007 | UNNEST all struct arrays in the dataset ... | struct_inner_field_blindness | extreme | ✅ | no_code_delimiter | 2 |
| CC-001 | Show the Start Date from Employee Assign... | column_name_collision | extreme | ✅ | fence | 4 |
| CC-002 | Compare the Position Title from Assignme... | column_name_collision | hard | ✅ | no_code_delimiter | 3 |
| CC-003 | Show the Employee Grade from Employee Ma... | column_name_collision | hard | ✅ | no_code_delimiter | 3 |
| CC-004 | Compare the End Date from Previous Emplo... | column_name_collision | extreme | ✅ | fence | 3 |
| CC-005 | Show the CV Job Title from CV Work Exper... | column_name_collision | extreme | ✅ | fence | 3 |
| CC-006 | Compare the CV Degree Name from CV Educa... | column_name_collision | hard | ✅ | fence | 3 |
| BR-001 | Show Employee Name, Email Address, Depar... | budget_ratio_edge | hard | ✅ | fence | 2 |
| BR-002 | For each employee, show: Name, Departmen... | budget_ratio_edge | extreme | ✅ | no_code_delimiter | 2 |
| BR-003 | Show me everything about Eisa Rames Kham... | budget_ratio_edge | extreme | ✅ | no_code_delimiter | 3 |
| BR-004 | Create a summary table with one row per ... | budget_ratio_edge | extreme | ✅ | fence | 3 |
| BR-005 | What are the distinct values in each col... | budget_ratio_edge | extreme | ✅ | no_code_delimiter | 2 |
| BR-006 | Show the schema of the enterprise_data t... | budget_ratio_edge | hard | ✅ | fence | 2 |

## 7. Multi-Turn Conversation Details

### RT-001: Allowance escalation trap

**Turns:** 4 | **Successful:** 4 | **Formats:** fence, no_code_delimiter

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the Basic Salary for each employ... | ✅ | fence | 0 | N/A | 2 |
| 2 | Now add the Housing Allowance and Cost o... | ✅ | no_code_delimiter | 0 | fence | 3 |
| 3 | Also include the Etihad Allowance and Se... | ✅ | no_code_delimiter | 2 | fence | 3 |
| 4 | Create a complete compensation breakdown... | ✅ | no_code_delimiter | 4 | fence | 2 |

### RT-002: Employee profile deep dive

**Turns:** 3 | **Successful:** 3 | **Formats:** fence, no_code_delimiter

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | List all employees with their name, depa... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | Add their Date of Joining and Last Promo... | ✅ | no_code_delimiter | 0 | fence | 3 |
| 3 | Now add their Family Book Number and Num... | ✅ | fence | 2 | fence | 2 |

### RT-003: Leave to competency pivot

**Turns:** 3 | **Successful:** 3 | **Formats:** fence, no_code_delimiter

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | How many employees have taken sick leave... | ✅ | no_code_delimiter | 0 | N/A | 2 |
| 2 | What are the detailed leave records? Sho... | ✅ | fence | 0 | fence | 2 |
| 3 | For those employees, what are their comp... | ✅ | fence | 2 | fence | 2 |

### RT-004: Career progression audit

**Turns:** 4 | **Successful:** 4 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Show all employees and their current gra... | ✅ | fence | 0 | N/A | 2 |
| 2 | Which employees have been promoted? Show... | ✅ | fence | 0 | fence | 2 |
| 3 | Show their full assignment history with ... | ✅ | fence | 2 | fence | 2 |
| 4 | Cross-reference with their previous empl... | ✅ | fence | 4 | fence | 3 |

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
