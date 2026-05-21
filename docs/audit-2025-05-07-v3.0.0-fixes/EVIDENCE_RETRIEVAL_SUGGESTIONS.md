# Column Selection — Adaptive Breadth Strategy

**Date:** 2025-05-20 (rev 5)  
**Context:** PandasAI v3.0.0 fork (chat-excel-server)  
**Scope:** Step 1 only — column selection with adaptive breadth  
**Status:** Simplified — retrieval mode classification removed

---

## 1. What This Strategy Does

The Step 1 LLM selects relevant columns from the schema based on the user question. The key insight is: **the LLM naturally decides column breadth based on question complexity** — no explicit mode classification needed.

- **Simple question** (e.g. "How many employees in HR?") → LLM selects few columns (just what's needed)
- **Complex question** (e.g. "What are the skills of employee 1137?") → LLM selects more columns (entity details + related context)
- **Compound question** (e.g. "Compare HR vs IT departments") → LLM selects generously (multiple entities, multiple attributes)

The prompt instructs the LLM to be **adaptive**: select more columns when the question implies breadth, fewer when it implies specificity.

---

## 2. Why No Retrieval Mode

Previous iterations used a 3-mode classification (direct/evidence/hybrid) to drive column selection breadth. This added complexity without proportional benefit:

1. **Mode classification was unreliable** — LLMs often disagree on boundary cases (e.g. "compare" → evidence or hybrid?)
2. **Column breadth is a continuum, not 3 buckets** — the LLM can naturally adjust selection without being forced into a mode
3. **The mode was used downstream in Step 2** but Step 2 already gets the trimmed DataFrame — it doesn't need a mode label to know what to do
4. **Removing modes simplifies the prompt** — less instruction = less confusion = more consistent column selection

The LLM's column selection IS the leniency decision. No separate classification step needed.

---

## 3. Implementation: Step 1 Column Selection

### 3.1 Architecture

```
User Query
  │
  ▼
Step 1: Column Selection (if wide table, LLM-based)
  │  LLM picks relevant columns from schema metadata
  │  Returns: {"selected": [...], "reasoning": "..."}
  │  DataFrame is trimmed to selected columns
  │
  ▼
Step 2: Code Generation (LLM-based)  ← NOT IN SCOPE
  │  ...
```

### 3.2 Step 1 Prompt — `select_columns.tmpl`

The prompt instructs the LLM to:

1. **Analyze the question** — understand what data the user needs
2. **Select columns adaptively** — more columns for broad/exploratory questions, fewer for specific/focused questions
3. **Include context columns** — when selecting entity details, always include identifying columns (name, ID) alongside the requested data
4. **Be generous when in doubt** — it's better to return more data than to miss relevant columns

**Column selection guidelines:**

- If the question asks about a **specific attribute** (e.g. "What is the salary of employee 1137?"), select the minimal columns needed
- If the question asks about **entity details** (e.g. "What are the skills of employee 1137?"), select the core columns PLUS related context columns (department, grade, etc.) that help the user understand the data
- If the question asks for a **comparison or list** (e.g. "Compare HR vs IT", "List all employees in finance"), be generous — include all potentially relevant columns
- **Always include identifying columns** (Employee Number, Employee Name) when selecting entity-specific data

**Response format:**
```json
{
  "selected": ["Column Name 1", "Column Name 2", "Struct Inner Field Name"],
  "reasoning": "brief explanation of why these columns are relevant and why this breadth was chosen"
}
```

### 3.3 Column Selector — `pandasai/core/column_selector.py`

The `ColumnSelector` class:

1. Builds the prompt with schema metadata (column names, types, descriptions, samples)
2. Calls the LLM
3. Parses the JSON response — extracts `selected` and `reasoning`
4. Validates column names (strip stray quotes, etc.)

```python
class ColumnSelector:
    def select(self, query: str) -> List[str]:
        prompt = self._build_prompt(query)
        response = self._state.config.llm.call(prompt, self._state)
        selected = self._parse_response(response)
        return self._validate_names(selected)
```

---

## 4. Why Adaptive Column Selection Works

### 4.1 The LLM Already Knows How to Be Adaptive

When you ask a human analyst "What columns do I need for this question?", they naturally:
- Select few columns for simple aggregation questions
- Select more columns for entity detail questions
- Select generously for exploratory/comparison questions

The LLM does the same thing when given clear guidelines. Explicit mode classification was forcing an unnecessary intermediate step.

### 4.2 Fewer Columns ≠ Simpler Code

Even with more columns, the Step 2 LLM has a manageable job because:
1. More columns just means a wider SELECT — the code logic doesn't change
2. The richer schema context actually HELPS the code generation LLM write correct SQL
3. Extra context columns (name, department) make the output more useful

### 4.3 The Virtuous Cycle

```
Broad/exploratory question
  → Step 1 selects MORE columns (adaptive)
  → Step 2 sees a RICHER schema
  → Step 2 writes code that returns complete data
  → User gets a MORE USEFUL answer
```

vs.

```
Specific/focused question
  → Step 1 selects FEWER columns (adaptive)
  → Step 2 sees a FOCUSED schema
  → Step 2 writes focused code
  → User gets a PRECISE answer
```

---

## 5. Testing Strategy

### 5.1 What We're Testing

For Part 1, we test ONLY the Step 1 column selection behavior:

1. **Column selection quality** — does the LLM select the right columns for each question?
2. **Adaptive breadth** — does the LLM select more columns for broad questions and fewer for specific ones?
3. **Context column inclusion** — does the LLM include identifying columns (name, ID) when appropriate?
4. **Struct field selection** — does the LLM correctly select inner fields of struct columns?

### 5.2 Test Method

The test follows the **exact same pipeline** the server uses:

1. Register the enterprise CSV file with semantic model
2. For each test question, call `ColumnSelector.select()` directly
3. Capture: selected columns, reasoning, raw LLM response

This is NOT a unit test with mocked LLM — it's a live LLM test that validates the full Step 1 pipeline end-to-end.

### 5.3 Test Questions

| # | Question | Breadth Expectation | Key Columns to Select |
|---|----------|---------------------|----------------------|
| 3b | "What are the main skills of employee 1137?" | Generous | Employee Number, Employee Name, CV Employee Competencies |
| 3 | Employee skills (detailed query) | Generous | Employee Number, Employee Name, CV Employee Competencies |
| 11 | "Give me the list of employees from human capital department" | Generous | Employee Name, Employee Number, Department, Grade |
| 12 | "Give me employees who speak chinese and have experience in AI" | Generous | Employee Name, Employee Number, CV Employee Competencies |
| 13a | "How many sick leaves did employee 1136 take in 2025?" | Moderate | Employee Number, Employee Leave Details |
| 15 | "What projects did Employee 982 work on compared to Employee 1177?" | Generous | Employee Number, Employee Name, project/assignment columns |
| 16 | "Which skills do they have in common?" | Generous | Employee Number, Employee Name, CV Employee Competencies |
| 19 | "Compare their education background." | Generous | Employee Number, Employee Name, education columns |
| 28 | "Average Salary of Senior Specialist in ADEO" | Moderate | Position Title, Salary columns |
| 35 | "Who has the longest service in ADEO?" | Moderate | Employee Name, Date of Joining, Years of Service |

### 5.4 Expected Behavior

For each question, the test checks:

1. **Selected columns** are non-empty
2. **Key columns** are present (substring match)
3. **Breadth is appropriate** — more columns for broad questions, fewer for focused ones
4. **Identifying columns** (Employee Number, Employee Name) are included when selecting entity-specific data

---

## 6. Current Implementation Status

| Component | Status | File |
|-----------|--------|------|
| `select_columns.tmpl` with adaptive breadth | ✅ Implemented | `pandasai/core/prompts/templates/select_columns.tmpl` |
| `ColumnSelector` with column selection | ✅ Implemented | `pandasai/core/column_selector.py` |
| Step 1 e2e test | 🔄 In progress | `tests/e2e/test_step1_column_selection.py` |

---

## 7. Key Design Decisions

### 7.1 No Mode Classification

The LLM's column selection IS the leniency decision. If it selects many columns, the question needs breadth. If it selects few, it doesn't. No separate mode label needed.

### 7.2 When in Doubt, Over-Select

It's safer to include an extra column than to miss a relevant one. Extra columns just add names to a SELECT statement; missing columns lose information permanently.

### 7.3 Context Columns Are Essential

When the user asks about an entity's attributes (e.g. "skills of employee 1137"), always include identifying columns (Employee Number, Employee Name) alongside the requested data. This makes the output self-explanatory.

### 7.4 Simpler Prompt = More Consistent Results

By removing the mode classification step, the prompt is shorter and more focused. The LLM has one job: select relevant columns. Less instruction means less room for confusion.
