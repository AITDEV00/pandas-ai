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
    """
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
    )

    llm_context_window = int(os.environ.get("LLM_CONTEXT_WINDOW", "250000"))

    pai.config.set({
        "llm": llm,
        "verbose": True,
        "llm_context_window": llm_context_window,
    })
