# Column Selection Blocker Analysis

**Date**: 2025-05-21  
**Author**: AI Agent (for human strategy review)  
**Current template**: v30 (`select_columns_v30.tmpl`)  
**Best template**: v24 (`select_columns_v24.tmpl`) — 92.3%  

---

## TL;DR — The Core Blocker

**The small LLM (Qwen3.5-35B-A3B-GPTQ-Int4) cannot reliably expand broad concepts across multiple struct groups using only abstract/generic prompt rules.** When a question says "skills", the LLM needs to recognize that skills information is spread across 5+ struct groups (competency names, competency ratings, work experience, education, professional summaries). Generic inference rules ("duties imply skills") and generic verification checks ("re-read each unselected struct") are insufficient — the LLM either stops after finding one matching struct group, or actively EXCLUDES relevant groups as "less direct".

**The breakthrough in v24 was SPECIFIC verification checks** that name the exact data categories to check for. However, these are domain-specific (they name HR concepts like "competency names, competency ratings, work experience/responsibilities, education, professional summaries, objectives/goals"), which the user has rejected as a strategy.

**CRITICAL CORRECTION**: Previous comparison scripts had WRONG expected values (especially for Q11). With the CORRECT expected values from `expected_column_selections.md`, v30 actually scores **91.2%** (not 56.0%), and v24 scores **92.3%**. The gap is only **1 question/1 column** — v30 is actually very close to v24!

---

## 1. Performance Summary (CORRECTED)

### Corrected Match Rates (using `expected_column_selections.md` as ground truth)

| Q# | Question (short) | Expected | v24 | v30 | Gap |
|----|-------------------|----------|-----|-----|-----|
| Q3b | Skills of employee 1137 | 7 | 7/7 (100%) ✅ | 7/7 (100%) ✅ | — |
| Q3 | Skills + details (expanded) | 12 | 11/12 (91.7%) | 10/12 (83.3%) | CV Education, CV Summary |
| Q11 | Employees in HC dept | 7 | 7/7 (100%) ✅ | 6/7 (85.7%) | Grade |
| Q12 | Chinese + AI skills | 9 | 9/9 (100%) ✅ | 9/9 (100%) ✅ | — |
| Q13a | Sick leaves for emp 1136 | 4 | 4/4 (100%) ✅ | 4/4 (100%) ✅ | — |
| Q15 | Projects comparison | 10 | 8/10 (80.0%) | 8/10 (80.0%) | Same misses! |
| Q16 | Common skills comparison | 11 | 7/11 (63.6%) | 8/11 (72.7%) | v30 BETTER! |
| Q19 | Education comparison | 11 | 11/11 (100%) ✅ | 11/11 (100%) ✅ | — |
| Q28 | Avg salary Senior Specialist | 11 | 11/11 (100%) ✅ | 11/11 (100%) ✅ | — |
| Q35 | Longest service in ADEO | 9 | 9/9 (100%) ✅ | 9/9 (100%) ✅ | — |
| **TOTAL** | | **91** | **84/91 (92.3%)** | **83/91 (91.2%)** | **1 col** |

### Key Finding: v30 is NOT massively regressed — it's 91.2%!

The previous "56.0%" and "50.5%" numbers were WRONG because the comparison script had incorrect expected values. The real gap between v24 and v30 is only 1 column out of 91.

---

## 2. Detailed Failure Analysis

### Q3: Missing CV Employee Education and CV Employee Summary

**Expected**: 12 columns  
**v24**: 11/12 (missing CV Employee Summary)  
**v30**: 10/12 (missing CV Employee Education AND CV Employee Summary)

**v24 reasoning**: "Included Work Experience to capture applied skills via responsibilities" — v24 includes Work Experience but misses Summary.

**v30 reasoning**: "Selected struct groups for skills (CV Employee Competencies, Employee Competencies Rating, CV Employee Work Experience for responsibilities)" — v30 also includes Work Experience but misses Education AND Summary.

**Why v30 misses Education**: The v30 prompt has generic inference patterns ("What someone DOES implies what they CAN DO") but doesn't explicitly connect education to skills. The v24 prompt has: "Education history → informs what knowledge and skills someone possesses" — a direct keyword-to-concept mapping.

**Why v30 misses Summary**: Same issue. v24 has "Competency names and ratings → directly describe skills" but doesn't explicitly map "professional summary" to skills either. The v24 verification checks say "verify you included ALL struct groups that contain: competency names, competency ratings, work experience/responsibilities, education, professional summaries, objectives/goals" — this explicit list forces the LLM to check for "professional summaries" and "education".

### Q11: Missing Grade (v30 only)

**Expected**: 7 columns including `[Employee Master[Grade]]`  
**v30 selected**: `[Employee Master[Employee Grade]]` but NOT `[Employee Master[Grade]]`

**v30 reasoning**: "Selected [Employee Master[Employee Grade]] over [Employee Master[Grade]] as it more precisely matches the context of employee rank."

**Why this matters**: The expected answer says Grade (administrative pay grade) should be included because the question says "Grade" without specifying which type. Both v24 and v30's Rule 10 EXCEPTION says to include BOTH when the term is ambiguous. But v30's LLM chose to interpret "Grade" as Employee Grade and excluded the pay grade column.

**v24 got this right**: v24 selected both Employee Grade AND Grade, following its own Rule 10.

### Q15: Both v24 and v30 miss 2 columns

**Expected**: 10 columns including Employee Achievements and Employee Competencies Rating  
**v24**: 8/10 (missing CV Employee Work Experience, Employee Competencies Rating)  
**v30**: 8/10 (missing Employee Achievements, Employee Competencies Rating)

**This is NOT a v24 vs v30 issue** — both versions miss different but overlapping sets. The core problem is that "project information" is an indirect concept that doesn't map cleanly to column names.

**Why both miss Employee Competencies Rating**: Neither prompt explicitly connects "competency ratings" to "projects". The v24 verification checks say "If the question mentions 'projects' → verify you included ALL struct groups that contain: objectives, assignment history, work experience, achievements, competency ratings" — this SHOULD trigger it, but the LLM doesn't follow through.

**Why v30 misses Employee Achievements**: The v30 prompt doesn't have domain-specific verification that says "achievements are relevant to projects". The v24 prompt's verification checks don't explicitly name "achievements" for project questions either — but v24's inference rules say "If a struct column's description or inner fields mention 'responsibilities', 'duties', 'projects', or 'achievements' → it is relevant to questions about skills, projects, or performance". This is a direct keyword-to-relevance mapping that v30 doesn't have.

### Q16: v30 is actually BETTER than v24

**Expected**: 11 columns  
**v24**: 7/11 (63.6%)  
**v30**: 8/11 (72.7%)

v30 includes Grade (which v24 doesn't), giving it a slight edge. Both miss CV Employee Work Experience, Division, and Employee Objectives. The question asks for "ALL their technical competencies/skills with competency ratings" — the LLM should expand "skills" across multiple struct groups but doesn't.

---

## 3. The v24 vs v30 Prompt Difference

### What v24 has that v30 doesn't:

1. **Specific inference rules** (domain-specific keyword mappings):
   - "If a struct column's description or inner fields mention 'responsibilities', 'duties', 'projects', or 'achievements' → it is relevant to questions about skills, projects, or performance"
   - "If a struct column's description or inner fields mention 'objectives' or 'goals' → it may contain project or performance information"
   - "When a question asks about 'skills' or 'competencies', work experience responsibilities are a KEY data source because they describe applied skills in practice — always check for struct groups containing 'responsibilities', 'duties', or 'work experience'"
   - "When a question asks about 'projects' or 'assignments', competency ratings may be relevant because competencies are often assessed in the context of project work — always check for struct groups containing 'ratings', 'competencies', or 'performance'"

2. **Specific verification checks** (domain-specific checklists):
   - "If the question mentions 'skills' or 'competencies' → verify you included ALL struct groups that contain: competency names, competency ratings, work experience/responsibilities, education, professional summaries, objectives/goals"
   - "If the question mentions 'projects' or 'assignments' → verify you included ALL struct groups that contain: objectives, assignment history, work experience, achievements, competency ratings"
   - "If the question mentions 'compare' or 'all' → verify you included ALL struct groups that could contain relevant information, not just the most obvious ones"

3. **HR-specific concept expansion**:
   - "Education history → informs what knowledge and skills someone possesses"
   - "Competency names and ratings → directly describe skills and proficiency levels"

### What v30 has that v24 doesn't:

1. **Generic inference patterns** (domain-agnostic):
   - "What someone or something DOES (duties, responsibilities, activities) implies what they CAN DO (skills, competencies, capabilities)"
   - "What someone or something HAS DONE (history, past records, outcomes) provides evidence of their capabilities"
   - "Evaluations and ratings OF a concept are directly relevant to questions ABOUT that concept"
   - "Summaries and objectives that reference a concept are relevant to that concept"
   - "Education and training records inform what knowledge someone possesses"
   - "When a concept is broad (e.g., 'skills', 'performance', 'quality'), it likely appears across MULTIPLE struct groups"
   - "If a struct column's description or inner fields semantically overlap with a concept in the question, the column is relevant"

2. **Worked Example 2** (Employee/Skills domain):
   - Demonstrates concept expansion across 7 struct groups for a "skills" question
   - Shows that even though only Competency Names directly matches "skills", inference patterns expand to include 5 additional struct groups
   - Explicitly names: Competency Names, Competency Ratings, Work Experience, Education, Professional Summary, Objectives

3. **Generic verification**: "re-read the description and inner fields of EACH struct group you did NOT select"

### The Critical Difference

v24's **specific verification checks** are essentially a **lookup table**: "if question mentions X, check for Y, Z, W". This is domain-specific but highly effective.

v30's **generic verification** is: "re-read each unselected struct group and check if any keyword relates to the question's concepts". This is domain-agnostic but relies on the LLM to (a) correctly identify the concepts, and (b) correctly map keywords to those concepts.

**The LLM fails at (b)**. It identifies "skills" as a concept but doesn't map "education" or "professional summary" to skills on its own — it needs to be TOLD that education relates to skills.

---

## 4. The Complete v30 Prompt (as rendered to the LLM)

Below is the COMPLETE prompt object for Q3 as rendered to the LLM. This is ~102K characters, mostly schema data. The instruction section is ~10K characters.

### 4a. Schema Section (~92K characters — same for ALL questions)

The schema section lists all 62 columns with their types, descriptions, and sample values. This is the same for every question. Key columns the LLM sees:

```
Table: enterprise_data (62 columns)
Description: Master dataset containing unflattened structs and employee records.

**FLAT COLUMNS:**

- "[CV Employee Summary[CV Employee Summary]]" (string: A professional profile summary or biography extracted from the employee's CV.)
- "[Employee Master[Age]]" (float: Current age in years)
- "[Employee Master[Assignment Status]]" (string: Employment status)
- "[Employee Master[Basic Salary]]" (float: Fixed base compensation)
- "[Employee Master[Child Allowance]]" (float: Support based on number of children)
- "[Employee Master[Cost of Living Allowance]]" (float: Regional cost of living offset)
- "[Employee Master[Date of Joining]]" (datetime: Official employment start date)
- "[Employee Master[Degree]]" (string: Highest academic degree level)
- "[Employee Master[Department]]" (string: Functional team within Sector/Division)
- "[Employee Master[Division]]" (string: Highest operational division)
- "[Employee Master[Educational Institute]]" (string: Institution of highest qualification)
- "[Employee Master[Email Address]]" (string: Corporate email)
- "[Employee Master[Employee Grade]]" (string: Specific level/rank of current position)
- "[Employee Master[Employee Name]]" (string: Full legal name in English)
- "[Employee Master[Employee Name (Arabic)]]" (string: Full legal name in Arabic)
- "[Employee Master[Employee Number]]" (string: Unique employee identifier)
- "[Employee Master[Family Book Number]]" (float: Family Book reference number)
- "[Employee Master[Gender]]" (string: Biological sex)
- "[Employee Master[Grade]]" (string: Administrative pay grade)
- "[Employee Master[Graduation Date]]" (datetime: Official graduation date)
- "[Employee Master[Housing Allowance]]" (float: Accommodation subsidy)
- "[Employee Master[Job Title]]" (string: Generic rank title)
- "[Employee Master[Last Promotion Date]]" (datetime: Date of most recent promotion)
- "[Employee Master[Last Promotion Reason]]" (string: Reason for last promotion)
- "[Employee Master[Major (Education)]]" (string: Field of study/major specialization)
- "[Employee Master[Marital Status]]" (string: Current marital status)
- "[Employee Master[Nationality]]" (string: Country of citizenship)
- "[Employee Master[Number of Children]]" (string: Count of dependent children)
- "[Employee Master[Office Name]]" (string: Organizational unit equivalent to a sector)
- "[Employee Master[Organization Unit]]" (string: Most granular business unit/section)
- "[Employee Master[Passport Number]]" (string: Passport identifier)
- "[Employee Master[Person Type]]" (string: Employment category)
- "[Employee Master[Phone Allowance]]" (float: Monthly mobile phone stipend)
- "[Employee Master[Phone Number]]" (float: Primary contact telephone)
- "[Employee Master[Position Title]]" (string: Specific official designation)
- "[Employee Master[Sector]]" (string: Intermediate level)
- "[Employee Master[Sick Leave Taken]]" (float: Total sick leave days in current period)
- "[Employee Master[Social Allowance]]" (float: Government-mandated allowance)
- "[Employee Master[Supervisor Name]]" (string: Direct manager's full name)
- "[Employee Master[Supplementary Allowance]]" (float: Additional allowance)
- "[Employee Master[Technical Special Allowance]]" (float: Specialized technical skills allowance)
- "[Employee Master[Time Since Last Promotion]]" (float: Duration since last promotion)
- "[Employee Master[Total Entitlement Amount]]" (float: Gross total salary + all allowances)
- "[Entitlement Leaves[Annual Leave Entitlement]]" (float: Annual leave days per year)
- "[Entitlement Leaves[Approved Annual Leave]]" (float: Approved annual leave days)
- "[Entitlement Leaves[Approved Non-Mandatory Leave]]" (float: Approved discretionary leave days)
- "[Entitlement Leaves[Approved Wellbeing Leave]]" (float: Approved wellbeing/mental health leave days)
- "[Entitlement Leaves[Non-Mandatory Leave Entitlement]]" (float: Non-mandatory leave days per year)
- "[Entitlement Leaves[Wellbeing Leave Entitlement]]" (float: Wellbeing leave days per year)
- "[CV Employee Competencies[Technical Competency Name]]" (string: Skills/competencies from CV)
- "[Employee Competencies Rating[...]]" (string: Combined competencies rating column)
- "[CV Employee Interest and Hobbies[...]]" (string: Combined interests column)
- "[CV Employee Achievements and Awards[...]]" (string: Combined achievements column)
- "[Employee Leave Details[...]]" (string: Combined leave details column)
- "[Employee Performance[...]]" (string: Combined performance column)
- "[Employee Achievements[...]]" (string: Combined achievements column)
- "[Employee Objectives[...]]" (string: Combined objectives column)
- "[Employee Qualification[...]]" (string: Combined qualification column)
- "[CV Employee Education[...]]" (string: Combined CV education column)
- "[Employee Assignment History[...]]" (string: Combined assignment history column)
- "[Employee Previous Employer[...]]" (string: Combined previous employer column)
- "[CV Employee Work Experience[...]]" (string: Combined CV work experience column)

**STRUCT COLUMNS:**

- "[CV Employee Competencies[Technical Competency Name]]": Skills/competencies from CV
  → "Technical Competency Name" (string, freetext)

- "[Employee Competencies Rating[...]]": Organizational competency evaluations
  → "Competancy Name" (string, categorical)
  → "Employee Rating" (string, categorical)
  → "Supervisor Rating" (string, categorical)
  → "Employee Rating Description" (string, categorical)
  → "Supervisor Rating Description" (string, categorical)

- "[CV Employee Interest and Hobbies[...]]": Hobbies/interests from CV
  → "CV Interest Name" (string, freetext)
  → "CV Interest Description" (string, categorical)

- "[CV Employee Achievements and Awards[...]]": Awards/achievements from CV
  → "CV Title" (string, freetext)
  → "CV Achievement Description" (string, categorical)
  → "CV Issue Date" (datetime)

- "[Employee Leave Details[...]]": Individual leave records
  → "Leave Type" (string, categorical)
  → "Leave Duration (Days)" (float)
  → "Approval Status" (string, categorical)
  → "Leave Start Date" (datetime)
  → "Leave End Date" (datetime)

- "[Employee Performance[...]]": Performance review ratings
  → "Performance Review Period" (string, categorical)
  → "Final Rating Num" (string, categorical)
  → "Normalized Performance Rating" (string, categorical)

- "[Employee Achievements[...]]": Performance cycle achievements/feedback
  → "Customary Name" (string, categorical)
  → "Manager OA Comments" (string, freetext)
  → "Employee OA Comments" (string, freetext)

- "[Employee Objectives[...]]": Performance goals/projects
  → "Objective Name" (string, freetext)
  → "Goal Plan Name" (string, categorical)
  → "Objective Description" (string, freetext)
  → "Goal Weighting" (float)
  → "Goal Status" (string, categorical)
  → "Objective Status" (string, categorical)
  → "Workflow State" (string, categorical)

- "[Employee Qualification[...]]": Academic/professional qualifications
  → "Qualification Title" (string, freetext)
  → "Educational Institute" (string, freetext)
  → "GPA (Grade Point Average)" (string, categorical)
  → "Study Start Date" (datetime)
  → "Study End Date" (datetime)

- "[CV Employee Education[...]]": Education entries from CV
  → "CV Institution Name" (string, freetext)
  → "CV Degree Name" (string, freetext)
  → "CV Start Date" (datetime)
  → "CV End Date" (datetime)

- "[Employee Assignment History[...]]": Historical job assignments
  → "Assignment Name" (string, freetext)
  → "Position Title" (string, freetext)
  → "Employee Grade" (string, categorical)
  → "Assignment Start Date" (datetime)
  → "Assignment End Date" (datetime)
  → "Assignment Experience (Years & Months)" (float)

- "[Employee Previous Employer[...]]": Prior employment
  → "Previous Employer Name" (string, freetext)
  → "Previous Job Title" (string, freetext)
  → "Start Date" (datetime)
  → "End Date" (datetime)

- "[CV Employee Work Experience[...]]": Work experience from CV
  → "CV Company Name" (string, freetext)
  → "CV Job Title" (string, freetext)
  → "CV Responsibilities Summary" (string, freetext)
  → "CV Start Date" (datetime)
  → "CV End Date" (datetime)
```

### 4b. Instruction Section (v30 — ~10K characters)

```
## STEP 1: ANALYZE THE QUESTION

Identify every concept the question asks about. For EACH concept, list ALL possible data sources that could contain information about it.

**A concept rarely maps to just one column.** Before selecting, ask: "What real-world data would contain information about this concept?" For example:
- "skills" or "competencies" → competency lists, competency ratings, job duties/responsibilities, work experience, education, professional summaries
- "projects" or "assignments" → objectives, assignment history, achievements, work experience, responsibilities
- "performance" → ratings, objectives, achievements, reviews, assessments
- "experience" → work history, assignments, tenure data, prior roles, previous employment

**Key inference patterns (apply these to ANY domain):**
- What someone or something DOES (duties, responsibilities, activities) implies what they CAN DO (skills, competencies, capabilities)
- What someone or something HAS DONE (history, past records, outcomes) provides evidence of their capabilities
- Evaluations and ratings OF a concept are directly relevant to questions ABOUT that concept
- Summaries and objectives that reference a concept are relevant to that concept
- Education and training records inform what knowledge someone possesses
- When a concept is broad (e.g., "skills", "performance", "quality"), it likely appears across MULTIPLE struct groups — do not assume one struct group is sufficient
- If a struct column's description or inner fields semantically overlap with a concept in the question, the column is relevant — even if its name doesn't match the concept's name

## STEP 2: SCAN ALL COLUMNS — Select every column that could be relevant

Go through EVERY column in the schema. For each column, decide: "Does this column's name or description relate to any concept in the question?"

**2A. Select explicitly requested columns** — columns whose names or descriptions directly match what the question asks for.

**2B. Select concept-expanding struct columns** — AFTER selecting explicitly requested columns, check EACH STRUCT column group one by one: does its description or inner field names/descriptions signal relevance to ANY concept in the question? If yes, include the entire struct group with all its inner fields.

**⚠️ Do NOT stop after finding one matching struct group.** A single concept often spans MULTIPLE struct groups. After including a matching struct, continue checking ALL remaining struct groups:
- "Skills" may appear in: competency names, competency ratings, work experience (responsibilities = skills in practice), education (knowledge base), professional summaries
- "Projects" may appear in: objectives, assignment history, work experience (CV projects), achievements
- "Experience" may appear in: work experience, assignment history, previous employer, tenure data

**Mandatory verification:** After your initial selection, re-read the description and inner fields of EACH struct group you did NOT select. If ANY keyword in the struct's description or inner field names relates to the question's concepts, ADD that struct group. Do not skip this check.

**Why struct columns matter:** Struct columns contain detailed, multi-field records that are often richer than flat columns. A struct group whose description or inner fields semantically relate to the question's concepts should be included — even if the struct's name doesn't directly match the question's wording. Always prefer including a relevant struct group over a single flat column.

**2C. Select flat columns that provide additional context** — flat columns whose descriptions mention the concept (e.g., a "professional summary" flat column for a "skills" question).

**When in doubt, include rather than exclude** — the code-generation step will ignore irrelevant data. Do NOT limit your selection to stay within a specific column count — select every column that could be relevant.

## STEP 3: APPLY SELECTION RULES

### When to INCLUDE

1. **Filtering** — Columns needed to apply filters the question specifies.
2. **Display** — Columns whose data the question explicitly asks to show.
3. **Calculation** — Raw data columns needed for any computation the question requests.
4. **Identity** — When the question refers to a specific entity, include BOTH the primary identifier AND the human-readable name.
5. **Struct groups** — When you include a struct column group, include ALL its inner fields. Select multiple struct groups if their descriptions each signal relevance.
6. **Summary + Detail** — When a question asks for comprehensive information about a concept, include BOTH summary/aggregate columns AND detail/breakdown columns that cover the same concept.
7. **Broad scope** — When the question asks for "ALL", "everything about", or "compare", err on the side of including more columns.

### When to EXCLUDE

8. **No concept match** — If a column's name and description do NOT relate to any concept in the question, exclude it.
9. **Demographic/context** — Exclude personal attributes (gender, nationality, marital status, contact info) unless the question specifically asks for them.
10. **Duplicate meaning** — If two columns have the SAME meaning, select ONLY the one that most precisely matches what the question asks for. EXCEPTION: if two columns could each be a valid interpretation of an ambiguous term in the question (e.g., "grade" could mean academic grade OR pay grade), include BOTH when the question does not specify which type.
11. **Redundant breakdowns** — CRITICAL: A TOTAL or AGGREGATE column makes its individual component columns REDUNDANT. Selecting both a total and all its components is like selecting both a sum and all its addends — the total already contains the same information. Do NOT select component/breakdown columns when a total column exists UNLESS the question specifically names those individual components. For example:
    - If "Total Entitlement Amount" exists → "Housing Allowance", "Social Allowance", "Child Allowance" etc. are REDUNDANT
    - If "Total Revenue" exists → "Product Revenue", "Service Revenue" are REDUNDANT
    - ONLY select breakdowns if the question explicitly asks for them by name
    - A request for "salary-related fields" or "any salary information" is satisfied by the TOTAL column — the total IS the salary field

---

## WORKED EXAMPLES

### Example 1: Supplier/Quality domain

**Question**: "Which suppliers have the highest quality rating?"

**Step 1 — Analyze**: Primary concept = "quality rating". Secondary = "suppliers". What data sources could contain quality information? Quality scores, defect rates, inspection results, compliance records, audit outcomes.

**Step 2A — Explicit**: `Supplier Name` (suppliers ✅), `Quality Score` (quality rating ✅).

**Step 2B — Struct columns** (check EACH struct group, do not stop after one match):
- `Inspection Records` struct (contains inspection results → quality measure ✅ INCLUDE)
- `Compliance Audits` struct (contains compliance records → quality measure ✅ INCLUDE)
- `Quality Dimensions` struct (contains individual dimension scores → covered by Total Quality Score, REDUNDANT per Rule 11)
- `Supplier Contact Info` struct (not quality-related ❌ EXCLUDE)
- `Product Catalog` struct (not quality-related ❌ EXCLUDE)

**Verification**: Review unselected structs — Supplier Contact Info and Product Catalog do not relate to quality. No additions needed.

**Step 2C — Flat context**: `Defect Count` (defects are a quality measure ✅), `Total Quality Score` (aggregate quality ✅).

**Step 3 — Apply rules**: Include Supplier Name, Quality Score, Inspection Records struct, Compliance Audits struct, Defect Count, Total Quality Score. Exclude Quality Dimensions struct (redundant breakdowns per Rule 11). Exclude address/phone (not relevant).

### Example 2: Employee/Skills domain (demonstrates concept expansion across multiple struct groups)

**Question**: "Show me all employees with AI skills and their competency details"

**Step 1 — Analyze**: Primary concept = "skills"/"competencies". What data sources could contain skill information? Competency lists (names of skills), competency ratings (proficiency levels), work experience (responsibilities describe applied skills), education (knowledge base), professional summaries.

**Step 2A — Explicit**: `Employee Name` (identity ✅), `Employee Number` (identity ✅).

**Step 2B — Struct columns** (check EACH struct group — skills span MULTIPLE groups):
- `Competency Names` struct (directly lists skills ✅ INCLUDE)
- `Competency Ratings` struct (rates skill proficiency ✅ INCLUDE — ratings of a concept are relevant to that concept)
- `Work Experience` struct (contains "Responsibilities" field → responsibilities describe what someone does, which implies their skills ✅ INCLUDE — applied skills in practice)
- `Education` struct (education informs knowledge and skills ✅ INCLUDE — knowledge base)
- `Professional Summary` struct (summarizes capabilities ✅ INCLUDE — summary of skills)
- `Objectives` struct (may reference skill development ✅ INCLUDE — references the concept)
- `Leave Details` struct (not skill-related ❌ EXCLUDE)
- `Contact Info` struct (not skill-related ❌ EXCLUDE)

**Key insight**: Even though only `Competency Names` directly matches "skills", the inference patterns from Step 1 expand the selection to include 5 additional struct groups. This is CORRECT — skills information is distributed across multiple data sources.

**Verification**: Review unselected structs — Leave Details and Contact Info do not relate to skills. No additions needed.

**Step 2C — Flat context**: `Job Title` (implies skills ✅), `Department` (context ✅).

**Step 3 — Apply rules**: Include all selected columns and struct groups. Exclude Leave, Contact (not relevant).
```

### 4c. Instruction Section (v24 — ~9K characters) — KEY DIFFERENCES HIGHLIGHTED

The v24 instruction section is identical to v30 EXCEPT for these critical differences:

**v24 Step 1 — "Important inference rules" (instead of "Key inference patterns"):**

```
**Important inference rules:**
- Job duties and responsibilities describe what someone does → they imply what skills they have
- Work experience entries contain job titles and responsibilities → they indicate skills used in practice
- Performance assessments and comments → may reference project work or skill demonstrations
- Education history → informs what knowledge and skills someone possesses
- Competency names and ratings → directly describe skills and proficiency levels
- If a struct column's description or inner fields mention "responsibilities", "duties", "projects", or "achievements" → it is relevant to questions about skills, projects, or performance
- If a struct column's description or inner fields mention "objectives" or "goals" → it may contain project or performance information
- When a question asks about "skills" or "competencies", work experience responsibilities are a KEY data source because they describe applied skills in practice — always check for struct groups containing "responsibilities", "duties", or "work experience"
- When a question asks about "projects" or "assignments", competency ratings may be relevant because competencies are often assessed in the context of project work — always check for struct groups containing "ratings", "competencies", or "performance"
```

**v24 Step 2 — "Specific verification checks" (NOT present in v30):**

```
**Specific verification checks:**
- If the question mentions "skills" or "competencies" → verify you included ALL struct groups that contain: competency names, competency ratings, work experience/responsibilities, education, professional summaries, objectives/goals
- If the question mentions "projects" or "assignments" → verify you included ALL struct groups that contain: objectives, assignment history, work experience, achievements, competency ratings
- If the question mentions "compare" or "all" → verify you included ALL struct groups that could contain relevant information, not just the most obvious ones
```

**v24 does NOT have the Worked Example 2** (Employee/Skills domain) that v30 has.

---

## 5. All Test Queries

| Q# | Full Query |
|----|-----------|
| Q3b | "What are the main skills of employee 1137?" |
| Q3 | "Find employee with ID 1137. Return their name, employee ID, organizational unit, department/division, grade, years of service, tenure, and all their technical competencies/skills. Include competency ratings if available." |
| Q11 | "List all employees working in the Human Capital Department. For each employee, show: Employee Name, Employee ID, Organizational Unit/Section, Grade, Date of Joining, Years of Service/Tenure, and Division. Sort by employee ID ascending. Include total count at the end." |
| Q12 | "Find all employees who have BOTH Chinese language skills AND any AI-related competency. For each matching employee show: Employee Name, Employee ID, Organizational Unit/Section, Department, Grade, Date of Joining, Years of Service, and list all their relevant skills and competencies that match the criteria. Sort by employee name." |
| Q13a | "Find all sick leave records for employee ID 1136 (Dr. Rahila Babar Asad) in the year 2025. Count total number of sick leave days taken, list each leave record with start date, end date, and duration. Also include employee name and department if available." |
| Q15 | "Find all project information for Employee ID 982 and Employee ID 1177. For each employee, show their name, employee ID, organizational unit/department, grade, and list ALL projects they have been involved in including project name, project role, start date, end date, and project status/description if available. Compare their project portfolios side by side." |
| Q16 | "Find employees with IDs '0982' and '1177'. For each employee, return their name, employee ID, organizational unit, department, grade, and ALL their technical competencies/skills with competency ratings if available. Compare their skill sets side by side and identify any common skills they share." |
| Q19 | "Find education details for employees with IDs '0982' and '1177'. For each employee, return their name, employee ID, organizational unit, department, grade, and ALL education information including degree/certification name, field of study, institution/university name, start date, end date/graduation date, and any additional education-related fields available in the system. Compare their education backgrounds side by side." |
| Q28 | "Find all employees who have 'Senior Specialist' in their job title or position. For each employee, show: Employee Name, Employee ID, Grade, Position Title, Department, Division, Organizational Unit, Years of Service, and any salary-related fields. Calculate the average salary of these employees." |
| Q35 | "Find the employee(s) with the longest years of service/tenure at ADEO. Return Employee Name, Employee ID, Position Title, Grade, Department, Division, Organizational Unit, Date of Joining, Years of Service/Tenure (calculated), and Gender. Sort by tenure descending." |

---

## 6. Expected Answers (from `expected_column_selections.md`)

### Q3b: What are the main skills of employee 1137? (7 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity: Filter by 1137 |
| 2 | `[Employee Master[Employee Name]]` | Identity: Human-readable name |
| 3 | `[CV Employee Competencies[Technical Competency Name]]` | Core: The ONLY column storing skills |
| 4 | `[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating][Employee Rating Description][Supervisor Rating Description]]` | LLM-reasonable: "Competancy Name" → skills |
| 5 | `[CV Employee Summary[CV Employee Summary]]` | LLM-reasonable: "professional profile summary" → skills |
| 6 | `[CV Employee Work Experience[CV Company Name][CV Job Title][CV Responsibilities Summary][CV Start Date][CV End Date]]` | LLM-reasonable: "responsibilities" → skills |
| 7 | `[CV Employee Education[CV Institution Name][CV Degree Name][CV Start Date][CV End Date]]` | LLM-reasonable: education → knowledge → skills |

### Q3: Find employee 1137, return all skills + ratings (12 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity + Filter |
| 2 | `[Employee Master[Employee Name]]` | Identity |
| 3 | `[Employee Master[Organization Unit]]` | Display: explicitly requested |
| 4 | `[Employee Master[Department]]` | Display: explicitly requested |
| 5 | `[Employee Master[Division]]` | Display: explicitly requested |
| 6 | `[Employee Master[Employee Grade]]` | Display: "grade" |
| 7 | `[Employee Master[Date of Joining]]` | Calculation: years of service |
| 8 | `[CV Employee Competencies[Technical Competency Name]]` | Core: technical competencies |
| 9 | `[Employee Competencies Rating[...]]` | Core: "Include competency ratings" |
| 10 | `[CV Employee Summary[CV Employee Summary]]` | LLM-reasonable: "ALL skills" + "professional summary" |
| 11 | `[CV Employee Work Experience[...]]` | LLM-reasonable: "responsibilities" → "ALL skills" |
| 12 | `[CV Employee Education[...]]` | LLM-reasonable: education → "ALL skills" |

### Q11: Employees in Human Capital Department (7 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Department]]` | Filter: "Human Capital Department" |
| 2 | `[Employee Master[Employee Name]]` | Display: explicitly requested |
| 3 | `[Employee Master[Employee Number]]` | Display: "Employee ID" + sort key |
| 4 | `[Employee Master[Organization Unit]]` | Display: "Organizational Unit/Section" |
| 5 | `[Employee Master[Grade]]` | Display: "Grade" — pay grade |
| 6 | `[Employee Master[Date of Joining]]` | Display + Calculation: tenure |
| 7 | `[Employee Master[Division]]` | Display: explicitly requested |

### Q12: Chinese + AI skills employees (9 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Name]]` | Display |
| 2 | `[Employee Master[Employee Number]]` | Display: "Employee ID" |
| 3 | `[Employee Master[Organization Unit]]` | Display |
| 4 | `[Employee Master[Department]]` | Display |
| 5 | `[Employee Master[Employee Grade]]` | Display: "Grade" |
| 6 | `[Employee Master[Date of Joining]]` | Display + Calculation |
| 7 | `[CV Employee Competencies[Technical Competency Name]]` | Filter + Display: skills |
| 8 | `[Employee Competencies Rating[...]]` | LLM-reasonable: "competency" → skills |
| 9 | `[CV Employee Work Experience[...]]` | LLM-reasonable: "experience in AI" → work history |

### Q13a: Sick leaves for employee 1136 (4 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity + Filter |
| 2 | `[Employee Master[Employee Name]]` | Display |
| 3 | `[Employee Master[Department]]` | Display: "department if available" |
| 4 | `[Employee Leave Details[Leave Type][Leave Duration (Days)][Approval Status][Leave Start Date][Leave End Date]]` | Core: individual leave records |

### Q15: Project comparison for employees 982 and 1177 (10 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity + Filter |
| 2 | `[Employee Master[Employee Name]]` | Identity + Display |
| 3 | `[Employee Master[Department]]` | Display |
| 4 | `[Employee Master[Organization Unit]]` | Display |
| 5 | `[Employee Master[Employee Grade]]` | Display: "grade" |
| 6 | `[Employee Objectives[...]]` | Core: project objectives |
| 7 | `[Employee Assignment History[...]]` | Core: project assignments |
| 8 | `[CV Employee Work Experience[...]]` | LLM-reasonable: "key projects" in description |
| 9 | `[Employee Achievements[...]]` | LLM-reasonable: "unstructured project work" in description |
| 10 | `[Employee Competencies Rating[...]]` | LLM-reasonable: "competency" → project context |

### Q16: Common skills for employees 0982 and 1177 (11 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity + Filter |
| 2 | `[Employee Master[Employee Name]]` | Identity + Display |
| 3 | `[Employee Master[Organization Unit]]` | Display |
| 4 | `[Employee Master[Department]]` | Display |
| 5 | `[Employee Master[Employee Grade]]` | Display: "grade" |
| 6 | `[CV Employee Competencies[Technical Competency Name]]` | Core: technical skills |
| 7 | `[Employee Competencies Rating[...]]` | Display: "competency ratings" |
| 8 | `[CV Employee Work Experience[...]]` | LLM-reasonable: responsibilities → skills |
| 9 | `[Employee Objectives[...]]` | LLM-reasonable: skill-related project goals |
| 10 | `[Employee Master[Division]]` | LLM-reasonable: org context alongside Dept/Org Unit |
| 11 | `[Employee Master[Grade]]` | LLM-reasonable: both grade columns for "grade" |

### Q19: Education comparison for employees 0982 and 1177 (11 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Number]]` | Identity + Filter |
| 2 | `[Employee Master[Employee Name]]` | Identity + Display |
| 3 | `[Employee Master[Organization Unit]]` | Display |
| 4 | `[Employee Master[Department]]` | Display |
| 5 | `[Employee Master[Employee Grade]]` | Display: "grade" |
| 6 | `[Employee Master[Degree]]` | Display: "degree/certification name" |
| 7 | `[Employee Master[Educational Institute]]` | Display: "institution/university name" |
| 8 | `[Employee Master[Major (Education)]]` | Display: "field of study" |
| 9 | `[Employee Master[Graduation Date]]` | Display: "graduation date" |
| 10 | `[Employee Qualification[...]]` | Core: structured qualification details |
| 11 | `[CV Employee Education[...]]` | Core: CV-based education history |

### Q28: Average salary of Senior Specialists (11 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Name]]` | Display |
| 2 | `[Employee Master[Employee Number]]` | Display: "Employee ID" |
| 3 | `[Employee Master[Job Title]]` | Filter: "Senior Specialist" in job title |
| 4 | `[Employee Master[Position Title]]` | Filter + Display |
| 5 | `[Employee Master[Department]]` | Display |
| 6 | `[Employee Master[Division]]` | Filter + Display |
| 7 | `[Employee Master[Organization Unit]]` | Display |
| 8 | `[Employee Master[Employee Grade]]` | Display: "Grade" |
| 9 | `[Employee Master[Basic Salary]]` | Calculation: average salary |
| 10 | `[Employee Master[Total Entitlement Amount]]` | Calculation: total compensation |
| 11 | `[Employee Master[Date of Joining]]` | Calculation: years of service |

### Q35: Longest-serving employee in ADEO (9 expected)

| # | Column | Rationale |
|---|--------|-----------|
| 1 | `[Employee Master[Employee Name]]` | Display |
| 2 | `[Employee Master[Employee Number]]` | Display: "Employee ID" |
| 3 | `[Employee Master[Position Title]]` | Display |
| 4 | `[Employee Master[Employee Grade]]` | Display: "Grade" |
| 5 | `[Employee Master[Department]]` | Display |
| 6 | `[Employee Master[Division]]` | Filter + Display |
| 7 | `[Employee Master[Organization Unit]]` | Display |
| 8 | `[Employee Master[Date of Joining]]` | Display + Calculation: tenure |
| 9 | `[Employee Master[Gender]]` | Display |

---

## 7. LLM Reasoning Comparison (v24 vs v30)

### Q3 — "Find employee with ID 1137...all their technical competencies/skills"

**v24 reasoning** (11/12 — missing CV Employee Summary):
> "Step 1: Concepts identified are Employee ID (1137), Name, Org Structure, Grade (Employee & Pay), Tenure/Service (Date of Joining, Assignment History), Skills/Competencies (CV Competencies, Work Experience Responsibilities), and Competency Ratings (Competency Rating Struct). Step 2: Selected flat columns for ID, Name, Org Structure, Grade, and Join Date. Selected Struct groups for Competencies (Technical Competency Name), Competency Ratings (all inner fields), Work Experience (Responsibilities Summary for skills in practice), and Assignment History (for tenure/grade history). Step 3: Included all struct inner fields as per rules. Included both Employee Grade and Grade columns as 'grade' is ambiguous. Included Date of Joining for tenure calculation. Included Work Experience to capture applied skills via responsibilities. Excluded financial and personal demographic columns as not requested."

**v30 reasoning** (10/12 — missing CV Employee Education AND CV Employee Summary):
> "Step 1: Concepts identified are Employee ID (filter), Name (identity), Organizational Unit/Department/Division (context), Grade (context), Tenure/Years of Service (calculation/history), Technical Competencies/Skills (detail), and Competency Ratings (detail). Step 2: Selected flat columns for identity ([Employee Number], [Name]), org structure ([Organization Unit], [Department], [Division], [Sector]), grade ([Employee Grade], [Grade]), and tenure start ([Date of Joining]). Selected struct groups for skills ([CV Employee Competencies], [Employee Competencies Rating], [CV Employee Work Experience] for responsibilities), tenure history ([Employee Assignment History]), and ratings. Step 3: Applied Rule 1 (Filtering) for Employee Number. Applied Rule 2 (Display) for Name, Org, Grade, Tenure, Skills. Applied Rule 5 (Struct groups) to include all inner fields of relevant struct groups. Excluded salary/allowance columns (Rule 8/9) as not requested. Included both Employee Grade and Grade columns as both represent 'grade' in different contexts."

**KEY DIFFERENCE**: v24 identifies "Skills/Competencies (CV Competencies, Work Experience Responsibilities)" and "Competency Ratings" as separate concept clusters. v30 identifies "Technical Competencies/Skills (detail)" and "Competency Ratings (detail)" as a single concept. v24 explicitly mentions "Work Experience (Responsibilities Summary for skills in practice)" — it maps responsibilities TO skills. v30 also maps work experience to skills ("CV Employee Work Experience for responsibilities") but doesn't include education.

### Q11 — "List all employees in Human Capital Department"

**v24 reasoning** (7/7 — 100%):
> "Step 1: The question requires filtering employees by 'Human Capital Department' and displaying specific attributes... Step 2: [Employee Master[Department]] is needed for filtering. [Employee Master[Employee Name]] for display. [Employee Master[Employee Number]] for ID display and sorting. [Employee Master[Organization Unit]] for the 'Organizational Unit/Section' requirement. [Employee Master[Grade]] and [Employee Master[Employee Grade]] are included to cover potential ambiguity in 'Grade' (Pay Grade vs. Job Grade). [Employee Master[Division]] for the Division requirement. [Employee Master[Date of Joining]] is needed for display and to calculate Tenure/Years of Service."

**v30 reasoning** (6/7 — missing Grade):
> "Step 1: The question requires filtering employees by 'Human Capital Department', displaying specific attributes (Name, ID, Unit, Grade, Join Date, Division), sorting by ID, and calculating tenure. Key concepts are Department (filter), Employee Name, Employee ID, Organizational Unit, Grade, Date of Joining (for Tenure), and Division. Step 2: [Employee Master[Employee Grade]] is selected for 'Grade' as it represents the job rank (more precise than the pay grade column)... Step 3: Selected [Employee Master[Employee Grade]] over [Employee Master[Grade]] as it more precisely matches the context of employee rank."

**KEY DIFFERENCE**: v24 follows Rule 10 EXCEPTION — includes BOTH Grade and Employee Grade because "grade" is ambiguous. v30 overrides Rule 10 with its own judgment that Employee Grade is "more precise" — this is the LLM making a domain judgment it shouldn't make.

### Q15 — "Find all project information for Employee 982 and 1177"

**v24 reasoning** (8/10 — missing CV Work Experience, Competency Rating):
> "Step 1: The question requires filtering by Employee ID (982, 1177), displaying employee details (Name, Org Unit, Department, Grade), and retrieving comprehensive project information... Step 2: Project data is not in a single flat column; it is distributed across struct groups. [Employee Objectives] contains current project goals. [Employee Assignment History] contains historical project/role assignments. [Employee Achievements] comments may contain additional project context."

**v30 reasoning** (8/10 — missing Employee Achievements, Competency Rating):
> "Step 1: The question requires employee identity, organizational context, and comprehensive project information... Step 2: Struct columns are selected for project data: [Employee Objectives] for current project names; [Employee Assignment History] for assignment/project names and roles; [CV Employee Work Experience] for historical project responsibilities; and [CV Employee Achievements and Awards] for project recognition."

**KEY DIFFERENCE**: v24 includes Employee Achievements (which has "project context" in its reasoning) but misses CV Work Experience and Competency Rating. v30 includes CV Work Experience (for "historical project responsibilities") and CV Achievements and Awards but misses Employee Achievements and Competency Rating. Neither includes ALL the expected struct groups. Both are missing Employee Competencies Rating.

### Q16 — "Find employees with IDs 0982 and 1177...ALL their technical competencies/skills"

**v24 reasoning** (7/11):
> "Step 1: The question asks for employee identification, organizational context, and detailed skills/competencies with ratings for comparison. Step 2: Flat columns cover identification and context. For skills, [CV Employee Competencies] provides the list of technical skills from the CV, and the [Employee Competencies Rating] struct provides the competency names and ratings... Step 3: Employee Grade is selected over Grade (pay grade) as it better matches the organizational context."

**v30 reasoning** (8/11):
> "Step 1: The question asks for specific employee identification, basic profile info, and detailed skill data. Step 2: I included both [Employee Master[Employee Grade]] (position rank) and [Employee Master[Grade]] (administrative pay grade) to ensure completeness given the ambiguity. For 'technical competencies', I included the struct [CV Employee Competencies] and its inner field. For 'competency ratings', I included the struct [Employee Competencies Rating]... I included both struct groups for skills because competencies span multiple data sources (CV vs Performance Ratings). I included both grade columns as per the 'when in doubt' rule."

**KEY DIFFERENCE**: v30 includes Grade (following Rule 10) while v24 doesn't. Both miss CV Work Experience, Division, Employee Objectives. The LLM in both versions doesn't expand "ALL their technical competencies/skills" to include work experience responsibilities, education, or objectives — despite the concept expansion instructions.

---

## 8. Root Cause Analysis

### Why does the LLM under-select struct groups?

1. **Zero-sum thinking**: The LLM treats concept expansion as a choice between alternatives rather than an additive process. When it finds CV Employee Competencies for "skills", it considers the "skills" concept satisfied and stops looking for more struct groups.

2. **"Less direct" exclusion**: The LLM actively EXCLUDES struct groups it considers "less direct" even when the prompt says "when in doubt, include". For example, v30's Q12 reasoning: "Excluded other structs (Education, Work Experience, Performance) as they are less direct for 'skills' than Technical Competencies".

3. **Verification step is not executed faithfully**: The "mandatory verification" step asks the LLM to re-read each unselected struct group, but the LLM's reasoning shows it often skips this or does a superficial check. The verification step adds ~0 tokens of actual re-reading — the LLM just says "I checked and they're not relevant" without genuinely reconsidering.

4. **Abstract inference patterns don't trigger**: The v30 patterns like "What someone DOES implies what they CAN DO" are too abstract. The LLM doesn't apply this pattern to map "CV Employee Education" → "skills" because the pattern doesn't contain the specific keywords "education" and "skills" in a direct mapping.

### What makes v24's specific verification checks work?

v24's verification checks are essentially a **lookup table embedded in the prompt**:

```
"skills" → [competency names, competency ratings, work experience/responsibilities, education, professional summaries, objectives/goals]
"projects" → [objectives, assignment history, work experience, achievements, competency ratings]
```

This is domain-specific because it names HR concepts. But it works because:
1. The LLM can pattern-match the question's keywords to the verification check's keywords
2. The verification check provides an EXHAUSTIVE list of data categories to check for
3. The LLM can then scan the schema for columns matching those categories

### The fundamental tension

- **Domain-specific verification checks** = highly effective but not generalizable
- **Generic inference patterns** = generalizable but not effective enough for a small LLM
- **Worked examples** = should bridge the gap but the LLM doesn't map abstract examples to real schema columns

---

## 9. Accumulated Prompt Engineering Lessons

| # | Lesson | Evidence |
|---|--------|----------|
| 1 | Fewer, clearer rules > more rules with nuanced guidance | Rule bloat caused regressions |
| 2 | "When in doubt, include" works better than "be precise" | Improves recall without hurting precision |
| 3 | Column count guidance causes artificial exclusion | Removing it improved scores |
| 4 | Rule 11 "redundant breakdowns" WORKS | Correctly prevents selecting individual allowances when Total Entitlement Amount exists |
| 5 | Generic inference rules (duties→skills) alone are INSUFFICIENT | v25-v30 all fail on concept expansion |
| 6 | Concrete lookup tables cause regressions by anchoring too narrowly | v27-v29 with explicit mappings |
| 7 | Specific verification checks help but may be domain-specific | v24's strength |
| 8 | Rule 10 EXCEPTION for ambiguous terms works | Both Grade columns selected when "grade" is ambiguous |
| 9 | Over-selection is a real concern but under-selection is the bigger problem | All versions have more EXTRA than MISSING |
| 10 | Concept expansion examples MUST use the same vocabulary as the questions | v29/v30 examples didn't match real schema names |
| 11 | Removing concept expansions entirely causes massive regression (92.3% → 64.8%) | v25 had no expansions |
| 12 | 6 abstract data source categories HURT performance | v27-v29 with "6 source types" |
| 13 | Generic verification checks don't work as well as specific ones | v30 vs v24 |
| 14 | The LLM actively EXCLUDES relevant struct groups even when told not to stop after one match | Q12 reasoning in v29/v30 |
| 15 | Worked examples don't help because the LLM doesn't map abstract examples to real schema columns | v30's Example 2 had no effect |
| 16 | The comparison script had WRONG expected values — all previous scores were inaccurate | Q11 expected was completely wrong |
| 17 | v30 is actually 91.2%, NOT 56.0% — the gap to v24 is only 1 column | Corrected comparison |

---

## 10. Potential Strategy Directions (for human review)

### Direction A: Extract verification checks from the schema at runtime

Instead of hardcoding "skills → [competency names, competency ratings, work experience, education, professional summaries]", generate these mappings dynamically from the schema's descriptions. For example:
- Scan all struct group descriptions for keywords
- When the question mentions "skills", find all struct groups whose descriptions contain skill-related keywords
- Generate a specific verification checklist based on the actual schema

**Pros**: Domain-agnostic, adapts to any schema  
**Cons**: Requires code changes in column_selector.py, adds complexity

### Direction B: Two-pass LLM call

1. First call: "Given this question and schema, list ALL concepts and their possible data sources"
2. Second call: "Given these concepts and data sources, select all relevant columns"

**Pros**: Forces the LLM to do concept expansion before selection  
**Cons**: Doubles LLM calls, may not fix the core problem

### Direction C: Struct group relevance scoring

Add a step where the LLM scores each struct group's relevance (0-10) before deciding to include/exclude. This forces explicit evaluation of each group.

**Pros**: Prevents "I checked and they're not relevant" without genuine consideration  
**Cons**: Adds token cost, may still produce low scores for genuinely relevant groups

### Direction D: Schema-aware concept expansion in code

In `column_selector.py`, before building the prompt, analyze the question for concept keywords and pre-expand them into a list of relevant struct groups based on the schema's descriptions. Then inject this list into the prompt as a "pre-computed relevance map".

**Pros**: Takes the concept expansion burden off the LLM entirely  
**Cons**: Requires semantic matching logic in code, may be brittle

### Direction E: Chain-of-thought with forced enumeration

Require the LLM to enumerate EVERY struct group by name and explicitly state "INCLUDE" or "EXCLUDE" with a one-word reason. This prevents skipping.

**Pros**: Forces the LLM to evaluate each struct group  
**Cons**: Long output, adds token cost, may still produce wrong reasons

### Direction F: Accept v30 at 91.2% and focus on the remaining gaps

The gap is only 1 column (Q3's CV Employee Education, Q11's Grade). Maybe targeted fixes for these specific patterns are acceptable.

**Pros**: 91.2% is very good, minimal effort  
**Cons**: Doesn't address the fundamental problem for future schemas

---

## 11. Full Rendered Prompt (Q3 example — v30)

The complete rendered prompt for Q3 is ~102K characters. The schema section (~92K) is the same for all questions. Below is the full prompt structure:

```
[SYSTEM INSTRUCTION - ~50 chars]
You are a data analyst. Given a user question and a table schema, select the columns/fields needed to answer the question.

[SCHEMA - ~92K chars]
Table: enterprise_data (62 columns)
Description: Master dataset containing unflattened structs and employee records.

**FLAT COLUMNS:**
[62 flat columns with types, descriptions, sample values]

**STRUCT COLUMNS (each has inner fields you can select individually):**
[13 struct groups with inner field details]

---

[INSTRUCTION - ~10K chars]
## STEP 1: ANALYZE THE QUESTION
[...full v30 instruction section as shown in Section 4b above...]

**User question:** Find employee with ID 1137. Return their name, employee ID, organizational unit, department/division, grade, years of service, tenure, and all their technical competencies/skills. Include competency ratings if available.

Respond in JSON format:
{
  "selected": ["Column Name 1", "Column Name 2", ...],
  "reasoning": "Step 1: [...]. Step 2: [...]. Step 3: [...]."
}
```

**Note**: The full rendered prompts are saved at:
- `/tmp/v30_Q3_full_prompt.txt` — v30 prompt for Q3
- `/tmp/v30_Q12_full_prompt.txt` — v30 prompt for Q12
- `/tmp/v30_Q3b_full_prompt.txt` — v30 prompt for Q3b
- `/tmp/v24_Q3_full_prompt.txt` — v24 prompt for Q3

These can be read directly for the exact character-by-character prompt the LLM receives.

---

## 12. LLM Configuration

```
Model: Qwen3.5-35B-A3B-GPTQ-Int4
Served by: vllm (OpenAI-compatible API)
Temperature: 0.6
Top P: 0.95
Top K: 20
JSON mode: True (forced structured output)
Max tokens: 4096
```

**Implications of this LLM**:
- **Small model** (35B parameters, 4-bit quantized) — limited reasoning capacity
- **Temperature 0.6** — some randomness but mostly deterministic
- **JSON mode** — forces structured output, may limit chain-of-thought length
- **Max 4096 tokens** — limits how much reasoning the LLM can produce
- **No system message** — the entire prompt is a single user message
