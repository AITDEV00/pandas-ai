"""Deterministic, schema-driven validation of LLM-generated Python+SQL code.

Unlike the LLM (which is non-deterministic and can re-hallucinate the same bug),
this validator performs *static* checks over the emitted code by replaying the
same schema-name checks the runtime would eventually hit, but *before* the code
is executed. This targets the class of bugs where the reasoning is correct but
the emitted code fabricates or garbles a schema identifier (struct column names,
struct field keys, placeholders, alias drift).

The checks are all derived from the actual DataFrame schema and from the
code text itself — there is no sampling, no temperature, and no second LLM call.
"""

import ast
import re
from typing import List, Set


# Identifiers that the code-execution sandbox provides without the model
# having to assign them (see pandasai/core/code_execution/environment.py and
# agent/base.py: pd, plt, np, execute_sql_query, plus any registered skills).
# Also include Python builtins so we don't false-positive on them.
_BUILTIN_NAMES = {
    "pd",
    "plt",
    "np",
    "execute_sql_query",
    # Python builtins commonly used in generated code
    "len",
    "range",
    "int",
    "float",
    "str",
    "list",
    "dict",
    "set",
    "tuple",
    "bool",
    "sum",
    "max",
    "min",
    "abs",
    "round",
    "sorted",
    "reversed",
    "enumerate",
    "zip",
    "map",
    "filter",
    "any",
    "all",
    "print",
    "type",
    "isinstance",
    "issubclass",
    "hasattr",
    "getattr",
    "setattr",
    "len",
    "open",
    "Exception",
    "ValueError",
    "KeyError",
    "TypeError",
    "NameError",
    "AttributeError",
    "IndexError",
    "ZeroDivisionError",
    "chr",
    "ord",
    "format",
    "next",
    "iter",
    "super",
    "object",
    "input",
    "repr",
    "callable",
    "divmod",
    "pow",
    "hash",
    "id",
    "vars",
    "globals",
    "locals",
    "import_dependency",
}


# Tokens that indicate the model left an unfinished placeholder in the code
# (e.g. R11 left a literal ``-- placeholder`` comment and ``ach[..]``).
_PLACEHOLDER_PATTERNS = [
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"TODO|FIXME|XXX|HACK", re.IGNORECASE),
    re.compile(r"\b\.\.\b|\b\.\.\.\b"),
    re.compile(r"\[\.\.\]|\[\.\.\."),
]


class StructuralCodeValidator:
    """Static, schema-driven checks over generated Python+SQL code."""

    def __init__(self, schema_columns: List[str]):
        # Full top-level column names from the schema, e.g.
        # "[Employee Master[Employee Number]]"
        self.schema_columns = set(schema_columns)

        # Struct field keys are the "unwrapped" identifiers used inside
        # ``rec['...']`` access. For a struct column like
        #   [Employee Leave Details[Leave Type][Leave Days]]
        # the valid accessor keys are:
        #   Employee Leave Details[Leave Type]
        #   Employee Leave Details[Leave Days]
        # and the full UNNEST target is the whole column name.
        self._struct_field_keys: Set[str] = set()
        for col in self.schema_columns:
            inner = col.strip()[1:-1] if col.strip().startswith("[") else col.strip()
            # inner looks like "Employee Leave Details[Leave Type][Leave Days]"
            match = re.match(r"^(?P<base>[^\[\]]+)(?P<fields>(?:\[[^\]]*\])*)$", inner)
            if match:
                base = match.group("base").strip()
                for fld in re.findall(r"\[([^\]]*)\]", match.group("fields")):
                    self._struct_field_keys.add(f"{base}[{fld}]")

    def validate(self, code: str) -> List[str]:
        """Return a list of human-readable problems; empty list == OK.

        Problems are formatted as actionable error messages so that when the
        validator fails, the retry prompt receives a precise, targeted signal.
        """
        problems: List[str] = []
        for sql in self._extract_sql_strings(code):
            problems.extend(self._check_placeholders(sql))
            problems.extend(self._check_unnest_columns(sql))
            problems.extend(self._check_struct_field_keys(sql))
        problems.extend(self._check_alias_consistency(code))
        problems.extend(self._check_undefined_variables(code))
        return problems

    # -- SQL string extraction ------------------------------------------------

    def _extract_sql_strings(self, code: str) -> List[str]:
        """Pull every DuckDB SQL literal from the generated Python code."""
        sql_literals: List[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # If we can't parse, leave validation to the interpreter.
            return sql_literals

        def add_node_literal(node) -> None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql_literals.append(node.value)

        for node in ast.walk(tree):
            # execute_sql_query("<sql>")
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "execute_sql_query":
                if node.args:
                    add_node_literal(node.args[0])
            # <var> = "SELECT ..."  (SQL assigned to a variable)
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    val = node.value.value.lstrip().upper()
                    if val.startswith(("SELECT", "WITH", "FROM", "EXPLAIN")):
                        sql_literals.append(node.value.value)

        return sql_literals

    # -- Check 1: unfinished placeholders --------------------------------------

    def _check_placeholders(self, sql: str) -> List[str]:
        problems = []
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(sql):
                problems.append(
                    "SQL contains an unfinished placeholder/comment (e.g. "
                    f"`{pattern.pattern}`). Remove all placeholder text such as "
                    "`-- placeholder`, `..`, `[..]`, `TODO` — every field must "
                    "be a real column reference, not a stub."
                )
        return problems

    # -- Check 2: UNNEST column strings must match the schema -------------------

    def _check_unnest_columns(self, sql: str) -> List[str]:
        problems = []
        # Match UNNEST("<column name>") where the column may be quoted with
        # double quotes and contains the bracket convention.
        for m in re.finditer(
            r'UNNEST\s*\(\s*(["\'])([^"\']+)\1\s*\)', sql
        ):
            col_ref = m.group(2)
            if col_ref not in self.schema_columns:
                problems.append(
                    f"`UNNEST(\"{col_ref}\")` references a struct column that is "
                    "NOT in the schema. Copy the struct column name "
                    "character-for-character from the schema (check for "
                    "hallucinated or dropped inner fields)."
                )
        return problems

    # -- Check 3: struct field keys must be valid --------------------------------

    def _check_struct_field_keys(self, sql: str) -> List[str]:
        problems = []
        # Match struct field access of the form  rec['<Base>[<Field>]']
        # The key is a base name followed by one-or-more [Field] groups, all
        # inside single quotes:  rec['Employee Leave Details[Leave Type]']
        for m in re.finditer(r"\w+\['([^'\[\]]+(?:\[[^\]]*\])+)'\]", sql):
            key = m.group(1)
            if key in self._struct_field_keys:
                continue
            # allow referencing a full flat column
            if key in self.schema_columns:
                continue
            problems.append(
                f"Struct field key '{key}' is not a valid schema field. Use the "
                "exact key names shown in the schema (e.g. "
                "'Employee Leave Details[Leave Type]'). Do not change case or "
                "invent fields."
            )
        return problems

    # -- Check 4: SQL alias vs Python accessor consistency ----------------------

    def _check_alias_consistency(self, code: str) -> List[str]:
        """Detect alias drift: SQL aliases a column ``AS x`` but the Python
        accessor later reads ``df['y']`` where y != x (R6 pattern).

        This is a best-effort heuristic — it walks the AST to find columns
        selected with an alias in each SQL literal, then checks that any
        df['<key>'] access in the Python body uses a known alias. Because a
        full dataflow analysis is out of scope, we only flag accesses where
        we can map an SQL SELECT alias to the same DataFrame variable.
        """
        problems: List[str] = []
        tree = self._safe_parse(code)
        if tree is None:
            return problems

        # Map variable name -> set of SQL aliases defined on it via
        # execute_sql_query or a "SELECT ... AS x" string assignment.
        alias_by_var: dict = {}
        for node in ast.walk(tree):
            # var = execute_sql_query("...")
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "execute_sql_query"
                and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.value.args
                and isinstance(node.value.args[0], ast.Constant)
            ):
                sql = node.value.args[0].value
                aliases = self._extract_sql_aliases(sql)
                if aliases:
                    alias_by_var[node.targets[0].id] = aliases

        # Now find df['key'] accesses and verify the key is a defined alias
        # OR a real schema column (a column may be referenced without an alias).
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            # df['key']
            if (
                isinstance(node.value, ast.Name)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                var = node.value.id
                key = node.slice.value
                known = alias_by_var.get(var)
                if known is not None and key not in known and key not in self.schema_columns:
                    problems.append(
                        f"Accessing `{var}['{key}']` but the SQL query for `{var}` "
                        f"defines aliases: {sorted(known)}. Use one of the defined "
                        "aliases (do not invent a column name)."
                    )
        return problems

    # -- Check 5: undefined variables used in f-strings -------------------------

    def _check_undefined_variables(self, code: str) -> List[str]:
        """Detect references to variables that are never assigned in the code.

        Catches the R4 pattern: reasoning named ``header_line`` but the emitted
        f-string used ``header`` (NameError at runtime).
        """
        problems: List[str] = []
        tree = self._safe_parse(code)
        if tree is None:
            return problems

        assigned = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    self._collect_name_target(t, assigned)
            elif isinstance(node, ast.AnnAssign):
                self._collect_name_target(node.target, assigned)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                self._collect_name_target(node.target, assigned)
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars is not None:
                        self._collect_name_target(item.optional_vars, assigned)
            elif isinstance(node, ast.FunctionDef):
                assigned.add(node.name)
                for a in node.args.args + node.args.kwonlyargs:
                    assigned.add(a.arg)
                if node.args.vararg:
                    assigned.add(node.args.vararg.arg)
                if node.args.kwarg:
                    assigned.add(node.args.kwarg.arg)
            elif isinstance(node, ast.comprehension):
                self._collect_name_target(node.target, assigned)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                assigned.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        assigned.add(alias.asname)
                    else:
                        assigned.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.asname:
                        assigned.add(alias.asname)
                    elif alias.name != "*":
                        assigned.add(alias.name)

        # Collect all Name loads that appear inside a JoinedStr (f-string).
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for val in node.values:
                    if isinstance(val, ast.FormattedValue) and isinstance(
                        val.value, ast.Name
                    ):
                        used.add(val.value.id)
            # Also catch the R4 pattern: a bare Name element inside a list
            # literal passed to str.join(...) e.g.
            #   '\n'.join([header, sep_line] + rows)
            # where `header` was never assigned (typo for `header_line`).
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
                and node.args
                and isinstance(node.args[0], (ast.List, ast.BinOp))
            ):
                for sub in ast.walk(node.args[0]):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                        used.add(sub.id)

        # Extend to catch the R10/R11 pattern: a Name referenced on the RHS of a
        # plain assignment or passed as a call argument — but NOT assigned
        # anywhere in the code (NameError at runtime).
        # e.g.  filtered = [x for x in raw if x in leadership_keywords]
        #       rows.append(assignments_query)            # undefined
        for node in ast.walk(tree):
            # RHS of an assignment / annotated-assign / aug-assign / walrus
            if isinstance(node, ast.Assign):
                self._collect_rhs_names(node.value, used)
            elif isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    self._collect_rhs_names(node.value, used)
            elif isinstance(node, ast.AugAssign):
                self._collect_rhs_names(node.value, used)
            elif isinstance(node, ast.NamedExpr):
                self._collect_rhs_names(node.value, used)
            # Call arguments (positional + keyword values)
            elif isinstance(node, ast.Call):
                for arg in node.args:
                    self._collect_rhs_names(arg, used)
                for kw in node.keywords:
                    if kw.value is not None:
                        self._collect_rhs_names(kw.value, used)

        # Remove names that the sandbox pre-defines, plus Python builtins.
        missing = (used - assigned) - _BUILTIN_NAMES
        for name in sorted(missing):
            problems.append(
                f"`{name}` is referenced but never assigned in the code. "
                "Check for a typo (e.g. did you mean a variable you defined "
                "earlier?). Ensure the exact variable name is assigned before "
                "it is referenced."
            )
        return problems

    @staticmethod
    def _collect_rhs_names(node, used: set) -> None:
        """Collect every Name in Load context from an expression node.

        ``ast.walk`` includes attribute values and the callee, but the callee
        of a call like ``df.head()`` (a Name with Load ctx on ``df``) is a valid
        reference too — if undefined, it would NameError at runtime. We only
        collect names whose context is Load to avoid treating assignment
        targets (Store context) as references.
        """
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                used.add(sub.id)

    @staticmethod
    def _collect_name_target(target, assigned: set) -> None:
        """Collect all Name identifiers from an assignment target (recursively)."""
        if isinstance(target, ast.Name):
            assigned.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                StructuralCodeValidator._collect_name_target(elt, assigned)
        elif isinstance(target, (ast.Starred,)):
            StructuralCodeValidator._collect_name_target(target.value, assigned)

    @staticmethod
    def _safe_parse(code: str):
        try:
            return ast.parse(code)
        except SyntaxError:
            return None

    @staticmethod
    def _extract_sql_aliases(sql: str) -> Set[str]:
        """Extract column aliases from a SELECT statement (best-effort).

        We only look inside the SELECT list (before FROM) and only capture the
        identifier immediately after ``AS``. UNNEST destructuring aliases
        (``AS t(rec)``) live after FROM and are not column aliases, so scanning
        only the SELECT clause avoids them entirely.
        """
        aliases = set()
        from_idx = re.search(r"\bFROM\b", sql, re.IGNORECASE)
        select_clause = sql[:from_idx.start()] if from_idx else sql
        for m in re.finditer(
            r"\bAS\s+[`\"']?([A-Za-z_]\w*)", select_clause, re.IGNORECASE
        ):
            aliases.add(m.group(1))
        return aliases

    @staticmethod
    def format_problems(problems: List[str]) -> str:
        if not problems:
            return ""
        return "Deterministic code self-review found:\n- " + "\n- ".join(problems)