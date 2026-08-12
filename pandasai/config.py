import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from pandasai.helpers.filemanager import DefaultFileManager, FileManager
from pandasai.llm.base import LLM


def _env_float(name: str) -> Optional[float]:
    """Read a float env var, returning None when unset/blank.

    Unset env vars map to None so the caller (code generation / column
    selection) omits them from the LLM sampling call and lets the model
    apply its own defaults.  This is the requested behaviour for DeepSeek:
    only temperature and top_p are pinned; everything else is left to the
    model defaults.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str) -> Optional[int]:
    """Parse an int env var, returning None when unset/blank/invalid."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


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
    # overrides to LLM.call(sampling_params=...).
    # Each value reads an env var; when unset it becomes None so the param is
    # omitted and the model applies its own default.  Override via config dict,
    # HTTP request body, or env vars (e.g. COLUMN_SELECTION_TEMPERATURE=0.6).
    column_selection_temperature: Optional[float] = _env_float("COLUMN_SELECTION_TEMPERATURE")
    column_selection_top_p: Optional[float] = _env_float("COLUMN_SELECTION_TOP_P")
    column_selection_top_k: Optional[int] = _env_int("COLUMN_SELECTION_TOP_K")
    column_selection_min_p: Optional[float] = _env_float("COLUMN_SELECTION_MIN_P")
    column_selection_repetition_penalty: Optional[float] = _env_float("COLUMN_SELECTION_REPETITION_PENALTY")
    column_selection_presence_penalty: Optional[float] = _env_float("COLUMN_SELECTION_PRESENCE_PENALTY")
    # Hard cap on output tokens for Step-1 (column selection) calls.  Bounds a
    # runaway selection/analysis so a single query cannot loop indefinitely.
    # Reads COLUMN_SELECTION_MAX_TOKENS; when unset the model default applies.
    column_selection_max_tokens: Optional[int] = _env_int("COLUMN_SELECTION_MAX_TOKENS")
    # Force JSON structured output for column selection (vllm supports this
    # via response_format={"type": "json_object"}).  When True, the LLM is
    # constrained to emit valid JSON, eliminating parse failures.
    column_selection_json_mode: bool = os.environ.get("COLUMN_SELECTION_JSON_MODE", "true").lower() == "true"

    # Use the instructor library for structured column selection. When True,
    # the ColumnSelector wraps the structured LLM with instructor (Mode.MD_JSON)
    # to get validated Pydantic output. This avoids grammar-constrained
    # response_format (which models like DeepSeek-V4-Flash DFLASH and
    # diffusiongemma reject) and instead extracts JSON from a code block.
    column_selection_use_instructor: bool = (
        os.environ.get("COLUMN_SELECTION_USE_INSTRUCTOR", "true").lower() == "true"
    )

    # Code generation sampling params — override the LLM's default sampling
    # settings for Step-2 (code generation) calls only.  These are passed as
    # per-call overrides to LLM.call(sampling_params=...).
    # Each param reads an env var; when unset it becomes None so the param is
    # omitted and the model's default is used.  For DeepSeek the requested
    # configuration is temperature=1.0, top_p=0.95, everything else None
    # (i.e. leave top_k / min_p / repetition_penalty / presence_penalty to the
    # model defaults).  Override via env vars or HTTP request body.
    code_generation_temperature: Optional[float] = _env_float("CODE_GENERATION_TEMPERATURE")
    code_generation_top_p: Optional[float] = _env_float("CODE_GENERATION_TOP_P")
    code_generation_top_k: Optional[int] = _env_int("CODE_GENERATION_TOP_K")
    code_generation_min_p: Optional[float] = _env_float("CODE_GENERATION_MIN_P")
    code_generation_repetition_penalty: Optional[float] = _env_float("CODE_GENERATION_REPETITION_PENALTY")
    code_generation_presence_penalty: Optional[float] = _env_float("CODE_GENERATION_PRESENCE_PENALTY")
    # Hard cap on the number of output tokens for Step-2 (code generation)
    # calls.  This bounds the response so a runaway reasoning/code generation
    # cannot loop indefinitely (a key cause of multi-hundred-second latencies
    # on complex multi-struct questions like R9-R13).  Reads
    # CODE_GENERATION_MAX_TOKENS; when unset the model default applies.
    code_generation_max_tokens: Optional[int] = _env_int("CODE_GENERATION_MAX_TOKENS")

    # Use the instructor library for structured code generation. When True,
    # the code generator requests a bounded 3-section response (reasoning_trace,
    # double_check, code) validated by Pydantic. This keeps the reasoning benefit
    # of thinking-mode while bounding output so DeepSeek-V4-Flash cannot loop.
    # The raw response code field is then extracted as the generated code.
    code_generation_use_instructor: bool = (
        os.environ.get("CODE_GENERATION_USE_INSTRUCTOR", "false").lower() == "true"
    )

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
