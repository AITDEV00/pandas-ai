# Solution Suggestions: Column Selection Pipeline & Bug Fixes

**Date:** 2025-05-08  
**Branch:** jya0-v3.0.0  
**Companion to:** `PLAN_COLUMN_SELECTION_PIPELINE.md`  
**Purpose:** Concrete, implementable solution for every issue identified in the plan document, with code snippets, test strategies, and risk assessments.

---

### Implementation Status Summary (Updated 2025-05-08)

| Issue | Status | Notes |
|-------|--------|-------|
| 1–6 | ⬜ Not started | Column selection pipeline (Phase 2–3) |
| 7 | 🟡 API updated | Memory API refactored (`size`→`memory_size`, `to_openai_messages_for_chat()`); `_build_step1_memory()` pending Phase 3 |
| 8 | ✅ Done | `_store_assistant_message()` implemented in `Agent._process_query()` |
| 9 | ✅ Done | All 3 layers: prompt improvements, runtime validation, handler coercion |
| 10 | ✅ Done | `_validate_output_type()` in handler.py |
| 11 | ✅ Done | Root cause fix (`ChartResponse.type="plot"`) + handler normalization |
| 12 | ✅ Done | `InvalidLLMOutputType` now raised in `ResponseParser._validate_response()` |
| 13 | ✅ Done | `code_strategy.tmpl` conditional `{% if output_type %}` block |
| 14 | 📝 Documented | Known limitation; workarounds documented |
| 15 | ⬜ Not started | Caching disabled by default; future work |
| 16 | ✅ Done | `_coerce_response_type()` + error response type |
| 17 | ✅ Done | DataFrame truncation in coercion (`.head()` + shape info) |
| 18 | 📝 Documented | Known limitation; future improvement noted |
| 19 | ✅ Done | Config fields added to `pandasai/config.py` |
| 20 | ✅ Done | All 10 open questions resolved |

**Dead code cleanup (Phase 5):** ✅ Complete — removed `BasePrompt.validate()`, `AbstractPrompt`, `LLM.is_pandasai_llm()`; fixed type annotations and f-strings.

---

## Table of Contents

1. [Issue 1: Wide Tables Overwhelm the LLM (§1–§3)](#issue-1-wide-tables-overwhelm-the-llm)
2. [Issue 2: Missing Column Descriptions (§4.1)](#issue-2-missing-column-descriptions)
3. [Issue 3: Column Selection Prompt Design (§4.2)](#issue-3-column-selection-prompt-design)
4. [Issue 4: Name Matching to Schema (§4.3)](#issue-4-name-matching-to-schema)
5. [Issue 5: Smart Removal — DataFrame + Schema Trimming (§4.4)](#issue-5-smart-removal--dataframe--schema-trimming)
6. [Issue 6: Temporary DataFrame Swap (§4.5)](#issue-6-temporary-dataframe-swap)
7. [Issue 7: Memory Across Two Steps (§4.6)](#issue-7-memory-across-two-steps)
8. [Issue 8: No Assistant Messages in History (§4.7)](#issue-8-no-assistant-messages-in-history)
9. [Issue 9: Output Type Mismatch — No Enforcement (§4.8 Bug A)](#issue-9-output-type-mismatch--no-enforcement)
10. [Issue 10: Clients Send Unsupported Types Like "text" (§4.8 Bug B)](#issue-10-clients-send-unsupported-types-like-text)
11. [Issue 11: ChartResponse.type = "chart" Instead of "plot" (§4.8 Bug C)](#issue-11-chartresponsetype--chart-instead-of-plot)
12. [Issue 12: Dead Correction Prompt Path (§4.8 Fix 3)](#issue-12-dead-correction-prompt-path)
13. [Issue 13: code_strategy.tmpl Contradicts Type Constraint (§4.8 Fix 2A)](#issue-13-code_strategytmpl-contradicts-type-constraint)
14. [Issue 14: Multi-Output Queries Not Supported (§4.8 Note)](#issue-14-multi-output-queries-not-supported)
15. [Issue 15: Column Selection Caching (§8.3)](#issue-15-column-selection-caching)
16. [Issue 16: New "error" Response Type (§4.8 Fix 2B)](#issue-16-new-error-response-type)
17. [Issue 17: DataFrame→String Coercion May Produce Enormous Output (§4.8 Fix 2B)](#issue-17-dataframestring-coercion-may-produce-enormous-output)
18. [Issue 18: Value-Type Mismatch Uses Wrong Correction Path (§4.8 Edge Case)](#issue-18-value-type-mismatch-uses-wrong-correction-path)
19. [Issue 19: Config Fields Don't Exist Yet (§3.2)](#issue-19-config-fields-dont-exist-yet)
20. [Issue 20: Open Questions Need Resolution (§10)](#issue-20-open-questions-need-resolution)

---

## Issue 1: Wide Tables Overwhelm the LLM

**Plan Reference:** §1 (Problem Statement), §2 (Proposed Solution), §3 (Architecture Design)

### Problem

Every chat turn sends the entire semantic layer (all columns, all samples, all CSV rows) to the LLM. With 200+ columns, each turn consumes 30K+ tokens. The LLM must find 3–5 relevant columns among 200 irrelevant ones while also writing correct DuckDB SQL. This is wasteful, slow, and error-prone.

### Solution: Two-Step Pipeline (Smart Removal)

The core insight: **don't change the pipeline — just make the object smaller before Step 2 sees it.**

**Step 1** (Column Selection): LLM sees only column names + types + descriptions + samples (no CSV rows, no SQL docs). Returns a flat list of relevant column/field names.

**Step 2** (Code Generation): Runs completely unchanged on a trimmed DataFrame/schema copy that contains only the selected columns.

### Implementation

#### File: `pandasai/core/column_selector.py` (NEW)

```python
"""Step 1: LLM-based column selection for wide tables.

The LLM returns a FLAT list of names — both flat column names and struct inner
field names are just strings. The matching logic resolves what each name refers to.
"""
from typing import Dict, List, Optional
from pandasai.agent.state import AgentState
from pandasai.core.prompts.base import BasePrompt


class ColumnSelector:
    def __init__(self, state: AgentState):
        self._state = state

    def select(self, query: str) -> List[str]:
        """Return flat list of column/field names relevant to the query."""
        prompt = self._build_prompt(query)
        response = self._state.config.llm.call(prompt, self._state)
        selected = self._parse_response(response)
        return self._validate_names(selected)

    def match_names_to_schema(
        self, names: List[str], df
    ) -> Dict[str, Optional[List[str]]]:
        """Match flat list of names to schema columns.

        Returns dict mapping DataFrame column names to:
          - None (flat column, include all)
          - List of inner field names (struct column, include only these fields)
        """
        from pandasai.helpers.semantic_matching import (
            get_matching_schema_columns,
            _extract_short_name,
        )

        result = {}

        for name in names:
            matches = get_matching_schema_columns(name, df.schema)
            if not matches:
                continue

            for matched_col in matches:
                if matched_col.name.startswith("[") and "]" in matched_col.name:
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
                    result[matched_col.name] = None

        return result

    def ensure_essential_columns(
        self, matched: Dict, df, query: str
    ) -> Dict:
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

        # Essential inner fields for struct columns
        for col_name, inner_fields in matched.items():
            if inner_fields is None:
                continue
            schema_col = next(
                (c for c in df.schema.columns if c.name == col_name), None
            )
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

        from pandasai.core.prompts.select_columns import SelectColumnsPrompt

        return SelectColumnsPrompt(
            context=self._state,
            query=query,
            flat_columns=flat_columns,
            struct_columns=struct_columns,
        )

    def _parse_response(self, response: str) -> List[str]:
        """Parse LLM response into flat list of names."""
        import json
        import re

        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            selected = data.get("selected", data.get("selected_columns", []))
            if isinstance(selected, list):
                return [str(s) for s in selected]
            if isinstance(selected, dict):
                names = []
                for k, v in selected.items():
                    names.append(k)
                    if isinstance(v, list):
                        names.extend(v)
                return names
        return []

    def _validate_names(self, names: List[str]) -> List[str]:
        """Basic validation — remove obviously invalid entries."""
        return [n for n in names if n and len(n) > 0]

    @staticmethod
    def _extract_struct_parent(bracket_name: str) -> Optional[str]:
        """Extract parent struct column name from bracket convention.

        '[Employee Achievements[Customary Name]]' → 'Employee Achievements'
        'Employee Name' → None
        """
        if not bracket_name.startswith("["):
            return None
        inner = bracket_name[1:-1]
        parent_end = inner.find("[")
        if parent_end > 0:
            return inner[:parent_end]
        return None
```

> **Note on LLM calls:** `self._state.config.llm.call(prompt, self._state)` now internally uses `self._state.memory.to_openai_messages_for_chat()` to construct the messages array (see Issue 7 update). For Step 1, the `_build_step1_memory()` method creates a temporary Memory with reduced `memory_size` so only the last N turns are included.

#### File: `pandasai/agent/base.py` (MODIFY — add to `_process_query()`)

```python
def _process_query(self, query: str, output_type: Optional[str] = None):
    """Process a query with optional 2-step column selection."""
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    # Step 1: Column Selection (if needed)
    original_dfs = None
    if self._should_select_columns():
        original_dfs = list(self._state.dfs)
        self._apply_column_selection(query)

    try:
        # Step 2: Code Generation + Execution (COMPLETELY UNCHANGED)
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)

        # Store assistant message for multi-turn context (see Issue 8)
        self._store_assistant_message(result, output_type)

        return result
    except CodeExecutionError:
        return self._handle_exception(code)
    finally:
        if original_dfs is not None:
            self._state.dfs = original_dfs

def _should_select_columns(self) -> bool:
    """Check if 2-step column selection should be used."""
    config = self._state.config
    if config.column_selection_enabled:
        return True
    total_cols = sum(len(df.columns) for df in self._state.dfs)
    return total_cols >= config.column_selection_threshold

def _apply_column_selection(self, query: str):
    """Step 1: Select columns and swap in trimmed DataFrames."""
    try:
        from pandasai.core.column_selector import ColumnSelector

        selector = ColumnSelector(self._state)
        selected_names = selector.select(query)
        if not selected_names:
            self._state.logger.log(
                "Column selection returned empty, using all columns"
            )
            return

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
    except Exception as e:
        self._state.logger.log(
            f"Column selection failed: {e}, using all columns"
        )
        return

def _build_trimmed_dataframe(self, df, matched: Dict[str, Optional[List[str]]]):
    """Build trimmed copy of DataFrame with only selected columns/inner-fields."""
    kept_col_names = list(matched.keys())
    trimmed_df = df[kept_col_names]

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
                        k: v
                        for k, v in trimmed_col.samples.items()
                        if k in inner_fields
                    }
                trimmed_schema_columns.append(trimmed_col)
        trimmed_df.schema.columns = trimmed_schema_columns

    return trimmed_df
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `ColumnSelector._parse_response()` | JSON parsing for valid, legacy, and malformed responses |
| Unit: `ColumnSelector._extract_struct_parent()` | Bracket convention parsing for `[Parent[Child]]` format |
| Unit: `ColumnSelector.match_names_to_schema()` | Flat names → schema column mapping with bracket convention |
| Unit: `Agent._build_trimmed_dataframe()` | DataFrame + schema trimming preserves data, filters correctly |
| Integration: 200-column dataset | End-to-end: Step 1 selects ~10 cols, Step 2 generates correct SQL |
| Integration: Follow-up query | Step 1 adds new columns, Step 2 adapts previous code |
| Regression: 30-column dataset | Column selection NOT triggered, existing pipeline unchanged |

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Step 1 selects wrong columns → Step 2 fails | `try/finally` restores original DataFrames; retry with full schema |
| Step 1 adds latency (extra LLM call) | Step 1 is cheap (~20K tokens vs ~35K for full prompt); saves tokens on Step 2 |
| LLM returns unparseable response | `_parse_response()` returns `[]` → fallback to all columns |
| Struct inner field names are ambiguous | `ensure_essential_columns()` adds critical fields; `get_matching_schema_columns()` handles multiple strategies |

---

## Issue 2: Missing Column Descriptions

**Plan Reference:** §4.1

### Problem

Column selection relies heavily on column descriptions. If descriptions are missing, the LLM can't make good selections. Many real-world datasets have sparse or missing descriptions.

### Solution: Auto-Fill at Registration Time

A one-time LLM call during registration that fills missing column descriptions. This is NOT per-query — it runs once and the descriptions are stored in the schema.

#### File: `server/core/description_filler.py` (NEW)

```python
"""Auto-fill missing column descriptions using LLM at registration time."""
import json
import re
from typing import List, Optional

from pandasai.data_loader.semantic_layer_schema import Column


def fill_missing_descriptions(df, pandasai_config, llm_config) -> None:
    """Use LLM to fill missing column descriptions in the schema.

    Modifies df.schema.columns in-place.
    """
    missing = [col for col in df.schema.columns if not col.description]
    if not missing:
        return

    from pandasai.core.prompts.auto_fill_descriptions import (
        AutoFillDescriptionsPrompt,
    )
    from server.core.llm_utils import _get_llm

    prompt = AutoFillDescriptionsPrompt(missing_columns=missing)
    llm = _get_llm(llm_config)
    response = llm.call(prompt)
    descriptions = _parse_descriptions(response)

    for col in df.schema.columns:
        if col.name in descriptions:
            col.description = descriptions[col.name]


def _parse_descriptions(response: str) -> dict:
    """Parse LLM response into {column_name: description} dict."""
    json_match = re.search(r"\{.*\}", response, re.DOTALL)
    if json_match:
        data = json.loads(json_match.group())
        return data.get("descriptions", {})
    return {}
```

#### File: `pandasai/core/prompts/templates/auto_fill_descriptions.tmpl` (NEW)

```
You are a data catalog assistant. Given column names, types, and sample values,
write a concise 1-sentence description for each column.

Columns needing descriptions:
{% for col in missing_columns %}
- name: "{{ col.name }}", type: {{ col.type }}{% if col.samples %}, samples: {{ col.samples | truncate(100) }}{% endif %}

{% endfor %}

Respond in JSON format:
{"descriptions": {"column_name": "description", ...}}
```

#### File: `server/features/register/handler.py` (MODIFY — add step 2c)

```python
# After step 2b (enrichment):

# --- 2c. Auto-fill missing column descriptions ---
if pandasai_config.auto_fill_descriptions and df.schema and df.schema.columns:
    from server.core.description_filler import fill_missing_descriptions
    fill_missing_descriptions(df, pandasai_config, llm_config)
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_parse_descriptions()` | Parses valid JSON, handles malformed responses |
| Integration: Dataset with 5 missing descriptions | All 5 descriptions filled, existing descriptions preserved |
| Integration: Dataset with no missing descriptions | Early return, no LLM call made |
| Edge: Description contains special characters | Parsed correctly, no encoding issues |

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| LLM generates inaccurate descriptions | Descriptions are hints, not constraints; wrong descriptions degrade selection but don't break it |
| LLM call fails at registration | Wrap in try/except; log warning; continue with empty descriptions |
| Cost: extra LLM call per registration | One-time cost; only runs when `auto_fill_descriptions=True`; only for columns missing descriptions |

---

## Issue 3: Column Selection Prompt Design

**Plan Reference:** §4.2

### Problem

Step 1 needs a purpose-built prompt that shows column metadata (name, type, description, samples) without CSV rows, SQL syntax docs, or code strategy.

### Solution: Dedicated `select_columns.tmpl` Template

#### File: `pandasai/core/prompts/templates/select_columns.tmpl` (NEW)

```
You are a data analyst. Given a table schema and a user question, select ONLY the
columns and struct inner fields needed to answer the question.

Table: {{ table_name }} ({{ total_columns }} columns)
{% if table_description %}Description: {{ table_description }}{% endif %}

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
    "Column Name 1",
    "Column Name 2",
    "Struct Inner Field Name"
  ],
  "reasoning": "brief explanation of why these columns are relevant"
}
```

#### File: `pandasai/core/prompts/select_columns.py` (NEW)

```python
"""Prompt class for the column selection step."""
from pandasai.core.prompts.base import BasePrompt


class SelectColumnsPrompt(BasePrompt):
    template_path = "select_columns.tmpl"

    def __init__(
        self,
        context,
        query: str,
        flat_columns: list,
        struct_columns: list,
        table_name: str = "data",
        table_description: str = "",
    ):
        total_columns = len(flat_columns) + len(struct_columns)
        super().__init__(
            context=context,
            query=query,
            flat_columns=flat_columns,
            struct_columns=struct_columns,
            table_name=table_name,
            table_description=table_description,
            total_columns=total_columns,
        )
```

### Key Design Decisions

1. **Flat list, not nested dict**: The LLM returns `["Employee Name", "Customary Name"]`, not `{"Employee Name": null, "Employee Achievements": ["Customary Name"]}`. Simpler for the LLM, and the matching logic resolves what each name refers to.

2. **No CSV rows**: Step 1 doesn't need data — it only needs metadata to decide which columns are relevant. This saves ~10K tokens.

3. **No SQL/code strategy**: Step 1 is strictly about WHICH columns, not HOW to use them. Step 2 handles that.

4. **Reasoning field**: The `reasoning` field helps with debugging and could be used for caching decisions later.

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `SelectColumnsPrompt` renders correctly | Template produces valid output with flat + struct columns |
| Unit: Template with no struct columns | Only flat columns section rendered |
| Integration: 200-column dataset | LLM returns ~5-15 column names for a specific query |

---

## Issue 4: Name Matching to Schema

**Plan Reference:** §4.3

### Problem

The LLM returns a flat list of names like `["Employee Name", "Customary Name"]`. We need to resolve each name to a top-level DataFrame column or an inner field of a struct column.

### Solution: Reuse `get_matching_schema_columns()` + New `_extract_struct_parent()`

The existing `get_matching_schema_columns()` in `pandasai/helpers/semantic_matching.py` already handles all four matching strategies (exact, inner column, prefixed inner, squashed parent). We only add `_extract_struct_parent()` to extract the parent struct name from bracket convention.

**No new matching code is written.** This prevents the two implementations from diverging.

> **Note on the correction prompt:** The agent's `_regenerate_code_after_error()` routes to
> `get_correct_output_type_error_prompt()` (a factory function defined in
> `pandasai/core/prompts/__init__.py`), which returns a `CorrectOutputTypeErrorPrompt`
> instance. The solution doc sometimes refers to this as "the correction prompt" or
> "`CorrectOutputTypeErrorPrompt`" — the actual call site uses the factory function.

### Implementation

See `ColumnSelector._extract_struct_parent()` and `ColumnSelector.match_names_to_schema()` in [Issue 1](#issue-1-wide-tables-overwhelm-the-llm).

### Critical Detail: Bracket Convention

The codebase uses **nested brackets** `[Parent[Child]]`, NOT dot notation `[Parent].Child`:

- ✅ Correct: `[Employee Achievements[Customary Name]]`
- ❌ Wrong: `[Employee Achievements].Customary Name`

The `_extract_struct_parent()` function parses the nested bracket convention:

```python
# '[Employee Achievements[Customary Name]]' → 'Employee Achievements'
inner = bracket_name[1:-1]           # 'Employee Achievements[Customary Name]'
parent_end = inner.find("[")         # position of first inner '['
return inner[:parent_end]            # 'Employee Achievements'
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_extract_struct_parent("[Employee Achievements[Customary Name]]")` | Returns `"Employee Achievements"` |
| Unit: `_extract_struct_parent("Employee Name")` | Returns `None` (not a bracket name) |
| Unit: `_extract_struct_parent("[Simple]")` | Returns `None` (no inner bracket) |
| Unit: `match_names_to_schema(["Employee Name"])` | Returns `{"Employee Name": None}` |
| Unit: `match_names_to_schema(["Customary Name"])` | Returns `{"Employee Achievements": ["Customary Name"]}` |
| Unit: `match_names_to_schema(["Customary Name", "Calculated Rating"])` | Returns `{"Employee Achievements": ["Customary Name", "Calculated Rating"]}` |
| Unit: `match_names_to_schema(["Unknown Column"])` | Returns `{}` (unrecognized name is skipped) |

---

## Issue 5: Smart Removal — DataFrame + Schema Trimming

**Plan Reference:** §4.4

### Problem

After selecting columns, we need to create a trimmed version of the DataFrame and its schema so Step 2 only sees the relevant columns.

### Solution: Shallow DataFrame Copy + Deep Schema Copy

```python
def _build_trimmed_dataframe(self, df, matched: Dict[str, Optional[List[str]]]):
    # 1. Column-level filtering (shallow copy — shares underlying data)
    kept_col_names = list(matched.keys())
    trimmed_df = df[kept_col_names]

    # 2. Schema-level filtering (deep copy — we modify the samples dict)
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

### Why This Works

| Concern | How It's Handled |
|---------|-----------------|
| DataFrame has fewer columns | `df[kept_col_names]` creates a view with only selected columns |
| Schema has fewer columns | We filter `schema.columns` to only matched ones |
| Struct inner fields are trimmed | We deep-copy the Column and filter its `samples` dict |
| CSV sample rows are regenerated | Serializer calls `df.head()` on the trimmed DataFrame → automatically correct |
| DuckDB SQL still works | Trimmed DataFrame still has all the data for kept columns; UNNEST works because struct column data is intact |

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: Trim flat columns only | DataFrame has only selected columns; schema matches |
| Unit: Trim struct column with specific inner fields | `samples` dict contains only selected inner fields |
| Unit: Struct column with `None` inner fields | All inner fields preserved (whole struct) |
| Unit: Column not in matched dict | Column removed from both DataFrame and schema |
| Integration: Full pipeline with trimmed DataFrame | Step 2 generates correct SQL on trimmed data |

---

## Issue 6: Temporary DataFrame Swap

**Plan Reference:** §4.5

### Problem

Step 2 runs on the trimmed DataFrame, but the original DataFrame must be restored after execution — even if execution fails.

### Solution: `try/finally` Pattern in `_process_query()`

```python
def _process_query(self, query: str, output_type: Optional[str] = None):
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    original_dfs = None
    if self._should_select_columns():
        original_dfs = list(self._state.dfs)
        self._apply_column_selection(query)

    try:
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)

        # Issue 8: Store assistant message for multi-turn context
        self._store_assistant_message(result, output_type)

        return result
    finally:
        if original_dfs is not None:
            self._state.dfs = original_dfs
```

> **Note:** The `_store_assistant_message()` call is now implemented (see Issue 8). The `try/finally` DataFrame swap pattern for column selection is the remaining piece not yet wired in.

### Critical Detail: `list(self._state.dfs)` Creates a Shallow Copy

We save `list(self._state.dfs)` — a new list containing the same DataFrame objects. When `_apply_column_selection()` replaces `self._state.dfs` with a new list of trimmed DataFrames, the `original_dfs` list still holds references to the original (untrimmed) DataFrames. The `finally` block restores the original list.

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: Successful execution | Original DataFrames restored after result |
| Unit: Code generation fails | Original DataFrames restored despite exception |
| Unit: Code execution fails | Original DataFrames restored despite exception |
| Unit: No column selection | `original_dfs` is None; `finally` block is a no-op |

---

## Issue 7: Memory Across Two Steps

**Plan Reference:** §4.6

### Problem

Step 1 and Step 2 are part of the SAME user turn, not separate turns. Memory should record ONE user message and ONE assistant response per turn. Step 1 must NOT write to memory.

### Solution: Step 1 Uses Temporary Memory; Step 2 Uses Full Memory

> **⚠️ Updated 2025-05-08:** The Memory API has been refactored since the original solution was written:
> - `memory.size` → `memory.memory_size` (renamed with proper property + setter)
> - The authoritative method for constructing LLM messages is now `memory.to_openai_messages_for_chat(num_turns)`, NOT `memory.all()` with a size limit
> - `Agent.set_message_history(num_turns)` is the public API for setting memory size (replaces `agent._state.memory._memory_size = ...`)
> - `LiteLLM.call()` and `BaseOpenAI.call()` now use `to_openai_messages_for_chat()` internally

```python
def _build_step1_memory(self) -> Memory:
    """Create a temporary Memory for Step 1 with reduced size limit."""
    from pandasai.helpers.memory import Memory

    original = self._state.memory
    step1_memory = Memory(
        memory_size=self._state.config.column_selection_memory_size,  # default 5
        agent_description=original.agent_description,
    )
    for msg in original.all():
        step1_memory.add(msg["message"], msg["is_user"])

    return step1_memory
```

Step 1 passes this temporary memory to the LLM call via the context. The LLM caller now uses `context.memory.to_openai_messages_for_chat()` (which reads `memory.memory_size`) instead of the old `context.memory.all()` with `memory.size` limit. So only the last 5 turns are included. Step 2 continues using the full memory.

**Key API differences from original solution:**

| Old API | New API | Notes |
|---------|---------|-------|
| `memory.size` | `memory.memory_size` | Renamed property with getter + setter |
| `memory.all()[:memory.size]` | `memory.to_openai_messages_for_chat(num_turns)` | Authoritative method; handles rounding, system prompt, dangling messages |
| `agent._state.memory._memory_size = N` | `agent.set_message_history(N)` | Public API; properly encapsulated |
| LLM reads `memory.all()` | LLM reads `to_openai_messages_for_chat()` | Called internally by LiteLLM and BaseOpenAI |

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_build_step1_memory()` | Creates Memory with correct `memory_size` and copied messages |
| Integration: Step 1 doesn't write to memory | After Step 1, `self._state.memory.count()` is unchanged |
| Integration: Step 2 uses full memory | Step 2's LLM call includes all memory messages via `to_openai_messages_for_chat()` |

---

## Issue 8: No Assistant Messages in History

**Plan Reference:** §4.7
**Status:** ✅ IMPLEMENTED

### Problem

The agent only stores user messages in memory — never the assistant's response. This means:
1. `LiteLLM.call()` sends a sequence of user questions with no responses in between
2. The LLM sees disconnected questions instead of a conversation
3. The LLM cannot reuse or adapt previously working code

### Solution: Store Assistant Message After Successful Execution

```python
def _store_assistant_message(self, result, output_type: Optional[str] = None):
    """Store the assistant's response in memory for multi-turn context.

    Stores for output_type "string" and "number" — these produce
    compact, useful context for the LLM on follow-up turns.

    Does NOT store for "dataframe", "plot", or "auto" — these types produce
    responses that are too large or not useful as LLM context.
    TODO: Implement storage for dataframe/plot/auto types later.
    """
    if output_type not in ("string", "number"):
        return

    response_text = str(result) if result else ""
    working_code = self._state.last_code_executed or ""

    if response_text and working_code:
        assistant_msg = f"{response_text}\n\n---\nCode:\n{working_code}"
    elif working_code:
        assistant_msg = working_code
    else:
        return

    self._state.memory.add(assistant_msg, is_user=False)
```

### Implementation Notes (2025-05-08)

The solution above is **fully implemented** in `pandasai/agent/base.py`:

- `_store_assistant_message()` is called in `_process_query()` after successful execution
- It stores assistant messages for `output_type in ("string", "number")` — exactly as designed
- The assistant message format is `"{response_text}\n\n---\nCode:\n{working_code}"`
- `to_openai_messages_for_chat()` now correctly produces alternating user/assistant message pairs
- The handler calls `agent.set_message_history(message_history)` to configure memory size via the public API

**Where to call it in `_process_query()`:**

```python
def _process_query(self, query: str, output_type: Optional[str] = None):
    self._state.output_type = output_type
    self._state.assign_prompt_id()

    # Step 1: Column Selection (if needed) — see Issue 1
    original_dfs = None
    if self._should_select_columns():
        original_dfs = list(self._state.dfs)
        self._apply_column_selection(query)

    try:
        code = self.generate_code_with_retries(str(query))
        result = self.execute_with_retries(code)

        # Store assistant message for multi-turn context
        self._store_assistant_message(result, output_type)

        return result
    except CodeExecutionError:
        return self._handle_exception(code)
    finally:
        if original_dfs is not None:
            self._state.dfs = original_dfs
```

### Why Only `("string", "number")`

| Output Type | `str(result)` | Suitable for Memory? | Why |
|---|---|---|---|
| `"string"` | Formatted text like `"Found 4 employee(s)..."` | ✅ Yes | Compact, human-readable |
| `"number"` | Just a number like `10` | ✅ Yes | Combined with code, tells the LLM the previous answer |
| `"dataframe"` | `str(df)` — raw DataFrame repr | ❌ No | Huge, messy, may cause token overflow |
| `"plot"` | File path like `"/path/to/chart.png"` | ❌ No | Not useful without the image |
| `"auto"` | Varies | ❌ No | Unpredictable type |

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_store_assistant_message()` with string output | Message stored with response text + code |
| Unit: `_store_assistant_message()` with number output | Message stored with number + code |
| Unit: `_store_assistant_message()` with dataframe output | No message stored |
| Unit: `_store_assistant_message()` with None output_type | No message stored |
| Integration: 3-turn conversation | Memory contains user/assistant pairs for string/number turns |

---

## Issue 9: Output Type Mismatch — No Enforcement

**Plan Reference:** §4.8 Bug A
**Status:** ✅ IMPLEMENTED (all 3 layers)

### Problem

When the user requests `output_type: "string"`, the LLM frequently ignores the constraint and returns `{"type": "number", "value": count}`. There is zero enforcement after the LLM generates code:

1. `ResponseParser._generate_response()` creates the response based solely on `result["type"]` — ignores requested `output_type`
2. The handler returns whatever type the code produced
3. The `CorrectOutputTypeErrorPrompt` retry path is dead code — `InvalidLLMOutputType` is never raised

### Solution: Three-Layer Defense-in-Depth

**Layer 1 — Better Prompts** (Fix 2 Part A): Improve `output_type_template.tmpl` with IMPORTANT blocks + counter-examples. Update `code_strategy.tmpl` to conditionally reinforce the type constraint.

**Layer 2 — Runtime Validation** (Fix 3): Raise `InvalidLLMOutputType` in `ResponseParser._validate_response()` when the generated type doesn't match the requested type. This activates the existing correction prompt path, giving the LLM a second chance.

**Layer 3 — Handler Enforcement** (Fix 2 Part B): As a safety net, coerce the response type in the handler. If coercion fails, return a clear error message.

### Implementation

#### Layer 1: `pandasai/core/prompts/templates/shared/output_type_template.tmpl` (MODIFY)

```jinja2
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

#### Layer 1: `pandasai/core/prompts/templates/shared/code_strategy.tmpl` (MODIFY)

Add conditional type selection section:

```jinja2
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

#### Layer 2: `pandasai/core/response/parser.py` (MODIFY)

```python
class ResponseParser:
    def __init__(self):
        self._output_type = None  # Set before each parse() call

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
                'Result must be in the format of dictionary of type and value like '
                '`result = {"type": ..., "value": ... }`'
            )

        # NEW: Check if generated type matches requested type
        if self._output_type and result["type"] != self._output_type:
            raise InvalidLLMOutputType(
                f"Output type mismatch: requested '{self._output_type}' "
                f"but generated '{result['type']}'. "
                f"The result type MUST be '{self._output_type}'. "
                f"Reformulate the data to match the requested type."
            )

        # Existing value-type validation (unchanged)
        elif result["type"] == "number":
            if not isinstance(result["value"], (int, float, np.int64)):
                raise InvalidOutputValueMismatch(...)
        # ... rest unchanged
```

#### Layer 2: `pandasai/agent/base.py` (MODIFY — in `execute_with_retries()`)

```python
def execute_with_retries(self, code: str) -> Any:
    max_retries = self._state.config.max_retries
    attempts = 0

    while attempts <= max_retries:
        try:
            result = self.execute_code(code)
            self._state.last_code_executed = code
            # NEW: Pass output_type to ResponseParser before parsing
            self._response_parser._output_type = self._state.output_type
            return self._response_parser.parse(result, code)
        except Exception as e:
            # ... existing retry logic unchanged
```

#### Layer 3: `server/features/chat/handler.py` (MODIFY)

See [Issue 10](#issue-10-clients-send-unsupported-types-like-text) for `_validate_output_type()` and [Issue 11](#issue-11-chartresponsetype--chart-instead-of-plot) for "chart" → "plot" normalization. The handler enforcement with `_coerce_response_type()` is detailed in [Issue 16](#issue-16-new-error-response-type).

### Implementation Notes (2025-05-08)

All three layers are implemented:

- **Layer 1 (Better Prompts):** `output_type_template.tmpl` has IMPORTANT blocks with counter-examples for each type. `code_strategy.tmpl` has conditional `{% if output_type %}` block that says "You MUST use type" when constrained.
- **Layer 2 (Runtime Validation):** `ResponseParser._output_type` attribute is set before `parse()` in `execute_with_retries()`. `_validate_response()` raises `InvalidLLMOutputType` on type mismatch, which activates the correction prompt path.
- **Layer 3 (Handler Enforcement):** `_coerce_response_type()` in handler.py attempts type coercion. If it fails, returns `{"type": "error", ...}` response.
- **Correction template:** `correct_output_type_error_prompt.tmpl` has IMPORTANT blocks with counter-examples.

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `output_type_template.tmpl` renders IMPORTANT blocks | Template contains counter-examples when `output_type` is set |
| Unit: `code_strategy.tmpl` renders conditional | "MUST use type" when output_type is set; "choose" when None |
| Unit: `ResponseParser._validate_response()` raises `InvalidLLMOutputType` | When `result["type"] != self._output_type` |
| Unit: `ResponseParser._validate_response()` does NOT raise | When `self._output_type is None` (auto mode) |
| Unit: `execute_with_retries()` sets `_response_parser._output_type` | Output type is passed before `parse()` |
| Integration: LLM generates wrong type → correction prompt fires | LLM gets second chance, generates correct type |
| Integration: LLM still wrong after retries → handler coerces | Handler converts `NumberResponse` → `"10"` string |

---

## Issue 10: Clients Send Unsupported Types Like "text"

**Plan Reference:** §4.8 Bug B
**Status:** ✅ IMPLEMENTED

### Problem

Clients may send `output_type = "text"` through the API. The server passes it through unvalidated. The `output_type_template.tmpl` only recognizes `"string"`, `"number"`, `"dataframe"`, `"plot"` — not `"text"`. When an unrecognized type is sent, NONE of the `elif` branches match, so the LLM receives no output type constraint at all.

### Solution: Validate and Reject Unsupported Types at the API Boundary

```python
# In server/features/chat/handler.py

SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}


def _validate_output_type(output_type: Optional[str]) -> Optional[str]:
    """Validate output_type against PandasAI's supported types.

    Returns the validated type, or None for auto/null.
    Raises HTTPException(400) for unsupported types.
    """
    if output_type is None:
        return None

    if output_type == "auto":
        return None  # "auto" = LLM chooses freely → normalize to None

    if output_type not in SUPPORTED_OUTPUT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported output_type: '{output_type}'. "
                f"Supported types are: 'string', 'number', 'dataframe', 'plot', 'auto'. "
                f"Hint: Use 'string' instead of 'text'."
            ),
        )

    return output_type
```

### Why Validate Instead of Normalize?

| Approach | Pros | Cons |
|----------|------|------|
| **Validate + reject** | Explicit API contract; fail fast; catches typos | Client must send correct type |
| **Normalize "text" → "string"** | No client changes needed | Hides bugs; doesn't catch other typos like "strng" |
| **Map common aliases** | More forgiving | Maintaining alias list is fragile; still need validation |

**Decision:** Validate + reject. The 400 error immediately tells the developer what's wrong. The hint `"Use 'string' instead of 'text'"` makes the fix obvious.

### Implementation Notes (2025-05-08)

`_validate_output_type()` is implemented in `server/features/chat/handler.py` with `SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}`. Called before `agent.chat()`/`agent.follow_up()`. Returns `None` for `"auto"` (normalized to auto mode).

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_validate_output_type(None)` | Returns `None` |
| Unit: `_validate_output_type("auto")` | Returns `None` |
| Unit: `_validate_output_type("string")` | Returns `"string"` |
| Unit: `_validate_output_type("text")` | Raises `HTTPException(400)` with hint |
| Unit: `_validate_output_type("chart")` | Raises `HTTPException(400)` |
| Unit: `_validate_output_type("strng")` | Raises `HTTPException(400)` |
| Integration: API call with `output_type="text"` | Returns 400 with error message |

---

## Issue 11: ChartResponse.type = "chart" Instead of "plot"

**Plan Reference:** §4.8 Bug C
**Status:** ✅ IMPLEMENTED (both root cause fix + handler workaround)

### Problem

`ChartResponse.__init__` hardcodes `type="chart"` even though the LLM generates `result = {"type": "plot", ...}` and the template instructs the LLM to use `"plot"`. This causes:
- The API returns `{"type": "chart"}` instead of `{"type": "plot"}`
- Handler enforcement sees `"chart" != "plot"` and tries to coerce even when the LLM was correct
- Inconsistent type values between what the client requests and what the API returns

### Solution: Two-Part Fix

**Part 1 — Root cause fix** in `pandasai/core/response/chart.py`:

```python
class ChartResponse(BaseResponse):
    def __init__(self, value: Any, last_code_executed: str):
        super().__init__(value, "plot", last_code_executed)  # Changed "chart" → "plot"
```

**Part 2 — Handler workaround** for backward compatibility during rollout:

```python
# In server/features/chat/handler.py — before enforcement checks
if actual_type == "chart":
    actual_type = "plot"
```

The handler workaround ensures that if the root cause fix hasn't been deployed yet (or if there are other code paths that create `ChartResponse` objects), the API still consistently returns `"plot"`.

### Implementation Notes (2025-05-08)

Both fixes are implemented:
- **Root cause:** `ChartResponse.__init__` in `pandasai/core/response/chart.py` now passes `"plot"` to `super().__init__()` instead of `"chart"`
- **Handler workaround:** `server/features/chat/handler.py` normalizes `actual_type == "chart"` → `"plot"` before enforcement checks

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `ChartResponse.__init__` | `response.type == "plot"` (not "chart") |
| Unit: Handler normalization | `"chart"` → `"plot"` before enforcement |
| Integration: `output_type="plot"` request | Response has `type: "plot"` |
| Integration: `output_type="auto"` with chart response | Response has `type: "plot"` |

### Risk

| Risk | Mitigation |
|------|-----------|
| Existing clients expect `"chart"` | Handler workaround normalizes; coordinate with client teams before root cause fix |
| Other code references `ChartResponse.type == "chart"` | Search codebase for `"chart"` references; update all |

---

## Issue 12: Dead Correction Prompt Path

**Plan Reference:** §4.8 Fix 3
**Status:** ✅ IMPLEMENTED

### Problem

`InvalidLLMOutputType` exists in `pandasai/exceptions.py` and is imported in `pandasai/agent/base.py`, but is **never raised** anywhere in the codebase. The correction branch in `_regenerate_code_after_error()` is dead code:

```python
if isinstance(error, InvalidLLMOutputType):
    prompt = get_correct_output_type_error_prompt(...)
```

### Solution: Raise `InvalidLLMOutputType` in `ResponseParser._validate_response()`

See [Issue 9, Layer 2](#issue-9-output-type-mismatch--no-enforcement) for the implementation.

Additionally, improve the correction template with the same counter-examples as the main template:

#### File: `pandasai/core/prompts/templates/correct_output_type_error_prompt.tmpl` (MODIFY)

```jinja2
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

**⚠️ Dependency on Issue 13:** This template includes `code_strategy.tmpl`, which currently says "choose the most appropriate type" — contradicting the error-correction context. The `code_strategy.tmpl` conditional fix (Issue 13) MUST be implemented first. After that fix, when `output_type` is set, `code_strategy.tmpl` will render "You MUST use type '{{output_type}}'" instead of "choose", which is consistent with the correction prompt's intent.

### Implementation Notes (2025-05-08)

The dead code path is now live:
- `ResponseParser._validate_response()` raises `InvalidLLMOutputType` when `self._output_type` is set and `result["type"] != self._output_type`
- `Agent._regenerate_code_after_error()` routes `InvalidLLMOutputType` to `get_correct_output_type_error_prompt()`
- The correction template has IMPORTANT blocks with counter-examples for each type
- Issue 13 dependency is satisfied: `code_strategy.tmpl` conditional is implemented

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `ResponseParser._validate_response()` raises `InvalidLLMOutputType` | Type mismatch detected when `self._output_type` is set |
| Unit: `_regenerate_code_after_error()` routes to correction prompt | `isinstance(error, InvalidLLMOutputType)` is True |
| Integration: LLM generates wrong type → correction fires → LLM fixes | Full retry cycle with improved template |
| Integration: LLM still wrong after max_retries → exception propagates | Handler catches and applies coercion |

---

## Issue 13: code_strategy.tmpl Contradicts Type Constraint

**Plan Reference:** §4.8 Fix 2A
**Status:** ✅ IMPLEMENTED

### Problem

`code_strategy.tmpl` is included AFTER `output_type_template.tmpl` in the main prompt and says "choose the most appropriate type for the user's question" — unconditionally. This contradicts the type constraint when a specific `output_type` is requested. The LLM might follow `code_strategy.tmpl`'s "choose" guidance over the constraint.

### Solution: Conditional Jinja2 Block in code_strategy.tmpl

```jinja2
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

This ensures `code_strategy.tmpl` reinforces the type constraint instead of contradicting it.

### Implementation Notes (2025-05-08)

Implemented in `pandasai/core/prompts/templates/shared/code_strategy.tmpl`:
- When `output_type` is set: renders `"You MUST use type '{{output_type}}' — this is non-negotiable."`
- When `output_type` is None: renders the "Choose the most appropriate type" guidance with type descriptions

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: Template renders "MUST use type" when `output_type="string"` | Constraint reinforced |
| Unit: Template renders "Choose" when `output_type=None` | LLM chooses freely |
| Integration: Full prompt with `output_type="string"` | Both `output_type_template.tmpl` and `code_strategy.tmpl` say "string" |

---

## Issue 14: Multi-Output Queries Not Supported

**Plan Reference:** §4.8 Note

### Problem

PandasAI's result format is `result = {"type": "<type>", "value": <value>}` — a single type-value pair. There is no mechanism for a query to return multiple types simultaneously (e.g., text answer + chart + dataframe export).

### Solution: Document as Known Limitation + Recommend Workarounds

This is a **fundamental limitation of the PandasAI result format**, not a bug we can fix in this iteration. Future work could extend the format to support multi-type responses.

#### Recommended Workarounds

1. **Multiple API calls**: Client makes separate calls with different `output_type` values
2. **Use `output_type = "auto"`**: Let the LLM choose the single most appropriate type
3. **Use `output_type = "dataframe"`**: Get the raw data and let the client render charts/format text

#### Documentation Addition

Add a note to the API documentation:

```
Note: Each query returns a single response type. If you need both a text summary
and a chart, make two API calls:
  1. {"query": "how many are female?", "output_type": "string"}
  2. {"query": "show me a chart of gender distribution", "output_type": "plot"}
```

### Future Work

Extend the result format to support multi-type responses:

```python
# Future format (NOT implemented now):
result = [
    {"type": "string", "value": "There are 10 female employees."},
    {"type": "plot", "value": "exports/charts/gender_dist.png"},
]
```

This would require changes across the entire pipeline (prompt, code generation, response parser, handler serialization). Too invasive for this iteration.

---

## Issue 15: Column Selection Caching

**Plan Reference:** §8.3

### Problem

Follow-up questions about the same topic may not change the column selection, but re-running Step 1 adds latency and cost. However, follow-ups can also ADD or REMOVE columns, so caching must be conservative.

### Solution: Disabled by Default; Future Opt-In

```python
# In AgentState:
last_selected_names: Optional[List[str]] = None
last_query: Optional[str] = None
```

For now, **caching is disabled** — every query runs column selection fresh. This ensures follow-up questions that add new columns ("now show me X too") or remove columns ("just the names please") work correctly.

When caching is enabled in the future, it should use a similarity threshold:

```python
def _is_similar_query(self, query1: str, query2: str) -> bool:
    """Check if two queries are about the same topic."""
    # Future implementation: use embedding similarity or keyword overlap
    # For now, always return False (no caching)
    return False
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_is_similar_query()` returns False | Caching disabled by default |
| Future: Similar query returns cached selection | Cache hit |
| Future: Different query re-runs selection | Cache miss |

---

## Issue 16: New "error" Response Type

**Plan Reference:** §4.8 Fix 2B
**Status:** ✅ IMPLEMENTED

### Problem

When coercion fails (e.g., client requests `"plot"` but the query produces a `"number"`), the handler returns `{"type": "error", "response": "..."}`. This is a new response type that clients must handle.

### Solution: Document the "error" Type + Client-Side Handling

The `ChatResponse.type: str` field already supports arbitrary strings, so no schema change is needed. But client code must check for `"error"`:

```javascript
// Client-side handling example
if (response.type === "error") {
    showErrorMessage(response.response);
} else {
    processResponse(response);
}
```

#### Handler Implementation: `_coerce_response_type()`

The handler works with response objects (`NumberResponse`, `StringResponse`, etc.) that
have `.value` and `.type` attributes. The coercion function must work with these objects:

```python
def _coerce_response_type(response_obj, actual_type: str, requested_type: str):
    """Attempt to coerce a response object from actual_type to requested_type.

    Args:
        response_obj: The response object (e.g., NumberResponse, StringResponse).
                      Has .value and .type attributes.
        actual_type: The response object's .type attribute (e.g., "number", "chart").
        requested_type: The output_type the client requested (e.g., "string", "plot").

    Returns (coerced_value, new_type) on success, or None if coercion fails.
    """
    raw_value = getattr(response_obj, 'value', response_obj)

    # string ← number: "10" instead of 10
    if requested_type == "string" and actual_type == "number":
        return (str(raw_value), "string")

    # string ← dataframe: use DataFrame string summary (truncated)
    if requested_type == "string" and actual_type == "dataframe":
        if hasattr(raw_value, 'head'):
            summary = (
                f"DataFrame ({len(raw_value)} rows × {len(raw_value.columns)} columns)\n"
                f"First 5 rows:\n{str(raw_value.head())}"
            )
            return (summary, "string")
        return (str(raw_value), "string")

    # number ← string: try to extract the number
    if requested_type == "number" and actual_type == "string":
        try:
            return (float(str(raw_value)), "number")
        except (ValueError, TypeError):
            return None

    # All other mismatches are nonsensical — can't coerce
    return None
```

### Implementation Notes (2025-05-08)

`_coerce_response_type()` is implemented in `server/features/chat/handler.py`. When coercion fails, the handler returns `{"type": "error", "response": "Unable to produce output_type '...'..."}`. The `ChatResponse.type: str` field already supports this.

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `_coerce_response_type(NumberResponse(10), "number", "string")` | Returns `("10", "string")` |
| Unit: `_coerce_response_type(StringResponse("42"), "string", "number")` | Returns `(42.0, "number")` |
| Unit: `_coerce_response_type(StringResponse("hello"), "string", "number")` | Returns `None` |
| Unit: `_coerce_response_type(ChartResponse(...), "plot", "string")` | Returns `None` (nonsensical) |
| Integration: Failed coercion returns error response | `{"type": "error", "response": "Unable to produce..."}` |

---

## Issue 17: DataFrame→String Coercion May Produce Enormous Output

**Plan Reference:** §4.8 Fix 2B (⚠️ Warning)

### Problem

When `output_type="string"` but the LLM produces a DataFrame, `_coerce_response_type()` calls `str(response)`. For large DataFrames, `str(df)` can be enormous (thousands of tokens), potentially causing:
- Token overflow in the response
- Slow serialization
- Client-side memory issues

### Solution: Truncate DataFrame String Representation

```python
def _coerce_response_type(response_obj, actual_type: str, requested_type: str):
    # ... other cases ...

    # string ← dataframe: truncate to avoid enormous output
    # (This case is already handled in the main _coerce_response_type implementation
    #  above — shown here for reference only.)
    if requested_type == "string" and actual_type == "dataframe":
        raw_value = getattr(response_obj, 'value', response_obj)
        if hasattr(raw_value, 'head'):
            summary = (
                f"DataFrame ({len(raw_value)} rows × {len(raw_value.columns)} columns)\n"
                f"First 5 rows:\n{str(raw_value.head())}"
            )
            return (summary, "string")
        return (str(raw_value), "string")

    # ... other cases ...
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: Small DataFrame (3 rows) | Full string representation |
| Unit: Large DataFrame (1000 rows) | Truncated to 5 rows + shape info |
| Unit: DataFrame with `.head()` method | Uses `.head()` for truncation |

---

## Issue 18: Value-Type Mismatch Uses Wrong Correction Path

**Plan Reference:** §4.8 Edge Case

### Problem

If the LLM generates `result = {"type": "string", "value": 10}` (correct type "string", but value is a number instead of a string), the existing `_validate_response()` raises `InvalidOutputValueMismatch` — NOT `InvalidLLMOutputType`. This means the correction prompt is the **generic** error prompt, not the output-type-specific one.

### Solution: Accept as Known Limitation; Future Improvement

This is an edge case — the LLM understood the type constraint (it chose "string") but put a number as the value. The generic error prompt will tell the LLM that `value` must be a string for type "string", which should be sufficient.

**Future improvement**: For `output_type in ("string", "number")`, catch `InvalidOutputValueMismatch` and route it to the output-type-specific correction prompt:

```python
# Future improvement (NOT implemented now):
def _regenerate_code_after_error(self, code: str, error: Exception) -> str:
    if isinstance(error, InvalidLLMOutputType):
        prompt = get_correct_output_type_error_prompt(...)
    elif isinstance(error, InvalidOutputValueMismatch) and self._state.output_type:
        # Route value-type mismatches to the type-specific prompt too
        prompt = get_correct_output_type_error_prompt(...)
    else:
        prompt = get_correct_error_prompt_for_sql(...)
    return self._code_generator.generate_code(prompt)
```

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `result = {"type": "string", "value": 10}` | Raises `InvalidOutputValueMismatch` (existing behavior) |
| Unit: Generic error prompt mentions value-type | LLM gets enough info to fix |
| Integration: Handler coerces `number → string` | Value 10 becomes "10" |

---

## Issue 19: Config Fields Don't Exist Yet

**Plan Reference:** §3.2
**Status:** ✅ IMPLEMENTED (config fields added)

### Problem

The plan proposes adding `column_selection_enabled`, `column_selection_threshold`, `column_selection_memory_size`, and `auto_fill_descriptions` to the `Config` class, but these fields don't exist yet.

### Solution: Add Fields to `pandasai/config.py`

```python
class Config(BaseModel):
    # ... existing fields ...

    # Column selection pipeline
    column_selection_enabled: bool = False
    column_selection_threshold: int = 30
    column_selection_memory_size: int = 5
    auto_fill_descriptions: bool = False
```

### Implementation Notes (2025-05-08)

All four config fields are added to `pandasai/config.py` with the exact defaults shown above. Server payload fields in `server/features/register/models.py` still need to be added (see Phase 1 checklist).

### Test Strategy

| Test | What It Verifies |
|------|-----------------|
| Unit: `Config()` defaults | `column_selection_enabled=False`, `column_selection_threshold=30`, etc. |
| Unit: `Config(column_selection_enabled=True)` | Field is set correctly |
| Unit: Server payload parsing | Fields map correctly from payload to Config |

---

## Issue 20: Open Questions Need Resolution

**Plan Reference:** §10

### Problem

The plan lists 10 open questions that need decisions before implementation.

### Solution: Resolutions

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

---

## Appendix A: Complete File Change Summary

### New Files

| File | Purpose |
|------|---------|
| `pandasai/core/column_selector.py` | Step 1: LLM column selection + smart removal |
| `pandasai/core/prompts/select_columns.py` | Prompt class for column selection |
| `pandasai/core/prompts/templates/select_columns.tmpl` | Step 1 prompt template |
| `pandasai/core/prompts/auto_fill_descriptions.py` | Prompt class for auto-fill |
| `pandasai/core/prompts/templates/auto_fill_descriptions.tmpl` | Auto-fill prompt template |
| `server/core/description_filler.py` | Auto-fill missing column descriptions |

### New Files (Testing)

| File | Purpose |
|------|---------|
| `tests/unit_tests/llms/test_base_llm.py` | Removed `test_is_pandasai_llm` test (dead code) |

### Modified Files

| File | Changes | Status |
|------|---------|--------|
| `pandasai/config.py` | Add `column_selection_enabled`, `column_selection_threshold`, `column_selection_memory_size`, `auto_fill_descriptions` | ✅ Done |
| `pandasai/agent/base.py` | Add `_should_select_columns()`, `_apply_column_selection()`, `_build_trimmed_dataframe()`, `_store_assistant_message()`, `set_message_history()`; modify `_process_query()`, `execute_with_retries()` | 🟡 Partial (`_store_assistant_message`, `set_message_history`, `execute_with_retries` done; column selection methods pending) |
| `pandasai/agent/state.py` | Add `last_selected_names`, `last_query` fields (for future caching) | ⬜ Not started |
| `pandasai/helpers/memory.py` | Renamed `size` → `memory_size` (property + setter); added `to_openai_messages_for_chat()`; fixed `_truncate` type hint; added `to_json` return type | ✅ Done |
| `pandasai/core/response/parser.py` | Add `self._output_type` attribute; raise `InvalidLLMOutputType` on type mismatch in `_validate_response()` | ✅ Done |
| `pandasai/core/response/chart.py` | Change `type="chart"` → `type="plot"` in `ChartResponse.__init__` | ✅ Done |
| `pandasai/core/prompts/base.py` | Removed dead `validate()` method and `AbstractPrompt` class | ✅ Done |
| `pandasai/core/prompts/templates/shared/output_type_template.tmpl` | Add IMPORTANT blocks with counter-examples + reformulation guidance | ✅ Done |
| `pandasai/core/prompts/templates/shared/code_strategy.tmpl` | Add conditional `{% if output_type %}` block | ✅ Done |
| `pandasai/core/prompts/templates/correct_output_type_error_prompt.tmpl` | Add IMPORTANT blocks with counter-examples | ✅ Done |
| `pandasai/llm/base.py` | Removed dead `is_pandasai_llm()` method | ✅ Done |
| `extensions/llms/openai/pandasai_openai/base.py` | Fixed `_client_params` type annotation (`any` → `Any`) | ✅ Done |
| `extensions/llms/litellm/pandasai_litellm/litellm.py` | Fixed pointless f-string (`f"litellm"` → `"litellm"`) | ✅ Done |
| `server/features/chat/handler.py` | Add `_validate_output_type()`, `_coerce_response_type()`, "chart" → "plot" normalization; use `agent.set_message_history()` | ✅ Done |
| `server/features/chat/models.py` | No change needed (ChatResponse.type is already `str`) | N/A |
| `server/features/register/handler.py` | Add step 2c: auto-fill missing descriptions | ⬜ Not started |
| `server/features/register/models.py` | Add `column_selection_enabled`, `column_selection_threshold`, `auto_fill_descriptions` fields | ⬜ Not started |

### Unchanged Files (Column Selection)

| File | Why No Change Needed |
|------|---------------------|
| `pandasai/helpers/dataframe_serializer.py` | Serializes the trimmed DataFrame as-is |
| `pandasai/core/prompts/templates/shared/search_strategy.tmpl` | Reads from schema → only sees matched columns |
| `pandasai/core/prompts/templates/shared/dataframe.tmpl` | Reads from DataFrame → fewer columns in CSV rows |
| `pandasai/helpers/column_enrichment.py` | Already ran at registration time |
| `pandasai/helpers/semantic_matching.py` | Used during matching step — no changes |

---

## Appendix B: Implementation Phase Checklist

### Phase 1: Foundation
- [x] Add config fields to `pandasai/config.py`
- [ ] Add server payload fields to `server/features/register/models.py`
- [ ] Add `_should_select_columns()` stub to `Agent`
- [ ] Add `_apply_column_selection()` stub to `Agent`

### Phase 2: Auto-Fill Descriptions
- [ ] Create `server/core/description_filler.py`
- [ ] Create `pandasai/core/prompts/auto_fill_descriptions.py`
- [ ] Create `pandasai/core/prompts/templates/auto_fill_descriptions.tmpl`
- [ ] Wire into register handler step 2c
- [ ] Test with dataset that has missing descriptions

### Phase 3: Column Selection
- [ ] Create `pandasai/core/column_selector.py`
- [ ] Create `pandasai/core/prompts/select_columns.py`
- [ ] Create `pandasai/core/prompts/templates/select_columns.tmpl`
- [ ] Implement `match_names_to_schema()` with bracket convention
- [ ] Implement `_build_trimmed_dataframe()` (smart removal)
- [ ] Wire into `Agent._process_query()` with try/finally swap pattern
- [ ] Add fallback logic and essential column protection

### Phase 4: Memory Fix + Output Type Enforcement ✅ COMPLETE
- [x] Add `_validate_output_type()` in handler.py
- [x] Improve `output_type_template.tmpl` with IMPORTANT blocks + counter-examples
- [x] Update `code_strategy.tmpl` with conditional `{% if output_type %}` block
- [x] Add handler-level enforcement with `_coerce_response_type()`
- [x] Add "chart" → "plot" normalization in handler
- [x] Fix `ChartResponse.__init__` root cause (`type="chart"` → `type="plot"`)
- [x] Add `_output_type` attribute to `ResponseParser`
- [x] Raise `InvalidLLMOutputType` in `_validate_response()` on type mismatch
- [x] Pass `output_type` to `ResponseParser` via `self._response_parser._output_type`
- [x] Improve `correct_output_type_error_prompt.tmpl` with counter-examples
- [x] Add `_store_assistant_message()` to `Agent._process_query()`
- [x] Rename `Memory.size` → `Memory.memory_size` with proper property + setter
- [x] Add `Agent.set_message_history()` public API
- [x] Add `Memory.to_openai_messages_for_chat()` authoritative method
- [x] Fix handler.py to use `agent.set_message_history()` (encapsulation)
- [ ] Add `_build_step1_memory()` to `ColumnSelector` (depends on Phase 3)
- [ ] Wire temporary memory into Step 1 LLM call (depends on Phase 3)
- [ ] Test multi-turn conversations with follow-up column add/remove
- [ ] Test output type enforcement end-to-end

### Phase 5: Dead Code Cleanup ✅ COMPLETE
- [x] Remove `BasePrompt.validate()` — dead code (never called, no overrides)
- [x] Remove `AbstractPrompt` class — dead code (never imported, never subclassed)
- [x] Remove `LLM.is_pandasai_llm()` — dead code (only called from its own test)
- [x] Fix Memory type hints (`_truncate` return type, `to_json` return type)
- [x] Fix BaseOpenAI `_client_params` type annotation (`any` → `Any`)
- [x] Fix LiteLLM f-string (`f"litellm"` → `"litellm"`)

### Phase 6: Caching & Polish
- [ ] Add `last_selected_names` to `AgentState`
- [ ] Implement column selection caching (disabled by default)
- [ ] Add logging/metrics for column selection hits/misses
- [ ] Integration testing with 100+ column datasets
- [ ] Document `"error"` response type for clients
- [ ] Document multi-output query limitation
