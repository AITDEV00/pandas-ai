"""
Adversarial Query Bank v2 — Targeted Column Selection Stress Tests

Based on findings from the first adversarial run (20260508_192200), this bank
specifically targets the three failure modes discovered:

1. COLUMN_SELECTION_HANOFF: Queries where the selector picks the right columns
   but the code generator ignores them and falls back to information_schema.
2. SEMANTIC_MAPPING_GAP: Queries using domain-specific terms that the selector
   can't map to the actual column names (e.g., "ADEO experience" → Date of Joining).
3. STRUCT_INNER_FIELD_BLINDNESS: Queries where the selector provides struct column
   names but the code generator can't discover inner fields through schema introspection.

Additionally adds:
4. RETRIAL_TRAP: Queries that work on first turn but fail on follow-up because
   the column selection context degrades over multi-turn conversations.
5. COLUMN_NAME_COLLISION: Queries where two different structs have similarly-named
   inner fields (e.g., "Start Date" in Assignment History vs "Start Date" in Leave).
6. BUDGET_RATIO_EDGE: Queries that need exactly the budget_ratio boundary number
   of columns, testing whether the selector truncates at the budget limit.
"""

# ============================================================================
# CATEGORY 1: COLUMN SELECTION HANDOFF FAILURE
# These queries target columns that the selector correctly identifies but the
# code generator then ignores, falling back to information_schema introspection.
# ============================================================================

COLUMN_SELECTION_HANDOFF = [
    {
        "id": "CH-001",
        "query": "What is the Etihad Allowance for Shamma Salem Saeed Aldhaheri?",
        "category": "column_selection_handoff",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Single-employee query for the most commonly missed allowance column. Selector should pick [Employee Master[Etihad Allowance]] but code gen may fall back to schema introspection."
    },
    {
        "id": "CH-002",
        "query": "List all employees who have a non-zero Secondment Allowance.",
        "category": "column_selection_handoff",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Secondment Allowance is another obscure column that the code gen step typically can't find through information_schema."
    },
    {
        "id": "CH-003",
        "query": "Compare the Social Allowance and Child Allowance for each employee. Which is higher?",
        "category": "column_selection_handoff",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two obscure allowance columns that may be filtered out. In the first run, CO-004 (Supplementary Allowance) worked but CO-001 (Etihad) didn't."
    },
    {
        "id": "CH-004",
        "query": "What is the Family Book Number for Eisa Rames Khamis AlDhaheri, and how many spouses and children does he have registered?",
        "category": "column_selection_handoff",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Family Book Number, Number of Spouses, Number of Children — all obscure demographic columns. CO-003 in v1 returned correct data, testing if single-employee focus changes behavior."
    },
    {
        "id": "CH-005",
        "query": "Show me the Special Contract Basic Salary for all employees. How does it differ from the regular Basic Salary?",
        "category": "column_selection_handoff",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Special Contract Basic Salary was reported as 'not available' in CO-005 v1. This column may genuinely not exist in the view, making it a test of whether the LLM can distinguish 'column filtered out' from 'column doesn't exist'."
    },
    {
        "id": "CH-006",
        "query": "What is the Phone Allowance for each employee? Is it the same across all grades?",
        "category": "column_selection_handoff",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Phone Allowance was found in v1 (CO-002 returned 0.0 for all). Testing if it's consistently found or if column selection variability affects results."
    },
    {
        "id": "CH-007",
        "query": "For each employee, show: Employee Name, Etihad Allowance, Secondment Allowance, Technical Special Allowance, Phone Allowance, and Supplementary Allowance.",
        "category": "column_selection_handoff",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requests 5 obscure allowance columns simultaneously. The column selector must include ALL of them, and the code gen must use them directly without schema introspection."
    },
]

# ============================================================================
# CATEGORY 2: SEMANTIC MAPPING GAP
# These queries use domain-specific terms that don't match column names directly.
# The selector must understand that "seniority" maps to Date of Joining, etc.
# ============================================================================

SEMANTIC_MAPPING_GAP = [
    {
        "id": "SM-001",
        "query": "Who are the most senior employees at ADEO? List them by years of service.",
        "category": "semantic_mapping_gap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "'Senior' and 'years of service' must map to [Employee Master[Date of Joining]]. In v1, AMT-002 Turn 1 failed because selector only picked Name and Email."
    },
    {
        "id": "SM-002",
        "query": "Which employees have been with ADEO the longest? Show their tenure in years.",
        "category": "semantic_mapping_gap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Another phrasing for 'seniority' / 'years of service'. Testing if different phrasing changes column selection behavior."
    },
    {
        "id": "SM-003",
        "query": "How many sick days has each employee used this year?",
        "category": "semantic_mapping_gap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "'Sick days' must map to [Employee Master[Sick Leave Taken]] or [Employee Leave Details] with Sick Leave type. Testing if the selector understands 'sick days' = 'Sick Leave'."
    },
    {
        "id": "SM-004",
        "query": "Which employees are due for promotion based on their time in current grade?",
        "category": "semantic_mapping_gap",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "'Time in current grade' requires [Employee Master[Last Promotion Date]] and [Employee Master[Grade]]. The selector must understand the semantic connection."
    },
    {
        "id": "SM-005",
        "query": "Show the organizational hierarchy: sectors, divisions, and departments with employee counts.",
        "category": "semantic_mapping_gap",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "'Organizational hierarchy' must map to Sector, Division, Department columns. Should be easier since these are common columns."
    },
    {
        "id": "SM-006",
        "query": "What is the gender diversity ratio in each department?",
        "category": "semantic_mapping_gap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "'Gender diversity ratio' must map to [Employee Master[Gender]] and [Employee Master[Department]]. Testing if 'diversity' triggers the right columns."
    },
    {
        "id": "SM-007",
        "query": "Which employees have the highest academic qualifications? Rank by degree level.",
        "category": "semantic_mapping_gap",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "'Academic qualifications' and 'degree level' must map to [Employee Master[Degree]] or [Employee Qualification[...]]. Testing if 'academic' triggers the right struct."
    },
]

# ============================================================================
# CATEGORY 3: STRUCT INNER FIELD BLINDNESS
# These queries require UNNEST on struct arrays where the inner field names
# are not discoverable through information_schema introspection.
# ============================================================================

STRUCT_INNER_FIELD_BLINDNESS = [
    {
        "id": "SB-001",
        "query": "List all leave records with their leave type, duration, and approval status for each employee.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [Employee Leave Details] struct. Inner fields: Leave Type, Leave Duration (Days), Approval Status, Leave Start Date, Leave End Date. Not visible in information_schema."
    },
    {
        "id": "SB-002",
        "query": "Show all competency ratings with the competency name, employee rating, and supervisor rating.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [Employee Competencies Rating] struct. Inner fields: Competancy Name, Employee Rating, Supervisor Rating, etc. Not visible in information_schema."
    },
    {
        "id": "SB-003",
        "query": "What are the objectives set for each employee? Show objective name, goal weighting, and status.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [Employee Objectives] struct. Inner fields: Objective Name, Goal Weighting, Goal Status, etc."
    },
    {
        "id": "SB-004",
        "query": "List all previous employers with company name, job title, start date, and end date for each employee.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [Employee Previous Employer] struct. Inner fields: Previous Employer Name, Previous Job Title, Start Date, End Date."
    },
    {
        "id": "SB-005",
        "query": "Show the assignment history for all employees: position title, grade, start date, end date, and experience duration.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [Employee Assignment History] struct. Inner fields: Assignment Name, Position Title, Employee Grade, Assignment Start/End Date, Experience."
    },
    {
        "id": "SB-006",
        "query": "What CV education records exist? Show institution name, degree, and end date for each employee.",
        "category": "struct_inner_field_blindness",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires UNNEST on [CV Employee Education] struct. Inner fields: CV Institute Name, CV Degree Name, CV End Date."
    },
    {
        "id": "SB-007",
        "query": "UNNEST all struct arrays in the dataset and show the total number of records in each struct type.",
        "category": "struct_inner_field_blindness",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires discovering and UNNESTing ALL struct columns. The ultimate test of struct field visibility."
    },
]

# ============================================================================
# CATEGORY 4: RETRIAL TRAP (Multi-turn degradation)
# These conversations start with queries that work, then progressively ask
# for columns that were filtered out in previous turns.
# ============================================================================

RETRIAL_TRAP_CONVERSATIONS = [
    {
        "id": "RT-001",
        "name": "Allowance escalation trap",
        "turns": [
            {
                "turn": 1,
                "query": "What is the Basic Salary for each employee?",
                "notes": "Easy — Basic Salary is a common column that the selector always includes."
            },
            {
                "turn": 2,
                "query": "Now add the Housing Allowance and Cost of Living Allowance to that list.",
                "notes": "Medium — these are less common but still flat columns."
            },
            {
                "turn": 3,
                "query": "Also include the Etihad Allowance and Secondment Allowance.",
                "notes": "Hard — these are the obscure columns that the selector typically omits."
            },
            {
                "turn": 4,
                "query": "Create a complete compensation breakdown with ALL allowance types including Special Contract Basic Salary.",
                "notes": "Extreme — requests every allowance column including ones that may not exist."
            },
        ]
    },
    {
        "id": "RT-002",
        "name": "Employee profile deep dive",
        "turns": [
            {
                "turn": 1,
                "query": "List all employees with their name, department, and job title.",
                "notes": "Easy — common flat columns."
            },
            {
                "turn": 2,
                "query": "Add their Date of Joining and Last Promotion Date.",
                "notes": "Medium — date columns that may be filtered."
            },
            {
                "turn": 3,
                "query": "Now add their Family Book Number and Number of Children.",
                "notes": "Hard — obscure demographic columns."
            },
        ]
    },
    {
        "id": "RT-003",
        "name": "Leave to competency pivot",
        "turns": [
            {
                "turn": 1,
                "query": "How many employees have taken sick leave?",
                "notes": "Easy — Sick Leave Taken is a flat column."
            },
            {
                "turn": 2,
                "query": "What are the detailed leave records? Show leave type, duration, and dates.",
                "notes": "Hard — requires UNNEST on Employee Leave Details struct."
            },
            {
                "turn": 3,
                "query": "For those employees, what are their competency ratings?",
                "notes": "Hard — requires switching to a different struct (Competencies Rating)."
            },
        ]
    },
    {
        "id": "RT-004",
        "name": "Career progression audit",
        "turns": [
            {
                "turn": 1,
                "query": "Show all employees and their current grade.",
                "notes": "Easy — Grade is a common flat column."
            },
            {
                "turn": 2,
                "query": "Which employees have been promoted? Show their Last Promotion Date.",
                "notes": "Medium — Last Promotion Date may be filtered."
            },
            {
                "turn": 3,
                "query": "Show their full assignment history with all position changes.",
                "notes": "Hard — requires UNNEST on Assignment History struct."
            },
            {
                "turn": 4,
                "query": "Cross-reference with their previous employer records to build a complete career timeline.",
                "notes": "Extreme — requires UNNEST on both Assignment History and Previous Employer structs."
            },
        ]
    },
]

# ============================================================================
# CATEGORY 5: COLUMN NAME COLLISION
# Queries where two different structs have similarly-named inner fields.
# ============================================================================

COLUMN_NAME_COLLISION = [
    {
        "id": "CC-001",
        "query": "Show the Start Date from Employee Assignment History and the Leave Start Date from Employee Leave Details for each employee. Are there any overlaps?",
        "category": "column_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Both structs have 'Start Date' inner fields. The selector must distinguish between [Employee Assignment History[...Assignment Start Date...]] and [Employee Leave Details[...Leave Start Date...]]."
    },
    {
        "id": "CC-002",
        "query": "Compare the Position Title from Assignment History with the Job Title from Employee Master. Are they always the same?",
        "category": "column_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two columns with similar semantic meaning but different sources. Selector must include both."
    },
    {
        "id": "CC-003",
        "query": "Show the Employee Grade from Employee Master and the Employee Grade from Assignment History. Do they match?",
        "category": "column_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Same field name 'Employee Grade' in two different locations. Selector must include both."
    },
    {
        "id": "CC-004",
        "query": "Compare the End Date from Previous Employer records with the Date of Joining from Employee Master. Is there a gap?",
        "category": "column_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "End Date (from Previous Employer struct) vs Date of Joining (from Employee Master flat column). Different names, same semantic concept."
    },
    {
        "id": "CC-005",
        "query": "Show the CV Job Title from CV Work Experience and the Previous Job Title from Previous Employer. Do they describe the same roles?",
        "category": "column_name_collision",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Two struct fields with similar names (CV Job Title vs Previous Job Title) from different structs. Selector must include both."
    },
    {
        "id": "CC-006",
        "query": "Compare the CV Degree Name from CV Education with the Degree from Employee Master. Are they consistent?",
        "category": "column_name_collision",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "CV Degree Name (struct inner field) vs Degree (flat column). Similar semantic meaning, different sources."
    },
]

# ============================================================================
# CATEGORY 6: BUDGET RATIO EDGE
# Queries that need exactly the budget_ratio boundary number of columns.
# With budget_ratio=0.10 and 104 columns, the selector gets ~10 column values.
# ============================================================================

BUDGET_RATIO_EDGE = [
    {
        "id": "BR-001",
        "query": "Show Employee Name, Email Address, Department, Sector, Job Title, Grade, Basic Salary, Total Entitlement Amount, Date of Joining, and Last Promotion Date for all employees.",
        "category": "budget_ratio_edge",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Exactly 10 flat columns requested. At budget_ratio=0.10, the selector should include all of them, but column value samples may be truncated."
    },
    {
        "id": "BR-002",
        "query": "For each employee, show: Name, Department, Grade, Basic Salary, Housing Allowance, Social Allowance, Cost of Living Allowance, Child Allowance, Technical Special Allowance, Phone Allowance, Supplementary Allowance, and Total Entitlement Amount.",
        "category": "budget_ratio_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "12 allowance columns requested. Exceeds the budget for column value samples. The selector must prioritize the most important ones."
    },
    {
        "id": "BR-003",
        "query": "Show me everything about Eisa Rames Khamis AlDhaheri: all personal details, all allowance components, all leave records, all competency ratings, all objectives, all qualifications, all previous employers, and all assignment history.",
        "category": "budget_ratio_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requests ALL columns for a single employee. The ultimate budget ratio stress test — the selector must decide which columns to include when the query asks for 'everything'."
    },
    {
        "id": "BR-004",
        "query": "Create a summary table with one row per employee and columns for: Name, Email, Department, Sector, Division, Nationality, Gender, Age, Degree, Grade, Basic Salary, Total Entitlement, Sick Leave Taken, Date of Joining, Employee Number, Job Title, Last Promotion Date, Number of Spouses, Number of Children, Family Book Number, Marital Status.",
        "category": "budget_ratio_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "21 flat columns explicitly listed. Far exceeds the budget. Tests whether the selector can handle explicit column enumeration."
    },
    {
        "id": "BR-005",
        "query": "What are the distinct values in each column of the Employee Master struct?",
        "category": "budget_ratio_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requests ALL distinct values from Employee Master. The selector must include every flat column in that struct."
    },
    {
        "id": "BR-006",
        "query": "Show the schema of the enterprise_data table including all column names, data types, and sample values.",
        "category": "budget_ratio_edge",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Meta-query about the schema itself. The selector must decide which columns to show when the query asks about 'all columns'."
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_adversarial_v2_single_turn_queries():
    """Get all single-turn queries from the v2 adversarial bank."""
    queries = []
    for category_list in [COLUMN_SELECTION_HANDOFF, SEMANTIC_MAPPING_GAP, 
                          STRUCT_INNER_FIELD_BLINDNESS, COLUMN_NAME_COLLISION,
                          BUDGET_RATIO_EDGE]:
        queries.extend(category_list)
    return queries


def get_all_adversarial_v2_multi_turn_conversations():
    """Get all multi-turn conversations from the v2 adversarial bank."""
    return RETRIAL_TRAP_CONVERSATIONS


def get_adversarial_v2_query_by_id(query_id):
    """Look up a specific query by its ID."""
    for q in get_all_adversarial_v2_single_turn_queries():
        if q["id"] == query_id:
            return q
    for conv in RETRIAL_TRAP_CONVERSATIONS:
        if conv["id"] == query_id:
            return conv
        for turn in conv["turns"]:
            turn_id = f"{conv['id']}_T{turn['turn']}"
            if turn_id == query_id:
                return {**turn, "id": turn_id, "conversation_id": conv["id"]}
    return None


def get_adversarial_v2_queries_by_category(category):
    """Get all queries in a specific category."""
    return [q for q in get_all_adversarial_v2_single_turn_queries() if q["category"] == category]


def get_adversarial_v2_queries_by_difficulty(difficulty):
    """Get all queries at a specific difficulty level."""
    return [q for q in get_all_adversarial_v2_single_turn_queries() if q["difficulty"] == difficulty]


def get_adversarial_v2_stats():
    """Get statistics about the v2 adversarial query bank."""
    single = get_all_adversarial_v2_single_turn_queries()
    multi = RETRIAL_TRAP_CONVERSATIONS
    total_turns = sum(len(c["turns"]) for c in multi)
    
    categories = {}
    for q in single:
        cat = q["category"]
        categories[cat] = categories.get(cat, 0) + 1
    categories["retrial_trap"] = len(multi)
    
    difficulties = {}
    for q in single:
        diff = q["difficulty"]
        difficulties[diff] = difficulties.get(diff, 0) + 1
    
    return {
        "total_single_turn": len(single),
        "total_multi_turn_conversations": len(multi),
        "total_multi_turn_turns": total_turns,
        "total_queries": len(single) + total_turns,
        "categories": categories,
        "difficulty": difficulties,
    }


if __name__ == "__main__":
    import json
    stats = get_adversarial_v2_stats()
    print(json.dumps(stats, indent=2))
