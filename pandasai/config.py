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
