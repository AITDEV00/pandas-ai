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
            "0 = no history; -1 = all history; null = server default (10). "
            "Rounded up to ensure complete user→assistant pairs."
        ),
    )
    column_selection_enabled: Optional[bool] = Field(
        None,
        description=(
            "Control column selection for this query. "
            "true = force Step 1 column selection; "
            "false = skip column selection; "
            "null (default) = auto-detect: use Step 1 if total columns >= column_selection_threshold."
        ),
    )
    column_selection_threshold: Optional[int] = Field(
        None,
        description=(
            "Auto-enable column selection when total columns >= this value. "
            "Only used when column_selection_enabled is null (auto-detect). "
            "null = use Config default (30)."
        ),
    )
    column_values_budget_ratio: Optional[float] = Field(
        None,
        description=(
            "Fraction of LLM context window to allocate for enriched column values. "
            "Controls how many token-budgeted sample values are included in the prompt. "
            "null = use Config default (0.10)."
        ),
    )

class ChatResponse(BaseModel):
    response: Any
    type: str
    last_code_executed: Optional[str] = None
    selected_columns: Optional[list] = Field(
        None,
        description=(
            "List of column names selected by Step 1 column selection. "
            "Null if column selection was not triggered."
        ),
    )
