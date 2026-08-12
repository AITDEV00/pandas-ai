"""Structured code-generation response model (used with the instructor library).

DeepSeek-V4-Flash's *unbounded* chain-of-thought (``thinking`` mode) can enter a
reasoning loop and never emit code (the "hang" we observed on the 0731 build).
Turning thinking fully OFF removes the loop but collapses codegen quality because
the model no longer reasons through the SQL.

Structured codegen is the middle ground: we ask the model for a **bounded,
schema-constrained** response.  The structure follows three research-backed
prompt families (as implemented in the ``instructor`` library):

  1. **Plan-and-Solve** (Wang et al., arXiv:2305.04091) — ``reasoning_trace`` is
     NOT free-form prose; it is an explicit plan: extract the variables/columns
     involved → list the exact schema columns each maps to → state the
     SQL/dataframe steps.  A *plan* is compact and bounded, unlike verbatim
     chain-of-thought, which is what loops.
  2. **Chain-of-Verification / CoVe** (Dhuliawala et al., arXiv:2309.11495) —
     ``verification_checks`` generates 2-3 targeted, falsifiable questions about
     the plan (e.g. "does column X exist in the schema?") and answers each
     against the *provided* schema — a separate structured pass, not folded into
     free reasoning.
  3. **Program-of-Thought** (Chen et al., arXiv:2211.10435) — ``code`` reasons
     *in code*: it emits the intermediate SQL/dataframe steps inline so the model
     "thinks" in executable form rather than in prose, which eliminates
     hallucinated column references and yields fewer runtime errors.

Because these are structured fields validated by Pydantic, the model is forced to
complete all of them and stop. It gets the reasoning benefit of thinking-mode
without the unbounded loop.
"""

from typing import List

from pydantic import BaseModel, Field


class VerificationCheck(BaseModel):
    """A single targeted, falsifiable check in the CoVe-style verification pass."""

    question: str = Field(
        description=(
            "A precise, answerable question about the plan: e.g. 'Does column "
            "'Date of Joining' exist in the provided schema?', 'Is employee "
            "number 1137 filtered with an exact match?'"
        )
    )
    answer: str = Field(
        description=(
            "The answer, grounded ONLY in the provided schema/columns and the "
            "query. If the plan is wrong, say so explicitly and state the "
            "correction. 1-2 sentences."
        )
    )
    plan_ok: bool = Field(
        description=(
            "True if the check confirms the plan is correct on this point; "
            "False if it reveals an error that must be fixed in the code."
        )
    )


class CodeGenResult(BaseModel):
    """Structured code-generation output: Plan-and-Solve + CoVe + Program-of-Thought.

    Mirrors the expected response shape. ``code`` must be valid Python that
    declares a ``result`` dict (same contract as the raw generate path).
    """

    reasoning_trace: str = Field(
        default="",
        description=(
            "PLAN-AND-SOLVE: a short, explicit plan, NOT free-form reasoning. "
            "Format exactly as: (1) VARIABLES/columns the question needs; "
            "(2) the EXACT schema table+column each maps to (use the bracketed "
            "[Table[Column]] names verbatim); (3) the SQL/dataframe steps to "
            "carry out. 3-6 sentences max. Commit to a plan immediately."
        ),
    )
    verification_checks: List[VerificationCheck] = Field(
        default_factory=list,
        description=(
            "CHAIN-OF-VERIFICATION: 2-3 targeted falsifiable checks about the "
            "plan (schema column existence, filter correctness, result-type "
            "match). Answer each against the provided schema, and mark "
            "plan_ok=False for any that reveal a mistake."
        ),
    )
    code: str = Field(
        description=(
            "PROGRAM-OF-THOUGHT: the final Python code, reasoning IN code. Write "
            "the intermediate SQL/dataframe steps as actual statements (define "
            "intermediate DataFrames or SQL queries with clear names), then end "
            "by declaring the variable `result` as a dict: "
            "result = {'type': <type>, 'value': <value>}. Valid Python. "
            "No markdown fences, no prose explanations.\n"
            "HARD RULES: (1) Never use DuckDB reserved keywords as SQL aliases "
            "or CTE/table names (e.g. 'both', 'group', 'order', 'table', 'select', "
            "'from', 'where'); quote any such identifier or rename it. "
            "(2) Every struct field you access via rec[...] or df[...] must use "
            "the EXACT case and spelling of the bracketed [Table[Column]] name "
            "that you UNNESTed — no abbreviation, no truncation, no case drift, "
            "and NEVER extra or missing brackets (a key like "
            "'Employee Leave Details[Leave Type]' must have exactly one opening "
            "[ and one closing ] before the quote; do not type ']]' or '['). "
            "(e.g. if you aliased 'Date of Joining' as doj, use 'doj', never "
            "'do'). (3) Declare every variable before you reference it. "
            "(4) Date columns are stored as VARCHAR. If you pass a date column "
            "to a date function (EXTRACT, YEAR, DATE_PART, strftime, comparison "
            "to a date), CAST it first: EXTRACT(YEAR FROM CAST(rec['Leave Start "
            "Date'] AS DATE)) = 2025. Likewise CAST(... AS DATE) before any "
            "date arithmetic."
        )
    )

    @property
    def double_check(self) -> str:
        """Backward-compatible summary of the verification pass.

        Some callers expect the old single ``double_check`` string field. Keep it
        derivable from ``verification_checks`` so existing audit logging and the
        ``_last_structured_double_check`` attribute still work.
        """
        if not self.verification_checks:
            return ""
        lines = [
            f"Q: {c.question}\nA: {c.answer} (plan_ok={c.plan_ok})"
            for c in self.verification_checks
        ]
        return "\n".join(lines)

    class Config:
        extra = "ignore"