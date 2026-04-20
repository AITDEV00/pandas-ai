import os
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM

import openai

# 1. Setup Custom HTTP Client (Bypass SSL)
custom_httpx_client = httpx.Client(verify=False)

# 2. Setup the official OpenAI Python Client leveraging the unverified HTTPX Client
custom_openai_client = openai.OpenAI(
    api_key="sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8",
    base_url="https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
    http_client=custom_httpx_client
)

# 3. Configure LiteLLM for your OpenAI-compatible endpoint
# Note: Adding 'openai/' prefix tells LiteLLM to use the OpenAI API format
llm = LiteLLM(
    model="openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
    client=custom_openai_client
)

# 3. Register the LLM configuration with PandasAI 
pai.config.set({
    "llm": llm
})

def main():
    # 4. Load your data (CSV or Excel)
    print("Loading data...")
    
    # Example for CSV:
    # df = pai.read_csv("path/to/your/data.csv")
    
    # Example for Excel:
    # df = pai.read_excel("path/to/your/data.xlsx")
    
    # --- For Demonstration Purposes, Creating a Dummy File First ---

    
    df = pai.read_excel("/home/jyao/ait-projects/chat-excel-server/pandas-ai/usecase_data.xlsx")
    print("Data loaded successfully!")

    # 5. Start chatting with your data
    query = "What data is there? give me a summary in english"
    print(f"\nQuerying: '{query}'")
    
    response = df.chat(query)
    print(f"\nResponse:\n{response}")

if __name__ == "__main__":
    main()
