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

        for name in names:
            matches = get_matching_schema_columns(name, df.schema)
            if not matches:
                # Name might be a top-level column not in schema (e.g. squashed)
                # or an inner field name without brackets — try direct match
                schema_names = {col.name for col in df.schema.columns}
                if name in schema_names:
                    result[name] = None
                else:
                    logger.debug("match_names_to_schema: no match for %r", name)
                continue

            for matched_col in matches:
                if matched_col.name.startswith("[") and "]" in matched_col.name:
                    parent = extract_struct_parent(matched_col.name)
                    # Decompose squashed schema column names into individual
                    # field names that match the samples dict keys.
                    # e.g. "[Parent[Field1][Field2][Field3]]" →
                    #   ["[Parent[Field1]]", "[Parent[Field2]]", "[Parent[Field3]]"]
                    # This ensures inner_fields entries match samples dict keys
                    # like "[Parent[Field1]]" rather than the full squashed name.
                    decomposed = decompose_squashed_name(matched_col.name)
                    logger.debug("match: LLM=%r → schema=%r → parent=%r, decomposed=%s", name, matched_col.name, parent, decomposed)
                    if parent:
                        if parent not in result:
                            result[parent] = []
                        if result[parent] is not None:
                            for field_name in decomposed:
                                if field_name not in result[parent]:
                                    result[parent].append(field_name)
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

            # --- Flat columns: add if essential ---
            if not parent:
                if col.name not in matched:
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

        # For struct parent names not found in df.columns, find the bracket-style
        # DataFrame columns that belong to that parent.
        #
        # Two possible layouts in df.columns:
        #   A) Separate columns per inner field:
        #        "[Parent[Field1]]", "[Parent[Field2]]", ...
        #   B) One combined column with all inner fields:
        #        "[Parent[Field1][Field2][Field3]]"
        struct_parent_names = [c for c in kept_col_names if c not in df.columns]
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
                        # Both inner_fields and samples keys now use the
                        # canonical schema column names, so direct comparison
                        # works without any name transformation.
                        trimmed_col.samples = {
                            k: v
                            for k, v in trimmed_col.samples.items()
                            if k in inner_fields
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
        """Build the column selection prompt with flat/struct column split."""
        flat_columns = []
        struct_columns = []
        table_name = "data"
        table_desc = ""
        for df in self._state.dfs:
            # Use the first DataFrame's name/description as the primary
            if table_name == "data":
                table_name = getattr(df.schema, "name", "data") if df.schema else "data"
                table_desc = getattr(df.schema, "description", "") if df.schema else ""
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
        """Basic validation — remove obviously invalid entries."""
        return [n for n in names if n and len(n.strip()) > 0]
