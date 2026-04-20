import base64
import os
import uuid
import tempfile
import pandasai as pai
from pandasai import Agent
from server.core.agent_store import agent_store

def create_agent_from_file_path(file_path: str, mimetype: str) -> str:
    """Reads the local file securely into an isolated agent session."""
    if "csv" in mimetype.lower() or file_path.endswith(".csv"):
        df = pai.read_csv(file_path)
    elif "excel" in mimetype.lower() or "spreadsheet" in mimetype.lower() or file_path.endswith(".xlsx"):
        df = pai.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported mimetype: {mimetype}")
        
    agent = Agent(df)
    conversation_id = agent_store.register_agent(agent)
    return conversation_id

def handle_base64_upload(base64_data: str, mimetype: str) -> str:
    """Takes a base64 payload, writes to temp dir avoiding overlap via UUID, returns conversation."""
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
    
    return create_agent_from_file_path(temp_path, mimetype)
