import uuid
import threading
import time
from typing import Dict, Optional, Tuple
from pandasai import Agent

# Default TTL for agent sessions (24 hours)
DEFAULT_TTL_SECONDS = 24 * 60 * 60

class AgentStore:
    """
    Thread-safe storage manager mapping exactly one UUID 
    to one active PandasAI Agent session securely.
    
    Supports TTL-based eviction to prevent memory leaks in
    long-running server processes.
    """
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._store: Dict[str, Tuple[Agent, float]] = {}  # (agent, last_access_time)
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def register_agent(self, agent: Agent) -> str:
        conversation_id = str(uuid.uuid4())
        with self._lock:
            self._store[conversation_id] = (agent, time.time())
        return conversation_id

    def get_agent(self, conversation_id: str) -> Optional[Agent]:
        with self._lock:
            entry = self._store.get(conversation_id)
            if entry is None:
                return None
            agent, _ = entry
            # Update last access time
            self._store[conversation_id] = (agent, time.time())
            return agent

    def remove_agent(self, conversation_id: str) -> bool:
        with self._lock:
            if conversation_id in self._store:
                del self._store[conversation_id]
                return True
            return False

    def evict_expired(self) -> int:
        """Remove all agents that haven't been accessed within the TTL period.
        
        Returns:
            int: Number of agents evicted.
        """
        now = time.time()
        evicted = 0
        with self._lock:
            expired_ids = [
                cid for cid, (_, last_access) in self._store.items()
                if now - last_access > self._ttl_seconds
            ]
            for cid in expired_ids:
                del self._store[cid]
                evicted += 1
        return evicted

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._store)

# Singleton reference used throughout the vertical slices
agent_store = AgentStore()
