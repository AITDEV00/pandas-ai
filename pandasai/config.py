import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from pandasai.helpers.filemanager import DefaultFileManager, FileManager
from pandasai.llm.base import LLM


class Config(BaseModel):
    save_logs: bool = True
    verbose: bool = False
    max_retries: int = 3
    llm: Optional[LLM] = None
    # Dedicated LLM for structured JSON calls (column selection, description
    # auto-fill).  When set, the ColumnSelector and description filler use this
    # instead of ``llm``.  Falls back to ``llm`` when None.
    structured_llm: Optional[LLM] = None
    file_manager: FileManager = Field(default_factory=DefaultFileManager)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    direct_sql: bool = True
    enrich_column_values: bool = True
    llm_context_window: int = int(os.environ.get("LLM_CONTEXT_WINDOW", "250000"))
    column_values_budget_ratio: float = 0.10
    column_values_token_budget: Optional[int] = None
    categorical_max_unique: int = 50
    sample_head_size: int = 10

    # Column selection pipeline (Issue 19)
    # Tri-state: True = force on, False = force off, None = auto-detect via threshold
    column_selection_enabled: Optional[bool] = None
    column_selection_threshold: int = 30
    column_selection_memory_size: int = 5
    auto_fill_descriptions: bool = True

    # Column selection sampling params — override the LLM's default sampling
    # settings for Step-1 (column selection) calls only.  Lower temperature
    # reduces variance on ambiguous queries.  These are passed as per-call
    # overrides to LiteLLM.call(sampling_params=...).
    # Defaults are tuned for Qwen3.5-35B-A3B via vllm with the V6 prompt.
    # Override via config dict, HTTP request body, or env vars
    # (e.g. COLUMN_SELECTION_TEMPERATURE=0.6).
    column_selection_temperature: Optional[float] = float(os.environ.get("COLUMN_SELECTION_TEMPERATURE", "0.6"))
    column_selection_top_p: Optional[float] = float(os.environ.get("COLUMN_SELECTION_TOP_P", "0.95"))
    column_selection_top_k: Optional[int] = int(os.environ.get("COLUMN_SELECTION_TOP_K", "20"))
    column_selection_min_p: Optional[float] = float(os.environ.get("COLUMN_SELECTION_MIN_P", "0.0"))
    column_selection_repetition_penalty: Optional[float] = float(os.environ.get("COLUMN_SELECTION_REPETITION_PENALTY", "1.0"))
    column_selection_presence_penalty: Optional[float] = float(os.environ.get("COLUMN_SELECTION_PRESENCE_PENALTY", "0.0"))
    # Force JSON structured output for column selection (vllm supports this
    # via response_format={"type": "json_object"}).  When True, the LLM is
    # constrained to emit valid JSON, eliminating parse failures.
    column_selection_json_mode: bool = os.environ.get("COLUMN_SELECTION_JSON_MODE", "true").lower() == "true"

    # Code generation sampling params — override the LLM's default sampling
    # settings for Step-2 (code generation) calls only.  These are passed as
    # per-call overrides to LiteLLM.call(sampling_params=...).
    # Override via config dict, HTTP request body, or env vars
    # (e.g. CODE_GENERATION_TEMPERATURE=0.7).
    code_generation_temperature: Optional[float] = float(os.environ.get("CODE_GENERATION_TEMPERATURE", "0.7"))
    code_generation_top_p: Optional[float] = float(os.environ.get("CODE_GENERATION_TOP_P", "0.95"))
    code_generation_top_k: Optional[int] = int(os.environ.get("CODE_GENERATION_TOP_K", "20"))
    code_generation_min_p: Optional[float] = float(os.environ.get("CODE_GENERATION_MIN_P", "0.0"))
    code_generation_repetition_penalty: Optional[float] = float(os.environ.get("CODE_GENERATION_REPETITION_PENALTY", "1.0"))
    code_generation_presence_penalty: Optional[float] = float(os.environ.get("CODE_GENERATION_PRESENCE_PENALTY", "0.0"))

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "Config":
        return cls(**config)


class ConfigManager:
    """A singleton class to manage the global configuration."""

    _config: Config = Config()

    @classmethod
    def set(cls, config_dict: Dict[str, Any]) -> None:
        """Set the global configuration."""
        cls._config = Config.from_dict(config_dict)

    @classmethod
    def get(cls) -> Config:
        """Get the global configuration."""
        if cls._config is None:
            cls._config = Config()

        return cls._config

    @classmethod
    def update(cls, config_dict: Dict[str, Any]) -> None:
        """Update the existing configuration with new values."""
        current_config = cls._config.model_dump()
        current_config.update(config_dict)
        cls._config = Config.from_dict(current_config)


class APIKeyManager:
    _api_key: Optional[str] = None

    @classmethod
    def set(cls, api_key: str):
        os.environ["PANDABI_API_KEY"] = api_key
        cls._api_key = api_key

    @classmethod
    def get(cls) -> Optional[str]:
        return cls._api_key
