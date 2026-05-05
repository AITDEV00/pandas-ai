import sys
import os
import json
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pandasai.config import ConfigManager
from pandasai.helpers.column_enrichment import ColumnValueExtractor

def generate_vocab():
    df = pd.read_excel("run/File (4).xlsx", sheet_name="Sheet")
    
    vocab = {"extracted_context": []}
    
    for col in df.columns:
        series = df[col]
        n_total = series.dropna().shape[0]
        n_unique = series.dropna().nunique()
        
        if pd.api.types.is_string_dtype(series) or series.dtype == object:
            col_type = "string"
        elif pd.api.types.is_integer_dtype(series):
            col_type = "integer"
        elif pd.api.types.is_float_dtype(series):
            col_type = "float"
        elif pd.api.types.is_datetime64_any_dtype(series):
            col_type = "datetime"
        elif pd.api.types.is_bool_dtype(series):
            col_type = "boolean"
        else:
            col_type = "unknown"
            
        samples = ColumnValueExtractor.extract(series, col_type, 50)
        
        semantic_type = None
        if col_type == "string":
            # Just to populate the semantic_type for the json if needed, though extract handles it
            semantic_type = ColumnValueExtractor._classify_string_column(series, 50)
        
        vocab["extracted_context"].append({
            "column": col,
            "type": col_type,
            "semantic_type": semantic_type,
            "samples": samples
        })
        
    with open("run/vocabulary_generated.json", "w") as f:
        json.dump(vocab, f, indent=2)

if __name__ == "__main__":
    generate_vocab()
    print("Generated run/vocabulary_generated.json")
