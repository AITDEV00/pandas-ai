"""Unit tests for Agent._store_assistant_message() (Issue 8).

Tests that:
- Only "string" and "number" output types are stored in memory
- DataFrame and plot results are NOT stored
- Both response text and code are stored when available
- Code-only messages are stored when no response text
- Nothing is stored when both text and code are empty
"""
import pytest
from unittest.mock import MagicMock, patch

from pandasai.agent.base import Agent
from pandasai.agent.state import AgentState
from pandasai.config import Config
from pandasai.llm.fake import FakeLLM


class TestStoreAssistantMessage:
    """Tests for Issue 8: _store_assistant_message()."""

    def _make_agent(self):
        """Create an Agent with a FakeLLM and real state."""
        llm = FakeLLM(output='result = {"type": "string", "value": "test"}')
        config = Config(llm=llm)
        state = AgentState(_config=config)
        agent = Agent.__new__(Agent)
        agent._state = state
        return agent

    def test_string_output_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "result = {'type': 'string', 'value': 'hello'}"

        initial_count = agent._state.memory.count()
        agent._store_assistant_message("hello", "string")

        assert agent._state.memory.count() == initial_count + 1

    def test_number_output_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "result = {'type': 'number', 'value': 42}"

        initial_count = agent._state.memory.count()
        agent._store_assistant_message(42, "number")

        assert agent._state.memory.count() == initial_count + 1

    def test_dataframe_output_not_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "result = {'type': 'dataframe', 'value': df}"

        initial_count = agent._state.memory.count()
        agent._store_assistant_message("some dataframe", "dataframe")

        assert agent._state.memory.count() == initial_count

    def test_plot_output_not_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "result = {'type': 'plot', 'value': 'chart.png'}"

        initial_count = agent._state.memory.count()
        agent._store_assistant_message("chart.png", "plot")

        assert agent._state.memory.count() == initial_count

    def test_none_output_type_not_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "result = {'type': 'string', 'value': 'hello'}"

        initial_count = agent._state.memory.count()
        agent._store_assistant_message("hello", None)

        assert agent._state.memory.count() == initial_count

    def test_both_text_and_code_stored(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "df['total'].sum()"

        agent._store_assistant_message("42", "number")

        messages = agent._state.memory.all()
        last_msg = messages[-1]
        assert "42" in last_msg["message"]
        assert "df['total'].sum()" in last_msg["message"]
        assert last_msg["is_user"] is False

    def test_code_only_stored_when_no_text(self):
        agent = self._make_agent()
        agent._state.last_code_executed = "df['total'].sum()"

        agent._store_assistant_message("", "number")

        messages = agent._state.memory.all()
        last_msg = messages[-1]
        assert last_msg["message"] == "df['total'].sum()"

    def test_nothing_stored_when_both_empty(self):
        agent = self._make_agent()
        agent._state.last_code_executed = ""

        initial_count = agent._state.memory.count()
        agent._store_assistant_message("", "string")

        assert agent._state.memory.count() == initial_count

    def test_nothing_stored_when_result_is_none(self):
        agent = self._make_agent()
        agent._state.last_code_executed = ""

        initial_count = agent._state.memory.count()
        agent._store_assistant_message(None, "string")

        assert agent._state.memory.count() == initial_count
