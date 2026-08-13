# Dev Environment — pandas-ai server

Reusable local dev harness for hitting the running pandas-ai server with the
`dev-env` dataset.

## Files

| File | Purpose |
|------|---------|
| `dev-env.csv` | Source dataset (uploaded via `/api/register/base64`) |
| `semantic-model.json` | PandasAI SemanticLayerSchema payload |
| `pandasai_config.json` | Registration-time config (`enrich_column_values`, `auto_fill_descriptions`) |
| `chat_config.json` | Per-question chat params (output_type, column selection, message_history) |
| `questions.json` | Map of question id → query text |
| `run_dev.py` | Helper: register CSV + run questions against the server |
| `.env` / `.env.example` | Credentials copied from the repo root (server reads them at startup) |

## Prerequisites

The server must be running locally on `http://localhost:8000` (with `.env` loaded):

```bash
cd /home/jyao/ADEO/service/pandas-ai
set -a && . ./.env && set +a && source .venv/bin/activate
export NODE_TLS_REJECT_UNAUTHORIZED=0 SSL_CERT_FILE="" REQUESTS_CA_BUNDLE=""
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

## Usage

```bash
source .venv/bin/activate
export NODE_TLS_REJECT_UNAUTHORIZED=0 SSL_CERT_FILE="" REQUESTS_CA_BUNDLE=""

# register + run all questions in questions.json
python run/dev-env/run_dev.py

# register + run only specific question ids
python run/dev-env/run_dev.py Q1 Q3 Q13

# register + one ad-hoc query
python run/dev-env/run_dev.py --chat "what is the average salary?"

# register only (print conversation_id for reuse)
python run/dev-env/run_dev.py --register-only

# reuse an existing conversation_id
python run/dev-env/run_dev.py --conversation <id> --chat "follow-up question"
```

## Request payloads

**Registration** (`POST /api/register/base64`):
```json
{
  "base64_data": "<base64 of dev-env.csv>",
  "mimetype": "text/csv",
  "semantic_model": { ...semantic-model.json... },
  "pandasai_config": {
    "enrich_column_values": true,
    "auto_fill_descriptions": false
  }
}
```

**Chat** (`POST /api/chat`) — from `chat_config.json`:
```json
{
  "conversation_id": "<id>",
  "query": "<question>",
  "output_type": "string",
  "column_selection_enabled": true,
  "column_selection_threshold": 30,
  "column_values_budget_ratio": 0.1,
  "message_history": 2
}
```

## Notes

- **`message_history`**: default (if omitted) is **10**. `2` = include the last 2
  user turns (rounded up to complete user→assistant pairs). `0` = no history; `-1` = all.
- **Env / creds**: `run/dev-env/.env` is copied from the repo root `.env` — the server
  (not this script) reads it. Keep credentials out of git (`.env` is ignored).
- The script does **not** load `.env` itself; it just talks to the already-running server.