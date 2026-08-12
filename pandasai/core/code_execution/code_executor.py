from typing import Any

from pandasai.core.code_execution.environment import get_environment
from pandasai.exceptions import CodeExecutionError, NoResultFoundError


def _root_cause_message(exc: Exception) -> str:
    """Build a concise, actionable error message from the ROOT cause.

    The sandbox ``exec()`` raises arbitrary exceptions (AttributeError,
    TypeError, duckdb Binder/Catalog/Parser errors, KeyError, etc.). We want
    the retry prompt to see the REAL error — not a generic wrapper — so it can
    actually fix the code. This walks the ``__cause__``/``__context__`` chain to
    the deepest exception and returns ``<ExceptionType>: <message>``, plus the
    failing ``<string>`` line number when present in the traceback.

    Falls back to ``str(exc)`` if the chain can't be walked.
    """
    import traceback

    # Walk to the deepest cause (root).
    root = exc
    seen = set()
    while root.__cause__ is not None and id(root.__cause__) not in seen:
        seen.add(id(root))
        root = root.__cause__

    # Prefer a root message that is not the generic wrapper string.
    root_msg = str(root).strip()
    if not root_msg or root_msg == "Code execution failed":
        # Try one level up / context for a real message.
        if exc.__cause__ is not None and str(exc.__cause__).strip():
            root_msg = str(exc.__cause__).strip()
        else:
            root_msg = root_msg or str(exc)

    root_type = type(root).__name__

    # Extract the failing user-code line (File "<string>", line N).
    line_no = None
    try:
        tb = traceback.TracebackException.from_exception(exc).stack
        for frame in tb:
            if frame.filename == "<string>":
                line_no = frame.lineno
                break
    except Exception:
        line_no = None

    line_hint = f" (at generated code line {line_no})" if line_no else ""
    return f"{root_type}: {root_msg}{line_hint}"


class CodeExecutor:
    """
    Handle the logic on how to handle different lines of code
    """

    _environment: dict

    def __init__(self) -> None:
        self._environment = get_environment()

    def add_to_env(self, key: str, value: Any) -> None:
        """
        Expose extra variables in the code to be used
        Args:
            key (str): Name of variable or lib alias
            value (Any): It can any value int, float, function, class etc.
        """
        self._environment[key] = value

    def execute(self, code: str) -> dict:
        try:
            exec(code, self._environment)
        except Exception as e:
            # Do NOT swallow the real error. Raising a bare "Code execution
            # failed" hides the true cause from the retry prompt, making every
            # regeneration blind. Instead, surface the ROOT exception type and
            # message (and the failing line) so the model actually has the
            # information it needs to fix the code. The full traceback is
            # preserved as the __cause__ chain for debugging.
            raise CodeExecutionError(
                _root_cause_message(e)
            ) from e
        return self._environment

    def execute_and_return_result(self, code: str) -> Any:
        """
        Executes the return updated environment
        """
        self.execute(code)

        # Get the result
        if "result" not in self._environment:
            raise NoResultFoundError(
                "No result was returned from the code execution. Please return the result in dictionary format, for example: result = {'type': ..., 'value': ...}"
            )

        return self._environment.get("result", None)

    @property
    def environment(self) -> dict:
        return self._environment
