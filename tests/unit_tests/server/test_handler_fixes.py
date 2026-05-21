"""Unit tests for handler bug fixes (Issues 10, 11, 16, 17).

Tests that:
- _validate_output_type() rejects unsupported types like "text" (Issue 10)
- _validate_output_type() normalizes "auto" to None (Issue 10)
- _validate_output_type() passes valid types through (Issue 10)
- _coerce_response_type() coerces number→string (Issue 16)
- _coerce_response_type() coerces string→number when possible (Issue 16)
- _coerce_response_type() returns None for nonsensical coercions (Issue 16)
- _coerce_response_type() truncates large DataFrames (Issue 17)
"""
import pandas as pd
import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from server.features.chat.handler import (
    SUPPORTED_OUTPUT_TYPES,
    _validate_output_type,
    _coerce_response_type,
)


class TestValidateOutputType:
    """Tests for Issue 10: _validate_output_type()."""

    def test_none_returns_none(self):
        assert _validate_output_type(None) is None

    def test_auto_returns_none(self):
        assert _validate_output_type("auto") is None

    def test_valid_types_pass_through(self):
        for valid_type in ("string", "number", "dataframe", "plot"):
            assert _validate_output_type(valid_type) == valid_type

    def test_text_rejected_with_hint(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_output_type("text")
        assert exc_info.value.status_code == 400
        assert "Use 'string' instead of 'text'" in exc_info.value.detail

    def test_chart_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_output_type("chart")
        assert exc_info.value.status_code == 400

    def test_typo_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_output_type("strng")
        assert exc_info.value.status_code == 400

    def test_supported_types_constant(self):
        assert SUPPORTED_OUTPUT_TYPES == {"string", "number", "dataframe", "plot", "evidence", "auto"}


class TestCoerceResponseType:
    """Tests for Issue 16 + Issue 17: _coerce_response_type()."""

    def _make_response_obj(self, value, response_type):
        """Create a mock response object with .value and .type attributes."""
        obj = MagicMock()
        obj.value = value
        obj.type = response_type
        return obj

    def test_string_from_number(self):
        response = self._make_response_obj(10, "number")
        result = _coerce_response_type(response, "number", "string")
        assert result == ("10", "string")

    def test_number_from_numeric_string(self):
        response = self._make_response_obj("42", "string")
        result = _coerce_response_type(response, "string", "number")
        assert result == (42.0, "number")

    def test_number_from_non_numeric_string_returns_none(self):
        response = self._make_response_obj("hello", "string")
        result = _coerce_response_type(response, "string", "number")
        assert result is None

    def test_plot_to_string_returns_none(self):
        response = self._make_response_obj("chart.png", "plot")
        result = _coerce_response_type(response, "plot", "string")
        assert result is None

    def test_string_from_small_dataframe(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        response = self._make_response_obj(df, "dataframe")
        result = _coerce_response_type(response, "dataframe", "string")
        assert result is not None
        coerced_value, new_type = result
        assert new_type == "string"
        # Small DataFrame should include data
        assert "a" in coerced_value

    def test_string_from_large_dataframe_truncated(self):
        """Issue 17: Large DataFrames should be truncated to avoid enormous output."""
        df = pd.DataFrame({"a": range(1000), "b": range(1000)})
        response = self._make_response_obj(df, "dataframe")
        result = _coerce_response_type(response, "dataframe", "string")
        assert result is not None
        coerced_value, new_type = result
        assert new_type == "string"
        # Should contain shape info and "First 5 rows"
        assert "1000 rows" in coerced_value
        assert "First 5 rows" in coerced_value

    def test_no_coercion_when_types_match(self):
        """When actual == requested, the handler doesn't call _coerce_response_type.
        But if it did, it should return None (no coercion needed)."""
        response = self._make_response_obj("hello", "string")
        result = _coerce_response_type(response, "string", "string")
        # string→string is not a coercion case, returns None
        assert result is None

    def test_dataframe_to_number_returns_none(self):
        response = self._make_response_obj(pd.DataFrame(), "dataframe")
        result = _coerce_response_type(response, "dataframe", "number")
        assert result is None

    def test_number_to_plot_returns_none(self):
        response = self._make_response_obj(42, "number")
        result = _coerce_response_type(response, "number", "plot")
        assert result is None
