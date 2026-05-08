from typing import Any, Optional

from .base import BaseResponse


class NumberResponse(BaseResponse):
    """
    Class for handling numerical responses.
    """

    def __init__(self, value: Any = None, last_code_executed: Optional[str] = None):
        super().__init__(value, "number", last_code_executed)
