import os
import time
import traceback
import warnings
from typing import Any, List, Optional, Union

import numpy as np
import pandas as pd

from pandasai.core.code_execution.code_executor import CodeExecutor
from pandasai.core.code_generation.base import CodeGenerator
from pandasai.core.prompts import (
    get_chat_prompt_for_sql,
    get_correct_error_prompt_for_sql,
    get_correct_output_type_error_prompt,
)
from pandasai.core.response.error import ErrorResponse
from pandasai.core.response.parser import ResponseParser
from pandasai.core.user_query import UserQuery
from pandasai.dataframe.base import DataFrame
from pandasai.dataframe.virtual_dataframe import VirtualDataFrame
from pandasai.exceptions import (
    CodeExecutionError,
    InvalidLLMOutputType,
    MissingVectorStoreError,
)
from pandasai.helpers.memory import Memory
from pandasai.sandbox import Sandbox
from pandasai.vectorstores.vectorstore import VectorStore

from ..config import Config
from ..data_loader.duck_db_connection_manager import DuckDBConnectionManager
from ..query_builders.base_query_builder import BaseQueryBuilder
from ..query_builders.sql_parser import SQLParser
from .state import AgentState


class Agent:
    """
    Base Agent class to improve the conversational experience in PandasAI
    """

    def __init__(
        self,
        dfs: Union[
            Union[DataFrame, VirtualDataFrame], List[Union[DataFrame, VirtualDataFrame]]
        ],
        config: Optional[Union[Config, dict]] = None,
        memory_size: Optional[int] = 10,
        vectorstore: Optional[VectorStore] = None,
        description: Optional[str] = None,
        sandbox: Sandbox = None,
    ):
        """
        Args:
            dfs (Union[Union[DataFrame, VirtualDataFrame], List[Union[DataFrame, VirtualDataFrame]]]): The dataframe(s) to be used for the conversation.
            config (Optional[Union[Config, dict]]): The configuration for the agent.
            memory_size (Optional[int]): The size of the memory.
            vectorstore (Optional[VectorStore]): The vectorstore to be used for the conversation.
            description (str): The description of the agent.
        """

        # Deprecation warnings
        if config is not None:
            warnings.warn(
                "The 'config' parameter is deprecated and will be removed in a future version. "
                "Please use the global configuration instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Transition pd dataframe to pandasai dataframe
        if isinstance(dfs, list):
            dfs = [DataFrame(df) if self.is_pd_dataframe(df) else df for df in dfs]
        elif self.is_pd_dataframe(dfs):
            dfs = DataFrame(dfs)

        if isinstance(dfs, list):
            sources = [df.schema.source or df._loader.source for df in dfs]
            if not BaseQueryBuilder.check_compatible_sources(sources):
                raise ValueError(
                    f"The sources of these datasets: {dfs} are not compatibles"
                )

        self.description = description
        self._state = AgentState()
        self._state.initialize(dfs, config, memory_size, vectorstore, description)

        self._code_generator = CodeGenerator(self._state)
        self._response_parser = ResponseParser()
        self._sandbox = sandbox

    def is_pd_dataframe(self, df: Union[DataFrame, VirtualDataFrame]) -> bool:
        return not isinstance(df, DataFrame) and isinstance(df, pd.DataFrame)

    def chat(self, query: str, output_type: Optional[str] = None):
        """
        Start a new chat interaction with the assistant on Dataframe.
        """
        if self._state.config.llm is None:
            raise ValueError(
                "PandasAI API key does not include LLM credits. Please configure an OpenAI or LiteLLM key. "
                "Learn more at: https://docs.pandas-ai.com/v3/large-language-models#how-to-set-up-any-llm%3F"
            )

        self.start_new_conversation()
        return self._process_query(query, output_type)

    def follow_up(self, query: str, output_type: Optional[str] = None):
        """
        Continue the existing chat interaction with the assistant on Dataframe.
        """
        return self._process_query(query, output_type)

    def generate_code(self, query: Union[UserQuery, str]) -> str:
        """Generate code using the LLM."""

        self._state.memory.add(str(query), is_user=True)

        self._state.logger.log("Generating new code...")
        prompt = get_chat_prompt_for_sql(self._state)

        code = self._code_generator.generate_code(prompt)
        self._state.last_prompt_used = prompt
        return code

    def execute_code(self, code: str) -> dict:
        """Execute the generated code."""
        self._state.logger.log(f"Executing code: {code}")

        code_executor = CodeExecutor()
        code_executor.add_to_env("execute_sql_query", self._execute_sql_query)
        for skill in self._state.skills:
            code_executor.add_to_env(skill.name, skill.func)

        if self._sandbox:
            return self._sandbox.execute(code, code_executor.environment)

        return code_executor.execute_and_return_result(code)

    def _execute_sql_query(self, query: str) -> pd.DataFrame:
        """
        Executes an SQL query on registered DataFrames.

        Args:
            query (str): The SQL query to execute.

        Returns:
            pd.DataFrame: The result of the SQL query as a pandas DataFrame.
        """
        if not self._state.dfs:
            raise ValueError("No DataFrames available to register for query execution.")

        db_manager = DuckDBConnectionManager()

        table_mapping = {}
        df_executor = None
        column_names = []

        for df in self._state.dfs:
            if hasattr(df, "query_builder"):
                # df is a valid dataset with query builder, loader and execute_sql_query method
                table_mapping[df.schema.name] = df.query_builder._get_table_expression()
                df_executor = df.execute_sql_query
            else:
                # dataset created from loading a csv, no query builder available
                db_manager.register(df.schema.name, df)
            # Collect known column names for auto-fix
            if df.schema and df.schema.columns:
                column_names.extend(col.name for col in df.schema.columns)

        # Auto-fix common LLM mistakes (missing brackets, wrong UNNEST alias)
        query = SQLParser.fix_common_llm_mistakes(query, column_names)

        final_query = SQLParser.replace_table_and_column_names(query, table_mapping)

        # Track SQL query for debug logging
        sql_entry = {
            "original_sql": query,
            "final_sql": final_query,
            "table_mapping": table_mapping,
            "error": None,
        }
        try:
            if not df_executor:
                result_df = db_manager.sql(final_query).df()
            else:
                result_df = df_executor(final_query)
        except Exception as e:
            sql_entry["error"] = f"{type(e).__name__}: {e}"
            self._state.sql_queries.append(sql_entry)
            raise

        # DuckDB returns STRUCT[] columns as numpy ndarrays inside the
        # pandas DataFrame cells.  LLM-generated code commonly tests
        # truthiness with ``if value and len(value) > 0:`` which raises
        # ``ValueError: The truth value of an array with more than one
        # element is ambiguous`` on multi-element ndarrays.  Converting
        # ndarrays to native Python lists fixes this and keeps dict
        # element access (``comp['key']``) working identically.
        for col in result_df.columns:
            sample = result_df[col].iloc[0] if len(result_df) > 0 else None
            if isinstance(sample, np.ndarray):
                result_df[col] = result_df[col].apply(
                    lambda v: v.tolist() if isinstance(v, np.ndarray) else v
                )

        # Capture result info for debug logging
        sql_entry["result_shape"] = list(result_df.shape)
        sql_entry["result_columns"] = list(result_df.columns)
        # Preview: first 5 rows as string (truncated for log size)
        try:
            preview_df = result_df.head(5)
            preview_str = preview_df.to_string(max_colwidth=50, max_rows=5)
            if len(preview_str) > 2000:
                preview_str = preview_str[:2000] + "\n... (truncated)"
            sql_entry["result_preview"] = preview_str
        except Exception:
            sql_entry["result_preview"] = "(preview unavailable)"
        self._state.sql_queries.append(sql_entry)

        return result_df

    def generate_code_with_retries(self, query: str) -> Any:
        """Generate code with retry logic.

        Total attempts = 1 (initial) + max_retries (regeneration attempts).
        """
        max_retries = self._state.config.max_retries
        exception = None

        # Reset per-query retry tracking
        self._state.code_attempts = []

        for attempt in range(1 + max_retries):
            try:
                if attempt == 0:
                    code = self.generate_code(query)
                else:
                    code = self._regenerate_code_after_error(
                        self._state.last_code_generated, exception
                    )
                # Capture raw LLM response for debug logging
                self._state.code_generation_raw_llm_response = code
                self._state.code_attempts.append({
                    "phase": "generation",
                    "attempt": attempt + 1,
                    "code": code,
                    "error": None,
                    # Snapshot the thinking trace produced by THIS generation
                    # call, before a later retry can overwrite it.
                    "thinking_trace": self._state.code_generation_thinking_trace,
                })
                return code
            except Exception as e:
                exception = e
                error_tb = traceback.format_exc()
                self._state.last_error_traceback = error_tb
                self._state.code_attempts.append({
                    "phase": "generation",
                    "attempt": attempt + 1,
                    "code": self._state.last_code_generated,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "error_traceback": error_tb,
                    "thinking_trace": self._state.code_generation_thinking_trace,
                })
                if attempt >= max_retries:
                    self._state.logger.log(
                        f"Maximum retry attempts exceeded. Last error: {e}"
                    )
                    raise
                self._state.logger.log(
                    f"Retrying Code Generation ({attempt}/{max_retries})..."
                )

    def execute_with_retries(self, code: str) -> Any:
        """Execute the code with retry logic.

        Total attempts = 1 (initial) + max_retries (regeneration attempts).
        """
        max_retries = self._state.config.max_retries

        for attempt in range(1 + max_retries):
            try:
                result = self.execute_code(code)
                # Track the code that actually executed successfully
                self._state.last_code_executed = code
                # Capture raw execution result for debug logging
                self._state.raw_execution_result = result
                # Issue 9 L2: Pass output_type to ResponseParser before parsing
                self._response_parser._output_type = self._state.output_type
                self._state.code_attempts.append({
                    "phase": "execution",
                    "attempt": attempt + 1,
                    "code": code,
                    "error": None,
                    # Snapshot the thinking trace that produced this code.
                    "thinking_trace": self._state.code_generation_thinking_trace,
                })
                return self._response_parser.parse(result, code)
            except Exception as e:
                error_tb = traceback.format_exc()
                self._state.last_error_traceback = error_tb
                self._state.code_attempts.append({
                    "phase": "execution",
                    "attempt": attempt + 1,
                    "code": code,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "error_traceback": error_tb,
                    "thinking_trace": self._state.code_generation_thinking_trace,
                })
                if attempt >= max_retries:
                    self._state.logger.log(f"Max retries reached. Error: {e}")
                    raise
                self._state.logger.log(
                    f"Retrying execution ({attempt + 1}/{max_retries})..."
                )
                code = self._regenerate_code_after_error(code, e)

    def train(
        self,
        queries: Optional[List[str]] = None,
        codes: Optional[List[str]] = None,
        docs: Optional[List[str]] = None,
    ) -> None:
        """
        Trains the context to be passed to model
        Args:
            queries (Optional[str], optional): user user
            codes (Optional[str], optional): generated code
            docs (Optional[List[str]], optional): additional docs
        Raises:
            ImportError: if default vector db lib is not installed it raises an error
        """
        if self._state.vectorstore is None:
            raise MissingVectorStoreError(
                "No vector store provided. Please provide a vector store to train the agent."
            )

        if (queries and not codes) or (not queries and codes):
            raise ValueError(
                "If either queries or codes are provided, both must be provided."
            )

        if docs is not None:
            self._state.vectorstore.add_docs(docs)

        if queries and codes:
            self._state.vectorstore.add_question_answer(queries, codes)

        self._state.logger.log("Agent successfully trained on the data")

    def set_message_history(self, num_turns: int):
        """Set the maximum number of user turns included in conversation history.

        Args:
            num_turns: Number of previous user turns to include. Rounded up
                to ensure complete user→assistant pairs.
        """
        self._state.memory.memory_size = num_turns

    def clear_memory(self):
        """
        Clears the memory
        """
        self._state.memory.clear()

    def add_message(self, message, is_user=False):
        """
        Add message to the memory. This is useful when you want to add a message
        to the memory without calling the chat function (for example, when you
        need to add a message from the agent).
        """
        self._state.memory.add(message, is_user=is_user)

    def start_new_conversation(self):
        """
        Clears the previous conversation
        """
        self.clear_memory()

    def _process_query(self, query: str, output_type: Optional[str] = None):
        """Process a user query and return the result.

        Supports a 2-step column selection pipeline for wide tables:
          Step 1: LLM selects relevant columns (small prompt, reduced memory)
          Step 2: Code generation runs on trimmed DataFrame/schema

        The original DataFrames are always restored in the ``finally`` block
        so that follow-up queries see the full schema again.
        """
        query = UserQuery(query)
        self._state.logger.log(f"Question: {query}")
        self._state.logger.log(
            f"Running PandasAI with {self._state.config.llm.type} LLM..."
        )

        # Reset per-query state
        self._state.last_selected_names = None
        self._state.code_attempts = []
        self._state.column_selection_log = []
        self._state.column_selection_raw_llm_response = None
        self._state.column_selection_prompt = None
        self._state.code_generation_raw_llm_response = None
        self._state.sql_queries = []
        self._state.last_error_traceback = None
        self._state.raw_execution_result = None
        self._state.trimmed_df_info = []
        self._state.retrieval_mode = None
        self._state.retrieval_mode_reasoning = None
        self._state.retrieval_mode_source = None

        # Snapshot key config values for debugging
        cfg = self._state.config
        self._state.config_snapshot = {
            "llm_type": getattr(cfg.llm, 'type', None) if cfg.llm else None,
            "max_retries": cfg.max_retries,
            "column_selection_enabled": cfg.column_selection_enabled,
            "column_selection_threshold": cfg.column_selection_threshold,
            "column_selection_memory_size": cfg.column_selection_memory_size,
            "column_values_budget_ratio": cfg.column_values_budget_ratio,
            "output_type": output_type,
            "save_logs": cfg.save_logs,
            "verbose": cfg.verbose,
        }

        self._state.output_type = output_type
        self._state.assign_prompt_id()
        self._state.timings = {}  # reset per query
        _t0 = time.time()

        # Step 1: Column Selection (if needed)
        original_dfs = None
        should_select = self._should_select_columns()
        total_cols = sum(len(df.columns) for df in self._state.dfs)
        if should_select:
            reason = ("forced on" if self._state.config.column_selection_enabled is True
                      else f"{total_cols} cols ≥ threshold ({self._state.config.column_selection_threshold})")
            self._state.logger.log(f"[Column Selection] Triggered: {reason}")
            original_dfs = list(self._state.dfs)  # Shallow copy of list
            _tcs0 = time.time()
            self._apply_column_selection(str(query))
            self._state.timings["column_selection"] = round(time.time() - _tcs0, 2)
            self._state.logger.log(
                f"[Timing] column_selection={self._state.timings['column_selection']}s"
            )
            # Diagnostic: show trimmed DF column names for Step 2
            for i, df in enumerate(self._state.dfs):
                self._state.logger.log(f"[Column Selection] Trimmed DF[{i}] columns: {list(df.columns)}")
                if hasattr(df, 'schema') and df.schema:
                    schema_names = [c.name for c in df.schema.columns]
                    self._state.logger.log(f"[Column Selection] Trimmed DF[{i}] schema: {schema_names}")
            # Capture trimmed DF info for debug logging
            for i, (orig_df, trimmed_df) in enumerate(zip(original_dfs, self._state.dfs)):
                self._state.trimmed_df_info.append({
                    "df_index": i,
                    "original_columns": list(orig_df.columns) if hasattr(orig_df, 'columns') else [],
                    "trimmed_columns": list(trimmed_df.columns) if hasattr(trimmed_df, 'columns') else [],
                    "original_shape": getattr(orig_df, 'shape', None),
                    "trimmed_shape": getattr(trimmed_df, 'shape', None),
                    "original_schema_names": [c.name for c in orig_df.schema.columns] if hasattr(orig_df, 'schema') and orig_df.schema else [],
                    "trimmed_schema_names": [c.name for c in trimmed_df.schema.columns] if hasattr(trimmed_df, 'schema') and trimmed_df.schema else [],
                })
        else:
            reason = ("forced off" if self._state.config.column_selection_enabled is False
                      else f"{total_cols} cols < threshold ({self._state.config.column_selection_threshold})")
            self._state.logger.log(f"[Column Selection] Skipped: {reason}")

        # === Isolate Step 2 from conversation history ===
        # When column selection is active, Step 2 (code generation) must not
        # see previous conversation history or last_code_generated — those may
        # contain column references from a different column selection, causing
        # the LLM to generate code referencing columns not in the trimmed set.
        # Step 1 retains full access via build_step1_memory().
        saved_memory = None
        saved_last_code = None
        if original_dfs is not None:
            saved_memory = self._state.memory
            saved_last_code = self._state.last_code_generated

            step2_memory = Memory(
                memory_size=1,
                agent_description=saved_memory.agent_description,
            )
            self._state.memory = step2_memory
            self._state.last_code_generated = None

        # === Step 1 Only mode ===
        # When STEP1_ONLY env var is set (or step1_only flag is True),
        # stop after column selection and return the selected columns
        # without running Step 2 (code generation). Useful for debugging
        # and testing the column selection pipeline in isolation.
        step1_only = os.environ.get("STEP1_ONLY", "").strip().lower() in ("1", "true", "yes")
        step1_only = step1_only or self._state.step1_only
        if step1_only:
            self._state.logger.log("[Step 1 Only] Skipping Step 2 (code generation). Returning column selection results only.")
            # Restore original DataFrames and memory (same as finally block)
            if saved_memory is not None:
                for msg in self._state.memory.all():
                    saved_memory.add(msg["message"], msg["is_user"])
                self._state.memory = saved_memory
                self._state.last_code_generated = saved_last_code
            if original_dfs is not None:
                self._state.dfs = original_dfs
            # Return a special result indicating Step 1 only
            from pandasai.core.response.string import StringResponse
            selected = self._state.last_selected_names or []
            return StringResponse(
                value=f"[STEP1_ONLY] Column selection complete. {len(selected)} columns selected.",
            )

        # Step 2: Code Generation
        code = ""
        try:
            _tcg0 = time.time()
            code = self.generate_code_with_retries(str(query))
            self._state.timings["code_generation"] = round(time.time() - _tcg0, 2)
            self._state.logger.log(
                f"[Timing] code_generation={self._state.timings['code_generation']}s "
                f"(attempts={len(self._state.code_attempts)})"
            )

            # Execute code with retries
            _tex0 = time.time()
            result = self.execute_with_retries(code)
            self._state.timings["code_execution"] = round(time.time() - _tex0, 2)
            self._state.logger.log(
                f"[Timing] code_execution={self._state.timings['code_execution']}s"
            )

            # Issue 8: Store assistant message for multi-turn context
            self._store_assistant_message(result, output_type)

            self._state.timings["total"] = round(time.time() - _t0, 2)
            self._state.logger.log("Response generated successfully.")
            return result

        except CodeExecutionError as exc:
            error_result = self._handle_exception(code)
            # Store the error as an assistant message so that the merge-back
            # in the finally block can transfer it to the original memory.
            self._store_error_message(error_result, code)
            return error_result
        except Exception as exc:
            # Unexpected error during code generation — still store something
            # so the merge-back doesn't lose the turn entirely.
            error_text = f"Error: {type(exc).__name__}: {exc}"
            self._state.memory.add(error_text, is_user=False)
            raise
        finally:
            # Merge Step 2's messages (user query + assistant response with
            # executed code) back into the original memory so Step 1 on the
            # next turn has full context. Then restore the original memory
            # and last_code_generated.
            if saved_memory is not None:
                for msg in self._state.memory.all():
                    saved_memory.add(msg["message"], msg["is_user"])
                self._state.memory = saved_memory
                self._state.last_code_generated = saved_last_code

            # ALWAYS restore original DataFrames — even on exception
            if original_dfs is not None:
                self._state.dfs = original_dfs

    def _regenerate_code_after_error(self, code: str, error: Exception) -> str:
        """Generate a new code snippet based on the error."""
        error_trace = traceback.format_exc()
        self._state.logger.log(f"Execution failed with error: {error_trace}")

        if isinstance(error, InvalidLLMOutputType):
            prompt = get_correct_output_type_error_prompt(
                self._state, code, error_trace
            )
        else:
            prompt = get_correct_error_prompt_for_sql(self._state, code, error_trace)

        return self._code_generator.generate_code(prompt)

    def _handle_exception(self, code: str) -> ErrorResponse:
        """Handle exceptions and return an error message."""
        error_message = traceback.format_exc()
        self._state.logger.log(f"Processing failed with error: {error_message}")

        return ErrorResponse(last_code_executed=code, error=error_message)

    def _store_assistant_message(self, result, output_type: Optional[str] = None):
        """Store the assistant's response in memory for multi-turn context.

        Issue 8: Stores for output_type "string" and "number" — these produce
        compact, useful context for the LLM on follow-up turns.

        Does NOT store for "dataframe", "plot", or None — these types produce
        responses that are too large or not useful as LLM context.
        """
        if output_type not in ("string", "number"):
            return

        response_text = str(result) if result else ""
        working_code = self._state.last_code_executed or ""

        if response_text and working_code:
            assistant_msg = f"{response_text}\n\n```python\n{working_code}\n```"
        elif working_code:
            assistant_msg = f"```python\n{working_code}\n```"
        else:
            return

        self._state.memory.add(assistant_msg, is_user=False)

    def _store_error_message(self, error_result: "ErrorResponse", code: str):
        """Store an error response in memory for multi-turn context.

        When code execution fails, the error response still needs to be
        recorded in memory so that the merge-back logic in _process_query's
        finally block can transfer it to the original memory. Without this,
        a failed turn produces no assistant message, which breaks the
        expected user/assistant alternating pattern in conversation history.
        """
        error_text = str(error_result) if error_result else ""
        working_code = code or ""

        if working_code:
            assistant_msg = f"{error_text}\n\n```python\n{working_code}\n```"
        else:
            assistant_msg = error_text

        if assistant_msg:
            self._state.memory.add(assistant_msg, is_user=False)

    def _should_select_columns(self) -> bool:
        """Check if 2-step column selection should be used.

        Tri-state logic for ``column_selection_enabled``:
          - ``True``  → force on (always select columns)
          - ``False`` → force off (never select columns)
          - ``None``  → auto-detect: select if total cols >= threshold
        """
        config = self._state.config
        if config.column_selection_enabled is True:
            return True
        if config.column_selection_enabled is False:
            return False
        # None → auto-detect via threshold
        total_cols = sum(len(df.columns) for df in self._state.dfs)
        return total_cols >= config.column_selection_threshold

    def _apply_column_selection(self, query: str):
        """Step 1: Select columns and swap in trimmed DataFrames.

        On failure, logs a warning and falls back to using all columns.
        The original DataFrames are preserved in ``_process_query``'s
        ``original_dfs`` variable and restored in the ``finally`` block.
        """
        # Reset per-query column selection log
        self._state.column_selection_log = []

        try:
            from pandasai.core.column_selector import ColumnSelector

            selector = ColumnSelector(self._state)

            # Capture the column selection prompt for debug logging
            _tp0 = time.time()
            self._state.column_selection_prompt = str(selector._build_prompt(query))

            # Use a temporary Memory with reduced size for Step 1
            original_memory = self._state.memory
            self._state.memory = selector.build_step1_memory()

            try:
                # Time ONLY the LLM call inside select() separately from the
                # schema matching / trimming that follows.  The column-selection
                # LLM call is where the ~135s / 400s timeouts occur, so split it
                # out so we never confuse it with codegen latency again.
                _tllm0 = time.time()
                selected_names = selector.select(query)
                self._state.timings["column_selection_llm"] = round(time.time() - _tllm0, 2)
                self._state.logger.log(
                    f"[Timing] column_selection_llm={self._state.timings['column_selection_llm']}s"
                )
            finally:
                # Always restore the full memory for Step 2
                self._state.memory = original_memory

            # Capture the raw LLM response for column selection
            # (The ColumnSelector.select() method parses the LLM response internally;
            #  we capture the raw response from the last LLM call via the state)
            if hasattr(selector, '_last_raw_response'):
                self._state.column_selection_raw_llm_response = selector._last_raw_response

            if not selected_names:
                self._state.logger.log("[Column Selection] LLM returned empty list — using all columns")
                self._state.column_selection_log.append({
                    "step": "llm_selection", "detail": {"selected_names": [], "result": "empty_fallback"}
                })
                return

            # Store the raw LLM-selected names on state for API response
            self._state.last_selected_names = selected_names
            self._state.logger.log(f"[Column Selection] LLM selected {len(selected_names)} columns: "
                  f"{selected_names}")
            self._state.column_selection_log.append({
                "step": "llm_selection",
                "detail": {
                    "selected_names": selected_names,
                    "count": len(selected_names),
                }
            })

            # ── Concept-based missing struct group detection ──
            # Warn if the LLM missed struct groups that should be selected
            # based on concept keywords in the query.
            self._detect_missing_struct_groups(query, selected_names)

            _ts0 = time.time()
            trimmed_dfs = []
            for i, df in enumerate(self._state.dfs):
                matched = selector.match_names_to_schema(selected_names, df)
                self._state.logger.log(f"[Column Selection] DF[{i}] matched after LLM: {matched}")
                self._state.column_selection_log.append({
                    "step": "schema_matching", "detail": {"df_index": i, "matched": matched}
                })
                if matched:
                    matched = selector.ensure_essential_columns(matched, df, query)
                    self._state.logger.log(f"[Column Selection] DF[{i}] matched after essential: {matched}")
                    self._state.column_selection_log.append({
                        "step": "essential_columns", "detail": {"df_index": i, "matched": matched}
                    })
                    trimmed_df = selector.build_trimmed_dataframe(df, matched)
                    trimmed_dfs.append(trimmed_df)
                else:
                    self._state.logger.log(f"[Column Selection] DF[{i}] no matches — keeping all columns")
                    self._state.column_selection_log.append({
                        "step": "no_matches_fallback", "detail": {"df_index": i}
                    })
                    trimmed_dfs.append(df)

            self._state.dfs = trimmed_dfs
            self._state.timings["column_selection_schema"] = round(time.time() - _ts0, 2)
            self._state.logger.log(
                f"[Timing] column_selection_schema={self._state.timings['column_selection_schema']}s"
            )
            final_col_count = sum(len(df.columns) for df in trimmed_dfs)
            self._state.logger.log(f"[Column Selection] Trimmed to {final_col_count} columns "
                  f"(after matching + essential-column guarantees)")
        except Exception as e:
            self._state.logger.log(f"[Column Selection] Failed: {e} — using all columns")
            return

    def _detect_missing_struct_groups(self, query: str, selected_names: list):
        """Log warnings when the LLM misses struct groups that should be selected
        based on concept keywords in the query.

        Uses the 5-path expansion framework (direct, measurement, evidence,
        summary, foundation) to detect gaps. This is diagnostic only —
        it does NOT modify the selection.
        """
        import re

        query_lower = query.lower()

        # Concept → (keyword patterns, 5-path expansion hints)
        # Each path describes WHAT to look for in struct group names/fields,
        # not specific struct group names — making this data-agnostic.
        CONCEPT_PATHS = {
            "skills": {
                "patterns": [r'\bskill\b', r'\bcompetenc', r'\babilit', r'\bproficien'],
                "paths": {
                    "direct": ["competenc", "skill"],
                    "measurement": ["rating", "proficien", "assessment", "score"],
                    "evidence": ["experience", "responsibilit", "duties", "achievement", "award"],
                    "summary": ["summary", "profile", "overview"],
                    "foundation": ["qualificat", "educat", "certificat", "degree"],
                },
            },
            "projects": {
                "patterns": [r'\bproject\b', r'\bassignment\b', r'\binitiative\b'],
                "paths": {
                    "direct": ["assignment", "project", "objective"],
                    "measurement": ["rating", "competenc", "performance"],
                    "evidence": ["experience", "achievement", "award", "responsibilit"],
                    "summary": ["summary", "profile"],
                    "foundation": [],
                },
            },
            "performance": {
                "patterns": [r'\bperformance\b', r'\bappraisal\b', r'\bevaluation\b'],
                "paths": {
                    "direct": ["performance", "rating"],
                    "measurement": ["competenc", "rating", "score"],
                    "evidence": ["objective", "achievement"],
                    "summary": ["summary"],
                    "foundation": [],
                },
            },
            "experience": {
                "patterns": [r'\bexperience\b', r'\bwork history\b', r'\bprevious employer\b'],
                "paths": {
                    "direct": ["experience", "employer"],
                    "measurement": [],
                    "evidence": ["assignment", "responsibilit"],
                    "summary": ["summary", "profile"],
                    "foundation": [],
                },
            },
            "education": {
                "patterns": [r'\beducat', r'\bqualificat', r'\bdegree\b', r'\bdiploma\b', r'\bacademic\b'],
                "paths": {
                    "direct": ["educat", "qualificat"],
                    "measurement": [],
                    "evidence": [],
                    "summary": [],
                    "foundation": ["degree", "certificat", "institut"],
                },
            },
            "leave": {
                "patterns": [r'\bleave\b', r'\bsick\b', r'\babsenc', r'\bholiday\b', r'\bvacation\b'],
                "paths": {
                    "direct": ["leave", "entitlement", "absence"],
                    "measurement": [],
                    "evidence": [],
                    "summary": [],
                    "foundation": [],
                },
            },
        }

        # Build a map of struct group names from the actual DataFrame schema
        struct_groups_in_schema = {}  # name → [inner_field_names]
        for df in self._state.dfs:
            if hasattr(df, 'schema') and df.schema and df.schema.columns:
                for col in df.schema.columns:
                    if col.type and 'list' in str(col.type) and 'struct' in str(col.type):
                        inner_fields = []
                        if hasattr(col, 'inner_fields') and col.inner_fields:
                            inner_fields = [f.name for f in col.inner_fields]
                        struct_groups_in_schema[col.name] = inner_fields

        if not struct_groups_in_schema:
            return  # No struct groups to check

        selected_str = " ".join(str(n) for n in selected_names).lower()

        for concept_name, concept_def in CONCEPT_PATHS.items():
            # Check if query matches this concept
            if not any(re.search(p, query_lower) for p in concept_def["patterns"]):
                continue

            # For each expansion path, find struct groups that match
            missing_by_path = {}
            for path_name, keywords in concept_def["paths"].items():
                if not keywords:
                    continue
                # Find struct groups whose name or inner fields contain any keyword
                expected_groups = set()
                for group_name, inner_fields in struct_groups_in_schema.items():
                    group_lower = group_name.lower()
                    fields_lower = " ".join(str(f) for f in inner_fields).lower()
                    if any(kw in group_lower or kw in fields_lower for kw in keywords):
                        expected_groups.add(group_name)

                # Check which expected groups are missing from the selection
                for group in expected_groups:
                    group_bracket = f"[{group.lower()}["
                    group_paren = f"{group.lower()}["
                    if group_bracket not in selected_str and group_paren not in selected_str:
                        missing_by_path.setdefault(path_name, []).append(group)

            if missing_by_path:
                all_missing = []
                for groups in missing_by_path.values():
                    all_missing.extend(groups)
                all_missing = list(dict.fromkeys(all_missing))  # dedupe, preserve order

                self._state.logger.log(
                    f"[Column Selection] ⚠ CONCEPT='{concept_name}' — "
                    f"missing struct groups by expansion path: {missing_by_path}. "
                    f"Selected: {selected_names}"
                )
                self._state.column_selection_log.append({
                    "step": "concept_gap_warning",
                    "detail": {
                        "concept": concept_name,
                        "missing_struct_groups": all_missing,
                        "missing_by_path": missing_by_path,
                        "selected_names": selected_names,
                    }
                })

    @property
    def last_generated_code(self):
        return self._state.last_code_generated

    @property
    def last_code_executed(self):
        # Prefer the tracked executed code (set after successful execution),
        # fall back to the generated code if execution hasn't completed yet
        return self._state.last_code_executed or self._state.last_code_generated

    @property
    def last_prompt_used(self):
        return self._state.last_prompt_used
