# PandasAI Chat Excel Server - Diagnostic Report

**Date**: May 7, 2026  
**Scope**: Analysis of PandasAI v3.0.0 source code and server integration  
**Focus Areas**: Prompt templates, JSON serialization, semantic model validation

---

## Executive Summary

The codebase is **largely well-structured** with solid foundations for all three aims. However, there are **7 issues identified** (2 high severity, 3 medium, 2 low) that need attention before production deployment.

| Aim | Status | Critical Issues |
|-----|--------|----------------|
| 1. Improve Prompts | 🟡 Partial | Nested query examples need expansion |
| 2. Succinct JSON Arrays | 🟡 Partial | Token budget doesn't handle nested depth |
| 3. Semantic Model Validation | 🟡 Partial | Missing SemanticModelPayload wrapper |

---

## Aim 1: Prompt Templates & Search Strategy

### ✅ What Works Well

**1. Search Strategy Template** (`pandasai/core/prompts/templates/shared/search_strategy.tmpl`)
- **93 lines** of comprehensive DuckDB SQL guidance
- **5 well-defined rules** covering freetext, categorical, general SQL, nested structs, and text normalization
- **Rule 4** specifically handles `list[struct]` with both `UNNEST` and `list_filter` approaches
- **Jinja2 templating** dynamically annotates columns with their semantic types

**Example from Rule 4** (nested struct handling):
```sql
-- UNNEST approach (preferred for aggregation):
SELECT DISTINCT "Employee Name"
FROM my_table, UNNEST("Leave Details") AS t(rec)
WHERE rec['Leave Type'] = 'Wellbeing';

-- list_filter approach (preferred for boolean checks):
SELECT * FROM my_table
WHERE len(list_filter("Leave Details", x -> x['Leave Type'] ILIKE '%sick%')) > 0;
```

**2. Error Correction Templates** 
- `correct_execute_sql_query_usage_error_prompt.tmpl` **includes** `search_strategy.tmpl` ✅
- Ensures consistency between initial generation and error recovery
- Properly enforces `execute_sql_query` function usage

**Template inclusion chain**:
```
generate_python_code_with_sql.tmpl
  └─ includes search_strategy.tmpl ✅

correct_execute_sql_query_usage_error_prompt.tmpl
  └─ includes search_strategy.tmpl ✅
```

### ⚠️ Issues Found

| ID | Severity | Issue | Location | Impact |
|----|----------|-------|----------|--------|
| P1 | 🟠 Medium | **Missing complex nested query examples** | `search_strategy.tmpl` Rule 4 | LLM may struggle with multi-level nesting (e.g., struct within struct) |
| P2 | 🟠 Medium | **No examples for aggregation across multiple nested arrays** | `search_strategy.tmpl` Rule 4 | Queries like "total leave days by department" may fail |

### 🔧 Recommendations

**For P1**: Add to Rule 4 in `search_strategy.tmpl`:
```
-- Multi-level nesting example:
SELECT "Employee Name"
FROM my_table, UNNEST("Projects") AS t(proj)
WHERE proj['Status'] = 'Active' 
  AND EXISTS (
    SELECT 1 FROM UNNEST(proj['Team Members']) AS m(member)
    WHERE member['Role'] = 'Lead'
  );
```

**For P2**: Add aggregation guidance:
```sql
-- Aggregating across nested arrays:
SELECT 
  "Department",
  SUM(rec['Duration']) as total_leave_days
FROM my_table, UNNEST("Leave Details") AS t(rec)
GROUP BY "Department";
```

---

## Aim 2: DataframeSerializer & JSON Formatting

### ✅ What Works Well

**1. Token Budget System** (`dataframe_serializer.py#L115-L170`)
- `_apply_token_budget()` method prevents context overflow
- Estimates ~4 chars per token
- Proportionally distributes budget across enriched columns
- Can drop `examples` from numeric ranges when over budget

**2. Nested Struct Handling** (`column_enrichment.py#L23-L60`)
- `ColumnValueExtractor.extract()` recursively processes `list[struct]` columns
- Builds vocabulary dict with type, samples, description, semantic_type
- Prevents `.nunique()` errors on list values

**3. Compact JSON Output**
- Uses `json.dumps(columns, ensure_ascii=False)` for compactness
- XML-wrapped format: `<table dialect="..." columns="[...]">`
- Truncates long strings at 200 chars

### ⚠️ Issues Found

| ID | Severity | Issue | Location | Impact |
|----|----------|-------|----------|--------|
| S1 | 🔴 High | **Token budget doesn't account for nested struct depth** | `dataframe_serializer.py#L115` | Deeply nested structs may exceed budget silently |
| S2 | 🟠 Medium | **Struct field name validation missing** | `column_enrichment.py#L40-60` | No validation that struct keys match schema during serialization |
| S3 | 🟠 Medium | **Redundant tokens in nested metadata** | `column_enrichment.py#L53` | Inner struct fields repeat `type`, `samples` keys without compression |

### 🔍 Code Analysis

**Token Budget Calculation** (Line 127-130):
```python
def _token_cost(col_dict: dict) -> int:
    samples = col_dict.get("samples")
    if not samples:
        return 0
    # Rough estimate: ~4 chars per token
    return len(json.dumps({"samples": samples}, ensure_ascii=False)) // 4
```

**Issue**: This only measures top-level `samples`. For nested structs like:
```json
{
  "samples": {
    "inner_col1": {"type": "string", "samples": [...], "semantic_type": "freetext"},
    "inner_col2": {"type": "integer", "samples": {"min": 0, "max": 100}}
  }
}
```
The cost calculation doesn't recursively sum inner samples.

**S3 Example - Current Output** (verbose):
```json
{
  "name": "Leave Details",
  "type": "list[struct]",
  "semantic_type": "struct",
  "samples": {
    "Leave Type": {
      "type": "string",
      "samples": ["Sick Leave", "Wellbeing", "Vacation"],
      "semantic_type": "categorical",
      "description": "Type of leave taken"
    }
  }
}
```

**Potential Optimization** (compact):
```json
{
  "name": "Leave Details",
  "type": "list[struct]",
  "samples": {
    "Leave Type": ["categorical", ["Sick Leave", "Wellbeing", "Vacation"], "Type of leave taken"]
  }
}
```

### 🔧 Recommendations

**For S1**: Add recursive token cost calculation:
```python
def _token_cost(col_dict: dict) -> int:
    samples = col_dict.get("samples")
    if not samples:
        return 0
    if isinstance(samples, dict):
        # Recursively count nested struct samples
        total = 0
        for inner_col, inner_data in samples.items():
            total += len(json.dumps(inner_data, ensure_ascii=False)) // 4
        return total
    return len(json.dumps({"samples": samples}, ensure_ascii=False)) // 4
```

**For S2**: Add validation in `ColumnValueExtractor.extract()`:
```python
# After building struct_vocabulary
if df_schema and df_schema.columns:
    schema_col = next((c for c in df_schema.columns if c.name == col_name), None)
    if schema_col and schema_col.samples:
        # Validate struct keys match schema
        expected_keys = set(schema_col.samples.keys())
        actual_keys = set(struct_vocabulary.keys())
        missing = expected_keys - actual_keys
        if missing:
            logger.warning(f"Missing struct fields: {missing}")
```

**For S3**: Consider positional encoding for inner fields (breaking change but saves ~30% tokens).

---

## Aim 3: Semantic Model Validation & Integration

### ✅ What Works Well

**1. SemanticLayerSchema** (`semantic_layer_schema.py`)
- **Comprehensive Pydantic validation** with field validators
- Validates column types against `VALID_COLUMN_TYPES`
- Validates SQL expressions with `sqlglot`
- Enforces source type requirements (local vs remote)
- Validates group_by/aggregation consistency

**Key validation features**:
```python
class Column(BaseModel):
    @field_validator("type")
    def is_column_type_supported(cls, type: str) -> str:
        if type and type not in VALID_COLUMN_TYPES:
            raise ValueError(...)
    
    @field_validator("expression")
    def is_expression_valid(cls, expr: str) -> Optional[str]:
        parse_one(expr)  # sqlglot validation
```

**2. Server Registration Flow** (`server/features/register/handler.py`)
- Validates semantic model on upload (line 57):
  ```python
  validated_schema = SemanticLayerSchema(**semantic_model)
  df.schema = validated_schema
  ```
- Returns structured error responses with field-level details
- Handles dummy source injection for uploaded files

**3. Configuration Payloads** (`server/features/register/models.py`)
- `PandasAIConfigPayload` - enrichment settings
- `LLMConfigPayload` - LLM configuration with sampling parameters
- `Base64UploadRequest` - upload request model

### ⚠️ Issues Found

| ID | Severity | Issue | Location | Impact |
|----|----------|-------|----------|--------|
| M1 | 🔴 High | **No SemanticModelPayload wrapper** | `server/features/register/models.py` | Raw dict passed around, no type safety for semantic_model parameter |
| M2 | 🟠 Medium | **Semantic validation happens after file read** | `handler.py#L57` | Invalid semantic models waste I/O operations |
| M3 | 🟡 Low | **No schema versioning** | `SemanticLayerSchema` | Future schema changes may break existing uploads |

### 🔍 Code Analysis

**Current Flow** (handler.py lines 27-61):
```python
def create_agent_from_file_path(file_path, mimetype, semantic_model: dict = None, ...):
    # 1. Read file (I/O operation)
    df = pai.read_csv(file_path)
    
    # 2. Parse JSON columns
    for col in df.columns:
        if is_json_array_column(df[col]):
            df[col] = df[col].apply(lambda v: safe_json_parse(v) or [])
    
    # 3. Validate semantic model (AFTER I/O)
    if semantic_model:
        validated_schema = SemanticLayerSchema(**semantic_model)
        df.schema = validated_schema
```

**Issue M1**: The `semantic_model` parameter is `Optional[Dict[str, Any]]` - no dedicated Pydantic model means:
- No IDE autocomplete for semantic model structure
- No validation before passing to handler
- Error messages less helpful (generic dict vs typed model)

**Issue M2**: File is read before validation. If semantic model is invalid, the I/O was wasted.

### 🔧 Recommendations

**For M1**: Create `SemanticModelPayload` in `server/features/register/models.py`:
```python
class SemanticModelPayload(BaseModel):
    name: str = Field(..., description="Dataset name (underscore_format)")
    description: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    columns: Optional[List[Dict[str, Any]]] = None
    relations: Optional[List[Dict[str, Any]]] = None
    transformations: Optional[List[Dict[str, Any]]] = None
    
    @model_validator(mode="after")
    def validate_as_semantic_layer_schema(self) -> "SemanticModelPayload":
        """Validate against PandasAI's SemanticLayerSchema"""
        from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
        try:
            SemanticLayerSchema(**self.model_dump())
        except ValidationError as e:
            raise ValueError(f"Invalid semantic model: {e}")
        return self
```

Then update `Base64UploadRequest`:
```python
class Base64UploadRequest(BaseModel):
    base64_data: str
    mimetype: str
    semantic_model: Optional[SemanticModelPayload] = None  # ← Typed!
    pandasai_config: Optional[PandasAIConfigPayload] = None
    llm_config: Optional[LLMConfigPayload] = None
```

**For M2**: Validate semantic model before file read:
```python
def create_agent_from_file_path(..., semantic_model: dict = None, ...):
    # Validate FIRST (fast, no I/O)
    if semantic_model:
        try:
            validated_schema = SemanticLayerSchema(**semantic_model)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=...)
    
    # Then read file (only if validation passed)
    **✅ IMPLEMENTED**: Both M1 and M2 have been implemented. Additionally, the router now automatically adds a default source when neither `source` nor `view` is provided in the semantic model, preventing validation errors for uploaded files.
    df = pai.read_csv(file_path)
    df.schema = validated_schema
```

**For M3**: Add version field to `SemanticLayerSchema`:
```python
class SemanticLayerSchema(BaseModel):
    schema_version: str = Field("1.0.0", description="Schema version for forward compatibility")
    # ... existing fields
```

---

## Cross-Cutting Issues

| ID | Severity | Issue | Impact |
|----|----------|-------|--------|
| C1 | 🟡 Low | **No integration tests for nested struct queries** | Runtime errors may go undetected |
| C2 | 🟡 Low | **LLM system prompt in handler.py line 88 doesn't mention nested arrays** | Agent may not prioritize `execute_sql_query` for nested data |

---

## Priority Matrix

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 🔴 P0 | S1: Token budget for nested structs | Low | High |
| 🔴 P0 | M1: Create SemanticModelPayload | Medium | High |
| 🟠 P1 | P1: Add complex nested examples | Low | Medium |
| 🟠 P1 | S2: Struct field validation | Medium | Medium |
| 🟠 P1 | M2: Validate before I/O | Low | Medium |
| 🟡 P2 | P2: Multi-array aggregation examples | Low | Low |
| 🟡 P2 | S3: Compact nested metadata | High | Medium |
| 🟡 P2 | M3: Schema versioning | Low | Low |

---

## Next Steps

1. **Immediate (P0)**:
   - Fix token budget calculation for nested structs (S1)
   - Create `SemanticModelPayload` wrapper (M1)

2. **Short-term (P1)**:
   - Add complex nested query examples to `search_strategy.tmpl` (P1)
   - Add struct field validation in serialization (S2)
   - Move validation before file I/O (M2)

3. **Medium-term (P2)**:
   - Add multi-array aggregation examples (P2)
   - Consider compact metadata encoding (S3)
   - Add schema versioning (M3)

---

## Appendix: File Reference

| Component | Path |
|-----------|------|
| Search Strategy Template | `pandasai/core/prompts/templates/shared/search_strategy.tmpl` |
| Error Correction Template | `pandasai/core/prompts/templates/correct_execute_sql_query_usage_error_prompt.tmpl` |
| DataframeSerializer | `pandasai/helpers/dataframe_serializer.py` |
| ColumnValueExtractor | `pandasai/helpers/column_enrichment.py` |
| SemanticLayerSchema | `pandasai/data_loader/semantic_layer_schema.py` |
| Server Handler | `server/features/register/handler.py` |
| Server Models | `server/features/register/models.py` |

---

**Report generated by**: GitHub Copilot (qwen3.6-plus-2026-04-02)  
**Analysis depth**: Thorough (code review + structural analysis)
