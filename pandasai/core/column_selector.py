"""ColumnSelector — Step 1 of the 2-step column selection pipeline (Issues 1, 4, 5).

When a DataFrame has many columns (wide table), sending the full schema to the
LLM wastes tokens and hurts accuracy.  The ColumnSelector asks the LLM to pick
only the relevant columns/fields based on the user query, then builds a trimmed
DataFrame + schema for the code-generation step.

Usage (inside Agent._process_query)::

    selector = ColumnSelector(state)
    selected_names = selector.select(query)
    matched = selector.match_names_to_schema(selected_names, df)
    matched = selector.ensure_essential_columns(matched, df, query)
    trimmed_df = selector.build_trimmed_dataframe(df, matched)
"""

import json
import logging
import re
from typing import Dict, List, Optional

from pandasai.agent.state import AgentState
from pandasai.core.prompts.base import BasePrompt
from pandasai.helpers.semantic_matching import (
    _extract_short_name,
    bracket_col_has_any_field,
    decompose_squashed_name,
    extract_struct_parent,
    get_matching_schema_columns,
    is_bracket_child_of,
)

logger = logging.getLogger(__name__)


class ColumnSelector:
    """Select relevant columns from a wide DataFrame using LLM."""

    def __init__(self, state: AgentState):
        self._state = state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, query: str) -> List[str]:
        """Run Step 1: build prompt → call LLM → parse → validate.

        Returns a flat list of column/field names relevant to *query*.
        """
        prompt = self._build_prompt(query)
        response = self._state.config.llm.call(prompt, self._state)
        selected = self._parse_response(response)
        return self._validate_names(selected)

    def match_names_to_schema(
        self, names: List[str], df
    ) -> Dict[str, Optional[List[str]]]:
        """Map flat names returned by the LLM to schema columns.

        Returns a dict mapping DataFrame column names to:
          - ``None``  → flat column, include all of it
          - ``list``  → struct column, include only these inner field names
                        (using the canonical schema column names)
        """
        result: Dict[str, Optional[List[str]]] = {}

        # Pre-compute: which parents have actual data in the DataFrame?
        # A bracket-style name like "[Employee Master[Etihad Allowance]]" could
        # be either:
        #   (a) a flat column that uses bracket notation for naming
        #   (b) a struct inner field whose parent has data in df.columns
        #   (c) a phantom column — in the schema but with NO data at all
        #
        # A parent is considered a "real struct parent" if:
        #   1. It's declared as list[struct] in the schema, OR
        #   2. It has list[struct] bracket-style children in df.columns
        #   3. It has combined bracket-style children in df.columns where
        #      the schema column name is embedded as an inner field
        #
        # If a bracket-style schema column's parent is NOT a real struct parent
        # and the column itself is NOT in df.columns (directly or as an inner
        # field of a combined column), it's a phantom column.
        df_column_set = set(df.columns) if hasattr(df, 'columns') else set()
        struct_parent_names: set[str] = set()
        for col in df.schema.columns:
            if col.type == "list[struct]" and not col.name.startswith("["):
                struct_parent_names.add(col.name)
            elif col.type == "list[struct]" and col.name.startswith("["):
                p = extract_struct_parent(col.name)
                if p:
                    struct_parent_names.add(p)
        # Also add parents that have list[struct] bracket-style children in
        # df.columns (covers the "combined column" layout where the parent
        # isn't declared as list[struct] in the schema but the DataFrame has
        # combined bracket-style columns that ARE list[struct]).
        for col_name in df.columns:
            if col_name.startswith("[") and "]" in col_name:
                schema_col = next(
                    (c for c in df.schema.columns if c.name == col_name), None
                )
                if schema_col and schema_col.type == "list[struct]":
                    p = extract_struct_parent(col_name)
                    if p:
                        struct_parent_names.add(p)

        # Build a set of bracket-style column names that have corresponding
        # data in df.columns (either directly or as inner fields of combined
        # columns).  This is used to distinguish real columns from phantoms.
        # For example:
        #   "[Employee Leave Details[Leave Type]]" → NOT in df.columns directly,
        #   but IS an inner field of the combined column "[Employee Leave Details[Leave Type][Leave Duration (Days)]...]"
        #   "[Employee Master[Etihad Allowance]]" → NOT in df.columns directly,
        #   and NOT an inner field of any combined column → phantom
        real_bracket_col_names: set[str] = set()
        for col_name in df.columns:
            if col_name.startswith("[") and "]" in col_name:
                # Decompose combined column names into individual field names
                decomposed = decompose_squashed_name(col_name)
                for field_name in decomposed:
                    real_bracket_col_names.add(field_name)
                # Also add the combined column name itself
                real_bracket_col_names.add(col_name)

        for name in names:
            matches = get_matching_schema_columns(name, df.schema)
            if not matches:
                # Name might be a top-level column not in schema (e.g. squashed)
                # or an inner field name without brackets — try direct match
                schema_names = {col.name for col in df.schema.columns}
                if name in schema_names:
                    result[name] = None
                elif name.startswith("[") and "]" in name:
                    # The LLM may return inner field names (e.g.
                    # "[Employee Leave Details[Leave Type]]") that are NOT
                    # in the schema because the handler replaced them with a
                    # combined list[struct] column.  Check if this is an
                    # inner field of a known struct parent and has real data.
                    parent = extract_struct_parent(name)
                    has_real_data = name in real_bracket_col_names
                    if parent and (parent in struct_parent_names or has_real_data):
                        decomposed = decompose_squashed_name(name)
                        logger.debug(
                            "match: LLM=%r → no schema match, but struct inner field of parent=%r, decomposed=%s",
                            name, parent, decomposed,
                        )
                        if parent not in result:
                            result[parent] = []
                        if result[parent] is not None:
                            for field_name in decomposed:
                                if field_name not in result[parent]:
                                    result[parent].append(field_name)
                    else:
                        logger.debug("match_names_to_schema: no match for %r", name)
                elif "[" in name and not name.startswith("["):
                    # The LLM may return duckdb_key-style names like
                    # "Employee Leave Details[Leave Type]" (Parent[Field]
                    # without outer brackets).  Try wrapping in outer brackets
                    # and matching as a struct inner field.
                    bracket_wrapped = f"[{name}]"
                    parent = extract_struct_parent(bracket_wrapped)
                    has_real_data = bracket_wrapped in real_bracket_col_names
                    if parent and (parent in struct_parent_names or has_real_data):
                        decomposed = decompose_squashed_name(bracket_wrapped)
                        logger.debug(
                            "match: LLM=%r → duckdb_key style, wrapped=%r, parent=%r, decomposed=%s",
                            name, bracket_wrapped, parent, decomposed,
                        )
                        if parent not in result:
                            result[parent] = []
                        if result[parent] is not None:
                            for field_name in decomposed:
                                if field_name not in result[parent]:
                                    result[parent].append(field_name)
                    else:
                        logger.debug("match_names_to_schema: no match for %r", name)
                else:
                    logger.debug("match_names_to_schema: no match for %r", name)
                continue

            for matched_col in matches:
                if matched_col.name.startswith("[") and "]" in matched_col.name:
                    # ── KEY FIX ──────────────────────────────────────────
                    # If the matched column name exists directly in df.columns,
                    # it is a FLAT column that uses bracket notation for naming
                    # (e.g. "[Employee Master[Employee Name]]").  Treat it
                    # as a flat column, NOT as a struct inner field.
                    # ──────────────────────────────────────────────────────
                    if matched_col.name in df_column_set:
                        result[matched_col.name] = None
                        logger.debug("match: LLM=%r → schema=%r → FLAT (in df.columns)", name, matched_col.name)
                        continue

                    parent = extract_struct_parent(matched_col.name)

                    # Check if this column has corresponding data in the
                    # DataFrame (either as an inner field of a combined
                    # column, or as a direct bracket-style column).
                    has_real_data = matched_col.name in real_bracket_col_names

                    # If the parent IS a real struct parent (declared
                    # list[struct] or has list[struct] children in df.columns),
                    # OR if the column has real data via combined columns,
                    # treat this as a struct inner field.
                    if parent and (parent in struct_parent_names or has_real_data):
                        # Standard struct inner field handling
                        decomposed = decompose_squashed_name(matched_col.name)
                        logger.debug("match: LLM=%r → schema=%r → parent=%r, decomposed=%s", name, matched_col.name, parent, decomposed)
                        if parent not in result:
                            result[parent] = []
                        if result[parent] is not None:
                            for field_name in decomposed:
                                if field_name not in result[parent]:
                                    result[parent].append(field_name)
                    elif parent:
                        # Parent is NOT a real struct parent and the column
                        # itself is NOT in df.columns — this is a phantom
                        # column from the semantic model.  Treat as flat
                        # column so build_trimmed_dataframe can warn & skip.
                        result[matched_col.name] = None
                        logger.debug("match: LLM=%r → schema=%r → PHANTOM (parent %r has no data)", name, matched_col.name, parent)
                    else:
                        # Bracket name but no parent — keep as-is
                        result[matched_col.name] = None
                else:
                    result[matched_col.name] = None

        return result

    def ensure_essential_columns(
        self, matched: Dict[str, Optional[List[str]]], df, query: str
    ) -> Dict[str, Optional[List[str]]]:
        """Always include essential columns/inner-fields for matched parents.

        Only adds essential columns for parents that are **already in matched**.
        Does NOT pull in new parents from unrelated struct columns.

        Essential column rules:
          - **Flat columns**: add if id_like, datetime, or query-mentioned
          - **Struct inner fields**: add only if query-mentioned or the parent's
            primary id_like field (e.g. Employee Number).  We do NOT blanket-add
            all datetime/id_like inner fields — that would re-inflate the trimmed
            DataFrame with irrelevant columns.

        Inner-field semantic_type is checked from TWO sources:
          1. Schema column level (``col.semantic_type``) — from user's semantic model
          2. Enrichment level (``samples[field].semantic_type``) — auto-classified
        Both sources are checked in a single pass to avoid redundant logic.

        All inner-field names in the ``matched`` dict use the canonical schema
        column names (e.g. ``"[Employee Leave Details[Leave Type]]"``), matching
        the semantic model and the ``samples`` dict keys exactly.
        """
        logger.debug("ensure_essential_columns input: %s", matched)
        essential_added = []

        # Build a set of actual DataFrame column names to filter out phantoms.
        df_col_set = set(df.columns) if hasattr(df, 'columns') else set()

        # Build a lookup: parent_name → parent SchemaColumn (for samples access)
        parent_schema_lookup = {}
        for col in df.schema.columns:
            if col.type == "list[struct]" and not col.name.startswith("["):
                parent_schema_lookup[col.name] = col

        # --- Single pass over schema columns ---
        for col in df.schema.columns:
            # Determine the parent name for this schema column
            if col.name.startswith("["):
                parent = extract_struct_parent(col.name)
            else:
                parent = None

            # --- Flat columns: add if essential AND not phantom ---
            if not parent:
                if col.name not in matched:
                    # Skip phantom columns (in schema but not in df.columns)
                    if col.name not in df_col_set:
                        continue
                    is_essential = (
                        col.semantic_type == "id_like"
                        or col.name.lower() in query.lower()
                        or col.type == "datetime"
                    )
                    if is_essential:
                        matched[col.name] = None
                        essential_added.append(f"flat:{col.name} (type={col.type}, semantic={col.semantic_type})")
                continue

            # --- Struct inner fields: only for already-matched parents ---
            if parent not in matched:
                continue

            # Decompose squashed schema column names into individual fields.
            # e.g. "[Parent[Field1][Field2]]" → ["[Parent[Field1]]", "[Parent[Field2]]"]
            decomposed = decompose_squashed_name(col.name)
            for field_name in decomposed:
                short_name = _extract_short_name(field_name)
                is_essential = False

                # Query-mentioned inner field (use short name for query matching)
                if short_name and short_name.lower() in query.lower():
                    is_essential = True

                # Primary ID field for the parent — from schema column level
                if col.semantic_type == "id_like":
                    existing_fields = matched[parent]
                    has_id_already = existing_fields is not None and any(
                        sc.name in existing_fields
                        for sc in df.schema.columns
                        if extract_struct_parent(sc.name) == parent
                        and sc.semantic_type == "id_like"
                    )
                    if not has_id_already:
                        is_essential = True

                if is_essential:
                    if matched[parent] is None:
                        matched[parent] = []
                    if field_name not in matched[parent]:
                        matched[parent].append(field_name)
                        essential_added.append(f"struct:{parent}[{field_name}] (schema-level, type={col.type}, semantic={col.semantic_type})")

        # --- Second pass: enrichment-level semantic_type from samples ---
        # This catches id_like/query-mentioned fields that the schema column level
        # didn't catch (e.g. enrichment classified a field as id_like but the
        # user's semantic model didn't declare it).
        for col_name, inner_fields in list(matched.items()):
            if inner_fields is None:
                continue
            # Look up the parent schema column (non-bracket name) for samples
            schema_col = parent_schema_lookup.get(col_name)
            if not schema_col:
                # Also check bracket-style schema entries (exact name match)
                schema_col = next(
                    (c for c in df.schema.columns if c.name == col_name), None
                )
            if not schema_col:
                # Also check by parent name — the schema column may be a
                # squashed bracket-style name (e.g. "[Parent[Field1][Field2]]")
                # while col_name is just "Parent".
                schema_col = next(
                    (c for c in df.schema.columns
                     if c.type == "list[struct]" and is_bracket_child_of(c.name, col_name)),
                    None
                )
            if not schema_col or schema_col.type != "list[struct]":
                continue
            essential = set(inner_fields)
            if isinstance(schema_col.samples, dict):
                # Both inner_fields and samples keys now use the canonical
                # schema column names (e.g. "[Employee Leave Details[Leave Type]]").
                has_id_field = any(
                    field_name in essential
                    and isinstance(schema_col.samples.get(field_name), dict)
                    and schema_col.samples[field_name].get("semantic_type") == "id_like"
                    for field_name in essential
                )
                for field_name, field_info in schema_col.samples.items():
                    if isinstance(field_info, dict):
                        if field_info.get("semantic_type") == "id_like" and not has_id_field:
                            essential.add(field_name)
                            has_id_field = True
                            essential_added.append(f"struct:{col_name}[{field_name}] (enrichment-level id_like)")
                        # Check short name against query for query-mentioned fields
                        short = _extract_short_name(field_name)
                        if short and short.lower() in query.lower():
                            essential.add(field_name)
            matched[col_name] = list(essential)

        logger.debug("essential columns added: %s", essential_added)
        logger.debug("ensure_essential_columns output: %s", matched)
        return matched

    def build_trimmed_dataframe(
        self, df, matched: Dict[str, Optional[List[str]]]
    ):
        """Build trimmed copy of DataFrame with only selected columns/inner-fields.

        - Shallow copy of the DataFrame data (shares underlying buffers)
        - Deep copy of schema Column objects (we modify the samples dict)
        - Returns a proper PandasAI DataFrame preserving all metadata

        The ``matched`` dict's inner_fields use canonical schema column names
        (e.g. ``"[Employee Leave Details[Leave Type]]"``) matching the semantic
        model and the ``samples`` dict keys exactly.
        """
        from pandasai.dataframe.base import DataFrame as PAIDataFrame

        # inner_fields contains canonical schema column names (e.g.
        # "[Employee Leave Details[Leave Type]]"). Extract short names for
        # matching against DataFrame column bracket groups.
        def _short_names_from_inner_fields(fields: Optional[List[str]]) -> Optional[List[str]]:
            if fields is None:
                return None
            return [_extract_short_name(f) for f in fields]

        # 1. Column-level filtering — select only matched columns
        # For flat columns, the key in `matched` is the actual df column name.
        # For struct columns, the key is the parent name (e.g. "Employee Previous
        # Employer"), but df.columns contains the bracket-style inner field names
        # (e.g. "[Employee Previous Employer[Previous Employer Name]]").
        # We must resolve struct parent names to their actual DataFrame columns.
        kept_col_names = list(matched.keys())
        existing_flat_cols = [c for c in kept_col_names if c in df.columns]
        logger.debug("build_trimmed: kept_col_names=%s", kept_col_names)
        logger.debug("build_trimmed: existing_flat_cols=%s", existing_flat_cols)

        # Separate phantom columns (in schema but not in df.columns, value=None)
        # from actual struct parent columns (value is a list of inner fields).
        # Phantom columns occur when the semantic model declares columns that
        # don't exist in the actual data — they should be skipped with a warning.
        phantom_cols = []
        struct_parent_names = []
        for c in kept_col_names:
            if c in df.columns:
                continue  # already in existing_flat_cols
            if matched[c] is None:
                # Flat column that doesn't exist in df — it's a phantom column
                phantom_cols.append(c)
                logger.warning(
                    "build_trimmed: column %r selected but not in DataFrame — "
                    "phantom column from semantic model, skipping", c
                )
            else:
                # Has inner fields — treat as struct parent
                struct_parent_names.append(c)
        logger.debug("build_trimmed: phantom_cols=%s", phantom_cols)
        logger.debug("build_trimmed: struct_parent_names=%s", struct_parent_names)
        struct_df_cols = []
        for parent in struct_parent_names:
            inner_fields = matched[parent]
            # Extract short names for bracket matching against DataFrame columns
            short_fields = _short_names_from_inner_fields(inner_fields)
            # Collect all DataFrame columns that are bracket-style children
            # of this parent, regardless of layout (separate or combined).
            parent_df_cols = [
                col_name for col_name in df.columns
                if is_bracket_child_of(col_name, parent)
            ]
            logger.debug("build_trimmed: parent=%r, inner_fields=%s, df_children=%s", parent, inner_fields, parent_df_cols)
            if short_fields is None:
                # Whole struct — include all bracket-style columns for this parent
                struct_df_cols.extend(parent_df_cols)
            else:
                # Specific inner fields — match by field name
                for col_name in parent_df_cols:
                    if bracket_col_has_any_field(col_name, short_fields):
                        struct_df_cols.append(col_name)
                        logger.debug("build_trimmed:   ✓ %s", col_name)
                    else:
                        logger.debug("build_trimmed:   ✗ %s", col_name)

        all_kept_cols = list(dict.fromkeys(existing_flat_cols + struct_df_cols))
        logger.debug("build_trimmed: final columns=%s", all_kept_cols)
        if not all_kept_cols:
            return df  # Safety: if nothing matched, return original

        # Pandas column slicing may lose custom metadata — wrap explicitly
        sliced = df[all_kept_cols]
        if not isinstance(sliced, PAIDataFrame):
            trimmed_df = PAIDataFrame(sliced)
            trimmed_df._table_name = getattr(df, "_table_name", None)
            trimmed_df.path = getattr(df, "path", None)
            trimmed_df._agent = getattr(df, "_agent", None)
        else:
            trimmed_df = sliced

        # 2. Schema-level filtering — include matched columns + their bracket-style
        # inner field schema entries.
        if df.schema and df.schema.columns:
            # Build a set of schema column names to keep
            kept_schema_names = set()

            for col_name, inner_fields in matched.items():
                # Skip phantom columns (in schema but not in df.columns)
                if col_name in phantom_cols:
                    continue

                if col_name in {c.name for c in df.schema.columns}:
                    # Parent name is in schema — keep it
                    kept_schema_names.add(col_name)
                else:
                    # Parent name is NOT in schema (bracket-style columns) —
                    # keep the bracket-style schema entries for the inner fields.
                    # Same two layouts as DataFrame columns:
                    #   A) Separate: "[Parent[Field1]]", "[Parent[Field2]]"
                    #   B) Combined: "[Parent[Field1][Field2][Field3]]"
                    parent_schema_cols = [
                        sc for sc in df.schema.columns
                        if is_bracket_child_of(sc.name, col_name)
                    ]
                    if inner_fields is None:
                        # Whole struct — keep all bracket-style entries for this parent
                        for sc in parent_schema_cols:
                            kept_schema_names.add(sc.name)
                    else:
                        # Specific inner fields — inner_fields now contains
                        # decomposed individual field names (e.g.
                        # "[Parent[Field1]]", "[Parent[Field2]]").
                        # Match by checking:
                        #   1. Direct match: schema column name is in inner_fields
                        #   2. Squashed match: schema column is a squashed name
                        #      that contains inner fields from inner_fields
                        for sc in parent_schema_cols:
                            if sc.name in inner_fields:
                                kept_schema_names.add(sc.name)
                            else:
                                # Check if this is a squashed schema column
                                # that contains any of the inner fields
                                sc_decomposed = decompose_squashed_name(sc.name)
                                if any(f in sc_decomposed for f in inner_fields):
                                    kept_schema_names.add(sc.name)

            trimmed_schema_columns = []
            for col in df.schema.columns:
                if col.name not in kept_schema_names:
                    continue
                # For struct parent columns with specific inner fields, filter samples.
                # Resolve bracket-style names (e.g. "[Employee Master[Employee Name]]")
                # to their parent key in matched (e.g. "Employee Master").
                inner_fields = matched.get(col.name)
                if inner_fields is None and col.name.startswith("["):
                    # Bracket-style column — look up by parent name
                    parent = extract_struct_parent(col.name)
                    if parent and parent in matched:
                        inner_fields = matched[parent]
                if inner_fields is not None and col.type == "list[struct]":
                    trimmed_col = col.model_copy(deep=True)
                    if isinstance(trimmed_col.samples, dict):
                        # Normalize inner_fields for comparison:
                        # - Strip outer brackets: "[Parent[Field]]" → "Parent[Field]"
                        # - This matches the flat keys used in the samples dict
                        normalized_fields = set()
                        for f in inner_fields:
                            if f.startswith("[") and f.endswith("]"):
                                normalized_fields.add(f[1:-1])
                            else:
                                normalized_fields.add(f)
                        # Also keep original names for backward compatibility
                        all_fields = set(inner_fields) | normalized_fields
                        trimmed_col.samples = {
                            k: v
                            for k, v in trimmed_col.samples.items()
                            if k in all_fields
                        }
                    trimmed_schema_columns.append(trimmed_col)
                else:
                    trimmed_schema_columns.append(col)

            # Deep copy the schema to avoid mutating the original
            trimmed_schema = df.schema.model_copy(deep=True)
            trimmed_schema.columns = trimmed_schema_columns
            trimmed_df.schema = trimmed_schema
            logger.debug("build_trimmed: kept_schema_names=%s", kept_schema_names)
            logger.debug("build_trimmed: final schema=%s", [c.name for c in trimmed_schema_columns])

        return trimmed_df

    # ------------------------------------------------------------------
    # Step 1 Memory (Issue 7)
    # ------------------------------------------------------------------

    def build_step1_memory(self) -> "Memory":
        """Create a temporary Memory for Step 1 with reduced size limit.

        Step 1 only needs recent context to understand the query — we use
        a smaller ``memory_size`` (default 5) to reduce token usage.
        The original memory is NOT modified.
        """
        from pandasai.helpers.memory import Memory

        original = self._state.memory
        step1_memory = Memory(
            memory_size=self._state.config.column_selection_memory_size,
            agent_description=original.agent_description,
        )
        for msg in original.all():
            step1_memory.add(msg["message"], msg["is_user"])

        return step1_memory

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, query: str) -> BasePrompt:
        """Build the column selection prompt with flat/struct column split.

        Filters out **phantom columns** — schema columns that don't exist in the
        actual DataFrame — so the LLM never selects columns that can't be queried.

        A schema column is considered "real" (not phantom) if:
          1. Its name exists directly in df.columns, OR
          2. It's an inner field of a combined column in df.columns
             (e.g. "[Employee Leave Details[Leave Type]]" is an inner field of
             the combined column "[Employee Leave Details[Leave Type][Leave Duration (Days)]...]")
        """
        flat_columns = []
        struct_columns = []
        table_name = "data"
        table_desc = ""
        for df in self._state.dfs:
            # Use the first DataFrame's name/description as the primary
            if table_name == "data":
                table_name = getattr(df.schema, "name", "data") if df.schema else "data"
                table_desc = getattr(df.schema, "description", "") if df.schema else ""

            # Build a set of real column names from df.columns.
            # Include both direct column names and decomposed inner field names
            # from combined columns.
            df_col_set = set(df.columns) if hasattr(df, 'columns') else set()
            real_col_names: set[str] = set(df_col_set)
            from pandasai.helpers.semantic_matching import decompose_squashed_name
            for col_name in df_col_set:
                if col_name.startswith("[") and "]" in col_name:
                    decomposed = decompose_squashed_name(col_name)
                    for field_name in decomposed:
                        real_col_names.add(field_name)

            phantom_count = 0

            for col in df.schema.columns:
                is_real = col.name in real_col_names
                if col.type == "list[struct]":
                    if is_real:
                        struct_columns.append(col)
                    else:
                        phantom_count += 1
                        logger.debug(
                            "_build_prompt: skipping phantom struct column %r "
                            "(not in df.columns)", col.name
                        )
                else:
                    if is_real:
                        flat_columns.append(col)
                    else:
                        phantom_count += 1
                        logger.debug(
                            "_build_prompt: skipping phantom flat column %r "
                            "(not in df.columns)", col.name
                        )

            if phantom_count > 0:
                logger.info(
                    "_build_prompt: filtered %d phantom column(s) from "
                    "column selection prompt (schema has columns not in data)",
                    phantom_count,
                )

        from pandasai.core.prompts.select_columns import SelectColumnsPrompt

        return SelectColumnsPrompt(
            context=self._state,
            query=query,
            flat_columns=flat_columns,
            struct_columns=struct_columns,
            table_name=table_name,
            table_description=table_desc,
        )

    def _parse_response(self, response: str) -> List[str]:
        """Parse LLM response into flat list of names.

        Handles multiple JSON formats:
          - ``{"selected": ["col1", "col2"]}``
          - ``{"selected_columns": ["col1", "col2"]}``
          - ``{"Parent": ["field1", "field2"]}``
        """
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning("Column selection: failed to parse JSON from LLM")
                return []

            # Standard format: {"selected": [...]}
            selected = data.get("selected", data.get("selected_columns", []))
            if isinstance(selected, list):
                return [str(s) for s in selected]

            # Dict format: {"Parent": ["field1", "field2"], "FlatCol": []}
            if isinstance(selected, dict):
                names = []
                for k, v in selected.items():
                    names.append(k)
                    if isinstance(v, list):
                        names.extend(v)
                return names

        return []

    def _validate_names(self, names: List[str]) -> List[str]:
        """Basic validation — remove obviously invalid entries.

        Also sanitizes LLM-returned names that have stray single quotes
        around the parent part (e.g. ``'Employee Leave Details'[Leave Type]``
        instead of ``Employee Leave Details[Leave Type]``).  The LLM sometimes
        adds these when it sees ``rec['Parent[Field]']`` in the prompt and
        misinterprets the single quotes as SQL string delimiters.
        """
        sanitized = []
        for n in names:
            if not n or not n.strip():
                continue
            # Strip stray single quotes around the parent part of
            # Parent[Field] names.  E.g.:
            #   "'Employee Leave Details'[Leave Type]"
            #   → "Employee Leave Details[Leave Type]"
            # Only strip if the name starts with a single quote and
            # contains brackets — this pattern indicates the LLM wrapped
            # the parent in quotes it saw from rec['...'] syntax.
            if n.startswith("'") and "[" in n:
                # Remove leading/trailing single quotes around the parent
                n = re.sub(r"^'+", "", n)
                # Also remove any trailing single quotes before the bracket
                n = re.sub(r"'+\[", "[", n)
            sanitized.append(n)
        return sanitized
