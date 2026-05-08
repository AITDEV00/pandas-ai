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


# ------------------------------------------------------------------
# Bracket-convention helpers (used by ColumnSelector)
# ------------------------------------------------------------------


def extract_struct_parent(bracket_name: str) -> Optional[str]:
    """Extract parent struct column name from bracket convention.

    ``'[Employee Achievements[Customary Name]]'`` → ``'Employee Achievements'``
    ``'[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]'``
        → ``'Employee Achievements'``
    ``'Employee Name'`` → ``None``
    """
    if not bracket_name.startswith("["):
        return None
    inner = bracket_name[1:-1]
    parent_end = inner.find("[")
    if parent_end > 0:
        return inner[:parent_end]
    return None


def is_bracket_child_of(col_name: str, parent: str) -> bool:
    """Check if *col_name* is a bracket-style inner field of *parent*.

    ``is_bracket_child_of('[Emp[Name]]', 'Emp')`` → True
    ``is_bracket_child_of('Emp', 'Emp')`` → False
    ``is_bracket_child_of('[Other[Name]]', 'Emp')`` → False
    """
    if not col_name.startswith("["):
        return False
    inner = col_name[1:-1]
    bracket_pos = inner.find("[")
    if bracket_pos < 0:
        return False
    return inner[:bracket_pos] == parent


def extract_field_from_llm_name(name: str) -> Optional[str]:
    """Extract the inner field name from an LLM-returned column name.

    The LLM may return names in two formats:
      - Without outer brackets: ``Parent[Field]``  → ``Field``
      - With outer brackets:    ``[Parent[Field]]`` → ``Field``

    ``'Employee Achievements[Customary Name]'``   → ``'Customary Name'``
    ``'[Employee Achievements[Customary Name]]'``  → ``'Customary Name'``
    ``'Employee Previous Employer[Start Date]'``   → ``'Start Date'``
    ``'[Employee Previous Employer[Start Date]]'`` → ``'Start Date'``
    ``'Employee Name'``                            → ``None``
    """
    # If the name starts with '[', it uses the bracket convention —
    # strip the outer brackets first so we only deal with the inner structure.
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]

    bracket_pos = name.find("[")
    if bracket_pos < 0:
        return None
    # Everything after the first '[' up to (but not including) the last ']'
    inner = name[bracket_pos + 1 :]
    if inner.endswith("]"):
        inner = inner[:-1]
    return inner if inner else None


def bracket_col_has_any_field(col_name: str, fields: list) -> bool:
    """Check if a bracket-style column contains any of the specified inner fields.

    Handles both separate and combined column layouts:
      - Separate: ``[Parent[Field1]]`` → checks if ``Field1`` is in *fields*
      - Combined: ``[Parent[Field1][Field2][Field3]]`` → checks if any
        of ``Field1``, ``Field2``, ``Field3`` is in *fields*
    """
    if not col_name.startswith("[") or not col_name.endswith("]"):
        return False
    # Strip the outer brackets
    inner = col_name[1:-1]
    # Find all [Field] groups after the parent name.
    # e.g. "Parent[Field1][Field2]" → extract "Field1", "Field2"
    # e.g. "Parent[Field1]" → extract "Field1"
    inner_fields_in_col = re.findall(r'\[([^\[\]]+)\]', inner)
    return any(f in inner_fields_in_col for f in fields)
