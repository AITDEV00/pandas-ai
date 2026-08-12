from __future__ import annotations

import ast
import re
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Optional

from pandasai.core.prompts.base import BasePrompt
from pandasai.core.prompts.generate_system_message import GenerateSystemMessagePrompt
from pandasai.helpers.memory import Memory

from ..exceptions import (
    APIKeyNotFoundError,
    MethodNotImplementedError,
    NoCodeFoundError,
)

if TYPE_CHECKING:
    from pandasai.agent.state import AgentState


class LLM:
    """Base class to implement a new LLM."""

    last_prompt: Optional[str] = None

    def __init__(self, api_key: Optional[str] = None, **kwargs: Any) -> None:
        """Initialize LLM.

        Args:
            api_key (Optional[str], optional): API key for LLM. Defaults to None.
            **kwargs (Any): Additional arguments.
        """
        self.api_key = api_key

    @property
    def type(self) -> str:
        """
        Return type of LLM.

        Raises:
            APIKeyNotFoundError: Type has not been implemented

        Returns:
            str: Type of LLM a string

        """
        raise APIKeyNotFoundError("Type has not been implemented")

    def _polish_code(self, code: str) -> str:
        """
        Polish the code by removing the leading "python" or "py",  \
        removing surrounding '`' characters  and removing trailing spaces and new lines.

        Args:
            code (str): A string of Python code.

        Returns:
            str: Polished code.

        """
        if re.match(r"^(python|py)", code):
            code = re.sub(r"^(python|py)", "", code)
        if re.match(r"^`.*`$", code):
            code = re.sub(r"^`(.*)`$", r"\1", code)
        code = code.strip()
        return code

    def _is_python_code(self, string):
        """
        Return True if it is valid python code.
        Args:
            string (str):

        Returns (bool): True if Python Code otherwise False

        """
        try:
            ast.parse(string)
            return True
        except SyntaxError:
            return False

    def _extract_code(self, response: str, separator: str = "```") -> str:
        """
        Extract the code from the response.

        Args:
            response (str): Response
            separator (str, optional): Separator. Defaults to "```".

        Raises:
            NoCodeFoundError: No code found in the response

        Returns:
            str: Extracted code from the response

        """
        code = response

        # If separator is in the response then we want the code in between only
        if separator in response and len(code.split(separator)) > 1:
            code = code.split(separator)[1]
        else:
            # Fallback: try to extract code after "Code:" markers that some LLMs
            # use (e.g. "---\nCode:" or just "Code:" at the start of a line).
            # This handles small LLMs that don't use markdown code fences.
            code_after_marker = self._extract_code_after_marker(response)
            if code_after_marker is not None:
                code = code_after_marker

        code = self._polish_code(code)

        # Even if the separator is not in the response, the output might still be valid python code
        if not self._is_python_code(code):
            raise NoCodeFoundError("No code found in the response")

        return code

    def _extract_code_robust(self, response: str) -> str:
        """Extract Python code from a structured `code` field with fallbacks.

        The raw ``_extract_code`` splits on the first ``` and can fail when the
        model wraps a long program in nested markdown fences, prepends prose, or
        emits the code with trailing explanations.  This tries, in order:

          1. the standard ``_extract_code`` path;
          2. the largest ```python``` (or ```) fenced block, taken whole;
          3. the largest substring that parses as valid Python (handles prose
             before/after the program);
          4. the whole response stripped of fences.

        Raises:
            NoCodeFoundError: If no candidate parses as valid Python.
        """
        # 1. Standard extraction (handles single fence / raw code).
        try:
            return self._extract_code(response)
        except NoCodeFoundError:
            pass

        # 2 & 3) Find all fenced blocks; prefer the largest one that parses.
        candidates: list[str] = []
        for m in re.finditer(r"```(?:python|py)?\s*\n(.*?)```", response, re.DOTALL):
            candidates.append(m.group(1))
        if not candidates:
            # No fences: treat the whole thing as a candidate.
            candidates.append(response)
        # Also always consider the raw response minus any fences.
        candidates.append(re.sub(r"```(?:python|py)?\s*|```", "", response))

        # Try candidates longest-first so the real program wins over fragments.
        for cand in sorted(candidates, key=len, reverse=True):
            cand = self._polish_code(cand)
            if self._is_python_code(cand):
                return cand

        # 4) Last resort: strip leading prose up to the first 'import'/'from'/'#'.
        stripped = response
        for marker in ("import ", "from ", "# TODO"):
            idx = stripped.find(marker)
            if idx > 0 and "\n" in stripped[: idx + 1]:
                stripped = stripped[idx:]
                break
        stripped = self._polish_code(stripped)
        if self._is_python_code(stripped):
            return stripped

        raise NoCodeFoundError("No code found in the response")

    def generate_code_structured(
        self,
        instruction: BasePrompt,
        context: Any = None,
        sampling_params: Optional[dict] = None,
    ) -> "CodeGenResult":
        """Generate code via a structured, bounded 3-section response.

        Unlike the raw ``call()`` path, the model is asked to return three
        validated fields: ``reasoning_trace`` (short plan), ``double_check``
        (self-review), and ``code`` (final Python). This keeps the reasoning
        benefit of thinking-mode while bounding the output so it cannot loop.

        Base implementation falls back to the unstructured path by prompting for
        JSON. Concrete LLMs (LiteLLM) override this to use the instructor
        library for guaranteed schema adherence.

        Returns:
            CodeGenResult: The structured generation result.
        """
        from pandasai.core.code_generation.structured import CodeGenResult

        # Default: re-use the raw call and parse sections out of the response.
        response = self.call(instruction, context=context, sampling_params=sampling_params)
        return CodeGenResult(code=self._extract_code(response))

    @staticmethod
    def _extract_code_after_marker(response: str) -> Optional[str]:
        """
        Extract code that appears after a 'Code:' marker in the LLM response.
        Some small LLMs format their output as:
            [preview text]
            ---
            Code:
            import pandas as pd
            ...

        Returns the code string after the marker, or None if no marker found.
        """
        # Match "---\nCode:" or "Code:" at the start of a line (with optional
        # whitespace before/after the marker).
        for pattern in (
            r"---\s*\n\s*Code\s*:\s*\n",
            r"\n\s*Code\s*:\s*\n",
        ):
            match = re.search(pattern, response)
            if match:
                return response[match.end():]
        return None

    def prepend_system_prompt(self, prompt: str, memory: Memory) -> str | Any:
        """
        Append system prompt to the chat prompt, useful when model doesn't have messages for chat history
        Args:
            prompt (str): prompt for chat method
            memory (Memory): user conversation history
        """
        if not memory:
            return prompt

        parts = []

        # Agent description as system context
        system_prompt = self.get_system_prompt(memory)
        if system_prompt.strip():
            parts.append(system_prompt)

        # Previous conversation (for completion models that don't have a messages API)
        prev_conversation = memory.get_previous_conversation()
        if prev_conversation:
            parts.append(prev_conversation)

        parts.append(prompt)

        return "\n".join(parts)

    def get_system_prompt(self, memory: Memory) -> Any:
        """
        Generate system prompt with agent info and previous conversations
        """
        system_prompt = GenerateSystemMessagePrompt(memory=memory)
        return system_prompt.to_string()

    @abstractmethod
    def call(self, instruction: BasePrompt, context: AgentState = None) -> str:
        """
        Execute the LLM with given prompt.

        Args:
            instruction (BasePrompt): A prompt object with instruction for LLM.
            context (AgentState, optional): AgentState. Defaults to None.

        Raises:
            MethodNotImplementedError: Call method has not been implemented

        """
        raise MethodNotImplementedError("Call method has not been implemented")

    def generate_code(self, instruction: BasePrompt, context: AgentState, sampling_params: dict = None) -> str:
        """
        Generate the code based on the instruction and the given prompt.

        Args:
            instruction (BasePrompt): Prompt with instruction for LLM.
            context (AgentState): Context to pass.
            sampling_params (dict, optional): Per-call sampling parameters that
                override the LLM's default settings for this call only.

        Returns:
            str: A string of Python code.

        """
        # Structured code generation: when enabled, request a bounded 3-section
        # response (reasoning_trace + double_check + code) validated by Pydantic.
        # This keeps the reasoning benefit of thinking-mode while bounding output
        # so DeepSeek-V4-Flash cannot loop. Concrete LLMs override
        # generate_code_structured to use instructor; the base falls back to the
        # raw call.
        use_structured = False
        if context is not None:
            cfg = getattr(context, "config", None)
            if cfg is not None:
                use_structured = getattr(cfg, "code_generation_use_instructor", False)

        if use_structured:
            result = self.generate_code_structured(
                instruction, context=context, sampling_params=sampling_params
            )
            self._last_raw_response = (
                result.model_dump_json() if hasattr(result, "model_dump_json") else str(result)
            )
            # Store the reasoning/double-check sections for audit.
            self._last_structured_reasoning = getattr(result, "reasoning_trace", "")
            self._last_structured_double_check = getattr(result, "double_check", "")
            # Store the raw verification_checks list (Plan/CoVe/PoT structured fields).
            self._last_structured_verification_checks = getattr(
                result, "verification_checks", []
            )
            # Structured `code` fields can arrive wrapped in markdown fences or
            # with prose; use the robust extractor so a long valid program is
            # not rejected just because the model fenced it.
            return self._extract_code_robust(result.code)

        response = self.call(instruction, context, sampling_params=sampling_params)
        # Store the raw LLM response for debug logging
        self._last_raw_response = response
        return self._extract_code(response)
