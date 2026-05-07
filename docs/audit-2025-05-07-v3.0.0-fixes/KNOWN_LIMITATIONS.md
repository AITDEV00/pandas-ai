# Known Limitations & Design Decisions

**Date:** 2025-05-08  
**Branch:** jya0-v3.0.0  
**Companion to:** `PLAN_COLUMN_SELECTION_PIPELINE.md`, `SOLUTION_SUGGESTIONS.md`

---

## Known Limitations

### 1. Multi-Output Queries Not Supported (Issue 14)

PandasAI's result format is `result = {"type": "<type>", "value": <value>}` — a single type-value pair. There is no mechanism for a query to return multiple types simultaneously (e.g., text answer + chart + dataframe export).

**Workarounds:**
- Make multiple API calls with different `output_type` values
- Use `output_type = "auto"` to let the LLM choose the single most appropriate type
- Use `output_type = "dataframe"` to get raw data and render charts/format text on the client side

**Example:**
```json
// Instead of one call expecting both text and chart, make two calls:
// 1. {"query": "how many are female?", "output_type": "string"}
// 2. {"query": "show me a chart of gender distribution", "output_type": "plot"}
```

**Future work:** Extend the result format to support multi-type responses:
```python
# Future format (NOT implemented now):
result = [
    {"type": "string", "value": "There are 10 female employees."},
    {"type": "plot", "value": "exports/charts/gender_dist.png"},
]
```

### 2. Value-Type Mismatch Uses Generic Correction Path (Issue 18)

If the LLM generates `result = {"type": "string", "value": 10}` (correct type "string", but value is a number instead of a string), the existing `_validate_response()` raises `InvalidOutputValueMismatch` — NOT `InvalidLLMOutputType`. This means the correction prompt is the **generic** error prompt, not the output-type-specific one.

**Current behavior:** The generic error prompt will tell the LLM that `value` must be a string for type "string", which should be sufficient in most cases. The handler's `_coerce_response_type()` will also attempt to coerce the value (e.g., `10` → `"10"` for string←number).

**Future improvement:** Route `InvalidOutputValueMismatch` to the type-specific correction prompt when `output_type` is set:
```python
# Future improvement (NOT implemented now):
def _regenerate_code_after_error(self, code: str, error: Exception) -> str:
    if isinstance(error, InvalidLLMOutputType):
        prompt = get_correct_output_type_error_prompt(...)
    elif isinstance(error, InvalidOutputValueMismatch) and self._state.output_type:
        prompt = get_correct_output_type_error_prompt(...)
    else:
        prompt = get_correct_error_prompt_for_sql(...)
    return self._code_generator.generate_code(prompt)
```

---

## Open Question Resolutions (Issue 20)

| # | Question | Resolution | Rationale |
|---|----------|-----------|-----------|
| 1 | Should Step 1 use the same LLM as Step 2? | **Yes, same LLM** | Simplicity; Step 1 is cheap (~20K tokens). Can optimize later with a smaller model. |
| 2 | Serialize ALL columns or just names+descriptions in Step 1? | **Names + types + descriptions + samples** | Samples are critical for understanding what a column contains (e.g., "status" is ambiguous without values). |
| 3 | What about multiple DataFrames? | **Union all columns, filter each independently** | Simple; works with the existing multi-DataFrame support. |
| 4 | Should auto-fill descriptions be a separate endpoint? | **No, during registration** | One-time cost; part of the enrichment pipeline. |
| 5 | What if the user's query needs columns the LLM didn't select? | **Retry with full DataFrame** | `try/finally` restores originals; existing retry logic handles SQL errors on missing columns. |
| 6 | Should we reduce `sample_head_size` for wide tables? | **No, column selection handles this** | After trimming, the DataFrame has few columns; `sample_head_size=10` is fine. |
| 7 | What if a struct column has 50+ inner fields? | **Show field names + types but NOT samples in Step 1** | Keeps Step 1 cheap; samples only in Step 2 via trimmed schema. |
| 8 | What if the user's query references an inner field by a different name? | **Rely on auto-fill descriptions + LLM semantic matching** | Good descriptions help the LLM match semantically. |
| 9 | Should Step 1 also select aggregation functions? | **No** | Step 1 is strictly about WHICH columns. Step 2 decides HOW to use them. |
| 10 | Does DuckDB SQL execution need the full DataFrame? | **No** | Trimmed DataFrame still has all data for kept columns; UNNEST works because struct column data is intact. |
