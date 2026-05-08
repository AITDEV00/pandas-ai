import json
import random
import typing

if typing.TYPE_CHECKING:
    from ..dataframe.base import DataFrame


class DataframeSerializer:
    MAX_COLUMN_TEXT_LENGTH = 200

    @classmethod
    def serialize(cls, df: "DataFrame", dialect: str = "postgres", config=None) -> str:
        """
        Convert df to a CSV-like format wrapped inside <table> tags, truncating long text values, and serializing only a subset of rows using df.head().

        Args:
            df (pd.DataFrame): Pandas DataFrame
            dialect (str): Database dialect (default is "postgres")
            config (Config): Configuration containing column value enrichment settings

        Returns:
            str: Serialized DataFrame string
        """
        if config is None:
            from pandasai.config import ConfigManager
            config = ConfigManager.get()

        # Start building the table metadata
        dataframe_info = f'<table dialect="{dialect}" table_name="{df.schema.name}"'

        # Add description attribute if available
        if df.schema.description is not None:
            dataframe_info += f' description="{df.schema.description}"'

        if df.schema.columns:
            from pandasai.dataframe.virtual_dataframe import VirtualDataFrame
            from pandasai.helpers.column_enrichment import ColumnValueExtractor
            from pandasai.helpers.semantic_matching import get_matching_schema_columns, merge_descriptions
            from pandasai.helpers.type_determination import determine_series_type, is_list_struct_column

            # Build a fast lookup: schema column name -> schema Column object
            schema_by_name = {col.name: col for col in df.schema.columns}

            columns = []
            for col_name in df.columns:
                # --- Resolve schema entry for this dataframe column ---
                schema_col = schema_by_name.get(col_name)

                # Detect list[struct] from actual data (needed even when schema
                # has a direct match, because schema type may be 'string' for these)
                is_list_struct = is_list_struct_column(df[col_name])

                if schema_col:
                    # Direct match found in schema (normal column)
                    col_dict = schema_col.model_dump(exclude_none=True)
                    # Override type if actual data is list[struct]
                    if is_list_struct:
                        col_dict["type"] = "list[struct]"
                        col_dict["semantic_type"] = "struct"
                else:
                    # No direct match — could be a squashed JSON array column
                    # e.g. "[Table[Col1][Col2]]" with schema entries "[Table[Col1]]", "[Table[Col2]]"
                    matched = get_matching_schema_columns(col_name, df.schema)
                    merged_desc = merge_descriptions(matched) if matched else None

                    if is_list_struct:
                        col_dict = {"name": col_name, "type": "list[struct]", "semantic_type": "struct"}
                    else:
                        col_dict = {"name": col_name, "type": determine_series_type(df[col_name])}

                    if merged_desc:
                        col_dict["description"] = merged_desc

                if config.enrich_column_values:
                    # Lazy extraction for local dataframes
                    if not isinstance(df, VirtualDataFrame) and col_dict.get("samples") is None:
                        result = ColumnValueExtractor.classify_and_extract(
                            df[col_name],
                            col_dict.get("type"),
                            config.categorical_max_unique,
                            df.schema
                        )
                        if result["samples"] is not None:
                            col_dict["samples"] = result["samples"]
                        if result["semantic_type"] is not None:
                            col_dict["semantic_type"] = result["semantic_type"]
                else:
                    # Strip out samples if enrichment disabled
                    col_dict.pop("samples", None)

                columns.append(col_dict)

            if config.enrich_column_values and any("samples" in c for c in columns):
                columns = cls._apply_token_budget(columns, config)

            dataframe_info += f' columns="{json.dumps(columns, ensure_ascii=False)}"'

        dataframe_info += f' dimensions="{df.rows_count}x{df.columns_count}">'

        # Truncate long values
        sample_size = min(getattr(config, "sample_head_size", 10), len(df))
        df_truncated = cls._truncate_dataframe(
            df.head(n=sample_size) if sample_size > 0 else df.head(0)
        )

        # Convert to CSV format
        dataframe_info += f"\n{df_truncated.to_csv(index=False)}"

        # Close the table tag
        dataframe_info += "</table>\n"

        return dataframe_info

    @classmethod
    def _apply_token_budget(cls, columns: list, config) -> list:
        if config.column_values_token_budget is not None:
            budget = config.column_values_token_budget
        else:
            budget = int(config.llm_context_window * config.column_values_budget_ratio)

        def _token_cost(col_dict: dict) -> int:
            samples = col_dict.get("samples")
            if not samples:
                return 0
            
            # Handle nested struct samples recursively
            if isinstance(samples, dict):
                # Recursively count nested struct samples
                total = 0
                for inner_col, inner_data in samples.items():
                    if isinstance(inner_data, dict):
                        total += len(json.dumps(inner_data, ensure_ascii=False)) // 4
                    else:
                        total += len(json.dumps({inner_col: inner_data}, ensure_ascii=False)) // 4
                return total
            
            # Rough estimate: ~4 chars per token
            return len(json.dumps({"samples": samples}, ensure_ascii=False)) // 4

        costs = {i: _token_cost(col) for i, col in enumerate(columns)}
        total = sum(costs.values())
        if total <= budget:
            return columns

        enriched_indices = [i for i, c in costs.items() if c > 0]
        if not enriched_indices:
            return columns

        per_col_share = budget // max(len(enriched_indices), 1)

        # Split into under vs over budget
        under_cost = sum(c for c in costs.values() if c <= per_col_share)
        remaining = budget - under_cost
        over_indices = [i for i, c in costs.items() if c > per_col_share]
        over_total = sum(costs[i] for i in over_indices)

        import copy
        result = [copy.deepcopy(col) for col in columns]
        for i in over_indices:
            col = result[i]
            proportion = costs[i] / over_total if over_total > 0 else 0
            col_token_budget = max(1, int(remaining * proportion))

            samples = col.get("samples")
            if isinstance(samples, list):
                # How many items fit in this column's token budget?
                # Assume ~7 chars (1.75 tokens) per word/item
                max_items = max(1, col_token_budget * 4 // 7)
                if len(samples) > max_items:
                    col["samples"] = sorted(random.sample(samples, max_items))
            elif isinstance(samples, dict):
                # Handle nested struct samples
                # Check if this is a struct vocabulary (has 'type' key in values)
                is_struct_vocab = any(
                    isinstance(v, dict) and "type" in v 
                    for v in samples.values()
                )
                
                if is_struct_vocab:
                    # Reduce samples per inner column proportionally
                    inner_cols = list(samples.keys())
                    inner_budget = max(1, col_token_budget // max(len(inner_cols), 1))
                    
                    for inner_col in inner_cols:
                        inner_data = samples[inner_col]
                        if isinstance(inner_data, dict):
                            inner_samples = inner_data.get("samples")
                            if isinstance(inner_samples, list) and len(inner_samples) > 3:
                                # Limit to 3 samples per inner column
                                max_inner = max(1, inner_budget * 4 // 7)
                                if len(inner_samples) > max_inner:
                                    samples[inner_col]["samples"] = random.sample(
                                        inner_samples, min(3, max_inner)
                                    )
                            elif isinstance(inner_samples, dict):
                                # Drop examples from numeric ranges if tight budget
                                if inner_budget < 5 and "examples" in inner_samples:
                                    samples[inner_col]["samples"] = {
                                        k: v for k, v in inner_samples.items() 
                                        if k != "examples"
                                    }
                else:
                    # If numeric range is over budget, drop examples list
                    if col_token_budget < 5:
                        col["samples"] = {k: v for k, v in samples.items() if k != "examples"}

        return result

    @classmethod
    def _truncate_dataframe(cls, df: "DataFrame") -> "DataFrame":
        """Truncates string values exceeding MAX_COLUMN_TEXT_LENGTH, and converts JSON-like values to truncated strings."""

        def truncate_value(value):
            if isinstance(value, (dict, list)):  # Convert JSON-like objects to strings
                value = json.dumps(value, ensure_ascii=False)

            if isinstance(value, str) and len(value) > cls.MAX_COLUMN_TEXT_LENGTH:
                return f"{value[: cls.MAX_COLUMN_TEXT_LENGTH]}…"
            return value

        return df.apply(lambda row: row.apply(truncate_value), axis=1)
