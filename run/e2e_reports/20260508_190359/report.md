# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 19:11:22
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_190359`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `f58b312c-584b-4a69-adf7-ee410797fdf9`

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 58 |
| Successful | 58 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 32 |
| Multi-turn queries | 26 |
| Avg LLM calls per query | 1.4 |
| Max LLM calls per query | 4 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 58 | 100.0% |

**Key finding:** The `marker` format (`---\nCode:`) in the LLM output would trigger `NoCodeFoundError` 
without the fallback extractor. The `fence` format (triple backticks) is the expected format.

## 3. Root Cause: Assistant Message Format in Conversation History

**Multi-turn conversations where `---\nCode:` marker appeared in assistant messages:** 0/8

The `_store_assistant_message()` method in `pandasai/agent/base.py` stores responses as:
```
f"{response_text}\n\n---\nCode:\n{working_code}"
```

This format is sent back to the LLM on follow-up turns, potentially teaching it to mimic 
the `---\nCode:` format instead of using code fences.

## 4. Results by Category

| Category | Total | Success | Fail | Success Rate |
|----------|-------|---------|------|--------------|
| aggregation | 2 | 2 | 0 | 100% |
| ambiguous | 2 | 2 | 0 | 100% |
| computed | 2 | 2 | 0 | 100% |
| count | 1 | 1 | 0 | 100% |
| count_filter | 2 | 2 | 0 | 100% |
| cross_struct | 1 | 1 | 0 | 100% |
| cross_struct_comparison | 1 | 1 | 0 | 100% |
| distinct | 1 | 1 | 0 | 100% |
| explanation | 1 | 1 | 0 | 100% |
| full_scan | 1 | 1 | 0 | 100% |
| grouped_aggregation | 2 | 2 | 0 | 100% |
| grouped_count | 2 | 2 | 0 | 100% |
| lookup | 4 | 4 | 0 | 100% |
| multi_filter | 2 | 2 | 0 | 100% |
| no_result | 2 | 2 | 0 | 100% |
| off_topic | 1 | 1 | 0 | 100% |
| struct_aggregation | 1 | 1 | 0 | 100% |
| struct_filter | 1 | 1 | 0 | 100% |
| struct_query | 3 | 3 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| easy | 10 | 10 | 0 | 100% |
| hard | 6 | 6 | 0 | 100% |
| medium | 11 | 11 | 0 | 100% |
| trivial | 5 | 5 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| SS-001 | How many employees are there? | count | trivial | ✅ | fence | 1 |
| SS-002 | How many female employees are there? | count_filter | trivial | ✅ | fence | 1 |
| SS-003 | How many male employees are there? | count_filter | trivial | ✅ | fence | 1 |
| SS-004 | What is Ayesha's job title? | lookup | easy | ✅ | fence | 1 |
| SS-005 | Which department does Afra work in? | lookup | easy | ✅ | fence | 1 |
| SS-006 | What is the nationality of all employees... | lookup | trivial | ✅ | fence | 1 |
| SS-007 | What is the average age of all employees... | aggregation | easy | ✅ | fence | 1 |
| SS-008 | What is the total basic salary paid acro... | aggregation | easy | ✅ | fence | 1 |
| SS-009 | List all the sectors in the organization... | distinct | easy | ✅ | fence | 1 |
| SS-010 | Who is the supervisor of Noura? | lookup | easy | ✅ | fence | 1 |
| SC-001 | How many employees are in each sector? G... | grouped_count | medium | ✅ | fence | 1 |
| SC-002 | What is the average basic salary by gend... | grouped_aggregation | medium | ✅ | fence | 1 |
| SC-003 | How many employees work in each departme... | grouped_count | medium | ✅ | fence | 1 |
| SC-004 | what is the percentage by different leav... | struct_query | hard | ✅ | fence | 2 |
| SC-005 | What are the different leave types taken... | struct_query | hard | ✅ | fence | 2 |
| SC-006 | List all competencies where the supervis... | struct_query | hard | ✅ | fence | 4 |
| SC-007 | Which female employees are in the Wellbe... | multi_filter | medium | ✅ | fence | 1 |
| SC-008 | Find employees who have a PhD degree and... | multi_filter | medium | ✅ | fence | 1 |
| SC-009 | What is the ratio of male to female empl... | computed | easy | ✅ | fence | 1 |
| SC-010 | What percentage of the total entitlement... | computed | medium | ✅ | fence | 1 |
| SC-011 | How many total leave days has each emplo... | struct_aggregation | hard | ✅ | fence | 1 |
| SC-012 | Are there any denied leave requests? If ... | struct_filter | medium | ✅ | fence | 2 |
| SC-013 | Which employees have both CV achievement... | cross_struct | hard | ✅ | fence | 1 |
| SC-014 | What is the average ADEO experience (in ... | grouped_aggregation | medium | ✅ | fence | 3 |
| SC-015 | Who are the most experienced employees i... | ambiguous | medium | ✅ | fence | 2 |
| SC-016 | Show me a summary of the employee data. | ambiguous | medium | ✅ | fence | 1 |
| EC-001 | How many employees named John are there? | no_result | easy | ✅ | fence | 1 |
| EC-002 | What is the salary of employee number 99... | no_result | easy | ✅ | fence | 1 |
| EC-003 | Show me all the data in the table. | full_scan | easy | ✅ | fence | 1 |
| EC-004 | Calculate the median salary and explain ... | explanation | medium | ✅ | fence | 1 |
| EC-005 | What is 2+2? | off_topic | trivial | ✅ | fence | 3 |
| EC-006 | Compare the total leave days taken vs. t... | cross_struct_comparison | hard | ✅ | fence | 2 |

## 7. Multi-Turn Conversation Details

### MT-001: Ayesha drill-down

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Find the employee named Ayesha. | ✅ | fence | 0 | N/A | 1 |
| 2 | What is her job title and department? | ✅ | fence | 2 | fence | 1 |
| 3 | What percentage by different leave types... | ✅ | fence | 4 | fence | 4 |

### MT-002: Sector comparison

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | List all the sectors and how many employ... | ✅ | fence | 0 | N/A | 1 |
| 2 | Which sector has the highest average sal... | ✅ | fence | 2 | fence | 1 |
| 3 | Who are the employees in that sector? | ✅ | fence | 4 | fence | 1 |

### MT-003: Leave analysis

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | How many employees have taken leave? | ✅ | fence | 0 | N/A | 3 |
| 2 | What are the different leave types avail... | ✅ | fence | 2 | fence | 1 |
| 3 | Which employee has taken the most wellbe... | ✅ | fence | 4 | fence | 2 |

### MT-004: Salary & compensation

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the average total entitlement am... | ✅ | fence | 0 | N/A | 1 |
| 2 | How does it differ between male and fema... | ✅ | fence | 2 | fence | 2 |
| 3 | Which employee has the highest total ent... | ✅ | fence | 4 | fence | 1 |

### MT-005: Competency analysis

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What competencies are evaluated for empl... | ✅ | fence | 0 | N/A | 1 |
| 2 | For the competency 'Digital Savviness', ... | ✅ | fence | 2 | fence | 1 |
| 3 | Are there any employees where the superv... | ✅ | fence | 4 | fence | 1 |

### MT-006: Career progression

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Which employees have been promoted recen... | ✅ | fence | 0 | N/A | 1 |
| 2 | What was the reason for their promotion? | ✅ | fence | 2 | fence | 1 |
| 3 | How long has it been since the last prom... | ✅ | fence | 4 | fence | 1 |

### MT-007: Education & qualifications

**Turns:** 3 | **Successful:** 3 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | What is the most common degree among emp... | ✅ | fence | 0 | N/A | 1 |
| 2 | Which employees have a Master's degree o... | ✅ | fence | 2 | fence | 4 |
| 3 | What qualifications do they hold? List t... | ✅ | fence | 4 | fence | 1 |

### MT-008: Long conversation stress test

**Turns:** 5 | **Successful:** 5 | **Formats:** fence

| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |
|------|-------|---------|--------|---------------|-----------------|-----------|
| 1 | Give me an overview of the organization'... | ✅ | fence | 0 | N/A | 1 |
| 2 | How is the gender distribution? | ✅ | fence | 2 | fence | 1 |
| 3 | What about the age distribution? | ✅ | fence | 4 | fence | 1 |
| 4 | Which department has the most employees? | ✅ | fence | 6 | fence | 1 |
| 5 | Who is the highest paid employee in that... | ✅ | fence | 8 | fence | 2 |

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
