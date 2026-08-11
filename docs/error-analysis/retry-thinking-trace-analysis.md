# Retried Questions — Thinking Trace Root-Cause Analysis

**Date:** 2026-08-11
**Scope:** All 19 questions in the "retried questions" batch (`tests/e2e/run_all_retried.py`), run 1× each with cache-bypass. For each question that required >1 execution attempt, this report reads the per-attempt LLM thinking trace and the first-failed code to classify the root cause of the code-generation bug.

**Key distinction:** A question "did not execute in the first turn" = the generated code raised an error on **Execution Attempt 1** and needed a retry. The thinking trace captured *before* that failed attempt is the best signal for why the bug occurred.

---

## 1. Batch Result Summary

| # | Question | Exec attempts | Passed 1st try? | Root cause class |
|---|----------|:---:|:---:|---|
| R1 | leave explore + sick 1136 | 1 | ✅ | — |
| R2 | Human Capital Dept | 1 | ✅ | — |
| R3 | Senior Specialist sorted + salary | 1 | ✅ | — |
| R4 | **longest tenure** | **3** | ❌ | Code-emission / transcription |
| R5 | Chinese + AI skills | 1 | ✅ | — |
| R6 | **emp 1137 CV skills** | **2** | ❌ | SQL-alias ↔ python mismatch |
| R7 | EC and Committees | 1 | ✅ | — |
| R8 | Director General Strategic Affairs | 1 | ✅ | — |
| R9 | **emp 982/1177 skills** | **3** | ❌ | Missing UNNEST + wrong struct key |
| R10 | **leadership positions** | **2** | ❌ | pandas API misuse (compiled regex + case flag) |
| R11 | **projects 982/1177** | **3** | ❌ | Schema column-name fabrication |
| R12 | compare education 0982/1177 | 1 | ✅ | — |
| R13 | sick 1136 count | 1 | ✅ | — |
| Q13a/b/c, Q19, Q28, Q30 | (sick, edu, senior spec, leadership) | 1 | ✅ | — |

**Result:** 14/19 passed on the first execution attempt; **5/19 required at least one retry** (R4, R6, R9, R10, R11).

> Note: Many historical logs show `gen=4 exec=0`. Those are the **step1 column-selection** pipeline-test logs, not end-to-end executions. They are excluded from this e2e analysis (they represent a different phase — column selection only).

---

## 2. Per-Question Diagnosis

### R4 — longest tenure (exec=3)

**Thinking trace (attempt 1):** The reasoning is *thorough and correct*. It plans the SQL correctly, computes `Years of Service` as `(CURRENT_DATE - join_date)/365.25`, sorts desc, limits 20, and even plans the markdown table carefully. It explicitly names the variables it intends to use: `header_line`, `sep_line`.

**Failed code (attempt 1):**
```python
header_line = '| ' + ' | '.join(headers) + ' |'
sep_line = '|' + '---|' * len(headers)
rows = []
for _, row in df.iterrows():
    rows.append(f"| {row['Employee Name']} | ...")
table_str = '\n'.join([header, separator_line] + rows)   # ← BUG
```
**Error:** `NameError: name 'header' is not defined`

**Root cause:** The model *reasoned* with `header_line`/`sep_line` but *emitted* `header`/`separator_line` in the final line. The final assembly line was not present in the reasoning (the trace ends with "Let's code"), so the model "re-invented" the variable names at emission time and got them wrong. **This is a plan-to-code variable-name mismatch.**

**Retry (attempt 2):** The model correctly fixes the names, but then introduces a *new* transcription bug:
```python
rows.append(f"| ... ", f"{row['Grade']} | ...", f"{doj} | ...")  # 3 args
```
**Error:** `TypeError: list.append() takes exactly one argument (3 given)`
A single f-string was split into three positional arguments while editing.

---

### R6 — employee 1137 CV skills (exec=2)

**Thinking trace (attempt 1):** Reasonable. It plans the UNNEST correctly and uses `rec['CV Employee Competencies[Technical Competency Name]'] AS skill`.

**Failed code (attempt 1):**
```python
rec['CV Employee Competencies[Technical Competency Name]'] AS skill   # SQL alias
...
skills = [s for s in df['skill_name'].tolist() if s is not None]      # ← BUG
```
**Error:** `KeyError: 'skill_name'`

**Root cause:** The SQL **aliases the column `AS skill`**, but the pandas accessor uses `df['skill_name']`. The alias name in SQL and the key in Python do not match. The model invented `skill_name` downstream even though it defined `skill` upstream in the *same* code block. **SQL-alias ↔ Python-accessor mismatch.**

---

### R9 — employees 982/1177 skills (exec=3)

**Thinking trace (attempt 1):** Very thorough and *correct* — it plans `LEFT JOIN UNNEST(...) AS t(rec)` and `rec['...']` access for the competencies and ratings structs.

**Failed code (attempt 1):** Referenced the struct field *directly as a column* without `UNNEST`:
```sql
SELECT "[Employee Master[Employee Number]]", "CV Employee Competencies[Technical Competency Name]"
FROM enterprise_data ...
```
**Error:** `Binder Error: Referenced column "CV Employee Competencies[Technical Competency Name]" not found in FROM clause`

**Failed code (attempt 2):** Emitted the `UNNEST` but used a wrong inner struct key:
```sql
rec['employee competencies rating[competancy name]']   -- wrong case/name
```
**Error:** `Binder Error: Could not find key "employee competencies rating[competancy name]" in struct`

**Root cause:** Even though the reasoning described the correct UNNEST + key, the **emitted SQL omitted the `UNNEST`** (plan-to-code gap) and then, when retrying, used a **lowercase/distorted struct key** that doesn't exist (schema-name mismatch). The model knows *what* to do at the reasoning level but fails to translate it into correct DuckDB struct syntax at emission.

---

### R10 — leadership positions (exec=2)

**Thinking trace (attempt 1):** Plans an `ILIKE` / `regexp_matches` SQL approach for matching leadership titles and even reasons about grade-seniority ordering.

**Failed code (attempt 1):** Fell back to Python `str.contains` with a **compiled regex plus `case=False`**:
```python
lead_pattern = re.compile(r'(?i)(chairman|director|...)', re.IGNORECASE)
leaders['Position'].str.contains(lead_pattern, case=False, na=False)   # ← BUG
```
**Error:** `ValueError: cannot process flags argument with a compiled pattern`

**Root cause:** **pandas API misuse.** When passing a pre-compiled regex to `str.contains()`, `case=False` (which compiles flags again) conflicts. The reasoning had planned a SQL approach; the emitted code switched to pandas and misused the API. This is a **pandas regex API misuse**, not a reasoning error.

---

### R11 — projects for IDs 982 & 1177 (exec=3)

**Thinking trace (attempt 1):** The reasoning is *very thorough* about which struct sources represent "projects" (objectives, assignment history, CV work experience, achievements), and it correctly picks the 5-path expansion. It even verbally self-corrects about exact column names.

**Failed code (attempt 1):**
```python
assg.'EmployeeAssignment_History[Assignment_Name]'   -- fabricated nested name + wrong deref
ach[..] AS proj_name,   -- literal placeholder left in code!
```
**Error:** `Parser Error: syntax error at or near 'EmployeeAssignment_History[Assignment_Name]'`

**Failed code (attempt 2):** Now uses `assg['...']` correctly, but the UNNEST string contains a **hallucinated field**:
```sql
LEFT JOIN UNNEST("[Employee Assignment History[Assignment Name][Position Title][Employee Grade][Assignment Start Date][Employee Number][Assignment End Date][...]]")
--                                        ↑ [Employee Number] does NOT exist in the actual struct column
```
**Error:** `Binder Error: Referenced column "…[Employee Number]…" not found in FROM clause`

**Root cause:** **Schema column-name fabrication.** The model invented `[Employee Number]` as a struct field inside the `Employee Assignment History` column name; the real schema column does not contain it. Also it left literal `-- placeholder` / `ach[..]` in the first attempt (incomplete code emission). The struct column-name string must be copied *exactly*; any invented token breaks binding.

---

## 3. Root-Cause Taxonomy

Looking across the 5 retried questions and the thinking traces, the model's **reasoning/planning is consistently strong** — but the bugs all occur at the boundary between "plan" and "emitted code". The patterns cluster into **4 classes**:

| # | Class | Definition | Examples |
|---|-------|-----------|----------|
| **A** | **Plan→code variable/alias drift** | The reasoning names a variable/alias; the emitted code uses a different name. | R4 `header_line`→`header`, `sep_line`→`separator_line`; R6 `AS skill`→`df['skill_name']` |
| **B** | **Transcription / editing slips** | While fixing a bug, the model corrupts surrounding code (split args, leftover placeholders, wrong variable name carried over). | R4 append-3-args; R11 `ach[..]` placeholder; R11 `-- placeholder` comment |
| **C** | **Schema column/struct-name fabrication** | The model writes a struct column name / key that does not exist in the schema (hallucinates a field, wrong case, or references without `UNNEST`). | R11 hallucinated `[Employee Number]`; R9 wrong-case key `competancy name`; R9 no-UNNEST reference |
| **D** | **Library API misuse** | The code uses a valid-intent but wrong API signature / flags. | R10 `str.contains(compiled, case=False)` |

**Most important finding:** None of the 5 failures was caused by the model misunderstanding the *user's question* or the *data domain*. All were caused by **imprecise code emission** (names, aliases, schema strings, API flags). This is consistent with high-temperature code generation (`CODE_GENERATION_TEMPERATURE=1.0`).

---

## 4. Why These Happen (per thinking trace evidence)

1. **Plan is abstract, code is concrete.** The reasoning describes *intent* ("unnest the competencies, access `rec[...]`, alias to skill") but does not verbatim reproduce the exact SQL string. The moment the model *generates* the concrete string, it can hallucinate field names (Class C) or drift aliases (Class A). The single most important cue: **struct column names must be copied character-for-character from the schema**, and any invented inner field breaks DuckDB binding.

2. **Retries re-derive code from scratch.** On retry the model does not merely patch; it re-emits the whole block, re-introducing fresh transcription slips (R4 second bug, R11 second hallucination).

3. **Long f-string/table formatting is fragile.** Multi-line f-strings with many `{row[...]}` accesses invite variable-name and argument-splitting errors (R4).

---

## 5. Recommended mitigations (for a future PR)

| Fix | Targets |
|-----|---------|
| **Pin struct/column names to schema**: inject the exact candidate struct column strings into the prompt and instruct "copy the UNNEST column string verbatim; do not invent inner fields; verify case matches schema." | C |
| **Post-parse alias consistency check**: statically scan the generated code so every SQL alias is used consistently in the pandas accessor, and every f-string variable is defined. Fail-fast with a targeted message instead of a runtime `NameError`/`KeyError`. | A, B |
| **Reject placeholder tokens** in generated code (`-- placeholder`, `..`, `TODO`) before execution. | B |
| **Prefer SQL-side string ops** for keyword filters (ILIKE/regexp_matches) instead of pushing compiled-regex + case-flag combos into pandas. | D |
| **Lower emission temperature for retries** (or add a deterministic "self-review" step that replays the schema check before executing). | all |

---

## 6. File locations / how to reproduce

- Runner: `tests/e2e/run_all_retried.py`
- Conv logs: `run/conv_logs/*.md` — each contains `#### ❌/✅ Execution Attempt N` and `<details>LLM Thinking (this attempt)` right before it.
- Batch output: `/tmp/run_all_retried.log`; reports in `run/e2e_reports/stability/`.

**Key diagnostic reading:** For each retried question, read the thinking trace immediately **above** `❌ Execution Attempt 1`, then compare the emitted code against what the reasoning *said* it would do. Every bug above is a divergence between those two.