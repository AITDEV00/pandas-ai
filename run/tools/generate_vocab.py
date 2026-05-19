"""
Test script: loads the unflattened Excel + semantic_model.json,
parses JSON arrays, builds a mock SemanticLayerSchema, and runs
ColumnValueExtractor.extract on every column to verify the full pipeline.
"""
import sys
import os
import json
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pandasai.helpers.column_enrichment import ColumnValueExtractor
from pandasai.helpers.type_determination import is_json_array_column, safe_json_parse, determine_series_type
from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema


DATA_FILE = os.path.join(os.path.dirname(__file__), "full data unflattened.xlsx")
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "semantic_model.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "vocabulary_generated.json")


def generate_vocab():
    # ---- 1. Load dataframe ----
    print(f"Loading {DATA_FILE} ...")
    df = pd.read_excel(DATA_FILE)
    print(f"  Loaded {df.shape[0]} rows x {df.shape[1]} cols")

    # ---- 2. Auto-detect and parse JSON array columns ----
    json_cols = []
    for col in df.columns:
        if is_json_array_column(df[col]):
            df[col] = df[col].apply(lambda v: safe_json_parse(v) or [])
            json_cols.append(col)
    print(f"  Parsed {len(json_cols)} JSON array columns")

    # ---- 3. Load semantic model ----
    schema = None
    if os.path.exists(SCHEMA_FILE):
        with open(SCHEMA_FILE) as f:
            schema_dict = json.load(f)
        # Inject a dummy source so SemanticLayerSchema validation passes
        if "source" not in schema_dict and "view" not in schema_dict:
            schema_dict["source"] = {"type": "csv", "path": DATA_FILE}
        schema = SemanticLayerSchema(**schema_dict)
        print(f"  Loaded semantic model with {len(schema.columns)} schema columns")
    else:
        print("  No semantic_model.json found — running without schema")

    # ---- 4. Extract vocabulary for every column ----
    vocab = {"extracted_context": []}

    for col in df.columns:
        series = df[col]
        col_type = determine_series_type(series)

        samples = ColumnValueExtractor.extract(series, col_type, 50, schema)

        entry = {
            "column": col,
            "type": col_type,
            "samples": samples,
        }

        # Detect struct columns vs normal string columns
        first_valid = series.dropna().iloc[0] if not series.dropna().empty else None
        if isinstance(first_valid, list):
            entry["type"] = "list[struct]"
            entry["semantic_type"] = "struct"
        elif col_type == "string":
            try:
                entry["semantic_type"] = ColumnValueExtractor._classify_string_column(series, 50)
            except Exception:
                entry["semantic_type"] = None

        vocab["extracted_context"].append(entry)

    # ---- 5. Write output ----
    with open(OUTPUT_FILE, "w") as f:
        json.dump(vocab, f, indent=2, default=str)

    # ---- 6. Summary ----
    total = len(vocab["extracted_context"])
    with_samples = sum(1 for e in vocab["extracted_context"] if e["samples"])
    struct_cols = sum(1 for e in vocab["extracted_context"] if isinstance(e["samples"], dict))
    print(f"\n=== RESULTS ===")
    print(f"  Total columns:       {total}")
    print(f"  Columns with samples: {with_samples}")
    print(f"  Struct columns:      {struct_cols}")

    # Show a preview of struct vocabulary
    for entry in vocab["extracted_context"]:
        if isinstance(entry["samples"], dict):
            print(f"\n  📦 {entry['column']}")
            for inner_col, inner_samples in entry["samples"].items():
                if isinstance(inner_samples, list):
                    preview = inner_samples[:3]
                    print(f"     ├─ {inner_col}: {preview} ... ({len(inner_samples)} total)")
                elif isinstance(inner_samples, dict):
                    print(f"     ├─ {inner_col}: {inner_samples}")

    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_vocab()
