# Chat Context — pandas-ai v3.0.0 Accuracy/Latency Optimization

**Model**: DeepSeek-V4-Flash-0731 (`openai/deepseek-ai/DeepSeek-V4-Flash-0731`), sparse MoE, temp 0.0
**Workspace**: `/home/jyao/ADEO/service/pandas-ai` · **Branch**: `jya0-v3.0.0` (pushed to `AITDEV00/pandas-ai`, in sync)
**Repos**: sinaptik-ai/pandas-ai (fork), 567-labs/instructor (fork `jya0-v1.15.4`)

---

## Architecture (2-step pipeline)
1. **Step-1 column selection** — `ColumnSelector`, temp 0. Uses shared YAML concept registry (5-path expansion: direct match, measurement/rating, applied/evidence, summary/profile, foundation/background). `_detect_missing_struct_groups()` in `agent/base.py` is data-driven (scans actual DataFrame schema per path).
2. **Step-2 codegen** — `CodeGenerator` with `structural_validator` + `CodeCleaner` + `CodeRequirementValidator`. Execution in `code_executor` sandbox. DuckDB for SQL, `UNNEST` for list-of-struct columns.

## Validated env (both local & Docker — committed in Makefile.build)
```
CODE_GENERATION_USE_INSTRUCTOR=true
CODE_GENERATION_TEMPERATURE=0.0
CODE_GENERATION_MAX_TOKENS=10000
COLUMN_SELECTION_MAX_TOKENS=10000
STRUCTURED_LLM_MODEL_NAME=openai/deepseek-ai/DeepSeek-V4-Flash-0731
# TLS bypass (internal LiteLLM):
NODE_TLS_REJECT_UNAUTHORIZED=0 SSL_CERT_FILE="" REQUESTS_CA_BUNDLE=""
```
**LLM**: LiteLLM `https://litellm.adeoaiengine.ecouncil.ae/c1`. Instructor `Mode.MD_JSON` for structured codegen.

## Environment setup (always use `python`, venv at `.venv`)
```bash
cd /home/jyao/ADEO/service/pandas-ai
source .venv/bin/activate
export NODE_TLS_REJECT_UNAUTHORIZED=0 SSL_CERT_FILE="" REQUESTS_CA_BUNDLE=""
set -a && . ./.env && set +a
# + the CODE_GENERATION_* / COLUMN_SELECTION_* / STRUCTURED_LLM_MODEL_NAME exports above
```

## Stability harness
`tests/e2e/run_stability_agent.py` — reads `STABILITY_QUESTIONS` from `run_stability.py`, filters by `QUESTIONS` env, runs via `ProcessPoolExecutor` (`STABILITY_WORKERS=4`), writes per-run JSONs + `summary.json`. `RUNS=5`, `CODEGEN_CACHE_BUSTER` forces fresh codegen.
```bash
OUTPUT_DIR=/tmp/xyz QUESTIONS="R13" STABILITY_WORKERS=4 RUNS=5 \
CODEGEN_CACHE_BUSTER="fix-$(date +%s)" python tests/e2e/run_stability_agent.py
```

## Current status (last verified)
- **Full 19Q stability bank**: 94/95 pass on the archived run `run/e2e_reports/stability/profiled/20260812_all19_perq_94of95/`.
- **Local one-shot run** (source + corrected `.env`, once per question) → `20260812_local_verify/` with `COMPARISON.md`:
  - **19/19 functional, 17/19 fully equivalent** to archived pass answers. R13 improved (local `0` vs old ref `nan` bug).
  - **2/19 differ only in rows surfaced (R8, R9)** — known multi-struct column-selection variance, not code regression.
  - Transient model variance (all pass on re-run): R3 empty-code, R12 double-bracket validator, Q30 empty df, R7 "No employees found".

## Key files
- `pandasai/llm/base.py` — `_extract_code_robust()` raises `NoCodeFoundError` (~line 169); `generate_code()` uses it for structured path.
- `extensions/llms/litellm/pandasai_litellm/litellm.py` — `LiteLLM.generate_code_structured()` (~line 263) via instructor. **Note: two module objects exist** (imported as `pandasai_litellm.litellm` and `extensions.llms.litellm.pandasai_litellm.litellm`) — patch the `pandasai_litellm` one.
- `pandasai/core/code_generation/structural_validator.py` — `_check_struct_field_keys` flags struct key bracket mismatches (source of R12 false-positive).
- `Makefile.build` — validated env defaults + `run`/`run-local` targets. `.env` git-ignored, used at runtime via `--env-file`.
- `Dockerfile` — reverted to upstream (no ENV additions). Image: `adeo-icarus-pandasai-server:latest` (built).

## Pending / possible next steps
- [ ] Optional: add logging in `generate_code_structured` to persist raw `code` field (better diagnostics for empty-code case).
- [ ] Optional: push Docker image to Dockerhub/Harbor (`make login && make push`, `make harbor_upload`).
- [ ] R8/R9 column-selection variance (skills/rating multi-struct) — possible further template tuning.
- [ ] Consider migrating more struct-group detection to the data-driven `_detect_missing_struct_groups` pattern.