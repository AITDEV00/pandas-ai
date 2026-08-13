#!/usr/bin/env python3
"""Dev-environment driver for the pandas-ai server + question bank.

Registers run/dev-env/dev-env.csv (+ semantic model) and runs the question bank
from test_bank.yaml, capturing the FULL HTTP response (incl. pipeline trace)
into per-run subfolders under run/dev-env/runs/<run_id>/.

Usage:
    python run/dev-env/run_dev.py                          # run all bank questions
    python run/dev-env/run_dev.py Q_DEV_PROJECTS Q_DEV_SKILLS
    python run/dev-env/run_dev.py --chat "some query"
    python run/dev-env/run_dev.py --register-only
    python run/dev-env/run_dev.py --conversation <id> --run-name myrun
"""
import argparse
import base64
import datetime as _dt
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
RUNS_DIR = HERE / "runs"
BASE_URL = "http://localhost:8000"

DATA_FILE = HERE / "dev-env.csv"
SEMANTIC_MODEL = HERE / "semantic-model.json"
PANDAI_CONFIG = HERE / "pandasai_config.json"
CHAT_CONFIG = HERE / "chat_config.json"
TEST_BANK = HERE / "test_bank.yaml"


def _resolve_cache_buster(explicit: str) -> str:
    """Return a cache-buster string.

    Priority:
      1. --cache-buster CLI arg (explicit)
      2. CODEGEN_CACHE_BUSTER env var (matches the e2e harness convention)
      3. empty string (no buster → caching may apply)
    """
    if explicit:
        return explicit
    return os.environ.get("CODEGEN_CACHE_BUSTER", "").strip()


def _apply_cache_buster(query: str, buster: str) -> str:
    """Append a hidden HTML comment to the query to defeat LLM prompt caching.

    Mirrors tests/e2e/run_stability_agent.py which appends
    `<!-- stability:{cache_buster} -->`. A fresh buster value per run forces
    fresh codegen even when the question text is identical.
    """
    if not buster:
        return query
    return f"{query}\n<!-- devrun:{buster} -->"


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_csv_base64(path: Path) -> str:
    return "data:text/csv;base64," + base64.b64encode(path.read_bytes()).decode()


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


def _new_run_dir(tag: str = "") -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    name = _ts()
    if tag:
        name = f"{name}_{tag}"
    d = RUNS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def register(client: httpx.Client, base_url: str, run_dir: Path) -> str:
    semantic = json.loads(SEMANTIC_MODEL.read_text())
    pandasai_config = json.loads(PANDAI_CONFIG.read_text())
    payload = {
        "base64_data": _load_csv_base64(DATA_FILE),
        "mimetype": "text/csv",
        "semantic_model": semantic,
        "pandasai_config": pandasai_config,
    }
    _write_json(run_dir / "register_request.json", payload)
    t0 = time.time()
    r = client.post(f"{base_url}/api/register/base64", json=payload, timeout=600)
    dt = time.time() - t0
    print(f"[register] {r.status_code} in {dt:.1f}s")
    if r.status_code != 200:
        _write_json(run_dir / "register_response.json", {"status": r.status_code, "detail": r.text})
        print(r.text[:3000])
        sys.exit(1)
    body = r.json()
    _write_json(run_dir / "register_response.json", body)
    conv_id = body.get("conversation_id")
    (run_dir / "conv_id.txt").write_text(conv_id)
    print(f"[conversation_id] {conv_id}")
    return conv_id


def run_chat(client, base_url, conv_id, qid, query, out_dir, cache_buster=""):
    config = json.loads(CHAT_CONFIG.read_text())
    final_query = _apply_cache_buster(query, cache_buster)
    body = {"conversation_id": conv_id, "query": final_query, **config}
    _write_json(out_dir / "request.json", body)
    t0 = time.time()
    r = client.post(f"{base_url}/api/chat", json=body, timeout=900)
    elapsed = time.time() - t0
    print(f"\n[chat {qid}] {r.status_code} in {elapsed:.1f}s")
    summary = {"qid": qid, "http_status": r.status_code, "elapsed_seconds": round(elapsed, 2)}

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"raw": r.text}
        _write_json(out_dir / "response.json", {"http_status": r.status_code, "elapsed_seconds": round(elapsed, 2), "detail": detail})
        (out_dir / "summary.txt").write_text(
            f"[{qid}] ERROR {r.status_code} in {elapsed:.1f}s\nquery: {query}\n\n{json.dumps(detail, indent=2, default=str)}\n"
        )
        print(f"[error] {json.dumps(detail, default=str)[:1500]}")
        summary["status"] = "fail_500"
        return summary

    resp = r.json()
    _write_json(out_dir / "response.json", resp)
    resp_type = resp.get("type")
    summary["status"] = "pass" if resp_type != "error" else "fail"
    summary["response_type"] = resp_type
    summary["answer"] = str(resp.get("response"))[:2000]
    summary["selected_columns"] = resp.get("selected_columns")
    summary["retrieval_mode"] = resp.get("retrieval_mode")
    summary["timings"] = resp.get("timings")

    print(f"[type] {resp_type}")
    print(f"[answer] {str(resp.get('response'))[:2000]}")
    print(f"[selected_columns] {resp.get('selected_columns')}")
    print(f"[retrieval_mode] {resp.get('retrieval_mode')}")

    (out_dir / "summary.txt").write_text(
        f"[{qid}] {resp_type} in {elapsed:.1f}s\n"
        f"answer: {resp.get('response')}\n"
        f"selected_columns: {resp.get('selected_columns')}\n"
        f"retrieval_mode: {resp.get('retrieval_mode')}\n"
        f"timings: {json.dumps(resp.get('timings'), default=str)}\n"
    )
    return summary


def run_bank_parallel(client, base_url, conv_id, questions, want, run_dir, cache_buster="", workers=5):
    """Run the given bank questions concurrently against a single conversation.

    Each question writes into its own subfolder under `run_dir`. Returns a list
    of summary dicts (order preserved by qid).
    """
    results = {}
    # A shared client for all worker threads.
    shared = client
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for q in questions:
            qid = q["id"]
            if want and qid not in want:
                continue
            out_dir = run_dir / qid
            futs[ex.submit(run_chat, shared, base_url, conv_id, qid, q["query"], out_dir, cache_buster)] = qid
        for fut in as_completed(futs):
            try:
                summary = fut.result()
            except Exception as e:  # noqa: BLE001
                qid = futs[fut]
                summary = {"qid": qid, "http_status": -1, "elapsed_seconds": 0, "status": "error", "error": str(e)}
                print(f"[{qid}] parallel error: {e}")
            results[summary["qid"]] = summary
    # Preserve bank order
    return [results[q["id"]] for q in questions if (not want or q["id"] in want)]


def run_stability_trials(base_url, bank, want, trials, run_dir, cache_buster="", workers=5):
    """Register a FRESH conversation per trial (clearing history) and run the
    bank in parallel, `trials` times. Returns a list of per-trial summaries.

    Each trial gets a UNIQUE cache buster (base buster + trial index) so that
    no two trials share identical prompt text — essential for an independent
    stability measurement.
    """
    trial_results = []
    with httpx.Client(timeout=900) as client:
        for t in range(1, trials + 1):
            print(f"\n{'='*60}\n=== TRIAL {t}/{trials} ===\n{'='*60}")
            trial_dir = run_dir / f"trial_{t}"
            trial_dir.mkdir(parents=True, exist_ok=True)

            # Unique cache buster per trial (defeats prompt caching between trials)
            trial_buster = cache_buster
            if trial_buster:
                trial_buster = f"{trial_buster}:trial{t}"

            # Fresh register (clears conversation history)
            conv_id = register(client, base_url, trial_dir)
            print(f"[trial {t}] fresh conversation: {conv_id}  cache_buster={trial_buster}")

            perq = run_bank_parallel(client, base_url, conv_id, bank["questions"], want, trial_dir, trial_buster, workers)
            trial_summary = {
                "trial": t,
                "conversation_id": conv_id,
                "cache_buster": trial_buster,
                "results": perq,
            }
            _write_json(trial_dir / "summary.json", {
                "trial": t, "conversation_id": conv_id, "cache_buster": trial_buster,
                "results": perq, "started": _ts(),
            })
            trial_results.append(trial_summary)

    # Roll up all trials into a single top-level summary.json
    _write_json(run_dir / "summary.json", {
        "started": _now(), "run_dir": str(run_dir), "trials": len(trial_results),
        "cache_buster": cache_buster, "trials_results": trial_results,
    })
    return trial_results


def _now() -> str:
    return _ts()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("questions", nargs="*", help="Bank question ids to run (default: all)")
    ap.add_argument("--chat", help="Ad-hoc single query")
    ap.add_argument("--register-only", action="store_true")
    ap.add_argument("--conversation", help="Reuse an existing conversation_id (skips register)")
    ap.add_argument("--run-tag", help="Tag appended to the run folder name")
    ap.add_argument("--bank", default=str(TEST_BANK), help="Path to test_bank.yaml")
    ap.add_argument("--cache-buster", default="", help="Value appended to the query to defeat prompt caching (else CODEGEN_CACHE_BUSTER env)")
    ap.add_argument("--trials", type=int, default=1, help="Number of fresh-register trials to run (clears conversation history each time)")
    ap.add_argument("--parallel", action="store_true", help="Run the bank questions in parallel (threads) within a trial")
    ap.add_argument("--workers", type=int, default=5, help="Max parallel workers when --parallel is set")
    args = ap.parse_args()

    base_url = BASE_URL
    cache_buster = _resolve_cache_buster(args.cache_buster)
    print(f"[cache_buster] {'ON (' + cache_buster + ')' if cache_buster else 'OFF'}")
    with httpx.Client() as client:
        r = client.get(f"{base_url}/health")
        print(f"[health] {r.status_code} {r.json()}")

        tag = args.run_tag or (args.questions[0] if args.questions else "chat")
        run_dir = _new_run_dir(tag)
        print(f"[run_dir] {run_dir}")
        _write_json(run_dir / "meta.json", {"started": _ts(), "bank": args.bank, "questions": args.questions})

        bank = yaml.safe_load(Path(args.bank).read_text())
        questions = bank["questions"]
        want = set(args.questions) if args.questions else None

        # ---- Stability trials mode: fresh register per trial, parallel within trial ----
        if args.trials > 1:
            run_stability_trials(base_url, bank, want, args.trials, run_dir, cache_buster, args.workers)
            print(f"\n[run summary] {run_dir / 'summary.json'}")
            return 0

        # ---- Single trial, parallel ----
        if args.parallel:
            conv_id = args.conversation
            if conv_id is None:
                conv_id = register(client, base_url, run_dir)
            else:
                (run_dir / "conv_id.txt").write_text(conv_id)
                print(f"[reuse conversation] {conv_id}")
            perq = run_bank_parallel(client, base_url, conv_id, questions, want, run_dir, cache_buster, args.workers)
            _write_json(run_dir / "summary.json", {
                "started": _now(), "run_dir": str(run_dir), "conversation_id": conv_id,
                "parallel": True, "results": perq,
            })
            print(f"\n[run summary] {run_dir / 'summary.json'}")
            return 0

        conv_id = args.conversation
        if conv_id is None:
            conv_id = register(client, base_url, run_dir)
        else:
            (run_dir / "conv_id.txt").write_text(conv_id)
            print(f"[reuse conversation] {conv_id}")

        if args.register_only:
            print(f"\nUse this conversation_id: {conv_id}")
            return 0

        if args.chat:
            run_chat(client, base_url, conv_id, "ADHOC", args.chat, run_dir / "ADHOC", cache_buster)
            return 0

        results = []
        for q in questions:
            qid = q["id"]
            if want and qid not in want:
                continue
            summary = run_chat(client, base_url, conv_id, qid, q["query"], run_dir / qid, cache_buster)
            results.append(summary)

        _write_json(run_dir / "summary.json", {
            "started": _now(), "run_dir": str(run_dir), "conversation_id": conv_id, "results": results,
        })
        print(f"\n[run summary] {run_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
