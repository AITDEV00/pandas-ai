"""
Reusable type detection utilities for pandas Series.

This module centralises all data-type heuristics so that handler.py,
column_enrichment.py, and any future consumers share one source of truth.
Functions rely on pandas built-in type inspection to minimise proprietary logic.
"""

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def is_json_array_column(series: pd.Series) -> bool:
    """Return True if the column appears to contain JSON array strings.

    The check is intentionally cheap: only the first non-null cell is inspected.
    """
    if not (pd.api.types.is_string_dtype(series) or series.dtype == object):
        return False
    first_val = series.dropna().iloc[0] if not series.dropna().empty else ""
    if not isinstance(first_val, str):
        return False
    stripped = first_val.strip()
    if not stripped.startswith("["):
        return False
    # Quick validation: try to parse just the first cell
    try:
        parsed = json.loads(stripped)
        return isinstance(parsed, list)
    except (json.JSONDecodeError, ValueError):
        return False


def is_list_struct_column(series: pd.Series) -> bool:
    """Return True if the column contains list-of-dict values (DuckDB list[struct]).

    The check is intentionally cheap: only the first non-null cell is inspected.
    This detects columns that were parsed from JSON arrays (via ``is_json_array_column``
    + ``safe_json_parse``) and now hold actual Python list[dict] values.
    """
    first_valid = series.dropna().iloc[0] if not series.dropna().empty else None
    return isinstance(first_valid, list)


def determine_series_type(series: pd.Series) -> str:
    """Infer the semantic type string for a pandas Series.

    Returns one of: 'float', 'integer', 'datetime', 'boolean', 'string', 'list[struct]'.
    Uses only pandas built-in type inspection.
    """
    if is_list_struct_column(series):
        return "list[struct]"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_numeric_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def safe_json_parse(val) -> Optional[list]:
    """Try to parse a single cell value as a JSON array, returning None on failure."""
    if pd.isna(val) or not isinstance(val, str):
        return None
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, ValueError):
        return None


def parse_json_array_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Detect JSON array string columns and parse them into native Python lists.

    After this transformation, :func:`is_list_struct_column` will correctly
    identify the column as ``list[struct]`` instead of ``string``.

    Returns the DataFrame with parsed columns modified in-place.
    """
    for col in df.columns:
        if is_json_array_column(df[col]):
            df[col] = df[col].apply(lambda v: safe_json_parse(v) or [])
    return df


# ---------------------------------------------------------------------------
# Struct field type casting
# ---------------------------------------------------------------------------
# After ``parse_json_array_columns`` converts JSON array strings into
# ``list[dict]``, all dict values are Python primitives from ``json.loads``.
# JSON has no native date/integer types, so date strings like "2025-01-15"
# remain as ``str``.  When DuckDB registers the DataFrame, it infers types
# from the Python objects — so struct fields end up as VARCHAR instead of
# DATE/TIMESTAMP, and numeric strings stay VARCHAR instead of FLOAT/INTEGER.
#
# ``cast_struct_field_types`` uses the semantic model schema to convert
# struct field values to their declared Python types (datetime, float, int)
# so that DuckDB infers the correct SQL types.
# ---------------------------------------------------------------------------


def _cast_datetime(v: Any) -> Any:
    """Cast a string/value to ``datetime.date`` using ``pandas.to_datetime``.

    Uses ``pandas.to_datetime`` with ``errors='coerce'`` for robust parsing
    of 50+ date formats (ISO 8601, locale-specific, compact, etc.) without
    raising exceptions.  Returns ``datetime.date`` (not ``Timestamp``) so
    that DuckDB infers ``DATE`` rather than ``TIMESTAMP``.

    Falls back to the original value if parsing yields NaT.
    """
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        # datetime → date (DuckDB DATE, not TIMESTAMP)
        return v.date()
    if not isinstance(v, str) or not v.strip():
        return v
    import warnings
    try:
        # dayfirst=True avoids UserWarning for DD/MM/YYYY and is the more
        # common format in enterprise data outside the US.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            ts = pd.to_datetime(v, errors="coerce", dayfirst=True)
        if pd.isna(ts):
            return v
        # Return date so DuckDB infers DATE, not TIMESTAMP
        return ts.date()
    except (ValueError, TypeError):
        return v


def _cast_float(v: Any) -> Any:
    """Cast a string/value to float using ``pandas.to_numeric``.

    Uses ``pandas.to_numeric`` with ``errors='coerce'`` for consistent
    numeric parsing.  Returns NaN for unparseable values, which triggers
    the fallback to the original value.
    """
    if isinstance(v, float):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str) or not v.strip():
        return v
    try:
        result = pd.to_numeric(v, errors="coerce")
        if pd.isna(result):
            return v
        return float(result)
    except (ValueError, TypeError):
        return v


def _cast_integer(v: Any) -> Any:
    """Cast a string/value to int using ``pandas.to_numeric``.

    Uses ``pandas.to_numeric`` with ``downcast='integer'`` and
    ``errors='coerce'`` for robust numeric parsing.  The downcast
    converts float-representable integers (e.g. ``"5.0"``) to int.
    Falls back to the original value for unparseable inputs.
    """
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if not isinstance(v, str) or not v.strip():
        return v
    try:
        result = pd.to_numeric(v, errors="coerce", downcast="integer")
        if pd.isna(result):
            return v
        return int(result)
    except (ValueError, TypeError):
        return v


def _cast_boolean(v: Any) -> Any:
    """Cast a string/value to bool using ``pydantic.TypeAdapter``.

    Uses Pydantic's ``TypeAdapter(bool)`` for robust boolean parsing that
    handles ``"true"``/``"false"``, ``"1"``/``"0"``, ``"yes"``/``"no"``
    (case-insensitive) and raises ``ValidationError`` on invalid input,
    which triggers the fallback to the original value.
    """
    if isinstance(v, bool):
        return v
    if not isinstance(v, str) or not v.strip():
        return v
    try:
        from pydantic import TypeAdapter
        return TypeAdapter(bool).validate_python(v)
    except Exception:
        return v


# Map of semantic-layer type strings → caster functions.
# Each callable takes a raw value (typically str from json.loads) and returns
# the converted value, or the original value if conversion fails.
_TYPE_CASTERS: Dict[str, Any] = {
    "datetime": _cast_datetime,
    "float": _cast_float,
    "integer": _cast_integer,
    "boolean": _cast_boolean,
}


def _build_struct_field_type_map(df: pd.DataFrame, schema: Any) -> Dict[str, Dict[str, str]]:
    """Build a mapping of struct column name → {inner_field_name: declared_type}.

    Uses the semantic model schema to find type declarations for struct inner
    fields.  The schema stores individual inner-field columns (e.g.
    ``[Employee Leave Details[Leave Start Date]]`` with type ``datetime``).
    This function resolves those to the actual dict keys used in the parsed
    data (``Employee Leave Details[Leave Start Date]`` — no outer brackets).

    Returns:
        Dict mapping ``column_name → {inner_field_key: type_string}``
    """
    if not schema or not hasattr(schema, "columns") or not schema.columns:
        return {}

    # Build lookup: schema column name → declared type
    schema_type_by_name: Dict[str, str] = {}
    for schema_col in schema.columns:
        if schema_col.type and schema_col.type != "list[struct]":
            schema_type_by_name[schema_col.name] = schema_col.type

    field_type_map: Dict[str, Dict[str, str]] = {}

    for col_name in df.columns:
        if not is_list_struct_column(df[col_name]):
            continue

        # Get the actual inner field keys from the first non-empty struct
        first_nonempty = next(
            (v for v in df[col_name].dropna() if isinstance(v, list) and v and isinstance(v[0], dict)),
            None,
        )
        if first_nonempty is None:
            continue

        inner_keys = list(first_nonempty[0].keys())
        inner_types: Dict[str, str] = {}

        for key in inner_keys:
            # The schema stores inner fields with outer brackets: [Parent[Field]]
            # The data dict key is: Parent[Field] (no outer brackets)
            bracket_name = f"[{key}]"

            # Try exact match first, then bracket-wrapped
            declared_type = schema_type_by_name.get(key) or schema_type_by_name.get(bracket_name)
            if declared_type and declared_type in _TYPE_CASTERS:
                inner_types[key] = declared_type

        if inner_types:
            field_type_map[col_name] = inner_types

    return field_type_map


def _make_row_caster(casters: Dict[str, Any]) -> Any:
    """Return a function that casts struct dict values for one DataFrame column.

    Uses a factory to avoid the closure-over-mutable-default-arg pattern and
    make the binding of *casters* explicit.
    """

    def _cast_row(row_list: list) -> list:
        if not isinstance(row_list, list):
            return row_list
        result = []
        for struct_dict in row_list:
            if not isinstance(struct_dict, dict):
                result.append(struct_dict)
                continue
            cast_dict = {}
            for k, v in struct_dict.items():
                caster = casters.get(k)
                cast_dict[k] = caster(v) if caster else v
            result.append(cast_dict)
        return result

    return _cast_row


def cast_struct_field_types(df: pd.DataFrame, schema: Any) -> pd.DataFrame:
    """Cast struct inner-field values to their declared types from the schema.

    After ``parse_json_array_columns`` converts JSON array strings into
    ``list[dict]``, all values are Python primitives from ``json.loads``.
    JSON has no native date type, so date strings like ``"2025-01-15"``
    remain as ``str``.  When DuckDB registers the DataFrame via
    ``connection.register()``, it infers types from the Python objects — so
    struct fields that should be DATE/TIMESTAMP end up as VARCHAR.

    This function uses the semantic model schema to convert struct field
    values to their declared Python types (``datetime.date``, ``float``,
    ``int``, ``bool``) so that DuckDB infers the correct SQL types.

    Must be called AFTER ``parse_json_array_columns()`` and AFTER the schema
    is assigned to the DataFrame (``df.schema = validated_schema``).

    Args:
        df: DataFrame with parsed struct columns (list[dict] values).
        schema: A SemanticLayerSchema with declared column types.

    Returns:
        The DataFrame with struct field values cast to their declared types.
    """
    field_type_map = _build_struct_field_type_map(df, schema)
    if not field_type_map:
        return df

    for col_name, inner_types in field_type_map.items():
        casters = {key: _TYPE_CASTERS[declared_type] for key, declared_type in inner_types.items()}
        df[col_name] = df[col_name].apply(_make_row_caster(casters))

    logger.info(
        "Cast struct field types for %d column(s): %s",
        len(field_type_map),
        {col: inner for col, inner in field_type_map.items()},
    )

    return df


# ---------------------------------------------------------------------------
# Flat (top-level) column type casting
# ---------------------------------------------------------------------------
# The semantic model declares flat columns too (e.g. ``datetime`` for a
# ``[Employee Master[Date of Joining]]`` column).  But when a CSV is loaded,
# pandas keeps these as ``object``/string dtype, and DuckDB infers ``VARCHAR``.
#
# The prompt tells the LLM the column is ``datetime``, so it writes pandas
# datetime code (``.dt.date``, ``.dt.days``, ``(today - doj.date())``), which
# crashes at runtime because the value is actually a string.  Casting flat
# columns to their declared type BEFORE DuckDB registration makes the runtime
# dtype match the prompt, eliminating this whole error class.
#
# ``cast_struct_field_types`` above only handles struct inner-fields. This
# function handles the top-level columns so both are covered.
# ---------------------------------------------------------------------------


def _build_flat_field_type_map(df: pd.DataFrame, schema: Any) -> Dict[str, str]:
    """Build a mapping of flat column name → declared type from the schema.

    Only includes top-level (non-list[struct]) columns whose declared type is
    in ``_TYPE_CASTERS`` (datetime, float, integer, boolean).  Columns that are
    already the correct dtype are skipped.

    Returns:
        Dict mapping ``column_name → type_string``.
    """
    if not schema or not hasattr(schema, "columns") or not schema.columns:
        return {}

    flat_type_map: Dict[str, str] = {}

    for schema_col in schema.columns:
        col_name = schema_col.name
        declared_type = schema_col.type
        if not declared_type or declared_type not in _TYPE_CASTERS:
            continue
        # Skip struct columns — handled by cast_struct_field_types
        if col_name not in df.columns:
            continue
        if is_list_struct_column(df[col_name]):
            continue
        flat_type_map[col_name] = declared_type

    return flat_type_map


def cast_flat_field_types(df: pd.DataFrame, schema: Any) -> pd.DataFrame:
    """Cast flat (top-level) columns to their declared types from the schema.

    The semantic model declares types for flat columns (datetime, integer,
    float, boolean), but CSV-loaded data keeps them as ``object``/string.
    ``duckdb.connection.register()`` infers SQL types from Python objects, so
    without this step a ``datetime``-declared column stays ``VARCHAR`` in
    DuckDB, causing LLM-generated datetime code (``.dt.*``, ``.date()``) to
    fail at runtime.

    Uses the same per-type caster functions as the struct path, so behaviour is
    consistent (each caster falls back to the original value on parse failure).

    Args:
        df: DataFrame with flat columns that may hold string values.
        schema: A SemanticLayerSchema with declared column types.

    Returns:
        The DataFrame with flat column values cast to their declared types.
    """
    flat_type_map = _build_flat_field_type_map(df, schema)
    if not flat_type_map:
        return df

    for col_name, declared_type in flat_type_map.items():
        caster = _TYPE_CASTERS[declared_type]
        series = df[col_name]
        # For datetime columns, cast element-wise so we return datetime.date
        # values (DuckDB DATE, not TIMESTAMP), consistent with struct fields.
        df[col_name] = series.apply(caster)

    logger.info(
        "Cast flat field types for %d column(s): %s",
        len(flat_type_map),
        flat_type_map,
    )

    return df
