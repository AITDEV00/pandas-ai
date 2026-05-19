import pandas as pd
import json
import argparse
import sys

def generate_semantic_payload_from_excel(excel_path: str, output_json: str):
    try:
        df_dict = pd.read_excel(excel_path)
    except FileNotFoundError:
        print(f"Error: {excel_path} not found.")
        sys.exit(1)
        
    schema = {
        "name": "enterprise_data",
        "description": "Master dataset containing unflattened structs and employee records.",
        "columns": []
    }
    
    # Map Python type names to PandasAI's accepted SemanticLayerSchema types
    TYPE_MAP = {
        "str": "string",
        "string": "string",
        "int": "integer",
        "integer": "integer",
        "float": "float",
        "datetime": "datetime",
        "bool": "boolean",
        "boolean": "boolean",
    }

    # Define columns exactly as they appear in the dictionary, wrapped in the table context
    # Use a dict keyed by name so duplicates in the Excel are silently deduplicated.
    # When a duplicate is found, the one with the longest description is kept.
    columns_by_name = {}
    for _, row in df_dict.iterrows():
        raw_type = str(row['[Python Type]']).strip().lower()
        col_name = f"[{row['[Table Name]']}[{row['[Column Name]']}]]"
        
        # Handle potential NaNs in description
        description = str(row['[Business Meaning]']) if pd.notna(row['[Business Meaning]']) else ""
        
        if col_name in columns_by_name:
            existing_desc = columns_by_name[col_name]["description"]
            if len(description) > len(existing_desc or ""):
                columns_by_name[col_name]["description"] = description
                columns_by_name[col_name]["type"] = TYPE_MAP.get(raw_type, "string")
        else:
            columns_by_name[col_name] = {
                "name": col_name,
                "type": TYPE_MAP.get(raw_type, "string"),
                "description": description
            }

    schema["columns"] = list(columns_by_name.values())
    n_dupes = len(df_dict) - len(schema["columns"])
    if n_dupes:
        print(f"  Warning: removed {n_dupes} duplicate column name(s) from the dictionary.")
        
    with open(output_json, 'w') as f:
        json.dump(schema, f, indent=2)
        
    print(f"Successfully generated SemanticLayerSchema payload to {output_json}")
    print(f"Found {len(schema['columns'])} top-level columns.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate SemanticLayerSchema JSON from Data Dictionary Excel.')
    parser.add_argument('--input', type=str, default='table definition and types.xlsx', help='Input Excel dictionary')
    parser.add_argument('--output', type=str, default='semantic_model.json', help='Output JSON file')
    
    args = parser.parse_args()
    generate_semantic_payload_from_excel(args.input, args.output)
