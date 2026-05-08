import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from server.core.llm_setup import setup_global_llm
from server.core.agent_store import agent_store
from server.features.register.router import router as register_router
from server.features.chat.router import router as chat_router

# Configure root logger so server module logs (e.g. auto-fill descriptions) are visible
_log_level_name = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, _log_level_name, logging.WARNING),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

def create_app() -> FastAPI:
    # 0. Load environment variables from .env file
    load_dotenv()

    # 1. Boot global settings before App starts routing
    setup_global_llm()

    # 2. Setup FastAPI App
    app = FastAPI(title="PandasAI Excel Server")

    # CORS: allow_origins=["*"] with allow_credentials=True is invalid per spec.
    # Use explicit origins from env var, or allow all without credentials.
    _allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=_allowed_origins != ["*"],  # Can't use True with wildcard
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Register Vertical Slice Routers
    app.include_router(register_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")

    @app.get("/health")
    def health_check():
        return {"status": "ok", "active_sessions": agent_store.active_count}

    @app.post("/api/admin/evict")
    def evict_expired_sessions():
        """Evict agent sessions that haven't been accessed within the TTL period."""
        evicted = agent_store.evict_expired()
        return {"evicted": evicted, "active_sessions": agent_store.active_count}

    return app

app = create_app()
