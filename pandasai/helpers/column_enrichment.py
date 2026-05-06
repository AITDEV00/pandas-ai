import math
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class ColumnValueExtractor:
    """Extracts semantic value metadata from a pandas Series, per column type."""

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
        first_valid = series.dropna().iloc[0] if not series.dropna().empty else None

        # --- INTERCEPT LIST OF STRUCTS ---
        # Broad check: if the first value is ANY list (even empty), treat as struct column.
        # This prevents fallthrough to .nunique() which cannot handle list values.
        if isinstance(first_valid, list):
            # Find the first non-empty list of dicts to determine the struct shape
            first_nonempty = next(
                (v for v in series.dropna() if isinstance(v, list) and v and isinstance(v[0], dict)),
                None
            )
            if first_nonempty is None:
                # All rows are empty arrays — nothing to extract
                return None
                
            all_structs = [struct for row_list in series.dropna() for struct in row_list if isinstance(struct, dict)]
            if not all_structs:
                return None
                
            from pandasai.helpers.semantic_matching import match_column_details_to_schema
            from pandasai.helpers.type_determination import determine_series_type
            
            temp_df = pd.DataFrame(all_structs)
            struct_vocabulary = {}
            for inner_col in temp_df.columns:
                inner_series = temp_df[inner_col]
                details = match_column_details_to_schema(inner_col, df_schema)
                inner_type = details["type"]
                inner_desc = details["description"]
                            
                # Fallback to pandas heuristics
                if not inner_type or inner_type == "unknown":
                    inner_type = determine_series_type(inner_series)
                    
                inner_samples = cls.extract(inner_series, inner_type, categorical_max_unique, df_schema)
                if inner_samples:
                    inner_entry = {
                        "type": inner_type,
                        "samples": inner_samples,
                    }
                    if inner_desc:
                        inner_entry["description"] = inner_desc
                    # Classify string inner columns
                    if inner_type == "string":
                        try:
                            inner_entry["semantic_type"] = cls._classify_string_column(inner_series, categorical_max_unique)
                        except Exception:
                            inner_entry["semantic_type"] = None
                    struct_vocabulary[inner_col] = inner_entry
            return struct_vocabulary

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
        cls, series: pd.Series, max_unique: int
    ) -> Optional[List[Any]]:
        classification = cls._classify_string_column(series, max_unique)

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
            return None

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
