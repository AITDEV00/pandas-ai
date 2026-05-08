"""
Query Bank for E2E LLM Behavior Testing
=========================================

Organized by:
  - Turn type: single_turn vs multi_turn
  - Complexity: simple vs complex
  - Category: the data domain the query targets

All queries are grounded in the actual data from `full data unflattened.xlsx`:
  - 16 employees, all Emirati
  - 6 Male, 10 Female
  - Sectors: Economic Affairs, Wellbeing, Infrastructure & Sustainability
  - Divisions: Chairman, Operational Affairs
  - Departments: 8 departments across sectors
  - Struct columns: Leave Details, Competencies, Objectives, Qualifications, etc.
  - Key names: Ayesha, Afra, Noura, Sara, Shamma, Eisa, Ali, Salem, etc.
"""

# ──────────────────────────────────────────────────────────────────────────────
# SINGLE-TURN QUERIES
# ──────────────────────────────────────────────────────────────────────────────

SINGLE_TURN_SIMPLE = [
    # ── Basic count / existence ───────────────────────────────────────────
    {
        "id": "SS-001",
        "query": "How many employees are there?",
        "category": "count",
        "expected_output_type": "number",
        "difficulty": "trivial",
        "notes": "Simple COUNT(*) on the table",
    },
    {
        "id": "SS-002",
        "query": "How many female employees are there?",
        "category": "count_filter",
        "expected_output_type": "number",
        "difficulty": "trivial",
        "notes": "COUNT with WHERE gender = Female",
    },
    {
        "id": "SS-003",
        "query": "How many male employees are there?",
        "category": "count_filter",
        "expected_output_type": "number",
        "difficulty": "trivial",
        "notes": "COUNT with WHERE gender = Male",
    },
    # ── Simple lookup ─────────────────────────────────────────────────────
    {
        "id": "SS-004",
        "query": "What is Ayesha's job title?",
        "category": "lookup",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "Simple WHERE name LIKE '%Ayesha%'",
    },
    {
        "id": "SS-005",
        "query": "Which department does Afra work in?",
        "category": "lookup",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "WHERE name LIKE '%Afra%' → department",
    },
    {
        "id": "SS-006",
        "query": "What is the nationality of all employees?",
        "category": "lookup",
        "expected_output_type": "string",
        "difficulty": "trivial",
        "notes": "All are Emirati — simple DISTINCT",
    },
    # ── Simple aggregation ────────────────────────────────────────────────
    {
        "id": "SS-007",
        "query": "What is the average age of all employees?",
        "category": "aggregation",
        "expected_output_type": "number",
        "difficulty": "easy",
        "notes": "AVG(age)",
    },
    {
        "id": "SS-008",
        "query": "What is the total basic salary paid across all employees?",
        "category": "aggregation",
        "expected_output_type": "number",
        "difficulty": "easy",
        "notes": "SUM(basic_salary)",
    },
    {
        "id": "SS-009",
        "query": "List all the sectors in the organization.",
        "category": "distinct",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "DISTINCT sector",
    },
    {
        "id": "SS-010",
        "query": "Who is the supervisor of Noura?",
        "category": "lookup",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "WHERE name LIKE '%Noura%' → supervisor_name",
    },
]

SINGLE_TURN_COMPLEX = [
    # ── Grouped aggregation ───────────────────────────────────────────────
    {
        "id": "SC-001",
        "query": "How many employees are in each sector? Give me a breakdown.",
        "category": "grouped_count",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "GROUP BY sector, COUNT(*)",
    },
    {
        "id": "SC-002",
        "query": "What is the average basic salary by gender?",
        "category": "grouped_aggregation",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "GROUP BY gender, AVG(salary)",
    },
    {
        "id": "SC-003",
        "query": "How many employees work in each department?",
        "category": "grouped_count",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "GROUP BY department, COUNT(*)",
    },
    # ── Struct / nested column queries ────────────────────────────────────
    {
        "id": "SC-004",
        "query": "what is the percentage by different leave types did ayesha take?",
        "category": "struct_query",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Requires unnesting Leave Details struct, filtering by name, then computing percentages per leave type. This is the exact production query that caused NoCodeFoundError.",
    },
    {
        "id": "SC-005",
        "query": "What are the different leave types taken by employees and how many days for each type?",
        "category": "struct_query",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Unnest Leave Details, GROUP BY leave_type, SUM(duration)",
    },
    {
        "id": "SC-006",
        "query": "List all competencies where the supervisor rating is higher than the employee rating for Sara Alharbi.",
        "category": "struct_query",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Unnest Competencies Rating struct, compare ratings",
    },
    # ── Multi-condition filter ────────────────────────────────────────────
    {
        "id": "SC-007",
        "query": "Which female employees are in the Wellbeing Sector and have a basic salary above 30000?",
        "category": "multi_filter",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "WHERE gender=Female AND sector=Wellbeing AND salary>30000",
    },
    {
        "id": "SC-008",
        "query": "Find employees who have a PhD degree and work in the Operational Affairs Division.",
        "category": "multi_filter",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "WHERE degree contains PhD AND division=Operational Affairs",
    },
    # ── Computed / derived ────────────────────────────────────────────────
    {
        "id": "SC-009",
        "query": "What is the ratio of male to female employees?",
        "category": "computed",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "Two COUNT queries + ratio computation in Python",
    },
    {
        "id": "SC-010",
        "query": "What percentage of the total entitlement amount is the basic salary for each employee?",
        "category": "computed",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "basic_salary / total_entitlement * 100 per employee",
    },
    # ── Leave-specific complex ────────────────────────────────────────────
    {
        "id": "SC-011",
        "query": "How many total leave days has each employee taken? Show the top 5.",
        "category": "struct_aggregation",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Unnest Leave Details, SUM(duration) per employee, ORDER BY DESC, LIMIT 5",
    },
    {
        "id": "SC-012",
        "query": "Are there any denied leave requests? If so, who and what type?",
        "category": "struct_filter",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "Unnest Leave Details, WHERE approval_status != Approved",
    },
    # ── Cross-struct ──────────────────────────────────────────────────────
    {
        "id": "SC-013",
        "query": "Which employees have both CV achievements and previous employer records?",
        "category": "cross_struct",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Requires checking two different struct columns are non-empty",
    },
    {
        "id": "SC-014",
        "query": "What is the average ADEO experience (in years) for employees in each sector?",
        "category": "grouped_aggregation",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "GROUP BY sector, AVG(adeo_experience)",
    },
    # ── Ambiguous / edge-case ─────────────────────────────────────────────
    {
        "id": "SC-015",
        "query": "Who are the most experienced employees in the organization?",
        "category": "ambiguous",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "Ambiguous: experience by years? by assignments? Tests LLM interpretation",
    },
    {
        "id": "SC-016",
        "query": "Show me a summary of the employee data.",
        "category": "ambiguous",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "Very open-ended — tests how LLM handles vague queries",
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# MULTI-TURN QUERIES
# ──────────────────────────────────────────────────────────────────────────────

MULTI_TURN_CONVERSATIONS = [
    # ── Conversation 1: Progressive drill-down on Ayesha ──────────────────
    {
        "id": "MT-001",
        "name": "Ayesha drill-down",
        "turns": [
            {
                "query": "Find the employee named Ayesha.",
                "expected_output_type": "string",
                "notes": "Simple lookup — establishes context",
            },
            {
                "query": "What is her job title and department?",
                "expected_output_type": "string",
                "notes": "Follow-up uses pronoun 'her' — tests anaphora resolution",
            },
            {
                "query": "What percentage by different leave types did she take?",
                "expected_output_type": "string",
                "notes": "Complex struct query with pronoun — exact production scenario",
            },
        ],
    },
    # ── Conversation 2: Sector comparison ─────────────────────────────────
    {
        "id": "MT-002",
        "name": "Sector comparison",
        "turns": [
            {
                "query": "List all the sectors and how many employees in each.",
                "expected_output_type": "string",
                "notes": "GROUP BY sector — establishes sector context",
            },
            {
                "query": "Which sector has the highest average salary?",
                "expected_output_type": "string",
                "notes": "Follow-up aggregation on sectors from previous turn",
            },
            {
                "query": "Who are the employees in that sector?",
                "expected_output_type": "string",
                "notes": "Pronoun 'that sector' — tests context carry-over",
            },
        ],
    },
    # ── Conversation 3: Leave analysis progression ────────────────────────
    {
        "id": "MT-003",
        "name": "Leave analysis",
        "turns": [
            {
                "query": "How many employees have taken leave?",
                "expected_output_type": "string",
                "notes": "Simple count with struct check",
            },
            {
                "query": "What are the different leave types available?",
                "expected_output_type": "string",
                "notes": "Follow-up: DISTINCT leave types from struct",
            },
            {
                "query": "Which employee has taken the most wellbeing leave days?",
                "expected_output_type": "string",
                "notes": "Specific struct aggregation — requires filtering by leave type and summing",
            },
        ],
    },
    # ── Conversation 4: Salary & compensation ─────────────────────────────
    {
        "id": "MT-004",
        "name": "Salary & compensation",
        "turns": [
            {
                "query": "What is the average total entitlement amount?",
                "expected_output_type": "number",
                "notes": "Simple AVG",
            },
            {
                "query": "How does it differ between male and female employees?",
                "expected_output_type": "string",
                "notes": "Follow-up: GROUP BY gender comparison",
            },
            {
                "query": "Which employee has the highest total entitlement?",
                "expected_output_type": "string",
                "notes": "ORDER BY DESC LIMIT 1",
            },
        ],
    },
    # ── Conversation 5: Competency deep-dive ──────────────────────────────
    {
        "id": "MT-005",
        "name": "Competency analysis",
        "turns": [
            {
                "query": "What competencies are evaluated for employees?",
                "expected_output_type": "string",
                "notes": "DISTINCT competency names from struct",
            },
            {
                "query": "For the competency 'Digital Savviness', what is the average employee rating?",
                "expected_output_type": "string",
                "notes": "Filter struct by competency name, AVG rating",
            },
            {
                "query": "Are there any employees where the supervisor rated them lower than they rated themselves for Digital Savviness?",
                "expected_output_type": "string",
                "notes": "Complex struct comparison — tests LLM's ability to compare nested fields",
            },
        ],
    },
    # ── Conversation 6: Career progression ────────────────────────────────
    {
        "id": "MT-006",
        "name": "Career progression",
        "turns": [
            {
                "query": "Which employees have been promoted recently?",
                "expected_output_type": "string",
                "notes": "Check last_promotion_date — some have it, some don't",
            },
            {
                "query": "What was the reason for their promotion?",
                "expected_output_type": "string",
                "notes": "Follow-up: last_promotion_reason",
            },
            {
                "query": "How long has it been since the last promotion for each promoted employee?",
                "expected_output_type": "string",
                "notes": "time_since_last_promotion column",
            },
        ],
    },
    # ── Conversation 7: Education & qualifications ────────────────────────
    {
        "id": "MT-007",
        "name": "Education & qualifications",
        "turns": [
            {
                "query": "What is the most common degree among employees?",
                "expected_output_type": "string",
                "notes": "GROUP BY degree, COUNT, ORDER BY DESC",
            },
            {
                "query": "Which employees have a Master's degree or higher?",
                "expected_output_type": "string",
                "notes": "Filter by degree containing Master or PhD",
            },
            {
                "query": "What qualifications do they hold? List the qualification titles.",
                "expected_output_type": "string",
                "notes": "Unnest Employee Qualification struct for those employees",
            },
        ],
    },
    # ── Conversation 8: Stress test — long conversation ───────────────────
    {
        "id": "MT-008",
        "name": "Long conversation stress test",
        "turns": [
            {
                "query": "Give me an overview of the organization's workforce.",
                "expected_output_type": "string",
                "notes": "Open-ended — builds broad context",
            },
            {
                "query": "How is the gender distribution?",
                "expected_output_type": "string",
                "notes": "Follow-up on context",
            },
            {
                "query": "What about the age distribution?",
                "expected_output_type": "string",
                "notes": "Another follow-up",
            },
            {
                "query": "Which department has the most employees?",
                "expected_output_type": "string",
                "notes": "Shift to department focus",
            },
            {
                "query": "Who is the highest paid employee in that department?",
                "expected_output_type": "string",
                "notes": "Pronoun 'that department' — tests long-range anaphora",
            },
        ],
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# EDGE CASE QUERIES
# ──────────────────────────────────────────────────────────────────────────────

EDGE_CASE_QUERIES = [
    {
        "id": "EC-001",
        "query": "How many employees named John are there?",
        "category": "no_result",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "No employee named John — tests graceful handling of empty results",
    },
    {
        "id": "EC-002",
        "query": "What is the salary of employee number 99999?",
        "category": "no_result",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "Non-existent employee number — tests error handling",
    },
    {
        "id": "EC-003",
        "query": "Show me all the data in the table.",
        "category": "full_scan",
        "expected_output_type": "string",
        "difficulty": "easy",
        "notes": "SELECT * — may hit token limits, tests truncation",
    },
    {
        "id": "EC-004",
        "query": "Calculate the median salary and explain what median means.",
        "category": "explanation",
        "expected_output_type": "string",
        "difficulty": "medium",
        "notes": "Tests if LLM adds explanatory text before/after code — potential NoCodeFoundError trigger",
    },
    {
        "id": "EC-005",
        "query": "What is 2+2?",
        "category": "off_topic",
        "expected_output_type": "string",
        "difficulty": "trivial",
        "notes": "Off-topic query — tests if LLM stays in data context or goes off-rails",
    },
    {
        "id": "EC-006",
        "query": "Compare the total leave days taken vs. the leave entitlement for each employee.",
        "category": "cross_struct_comparison",
        "expected_output_type": "string",
        "difficulty": "hard",
        "notes": "Requires comparing struct data (leave details) with flat columns (entitlement leaves)",
    },
]


def get_all_single_turn_queries():
    """Return all single-turn queries combined."""
    return SINGLE_TURN_SIMPLE + SINGLE_TURN_COMPLEX + EDGE_CASE_QUERIES


def get_all_multi_turn_conversations():
    """Return all multi-turn conversations."""
    return MULTI_TURN_CONVERSATIONS


def get_query_by_id(query_id: str):
    """Look up a specific query or conversation by ID."""
    for q in get_all_single_turn_queries():
        if q["id"] == query_id:
            return q
    for conv in get_all_multi_turn_conversations():
        if conv["id"] == query_id:
            return conv
    return None


def get_queries_by_category(category: str):
    """Filter single-turn queries by category."""
    return [q for q in get_all_single_turn_queries() if q.get("category") == category]


def get_queries_by_difficulty(difficulty: str):
    """Filter single-turn queries by difficulty."""
    return [q for q in get_all_single_turn_queries() if q.get("difficulty") == difficulty]


if __name__ == "__main__":
    print("Query Bank Summary")
    print("=" * 50)
    print(f"\nSingle-turn simple:  {len(SINGLE_TURN_SIMPLE)}")
    print(f"Single-turn complex: {len(SINGLE_TURN_COMPLEX)}")
    print(f"Edge cases:          {len(EDGE_CASE_QUERIES)}")
    print(f"Multi-turn convos:   {len(MULTI_TURN_CONVERSATIONS)}")
    
    total_single = len(SINGLE_TURN_SIMPLE) + len(SINGLE_TURN_COMPLEX) + len(EDGE_CASE_QUERIES)
    total_multi_turns = sum(len(c["turns"]) for c in MULTI_TURN_CONVERSATIONS)
    print(f"\nTotal single-turn queries: {total_single}")
    print(f"Total multi-turn queries:  {total_multi_turns}")
    print(f"Grand total queries:       {total_single + total_multi_turns}")
    
    print("\n--- Categories ---")
    categories = set()
    for q in get_all_single_turn_queries():
        categories.add(q.get("category", "uncategorized"))
    for cat in sorted(categories):
        count = len(get_queries_by_category(cat))
        print(f"  {cat}: {count}")
    
    print("\n--- Multi-turn conversations ---")
    for conv in MULTI_TURN_CONVERSATIONS:
        print(f"  {conv['id']}: {conv['name']} ({len(conv['turns'])} turns)")
