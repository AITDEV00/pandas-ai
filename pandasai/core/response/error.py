from typing import Optional

from .base import BaseResponse


class ErrorResponse(BaseResponse):
    """
    Class for handling error responses.
    """

    def __init__(
        self,
        value="Unfortunately, I was not able to get your answer. Please try again.",
        last_code_executed: Optional[str] = None,
        error: Optional[str] = None,
    ):
        super().__init__(value, "error", last_code_executed, error)
