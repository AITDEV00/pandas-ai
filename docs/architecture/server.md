# Server Architecture — Vertical Slice

The chat-excel-server is a FastAPI service built on **PandasAI v3.0.0**. It uses
**Vertical Slice Architecture (VSA)**: each feature is self-contained in its own
directory under `server/features/`, with only truly cross-cutting concerns in
`server/core/`.

```
server/
├── main.py                    # FastAPI app entry point (create_app())
├── core/                      # Shared core utilities
│   ├── llm_setup.py          # Global LLM configuration
│   └── agent_store.py        # Agent state management
└── features/                  # Feature slices
    ├── chat/                  # Chat feature
    │   ├── router.py         # API routes
    │   ├── handler.py        # Business logic
    │   └── models.py         # Pydantic models
    └── register/             # Register feature
        ├── router.py
        ├── handler.py
        └── models.py
```

## VSA principles

- **Each feature is self-contained** — router, handler, models live in one directory.
- **No horizontal layers** — avoid the traditional service/repository split.
- **Feature isolation** — each slice handles its own concerns.
- **Shared core** — only genuinely cross-cutting concerns go in `server/core/`.

## Tech stack

- **Python 3.11** (WSL2)
- **FastAPI** for the REST API
- **PandasAI v3.0.0** for natural-language data querying
- **LiteLLM** for LLM abstraction
- **Pydantic** for request/response models
- **Uvicorn** as the ASGI server
- **Poetry** for dependency management

## Adding a feature

1. Create a directory under `server/features/<name>/` with `router.py`,
   `handler.py`, and `models.py`.
2. Register the router in `server/main.py` → `create_app()`.

See also [Code Generation Pipeline](codegen-pipeline.md) and
[Concurrent Registration Logic Map](concurrent-registration-logic-map.md).