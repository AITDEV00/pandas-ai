# Detective Notes — Stability Investigation (5-Trial Run)

Investigation of the 5-trial stability run: `runs/20260813_104904_stability5_parallel`
(cache buster `stability-1786603744`, per-trial buster `:trialN`, fresh register per trial)

> **Verdict up front:** The 6 failures are **NOT a single fixed bug**. They are
> **LLM code-generation instability** (the model writes subtly wrong SQL/struct
> keys on some attempts), amplified by a **runaway self-review + retry loop**
> that does not converge. The >30s latencies come from the **same retry loop**
> burning 4–15 LLM regeneration calls, each 5–25s. One **schema typo** is a
> *compounding trap* that forces near-guaranteed failure on skills queries.

## Conversation IDs per trial
- T1: dc8d1163-9704-4fd6-baf7-0673dc5ae81e
- T2: e0de766d-1b5e-4443-a6d9-67101090777f
- T3: 438a056a-9e8e-49e3-8b5c-3ecf5f169db9
- T4: f489c191-a572-42c8-a599-ff5ec99eb4f4
- T5: 4b5a3834-df2f-49b8-85a3-04e35b3c8d64

## Stability Matrix (from summary.json)
`p`=pass, `f`=fail_500; time in seconds.

| Question | T1 | T2 | T3 | T4 | T5 |
|----------|-----|-----|-----|-----|-----|
| PROJECTS | p 61s | **f 24s** | **f 25s** | p 36s | **f 28s** |
| SKILLS | p 14s | **f 24s** | p 10s | p 38s | p 153s |
| ORGUNIT | **f 35s** | p 30s | p 14s | **f 48s** | p 54s |
| CHINESE_AI_AND | p 21s | p 26s | p 38s | **f 48s** | **f 79s** |
| CHINESE_AI_OR | p 62s | p 32s | p 165s | p 34s | p 33s |

**19/25 pass (76%).** No single question always fails; no question always passes
— pure **nondeterminism**. Timing varies 5x-15x for the SAME question.

---

## CORE MECHANISM: The Self-Review + Retry Loop

Every query flows through:
1. **Column selection** (Step 1) - 1 LLM call
2. **Code generation** (`generate_code_with_retries`, 1 + `max_retries=3` attempts)
3. **Structural self-review** (`_run_structural_self_review`) - raised inline in generation; on failure feeds a `ValueError` back to retry
4. **Code execution** (`execute_with_retries`, 1 + 3 attempts) - on failure regenerates code and loops

So a single query can make up to **4 (gen) x 4 (exec) = 16 LLM calls** when everything fails. Each call to DeepSeek-V4-Flash takes **5-25s**. **This is the primary driver of both slowness and failures.**

Observed attempt counts per failing/slow turn:

| Turn | gen | exec | LLM calls ~ |
|------|-----|------|------------|
| T2 PROJECTS (f) | 4 | 2 | ~6 |
| T3 ORGUNIT (f) | 5 | 3 | ~8 |
| T1 ORGUNIT (f) | 4 | 3 | ~7 |
| T5 CHINESE_AI_AND (f) | 6 | 8 | ~14 |
| T4 CHINESE_AI_AND (f) | 9 | 5 | ~14 |
| T3 CHINESE_AI_OR (p, 165s) | 9 | 6 | ~15 |
| T5 SKILLS (p, 153s) | 4 | 4 | ~8 |
| T4 PROJECTS (p, 36s) | 7 | 2 | ~9 |

**Rule of thumb:** every additional retry ~= +8-20s. Queries >60s are almost always 3+ retries deep.

---

## CASE-BY-CASE ANALYSIS

### Failure A: T1 ORGUNIT - 35.2s (dc8d1163 T3)
**Final error:** `No code found in the response`
**Sequence:** 6 self-review flags -> `ParserException: syntax error near "["` -> `No code found`

**Root cause - EXTRA BRACKET (LLM syntax error):**
```sql
rec['Employee Assignment History[Assignment Name]]'] AS assignment_name,
```
The model wrote a **double closing `]`** (`Name]]']`) instead of the correct single-close (`Name]']`). Correct field access is `rec['Employee Assignment History[Assignment Name]']`. The extra `]` corrupted the DuckDB parse (syntax error near `[`). On retry the model panicked and eventually produced no code.

### Failure B: T2 SKILLS - 23.8s (e0de766d T1)
**Final error:** `No code found in the response`
**Sequence:** 19 self-review events, output-type mismatch (dataframe vs string), `KeyError: match_type`

**Root cause 1 (primary):** The schema typo trap (see "Schema Typo Trap" below). The model wrote `Employee Competencies Rating[Competency Name]` (correct spelling) but schema field is **`Competancy Name`** (misspelled). Validator rejects the correct spelling as "not a valid schema field" -> the model keeps trying correct spelling, which can never pass.

**Root cause 2:** A `UNION` query with misaligned column lists -> `KeyError: Index(['match_type'])` when pandas `.concat`'d mismatched columns.

### Failure C: T3 PROJECTS - 24.9s (438a056a T1)
**Root cause:** model wrote struct key `CV Employee Job Experience[CV Responsibilities Summary]` - schema field is **`CV Employee Work Experience[CV Responsibilities Summary]`** (model dropped `Work ` and invented `Job `). Validator correctly rejects -> retry loop -> no convergence.

### Failure D: T4 ORGUNIT - 47.7s (f489c191 T3)
**Final error:** `Deterministic code self-review found:`
**Root cause:** a cascade: BinderException `Referenced column "[Employee Master[Number]]" not found` and `"[EmployeeMaster[Employee Number]]" not found` - the model **mangled the column name** (dropped brackets/spaces). Combined with extra-bracket bug and UNNEST issues. The self-review kept catching new errors on each attempt; model could not converge in 9 gen + 4 exec.

### Failure E: T5 PROJECTS - 28.5s (4b5a3834 T1)
**Root cause:** `BinderException: Referenced column "[Employee Master[Organization Unit]]" not found in FROM clause` - model selected a column that does not exist (ORGUNIT data lives in **`Employee Assignment History[Position Title]`**, not a master field). Also `Values list "e" does not have a column named "[Employee Objectives[...]]"` - a UNION/multi-UNNEST with mismatched columns. Model kept trying similar wrong queries.

### Failure F: T5 CHINESE_AI_AND - 78.9s (4b5a3834 T4)
**Root cause:** the longest failure. Sequence of distinct errors across 6 gen + 8 exec:
- `Duplicate alias "t"` - model used `AS t(rec)` for TWO different UNNESTs (alias collision)
- `Could not find key "cv employee achievements and awards[cv title]" in struct (Candidate Entries: t)` - **UNNEST alias nesting-level bug** (NOT a case-sensitivity issue; DuckDB struct lookup is case-INSENSITIVE, verified). The model accessed the struct as `rec['cv employee...']` against the OUTER alias `t`, but the destructured struct lives inside `t.rec['...']`. The lowercase in DuckDB's message is just normalisation (red herring). See retry-root-cause-analysis.md Finding 2.
- `ParserException: syntax error near "AS"` - the extra-bracket corruption
- 21 self-review events
This is a **chain of compounding SQL errors** the retry loop could not escape.

---

## CROSS-CUTTING ROOT CAUSES (the 4 real levers)

### 1. Schema typo trap: `Competancy Name` vs `Competency Name` (HIGHEST LEVERAGE)
The dataset/schema field is misspelled:
```
Employee Competencies Rating[Competancy Name]      <- schema (misspelled)
Employee Competencies Rating[Competency Name]      <- model writes (correct spelling!)
```
- The validator correctly rejects the correct spelling because it's not in the schema.
- **The model is "more correct" than the schema.** Every skills query is a coin-flip: if the model copies the misspelled key -> pass (fast); if it writes the correct spelling -> guaranteed failure via endless retry.
- **Evidence:** T3 SKILLS (PASS, 10s) used `Competancy` 118x; the slow T5 SKILLS (153s) and failing T2 SKILLS kept writing `Competency`.
- **Fix:** rename the schema + data column to the correct `Competency Name`. This single fix likely eliminates most SKILLS failures AND slowness.

### 2. Struct-field access syntax (extra closing bracket)
Model frequently writes `rec['Parent[Field]']` as `rec['Parent[Field]]']` (extra `]`). Root cause: the schema UNNEST column itself has a trailing `]` (e.g. `"[Employee Assignment History[...][...]]"`), and the model confuses the **column's** closing bracket with the **field accessor's** closing bracket.
- Causes `ParserException: syntax error near "["` / near `"AS"`.
- Appears in ORGUNIT and CHINESE_AI failures.

### 3. Struct-key hallucination / abbreviation (case & name)
The model invents or abbreviates struct field keys instead of copying exactly:
- `CV Employee Job Experience[CV Responsibilities Summary]` (invented "Job")
- `CV Employee Achievements and Awards[CV Description]` -> real is `[CV Achievement Description]`
- `Employee Achievements[Manager Comments]` -> real is `[Manager OA Comments]`
- UNNEST nesting-level access: reading `outer['key']` instead of `outer.inner['key']`/`inner['key']` when destructured `AS outer(inner)` (the real cause of the `Could not find key ... Candidate Entries: t` errors). DuckDB struct lookup is case-insensitive.
All rejected by the validator (correctly), feeding retries.

### 4. The retry loop does not guarantee convergence and is the latency amplifier
- `max_retries=3` allows up to ~16 LLM calls for a single query.
- The retry prompt only gets the **error text** back; the model re-generates fresh code that often contains a **different** error, so it can "wander" through 5-14 attempts.
- Even in PASSING cases, the loop burns time: 165s (T3 OR), 153s (T5 SKILLS), 61s (T1 PROJECTS).
- It cannot fix the schema typo (attempt 1) because the model keeps writing correct English.

---

## Recommendations (ranked by leverage)

1. **Fix the schema typo** `Competancy` -> `Competency` (semantic model + dataset). Eliminates the #1 guaranteed-failure trap and slashes SKILLS latency.
2. **Harden the validator** for the extra-bracket bug: when a flagged field's bracket-stripped core matches a valid key, auto-**correct** it in the cleaner instead of only rejecting it (the "UNBALANCED brackets" branch already finds `hint` - actually apply the fix).
3. **Cap the retry loop** and, when 2 consecutive attempts produce the **same** error class (e.g. two `BinderException` in a row), fall back to a simpler/known-good pattern instead of re-generating blindly.
4. **Case-insensitive struct-key matching** in DuckDB execution, or instruct the model to copy keys verbatim from the schema.
5. Reduce `max_retries` or add a time budget to bound worst-case latency (protect against the 165s outlier).
6. For `UNION`-generating queries, validate column-count/name alignment before execution (prevent `KeyError: match_type` / `Values list` / `Duplicate alias`).

---

## Notes on method
- Timing matrix and statuses are from `runs/.../summary.json` (authoritative HTTP results).
- Attempt counts and error sequences are from `run/conv_logs/<conv>.md` per CHAT TURN section.
- Error classes verified against `structural_validator.py`, `agent/base.py`, and the actual CSV column headers in `run/dev-env/dev-env.csv`.
