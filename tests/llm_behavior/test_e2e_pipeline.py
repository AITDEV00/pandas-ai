"""
End-to-End LLM Behavior Test — Exact Server Pipeline Replication
================================================================

This script replicates 1:1 the exact data flow from the chat-excel-server:

  1. REGISTER: Upload the Excel file + semantic model → get conversation_id
  2. CHAT: Send queries → monitor every step of the LLM interaction

It does NOT use the running server. Instead, it imports and calls the exact
same Python functions the server uses, with hooks to inspect intermediate
state at each step.

Usage:
    python tests/llm_behavior/test_e2e_pipeline.py

    # With custom file path:
    python tests/llm_behavior/test_e2e_pipeline.py --file /path/to/data.xlsx

    # Skip registration (reuse existing conversation):
    python tests/llm_behavior/test_e2e_pipeline.py --conv-id UUID

    # Multiple queries:
    python tests/llm_behavior/test_e2e_pipeline.py --queries "query1" "query2" "query3"
"""

import ast
import json
import os
import re
import sys
import time
import traceback
import urllib3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import openai

urllib3.disable_warnings()

# ── LLM Configuration (same as server .env) ────────────────────────────────
LLM_API_KEY = os.environ.get(
    "LLM_API_KEY", "sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8"
)
LLM_BASE_URL = os.environ.get(
    "LLM_BASE_URL",
    "https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
)
LLM_MODEL = os.environ.get(
    "LLM_MODEL_NAME", "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
)
LLM_CONTEXT_WINDOW = int(os.environ.get("LLM_CONTEXT_WINDOW", "250000"))

# ── Default file path ──────────────────────────────────────────────────────
DEFAULT_XLSX = "/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx"

# ── Semantic Model (from user's curl command) ──────────────────────────────
SEMANTIC_MODEL = {
    "name": "enterprise_data",
    "description": "Master dataset containing unflattened structs and employee records.",
    "columns": [
        {"name": "[CV Employee Achievements and Awards[CV Achievement Description]]", "type": "string", "description": "A description of the context or significance of the award/achievement."},
        {"name": "[CV Employee Achievements and Awards[CV Issue Date]]", "type": "datetime", "description": "The date when the award or achievement was granted."},
        {"name": "[CV Employee Achievements and Awards[CV Title]]", "type": "string", "description": "The title of a professional award or achievement listed on the employee's CV."},
        {"name": "[CV Employee Competencies[Technical Competency Name]]", "type": "string", "description": "A specific skill or competency listed related to the employee. This can include languages, hard skills, soft skills."},
        {"name": "[CV Employee Education[CV Degree Name]]", "type": "string", "description": "The name of a degree as self-reported on the employee's CV."},
        {"name": "[CV Employee Education[CV End Date]]", "type": "datetime", "description": "The end date of an education entry on the employee's CV."},
        {"name": "[CV Employee Education[CV Institution Name]]", "type": "string", "description": "The name of an educational institution as self-reported on the employee's CV."},
        {"name": "[CV Employee Education[CV Start Date]]", "type": "datetime", "description": "The start date of an education entry on the employee's CV."},
        {"name": "[CV Employee Interest and Hobbies[CV Interest Description]]", "type": "string", "description": "Details describing the nature or level of engagement in the hobby/interest."},
        {"name": "[CV Employee Interest and Hobbies[CV Interest Name]]", "type": "string", "description": "A specific hobby or personal interest listed on the employee's CV."},
        {"name": "[CV Employee Summary[CV Employee Summary]]", "type": "string", "description": "A professional profile summary or biography extracted from the employee's CV."},
        {"name": "[CV Employee Work Experience[CV Company Name]]", "type": "string", "description": "A company name listed in the work experience section of the employee's CV."},
        {"name": "[CV Employee Work Experience[CV End Date]]", "type": "datetime", "description": "The end date of a work experience entry on the CV."},
        {"name": "[CV Employee Work Experience[CV Job Title]]", "type": "string", "description": "A job title listed in the work experience section of the employee's CV."},
        {"name": "[CV Employee Work Experience[CV Responsibilities Summary]]", "type": "string", "description": "A summary of duties and responsibilities for a role listed on the employee's CV."},
        {"name": "[CV Employee Work Experience[CV Start Date]]", "type": "datetime", "description": "The start date of a work experience entry on the employee's CV."},
        {"name": "[Employee Achievements[Customary Name]]", "type": "string", "description": "The year of the performance cycle being evaluated."},
        {"name": "[Employee Achievements[Employee OA Comments]]", "type": "string", "description": "The employee's comments regarding the 'Overall Assessment' (OA) of the employee's performance."},
        {"name": "[Employee Achievements[Manager OA Comments]]", "type": "string", "description": "The manager's comments regarding the 'Overall Assessment' (OA) of the employee's performance."},
        {"name": "[Employee Assignment History[Assignment End Date]]", "type": "datetime", "description": "The date when a specific historical assignment ended."},
        {"name": "[Employee Assignment History[Assignment Experience (Years & Months)]]", "type": "float", "description": "The duration of experience gained during a specific assignment, expressed in years and months."},
        {"name": "[Employee Assignment History[Assignment Name]]", "type": "string", "description": "The name of a specific job assignment or role in the employee's history with the company."},
        {"name": "[Employee Assignment History[Assignment Start Date]]", "type": "datetime", "description": "The date when a specific historical assignment began."},
        {"name": "[Employee Assignment History[Employee Grade]]", "type": "string", "description": "The employee grade held during a specific historical assignment."},
        {"name": "[Employee Assignment History[Position Title]]", "type": "string", "description": "The position title held during a specific historical assignment."},
        {"name": "[Employee Competencies Rating[Competancy Name]]", "type": "string", "description": "The name of a standard organizational competency being evaluated (e.g., 'Digital Saviness', 'Entrepreneurship', 'Public Service Excellence', 'Learning Agility')."},
        {"name": "[Employee Competencies Rating[Employee Rating]]", "type": "string", "description": "The self-assessment score given by the employee for a specific competency."},
        {"name": "[Employee Competencies Rating[Employee Rating Description]]", "type": "string", "description": "The employee's written justification or comment supporting their self-rating."},
        {"name": "[Employee Competencies Rating[Supervisor Rating]]", "type": "string", "description": "The score given by the supervisor for the employee's competency during evaluation."},
        {"name": "[Employee Competencies Rating[Supervisor Rating Description]]", "type": "string", "description": "The supervisor's written justification or comment supporting their rating of the employee."},
        {"name": "[Employee Leave Details[Approval Status]]", "type": "string", "description": "The current processing status of the leave request (e.g., Approved, Pending, Rejected)."},
        {"name": "[Employee Leave Details[Leave Duration (Days)]]", "type": "float", "description": "The duration of the specific leave instance in days."},
        {"name": "[Employee Leave Details[Leave End Date]]", "type": "datetime", "description": "The end date of the specific leave record."},
        {"name": "[Employee Leave Details[Leave Start Date]]", "type": "datetime", "description": "The start date of the specific leave record."},
        {"name": "[Employee Leave Details[Leave Type]]", "type": "string", "description": "The category of a specific leave request (e.g., Annual, Sick, Emergency, Hajj)."},
        {"name": "[Employee Master[ADEO Experience (Years)]]", "type": "float", "description": "The number of years the employee has worked for ADEO."},
        {"name": "[Employee Master[Age]]", "type": "float", "description": "The employee's current age in years."},
        {"name": "[Employee Master[Assignment Status]]", "type": "string", "description": "The current employment status of the employee (e.g., Active, On Leave, Suspended, Terminated)."},
        {"name": "[Employee Master[Basic Salary]]", "type": "float", "description": "The fixed base compensation paid to the employee excluding any allowances, bonuses, or benefits."},
        {"name": "[Employee Master[Child Allowance]]", "type": "float", "description": "Financial support provided to the employee based on the number of eligible children."},
        {"name": "[Employee Master[Cost of Living Allowance]]", "type": "float", "description": "An allowance designed to offset the cost of living in a specific region or city."},
        {"name": "[Employee Master[Date of Joining]]", "type": "datetime", "description": "The date on which the employee officially commenced employment with the organization."},
        {"name": "[Employee Master[Degree]]", "type": "string", "description": "The highest academic degree level obtained by the employee (e.g., Bachelor's, Master's, PhD)."},
        {"name": "[Employee Master[Department]]", "type": "string", "description": "The specific functional team within a Sector or Division where the employee works."},
        {"name": "[Employee Master[Division]]", "type": "string", "description": "The highest operational division within the organization (e.g., Strategic Affairs, Operational Affairs)."},
        {"name": "[Employee Master[Educational Institute]]", "type": "string", "description": "The name of the university, college, or institution where the employee obtained their highest qualification."},
        {"name": "[Employee Master[Email Address]]", "type": "string", "description": "The corporate email address assigned to the employee for professional communication."},
        {"name": "[Employee Master[Employee Grade]]", "type": "string", "description": "The specific level or rank associated with the employee's current position."},
        {"name": "[Employee Master[Employee Name]]", "type": "string", "description": "The full legal name of the employee in English."},
        {"name": "[Employee Master[Employee Name (Arabic)]]", "type": "string", "description": "The full legal name of the employee in Arabic script."},
        {"name": "[Employee Master[Employee Number]]", "type": "string", "description": "A unique numeric or alphanumeric identifier assigned to the employee for system tracking."},
        {"name": "[Employee Master[Etihad Allowance]]", "type": "float", "description": "Allowance granted under the Etihad employment category policy."},
        {"name": "[Employee Master[Family Book Number]]", "type": "float", "description": "The unique reference number for the Family Book (Khulasat Al Qaid)."},
        {"name": "[Employee Master[Gender]]", "type": "string", "description": "The biological sex of the employee."},
        {"name": "[Employee Master[Grade]]", "type": "string", "description": "The administrative pay grade assigned to the employee."},
        {"name": "[Employee Master[Graduation Date]]", "type": "datetime", "description": "The date when the employee officially graduated from their educational institution."},
        {"name": "[Employee Master[Housing Allowance]]", "type": "float", "description": "Financial benefit provided to cover or subsidize the employee's accommodation expenses."},
        {"name": "[Employee Master[Job Title]]", "type": "string", "description": "The generic or rank title associated with the employee's role (e.g., 'Senior Specialist', 'Director', 'Assistant Advisor', 'Director General')."},
        {"name": "[Employee Master[Last Promotion Date]]", "type": "datetime", "description": "The date on which the employee received their most recent promotion."},
        {"name": "[Employee Master[Last Promotion Reason]]", "type": "string", "description": "The recorded reason or justification for the last promotion (e.g., Merit, Reorganization)."},
        {"name": "[Employee Master[Major (Education)]]", "type": "string", "description": "The specific field of study or major specialization of the employee's highest degree."},
        {"name": "[Employee Master[Marital Status]]", "type": "string", "description": "The current marital status of the employee (e.g., Married, Single)."},
        {"name": "[Employee Master[Nationality]]", "type": "string", "description": "The country of citizenship held by the employee."},
        {"name": "[Employee Master[Number of Children]]", "type": "string", "description": "The count of children dependent on the employee."},
        {"name": "[Employee Master[Number of Spouses]]", "type": "float", "description": "The number of spouses currently recorded for the employee."},
        {"name": "[Employee Master[Office Name]]", "type": "string", "description": "The organizational unit equivalent to a sector (e.g., DG Office, Chairman Protocol Office)"},
        {"name": "[Employee Master[Organization Unit]]", "type": "string", "description": "The most granular organizational business unit or section to which the employee belongs."},
        {"name": "[Employee Master[Passport Number]]", "type": "string", "description": "The unique alphanumeric identifier of the employee's passport."},
        {"name": "[Employee Master[Person Type]]", "type": "string", "description": "The employment category of the individual (e.g., Permanent Employee, Contractor, Intern, or Secondee)."},
        {"name": "[Employee Master[Phone Allowance]]", "type": "float", "description": "A monthly stipend to cover mobile phone usage for business purposes."},
        {"name": "[Employee Master[Phone Number]]", "type": "float", "description": "The primary contact telephone number for the employee."},
        {"name": "[Employee Master[Position Title]]", "type": "string", "description": "The specific official designation of the employee within the organizational structure, which may include specific team or functional identifiers."},
        {"name": "[Employee Master[Secondment Allowance]]", "type": "float", "description": "Allowance paid during a temporary assignment to another entity or location."},
        {"name": "[Employee Master[Sector]]", "type": "string", "description": "The intermediate organizational level situated between the Division and the Department."},
        {"name": "[Employee Master[Sick Leave Taken]]", "type": "float", "description": "The total number of sick leave days utilized by the employee in the current period."},
        {"name": "[Employee Master[Social Allowance]]", "type": "float", "description": "A government-mandated allowance typically provided to nationals, often based on marital status."},
        {"name": "[Employee Master[Special Contract Basic Salary]]", "type": "float", "description": "Base salary paid under a special employment contract."},
        {"name": "[Employee Master[Supervisor Name]]", "type": "string", "description": "The full name of the employee's direct manager."},
        {"name": "[Employee Master[Supplementary Allowance]]", "type": "float", "description": "An additional financial allowance provided to supplement the basic salary, often used to adjust total compensation."},
        {"name": "[Employee Master[Technical Special Allowance]]", "type": "float", "description": "An allowance granted to employees with specialized technical skills or for performing specific technical roles."},
        {"name": "[Employee Master[Time Since Last Promotion]]", "type": "float", "description": "The calculated duration (typically in months or years) since the last promotion occurred."},
        {"name": "[Employee Master[Total Entitlement Amount]]", "type": "float", "description": "The gross total of the basic salary plus all applicable allowances."},
        {"name": "[Employee Objectives[Goal Plan Name]]", "type": "string", "description": "The name of the performance cycle or period (e.g., 2023 Performance Objectives)."},
        {"name": "[Employee Objectives[Goal Status]]", "type": "string", "description": "The approval status of the goal plan (e.g., Approved)."},
        {"name": "[Employee Objectives[Goal Weighting]]", "type": "float", "description": "The numerical weight assigned to the objective as a percentage of the total goal."},
        {"name": "[Employee Objectives[Objective Description]]", "type": "string", "description": "Detailed context or requirements for the objective."},
        {"name": "[Employee Objectives[Objective Name]]", "type": "string", "description": "The title or short description of a specific performance goal or objective set for the employee."},
        {"name": "[Employee Objectives[Objective Status]]", "type": "string", "description": "The specific status of the individual objective (e.g., APPROVED)."},
        {"name": "[Employee Objectives[Workflow State]]", "type": "string", "description": "The current state of the objective within the performance workflow (e.g., COMPLETE)."},
        {"name": "[Employee Previous Employer[End Date]]", "type": "datetime", "description": "The end date of the employment period with the previous employer."},
        {"name": "[Employee Previous Employer[Previous Employer Name]]", "type": "string", "description": "The name of a company where the employee worked prior to joining the current organization."},
        {"name": "[Employee Previous Employer[Previous Job Title]]", "type": "string", "description": "The job title the employee held at their previous employer."},
        {"name": "[Employee Previous Employer[Start Date]]", "type": "datetime", "description": "The start date of the employment period with the previous employer."},
        {"name": "[Employee Qualification[Educational Institute]]", "type": "string", "description": "The institution that awarded the specific qualification."},
        {"name": "[Employee Qualification[GPA (Grade Point Average)]]", "type": "string", "description": "The grade point average or score achieved for the specific qualification."},
        {"name": "[Employee Qualification[Qualification Title]]", "type": "string", "description": "The name of a specific academic or professional qualification held by the employee."},
        {"name": "[Employee Qualification[Study End Date]]", "type": "datetime", "description": "The date when the employee completed the specific qualification."},
        {"name": "[Employee Qualification[Study Start Date]]", "type": "datetime", "description": "The date when the employee began studying for the specific qualification."},
        {"name": "[Entitlement Leaves[Annual Leave Entitlement]]", "type": "float", "description": "The total number of annual leave days (vacation) the employee is entitled to per year."},
        {"name": "[Entitlement Leaves[Approved Annual Leave]]", "type": "float", "description": "The number of annual leave days currently approved for the employee."},
        {"name": "[Entitlement Leaves[Approved Non-Mandatory Leave]]", "type": "float", "description": "The number of days of discretionary or non-statutory leave that have been approved and taken."},
        {"name": "[Entitlement Leaves[Approved Wellbeing Leave]]", "type": "float", "description": "The number of days of wellbeing/mental health leave that have been approved and taken."},
        {"name": "[Entitlement Leaves[Non-Mandatory Leave Entitlement]]", "type": "float", "description": "The total number of non-mandatory leave days allocated to the employee per year."},
        {"name": "[Entitlement Leaves[Wellbeing Leave Entitlement]]", "type": "float", "description": "The total number of wellbeing leave days allocated to the employee per year."},
    ],
}

# Default system prompt (from LLMConfigPayload)
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert data assistant. Use execute_sql_query for data retrieval "
    "and aggregation. For presenting results, write Python code: compute derived "
    "values, format strings, build conditional logic, and choose the best result "
    "type (string for answers, number for counts, dataframe for tables, plot for "
    "charts). Do not make assumptions about data formats without checking the "
    "vocabulary lists."
)

# Default test queries
DEFAULT_QUERIES = [
    "what is the percetage by different leave types did ayesha take?",
    "Find employees with the name 'Ayesha' and return their employee ID and full name.",
    "How many male and female employees are there? Give me the ratio.",
]


# ── Monitoring data structures ─────────────────────────────────────────────

@dataclass
class StepResult:
    """Captures the state at each pipeline step."""
    step_name: str
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    raw_output: Any = None
    error: Optional[str] = None


@dataclass
class QueryTestResult:
    """Results for a single query through the full pipeline."""
    query: str
    steps: List[StepResult] = field(default_factory=list)
    final_response: Any = None
    final_type: Optional[str] = None
    success: bool = False
    error: Optional[str] = None

    @property
    def llm_raw_response(self) -> Optional[str]:
        """Get the raw LLM response from the steps."""
        for step in self.steps:
            if step.step_name == "llm_response":
                return step.raw_output
        return None

    @property
    def extracted_code(self) -> Optional[str]:
        """Get the extracted code from the steps."""
        for step in self.steps:
            if step.step_name == "code_extraction":
                return step.raw_output
        return None

    @property
    def prompt_messages(self) -> Optional[list]:
        """Get the messages sent to the LLM."""
        for step in self.steps:
            if step.step_name == "llm_call":
                return step.details.get("messages")
        return None


# ── Monkey-patch hooks ─────────────────────────────────────────────────────

_original_lite_llm_call = None
_original_extract_code = None
_original_generate_code = None
_step_collector: List[StepResult] = []


def _install_hooks():
    """Install monkey-patches on PandasAI internals to capture intermediate state."""
    global _original_lite_llm_call, _original_extract_code, _original_generate_code

    from pandasai_litellm.litellm import LiteLLM
    from pandasai.llm.base import LLM
    from pandasai.core.code_generation.base import CodeGenerator

    # Hook 1: LiteLLM.call() — capture messages sent and raw response
    _original_lite_llm_call = LiteLLM.call

    def hooked_call(self, instruction, context=None):
        memory = context.memory if context else None
        messages = memory.to_openai_messages_for_chat() if memory else []
        user_prompt = instruction.to_string()
        messages_copy = list(messages)
        messages_copy.append({"role": "user", "content": user_prompt})

        _step_collector.append(StepResult(
            step_name="llm_call",
            timestamp=time.time(),
            details={
                "num_messages": len(messages_copy),
                "message_roles": [m["role"] for m in messages_copy],
                "user_prompt_length": len(user_prompt),
                "user_prompt_first_500": user_prompt[:500],
                "system_prompt": messages_copy[0]["content"][:300] if messages_copy and messages_copy[0]["role"] == "system" else None,
                "history_messages": len(messages_copy) - 2 if len(messages_copy) > 2 else 0,
            },
        ))

        # Also save the full messages for detailed inspection
        _step_collector.append(StepResult(
            step_name="llm_messages_full",
            timestamp=time.time(),
            raw_output=messages_copy,
        ))

        response = _original_lite_llm_call(self, instruction, context)

        _step_collector.append(StepResult(
            step_name="llm_response",
            timestamp=time.time(),
            details={
                "response_length": len(response) if response else 0,
                "response_first_300": (response or "")[:300],
            },
            raw_output=response,
        ))

        return response

    LiteLLM.call = hooked_call

    # Hook 2: LLM._extract_code() — capture extraction method used
    _original_extract_code = LLM._extract_code

    def hooked_extract_code(self, response, separator="```"):
        has_separator = separator in response
        has_marker = bool(
            re.search(r"---\s*\n\s*Code\s*:", response)
            or re.search(r"\n\s*Code\s*:\s*\n", response)
        )

        _step_collector.append(StepResult(
            step_name="code_extraction",
            timestamp=time.time(),
            details={
                "has_separator": has_separator,
                "has_code_marker": has_marker,
                "response_first_300": response[:300] if response else "",
            },
        ))

        try:
            code = _original_extract_code(self, response, separator)
            _step_collector.append(StepResult(
                step_name="code_extracted",
                timestamp=time.time(),
                raw_output=code,
                details={
                    "code_length": len(code),
                    "code_first_200": code[:200],
                },
            ))
            return code
        except Exception as e:
            _step_collector.append(StepResult(
                step_name="code_extraction_failed",
                timestamp=time.time(),
                error=str(e),
                details={
                    "exception_type": type(e).__name__,
                    "response_first_300": response[:300] if response else "",
                },
            ))
            raise

    LLM._extract_code = hooked_extract_code

    # Hook 3: CodeGenerator.generate_code — capture the prompt used
    _original_generate_code = CodeGenerator.generate_code

    def hooked_generate_code(self, prompt):
        prompt_str = prompt.to_string()
        _step_collector.append(StepResult(
            step_name="prompt_rendered",
            timestamp=time.time(),
            details={
                "prompt_length": len(prompt_str),
                "prompt_last_300": prompt_str[-300:],
            },
            raw_output=prompt_str,
        ))
        return _original_generate_code(self, prompt)

    CodeGenerator.generate_code = hooked_generate_code


def _uninstall_hooks():
    """Remove all monkey-patches."""
    from pandasai_litellm.litellm import LiteLLM
    from pandasai.llm.base import LLM
    from pandasai.core.code_generation.base import CodeGenerator

    if _original_lite_llm_call:
        LiteLLM.call = _original_lite_llm_call
    if _original_extract_code:
        LLM._extract_code = _original_extract_code
    if _original_generate_code:
        CodeGenerator.generate_code = _original_generate_code


# ── Registration (exact server flow) ───────────────────────────────────────

def register_file(
    file_path: str,
    semantic_model: dict,
    enrich_column_values: bool = True,
    auto_fill_descriptions: bool = False,
    column_selection_enabled: bool = False,
    column_selection_threshold: int = 30,
    column_values_budget_ratio: float = 0.10,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> tuple:
    """
    Replicates the /api/register/file endpoint exactly.

    Returns (conversation_id, agent, df) tuple.
    """
    import pandasai as pai
    from pandasai.helpers.type_determination import parse_json_array_columns
    from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
    from pydantic import ValidationError
    from server.core.llm_setup import create_litellm
    from server.features.register.handler import create_agent_from_file_path
    from server.features.register.models import (
        PandasAIConfigPayload, LLMConfigPayload, SemanticModelPayload,
    )

    print(f"\n{'='*70}")
    print(f"  STEP 0: REGISTER FILE")
    print(f"{'='*70}")
    print(f"  File: {file_path}")
    print(f"  Semantic model columns: {len(semantic_model.get('columns', []))}")
    print(f"  Enrich column values: {enrich_column_values}")
    print(f"  Auto-fill descriptions: {auto_fill_descriptions}")

    # Build the exact payloads the server uses
    semantic_model_payload = SemanticModelPayload(**semantic_model)
    config_payload = PandasAIConfigPayload(
        enrich_column_values=enrich_column_values,
        auto_fill_descriptions=auto_fill_descriptions,
    )
    llm_payload = LLMConfigPayload(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model_name=LLM_MODEL,
        system_prompt=system_prompt,
    )

    # Call the exact handler function
    result = create_agent_from_file_path(
        file_path,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        semantic_model=semantic_model_payload,
        pandasai_config=config_payload,
        llm_config=llm_payload,
    )

    print(f"  ✅ Registration complete!")
    print(f"  Conversation ID: {result.conversation_id}")
    print(f"  Extracted context columns: {len(result.extracted_context) if result.extracted_context else 0}")

    # Also get the agent from the store for direct access
    from server.core.agent_store import agent_store
    agent = agent_store.get_agent(result.conversation_id)

    return result.conversation_id, agent


# ── Chat query (exact server flow with monitoring) ─────────────────────────

def run_chat_query(
    agent,
    query: str,
    output_type: str = "string",
    column_selection_enabled: bool = False,
    column_selection_threshold: int = 30,
    column_values_budget_ratio: float = 0.10,
) -> QueryTestResult:
    """
    Send a chat query through the EXACT same path the server uses,
    with monitoring hooks at every step.

    Returns a QueryTestResult with detailed step-by-step information.
    """
    global _step_collector
    _step_collector = []  # Reset for this query

    result = QueryTestResult(query=query)

    print(f"\n{'='*70}")
    print(f"  CHAT QUERY: {query[:70]}...")
    print(f"  output_type: {output_type}")
    print(f"  column_selection_enabled: {column_selection_enabled}")
    print(f"{'='*70}")

    try:
        # Apply per-query config overrides (same as handler)
        _overrides = {}
        if column_selection_enabled is not None:
            _overrides["column_selection_enabled"] = agent._state.config.column_selection_enabled
            agent._state.config.column_selection_enabled = column_selection_enabled
        if column_selection_threshold is not None:
            _overrides["column_selection_threshold"] = agent._state.config.column_selection_threshold
            agent._state.config.column_selection_threshold = column_selection_threshold
        if column_values_budget_ratio is not None:
            _overrides["column_values_budget_ratio"] = agent._state.config.column_values_budget_ratio
            agent._state.config.column_values_budget_ratio = column_values_budget_ratio

        # Step: Memory state before query
        memory_count = agent._state.memory.count()
        memory_messages = agent._state.memory.all()
        print(f"\n  📝 Memory state: {memory_count} messages")
        if memory_messages:
            for i, msg in enumerate(memory_messages[-4:]):
                role = "USER" if msg["is_user"] else "ASST"
                content_preview = msg["message"][:80].replace("\n", " ")
                print(f"    [{i}] {role}: {content_preview}...")

        # Step: Determine chat vs follow_up
        is_follow_up = memory_count > 0
        print(f"\n  🔄 Using: {'follow_up()' if is_follow_up else 'chat()'}")

        try:
            # Use the exact same logic as handle_chat_query
            if is_follow_up:
                response = agent.follow_up(query, output_type=output_type)
            else:
                response = agent.chat(query, output_type=output_type)

            # Extract type
            actual_type = getattr(response, 'type', None) or output_type or "auto"
            if actual_type == "chart":
                actual_type = "plot"

            result.final_response = str(response) if response else None
            result.final_type = actual_type
            result.success = True

            print(f"\n  ✅ Query succeeded!")
            print(f"  Response type: {actual_type}")
            print(f"  Response: {str(response)[:200]}...")
            print(f"  Last code executed: {(agent.last_code_executed or '')[:200]}...")

        finally:
            # Restore overrides
            for attr, original_value in _overrides.items():
                setattr(agent._state.config, attr, original_value)

    except Exception as e:
        result.error = f"{type(e).__name__}: {str(e)}"
        result.success = False
        print(f"\n  ❌ Query FAILED: {type(e).__name__}: {str(e)}")
        traceback.print_exc()

    # Collect all step results
    result.steps = list(_step_collector)

    return result


# ── Analysis ────────────────────────────────────────────────────────────────

def analyze_step(result: QueryTestResult) -> None:
    """Print detailed analysis of each step in the pipeline."""
    print(f"\n{'─'*70}")
    print(f"  STEP-BY-STEP ANALYSIS: {result.query[:60]}...")
    print(f"{'─'*70}")

    for step in result.steps:
        status = "✅" if step.error is None else "❌"
        print(f"\n  {status} [{step.step_name}]")

        if step.details:
            for k, v in step.details.items():
                if isinstance(v, str) and len(v) > 100:
                    print(f"    {k}: {v[:100]}...")
                else:
                    print(f"    {k}: {v}")

        if step.error:
            print(f"    ERROR: {step.error}")

        if step.raw_output and step.step_name == "llm_response":
            raw = step.raw_output
            print(f"\n    ── RAW LLM RESPONSE (full) ──")
            print(f"    {raw[:500]}")
            if len(raw) > 500:
                print(f"    ... ({len(raw)} chars total)")

    # Summary
    print(f"\n  ── SUMMARY ──")
    print(f"  Success: {result.success}")
    print(f"  Final type: {result.final_type}")

    if result.llm_raw_response:
        raw = result.llm_raw_response
        has_fences = "```" in raw
        has_code_marker = bool(
            re.search(r"---\s*\n\s*Code\s*:", raw)
            or re.search(r"\n\s*Code\s*:\s*\n", raw)
        )
        print(f"  LLM format: {'fence' if has_fences else 'marker' if has_code_marker else 'unknown'}")
        print(f"  Has code fences (```): {has_fences}")
        print(f"  Has Code: marker: {has_code_marker}")

    if result.prompt_messages:
        msgs = result.prompt_messages
        print(f"  Messages sent to LLM: {len(msgs)}")
        for i, msg in enumerate(msgs):
            role = msg["role"]
            content_len = len(msg.get("content", ""))
            print(f"    [{i}] {role}: {content_len} chars")


def save_detailed_results(
    results: List[QueryTestResult],
    output_path: str,
):
    """Save detailed results to JSON for post-analysis."""
    output = []
    for r in results:
        entry = {
            "query": r.query,
            "success": r.success,
            "final_type": r.final_type,
            "final_response": r.final_response,
            "error": r.error,
            "steps": [],
        }
        for step in r.steps:
            step_data = {
                "step_name": step.step_name,
                "timestamp": step.timestamp,
                "details": step.details,
                "error": step.error,
            }
            if step.step_name in ("llm_response", "code_extracted"):
                step_data["raw_output"] = step.raw_output
            if step.step_name == "prompt_rendered":
                step_data["raw_output"] = step.raw_output
            if step.step_name == "llm_messages_full":
                step_data["messages"] = step.raw_output
            entry["steps"].append(step_data)
        output.append(entry)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  📁 Detailed results saved to: {output_path}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E Pipeline Test — Exact Server Replication")
    parser.add_argument("--file", default=DEFAULT_XLSX, help="Path to XLSX file")
    parser.add_argument("--conv-id", default=None, help="Skip registration, use existing conversation ID")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES, help="Queries to test")
    parser.add_argument("--output-type", default="string", help="Output type (default: string)")
    parser.add_argument("--no-enrich", action="store_true", help="Disable column value enrichment")
    parser.add_argument("--column-selection", action="store_true", help="Enable column selection step")
    parser.add_argument("--save", default=None, help="Save detailed results to JSON file")
    parser.add_argument("--skip-registration", action="store_true", help="Skip file registration (use for testing chat only)")
    args = parser.parse_args()

    print("=" * 70)
    print("  E2E PIPELINE TEST — EXACT SERVER REPLICATION")
    print(f"  File: {args.file}")
    print(f"  Queries: {len(args.queries)}")
    print(f"  Output type: {args.output_type}")
    print(f"  Column selection: {args.column_selection}")
    print(f"  Enrichment: {not args.no_enrich}")
    print("=" * 70)

    # Install monitoring hooks
    _install_hooks()
    print("\n  🔌 Monitoring hooks installed on PandasAI internals")

    all_results: List[QueryTestResult] = []

    try:
        # ── Step 1: Register file ──────────────────────────────────────
        agent = None
        conversation_id = args.conv_id

        if not args.skip_registration and not args.conv_id:
            if not os.path.exists(args.file):
                print(f"\n  ❌ File not found: {args.file}")
                print(f"  Please provide the correct path with --file")
                return

            conversation_id, agent = register_file(
                file_path=args.file,
                semantic_model=SEMANTIC_MODEL,
                enrich_column_values=not args.no_enrich,
                auto_fill_descriptions=False,
            )
        elif args.conv_id:
            from server.core.agent_store import agent_store
            agent = agent_store.get_agent(args.conv_id)
            if not agent:
                print(f"  ❌ Conversation ID not found: {args.conv_id}")
                return
            print(f"\n  Using existing conversation: {args.conv_id}")
        else:
            print(f"\n  ⚠️  Skipping registration — no agent available")
            return

        # ── Step 2: Run queries ────────────────────────────────────────
        for i, query in enumerate(args.queries):
            print(f"\n\n{'#'*70}")
            print(f"  QUERY {i+1}/{len(args.queries)}")
            print(f"{'#'*70}")

            result = run_chat_query(
                agent=agent,
                query=query,
                output_type=args.output_type,
                column_selection_enabled=args.column_selection if args.column_selection else False,
                column_selection_threshold=30,
                column_values_budget_ratio=0.10,
            )

            analyze_step(result)
            all_results.append(result)

            # Brief pause between queries
            if i < len(args.queries) - 1:
                time.sleep(2)

        # ── Step 3: Summary ────────────────────────────────────────────
        print(f"\n\n{'='*70}")
        print(f"  FINAL SUMMARY")
        print(f"{'='*70}")

        total = len(all_results)
        succeeded = sum(1 for r in all_results if r.success)
        failed = total - succeeded

        print(f"\n  Total queries: {total}")
        print(f"  Succeeded: {succeeded}")
        print(f"  Failed: {failed}")

        # Check for format issues
        fence_count = 0
        marker_count = 0
        no_code_count = 0

        for r in all_results:
            raw = r.llm_raw_response
            if raw:
                if "```" in raw:
                    fence_count += 1
                elif re.search(r"---\s*\n\s*Code\s*:", raw) or re.search(r"\n\s*Code\s*:\s*\n", raw):
                    marker_count += 1
                else:
                    no_code_count += 1

        print(f"\n  LLM Output Format:")
        print(f"    Code fences (```): {fence_count}")
        print(f"    Code: marker:      {marker_count}")
        print(f"    No code found:     {no_code_count}")

        # Per-query summary
        print(f"\n  Per-query results:")
        for i, r in enumerate(all_results):
            status = "✅" if r.success else "❌"
            raw = r.llm_raw_response or ""
            fmt = "fence" if "```" in raw else ("marker" if re.search(r"---\s*\n\s*Code\s*:", raw) or re.search(r"\n\s*Code\s*:\s*\n", raw) else "unknown")
            print(f"    {status} Q{i+1}: {r.query[:50]}... | type={r.final_type} | format={fmt}")

        # Save if requested
        if args.save:
            save_detailed_results(all_results, args.save)

    finally:
        # Always clean up hooks
        _uninstall_hooks()
        print(f"\n  🔌 Monitoring hooks removed")


if __name__ == "__main__":
    main()
