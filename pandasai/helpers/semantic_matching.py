"""
Modular matching strategies for resolving DataFrame column names against SemanticLayerSchema entries.

This file is intentionally kept separate so that new matching heuristics
(regex, fuzzy, alias tables, etc.) can be added without touching enrichment or serialization logic.
"""

import re
from typing import Any, List, Optional


def match_column_details_to_schema(col_name: str, df_schema: Any) -> dict:
    """
    Matches a single column name to a SemanticLayerSchema entry and returns
    both type and description.

    Returns a dict with 'type' (str | None) and 'description' (str | None).
    """
    matches = get_matching_schema_columns(col_name, df_schema)
    if matches:
        col = matches[0]
        return {"type": col.type, "description": getattr(col, "description", None)}
    return {"type": None, "description": None}


def get_matching_schema_columns(col_name: str, df_schema: Any) -> List:
    """
    Returns all SemanticLayerSchema Column objects whose name matches ``col_name``.

    This supports the squashed column convention: if the dataframe column is
    ``[Employee Achievements[Customary Name][Manager OA Comments]]``, this function
    will return schema entries for both ``[Employee Achievements[Customary Name]]``
    and ``[Employee Achievements[Manager OA Comments]]``.
    """
    if not df_schema or not hasattr(df_schema, "columns") or not df_schema.columns:
        return []

    results = []
    for schema_col in df_schema.columns:
        # Strategy 1: Exact match
        if schema_col.name == col_name:
            results.append(schema_col)
            continue

        # Strategy 2: Inner column match — schema name ends with [col_name]]
        #   e.g. schema has "[Employee Master[Employee Name]]", col_name is "Employee Name"
        if schema_col.name.endswith(f"[{col_name}]]"):
            results.append(schema_col)
            continue

        # Strategy 2b: Prefixed inner column match — col_name contains brackets
        #   e.g. col_name is "Employee Performance[Calculated Rating]",
        #   schema has "[Employee Performance[Calculated Rating][Normalized Performance Rating]]"
        #   In the schema, the bracket group is "[Employee Performance[Calculated Rating]"
        #   (one closing bracket), not "[Employee Performance[Calculated Rating]]" (two).
        if "[" in col_name:
            # Strip trailing ] from col_name's inner brackets to match schema format
            bracket_group = f"[{col_name}"
            if bracket_group in schema_col.name:
                results.append(schema_col)
                continue

        # Strategy 3: Squashed parent match — col_name contains multiple bracket groups
        #   e.g. col_name is "[Table[Col1][Col2]]", schema has "[Table[Col1]]"
        if _is_inner_column_of(schema_col.name, col_name):
            results.append(schema_col)

    return results


def merge_descriptions(schema_columns: List) -> Optional[str]:
    """
    Merge the descriptions from multiple matched schema columns into a single string.
    Returns None if no descriptions are available.
    """
    descriptions = []
    for col in schema_columns:
        if col.description:
            # Extract the short column name from the bracket convention
            short_name = _extract_short_name(col.name)
            descriptions.append(f"{short_name}: {col.description}")
    return " | ".join(descriptions) if descriptions else None


def _extract_short_name(schema_name: str) -> str:
    """Extract the innermost column name from a bracket convention name.

    '[Employee Master[Employee Name]]' -> 'Employee Name'
    'plain_name' -> 'plain_name'
    """
    # Find the last bracketed segment
    match = re.search(r"\[([^\[\]]+)\]\]$", schema_name)
    if match:
        return match.group(1)
    return schema_name


def _is_inner_column_of(schema_name: str, df_col_name: str) -> bool:
    """Check if ``schema_name`` represents one of the inner columns inside ``df_col_name``.

    For example:
        schema_name  = '[Employee Achievements[Customary Name]]'
        df_col_name  = '[Employee Achievements[Customary Name][Manager OA Comments]]'
        -> True, because 'Customary Name' appears as a bracket group in df_col_name.
    """
    short = _extract_short_name(schema_name)
    if short == schema_name:
        return False  # Not in bracket convention, skip
    return f"[{short}]" in df_col_name
