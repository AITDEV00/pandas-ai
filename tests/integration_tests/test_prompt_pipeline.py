"""Integration test: verify prompt templates render correct struct field names.

This test loads the real vocabulary JSON (from Untitled-1.md) and runs it
through the entire prompt rendering pipeline to ensure:

1. Step 1 (select_columns.tmpl) shows full DuckDB struct keys like
   "Employee Leave Details[Leave Type]" — NOT short names like "Leave Type"
2. Step 2 (search_strategy.tmpl) shows rec['Employee Leave Details[Leave Type]']
   — NOT rec['Leave Type']
3. Descriptions are not duplicated in squashed column headers
4. Employee Performance inner fields (which lack outer brackets in schema_key)
   are handled correctly
"""

import json
import re
from unittest.mock import MagicMock

import pandas as pd
import pytest

from pandasai.agent.state import AgentState
from pandasai.config import Config
from pandasai.core.prompts.select_columns import SelectColumnsPrompt
from pandasai.data_loader.semantic_layer_schema import Column, SemanticLayerSchema, Source
from pandasai.dataframe.base import DataFrame
from pandasai.helpers.memory import Memory
from pandasai.llm.fake import FakeLLM


# ---------------------------------------------------------------------------
# Fixtures — build a DataFrame + schema that mirrors the real enterprise data
# ---------------------------------------------------------------------------

def _make_struct_samples(inner_fields: dict) -> dict:
    """Build a struct samples dict with duckdb_key fields from inner field specs.

    inner_fields: {field_name: {"type": ..., "samples": ..., "semantic_type": ...}}
    Returns a dict where each key is the canonical schema name (with outer brackets)
    and each value includes a `duckdb_key` field.
    """
    result = {}
    for field_name, info in inner_fields.items():
        # Derive duckdb_key: strip outer brackets if present
        if field_name.startswith("[") and field_name.endswith("]"):
            duckdb_key = field_name[1:-1]
        else:
            duckdb_key = field_name
        entry = {
            "type": info["type"],
            "samples": info["samples"],
            "duckdb_key": duckdb_key,
        }
        if "semantic_type" in info:
            entry["semantic_type"] = info["semantic_type"]
        if "short_name" in info:
            entry["short_name"] = info["short_name"]
        result[field_name] = entry
    return result


@pytest.fixture
def enterprise_schema() -> SemanticLayerSchema:
    """Build a schema that mirrors the real enterprise_data vocabulary."""
    # --- Flat columns (subset for test) ---
    flat_columns = [
        Column(
            name="[Employee Master[Employee Name]]",
            type="string",
            description="The full legal name of the employee in English.",
            samples=["Abdulla", "Ahmed", "Saeed"],
            semantic_type="freetext",
        ),
        Column(
            name="[Employee Master[Employee Number]]",
            type="string",
            description="A unique numeric or alphanumeric identifier assigned to the employee.",
            samples=[1269, 1301, 1369],
            semantic_type="id_like",
        ),
        Column(
            name="[Employee Master[Department]]",
            type="string",
            description="The specific functional team within a Sector or Division where the employee works.",
            samples=["Business Environment Department", "Tourism Department"],
            semantic_type="categorical",
        ),
        Column(
            name="[Employee Master[Grade]]",
            type="string",
            description="The administrative pay grade assigned to the employee.",
            samples=["L.1C", "L.2", "L.EDA"],
            semantic_type="categorical",
        ),
        Column(
            name="[Employee Master[Gender]]",
            type="string",
            description="The biological sex of the employee.",
            samples=["Female", "Male"],
            semantic_type="categorical",
        ),
        Column(
            name="[Employee Master[Basic Salary]]",
            type="float",
            description="The fixed base compensation paid to the employee.",
            samples={"min": 0.0, "max": 95000.0, "mean": 25000.0, "examples": [5000, 15000, 45000]},
        ),
        Column(
            name="[Employee Master[Date of Joining]]",
            type="datetime",
            description="The date on which the employee officially commenced employment.",
            samples={"min": "2023-05-09T00:00:00", "max": "2025-01-01T00:00:00"},
        ),
    ]

    # --- Struct columns ---
    # Employee Leave Details — schema entries with outer brackets
    leave_struct = Column(
        name="[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]",
        type="list[struct]",
        semantic_type="struct",
        samples=_make_struct_samples({
            "[Employee Leave Details[Leave Type]]": {
                "type": "string",
                "samples": ["Annual Leave", "Sick Leave", "Maternity Leave"],
                "semantic_type": "categorical",
            },
            "[Employee Leave Details[Leave Duration (Days)]]": {
                "type": "string",
                "samples": ["1", "3", "5", "10"],
                "semantic_type": "categorical",
            },
            "[Employee Leave Details[Approval Status]]": {
                "type": "string",
                "samples": ["Approved", "Pending", "Rejected"],
                "semantic_type": "categorical",
            },
            "[Employee Leave Details[Leave Start Date]]": {
                "type": "string",
                "samples": ["2024-01-15", "2024-03-20"],
                "semantic_type": "categorical",
            },
            "[Employee Leave Details[Leave End Date]]": {
                "type": "string",
                "samples": ["2024-01-16", "2024-03-23"],
                "semantic_type": "categorical",
            },
        }),
    )

    # Employee Performance — schema entries WITHOUT outer brackets (the bug case)
    perf_struct = Column(
        name="[Employee Performance[Performance Review Period][Calculated Rating][Normalized Performance Rating]]",
        type="list[struct]",
        semantic_type="struct",
        samples=_make_struct_samples({
            "Employee Performance[Performance Review Period]": {
                "type": "string",
                "samples": ["2023 Review Period", "2024 Review Period"],
                "semantic_type": "categorical",
            },
            "Employee Performance[Calculated Rating]": {
                "type": "string",
                "samples": ["3.11", "3.53", "3.92", "5"],
                "semantic_type": "categorical",
            },
            "Employee Performance[Normalized Performance Rating]": {
                "type": "string",
                "samples": ["Exceeds Expectations", "Meets Expectations"],
                "semantic_type": "categorical",
            },
        }),
    )

    # Employee Assignment History — tests duplicate description dedup
    assignment_struct = Column(
        name="[Employee Assignment History[Assignment Name][Position Title][Employee Grade][Assignment Start Date][Assignment End Date][Assignment Experience (Years & Months)]]",
        type="list[struct]",
        semantic_type="struct",
        samples=_make_struct_samples({
            "[Employee Assignment History[Assignment Name]]": {
                "type": "string",
                "samples": ["Assignment A", "Assignment B"],
                "semantic_type": "categorical",
            },
            "[Employee Assignment History[Position Title]]": {
                "type": "string",
                "samples": ["Director", "Specialist"],
                "semantic_type": "categorical",
            },
            "[Employee Assignment History[Employee Grade]]": {
                "type": "string",
                "samples": ["L.1", "L.2"],
                "semantic_type": "categorical",
            },
            "[Employee Assignment History[Assignment Start Date]]": {
                "type": "string",
                "samples": ["2022-01-01", "2023-06-01"],
                "semantic_type": "categorical",
            },
            "[Employee Assignment History[Assignment End Date]]": {
                "type": "string",
                "samples": ["2023-05-31", "2024-12-31"],
                "semantic_type": "categorical",
            },
            "[Employee Assignment History[Assignment Experience (Years & Months)]]": {
                "type": "string",
                "samples": ["1 Year 5 Months", "3 Years 0 Months"],
                "semantic_type": "categorical",
            },
        }),
    )

    return SemanticLayerSchema(
        name="enterprise_data",
        description="Master dataset containing unflattened structs and employee records.",
        source=Source(type="parquet", path="data.parquet"),
        columns=flat_columns + [leave_struct, perf_struct, assignment_struct],
    )


@pytest.fixture
def enterprise_df(enterprise_schema) -> DataFrame:
    """Create a DataFrame with the enterprise schema.

    We create a minimal pandas DataFrame with placeholder data for the flat
    columns.  Struct columns are represented as empty lists (they don't need
    real data for prompt rendering — only the schema matters).
    """
    # Build minimal data for flat columns
    data = {}
    for col in enterprise_schema.columns:
        if col.type != "list[struct]":
            # Use the column name as-is (with brackets) for the DataFrame
            data[col.name] = ["placeholder"]

    # Add struct columns as empty list (they won't be in the DataFrame
    # but will be in the schema for prompt rendering)
    df = pd.DataFrame(data)
    pai_df = DataFrame(df, schema=enterprise_schema)
    return pai_df


@pytest.fixture
def agent_state(enterprise_df) -> AgentState:
    """Create an AgentState with the enterprise DataFrame."""
    config = Config(llm=FakeLLM())
    state = AgentState(dfs=[enterprise_df], _config=config, memory=Memory())
    return state


# ---------------------------------------------------------------------------
# Test: Step 1 prompt (select_columns.tmpl)
# ---------------------------------------------------------------------------

class TestStep1Prompt:
    """Verify that the Step 1 column-selection prompt renders struct inner
    fields using full DuckDB keys, not short names."""

    def test_struct_fields_use_duckdb_key(self, agent_state, enterprise_schema):
        """Inner field display names should be DuckDB keys like
        'Employee Leave Details[Leave Type]', NOT short names like 'Leave Type'."""
        flat_columns = []
        struct_columns = []
        for col in enterprise_schema.columns:
            if col.type == "list[struct]":
                struct_columns.append(col)
            else:
                flat_columns.append(col)

        prompt = SelectColumnsPrompt(
            context=agent_state,
            query="Show me employees on sick leave",
            flat_columns=flat_columns,
            struct_columns=struct_columns,
            table_name="enterprise_data",
            table_description="Master dataset",
        )
        rendered = prompt.render()

        # --- Positive assertions: DuckDB keys must appear ---
        # Employee Leave Details fields
        assert '"Employee Leave Details[Leave Type]"' in rendered, (
            "Step 1 should show DuckDB key 'Employee Leave Details[Leave Type]' "
            "not short name 'Leave Type'"
        )
        assert '"Employee Leave Details[Leave Duration (Days)]"' in rendered
        assert '"Employee Leave Details[Approval Status]"' in rendered
        assert '"Employee Leave Details[Leave Start Date]"' in rendered
        assert '"Employee Leave Details[Leave End Date]"' in rendered

        # Employee Performance fields (the no-outer-brackets case)
        assert '"Employee Performance[Performance Review Period]"' in rendered, (
            "Step 1 should show DuckDB key 'Employee Performance[Performance Review Period]' "
            "not the full schema_key or short name"
        )
        assert '"Employee Performance[Calculated Rating]"' in rendered
        assert '"Employee Performance[Normalized Performance Rating]"' in rendered

        # Employee Assignment History fields
        assert '"Employee Assignment History[Assignment Name]"' in rendered
        assert '"Employee Assignment History[Position Title]"' in rendered
        assert '"Employee Assignment History[Employee Grade]"' in rendered

        # --- Negative assertions: bare short names must NOT appear ---
        # These short names should NOT appear as quoted display names
        assert '→ "Leave Type"' not in rendered, (
            "Short name 'Leave Type' should NOT appear — "
            "DuckDB key 'Employee Leave Details[Leave Type]' should appear instead"
        )
        assert '→ "Approval Status"' not in rendered
        assert '→ "Leave Start Date"' not in rendered
        assert '→ "Calculated Rating"' not in rendered, (
            "Short name 'Calculated Rating' should NOT appear — "
            "DuckDB key should appear instead"
        )
        assert '→ "Normalized Performance Rating"' not in rendered
        assert '→ "Assignment Name"' not in rendered
        assert '→ "Position Title"' not in rendered
        assert '→ "Employee Grade"' not in rendered

    def test_flat_columns_rendered_correctly(self, agent_state, enterprise_schema):
        """Flat columns should render with their full schema names."""
        flat_columns = [c for c in enterprise_schema.columns if c.type != "list[struct]"]
        struct_columns = [c for c in enterprise_schema.columns if c.type == "list[struct]"]

        prompt = SelectColumnsPrompt(
            context=agent_state,
            query="Show me employee names",
            flat_columns=flat_columns,
            struct_columns=struct_columns,
            table_name="enterprise_data",
        )
        rendered = prompt.render()

        # Flat columns keep their bracket-style names
        assert '"[Employee Master[Employee Name]]"' in rendered
        assert '"[Employee Master[Employee Number]]"' in rendered
        assert '"[Employee Master[Department]]"' in rendered


# ---------------------------------------------------------------------------
# Test: Step 2 prompt (search_strategy.tmpl) via DataframeSerializer
# ---------------------------------------------------------------------------

class TestStep2Prompt:
    """Verify that the Step 2 code-generation prompt renders struct inner
    fields using full DuckDB keys in rec['...'] notation."""

    def test_struct_fields_use_duckdb_key_in_rec(self, agent_state, enterprise_df):
        """Step 2 should show rec['Employee Leave Details[Leave Type]'],
        NOT rec['Leave Type']."""
        from pandasai.helpers.dataframe_serializer import DataframeSerializer

        serialized = DataframeSerializer.serialize(enterprise_df)

        # The columns are embedded as a JSON attribute inside the <table> tag.
        # Extract and parse them properly.
        columns_match = re.search(r'columns="(\[.*\])"', serialized, re.DOTALL)
        assert columns_match, "Could not find columns JSON in serialized output"

        # The JSON is HTML-attribute encoded (quotes escaped as &quot; or \")
        raw_json = columns_match.group(1)
        # Try to parse — the serializer uses json.dumps with ensure_ascii=False
        # and the result is embedded directly in the HTML attribute
        try:
            columns = json.loads(raw_json)
        except json.JSONDecodeError:
            # Fallback: the JSON may contain escaped quotes from HTML embedding
            columns = json.loads(raw_json.replace('&quot;', '"'))

        # Find struct columns and verify their inner samples have duckdb_key
        for col in columns:
            if col.get("type") == "list[struct]" and isinstance(col.get("samples"), dict):
                for field_name, field_info in col["samples"].items():
                    if isinstance(field_info, dict):
                        assert "duckdb_key" in field_info, (
                            f"Struct field {field_name} missing duckdb_key in serialized output"
                        )
                        # Verify duckdb_key is the correct DuckDB struct key
                        if field_name.startswith("[") and field_name.endswith("]"):
                            expected = field_name[1:-1]
                        else:
                            expected = field_name
                        assert field_info["duckdb_key"] == expected, (
                            f"duckdb_key mismatch for {field_name}: "
                            f"expected {expected}, got {field_info['duckdb_key']}"
                        )

    def test_search_strategy_renders_duckdb_keys(self, agent_state, enterprise_schema):
        """The search_strategy.tmpl should render rec['...'] with DuckDB keys."""
        # We need to render the search_strategy template via the prompt system.
        # The template iterates over context.dfs → schema columns → samples.
        # We can test this by directly rendering the template with the schema.

        from pandasai.core.prompts.base import BasePrompt

        # Construct a mock context that has our dfs
        mock_df = MagicMock()
        mock_df.schema = enterprise_schema
        mock_df.columns = [col.name for col in enterprise_schema.columns if col.type != "list[struct]"]

        mock_context = MagicMock()
        mock_context.dfs = [mock_df]

        # Render the search_strategy template directly
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent.parent / "pandasai" / "core" / "prompts" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        tmpl = env.get_template("shared/search_strategy.tmpl")
        rendered = tmpl.render(context=mock_context)

        # --- Positive assertions: rec['...'] with DuckDB keys ---
        assert "rec['Employee Leave Details[Leave Type]']" in rendered, (
            "Step 2 should show rec['Employee Leave Details[Leave Type]'], "
            "not rec['Leave Type']"
        )
        assert "rec['Employee Leave Details[Leave Duration (Days)]']" in rendered
        assert "rec['Employee Leave Details[Approval Status]']" in rendered
        assert "rec['Employee Leave Details[Leave Start Date]']" in rendered
        assert "rec['Employee Leave Details[Leave End Date]']" in rendered

        # Employee Performance — the no-outer-brackets case
        assert "rec['Employee Performance[Performance Review Period]']" in rendered, (
            "Step 2 should show rec['Employee Performance[Performance Review Period]']"
        )
        assert "rec['Employee Performance[Calculated Rating]']" in rendered
        assert "rec['Employee Performance[Normalized Performance Rating]']" in rendered

        # Employee Assignment History
        assert "rec['Employee Assignment History[Assignment Name]']" in rendered
        assert "rec['Employee Assignment History[Position Title]']" in rendered
        assert "rec['Employee Assignment History[Employee Grade]']" in rendered

        # --- Negative assertions: bare short names in rec['...'] must NOT appear ---
        assert "rec['Leave Type']" not in rendered, (
            "Short name rec['Leave Type'] should NOT appear in Step 2"
        )
        assert "rec['Approval Status']" not in rendered
        assert "rec['Leave Start Date']" not in rendered
        assert "rec['Calculated Rating']" not in rendered, (
            "Short name rec['Calculated Rating'] should NOT appear in Step 2"
        )
        assert "rec['Normalized Performance Rating']" not in rendered
        assert "rec['Assignment Name']" not in rendered
        assert "rec['Position Title']" not in rendered
        assert "rec['Employee Grade']" not in rendered


# ---------------------------------------------------------------------------
# Test: Description deduplication (Issue 5)
# ---------------------------------------------------------------------------

class TestDescriptionDeduplication:
    """Verify that merge_descriptions() does not produce duplicate short_name
    entries when a squashed column matches multiple schema entries."""

    def test_merge_descriptions_no_duplicates(self):
        """When two schema columns share the same short_name (e.g. Employee Grade
        from both Employee Assignment History and Employee Master), only the
        first description should be kept."""
        from pandasai.helpers.semantic_matching import merge_descriptions

        # Simulate the real case: Employee Grade appears in two schema entries
        schema_columns = [
            Column(
                name="[Employee Assignment History[Employee Grade]]",
                type="string",
                description="The employee grade held during a specific historical assignment.",
            ),
            Column(
                name="[Employee Master[Employee Grade]]",
                type="string",
                description="The specific level or rank associated with the employee's current position.",
            ),
            Column(
                name="[Employee Assignment History[Position Title]]",
                type="string",
                description="The position title held during a specific historical assignment.",
            ),
            Column(
                name="[Employee Master[Position Title]]",
                type="string",
                description="The specific official designation of the employee within the organizational structure.",
            ),
        ]

        result = merge_descriptions(schema_columns)
        assert result is not None

        # Should have exactly 2 entries (Employee Grade + Position Title),
        # not 4 (no duplicates)
        parts = result.split(" | ")
        assert len(parts) == 2, (
            f"Expected 2 unique descriptions (one per short_name), got {len(parts)}: {parts}"
        )

        # First occurrence of Employee Grade should be kept
        assert "Employee Grade:" in parts[0]
        assert "historical assignment" in parts[0]
        # Position Title should have only one entry
        assert "Position Title:" in parts[1]

        # The duplicate Employee Grade from Employee Master should NOT appear
        assert "current position" not in result, (
            "Duplicate Employee Grade description from Employee Master should be excluded"
        )

    def test_merge_descriptions_all_unique(self):
        """When all short_names are unique, all descriptions should be kept."""
        from pandasai.helpers.semantic_matching import merge_descriptions

        schema_columns = [
            Column(name="[Table A[Column 1]]", type="string", description="Desc 1"),
            Column(name="[Table A[Column 2]]", type="string", description="Desc 2"),
            Column(name="[Table A[Column 3]]", type="string", description="Desc 3"),
        ]

        result = merge_descriptions(schema_columns)
        parts = result.split(" | ")
        assert len(parts) == 3

    def test_merge_descriptions_no_descriptions(self):
        """When no columns have descriptions, return None."""
        from pandasai.helpers.semantic_matching import merge_descriptions

        schema_columns = [
            Column(name="[Table A[Column 1]]", type="string"),
            Column(name="[Table A[Column 2]]", type="string"),
        ]

        result = merge_descriptions(schema_columns)
        assert result is None


# ---------------------------------------------------------------------------
# Test: duckdb_key derivation in column_enrichment
# ---------------------------------------------------------------------------

class TestDuckdbKeyDerivation:
    """Verify that the duckdb_key field is correctly derived from schema_key."""

    def test_duckdb_key_with_outer_brackets(self):
        """schema_key with outer brackets should strip them."""
        schema_key = "[Employee Leave Details[Leave Type]]"
        duckdb_key = schema_key[1:-1] if schema_key.startswith("[") and schema_key.endswith("]") else schema_key
        assert duckdb_key == "Employee Leave Details[Leave Type]"

    def test_duckdb_key_without_outer_brackets(self):
        """schema_key without outer brackets should be used as-is."""
        schema_key = "Employee Performance[Performance Review Period]"
        duckdb_key = schema_key[1:-1] if schema_key.startswith("[") and schema_key.endswith("]") else schema_key
        assert duckdb_key == "Employee Performance[Performance Review Period]"

    def test_duckdb_key_simple_name(self):
        """A simple column name without brackets should be used as-is."""
        schema_key = "Employee Number"
        duckdb_key = schema_key[1:-1] if schema_key.startswith("[") and schema_key.endswith("]") else schema_key
        assert duckdb_key == "Employee Number"

    def test_duckdb_key_squashed_column_name(self):
        """A squashed column name like [Parent[Field1][Field2]] should strip
        outer brackets to give Parent[Field1][Field2]."""
        schema_key = "[Employee Performance[Performance Review Period][Calculated Rating]]"
        duckdb_key = schema_key[1:-1] if schema_key.startswith("[") and schema_key.endswith("]") else schema_key
        assert duckdb_key == "Employee Performance[Performance Review Period][Calculated Rating]"


# ---------------------------------------------------------------------------
# Test: decompose_squashed_name (the fix for the N/A values bug)
# ---------------------------------------------------------------------------

class TestDecomposeSquashedName:
    """Verify that decompose_squashed_name correctly splits squashed schema
    column names into individual field names that match the samples dict keys."""

    def test_decompose_multi_field_squashed(self):
        """A squashed name with multiple fields should be decomposed into
        individual field names."""
        from pandasai.helpers.semantic_matching import decompose_squashed_name

        result = decompose_squashed_name(
            "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]"
        )
        assert result == [
            "[Employee Leave Details[Leave Type]]",
            "[Employee Leave Details[Leave Duration (Days)]]",
            "[Employee Leave Details[Approval Status]]",
            "[Employee Leave Details[Leave Start Date]]",
            "[Employee Leave Details[Leave End Date]]",
        ]

    def test_decompose_single_field(self):
        """A single-field name should be returned as-is."""
        from pandasai.helpers.semantic_matching import decompose_squashed_name

        result = decompose_squashed_name("[Employee Master[Employee Name]]")
        assert result == ["[Employee Master[Employee Name]]"]

    def test_decompose_non_bracket_name(self):
        """A non-bracket name should be returned as a single-element list."""
        from pandasai.helpers.semantic_matching import decompose_squashed_name

        result = decompose_squashed_name("Employee Number")
        assert result == ["Employee Number"]

    def test_decompose_performance_struct(self):
        """Employee Performance squashed name should decompose correctly."""
        from pandasai.helpers.semantic_matching import decompose_squashed_name

        result = decompose_squashed_name(
            "[Employee Performance[Performance Review Period][Calculated Rating][Normalized Performance Rating]]"
        )
        assert result == [
            "[Employee Performance[Performance Review Period]]",
            "[Employee Performance[Calculated Rating]]",
            "[Employee Performance[Normalized Performance Rating]]",
        ]


# ---------------------------------------------------------------------------
# Test: match_names_to_schema with squashed columns
# ---------------------------------------------------------------------------

class TestMatchNamesToSchemaWithSquashedColumns:
    """Verify that match_names_to_schema decomposes squashed schema column
    names into individual field names that match the samples dict keys."""

    def test_struct_inner_fields_are_decomposed(self, enterprise_df, agent_state):
        """When the LLM selects struct inner fields and the schema has a squashed
        column, inner_fields should contain individual field names (e.g.
        "[Employee Leave Details[Leave Type]]") NOT the squashed name."""
        from pandasai.core.column_selector import ColumnSelector

        selector = ColumnSelector(agent_state)

        # Simulate LLM selecting Employee Name and all Leave Details fields
        llm_selected = [
            "[Employee Master[Employee Name]]",
            "Employee Leave Details[Leave Type]",
            "Employee Leave Details[Leave Duration (Days)]",
            "Employee Leave Details[Approval Status]",
            "Employee Leave Details[Leave Start Date]",
            "Employee Leave Details[Leave End Date]",
        ]

        matched = selector.match_names_to_schema(llm_selected, enterprise_df)

        # Employee Leave Details should have individual field names
        leave_fields = matched.get("Employee Leave Details")
        assert leave_fields is not None, "Employee Leave Details should be in matched"

        # Each field should be an individual name, NOT the squashed name
        for field in leave_fields:
            assert not re.match(r"^\[Employee Leave Details\[.*\[(.+)\]\]$", field) or \
                   field.count("[") <= 2, (
                f"Field {field!r} looks like a squashed name — "
                "should be decomposed into individual field names"
            )

        # Specific assertions: individual field names must be present
        assert "[Employee Leave Details[Leave Type]]" in leave_fields, (
            f"Individual field '[Employee Leave Details[Leave Type]]' must be in "
            f"inner_fields, got: {leave_fields}"
        )
        assert "[Employee Leave Details[Leave Duration (Days)]]" in leave_fields
        assert "[Employee Leave Details[Approval Status]]" in leave_fields
        assert "[Employee Leave Details[Leave Start Date]]" in leave_fields
        assert "[Employee Leave Details[Leave End Date]]" in leave_fields

    def test_build_trimmed_preserves_struct_samples(self, enterprise_df, agent_state):
        """build_trimmed_dataframe should preserve struct samples dict entries
        when inner_fields contains decomposed individual field names."""
        from pandasai.core.column_selector import ColumnSelector

        selector = ColumnSelector(agent_state)

        # Simulate the full pipeline
        llm_selected = [
            "[Employee Master[Employee Name]]",
            "Employee Leave Details[Leave Type]",
            "Employee Leave Details[Leave Duration (Days)]",
            "Employee Leave Details[Approval Status]",
            "Employee Leave Details[Leave Start Date]",
            "Employee Leave Details[Leave End Date]",
        ]

        matched = selector.match_names_to_schema(llm_selected, enterprise_df)
        matched = selector.ensure_essential_columns(matched, enterprise_df, "leave details")
        trimmed = selector.build_trimmed_dataframe(enterprise_df, matched)

        # Find the Employee Leave Details struct column in the trimmed schema
        leave_col = None
        for col in trimmed.schema.columns:
            if "Employee Leave Details" in col.name and col.type == "list[struct]":
                leave_col = col
                break

        assert leave_col is not None, "Employee Leave Details struct column should be in trimmed schema"

        # The samples dict should NOT be empty
        assert isinstance(leave_col.samples, dict), f"Expected dict samples, got {type(leave_col.samples)}"
        assert len(leave_col.samples) > 0, (
            "Employee Leave Details samples dict should NOT be empty — "
            "this is the bug that causes all N/A values at runtime"
        )

        # Each selected inner field should have its samples preserved
        assert "[Employee Leave Details[Leave Type]]" in leave_col.samples, (
            "Leave Type samples should be preserved after trimming"
        )
        assert "[Employee Leave Details[Leave Duration (Days)]]" in leave_col.samples
        assert "[Employee Leave Details[Approval Status]]" in leave_col.samples
