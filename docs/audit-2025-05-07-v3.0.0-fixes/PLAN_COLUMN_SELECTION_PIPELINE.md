# Plan: Two-Step Column Selection Pipeline for Wide Tables

**Date:** 2025-05-07  
**Branch:** jya0-v3.0.0  
**Status:** Draft — Pending Implementation  
**Updated:** 2025-05-07 — Simplified: "Smart Removal" approach (trim a copy, not thread a filter)

---

## 1. Problem Statement

### Current Flow
```
User Query → Agent._process_query() → LLM sees ALL columns + ALL sample values → generates code
```

Every chat turn sends the **entire semantic layer** (all columns, all samples, all CSV rows) to the LLM. This works for ≤63 columns, but breaks at scale:

| Columns | Column Metadata | CSV Data (10 rows) | Memory (10 turns) | **Grand Total** |
|---------|----------------|--------------------|--------------------|-----------------|
| 63      | ~5,000 tok     | ~3,150 tok         | ~5,500 tok         | **~16,650 tok** |
| 100     | ~8,000 tok     | ~5,000 tok         | ~5,500 tok         | **~21,500 tok** |
| 200     | ~16,000 tok    | ~10,000 tok        | ~5,500 tok         | **~34,500 tok** |

With 200+ columns, each turn consumes 30K+ tokens — and memory of 10 turns adds 5.5K more. The LLM must parse all of this to write a SQL query that references maybe 3-5 columns. This is wasteful, slow, and error-prone.

### Root Cause
The LLM is forced to be a **column selector AND code generator** in one shot. For wide tables, the signal-to-noise ratio is terrible — the LLM must find 3 relevant columns among 200 irrelevant ones while also writing correct DuckDB SQL.

---

## 2. Proposed Solution: Two-Step Pipeline (Smart Removal)

### Core Insight

> The current data structure already works well. Don't change the pipeline — just make the object smaller before Step 2 sees it.

Instead of threading a `selected_columns` filter through the serializer, prompts, and agent, we simply:

1. **Step 1**: LLM returns a list of column names (flat or struct inner fields — doesn't matter)
2. **Match** those names to the schema using the existing `get_matching_schema_columns()` bracket convention
3. **Trim a copy** of the DataFrame + schema: keep only matched columns, trim struct inner-field samples to only matched fields
4. **Regenerate** sample rows from the trimmed DataFrame (just `df[kept_cols].head()`)
5. **Swap** `self._state.dfs` with the trimmed copy
6. **Step 2 runs completely unchanged** — it sees a smaller DataFrame/schema and works perfectly

### New Flow
```
User Query
  ↓
Step 1: Column Selection (cheap, fast, small context)
  - LLM sees ONLY: column names + types + descriptions + sample values (no CSV rows)
  - LLM returns: flat list of relevant column/field names + reasoning
  ↓
Smart Removal: Build trimmed DataFrame + schema copy
  - Match returned names → schema columns (flat columns → exact match, inner fields → bracket convention)
  - Create a shallow copy of the DataFrame with only matched columns
  - Create a deep copy of the schema with only matched columns + trimmed struct samples
  - Regenerate CSV sample rows from the trimmed DataFrame
  - Swap agent._state.dfs with the trimmed copy
  ↓
Step 2: Code Generation (UNCHANGED — just sees a smaller DataFrame)
  - Existing pipeline runs as-is: serialize, prompt, generate code, execute
  - The LLM sees only relevant columns with their full context
  ↓
Execute code → Return result
```

### Why This Is Simpler
- **Zero changes to DataframeSerializer** — no new parameters, no conditional filtering
- **Zero changes to prompt templates** — they already handle struct columns correctly
- **Zero changes to Step 2** — the existing code path works on the trimmed object
- **Struct inner fields are just names** — the LLM returns "Customary Name" and we match it to the parent struct column's inner field using existing bracket convention
- **Sample rows are regenerated** — `df[kept_cols].head()` gives us fresh CSV rows with only the kept columns
- **The original DataFrame is preserved** — we swap back after execution so the next query starts from the full DataFrame

---

## 3. Architecture Design

### 3.1 New Components

```
server/
  features/
    chat/
      handler.py              ← Modified: orchestrates 2-step pipeline
pandasai/
  core/
    column_selector.py         ← NEW: Step 1 — LLM column selection + smart removal
    prompts/
      templates/
        select_columns.tmpl    ← NEW: Step 1 prompt template
  agent/
    base.py                    ← Modified: _process_query() → 2-step when wide
  config.py                    ← Modified: new config fields
```

**What was REMOVED from the original plan:**
- ~~`column_filter.py`~~ — not needed, we trim the object itself
- ~~Changes to `dataframe_serializer.py`~~ — not needed, serializer works on the trimmed object
- ~~Changes to prompt templates (search_strategy, code_strategy)~~ — not needed, they work on the trimmed object
- ~~`selected_columns` parameter threading~~ — not needed

### 3.2 Config Additions

```python
# pandasai/config.py
class Config:
    # ... existing fields ...
    
    # Column selection pipeline
    column_selection_enabled: bool = False       # Toggle for 2-step pipeline
    column_selection_threshold: int = 30         # Auto-enable when cols >= this
    column_selection_memory_size: int = 5        # Memory turns for Step 1 (enough for follow-up column add/remove)
    auto_fill_descriptions: bool = False         # LLM fills missing column descriptions
```

### 3.3 HTTP API Additions

```python
# server/features/register/models.py

class PandasAIConfigPayload(BaseModel):
    # ... existing fields ...
    column_selection_enabled: bool = Field(False, description="Enable 2-step column selection for wide tables")
    column_selection_threshold: int = Field(30, description="Auto-enable column selection when column count >= this value")
    auto_fill_descriptions: bool = Field(False, description="Use LLM to fill missing column descriptions after enrichment")
```

---

## 4. Detailed Design

### 4.1 Step 0: Auto-Fill Missing Column Descriptions

**When:** During registration, after enrichment (step 2b in handler.py)  
**Why:** The column selection step relies heavily on column descriptions. If descriptions are missing or don't match the actual data, the LLM can't make good selections.

**Flow:**
```
After enrichment completes:
  1. Scan schema.columns for any with description=None or description==""
  2. If auto_fill_descriptions=True AND missing_count > 0:
     a. Build a lightweight prompt: column name + type + sample values → description
     b. Call LLM once with ALL missing columns in batch (not one-by-one)
     c. Parse response and back-fill schema column descriptions
  3. Save enriched schema to agent state
```

**Prompt template** (`auto_fill_descriptions.tmpl`):
```
You are a data catalog assistant. Given column names, types, and sample values, 
write a concise 1-sentence description for each column.

Columns needing descriptions:
{% for col in missing_columns %}
- name: {{ col.name }}, type: {{ col.type }}, samples: {{ col.samples }}
{% endfor %}

Respond in JSON format:
{"descriptions": {"column_name": "description", ...}}
```

**Important:** This is a ONE-TIME cost at registration time, not per-query. The descriptions are stored in the schema and reused for all subsequent queries.

### 4.2 Step 1: Column Selection

**When:** During `_process_query()`, BEFORE code generation  
**Trigger:** `column_selection_enabled=True` OR `len(columns) >= column_selection_threshold`

**Flow:**
```
1. Build column selection context:
   - For each column: name, type, description, semantic_type, samples
   - For struct columns: list inner fields with their types + samples
   - NO CSV rows, NO DuckDB syntax docs, NO code strategy
   - Include the user's query

2. Call LLM with select_columns.tmpl prompt + conversation history as proper messages
   - The LiteLLM.call() already sends memory.all() as {"role": "user/assistant"} messages
   - Step 1 creates a temporary Memory with `column_selection_memory_size` (default 5) turns
   - Follow-up questions that add/remove columns need enough history to understand context
   - The rendered prompt template is the final user message (same pattern as Step 2)

3. Parse response → flat list of column/field names

4. Match names to schema columns using existing `get_matching_schema_columns()`:
   - Flat column names → exact match + inner column match (Strategy 1+2)
   - Inner field names → inner column match + bracket convention (Strategy 2+3)
   - Squashed parent names → squashed parent match (Strategy 4)
   - See §4.3 for how we reuse the existing matching function

5. Run Smart Removal (§4.4) to build trimmed DataFrame + schema

6. Swap agent._state.dfs with trimmed copy
```

**Prompt template** (`select_columns.tmpl`):
```
You are a data analyst. Given a table schema and a user question, select ONLY the 
columns and struct inner fields needed to answer the question.

Table: {{ table_name }} ({{ total_columns }} columns)
Description: {{ table_description }}

**FLAT COLUMNS:**
{% for col in flat_columns %}
- "{{ col.name }}" ({{ col.type }}{% if col.description %}: {{ col.description }}{% endif %})
  {% if col.samples %}Values: {{ col.samples | truncate(100) }}{% endif %}
{% endfor %}

**STRUCT COLUMNS (each has inner fields you can select individually):**
{% for col in struct_columns %}
- "{{ col.name }}"{% if col.description %}: {{ col.description }}{% endif %} — inner fields:
{% for field_name, field_info in col.samples.items() %}
    → "{{ field_name }}" ({{ field_info.type }}{% if field_info.semantic_type %}, {{ field_info.semantic_type }}{% endif %})
{% endfor %}
{% endfor %}

User question: {{ query }}

Respond in JSON format:
{
  "selected": [
    "Employee Name",
    "Department",
    "Customary Name",
    "Calculated Rating",
    "Leave Balance"
  ],
  "reasoning": "brief explanation"
}
```

**Conversation history is NOT in the template** — it's handled by the LLM call mechanism. The existing `LiteLLM.call()` sends `memory.all()` as proper `{"role": "user/assistant", "content": ...}` messages before the final user prompt. Step 1 uses a temporary `Memory` object with `column_selection_memory_size` (default 5) turns, which gives enough context for follow-up questions that add or remove columns.

This is the same pattern as Step 2 — the template only contains the task-specific content, and conversation history is injected by the LLM layer.

**Key simplification:** The LLM returns a **flat list of names**, not a nested dict. Both flat column names and struct inner field names are just strings in the list. The matching logic (§4.3) resolves what each name refers to.

**Token cost estimate for Step 1 (200 columns, 30 struct):**
- Flat column metadata (name + type + description + samples): ~80 tok/col × 170 = ~13,600 tok
- Struct column metadata (name + description + inner fields): ~80 tok/col × 30 + ~8 tok/field × 150 fields = ~3,600 tok
- No CSV rows, no code strategy docs, no DuckDB syntax
- Query + template overhead: ~500 tok
- Memory (5 turns): ~2,750 tok
- **Total Step 1: ~20,450 tok**

### 4.3 Name Matching: Flat List → Schema Columns (Reusing Existing Matching)

The LLM returns names like `["Employee Name", "Customary Name", "Calculated Rating"]`. We need to resolve each name to:

1. A **top-level DataFrame column** (for flat columns and struct parent columns)
2. An **inner field** of a struct column (for struct inner fields)

**Key insight:** The existing `get_matching_schema_columns()` in `pandasai/helpers/semantic_matching.py` already handles ALL of these cases with 4 matching strategies:

| Strategy | What It Matches | Example |
|----------|----------------|---------|
| 1. Exact match | Schema column name exactly | `"Employee Name"` → `Employee Name` |
| 2. Inner column match | Name matches the innermost `[name]]` | `"Employee Name"` → `[Employee Master[Employee Name]]` |
| 3. Prefixed inner match | Bracket group is a substring | `"Employee Performance[Calculated Rating]"` → `[Employee Performance[Calculated Rating][...]]` |
| 4. Squashed parent match | Schema col is inner column of DataFrame col | `[Employee Achievements[Customary Name]]` is inner of `[Employee Achievements[Customary Name][Manager OA Comments]]` |

We **reuse** this function entirely instead of writing new matching code. The only new logic is grouping matched schema columns by their **parent DataFrame column name**:

```python
def match_names_to_schema(self, names: List[str], df) -> Dict[str, Optional[List[str]]]:
    """Match a flat list of column/field names to the schema.
    
    Reuses get_matching_schema_columns() for ALL matching — no redundant matching code.
    
    Returns dict mapping DataFrame column names to:
      - None (flat column, include all)
      - List of inner field names (struct column, include only these fields)
    
    Example:
      Input:  ["Employee Name", "Customary Name", "Calculated Rating", "Leave Balance"]
      Output: {
        "Employee Name": None,           # flat column
        "Employee Achievements": ["Customary Name", "Calculated Rating"],  # struct — matched inner fields
        "Leave Balance": None,           # struct — name matched the whole column
      }
    """
    from pandasai.helpers.semantic_matching import get_matching_schema_columns, _extract_short_name
    
    result = {}
    
    for name in names:
        # Use the EXISTING matching function — handles exact, inner, prefixed, squashed
        matches = get_matching_schema_columns(name, df.schema)
        
        if not matches:
            continue  # LLM returned an unrecognized name — skip silently
        
        for matched_col in matches:
            # Check if this is a squashed inner column (bracket convention)
            if matched_col.name.startswith("[") and "]" in matched_col.name:
                # Inner field of a struct column — extract parent + field name
                parent_name = self._extract_struct_parent(matched_col.name)
                field_name = _extract_short_name(matched_col.name)
                if parent_name:
                    if parent_name not in result:
                        result[parent_name] = []
                    if result[parent_name] is not None:
                        result[parent_name].append(field_name)
                else:
                    result[matched_col.name] = None
            else:
                # Flat column or whole struct column
                result[matched_col.name] = None
    
    return result

@staticmethod
def _extract_struct_parent(bracket_name: str) -> Optional[str]:
    """Extract the parent struct column name from a bracket convention name.
    
    Reuses the bracket convention already defined in semantic_matching.py.
    
    '[Employee Achievements[Customary Name]]' → 'Employee Achievements'
    'Employee Name' → None (not a bracket name)
    """
    if not bracket_name.startswith("["):
        return None
    # Remove outer brackets: '[Employee Achievements[Customary Name]]' → 'Employee Achievements[Customary Name]'
    inner = bracket_name[1:-1]
    # Find the first inner '[' — everything before it is the parent
    parent_end = inner.find("[")
    if parent_end > 0:
        return inner[:parent_end]
    return None
```

**Why this is better than writing new matching code:**
- `get_matching_schema_columns()` already handles exact match, inner column match (`[name]]`), prefixed inner match, and squashed parent match
- `_extract_short_name()` already extracts the innermost name from bracket convention
- We only add `_extract_struct_parent()` — a simple string parse that reuses the bracket convention
- No duplicated matching strategies, no risk of the two implementations diverging

**How it works for list[struct] inner fields:**

The LLM returns `"Customary Name"`. The existing `get_matching_schema_columns()` Strategy 2 matches it to the schema column `[Employee Achievements[Customary Name]]`. Then `_extract_struct_parent()` extracts `"Employee Achievements"` and `_extract_short_name()` extracts `"Customary Name"` → result: `{"Employee Achievements": ["Customary Name"]}`.

If the user also selected `"Calculated Rating"` → same process → merge: `{"Employee Achievements": ["Customary Name", "Calculated Rating"]}`.

### 4.4 Smart Removal: Build Trimmed DataFrame + Schema

This is the core of the simplified approach. Instead of threading a filter through the whole pipeline, we create a trimmed copy of the DataFrame and its schema, then swap it into `agent._state.dfs`.

```python
def _build_trimmed_dataframe(self, df, matched: Dict[str, Optional[List[str]]]):
    """Build a trimmed copy of the DataFrame with only selected columns and inner fields.
    
    Args:
        df: Original PandasAI DataFrame
        matched: Dict from match_names_to_schema()
            - {"flat_col": None} → keep this column fully
            - {"struct_col": ["field1", "field2"]} → keep column, trim inner field samples
            - {"struct_col": None} → keep column with all inner fields
    
    Returns:
        Trimmed DataFrame (shallow copy with trimmed schema)
    """
    # 1. Column-level filtering: keep only matched columns in the DataFrame
    kept_col_names = list(matched.keys())
    trimmed_df = df[kept_col_names]  # Shallow copy — shares underlying data
    
    # 2. Schema-level filtering: deep copy the schema and trim it
    if df.schema and df.schema.columns:
        trimmed_schema_columns = []
        for col in df.schema.columns:
            if col.name not in matched:
                continue  # Remove this column entirely
            
            inner_fields = matched[col.name]
            
            if inner_fields is None or col.type != "list[struct]":
                # Flat column or struct with all fields — keep as-is
                trimmed_schema_columns.append(col)
            else:
                # Struct column with specific inner fields — trim the samples dict
                trimmed_col = col.model_copy(deep=True)
                if isinstance(trimmed_col.samples, dict):
                    trimmed_col.samples = {
                        k: v for k, v in trimmed_col.samples.items()
                        if k in inner_fields
                    }
                trimmed_schema_columns.append(trimmed_col)
        
        # Replace the schema columns on the trimmed DataFrame
        trimmed_df.schema.columns = trimmed_schema_columns
    
    # 3. Sample rows are automatically regenerated by the serializer
    # When DataframeSerializer.serialize() runs on the trimmed DataFrame,
    # it calls df.head() on the trimmed columns → fresh CSV with only kept columns
    
    return trimmed_df
```

**Why this works:**

| Concern | How It's Handled |
|---------|-----------------|
| DataFrame has fewer columns | `df[kept_col_names]` creates a view with only selected columns |
| Schema has fewer columns | We filter `schema.columns` to only matched ones |
| Struct inner fields are trimmed | We deep-copy the Column and filter its `samples` dict |
| CSV sample rows are regenerated | Serializer calls `df.head()` on the trimmed DataFrame → automatically correct |
| search_strategy.tmpl categorizes correctly | It reads from the schema → only sees matched columns with trimmed samples |
| code_strategy.tmpl generates correct UNNEST | It reads from the schema → struct columns still have type "list[struct]" with relevant inner fields |
| Original DataFrame is preserved | We swap back after execution (try/finally) |
| DuckDB SQL still works | The trimmed DataFrame still has all the data for the kept columns. UNNEST still works because struct column data is intact — we only trimmed the schema metadata |

### 4.5 The Swap: Temporary DataFrame Replacement

```python
def _process_query(self, query: str, output_type: Optional[str] = None):
    """Process a query with optional 2-step column selection."""
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    # Step 1: Column Selection (if needed)
    original_dfs = None
    if self._should_select_columns():
        original_dfs = list(self._state.dfs)  # Save originals
        self._apply_column_selection(query)    # Swap in trimmed copies

    try:
        # Step 2: Code Generation + Execution (COMPLETELY UNCHANGED)
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)
        return result
    finally:
        # Always restore original DataFrames
        if original_dfs is not None:
            self._state.dfs = original_dfs
```

**Critical detail:** We swap back in the `finally` block so the original DataFrame is always restored, even if code generation or execution fails. This ensures:
- The next query starts from the full DataFrame
- Retry logic uses the trimmed DataFrame for the current query only
- No state leakage between queries

### 4.6 Memory Across the Two Steps

**Key insight:** Step 1 and Step 2 are part of the SAME user turn, not separate turns. The user asks one question, and internally we do two LLM calls. Memory should record ONE user message and ONE assistant response per turn.

**Implementation:**
```
Step 1 (Column Selection):
  - Does NOT add to memory (it's an internal operation, not a conversation turn)
  - Uses a SEPARATE, temporary LLM call with minimal context
  - The LLM call for Step 1 is isolated — it doesn't touch agent._state.memory

Step 2 (Code Generation):  
  - Adds user query to memory (same as current: memory.add(query, is_user=True))
  - Generates code using filtered context
  - After execution, response is added to memory (same as current)
```

**Memory size adjustment for wide tables:**
```
For wide tables (column_selection_enabled=True):
  - Reduce memory_size to 3-5 turns (from default 10)
  - Each turn's prompt already includes ~17K tokens of column metadata in Step 1
  - 10 turns of memory would add ~5.5K tokens on top of that
  - 3 turns = ~1.6K tokens of memory — much more sustainable
```

This can be configured via `column_selection_memory_size` in Config.

### 4.7 Proper Message History: Store User + Assistant Messages

**Current bug:** The agent only stores user messages in memory — it never stores the assistant's response. This means:

1. `LiteLLM.call()` sends `memory.all()` as message history, but there are NO assistant messages — just a sequence of user questions with no responses in between
2. The LLM sees disconnected questions like `"Show me employee names"` → `"Now show me their leave balance"` with no context about what code was generated or what happened
3. The LLM cannot reuse or adapt previously working code — it must regenerate from scratch every turn

**This is a pre-existing bug** that becomes critical with column selection because:
- Step 1 needs to understand what columns were previously selected (stored in the assistant message)
- Step 2 needs to see the previously working code to adapt it for follow-up questions
- Without assistant messages, the LLM has no idea what happened in previous turns beyond the raw question text

**Fix:** After each successful turn, store the formatted text response + working code as an assistant message — but **only when `output_type == "string"`** (or `"number"`):

```python
# In Agent._process_query():
def _process_query(self, query: str, output_type: Optional[str] = None):
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    # Step 0: Add user query to memory (BEFORE generate_code, which also adds it — see note below)
    # Currently: generate_code() calls memory.add(query, is_user=True)
    # We keep this — the user message is already being stored correctly

    try:
        # Step 1: Column Selection (if needed)
        original_dfs = None
        if self._should_select_columns():
            original_dfs = list(self._state.dfs)
            self._apply_column_selection(str(query))

        # Step 2: Code Generation + Execution
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)

        # ✅ NEW: Store assistant message in memory (text output only)
        self._store_assistant_message(result, output_type)

        return result
    except CodeExecutionError:
        # On failure, still store the attempted code if available
        if self._state.last_code_executed and output_type in ("string", "number"):
            self._state.memory.add(self._state.last_code_executed, is_user=False)
        return self._handle_exception(code)
    finally:
        if original_dfs is not None:
            self._state.dfs = original_dfs

def _store_assistant_message(self, result, output_type: Optional[str] = None):
    """Store the assistant's response in memory for multi-turn context.
    
    Stores for output_type "string" ("text") and "number" — these produce
    compact, useful context for the LLM on follow-up turns.
    
    Does NOT store for "dataframe", "plot", or "auto" — these types produce
    responses that are too large or not useful as LLM context.
    TODO: Implement storage for dataframe/plot/auto types later.
    """
    # Only store for types that produce compact, useful memory context
    if output_type not in ("string", "number"):
        # TODO: Implement storage for dataframe, plot, and auto types later.
        #   - dataframe: str(df) is huge and messy; need a compact summary
        #   - plot: just a file path; not useful without the image
        #   - auto: unpredictable type; need to check actual response type
        return
    
    # Build the assistant message from the two most valuable pieces of context:
    # 1. The formatted response (what the user saw)
    # 2. The working code that produced it (for code reuse on follow-ups)
    response_text = str(result) if result else ""
    working_code = self._state.last_code_executed or ""
    
    if response_text and working_code:
        assistant_msg = f"{response_text}\n\n---\nCode:\n{working_code}"
    elif working_code:
        assistant_msg = working_code
    else:
        return  # Nothing useful to store
    
    self._state.memory.add(assistant_msg, is_user=False)
```

**Why only `output_type` in `("string", "number")`:**

| Output Type | What `str(result)` Returns | Suitable for Memory? | Why |
|---|---|---|---|
| `"string"` (text) | Formatted text like `"Found 4 employee(s)..."` | ✅ Yes | Human-readable, compact, tells the LLM exactly what was answered |
| `"number"` | Just a number like `10` | ✅ Yes | Combined with the working code, the LLM knows the previous answer was a count of 10 — useful for follow-ups like "how many are male?" |
| `"dataframe"` | `str(df)` — raw DataFrame repr | ❌ No | Huge, messy, not useful as LLM context; may cause token overflow. TODO: implement later |
| `"plot"` / chart | File path string like `"/path/to/chart.png"` | ❌ No | Not useful — the LLM can't see the image from a file path. TODO: implement later |
| `"auto"` | Varies | ❌ No | Unpredictable — could be any of the above. TODO: implement later |

Storing non-string/number responses would bloat memory with useless content and could cause errors (e.g., trying to stringify a large DataFrame). The `output_type in ("string", "number")` guard ensures we only store clean, useful assistant messages.

**What the LLM sees with proper message history (3-turn example):**

```
messages = [
  {"role": "system", "content": "You are a data analyst..."},

  // Turn 1 (string output)
  {"role": "user", "content": "Show me employee names"},
  {"role": "assistant", "content": "Found 10 employee(s):\nName: Ahmed...\n---\nCode:\nresult = execute_sql_query(\"SELECT [Employee Name] FROM employees LIMIT 10\")"},

  // Turn 2 (number output — also stored)
  {"role": "user", "content": "How many are female?"},
  {"role": "assistant", "content": "10\n\n---\nCode:\nresult = {'type': 'number', 'value': int(df.iloc[0]['female_count'])}"},

  // Turn 3 (current — string output)
  {"role": "user", "content": [full rendered prompt with schema + CSV + code strategy]}
]
```

**Why number responses are useful in memory:** When the user asks "how many are male?" after "how many are female?", the LLM sees the previous answer was 10 (females) and the SQL that produced it. It can adapt the same query with `WHERE gender = 'Male'` — much faster than regenerating from scratch.

**Why storing BOTH the text response AND the working code is valuable:**

1. **Text response tells the LLM what was answered:** When the user asks "what about Zayed University?", the LLM sees the previous response listed 4 employees from Zayed University. On a follow-up like "how many of them are in IT?", the LLM knows exactly which employees were found and can filter further — no need to re-query

2. **Working code tells the LLM how to write the next query:** The LLM can see the exact `SELECT` + `UNNEST` syntax that worked and adapt it — just add `WHERE department = 'IT'` instead of regenerating from scratch. This is especially valuable for struct columns where UNNEST syntax is tricky

3. **Column selection context for Step 1:** Step 1 sees the previous code containing `SELECT [Employee Name], UNNEST([Leave Balance])` → knows those columns were previously selected. A follow-up like "also show department" means adding to the existing selection

4. **Error recovery:** If a previous code attempt failed and was retried, the LLM can see what was tried and avoid repeating the same mistake

5. **Consistent output formatting:** The LLM can see the exact formatting style used previously (e.g., `======` separators, `Name: ... Employee Number: ...` layout) and maintain consistency across turns

**Important: What NOT to store in memory:**

- ❌ The full rendered prompt (schema + CSV + strategy) — enormous and redundant with the current turn's prompt
- ❌ The LLM's raw response (includes reasoning, markdown, etc.) — only the extracted code + formatted text matter
- ❌ Step 1's column selection result — it's an internal operation, not a conversation turn
- ❌ Non-string/number responses (dataframe, plot, auto) — too large, not useful, or may cause errors. TODO: implement later
- ✅ Only the formatted response + final working code for string and number types — compact, informative, and reusable

**Token efficiency of the assistant message:**

- A typical string response: ~100-300 tokens (e.g., "Found 4 employee(s)..." with details)
- A typical number response: ~5-20 tokens (just the number, e.g., "10")
- A typical `execute_sql_query(...)` code block: ~50-100 tokens
- Separator + overhead: ~10 tokens
- **Total per turn (string): ~160-410 tokens**
- **Total per turn (number): ~65-130 tokens**
- With `memory_size=5`, 5 assistant messages = ~325-2,050 tokens (depending on mix)
- Compare to the full rendered prompt (~10K-35K tokens) — the assistant message is <2% of that
- This is a tiny cost for the massive benefit of conversation context + code reuse

**Interaction with column selection:**

When column selection is active, the stored code references columns that were in the trimmed DataFrame. On the next turn:
- Step 1 sees the previous code → knows which columns were used → can decide to add/remove columns
- Step 2 sees the previous code → can adapt it for the new query (e.g., add a column to the SELECT)
- The trimmed DataFrame for the new turn may have different columns than the previous turn — that's fine, the LLM is smart enough to adapt

**Note on `generate_code()` and memory:** Currently, `generate_code()` calls `memory.add(query, is_user=True)` internally. This means the user message is added BEFORE the LLM call. We keep this behavior — the assistant message is added AFTER successful execution. This ensures the message history is always in the correct order: user → assistant → user → assistant.

---

### 4.8 Output Type Mismatch Bug: No Enforcement of Requested Type

**Bug discovered:** When the user requests `output_type: "text"` (or even the correct PandasAI type `"string"`), the response comes back with `type: "number"`. The LLM ignores the output_type constraint and there is no runtime enforcement.

**Example (even with the correct "string" type):**
```json
// Request:
{"query": "how many are female", "output_type": "string"}

// Response (WRONG — should be type: "string"):
{"response": "10", "type": "number", "last_code_executed": "...result = {'type': 'number', 'value': count}"}
```

**Root cause:** Two compounding bugs:

#### Bug A (PRIMARY): No runtime enforcement of requested output_type

The `output_type_template.tmpl` correctly tells the LLM `type (must be "string")` when `output_type = "string"`. But the LLM frequently ignores this constraint — for a "how many" question, it decides `"number"` is more appropriate and generates `result = {'type': 'number', 'value': count}`.

There is **zero enforcement** after the LLM generates code:

1. `ResponseParser._generate_response()` creates the response type based **solely** on `result["type"]` from the executed code — it completely ignores the requested `output_type`
2. The handler's `actual_type = getattr(response, 'type', None)` returns whatever the code produced, not what was requested
3. There's no post-processing that converts a `NumberResponse` to a `StringResponse` when `output_type == "string"`
4. The `CorrectOutputTypeErrorPrompt` retry path exists but is only triggered on `InvalidLLMOutputType` exceptions — and the code executes successfully, so no error is raised

**The full broken flow (even with correct "string" type):**
```
User → output_type: "string"
  ↓
handler.py → passes output_type="string" to agent.chat()
  ↓
agent/base.py → stores self._state.output_type = "string"
  ↓
output_type_template.tmpl → renders "type (must be 'string')" ✅
  ↓
LLM → IGNORES constraint, generates {'type': 'number', 'value': count} ❌
  ↓
ResponseParser → creates NumberResponse(type="number") ← no enforcement
  ↓
handler.py → actual_type = response.type = "number" ← no enforcement
  ↓
API Response → {"type": "number", ...}  ❌ Should be "string"
```

#### Bug B (SECONDARY): Clients may send "text" but PandasAI uses "string"

The `output_type_template.tmpl` only recognizes `"string"`, `"number"`, `"dataframe"`, `"plot"` — not `"text"`. When a client sends `output_type = "text"` through the API, the server passes it through unvalidated, and NONE of the `elif` branches match, so the LLM receives **no output type constraint at all** (the template renders nothing for the type instruction).

This is a secondary issue because even with the correct `"string"` type, Bug A means the LLM can still ignore the constraint. But fixing Bug B is still important — when `output_type = "text"` is sent, the LLM doesn't even get the constraint in the first place.

#### Bug C (TERTIARY): ChartResponse reports type "chart" instead of "plot"

When the LLM generates `result = {"type": "plot", "value": "exports/charts/temp_chart_xxx.png"}`, the `ResponseParser._generate_response()` correctly matches `result["type"] == "plot"` and creates a `ChartResponse`. But `ChartResponse.__init__` hardcodes `self.type = "chart"`:

```python
# pandasai/core/response/chart.py
class ChartResponse(BaseResponse):
    def __init__(self, value: Any, last_code_executed: str):
        super().__init__(value, "chart", last_code_executed)  # ← "chart", NOT "plot"
```

This means:
- The handler reads `actual_type = getattr(response, 'type', None)` → `"chart"`
- The API response sends `{"type": "chart", ...}` instead of `{"type": "plot", ...}`
- The handler's enforcement check `if output_type and actual_type != output_type` would see `"chart" != "plot"` and try to coerce — **even when the LLM correctly generated type "plot"**
- The client receives an unexpected type value

**Impact on enforcement:** Any enforcement logic must account for this `"plot"` → `"chart"` mapping. The simplest fix is to normalize `actual_type` at the handler level: if `actual_type == "chart"`, treat it as `"plot"`.

#### Discovery: How Response Types Are Generated

The response type is **determined entirely by the LLM-generated code**. The full flow:

1. **Prompt instructs the LLM on result format** — `generate_python_code_with_sql.tmpl`:
   ```
   At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
   result = {"type": "<type>", "value": <value>}
   ```
   The `output_type_template.tmpl` conditionally constrains which type to use.

2. **LLM generates code** — The LLM decides the type. For example, for "how many are female?":
   ```python
   result = {"type": "number", "value": count}  # LLM chose "number"
   ```

3. **CodeCleaner processes the code** — `pandasai/core/code_generation/code_cleaning.py`:
   - `_replace_output_filenames_with_temp_chart()`: Replaces ALL `.png` paths with `exports/charts/temp_chart_{uuid}.png`
   - This means the LLM's `plt.savefig("temp_chart.png")` becomes `plt.savefig("exports/charts/temp_chart_<uuid>.png")`
   - The same replacement applies to `result = {"type": "plot", "value": "temp_chart.png"}` → `{"type": "plot", "value": "exports/charts/temp_chart_<uuid>.png"}`
   - Chart directory: `{project_root}/exports/charts/` (created by `Folder.create()` in `AgentState._configure()`)

4. **CodeExecutor runs the code** — `exec(code, env)` then extracts `env["result"]`

5. **ResponseParser creates the response** — Based **solely** on `result["type"]`:
   - `"number"` → `NumberResponse(type="number")`
   - `"string"` → `StringResponse(type="string")`
   - `"dataframe"` → `DataFrameResponse(type="dataframe")`
   - `"plot"` → `ChartResponse(type="chart")` ⚠️ **mismatch**
   - anything else → raises `InvalidOutputValueMismatch`

6. **Validation only checks value-type consistency** — `_validate_response()` checks that the value matches the declared type (e.g., `"number"` value is actually numeric), but does NOT check whether the type matches the requested `output_type`.

**Key finding:** The `CorrectOutputTypeErrorPrompt` correction path exists but is **dead code** — `InvalidLLMOutputType` is never raised anywhere in the codebase. The branch in `_regenerate_code_after_error()`:
```python
if isinstance(error, InvalidLLMOutputType):
    prompt = get_correct_output_type_error_prompt(...)
```
is never triggered because no code raises `InvalidLLMOutputType`. The exception class exists in `pandasai/exceptions.py` but is only used in tests.

**The existing correction template** — `correct_output_type_error_prompt.tmpl` — simply says:
```
The result type should be: {{output_type}}
```
This is much weaker than the improved `output_type_template.tmpl` we plan — it doesn't explain WHY the type matters or give counter-examples. It needs to be improved alongside the main template.

#### Fix 1: Validate output_type in the server handler — reject unsupported types

Instead of silently normalizing `"text"` → `"string"`, validate the output_type and reject any unsupported value with a clear error. This prevents silent misconfigurations and makes the API contract explicit:

```python
# In server/features/chat/handler.py

SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}

def _validate_output_type(output_type: Optional[str]) -> Optional[str]:
    """Validate output_type against PandasAI's supported types.
    
    PandasAI supports: "string", "number", "dataframe", "plot".
    "auto" means the LLM chooses the type freely (same as None/omitted).
    Any other value (including "text", "chart", "graph", etc.) is rejected
    with a clear error so the client knows exactly what's supported.
    
    Note: "text" is NOT a valid PandasAI type — use "string" instead.
    Note: "auto" lets the LLM decide the type — no enforcement is applied.
    """
    if output_type is None:
        return None  # No type requested — LLM chooses freely
    
    if output_type == "auto":
        return None  # "auto" = LLM chooses freely — normalize to None
    
    if output_type not in SUPPORTED_OUTPUT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported output_type: '{output_type}'. "
                   f"Supported types are: 'string', 'number', 'dataframe', 'plot', 'auto'. "
                   f"Hint: Use 'string' instead of 'text'."
        )
    
    return output_type

def handle_chat_query(conversation_id: str, query: str, output_type: str = None) -> dict:
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")
    
    # Validate output_type before passing to PandasAI
    output_type = _validate_output_type(output_type)
    # After validation:
    #   - output_type is None (client sent None or "auto") → LLM chooses freely, no enforcement
    #   - output_type is "string"/"number"/"dataframe"/"plot" → enforce this type
    
    try:
        if agent._state.memory.count() > 0:
            response = agent.follow_up(query, output_type=output_type)
        else:
            response = agent.chat(query, output_type=output_type)
        # ...
```

**Why validate instead of normalize?**

1. **Explicit > implicit**: Silently mapping `"text"` → `"string"` hides a client bug. The client should send the correct type.
2. **Fail fast**: A 400 error immediately tells the developer their API call is wrong, instead of silently changing behavior.
3. **Prevents future confusion**: If `"text"` were normalized, a developer might never realize they're using the wrong type. With a 400 error, they fix it once and never make the mistake again.
4. **API contract clarity**: The supported types are now documented and enforced. No guessing.
5. **Catches all invalid types**: Not just `"text"` — also catches typos like `"strng"`, `"num"`, `"chart"`, `"graph"`, etc.

**Why "auto" maps to None instead of being rejected?**

- `"auto"` is a common API convention meaning "let the system decide" — it's reasonable for clients to send it
- In PandasAI, `output_type=None` triggers `{% if not output_type %}` in the template, which renders "possible values..." (LLM chooses freely) — exactly the "auto" behavior
- Mapping `"auto"` → `None` at the validation boundary keeps the internal logic simple: `None` always means "no constraint"
- The enforcement logic (Fix 2 Part B + Fix 3) only activates when `output_type` is not None — so `"auto"` bypasses all enforcement, which is correct

**Common mistakes this catches:**

| Client sends | Current behavior | New behavior |
|---|---|---|
| `"text"` | Silently ignored by template → LLM chooses freely | **400 error**: "Use 'string' instead of 'text'" |
| `"chart"` | Same — no constraint | **400 error**: "Unsupported output_type: 'chart'" |
| `"auto"` | Same — no constraint | ✅ LLM chooses freely (same as `null`) |
| `"strng"` (typo) | Same — no constraint | **400 error**: "Unsupported output_type: 'strng'" |
| `"string"` | ✅ Works correctly | ✅ Works correctly |
| `null` / omitted | LLM chooses freely | LLM chooses freely (same as before) |

#### Fix 2: Prompt template improvements + handler-level enforcement

This fix has two parts: (a) improve the prompt template so the LLM better respects the requested type, and (b) enforce the type in the handler as a safety net.

##### Part A: Improve the output_type prompt template

The current `output_type_template.tmpl` just says `type (must be "string")` — a single line that's easy for the LLM to ignore. We need a stronger instruction that explains **why** the type matters and what to do when the query seems to suggest a different type:

```jinja2
{# In output_type_template.tmpl — improved version #}

{% if not output_type %}
type (possible values "string", "number", "dataframe", "plot"). Examples: { "type": "string", "value": f"The highest salary is {highest_salary}." } or { "type": "number", "value": 125 } or { "type": "dataframe", "value": pd.DataFrame({...}) } or { "type": "plot", "value": "temp_chart.png" }
{% elif output_type == "number" %}
type (must be "number"), value must be int or float. Example: { "type": "number", "value": 125 }
{% elif output_type == "string" %}
type (must be "string"), value must be a formatted string. Example: { "type": "string", "value": f"The highest salary is {highest_salary}." }

IMPORTANT: Even if the query seems to ask for a count or number, you MUST return type "string" with a descriptive text value. For example, if the query is "how many are female?", return: { "type": "string", "value": f"There are {count} female employees." } — NOT { "type": "number", "value": count }
{% elif output_type == "dataframe" %}
type (must be "dataframe"), value must be pd.DataFrame or pd.Series. Example: { "type": "dataframe", "value": pd.DataFrame({...}) }

IMPORTANT: Even if the query asks for a count or summary, you MUST return type "dataframe" with the data in a DataFrame. For example, if the query is "how many are female?", return the count in a DataFrame: { "type": "dataframe", "value": pd.DataFrame({"female_count": [count]}) } — NOT { "type": "number", "value": count }
{% elif output_type == "plot" %}
type (must be "plot"), value must be a string file path. Example: { "type": "plot", "value": "temp_chart.png" }

IMPORTANT: Even if the query asks for a number or text, you MUST return type "plot" and generate a chart. For example, if the query is "how many are female?", create a bar chart showing the count and return: { "type": "plot", "value": "temp_chart.png" } — NOT { "type": "number", "value": count }
{% endif %}
```

**Key improvements:**

1. **Explicit "IMPORTANT" constraint for each type**: Instead of just `type (must be "string")`, each type now has a clear instruction that says "Even if the query seems to ask for X, you MUST return type Y" with a concrete example
2. **Counter-example pattern**: Shows both what TO return and what NOT to return — this is more effective than just showing the correct example
3. **Covers the most common LLM mistake**: The LLM's most common error is returning `{"type": "number"}` for count queries regardless of the requested type. Each type now explicitly addresses this with "how many" as the example
4. **Type-specific reformulation guidance**: Tells the LLM exactly how to reformulate data to match the requested type:
   - `"string"` → wrap the number in a descriptive sentence
   - `"dataframe"` → put the data in a DataFrame
   - `"plot"` → generate a chart from the data

**Why this works better than just enforcement:**

- If the LLM generates the correct type from the start, there's no need for post-processing or coercion
- The LLM's code is cleaner — it directly produces the right format instead of producing the "wrong" format and being coerced later
- The working code stored in memory will also have the correct type, making follow-up turns more consistent

**⚠️ Coherence issue with `code_strategy.tmpl`:** The `code_strategy.tmpl` is included AFTER the `output_type_template.tmpl` in the main prompt and says "choose the most appropriate type for the user's question". This conflicts with the type constraint when a specific `output_type` is requested. The LLM might follow `code_strategy.tmpl`'s "choose" guidance over the constraint.

**Fix:** Update `code_strategy.tmpl` to conditionally respect the `output_type`:

```jinja2
{# In code_strategy.tmpl — updated section #}

**Result type selection:**
{% if output_type %}
You MUST use type "{{output_type}}" — this is non-negotiable. Do NOT choose a different type regardless of what the query seems to ask for. Reformulate the data as needed to match this type.
{% else %}
Choose the most appropriate type for the user's question:
- `"string"` → for natural language answers, summaries, comparisons
- `"number"` → for counts, averages, percentages
- `"dataframe"` → for tables/lists of data
- `"plot"` → for charts
{% endif %}
```

This ensures the `code_strategy.tmpl` reinforces the type constraint instead of contradicting it.

##### Part B: Handler-level enforcement (safety net)

Even with improved prompts, the LLM may occasionally ignore the constraint. The handler enforces the type as a safety net. This must handle three scenarios:

1. **Type matches** — no action needed
2. **Type mismatches but coercion is possible** — convert the response value
3. **Type mismatches and coercion fails or is nonsensical** — return a clear error message

```python
# In server/features/chat/handler.py, after getting the response:

actual_type = getattr(response, 'type', None) or output_type or "auto"

# ✅ NEW: Normalize ChartResponse.type = "chart" → "plot"
# Bug C: ChartResponse hardcodes type="chart" even though LLM generates type="plot"
# This is a handler-level workaround. The root cause should also be fixed in
# pandasai/core/response/chart.py: change super().__init__(value, "chart", ...) 
# to super().__init__(value, "plot", ...) so response.type is consistent.
if actual_type == "chart":
    actual_type = "plot"

# ✅ NEW: Enforce requested output_type when the LLM chose a different type
if output_type and actual_type != output_type:
    # The LLM ignored the type constraint — try to coerce the response
    coerced = _coerce_response_type(response, actual_type, output_type)
    if coerced is not None:
        response_value, actual_type = coerced
    else:
        # Coercion failed or is nonsensical — return a clear error message
        # instead of silently returning the wrong type
        return {
            "response": (
                f"Unable to produce the requested output type '{output_type}' for this query. "
                f"The query naturally produces a '{actual_type}' result. "
                f"Please adjust the output_type to '{actual_type}' or rephrase the query."
            ),
            "type": "error",
            "last_code_executed": getattr(response, 'last_code_executed', None),
        }
else:
    # Type matches or no type was requested — use the response as-is
    if actual_type == 'dataframe' and hasattr(response, 'value') and hasattr(response.value, 'to_dict'):
        response_value = response.value.to_dict(orient='records')
    elif actual_type == 'plot' and hasattr(response, 'value'):
        response_value = str(response.value)  # File path: "exports/charts/temp_chart_xxx.png"
    else:
        response_value = str(response) if response is not None else None
```

The `_coerce_response_type()` helper handles each coercion case:

```python
def _coerce_response_type(response, actual_type: str, requested_type: str):
    """Attempt to coerce a response from actual_type to requested_type.
    
    Returns (response_value, new_type) on success, or None if coercion
    is not possible or nonsensical.
    """
    # string ← number: "10" instead of 10
    if requested_type == "string" and actual_type == "number":
        return (str(response), "string")
    
    # string ← dataframe: use DataFrame's string summary
    if requested_type == "string" and actual_type == "dataframe":
        # ⚠️ Warning: str(df) can be enormous for large DataFrames.
        # Consider truncating to first N rows or using df.describe() instead.
        return (str(response), "string")
    
    # number ← string: try to extract the number
    if requested_type == "number" and actual_type == "string":
        try:
            return (float(str(response)), "number")
        except (ValueError, TypeError):
            return None  # Can't extract a number — coercion failed
    
    # ❌ All other mismatches are nonsensical — can't coerce:
    # - plot → string: chart already saved to disk, can't meaningfully convert
    # - string → plot: no chart was generated, can't create one from text
    # - number → plot: no chart was generated, can't create one from a number
    # - dataframe → plot: no chart was generated, can't create one from a DataFrame
    # - plot → number: chart file path is not a meaningful number
    # etc.
    return None
```

**Why return an error when coercion fails?**

Previously, the handler would silently return the LLM's type when coercion wasn't possible. This is wrong because:

1. **The API contract is broken**: The client asked for type X and received type Y. This is a bug from the client's perspective.
2. **Silent failures are worse than errors**: The client might process the wrong type and crash, or worse — silently produce incorrect results.
3. **An error message is actionable**: The client knows exactly what happened and can either change the `output_type` or rephrase the query.
4. **It prevents downstream confusion**: Without the error, the client might think the response is correct and use it incorrectly.

**Example error responses:**

```json
// Client requests "plot" but query is "what is the total salary?"
{
    "response": "Unable to produce the requested output type 'plot' for this query. The query naturally produces a 'number' result. Please adjust the output_type to 'number' or rephrase the query.",
    "type": "error",
    "last_code_executed": "..."
}

// Client requests "number" but query is "show me all employees"
{
    "response": "Unable to produce the requested output type 'number' for this query. The query naturally produces a 'dataframe' result. Please adjust the output_type to 'dataframe' or rephrase the query.",
    "type": "error",
    "last_code_executed": "..."
}
```

**Why both prompt improvements AND handler enforcement?**

- **Prompt improvements** (Part A) fix the root cause — the LLM generates the correct type from the start, so no coercion is needed. This means the stored working code also has the correct type.
- **Handler enforcement** (Part B) is a safety net for the rare cases the LLM still ignores the constraint. It ensures the API always returns the correct type, or a clear error if the type is fundamentally incompatible.
- Together they provide **defense in depth**: the prompt makes it very likely the LLM complies, and the handler guarantees it even if the LLM doesn't.

**⚠️ New `"error"` response type:** When coercion fails, the handler returns `{"type": "error", "response": "..."}`. This is a new response type not in the original `ChatResponse` model. Clients must handle this type — check `if response.type == "error"` and display the error message to the user instead of trying to process the response value. The `ChatResponse` model's `type: str` field already supports arbitrary strings, so no schema change is needed, but client code should be updated.

**Why enforce at the handler level instead of inside PandasAI?**

1. PandasAI's `ResponseParser` is a third-party library — modifying it would create a maintenance burden
2. The handler already has access to both the requested `output_type` and the actual response type
3. The enforcement is an API-level concern: "the user asked for X, ensure they get X"
4. This is a defensive layer that works regardless of whether the LLM complies with the prompt
5. The `str(response)` conversion is safe for all response types (all inherit `BaseResponse.__str__()` → `str(self.value)`)

#### Fix 3: Activate the correction prompt path for output_type mismatches

PandasAI already has a `CorrectOutputTypeErrorPrompt` and a retry mechanism in `_regenerate_code_after_error()`:

```python
# pandasai/agent/base.py — existing code (currently dead path)
def _regenerate_code_after_error(self, code: str, error: Exception) -> str:
    if isinstance(error, InvalidLLMOutputType):
        prompt = get_correct_output_type_error_prompt(
            self._state, code, error_trace
        )
    else:
        prompt = get_correct_error_prompt_for_sql(self._state, code, error_trace)
    return self._code_generator.generate_code(prompt)
```

The problem: `InvalidLLMOutputType` is **never raised** anywhere in the codebase — the branch is dead code. The `_validate_response()` method only validates the **structure** of the result (has "type" and "value" keys, value matches declared type) — it never checks whether the type matches the requested `output_type`.

**Fix:** Raise `InvalidLLMOutputType` in `ResponseParser._validate_response()` when the generated type doesn't match the requested type. This activates the existing correction path, giving the LLM a chance to fix its mistake before the handler falls back to coercion.

```python
# In pandasai/core/response/parser.py — add type mismatch check

class ResponseParser:
    def __init__(self):
        self._output_type = None  # Set before each parse() call via agent

    def parse(self, result: dict, last_code_executed: str = None) -> BaseResponse:
        self._validate_response(result)
        return self._generate_response(result, last_code_executed)

    def _validate_response(self, result: dict):
        # Existing structural validation (unchanged)
        if (
            not isinstance(result, dict)
            or "type" not in result
            or "value" not in result
        ):
            raise InvalidOutputValueMismatch(
                'Result must be in the format of dictionary of type and value like `result = {"type": ..., "value": ... }`'
            )
        
        # ✅ NEW: Check if the generated type matches the requested type
        # Only check when a specific type was requested (not "auto"/None)
        if self._output_type and result["type"] != self._output_type:
            raise InvalidLLMOutputType(
                f"Output type mismatch: requested '{self._output_type}' but generated '{result['type']}'. "
                f"The result type MUST be '{self._output_type}'. "
                f"Reformulate the data to match the requested type."
            )
        
        # Existing value-type validation (unchanged)
        elif result["type"] == "number":
            if not isinstance(result["value"], (int, float, np.int64)):
                raise InvalidOutputValueMismatch(...)
        # ... rest unchanged
```

**How to pass output_type to ResponseParser:**

Currently, `ResponseParser()` is instantiated once in `Agent.__init__()` with no args. We need to pass the output_type before each `parse()` call. The simplest approach — set it on the instance before calling parse in `execute_with_retries()`:

```python
# In pandasai/agent/base.py — execute_with_retries()

def execute_with_retries(self, code: str) -> Any:
    max_retries = self._state.config.max_retries
    attempts = 0

    while attempts <= max_retries:
        try:
            result = self.execute_code(code)
            self._state.last_code_executed = code
            # ✅ NEW: Pass output_type to ResponseParser before parsing
            self._response_parser._output_type = self._state.output_type
            return self._response_parser.parse(result, code)
        except Exception as e:
            # ... retry logic unchanged
```

This is minimal and doesn't require changing the `ResponseParser.__init__()` signature. The `output_type` is already stored in `self._state.output_type` (set by `_process_query()`), so we just need to pass it through.

**Why not change ResponseParser.__init__() to accept output_type?** Because the Agent creates `ResponseParser()` once in `__init__()` and reuses it across all queries. The output_type changes per query, so it must be set per-call, not per-instance. Adding `_output_type` as a mutable attribute set before `parse()` is the simplest approach.

**How this activates the correction path:**

1. `execute_with_retries()` calls `self._response_parser.parse(result, code)`
2. `_validate_response()` raises `InvalidLLMOutputType` because `result["type"] != self._output_type`
3. `execute_with_retries()` catches the exception and calls `_regenerate_code_after_error(code, e)`
4. Since `isinstance(error, InvalidLLMOutputType)` is `True`, it uses `CorrectOutputTypeErrorPrompt`
5. The LLM gets a second chance to generate code with the correct type
6. If the retry also fails (after `max_retries`), the exception propagates to the handler
7. The handler catches it and applies Part B enforcement (coercion or error message)

**The improved correction template:**

The existing `correct_output_type_error_prompt.tmpl` is too weak — its type-specific instruction is just `The result type should be: {{output_type}}` (the template also includes `duckdb_syntax.tmpl`, `sql_functions.tmpl`, `code_strategy.tmpl`, tables, and conversation history, but the output-type-specific guidance is minimal). We need to improve the type-specific section with the same counter-examples and reformulation guidance as the main template:

```jinja2
{# In correct_output_type_error_prompt.tmpl — improved version #}

{% include 'shared/duckdb_syntax.tmpl' with context %}

{% include 'shared/sql_functions.tmpl' with context %}

<result_format>
At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
result = {"type": "<type>", "value": <value>}

The result type MUST be: {{output_type}}

IMPORTANT: The previous code generated the WRONG output type. You MUST fix this.
{% if output_type == "string" %}
Do NOT return type "number". Even if the query asks "how many" or "what is the count", you MUST return type "string" with a descriptive text value. For example: result = {"type": "string", "value": f"There are {count} female employees."} — NOT result = {"type": "number", "value": count}
{% elif output_type == "number" %}
Do NOT return type "string". You MUST return type "number" with a numeric value. For example: result = {"type": "number", "value": count} — NOT result = {"type": "string", "value": f"The count is {count}"}
{% elif output_type == "dataframe" %}
Do NOT return type "number" or "string". You MUST return type "dataframe" with a DataFrame value. For example: result = {"type": "dataframe", "value": pd.DataFrame({"count": [count]})} — NOT result = {"type": "number", "value": count}
{% elif output_type == "plot" %}
Do NOT return type "number" or "string". You MUST return type "plot" with a chart file path. Generate a chart using matplotlib/plotly and return: result = {"type": "plot", "value": "temp_chart.png"} — NOT result = {"type": "number", "value": count}
{% endif %}
Do NOT use `return`. Do NOT name the variable anything else (not `result_dict`, `result_value`, `output`, etc.).
</result_format>

{% include 'shared/code_strategy.tmpl' with context %}

<tables>
{% for df in context.dfs %}{% set index = loop.index %}{% include 'shared/dataframe.tmpl' with context %}{% endfor %}
</tables>

The user asked the following question:
{{context.memory.get_conversation()}}

You generated the following Python code:
{{code}}

However, it resulted in the following error:
{{error}}

Fix the python code above and generate the new python code. Make sure the result type is exactly "{{output_type}}".
```

**Key improvements over the existing correction template:**

1. **Explicit "WRONG type" instruction**: Tells the LLM that the previous code generated the wrong type — it needs to fix it
2. **Same counter-example pattern as the main template**: Shows what NOT to return and what to return instead
3. **Type-specific reformulation guidance**: Same as the main template — tells the LLM exactly how to reformulate
4. **Repeats the output_type constraint at the end**: "Make sure the result type is exactly '{{output_type}}'" — reinforcement

**How the full defense-in-depth works:**

```
User → output_type: "string"
  ↓
1. Validate output_type → "string" is supported ✅ (Fix 1)
  ↓
2. Generate code → output_type_template.tmpl renders IMPORTANT constraint ✅ (Fix 2 Part A)
   code_strategy.tmpl reinforces "MUST use type 'string'" ✅ (Fix 2 Part A)
  ↓
3. LLM generates result = {"type": "number", "value": count} ❌
  ↓
4. ResponseParser._validate_response() raises InvalidLLMOutputType ✅ (Fix 3)
  ↓
5. execute_with_retries() catches it → _regenerate_code_after_error()
  ↓
6. CorrectOutputTypeErrorPrompt tells LLM to fix the type ✅ (Fix 3 improved template)
  ↓
7a. LLM fixes → result = {"type": "string", "value": f"There are {count} employees"} ✅
  ↓
  Response → {"type": "string", ...} ✅

7b. LLM still generates wrong type after max_retries → exception propagates
  ↓
8. Handler enforcement: coerce NumberResponse → "10" ✅ (Fix 2 Part B)
  ↓
  Response → {"type": "string", "response": "10"} ✅

7c. Coercion fails (e.g., plot → string) → error message ✅ (Fix 2 Part B)
  ↓
  Response → {"type": "error", "response": "Unable to produce type 'string'..."} ✅
```

**⚠️ Edge case: value-type mismatch (type is correct, value is wrong)**

If the LLM generates `result = {"type": "string", "value": 10}` (correct type "string", but value is a number instead of a string), the existing `_validate_response()` raises `InvalidOutputValueMismatch` — NOT `InvalidLLMOutputType`. This means the correction prompt would be the **generic** error prompt, not the output-type-specific one.

This is acceptable because:
1. The type IS correct — the LLM understood the type constraint
2. The value-type validation already catches this error
3. The generic error prompt will tell the LLM that `value` must be a string for type "string"
4. The handler's enforcement (Fix 2 Part B) would coerce `number → string` if needed

Future improvement: For `output_type in ("string", "number")`, we could also catch `InvalidOutputValueMismatch` and route it to the output-type-specific correction prompt, but this adds complexity for a rare edge case.

**Why activate the correction path instead of just relying on handler enforcement?**

1. **The LLM gets a second chance**: If the LLM just made a mistake, the correction prompt gives it a chance to fix it — the response will be higher quality than a coerced one
2. **The stored working code will be correct**: If the LLM fixes the type on retry, the code stored in memory will have the correct type, making follow-up turns more consistent
3. **Less coercion needed**: If the correction prompt works (which it should most of the time given the improved template), the handler rarely needs to coerce
4. **Better error messages**: If the LLM still fails after retries, the exception message tells the handler exactly what went wrong — it can provide a more specific error to the client

**Decision:** Implement all four: (1) validate output_type and reject unsupported types, (2) improve prompt template with explicit counter-examples and reformulation guidance, (3) enforce type in handler as safety net with error message for failed coercion, (4) activate the correction prompt path by raising `InvalidLLMOutputType` on type mismatch with improved correction template.

#### Note: "auto" type bypasses all enforcement

When `output_type` is `None` or `"auto"` (which maps to `None` in `_validate_output_type()`):

1. **No type constraint in the prompt**: `output_type_template.tmpl` renders `{% if not output_type %}` → "possible values..." (LLM chooses freely)
2. **No `InvalidLLMOutputType` raised**: `ResponseParser._validate_response()` only checks type mismatch when `self._output_type` is not None
3. **No handler enforcement**: The handler's `if output_type and actual_type != output_type` check is skipped when `output_type is None`
4. **No coercion or error**: Since there's no requested type, the LLM's choice is accepted as-is

This is correct behavior — "auto" means the client doesn't care about the type. The LLM should be free to choose the most appropriate type for the query.

**Important:** The handler still needs to normalize `ChartResponse.type = "chart"` → `"plot"` even for "auto" mode, because the API should consistently return `"plot"` (not `"chart"`) for chart responses regardless of whether the type was requested or auto-selected.

#### Note: Multi-output queries are NOT supported

PandasAI's result format is `result = {"type": "<type>", "value": <value>}` — a single type-value pair. There is no mechanism for a query to return multiple types simultaneously (e.g., text answer + chart + dataframe export).

If a user asks "show me the top 10 employees and also create a chart of their salaries", the LLM must choose ONE type:
- If `output_type = "dataframe"` → returns the table (no chart)
- If `output_type = "plot"` → returns the chart (no table)
- If `output_type = "auto"` → LLM chooses whichever it thinks is more appropriate
- If `output_type = "string"` → LLM must reformulate as text (e.g., "The top 10 employees are...")

**This is a fundamental limitation of the PandasAI result format.** Future work could extend the format to support multi-type responses (e.g., `result = [{"type": "string", "value": "..."}, {"type": "plot", "value": "..."}]`), but that would require changes across the entire pipeline (prompt, code generation, response parser, handler serialization).

**For now, the recommended approach for multi-output queries is:**
1. The client should make multiple API calls with different `output_type` values
2. Or use `output_type = "auto"` and let the LLM choose the single most appropriate type
3. Or use `output_type = "dataframe"` to get the raw data and let the client render charts/format text

---

## 5. Integration with Existing Code

### 5.1 Agent._process_query() Modification

```python
def _process_query(self, query: str, output_type: Optional[str] = None):
    """Process a query with optional 2-step column selection."""
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    # Step 1: Column Selection (if needed)
    original_dfs = None
    if self._should_select_columns():
        original_dfs = list(self._state.dfs)  # Save originals
        self._apply_column_selection(query)    # Swap in trimmed copies

    try:
        # Step 2: Code Generation + Execution (COMPLETELY UNCHANGED)
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)
        return result
    finally:
        # Always restore original DataFrames
        if original_dfs is not None:
            self._state.dfs = original_dfs

def _should_select_columns(self) -> bool:
    """Check if 2-step column selection should be used."""
    config = self._state.config
    if config.column_selection_enabled:
        return True
    total_cols = sum(len(df.columns) for df in self._state.dfs)
    if total_cols >= config.column_selection_threshold:
        return True
    return False

def _apply_column_selection(self, query: str):
    """Step 1: Select columns and swap in trimmed DataFrames."""
    from pandasai.core.column_selector import ColumnSelector
    selector = ColumnSelector(self._state)
    
    selected_names = selector.select(query)
    if not selected_names:
        return  # Fallback: keep all columns
    
    trimmed_dfs = []
    for df in self._state.dfs:
        matched = selector.match_names_to_schema(selected_names, df)
        if matched:
            matched = selector.ensure_essential_columns(matched, df, query)
            trimmed_df = self._build_trimmed_dataframe(df, matched)
            trimmed_dfs.append(trimmed_df)
        else:
            trimmed_dfs.append(df)
    
    self._state.dfs = trimmed_dfs

def _build_trimmed_dataframe(self, df, matched: Dict[str, Optional[List[str]]]):
    """Build trimmed copy of DataFrame with only selected columns/inner-fields."""
    # Column-level filtering
    kept_col_names = list(matched.keys())
    trimmed_df = df[kept_col_names]
    
    # Schema-level filtering
    if df.schema and df.schema.columns:
        trimmed_schema_columns = []
        for col in df.schema.columns:
            if col.name not in matched:
                continue
            inner_fields = matched[col.name]
            if inner_fields is None or col.type != "list[struct]":
                trimmed_schema_columns.append(col)
            else:
                trimmed_col = col.model_copy(deep=True)
                if isinstance(trimmed_col.samples, dict):
                    trimmed_col.samples = {
                        k: v for k, v in trimmed_col.samples.items()
                        if k in inner_fields
                    }
                trimmed_schema_columns.append(trimmed_col)
        trimmed_df.schema.columns = trimmed_schema_columns
    
    return trimmed_df
```

### 5.2 ColumnSelector Class (New)

```python
# pandasai/core/column_selector.py
from typing import Dict, List, Optional

class ColumnSelector:
    """Selects relevant columns (and struct inner fields) for a given query using LLM.
    
    The LLM returns a FLAT list of names — both flat column names and struct inner
    field names are just strings. The matching logic resolves what each name refers to.
    """
    
    def __init__(self, state: AgentState):
        self._state = state
    
    def select(self, query: str) -> List[str]:
        """Return flat list of column/field names relevant to the query.
        
        Example: ["Employee Name", "Customary Name", "Calculated Rating", "Leave Balance"]
        """
        prompt = self._build_prompt(query)
        response = self._state.config.llm.call(prompt, self._state)
        selected = self._parse_response(response)
        return self._validate_names(selected)
    
    def match_names_to_schema(self, names: List[str], df) -> Dict[str, Optional[List[str]]]:
        """Match flat list of names to schema columns.
        
        Reuses get_matching_schema_columns() for ALL matching — no redundant code.
        
        Returns dict:
        {
            "Employee Name": None,           # flat column
            "Employee Achievements": ["Customary Name", "Calculated Rating"],  # struct
            "Leave Balance": None,           # struct — all fields
        }
        """
        from pandasai.helpers.semantic_matching import get_matching_schema_columns, _extract_short_name
        
        schema_by_name = {col.name: col for col in df.schema.columns}
        result = {}
        
        for name in names:
            matches = get_matching_schema_columns(name, df.schema)
            if not matches:
                continue
            
            for matched_col in matches:
                if matched_col.name.startswith("[") and "]" in matched_col.name:
                    # Squashed inner column — extract parent struct + field name
                    parent = self._extract_struct_parent(matched_col.name)
                    field = _extract_short_name(matched_col.name)
                    if parent:
                        if parent not in result:
                            result[parent] = []
                        if result[parent] is not None:
                            result[parent].append(field)
                    else:
                        result[matched_col.name] = None
                else:
                    # Flat column or whole struct column
                    result[matched_col.name] = None
        
        return result
    
    def ensure_essential_columns(self, matched: Dict, df, query: str) -> Dict:
        """Always include ID, datetime, and query-mentioned columns/inner-fields."""
        for col in df.schema.columns:
            if col.name in matched:
                continue
            if col.semantic_type == "id_like":
                matched[col.name] = None
            elif col.name.lower() in query.lower():
                matched[col.name] = None
            elif col.type == "datetime":
                matched[col.name] = None
        
        # Also ensure essential inner fields for struct columns
        for col_name, inner_fields in matched.items():
            if inner_fields is None:
                continue
            schema_col = next((c for c in df.schema.columns if c.name == col_name), None)
            if not schema_col or schema_col.type != "list[struct]":
                continue
            essential = set(inner_fields)
            if isinstance(schema_col.samples, dict):
                for field_name, field_info in schema_col.samples.items():
                    if isinstance(field_info, dict):
                        if field_info.get("semantic_type") == "id_like":
                            essential.add(field_name)
                        if field_info.get("type") == "datetime":
                            essential.add(field_name)
                    if field_name.lower() in query.lower():
                        essential.add(field_name)
            matched[col_name] = list(essential)
        
        return matched
    
    def _build_prompt(self, query: str) -> BasePrompt:
        """Build the column selection prompt."""
        flat_columns = []
        struct_columns = []
        for df in self._state.dfs:
            for col in df.schema.columns:
                if col.type == "list[struct]":
                    struct_columns.append(col)
                else:
                    flat_columns.append(col)
        
        return SelectColumnsPrompt(
            context=self._state,
            query=query,
            flat_columns=flat_columns,
            struct_columns=struct_columns,
        )
    
    def _parse_response(self, response: str) -> List[str]:
        """Parse LLM response into flat list of names."""
        import json, re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            selected = data.get("selected", data.get("selected_columns", []))
            if isinstance(selected, list):
                return [str(s) for s in selected]
            if isinstance(selected, dict):
                # Legacy dict format: flatten into list
                names = []
                for k, v in selected.items():
                    names.append(k)
                    if isinstance(v, list):
                        names.extend(v)
                return names
        return []
    
    def _validate_names(self, names: List[str]) -> List[str]:
        """Basic validation — just remove obviously invalid entries."""
        return [n for n in names if n and len(n) > 0]
```

### 5.3 What Does NOT Change (for column selection only)

This is the key benefit of the Smart Removal approach. The following files are **completely untouched by the column selection pipeline** (§4.1–§4.6):

| File | Why No Change Needed |
|------|---------------------|
| `pandasai/helpers/dataframe_serializer.py` | Serializes the trimmed DataFrame as-is — fewer columns, smaller CSV |
| `pandasai/core/prompts/templates/shared/search_strategy.tmpl` | Reads from schema → only sees matched columns |
| `pandasai/core/prompts/templates/shared/dataframe.tmpl` | Reads from DataFrame → fewer columns in CSV rows |
| `pandasai/helpers/column_enrichment.py` | Already ran at registration time — no changes |
| `pandasai/helpers/semantic_matching.py` | Used during matching step — no changes |
| `server/features/register/handler.py` | Registration is unchanged — enrichment still runs fully |

**Note:** The following files ARE modified by the output type bug fixes (§4.7–§4.8), which are separate from column selection:
- `server/features/chat/handler.py` — adds `_validate_output_type()`, `_coerce_response_type()`, "chart" → "plot" normalization (§4.8 Fix 1, Fix 2 Part B)
- `pandasai/core/prompts/templates/shared/code_strategy.tmpl` — adds conditional `{% if output_type %}` block (§4.8 Fix 2 Part A)
- `pandasai/core/response/chart.py` — fixes `ChartResponse.type` from "chart" to "plot" (§4.8 Bug C root cause fix)
- `pandasai/core/response/parser.py` — adds `_output_type` attribute and raises `InvalidLLMOutputType` (§4.8 Fix 3)
- `pandasai/core/prompts/templates/shared/output_type_template.tmpl` — adds IMPORTANT blocks with counter-examples (§4.8 Fix 2 Part A)
- `pandasai/core/prompts/templates/correct_output_type_error_prompt.tmpl` — adds counter-examples (§4.8 Fix 3)

### 5.4 Register Handler: Auto-Fill Descriptions

```python
# In server/features/register/handler.py, after step 2b:

# --- 2c. Auto-fill missing column descriptions ---
if pandasai_config.auto_fill_descriptions and df.schema and df.schema.columns:
    from server.core.description_filler import fill_missing_descriptions
    fill_missing_descriptions(df, pandasai_config, llm_config)
```

```python
# server/core/description_filler.py

def fill_missing_descriptions(df, pandasai_config, llm_config):
    """Use LLM to fill missing column descriptions in the schema."""
    missing = [col for col in df.schema.columns if not col.description]
    if not missing:
        return
    
    prompt = AutoFillDescriptionsPrompt(missing_columns=missing)
    llm = _get_llm(llm_config)
    response = llm.call(prompt)
    descriptions = _parse_descriptions(response)
    for col in df.schema.columns:
        if col.name in descriptions:
            col.description = descriptions[col.name]
```

---

## 6. Token Budget Analysis

### 200-column dataset comparison (170 flat + 30 struct with 5 fields each)

| Metric | Current (1-step) | Proposed (2-step) | Savings |
|--------|------------------|--------------------|---------|
| Step 1 prompt | — | ~20,450 tok | — |
| Step 2 prompt (10 cols, 2 struct × 3 fields) | ~34,500 tok | ~9,800 tok | -24,700 tok |
| **Total per turn** | **~34,500 tok** | **~30,250 tok** | **-12%** |
| Code quality | LLM sees 200 cols + all inner fields | LLM sees 10 cols + 6 inner fields | **Much better** |
| SQL errors | Frequent (wrong column/field names) | Rare (only relevant columns/fields) | **Much better** |

### 63-column dataset (current production)

| Metric | Current (1-step) | Proposed (2-step) | Savings |
|--------|------------------|--------------------|---------|
| Step 1 prompt | — | ~10,500 tok | — |
| Step 2 prompt | ~16,650 tok | ~5,500 tok | -11,150 tok |
| **Total per turn** | **~16,650 tok** | **~16,000 tok** | **-4%** |

*For ≤30 columns, column selection is NOT triggered (threshold default). The 1-step pipeline continues as-is.*

---

## 7. Memory Strategy for Wide Tables

### Problem
With `memory_size=10` and 200 columns, each turn's Step 1 already uses ~17K tokens. If memory includes 10 turns of previous Q&A, that's another ~5.5K tokens.

### Pre-requisite: Proper Message History (§4.7)

The memory fix in §4.7 is **required** before the column selection pipeline works well. Without assistant messages in history:
- Step 1 can't see which columns were previously selected
- Step 2 can't adapt previously working code for follow-up questions
- The LLM sees a sequence of disconnected user questions instead of a real conversation

After §4.7 is implemented, each turn adds (when `output_type` is `"string"` or `"number"`):
- `memory.add(query, is_user=True)` — the user's question (~10-30 tokens)
- `memory.add(response_text + code, is_user=False)` — the formatted response + working code (~160-410 tokens for string, ~60-200 tokens for number)

With `memory_size=5`, that's 5 × (30 + 285) = ~1,575 tokens of history — still extremely cheap and very informative. Non-string/number turns (dataframe, plot, auto) only add the user message, no assistant message (TODO: implement later).

### Pre-requisite: Output Type Validation + Enforcement (§4.8)

The server must (1) validate `output_type` and reject unsupported types with 400 error (accepting `"auto"` → maps to `None`), (2) improve the `output_type_template.tmpl` prompt template with explicit counter-examples so the LLM respects the requested type, **and update `code_strategy.tmpl` to conditionally reinforce the type constraint** (currently it says "choose the most appropriate type" which contradicts the constraint), (3) enforce the type in the handler as a safety net (with error message for failed coercion, and normalize `ChartResponse.type = "chart"` → `"plot"`), and (4) activate the `CorrectOutputTypeErrorPrompt` correction path by raising `InvalidLLMOutputType` in `ResponseParser._validate_response()` when the generated type doesn't match the requested type (passing `output_type` to `ResponseParser` via `self._response_parser._output_type = self._state.output_type` before `parse()`), **with an improved correction template that includes the same counter-examples**. Enforcement only applies when a specific type is requested — `"auto"` / `None` bypasses all enforcement. Without these fixes:
- Unsupported types like `"text"` silently pass through, causing the prompt template to render no constraint
- Even with `output_type = "string"`, the LLM frequently ignores the constraint and returns a different type (e.g., "number" for count queries)
- There is no runtime enforcement — the response type is whatever the LLM's code produced
- `ChartResponse.type = "chart"` (not `"plot"`) causes false mismatches in enforcement
- The `CorrectOutputTypeErrorPrompt` retry path is dead code — `InvalidLLMOutputType` is never raised
- The `_store_assistant_message()` check for `output_type in ("string", "number")` would store the wrong type context

### Memory Configuration for Column Selection

Step 1 uses a temporary `Memory` object with `column_selection_memory_size` (default 5) turns — enough for follow-up questions that add or remove columns. Step 2 uses the full memory. Since Step 1 doesn't write to memory, this is safe.

**How it works:** The `LiteLLM.call()` method already sends `memory.all()` as proper `{"role": "user/assistant", "content": ...}` messages. Step 1 creates a temporary `Memory` with the same conversation history but a smaller `size` limit:

```python
def _build_step1_memory(self) -> Memory:
    """Create a temporary Memory for Step 1 with reduced size limit."""
    from pandasai.helpers.memory import Memory
    
    original = self._state.memory
    step1_memory = Memory(
        memory_size=self._state.config.column_selection_memory_size,  # default 5
        agent_description=original.agent_description,
    )
    # Copy all messages from original memory
    for msg in original.all():
        step1_memory.add(msg["message"], msg["is_user"])
    
    return step1_memory
```

When `LiteLLM.call(instruction, context)` runs, it reads `context.memory.all()` with the `memory.size` limit, so only the last 5 turns are included as message history. The assistant messages (working code from §4.7) give Step 1 crucial context about which columns were previously selected.

---

## 8. Fallback & Safety

### 8.1 When Column Selection Fails
If Step 1 returns invalid names, empty list, or unparsable JSON:
```python
def _apply_column_selection(self, query: str):
    try:
        selector = ColumnSelector(self._state)
        selected_names = selector.select(query)
        if not selected_names:
            self._state.logger.log("Column selection returned empty, using all columns")
            return  # Keep original DataFrames
        # ... build trimmed DataFrames ...
    except Exception as e:
        self._state.logger.log(f"Column selection failed: {e}, using all columns")
        return  # Keep original DataFrames
```

### 8.2 Always Include Key Columns
The `ensure_essential_columns()` method always includes:
- Primary key / ID columns (`semantic_type="id_like"`)
- Columns referenced in the user's query text (string matching)
- Time/date columns (often needed for filtering)
- For struct columns: ID-like and datetime inner fields

### 8.3 Column Selection Caching
If the user asks follow-up questions about the same topic, the column selection may not change. However, follow-ups can also **add or remove** columns (e.g., "now also show me their department"), so caching must be conservative:

```python
# In AgentState:
last_selected_names: Optional[List[str]] = None
last_query: Optional[str] = None

# In _apply_column_selection():
# Only reuse cached selection if the query is very similar (same topic)
# Otherwise, re-run selection — follow-ups may need different columns
if self._state.last_selected_names and self._is_similar_query(query, self._state.last_query):
    return self._state.last_selected_names
```

For now, caching is **disabled by default** — every query runs column selection fresh. This ensures follow-up questions that add new columns ("now show me X too") or remove columns ("just the names please") work correctly. Caching can be enabled later with a similarity threshold.

### 8.4 Original DataFrame Always Restored
The `try/finally` pattern in `_process_query()` ensures the original DataFrame is always restored, even if code generation or execution fails. This prevents state leakage between queries.

---

## 9. Implementation Order

### Phase 1: Foundation (No LLM changes yet)
1. Add config fields: `column_selection_enabled`, `column_selection_threshold`, `auto_fill_descriptions`
2. Add server payload fields matching the config
3. Add `_should_select_columns()` and `_apply_column_selection()` stubs to Agent

### Phase 2: Auto-Fill Descriptions (Registration time)
4. Create `server/core/description_filler.py`
5. Create `pandasai/core/prompts/templates/auto_fill_descriptions.tmpl`
6. Wire into register handler step 2c
7. Test with a dataset that has missing descriptions

### Phase 3: Column Selection (Query time)
8. Create `pandasai/core/column_selector.py` (ColumnSelector class)
9. Create `pandasai/core/prompts/templates/select_columns.tmpl`
10. Create `pandasai/core/prompts/select_columns.py` (prompt class)
11. Implement `match_names_to_schema()` with bracket convention
12. Implement `_build_trimmed_dataframe()` (smart removal)
13. Wire into `Agent._process_query()` with try/finally swap pattern
14. Add fallback logic and essential column protection

### Phase 4: Memory Fix + Optimization
15. **Fix output_type mismatch**: (a) Add `_validate_output_type()` in handler.py — reject unsupported types with 400 error; accept `"auto"` → map to `None` (LLM chooses freely); (b) Improve `output_type_template.tmpl` with IMPORTANT blocks + counter-examples + reformulation guidance; (c) Update `code_strategy.tmpl` to conditionally respect `output_type` (reinforce constraint instead of "choose"); (d) Add handler-level enforcement with `_coerce_response_type()` + error message for failed coercion; (e) Normalize `ChartResponse.type = "chart"` → `"plot"` in handler (workaround for Bug C); (e2) Fix `ChartResponse.__init__` root cause — change hardcoded `type="chart"` to `type="plot"` in `pandasai/core/response/chart.py`; (f) Activate `CorrectOutputTypeErrorPrompt` by raising `InvalidLLMOutputType` in `ResponseParser._validate_response()` when type doesn't match (only when `output_type` is not None); (g) Pass `output_type` to `ResponseParser` via `self._response_parser._output_type = self._state.output_type` before `parse()`; (h) Improve `correct_output_type_error_prompt.tmpl` with same counter-examples (§4.8)
16. **Fix message history**: Add `_store_assistant_message()` method that stores formatted response + working code as assistant message for `output_type in ("string", "number")`, with TODO comments for dataframe/plot/auto (§4.7)
17. Verify `LiteLLM.call()` now sends proper user/assistant message pairs in history
18. Add `_build_step1_memory()` method to ColumnSelector — creates temporary `Memory` with `column_selection_memory_size` (default 5) turns
19. Wire temporary memory into Step 1 LLM call (pass via context or override `context.memory`)
20. Test multi-turn conversations with follow-up column add/remove scenarios
21. Verify that Step 2 still uses full memory (Step 1 doesn't write to memory)
22. Test that the LLM can adapt previously working code on follow-up questions (e.g., "sort by department" should modify previous SELECT, not regenerate from scratch)
23. **Known limitation**: Multi-output queries (text + chart + df) are NOT supported — PandasAI's `result = {"type": ..., "value": ...}` format only supports a single type per query. Clients should make multiple API calls with different `output_type` values, or use `output_type = "auto"` and let the LLM choose the single most appropriate type.

### Phase 5: Caching & Polish
23. Add `last_selected_names` to `AgentState`
24. Implement column selection caching
25. Add logging/metrics for column selection hits/misses
26. Integration testing with 100+ column datasets

---

## 10. Open Questions

1. **Should Step 1 use the same LLM as Step 2?**  
   → Yes, for simplicity. But Step 1 could use a cheaper/smaller model since it's a simpler task. This is a future optimization.

2. **Should we serialize ALL columns in Step 1 or just names+descriptions?**  
   → Names + types + descriptions + samples. The samples are critical for the LLM to understand what a column contains (e.g., "status" could mean anything without seeing the values).

3. **What about multiple DataFrames?**  
   → Column selection works the same — just union all columns from all DataFrames in the prompt, then filter each DataFrame independently.

4. **Should auto-fill descriptions be a separate endpoint?**  
   → No, it should happen during registration as part of the enrichment pipeline. It's a one-time cost.

5. **How to handle the case where the user's query needs columns the LLM didn't select?**  
   → The code execution will fail (SQL error on missing column). The existing retry logic will catch this and regenerate. On the next attempt, the full DataFrame is restored (try/finally), so the retry sees all columns.

6. **Should we reduce `sample_head_size` for wide tables?**  
   → Yes. For 200 columns, even 10 rows × 200 cols = 2000 cells. With column selection, we only serialize 10 rows × 10 cols = 100 cells. But we could also reduce to 5 rows for extra savings.

7. **What if a struct column has 50+ inner fields?**  
   → Show field names + types but NOT samples in Step 1. This keeps Step 1 cheap while still giving the LLM enough info to select the right inner fields. Samples are only included in Step 2 via the trimmed schema.

8. **What if the user's query references an inner field by a different name?**  
   → The auto-fill descriptions feature (§5.4) helps — if inner fields have good descriptions, the LLM can match semantically. Without descriptions, we rely on the LLM's understanding of field names alone.

9. **Should Step 1 also select aggregation functions?**  
   → No. Step 1 is strictly about WHICH columns/inner-fields to include. The LLM in Step 2 decides HOW to use them.

10. **What about the DuckDB SQL execution — does it need the full DataFrame?**  
    → No. The trimmed DataFrame still has all the data for the kept columns. DuckDB only sees the registered DataFrames, and the registered DataFrame has the kept columns' data. The UNNEST still works because the struct column data is intact — we only trimmed the schema metadata, not the underlying pandas data.
