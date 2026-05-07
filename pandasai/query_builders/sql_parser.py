from typing import List, Optional

import re

import sqlglot
from sqlglot import ParseError, exp, parse_one
from sqlglot.optimizer.qualify_columns import quote_identifiers

from pandasai.exceptions import MaliciousQueryError


class SQLParser:
    @staticmethod
    def fix_common_llm_mistakes(query: str, column_names: List[str] = None) -> str:
        """
        Auto-fix common mistakes small LLMs make when generating DuckDB SQL.

        All fixes are schema-driven: we only correct what we can verify against
        the actual column names from the DataFrame schema. No heuristic guessing.

        Fixes:
        1. Column name mismatches: if the LLM wrote "X" but the schema has
           "[X]", we replace "X" with "[X]". Only applies when column_names
           is provided — without it, no column name fixing is attempted.
        2. Wrong UNNEST alias pattern: DuckDB requires UNNEST(...) AS t(rec)
           for struct field access via rec['field']. The LLM sometimes writes
           AS <alias> and <alias>['field'], which DuckDB rejects. This is a
           DuckDB syntax requirement, not a convention.
        3. alias.rec['field'] → alias['field']: When using AS t1(pp), the LLM
           sometimes writes pp.rec['field'] instead of pp['field']. In DuckDB,
           pp IS the struct — .rec tries to find a key called "rec" inside it.

        Args:
            query: The SQL query to fix.
            column_names: Known valid column names from the DataFrame schema.
                         Only used for Fix 1 — without it, only Fix 2 applies.
        """
        if not query:
            return query

        # --- Fix 1: Schema-driven column name correction ---
        # For each known column name, check if the LLM wrote a "stripped"
        # version (e.g. missing outer brackets) and replace it with the
        # correct name from the schema.
        #
        # This is purely data-driven: we only fix what we KNOW is wrong
        # based on the actual schema. No heuristic pattern matching.
        if column_names:
            for col_name in column_names:
                # Only consider column names that start with [ and end with ]
                # (the bracket convention). For simple names like "Sales" or
                # "Revenue_Q1", there's nothing to fix.
                if col_name.startswith('[') and col_name.endswith(']'):
                    inner = col_name[1:-1]
                    # If the LLM wrote "inner" instead of "[inner]", fix it.
                    # e.g. "Employee Master[Employee Name]" → "[Employee Master[Employee Name]]"
                    wrong = f'"{inner}"'
                    right = f'"{col_name}"'
                    if wrong in query and right not in query:
                        query = query.replace(wrong, right)

        # --- Fix 2: Wrong UNNEST alias pattern ---
        # DuckDB syntax: UNNEST(...) AS t(rec) → access fields as rec['field']
        # LLM mistake:    UNNEST(...) AS pe   → access fields as pe['field'] (BROKEN)
        #
        # This is a DuckDB syntax requirement, not a convention.
        # When UNNEST returns list[struct], you MUST use the AS alias(rec)
        # pattern to destructure the struct. Without (rec), the alias refers
        # to the whole row (a single column called "unnest"), not the struct.

        # Find UNNEST aliases that are NOT in the t(rec) or t1(rec) pattern
        unnest_aliases = re.findall(
            r'UNNEST\s*\([^)]+\)\s+AS\s+(\w+)\b(?!\s*\()', query
        )

        for alias in unnest_aliases:
            # Skip aliases already in t(rec) or t1(rec), t2(rec) form
            if alias.startswith('t') and (alias == 't' or alias[1:].isdigit()):
                continue

            # Replace alias declaration: AS <alias> → AS t(rec)
            query = re.sub(
                rf'UNNEST\s*\([^)]+\)\s+AS\s+{re.escape(alias)}\b(?!\s*\()',
                'AS t(rec)',
                query
            )

            # Replace field access: <alias>['field'] → rec['field']
            query = re.sub(
                rf'\b{re.escape(alias)}\.rec\[',
                'rec[',
                query
            )
            query = re.sub(
                rf'\b{re.escape(alias)}\[',
                'rec[',
                query
            )

        # --- Fix 3: alias.rec['field'] → alias['field'] ---
        # When using AS t1(pp), the LLM sometimes writes pp.rec['field'] instead
        # of pp['field']. In DuckDB, pp IS the struct — .rec tries to find a key
        # called "rec" inside it, which doesn't exist.
        # This pattern applies to ANY variable used as a UNNEST destructuring alias,
        # not just the ones caught by Fix 2 (which only handles non-t aliases).
        query = re.sub(
            r'\b(\w+)\.rec\[',
            r"\1[",
            query
        )

        return query

    @staticmethod
    def replace_table_and_column_names(query, table_mapping):
        """
        Transform a SQL query by replacing table names with either new table names or subqueries.

        Args:
            query (str): Original SQL query
            table_mapping (dict): Dictionary mapping original table names to either:
                           - actual table names (str)
                           - subqueries (str)
        """
        # If no table replacements needed, skip sqlglot parsing entirely.
        # sqlglot cannot parse DuckDB-specific syntax like UNNEST aliases
        # (t.comp(rec)) or bracket-enclosed column names, so we avoid
        # round-tripping through parse_one when there's nothing to replace.
        if not table_mapping:
            return query

        # Pre-parse all subqueries in mapping to avoid repeated parsing
        parsed_mapping = {}
        for key, value in table_mapping.items():
            try:
                parsed_mapping[key] = parse_one(value)
            except ParseError:
                raise ValueError(f"{value} is not a valid SQL expression")

        def transform_node(node):
            # Handle Table nodes
            if isinstance(node, exp.Table):
                original_name = node.name

                if original_name in table_mapping:
                    alias = node.alias or original_name
                    mapped_value = parsed_mapping[original_name]
                    if isinstance(mapped_value, exp.Alias):
                        return exp.Subquery(
                            this=mapped_value.this.this,
                            alias=alias,
                        )
                    elif isinstance(mapped_value, exp.Column):
                        return exp.Table(this=mapped_value.this, alias=alias)
                    return exp.Subquery(this=mapped_value, alias=alias)

            return node

        # Parse the SQL query
        parsed = parse_one(query)

        # Transform the query
        transformed = parsed.transform(transform_node)
        transformed = transformed.transform(quote_identifiers)

        # Convert back to SQL string
        return transformed.sql(pretty=True)

    @staticmethod
    def transpile_sql_dialect(
        query: str, to_dialect: str, from_dialect: Optional[str] = None
    ):
        # When target is DuckDB, assume input is also DuckDB to preserve
        # dialect-specific operators like ILIKE
        if to_dialect == "duckdb" and from_dialect is None:
            from_dialect = "duckdb"

        # When source and target dialect are the same, skip transpilation
        # entirely. sqlglot cannot parse DuckDB-specific syntax like
        # struct field access (rec['Field']) or bracket-enclosed column
        # names ("[Table[Col1][Col2]]"), so round-tripping through
        # parse_one would either fail or corrupt the query.
        if from_dialect == to_dialect:
            return query

        placeholder = "___PLACEHOLDER___"
        query = query.replace("%s", placeholder)
        query = (
            parse_one(query, read=from_dialect) if from_dialect else parse_one(query)
        )
        result = query.sql(dialect=to_dialect, pretty=True)

        if to_dialect == "duckdb":
            return result.replace(placeholder, "?")

        return result.replace(placeholder, "%s")

    @staticmethod
    def extract_table_names(sql_query: str, dialect: str = "postgres") -> List[str]:
        # Parse the SQL query
        parsed = sqlglot.parse(sql_query, dialect=dialect)
        table_names = []
        cte_names = set()

        for stmt in parsed:
            # Identify and store CTE names
            for cte in stmt.find_all(exp.With):
                for cte_expr in cte.expressions:
                    cte_names.add(cte_expr.alias_or_name)

            # Extract table names, excluding CTEs
            for node in stmt.find_all(exp.Table):
                if node.name not in cte_names:  # Ignore CTE names
                    table_names.append(node.name)

        return table_names
