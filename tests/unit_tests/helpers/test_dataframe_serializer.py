from pandasai.helpers.dataframe_serializer import DataframeSerializer, _json_default


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


class TestJsonDefault:
    """``_json_default`` serializes non-JSON-native values (e.g. struct dates).

    Struct fields are cast to ``datetime.date`` before DuckDB registration. When
    the DataFrame is re-serialized into a prompt (error-correction template), the
    date objects must serialize without raising ``TypeError``.
    """

    def test_date_serializes_to_iso(self):
        import json
        from datetime import date

        out = json.dumps({"d": date(2025, 1, 15)}, default=_json_default)
        assert '"2025-01-15"' in out

    def test_struct_with_date_and_none(self):
        import json
        from datetime import date

        struct = [{"type": "Sick", "start": date(2025, 1, 15), "end": None}]
        out = json.loads(json.dumps(struct, default=_json_default))
        assert out[0]["start"] == "2025-01-15"
        assert out[0]["end"] is None

    def test_datetime_serializes(self):
        import json
        from datetime import datetime

        out = json.dumps(datetime(2025, 1, 15, 10, 30), default=_json_default)
        assert '"2025-01-15T10:30:00"' in out

    def test_non_serializable_falls_back_to_str(self):
        import json

        class Weird:
            def __str__(self):
                return "weird"

        out = json.dumps({"v": Weird()}, default=_json_default)
        assert '"weird"' in out
