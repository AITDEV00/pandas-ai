from litellm import completion
import litellm as _litellm

from pandasai.agent.state import AgentState
from pandasai.core.prompts.base import BasePrompt
from pandasai.llm.base import LLM
import logging


# ---------------------------------------------------------------------------
# Per-ATTEMPT instrumentation.
#
# litellm retries failed provider calls automatically. A single outer wall-clock
# timer around `completion()` therefore conflates the time of a failed attempt
# (e.g. a 30s httpx timeout) with the time of the successful retry that follows.
# The provider dashboard only shows the *successful* attempt, so it looks like
# the model was fast while our caller saw a much larger wall time.
#
# To expose this, we register litellm's own success/failure callbacks. They fire
# once per attempt with that attempt's start/end timestamps. Records accumulate
# in the module-level _ATTEMPTS list; call() snapshots the range it spans and
# reports it on the [LLM-CALL] line, and the harness can read them all.
# ---------------------------------------------------------------------------

_ATTEMPTS = []  # list[dict]: one entry per provider request attempt


def _attempt_callback(kind, response_or_exc, start_time, end_time):
    dur = round(end_time.timestamp() - start_time.timestamp(), 3)
    rec = {
        "seq": len(_ATTEMPTS) + 1,
        "kind": kind,  # "success" | "failure"
        "dur_s": dur,
    }
    if kind == "failure":
        rec["error"] = str(response_or_exc)[:300]
    else:
        try:
            usage = getattr(response_or_exc, "usage", None)
            if usage is not None:
                rec["in_tokens"] = getattr(usage, "prompt_tokens", None)
                rec["out_tokens"] = getattr(usage, "completion_tokens", None)
        except Exception:
            pass
    _ATTEMPTS.append(rec)


# Register once per process.
if not getattr(_litellm, "_jyao_attempt_cb_registered", False):
    def _success_cb(kwargs, resp, start, end):
        _attempt_callback("success", resp, start, end)

    def _failure_cb(kwargs, exc, start, end):
        _attempt_callback("failure", exc, start, end)

    _litellm.success_callback = [_success_cb]
    _litellm.failure_callback = [_failure_cb]
    _litellm._jyao_attempt_cb_registered = True


def get_attempt_log():
    """Return a shallow copy of all provider request attempts recorded so far."""
    return list(_ATTEMPTS)


# Phase labels for the per-query LLM call log. The agent calls the raw
# `call()` path for BOTH Step-1 column selection and the unstructured codegen
# fallback, so the raw path cannot self-identify its stage reliably. The
# structured codegen path is unambiguously code generation.
_PHASE_STRUCTURED_CODEGEN = "codegen_structured"
_PHASE_UNKNOWN = "unknown"


class LiteLLM(LLM):
    """A lightweight wrapper for interacting with a specified LLM model.

    This class provides an interface to generate text based on user instructions
    using the specified language model. It allows for customization through additional
    parameters passed during initialization.

    Args:
        model (str): The name of the language model to use.
        **kwargs: Additional parameters for the model's completion settings.

    Properties:
        type (str): Returns the type of the LLM, which is 'litellm'.

    Methods:
        call(instruction: BasePrompt, _: AgentState = None) -> str:
            Generates a response based on the provided instruction."""

    def __init__(self, model: str, **kwargs):
        """
        Initializes the wrapper with the model name and any additional parameters.

        Args:
            model (str): The name of the LLM model.
            **kwargs: Any additional parameters required for completion.
        """
        super().__init__(api_key=None)
        self.model = model
        # Optional per-call timeout (seconds). When set, the completion/stream
        # is aborted if it exceeds this budget. Pop it BEFORE storing params so
        # it is not forwarded to the provider.
        self.timeout = kwargs.pop("timeout", None)
        self.params = kwargs
        self._last_thinking_trace = None
        self._last_finish_reason = None
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)

    @property
    def type(self) -> str:
        """Get the type of the model.

        This property returns the string representation of the model's type,
        which is 'litellm'.

        Returns:
            str: The type of the model."""
        return "litellm"

    def call(self, instruction: BasePrompt, context: AgentState = None, sampling_params: dict = None) -> str:
        """Generates a completion response based on the provided instruction.

        This method converts the given instruction into a user prompt string and
        sends it to a model for processing. It returns the content of the first
        message from the model's response.

        Args:
            instruction (BasePrompt): The instruction to convert into a prompt.
            context (AgentState, optional): An optional state of the agent. Defaults to None.
            sampling_params (dict, optional): Per-call sampling parameters that override
                the instance-level ``self.params``. Keys here take precedence over
                ``self.params`` for this call only. Useful for setting different
                temperature/penalties for column selection vs code generation.

        Returns:
            str: The content of the model's response to the user prompt."""

        memory = context.memory if context else None

        # Build the messages array using the authoritative method.
        # This ensures: (1) system prompt is always first, (2) conversation
        # history is rounded to complete user→assistant pairs, (3) the
        # current query is excluded (it goes in the instruction template).
        messages = memory.to_openai_messages_for_chat() if memory else []

        # The rendered instruction (table schemas + query + output format) as final user message
        user_prompt = instruction.to_string()
        messages.append({"role": "user", "content": user_prompt})

        self.last_prompt = "\n".join(m["content"] for m in messages)

        if context and context.logger:
            context.logger.log(
                f"LLM PROMPT ({len(messages)} messages, ~{len(self.last_prompt)} chars)"
            )

        # Merge instance params with per-call sampling_params.
        # Per-call params take precedence (override) over instance params.
        merged_params = {**self.params}
        if sampling_params:
            merged_params.update(sampling_params)

        # Apply the configured timeout (seconds). Bound the whole request —
        # including the reasoning chain-of-thought — so a slow reasoning model
        # (e.g. DeepSeek V4 Flash emitting 100k CoT tokens) is aborted instead
        # of hanging. 0/None means no timeout.
        timeout = self.timeout or merged_params.pop("timeout", None)
        if timeout:
            merged_params["timeout"] = timeout

        import time as _t
        _call_start = _t.monotonic()
        _attempts_start = len(_ATTEMPTS)  # snapshot before the request
        response = completion(
            model=self.model,
            messages=messages,
            **merged_params,
        )
        _call_elapsed = round(_t.monotonic() - _call_start, 2)
        _attempts = _ATTEMPTS[_attempts_start:]  # this call's own attempts

        self._last_thinking_trace = None
        self._last_finish_reason = None

        # Capture the thinking / reasoning trace from the raw response so it
        # can be audited in the conversation log.  DeepSeek (and other
        # reasoning models) surface "chain of thought" via reasoning_content
        # on the first choice; guard against absence so non-thinking models
        # still work.
        try:
            first_choice = response.choices[0]
            message = getattr(first_choice, "message", None)
            if message is not None:
                reasoning = getattr(message, "reasoning_content", None)
                if reasoning is not None and str(reasoning).strip():
                    self._last_thinking_trace = str(reasoning)
            # finish_reason tells us if the response was truncated at the
            # max_tokens budget ("length") vs. a normal end ("stop"). This is
            # the key signal for diagnosing runaway generations that were cut
            # off at the 10k-token cap.
            fr = getattr(first_choice, "finish_reason", None)
            self._last_finish_reason = getattr(fr, "reason", None) if not isinstance(fr, str) else fr
        except Exception:
            self._last_thinking_trace = None

        content = response.choices[0].message.content

        # Token usage (litellm responses expose .usage when the provider sends it).
        usage = getattr(response, "usage", None)
        tok_str = ""
        if usage is not None:
            tok_str = (f" (in={getattr(usage, 'prompt_tokens', '?')} "
                       f"out={getattr(usage, 'completion_tokens', '?')} "
                       f"reasoning={getattr(usage, 'completion_tokens_details', None) and getattr(usage.completion_tokens_details, 'reasoning_tokens', '?') or '?'})")

        if context and context.logger:
            context.logger.log(
                f"[LLM-CALL] done in {_call_elapsed}s{tok_str} | "
                f"content={len(content)} chars | "
                f"reasoning={len(self._last_thinking_trace or '')} chars | "
                f"finish={self._last_finish_reason}"
            )
            # Per-attempt breakdown (exposes litellm retries the dashboard hides)
            for a in _attempts:
                a_str = (f"[ATTEMPT] #{a['seq']} {a['kind']} {a['dur_s']}s"
                         + (f" | in={a['in_tokens']} out={a['out_tokens']}" if a.get('in_tokens') is not None else "")
                         + (f" | err={a['error']}" if a.get('error') else ""))
                context.logger.log(a_str)
            if len(_attempts) > 1:
                context.logger.log(
                    f"[ATTEMPT] NOTE: {len(_attempts)} attempts took {_call_elapsed}s wall "
                    f"-> successful provider attempt(s) were {[a['dur_s'] for a in _attempts if a['kind']=='success']}s"
                )
            context.logger.log(
                f"LLM RESPONSE ({len(content)} chars):\n{content}"
            )
            if self._last_thinking_trace:
                context.logger.log(
                    f"LLM THINKING TRACE ({len(self._last_thinking_trace)} chars):\n"
                    f"{self._last_thinking_trace}"
                )

        # Record this call in the per-query LLM call log for precise profiling.
        # The raw call() path serves Step-1 column selection AND the unstructured
        # codegen fallback; correlate by order with state.timings in the analyzer.
        if context is not None and hasattr(context, "llm_call_log"):
            context.llm_call_log.append({
                "seq": len(context.llm_call_log) + 1,
                "phase": _PHASE_UNKNOWN,
                "kind": "raw_call",
                "elapsed_s": _call_elapsed,
                "attempts": len(_attempts),
                "attempts_detail": list(_attempts),
                "finish_reason": self._last_finish_reason,
                "thinking_chars": len(self._last_thinking_trace or ""),
                "fallback": False,
            })

        return content

    def generate_code_structured(
        self,
        instruction: BasePrompt,
        context: AgentState = None,
        sampling_params: dict = None,
    ):
        """Generate code via a structured, bounded 3-section response.

        Asks the model for three validated fields — ``reasoning_trace`` (short
        plan), ``double_check`` (self-review), ``code`` (final Python) — using
        the instructor library (``Mode.MD_JSON``). This is the middle ground
        between full thinking-mode (which loops on DeepSeek-V4-Flash) and
        thinking-off (which collapses quality): the model gets a bounded place
        to reason, and the structured fields force it to commit to code and stop.

        Returns:
            CodeGenResult: the validated structured result (``.code`` holds the
            generated Python).
        """
        import time as _t

        from pandasai.core.code_generation.structured import CodeGenResult

        memory = context.memory if context else None
        messages = memory.to_openai_messages_for_chat() if memory else []
        messages.append({"role": "user", "content": instruction.to_string()})
        self.last_prompt = "\n".join(m["content"] for m in messages)

        merged_params = {**self.params}
        if sampling_params:
            merged_params.update(sampling_params)
        # max_tokens cap still bounds the whole structured response.
        timeout = self.timeout or merged_params.pop("timeout", None)
        if timeout:
            merged_params["timeout"] = timeout

        extra_body = merged_params.get("extra_body")
        create_kwargs = {}
        if extra_body and isinstance(extra_body, dict):
            create_kwargs["extra_body"] = extra_body
        # Forward safe sampling params that instructor accepts for the codegen
        # call (temperature 0.2, max_tokens cap, etc.) so the structured path
        # behaves like the raw path.
        for key in (
            "temperature",
            "max_tokens",
            "top_p",
            "top_k",
            "min_p",
            "repetition_penalty",
            "presence_penalty",
            "reasoning_effort",
            "allowed_openai_params",
        ):
            if key in merged_params and merged_params[key] is not None:
                create_kwargs[key] = merged_params[key]

        model_name = self.model
        raw_model = model_name
        if raw_model.startswith("openai/"):
            raw_model = raw_model[len("openai/"):]

        import instructor
        from instructor import Mode

        client = merged_params.get("client")

        _call_start = _t.monotonic()
        _attempts_start = len(_ATTEMPTS)
        try:
            if client is not None:
                ic = instructor.from_openai(client, mode=Mode.MD_JSON, model=raw_model)
                result, raw_response = ic.create_with_completion(
                    response_model=CodeGenResult,
                    messages=messages,
                    **create_kwargs,
                )
            else:
                from litellm import completion
                from instructor.v2.providers.litellm.client import from_litellm

                ic = from_litellm(completion, mode=Mode.MD_JSON)
                result, raw_response = ic.create_with_completion(
                    response_model=CodeGenResult,
                    model=model_name,
                    messages=messages,
                    **create_kwargs,
                )
            _attempts = _ATTEMPTS[_attempts_start:]
        except Exception:
            # If instructor fails, fall back to the unstructured path so codegen
            # still works (degraded) rather than aborting the whole query.
            if context and context.logger:
                context.logger.log(
                    "[LLM-CALL] structured codegen failed; falling back to raw call()"
                )
            if context is not None and hasattr(context, "llm_call_log"):
                context.llm_call_log.append({
                    "phase": _PHASE_STRUCTURED_CODEGEN,
                    "kind": "structured_codegen",
                    "elapsed_s": round(_t.monotonic() - _call_start, 3),
                    "attempts": len(_ATTEMPTS[_attempts_start:]),
                    "attempts_detail": list(_ATTEMPTS[_attempts_start:]),
                    "finish_reason": None,
                    "thinking_chars": 0,
                    "fallback": True,
                })
            return super().generate_code_structured(
                instruction, context=context, sampling_params=sampling_params
            )
        _elapsed = round(_t.monotonic() - _call_start, 2)
        _attempts = _ATTEMPTS[_attempts_start:]

        # Capture thinking trace from the underlying completion for audit.
        trace = None
        finish_reason = None
        try:
            if raw_response is not None:
                choice = getattr(raw_response, "choices", None)
                if choice:
                    message = getattr(choice[0], "message", None)
                    reasoning = getattr(message, "reasoning_content", None)
                    if reasoning is not None and str(reasoning).strip():
                        trace = str(reasoning)
                    fr = getattr(choice[0], "finish_reason", None)
                    finish_reason = getattr(fr, "reason", None) if not isinstance(fr, str) else fr
        except Exception:
            trace = None
        self._last_thinking_trace = trace
        self._last_finish_reason = finish_reason

        # Record this call in the per-query LLM call log for precise profiling.
        if context is not None and hasattr(context, "llm_call_log"):
            context.llm_call_log.append({
                "seq": len(context.llm_call_log) + 1,
                "phase": _PHASE_STRUCTURED_CODEGEN,
                "kind": "structured_codegen",
                "elapsed_s": _elapsed,
                "attempts": len(_attempts),
                "attempts_detail": list(_attempts),
                "finish_reason": finish_reason,
                "thinking_chars": len(trace or ""),
                "fallback": False,
            })

        if context and context.logger:
            context.logger.log(
                f"[LLM-CALL][STRUCTURED] done in {_elapsed}s | "
                f"code={len(result.code)} chars | reasoning_trace={len(result.reasoning_trace)} "
                f"chars | verification_checks={len(result.verification_checks)} | "
                f"thinking_trace={len(trace or '')} chars"
            )
            context.logger.log(
                f"[STRUCTURED] reasoning_trace: {result.reasoning_trace}\n"
                f"[STRUCTURED] verification_checks: {result.double_check}"
            )
            context.logger.log(f"[STRUCTURED] code:\n{result.code}")

        return result
