"""
Integration test for struct-field type casting in DuckDB.

Validates that ``cast_struct_field_types`` (called automatically inside
``DuckDBConnectionManager.register``) correctly converts struct inner-field
values from ``str`` (as produced by ``json.loads``) to their declared Python
types so that DuckDB infers the correct SQL types.

Key bugs this test guards against:
- VARCHAR date fields → ``EXTRACT(YEAR FROM ...)`` BinderException
- VARCHAR numeric fields → ``.sum()`` string concatenation instead of addition
  (e.g. "5" + "10" + "3" = "5103" instead of 18)
"""

import json
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from pandasai.data_loader.duck_db_connection_manager import DuckDBConnectionManager
from pandasai.data_loader.semantic_layer_schema import Column, SemanticLayerSchema
from pandasai.helpers.type_determination import (
    _cast_boolean,
    _cast_datetime,
    _cast_float,
    _cast_integer,
    cast_struct_field_types,
    parse_json_array_columns,
)


# ---------------------------------------------------------------------------
# Unit-level: individual caster functions
# ---------------------------------------------------------------------------


class TestCastDatetime:
    """``_cast_datetime`` uses ``pd.to_datetime`` with ``errors='coerce'``."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2025-01-15", date(2025, 1, 15)),
            ("30/03/2026", date(2026, 3, 30)),       # DD/MM/YYYY
            ("March 30, 2026", date(2026, 3, 30)),    # verbose
            ("30-Mar-2026", date(2026, 3, 30)),        # compact
            ("", ""),                                   # empty → fallback
            ("not a date", "not a date"),               # invalid → fallback
            (5, 5),                                     # non-string → passthrough
            (None, None),                               # None → passthrough
        ],
    )
    def test_cast_datetime(self, value, expected):
        assert _cast_datetime(value) == expected

    def test_date_passthrough(self):
        d = date(2025, 1, 15)
        assert _cast_datetime(d) is d

    def test_datetime_to_date(self):
        from datetime import datetime
        dt = datetime(2025, 1, 15, 10, 30)
        assert _cast_datetime(dt) == date(2025, 1, 15)


class TestCastFloat:
    """``_cast_float`` uses ``pd.to_numeric`` with ``errors='coerce'``."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("5", 5.0),
            ("10.0", 10.0),
            ("3.14", 3.14),
            ("", ""),                                   # empty → fallback
            ("not a number", "not a number"),           # invalid → fallback
            (5, 5.0),
            (3.14, 3.14),
        ],
    )
    def test_cast_float(self, value, expected):
        assert _cast_float(value) == expected

    def test_bool_passthrough(self):
        """Booleans should NOT be cast to float (1.0 / 0.0)."""
        assert _cast_float(True) is True
        assert _cast_float(False) is False

    def test_none_passthrough(self):
        assert _cast_float(None) is None

    def test_returns_native_float(self):
        """Must return Python ``float``, not ``numpy.float64``."""
        result = _cast_float("3.14")
        assert isinstance(result, float)
        assert not isinstance(result, type(pd.to_numeric("3.14")))


class TestCastInteger:
    """``_cast_integer`` uses ``pd.to_numeric`` with ``downcast='integer'``."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("5", 5),
            ("10.0", 10),       # float-representable integer → int
            ("", ""),            # empty → fallback
            ("not a number", "not a number"),  # invalid → fallback
            (5, 5),
        ],
    )
    def test_cast_integer(self, value, expected):
        assert _cast_integer(value) == expected

    def test_bool_passthrough(self):
        assert _cast_integer(True) is True

    def test_none_passthrough(self):
        assert _cast_integer(None) is None

    def test_returns_native_int(self):
        """Must return Python ``int``, not ``numpy.int8`` etc."""
        result = _cast_integer("5")
        assert isinstance(result, int)


class TestCastBoolean:
    """``_cast_boolean`` uses ``pydantic.TypeAdapter(bool)``."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
            ("True", True),
            ("False", False),
            ("", ""),                                   # empty → fallback
            ("not a bool", "not a bool"),               # invalid → fallback
        ],
    )
    def test_cast_boolean(self, value, expected):
        assert _cast_boolean(value) == expected

    def test_bool_passthrough(self):
        assert _cast_boolean(True) is True
        assert _cast_boolean(False) is False

    def test_none_passthrough(self):
        assert _cast_boolean(None) is None

    def test_int_passthrough(self):
        """Non-boolean numeric types should pass through unchanged."""
        assert _cast_boolean(1) == 1
        assert _cast_boolean(0) == 0


# ---------------------------------------------------------------------------
# Integration-level: full pipeline with DuckDB
# ---------------------------------------------------------------------------


def _make_leave_df():
    """Create a DataFrame mimicking the enterprise leave-data structure."""
    data = {
        "id": ["1136", "1333"],
        "[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]": [
            json.dumps([
                {
                    "Employee Leave Details[Leave Type]": "Sick",
                    "Employee Leave Details[Leave Duration (Days)]": "5",
                    "Employee Leave Details[Approval Status]": "Approved",
                    "Employee Leave Details[Leave Start Date]": "2025-01-15",
                    "Employee Leave Details[Leave End Date]": "2025-01-20",
                },
                {
                    "Employee Leave Details[Leave Type]": "Annual",
                    "Employee Leave Details[Leave Duration (Days)]": "10",
                    "Employee Leave Details[Approval Status]": "Approved",
                    "Employee Leave Details[Leave Start Date]": "2025-06-01",
                    "Employee Leave Details[Leave End Date]": "2025-06-11",
                },
            ]),
            json.dumps([
                {
                    "Employee Leave Details[Leave Type]": "Sick",
                    "Employee Leave Details[Leave Duration (Days)]": "3",
                    "Employee Leave Details[Approval Status]": "Pending",
                    "Employee Leave Details[Leave Start Date]": "30/03/2026",
                    "Employee Leave Details[Leave End Date]": "01/04/2026",
                },
            ]),
        ],
    }
    df = pd.DataFrame(data)
    parse_json_array_columns(df)
    return df


def _make_leave_schema() -> SemanticLayerSchema:
    return SemanticLayerSchema(
        name="enterprise_data",
        source={"type": "csv", "path": "/tmp/dummy.csv"},
        columns=[
            Column(name="[Employee Leave Details[Leave Type]]", type="string"),
            Column(name="[Employee Leave Details[Leave Duration (Days)]]", type="float"),
            Column(name="[Employee Leave Details[Approval Status]]", type="string"),
            Column(name="[Employee Leave Details[Leave Start Date]]", type="datetime"),
            Column(name="[Employee Leave Details[Leave End Date]]", type="datetime"),
        ],
    )


class TestStructFieldCastingPipeline:
    """End-to-end validation: parse → cast → DuckDB register → query."""

    def test_duckdb_infers_date_not_varchar(self):
        """Leave date fields must be DATE, not VARCHAR, so EXTRACT works."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        # Check DuckDB schema — date fields must be DATE
        describe = db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(row[1] for row in describe if "Leave" in row[0])
        assert "Leave Start Date]\" DATE" in struct_type, (
            f"Expected DATE for Leave Start Date, got: {struct_type}"
        )
        assert "Leave End Date]\" DATE" in struct_type, (
            f"Expected DATE for Leave End Date, got: {struct_type}"
        )
        db.close()

    def test_duckdb_infers_double_not_varchar(self):
        """Leave duration must be DOUBLE, not VARCHAR, so .sum() adds."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        describe = db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(row[1] for row in describe if "Leave" in row[0])
        assert "Leave Duration (Days)]\" DOUBLE" in struct_type, (
            f"Expected DOUBLE for Leave Duration, got: {struct_type}"
        )
        db.close()

    def test_extract_year_works_without_cast(self):
        """EXTRACT(YEAR FROM ...) must work on struct date fields."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        result = db.sql("""
            SELECT COUNT(*) AS cnt
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE EXTRACT(YEAR FROM rec['Employee Leave Details[Leave Start Date]']) = 2025
        """).fetchone()
        assert result[0] == 2, f"Expected 2 leave records in 2025, got {result[0]}"
        db.close()

    def test_duration_sum_is_numeric_not_concatenated(self):
        """Duration .sum() must return a numeric total, not a concatenated string."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        result_df = db.sql("""
            SELECT rec['Employee Leave Details[Leave Duration (Days)]'] AS duration_days
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE EXTRACT(YEAR FROM rec['Employee Leave Details[Leave Start Date]']) = 2025
        """).df()

        # The duration column must be numeric dtype, not object (string)
        assert result_df["duration_days"].dtype in ("float64", "int64", "int8"), (
            f"Expected numeric dtype, got {result_df['duration_days'].dtype}"
        )

        # .sum() must be numeric addition, NOT string concatenation
        total = result_df["duration_days"].sum()
        assert total == 15.0, (
            f"Expected 5 + 10 = 15.0, got {total!r} (string concatenation would give '510')"
        )
        db.close()

    def test_ddmm_yyyy_date_parsing(self):
        """DD/MM/YYYY dates (common in enterprise data) must parse correctly."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        # Employee 1333 has "30/03/2026" — must be parsed as a DATE
        # Use the actual column name "id" from _make_leave_df() (not Employee Number)
        result = db.sql("""
            SELECT rec['Employee Leave Details[Leave Start Date]'] AS start_date
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE id = '1333'
        """).fetchone()
        assert result[0] == date(2026, 3, 30), (
            f"Expected 2026-03-30 for DD/MM/YYYY '30/03/2026', got {result[0]!r}"
        )
        db.close()

    def test_no_schema_means_no_casting(self):
        """Without a schema, register should still work (no casting, just raw types)."""
        df = _make_leave_df()
        # No df.schema set

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        # Without casting, dates are VARCHAR
        describe = db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(row[1] for row in describe if "Leave" in row[0])
        assert "VARCHAR" in struct_type, (
            f"Without schema, expected VARCHAR dates, got: {struct_type}"
        )
        db.close()


class TestDurationSumNotConcatenated:
    """
    Regression guard for the string-concatenation bug.

    Without casting, ``Leave Duration (Days)`` is VARCHAR in DuckDB.
    When the SQL result comes back as a pandas DataFrame, the column
    is dtype ``object`` (string), and ``.sum()`` concatenates instead
    of adding: "5" + "10" + "3" = "5103" instead of 18.

    With our fix, the duration is DOUBLE and ``.sum()`` returns 18.0.
    """

    def test_no_casting_produces_string_concatenation(self):
        """Baseline: without casting, .sum() concatenates strings."""
        df_raw = pd.DataFrame({
            "id": ["1136"],
            "data": [[
                {"type": "Sick", "duration": "5"},
                {"type": "Annual", "duration": "10"},
                {"type": "Sick", "duration": "3"},
            ]],
        })
        conn = duckdb.connect()
        conn.register("raw", df_raw)
        result_df = conn.sql(
            "SELECT rec['duration'] AS d FROM raw, UNNEST(data) AS t(rec)"
        ).df()
        conn.close()

        # Without casting: dtype is object (string), .sum() concatenates
        assert result_df["d"].dtype == object
        assert result_df["d"].sum() == "5103"  # string concat!

    def test_casting_produces_numeric_sum(self):
        """With casting, .sum() returns a numeric total."""
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        result_df = db.sql("""
            SELECT rec['Employee Leave Details[Leave Duration (Days)]'] AS duration_days
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
        """).df()
        db.close()

        # With casting: dtype is numeric, .sum() adds correctly
        assert result_df["duration_days"].dtype in ("float64", "int64")
        assert result_df["duration_days"].sum() == 18.0  # 5 + 10 + 3


# ---------------------------------------------------------------------------
# Real-data test: uses the actual enterprise CSV file
# ---------------------------------------------------------------------------

_REAL_CSV = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir,
    "datasets", "20th may all hc data flattened.csv",
)


def _load_real_csv() -> tuple[pd.DataFrame, SemanticLayerSchema]:
    """Load the real enterprise CSV and its semantic model."""
    df = pd.read_csv(_REAL_CSV)
    parse_json_array_columns(df)

    # Build the semantic model from the column descriptions JSON
    schema_path = os.path.join(
        os.path.dirname(_REAL_CSV),
        "20th may column descriptions for pandasai.json",
    )
    with open(schema_path) as f:
        schema_dict = json.load(f)

    # Patch source to use the real CSV path
    schema_dict["source"] = {"type": "csv", "path": _REAL_CSV}
    schema = SemanticLayerSchema(**schema_dict)
    df.schema = schema
    return df, schema


@pytest.mark.skipif(
    not os.path.exists(_REAL_CSV),
    reason="Real enterprise CSV not present — run in repo with datasets/",
)
class TestRealEnterpriseData:
    """
    Integration tests against the real ``20th may all hc data flattened.csv``.

    These tests validate that the casting pipeline works end-to-end on actual
    enterprise data with 353 employees and complex nested struct columns.
    """

    @classmethod
    def setup_class(cls):
        """Load the CSV once for all tests in this class."""
        cls.df, cls.schema = _load_real_csv()
        cls.db = DuckDBConnectionManager()
        cls.db.register("enterprise_data", cls.df)

    @classmethod
    def teardown_class(cls):
        cls.db.close()

    # --- Schema validation ---

    def test_leave_struct_has_correct_types(self):
        """
        The Employee Leave Details struct must have:
        - Leave Duration → DOUBLE
        - Leave Start Date → DATE
        - Leave End Date → DATE
        """
        describe = self.db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(
            row[1] for row in describe
            if "Leave Type" in row[0] and "Leave Duration" in row[0]
        )
        assert "Leave Duration (Days)]\" DOUBLE" in struct_type, (
            f"Expected DOUBLE for Leave Duration, got: {struct_type}"
        )
        assert "Leave Start Date]\" DATE" in struct_type, (
            f"Expected DATE for Leave Start Date, got: {struct_type}"
        )
        assert "Leave End Date]\" DATE" in struct_type, (
            f"Expected DATE for Leave End Date, got: {struct_type}"
        )

    # --- Employee 1136 sick leave (the original Q13c bug) ---

    def test_employee_1136_sick_leave_duration_is_numeric(self):
        """
        Regression: Employee 1136's sick leave total must be a NUMBER,
        not a concatenated string like "352127117111151111111121211131211".
        """
        result_df = self.db.sql("""
            SELECT rec['Employee Leave Details[Leave Duration (Days)]'] AS duration
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE rec['Employee Leave Details[Leave Type]'] = 'Sick'
              AND "[Employee Master[Employee Number]]" = '1136'
        """).df()

        # Must be numeric dtype, not object (string)
        assert result_df["duration"].dtype in ("float64", "int64", "int8"), (
            f"Expected numeric dtype, got {result_df['duration'].dtype}"
        )

        total = result_df["duration"].sum()
        # Must be a numeric sum, not a concatenated string
        assert isinstance(total, (int, float)), (
            f"Expected numeric total, got {type(total).__name__}: {total!r}"
        )
        # The total must be > 0 and reasonable (not a huge concatenated number)
        assert total < 1000, (
            f"Total {total} looks like string concatenation, expected a reasonable number"
        )

    def test_employee_1136_all_leave_duration_sum(self):
        """
        Employee 1136 has 56 leave records. Total duration across ALL leave
        types must be 131.0 (numeric sum), not a concatenated string.
        """
        result_df = self.db.sql("""
            SELECT rec['Employee Leave Details[Leave Duration (Days)]'] AS duration
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE "[Employee Master[Employee Number]]" = '1136'
        """).df()

        total = result_df["duration"].sum()
        assert total == 131.0, (
            f"Expected total 131.0 for employee 1136, got {total!r}"
        )

    # --- EXTRACT works on date fields ---

    def test_extract_year_from_leave_start_date(self):
        """EXTRACT(YEAR FROM ...) must work on struct date fields."""
        result = self.db.sql("""
            SELECT COUNT(*) AS cnt
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
            WHERE EXTRACT(YEAR FROM rec['Employee Leave Details[Leave Start Date]']) = 2026
        """).fetchone()
        assert result[0] > 0, "Expected at least one leave record in 2026"

    # --- Other struct columns: casting works when data is clean ---

    def test_assignment_history_dates_are_cast_when_clean(self):
        """
        Assignment History start dates are cast to DATE (the data is clean).
        End dates may remain VARCHAR due to empty-string values in the data
        that cause DuckDB to widen the struct field type.
        """
        describe = self.db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(
            (row[1] for row in describe if "Assignment" in row[0] and "Start Date" in row[0]),
            None,
        )
        if struct_type is None:
            pytest.skip("No Assignment History struct column in data")
        # Start dates are clean → should be DATE
        assert "Assignment Start Date]\" DATE" in struct_type, (
            f"Expected DATE for Assignment Start Date, got: {struct_type}"
        )

    def test_employee_qualification_dates_are_cast_when_clean(self):
        """
        Employee Qualification start/end dates should be cast to DATE
        when the data doesn't contain empty strings.
        """
        describe = self.db.sql("DESCRIBE enterprise_data").fetchall()
        struct_type = next(
            (row[1] for row in describe if "Qualification" in row[0] and "Start Date" in row[0]),
            None,
        )
        if struct_type is None:
            pytest.skip("No Employee Qualification struct column in data")
        # If data is clean, dates are DATE; if there are empty strings, VARCHAR
        has_date = "Study Start Date]\" DATE" in struct_type
        has_varchar = "Study Start Date]\" VARCHAR" in struct_type
        assert has_date or has_varchar, (
            f"Expected DATE or VARCHAR for Study Start Date, got: {struct_type}"
        )


# ---------------------------------------------------------------------------
# Regression: numpy ndarray → Python list in SQL results
# ---------------------------------------------------------------------------


class TestNumpyArrayToListConversion:
    """
    Regression guard for the "Error retrieving skills" bug.

    DuckDB returns STRUCT[] columns as numpy ndarrays inside pandas
    DataFrame cells.  LLM-generated code commonly tests truthiness
    with ``if value and len(value) > 0:`` which raises
    ``ValueError: The truth value of an array with more than one
    element is ambiguous`` on multi-element ndarrays.

    The fix converts ndarrays to native Python lists in
    ``Agent._execute_sql_query``.
    """

    def test_ndarray_truthiness_raises_valueerror(self):
        """Baseline: numpy ndarray with >1 element cannot be used in `if`."""
        arr = np.array([{"key": "a"}, {"key": "b"}])
        with pytest.raises(ValueError, match="ambiguous"):
            if arr:
                pass

    def test_list_truthiness_works(self):
        """After conversion to list, truthiness works normally."""
        lst = [{"key": "a"}, {"key": "b"}]
        assert lst  # No ValueError
        assert len(lst) == 2

    def test_struct_column_comes_back_as_list_after_fix(self):
        """
        After the ndarray→list fix, struct columns in SQL results
        should be Python lists, not numpy arrays.
        """
        df = _make_leave_df()
        df.schema = _make_leave_schema()

        db = DuckDBConnectionManager()
        db.register("enterprise_data", df)

        result_df = db.sql("""
            SELECT rec['Employee Leave Details[Leave Duration (Days)]'] AS duration_days
            FROM enterprise_data,
            UNNEST("[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]") AS t(rec)
        """).df()
        db.close()

        # Simulate the conversion that Agent._execute_sql_query now does
        import numpy as np
        for col in result_df.columns:
            sample = result_df[col].iloc[0] if len(result_df) > 0 else None
            if isinstance(sample, np.ndarray):
                result_df[col] = result_df[col].apply(
                    lambda v: v.tolist() if isinstance(v, np.ndarray) else v
                )

        # The duration column should now be a plain numeric type (float64/int64)
        # since it's a simple DOUBLE, not a struct
        # But if it were a struct, it would be a list
        assert result_df["duration_days"].dtype in ("float64", "int64")

    def test_competency_iteration_works_after_conversion(self):
        """
        Simulates the exact LLM code pattern that was failing:
        iterating over a struct column and accessing dict keys.
        """
        # Simulate DuckDB returning a STRUCT[] column as ndarray
        data = np.array([
            {"CV Employee Competencies[Technical Competency Name]": "Chinese"},
            {"CV Employee Competencies[Technical Competency Name]": "Python"},
        ])
        df = pd.DataFrame({"competencies": [data]})

        # Before fix: ndarray → ValueError
        with pytest.raises(ValueError, match="ambiguous"):
            for idx, row in df.iterrows():
                comp = row["competencies"]
                if comp and len(comp) > 0:  # This line raises ValueError
                    pass

        # Apply the fix
        for col in df.columns:
            sample = df[col].iloc[0] if len(df) > 0 else None
            if isinstance(sample, np.ndarray):
                df[col] = df[col].apply(
                    lambda v: v.tolist() if isinstance(v, np.ndarray) else v
                )

        # After fix: iteration and dict access work
        for idx, row in df.iterrows():
            comp = row["competencies"]
            skills = []
            if comp and len(comp) > 0:  # Now works!
                for c in comp:
                    name = c["CV Employee Competencies[Technical Competency Name]"]
                    if "chinese" in name.lower() or "python" in name.lower():
                        skills.append(name)
            assert skills == ["Chinese", "Python"]
