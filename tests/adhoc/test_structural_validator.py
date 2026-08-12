"""Smoke test for the deterministic structural self-review validator.

Mirrors the real bug patterns from the retry-thinking-trace analysis (R4, R6,
R11) to confirm the validator catches them, and confirms clean code passes.
"""
from pandasai.core.code_generation.structural_validator import (
    StructuralCodeValidator,
)


SCHEMA = [
    "[Employee Master[Employee Name]]",
    "[Employee Master[Employee Number]]",
    "[Employee Leave Details[Leave Type][Leave Days]]",
    "[Employee Assignment History[Assignment Name][Position Title]]",
    "[CV Employee Competencies[Technical Competency Name]]",
    "[Employee Qualification[Qualification Title]]",
]

VALIDATOR = StructuralCodeValidator(SCHEMA)


def _validate(code: str):
    return VALIDATOR.validate(code)


def test_r6_alias_drift_detected():
    code = """\
df = execute_sql_query('SELECT name AS skill FROM [Employee Master[Employee Name]]')
df['skill_name']
"""
    problems = _validate(code)
    assert any("skill_name" in p for p in problems), problems


def test_r4_undefined_variable_detected():
    code = """\
header_line = 'Name,Title'
sep_line = '---'
out = chr(10).join([header, sep_line])
"""
    problems = _validate(code)
    assert any("`header` is referenced" in p for p in problems), problems


def test_r10_undefined_var_in_rhs_detected():
    """R10 pattern: Name used on RHS of a general expression but never assigned."""
    code = """\
df = execute_sql_query('SELECT * FROM [Employee Master[Employee Name]]')
leadership_rows = [r for r in df.itertuples() if r.position in leadership_keywords]
result = len(leadership_rows)
"""
    problems = _validate(code)
    assert any("`leadership_keywords` is referenced" in p for p in problems), problems


def test_r11_undefined_var_as_call_arg_detected():
    """R11 pattern: Name passed as a call argument but never assigned."""
    code = """\
df = execute_sql_query('SELECT * FROM [Employee Master[Employee Name]]')
rows = []
rows.append(assignments_query)
result = rows
"""
    problems = _validate(code)
    assert any("`assignments_query` is referenced" in p for p in problems), problems


def test_sandbox_date_helpers_not_flagged():
    """years_between / as_date / today are sandbox-predefined; not undefined."""
    code = """\
df = execute_sql_query('SELECT [Employee Master[Date of Joining]] AS doj FROM enterprise_data')
tenure = years_between(as_date(df['doj']), today())
result = {'type': 'number', 'value': float(tenure)}
"""
    problems = _validate(code)
    assert problems == [], problems


def test_sandbox_date_helpers_inside_sql_not_flagged():
    """Helpers used inside a SQL literal must not trip undefined-var scan."""
    code = """\
df = execute_sql_query(
    "SELECT years_between(as_date([Employee Master[Date of Joining]]), today()) AS yrs FROM enterprise_data"
)
result = len(df)
"""
    problems = _validate(code)
    assert problems == [], problems


def test_defined_rhs_and_builtins_pass():
    """Names assigned in code, sandbox globals, and builtins must not flag."""
    code = """\
df = execute_sql_query('SELECT name FROM [Employee Master[Employee Name]]')
leadership_keywords = ['DG', 'Director']
rows = [r for r in df.itertuples() if any(k in str(r.name) for k in leadership_keywords)]
result = pd.DataFrame(rows)
"""
    problems = _validate(code)
    assert problems == [], problems


def test_r11_placeholder_detected():
    code = """\
df = execute_sql_query('''
UNNEST("[Employee Assignment History[Assignment Name][Position Title]]") AS t(rec)
-- placeholder TODO
SELECT rec['Employee Assignment History[Fake Field]'] FROM t
''')
"""
    problems = _validate(code)
    assert any("placeholder" in p for p in problems), problems


def test_r11_hallucinated_unnest_column_detected():
    code = """\
df = execute_sql_query('''
UNNEST("[Employee Master[Employee Name][Fake Inner]]") AS t(rec)
SELECT rec['Employee Master[Employee Name]'] FROM t
''')
"""
    problems = _validate(code)
    assert any("NOT in the schema" in p for p in problems), problems


def test_r11_bad_struct_field_key_detected():
    code = """\
df = execute_sql_query('''
SELECT rec['Employee Assignment History[Fake Field]']
FROM UNNEST("[Employee Assignment History[Assignment Name][Position Title]]") AS t(rec)
''')
"""
    problems = _validate(code)
    assert any("Struct field key" in p for p in problems), problems


def test_clean_code_passes():
    code = """\
df = execute_sql_query('SELECT name AS skill_name FROM [Employee Master[Employee Name]]')
print(df['skill_name'])
"""
    problems = _validate(code)
    assert problems == [], problems


# -- SQL function allowlist (Q35-class: invented / foreign-dialect functions) --


def test_unknown_sql_function_julianday_detected():
    """SQLite's `julianday` is not a DuckDB function -> must be flagged."""
    code = """\
df = execute_sql_query('SELECT julianday(CURRENT_DATE) AS j FROM t')
result = len(df)
"""
    problems = _validate(code)
    assert any("julianday" in p and "does NOT exist" in p for p in problems), problems


def test_unknown_sql_function_to_date_detected():
    """`to_date` is not a DuckDB function."""
    code = """\
df = execute_sql_query("SELECT to_date('2020-01-01') AS d FROM t")
result = len(df)
"""
    problems = _validate(code)
    assert any("to_date" in p and "does NOT exist" in p for p in problems), problems


def test_native_duckdb_functions_pass():
    """Real DuckDB functions must NOT be flagged."""
    code = """\
df = execute_sql_query(
    "SELECT date_diff('day', a, b) AS d, strptime('2020-01-01', '%Y-%m-%d') AS dt, "
    "EXTRACT(YEAR FROM d) AS y, CAST(a AS DATE) AS c, "
    "DATE_TRUNC('year', d) AS tr, LOWER(n) AS ln, COALESCE(x, 0) AS cx FROM t"
)
result = len(df)
"""
    problems = _validate(code)
    assert problems == [], problems


def test_helper_macros_pass():
    """Our injected helpers (years_between / as_date / today) are valid SQL."""
    code = """\
df = execute_sql_query(
    "SELECT years_between(start, today()) AS yrs, as_date(start) AS sd FROM t"
)
result = len(df)
"""
    problems = _validate(code)
    assert problems == [], problems


# -- R12: UNNEST struct-access nesting level ---------------------------------


def test_unnest_outer_alias_access_detected():
    """`q['Employee Qualification[...]']` reads from the outer UNNEST alias.
    The struct is nested under the inner field `rec`; reading `q['...']` is
    wrong and raises 'Could not find key ... Candidate entries: rec'."""
    code = """\
df = execute_sql_query('''
SELECT q['Employee Qualification[Qualification Title]']
FROM enterprise_data
LEFT JOIN UNNEST("[Employee Qualification[Qualification Title]]") AS q(rec) ON TRUE
''')
"""
    problems = _validate(code)
    assert any("outer UNNEST alias" in p and "inner field" in p for p in problems), problems


def test_unnest_inner_field_access_passes():
    """`rec['key']` and `q.rec['key']` are the correct nesting levels."""
    code = """\
df = execute_sql_query('''
SELECT rec['Employee Qualification[Qualification Title]'] AS a,
       q.rec['Employee Qualification[Qualification Title]'] AS b
FROM enterprise_data
LEFT JOIN UNNEST("[Employee Qualification[Qualification Title]]") AS q(rec) ON TRUE
''')
"""
    problems = _validate(code)
    assert problems == [], problems


# -- Near-miss undefined-variable typo hint ------------------------------------


def test_undefined_var_typo_suggests_close_match():
    """`emp_9822` closely matches assigned `emp_982` -> give a precise hint."""
    code = """\
emp_982 = df[df['emp_id'] == '0982']
out = emp_9822.iloc[0]['name']
result = {'type': 'string', 'value': out}
"""
    problems = _validate(code)
    assert any("emp_9822" in p and "emp_982" in p for p in problems), problems


def test_undefined_var_no_similar_name_keeps_generic_msg():
    """No close match -> generic message, no false hint."""
    code = """\
df = execute_sql_query('SELECT name FROM [Employee Master[Employee Name]]')
out = completely_unrelated_thing.iloc[0]['name']
result = out
"""
    problems = _validate(code)
    assert any("`completely_unrelated_thing` is referenced" in p for p in problems), problems


# -- Bare aggregate (R13 nan: SUM over zero rows) ------------------------------


def test_bare_sum_aggregate_detected():
    """Bare SUM(...) over possibly-empty data -> flag for COALESCE."""
    code = """\
df = execute_sql_query('SELECT SUM(rec[\\'Employee Leave Details[Leave Days]\\']) AS total FROM enterprise_data')
result = {'type': 'number', 'value': float(df['total'].iloc[0])}
"""
    problems = _validate(code)
    assert any("COALESCE" in p and "SUM" in p for p in problems), problems


def test_coalesced_sum_passes():
    """COALESCE(SUM(x), 0) must NOT be flagged."""
    code = """\
df = execute_sql_query("SELECT COALESCE(SUM(x), 0) AS total FROM enterprise")
result = len(df)
"""
    problems = _validate(code)
    assert problems == [], problems


def test_bare_count_not_flagged():
    """COUNT already returns 0 on empty; must not be flagged."""
    code = """\
df = execute_sql_query('SELECT COUNT(*) AS n FROM enterprise')
result = {'type': 'number', 'value': int(df['n'].iloc[0])}
"""
    problems = _validate(code)
    assert problems == [], problems


if __name__ == "__main__":
    import sys
    import traceback

    failed = 0
    tests = [fn for name, fn in globals().items() if name.startswith("test_") and callable(fn)]
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)