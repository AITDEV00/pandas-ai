# E2E LLM Behavior Test Report

**Generated:** 2026-05-08 21:42:40
**Report directory:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/20260508_214229`
**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)
**Data file:** `/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx`
**Conversation ID:** `1b139fb8-5c46-4d33-957c-d7e6201831f8`
**Column Selection:** `False` (threshold=30, budget=0.1)

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Total queries executed | 1 |
| Successful | 1 (100.0%) |
| Failed | 0 (0.0%) |
| Single-turn queries | 1 |
| Multi-turn queries | 0 |
| Avg LLM calls per query | 2.0 |
| Max LLM calls per query | 2 |

## 2. LLM Output Format Analysis

This is the key analysis for the `NoCodeFoundError` root cause.

| Format | Count | Percentage |
|--------|-------|------------|
| no_code_delimiter | 1 | 100.0% |

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
| bracket_naming_inconsistency | 1 | 1 | 0 | 100% |

## 5. Results by Difficulty

| Difficulty | Total | Success | Fail | Success Rate |
|------------|-------|---------|------|--------------|
| extreme | 1 | 1 | 0 | 100% |

## 6. Single-Turn Query Details

| ID | Query | Category | Difficulty | Success | Format | LLM Calls |
|----|-------|----------|------------|---------|--------|-----------|
| BN-001 | what is the percentage by different leav... | bracket_naming_inconsistency | extreme | ✅ | no_code_delimiter | 2 |

## 7. Multi-Turn Conversation Details

## 8. Failure Analysis

🎉 **No failures detected!** All queries completed successfully.

## 9. Recommendations

### ✅ No `---\nCode:` Marker in LLM Output

The LLM consistently used code fences. However, the root cause still exists:
`_store_assistant_message()` stores `---\nCode:` format in memory, which is sent back to the LLM.
This may cause the LLM to mimic the format under certain conditions.

**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\nCode:`.
