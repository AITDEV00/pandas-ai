"""
Unit tests for pandasai.helpers.semantic_matching

Covers the matching strategies used by the server handler step 2b to
reconcile user-provided schema entries with actual DataFrame column names.
"""

import pytest

from pandasai.helpers.semantic_matching import (
    _extract_short_name,
    _is_inner_column_of,
    extract_struct_parent,
    get_matching_schema_columns,
    merge_descriptions,
)
from pandasai.data_loader.semantic_layer_schema import Column, SemanticLayerSchema


# ------------------------------------------------------------------
# _extract_short_name
# ------------------------------------------------------------------

class TestExtractShortName:
    def test_bracket_convention(self):
        assert _extract_short_name("[Employee Master[Employee Name]]") == "Employee Name"

    def test_nested_brackets(self):
        assert _extract_short_name("[Emp[A][B][C]]") == "C"

    def test_plain_name(self):
        assert _extract_short_name("Employee Name") == "Employee Name"

    def test_single_bracket_no_inner(self):
        """A bare bracket name like '[Name]' has no inner field — returns as-is."""
        assert _extract_short_name("[Name]") == "[Name]"


# ------------------------------------------------------------------
# extract_struct_parent
# ------------------------------------------------------------------

class TestExtractStructParent:
    def test_simple_struct(self):
        assert extract_struct_parent("[Employee Achievements[Customary Name]]") == "Employee Achievements"

    def test_multi_field_struct(self):
        assert (
            extract_struct_parent(
                "[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]"
            )
            == "Employee Achievements"
        )

    def test_plain_name_returns_none(self):
        assert extract_struct_parent("Employee Name") is None

    def test_no_inner_fields_returns_none(self):
        assert extract_struct_parent("[Employee Achievements]") is None


# ------------------------------------------------------------------
# _is_inner_column_of  — the cross-contamination fix
# ------------------------------------------------------------------

class TestIsInnerColumnOf:
    """Verify that _is_inner_column_of correctly matches inner columns
    within the SAME struct parent and rejects cross-contamination between
    DIFFERENT struct parents that share inner field names.
    """

    # --- Same-parent matches (should be True) ---

    def test_same_parent_single_field(self):
        """Single inner field of the same parent struct."""
        assert _is_inner_column_of(
            "[Employee Achievements[Customary Name]]",
            "[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]",
        )

    def test_same_parent_another_field(self):
        """Another inner field of the same parent struct."""
        assert _is_inner_column_of(
            "[Employee Achievements[Manager OA Comments]]",
            "[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]",
        )

    def test_same_parent_work_experience(self):
        """Work experience inner field matched against work experience combined column."""
        assert _is_inner_column_of(
            "[CV Employee Work Experience[CV End Date]]",
            "[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]",
        )

    def test_same_parent_education(self):
        """Education inner field matched against education combined column."""
        assert _is_inner_column_of(
            "[CV Employee Education[CV End Date]]",
            "[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]",
        )

    # --- Cross-contamination rejection (should be False) ---

    def test_cross_contamination_work_exp_vs_education(self):
        """Work Experience inner field should NOT match Education combined column,
        even though both share 'CV End Date' as an inner field name."""
        assert not _is_inner_column_of(
            "[CV Employee Work Experience[CV End Date]]",
            "[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]",
        )

    def test_cross_contamination_education_vs_work_exp(self):
        """Education inner field should NOT match Work Experience combined column."""
        assert not _is_inner_column_of(
            "[CV Employee Education[CV End Date]]",
            "[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]",
        )

    def test_cross_contamination_achievements_vs_education(self):
        """Achievements inner field should NOT match Education combined column."""
        assert not _is_inner_column_of(
            "[CV Employee Achievements and Awards[CV Issue Date]]",
            "[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]",
        )

    # --- Edge cases ---

    def test_plain_schema_name_returns_false(self):
        """A plain (non-bracket) schema name should return False."""
        assert not _is_inner_column_of("Employee Name", "[Table[A][B]]")

    def test_unrelated_structs(self):
        """Completely unrelated struct parents should not match."""
        assert not _is_inner_column_of(
            "[Employee Leave Details[Leave Type]]",
            "[Employee Performance[Performance Review Period][Calculated Rating]]",
        )


# ------------------------------------------------------------------
# get_matching_schema_columns  — integration of strategies
# ------------------------------------------------------------------

class TestGetMatchingSchemaColumns:
    @pytest.fixture
    def schema(self):
        """Schema with CV columns that share inner field names."""
        columns = [
            Column(name="[CV Employee Work Experience[CV End Date]]", type="datetime", description="Work end date"),
            Column(name="[CV Employee Work Experience[CV Company Name]]", type="string", description="Company name"),
            Column(name="[CV Employee Education[CV End Date]]", type="datetime", description="Education end date"),
            Column(name="[CV Employee Education[CV Institution Name]]", type="string", description="Institution"),
            Column(name="Employee Name", type="string", description="Employee name"),
        ]
        return SemanticLayerSchema(
            name="test",
            source={"type": "csv", "path": "test.csv"},
            columns=columns,
        )

    def test_work_experience_combined_matches_only_work_exp_fields(self, schema):
        """When looking for inner fields of Work Experience combined column,
        only Work Experience schema entries should be returned — NOT Education."""
        matches = get_matching_schema_columns(
            "[CV Employee Work Experience[CV Company Name][CV Job Title][CV Start Date][CV End Date]]",
            schema,
        )
        matched_names = [m.name for m in matches]
        # Should include Work Experience fields
        assert "[CV Employee Work Experience[CV End Date]]" in matched_names
        assert "[CV Employee Work Experience[CV Company Name]]" in matched_names
        # Should NOT include Education fields
        assert "[CV Employee Education[CV End Date]]" not in matched_names
        assert "[CV Employee Education[CV Institution Name]]" not in matched_names

    def test_education_combined_matches_only_education_fields(self, schema):
        """When looking for inner fields of Education combined column,
        only Education schema entries should be returned."""
        matches = get_matching_schema_columns(
            "[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]",
            schema,
        )
        matched_names = [m.name for m in matches]
        assert "[CV Employee Education[CV End Date]]" in matched_names
        assert "[CV Employee Education[CV Institution Name]]" in matched_names
        assert "[CV Employee Work Experience[CV End Date]]" not in matched_names

    def test_exact_match_strategy(self, schema):
        """Exact match should still work."""
        matches = get_matching_schema_columns("Employee Name", schema)
        assert len(matches) == 1
        assert matches[0].name == "Employee Name"


# ------------------------------------------------------------------
# merge_descriptions
# ------------------------------------------------------------------

class TestMergeDescriptions:
    def test_merges_multiple_descriptions(self):
        cols = [
            Column(name="[Table[A]]", type="string", description="Field A desc"),
            Column(name="[Table[B]]", type="string", description="Field B desc"),
        ]
        result = merge_descriptions(cols)
        assert "A: Field A desc" in result
        assert "B: Field B desc" in result

    def test_deduplicates_same_short_name(self):
        cols = [
            Column(name="[Table[A]]", type="string", description="First A desc"),
            Column(name="[Table[A]]", type="string", description="Duplicate A desc"),
        ]
        result = merge_descriptions(cols)
        assert result == "A: First A desc"

    def test_returns_none_for_no_descriptions(self):
        cols = [
            Column(name="[Table[A]]", type="string", description=None),
        ]
        assert merge_descriptions(cols) is None
