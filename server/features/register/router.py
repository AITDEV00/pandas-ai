import os
import tempfile
import uuid
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from .models import Base64UploadRequest, RegisterResponse
from .handler import handle_base64_upload, create_agent_from_file_path

router = APIRouter(prefix="/register", tags=["Registration"])

@router.post("/base64", response_model=RegisterResponse)
async def register_base64(payload: Base64UploadRequest):
    """Register endpoints using pure JSON base64 payloads."""
    try:
        convo_id = handle_base64_upload(payload.base64_data, payload.mimetype)
        return RegisterResponse(conversation_id=convo_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/file", response_model=RegisterResponse)
async def register_file(file: UploadFile = File(...)):
    """Register endpoints via standard multipart/form-data upload."""
    try:
        ext = ".csv" if "csv" in file.content_type.lower() else ".xlsx"
        safe_id = str(uuid.uuid4())
        
        temp_dir = os.path.join(tempfile.gettempdir(), "pandasai_uploads")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"upload_{safe_id}{ext}")
        
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        convo_id = create_agent_from_file_path(temp_path, file.content_type)
        return RegisterResponse(conversation_id=convo_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
