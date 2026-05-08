---
description: Project context and coding guidelines for the PandasAI chat-excel-server service using Vertical Slice Architecture (VSA)
applyTo: '**/pandas-ai/**'
---

# PandasAI Chat Excel Server - Project Context

## Project Overview

This is a service built on **PandasAI v3.0.0**, a Python framework that enables natural language querying of Excel files and databases. The service provides a REST API for chatting with Excel data using AI-powered code generation.

## Key Paths

- **Service code**: `/home/jyao/ait-projects/chat-excel-server/pandas-ai/server/`
- **PandasAI source**: `/home/jyao/ADEO/services/ait-icarus/pandas-ai/pandasai/`
- **PandasAI docs**: `/home/jyao/ADEO/services/ait-icarus/pandas-ai/docs/v3/`
- **Examples**: `/home/jyao/ADEO/services/ait-icarus/pandas-ai/examples/`
- **Root workspace**: `/home/jyao/ADEO/services/ait-icarus/pandas-ai/`

## Architecture: Vertical Slice Architecture (VSA)

The server uses **Vertical Slice Architecture** where each feature is organized in its own directory under `server/features/`:

```
server/
├── main.py                    # FastAPI app entry point
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

### VSA Principles

- **Each feature is self-contained**: router, handler, models in one directory
- **No horizontal layers**: avoid traditional service/repository pattern
- **Feature isolation**: each slice handles its own concerns
- **Shared core**: only truly cross-cutting concerns go in `core/`

## Technology Stack

- **Python 3.11** (WSL2 environment)
- **FastAPI** for REST API
- **PandasAI v3.0.0** for natural language data querying
- **LiteLLM** for LLM abstraction
- **Pydantic** for request/response models
- **Uvicorn** as ASGI server
- **Poetry** for dependency management and venv

## Development Environment

- **Always in WSL2**: use Linux paths and commands
- **Docker support**: see `Dockerfile` and `docker-compose.yml`
- **Build commands**: use `Makefile` targets (e.g., `make test_core`)
- **Code quality**: ruff for formatting, pytest for testing

## PandasAI Usage Patterns

### Basic Configuration
```python
import pandasai as pai
from pandasai_litellm.litellm import LiteLLM

# Configure LLM
pai.config.set({
    "llm": llm,
    "verbose": True
})

# Load data
df = pai.read_csv("path/to/file.csv")

# Chat with data
response = df.chat("What is the average revenue?")
```

### Server Pattern
- LLM is configured globally in `server/core/llm_setup.py`
- Each conversation maintains state via agent store
- Features are registered as FastAPI routers in `main.py`

## Coding Guidelines

1. **Follow VSA strictly**: new features go in `server/features/<feature_name>/`
2. **Use Pydantic models**: all request/response data must be typed
3. **Keep features isolated**: avoid cross-feature dependencies
4. **Use existing patterns**: follow the `chat` feature structure as template
5. **WSL2 paths**: always use absolute Linux paths, not Windows paths
6. **Type hints**: all functions should have type annotations
7. **Error handling**: use PandasAI's exception system from `pandasai.exceptions`

## Common Tasks

- **Add new feature**: create directory under `server/features/` with router, handler, models
- **Register router**: add to `server/main.py` `create_app()` function
- **Test locally**: run `uvicorn server.main:app --reload`
- **Run in Docker**: use `docker-compose up`

## Important Notes

- The service uses a custom LLM endpoint (see `llm_setup.py`)
- SSL verification is disabled for the internal inference engine
- Conversations maintain memory across multiple turns
- PandasAI generates Python code from natural language queries
