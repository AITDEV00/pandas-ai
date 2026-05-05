import base64
import os
import uuid
import tempfile
import json
import httpx
import openai
import pandasai as pai
from fastapi import HTTPException
from pydantic import ValidationError
from pandasai import Agent
from pandasai_litellm.litellm import LiteLLM
from pandasai.data_loader.semantic_layer_schema import SemanticLayerSchema
from server.core.agent_store import agent_store
from .models import RegisterResponse, ColumnContext, PandasAIConfigPayload, LLMConfigPayload

def create_agent_from_file_path(
    file_path: str, 
    mimetype: str,
    semantic_model: dict = None,
    pandasai_config: PandasAIConfigPayload = None,
    llm_config: LLMConfigPayload = None
) -> RegisterResponse:
    """Reads the local file securely into an isolated agent session."""
    if "csv" in mimetype.lower() or file_path.endswith(".csv"):
        df = pai.read_csv(file_path)
    elif "excel" in mimetype.lower() or "spreadsheet" in mimetype.lower() or file_path.endswith(".xlsx"):
        df = pai.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported mimetype: {mimetype}")

    if pandasai_config is None:
        pandasai_config = PandasAIConfigPayload()
        
    if llm_config is None:
        llm_config = LLMConfigPayload()
        
    # --- 1. Dynamic Semantic Model & Error Handling ---
    if semantic_model:
        if "name" not in semantic_model:
            semantic_model["name"] = getattr(df, "_table_name", "uploaded_table")
        if "source" not in semantic_model and "view" not in semantic_model:
            semantic_model["source"] = {"type": "csv" if file_path.endswith(".csv") else "excel", "path": file_path}
            
        try:
            validated_schema = SemanticLayerSchema(**semantic_model)
            df.schema = validated_schema
        except ValidationError as e:
            errors = [{"field": ".".join(map(str, err["loc"])), "error": err["msg"]} for err in e.errors()]
            raise HTTPException(status_code=400, detail={"message": "Semantic Model Validation Failed", "errors": errors})

    # --- 2. Apply Custom LLM Config ---
    from pandasai.config import ConfigManager
    global_config_obj = ConfigManager.get()
    agent_config = global_config_obj.model_dump()
    agent_config["llm"] = global_config_obj.llm  # Preserve actual object instead of dict
    
    agent_config.update(pandasai_config.model_dump())
    
    if llm_config.api_key and llm_config.base_url:
        custom_httpx_client = httpx.Client(verify=False)
        custom_openai_client = openai.OpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            http_client=custom_httpx_client
        )
        
        # Extract all LiteLLM generation sampling parameters
        sampling_params = llm_config.model_dump(
            exclude={"api_key", "base_url", "model_name", "system_prompt"}, 
            exclude_unset=True, 
            exclude_none=True
        )
        
        custom_llm = LiteLLM(
            model=llm_config.model_name,
            client=custom_openai_client,
            **sampling_params
        )
        agent_config["llm"] = custom_llm

    # Inject the system prompt via the description parameter
    agent = Agent([df], config=agent_config, description=llm_config.system_prompt)
    conversation_id = agent_store.register_agent(agent)
    
    # --- 3. Extract Context for API Response ---
    extracted_context = None
    if pandasai_config.enrich_column_values:
        # Trigger lazy extraction so we can return the exact tokens sent to LLM
        agent._state.dfs[0].serialize_dataframe(config=agent._state.config)
        
        extracted_context = []
        for col in agent._state.dfs[0].schema.columns:
            if col.samples is not None:
                extracted_context.append(ColumnContext(column=col.name, samples=col.samples))

    return RegisterResponse(conversation_id=conversation_id, extracted_context=extracted_context)

def handle_base64_upload(
    base64_data: str, 
    mimetype: str,
    semantic_model: dict = None,
    pandasai_config: PandasAIConfigPayload = None,
    llm_config: LLMConfigPayload = None
) -> RegisterResponse:
    """Takes a base64 payload, writes to temp dir avoiding overlap via UUID, returns RegisterResponse."""
    if base64_data.startswith("data:"):
        base64_data = base64_data.split(",")[1]

    file_bytes = base64.b64decode(base64_data)
    
    ext = ".csv" if "csv" in mimetype.lower() else ".xlsx"
    safe_id = str(uuid.uuid4())
    
    temp_dir = os.path.join(tempfile.gettempdir(), "pandasai_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"upload_{safe_id}{ext}")
    
    with open(temp_path, "wb") as f:
        f.write(file_bytes)
    
    return create_agent_from_file_path(
        temp_path, 
        mimetype,
        semantic_model=semantic_model,
        pandasai_config=pandasai_config,
        llm_config=llm_config
    )
