import asyncio
from fastapi import APIRouter
from .models import ChatRequest, ChatResponse
from .handler import handle_chat_query

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Submit a prompt to a specific registered conversation. 
    Maintains memory across multiple turns.
    
    Offloaded to a thread pool so the event loop stays responsive
    for /health and /register requests while LLM calls are in progress.
    """
    result = await asyncio.to_thread(
        handle_chat_query,
        conversation_id=request.conversation_id, 
        query=request.query, 
        output_type=request.output_type,
        message_history=request.message_history,
        column_selection_enabled=request.column_selection_enabled,
        column_selection_threshold=request.column_selection_threshold,
        column_values_budget_ratio=request.column_values_budget_ratio,
        column_selection_temperature=request.column_selection_temperature,
        column_selection_top_p=request.column_selection_top_p,
        column_selection_top_k=request.column_selection_top_k,
        code_generation_temperature=request.code_generation_temperature,
        code_generation_top_p=request.code_generation_top_p,
        code_generation_top_k=request.code_generation_top_k,
        step1_only=request.step1_only,
    )
    return ChatResponse(**result)
