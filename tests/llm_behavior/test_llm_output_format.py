"""
LLM Output Format Test Harness
===============================

Sends realistic PandasAI prompts to the actual LLM and analyzes:
1. Code extraction success rate (``` vs ---\nCode: vs other)
2. Preview text / hallucination presence
3. DuckDB SQL syntax correctness
4. Result type compliance (string vs dataframe)
5. Code validity (ast.parse)

This is a manual integration test — not part of CI/CD.
Requires the LLM endpoint to be reachable.
"""

import ast
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import litellm

# ── LLM Configuration (from .env) ──────────────────────────────────────────
LLM_API_KEY = "sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8"
LLM_BASE_URL = "https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1"
LLM_MODEL = "openai/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"


# ── Prompt Templates ────────────────────────────────────────────────────────

# The ORIGINAL prompt ending (before our fix)
PROMPT_ENDING_ORIGINAL = """Generate python code and return full updated code:"""

# The FIXED prompt ending (with explicit code fence instruction)
PROMPT_ENDING_FIXED = """Generate python code and return full updated code wrapped in triple backticks:
```python
# your code here
```"""

# The result_format block WITHOUT the "no preview text" instruction
RESULT_FORMAT_ORIGINAL = """<result_format>
At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
result = {"type": "<type>", "value": <value>}
type (must be "string"), value must be a formatted string. Example: { "type": "string", "value": f"The highest salary is {highest_salary}." }

IMPORTANT: Even if the query seems to ask for a count or number, you MUST return type "string" with a descriptive text value. For example, if the query is "how many are female?", return: { "type": "string", "value": f"There are {count} female employees." } — NOT { "type": "number", "value": count }
Do NOT use `return`. Do NOT name the variable anything else (not `result_dict`, `result_value`, `output`, etc.).
</result_format>"""

# The result_format block WITH the "no preview text" instruction
RESULT_FORMAT_FIXED = """<result_format>
At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
result = {"type": "<type>", "value": <value>}
type (must be "string"), value must be a formatted string. Example: { "type": "string", "value": f"The highest salary is {highest_salary}." }

IMPORTANT: Even if the query seems to ask for a count or number, you MUST return type "string" with a descriptive text value. For example, if the query is "how many are female?", return: { "type": "string", "value": f"There are {count} female employees." } — NOT { "type": "number", "value": count }
Do NOT use `return`. Do NOT name the variable anything else (not `result_dict`, `result_value`, `output`, etc.).
Do NOT include preview text, result tables, or explanations before or after the code. Return ONLY the code.
</result_format>"""

# Shared prompt sections (realistic, matching what PandasAI sends)
DUCKDB_SYNTAX_BLOCK = """<duckdb_syntax>
You are writing **DuckDB SQL** — NOT PostgreSQL, MySQL, or T-SQL. Key differences:

1. **IS only works with NULL**: `IS NULL` / `IS NOT NULL` / `IS DISTINCT FROM` / `IS NOT DISTINCT FROM` are the ONLY valid `IS` expressions.
   - ✅ `WHERE col != '' AND col IS NOT NULL`
   - ❌ `WHERE col IS NOT ''` ← SYNTAX ERROR

2. **Column names with brackets**: When a column name contains `[...]`, the outer `[...]` is part of the name and MUST be included in double quotes.
   - ✅ `"[Employee Master[Employee Name]]"`
   - ❌ `"Employee Master[Employee Name]"` ← missing outer brackets

3. **String search**: Use `ILIKE '%term%'` for case-insensitive search.
4. **Double quotes = identifiers, single quotes = strings**: `"column_name"` is an identifier, `'string value'` is a string literal.
</duckdb_syntax>"""

SQL_FUNCTIONS_BLOCK = """The following functions have already been provided. Please use them as needed and do not redefine them.
<function>
def execute_sql_query(sql_query: str) -> pd.DataFrame
    Execute a DuckDB SQL query and return the result as a pandas DataFrame.
</function>"""

CODE_STRATEGY_BLOCK = """<code_strategy>
**You can write ANY valid Python code.** Use `execute_sql_query` for data retrieval, then process results with Python.

**Strategy: Divide and conquer**
1. Use SQL for filtering, joining, and aggregation (via `execute_sql_query`)
2. Use Python for presenting, formatting, computing derived values, and conditional logic
3. Keep SQL queries simple — retrieve raw data, then process in Python

**Result type selection:**
You MUST use type "string" — this is non-negotiable. Do NOT choose a different type regardless of what the query seems to ask for. Reformulate the data as needed to match this type.

**IMPORTANT: Use exact column names from the schema listings above.** Flat columns are `"column_name"`, struct fields after UNNEST are `var['field_name']`.
</code_strategy>"""

COLUMNS_BLOCK = """<columns>
<table_name>enterprise_data</table_name>
<column name="[Employee Master[Employee Name]]" type="VARCHAR">Employee full name</column>
<column name="[Employee Master[Employee Number]]" type="INTEGER">Unique employee identifier</column>
<column name="[Employee Master[Gender]]" type="VARCHAR">Employee gender (Male/Female)</column>
<column name="[Employee Master[Nationality]]" type="VARCHAR">Employee nationality</column>
</columns>"""

TABLE_BLOCK = """<table dialect="duckdb" table_name="enterprise_data">
[Employee Master[Employee Name]]|[Employee Master[Employee Number]]|[Employee Master[Gender]]|[Employee Master[Nationality]]
Ayesha Khalifa Shaheen Alghfeli|1306|Female|Emirati
Mohammed Ahmed Ali Alhammadi|2001|Male|Emirati
Ayesha Ahmed Khalifa Alameeri|1345|Female|Emirati
Fatima Saeed Obaid Alketbi|1450|Female|Emirati
Omar Hassan Mohammed Aldhaheri|1890|Male|Emirati
</table>"""

STARTER_CODE = """```python
# TODO: import the required dependencies
import pandas as pd

# Write code here

# Declare result var: type (must be "string"), value must be a formatted string.
```
"""


# ── Test Queries ─────────────────────────────────────────────────────────────

TEST_QUERIES = [
    "Find employees with the name 'Ayesha' and return their employee ID and full name.",
    "How many male and female employees are there? Give me the ratio.",
    "List all Emirati employees with their employee numbers.",
    "Search for employees whose name contains 'Mohammed'.",
    "What is the total count of employees in the database?",
]


# ── Analysis ─────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    query: str
    prompt_variant: str
    raw_response: str
    response_length: int = 0

    # Format analysis
    has_code_fences: bool = False        # ``` ... ```
    has_code_marker: bool = False        # ---\nCode: or \nCode:\n
    has_preview_text: bool = False       # Text before code
    has_hallucinated_table: bool = False # Markdown table with fabricated data

    # Code quality
    code_extracted: bool = False
    code_valid_python: bool = False
    result_type_correct: bool = False    # type="string"
    result_type_value: str = ""

    # SQL quality
    sql_uses_ilike_operator: bool = False  # Correct: col ILIKE '%x%'
    sql_uses_ilike_function: bool = False  # Wrong: ILIKE(col, '%x%')
    sql_column_names_correct: bool = False # Uses exact bracket names

    # Extraction method that worked
    extraction_method: str = ""  # "fence", "marker", "raw", "failed"

    error: Optional[str] = None


def analyze_response(response: str, query: str, prompt_variant: str) -> AnalysisResult:
    """Analyze an LLM response for format and quality issues."""
    result = AnalysisResult(
        query=query,
        prompt_variant=prompt_variant,
        raw_response=response,
        response_length=len(response),
    )

    try:
        # ── Format detection ──
        result.has_code_fences = "```" in response
        result.has_code_marker = bool(
            re.search(r"---\s*\n\s*Code\s*:", response)
            or re.search(r"\n\s*Code\s*:\s*\n", response)
        )

        # Detect preview text: any non-code text before the code block
        code_start = None
        if result.has_code_fences:
            fence_match = re.search(r"```", response)
            if fence_match:
                code_start = fence_match.start()
        elif result.has_code_marker:
            marker_match = re.search(r"(---\s*\n\s*Code\s*:|\n\s*Code\s*:)", response)
            if marker_match:
                code_start = marker_match.start()

        if code_start and code_start > 0:
            before_code = response[:code_start].strip()
            result.has_preview_text = len(before_code) > 10
            result.has_hallucinated_table = bool(re.search(r"\|.*\|.*\|", before_code))

        # ── Code extraction ──
        code = None

        # Method 1: Code fences
        if "```" in response and len(response.split("```")) > 1:
            code = response.split("```")[1]
            # Remove leading "python" or "py"
            code = re.sub(r"^(python|py)\n", "", code)
            result.extraction_method = "fence"
        else:
            # Method 2: Code markers
            for pattern in (
                r"---\s*\n\s*Code\s*:\s*\n",
                r"\n\s*Code\s*:\s*\n",
            ):
                match = re.search(pattern, response)
                if match:
                    code = response[match.end():]
                    result.extraction_method = "marker"
                    break

        if code is None:
            # Method 3: Try the whole response as code
            code = response.strip()
            result.extraction_method = "raw"

        code = code.strip()

        # ── Python validity ──
        try:
            ast.parse(code)
            result.code_valid_python = True
            result.code_extracted = True
        except SyntaxError:
            result.code_valid_python = False
            # Still check if we extracted something that looks like code
            result.code_extracted = "import " in code or "execute_sql_query" in code

        # ── Result type check ──
        type_match = re.search(r'"type"\s*:\s*"(\w+)"', code)
        if type_match:
            result.result_type_value = type_match.group(1)
            result.result_type_correct = result.result_type_value == "string"

        # ── SQL quality checks ──
        # Check for ILIKE as operator (correct): col ILIKE '%x%'
        result.sql_uses_ilike_operator = bool(re.search(r'"[^"]*"\s+ILIKE\s+', code))

        # Check for ILIKE as function (wrong): ILIKE(col, '%x%')
        result.sql_uses_ilike_function = bool(re.search(r'ILIKE\s*\(', code))

        # Check column names: should use exact bracket format
        result.sql_column_names_correct = bool(
            re.search(r'"\[Employee Master\[', code)
        )

    except Exception as e:
        result.error = str(e)

    return result


def call_llm(prompt: str) -> str:
    """Send a prompt to the LLM and return the response text."""
    import httpx
    import openai

    # Use the same approach as server/core/llm_setup.py:
    # httpx client (no SSL verify) → OpenAI client → direct completion
    httpx_client = httpx.Client(verify=False)
    openai_client = openai.OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        http_client=httpx_client,
    )

    response = openai_client.chat.completions.create(
        model="/model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
        messages=[{"role": "user", "content": prompt}],
        timeout=60,
    )

    httpx_client.close()
    return response.choices[0].message.content


def build_prompt(
    result_format: str,
    prompt_ending: str,
    query: str,
) -> str:
    """Build a full PandasAI-style prompt from components."""
    parts = [
        DUCKDB_SYNTAX_BLOCK,
        SQL_FUNCTIONS_BLOCK,
        result_format,
        CODE_STRATEGY_BLOCK,
        COLUMNS_BLOCK,
        TABLE_BLOCK,
        f"Update this initial code:\n{STARTER_CODE}",
        f"Answer the following question:\n{query}\n",
        prompt_ending,
    ]
    return "\n\n".join(parts)


def run_test_suite(
    variant_name: str,
    result_format: str,
    prompt_ending: str,
    queries: list[str] = TEST_QUERIES,
    runs_per_query: int = 2,
) -> list[AnalysisResult]:
    """Run a test suite with a given prompt variant."""
    results = []

    for query in queries:
        for run_idx in range(runs_per_query):
            prompt = build_prompt(result_format, prompt_ending, query)
            print(f"  [{variant_name}] Query: {query[:60]}... (run {run_idx+1}/{runs_per_query})")

            try:
                response = call_llm(prompt)
                analysis = analyze_response(response, query, variant_name)
                results.append(analysis)
                print(f"    → format: {analysis.extraction_method}, "
                      f"valid_python: {analysis.code_valid_python}, "
                      f"preview: {analysis.has_preview_text}, "
                      f"type: {analysis.result_type_value}, "
                      f"ILIKE_op: {analysis.sql_uses_ilike_operator}, "
                      f"ILIKE_fn: {analysis.sql_uses_ilike_function}")
            except Exception as e:
                print(f"    → ERROR: {e}")
                results.append(AnalysisResult(
                    query=query,
                    prompt_variant=variant_name,
                    raw_response="",
                    error=str(e),
                ))

            # Small delay to avoid rate limiting
            time.sleep(1)

    return results


def print_summary(results: list[AnalysisResult], variant_name: str):
    """Print a summary table for a test variant."""
    total = len(results)
    if total == 0:
        print(f"\n{'='*70}")
        print(f"  {variant_name}: NO RESULTS")
        return

    extracted = sum(1 for r in results if r.code_extracted)
    valid_python = sum(1 for r in results if r.code_valid_python)
    with_preview = sum(1 for r in results if r.has_preview_text)
    with_hallucination = sum(1 for r in results if r.has_hallucinated_table)
    type_correct = sum(1 for r in results if r.result_type_correct)
    ilike_operator = sum(1 for r in results if r.sql_uses_ilike_operator)
    ilike_function = sum(1 for r in results if r.sql_uses_ilike_function)
    col_names_ok = sum(1 for r in results if r.sql_column_names_correct)

    # Extraction method breakdown
    methods = {}
    for r in results:
        m = r.extraction_method or "failed"
        methods[m] = methods.get(m, 0) + 1

    print(f"\n{'='*70}")
    print(f"  VARIANT: {variant_name}")
    print(f"{'='*70}")
    print(f"  Total responses:          {total}")
    print(f"  Code extracted:           {extracted}/{total} ({100*extracted/total:.0f}%)")
    print(f"  Valid Python:             {valid_python}/{total} ({100*valid_python/total:.0f}%)")
    print(f"  Preview text present:     {with_preview}/{total} ({100*with_preview/total:.0f}%)")
    print(f"  Hallucinated tables:      {with_hallucination}/{total} ({100*with_hallucination/total:.0f}%)")
    print(f"  Result type='string':     {type_correct}/{total} ({100*type_correct/total:.0f}%)")
    print(f"  ILIKE as operator (✓):    {ilike_operator}/{total}")
    print(f"  ILIKE as function (✗):    {ilike_function}/{total}")
    print(f"  Correct column names:     {col_names_ok}/{total}")
    print(f"  Extraction methods:       {dict(methods)}")
    print(f"{'='*70}")

    # Show raw responses for first 2 results
    print(f"\n  --- Sample responses ({variant_name}) ---")
    for i, r in enumerate(results[:3]):
        print(f"\n  [{i+1}] Query: {r.query[:70]}...")
        print(f"  Extraction: {r.extraction_method} | Valid: {r.code_valid_python} | Preview: {r.has_preview_text}")
        # Show first 500 chars of raw response
        preview = r.raw_response[:500] if r.raw_response else "(empty)"
        print(f"  Raw (first 500 chars):\n  {preview}")
        if len(r.raw_response) > 500:
            print(f"  ... ({len(r.raw_response)} chars total)")


def compare_variants(baseline: list[AnalysisResult], improved: list[AnalysisResult]):
    """Print a comparison between two variants."""
    print(f"\n{'#'*70}")
    print(f"  COMPARISON: BASELINE vs FIXED")
    print(f"{'#'*70}")

    metrics = [
        ("Code extracted", lambda r: r.code_extracted),
        ("Valid Python", lambda r: r.code_valid_python),
        ("No preview text", lambda r: not r.has_preview_text),
        ("No hallucinated tables", lambda r: not r.has_hallucinated_table),
        ("Result type=string", lambda r: r.result_type_correct),
        ("ILIKE as operator (✓)", lambda r: r.sql_uses_ilike_operator),
        ("No ILIKE function (✗)", lambda r: not r.sql_uses_ilike_function),
        ("Correct column names", lambda r: r.sql_column_names_correct),
    ]

    b_total = len(baseline) or 1
    i_total = len(improved) or 1

    print(f"  {'Metric':<30} {'Baseline':>10} {'Fixed':>10} {'Delta':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")

    for name, metric_fn in metrics:
        b_val = sum(1 for r in baseline if metric_fn(r))
        i_val = sum(1 for r in improved if metric_fn(r))
        b_pct = 100 * b_val / b_total
        i_pct = 100 * i_val / i_total
        delta = i_pct - b_pct
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  {name:<30} {b_pct:>9.0f}% {i_pct:>9.0f}% {delta:>+8.0f}% {arrow}")

    # Extraction method comparison
    b_methods = {}
    i_methods = {}
    for r in baseline:
        m = r.extraction_method or "failed"
        b_methods[m] = b_methods.get(m, 0) + 1
    for r in improved:
        m = r.extraction_method or "failed"
        i_methods[m] = i_methods.get(m, 0) + 1
    print(f"\n  Extraction methods:")
    print(f"    Baseline: {dict(b_methods)}")
    print(f"    Fixed:    {dict(i_methods)}")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import urllib3
    urllib3.disable_warnings()

    parser = argparse.ArgumentParser(description="LLM Output Format Test Harness")
    parser.add_argument(
        "--variant",
        choices=["baseline", "fixed", "both"],
        default="both",
        help="Which prompt variant to test",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of runs per query (default: 2)",
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=5,
        help="Number of queries to test (default: 5)",
    )
    args = parser.parse_args()

    queries = TEST_QUERIES[: args.queries]

    print("=" * 70)
    print("  LLM OUTPUT FORMAT TEST HARNESS")
    print(f"  Model: {LLM_MODEL}")
    print(f"  Queries: {len(queries)}, Runs per query: {args.runs}")
    print(f"  Variant: {args.variant}")
    print("=" * 70)

    baseline_results = []
    fixed_results = []

    if args.variant in ("baseline", "both"):
        print("\n\n>>> RUNNING BASELINE (original prompt) <<<\n")
        baseline_results = run_test_suite(
            variant_name="BASELINE",
            result_format=RESULT_FORMAT_ORIGINAL,
            prompt_ending=PROMPT_ENDING_ORIGINAL,
            queries=queries,
            runs_per_query=args.runs,
        )
        print_summary(baseline_results, "BASELINE")

    if args.variant in ("fixed", "both"):
        print("\n\n>>> RUNNING FIXED (new prompt + no-preview instruction) <<<\n")
        fixed_results = run_test_suite(
            variant_name="FIXED",
            result_format=RESULT_FORMAT_FIXED,
            prompt_ending=PROMPT_ENDING_FIXED,
            queries=queries,
            runs_per_query=args.runs,
        )
        print_summary(fixed_results, "FIXED")

    if args.variant == "both":
        compare_variants(baseline_results, fixed_results)

    print("\n\nDone!")
