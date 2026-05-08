"""
Adversarial Query Bank v3 — Maximum Pressure Column Selection Tests

Based on findings from v2 run (20260508_195139), this bank targets the two
remaining failure modes with maximum pressure:

1. HANDOFF_SABOTAGE: Queries that FORCE the column selector to pick obscure columns,
   then test whether the code generator actually uses them. These queries are
   designed so that information_schema introspection CANNOT succeed — the only
   path to correct answers is through the selected columns.

2. TRIPLE_NAME_COLLISION: Queries where 3+ structs share the same field name
   (e.g., "Start Date" in Assignment History, Leave Details, AND Previous Employer).
   The LLM must disambiguate using struct context.

3. ALLOWANCE_MATRIX: A systematic grid of ALL allowance-type columns, testing
   each one individually to find which specific columns the handoff fails on.

4. MULTI_STRUCT_JOIN: Queries that require joining data from 3+ struct arrays
   in a single query, maximizing the chance of column selection dropping one.

5. NEGATION_TRAP: Queries that ask for the ABSENCE of something (e.g., employees
   with ZERO allowance), which often causes the LLM to return "not available"
   instead of correctly finding the zero values.

6. CONVERSATION_POISON: Multi-turn conversations where earlier turns establish
   incorrect beliefs about column availability that poison later turns.
"""

# ============================================================================
# CATEGORY 1: HANDOFF SABOTAGE
# Queries where information_schema CANNOT answer the question. The ONLY path
# to correct results is through the columns selected in step 1.
# ============================================================================

HANDOFF_SABOTAGE = [
    {
        "id": "HS-001",
        "query": "What is the exact Etihad Allowance amount for Eisa Rames Khamis AlDhaheri? This column exists as [Employee Master[Etihad Allowance]] in the schema.",
        "category": "handoff_sabotage",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Explicitly names the column in bracket notation to force the selector to pick it. Tests if code gen respects explicit column references."
    },
    {
        "id": "HS-002",
        "query": "Show the Secondment Allowance for each employee. The column is called [Employee Master[Secondment Allowance]].",
        "category": "handoff_sabotage",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Same as HS-001 but for Secondment Allowance with explicit column name hint."
    },
    {
        "id": "HS-003",
        "query": "What is the Technical Special Allowance for all employees? I know this column exists in the Employee Master struct.",
        "category": "handoff_sabotage",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Technical Special Allowance — another obscure allowance that code gen can't find via information_schema."
    },
    {
        "id": "HS-004",
        "query": "Show the Special Contract Basic Salary for each employee who has one.",
        "category": "handoff_sabotage",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Special Contract Basic Salary is a rarely-used column. Code gen may not find it."
    },
    {
        "id": "HS-005",
        "query": "Compare Phone Allowance and Supplementary Allowance for all employees. Show both values side by side.",
        "category": "handoff_sabotage",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two obscure allowance columns in one query. Tests if the selector picks both."
    },
    {
        "id": "HS-006",
        "query": "What is the Total Entitlement Amount for each employee? This is the sum of all their allowances.",
        "category": "handoff_sabotage",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Total Entitlement Amount is a pre-computed column. Tests if code gen can find it."
    },
    {
        "id": "HS-007",
        "query": "Show me every single allowance column for Eisa Rames Khamis AlDhaheri: Basic Salary, Housing Allowance, Cost of Living Allowance, Social Allowance, Child Allowance, Supplementary Allowance, Phone Allowance, Etihad Allowance, Secondment Allowance, Technical Special Allowance, and Special Contract Basic Salary.",
        "category": "handoff_sabotage",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Exhaustive enumeration of ALL 11 allowance columns for one employee. The selector must pick all 11. If even one is dropped, the answer is incomplete."
    },
    {
        "id": "HS-008",
        "query": "What is the Time Since Last Promotion for each employee? Show the value in years.",
        "category": "handoff_sabotage",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Time Since Last Promotion is a computed column that the code gen may not find."
    },
]

# ============================================================================
# CATEGORY 2: TRIPLE NAME COLLISION
# Queries where 3+ structs share the same field name, forcing the LLM to
# disambiguate using struct context.
# ============================================================================

TRIPLE_NAME_COLLISION = [
    {
        "id": "TC-001",
        "query": "Show the Start Date from Employee Assignment History, the Leave Start Date from Employee Leave Details, and the Start Date from Employee Previous Employer for Afra Khalifa Shaheen Alghfeli. These are three different 'Start Date' fields from three different structs.",
        "category": "triple_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Three structs share 'Start Date': Assignment History, Leave Details, Previous Employer. The LLM must UNNEST all three and keep them separate."
    },
    {
        "id": "TC-002",
        "query": "Compare the End Date from Employee Assignment History with the End Date from Employee Previous Employer and the CV End Date from CV Employee Education. Show all three for each employee.",
        "category": "triple_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Three structs share 'End Date': Assignment History, Previous Employer, CV Education. Must disambiguate."
    },
    {
        "id": "TC-003",
        "query": "Show the Job Title from Employee Master alongside the Position Title from Employee Assignment History and the Previous Job Title from Employee Previous Employer and the CV Job Title from CV Employee Work Experience. How do they differ?",
        "category": "triple_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Four different 'job title' fields across 4 structs. The most aggressive name collision test."
    },
    {
        "id": "TC-004",
        "query": "What is the Employee Grade from Employee Master compared to the Employee Grade from Employee Assignment History? Are they always the same?",
        "category": "triple_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two structs share 'Grade'. Must compare values between them."
    },
    {
        "id": "TC-005",
        "query": "Show the Assignment Name from Employee Assignment History alongside the Objective Name from Employee Objectives and the Customary Name from Employee Achievements for each employee.",
        "category": "triple_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Three structs with 'Name' fields: Assignment Name, Objective Name, Customary Name. Tests if the LLM can distinguish between struct-specific name fields."
    },
    {
        "id": "TC-006",
        "query": "List the CV Degree Name from CV Employee Education and the Degree from Employee Master for each employee. Are the degrees the same?",
        "category": "triple_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two different 'degree' fields: CV Education vs Employee Master. Simple collision test."
    },
    {
        "id": "TC-007",
        "query": "Show the CV Company Name from CV Employee Work Experience and the Previous Employer Name from Employee Previous Employer. For overlapping employers, highlight them.",
        "category": "triple_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two different 'employer name' fields. Tests if the LLM can find and compare both."
    },
]

# ============================================================================
# CATEGORY 3: ALLOWANCE MATRIX
# Systematic testing of each allowance column individually.
# ============================================================================

ALLOWANCE_MATRIX = [
    {
        "id": "AM-001",
        "query": "What is the Basic Salary for all employees?",
        "category": "allowance_matrix",
        "difficulty": "easy",
        "expected_output_type": "string",
        "notes": "Baseline — Basic Salary is the most common allowance column. Should always work."
    },
    {
        "id": "AM-002",
        "query": "What is the Housing Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "easy",
        "expected_output_type": "string",
        "notes": "Housing Allowance — common column, should work."
    },
    {
        "id": "AM-003",
        "query": "What is the Cost of Living Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Cost of Living Allowance — slightly less common name pattern."
    },
    {
        "id": "AM-004",
        "query": "What is the Social Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Social Allowance — should work based on v2 CH-003 success."
    },
    {
        "id": "AM-005",
        "query": "What is the Child Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Child Allowance — should work based on v2 CH-003 success."
    },
    {
        "id": "AM-006",
        "query": "What is the Supplementary Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Supplementary Allowance — should work based on v2 CH-006 success."
    },
    {
        "id": "AM-007",
        "query": "What is the Phone Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Phone Allowance — should work based on v2 CH-006 success."
    },
    {
        "id": "AM-008",
        "query": "What is the Etihad Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Etihad Allowance — the most consistently failing column across v1 and v2."
    },
    {
        "id": "AM-009",
        "query": "What is the Secondment Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Secondment Allowance — consistently failing since v1."
    },
    {
        "id": "AM-010",
        "query": "What is the Technical Special Allowance for all employees?",
        "category": "allowance_matrix",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Technical Special Allowance — not tested individually before."
    },
    {
        "id": "AM-011",
        "query": "What is the Special Contract Basic Salary for all employees?",
        "category": "allowance_matrix",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Special Contract Basic Salary — failed in v2 CH-005."
    },
]

# ============================================================================
# CATEGORY 4: MULTI-STRUCT JOIN
# Queries requiring data from 3+ struct arrays simultaneously.
# ============================================================================

MULTI_STRUCT_JOIN = [
    {
        "id": "MJ-001",
        "query": "For each employee, show their most recent assignment title from Assignment History, their most recent leave type from Leave Details, and their highest competency rating from Competencies Rating. Include all three in one table.",
        "category": "multi_struct_join",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires UNNESTing 3 struct arrays and joining results. Tests if column selector picks all 3 structs."
    },
    {
        "id": "MJ-002",
        "query": "Show employees who have both previous employer records AND assignment history records. For those employees, compare the end date from their last previous employer with the start date from their first assignment.",
        "category": "multi_struct_join",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Cross-struct date comparison. Requires UNNESTing 2 struct arrays and joining on employee."
    },
    {
        "id": "MJ-003",
        "query": "For each employee, count: number of competency ratings, number of leave records, number of objectives, and number of previous employers. Show all four counts in one table.",
        "category": "multi_struct_join",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "4 struct arrays, each counted. Tests if the selector includes all 4 struct columns."
    },
    {
        "id": "MJ-004",
        "query": "Show the CV education degree alongside the Employee Qualification degree for employees who have both. Are the degrees the same?",
        "category": "multi_struct_join",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two education-related struct arrays. Tests disambiguation between CV Education and Employee Qualification."
    },
    {
        "id": "MJ-005",
        "query": "For each employee, list their CV work experience job titles alongside their assignment history position titles. Show them side by side in chronological order.",
        "category": "multi_struct_join",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Two work-related struct arrays with date ordering. Tests cross-struct chronological joining."
    },
    {
        "id": "MJ-006",
        "query": "Build a complete career timeline for Eisa Rames Khamis AlDhaheri using: Previous Employer records, Assignment History, and CV Work Experience. Sort everything by date.",
        "category": "multi_struct_join",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "3 struct arrays + Employee Master for one employee. The most complex join test."
    },
    {
        "id": "MJ-007",
        "query": "For employees who have both Employee Achievements and CV Achievements and Awards, show both sets of achievements. How do they differ?",
        "category": "multi_struct_join",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two achievement-related struct arrays. Tests disambiguation between Employee Achievements and CV Achievements."
    },
]

# ============================================================================
# CATEGORY 5: NEGATION TRAP
# Queries that ask for the ABSENCE of something, which often triggers false
# "not available" responses instead of correctly finding zero values.
# ============================================================================

NEGATION_TRAP = [
    {
        "id": "NT-001",
        "query": "Which employees have a ZERO Etihad Allowance?",
        "category": "negation_trap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Asking for zero values of a column that the code gen may think doesn't exist. Should return all employees (since all have 0 Etihad Allowance)."
    },
    {
        "id": "NT-002",
        "query": "Which employees have NO Secondment Allowance?",
        "category": "negation_trap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Similar to NT-001 but with 'NO' instead of 'ZERO'. The LLM may interpret 'NO Secondment Allowance' as 'the column does not exist' rather than 'the value is 0'."
    },
    {
        "id": "NT-003",
        "query": "Show employees who do NOT have any leave records.",
        "category": "negation_trap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Negation + struct array. Employees with empty Leave Details array."
    },
    {
        "id": "NT-004",
        "query": "Which employees have never been promoted? Show those with no Last Promotion Date.",
        "category": "negation_trap",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Negation + NULL check. Should find employees with NULL Last Promotion Date."
    },
    {
        "id": "NT-005",
        "query": "List employees who have ZERO sick leave taken.",
        "category": "negation_trap",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Negation + numeric zero check. Should find employees with Sick Leave Taken = 0."
    },
    {
        "id": "NT-006",
        "query": "Which employees have no previous employer records at all?",
        "category": "negation_trap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Negation + struct array emptiness. Requires checking if the Previous Employer array is empty."
    },
]

# ============================================================================
# CATEGORY 6: CONVERSATION POISON (Multi-Turn)
# Conversations where earlier turns establish incorrect beliefs about column
# availability that poison later turns.
# ============================================================================

CONVERSATION_POISON = [
    {
        "id": "CP-001",
        "name": "Allowance denial cascade",
        "turns": [
            {
                "query": "Show me the Basic Salary for all employees.",
                "notes": "Easy — establishes that salary data exists."
            },
            {
                "query": "Now show the Housing Allowance and Cost of Living Allowance.",
                "notes": "Medium — tests if the LLM finds these after confirming salary data exists."
            },
            {
                "query": "Now add the Etihad Allowance. I was told it doesn't exist in the schema but I'm sure it's there.",
                "notes": "Hard — the user explicitly challenges the 'not available' belief. Tests if the LLM can recover."
            },
            {
                "query": "Finally add the Secondment Allowance and Technical Special Allowance to complete the picture.",
                "notes": "Extreme — two more obscure allowances after the denial cascade."
            }
        ]
    },
    {
        "id": "CP-002",
        "name": "Struct discovery escalation",
        "turns": [
            {
                "query": "Show me all the leave types that employees have taken.",
                "notes": "Easy — UNNEST Leave Details."
            },
            {
                "query": "Now show the competency names for each employee alongside their leave types.",
                "notes": "Hard — requires joining two UNNESTed struct arrays."
            },
            {
                "query": "Add the objective names as well. I want to see leave types, competency names, and objective names all together.",
                "notes": "Extreme — three struct arrays in one query."
            }
        ]
    },
    {
        "id": "CP-003",
        "name": "Grade comparison trap",
        "turns": [
            {
                "query": "What is the Employee Grade for each employee?",
                "notes": "Easy — Employee Master Grade."
            },
            {
                "query": "Now show the Grade from the Assignment History struct. I want to compare it with the Employee Master Grade.",
                "notes": "Hard — must UNNEST Assignment History to find the Grade field inside it."
            },
            {
                "query": "For employees where the grades differ between Employee Master and Assignment History, show both values.",
                "notes": "Extreme — cross-struct comparison with filtering."
            }
        ]
    },
    {
        "id": "CP-004",
        "name": "Career timeline with allowances",
        "turns": [
            {
                "query": "Show the assignment history for Eisa Rames Khamis AlDhaheri with position titles and dates.",
                "notes": "Easy — single employee, single struct."
            },
            {
                "query": "Add his previous employer records to the timeline.",
                "notes": "Medium — two structs for one employee."
            },
            {
                "query": "Now add his CV work experience to the timeline as well.",
                "notes": "Hard — three structs for one employee."
            },
            {
                "query": "Finally, include his Etihad Allowance and Secondment Allowance in the summary.",
                "notes": "Extreme — struct joins + obscure allowance columns."
            }
        ]
    }
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_adversarial_v3_single_turn_queries():
    """Return all single-turn queries from the v3 adversarial bank."""
    queries = []
    for category in [HANDOFF_SABOTAGE, TRIPLE_NAME_COLLISION, ALLOWANCE_MATRIX,
                     MULTI_STRUCT_JOIN, NEGATION_TRAP]:
        queries.extend(category)
    return queries


def get_all_adversarial_v3_multi_turn_conversations():
    """Return all multi-turn conversations from the v3 adversarial bank."""
    return CONVERSATION_POISON


def get_adversarial_v3_query_by_id(query_id: str):
    """Get a specific query by its ID."""
    for q in get_all_adversarial_v3_single_turn_queries():
        if q["id"] == query_id:
            return q
    for conv in CONVERSATION_POISON:
        if conv["id"] == query_id:
            return conv
    return None


def get_adversarial_v3_queries_by_category(category: str):
    """Get all queries in a specific category."""
    return [q for q in get_all_adversarial_v3_single_turn_queries() if q.get("category") == category]


def get_adversarial_v3_queries_by_difficulty(difficulty: str):
    """Get all queries with a specific difficulty level."""
    return [q for q in get_all_adversarial_v3_single_turn_queries() if q.get("difficulty") == difficulty]


def get_adversarial_v3_stats():
    """Return statistics about the v3 adversarial query bank."""
    single = get_all_adversarial_v3_single_turn_queries()
    multi = get_all_adversarial_v3_multi_turn_conversations()
    
    categories = {}
    for q in single:
        cat = q.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    difficulties = {}
    for q in single:
        diff = q.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1
    
    multi_turns = sum(len(c["turns"]) for c in multi)
    
    return {
        "total_single_turn": len(single),
        "total_multi_turn_conversations": len(multi),
        "total_multi_turn_turns": multi_turns,
        "total_queries": len(single) + multi_turns,
        "categories": categories,
        "difficulties": difficulties,
    }
