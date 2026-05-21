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
    # Per-query sampling param overrides (null = use config default)
    column_selection_temperature: Optional[float] = Field(
        None,
        description="Override column selection temperature for this query. null = use config default (0.6).",
    )
    column_selection_top_p: Optional[float] = Field(
        None,
        description="Override column selection top_p for this query. null = use config default (0.95).",
    )
    column_selection_top_k: Optional[int] = Field(
        None,
        description="Override column selection top_k for this query. null = use config default (20).",
    )
    code_generation_temperature: Optional[float] = Field(
        None,
        description="Override code generation temperature for this query. null = use config default (0.7).",
    )
    code_generation_top_p: Optional[float] = Field(
        None,
        description="Override code generation top_p for this query. null = use config default (0.95).",
    )
    code_generation_top_k: Optional[int] = Field(
        None,
        description="Override code generation top_k for this query. null = use config default (20).",
    )
    step1_only: Optional[bool] = Field(
        None,
        description=(
            "When true, stop after Step 1 (column selection) and return selected columns "
            "without running Step 2 (code generation). Useful for debugging and testing "
            "the column selection pipeline in isolation. null = use env STEP1_ONLY or False."
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
    # Strategy 4: Dual-mode column selection fields
    retrieval_mode: Optional[str] = Field(
        None,
        description=(
            "Retrieval mode from Step 1 LLM classification. "
            "One of: 'direct' (LLM synthesizes answer), "
            "'evidence' (return DataFrame), 'hybrid' (compound query + DataFrame). "
            "Null if column selection was not triggered."
        ),
    )
    retrieval_mode_reasoning: Optional[str] = Field(
        None,
        description="LLM's reasoning for the chosen retrieval mode. Null if not available.",
    )
    retrieval_mode_source: Optional[str] = Field(
        None,
        description="Source of the retrieval_mode decision. Currently 'step1_llm'. Null if not available.",
    )
    pipeline: Optional[dict] = Field(
        None,
        description=(
            "Full pipeline trace including column selection log, raw LLM responses, "
            "prompt text, and trimmed DataFrame info. Only populated when step1_only=True "
            "or when CONVERSATION_LOG_DIR is set."
        ),
    )
