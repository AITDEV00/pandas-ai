"""
Adversarial Query Bank — Column Selection Stress Testing
=========================================================

Designed to break the LLM when `column_selection_enabled: true` with
`column_selection_threshold: 30` and `column_values_budget_ratio: 0.10`.

Attack Vectors:
1. COLUMN_OMISSION: Queries needing obscure columns the LLM might not select
2. CROSS_STRUCT_DEEP: Queries requiring columns from 5+ different structs
3. AMBIGUOUS_REF: Queries with column names that are similar or overlapping
4. IMPLICIT_DEP: Queries where intermediate columns are needed but not obvious
5. MULTI_STRUCT_UNNEST: Queries requiring UNNEST on multiple struct arrays
6. NEGATION_EDGE: Negative/absence queries that need full scans
7. COMPOUND_AGGREGATION: Multi-level aggregations across struct boundaries
8. TEMPORAL_CROSS: Time-based queries spanning assignment history + leave + promotions
"""

from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 1: COLUMN_OMISSION — Obscure columns the LLM might skip
# ═══════════════════════════════════════════════════════════════════════════

COLUMN_OMISSION = [
    {
        "id": "CO-001",
        "query": "What is the Etihad Allowance for each employee, and how does it compare to their Secondment Allowance?",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Etihad Allowance]] and [Employee Master[Secondment Allowance]] — both obscure allowance columns the LLM might skip in favor of Basic Salary / Total Entitlement",
    },
    {
        "id": "CO-002",
        "query": "Which employees receive a Technical Special Allowance, and what is their Phone Allowance?",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Technical Special Allowance]] and [Employee Master[Phone Allowance]] — very niche columns",
    },
    {
        "id": "CO-003",
        "query": "List employees who have a Family Book Number recorded, along with their Number of Spouses and Number of Children.",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Family Book Number]], [Employee Master[Number of Spouses]], [Employee Master[Number of Children]] — rarely queried demographic columns",
    },
    {
        "id": "CO-004",
        "query": "What is the Supplementary Allowance as a percentage of Total Entitlement Amount for each employee?",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Supplementary Allowance]] — an obscure column that column selection might skip",
    },
    {
        "id": "CO-005",
        "query": "Which employees have a Special Contract Basic Salary different from their regular Basic Salary?",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Special Contract Basic Salary]] — extremely niche column",
    },
    {
        "id": "CO-006",
        "query": "What is the total Cost of Living Allowance and Housing Allowance paid across all employees?",
        "category": "column_omission",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Needs two specific allowance columns that might be omitted in favor of Total Entitlement",
    },
    {
        "id": "CO-007",
        "query": "Show me the Child Allowance for employees who have more than 0 children. Also show their Social Allowance.",
        "category": "column_omission",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Child Allowance]], [Employee Master[Social Allowance]], [Employee Master[Number of Children]] — 3 obscure columns",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 2: CROSS_STRUCT_DEEP — Columns from 5+ different structs
# ═══════════════════════════════════════════════════════════════════════════

CROSS_STRUCT_DEEP = [
    {
        "id": "CS-001",
        "query": "For each employee with a Master's degree, list their name, their qualification titles, their competency names with supervisor ratings, and their leave types with durations.",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (degree, name) + Employee Qualification + Employee Competencies Rating + Employee Leave Details — 4 structs. Column selection must pick the right struct fields from each.",
    },
    {
        "id": "CS-002",
        "query": "Which employees have both CV work experience and assignment history? Show their CV company names alongside their assignment names and the overlap in dates if any.",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs CV Employee Work Experience + Employee Assignment History + Employee Master — date overlap computation requires start/end from both structs",
    },
    {
        "id": "CS-003",
        "query": "For employees who have been promoted, show their promotion date, the objectives they had during that period, and their competency ratings at the time.",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (promotion date) + Employee Objectives + Employee Competencies Rating — temporal correlation across structs",
    },
    {
        "id": "CS-004",
        "query": "List employees who have previous employer records, their CV achievements, and their current assignment history. Show the career progression chronologically.",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Previous Employer + CV Employee Achievements + Employee Assignment History — 3 structs with date ordering",
    },
    {
        "id": "CS-005",
        "query": "For each employee, show: their current job title and department, their highest qualification, their total leave days taken, and whether their supervisor rated them higher or lower than their self-rating on any competency.",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master + Employee Qualification + Employee Leave Details + Employee Competencies Rating — 4 structs with conditional logic",
    },
    {
        "id": "CS-006",
        "query": "Compare the educational institute from Employee Master with the institutions listed in Employee Qualification. Are they always the same?",
        "category": "cross_struct_deep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Educational Institute]] + [Employee Qualification[Educational Institute]] — two different columns with similar names from different structs. Column selection might confuse them.",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 3: AMBIGUOUS_REF — Similar/overlapping column names
# ═══════════════════════════════════════════════════════════════════════════

AMBIGUOUS_REF = [
    {
        "id": "AR-001",
        "query": "What is the difference between an employee's Grade and their Employee Grade?",
        "category": "ambiguous_ref",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Two columns: [Employee Master[Grade]] and [Employee Assignment History[Employee Grade]] — column selection might pick the wrong one or miss one",
    },
    {
        "id": "AR-002",
        "query": "Compare the Position Title from Employee Master with the Position Title from Assignment History for each employee.",
        "category": "ambiguous_ref",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "[Employee Master[Position Title]] vs [Employee Assignment History[Position Title]] — same name, different struct",
    },
    {
        "id": "AR-003",
        "query": "What is the difference between the Degree field in Employee Master and the CV Degree Name in CV Employee Education?",
        "category": "ambiguous_ref",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "[Employee Master[Degree]] vs [CV Employee Education[CV Degree Name]] — similar concepts, different columns",
    },
    {
        "id": "AR-004",
        "query": "Show me the Job Title and the CV Job Title for employees who have CV work experience. Are they different?",
        "category": "ambiguous_ref",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "[Employee Master[Job Title]] vs [CV Employee Work Experience[CV Job Title]] — same concept, different sources",
    },
    {
        "id": "AR-005",
        "query": "Compare the Educational Institute from Employee Master with the institution names from both Employee Qualification and CV Employee Education.",
        "category": "ambiguous_ref",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Three columns with similar meaning: [Employee Master[Educational Institute]], [Employee Qualification[Educational Institute]], [CV Employee Education[CV Institution Name]]",
    },
    {
        "id": "AR-006",
        "query": "What is the relationship between an employee's Department, their Organization Unit, and their Office Name?",
        "category": "ambiguous_ref",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "Three organizational hierarchy columns that might be confused: Department, Organization Unit, Office Name",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 4: IMPLICIT_DEP — Hidden column dependencies
# ═══════════════════════════════════════════════════════════════════════════

IMPLICIT_DEP = [
    {
        "id": "ID-001",
        "query": "Which employees have used more than 80% of their annual leave entitlement?",
        "category": "implicit_dep",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs both [Entitlement Leaves[Annual Leave Entitlement]] and [Entitlement Leaves[Approved Annual Leave]] — the LLM might select only one",
    },
    {
        "id": "ID-002",
        "query": "Calculate the leave utilization rate for each leave type: approved days divided by entitlement days.",
        "category": "implicit_dep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs 6 columns: Annual Leave Entitlement, Approved Annual Leave, Non-Mandatory Leave Entitlement, Approved Non-Mandatory Leave, Wellbeing Leave Entitlement, Approved Wellbeing Leave — column selection might miss the entitlement columns",
    },
    {
        "id": "ID-003",
        "query": "Which employees have a Time Since Last Promotion greater than 24 months but have received a Financial Increase as their Last Promotion Reason?",
        "category": "implicit_dep",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Time Since Last Promotion]] AND [Employee Master[Last Promotion Reason]] — the reason column is easy to miss",
    },
    {
        "id": "ID-004",
        "query": "For each employee, calculate the total compensation as Basic Salary + Housing Allowance + Cost of Living Allowance + Child Allowance + Social Allowance + Phone Allowance + Supplementary Allowance. Compare with Total Entitlement Amount.",
        "category": "implicit_dep",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs 8 salary/allowance columns — column selection with threshold 30 might omit the less common allowances. The LLM must select ALL of them to compute correctly.",
    },
    {
        "id": "ID-005",
        "query": "Which employees have a Graduation Date that is after their Date of Joining? This would indicate they joined before graduating.",
        "category": "implicit_dep",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Graduation Date]] AND [Employee Master[Date of Joining]] — two date columns that might not both be selected",
    },
    {
        "id": "ID-006",
        "query": "Find employees whose Sick Leave Taken exceeds their Wellbeing Leave Entitlement.",
        "category": "implicit_dep",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Needs [Employee Master[Sick Leave Taken]] AND [Entitlement Leaves[Wellbeing Leave Entitlement]] — cross-struct comparison with non-obvious dependency",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 5: MULTI_STRUCT_UNNEST — UNNEST on multiple struct arrays
# ═══════════════════════════════════════════════════════════════════════════

MULTI_STRUCT_UNNEST = [
    {
        "id": "MU-001",
        "query": "For each leave type, show the employee name, the leave duration, and the competency where they rated themselves highest. Join leave details with competency ratings.",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on both Employee Leave Details AND Employee Competencies Rating — two struct arrays in the same query. Column selection must include both.",
    },
    {
        "id": "MU-002",
        "query": "List employees who have objectives with a goal weighting above 50% AND have taken more than 20 days of non-mandatory leave.",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on Employee Objectives AND Employee Leave Details — two struct arrays with filtering",
    },
    {
        "id": "MU-003",
        "query": "Show each employee's CV work experience company alongside their previous employer name. Are there any overlapping companies?",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on CV Employee Work Experience AND Employee Previous Employer — two struct arrays with value comparison",
    },
    {
        "id": "MU-004",
        "query": "For each employee, list their qualification titles alongside their CV education degree names. Identify any qualifications not listed in their CV.",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on Employee Qualification AND CV Employee Education — two struct arrays with set comparison",
    },
    {
        "id": "MU-005",
        "query": "Show each employee's assignment history positions alongside their CV work experience job titles in chronological order.",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on Employee Assignment History AND CV Employee Work Experience — two struct arrays with date ordering",
    },
    {
        "id": "MU-006",
        "query": "For Ayesha Al Qubaisi, list all her leave records, competency ratings, objectives, and qualifications in a single comprehensive report.",
        "category": "multi_struct_unnest",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs UNNEST on 4 struct arrays simultaneously. Column selection must include ALL of them for this specific employee.",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 6: NEGATION_EDGE — Negative/absence queries requiring full scans
# ═══════════════════════════════════════════════════════════════════════════

NEGATION_EDGE = [
    {
        "id": "NE-001",
        "query": "Which employees have NO leave records at all?",
        "category": "negation_edge",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Requires checking absence of struct array entries — column selection might skip the leave struct entirely since the query is about absence",
    },
    {
        "id": "NE-002",
        "query": "Which employees have no competency ratings recorded?",
        "category": "negation_edge",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Absence query on competency struct — column selection might not include competency columns",
    },
    {
        "id": "NE-003",
        "query": "Are there any employees with no objectives set? List them.",
        "category": "negation_edge",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Absence query on objectives struct",
    },
    {
        "id": "NE-004",
        "query": "Which employees have no previous employer records and no CV work experience?",
        "category": "negation_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Double absence query across two structs — column selection must include both structs even though the query is about their absence",
    },
    {
        "id": "NE-005",
        "query": "Find employees who have never been promoted (no Last Promotion Date).",
        "category": "negation_edge",
        "difficulty": "medium",
        "expected_output_type": "string",
        "notes": "NULL check on [Employee Master[Last Promotion Date]] — column selection might skip this column",
    },
    {
        "id": "NE-006",
        "query": "Which employees have no qualifications listed and no CV education entries?",
        "category": "negation_edge",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Double absence across Employee Qualification and CV Employee Education structs",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 7: COMPOUND_AGGREGATION — Multi-level aggregations across structs
# ═══════════════════════════════════════════════════════════════════════════

COMPOUND_AGGREGATION = [
    {
        "id": "CA-001",
        "query": "For each department, calculate: the average employee rating across all competencies, the total leave days taken, and the average ADEO experience. Present as a department scorecard.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (department, ADEO experience) + Employee Competencies Rating (employee rating) + Employee Leave Details (duration) — multi-struct GROUP BY with AVG and SUM",
    },
    {
        "id": "CA-002",
        "query": "Calculate a 'retention risk score' for each employee: (months since last promotion * 2) + (number of previous employers * 3) - (ADEO experience in years). Show the top 5 highest risk.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (time since last promotion, ADEO experience) + Employee Previous Employer (count) — computed metric across structs",
    },
    {
        "id": "CA-003",
        "query": "For each sector, show: the number of employees, the average competency supervisor rating, the percentage of employees with Master's degree or higher, and the total approved annual leave days.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs 4 structs: Employee Master (sector, degree) + Employee Competencies Rating (supervisor rating) + Entitlement Leaves (approved annual leave) — multi-metric sector dashboard",
    },
    {
        "id": "CA-004",
        "query": "Which department has the highest ratio of approved leave days to total entitlement days? Include all leave types.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (department) + all 6 Entitlement Leaves columns — ratio computation requiring all entitlement and approved columns",
    },
    {
        "id": "CA-005",
        "query": "For each employee grade, calculate the average basic salary, the average total entitlement, the average number of competency ratings, and the average leave days taken.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (grade, salary, entitlement) + Employee Competencies Rating (count) + Employee Leave Details (sum duration) — grouped by grade across 3 structs",
    },
    {
        "id": "CA-006",
        "query": "Create a 'performance index' for each employee: (average supervisor competency rating / 5) * 100 + (objectives completion rate * 50) - (sick leave days taken * 2). Rank employees by this index.",
        "category": "compound_aggregation",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Competencies Rating (supervisor rating) + Employee Objectives (status) + Employee Master (sick leave) — compound computed metric across structs",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 8: TEMPORAL_CROSS — Time-based queries across multiple structs
# ═══════════════════════════════════════════════════════════════════════════

TEMPORAL_CROSS = [
    {
        "id": "TC-001",
        "query": "Which employees took leave within 30 days of their last promotion date? Show the promotion date and leave dates.",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (last promotion date) + Employee Leave Details (leave start date) — date arithmetic across structs",
    },
    {
        "id": "TC-002",
        "query": "Are there any employees whose assignment history shows they changed departments? Compare their current department with their assignment history positions.",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Master (department) + Employee Assignment History (assignment name, position title) — temporal comparison",
    },
    {
        "id": "TC-003",
        "query": "For employees with previous employer records, how much time elapsed between their previous employer end date and their ADEO date of joining?",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Previous Employer (end date) + Employee Master (date of joining) — date gap computation across structs",
    },
    {
        "id": "TC-004",
        "query": "Which employees have CV education end dates that overlap with their ADEO employment? This means they were studying while employed.",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs CV Employee Education (end date) + Employee Master (date of joining) — overlap detection across structs",
    },
    {
        "id": "TC-005",
        "query": "Show the complete career timeline for Eisa AlDhaheri: previous employers, ADEO joining date, assignment history, and promotions, all ordered by date.",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Previous Employer + Employee Master + Employee Assignment History — multi-struct temporal ordering for a specific employee",
    },
    {
        "id": "TC-006",
        "query": "For each employee, calculate the total time spent in all previous assignments (from assignment history) and compare it with their ADEO experience in years.",
        "category": "temporal_cross",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs Employee Assignment History (experience duration) + Employee Master (ADEO experience) — cross-struct numeric comparison",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 9: ADVERSARIAL_MULTI_TURN — Multi-turn conversations designed to
#              exploit column selection limitations
# ═══════════════════════════════════════════════════════════════════════════

ADVERSARIAL_MULTI_TURN = [
    {
        "id": "AMT-001",
        "name": "Allowance deep dive",
        "turns": [
            {"query": "What is the total entitlement amount for each employee?", "expected_output_type": "string", "notes": "Simple opener — LLM selects obvious columns"},
            {"query": "Now break down that total into each individual allowance component: Basic Salary, Housing, Cost of Living, Child, Social, Phone, Supplementary, Etihad, Secondment, and Technical Special.", "expected_output_type": "string", "notes": "Follow-up requires ALL 10 allowance columns — column selection on follow-up may not include them all"},
            {"query": "Which employees have a non-zero Etihad Allowance or Secondment Allowance?", "expected_output_type": "string", "notes": "Targets the most obscure allowances — column selection likely omitted these in earlier turns"},
        ],
    },
    {
        "id": "AMT-002",
        "name": "Career timeline reconstruction",
        "turns": [
            {"query": "Who are the most senior employees by ADEO experience?", "expected_output_type": "string", "notes": "Simple opener"},
            {"query": "For those senior employees, what previous employers did they have before joining ADEO?", "expected_output_type": "string", "notes": "Follow-up needs Employee Previous Employer struct"},
            {"query": "What about their assignment history at ADEO? List all their past positions and durations.", "expected_output_type": "string", "notes": "Needs Employee Assignment History struct — a third struct the LLM may not have selected"},
            {"query": "Do any of their previous employer dates overlap with their ADEO assignment history?", "expected_output_type": "string", "notes": "Cross-struct date comparison — requires columns from both previous employer and assignment history"},
        ],
    },
    {
        "id": "AMT-003",
        "name": "Leave entitlement trap",
        "turns": [
            {"query": "How many leave days has each employee taken in total?", "expected_output_type": "string", "notes": "Simple leave aggregation"},
            {"query": "What is their leave entitlement for each type?", "expected_output_type": "string", "notes": "Needs Entitlement Leaves struct — column selection may not include entitlement columns since the first query only needed taken days"},
            {"query": "Calculate the utilization rate: approved days divided by entitlement days for each leave type.", "expected_output_type": "string", "notes": "Requires both approved AND entitlement columns — the LLM must have selected both in previous turns"},
        ],
    },
    {
        "id": "AMT-004",
        "name": "Competency-qualification correlation",
        "turns": [
            {"query": "What are the average competency ratings by department?", "expected_output_type": "string", "notes": "Simple competency aggregation"},
            {"query": "What is the highest degree held by employees in each department?", "expected_output_type": "string", "notes": "Needs degree column — may not be selected if column selection focused on competency columns"},
            {"query": "Is there a correlation between education level and competency ratings? Compare employees with Master's vs Bachelor's degrees.", "expected_output_type": "string", "notes": "Cross-references degree AND competency ratings — both must be available"},
        ],
    },
    {
        "id": "AMT-005",
        "name": "Struct absence discovery",
        "turns": [
            {"query": "List all employees and their current job titles.", "expected_output_type": "string", "notes": "Simple Employee Master query"},
            {"query": "Which of these employees have no leave records?", "expected_output_type": "string", "notes": "Absence check — column selection may not include leave struct since we're checking for its absence"},
            {"query": "And which ones have no competency ratings?", "expected_output_type": "string", "notes": "Another absence check on a different struct"},
            {"query": "Are there any employees with neither leave records nor competency ratings?", "expected_output_type": "string", "notes": "Double absence — requires both structs to be available despite no positive data"},
        ],
    },
    {
        "id": "AMT-006",
        "name": "Salary component audit",
        "turns": [
            {"query": "What is the average total entitlement amount?", "expected_output_type": "number", "notes": "Simple number query"},
            {"query": "What are the individual components that make up that total? List each allowance type and its average.", "expected_output_type": "string", "notes": "Needs ALL allowance columns — column selection likely only included Total Entitlement for the first query"},
            {"query": "For employees with a Special Contract Basic Salary, how does it differ from the regular Basic Salary?", "expected_output_type": "string", "notes": "Needs the most obscure salary column — Special Contract Basic Salary"},
            {"query": "Calculate a corrected total entitlement by summing all individual allowance components. Does it match the stored Total Entitlement Amount?", "expected_output_type": "string", "notes": "Requires ALL 10 allowance columns for verification — if any were omitted by column selection, the sum will be wrong"},
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 10: EXTREME_SINGLE — Single-turn queries that push all limits
# ═══════════════════════════════════════════════════════════════════════════

EXTREME_SINGLE = [
    {
        "id": "ES-001",
        "query": "Create a comprehensive employee dashboard showing: name, department, sector, job title, grade, basic salary, total entitlement, ADEO experience, last promotion date, highest degree, total leave days taken, average competency self-rating, and number of objectives. Include all employees.",
        "category": "extreme_single",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires columns from 5+ structs in a single query — column selection must pick the right subset from 104 columns",
    },
    {
        "id": "ES-002",
        "query": "For each employee, compute a 'total compensation gap' which is the Total Entitlement Amount minus the sum of (Basic Salary + Housing Allowance + Cost of Living Allowance + Child Allowance + Social Allowance + Phone Allowance + Supplementary Allowance + Etihad Allowance + Secondment Allowance + Technical Special Allowance). Show employees where this gap is non-zero.",
        "category": "extreme_single",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Requires ALL 11 salary/allowance columns — if column selection misses even one, the computation is wrong",
    },
    {
        "id": "ES-003",
        "query": "Identify employees who have: (1) a Master's degree or higher, (2) a supervisor competency rating above 3, (3) taken less than 10 days of sick leave, (4) been with ADEO for more than 1 year, and (5) have at least one objective with APPROVED status. List their names and details.",
        "category": "extreme_single",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "5-condition filter across 4 structs (Employee Master, Competencies, Leave, Objectives) — column selection must include all required columns from each",
    },
    {
        "id": "ES-004",
        "query": "Show a cross-tabulation of Gender × Degree with the count of employees and their average ADEO experience in each cell.",
        "category": "extreme_single",
        "difficulty": "hard",
        "expected_output_type": "string",
        "notes": "Pivot-style query requiring Gender, Degree, ADEO Experience — column selection might skip Degree if it seems unrelated",
    },
    {
        "id": "ES-005",
        "query": "For each sector, rank employees by their total leave days taken (descending) and show only the top 2 per sector along with their competency ratings.",
        "category": "extreme_single",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Window function (ROW_NUMBER) with GROUP BY sector + struct join (Leave + Competencies) — complex SQL that column selection must support",
    },
    {
        "id": "ES-006",
        "query": "What is the correlation between the number of qualifications an employee has and their average supervisor competency rating? Show the data points.",
        "category": "extreme_single",
        "difficulty": "extreme",
        "expected_output_type": "string",
        "notes": "Needs count of Employee Qualification entries + average of Employee Competencies Rating supervisor rating — correlation between two struct array metrics",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

ALL_SINGLE_TURN_CATEGORIES = [
    COLUMN_OMISSION,
    CROSS_STRUCT_DEEP,
    AMBIGUOUS_REF,
    IMPLICIT_DEP,
    MULTI_STRUCT_UNNEST,
    NEGATION_EDGE,
    COMPOUND_AGGREGATION,
    TEMPORAL_CROSS,
    EXTREME_SINGLE,
]


def get_all_adversarial_single_turn_queries() -> List[dict]:
    """Get all single-turn adversarial queries."""
    queries = []
    for category in ALL_SINGLE_TURN_CATEGORIES:
        queries.extend(category)
    return queries


def get_all_adversarial_multi_turn_conversations() -> List[dict]:
    """Get all adversarial multi-turn conversations."""
    return list(ADVERSARIAL_MULTI_TURN)


def get_adversarial_query_by_id(query_id: str) -> Optional[dict]:
    """Look up a specific adversarial query or conversation by ID."""
    # Search single-turn
    for category in ALL_SINGLE_TURN_CATEGORIES:
        for q in category:
            if q["id"] == query_id:
                return q
    # Search multi-turn
    for conv in ADVERSARIAL_MULTI_TURN:
        if conv["id"] == query_id:
            return conv
    return None


def get_adversarial_queries_by_category(category_name: str) -> List[dict]:
    """Get all queries matching a category name."""
    results = []
    for category in ALL_SINGLE_TURN_CATEGORIES:
        for q in category:
            if q.get("category") == category_name:
                results.append(q)
    return results


def get_adversarial_queries_by_difficulty(difficulty: str) -> List[dict]:
    """Get all queries matching a difficulty level."""
    results = []
    for category in ALL_SINGLE_TURN_CATEGORIES:
        for q in category:
            if q.get("difficulty") == difficulty:
                results.append(q)
    return results


def get_adversarial_stats() -> Dict[str, int]:
    """Get statistics about the adversarial query bank."""
    single = get_all_adversarial_single_turn_queries()
    multi = get_all_adversarial_multi_turn_conversations()
    multi_turns = sum(len(c["turns"]) for c in multi)
    return {
        "total_single_turn": len(single),
        "total_multi_turn_conversations": len(multi),
        "total_multi_turn_turns": multi_turns,
        "total_queries": len(single) + multi_turns,
        "categories": {
            "column_omission": len(COLUMN_OMISSION),
            "cross_struct_deep": len(CROSS_STRUCT_DEEP),
            "ambiguous_ref": len(AMBIGUOUS_REF),
            "implicit_dep": len(IMPLICIT_DEP),
            "multi_struct_unnest": len(MULTI_STRUCT_UNNEST),
            "negation_edge": len(NEGATION_EDGE),
            "compound_aggregation": len(COMPOUND_AGGREGATION),
            "temporal_cross": len(TEMPORAL_CROSS),
            "extreme_single": len(EXTREME_SINGLE),
            "adversarial_multi_turn": len(ADVERSARIAL_MULTI_TURN),
        },
        "difficulty": {
            "medium": len(get_adversarial_queries_by_difficulty("medium")),
            "hard": len(get_adversarial_queries_by_difficulty("hard")),
            "extreme": len(get_adversarial_queries_by_difficulty("extreme")),
        },
    }


if __name__ == "__main__":
    import json
    stats = get_adversarial_stats()
    print(json.dumps(stats, indent=2))
