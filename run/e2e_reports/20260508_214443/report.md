# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 21:54:25
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_214443`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `00d5bc88-cada-4aac-bbf7-540c9cb253dc`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 40 |
| Successful | 40 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 40 |
| Multi-turn queries | 0 |
| Avg LLM calls per query | 2.5 |
| Max LLM calls per query | 5 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| fence | 21 | 52.5% |
| no_code_delimiter | 19 | 47.5% |

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
| bracket_naming_inconsistency | 8 | 8 | 0 | 100% |
| column_hint_phrasing | 8 | 8 | 0 | 100% |
| employee_id_leading_zero | 5 | 5 | 0 | 100% |
| multi_struct_field_selection | 5 | 5 | 0 | 100% |
| naming_convention_stress | 6 | 6 | 0 | 100% |
| struct_field_prompt_confusion | 8 | 8 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| extreme | 16 | 16 | 0 | 100% |
| hard | 21 | 21 | 0 | 100% |
| medium | 3 | 3 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| BN-001 | what is the percentage by different leav... | bracket_naming_inconsistency | extreme | ✅ | fence | 2 |
| BN-002 | what is the percentage by different leav... | bracket_naming_inconsistency | hard | ✅ | no_code_delimiter | 3 |
| BN-003 | Show me the leave type and duration for ... | bracket_naming_inconsistency | extreme | ✅ | no_code_delimiter | 5 |
| BN-004 | List all leave types and their approval ... | bracket_naming_inconsistency | hard | ✅ | fence | 2 |
| BN-005 | What are the different assignment names ... | bracket_naming_inconsistency | extreme | ✅ | fence | 2 |
| BN-006 | Show previous employer names and job tit... | bracket_naming_inconsistency | extreme | ✅ | fence | 4 |
| BN-007 | What qualifications does Ahmed have? Sho... | bracket_naming_inconsistency | extreme | ✅ | no_code_delimiter | 2 |
| BN-008 | What are the CV work experience details ... | bracket_naming_inconsistency | extreme | ✅ | no_code_delimiter | 2 |
| EZ-001 | whatis the employee id of ayesha | employee_id_leading_zero | hard | ✅ | no_code_delimiter | 2 |
| EZ-002 | What is the employee number for Eisa Ram... | employee_id_leading_zero | hard | ✅ | no_code_delimiter | 2 |
| EZ-003 | List all employee IDs and names. The emp... | employee_id_leading_zero | hard | ✅ | no_code_delimiter | 2 |
| EZ-004 | Find the employee with ID 0111. What is ... | employee_id_leading_zero | extreme | ✅ | fence | 2 |
| EZ-005 | What is the Family Book Number for Ayesh... | employee_id_leading_zero | hard | ✅ | no_code_delimiter | 2 |
| SP-001 | what is the percetage by different leave... | struct_field_prompt_confusion | hard | ✅ | no_code_delimiter | 4 |
| SP-002 | Which employees have taken Annual leave?... | struct_field_prompt_confusion | hard | ✅ | fence | 2 |
| SP-003 | Show me the assignment history for each ... | struct_field_prompt_confusion | hard | ✅ | fence | 2 |
| SP-004 | What degrees do employees have? Show the... | struct_field_prompt_confusion | hard | ✅ | fence | 3 |
| SP-005 | What are the objectives for Noura? Show ... | struct_field_prompt_confusion | hard | ✅ | fence | 3 |
| SP-006 | Show the competency ratings for each emp... | struct_field_prompt_confusion | hard | ✅ | fence | 4 |
| SP-007 | What achievements does Shamma have? Show... | struct_field_prompt_confusion | hard | ✅ | no_code_delimiter | 2 |
| SP-008 | List all employees and their hobbies. Sh... | struct_field_prompt_confusion | hard | ✅ | fence | 2 |
| CH-001 | What leave types did Ayesha take? use th... | column_hint_phrasing | extreme | ✅ | fence | 2 |
| CH-002 | What leave types did Ayesha take? Use th... | column_hint_phrasing | extreme | ✅ | fence | 2 |
| CH-003 | What leave types did Ayesha take? use th... | column_hint_phrasing | hard | ✅ | fence | 3 |
| CH-004 | What leave types did Ayesha take? Refer ... | column_hint_phrasing | hard | ✅ | fence | 2 |
| CH-005 | What leave types did Ayesha take? Look a... | column_hint_phrasing | extreme | ✅ | no_code_delimiter | 2 |
| CH-006 | What leave types did Ayesha take? Check ... | column_hint_phrasing | hard | ✅ | no_code_delimiter | 2 |
| CH-007 | Show me leave types and durations for al... | column_hint_phrasing | medium | ✅ | no_code_delimiter | 2 |
| CH-008 | Show me leave types and durations for al... | column_hint_phrasing | medium | ✅ | no_code_delimiter | 3 |
| MS-001 | Show each employee's leave types and the... | multi_struct_field_selection | extreme | ✅ | no_code_delimiter | 2 |
| MS-002 | For each employee, show their previous e... | multi_struct_field_selection | extreme | ✅ | fence | 5 |
| MS-003 | Show Ayesha's leave types, assignment hi... | multi_struct_field_selection | extreme | ✅ | fence | 3 |
| MS-004 | Compare each employee's CV work experien... | multi_struct_field_selection | extreme | ✅ | no_code_delimiter | 2 |
| MS-005 | Show each employee's qualifications and ... | multi_struct_field_selection | hard | ✅ | no_code_delimiter | 2 |
| NC-001 | What is the total leave duration in days... | naming_convention_stress | hard | ✅ | fence | 2 |
| NC-002 | What is the total leave duration for eac... | naming_convention_stress | extreme | ✅ | fence | 2 |
| NC-003 | Show the Previous Employer Name and Prev... | naming_convention_stress | hard | ✅ | no_code_delimiter | 5 |
| NC-004 | Show [Employee Previous Employer[Previou... | naming_convention_stress | extreme | ✅ | fence | 2 |
| NC-005 | What is the CV Employee Summary for each... | naming_convention_stress | medium | ✅ | no_code_delimiter | 3 |
| NC-006 | Show the Goal Plan Name and Objective Na... | naming_convention_stress | hard | ✅ | fence | 2 |

## 7. Multi-Turn Conversation Details

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
