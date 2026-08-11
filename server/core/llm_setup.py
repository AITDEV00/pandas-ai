import logging
import os
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
import openai

logger = logging.getLogger(__name__)


def create_litellm(
    api_key: str,
    base_url: str,
    model_name: str,
    verify_ssl: bool = False,
    **litellm_kwargs,
) -> LiteLLM:
    """Factory: build a LiteLLM instance backed by a custom OpenAI client.

    Centralises the httpx + openai + LiteLLM wiring so both the global
    setup and per-request handlers share the same logic.
    """
    custom_httpx_client = httpx.Client(verify=verify_ssl)
    try:
        custom_openai_client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=custom_httpx_client,
        )
        return LiteLLM(
            model=model_name,
            client=custom_openai_client,
            **litellm_kwargs,
        )
    except Exception:
        custom_httpx_client.close()
        raise


def _structured_thinking_kwargs() -> dict:
    """Return ``chat_template_kwargs`` that toggles the structured LLM's thinking.

    The structured LLM (used for column selection / description auto-fill) can
    be a reasoning model like DeepSeek-V4. When ``STRUCTURED_LLM_THINKING`` is
    set to ``false`` (case-insensitive), we emit ``{"thinking": false}`` in the
    request body so it does NOT spend tokens/time reasoning before producing its
    JSON column-selection output. Defaults to enabled (no override).

    Returns:
        dict: A dict safe to merge into ``litellm_kwargs``. Empty when the env
        var is unset or truthy.
    """
    flag = os.environ.get("STRUCTURED_LLM_THINKING", "").strip().lower()
    if flag == "false":
        return {"extra_body": {"chat_template_kwargs": {"thinking": False}}}
    return {}


def _codegen_thinking_kwargs() -> dict:
    """Return ``chat_template_kwargs`` that toggles the coding model's thinking.

    The DeepSeek coding model surfaces chain-of-thought via the
    ``chat_template_kwargs.thinking`` flag in the request body (see the user
    example: ``{"chat_template_kwargs": {"thinking": true}}``). When the
    ``CODE_GENERATION_THINKING`` env var is set to ``false`` (case-insensitive),
    we emit ``{"thinking": false}`` so the code-generation LLM does NOT spend
    tokens/time reasoning before producing code. Defaults to enabled.

    Returns:
        dict: A dict safe to merge into ``litellm_kwargs``. Empty when the env
        var is unset or truthy, so existing behaviour is unchanged.
    """
    flag = os.environ.get("CODE_GENERATION_THINKING", "").strip().lower()
    if flag == "false":
        # Use extra_body so litellm reliably forwards it into the OpenAI
        # request body as a top-level field. The vLLM/DeepSeek endpoint reads
        # chat_template_kwargs.thinking to toggle chain-of-thought.
        return {"extra_body": {"chat_template_kwargs": {"thinking": False}}}
    return {}


def setup_structured_llm(json_mode: bool = False):
    """Build a dedicated LLM for structured JSON calls (column selection, auto-fill).

    Reads the ``STRUCTURED_LLM_*`` env vars; the API key and base URL fall back
    to the main ``LLM_*`` credentials so the structured model can reuse the main
    endpoint with a different model name.

    Requires ``STRUCTURED_LLM_MODEL_NAME`` to be set explicitly.  When it's
    missing (or credentials are incomplete), logs a warning and returns None so
    callers fall back to the main LLM — there is no hidden default model.

    Args:
        json_mode: When True, forces ``response_format={"type": "json_object"}``
            on the instance. Leave False for callers that control JSON mode
            themselves via sampling params (e.g. the ColumnSelector, which gates
            it on ``column_selection_json_mode``).
            The env var ``STRUCTURED_LLM_JSON_MODE`` overrides this: set it to
            "false" to disable grammar-constrained JSON (required for models like
            DeepSeek-V4-Flash whose speculative decoding rejects
            ``response_format``).
    """
    # Env override takes precedence so operators can disable grammar-constrained
    # JSON for models that reject ``response_format`` (e.g. DeepSeek-V4-Flash
    # DFLASH) without editing code.
    env_override = os.environ.get("STRUCTURED_LLM_JSON_MODE")
    if env_override is not None:
        json_mode = env_override.lower() == "true"
        if not json_mode:
            logger.info(
                "STRUCTURED_LLM_JSON_MODE=false — disabling response_format grammar "
                "constraint for the structured LLM"
            )

    model_name = os.environ.get("STRUCTURED_LLM_MODEL_NAME")
    if not model_name:
        logger.warning(
            "STRUCTURED_LLM_MODEL_NAME not set — structured JSON calls will use the main LLM"
        )
        return None

    api_key = os.environ.get("STRUCTURED_LLM_API_KEY") or os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("STRUCTURED_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
    verify_ssl = os.environ.get("STRUCTURED_LLM_VERIFY_SSL", "false").lower() == "true"

    if not api_key or not base_url:
        logger.warning(
            "Structured LLM credentials missing — structured calls will use the main LLM"
        )
        return None

    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    kwargs.update(_structured_thinking_kwargs())
    return create_litellm(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        verify_ssl=verify_ssl,
        **kwargs,
    )


def setup_global_llm():
    """
    Configures LiteLLM to map to the local OpenAI-compatible inference engine.
    All credentials are read from environment variables for security.
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    model_name = os.environ.get("LLM_MODEL_NAME", "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "false").lower() == "true"

    if not api_key or not base_url:
        # If env vars are not set, skip global LLM setup.
        # The register endpoint can still provide per-request LLM config.
        return

    llm = create_litellm(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        verify_ssl=verify_ssl,
        **_codegen_thinking_kwargs(),
    )

    llm_context_window = int(os.environ.get("LLM_CONTEXT_WINDOW", "250000"))

    pai.config.set({
        "llm": llm,
        "verbose": True,
        "llm_context_window": llm_context_window,
    })
