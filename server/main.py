from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from server.core.llm_setup import setup_global_llm
from server.features.register.router import router as register_router
from server.features.chat.router import router as chat_router

def create_app() -> FastAPI:
    # 0. Load environment variables from .env file
    load_dotenv()

    # 1. Boot global settings before App starts routing
    setup_global_llm()

    # 2. Setup FastAPI App
    app = FastAPI(title="PandasAI Excel Server")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Register Vertical Slice Routers
    app.include_router(register_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    return app

app = create_app()
