from fastapi import APIRouter
from .models import ChatRequest, ChatResponse
from .handler import handle_chat_query

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Submit a prompt to a specific registered conversation. 
    Maintains memory across multiple turns.
    """
    result = handle_chat_query(
        conversation_id=request.conversation_id, 
        query=request.query, 
        output_type=request.output_type
    )
    return ChatResponse(**result)
