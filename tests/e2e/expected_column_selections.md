# Expected Column Selections per Question

This file documents **which columns SHOULD be selected** for each test question,
based on the **exact columns the LLM sees** in the V6 prompt (after phantom column
filtering and semantic model registration). Column names use the exact bracket
notation the LLM receives.

**How to use this file:**
- Each question has a table of expected columns with rationale
- Add your own notes in the `YOUR NOTES` section under each question
- Mark columns you disagree with or want to add/remove
- Use this as the basis for evaluating LLM column selection accuracy

---

## What the LLM Actually Sees (62 flat + 12 struct groups)

These are the **exact columns** the LLM receives after the agent registers the
data and the prompt builder filters phantom columns. Column names use the exact
bracket notation from the V6 prompt.

### Flat Columns (the LLM sees these as individual selectable items)

| # | Column Name | Type | Description |
|---|------------|------|-------------|
| 1 | `[CV Employee Summary[CV Employee Summary]]` | string | Professional profile summary from CV |
| 2 | `[Employee Master[Age]]` | float | Current age in years |
| 3 | `[Employee Master[Assignment Status]]` | string | Employment status (Active, Terminated, etc.) |
| 4 | `[Employee Master[Basic Salary]]` | float | Fixed base compensation |
| 5 | `[Employee Master[Child Allowance]]` | float | Support based on number of children |
| 6 | `[Employee Master[Cost of Living Allowance]]` | float | Regional cost of living offset |
| 7 | `[Employee Master[Date of Joining]]` | datetime | Official employment start date |
| 8 | `[Employee Master[Degree]]` | string | Highest academic degree level |
| 9 | `[Employee Master[Department]]` | string | Functional team within Sector/Division |
| 10 | `[Employee Master[Division]]` | string | Highest operational division |
| 11 | `[Employee Master[Educational Institute]]` | string | Institution of highest qualification |
| 12 | `[Employee Master[Email Address]]` | string | Corporate email |
| 13 | `[Employee Master[Employee Grade]]` | string | Specific level/rank of current position |
| 14 | `[Employee Master[Employee Name]]` | string | Full legal name in English |
| 15 | `[Employee Master[Employee Name (Arabic)]]` | string | Full legal name in Arabic |
| 16 | `[Employee Master[Employee Number]]` | string | Unique employee identifier |
| 17 | `[Employee Master[Family Book Number]]` | float | Family Book reference number |
| 18 | `[Employee Master[Gender]]` | string | Biological sex |
| 19 | `[Employee Master[Grade]]` | string | Administrative pay grade |
| 20 | `[Employee Master[Graduation Date]]` | datetime | Official graduation date |
| 21 | `[Employee Master[Housing Allowance]]` | float | Accommodation subsidy |
| 22 | `[Employee Master[Job Title]]` | string | Generic rank title (e.g. Senior Specialist) |
| 23 | `[Employee Master[Last Promotion Date]]` | datetime | Date of most recent promotion |
| 24 | `[Employee Master[Last Promotion Reason]]` | string | Reason for last promotion |
| 25 | `[Employee Master[Major (Education)]]` | string | Field of study/major specialization |
| 26 | `[Employee Master[Marital Status]]` | string | Current marital status |
| 27 | `[Employee Master[Nationality]]` | string | Country of citizenship |
| 28 | `[Employee Master[Number of Children]]` | string | Count of dependent children |
| 29 | `[Employee Master[Office Name]]` | string | Organizational unit equivalent to a sector |
| 30 | `[Employee Master[Organization Unit]]` | string | Most granular business unit/section |
| 31 | `[Employee Master[Passport Number]]` | string | Passport identifier |
| 32 | `[Employee Master[Person Type]]` | string | Employment category (Permanent, Contractor, etc.) |
| 33 | `[Employee Master[Phone Allowance]]` | float | Monthly mobile phone stipend |
| 34 | `[Employee Master[Phone Number]]` | float | Primary contact telephone |
| 35 | `[Employee Master[Position Title]]` | string | Specific official designation |
| 36 | `[Employee Master[Sector]]` | string | Intermediate level (Division → Sector → Department) |
| 37 | `[Employee Master[Sick Leave Taken]]` | float | Total sick leave days in current period |
| 38 | `[Employee Master[Social Allowance]]` | float | Government-mandated allowance for nationals |
| 39 | `[Employee Master[Supervisor Name]]` | string | Direct manager's full name |
| 40 | `[Employee Master[Supplementary Allowance]]` | float | Additional allowance to supplement salary |
| 41 | `[Employee Master[Technical Special Allowance]]` | float | Specialized technical skills allowance |
| 42 | `[Employee Master[Time Since Last Promotion]]` | float | Duration since last promotion |
| 43 | `[Employee Master[Total Entitlement Amount]]` | float | Gross total (salary + all allowances) |
| 44 | `[Entitlement Leaves[Annual Leave Entitlement]]` | float | Annual leave days entitled per year |
| 45 | `[Entitlement Leaves[Approved Annual Leave]]` | float | Approved annual leave days |
| 46 | `[Entitlement Leaves[Approved Non-Mandatory Leave]]` | float | Approved discretionary leave days |
| 47 | `[Entitlement Leaves[Approved Wellbeing Leave]]` | float | Approved wellbeing/mental health leave days |
| 48 | `[Entitlement Leaves[Non-Mandatory Leave Entitlement]]` | float | Non-mandatory leave days per year |
| 49 | `[Entitlement Leaves[Wellbeing Leave Entitlement]]` | float | Wellbeing leave days per year |
| 50 | `[CV Employee Competencies[Technical Competency Name]]` | string | Skills/competencies from CV |
| 51 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | string | Combined competencies rating column |
| 52 | `[CV Employee Interest and Hobbies[CV Interest Name][CV Interest Description]]` | string | Combined interests column |
| 53 | `[CV Employee Achievements and Awards[CV Title][CV Achievement Description][CV Issue Date]]` | string | Combined achievements column |
| 54 | `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]` | string | Combined leave details column |
| 55 | `[Employee Performance[Performance Review Period][Final Rating Num][Normalized Performance Rating]]` | string | Combined performance column |
| 56 | `[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]` | string | Combined achievements column |
| 57 | `[Employee Objectives[Objective Name][Goal Plan Name][Objective Description][Goal Weighting][Goal Status][Objective Status][Workflow State]]` | string | Combined objectives column |
| 58 | `[Employee Qualification[Qualification Title][Educational Institute][GPA (Grade Point Average)][Study Start Date][Study End Date]]` | string | Combined qualification column |
| 59 | `[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]` | string | Combined CV education column |
| 60 | `[Employee Assignment History[Assignment Name][Position Title][Employee Grade][Assignment Start Date][Assignment End Date][Assignment Experience (Years & Months)]]` | string | Combined assignment history column |
| 61 | `[Employee Previous Employer[Previous Employer Name][Previous Job Title][Start Date][End Date]]` | string | Combined previous employer column |
| 62 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | string | Combined CV work experience column |

### Struct Columns (the LLM sees these as groups with named inner fields)

| # | Struct Group (combined name) | Inner Fields | Description |
|---|----------------------------|-------------|-------------|
| 1 | `[CV Employee Competencies[Technical Competency Name]]` | → `[CV Employee Competencies[Technical Competency Name]]` (string, freetext) | Skills/competencies from CV |
| 2 | `[Employee Competencies Rating[...]]` | → Competancy Name (string, categorical), Employee Rating (string, categorical), Supervisor Rating (string, categorical), Employee Rating Description (string, categorical), Supervisor Rating Description (string, categorical) | Organizational competency evaluations |
| 3 | `[CV Employee Interest and Hobbies[...]]` | → CV Interest Name (string, freetext), CV Interest Description (string, categorical) | Hobbies/interests from CV |
| 4 | `[CV Employee Achievements and Awards[...]]` | → CV Title (string, freetext), CV Achievement Description (string, categorical), CV Issue Date (datetime) | Awards/achievements from CV |
| 5 | `[Employee Leave Details[...]]` | → Leave Type (string, categorical), Leave Duration (Days) (float), Approval Status (string, categorical), Leave Start Date (datetime), Leave End Date (datetime) | Individual leave records |
| 6 | `[Employee Performance[...]]` | → Performance Review Period (string, categorical), Final Rating Num (string, categorical), Normalized Performance Rating (string, categorical) | Performance review ratings |
| 7 | `[Employee Achievements[...]]` | → Customary Name (string, categorical), Manager OA Comments (string, freetext), Employee OA Comments (string, freetext) | Performance cycle achievements/feedback |
| 8 | `[Employee Objectives[...]]` | → Objective Name (string, freetext), Goal Plan Name (string, categorical), Objective Description (string, freetext), Goal Weighting (float), Goal Status (string, categorical), Objective Status (string, categorical), Workflow State (string, categorical) | Performance goals/projects |
| 9 | `[Employee Qualification[...]]` | → Qualification Title (string, freetext), `[Employee Master[Educational Institute]]` (string, freetext), GPA (Grade Point Average) (string, categorical), Study Start Date (datetime), Study End Date (datetime) | Academic/professional qualifications |
| 10 | `[CV Employee Education[...]]` | → CV Institution Name (string, freetext), CV Degree Name (string, freetext), CV Start Date (datetime), CV End Date (datetime) | Education entries from CV |
| 11 | `[Employee Assignment History[...]]` | → Assignment Name (string, freetext), Position Title (string, freetext), Employee Grade (string, categorical), Assignment Start Date (datetime), Assignment End Date (datetime), Assignment Experience (Years & Months) (float) | Historical job assignments |
| 12 | `[Employee Previous Employer[...]]` | → Previous Employer Name (string, freetext), Previous Job Title (string, freetext), Start Date (datetime), End Date (datetime) | Prior employment |
| 13 | `[CV Employee Work Experience[...]]` | → CV Company Name (string, freetext), CV Job Title (string, freetext), CV Responsibilities Summary (string, freetext), CV Start Date (datetime), CV End Date (datetime) | Work experience from CV |

> **NOTE:** The LLM sees BOTH the flat combined column (e.g. `[Employee Leave Details[Leave Type][Leave Duration (Days)]...]`)
> AND the struct group with individual inner fields. It can select either the combined
> name (which selects all inner fields) or individual inner field names.

### Columns NOT in the prompt (phantom/filtered)

These columns exist in the semantic model JSON but are **not shown to the LLM**
because they don't exist in the actual DataFrame:

- `[Employee Master[ADEO Experience (Years)]]`
- `[Employee Master[Etihad Allowance]]`
- `[Employee Master[Secondment Allowance]]`
- `[Employee Master[Special Contract Basic Salary]]`

---

## Q3b: What are the main skills of employee 1137?

**Question type:** Narrow — asking for skills of a specific employee

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity**: Filter by employee ID 1137 (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Identity**: Human-readable name (Rule 4) |
| 3 | `[CV Employee Competencies[Technical Competency Name]]` | **Core data**: The ONLY column that stores skills/competencies. This is both a flat column and a struct group with one inner field |
| 4 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | **LLM-reasonable**: Description says "Competancy Name: The name of a standard organizational competency being evaluated" — the LLM sees "competency" and reasonably includes it for a "skills" question |
| 5 | `[CV Employee Summary[CV Employee Summary]]` | **LLM-reasonable**: Description says "A professional profile summary or biography extracted from the employee's CV" — CV summaries typically list skills and qualifications |
| 6 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | **LLM-reasonable**: CV Responsibilities Summary is described as "A comprehensive list of duties and key projects" — the LLM may see responsibilities as indicative of skills |
| 7 | `[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]` | **LLM-reasonable**: Education background informs skill set — the LLM may include it as context for what skills someone possesses |

**Expected total: 7 columns** (3 core + 4 LLM-reasonable)

### What should NOT be selected
- Department, Grade, Organization Unit — the question only asks for skills, not organizational context. The LLM may include these for completeness, but they are not skill-related

### YOUR NOTES
<!-- WHY THE USER SAID TO INCLUDE THE "NOT SELECTED" COLUMNS:
     The LLM doesn't have our domain knowledge. When it sees column descriptions
     containing words like "Competancy Name", "professional profile summary", "CV Responsibilities Summary",
     and "CV Degree Name", it can reasonably infer these are relevant to a "skills" question.
     
     - Employee Competencies Rating: We know these are organizational performance evaluations
       (Digital Saviness, etc.), NOT technical skills. But the LLM sees "Competancy Name" and
       reasonably associates it with "skills".
     - CV Employee Summary: We know it's a generic profile, but the LLM sees "professional profile
       summary" which often lists skills.
     - CV Employee Work Experience: We know it's job history, but "CV Responsibilities Summary"
       sounds skill-relevant — responsibilities = things you can do = skills.
     - CV Employee Education: We know it's education, not skills, but education informs skill set.
     
     Key insight: Expected columns should be based on what the LLM CAN REASONABLY INFER from the
     prompt descriptions, not on what a domain expert knows the columns truly represent. The
     original "NOT selected" list assumed the LLM would know that Employee Competencies Rating =
     organizational evaluations (not technical skills), but the LLM only sees the description text,
     not our domain context. -->



---

## Q3: What are this employee's main skills? (expanded query)

**Full query:** "Find employee with ID 1137. Return their name, employee ID, organizational unit, department/division, grade, years of service, tenure, and all their technical competencies/skills. Include competency ratings if available."

**Question type:** Broad — explicitly asks for multiple attributes + skills + ratings

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity**: Filter by 1137 + display (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Identity**: Display name (Rule 4) |
| 3 | `[Employee Master[Organization Unit]]` | **Display**: Explicitly requested |
| 4 | `[Employee Master[Department]]` | **Display**: Explicitly requested ("department/division") |
| 5 | `[Employee Master[Division]]` | **Display**: Explicitly requested ("department/division") |
| 6 | `[Employee Master[Employee Grade]]` | **Display**: "grade" explicitly requested |
| 7 | `[Employee Master[Date of Joining]]` | **Calculation**: Needed to compute years of service/tenure |
| 8 | `[CV Employee Competencies[Technical Competency Name]]` | **Core data**: Technical competencies/skills explicitly requested |
| 9 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | **Core data**: "Include competency ratings if available" — explicit request. Select the combined struct name to get all inner fields |
| 10 | `[CV Employee Summary[CV Employee Summary]]` | **LLM-reasonable**: "Professional profile summary or biography from CV" — CV summaries typically list skills and qualifications, relevant when the query asks for "ALL their technical competencies/skills" |
| 11 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | **LLM-reasonable**: CV Responsibilities Summary = "A comprehensive list of duties and key projects" — the LLM may see responsibilities as skill-relevant, especially when the question asks for "ALL their technical competencies/skills" |
| 12 | `[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]` | **LLM-reasonable**: Education background informs skill set — the LLM may include it as context for what skills someone possesses |

**Expected total: 12 columns** (7 flat + 5 struct combined names)

### What should NOT be selected
- Grade (administrative pay grade) — redundant with Employee Grade (Rule 8). The question says "grade" which maps to Employee Grade (specific rank)
- ADEO Experience (Years) — NOT in the prompt (phantom column)
- Salary, allowances — not requested

### YOUR NOTES
<!-- WHY THE USER SAID TO INCLUDE CV Employee Education AND CV Employee Work Experience:
     The expanded query explicitly asks for "ALL their technical competencies/skills" — the word
     "ALL" is a signal to the LLM to be broad. When the LLM sees column descriptions containing
     "professional profile summary", "responsibilities", and "education", it can reasonably
     infer these provide additional skill context. The original exclusion of CV Employee Work
     Experience and CV Employee Education was based on our domain knowledge that these are not
     "skills" columns — but the LLM doesn't have that distinction. From the LLM's perspective,
     responsibilities = things you can do = skills, and education = informs skill set.
     
     Key insight: The word "ALL" in the query activates a broader selection strategy. The LLM
     should include columns that MIGHT contain skill information, not just columns that ARE skills. -->



---

## Q11: Give me the list of employees from human capital department

**Full query:** "List all employees working in the Human Capital Department. For each employee, show: Employee Name, Employee ID, Organizational Unit/Section, Grade, Date of Joining, Years of Service/Tenure, and Division. Sort by employee ID ascending. Include total count at the end."

**Question type:** Medium — list employees in a specific department with specified display fields

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Department]]` | **Filter**: Filter for "Human Capital Department" (Rule 1) |
| 2 | `[Employee Master[Employee Name]]` | **Display**: Explicitly requested |
| 3 | `[Employee Master[Employee Number]]` | **Display**: "Employee ID" + sort key (Rule 4) |
| 4 | `[Employee Master[Organization Unit]]` | **Display**: "Organizational Unit/Section" explicitly requested |
| 5 | `[Employee Master[Grade]]` | **Display**: "Grade" explicitly requested |
| 6 | `[Employee Master[Date of Joining]]` | **Display + Calculation**: Explicitly requested, also needed for tenure |
| 7 | `[Employee Master[Division]]` | **Display**: Explicitly requested |

**Expected total: 7 columns**

### What should NOT be selected
- Employee Grade — "Grade" maps to the Grade column here. Selecting both Grade and Employee Grade is redundant (Rule 8). The question says "Grade" which is the pay grade
- Division is already requested — don't need Sector too
- No salary, no skills, no leave data — not requested

### YOUR NOTES
<!-- The LLM selected Grade (not Employee Grade). Do you agree? Grade = administrative pay grade, Employee Grade = specific rank. For an employee listing, which is more appropriate? -->



---

## Q12: Give me employees who speak chinese and have experience in AI

**Full query:** "Find all employees who have BOTH Chinese language skills AND any AI-related competency... For each employee show: Employee Name, Employee ID, Organizational Unit/Section, Department, Grade, Date of Joining, Years of Service, and list all their relevant skills..."

**Question type:** Medium — filter by skills + display specified attributes

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Name]]` | **Display**: Explicitly requested |
| 2 | `[Employee Master[Employee Number]]` | **Display**: "Employee ID" (Rule 4) |
| 3 | `[Employee Master[Organization Unit]]` | **Display**: "Organizational Unit/Section" explicitly requested |
| 4 | `[Employee Master[Department]]` | **Display**: Explicitly requested |
| 5 | `[Employee Master[Employee Grade]]` | **Display**: "Grade" explicitly requested |
| 6 | `[Employee Master[Date of Joining]]` | **Display + Calculation**: "Date of Joining" + needed for "Years of Service" |
| 7 | `[CV Employee Competencies[Technical Competency Name]]` | **Filter + Display**: The ONLY column that stores skills including languages and AI competencies. Needed both to filter (Chinese, AI) and to display the matching skills |
| 8 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | **LLM-reasonable**: Description says "Competancy Name: The name of a standard organizational competency being evaluated" — both columns relate to "competencies", the LLM can't distinguish organizational vs technical from descriptions alone |
| 9 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | **LLM-reasonable**: CV Responsibilities Summary description says "Used to identify the employee's historical project experience and industry background" — DIRECTLY relevant to finding "experience in AI" |

**Expected total: 9 columns**

### What should NOT be selected
- Division, Sector — not explicitly requested
- ADEO Experience (Years) — NOT in the prompt (phantom column)

### YOUR NOTES
<!-- WHY THE USER SAID TO INCLUDE Employee Competencies Rating AND CV Employee Work Experience:
     - Employee Competencies Rating: We know these are organizational competency evaluations
       (Digital Saviness, Entrepreneurship, etc.), NOT technical skills/languages. But the LLM
       sees "Competancy Name" and can't distinguish "organizational competency evaluation" from
       "technical skill" based on the description alone. Both this column and CV Employee
       Competencies have "Competenc" in their names/descriptions.
     - CV Employee Work Experience: We know it's job history, not skills. But its description
       explicitly says "Used to identify the employee's historical project experience and industry
       background" — this is DIRECTLY relevant to finding "experience in AI". The LLM sees this
       and reasonably selects it.
     
     Key insight: When the question asks for "experience in AI", the CV Employee Work Experience
     column's description literally says "identify the employee's historical project experience".
     The LLM would be wrong NOT to select it given that description. -->



---

## Q13a: How many sick leaves did employee 1136 take in 2025?

**Full query:** "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) in the year 2025. Count total number of sick leave days taken, list each leave record with start date, end date, and duration. Also include employee name and department if available."

**Question type:** Narrow — count sick leaves for a specific employee in a specific year

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity + Filter**: Filter by employee ID 1136 (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Display**: "include employee name" (Rule 4) |
| 3 | `[Employee Master[Department]]` | **Display**: "include... department if available" |
| 4 | `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]` | **Core data**: The ONLY struct that stores individual leave records. Select the combined name to get all inner fields: Leave Type (filter "Sick"), Leave Start Date (filter 2025), Leave End Date, Leave Duration (Days) (for counting), Approval Status |

**Expected total: 4 columns** (3 flat + 1 struct combined name)

### What should NOT be selected
- Sick Leave Taken (flat) — this is a summary total in Employee Master, NOT the individual leave records the question asks for. It also only covers "current period", not specifically 2025
- Entitlement Leaves — these are leave entitlements/balances, not actual leave records
- Approval Status — included automatically via the struct "all inner fields" rule, even though not explicitly asked. Acceptable overhead

### YOUR NOTES
<!-- The LLM selected the Employee Leave Details struct (combined name). This includes Approval Status which the question doesn't ask for. Is the struct all-inner-fields rule acceptable overhead here? Or should the prompt allow selective inner field selection? -->



---

## Q15: What projects did Employee 982 work on compared to Employee 1177?

**Full query:** "Find all project information for Employee ID 982 and Employee ID 1177. For each employee, show their name, employee ID, organizational unit/department, grade, and list ALL projects they have been involved in including project name, project role, start date, end date, and project status/description if available. Compare their project portfolios side by side."

**Question type:** Broad — compare two employees' project portfolios

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity + Filter**: Filter by IDs 982 and 1177 (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Identity + Display**: Show names (Rule 4) |
| 3 | `[Employee Master[Department]]` | **Display**: "organizational unit/department" requested |
| 4 | `[Employee Master[Organization Unit]]` | **Display**: "organizational unit/department" requested |
| 5 | `[Employee Master[Employee Grade]]` | **Display**: "grade" requested |
| 6 | `[Employee Objectives[Objective Name][Goal Plan Name][Objective Description][Goal Weighting][Goal Status][Objective Status][Workflow State]]` | **Core data**: Objective Name = project name, Objective Description = project description/status, Goal Plan Name = performance cycle. Objectives contain the formal project assignments |
| 7 | `[Employee Assignment History[Assignment Name][Position Title][Employee Grade][Assignment Start Date][Assignment End Date][Assignment Experience (Years & Months)]]` | **Core data**: Assignment Name = project/role name, Position Title = project role, Assignment Start/End Date = dates. Assignments capture the timeline of project involvement |
| 8 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | **LLM-reasonable**: CV Responsibilities Summary description says "A comprehensive list of duties and key projects managed or contributed to in previous roles" — DIRECTLY relevant to a "projects" question. The LLM sees "key projects" in the description and reasonably selects it |
| 9 | `[Employee Achievements[Customary Name][Manager OA Comments][Employee OA Comments]]` | **LLM-reasonable**: Description explicitly says it's "a critical source for discovering 'unstructured' project work, such as supporting other teams" — DIRECTLY relevant to finding projects. The LLM sees this description and should select it for a project comparison question |
| 10 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | **LLM-reasonable**: Description mentions "Competancy Name" which may include project-related competencies. The LLM may include it as potentially relevant to project work |

**Expected total: 10 columns** (5 flat + 5 struct combined names)

### What should NOT be selected
- CV Employee Achievements and Awards — these are awards from CV, not project assignments
- Employee Leave Details — not relevant to projects
- Salary, allowances — not relevant

### YOUR NOTES
<!-- WHY THE USER SAID TO INCLUDE CV Employee Work Experience, Employee Achievements, AND Employee Competencies Rating:
     - CV Employee Work Experience: We know it's PREVIOUS employer work history, not current
       projects. But the description says "A comprehensive list of duties and key projects managed
       or contributed to" — the LLM sees "key projects" and reasonably selects it for a project
       question. The description literally says "projects"!
     - Employee Achievements: We know these are performance review comments, not project assignments.
       But the description explicitly says "a critical source for discovering unstructured project
       work" — this is DIRECTLY relevant to a project question. The LLM would be wrong NOT to
       select it given that description.
     - Employee Competencies Rating: Both competency columns have "Competenc" in their names.
       The LLM can't distinguish which one is more relevant to "projects" from descriptions alone.
     
     Key insight: The Employee Achievements description is the strongest case — it literally says
     "critical source for discovering project work". The LLM MUST select it for a project question.
     The CV Employee Work Experience description also literally says "key projects". These are
     not arguable — the descriptions make them directly relevant. -->



---

## Q16: Which skills do they have in common?

**Full query:** "Find employees with IDs '0982' and '1177'. For each employee, return their name, employee ID, organizational unit, department, grade, and ALL their technical competencies/skills with competency ratings if available. Compare their skill sets side by side and identify any common skills they share."

**Question type:** Medium-Broad — compare skills between two specific employees

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity + Filter**: Filter by IDs 0982 and 1177 (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Identity + Display**: Show names (Rule 4) |
| 3 | `[Employee Master[Organization Unit]]` | **Display**: Explicitly requested |
| 4 | `[Employee Master[Department]]` | **Display**: Explicitly requested |
| 5 | `[Employee Master[Employee Grade]]` | **Display**: "grade" requested |
| 6 | `[CV Employee Competencies[Technical Competency Name]]` | **Core data**: The ONLY column storing technical skills/competencies. Needed to find common skills |
| 7 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | **Display**: "with competency ratings if available" — explicitly requested |
| 8 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | **LLM-reasonable**: CV Responsibilities Summary = "A comprehensive list of duties and key projects" — the LLM may see responsibilities as indicative of skills used in practice, relevant for a skill comparison question |
| 9 | `[Employee Objectives[Objective Name][Goal Plan Name][Objective Description][Goal Weighting][Goal Status][Objective Status][Workflow State]]` | **LLM-reasonable**: Objective Description may contain skill-related project goals. The LLM may include it for completeness when comparing "skill sets" |
| 10 | `[Employee Master[Division]]` | **LLM-reasonable**: Organizational context the LLM may include for completeness alongside Department and Organization Unit |
| 11 | `[Employee Master[Grade]]` | **LLM-reasonable**: The LLM sees both Grade and Employee Grade as potentially relevant — Grade as "administrative pay grade" may correlate with skill level |

**Expected total: 11 columns** (6 flat + 5 struct combined names)

### What should NOT be selected
- Salary, allowances — not relevant to skills comparison
- Employee Leave Details — not relevant to skills
- Entitlement Leaves — not relevant to skills

### YOUR NOTES
<!-- WHY THE USER SAID TO INCLUDE CV Employee Work Experience, Employee Objectives, Division, AND Grade:
     - CV Employee Work Experience: We know it's job history, not skills. But the description
       says "A comprehensive list of duties and key projects" — the LLM may see duties/responsibilities
       as indicative of skills used in practice. For a skill comparison, this is plausibly relevant.
     - Employee Objectives: We know these are performance goals, not skills. But Objective
       Description may contain skill-related project goals, and the LLM may include it for
       completeness when the question says "compare their skill sets".
     - Division: The LLM may include it as organizational context alongside Department and
       Organization Unit, since all three describe where the employee sits.
     - Grade: The LLM sees both Grade (pay grade) and Employee Grade (rank) and may select both
       as potentially relevant — Grade as "administrative pay grade" may correlate with skill level.
     
     Key insight: For Q16, the user's instruction to include these columns reflects the fact that
     the LLM operates on description signals, not domain knowledge. When the query says "compare
     their skill sets", the LLM should err on the side of inclusion for columns whose descriptions
     contain skill-relevant signals (responsibilities, objectives, organizational level). -->



---

## Q19: Compare their education background.

**Full query:** "Find education details for employees with IDs '0982' and '1177'. For each employee, return their name, employee ID, organizational unit, department, grade, and ALL education information including degree/certification name, field of study, institution/university name, start date, end date/graduation date, and any additional education-related fields available in the system. Compare their education backgrounds side by side."

**Question type:** Broad — comprehensive education comparison between two employees

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Number]]` | **Identity + Filter**: Filter by IDs 0982 and 1177 (Rule 4) |
| 2 | `[Employee Master[Employee Name]]` | **Identity + Display**: Show names (Rule 4) |
| 3 | `[Employee Master[Organization Unit]]` | **Display**: Explicitly requested |
| 4 | `[Employee Master[Department]]` | **Display**: Explicitly requested |
| 5 | `[Employee Master[Employee Grade]]` | **Display**: "grade" requested |
| 6 | `[Employee Master[Degree]]` | **Display**: "degree/certification name" — flat column for highest degree |
| 7 | `[Employee Master[Educational Institute]]` | **Display**: "institution/university name" — flat column for highest qualification institution |
| 8 | `[Employee Master[Major (Education)]]` | **Display**: "field of study" — flat column |
| 9 | `[Employee Master[Graduation Date]]` | **Display**: "graduation date" — flat column |
| 10 | `[Employee Qualification[Qualification Title][Educational Institute][GPA (Grade Point Average)][Study Start Date][Study End Date]]` | **Core data**: Structured qualification details — Qualification Title, Educational Institute, GPA, Study Start/End Dates |
| 11 | `[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]` | **Core data**: CV-based education history — CV Degree Name, CV Institution Name, CV Start/End Dates |

**Expected total: 11 columns** (9 flat + 2 struct combined names)

### What should NOT be selected
- Grade (administrative pay grade) — redundant with Employee Grade (Rule 8). The question says "grade" in the context of education attributes, not pay grade
- CV Employee Competencies — skills, not education
- Employee Competencies Rating — performance evaluations, not education
- Salary, allowances — not related to education
- Employee Previous Employer — work history, not education

### What about flat Degree/Institute/Major vs struct qualifications?
The flat columns show the **highest** degree/institution/major. The structs show **ALL**
qualifications/education entries. The question asks for "ALL education information",
so both are needed — the flat columns provide summary data, the structs provide detail.

### YOUR NOTES
<!-- The LLM selected both Grade AND Employee Grade. The question uses "grade" in the list of display attributes alongside name, ID, org unit, department — this is organizational context, not education "grade" (GPA). Should we exclude the flat Grade column? Or is it useful context? Also, is the flat Degree/Educational Institute/Major/Graduation Date redundant with the Employee Qualification and CV Education structs? -->



---

## Q28: Average Salary of Senior Specialist in ADEO

**Full query:** "Find all employees who have 'Senior Specialist' in their job title or position. For each employee, show: Employee Name, Employee ID, Grade, Position Title, Department, Division, Organizational Unit, Years of Service, and any salary-related fields... Calculate the average salary..."

**Question type:** Medium — filter by job title, display attributes, calculate average salary

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Name]]` | **Display**: Explicitly requested |
| 2 | `[Employee Master[Employee Number]]` | **Display**: "Employee ID" (Rule 4) |
| 3 | `[Employee Master[Job Title]]` | **Filter**: Filter for "Senior Specialist" in job title (Rule 1) |
| 4 | `[Employee Master[Position Title]]` | **Filter + Display**: Also filter for "Senior Specialist" in position + explicitly displayed |
| 5 | `[Employee Master[Department]]` | **Display**: Explicitly requested |
| 6 | `[Employee Master[Division]]` | **Filter + Display**: Filter for "ADEO" + explicitly displayed |
| 7 | `[Employee Master[Organization Unit]]` | **Display**: Explicitly requested |
| 8 | `[Employee Master[Employee Grade]]` | **Display**: "Grade" requested |
| 9 | `[Employee Master[Basic Salary]]` | **Calculation**: For average salary calculation |
| 10 | `[Employee Master[Total Entitlement Amount]]` | **Calculation**: Total compensation — the question says "any salary-related fields" (Rule 9: prefer totals over breakdowns) |
| 11 | `[Employee Master[Date of Joining]]` | **Calculation**: Needed for "Years of Service" computation |

**Expected total: 11 columns**

### What should NOT be selected
- Grade (administrative pay grade) — redundant with Employee Grade (Rule 8)
- Individual allowance breakdowns (Child, Housing, Phone, Social, Supplementary, etc.) — Rule 9: "Do NOT select breakdown columns when a total exists". Total Entitlement Amount covers this
- Sick Leave Taken — not requested
- CV data, competencies — not requested

### YOUR NOTES
<!-- The LLM selected both Grade and Employee Grade. For a salary analysis, the pay grade (Grade) might be more relevant since it maps to salary bands. But Employee Grade is the specific rank. Which one do you prefer? Also, should Basic Salary be included alongside Total Entitlement Amount? The question asks for "average salary" — which salary field should be used for the calculation? -->



---

## Q35: Who has the longest service in ADEO?

**Full query:** "Find the employee(s) with the longest years of service/tenure at ADEO. Return Employee Name, Employee ID, Position Title, Grade, Department, Division, Organizational Unit, Date of Joining, Years of Service/Tenure (calculated), and Gender. Sort by tenure descending..."

**Question type:** Medium — find longest-serving employees in ADEO

### Expected Columns

| # | Column (exact name the LLM should select) | Rationale |
|---|-------------------------------------------|-----------|
| 1 | `[Employee Master[Employee Name]]` | **Display**: Explicitly requested |
| 2 | `[Employee Master[Employee Number]]` | **Display**: "Employee ID" (Rule 4) |
| 3 | `[Employee Master[Position Title]]` | **Display**: Explicitly requested |
| 4 | `[Employee Master[Employee Grade]]` | **Display**: "Grade" explicitly requested |
| 5 | `[Employee Master[Department]]` | **Display**: Explicitly requested |
| 6 | `[Employee Master[Division]]` | **Filter + Display**: Filter for ADEO + explicitly displayed |
| 7 | `[Employee Master[Organization Unit]]` | **Display**: Explicitly requested |
| 8 | `[Employee Master[Date of Joining]]` | **Display + Calculation**: Explicitly requested + needed to calculate tenure |
| 9 | `[Employee Master[Gender]]` | **Display**: Explicitly requested |

**Expected total: 9 columns**

### What should NOT be selected
- ADEO Experience (Years) — NOT in the prompt (phantom column). Even if it were, Date of Joining is explicitly requested AND needed for calculation
- Grade (pay grade) — redundant with Employee Grade (Rule 8)
- Salary, allowances — not requested
- CV data, competencies — not requested
- Assignment Status, Person Type — not requested

### YOUR NOTES
<!-- The LLM selected these exact 9 columns. Note that ADEO Experience (Years) is a phantom column and not available. Date of Joining is the correct choice for computing tenure. Do you agree? -->



---

## Summary: Expected vs LLM Selection

| Q# | Question (short) | Expected Cols | LLM Names | LLM Trimmed | Key Differences |
|----|-------------------|---------------|------------|-------------|-----------------|
| 3b | Skills of employee 1137 | 7 | 4 | 3 | ⚠️ Updated: now includes 4 LLM-reasonable columns (Competency Rating, CV Summary, CV Work Exp, CV Education). LLM under-selected vs new expectation |
| 3 | Skills + details (expanded) | 12 | 13 | 9 | ⚠️ Updated: now includes CV Summary, CV Work Exp, CV Education. LLM over-selected on inner fields but under-selected on LLM-reasonable columns |
| 11 | Employees in HC dept | 7 | 7 | 7 | ✅ Match |
| 12 | Chinese + AI skills | 9 | 7 | 7 | ⚠️ Updated: now includes Competency Rating + CV Work Exp. LLM under-selected vs new expectation |
| 13a | Sick leaves for emp 1136 | 4 | 7 | 4 | ✅ Correct after trimming (struct rule) |
| 15 | Projects comparison | 10 | 17 | 7 | ⚠️ Updated: now includes CV Work Exp, Employee Achievements, Competency Rating. LLM under-selected vs new expectation |
| 16 | Common skills comparison | 11 | 11 | 7 | ⚠️ Updated: now includes CV Work Exp, Employee Objectives, Division, Grade. LLM trimmed count matches but column selection differs |
| 19 | Education comparison | 11 | 18 | 12 | ⚠️ LLM selected Grade + Employee Grade (redundant) + individual inner field names |
| 28 | Avg salary Senior Specialist | 11 | 12 | 12 | ⚠️ LLM selected Grade + Employee Grade (redundant) |
| 35 | Longest service in ADEO | 9 | 9 | 9 | ✅ Match |

### Recurring Issues to Discuss

1. **Grade vs Employee Grade redundancy** — The LLM frequently selects both. Rule 8 says "Do NOT select redundant columns". Should the prompt be more explicit about which one to prefer?

2. **Struct combined name vs individual inner field names** — The LLM sometimes selects BOTH the combined struct name (e.g. `[Employee Leave Details[Leave Type][Leave Duration]...]`) AND individual inner field names (e.g. `[Employee Leave Details[Leave Type]]`). This leads to inflated name counts. The struct rule says "include ALL inner fields" — selecting the combined name should be sufficient.

3. **Date of Joining for tenure** — ADEO Experience (Years) is a phantom column, so Date of Joining is the only option for computing tenure. The LLM consistently picks this correctly.

4. **Duplicate selections** — Q3b had a duplicate CV Competencies entry. This is a parsing issue, not a selection issue.

5. **Employee Performance struct** — This struct exists in the prompt but was never selected by the LLM for any question. It contains Performance Review Period, Final Rating Num, and Normalized Performance Rating. Is this ever relevant?

6. **LLM-reasonable vs domain-expert selection** — A key finding from this analysis: columns that a domain expert would exclude (e.g., Employee Competencies Rating for "skills" questions, CV Employee Work Experience for "project" questions) should actually be in the expected list because the LLM can only reason from column descriptions, not from domain knowledge. When descriptions contain overlapping signals (e.g., both columns mention "competency", or a description literally says "key projects"), the LLM should select both. The original "NOT selected" lists were based on what a human expert knows, not on what the LLM can reasonably infer. This is the core reason the user asked to include those columns.

---

## YOUR OVERALL NOTES

<!-- CORE PRINCIPLE: Expected column selections should be based on what the LLM CAN REASONABLY INFER
     from the prompt descriptions, not on what a domain expert knows the columns truly represent.
     
     When column descriptions contain overlapping signals (e.g., both columns mention "competency",
     or a description literally says "key projects"), the LLM should err on the side of inclusion.
     
     The distinction between "organizational competency evaluation" and "technical skill" is a
     human expert judgment that the LLM cannot make from column names/descriptions alone.
     
     Similarly, when a description says "A comprehensive list of duties and key projects managed
     or contributed to" (CV Employee Work Experience), the LLM should select it for a "projects"
     question — the description literally says "projects".
     
     And when a description says "a critical source for discovering unstructured project work"
     (Employee Achievements), the LLM MUST select it for a project question.
     
     This principle was the user's key insight: the original "NOT selected" columns were excluded
     based on domain knowledge, not based on what the LLM can reasonably infer from the prompt. -->

<!-- Use this space for cross-cutting observations, prompt improvement ideas, or anything else -->
