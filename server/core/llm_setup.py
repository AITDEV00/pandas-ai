import httpx
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM
import openai

def setup_global_llm():
    """
    Configures LiteLLM precisely to securely map to the local 
    OpenAI-compatible inference engine while bypassing SSL verification.
    """
    custom_httpx_client = httpx.Client(verify=False)

    custom_openai_client = openai.OpenAI(
        api_key="sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8",
        base_url="https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
        http_client=custom_httpx_client
    )

    llm = LiteLLM(
        model="openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
        client=custom_openai_client
    )

    pai.config.set({
        "llm": llm,
        "verbose": True
    })
