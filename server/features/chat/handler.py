from fastapi import HTTPException
from server.core.agent_store import agent_store

def handle_chat_query(conversation_id: str, query: str, output_type: str = None) -> dict:
    """Retrieves session state, queries the LLM, and formats the response object safely."""
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")
        
    try:
        # Provide output_type per turn if the frontend specifically demands it
        response = agent.chat(query, output_type=output_type)
        
        # In PandasAI, response could be a primitive string, number, or a Dataframe.
        # It could also be a file path if a chart was generated. Convert to string to be JSON safe.
        response_str = str(response) if response is not None else None
        
        return {
            "response": response_str,
            "type": output_type or "auto",
            "last_code_executed": getattr(agent, "last_generated_code", None)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
