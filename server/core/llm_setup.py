import os
import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
import openai

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

    custom_httpx_client = httpx.Client(verify=verify_ssl)
    custom_openai_client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=custom_httpx_client,
    )

    llm = LiteLLM(
        model=model_name,
        client=custom_openai_client,
    )

    pai.config.set({
        "llm": llm,
        "verbose": True,
    })
