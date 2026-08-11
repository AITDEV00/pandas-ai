from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pandasai.config import Config, ConfigManager
from pandasai.constants import DEFAULT_CHART_DIRECTORY
from pandasai.ee.skills.manager import SkillsManager
from pandasai.helpers.folder import Folder
from pandasai.helpers.logger import Logger
from pandasai.helpers.memory import Memory
from pandasai.vectorstores.vectorstore import VectorStore

if TYPE_CHECKING:
    from pandasai.dataframe import DataFrame, VirtualDataFrame
    from pandasai.llm.base import LLM


@dataclass
class AgentState:
    """
    Context class for managing pipeline attributes and passing them between steps.
    """

    dfs: List[Union[DataFrame, VirtualDataFrame]] = field(default_factory=list)
    _config: Optional[Union[Config, dict]] = None
    memory: Memory = field(default_factory=Memory)
    vectorstore: Optional[VectorStore] = None
    intermediate_values: Dict[str, Any] = field(default_factory=dict)
    logger: Optional[Logger] = None
    last_code_generated: Optional[str] = None
    last_code_executed: Optional[str] = None
    last_prompt_id: Optional[str] = None
    last_prompt_used: Optional[str] = None
    last_result: Optional[Any] = None
    last_error: Optional[str] = None
    skills: List[Any] = field(default_factory=list)
    output_type: Optional[str] = None

    # Column selection caching (Issue 15)
    last_selected_names: Optional[List[str]] = None
    last_query: Optional[str] = None

    # Retry tracking — accumulated across code generation & execution retries
    code_attempts: List[Dict[str, Any]] = field(default_factory=list)
    # Each entry: {"phase": "generation"|"execution", "attempt": int, "code": str, "error": str|None}

    # Column selection detail log — populated during _apply_column_selection
    column_selection_log: List[Dict[str, Any]] = field(default_factory=list)
    # Each entry: {"step": str, "detail": Any}

    # ── Debug / diagnostic tracking ──────────────────────────────────────
    # Populated during _process_query() and extracted by the server's
    # conversation logger.  All fields are reset at the start of each query.

    # Raw LLM response text (before parsing) for column selection Step 1
    column_selection_raw_llm_response: Optional[str] = None

    # The prompt sent to LLM for column selection Step 1
    column_selection_prompt: Optional[str] = None

    # Raw LLM response text (before cleaning) for code generation Step 2
    code_generation_raw_llm_response: Optional[str] = None

    # LLM thinking/reasoning trace (reasoning_content) captured from the raw
    # response for the last code-generation call.  Populated by LiteLLM.call()
    # and read by the server's conversation logger so the model's "thinking"
    # behind each generated code attempt can be audited.
    code_generation_thinking_trace: Optional[str] = None

    # Same, for column selection Step 1 calls.
    column_selection_thinking_trace: Optional[str] = None

    # SQL queries executed by _execute_sql_query() during code execution
    # Each entry: {"sql": str, "result_shape": tuple, "result_columns": list,
    #              "result_preview": str, "error": str|None}
    sql_queries: List[Dict[str, Any]] = field(default_factory=list)

    # Full error traceback (not just str(e)) for the last error
    last_error_traceback: Optional[str] = None

    # Config snapshot at query time (key values only)
    config_snapshot: Optional[Dict[str, Any]] = None

    # Trimmed DataFrame info (only when column selection is active)
    # Each entry: {"df_index": int, "original_columns": list, "trimmed_columns": list,
    #              "original_shape": tuple, "trimmed_shape": tuple}
    trimmed_df_info: List[Dict[str, Any]] = field(default_factory=list)

    # Code execution result before parsing (the raw result dict)
    raw_execution_result: Optional[Any] = None

    # Strategy 4: Dual-mode column selection — retrieval mode from Step 1 LLM
    # retrieval_mode: "direct" | "evidence" | "hybrid" — set by _apply_column_selection
    retrieval_mode: Optional[str] = None
    retrieval_mode_reasoning: Optional[str] = None
    retrieval_mode_source: Optional[str] = None  # "step1_llm" or future "api_override"

    # Step 1 only mode — when True, skip Step 2 (code generation) and return
    # column selection results only. Useful for debugging and testing.
    step1_only: bool = False

    def __post_init__(self):
        if isinstance(self.config, dict):
            self.config = Config(**self.config)

    def initialize(
        self,
        dfs: Union[
            Union[DataFrame, VirtualDataFrame], List[Union[DataFrame, VirtualDataFrame]]
        ],
        config: Optional[Union[Config, dict]] = None,
        memory_size: Optional[int] = 10,
        vectorstore: Optional[VectorStore] = None,
        description: Optional[str] = None,
    ):
        """Initialize the state with the given parameters."""
        self.dfs = dfs if isinstance(dfs, list) else [dfs]
        self.config = self._get_config(config)
        self.skills = SkillsManager.get_skills()
        if config:
            self.config.llm = self._get_llm(self.config.llm)
        self.memory = Memory(memory_size, agent_description=description)
        self.logger = Logger(
            save_logs=self.config.save_logs, verbose=self.config.verbose
        )
        self.vectorstore = vectorstore
        self._configure()

    def _configure(self):
        """Configure paths for charts."""
        # Add project root path if save_charts_path is default
        Folder.create(DEFAULT_CHART_DIRECTORY)

    def _get_config(self, config: Union[Config, dict, None]) -> Config:
        """Load a config to be used for queries."""
        if config is None:
            return ConfigManager.get()

        if isinstance(config, dict):
            return Config(**config)

        return config

    def _get_llm(self, llm: Optional[LLM] = None) -> LLM:
        """Load and configure the LLM."""
        return llm

    def assign_prompt_id(self):
        """Assign a new prompt ID."""
        self.last_prompt_id = str(uuid.uuid4())

        if self.logger:
            self.logger.log(f"Prompt ID: {self.last_prompt_id}")

    def reset_intermediate_values(self):
        """Resets the intermediate values dictionary."""
        self.intermediate_values.clear()

    def add(self, key: str, value: Any):
        """Adds a single key-value pair to intermediate values."""
        self.intermediate_values[key] = value

    def add_many(self, values: Dict[str, Any]):
        """Adds multiple key-value pairs to intermediate values."""
        self.intermediate_values.update(values)

    def get(self, key: str, default: Any = "") -> Any:
        """Fetches a value from intermediate values or returns a default."""
        return self.intermediate_values.get(key, default)

    @property
    def config(self):
        """
        Returns the local config if set, otherwise fetches the global config.
        """
        if self._config is not None:
            return self._config

        import pandasai as pai

        return pai.config.get()

    @config.setter
    def config(self, value: Union[Config, dict, None]):
        """
        Allows setting a new config value.
        """
        self._config = Config(**value) if isinstance(value, dict) else value
