"""Unit tests for the conversation status endpoint and AgentStore.exists().

Covers:
- exists() returns True for a registered conversation
- exists() returns False for an unknown / removed conversation
- exists() is non-mutating: it does NOT refresh the TTL (unlike get_agent)
- GET /api/conversations/{id} returns 200 + {"exists": True} when alive
- GET /api/conversations/{id} returns 404 + {"exists": False} when missing
"""
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.core.agent_store import AgentStore


# ---------------------------------------------------------------------------
# AgentStore.exists() — pure store tests
# ---------------------------------------------------------------------------

class TestExists:
    """Tests for AgentStore.exists()."""

    def test_exists_true_for_registered_conversation(self):
        store = AgentStore(ttl_seconds=60)
        agent = MagicMock()
        cid = store.register_agent(agent)
        assert store.exists(cid) is True

    def test_exists_false_for_unknown_conversation(self):
        store = AgentStore(ttl_seconds=60)
        store.register_agent(MagicMock())
        assert store.exists("does-not-exist-uuid") is False

    def test_exists_false_after_removal(self):
        store = AgentStore(ttl_seconds=60)
        cid = store.register_agent(MagicMock())
        assert store.exists(cid) is True
        store.remove_agent(cid)
        assert store.exists(cid) is False

    def test_exists_false_after_ttl_expiry(self):
        """An expired conversation should be reported as non-existent
        once evict_expired() has run."""
        store = AgentStore(ttl_seconds=0)  # expires immediately
        cid = store.register_agent(MagicMock())
        # TTL=0 means everything is already expired.
        time.sleep(0.01)
        store.evict_expired()
        assert store.exists(cid) is False

    def test_exists_does_not_refresh_ttl(self):
        """exists() must NOT reset the last-access time.

        This is the core guarantee: a status check that isn't followed by a
        chat must not keep an idle conversation alive.
        """
        store = AgentStore(ttl_seconds=60)
        cid = store.register_agent(MagicMock())

        # Record the access time set at registration.
        with store._lock:
            _original_access = store._store[cid][1]

        # Wait briefly so a refresh would be detectable.
        time.sleep(0.05)

        # Calling exists() should NOT change the stored access time.
        assert store.exists(cid) is True

        with store._lock:
            _access_after_exists = store._store[cid][1]

        assert _access_after_exists == _original_access, (
            "exists() must not refresh the TTL (last_access_time unchanged)"
        )

    def test_get_agent_does_refresh_ttl(self):
        """Sanity check: get_agent() DOES refresh the TTL.

        This confirms our non-mutating exists() is meaningfully different
        from the mutating get_agent(), validating the design choice.
        """
        store = AgentStore(ttl_seconds=60)
        cid = store.register_agent(MagicMock())

        with store._lock:
            original_access = store._store[cid][1]

        time.sleep(0.05)
        store.get_agent(cid)  # should refresh

        with store._lock:
            refreshed_access = store._store[cid][1]

        assert refreshed_access > original_access, (
            "get_agent() should refresh the TTL (control case)"
        )


# ---------------------------------------------------------------------------
# GET /api/conversations/{conversation_id} — endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with setup_global_llm patched out (no real LLM needed)."""
    with patch("server.core.llm_setup.setup_global_llm"):
        from server.main import app
        with TestClient(app) as c:
            yield c


class TestConversationStatusEndpoint:
    """Tests for GET /api/conversations/{conversation_id}."""

    def test_returns_200_when_conversation_exists(self, client):
        from server.core.agent_store import agent_store
        cid = agent_store.register_agent(MagicMock())
        try:
            resp = client.get(f"/api/conversations/{cid}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["exists"] is True
            assert body["conversation_id"] == cid
        finally:
            agent_store.remove_agent(cid)

    def test_returns_404_when_conversation_missing(self, client):
        resp = client.get("/api/conversations/nonexistent-uuid")
        assert resp.status_code == 404
        body = resp.json()
        # FastAPI nests HTTPException detail under "detail".
        assert body["detail"]["exists"] is False
        assert "not found" in body["detail"]["message"].lower()

    def test_status_check_does_not_refresh_ttl(self, client):
        """Hitting the endpoint must not keep an idle conversation alive."""
        from server.core.agent_store import agent_store
        cid = agent_store.register_agent(MagicMock())
        try:
            with agent_store._lock:
                original_access = agent_store._store[cid][1]

            time.sleep(0.05)
            resp = client.get(f"/api/conversations/{cid}")
            assert resp.status_code == 200

            with agent_store._lock:
                access_after = agent_store._store[cid][1]

            assert access_after == original_access, (
                "Status endpoint must not refresh the TTL"
            )
        finally:
            agent_store.remove_agent(cid)
