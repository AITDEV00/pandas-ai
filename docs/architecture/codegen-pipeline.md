# Code Generation Pipeline

How PandasAI turns a natural-language query into executable Python + SQL, and
where deterministic validation runs.

## Flow

1. **LLM prompt** — the query, schema listings, and a code strategy are sent to
   the model (via LiteLLM).
2. **Code generation** — the model returns Python that calls `execute_sql_query(...)`
   for DuckDB, then processes the returned DataFrame with pandas.
3. **Requirement validation** — `CodeGenerator.validate_and_clean_code()` checks
   the code meets the configured requirements.
4. **Deterministic structural self-review** — a *static* validator
   (`StructuralCodeValidator`) replays schema-name checks over the emitted code
   **before** execution, catching fabricated struct column names, bad struct
   field keys, placeholder tokens, alias drift, and undefined variables.
5. **Cleaning** — the code cleaner normalizes the generated code.
6. **Execution** — the sandbox runs the code against DuckDB and returns a response.

## The structural self-review

The validator lives at
`pandasai/core/code_generation/structural_validator.py` and is wired into
`CodeGenerator.validate_and_clean_code()` in
`pandasai/core/code_generation/base.py`.

It is **deterministic** — no sampling, no temperature, no second LLM call. It
performs static checks that replay the exact schema-name checks the runtime
would eventually hit, but *earlier*, so a wasted retry is avoided. Checks:

| Check | What it detects |
|-------|-----------------|
| Placeholder rejection | `placeholder`, `TODO`, `..`, `[..]` tokens in SQL |
| UNNEST column match | `UNNEST("...")` strings that aren't in the schema character-for-character |
| Struct field keys | `rec['Base[Field]']` access using an invalid key |
| Alias consistency | `AS skill` in SQL vs `df['skill_name']` in Python (drift) |
| Undefined variables | f-string / join referencing a var never assigned |

If a check fails, it raises a precise `ValueError` that flows back into the
agent's retry loop as the error signal — telling the model the exact problem
instead of a generic execution failure.

> **Temperature note:** emission temperature is kept the same for retries — the
> deterministic self-review does not rely on lowering temperature.

## Retry loop

When execution fails, the error message (including any structural self-review
finding) is fed back to the LLM as the signal for the next attempt. See
[Retry Thinking-Trace Analysis](../error-analysis/retry-thinking-trace-analysis.md)
for the failure taxonomy.