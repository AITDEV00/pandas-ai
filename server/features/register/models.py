from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class PandasAIConfigPayload(BaseModel):
    enrich_column_values: bool = Field(False, description="Enable semantic enrichment of column values")
    llm_context_window: int = Field(8192, description="Context window of the LLM to calculate proportional budget")
    column_values_token_budget: Optional[int] = Field(None, description="Hard cap on token budget for column enrichment")
    categorical_max_unique: int = Field(50, description="Max unique values before a column is no longer considered categorical")

class LLMConfigPayload(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
    system_prompt: Optional[str] = Field(
        "You are an expert data assistant. Always follow the DuckDB Search Strategy provided in the context exactly. Do not invent Python code for filtering data; always use the `execute_sql_query` function. Do not make assumptions about data formats without checking the vocabulary lists.",
        description="Instructional prompt to guide the agent behavior"
    )
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    stop: Optional[List[str]] = None
    seed: Optional[int] = None

class Base64UploadRequest(BaseModel):
    base64_data: str
    mimetype: str
    semantic_model: Optional[Dict[str, Any]] = Field(None, description="PandasAI SemanticLayerSchema as JSON")
    pandasai_config: Optional[PandasAIConfigPayload] = Field(default_factory=PandasAIConfigPayload)
    llm_config: Optional[LLMConfigPayload] = Field(default_factory=LLMConfigPayload)

class ColumnContext(BaseModel):
    column: str
    samples: Any

class RegisterResponse(BaseModel):
    conversation_id: str
    extracted_context: Optional[List[ColumnContext]] = None
