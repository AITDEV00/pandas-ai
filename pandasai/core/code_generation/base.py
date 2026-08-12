import time
import traceback

from pandasai.agent.state import AgentState
from pandasai.core.prompts.base import BasePrompt

from .code_cleaning import CodeCleaner
from .code_validation import CodeRequirementValidator
from .structural_validator import StructuralCodeValidator


class CodeGenerator:
    def __init__(self, context: AgentState):
        self._context = context
        self._code_cleaner = CodeCleaner(self._context)
        self._code_validator = CodeRequirementValidator(self._context)
        # Deterministic, schema-driven self-review that catches fabricated or
        # garbled schema identifiers (struct names, aliases, placeholders) that
        # the LLM would otherwise only discover at execution time.
        self._structural_validator = self._build_structural_validator()

    def generate_code(self, prompt: BasePrompt) -> str:
        """
        Generates code using a given LLM and performs validation and cleaning steps.

        Args:
            prompt (BasePrompt): The prompt to guide code generation.

        Returns:
            str: The final cleaned and validated code.

        Raises:
            Exception: If any step fails during the process.
        """
        step_timings = {}
        try:
            # Build per-call sampling params for code generation.
            # These override the LLM's default settings for this call only.
            sampling_params = self._get_sampling_params()

            # Generate the code
            _t0 = time.monotonic()
            code = self._context.config.llm.generate_code(prompt, self._context, sampling_params=sampling_params)
            step_timings["llm_call_s"] = round(time.monotonic() - _t0, 3)
            # Store the original generated code (for logging purposes)
            self._context.last_code_generated = code
            # Capture the raw LLM response for code generation debug logging
            raw_response = getattr(self._context.config.llm, '_last_raw_response', None)
            if raw_response is not None:
                self._context.code_generation_raw_llm_response = raw_response
            # Capture the LLM thinking / reasoning trace (if the model exposed
            # one) so the conversation log can show WHY the model chose this
            # code — invaluable for diagnosing code-generation bugs.
            thinking = getattr(self._context.config.llm, '_last_thinking_trace', None)
            if thinking is not None:
                self._context.code_generation_thinking_trace = thinking
            # Capture the structured reasoning/double-check sections (when
            # structured codegen is enabled) for audit in the conversation log.
            sr = getattr(self._context.config.llm, '_last_structured_reasoning', None)
            if sr:
                self._context.code_generation_structured_reasoning = sr
            sc = getattr(self._context.config.llm, '_last_structured_double_check', None)
            if sc:
                self._context.code_generation_structured_double_check = sc
            svc = getattr(
                self._context.config.llm, '_last_structured_verification_checks', None)
            if svc:
                self._context.code_generation_structured_verification_checks = svc
            self._context.logger.log(f"Code Generated:\n{code}")

            # Validate and clean the code (timed in sub-steps inside
            # validate_and_clean_code, which keeps the public entry point
            # intact so callers can mock it).
            cleaned_code = self.validate_and_clean_code(code, step_timings)
            # Update with the final cleaned code (for subsequent processing and multi-turn conversations)
            self._context.last_code_generated = cleaned_code

            step_timings["total_s"] = round(
                step_timings["llm_call_s"] + step_timings.get("validation_s", 0.0), 3
            )
            self._context.code_generation_step_timings.append(step_timings)

            return cleaned_code

        except Exception as e:
            error_message = f"An error occurred during code generation: {e}"
            stack_trace = traceback.format_exc()

            self._context.logger.log(error_message)
            self._context.logger.log(f"Stack Trace:\n{stack_trace}")

            raise e

    def _get_sampling_params(self) -> dict | None:
        """Build per-call sampling params from config for code generation.

        Returns None if no code-generation-specific params are configured,
        so the LLM's default settings are used.
        """
        cfg = self._context.config
        params = {}
        if getattr(cfg, "code_generation_temperature", None) is not None:
            params["temperature"] = cfg.code_generation_temperature
        if getattr(cfg, "code_generation_top_p", None) is not None:
            params["top_p"] = cfg.code_generation_top_p
        if getattr(cfg, "code_generation_top_k", None) is not None:
            params["top_k"] = cfg.code_generation_top_k
        if getattr(cfg, "code_generation_min_p", None) is not None:
            params["min_p"] = cfg.code_generation_min_p
        if getattr(cfg, "code_generation_repetition_penalty", None) is not None:
            params["repetition_penalty"] = cfg.code_generation_repetition_penalty
        if getattr(cfg, "code_generation_presence_penalty", None) is not None:
            params["presence_penalty"] = cfg.code_generation_presence_penalty
        # Bounds the output so a runaway generation cannot loop indefinitely
        # (a key cause of multi-hundred-second latencies on complex questions).
        if getattr(cfg, "code_generation_max_tokens", None) is not None:
            params["max_tokens"] = cfg.code_generation_max_tokens
        return params if params else None

    def validate_and_clean_code(self, code: str, step_timings: dict | None = None) -> str:
        # Validate code requirements
        self._context.logger.log("Validating code requirements...")
        _t1 = time.monotonic()
        if not self._code_validator.validate(code):
            raise ValueError("Code validation failed due to unmet requirements.")
        if step_timings is not None:
            step_timings["code_validation_s"] = round(time.monotonic() - _t1, 3)
        self._context.logger.log("Code validation successful.")

        # Deterministic self-review: replay the schema-name checks against the
        # generated code. If the code fabricated a struct column name, a struct
        # field key, left a placeholder, or drifted an alias, we raise a precise,
        # targeted error NOW so the retry prompt receives it — instead of only
        # discovering it at execution time (and re-using a wasted retry).
        _t2 = time.monotonic()
        self._run_structural_self_review(code)
        if step_timings is not None:
            step_timings["structural_review_s"] = round(time.monotonic() - _t2, 3)

        # Clean the code
        self._context.logger.log("Cleaning the generated code...")
        _t3 = time.monotonic()
        cleaned_code = self._code_cleaner.clean_code(code)
        if step_timings is not None:
            step_timings["cleaning_s"] = round(time.monotonic() - _t3, 3)
            step_timings["validation_s"] = round(
                step_timings["code_validation_s"]
                + step_timings["structural_review_s"]
                + step_timings["cleaning_s"], 3
            )
        return cleaned_code

    def _run_structural_self_review(self, code: str) -> None:
        """Run the deterministic structural self-review over generated code.

        Raises a ValueError describing the exact problems found. The retry
        loop in the agent picks this up and feeds it back to the LLM as the
        error message, so the model can fix the precise issue.
        """
        if self._structural_validator is None:
            return
        problems = self._structural_validator.validate(code)
        if problems:
            msg = StructuralCodeValidator.format_problems(problems)
            self._context.logger.log(msg)
            raise ValueError(msg)

    def _build_structural_validator(self):
        """Build a StructuralCodeValidator from the current schema columns.

        Returns None when no schema columns are available (e.g. during the
        fallback path) so the checks are skipped rather than raising.
        """
        try:
            columns = []
            for df in self._context.dfs:
                if df.schema and df.schema.columns:
                    columns.extend(col.name for col in df.schema.columns)
            if not columns:
                return None
            return StructuralCodeValidator(columns)
        except Exception:
            # Never let the validator itself break code generation.
            return None
