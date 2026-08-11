# Run Artifacts

Where E2E reports, conversation logs, and per-question stability results live
under `run/`, and the current cleanup/archive policy.

## Directory layout

```
run/
├── conv_logs/                  # per-conversation chat turn summaries (*.md)
│   └── <uuid>.md
├── e2e_reports/                # E2E batch outputs (timestamped dirs)
│   ├── <YYYYMMDD_HHMMSS>_<run_type>/
│   └── stability/              # per-question 1x/3x/5x JSON + summaries
├── tools/                      # schema / semantic-model helper scripts
│   ├── generate_semantic_model.py
│   ├── generate_vocab.py
│   ├── get_schema.py
│   └── verify_classification.py
├── *.xlsx / *.json             # source datasets & semantic model
│   ├── full data unflattened.xlsx
│   ├── full data unflattened context return.json
│   ├── semantic_model.json
│   └── table definition and types.xlsx
└── archive/                    # old reports & logs packed into tarballs
```

## Stability reports

Per-question results are written to `run/e2e_reports/stability/`:

- `Q<id>_<N>x.json` — per-question results across N runs.
- `R<id>_..._<N>x.json` — retried questions (e.g. `R11_projects_982_1177_1x.json`).
- `all_retried_summary.json` — the batch summary of all retried questions.
- `all_retried_rerun.log` — full console log of a batch re-run.

## Archive policy

Everything under `run/` is **gitignored** (`run/e2e_reports/`, `run/conv_logs/`),
so it is never committed. To keep the working tree from bloating:

1. Old, completed E2E report directories and old conv logs are packed into a
   timestamped tarball under `run/archive/`.
2. Recent runs, the `stability/` reports, `tools/`, and the source data files
   stay in place.
3. Re-run the archive as needed (see below).

## Re-archive script

The cleanup is done with a small script kept in the repo so it is repeatable:

```bash
# dry-run first
python run/archive/archive_old_runs.py --dry-run

# actually pack old e2e dirs + old conv logs into run/archive/
python run/archive/archive_old_runs.py
```

Run it with the `.venv` activated.