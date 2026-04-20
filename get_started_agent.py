import os
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
from pandasai import Agent
import openai

def main():
    # 1. Setup Custom HTTP Client (Bypass SSL)
    custom_httpx_client = httpx.Client(verify=False)

    # 2. Setup the official OpenAI Python Client leveraging the unverified HTTPX Client
    custom_openai_client = openai.OpenAI(
        api_key="sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8",
        base_url="https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
        http_client=custom_httpx_client
    )

    # 3. Configure LiteLLM
    llm = LiteLLM(
        model="openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
        client=custom_openai_client
    )

    # 4. Register the LLM configuration with PandasAI 
    pai.config.set({
        "llm": llm,
        # "verbose": True
    })

    print("Loading data...")
    # 5. Load your Excel Data
    df = pai.read_excel("/home/jyao/ait-projects/chat-excel-server/pandas-ai/usecase_data.xlsx")
    
    # 6. Initialize an Agent (Agents retain memory/context for back-to-back questions)
    agent = Agent(df)
    
    print("\nData loaded successfully! You are now chatting with your Excel file.")
    print("The Agent will remember your previous questions within this session.")
    print("Type 'exit' or 'quit' to stop.\n")

    # 7. Start CLI interaction loop
    while True:
        try:
            query = input("\n👤 You: ")
            
            # Check for termination keyword
            if query.strip().lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
                
            # Skip empty inputs
            if not query.strip():
                continue
                
            print("🤖 Agent is thinking...")
            
            # Ask the agent
            response = agent.chat(query)
            
            print(f"✅ Response:\n{response}")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
