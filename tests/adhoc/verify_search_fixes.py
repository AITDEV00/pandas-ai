import sys
from pathlib import Path

# Add project root to sys.path so we can import pandasai
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
from pandasai.config import ConfigManager
from pandasai.dataframe.base import DataFrame
from pandasai.core.prompts.generate_python_code_with_sql import GeneratePythonCodeWithSQLPrompt

def main():
    print("Testing PandasAI Search Improvements...")
    
    # 1. Test BOM Handling (Fix A)
    print("\n--- 1. Testing BOM Handling ---")
    df = pd.read_csv(Path(__file__).parent.parent.parent / "examples" / "data" / "emirati_employees_data.csv", encoding="utf-8-sig")
    print(f"Columns: {list(df.columns)}")
    if "English Name" in df.columns:
        print("✅ BOM handling successful")
    else:
        print("❌ BOM handling failed")

    # 2. Test Configuration Defaults (Fix B, Fix G part 1)
    print("\n--- 2. Testing Configuration Defaults ---")
    config = ConfigManager.get()
    print(f"enrich_column_values: {config.enrich_column_values}")
    print(f"sample_head_size: {getattr(config, 'sample_head_size', 'missing')}")
    if config.enrich_column_values and getattr(config, 'sample_head_size', None) == 10:
        print("✅ Config defaults successful")
    else:
        print("❌ Config defaults failed")

    # 3. Test Prompt Generation (Fix C, D, E, G part 2)
    print("\n--- 3. Testing Prompt Generation ---")
    from pandasai import SmartDataframe
    sdf = SmartDataframe(df.head(50), config=config)
    
    # We can use _process_query or similar, or just build the context manually from sdf
    from pandasai.core.prompts.base import PromptContext
    from pandasai.helpers.memory import Memory
    
    # Force enrich column values on the df (usually happens on query)
    sdf._engine.get_df_info(sdf._dfs)
    
    context = PromptContext(
        dfs=sdf._dfs,
        memory=Memory(),
        skills=[],
        custom_instructions=None,
        config=config,
    )
    
    prompt = GeneratePythonCodeWithSQLPrompt(
        context=context,
        last_code_generated=None
    )
    
    rendered_prompt = prompt.to_string()
    
    # Check for correct search strategy instructions
    if "SEARCH STRATEGY" in rendered_prompt or "Search Strategy" in rendered_prompt:
        print("✅ Search strategy block found in prompt")
    else:
        print("❌ Search strategy block missing")

    # Check for specific column instructions (e.g. English Name)
    if 'Column "English Name"' in rendered_prompt:
        print("✅ Column-specific instructions found for 'English Name'")
        
        # Extract the section for 'English Name'
        idx = rendered_prompt.find('Column "English Name"')
        end_idx = rendered_prompt.find('Column', idx + 10)
        section = rendered_prompt[idx:end_idx] if end_idx != -1 else rendered_prompt[idx:idx+500]
        
        if "freetext" in section:
            print("✅ 'English Name' correctly classified as freetext")
        else:
            print("❌ 'English Name' not classified as freetext")
            
        if "ILIKE" in section:
            print("✅ 'English Name' instruction includes ILIKE")
        else:
            print("❌ 'English Name' instruction missing ILIKE")
            
    else:
        print("❌ Column-specific instructions missing")
        
    print("\nSnippet of generated prompt:")
    print("-" * 50)
    
    # Find the strategy block and print a snippet
    start_idx = rendered_prompt.find("SQL Engine & Search Strategy")
    if start_idx != -1:
        print(rendered_prompt[start_idx:start_idx+1500])
    else:
        print("Strategy block not found.")
    
    print("-" * 50)

if __name__ == "__main__":
    main()
