"""Unit tests for Config new fields (Issue 19) and AgentState new fields (Issue 15).

Tests that:
- Config has column_selection_enabled, column_selection_threshold, column_selection_memory_size, auto_fill_descriptions
- Config defaults are correct
- AgentState has last_selected_names and last_query
- AgentState defaults are None
"""
import pytest

from pandasai.agent.state import AgentState
from pandasai.config import Config
from pandasai.llm.fake import FakeLLM


class TestConfigNewFields:
    """Tests for Issue 19: New config fields for column selection pipeline."""

    def test_column_selection_enabled_default(self):
        config = Config()
        assert config.column_selection_enabled is False

    def test_column_selection_threshold_default(self):
        config = Config()
        assert config.column_selection_threshold == 30

    def test_column_selection_memory_size_default(self):
        config = Config()
        assert config.column_selection_memory_size == 5

    def test_auto_fill_descriptions_default(self):
        config = Config()
        assert config.auto_fill_descriptions is False

    def test_column_selection_enabled_can_be_set(self):
        llm = FakeLLM()
        config = Config(llm=llm, column_selection_enabled=True)
        assert config.column_selection_enabled is True

    def test_column_selection_threshold_can_be_set(self):
        llm = FakeLLM()
        config = Config(llm=llm, column_selection_threshold=50)
        assert config.column_selection_threshold == 50

    def test_auto_fill_descriptions_can_be_set(self):
        llm = FakeLLM()
        config = Config(llm=llm, auto_fill_descriptions=True)
        assert config.auto_fill_descriptions is True

    def test_config_serialization_includes_new_fields(self):
        config = Config()
        data = config.model_dump()
        assert "column_selection_enabled" in data
        assert "column_selection_threshold" in data
        assert "column_selection_memory_size" in data
        assert "auto_fill_descriptions" in data


class TestAgentStateNewFields:
    """Tests for Issue 15: New AgentState fields for column selection caching."""

    def test_last_selected_names_default(self):
        llm = FakeLLM()
        config = Config(llm=llm)
        state = AgentState(_config=config)
        assert state.last_selected_names is None

    def test_last_query_default(self):
        llm = FakeLLM()
        config = Config(llm=llm)
        state = AgentState(_config=config)
        assert state.last_query is None

    def test_last_selected_names_can_be_set(self):
        llm = FakeLLM()
        config = Config(llm=llm)
        state = AgentState(_config=config)
        state.last_selected_names = ["name", "age", "salary"]
        assert state.last_selected_names == ["name", "age", "salary"]

    def test_last_query_can_be_set(self):
        llm = FakeLLM()
        config = Config(llm=llm)
        state = AgentState(_config=config)
        state.last_query = "What is the average salary?"
        assert state.last_query == "What is the average salary?"
