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
from .models import RegisterResponse, ColumnContext, PandasAIConfigPayload, LLMConfigPayload, SemanticModelPayload

def create_agent_from_file_path(
    file_path: str, 
    mimetype: str,
    semantic_model: SemanticModelPayload = None,
    pandasai_config: PandasAIConfigPayload = None,
    llm_config: LLMConfigPayload = None
) -> RegisterResponse:
    """Reads the local file securely into an isolated agent session."""
    
    # --- 0. Pre-validate semantic model BEFORE file I/O (fast-fail) ---
    if semantic_model:
        # SemanticModelPayload already validates in its model_validator
        # Convert to dict for later use
        semantic_model_dict = semantic_model.model_dump(exclude_none=True)
    else:
        semantic_model_dict = None
    
    # --- 1. Read file (only after validation passes) ---
    if "csv" in mimetype.lower() or file_path.endswith(".csv"):
        df = pai.read_csv(file_path)
    elif "excel" in mimetype.lower() or "spreadsheet" in mimetype.lower() or file_path.endswith(".xlsx"):
        df = pai.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported mimetype: {mimetype}")

    from pandasai.helpers.type_determination import parse_json_array_columns

    parse_json_array_columns(df)

    if pandasai_config is None:
        pandasai_config = PandasAIConfigPayload()
        
    if llm_config is None:
        llm_config = LLMConfigPayload()
        
    # --- 2. Apply Semantic Model to DataFrame ---
    if semantic_model_dict:
        if "name" not in semantic_model_dict:
            semantic_model_dict["name"] = getattr(df, "_table_name", "uploaded_table")
        if "source" not in semantic_model_dict and "view" not in semantic_model_dict:
            # PandasAI only accepts csv/parquet as local source types.
            # This is a dummy source — the data is already loaded into the DataFrame.
            semantic_model_dict["source"] = {"type": "csv", "path": file_path}
            
        try:
            validated_schema = SemanticLayerSchema(**semantic_model_dict)
            df.schema = validated_schema
        except ValidationError as e:
            errors = [{"field": ".".join(map(str, err["loc"])), "error": err["msg"]} for err in e.errors()]
            raise HTTPException(status_code=400, detail={"message": "Semantic Model Validation Failed", "errors": errors})

    # --- 2b. Patch schema columns to reflect actual data types ---
    # After JSON array parsing, some columns that the user declared as "string"
    # are actually list[struct]. The serializer handles this in its col_dict,
    # but the template reads from df.schema.columns — so we must back-patch
    # the schema Column objects with the correct type, semantic_type, and samples.
    #
    # IMPORTANT: When a DataFrame column is list[struct] and the match is via
    # semantic matching (inner/parent match), we must NOT patch the inner schema
    # column — instead we ADD the squashed column to the schema. The inner columns
    # are useful for the serializer's XML but the template needs the actual
    # DuckDB column name for UNNEST.
    if df.schema and df.schema.columns:
        from pandasai.helpers.type_determination import is_list_struct_column
        from pandasai.helpers.semantic_matching import get_matching_schema_columns, merge_descriptions
        from pandasai.data_loader.semantic_layer_schema import Column as SchemaColumn

        schema_by_name = {col.name: col for col in df.schema.columns}
        new_schema_columns = []

        for col_name in df.columns:
            series = df[col_name]
            is_struct = is_list_struct_column(series)

            exact_match = schema_by_name.get(col_name)

            if is_struct:
                # --- Struct column handling ---
                if exact_match is not None:
                    # Direct match — patch the existing schema column
                    if exact_match.type != "list[struct]":
                        exact_match.type = "list[struct]"
                        exact_match.semantic_type = "struct"

                    if pandasai_config.enrich_column_values and exact_match.samples is None:
                        from pandasai.helpers.column_enrichment import ColumnValueExtractor
                        result = ColumnValueExtractor.classify_and_extract(
                            series, "list[struct]", pandasai_config.categorical_max_unique, df.schema
                        )
                        if result["samples"] is not None:
                            exact_match.samples = result["samples"]
                        if result["semantic_type"] is not None and exact_match.semantic_type is None:
                            exact_match.semantic_type = result["semantic_type"]
                else:
                    # No exact match — the squashed column is NOT in the schema.
                    # Semantic matching would return inner columns, but we must NOT
                    # patch those. Instead, add the squashed column as a new entry.
                    matches = get_matching_schema_columns(col_name, df.schema)
                    merged_desc = merge_descriptions(matches) if matches else None

                    samples = None
                    if pandasai_config.enrich_column_values:
                        from pandasai.helpers.column_enrichment import ColumnValueExtractor
                        result = ColumnValueExtractor.classify_and_extract(
                            series, "list[struct]", pandasai_config.categorical_max_unique, df.schema
                        )
                        samples = result.get("samples")

                    new_col = SchemaColumn(
                        name=col_name,
                        type="list[struct]",
                        semantic_type="struct",
                        samples=samples,
                        description=merged_desc,
                    )
                    new_schema_columns.append(new_col)
            else:
                # --- Non-struct column enrichment ---
                # Enrich normal columns with samples/semantic_type so the template
                # and the API response both include their vocabulary.
                if pandasai_config.enrich_column_values and exact_match is not None and exact_match.samples is None:
                    from pandasai.helpers.column_enrichment import ColumnValueExtractor
                    result = ColumnValueExtractor.classify_and_extract(
                        series, exact_match.type, pandasai_config.categorical_max_unique, df.schema
                    )
                    if result["samples"] is not None:
                        exact_match.samples = result["samples"]
                    if result["semantic_type"] is not None and exact_match.semantic_type is None:
                        exact_match.semantic_type = result["semantic_type"]

        # Append any new columns to the schema
        if new_schema_columns:
            df.schema.columns = list(df.schema.columns) + new_schema_columns

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
    # df is already a PandasAI DataFrame (from pai.read_csv/read_excel).
    # Its schema was patched in step 2b and is preserved through Agent creation.
    agent = Agent([df], config=agent_config, description=llm_config.system_prompt)
    conversation_id = agent_store.register_agent(agent)
    
    # --- 3. Extract Context for API Response ---
    # Schema columns were already enriched in step 2b, so just read from them.
    extracted_context = None
    if pandasai_config.enrich_column_values and df.schema and df.schema.columns:
        extracted_context = []
        for schema_col in df.schema.columns:
            if schema_col.samples is not None:
                extracted_context.append(ColumnContext(
                    column=schema_col.name,
                    type=schema_col.type,
                    semantic_type=schema_col.semantic_type,
                    samples=schema_col.samples,
                ))

    return RegisterResponse(conversation_id=conversation_id, extracted_context=extracted_context)

def handle_base64_upload(
    base64_data: str, 
    mimetype: str,
    semantic_model: SemanticModelPayload = None,
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
