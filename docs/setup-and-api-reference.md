# Setup Instructions for PandasAI with Custom VLLM Proxy & LiteLLM

## 1. Install Poetry and Dependencies

```bash
# Navigate to the PandasAI project root directory
cd /home/jyao/ait-projects/chat-excel-server/pandas-ai

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install Python 3.11 (if needed)
sudo apt update
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.11 python3.11-venv -y
```

## 2. Install PandasAI Core Dependencies

```bash
# Sync / Install the core PandasAI dependencies using your lock file
poetry sync

# Inject the httpx unverified client and the pandasai-litellm extension
# directly into the managed Poetry environment (prevents modifying pyproject.toml)
poetry run pip install httpx ./extensions/llms/litellm

# Run the get_started.py script
poetry run python get_started.py

# Install FastAPI networking layers injected into the poetry environment
poetry run pip install fastapi uvicorn python-multipart
```

## 3. `/register` — Base64 File Upload

Register-time config controls schema building:

| Parameter | Description |
|-----------|-------------|
| `enrich_column_values` | Extract sample values for each column (stored in schema) |
| `categorical_max_unique` | Max unique values before a column is no longer considered categorical |
| `auto_fill_descriptions` | Use LLM to fill missing column descriptions after enrichment |

**Example payload** (POST to `http://localhost:8000/register`):

```json
{
  "base64_data": "data:text/csv;base64,RGF0Z...<BASE64_STRING_HERE>",
  "mimetype": "text/csv",
  "pandasai_config": {
    "enrich_column_values": true,
    "categorical_max_unique": 50,
    "auto_fill_descriptions": true
  },
  "llm_config": {
    "api_key": "sk-your-vllm-key",
    "base_url": "http://your-vllm-host/v1",
    "model_name": "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4",
    "llm_context_window": 250000,
    "temperature": 0.1,
    "max_tokens": 1024
  }
}
```

## 4. `/register/file` — Multipart Form Upload

Use this when sending the raw file over HTTP instead of base64:

```bash
curl -X POST http://localhost:8000/register/file \
  -F "file=@/path/to/your/data.csv" \
  -F 'pandasai_config={"enrich_column_values": true, "auto_fill_descriptions": true}' \
  -F 'llm_config={"api_key": "sk-your-vllm-key", "base_url": "http://your-vllm-host/v1", "model_name": "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4", "llm_context_window": 250000}'
```

## 5. Register vs Chat Config Separation

> **Note**: `/register` only controls schema building. Query-time tuning is done via `/chat`.

Fields that were previously in `pandasai_config` but are now per-query:

| Field | Moved To | Reason |
|-------|----------|--------|
| `llm_context_window` | `llm_config` | It's an LLM property |
| `column_values_budget_ratio` | `/chat` | Token budget is query-time |
| `column_selection_threshold` | `/chat` | Column selection is query-time |
| `column_selection_enabled` | `/chat` | Column selection is query-time |

## 6. `/chat` — Query-Time Controls

Column selection (Step 1) triggers when:
- `column_selection_enabled=true` (force on), OR
- `column_selection_enabled=null` (auto-detect) AND total columns ≥ `column_selection_threshold`

Per-query overrides (`null` = use Config default):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `column_selection_enabled` | `null` | `true`=force, `false`=skip, `null`=auto-detect |
| `column_selection_threshold` | `30` | Auto-detect threshold |
| `column_values_budget_ratio` | `0.10` | Fraction of context window for sample values |
| `message_history` | `10` | How many past user turns to include in LLM context |

**Example payload** (POST to `http://localhost:8000/chat`):

```json
{
  "conversation_id": "<conversation_id_from_register_response>",
  "query": "Show me the top 10 employees by salary",
  "output_type": "dataframe",
  "message_history": 10,
  "column_selection_enabled": null,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.10
}
```

**Supported `output_type` values**: `"string"`, `"number"`, `"dataframe"`, `"plot"`, `"auto"`  
(Use `"auto"` or omit to let the LLM choose the best type)
