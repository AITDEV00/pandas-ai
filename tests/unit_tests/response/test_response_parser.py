"""Unit tests for ResponseParser bug fixes (Issue 9 L2).

Tests that:
- ResponseParser has _output_type attribute
- _validate_response() raises InvalidLLMOutputType when generated type != requested type
- _validate_response() does NOT raise when _output_type is None (auto mode)
- _validate_response() still raises InvalidOutputValueMismatch for structural errors
"""
import numpy as np
import pytest

from pandasai.core.response.parser import ResponseParser
from pandasai.exceptions import InvalidLLMOutputType, InvalidOutputValueMismatch


class TestResponseParserOutputType:
    """Tests for Issue 9 L2: ResponseParser._output_type validation."""

    def test_parser_has_output_type_attribute(self):
        parser = ResponseParser()
        assert hasattr(parser, "_output_type")
        assert parser._output_type is None

    def test_validate_raises_invalid_llm_output_type_on_mismatch(self):
        parser = ResponseParser()
        parser._output_type = "string"
        result = {"type": "number", "value": 42}

        with pytest.raises(InvalidLLMOutputType) as exc_info:
            parser._validate_response(result)

        assert "requested 'string'" in str(exc_info.value)
        assert "generated 'number'" in str(exc_info.value)

    def test_validate_does_not_raise_when_output_type_is_none(self):
        parser = ResponseParser()
        parser._output_type = None
        result = {"type": "number", "value": 42}

        # Should not raise — auto mode allows any type
        assert parser._validate_response(result) is True

    def test_validate_does_not_raise_when_types_match(self):
        parser = ResponseParser()
        parser._output_type = "string"
        result = {"type": "string", "value": "hello"}

        # Should not raise — types match
        assert parser._validate_response(result) is True

    def test_validate_still_raises_structural_error(self):
        parser = ResponseParser()
        parser._output_type = "string"
        result = {"type": "string"}  # Missing "value" key

        with pytest.raises(InvalidOutputValueMismatch):
            parser._validate_response(result)

    def test_validate_still_raises_value_type_mismatch(self):
        parser = ResponseParser()
        parser._output_type = "number"
        result = {"type": "number", "value": "not_a_number"}

        with pytest.raises(InvalidOutputValueMismatch):
            parser._validate_response(result)

    def test_validate_output_type_checked_before_value_type(self):
        """InvalidLLMOutputType should be raised before InvalidOutputValueMismatch."""
        parser = ResponseParser()
        parser._output_type = "string"
        # Type is "number" (wrong) AND value is a string (also wrong for number)
        result = {"type": "number", "value": "not_a_number"}

        with pytest.raises(InvalidLLMOutputType):
            parser._validate_response(result)

    @pytest.mark.parametrize(
        "requested,generated",
        [
            ("string", "number"),
            ("string", "dataframe"),
            ("string", "plot"),
            ("number", "string"),
            ("number", "dataframe"),
            ("number", "plot"),
            ("dataframe", "string"),
            ("dataframe", "number"),
            ("plot", "string"),
            ("plot", "number"),
        ],
    )
    def test_all_type_mismatches_raise(self, requested, generated):
        parser = ResponseParser()
        parser._output_type = requested
        result = {"type": generated, "value": "anything"}

        with pytest.raises(InvalidLLMOutputType):
            parser._validate_response(result)
