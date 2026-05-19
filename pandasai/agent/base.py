import traceback
import warnings
from typing import Any, List, Optional, Union

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

        if not df_executor:
            return db_manager.sql(final_query).df()
        else:
            return df_executor(final_query)

    def generate_code_with_retries(self, query: str) -> Any:
        """Generate code with retry logic.

        Total attempts = 1 (initial) + max_retries (regeneration attempts).
        """
        max_retries = self._state.config.max_retries
        exception = None

        for attempt in range(1 + max_retries):
            try:
                if attempt == 0:
                    return self.generate_code(query)
                else:
                    return self._regenerate_code_after_error(
                        self._state.last_code_generated, exception
                    )
            except Exception as e:
                exception = e
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
                # Issue 9 L2: Pass output_type to ResponseParser before parsing
                self._response_parser._output_type = self._state.output_type
                return self._response_parser.parse(result, code)
            except Exception as e:
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

        self._state.output_type = output_type
        self._state.assign_prompt_id()

        # Step 1: Column Selection (if needed)
        original_dfs = None
        should_select = self._should_select_columns()
        total_cols = sum(len(df.columns) for df in self._state.dfs)
        if should_select:
            reason = ("forced on" if self._state.config.column_selection_enabled is True
                      else f"{total_cols} cols ≥ threshold ({self._state.config.column_selection_threshold})")
            self._state.logger.log(f"[Column Selection] Triggered: {reason}")
            original_dfs = list(self._state.dfs)  # Shallow copy of list
            self._apply_column_selection(str(query))
            # Diagnostic: show trimmed DF column names for Step 2
            for i, df in enumerate(self._state.dfs):
                self._state.logger.log(f"[Column Selection] Trimmed DF[{i}] columns: {list(df.columns)}")
                if hasattr(df, 'schema') and df.schema:
                    schema_names = [c.name for c in df.schema.columns]
                    self._state.logger.log(f"[Column Selection] Trimmed DF[{i}] schema: {schema_names}")
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

        # Step 2: Code Generation
        code = ""
        try:
            code = self.generate_code_with_retries(str(query))

            # Execute code with retries
            result = self.execute_with_retries(code)

            # Issue 8: Store assistant message for multi-turn context
            self._store_assistant_message(result, output_type)

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
        try:
            from pandasai.core.column_selector import ColumnSelector

            selector = ColumnSelector(self._state)

            # Use a temporary Memory with reduced size for Step 1
            original_memory = self._state.memory
            self._state.memory = selector.build_step1_memory()

            try:
                selected_names = selector.select(query)
            finally:
                # Always restore the full memory for Step 2
                self._state.memory = original_memory

            if not selected_names:
                self._state.logger.log("[Column Selection] LLM returned empty list — using all columns")
                return

            # Store the raw LLM-selected names on state for API response
            self._state.last_selected_names = selected_names
            self._state.logger.log(f"[Column Selection] LLM selected {len(selected_names)} columns: "
                  f"{selected_names}")

            trimmed_dfs = []
            for i, df in enumerate(self._state.dfs):
                matched = selector.match_names_to_schema(selected_names, df)
                self._state.logger.log(f"[Column Selection] DF[{i}] matched after LLM: {matched}")
                if matched:
                    matched = selector.ensure_essential_columns(matched, df, query)
                    self._state.logger.log(f"[Column Selection] DF[{i}] matched after essential: {matched}")
                    trimmed_df = selector.build_trimmed_dataframe(df, matched)
                    trimmed_dfs.append(trimmed_df)
                else:
                    self._state.logger.log(f"[Column Selection] DF[{i}] no matches — keeping all columns")
                    trimmed_dfs.append(df)

            self._state.dfs = trimmed_dfs
            final_col_count = sum(len(df.columns) for df in trimmed_dfs)
            self._state.logger.log(f"[Column Selection] Trimmed to {final_col_count} columns "
                  f"(after matching + essential-column guarantees)")
        except Exception as e:
            self._state.logger.log(f"[Column Selection] Failed: {e} — using all columns")
            return

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
