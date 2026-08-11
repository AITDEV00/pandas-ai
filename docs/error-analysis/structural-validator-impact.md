# Structural Validator — Impact Verification (Batch Re-run)

**Date:** 2026-08-11
**Setup:** Same 19 "retried questions" batch, run 1× each with cache-bypass,
with the new deterministic structural self-review validator wired into the
code-generation pipeline. Emission temperature **unchanged** (1.0).

## Headline result

| Metric | Baseline (pre-validator) | After (with validator) |
|--------|:---:|:---:|
| Questions needing ≥1 retry | 5/19 (R4, R6, R9, R10, R11) | **3/19** (R10, R11, +3 others) |
| R4 longest tenure (was 3 attempts) | 3 | **1** |
| R6 emp 1137 skills (was 2) | 2 | **1** |
| R9 emp 982/1177 skills (was 3) | 3 | **1** |
| R10 leadership (was 2) | 2 | **2** (NameError — different bug) |
| R11 projects (was 3) | 3 | **2** (NameError — different bug) |

The three previously-failing questions whose root cause was in the validator's
scope (schema/alias/placeholder errors) all dropped to **1 execution attempt**.

## Validator fired during this batch

`grep "Deterministic code self-review"` found activations on:

- **R4 (longest tenure)** — caught `Accessing df['tenure_years'] but the SQL
  query defines aliases: [department, division, employee_grade, ...]`. The
  generated code referenced a column that did not match the SQL aliases —
  an **alias-drift** bug that would have failed at runtime with a KeyError.
  The validator raised a precise message into the retry loop and the model
  fixed it; R4 finished successfully.
- **R5 (Chinese + AI skills)** — validator fired there too.

## Remaining retries (3 questions, 2 attempts each)

The validator does **not** catch variable *name* references that occur outside
of f-strings / `join` (they are only "assigned" later, or the reference is a
bare Name in a non-joined expression). Examples from the re-run:

- **R10 (leadership positions)**: `NameError: name 'leadership_keywords' is not
  defined`
- **R11 (projects)**: `NameError: name 'assignments_query' is not defined`

These are the same "plan-to-code variable-name mismatch" class as R4, but the
undefined variable appears in a **plain assignment/expression** (e.g.
`something = leadership_keywords`), which the current undefined-variable check
only detects inside f-strings and `str.join(...)` list arguments. It does not
(yet) flag a Name load used in a regular assignment RHS.

## Conclusion

- The deterministic validator **eliminated the schema-fabrication / alias-drift
  class of retries** (R4, R6, R9 all now 1 attempt).
- It also **prevented a latent runtime bug** on R4 by catching the bad alias
  before execution.
- R10/R11 retries remain because the undefined-variable check is scoped to
  f-strings and `join` lists; a variable used on the RHS of a normal assignment
  is not yet covered.

## Possible next step

Extend `_check_undefined_variables` to also flag `Name` loads appearing on the
right-hand side of assignments / as call arguments — not just inside
`JoinedStr` and `join(...)` list args — to close the R10/R11 gap. (Optional;
the current implementation already delivered the main win.)

## Files

- Validator: `pandasai/core/code_generation/structural_validator.py`
- Wired in: `pandasai/core/code_generation/base.py`
- Prompt: `pandasai/core/prompts/templates/shared/code_strategy.tmpl`
- Batch runner: `tests/e2e/run_all_retried.py`
- Per-question JSON: `run/e2e_reports/stability/*_1x.json`
- Batch summary: `run/e2e_reports/stability/all_retried_summary.json`