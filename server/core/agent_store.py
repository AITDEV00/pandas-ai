import uuid
import threading
from typing import Dict, Optional
from pandasai import Agent

class AgentStore:
    """
    Thread-safe storage manager mapping exactly one UUID 
    to one active PandasAI Agent session securely.
    """
    def __init__(self):
        self._store: Dict[str, Agent] = {}
        self._lock = threading.Lock()

    def register_agent(self, agent: Agent) -> str:
        conversation_id = str(uuid.uuid4())
        with self._lock:
            self._store[conversation_id] = agent
        return conversation_id

    def get_agent(self, conversation_id: str) -> Optional[Agent]:
        with self._lock:
            return self._store.get(conversation_id)

    def remove_agent(self, conversation_id: str):
        with self._lock:
            if conversation_id in self._store:
                del self._store[conversation_id]

# Singleton reference used throughout the vertical slices
agent_store = AgentStore()
