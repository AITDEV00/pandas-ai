"""
Reusable type detection utilities for pandas Series.

This module centralises all data-type heuristics so that handler.py,
column_enrichment.py, and any future consumers share one source of truth.
Functions rely on pandas built-in type inspection to minimise proprietary logic.
"""

import json
from typing import Optional

import pandas as pd


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
