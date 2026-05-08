import ast
import os.path
import re
import uuid
from pathlib import Path

import astor

from pandasai.agent.state import AgentState
from pandasai.constants import DEFAULT_CHART_DIRECTORY
from pandasai.core.code_execution.code_executor import CodeExecutor
from pandasai.query_builders.sql_parser import SQLParser

from ...exceptions import MaliciousQueryError


class CodeCleaner:
    def __init__(self, context: AgentState):
        """
        Initialize the CodeCleaner with the provided context.

        Args:
            context (AgentState): The pipeline context for cleaning and validation.
        """
        self.context = context

    def _check_direct_sql_func_def_exists(self, node: ast.AST) -> bool:
        """
        Check if the node defines a direct SQL execution function.
        """
        return isinstance(node, ast.FunctionDef) and node.name == "execute_sql_query"

    def _check_if_skill_func_def_exists(self, node: ast.AST) -> bool:
        """
        Check if the node defines a skill function.
        """
        for skill in self.context.skills:
            if isinstance(node, ast.FunctionDef) and node.name == skill.name:
                return True
        return False

    def _replace_table_names(
        self, sql_query: str, table_names: list, allowed_table_names: dict
    ) -> str:
        """
        Replace table names in the SQL query with case-sensitive or authorized table names.
        """
        regex_patterns = {
            table_name: re.compile(r"\b" + re.escape(table_name) + r"\b")
            for table_name in table_names
        }
        for table_name in table_names:
            if table_name in allowed_table_names:
                quoted_table_name = allowed_table_names[table_name]
                sql_query = regex_patterns[table_name].sub(quoted_table_name, sql_query)
            else:
                raise MaliciousQueryError(
                    f"Query uses unauthorized table: {table_name}."
                )
        return sql_query

    @staticmethod
    def _normalize_duckdb_struct_syntax(sql: str) -> str:
        """Replace DuckDB struct field access with placeholders for sqlglot parsing.

        DuckDB uses ``rec['Field Name']`` syntax for struct field access and
        ``CROSS JOIN UNNEST(col) AS t(rec)`` for struct unnesting.  sqlglot
        cannot parse these correctly and may extract spurious table names
        (e.g. "columns" from ``information_schema.columns``, or field names
        misidentified as table references).

        This method replaces struct access patterns with safe placeholders so
        sqlglot can correctly identify only real table names.  The original
        query is returned unchanged — only the *normalized* copy is used for
        table-name extraction.
        """
        # Replace rec['...'] and similar struct field access patterns
        # e.g. rec['Employee Leave Details[Leave Type]'] → rec['__STRUCT_FIELD__']
        normalized = re.sub(
            r"(\w+)\['([^']*)'\]",
            r"\1['__STRUCT_FIELD__']",
            sql,
        )
        # Replace bracket-enclosed column names in SELECT/WHERE clauses
        # e.g. "[Employee Master[Employee Name]]" → "__BRACKET_COL__"
        normalized = re.sub(
            r'"\[([^\]]+)\[([^\]]+)\]\]"',
            r'"__BRACKET_COL__"',
            normalized,
        )
        return normalized

    def _clean_sql_query(self, sql_query: str) -> str:
        """
        Clean the SQL query by trimming semicolons and validating table names.
        """
        sql_query = sql_query.rstrip(";")
        dialect = self.context.dfs[0].get_dialect()

        # Normalize DuckDB struct syntax before passing to sqlglot.
        # sqlglot may misparse rec['Field'] and bracket-enclosed column names,
        # extracting spurious table names that cause false MaliciousQueryError.
        normalized_query = self._normalize_duckdb_struct_syntax(sql_query)

        try:
            table_names = SQLParser.extract_table_names(normalized_query, dialect)
        except Exception as e:
            # sqlglot may fail to tokenize SQL with DuckDB-specific syntax
            # like struct field access (rec['Field Name']) or bracket-enclosed
            # column names. Skip table name validation and return the trimmed query.
            self.context.logger.log(
                f"Skipping SQL table-name validation: sqlglot could not parse the query "
                f"(likely due to DuckDB struct/bracket syntax). Error: {e}"
            )
            return sql_query
        allowed_table_names = {
            df.schema.name: df.schema.name for df in self.context.dfs
        } | {f'"{df.schema.name}"': df.schema.name for df in self.context.dfs}

        return self._replace_table_names(sql_query, table_names, allowed_table_names)

    def _validate_and_make_table_name_case_sensitive(self, node: ast.AST) -> ast.AST:
        """
        Validate table names and convert them to case-sensitive names in the SQL query.
        """
        if isinstance(node, ast.Assign):
            if (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ["sql_query", "query"]
            ):
                sql_query = self._clean_sql_query(node.value.value)
                node.value.value = sql_query
            elif (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "execute_sql_query"
                and len(node.value.args) == 1
                and isinstance(node.value.args[0], ast.Constant)
                and isinstance(node.value.args[0].value, str)
            ):
                sql_query = self._clean_sql_query(node.value.args[0].value)
                node.value.args[0].value = sql_query

        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if (
                isinstance(node.value.func, ast.Name)
                and node.value.func.id == "execute_sql_query"
                and len(node.value.args) == 1
                and isinstance(node.value.args[0], ast.Constant)
                and isinstance(node.value.args[0].value, str)
            ):
                sql_query = self._clean_sql_query(node.value.args[0].value)
                node.value.args[0].value = sql_query

        return node

    def get_target_names(self, targets):
        target_names = []
        is_slice = False

        for target in targets:
            if isinstance(target, ast.Name) or (
                isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
            ):
                target_names.append(
                    target.id if isinstance(target, ast.Name) else target.value.id
                )
                is_slice = isinstance(target, ast.Subscript)

        return target_names, is_slice, target

    def check_is_df_declaration(self, node: ast.AST):
        value = node.value
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and hasattr(value.func.value, "id")
            and value.func.value.id == "pd"
            and value.func.attr == "DataFrame"
        )

    def clean_code(self, code: str) -> str:
        """
        Clean the provided code by validating imports, handling SQL queries, and processing charts.

        Args:
            code (str): The code to clean.

        Returns:
            tuple: Cleaned code as a string and a list of additional dependencies.
        """
        code = self._replace_output_filenames_with_temp_chart(code)

        # If plt.show is in the code, remove that line
        code = re.sub(r"plt.show\(\)", "", code)

        tree = ast.parse(code)
        new_body = []

        for node in tree.body:
            if self._check_direct_sql_func_def_exists(node):
                continue

            # check if skill function definition exists and skip it
            if self._check_if_skill_func_def_exists(node):
                continue

            node = self._validate_and_make_table_name_case_sensitive(node)

            new_body.append(node)

        new_tree = ast.Module(body=new_body)
        return astor.to_source(new_tree, pretty_source=lambda x: "".join(x)).strip()

    def _replace_output_filenames_with_temp_chart(self, code: str) -> str:
        """
        Replace output file names with "temp_chart.png".
        """
        _id = uuid.uuid4()
        chart_path = os.path.join(DEFAULT_CHART_DIRECTORY, f"temp_chart_{_id}.png")
        chart_path = chart_path.replace("\\", "\\\\")
        return re.sub(
            r"""(['"])([^'"]*\.png)\1""",
            lambda m: f"{m.group(1)}{chart_path}{m.group(1)}",
            code,
        )
