"""Prompt class for auto-filling missing column descriptions."""
from pandasai.core.prompts.base import BasePrompt


class AutoFillDescriptionsPrompt(BasePrompt):
    """Prompt for auto-filling missing column descriptions using LLM.

    Sends the full column list with types and samples, plus a list of keys
    that are missing descriptions.  The LLM generates descriptions only for
    the missing keys and returns them as ``{"descriptions": {key: desc}}``.
    """

    template_path = "auto_fill_descriptions.tmpl"

    def __init__(
        self,
        context,
        columns: list,
        missing_keys: list,
        sample_rows: str = "",
        table_name: str = "data",
    ):
        super().__init__(
            context=context,
            columns=columns,
            missing_keys=missing_keys,
            sample_rows=sample_rows,
            table_name=table_name,
        )
