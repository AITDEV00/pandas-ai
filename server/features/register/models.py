from pydantic import BaseModel, Field, model_validator
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
        "You are an expert data assistant. Use execute_sql_query for data retrieval and aggregation. For presenting results, write Python code: compute derived values, format strings, build conditional logic, and choose the best result type (string for answers, number for counts, dataframe for tables, plot for charts). Do not make assumptions about data formats without checking the vocabulary lists.",
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

class SemanticModelPayload(BaseModel):
    """Wrapper for PandasAI SemanticLayerSchema with pre-validation"""
    schema_version: str = Field("1.0.0", description="Schema version for forward compatibility")
    name: str = Field(..., description="Dataset name (underscore_format)")
    description: Optional[str] = Field(None, description="Dataset description")
    source: Optional[Dict[str, Any]] = Field(None, description="Data source configuration")
    columns: Optional[List[Dict[str, Any]]] = Field(None, description="Column definitions")
    relations: Optional[List[Dict[str, Any]]] = Field(None, description="Column relationships")
    transformations: Optional[List[Dict[str, Any]]] = Field(None, description="Data transformations")
    
    @model_validator(mode="after")
    def validate_as_semantic_layer_schema(self) -> "SemanticModelPayload":
        """Validate against PandasAI's SemanticLayerSchema"""
        from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
        from pydantic import ValidationError
        
        try:
            schema_dict = self.model_dump(exclude_none=True)
            # Inject a placeholder source if neither source nor view is provided.
            # The actual file path is set later by the handler after file I/O.
            if "source" not in schema_dict and "view" not in schema_dict:
                schema_dict["source"] = {"type": "csv", "path": "placeholder"}
            SemanticLayerSchema(**schema_dict)
        except ValidationError as e:
            raise ValueError(f"Invalid semantic model: {e}")
        return self

class Base64UploadRequest(BaseModel):
    base64_data: str
    mimetype: str
    semantic_model: Optional[SemanticModelPayload] = Field(None, description="PandasAI SemanticLayerSchema payload")
    pandasai_config: Optional[PandasAIConfigPayload] = Field(default_factory=PandasAIConfigPayload)
    llm_config: Optional[LLMConfigPayload] = Field(default_factory=LLMConfigPayload)

class ColumnContext(BaseModel):
    column: str
    type: Optional[str] = None
    semantic_type: Optional[str] = None
    samples: Any

class RegisterResponse(BaseModel):
    conversation_id: str
    extracted_context: Optional[List[ColumnContext]] = None
