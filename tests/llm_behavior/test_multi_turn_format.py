"""
Multi-turn LLM Output Format Test
===================================

Simulates the EXACT multi-turn conversation flow from the production trace:
1. First query succeeds (gender ratio)
2. Second query fails (Ayesha name search) because LLM switches to ---\nCode: format

This tests whether the LLM's output format changes across conversation turns,
which is what we observed in the production trace.
"""

import ast
import re
import time
import httpx
import openai
import urllib3

urllib3.disable_warnings()

# ── LLM Configuration ──────────────────────────────────────────────────────
LLM_API_KEY = "sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8"
LLM_BASE_URL = "https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1"
LLM_MODEL = "/model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"

# ── Shared prompt sections ──────────────────────────────────────────────────

DUCKDB_SYNTAX = """<duckdb_syntax>
You are writing **DuckDB SQL** — NOT PostgreSQL, MySQL, or T-SQL. Key differences:

1. **IS only works with NULL**: `IS NULL` / `IS NOT NULL` are the ONLY valid `IS` expressions.
2. **Column names with brackets**: When a column name contains `[...]`, the outer `[...]` is part of the name and MUST be included in double quotes.
   - ✅ `"[Employee Master[Employee Name]]"`
   - ❌ `"Employee Master[Employee Name]"` ← missing outer brackets
3. **String search**: Use `ILIKE '%term%'` for case-insensitive search.
4. **Double quotes = identifiers, single quotes = strings**.
</duckdb_syntax>"""

SQL_FUNCTIONS = """The following functions have already been provided. Please use them as needed and do not redefine them.
<function>
def execute_sql_query(sql_query: str) -> pd.DataFrame
    Execute a DuckDB SQL query and return the result as a pandas DataFrame.
</function>"""

RESULT_FORMAT_ORIGINAL = """<result_format>
At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
result = {"type": "<type>", "value": <value>}
type (must be "string"), value must be a formatted string. Example: { "type": "string", "value": f"The highest salary is {highest_salary}." }
Do NOT use `return`. Do NOT name the variable anything else (not `result_dict`, `result_value`, `output`, etc.).
</result_format>"""

RESULT_FORMAT_FIXED = """<result_format>
At the end of the generated code, you MUST declare a variable named exactly `result` as a dictionary:
result = {"type": "<type>", "value": <value>}
type (must be "string"), value must be a formatted string. Example: { "type": "string", "value": f"The highest salary is {highest_salary}." }
Do NOT use `return`. Do NOT name the variable anything else (not `result_dict`, `result_value`, `output`, etc.).
Do NOT include preview text, result tables, or explanations before or after the code. Return ONLY the code.
</result_format>"""

CODE_STRATEGY = """<code_strategy>
**You can write ANY valid Python code.** Use `execute_sql_query` for data retrieval, then process results with Python.

**Strategy: Divide and conquer**
1. Use SQL for filtering, joining, and aggregation (via `execute_sql_query`)
2. Use Python for presenting, formatting, computing derived values, and conditional logic
3. Keep SQL queries simple — retrieve raw data, then process in Python

**Result type selection:**
You MUST use type "string" — this is non-negotiable.

**IMPORTANT: Use exact column names from the schema listings above.**
</code_strategy>"""

COLUMNS = """<columns>
<table_name>enterprise_data</table_name>
<column name="[Employee Master[Employee Name]]" type="VARCHAR">Employee full name</column>
<column name="[Employee Master[Employee Number]]" type="INTEGER">Unique employee identifier</column>
<column name="[Employee Master[Gender]]" type="VARCHAR">Employee gender (Male/Female)</column>
<column name="[Employee Master[Nationality]]" type="VARCHAR">Employee nationality</column>
</columns>"""

TABLE = """<table dialect="duckdb" table_name="enterprise_data">
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
```"""


def build_system_prompt(result_format: str) -> str:
    return f"""You are a data analyst assistant. You write Python code to answer questions about data.
You use DuckDB SQL via the execute_sql_query function, then process results in Python.
Always wrap your code in triple backticks (```python ... ```). Return ONLY the code — no explanations, no preview tables, no markdown tables with fabricated data."""


def build_user_prompt(result_format: str, prompt_ending: str, query: str) -> str:
    parts = [
        DUCKDB_SYNTAX,
        SQL_FUNCTIONS,
        result_format,
        CODE_STRATEGY,
        COLUMNS,
        TABLE,
        f"Update this initial code:\n{STARTER_CODE}",
        f"Answer the following question:\n{query}",
        prompt_ending,
    ]
    return "\n\n".join(parts)


def call_llm(messages: list[dict]) -> str:
    """Send messages to the LLM and return the response text."""
    httpx_client = httpx.Client(verify=False)
    openai_client = openai.OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        http_client=httpx_client,
    )

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        timeout=60,
    )

    httpx_client.close()
    return response.choices[0].message.content


def analyze_format(response: str) -> dict:
    """Analyze the format of an LLM response."""
    has_fences = "```" in response
    has_code_marker = bool(
        re.search(r"---\s*\n\s*Code\s*:", response)
        or re.search(r"\n\s*Code\s*:\s*\n", response)
    )

    # Detect preview text before code
    code_start = None
    if has_fences:
        m = re.search(r"```", response)
        if m:
            code_start = m.start()
    elif has_code_marker:
        m = re.search(r"(---\s*\n\s*Code\s*:|\n\s*Code\s*:)", response)
        if m:
            code_start = m.start()

    has_preview = False
    has_hallucinated_table = False
    if code_start and code_start > 10:
        before = response[:code_start].strip()
        has_preview = len(before) > 10
        has_hallucinated_table = bool(re.search(r"\|.*\|.*\|", before))

    # Try to extract code
    code = None
    method = "failed"
    if has_fences and len(response.split("```")) > 1:
        code = response.split("```")[1]
        code = re.sub(r"^(python|py)\n", "", code).strip()
        method = "fence"
    elif has_code_marker:
        for pattern in (r"---\s*\n\s*Code\s*:\s*\n", r"\n\s*Code\s*:\s*\n"):
            m = re.search(pattern, response)
            if m:
                code = response[m.end():].strip()
                method = "marker"
                break

    valid_python = False
    if code:
        try:
            ast.parse(code)
            valid_python = True
        except SyntaxError:
            pass

    # Check result type
    type_match = re.search(r'"type"\s*:\s*"(\w+)"', response)
    result_type = type_match.group(1) if type_match else "unknown"

    # Check SQL quality
    ilike_op = bool(re.search(r'"[^"]*"\s+ILIKE\s+', response))
    ilike_fn = bool(re.search(r'ILIKE\s*\(', response))

    return {
        "has_fences": has_fences,
        "has_code_marker": has_code_marker,
        "has_preview": has_preview,
        "has_hallucinated_table": has_hallucinated_table,
        "extraction_method": method,
        "valid_python": valid_python,
        "result_type": result_type,
        "ilike_operator": ilike_op,
        "ilike_function": ilike_fn,
        "response_length": len(response),
    }


def run_multi_turn_test(
    variant_name: str,
    result_format: str,
    prompt_ending: str,
    num_rounds: int = 3,
):
    """
    Run a multi-turn conversation test that simulates the production scenario:
    Turn 1: Gender ratio query (the one that succeeded in production)
    Turn 2: Ayesha name search (the one that failed in production)
    Turn 3: Another search query to check consistency
    """
    queries = [
        "Calculate the ratio of men to women employees.",
        "Find employees with the name 'Ayesha' and return their employee ID and full name.",
        "List all Emirati female employees with their employee numbers.",
    ]

    system_prompt = build_system_prompt(result_format)
    messages = [{"role": "system", "content": system_prompt}]

    results = []

    for round_idx in range(num_rounds):
        query = queries[round_idx % len(queries)]
        user_prompt = build_user_prompt(result_format, prompt_ending, query)

        messages.append({"role": "user", "content": user_prompt})

        print(f"\n  [{variant_name}] Round {round_idx+1}: {query[:70]}...")

        try:
            response = call_llm(messages)
            analysis = analyze_format(response)
            analysis["query"] = query
            analysis["round"] = round_idx + 1
            results.append(analysis)

            print(f"    → format: {analysis['extraction_method']}, "
                  f"valid: {analysis['valid_python']}, "
                  f"preview: {analysis['has_preview']}, "
                  f"hallucinated: {analysis['has_hallucinated_table']}, "
                  f"type: {analysis['result_type']}, "
                  f"ILIKE_op: {analysis['ilike_operator']}, "
                  f"ILIKE_fn: {analysis['ilike_function']}")

            # Show first 300 chars of response for inspection
            print(f"    → Response start: {response[:200].replace(chr(10), ' ')}")

            # Add assistant response to conversation history (simulating multi-turn)
            messages.append({"role": "assistant", "content": response})

        except Exception as e:
            print(f"    → ERROR: {e}")
            results.append({
                "query": query,
                "round": round_idx + 1,
                "extraction_method": "error",
                "valid_python": False,
                "has_preview": False,
                "has_hallucinated_table": False,
                "has_fences": False,
                "has_code_marker": False,
                "result_type": "error",
                "ilike_operator": False,
                "ilike_function": False,
                "response_length": 0,
            })

        time.sleep(2)  # Rate limiting

    return results


def print_multi_turn_summary(results: list[dict], variant_name: str):
    """Print summary for multi-turn results."""
    total = len(results)
    if total == 0:
        return

    print(f"\n{'='*70}")
    print(f"  MULTI-TURN RESULTS: {variant_name}")
    print(f"{'='*70}")

    for r in results:
        print(f"  Round {r['round']}: {r['query'][:50]}...")
        print(f"    Extraction: {r['extraction_method']} | Valid: {r['valid_python']} | "
              f"Preview: {r['has_preview']} | Hallucinated: {r['has_hallucinated_table']} | "
              f"Type: {r['result_type']}")

    extracted = sum(1 for r in results if r["extraction_method"] in ("fence", "marker", "raw"))
    valid = sum(1 for r in results if r["valid_python"])
    with_preview = sum(1 for r in results if r["has_preview"])
    with_hallucination = sum(1 for r in results if r["has_hallucinated_table"])
    type_ok = sum(1 for r in results if r["result_type"] == "string")

    print(f"\n  Summary:")
    print(f"    Code extracted:  {extracted}/{total}")
    print(f"    Valid Python:    {valid}/{total}")
    print(f"    Preview text:    {with_preview}/{total}")
    print(f"    Hallucinations:  {with_hallucination}/{total}")
    print(f"    Type='string':   {type_ok}/{total}")

    # Check if format degrades across turns
    fence_by_round = {}
    for r in results:
        rd = r["round"]
        fence_by_round[rd] = fence_by_round.get(rd, 0) + (1 if r["has_fences"] else 0)
    print(f"    Code fences by round: {fence_by_round}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-turn LLM Output Format Test")
    parser.add_argument(
        "--variant",
        choices=["baseline", "fixed", "both"],
        default="both",
        help="Which prompt variant to test",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Number of conversation rounds (default: 3)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=2,
        help="Number of times to repeat the full conversation (default: 2)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  MULTI-TURN LLM OUTPUT FORMAT TEST")
    print(f"  Model: {LLM_MODEL}")
    print(f"  Rounds per conversation: {args.rounds}")
    print(f"  Conversation repeats: {args.repeat}")
    print("=" * 70)

    PROMPT_ENDING_ORIGINAL = "Generate python code and return full updated code:"
    PROMPT_ENDING_FIXED = """Generate python code and return full updated code wrapped in triple backticks:
```python
# your code here
```"""

    all_baseline = []
    all_fixed = []

    if args.variant in ("baseline", "both"):
        for rep in range(args.repeat):
            print(f"\n\n{'#'*70}")
            print(f"  BASELINE - Conversation {rep+1}/{args.repeat}")
            print(f"{'#'*70}")
            results = run_multi_turn_test(
                variant_name="BASELINE",
                result_format=RESULT_FORMAT_ORIGINAL,
                prompt_ending=PROMPT_ENDING_ORIGINAL,
                num_rounds=args.rounds,
            )
            all_baseline.extend(results)
            print_multi_turn_summary(results, f"BASELINE (conv {rep+1})")

    if args.variant in ("fixed", "both"):
        for rep in range(args.repeat):
            print(f"\n\n{'#'*70}")
            print(f"  FIXED - Conversation {rep+1}/{args.repeat}")
            print(f"{'#'*70}")
            results = run_multi_turn_test(
                variant_name="FIXED",
                result_format=RESULT_FORMAT_FIXED,
                prompt_ending=PROMPT_ENDING_FIXED,
                num_rounds=args.rounds,
            )
            all_fixed.extend(results)
            print_multi_turn_summary(results, f"FIXED (conv {rep+1})")

    # Final comparison
    if args.variant == "both":
        print(f"\n\n{'#'*70}")
        print(f"  FINAL COMPARISON")
        print(f"{'#'*70}")
        print_multi_turn_summary(all_baseline, "ALL BASELINE")
        print_multi_turn_summary(all_fixed, "ALL FIXED")

    print("\nDone!")
