"""Prompt class for the column selection step (Issue 3)."""
from pandasai.core.prompts.base import BasePrompt


class SelectColumnsPrompt(BasePrompt):
    """Prompt for Step 1: LLM-based column selection for wide tables.

    This prompt shows only column metadata (name, type, description, samples)
    without CSV rows or SQL docs. The LLM returns a flat list of relevant
    column/field names.
    """

    template_path = "select_columns.tmpl"

    def __init__(
        self,
        context,
        query: str,
        flat_columns: list,
        struct_columns: list,
        table_name: str = "data",
        table_description: str = "",
    ):
        total_columns = len(flat_columns) + len(struct_columns)
        super().__init__(
            context=context,
            query=query,
            flat_columns=flat_columns,
            struct_columns=struct_columns,
            table_name=table_name,
            table_description=table_description,
            total_columns=total_columns,
        )
