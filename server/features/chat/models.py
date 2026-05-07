from pydantic import BaseModel, Field
from typing import Optional, Any

class ChatRequest(BaseModel):
    conversation_id: str
    query: str
    output_type: Optional[str] = None
    message_history: Optional[int] = Field(
        None,
        description=(
            "Number of previous user turns to include as conversation history. "
            "Rounded up to ensure complete user→assistant pairs. "
            "If not set, uses the server default (10)."
        ),
    )

class ChatResponse(BaseModel):
    response: Any
    type: str
    last_code_executed: Optional[str] = None
