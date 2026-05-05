import pandas as pd
from pandasai import Agent
from pandasai.config import ConfigManager

def test_enrichment():
    data = {
        "status": ["Pending", "Shipped", "Delivered", "Cancelled", "Pending", "Shipped"] * 20, # 120 rows, 4 unique
        "notes": [f"This is a very unique long note number {i} detailing some problem" for i in range(120)], # 120 unique
        "amount": [12.5, 450.0, 5000.0, 10.99, 99.99, 250.0] * 20, # 120 rows
        "user_id": [f"user_{i}" for i in range(120)] # 120 unique, id-like
    }
    df = pd.DataFrame(data)

    # Test 1: Enrichment disabled
    print("--- Test 1: Enrichment Disabled ---")
    agent1 = Agent([df], config={"enrich_column_values": False})
    prompt1 = agent1._state.dfs[0].serialize_dataframe(config=agent1._state.config)
    print("amount samples included?", "samples" in prompt1 and "amount" in prompt1)

    # Test 2: Enrichment enabled, small budget
    print("--- Test 2: Enrichment Enabled ---")
    agent2 = Agent([df], config={
        "enrich_column_values": True,
        "column_values_token_budget": 50, # Tight budget
    })
    prompt2 = agent2._state.dfs[0].serialize_dataframe(config=agent2._state.config)
    print(prompt2)

if __name__ == "__main__":
    test_enrichment()
