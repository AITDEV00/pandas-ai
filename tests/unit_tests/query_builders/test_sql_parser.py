import pytest

from pandasai.exceptions import MaliciousQueryError
from pandasai.query_builders.sql_parser import SQLParser


class TestSqlParser:
    @staticmethod
    @pytest.mark.parametrize(
        "query, table_mapping, expected",
        [
            (
                "SELECT * FROM customers",
                {"customers": "clients"},
                """SELECT
  *
FROM "clients" AS customers""",
            ),
            (
                "SELECT * FROM orders",
                {"orders": "(SELECT * FROM sales)"},
                """SELECT
  *
FROM (
  (
    SELECT
      *
    FROM "sales"
  )
) AS orders""",
            ),
            (
                "SELECT * FROM customers c",
                {"customers": "clients"},
                """SELECT
  *
FROM "clients" AS c""",
            ),
            (
                "SELECT c.id, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id",
                {"customers": "clients", "orders": "(SELECT * FROM sales)"},
                '''SELECT
  "c"."id",
  "o"."amount"
FROM "clients" AS c
JOIN (
  (
    SELECT
      *
    FROM "sales"
  )
) AS o
  ON "c"."id" = "o"."customer_id"''',
            ),
            (
                """SELECT d.name AS department, hse.name AS employee, hse.salary
FROM (
    SELECT * FROM employees WHERE salary > 50000
) AS hse
JOIN departments d ON hse.dept_id = d.id;
""",
                {"employees": "employee", "departments": "department"},
                """SELECT
  "d"."name" AS "department",
  "hse"."name" AS "employee",
  "hse"."salary"
FROM (
  SELECT
    *
  FROM "employee" AS employees
  WHERE
    "salary" > 50000
) AS "hse"
JOIN "department" AS d
  ON "hse"."dept_id" = "d"."id"
""",
            ),
        ],
    )
    def test_replace_table_names(query, table_mapping, expected):
        result = SQLParser.replace_table_and_column_names(query, table_mapping)
        assert result.strip() == expected.strip()

    def test_mysql_transpilation(self):
        query = '''SELECT COUNT(*) AS "total_rows"'''
        expected = """SELECT\n  COUNT(*) AS `total_rows`"""
        result = SQLParser.transpile_sql_dialect(query, to_dialect="mysql")
        assert result.strip() == expected.strip()

    @staticmethod
    @pytest.mark.parametrize(
        "sql_query, dialect, expected_tables",
        [
            # 1. Simple SELECT query
            ("SELECT * FROM users;", "postgres", ["users"]),
            # 2. Query with INNER JOIN
            (
                "SELECT * FROM users u JOIN orders o ON u.id = o.user_id;",
                "postgres",
                ["users", "orders"],
            ),
            # 3. Query with LEFT JOIN
            (
                "SELECT * FROM customers c LEFT JOIN orders o ON c.id = o.customer_id;",
                "postgres",
                ["customers", "orders"],
            ),
            # 4. Subquery
            (
                "SELECT * FROM (SELECT * FROM employees) AS e;",
                "postgres",
                ["employees"],
            ),
            # 5. CTE (Common Table Expression)
            (
                """
    WITH sales_data AS (SELECT * FROM sales)
    SELECT * FROM sales_data;
    """,
                "postgres",
                ["sales"],
            ),
            # 6. Table with alias (should return original table name)
            ("SELECT u.name FROM users AS u;", "postgres", ["users"]),
            # 7. Schema-prefixed table
            ("SELECT * FROM sales.customers;", "postgres", ["customers"]),
            # 8. Quoted table names (double quotes for PostgreSQL, backticks for MySQL)
            ('SELECT * FROM "Order Details";', "postgres", ["Order Details"]),
            # ("SELECT * FROM `Order Details`;", "mysql", ["Order Details"]),
            # 11. Edge Case: Invalid Query (should return empty list instead of raising an error)
            ("SELECT *", "postgres", []),
        ],
    )
    def test_extract_table_names(sql_query, dialect, expected_tables):
        result = SQLParser.extract_table_names(sql_query, dialect)
        assert SQLParser.extract_table_names(sql_query, dialect) == expected_tables

    # --- fix_common_llm_mistakes tests ---

    def test_fix_brackets_schema_driven(self):
        """Schema-driven: LLM wrote stripped name, schema has bracketed name."""
        sql = 'SELECT "Employee Master[Employee Name]" FROM t'
        cols = ["[Employee Master[Employee Name]]"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"[Employee Master[Employee Name]]"' in result

    def test_fix_brackets_already_correct(self):
        """Already-correct bracketed names should not be changed."""
        sql = 'SELECT "[Employee Master[Employee Name]]" FROM t'
        cols = ["[Employee Master[Employee Name]]"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"[Employee Master[Employee Name]]"' in result

    def test_fix_brackets_no_column_names(self):
        """Without column_names, bracket fix must NOT be attempted."""
        sql = 'SELECT "Employee Master[Employee Name]" FROM t'
        result = SQLParser.fix_common_llm_mistakes(sql, column_names=None)
        assert '"[Employee Master[Employee Name]]"' not in result

    def test_fix_brackets_simple_names_untouched(self):
        """Simple column names (no brackets) must not be altered."""
        sql = 'SELECT "Sales", "Revenue_Q1" FROM t'
        cols = ["Sales", "Revenue_Q1"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"Sales"' in result
        assert '"Revenue_Q1"' in result

    def test_fix_brackets_mixed_convention(self):
        """Only bracketed column names get fixed; simple names stay as-is."""
        sql = 'SELECT "Employee Master[Employee Name]", "Sales" FROM t'
        cols = ["[Employee Master[Employee Name]]", "Sales"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"[Employee Master[Employee Name]]"' in result
        assert '"Sales"' in result

    def test_fix_unnest_alias_wrong(self):
        """Wrong UNNEST alias (AS pe) gets fixed to AS t(rec)."""
        sql = "SELECT pe['field'] FROM t CROSS JOIN UNNEST(\"col\") AS pe"
        result = SQLParser.fix_common_llm_mistakes(sql)
        assert "AS t(rec)" in result
        assert "pe['" not in result
        assert "rec['field']" in result

    def test_fix_unnest_alias_correct_preserved(self):
        """Correct UNNEST aliases (t1, t2) are preserved."""
        sql = (
            "SELECT t1.rec['a'], t2.rec['b'] FROM t "
            "CROSS JOIN UNNEST(\"c1\") AS t1(rec) "
            "CROSS JOIN UNNEST(\"c2\") AS t2(rec)"
        )
        result = SQLParser.fix_common_llm_mistakes(sql)
        assert "AS t1(rec)" in result
        assert "AS t2(rec)" in result

    def test_fix_combined_bracket_and_unnest(self):
        """The actual failing case: missing brackets + wrong UNNEST alias."""
        sql = (
            'SELECT "Employee Master[Employee Name]", '
            "pe['Employee Performance[Calculated Rating]'] AS rating "
            'FROM enterprise_data '
            'CROSS JOIN UNNEST("[Employee Performance[...]]") AS pe'
        )
        cols = ["[Employee Master[Employee Name]]"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"[Employee Master[Employee Name]]"' in result
        assert "AS t(rec)" in result
        assert "rec['Employee Performance[Calculated Rating]']" in result

    def test_fix_different_convention_no_brackets(self):
        """Different Excel with no bracket convention should not break."""
        sql = 'SELECT "Sales", pe["Rating"] FROM t CROSS JOIN UNNEST("Reviews") AS pe'
        cols = ["Sales"]
        result = SQLParser.fix_common_llm_mistakes(sql, cols)
        assert '"Sales"' in result
        assert "AS t(rec)" in result

    def test_fix_empty_query(self):
        """Empty/None query returns as-is."""
        assert SQLParser.fix_common_llm_mistakes("") == ""
        assert SQLParser.fix_common_llm_mistakes(None) is None

    def test_fix_alias_rec_field_access(self):
        """alias.rec['field'] → alias['field'] (pp IS the struct, .rec is wrong)."""
        sql = "SELECT pp.rec['field_a'], pr.rec['field_b'] FROM t"
        result = SQLParser.fix_common_llm_mistakes(sql)
        assert "pp['field_a']" in result
        assert "pr['field_b']" in result
        assert ".rec[" not in result
