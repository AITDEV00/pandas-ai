from fastapi import HTTPException
from server.core.agent_store import agent_store

def handle_chat_query(conversation_id: str, query: str, output_type: str = None) -> dict:
    """Retrieves session state, queries the LLM, and formats the response object safely."""
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")
        
    try:
        # Use follow_up() for subsequent turns to preserve multi-turn memory.
        # chat() clears memory (starts fresh), follow_up() preserves it.
        if agent._state.memory.count() > 0:
            response = agent.follow_up(query, output_type=output_type)
        else:
            response = agent.chat(query, output_type=output_type)

        # Extract the actual type from the response object (authoritative source)
        # Falls back to the requested type, then "auto"
        actual_type = getattr(response, 'type', None) or output_type or "auto"

        # Serialize response value appropriately based on type
        if actual_type == 'dataframe' and hasattr(response, 'value') and hasattr(response.value, 'to_dict'):
            response_value = response.value.to_dict(orient='records')
        else:
            response_value = str(response) if response is not None else None
        
        return {
            "response": response_value,
            "type": actual_type,
            "last_code_executed": getattr(agent, "last_code_executed", None)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
