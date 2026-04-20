from pydantic import BaseModel
from typing import Optional, Any

class ChatRequest(BaseModel):
    conversation_id: str
    query: str
    output_type: Optional[str] = None

class ChatResponse(BaseModel):
    response: Any
    type: str
    last_code_executed: Optional[str] = None
