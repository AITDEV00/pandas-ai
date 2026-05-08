import math
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pandasai.helpers.type_determination import determine_series_type, is_list_struct_column


class ColumnValueExtractor:
    """Extracts semantic value metadata from a pandas Series, per column type."""

    @classmethod
    def classify_and_extract(
        cls,
        series: pd.Series,
        col_type: str,
        categorical_max_unique: int = 50,
        df_schema: Any = None,
    ) -> Dict[str, Any]:
        """Extract samples and semantic_type in a single pass.

        Returns a dict with keys:
          - ``samples``: the enrichment result (list, dict, or None)
          - ``semantic_type``: one of ``VALID_SEMANTIC_TYPES`` or None

        This avoids the double-classification that occurs when calling
        ``_classify_string_column()`` and ``extract()`` separately for
        string columns.
        """
        # list[struct] columns always have semantic_type "struct"
        if is_list_struct_column(series):
            return {
                "samples": cls._extract_struct_vocabulary(series, categorical_max_unique, df_schema),
                "semantic_type": "struct",
            }

        # String columns: classify once, then extract using the classification
        if col_type == "string":
            # Fast check if it's actually datetime masquerading as string
            sample_strs = series.dropna().head(20).astype(str)
            if not sample_strs.empty and sample_strs.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.8:
                return {"samples": cls._extract_datetime(series), "semantic_type": None}

            classification = cls._classify_string_column(series, categorical_max_unique)
            samples = cls._extract_string(series, categorical_max_unique, _classification=classification)
            return {"samples": samples, "semantic_type": classification}

        # All other column types have no semantic_type
        samples = cls.extract(series, col_type, categorical_max_unique, df_schema)
        return {"samples": samples, "semantic_type": None}

    @classmethod
    def extract(
        cls,
        series: pd.Series,
        col_type: str,
        categorical_max_unique: int = 50,
        df_schema: Any = None
    ) -> Optional[Any]:
        """
        Returns samples for a column Series to be fed to the LLM.
        """
        # --- INTERCEPT LIST OF STRUCTS ---
        # If the column contains list-of-dict values, extract struct vocabulary.
        # This prevents fallthrough to .nunique() which cannot handle list values.
        if is_list_struct_column(series):
            return cls._extract_struct_vocabulary(series, categorical_max_unique, df_schema)

        if col_type == "string":
            # Fast check if it's actually datetime masquerading as string
            sample_strs = series.dropna().head(20).astype(str)
            if not sample_strs.empty and sample_strs.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.8:
                return cls._extract_datetime(series)
            return cls._extract_string(series, categorical_max_unique)
        elif col_type in ("integer", "float"):
            return cls._extract_numeric(series)
        elif col_type == "datetime":
            return cls._extract_datetime(series)
        elif col_type == "boolean":
            return cls._extract_boolean(series)
        return None

    @classmethod
    def _extract_struct_vocabulary(
        cls, series: pd.Series, categorical_max_unique: int, df_schema: Any
    ) -> Optional[Dict]:
        """Extract struct field vocabulary from a list[struct] column.

        Flattens all struct dicts into a temporary DataFrame, then extracts
        samples for each inner column using the same classification logic.
        """
        # Find the first non-empty list of dicts to determine the struct shape
        first_nonempty = next(
            (v for v in series.dropna() if isinstance(v, list) and v and isinstance(v[0], dict)),
            None
        )
        if first_nonempty is None:
            return None

        all_structs = [struct for row_list in series.dropna() for struct in row_list if isinstance(struct, dict)]
        if not all_structs:
            return None

        from pandasai.helpers.semantic_matching import (
            _extract_short_name,
            get_matching_schema_columns,
            match_column_details_to_schema,
        )

        temp_df = pd.DataFrame(all_structs)
        struct_vocabulary = {}
        for inner_col in temp_df.columns:
            inner_series = temp_df[inner_col]
            # Use the schema column name as the samples key (the canonical name
            # from the semantic model), falling back to the raw pandas column
            # name if no schema match is found.
            schema_matches = get_matching_schema_columns(inner_col, df_schema)
            schema_key = schema_matches[0].name if schema_matches else inner_col
            details = match_column_details_to_schema(inner_col, df_schema)
            inner_type = details["type"]
            inner_desc = details["description"]

            # Fallback to pandas heuristics
            # Also: if the schema returned list[struct], it matched the parent
            # squashed column instead of an actual inner field.  An inner field
            # of a struct cannot itself be list[struct] (DuckDB doesn't support
            # nested list[struct] in UNNEST), so this is a false match.
            if not inner_type or inner_type == "unknown" or inner_type == "list[struct]":
                inner_type = determine_series_type(inner_series)

            inner_samples = cls.extract(inner_series, inner_type, categorical_max_unique, df_schema)
            # Classify string inner columns so we always set semantic_type
            inner_semantic_type = None
            if inner_type == "string":
                try:
                    inner_semantic_type = cls._classify_string_column(inner_series, categorical_max_unique)
                except Exception:
                    inner_semantic_type = None

            # For id_like inner fields, _extract_string (called by extract())
            # now returns up to 5 representative values, so inner_samples
            # should already be populated.  The fallback below is a safety
            # net in case extract() returned None for an older code path.
            if inner_samples is None and inner_semantic_type == "id_like":
                sample_vals = inner_series.dropna().unique().tolist()
                inner_samples = sorted(sample_vals[:5]) if sample_vals else None

            if inner_samples:
                inner_entry = {
                    "type": inner_type,
                    "samples": inner_samples,
                    "short_name": _extract_short_name(schema_key),
                }
                if inner_desc:
                    inner_entry["description"] = inner_desc
                if inner_semantic_type is not None:
                    inner_entry["semantic_type"] = inner_semantic_type
                struct_vocabulary[schema_key] = inner_entry

        return struct_vocabulary if struct_vocabulary else None

    @classmethod
    def _classify_string_column(
        cls, series: pd.Series, max_unique: int
    ) -> str:
        """Returns 'categorical', 'freetext', or 'id_like' based on multi-signal classifier."""
        n_total = series.dropna().shape[0]
        if n_total == 0:
            return "id_like"

        n_unique = series.dropna().nunique()
        avg_words = series.dropna().astype(str).apply(lambda v: len(str(v).split())).mean()

        # Signal 1: Paragraphs/Free-text — multi-word cells are ALWAYS free-text
        if avg_words > 4.0:
            return "freetext"

        # Signal 2: ID-like for highly unique short strings
        if n_unique == n_total and n_total > 5 and avg_words < 2.0:
            # Check length variance (IDs usually have consistent lengths)
            str_lengths = series.dropna().astype(str).apply(len)
            if str_lengths.mean() > 0 and (str_lengths.std() / str_lengths.mean()) < 0.2:
                return "id_like"

        # Signal 3: Absolute cap
        if n_unique <= max_unique:
            return "categorical"

        # Signal 4: Frequency concentration (Top 20 cover > 80%)
        top20_coverage = series.value_counts(normalize=True).head(20).sum()
        if top20_coverage > 0.8:
            return "categorical"

        # Signal 5: Log-scaled dynamic ratio
        dynamic_threshold = min(0.5, max(0.01, 10.0 / math.sqrt(n_total)))
        ratio = n_unique / n_total
        if ratio < dynamic_threshold:
            return "categorical"

        # Signal 6: Fallback to freetext vs id_like
        if avg_words > 2.0:
            return "freetext"

        str_lengths = series.dropna().astype(str).apply(len)
        mean_len = str_lengths.mean()
        if mean_len > 0:
            cv = str_lengths.std() / mean_len
            if cv < 0.1:
                return "id_like"

        return "freetext"

    @classmethod
    def _extract_string(
        cls, series: pd.Series, max_unique: int, _classification: Optional[str] = None
    ) -> Optional[List[Any]]:
        classification = _classification or cls._classify_string_column(series, max_unique)

        if classification == "categorical":
            # Keep exact original-case values — safe for SQL WHERE clauses
            return sorted(series.dropna().unique().tolist())

        elif classification == "freetext":
            # Word vocabulary: split on whitespace/newlines, lowercase, deduplicate
            words = set()
            for val in series.dropna():
                tokens = re.split(r"[\s\n\r]+", str(val).strip())
                for token in tokens:
                    cleaned = token.strip(".,;:!?\"'()[]{}-—")
                    if cleaned and len(cleaned) > 1:  # skip single chars
                        words.add(cleaned)
            return sorted(words) if words else None

        else:  # id_like
            # Return a few representative values so the LLM knows this column
            # exists and can use it for JOINs / filtering.  Without samples,
            # id_like columns vanish from context entirely and the LLM
            # hallucinates column names.
            sample_vals = series.dropna().unique().tolist()
            return sorted(sample_vals[:5]) if sample_vals else None

    @classmethod
    def _extract_numeric(cls, series: pd.Series) -> Optional[Dict[str, Any]]:
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if clean.empty:
            return None
        # 3 evenly-distributed example values (min, midpoint, max area)
        examples = clean.sample(min(3, len(clean)), random_state=42).round(4).tolist()
        return {
            "min": round(float(clean.min()), 4),
            "max": round(float(clean.max()), 4),
            "mean": round(float(clean.mean()), 4),
            "examples": sorted(examples),
        }

    @classmethod
    def _extract_datetime(cls, series: pd.Series) -> Optional[Dict[str, Any]]:
        clean = pd.to_datetime(series, errors="coerce").dropna()
        if clean.empty:
            return None
        examples = clean.sample(min(3, len(clean)), random_state=42)
        return {
            "min": clean.min().isoformat(),
            "max": clean.max().isoformat(),
            "examples": sorted(e.isoformat() for e in examples),
        }

    @classmethod
    def _extract_boolean(cls, series: pd.Series) -> Optional[List[Any]]:
        vals = series.dropna().unique().tolist()
        return sorted(str(v) for v in vals) if vals else None
