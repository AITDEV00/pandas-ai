import os
import tempfile
import uuid
import shutil
import json
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from .models import Base64UploadRequest, RegisterResponse, PandasAIConfigPayload, LLMConfigPayload, SemanticModelPayload
from .handler import handle_base64_upload, create_agent_from_file_path

router = APIRouter(prefix="/register", tags=["Registration"])

@router.post("/base64", response_model=RegisterResponse)
async def register_base64(payload: Base64UploadRequest):
    """Register endpoints using pure JSON base64 payloads."""
    try:
        response = handle_base64_upload(
            payload.base64_data, 
            payload.mimetype,
                semantic_model=payload.semantic_model,
            pandasai_config=payload.pandasai_config,
            llm_config=payload.llm_config
        )
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/file", response_model=RegisterResponse)
async def register_file(
    file: UploadFile = File(...),
    semantic_model: Optional[str] = Form(None, description="JSON string of SemanticLayerSchema"),
    pandasai_config: Optional[str] = Form(None, description="JSON string of PandasAIConfigPayload"),
    llm_config: Optional[str] = Form(None, description="JSON string of LLMConfigPayload")
):
    """Register endpoints via standard multipart/form-data upload."""
    try:
        # Parse and validate semantic model FIRST (fast-fail before file I/O)
        semantic_model_payload = None
        if semantic_model:
            semantic_model_dict = json.loads(semantic_model)
            # Validate using SemanticModelPayload (handler will inject default source if needed)
            semantic_model_payload = SemanticModelPayload(**semantic_model_dict)
        
        config_payload = PandasAIConfigPayload(**json.loads(pandasai_config)) if pandasai_config else PandasAIConfigPayload()
        llm_payload = LLMConfigPayload(**json.loads(llm_config)) if llm_config else LLMConfigPayload()

        ext = ".csv" if "csv" in file.content_type.lower() else ".xlsx"
        safe_id = str(uuid.uuid4())
        
        temp_dir = os.path.join(tempfile.gettempdir(), "pandasai_uploads")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"upload_{safe_id}{ext}")
        
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        try:
            response = create_agent_from_file_path(
                temp_path, 
                file.content_type,
                semantic_model=semantic_model_payload,
                pandasai_config=config_payload,
                llm_config=llm_payload
            )
            return response
        finally:
            # Clean up the temp file — the DataFrame is already in memory
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="semantic_model, pandasai_config, and llm_config must be valid JSON strings.")
    except ValueError as e:
        # Catch SemanticModelPayload validation errors
        raise HTTPException(status_code=400, detail=f"Invalid semantic model: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
