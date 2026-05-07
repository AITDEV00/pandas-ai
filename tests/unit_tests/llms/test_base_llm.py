"""Unit tests for the base LLM class"""

import pytest

from pandasai.exceptions import APIKeyNotFoundError, NoCodeFoundError
from pandasai.helpers.memory import Memory
from pandasai.llm import LLM


class TestBaseLLM:
    """Unit tests for the base LLM class"""

    def test_type(self):
        with pytest.raises(APIKeyNotFoundError):
            LLM().type

    def test_polish_code(self):
        code = "python print('Hello World')"
        assert LLM()._polish_code(code) == "print('Hello World')"
        code = "py print('Hello World')"
        assert LLM()._polish_code(code) == "print('Hello World')"
        code = "`print('Hello World')`"
        assert LLM()._polish_code(code) == "print('Hello World')"
        code = "``print('Hello World')``"
        assert LLM()._polish_code(code) == "`print('Hello World')`"
        code = "print('Hello World')"
        assert LLM()._polish_code(code) == "print('Hello World')"
        code = "import pandas as pd\nprint('Hello World')"
        assert LLM()._polish_code(code) == "import pandas as pd\nprint('Hello World')"

    def test_is_python_code(self):
        code = "python print('Hello World')"
        assert LLM()._is_python_code(code) is False
        code = "py print('Hello World')"
        assert LLM()._is_python_code(code) is False
        code = "`print('Hello World')`"
        assert LLM()._is_python_code(code) is False
        code = "print('Hello World')"
        assert LLM()._is_python_code(code) is True
        code = "1 +"
        assert LLM()._is_python_code(code) is False
        code = "1 + 1"
        assert LLM()._is_python_code(code) is True

    def test_extract_code(self):
        code = """Sure, here is your code:
```python
print('Hello World')
```
"""
        assert LLM()._extract_code(code) == "print('Hello World')"

        code = """Sure, here is your code:

```
print('Hello World')
```
"""
        assert LLM()._extract_code(code) == "print('Hello World')"

        code = """num_rows = dfs[0].shape[0]"""
        assert LLM()._extract_code(code) == "num_rows = dfs[0].shape[0]"

        code = """Sure, here is your code:

```py
print('Hello World')
```
"""
        assert LLM()._extract_code(code) == "print('Hello World')"

        code = """Sure, here is your code:

``py
print('Hello World')
``
"""
        with pytest.raises(NoCodeFoundError) as exc:
            LLM()._extract_code(code)
        assert "No code found" in str(exc.value)

        code = """Sure, here is your code:
`py
print('Hello World')
`
"""
        with pytest.raises(NoCodeFoundError) as exc:
            LLM()._extract_code(code)
        assert "No code found" in str(exc.value)

        code = """Sure, here is your code:
print('Hello World')
"""
        with pytest.raises(NoCodeFoundError) as exc:
            LLM()._extract_code(code)
        assert "No code found" in str(exc.value)

        code = """'''"""
        with pytest.raises(NoCodeFoundError) as exc:
            LLM()._extract_code(code)
        assert "No code found" in str(exc.value)

    def test_get_system_prompt_empty_memory(self):
        # No agent_description → empty string
        assert LLM().get_system_prompt(Memory()) == ""

    def test_get_system_prompt_memory_with_agent_description(self):
        mem = Memory(agent_description="xyz")
        assert LLM().get_system_prompt(mem) == " xyz "

    def test_get_system_prompt_no_conversation_history(self):
        """System prompt should NOT include conversation history.
        Conversation history is sent via OpenAI messages array for chat models,
        or via prepend_system_prompt for completion models."""
        mem = Memory(agent_description="xyz", memory_size=10)
        mem.add("hello world", True)
        mem.add('print("hello world)', False)
        mem.add("hello world", True)
        # System prompt should only contain agent_description, NOT conversation
        assert "PREVIOUS CONVERSATION" not in LLM().get_system_prompt(mem)
        assert " xyz " in LLM().get_system_prompt(mem)

    def test_prepend_system_prompt_with_empty_mem(self):
        # Empty memory (no messages): just the prompt
        result = LLM().prepend_system_prompt("hello world", Memory())
        assert result == "hello world"

    def test_prepend_system_prompt_with_non_empty_mem(self):
        # Non-empty memory: system prompt + previous conversation + prompt
        mem = Memory(agent_description="xyz", memory_size=10)
        mem.add("hello world", True)
        mem.add('print("hello world)', False)
        mem.add("hello world", True)
        result = LLM().prepend_system_prompt("hello world", mem)
        # Should contain agent description
        assert " xyz " in result
        # Should contain previous conversation messages (for completion models)
        assert "### QUERY" in result
        assert "### ANSWER" in result
        # Should contain the prompt
        assert result.endswith("hello world")

    def test_prepend_system_prompt_with_memory_none(self):
        assert LLM().prepend_system_prompt("hello world", None) == "hello world"
