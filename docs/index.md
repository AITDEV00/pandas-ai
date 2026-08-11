# PandasAI — Internal Dev Docs

This site is a **quick navigator** for the internal engineering documentation
and run artifacts in this workspace. It maps where every analysis, audit,
root-cause register, and run report lives, so you know exactly which file to
open for a given task.

> The Mintlify public docs (`v2/`, `v3/`, authored in `.mdx`) are **not** part
> of this MkDocs site — they are served separately via `docs/mint.json`.

## Quick Links

| Topic | Entry point |
|-------|-------------|
| Architecture & server (Vertical Slice) | [Architecture](architecture/index.md) |
| Root causes & debugging | [Error Analysis](error-analysis/index.md) |
| Column selection work | [Column Selection](column-selection/index.md) |
| Audits & fixes | [Audits & Fixes](audit/index.md) |
| Setup & API reference | [Setup & API](setup-and-api-reference.md) |
| MkDocs / this site | [MkDocs Setup](mkdocs-setup.md) |
| Run logs & E2E reports | [Run Artifacts](run-artifacts/index.md) |

---

## Docs Map

- **Architecture** — server slice layout, code-generation pipeline, registration logic.
- **Error analysis & root causes** — register of LLM codegen failures, code-smell detection technique, the retry thinking-trace analysis and the per-attempt logic map.
- **Column selection** — the blocker analysis and DuckDB search options for struct columns.
- **Audits & fixes** — the 2025-05-07 v3.0.0 audit register and its planned/solved fixes.
- **Setup & API** — how to run the server, test, and call the API.
- **Run artifacts** — where E2E reports, conv logs, and per-question stability results are stored (under `run/`).

## Run-Artifact layout (`run/`)

```
run/
├── conv_logs/                  # per-conversation chat turn summaries (*.md)
├── e2e_reports/                # E2E batch outputs (timestamped dirs)
│   └── stability/              # per-question 1x/3x/5x JSON + summaries
├── tools/                      # schema / semantic-model helper scripts
├── *.xlsx / *.json             # source datasets & semantic model
└── archive/                    # old reports & logs packed into tarballs
```

See [Run Artifacts](run-artifacts/index.md) for the current cleanup policy.