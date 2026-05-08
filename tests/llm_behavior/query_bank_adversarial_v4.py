"""
Adversarial Query Bank v4 — Column Selection Naming & Type Preservation Tests

Based on failure cases from real user queries, this bank targets three specific
failure modes in the 2-step column selection pipeline:

1. BRACKET_NAMING_INCONSISTENCY: The Step 1 LLM sees struct inner fields as
   "flat columns" with bracket-style names (e.g., "[Employee Leave Details[Leave Type]]")
   because the `_build_prompt()` method classifies them as flat when their parent
   is a combined column. When the LLM returns these names WITH outer brackets,
   the Step 2 code generator gets confused — it tries to find a column named
   "[Employee Leave Details[Leave Type]]" but the actual DataFrame column is the
   combined "[Employee Leave Details[Leave Type][Leave Duration (Days)]...]".
   
   The WORKING case is when the LLM returns names WITHOUT outer brackets
   (e.g., "Employee Leave Details[Leave Type]"), which matches the `duckdb_key`
   format used in the struct samples dict that the code gen sees.
   
   ROOT CAUSE: The select_columns.tmpl template shows inner fields as flat columns
   using `col.name` which includes brackets. The LLM copies this format. But the
   code gen prompt uses `duckdb_key` / `short_name` which DON'T include brackets.
   This naming mismatch causes the code gen to fail when it tries to reference
   columns by the wrong name.

2. EMPLOYEE_ID_LEADING_ZERO: The Employee Number column is declared as "string"
   in the semantic model, but the DataFrame reads it as integer from Excel,
   stripping leading zeros (e.g., "0111" becomes 111). The LLM correctly selects
   the column, but the data has already lost the leading zero during Excel import.

3. STRUCT_FIELD_PROMPT_CONFUSION: Queries that explicitly reference struct inner
   fields by name ("use the leave detail column") vs by category ("use the
   employee leave detail columns"). The former confuses the LLM because it sees
   inner fields as flat columns and doesn't know they're part of a struct.

These tests are designed to be run WITH column selection enabled
(--column-selection --column-selection-threshold 30).
"""

# ============================================================================
# CATEGORY 1: BRACKET NAMING INCONSISTENCY
# These queries target the exact failure case where the Step 1 LLM returns
# struct inner field names WITH outer brackets (e.g., "[Employee Leave Details[Leave Type]]")
# which don't match any actual DataFrame column. The code gen then falls back
# to DESCRIBE/information_schema which can't find the right column either.
# ============================================================================

BRACKET_NAMING_INCONSISTENCY = [
    {
        "id": "BN-001",
        "query": "what is the percentage by different leave types did ayesha take? use the leave detail column",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "EXACT REPRODUCTION of user's failure case. The phrase 'leave detail column' triggers the LLM to return bracket-style names like [Employee Leave Details[Leave Type]] which don't match the actual combined DataFrame column. The working variant uses 'employee leave detail columns' (plural)."
    },
    {
        "id": "BN-002",
        "query": "what is the percentage by different leave types did ayesha take? use the employee leave detail columns",
        "category": "bracket_naming_inconsistency",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "WORKING VARIANT of BN-001. The phrase 'employee leave detail columns' (plural) triggers the LLM to return names WITHOUT outer brackets like 'Employee Leave Details[Leave Type]' which match duckdb_key format. This should succeed where BN-001 fails."
    },
    {
        "id": "BN-003",
        "query": "Show me the leave type and duration for all employees. Use the leave detail column.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Same 'leave detail column' trigger as BN-001 but for all employees, not just Ayesha. Tests if the bracket naming issue is consistent across different query patterns."
    },
    {
        "id": "BN-004",
        "query": "List all leave types and their approval status for Nouf. Use the leave details.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests struct field selection for Leave Type + Approval Status. The LLM must select both inner fields. If the LLM returns bracket-style names, code gen may fail."
    },
    {
        "id": "BN-005",
        "query": "What are the different assignment names and their start dates for Ali? Use the assignment history column.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Tests bracket naming with Employee Assignment History struct. Same pattern as leave details — inner fields shown as flat columns in the prompt."
    },
    {
        "id": "BN-006",
        "query": "Show previous employer names and job titles for Sara. Use the previous employer column.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Tests bracket naming with Employee Previous Employer struct. Inner fields like 'Previous Employer Name' and 'Previous Job Title' are shown as flat columns."
    },
    {
        "id": "BN-007",
        "query": "What qualifications does Ahmed have? Show the qualification title and GPA. Use the qualification column.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Tests bracket naming with Employee Qualification struct. Qualification Title and GPA are inner fields."
    },
    {
        "id": "BN-008",
        "query": "What are the CV work experience details for Afra? Show company name and job title. Use the CV work experience column.",
        "category": "bracket_naming_inconsistency",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Tests bracket naming with CV Employee Work Experience struct. Company Name and Job Title are inner fields."
    },
]

# ============================================================================
# CATEGORY 2: EMPLOYEE ID LEADING ZERO
# These queries target the Employee Number column where leading zeros are
# stripped during Excel import because the column is typed as integer.
# The semantic model declares it as "string" but the DataFrame has it as int.
# ============================================================================

EMPLOYEE_ID_LEADING_ZERO = [
    {
        "id": "EZ-001",
        "query": "whatis the employee id of ayesha",
        "category": "employee_id_leading_zero",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "EXACT REPRODUCTION of user's failure case. Employee ID for Ayesha should be '0111' but is returned as 111 because the leading zero is stripped during Excel import. The column is declared as 'string' in the semantic model but read as integer from Excel."
    },
    {
        "id": "EZ-002",
        "query": "What is the employee number for Eisa Rames Khamis AlDhaheri? Show the full ID with any leading zeros.",
        "category": "employee_id_leading_zero",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests Employee Number for Eisa. Same leading zero issue — the LLM must return the ID as a string to preserve formatting."
    },
    {
        "id": "EZ-003",
        "query": "List all employee IDs and names. The employee ID should show the full number including leading zeros.",
        "category": "employee_id_leading_zero",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests all employee IDs. If the DataFrame has them as integers, leading zeros are already lost at import time. This tests whether the type inference system correctly preserves string types."
    },
    {
        "id": "EZ-004",
        "query": "Find the employee with ID 0111. What is their name?",
        "category": "employee_id_leading_zero",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Search by Employee Number with leading zero. If the data has '111' instead of '0111', the search will fail. This is the most direct test of the type preservation issue."
    },
    {
        "id": "EZ-005",
        "query": "What is the Family Book Number for Ayesha? This is a numeric ID that may have leading zeros.",
        "category": "employee_id_leading_zero",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests Family Book Number which is declared as 'float' in the semantic model but may have leading zeros or need string formatting."
    },
]

# ============================================================================
# CATEGORY 3: STRUCT FIELD PROMPT CONFUSION
# These queries test whether the LLM can correctly identify and select struct
# inner fields when the prompt shows them as flat columns. The key issue is
# that the select_columns.tmpl template shows inner fields like
# "[Employee Leave Details[Leave Type]]" as FLAT columns, but they're actually
# part of a combined struct column. The LLM doesn't know they're struct fields.
# ============================================================================

STRUCT_FIELD_PROMPT_CONFUSION = [
    {
        "id": "SP-001",
        "query": "what is the percetage by different leave types did ayesha take?",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "WORKING CASE from user's failure cases. Without 'use the leave detail column', the LLM returns names WITHOUT outer brackets and the query succeeds. This is the baseline to compare against BN-001."
    },
    {
        "id": "SP-002",
        "query": "Which employees have taken Annual leave? Check the leave type column.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests the LLM's ability to select the Leave Type inner field when told to 'check the leave type column'. The phrase 'column' (singular) may trigger bracket-style naming."
    },
    {
        "id": "SP-003",
        "query": "Show me the assignment history for each employee. Include the assignment name and the position title.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests struct field selection for Assignment History without explicit 'use the column' phrasing. The LLM must infer that 'assignment name' and 'position title' are inner fields of the Assignment History struct."
    },
    {
        "id": "SP-004",
        "query": "What degrees do employees have? Show the degree name and institution from the CV education section.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests CV Employee Education struct. The LLM must select CV Degree Name and CV Institution Name as inner fields."
    },
    {
        "id": "SP-005",
        "query": "What are the objectives for Noura? Show the objective name and its status.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests Employee Objectives struct. Objective Name and Objective Status are inner fields."
    },
    {
        "id": "SP-006",
        "query": "Show the competency ratings for each employee. Include the competency name and the employee rating.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests Employee Competencies Rating struct. Competancy Name and Employee Rating are inner fields."
    },
    {
        "id": "SP-007",
        "query": "What achievements does Shamma have? Show the achievement title and issue date.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests CV Employee Achievements and Awards struct. CV Title and CV Issue Date are inner fields."
    },
    {
        "id": "SP-008",
        "query": "List all employees and their hobbies. Show the interest name and description.",
        "category": "struct_field_prompt_confusion",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests CV Employee Interest and Hobbies struct. CV Interest Name and CV Interest Description are inner fields."
    },
]

# ============================================================================
# CATEGORY 4: COLUMN HINT PHRASING VARIANTS
# These queries systematically test different phrasings of "use the X column"
# to determine which phrasings trigger bracket-style naming and which don't.
# This helps identify the exact prompt pattern that causes the failure.
# ============================================================================

COLUMN_HINT_PHRASING = [
    {
        "id": "CH-001",
        "query": "What leave types did Ayesha take? use the leave detail column",
        "category": "column_hint_phrasing",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Lowercase 'use the leave detail column' — matches the exact failing user query."
    },
    {
        "id": "CH-002",
        "query": "What leave types did Ayesha take? Use the Leave Detail column",
        "category": "column_hint_phrasing",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Capitalized 'Use the Leave Detail column' — tests if capitalization matters."
    },
    {
        "id": "CH-003",
        "query": "What leave types did Ayesha take? use the employee leave detail columns",
        "category": "column_hint_phrasing",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Lowercase 'use the employee leave detail columns' (plural) — matches the working user query."
    },
    {
        "id": "CH-004",
        "query": "What leave types did Ayesha take? Refer to the Employee Leave Details struct",
        "category": "column_hint_phrasing",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Uses 'struct' terminology — tests if the LLM understands struct references differently."
    },
    {
        "id": "CH-005",
        "query": "What leave types did Ayesha take? Look at [Employee Leave Details[Leave Type]]",
        "category": "column_hint_phrasing",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Uses explicit bracket-style column name in the query — forces the LLM to use bracket notation."
    },
    {
        "id": "CH-006",
        "query": "What leave types did Ayesha take? Check Employee Leave Details[Leave Type]",
        "category": "column_hint_phrasing",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Uses duckdb_key-style column name (no outer brackets) — should work correctly."
    },
    {
        "id": "CH-007",
        "query": "Show me leave types and durations for all employees. I want to see the leave details.",
        "category": "column_hint_phrasing",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Indirect reference to leave details — no explicit 'use the column' phrasing. Should work naturally."
    },
    {
        "id": "CH-008",
        "query": "Show me leave types and durations for all employees. Use the leave data.",
        "category": "column_hint_phrasing",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Vague 'use the leave data' — tests if vague references still trigger the bracket naming issue."
    },
]

# ============================================================================
# CATEGORY 5: MULTI-STRUCT FIELD SELECTION
# These queries require selecting inner fields from MULTIPLE struct columns
# in the same query. This tests whether the column selector can correctly
# handle multiple struct parents simultaneously, and whether the code gen
# can correctly UNNEST multiple struct arrays.
# ============================================================================

MULTI_STRUCT_FIELD_SELECTION = [
    {
        "id": "MS-001",
        "query": "Show each employee's leave types and their assignment names. Use both the leave details and assignment history.",
        "category": "multi_struct_field_selection",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires UNNEST of both Employee Leave Details and Employee Assignment History. Tests if the column selector picks fields from both structs and code gen handles both UNNESTs."
    },
    {
        "id": "MS-002",
        "query": "For each employee, show their previous employer names and their CV education degrees. Use both the previous employer and CV education columns.",
        "category": "multi_struct_field_selection",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires UNNEST of Employee Previous Employer and CV Employee Education. Two struct arrays in one query."
    },
    {
        "id": "MS-003",
        "query": "Show Ayesha's leave types, assignment history, and previous employers all in one report. Use the leave detail, assignment history, and previous employer columns.",
        "category": "multi_struct_field_selection",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Triple UNNEST: Leave Details + Assignment History + Previous Employer. Maximum pressure on column selector and code gen."
    },
    {
        "id": "MS-004",
        "query": "Compare each employee's CV work experience with their assignment history. Show company names and assignment names side by side.",
        "category": "multi_struct_field_selection",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "UNNEST of CV Employee Work Experience and Employee Assignment History. Cross-struct comparison."
    },
    {
        "id": "MS-005",
        "query": "Show each employee's qualifications and their competencies. Include qualification title and competency name.",
        "category": "multi_struct_field_selection",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "UNNEST of Employee Qualification and Employee Competencies Rating. Two struct arrays."
    },
]

# ============================================================================
# CATEGORY 6: NAMING CONVENTION STRESS TEST
# These queries specifically test the naming convention boundary — what happens
# when the LLM sees inner fields as flat columns in the prompt and must decide
# how to reference them in its response. The key variable is whether the LLM
# returns names with or without outer brackets.
# ============================================================================

NAMING_CONVENTION_STRESS = [
    {
        "id": "NC-001",
        "query": "What is the total leave duration in days for each leave type for Ayesha? I need Leave Type and Leave Duration (Days) from the Employee Leave Details.",
        "category": "naming_convention_stress",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Uses the exact field names 'Leave Type' and 'Leave Duration (Days)' which match the short_name format. Should trigger non-bracket naming."
    },
    {
        "id": "NC-002",
        "query": "What is the total leave duration for each leave type for Ayesha? I need [Employee Leave Details[Leave Type]] and [Employee Leave Details[Leave Duration (Days)]].",
        "category": "naming_convention_stress",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Uses the exact bracket-style names that appear in the prompt. Forces the LLM to copy the bracket format, which is the failing pattern."
    },
    {
        "id": "NC-003",
        "query": "Show the Previous Employer Name and Previous Job Title for each employee. I need these from the Employee Previous Employer struct.",
        "category": "naming_convention_stress",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Uses short_name format for Previous Employer fields. Should work if the LLM returns non-bracket names."
    },
    {
        "id": "NC-004",
        "query": "Show [Employee Previous Employer[Previous Employer Name]] and [Employee Previous Employer[Previous Job Title]] for each employee.",
        "category": "naming_convention_stress",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Uses bracket-style names for Previous Employer fields. Forces the failing pattern."
    },
    {
        "id": "NC-005",
        "query": "What is the CV Employee Summary for each employee? Show the summary text.",
        "category": "naming_convention_stress",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Tests a single inner field struct (CV Employee Summary has only one field). Simpler case — should always work."
    },
    {
        "id": "NC-006",
        "query": "Show the Goal Plan Name and Objective Name for each employee's objectives. I need these from the Employee Objectives.",
        "category": "naming_convention_stress",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Tests Employee Objectives struct with short_name format. Multiple inner fields."
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_adversarial_v4_single_turn_queries():
    """Return all single-turn queries from the v4 adversarial bank."""
    queries = []
    for category in [BRACKET_NAMING_INCONSISTENCY, EMPLOYEE_ID_LEADING_ZERO,
                     STRUCT_FIELD_PROMPT_CONFUSION, COLUMN_HINT_PHRASING,
                     MULTI_STRUCT_FIELD_SELECTION, NAMING_CONVENTION_STRESS]:
        queries.extend(category)
    return queries


def get_all_adversarial_v4_multi_turn_conversations():
    """Return all multi-turn conversations from the v4 adversarial bank."""
    return []


def get_adversarial_v4_query_by_id(query_id: str):
    """Get a specific query by its ID."""
    for q in get_all_adversarial_v4_single_turn_queries():
        if q["id"] == query_id:
            return q
    return None


def get_adversarial_v4_queries_by_category(category: str):
    """Get all queries in a specific category."""
    return [q for q in get_all_adversarial_v4_single_turn_queries() if q.get("category") == category]


def get_adversarial_v4_queries_by_difficulty(difficulty: str):
    """Get all queries with a specific difficulty level."""
    return [q for q in get_all_adversarial_v4_single_turn_queries() if q.get("difficulty") == difficulty]


def get_adversarial_v4_stats():
    """Return statistics about the v4 adversarial query bank."""
    single = get_all_adversarial_v4_single_turn_queries()
    
    categories = {}
    for q in single:
        cat = q.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    difficulties = {}
    for q in single:
        diff = q.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1
    
    return {
        "total_single_turn": len(single),
        "total_multi_turn_conversations": 0,
        "total_multi_turn_turns": 0,
        "total_queries": len(single),
        "categories": categories,
        "difficulties": difficulties,
    }


if __name__ == "__main__":
    import json
    stats = get_adversarial_v4_stats()
    print(json.dumps(stats, indent=2))
    print()
    print("Query IDs:")
    for q in get_all_adversarial_v4_single_turn_queries():
        print(f"  {q['id']}: {q['query'][:80]}...")
