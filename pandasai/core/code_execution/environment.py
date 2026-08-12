"""Module to import optional dependencies.

Source: Taken from pandas/compat/_optional.py
"""

import importlib
import types

INSTALL_MAPPING = {}


def get_version(module: types.ModuleType) -> str:
    """Get the version of a module."""
    version = getattr(module, "__version__", None)

    if version is None:
        raise ImportError(f"Can't determine version for {module.__name__}")

    return version


def get_environment() -> dict:
    """
    Returns the environment for the code to be executed.

    Returns (dict): A dictionary of environment variables
    """
    env = {
        "pd": import_dependency("pandas"),
        "plt": import_dependency("matplotlib.pyplot"),
        "np": import_dependency("numpy"),
    }

    # Expose date-arithmetic helper functions mirroring the DuckDB SQL macros
    # (years_between / as_date / today).  LLM-generated code mixes SQL and
    # pandas, so providing a consistent Python-side helper (matching the SQL
    # macro of the same name) lets the model compute "years of service" etc.
    # without hand-rolling fragile date arithmetic that errors on string vs
    # date mismatches.  These are injected into the exec namespace so the code
    # can call them directly; they're documented in the prompt contract too.
    try:
        from datetime import date

        import pandas as pd

        def years_between(a, b) -> float:
            """Whole years between two date-like values (signed).

            Mirrors the DuckDB SQL macro of the same name: args may be strings,
            ``datetime.date`` or ``datetime.datetime``; they are coerced to
            dates and the (signed) difference in whole years is returned.
            ``years_between(earlier, later)`` is non-negative; reversed args
            give a negative result.
            """

            def _as_date(v):
                if v is None:
                    return None
                if hasattr(v, "date") and not isinstance(v, date):
                    return v.date()
                if isinstance(v, str):
                    return pd.to_datetime(v, errors="coerce").date()
                if isinstance(v, pd.Timestamp):
                    return v.date()
                return v

            a_d, b_d = _as_date(a), _as_date(b)
            if a_d is None or b_d is None:
                return None
            years = abs(b_d.year - a_d.year)
            if (b_d.month, b_d.day) < (a_d.month, a_d.day):
                years -= 1
            return years if b_d >= a_d else -years

        def as_date(x):
            """Coerce an arbitrary date-like value to ``datetime.date``."""
            import pandas as pd

            if hasattr(x, "date") and not isinstance(x, date):
                return x.date()
            if isinstance(x, str):
                return pd.to_datetime(x, errors="coerce").date()
            return x

        def today():
            """Today's date, matching ``date.today()``."""
            return date.today()

        env["years_between"] = years_between
        env["as_date"] = as_date
        env["today"] = today
    except Exception:  # pragma: no cover - helpers are non-critical
        pass

    return env


def import_dependency(
    name: str,
    extra: str = "",
    errors: str = "raise",
):
    """
    Import an optional dependency.

    By default, if a dependency is missing an ImportError with a nice
    message will be raised. If a dependency is present, but too old,
    we raise.

    Args:
        name (str): The module name.
        extra (str): An additional text to include in the ImportError message.
        errors (str): Representing an action to do when a dependency
            is not found or its version is too old.
            Possible values: "raise", "warn", "ignore":
                * raise : Raise an ImportError
                * warn : Only applicable when a module's version is too old.
                  Warns that the version is too old and returns None
                * ignore: If the module is not installed, return None, otherwise,
                  return the module, even if the version is too old.
                  It's expected that users validate the version locally when
                  using ``errors="ignore"`` (see. ``io/html.py``)
        min_version (str): Specify a minimum version that is different from
            the global pandas minimum version required. Defaults to None.

    Returns:
         Optional[module]:
            The imported module, when found and the version is correct.
            None is returned when the package is not found and `errors`
            is False, or when the package's version is too old and `errors`
            is `'warn'`.
    """

    assert errors in {"warn", "raise", "ignore"}

    package_name = INSTALL_MAPPING.get(name)
    install_name = package_name if package_name is not None else name

    msg = (
        f"Missing optional dependency '{install_name}'. {extra} "
        f"Use pip or conda to install {install_name}."
    )
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        if errors == "raise":
            raise ImportError(msg) from exc
        return None

    return module
