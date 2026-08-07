import logging
from typing import Optional

import duckdb
import pandas as pd

from pandasai.helpers.type_determination import (
    cast_flat_field_types,
    cast_struct_field_types,
)
from pandasai.query_builders.sql_parser import SQLParser

logger = logging.getLogger(__name__)


class DuckDBConnectionManager:
    def __init__(self):
        """Initialize a DuckDB connection."""
        self.connection = duckdb.connect()
        self._registered_tables = set()

    def __del__(self):
        """Destructor to ensure the DuckDB connection is closed."""
        try:
            self.close()
        except Exception:
            pass  # Prevent exceptions during garbage collection

    def register(self, name: str, df: pd.DataFrame):
        """Registers a DataFrame as a DuckDB table.

        Before registering, applies the semantic model's declared types to struct
        inner-field values.  ``duckdb.connection.register()`` infers SQL types
        from the Python objects in the DataFrame — it has no type-hint parameter.
        Without this step, struct fields parsed from JSON remain as Python ``str``
        (because ``json.loads`` has no native date type), causing DuckDB to infer
        ``VARCHAR`` instead of ``DATE``/``DOUBLE``/``INTEGER``.

        The semantic model is the source of truth: each caster tries the declared
        type first and falls back to the original value on error, so invalid or
        unparseable values are preserved rather than silently dropped.
        """
        schema = getattr(df, "schema", None)
        if schema:
            cast_struct_field_types(df, schema)
            cast_flat_field_types(df, schema)
        self.connection.register(name, df)
        self._registered_tables.add(name)

    def unregister(self, name: str):
        """Unregister a previously registered DuckDB table."""
        if name in self._registered_tables:
            self.connection.unregister(name)
            self._registered_tables.remove(name)

    def sql(self, query: str, params: Optional[list] = None):
        """Executes an SQL query and returns the result as a Pandas DataFrame."""
        query = SQLParser.transpile_sql_dialect(query, to_dialect="duckdb")
        return self.connection.sql(query, params=params)

    def close(self):
        """Closes the DuckDB connection."""
        if hasattr(self, "connection") and self.connection:
            self.connection.close()
            self.connection = None
            self._registered_tables.clear()
