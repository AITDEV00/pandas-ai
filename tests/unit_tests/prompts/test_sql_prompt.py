"""Unit tests for the GeneratePythonCodeWithSQLPrompt class"""

import os
import sys

import pytest

import pandasai as pai
from pandasai import Agent
from pandasai.core.prompts.generate_python_code_with_sql import (
    GeneratePythonCodeWithSQLPrompt,
)
from pandasai.llm.fake import FakeLLM


class TestGeneratePythonCodeWithSQLPrompt:
    """Unit tests for the GeneratePythonCodeWithSQLPrompt class"""

    @pytest.mark.parametrize(
        "output_type,expected_in_prompt",
        [
            # No output_type → auto mode, should contain all type options
            (
                "",
                'type (possible values "string", "number", "dataframe", "plot")',
            ),
            # Specific output_type → should contain the type-specific IMPORTANT block
            (
                "number",
                'type (must be "number"), value must be int or float',
            ),
            (
                "dataframe",
                'type (must be "dataframe"), value must be pd.DataFrame or pd.Series',
            ),
            (
                "plot",
                'type (must be "plot"), value must be a string file path',
            ),
            (
                "string",
                'type (must be "string"), value must be a formatted string',
            ),
        ],
    )
    def test_output_type_in_rendered_prompt(self, output_type, expected_in_prompt):
        """Test that the output_type template is correctly rendered in the prompt."""

        os.environ["PANDABI_API_URL"] = ""
        os.environ["PANDABI_API_KEY"] = ""

        llm = FakeLLM()
        agent = Agent(
            pai.DataFrame(),
            config={"llm": llm},
        )
        prompt = GeneratePythonCodeWithSQLPrompt(
            context=agent._state,
            output_type=output_type,
        )
        prompt_content = prompt.to_string()
        if sys.platform.startswith("win"):
            prompt_content = prompt_content.replace("\r\n", "\n")

        # Verify the expected output_type text appears in the rendered prompt
        assert expected_in_prompt in prompt_content

    def test_prompt_contains_duckdb_syntax(self):
        """Test that the prompt includes DuckDB syntax guidance."""
        os.environ["PANDABI_API_URL"] = ""
        os.environ["PANDABI_API_KEY"] = ""

        llm = FakeLLM()
        agent = Agent(pai.DataFrame(), config={"llm": llm})
        prompt = GeneratePythonCodeWithSQLPrompt(
            context=agent._state, output_type=""
        )
        prompt_content = prompt.to_string()
        assert "<duckdb_syntax>" in prompt_content
        assert "DuckDB SQL" in prompt_content

    def test_prompt_contains_code_strategy(self):
        """Test that the prompt includes the code strategy section."""
        os.environ["PANDABI_API_URL"] = ""
        os.environ["PANDABI_API_KEY"] = ""

        llm = FakeLLM()
        agent = Agent(pai.DataFrame(), config={"llm": llm})
        prompt = GeneratePythonCodeWithSQLPrompt(
            context=agent._state, output_type=""
        )
        prompt_content = prompt.to_string()
        assert "<code_strategy>" in prompt_content
        assert "execute_sql_query" in prompt_content

    def test_prompt_with_specific_output_type_contains_important_block(self):
        """Test that a specific output_type produces an IMPORTANT block."""
        os.environ["PANDABI_API_URL"] = ""
        os.environ["PANDABI_API_KEY"] = ""

        llm = FakeLLM()
        agent = Agent(pai.DataFrame(), config={"llm": llm})
        prompt = GeneratePythonCodeWithSQLPrompt(
            context=agent._state, output_type="number"
        )
        prompt_content = prompt.to_string()
        assert "IMPORTANT" in prompt_content
        assert '"number"' in prompt_content

    def test_code_strategy_conditional_with_output_type(self):
        """Test Issue 13: code_strategy.tmpl conditional — when output_type is set,
        the prompt should say 'You MUST use type' instead of 'Choose the most appropriate type'."""
        os.environ["PANDABI_API_URL"] = ""
        os.environ["PANDABI_API_KEY"] = ""

        llm = FakeLLM()

        # With output_type → "You MUST use type"
        agent = Agent(pai.DataFrame(), config={"llm": llm})
        prompt_with_type = GeneratePythonCodeWithSQLPrompt(
            context=agent._state, output_type="string"
        )
        content_with_type = prompt_with_type.to_string()
        assert 'You MUST use type "string"' in content_with_type

        # Without output_type → "Choose the most appropriate type"
        agent2 = Agent(pai.DataFrame(), config={"llm": llm})
        prompt_without_type = GeneratePythonCodeWithSQLPrompt(
            context=agent2._state, output_type=""
        )
        content_without_type = prompt_without_type.to_string()
        assert "Choose the most appropriate type" in content_without_type
