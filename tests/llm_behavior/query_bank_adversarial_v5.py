"""
Adversarial Query Bank v5 — Column Selection Memory Isolation Tests
====================================================================

Tests the fix for the column selection memory leak bug:

  **Problem**: In multi-turn conversations with column selection enabled,
  Step 2 (code generation) could see previous turns' conversation history
  and `last_code_generated`, which contained column references from a
  DIFFERENT column selection. The LLM would copy those old column names
  into the new code, referencing columns not in the current trimmed set.

  **Fix**: Step 2 now runs with an isolated empty Memory and
  `last_code_generated=None`. Step 2's messages are merged back into
  the original memory in `finally` so Step 1 retains full context.

This bank targets the exact failure mode: **multi-turn conversations where
successive queries select DIFFERENT columns, and the LLM must NOT reference
columns from a previous turn's selection.**

Test Design
-----------
Each test is a **multi-turn conversation** — a sequence of queries sent via
`follow_up()` where:

1. Turn 1 selects columns from domain A (e.g., salary/compensation)
2. Turn 2 selects columns from domain B (e.g., leave details)
3. The generated code on Turn 2 must ONLY use columns from domain B

The key assertion: **Turn N's generated code must not reference any column
that is not in Turn N's trimmed column set.**

Categories
----------
1. CROSS_DOMAIN_LEAK: Successive queries target completely different domains.
   The most likely leak vector — previous code references columns the LLM
   might copy.

2. OVERLAPPING_DOMAIN_LEAK: Successive queries share some columns but differ
   in others. Tests if the LLM can correctly use the intersection without
   adding columns from the previous turn that aren't in the current selection.

3. NARROW_THEN_WIDE: First query selects few columns, second selects many.
   The leak risk is lower but the "Last code generated" from the narrow
   query might constrain the LLM's approach.

4. WIDE_THEN_NARROW: First query selects many columns, second selects few.
   HIGH leak risk — previous code references columns not in the current
   trimmed set. This is the exact scenario the fix addresses.

5. THREE_TURN_CASCADE: Three successive queries, each selecting different
   columns. Tests that the isolation works across multiple follow-ups.

6. SAME_DOMAIN_REFINEMENT: Queries about the same domain but with different
   granularity. Tests that the LLM correctly narrows/expands without
   hallucinating columns from the previous turn.
"""

# ============================================================================
# CATEGORY 1: CROSS-DOMAIN LEAK
# Each turn targets a completely different part of the schema.
# The LLM must not carry over column references from the previous turn.
# ============================================================================

CROSS_DOMAIN_LEAK = [
    {
        "id": "CD-001",
        "conversation": [
            {
                "turn": 1,
                "query": "What is the average basic salary across all employees?",
                "expected_columns": ["Employee Name", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Leave Duration (Days)", "Assignment Name"],
            },
            {
                "turn": 2,
                "query": "What types of leave did Ayesha take?",
                "expected_columns": ["Employee Name", "Leave Type"],
                "forbidden_columns": ["Basic Salary", "Department", "Job Title"],
            },
        ],
        "category": "cross_domain_leak",
        "difficulty": "hard",
        "notes": "Turn 1 uses salary columns, Turn 2 uses leave columns. The LLM must NOT reference Basic Salary in Turn 2's code.",
    },
    {
        "id": "CD-002",
        "conversation": [
            {
                "turn": 1,
                "query": "How many employees are in each department?",
                "expected_columns": ["Employee Name", "Department"],
                "forbidden_columns": ["Leave Type", "Basic Salary", "GPA (Grade Point Average)"],
            },
            {
                "turn": 2,
                "query": "What qualifications does Ahmed have? Show the qualification title.",
                "expected_columns": ["Employee Name", "Qualification Title"],
                "forbidden_columns": ["Department", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "cross_domain_leak",
        "difficulty": "hard",
        "notes": "Turn 1: department headcount. Turn 2: qualifications. Completely different domains.",
    },
    {
        "id": "CD-003",
        "conversation": [
            {
                "turn": 1,
                "query": "List all employees and their email addresses.",
                "expected_columns": ["Employee Name", "Email Address"],
                "forbidden_columns": ["Basic Salary", "Leave Type", "Assignment Name"],
            },
            {
                "turn": 2,
                "query": "What is the total leave duration in days for each employee?",
                "expected_columns": ["Employee Name", "Leave Duration (Days)"],
                "forbidden_columns": ["Email Address", "Basic Salary", "Department"],
            },
        ],
        "category": "cross_domain_leak",
        "difficulty": "hard",
        "notes": "Turn 1: email addresses. Turn 2: leave durations. No overlap in selected columns.",
    },
    {
        "id": "CD-004",
        "conversation": [
            {
                "turn": 1,
                "query": "What are the different assignment names for Ali?",
                "expected_columns": ["Employee Name", "Assignment Name"],
                "forbidden_columns": ["Basic Salary", "Leave Type", "Email Address"],
            },
            {
                "turn": 2,
                "query": "What is the average total entitlement amount by sector?",
                "expected_columns": ["Sector", "Total Entitlement Amount"],
                "forbidden_columns": ["Assignment Name", "Leave Type", "Qualification Title"],
            },
        ],
        "category": "cross_domain_leak",
        "difficulty": "hard",
        "notes": "Turn 1: assignment history. Turn 2: compensation by sector. Completely different.",
    },
]

# ============================================================================
# CATEGORY 2: OVERLAPPING DOMAIN LEAK
# Successive queries share some columns but differ in others.
# The LLM must only use the current trimmed set, not the previous one.
# ============================================================================

OVERLAPPING_DOMAIN_LEAK = [
    {
        "id": "OD-001",
        "conversation": [
            {
                "turn": 1,
                "query": "List all employees with their department and job title.",
                "expected_columns": ["Employee Name", "Department", "Job Title"],
                "forbidden_columns": ["Basic Salary", "Leave Type"],
            },
            {
                "turn": 2,
                "query": "What is the headcount by department only?",
                "expected_columns": ["Employee Name", "Department"],
                "forbidden_columns": ["Job Title", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "overlapping_domain_leak",
        "difficulty": "medium",
        "notes": "Turn 2 drops Job Title. The LLM must not reference Job Title even though it was in Turn 1.",
    },
    {
        "id": "OD-002",
        "conversation": [
            {
                "turn": 1,
                "query": "Show Ayesha's leave types and their approval status.",
                "expected_columns": ["Employee Name", "Leave Type", "Approval Status"],
                "forbidden_columns": ["Basic Salary", "Department"],
            },
            {
                "turn": 2,
                "query": "What is the total leave duration in days for Ayesha by leave type?",
                "expected_columns": ["Employee Name", "Leave Type", "Leave Duration (Days)"],
                "forbidden_columns": ["Approval Status", "Basic Salary"],
            },
        ],
        "category": "overlapping_domain_leak",
        "difficulty": "hard",
        "notes": "Both turns use Leave Type, but Turn 2 drops Approval Status and adds Leave Duration. The LLM must not reference Approval Status from Turn 1.",
    },
    {
        "id": "OD-003",
        "conversation": [
            {
                "turn": 1,
                "query": "Show each employee's name, department, and basic salary.",
                "expected_columns": ["Employee Name", "Department", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Total Entitlement Amount"],
            },
            {
                "turn": 2,
                "query": "What is the total entitlement amount for each employee?",
                "expected_columns": ["Employee Name", "Total Entitlement Amount"],
                "forbidden_columns": ["Department", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "overlapping_domain_leak",
        "difficulty": "hard",
        "notes": "Turn 1: name + dept + salary. Turn 2: name + total entitlement. Turn 2 must not reference Department or Basic Salary even though both are compensation-related.",
    },
]

# ============================================================================
# CATEGORY 3: NARROW THEN WIDE
# First query selects few columns, second selects many.
# Lower leak risk but tests that isolation doesn't break expansion.
# ============================================================================

NARROW_THEN_WIDE = [
    {
        "id": "NW-001",
        "conversation": [
            {
                "turn": 1,
                "query": "How many employees are there?",
                "expected_columns": ["Employee Name"],
                "forbidden_columns": ["Basic Salary", "Leave Type", "Department"],
            },
            {
                "turn": 2,
                "query": "Show each employee's name, department, sector, and job title.",
                "expected_columns": ["Employee Name", "Department", "Sector", "Job Title"],
                "forbidden_columns": ["Basic Salary", "Leave Type"],
            },
        ],
        "category": "narrow_then_wide",
        "difficulty": "medium",
        "notes": "Turn 1 is trivially narrow (just count). Turn 2 expands. The LLM must use all 4 columns in Turn 2 without being constrained by Turn 1's narrow scope.",
    },
    {
        "id": "NW-002",
        "conversation": [
            {
                "turn": 1,
                "query": "What is Ayesha's email address?",
                "expected_columns": ["Employee Name", "Email Address"],
                "forbidden_columns": ["Department", "Basic Salary", "Leave Type"],
            },
            {
                "turn": 2,
                "query": "Show Ayesha's full profile: name, department, sector, job title, and basic salary.",
                "expected_columns": ["Employee Name", "Department", "Sector", "Job Title", "Basic Salary"],
                "forbidden_columns": ["Email Address", "Leave Type"],
            },
        ],
        "category": "narrow_then_wide",
        "difficulty": "medium",
        "notes": "Turn 1: just email. Turn 2: full profile. Tests that isolation doesn't prevent the LLM from using a wider column set.",
    },
]

# ============================================================================
# CATEGORY 4: WIDE THEN NARROW
# First query selects many columns, second selects few.
# THIS IS THE PRIMARY LEAK SCENARIO the fix addresses.
# ============================================================================

WIDE_THEN_NARROW = [
    {
        "id": "WN-001",
        "conversation": [
            {
                "turn": 1,
                "query": "Show each employee's name, department, sector, job title, and basic salary.",
                "expected_columns": ["Employee Name", "Department", "Sector", "Job Title", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Email Address"],
            },
            {
                "turn": 2,
                "query": "What is Ayesha's email address?",
                "expected_columns": ["Employee Name", "Email Address"],
                "forbidden_columns": ["Department", "Sector", "Job Title", "Basic Salary"],
            },
        ],
        "category": "wide_then_narrow",
        "difficulty": "hard",
        "notes": "PRIMARY LEAK TEST. Turn 1 uses 5 columns including Department/Sector/Job Title/Basic Salary. Turn 2 only needs Email Address. Without the fix, the LLM might reference Department or Basic Salary from Turn 1's code.",
    },
    {
        "id": "WN-002",
        "conversation": [
            {
                "turn": 1,
                "query": "Show all leave details: employee name, leave type, approval status, start date, end date, and duration.",
                "expected_columns": ["Employee Name", "Leave Type", "Approval Status", "Leave Start Date", "Leave End Date", "Leave Duration (Days)"],
                "forbidden_columns": ["Basic Salary", "Department"],
            },
            {
                "turn": 2,
                "query": "How many employees are in each department?",
                "expected_columns": ["Employee Name", "Department"],
                "forbidden_columns": ["Leave Type", "Approval Status", "Leave Duration (Days)", "Basic Salary"],
            },
        ],
        "category": "wide_then_narrow",
        "difficulty": "hard",
        "notes": "Turn 1: full leave details (6 columns). Turn 2: just department headcount. Without the fix, the LLM might reference Leave Type or Approval Status from Turn 1's code.",
    },
    {
        "id": "WN-003",
        "conversation": [
            {
                "turn": 1,
                "query": "Show each employee with their name, gender, nationality, department, sector, division, job title, and basic salary.",
                "expected_columns": ["Employee Name", "Gender", "Nationality", "Department", "Sector", "Division", "Job Title", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Email Address"],
            },
            {
                "turn": 2,
                "query": "What is the gender ratio across the organization?",
                "expected_columns": ["Employee Name", "Gender"],
                "forbidden_columns": ["Nationality", "Department", "Sector", "Division", "Job Title", "Basic Salary"],
            },
        ],
        "category": "wide_then_narrow",
        "difficulty": "hard",
        "notes": "Turn 1: 8-column wide profile. Turn 2: just gender count. Maximum leak risk — 6 columns from Turn 1 are NOT in Turn 2's selection.",
    },
    {
        "id": "WN-004",
        "conversation": [
            {
                "turn": 1,
                "query": "List all employees with their assignment name, position title, and assignment start date.",
                "expected_columns": ["Employee Name", "Assignment Name", "Position Title", "Assignment Start Date"],
                "forbidden_columns": ["Basic Salary", "Leave Type", "Email Address"],
            },
            {
                "turn": 2,
                "query": "What is the average basic salary?",
                "expected_columns": ["Basic Salary"],
                "forbidden_columns": ["Assignment Name", "Position Title", "Assignment Start Date"],
            },
        ],
        "category": "wide_then_narrow",
        "difficulty": "hard",
        "notes": "Turn 1: assignment history (4 columns). Turn 2: just salary average. Zero overlap in selected columns — maximum leak potential.",
    },
]

# ============================================================================
# CATEGORY 5: THREE-TURN CASCADE
# Three successive queries, each selecting different columns.
# Tests that isolation works across multiple follow-ups.
# ============================================================================

THREE_TURN_CASCADE = [
    {
        "id": "TC-001",
        "conversation": [
            {
                "turn": 1,
                "query": "What is the average basic salary by department?",
                "expected_columns": ["Department", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Email Address", "Assignment Name"],
            },
            {
                "turn": 2,
                "query": "What types of leave did Ayesha take?",
                "expected_columns": ["Employee Name", "Leave Type"],
                "forbidden_columns": ["Department", "Basic Salary", "Assignment Name"],
            },
            {
                "turn": 3,
                "query": "What are the different assignment names for Ali?",
                "expected_columns": ["Employee Name", "Assignment Name"],
                "forbidden_columns": ["Department", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "three_turn_cascade",
        "difficulty": "hard",
        "notes": "Three turns, each from a different domain: salary → leave → assignments. Each turn must only use its own domain's columns.",
    },
    {
        "id": "TC-002",
        "conversation": [
            {
                "turn": 1,
                "query": "How many male and female employees are there?",
                "expected_columns": ["Employee Name", "Gender"],
                "forbidden_columns": ["Basic Salary", "Leave Type", "Department"],
            },
            {
                "turn": 2,
                "query": "What is the total entitlement amount for each employee?",
                "expected_columns": ["Employee Name", "Total Entitlement Amount"],
                "forbidden_columns": ["Gender", "Leave Type", "Department"],
            },
            {
                "turn": 3,
                "query": "List all employees in the Economic Affairs sector.",
                "expected_columns": ["Employee Name", "Sector"],
                "forbidden_columns": ["Gender", "Total Entitlement Amount", "Leave Type"],
            },
        ],
        "category": "three_turn_cascade",
        "difficulty": "hard",
        "notes": "Gender count → compensation → sector filter. Each turn uses completely different columns.",
    },
    {
        "id": "TC-003",
        "conversation": [
            {
                "turn": 1,
                "query": "Show Ayesha's full profile: name, department, job title, and basic salary.",
                "expected_columns": ["Employee Name", "Department", "Job Title", "Basic Salary"],
                "forbidden_columns": ["Leave Type", "Email Address"],
            },
            {
                "turn": 2,
                "query": "What types of leave did Ayesha take?",
                "expected_columns": ["Employee Name", "Leave Type"],
                "forbidden_columns": ["Department", "Job Title", "Basic Salary"],
            },
            {
                "turn": 3,
                "query": "What is Ayesha's email address?",
                "expected_columns": ["Employee Name", "Email Address"],
                "forbidden_columns": ["Department", "Job Title", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "three_turn_cascade",
        "difficulty": "hard",
        "notes": "Same person (Ayesha) across 3 turns with different column domains. Tests that isolation works even when the entity is the same.",
    },
]

# ============================================================================
# CATEGORY 6: SAME-DOMAIN REFINEMENT
# Queries about the same domain but with different granularity.
# Tests that the LLM correctly narrows/expands without hallucinating.
# ============================================================================

SAME_DOMAIN_REFINEMENT = [
    {
        "id": "SD-001",
        "conversation": [
            {
                "turn": 1,
                "query": "Show all compensation details: basic salary, housing allowance, and total entitlement.",
                "expected_columns": ["Employee Name", "Basic Salary", "Housing Allowance", "Total Entitlement Amount"],
                "forbidden_columns": ["Leave Type", "Department"],
            },
            {
                "turn": 2,
                "query": "What is the average basic salary only?",
                "expected_columns": ["Basic Salary"],
                "forbidden_columns": ["Housing Allowance", "Total Entitlement Amount", "Leave Type"],
            },
        ],
        "category": "same_domain_refinement",
        "difficulty": "medium",
        "notes": "Both turns are about compensation, but Turn 2 narrows to just Basic Salary. The LLM must not reference Housing Allowance or Total Entitlement even though they're in the same domain.",
    },
    {
        "id": "SD-002",
        "conversation": [
            {
                "turn": 1,
                "query": "Show leave type and duration for Ayesha.",
                "expected_columns": ["Employee Name", "Leave Type", "Leave Duration (Days)"],
                "forbidden_columns": ["Approval Status", "Basic Salary"],
            },
            {
                "turn": 2,
                "query": "What is the approval status of Ayesha's leaves?",
                "expected_columns": ["Employee Name", "Leave Type", "Approval Status"],
                "forbidden_columns": ["Leave Duration (Days)", "Basic Salary"],
            },
        ],
        "category": "same_domain_refinement",
        "difficulty": "hard",
        "notes": "Both about Ayesha's leaves. Turn 1: type + duration. Turn 2: type + approval. The LLM must not reference Leave Duration in Turn 2 even though it was just used in Turn 1.",
    },
    {
        "id": "SD-003",
        "conversation": [
            {
                "turn": 1,
                "query": "List all employees with their sector and division.",
                "expected_columns": ["Employee Name", "Sector", "Division"],
                "forbidden_columns": ["Department", "Basic Salary", "Leave Type"],
            },
            {
                "turn": 2,
                "query": "Show employees by department instead.",
                "expected_columns": ["Employee Name", "Department"],
                "forbidden_columns": ["Sector", "Division", "Basic Salary", "Leave Type"],
            },
        ],
        "category": "same_domain_refinement",
        "difficulty": "medium",
        "notes": "Both about org structure. Turn 1: sector + division. Turn 2: department only. The LLM must not reference Sector/Division in Turn 2.",
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_all_adversarial_v5_conversations():
    """Return all multi-turn conversations from the v5 adversarial bank."""
    conversations = []
    for category in [CROSS_DOMAIN_LEAK, OVERLAPPING_DOMAIN_LEAK,
                     NARROW_THEN_WIDE, WIDE_THEN_NARROW,
                     THREE_TURN_CASCADE, SAME_DOMAIN_REFINEMENT]:
        conversations.extend(category)
    return conversations


def get_adversarial_v5_by_id(conv_id: str):
    """Get a specific conversation by its ID."""
    for conv in get_all_adversarial_v5_conversations():
        if conv["id"] == conv_id:
            return conv
    return None


def get_adversarial_v5_by_category(category: str):
    """Get all conversations in a specific category."""
    return [c for c in get_all_adversarial_v5_conversations() if c.get("category") == category]


def get_adversarial_v5_stats():
    """Return statistics about the v5 adversarial query bank."""
    conversations = get_all_adversarial_v5_conversations()
    total_turns = sum(len(c["conversation"]) for c in conversations)

    categories = {}
    for c in conversations:
        cat = c.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total_conversations": len(conversations),
        "total_turns": total_turns,
        "categories": categories,
    }
