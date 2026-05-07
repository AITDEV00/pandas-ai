from pandasai.helpers.dataframe_serializer import DataframeSerializer


class TestDataframeSerializer:
    def test_serialize_with_name_and_description(self, sample_df):
        """Test serialization with name and description attributes."""

        result = DataframeSerializer.serialize(sample_df)
        expected = """<table dialect="postgres" table_name="table_6c30b42101939c7bdf95f4c1052d615c" columns="[{"name": "A", "type": "integer", "samples": {"min": 1.0, "max": 3.0, "mean": 2.0, "examples": [1, 2, 3]}}, {"name": "B", "type": "integer", "samples": {"min": 4.0, "max": 6.0, "mean": 5.0, "examples": [4, 5, 6]}}]" dimensions="3x2">
A,B
1,4
2,5
3,6
</table>
"""
        assert result.replace("\r\n", "\n") == expected.replace("\r\n", "\n")

    def test_serialize_with_name_and_description_with_dialect(self, sample_df):
        """Test serialization with name and description attributes."""

        result = DataframeSerializer.serialize(sample_df, dialect="mysql")
        expected = """<table dialect="mysql" table_name="table_6c30b42101939c7bdf95f4c1052d615c" columns="[{"name": "A", "type": "integer", "samples": {"min": 1.0, "max": 3.0, "mean": 2.0, "examples": [1, 2, 3]}}, {"name": "B", "type": "integer", "samples": {"min": 4.0, "max": 6.0, "mean": 5.0, "examples": [4, 5, 6]}}]" dimensions="3x2">
A,B
1,4
2,5
3,6
</table>
"""
        assert result.replace("\r\n", "\n") == expected.replace("\r\n", "\n")

    def test_serialize_with_dataframe_long_strings(self, sample_df):
        """Test serialization with long strings to ensure truncation."""

        # Generate a DataFrame with a long string in column 'A'
        long_text = "A" * 300
        sample_df.loc[0, "A"] = long_text

        # Serialize the DataFrame
        result = DataframeSerializer.serialize(sample_df, dialect="mysql")

        # Expected truncated value (200 characters + ellipsis)
        truncated_text = long_text[: DataframeSerializer.MAX_COLUMN_TEXT_LENGTH] + "…"

        # Expected output
        expected = f"""<table dialect="mysql" table_name="table_6c30b42101939c7bdf95f4c1052d615c" columns="[{{"name": "A", "type": "integer", "samples": {{"min": 2.0, "max": 3.0, "mean": 2.5, "examples": [2.0, 3.0]}}}}, {{"name": "B", "type": "integer", "samples": {{"min": 4.0, "max": 6.0, "mean": 5.0, "examples": [4, 5, 6]}}}}]" dimensions="3x2">
A,B
{truncated_text},4
2,5
3,6
</table>
"""

        # Normalize line endings before asserting
        assert result.replace("\r\n", "\n") == expected.replace("\r\n", "\n")
