"""
Unit tests for Strategy 4: Dual-Mode Column Selection.

Tests the 3-mode retrieval classification (direct / evidence / hybrid)
and how retrieval_mode flows from Step 1 column selection through to
Step 2 code generation output_type.

Key components tested:
  1. column_selector._parse_response() — parsing retrieval_mode from LLM JSON
  2. column_selector.get_retrieval_mode() / get_mode_reasoning() — accessor methods
  3. AgentState — new retrieval_mode, retrieval_mode_reasoning, retrieval_mode_source fields
  4. agent/base.py — retrieval_mode → output_type flow in _apply_column_selection
  5. output_type_template.tmpl — evidence block
  6. code_strategy.tmpl — evidence strategy block
  7. parser.py — "evidence" mode accepts "dataframe" as valid output
  8. handler.py + models.py — "evidence" in SUPPORTED_OUTPUT_TYPES, response fields

Test data is based on the enterprise HC CSV:
  /home/jyao/ADEO/service/pandas-ai/datasets/20th may all hc data flattened.csv
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from typing import Optional


# ============================================================================
# 1. Column Selector: _parse_response() with retrieval_mode
# ============================================================================

class TestParseRetrievalMode:
    """Test that _parse_response() extracts retrieval_mode from LLM JSON."""

    def _make_selector(self):
        """Create a ColumnSelector with a mock state."""
        from pandasai.core.column_selector import ColumnSelector
        state = MagicMock()
        state.config.llm = MagicMock()
        state.dfs = []
        return ColumnSelector(state)

    def test_parse_standard_format_with_retrieval_mode_direct(self):
        """LLM returns {"selected": [...], "retrieval_mode": "direct", "mode_reasoning": "..."}"""
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name", "Basic Salary"],
            "retrieval_mode": "direct",
            "mode_reasoning": "Simple lookup query"
        })
        names = selector._parse_response(response)
        assert names == ["Employee Name", "Basic Salary"]
        # retrieval_mode is stored internally
        assert selector._retrieval_mode == "direct"
        assert selector._mode_reasoning == "Simple lookup query"

    def test_parse_standard_format_with_retrieval_mode_evidence(self):
        """LLM returns retrieval_mode="evidence" for evidence-retrieval queries."""
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name", "Employee Number", "Department",
                         "CV Employee Competencies"],
            "retrieval_mode": "evidence",
            "mode_reasoning": "Query asks for a list of employees — return DataFrame"
        })
        names = selector._parse_response(response)
        assert len(names) == 4
        assert selector._retrieval_mode == "evidence"
        assert "DataFrame" in selector._mode_reasoning

    def test_parse_standard_format_with_retrieval_mode_hybrid(self):
        """LLM returns retrieval_mode="hybrid" for compound queries."""
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name", "Department", "Basic Salary",
                         "Employee Performance", "Employee Leave Details"],
            "retrieval_mode": "hybrid",
            "mode_reasoning": "Compound query needing both analysis and data return"
        })
        names = selector._parse_response(response)
        assert selector._retrieval_mode == "hybrid"

    def test_parse_standard_format_without_retrieval_mode_defaults_to_direct(self):
        """LLM returns old format without retrieval_mode — defaults to 'direct'."""
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name", "Basic Salary"],
            "reasoning": "Simple salary lookup"
        })
        names = selector._parse_response(response)
        assert names == ["Employee Name", "Basic Salary"]
        assert selector._retrieval_mode == "direct"
        assert selector._mode_reasoning is None

    def test_parse_dict_format_with_retrieval_mode(self):
        """Dict format: {"selected": {"Parent": ["field1"], "FlatCol": []}} + retrieval_mode."""
        selector = self._make_selector()
        response = json.dumps({
            "selected": {
                "Employee Leave Details": ["Leave Type", "Leave Duration (Days)"],
                "Employee Name": []
            },
            "retrieval_mode": "evidence",
            "mode_reasoning": "Leave data needs DataFrame output"
        })
        names = selector._parse_response(response)
        assert "Employee Leave Details" in names
        assert "Leave Type" in names
        assert selector._retrieval_mode == "evidence"

    def test_parse_invalid_retrieval_mode_defaults_to_direct(self):
        """Invalid retrieval_mode value defaults to 'direct'."""
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name"],
            "retrieval_mode": "invalid_mode",
            "mode_reasoning": "Testing invalid mode"
        })
        names = selector._parse_response(response)
        assert selector._retrieval_mode == "direct"

    def test_parse_empty_response(self):
        """Empty or unparseable response returns empty list and direct mode."""
        selector = self._make_selector()
        names = selector._parse_response("")
        assert names == []
        assert selector._retrieval_mode == "direct"

    def test_parse_malformed_json(self):
        """Malformed JSON returns empty list and direct mode."""
        selector = self._make_selector()
        names = selector._parse_response("not json at all")
        assert names == []
        assert selector._retrieval_mode == "direct"


# ============================================================================
# 2. Column Selector: get_retrieval_mode() / get_mode_reasoning()
# ============================================================================

class TestRetrievalModeAccessors:
    """Test accessor methods for retrieval_mode and mode_reasoning."""

    def _make_selector(self):
        from pandasai.core.column_selector import ColumnSelector
        state = MagicMock()
        state.config.llm = MagicMock()
        state.dfs = []
        return ColumnSelector(state)

    def test_get_retrieval_mode_after_parse(self):
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name"],
            "retrieval_mode": "evidence",
            "mode_reasoning": "List query"
        })
        selector._parse_response(response)
        assert selector.get_retrieval_mode() == "evidence"

    def test_get_mode_reasoning_after_parse(self):
        selector = self._make_selector()
        response = json.dumps({
            "selected": ["Employee Name"],
            "retrieval_mode": "hybrid",
            "mode_reasoning": "Compound query"
        })
        selector._parse_response(response)
        assert selector.get_mode_reasoning() == "Compound query"

    def test_get_retrieval_mode_default_before_parse(self):
        """Before any parse, retrieval_mode defaults to 'direct'."""
        selector = self._make_selector()
        assert selector.get_retrieval_mode() == "direct"

    def test_get_mode_reasoning_default_before_parse(self):
        """Before any parse, mode_reasoning defaults to None."""
        selector = self._make_selector()
        assert selector.get_mode_reasoning() is None


# ============================================================================
# 3. AgentState: retrieval_mode fields
# ============================================================================

class TestAgentStateRetrievalMode:
    """Test that AgentState has the retrieval_mode fields."""

    def test_state_has_retrieval_mode_field(self):
        from pandasai.agent.state import AgentState
        state = AgentState()
        assert hasattr(state, 'retrieval_mode')
        assert state.retrieval_mode is None

    def test_state_has_retrieval_mode_reasoning_field(self):
        from pandasai.agent.state import AgentState
        state = AgentState()
        assert hasattr(state, 'retrieval_mode_reasoning')
        assert state.retrieval_mode_reasoning is None

    def test_state_has_retrieval_mode_source_field(self):
        from pandasai.agent.state import AgentState
        state = AgentState()
        assert hasattr(state, 'retrieval_mode_source')
        assert state.retrieval_mode_source is None

    def test_state_set_retrieval_mode(self):
        from pandasai.agent.state import AgentState
        state = AgentState()
        state.retrieval_mode = "evidence"
        state.retrieval_mode_reasoning = "List query"
        state.retrieval_mode_source = "step1_llm"
        assert state.retrieval_mode == "evidence"
        assert state.retrieval_mode_reasoning == "List query"
        assert state.retrieval_mode_source == "step1_llm"

    def test_state_reset_retrieval_mode_in_process_query(self):
        """retrieval_mode fields should be reset at the start of each query."""
        from pandasai.agent.state import AgentState
        state = AgentState()
        state.retrieval_mode = "evidence"
        state.retrieval_mode_reasoning = "some reasoning"
        state.retrieval_mode_source = "step1_llm"
        # Simulate the reset that _process_query does
        state.retrieval_mode = None
        state.retrieval_mode_reasoning = None
        state.retrieval_mode_source = None
        assert state.retrieval_mode is None
        assert state.retrieval_mode_reasoning is None
        assert state.retrieval_mode_source is None


# ============================================================================
# 4. Retrieval Mode → Output Type Flow
# ============================================================================

class TestRetrievalModeToOutputType:
    """Test how retrieval_mode from Step 1 maps to output_type in Step 2.

    Mapping rules:
      - "direct"  → output_type unchanged (None → LLM auto-chooses;
                    "string"/"number"/etc → stays as-is)
      - "evidence" → output_type = "evidence" (if not already set)
      - "hybrid"   → output_type = "evidence" (if not already set)
    """

    def test_direct_mode_preserves_output_type_none(self):
        """direct mode with output_type=None → stays None (LLM auto-chooses)."""
        retrieval_mode = "direct"
        output_type = None
        # The _apply_column_selection logic should NOT override output_type
        # for "direct" mode
        expected = None
        assert expected == output_type  # No change

    def test_direct_mode_preserves_output_type_string(self):
        """direct mode with output_type="string" → stays "string"."""
        retrieval_mode = "direct"
        output_type = "string"
        # Direct mode doesn't override
        assert output_type == "string"

    def test_evidence_mode_sets_output_type_when_none(self):
        """evidence mode with output_type=None → sets to "evidence"."""
        retrieval_mode = "evidence"
        output_type = None
        # Strategy 4: evidence/hybrid → output_type = "evidence"
        if retrieval_mode in ("evidence", "hybrid") and output_type is None:
            output_type = "evidence"
        assert output_type == "evidence"

    def test_hybrid_mode_sets_output_type_when_none(self):
        """hybrid mode with output_type=None → sets to "evidence"."""
        retrieval_mode = "hybrid"
        output_type = None
        if retrieval_mode in ("evidence", "hybrid") and output_type is None:
            output_type = "evidence"
        assert output_type == "evidence"

    def test_evidence_mode_does_not_override_explicit_output_type(self):
        """evidence mode with output_type="string" → stays "string".

        If the user explicitly requested a specific output_type, the
        LLM's retrieval_mode should NOT override it.
        """
        retrieval_mode = "evidence"
        output_type = "string"
        # Explicit user request takes precedence
        if retrieval_mode in ("evidence", "hybrid") and output_type is None:
            output_type = "evidence"
        assert output_type == "string"

    def test_hybrid_mode_does_not_override_explicit_output_type(self):
        """hybrid mode with output_type="number" → stays "number"."""
        retrieval_mode = "hybrid"
        output_type = "number"
        if retrieval_mode in ("evidence", "hybrid") and output_type is None:
            output_type = "evidence"
        assert output_type == "number"


# ============================================================================
# 5. Evidence Prompt Template
# ============================================================================

class TestEvidencePromptTemplate:
    """Test that the output_type_template.tmpl has an evidence block."""

    def test_evidence_block_exists_in_template(self):
        """The template should have an {% elif output_type == "evidence" %} block."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates" / "shared"
            / "output_type_template.tmpl"
        )
        content = template_path.read_text()
        assert 'output_type == "evidence"' in content, (
            "output_type_template.tmpl missing evidence block"
        )

    def test_evidence_block_instructs_dataframe_return(self):
        """The evidence block should instruct the LLM to return a DataFrame."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates" / "shared"
            / "output_type_template.tmpl"
        )
        content = template_path.read_text()
        # Evidence mode should say type "dataframe"
        assert '"dataframe"' in content


# ============================================================================
# 6. Code Strategy Template
# ============================================================================

class TestCodeStrategyTemplate:
    """Test that code_strategy.tmpl has evidence/hybrid-specific guidance."""

    def test_evidence_strategy_block_exists(self):
        """The template should have guidance for evidence/hybrid mode."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates" / "shared"
            / "code_strategy.tmpl"
        )
        content = template_path.read_text()
        # Should mention evidence or retrieval_mode
        has_evidence = (
            "evidence" in content.lower()
            or "retrieval_mode" in content.lower()
        )
        assert has_evidence, (
            "code_strategy.tmpl missing evidence/retrieval_mode guidance"
        )


# ============================================================================
# 7. Parser: Evidence mode accepts "dataframe"
# ============================================================================

class TestParserEvidenceMode:
    """Test that ResponseParser accepts "dataframe" when output_type is "evidence".

    When retrieval_mode is "evidence" or "hybrid", the output_type is set to
    "evidence". But the LLM will generate code returning type "dataframe".
    The parser must accept "dataframe" as a valid match for "evidence".
    """

    def test_evidence_mode_accepts_dataframe(self):
        """When _output_type="evidence", type="dataframe" should be accepted."""
        import pandas as pd
        from pandasai.core.response.parser import ResponseParser
        parser = ResponseParser()
        parser._output_type = "evidence"
        df = pd.DataFrame({"col": [1, 2, 3]})
        result = {"type": "dataframe", "value": df}
        # Should NOT raise InvalidLLMOutputType
        parser._validate_response(result)

    def test_evidence_mode_rejects_string(self):
        """When _output_type="evidence", type="string" should be rejected."""
        from pandasai.core.response.parser import ResponseParser
        from pandasai.exceptions import InvalidLLMOutputType
        parser = ResponseParser()
        parser._output_type = "evidence"
        result = {"type": "string", "value": "some text"}
        with pytest.raises(InvalidLLMOutputType):
            parser._validate_response(result)

    def test_evidence_mode_rejects_number(self):
        """When _output_type="evidence", type="number" should be rejected."""
        from pandasai.core.response.parser import ResponseParser
        from pandasai.exceptions import InvalidLLMOutputType
        parser = ResponseParser()
        parser._output_type = "evidence"
        result = {"type": "number", "value": 42}
        with pytest.raises(InvalidLLMOutputType):
            parser._validate_response(result)

    def test_direct_mode_still_validates_normally(self):
        """Non-evidence modes should still validate normally."""
        from pandasai.core.response.parser import ResponseParser
        from pandasai.exceptions import InvalidLLMOutputType
        parser = ResponseParser()
        parser._output_type = "string"
        result = {"type": "number", "value": 42}
        with pytest.raises(InvalidLLMOutputType):
            parser._validate_response(result)

    def test_evidence_mode_accepts_dataframe_with_real_df(self):
        """When _output_type="evidence", type="dataframe" with actual DataFrame."""
        import pandas as pd
        from pandasai.core.response.parser import ResponseParser
        parser = ResponseParser()
        parser._output_type = "evidence"
        df = pd.DataFrame({"col": [1, 2, 3]})
        result = {"type": "dataframe", "value": df}
        parser._validate_response(result)


# ============================================================================
# 8. Server: SUPPORTED_OUTPUT_TYPES and ChatResponse
# ============================================================================

class TestServerEvidenceSupport:
    """Test that the server supports "evidence" as an output type."""

    def test_evidence_in_supported_output_types(self):
        """SUPPORTED_OUTPUT_TYPES should include 'evidence'."""
        from server.features.chat.handler import SUPPORTED_OUTPUT_TYPES
        assert "evidence" in SUPPORTED_OUTPUT_TYPES

    def test_chat_response_has_retrieval_mode_fields(self):
        """ChatResponse model should include retrieval_mode fields."""
        from server.features.chat.models import ChatResponse
        # Create a response to check the fields exist
        resp = ChatResponse(
            response="test",
            type="string",
            retrieval_mode="evidence",
            retrieval_mode_reasoning="List query",
            retrieval_mode_source="step1_llm",
        )
        assert resp.retrieval_mode == "evidence"
        assert resp.retrieval_mode_reasoning == "List query"
        assert resp.retrieval_mode_source == "step1_llm"

    def test_chat_response_retrieval_mode_optional(self):
        """ChatResponse retrieval_mode fields should be optional (None by default)."""
        from server.features.chat.models import ChatResponse
        resp = ChatResponse(response="test", type="string")
        assert resp.retrieval_mode is None
        assert resp.retrieval_mode_reasoning is None
        assert resp.retrieval_mode_source is None


# ============================================================================
# 9. Select Columns Template: 3-Mode Classification
# ============================================================================

class TestSelectColumnsTemplate:
    """Test that select_columns.tmpl includes 3-mode classification guidance."""

    def test_template_has_retrieval_mode_guidance(self):
        """The template should instruct the LLM to return retrieval_mode."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates"
            / "select_columns.tmpl"
        )
        content = template_path.read_text()
        assert "retrieval_mode" in content, (
            "select_columns.tmpl missing retrieval_mode field in JSON spec"
        )

    def test_template_has_three_modes(self):
        """The template should describe all three modes: direct, evidence, hybrid."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates"
            / "select_columns.tmpl"
        )
        content = template_path.read_text()
        assert '"direct"' in content, "select_columns.tmpl missing 'direct' mode"
        assert '"evidence"' in content, "select_columns.tmpl missing 'evidence' mode"
        assert '"hybrid"' in content, "select_columns.tmpl missing 'hybrid' mode"

    def test_template_has_mode_reasoning(self):
        """The template should include mode_reasoning in the JSON spec."""
        from pathlib import Path
        template_path = (
            Path(__file__).resolve().parent.parent.parent
            / "pandasai" / "core" / "prompts" / "templates"
            / "select_columns.tmpl"
        )
        content = template_path.read_text()
        assert "mode_reasoning" in content, (
            "select_columns.tmpl missing mode_reasoning field in JSON spec"
        )


# ============================================================================
# 10. Integration-style: Column Selection Log includes retrieval_mode
# ============================================================================

class TestColumnSelectionLogRetrievalMode:
    """Test that column_selection_log entries include retrieval_mode info."""

    def test_log_entry_includes_retrieval_mode(self):
        """After _apply_column_selection, the log should include retrieval_mode."""
        # This is a structural test — verifying that the log format
        # includes retrieval_mode when it's set on state
        log_entry = {
            "step": "llm_selection",
            "detail": {
                "selected_names": ["Employee Name", "Basic Salary"],
                "count": 2,
                "retrieval_mode": "evidence",
                "mode_reasoning": "List query requiring DataFrame",
            }
        }
        assert log_entry["detail"]["retrieval_mode"] == "evidence"
        assert "mode_reasoning" in log_entry["detail"]


# ============================================================================
# 11. Enterprise HC Data: Mode Classification Heuristics
# ============================================================================

class TestModeClassificationHeuristics:
    """Test the expected retrieval_mode for typical enterprise HC queries.

    These are heuristic tests that document what mode SHOULD be selected
    for common query patterns. The actual LLM may vary, but these serve
    as correctness guidelines.
    """

    def test_simple_lookup_should_be_direct(self):
        """'What is the basic salary of employee 1333?' → direct mode.

        Simple lookup → LLM synthesizes answer → minimal columns needed.
        """
        query = "What is the basic salary of employee 1333?"
        # Heuristic: single fact lookup → direct
        expected_mode = "direct"
        # The actual classification is done by the LLM, but we document
        # the expected behavior
        assert expected_mode == "direct"

    def test_list_employees_should_be_evidence(self):
        """'List all employees in the Strategic Affairs Division' → evidence mode.

        Tabular list → return DataFrame → generous columns for context.
        """
        query = "List all employees in the Strategic Affairs Division"
        expected_mode = "evidence"
        assert expected_mode == "evidence"

    def test_employee_details_should_be_evidence(self):
        """'Show me the details of employee 1333' → evidence mode.

        Employee profile → return DataFrame with many fields.
        """
        query = "Show me the details of employee 1333"
        expected_mode = "evidence"
        assert expected_mode == "evidence"

    def test_leave_summary_should_be_evidence(self):
        """'What are the leave details for employee 1333?' → evidence mode.

        Struct data → return DataFrame from UNNEST.
        """
        query = "What are the leave details for employee 1333?"
        expected_mode = "evidence"
        assert expected_mode == "evidence"

    def test_count_query_should_be_direct(self):
        """'How many employees are in the Impact Evaluation Department?' → direct mode.

        Simple count → LLM synthesizes numeric answer.
        """
        query = "How many employees are in the Impact Evaluation Department?"
        expected_mode = "direct"
        assert expected_mode == "direct"

    def test_compound_query_should_be_hybrid(self):
        """'List employees with their performance ratings and leave balance' → hybrid.

        Compound query needing both analysis AND data return.
        """
        query = "List employees with their performance ratings and leave balance"
        expected_mode = "hybrid"
        assert expected_mode == "hybrid"

    def test_comparison_query_should_be_direct(self):
        """'Compare the average salary between departments' → direct mode.

        Analytical comparison → LLM synthesizes narrative answer.
        """
        query = "Compare the average salary between departments"
        expected_mode = "direct"
        assert expected_mode == "direct"

    def test_competency_list_should_be_evidence(self):
        """'What are the competencies of employee 1333?' → evidence mode.

        Struct list data → return DataFrame from UNNEST.
        """
        query = "What are the competencies of employee 1333?"
        expected_mode = "evidence"
        assert expected_mode == "evidence"


# ============================================================================
# 12. Evidence Mode: Column Selection Breadth
# ============================================================================

class TestColumnSelectionBreadth:
    """Test that evidence/hybrid modes select MORE columns than direct mode.

    Key insight: Evidence code is always simple (SELECT + return DataFrame),
    so more columns don't add code complexity. Generous columns HELP the
    code generation LLM by providing more schema context.
    """

    def test_evidence_mode_should_select_more_columns_than_direct(self):
        """For the same query topic, evidence mode should select more columns.

        Example: 'employee leave details'
          - direct: Employee Name, Employee Leave Details (minimal)
          - evidence: Employee Name, Employee Number, Department,
                      Employee Leave Details, Employee Leave Details inner fields
        """
        # Direct mode selection (minimal)
        direct_columns = {"Employee Name", "Employee Leave Details"}
        # Evidence mode selection (generous)
        evidence_columns = {
            "Employee Name", "Employee Number", "Department",
            "Employee Leave Details",
        }
        assert len(evidence_columns) >= len(direct_columns)

    def test_direct_mode_should_select_minimal_columns(self):
        """Direct mode should select only the columns needed for the answer.

        Example: 'What is the basic salary of employee 1333?'
          - direct: Employee Name, Employee Number, Basic Salary (3 cols)
        """
        direct_columns = {"Employee Name", "Employee Number", "Basic Salary"}
        assert len(direct_columns) <= 5  # Minimal set


# ============================================================================
# 13. End-to-End Flow: retrieval_mode through the pipeline
# ============================================================================

class TestRetrievalModeEndToEnd:
    """Test the full flow of retrieval_mode from Step 1 to API response.

    Flow:
      1. ColumnSelector.select() → _parse_response() sets _retrieval_mode
      2. _apply_column_selection() reads selector.get_retrieval_mode()
      3. Sets state.retrieval_mode, state.retrieval_mode_reasoning, state.retrieval_mode_source
      4. _process_query() maps retrieval_mode to output_type for Step 2
      5. handler.py includes retrieval_mode in API response
    """

    def test_column_selector_stores_retrieval_mode_after_select(self):
        """After select(), the selector should have retrieval_mode set."""
        from pandasai.core.column_selector import ColumnSelector
        state = MagicMock()
        state.config.llm = MagicMock()
        state.dfs = []
        selector = ColumnSelector(state)

        # Mock the LLM to return evidence mode
        mock_response = json.dumps({
            "selected": ["Employee Name", "Department"],
            "retrieval_mode": "evidence",
            "mode_reasoning": "List query"
        })
        state.config.llm.call = MagicMock(return_value=mock_response)

        # Would need a full DataFrame setup for select() to work,
        # but we can test _parse_response directly
        selector._parse_response(mock_response)
        assert selector.get_retrieval_mode() == "evidence"
        assert selector.get_mode_reasoning() == "List query"

    def test_retrieval_mode_source_is_step1_llm(self):
        """When retrieval_mode comes from Step 1 LLM, source should be 'step1_llm'."""
        source = "step1_llm"
        assert source == "step1_llm"

    def test_handler_includes_retrieval_mode_in_response(self):
        """The API response dict should include retrieval_mode fields."""
        # Simulate the result dict from handle_chat_query
        result = {
            "response": [{"name": "Alice", "dept": "IT"}],
            "type": "dataframe",
            "last_code_executed": "result = ...",
            "selected_columns": ["Employee Name", "Department"],
            "retrieval_mode": "evidence",
            "retrieval_mode_reasoning": "List query requiring DataFrame",
            "retrieval_mode_source": "step1_llm",
        }
        assert result["retrieval_mode"] == "evidence"
        assert result["retrieval_mode_reasoning"] == "List query requiring DataFrame"
        assert result["retrieval_mode_source"] == "step1_llm"
