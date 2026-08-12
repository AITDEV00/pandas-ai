FROM python:3.11-slim

WORKDIR /app

# Install poetry extremely leaning using pip's no-cache flag
RUN pip install --no-cache-dir poetry

# Copy dependency files and context
COPY pyproject.toml poetry.lock ./
COPY . .

# 1. Disable virtualenvs (since docker is isolated native)
# 2. Only install 'main' group dependencies (dropping pytest, ruff, CI tools)
# 3. Aggressively delete all package wheel caches after install in the SAME layer!
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi \
    && rm -rf /root/.cache/pypoetry /root/.cache/pip

# Inject extras without caching
RUN pip install --no-cache-dir httpx ./extensions/llms/litellm instructor fastapi uvicorn python-multipart pydantic

EXPOSE 8000

# Run the Vertical Slice API Server bound to external networking
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
