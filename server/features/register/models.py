from pydantic import BaseModel

class Base64UploadRequest(BaseModel):
    base64_data: str
    mimetype: str

class RegisterResponse(BaseModel):
    conversation_id: str
