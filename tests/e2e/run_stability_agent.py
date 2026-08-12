"""Run the STABILITY question bank (19 Q) through the production agent.chat()
path, 5 runs each, IN PARALLEL across (question, run) tasks via a process pool,
with per-run cache busting. Records for every run:

  - executed (bool) / response_type / response_value / error / failure_stage
  - code_attempts: how many generation + execution attempts (the retry count)
  - timings: column_selection, code_generation, code_execution, total
  - retried: True if gen or exec attempts > 1 (the "had to retry once" signal)

Usage (env same as run_chat_retry_all.py + QUESTIONS, STABILITY_Q, RUNS):
  CODE_GENERATION_USE_INSTRUCTOR=true CODE_GENERATION_TEMPERATURE=0.2 \
  STRUCTURED_LLM_MODEL_NAME="openai/deepseek-ai/DeepSeek-V4-Flash-0731" \
  OUTPUT_DIR=/tmp/stability_agent STABILITY_WORKERS=4 \
  python tests/e2e/run_stability_agent.py

Set QUESTIONS="Q13a,Q19" and/or RUNS=3 to narrow.
"""
import json
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from run_step2_all import PROJECT_ROOT, OUTPUT_DIR, build_agent
from run_stability import STABILITY_QUESTIONS


def run_one(question_id: str, query: str, run_no: int) -> dict:
    from pandasai.agent.state import AgentState

    out = {
        "question": question_id,
        "run": run_no,
        "query": query,
        "executed": None,
        "response_type": None,
        "response_value": None,
        "error": None,
        "failure_stage": None,
        "code_attempts": [],
        "timings": {},
        "elapsed_total": None,
    }

    agent = build_agent()
    state: AgentState = agent._state

    # Capture every [LLM-CALL] / [ATTEMPT] logger line for inspection.
    captured_logs = []
    orig_logger = state.logger

    class _CaptureLogger:
        def log(self, msg):
            captured_logs.append(str(msg))
            if orig_logger is not None:
                orig_logger.log(msg)

    state.logger = _CaptureLogger()

    # Per-run cache buster: unique marker so the provider can't serve a stale
    # cached codegen response for an identical prompt across runs.
    cache_buster = os.environ.get("CODEGEN_CACHE_BUSTER", "").strip()
    chat_query = (
        f"{query}\n<!-- stability:{cache_buster} -->"
        if cache_buster else query
    )

    t_start = time.time()
    try:
        result = agent.chat(chat_query)
        out["response_type"] = getattr(result, "type", None)
        out["response_value"] = _safe_value(getattr(result, "value", None))
        out["executed"] = result.type != "error"
        out["error"] = getattr(result, "error", None)
        if result.type == "error":
            out["failure_stage"] = "execution"
    except Exception as e:
        out["executed"] = False
        out["error"] = str(e)
        out["failure_stage"] = "uncaught_exception"
        out["error_traceback"] = traceback.format_exc()

    out["elapsed_total"] = round(time.time() - t_start, 2)
    out["timings"] = dict(state.timings)
    out["code_attempts"] = state.code_attempts

    # Retry classification: "had to retry" = more than one generation attempt
    # OR more than one execution attempt. A normal successful run is exactly
    # 1 generation + 1 execution (total attempts == 2) — that is NOT a retry.
    gen_attempts = sum(1 for a in out["code_attempts"] if a.get("phase") == "generation")
    exec_attempts = sum(1 for a in out["code_attempts"] if a.get("phase") == "execution")
    out["gen_attempts"] = gen_attempts
    out["exec_attempts"] = exec_attempts
    out["retried"] = bool(gen_attempts > 1 or exec_attempts > 1)

    # Restore the real logger.
    state.logger = orig_logger
    return out


def _safe_value(value):
    if value is None:
        return None
    try:
        if hasattr(value, "head"):
            return value.head(5).to_dict("records")
    except Exception:
        pass
    s = str(value)
    return s[:2000]


def _worker(args: tuple) -> dict:
    """ProcessPool worker: set up global LLM then run one (question, run)."""
    qid, query, r, cache_buster = args
    try:
        from server.core.llm_setup import setup_global_llm
        setup_global_llm()
    except Exception:
        pass
    os.environ["CODEGEN_CACHE_BUSTER"] = cache_buster
    try:
        return run_one(qid, query, r)
    except Exception as e:
        return {
            "question": qid, "run": r, "query": query,
            "executed": False, "response_type": None, "response_value": None,
            "error": str(e), "failure_stage": "worker_error",
            "error_traceback": traceback.format_exc(),
            "code_attempts": [], "timings": {}, "elapsed_total": None,
            "gen_attempts": 0, "exec_attempts": 0, "retried": False,
        }


def main():
    from server.core.llm_setup import setup_global_llm
    setup_global_llm()

    runs = int(os.environ.get("RUNS", "5"))
    filter_env = os.environ.get("QUESTIONS", "").strip()
    if filter_env:
        filter_set = {p.strip().lower() for p in filter_env.split(",") if p.strip()}
        qs = {k: v for k, v in STABILITY_QUESTIONS.items() if k.lower() in filter_set}
    else:
        qs = STABILITY_QUESTIONS

    run_dir = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_stability_agent"
    run_dir.mkdir(parents=True, exist_ok=True)
    workers = int(os.environ.get("STABILITY_WORKERS", "4"))
    print(f"Running stability bank ({len(qs)} questions x {runs} runs) in PARALLEL")
    print(f"Workers: {workers}")
    print(f"Cache buster: {'ON' if os.environ.get('CODEGEN_CACHE_BUSTER') else 'OFF'}")
    print(f"Output: {run_dir}\n")

    # Build all (question, run) tasks with a unique per-run cache-buster marker
    # so the provider can't serve a stale cached codegen response across runs.
    tasks = []
    for qid, query in qs.items():
        for r in range(1, runs + 1):
            tasks.append((qid, query, r, f"{qid}-r{r}-{int(time.time())}"))

    all_results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, t): t for t in tasks}
        for fut in as_completed(futs):
            t = futs[fut]
            qid, _, r, _ = t
            try:
                out = fut.result()
            except Exception as e:
                out = {
                    "question": qid, "run": r, "query": None,
                    "executed": False, "response_type": None,
                    "error": str(e), "failure_stage": "pool_error",
                    "code_attempts": [], "timings": {},
                    "elapsed_total": None, "gen_attempts": 0,
                    "exec_attempts": 0, "retried": False,
                }
            all_results.append(out)
            status = "OK" if out["executed"] else "FAIL"
            retried = " RETRY" if out.get("retried") else ""
            print(
                f"  [{qid:>20} r{r}/{runs}] {status:4}{retried}  "
                f"type={out['response_type']}  gen={out.get('gen_attempts')} "
                f"exec={out.get('exec_attempts')}  tot={out.get('elapsed_total')}s",
                flush=True,
            )
            with open(run_dir / f"{qid}_r{r}.json", "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False, default=str)

    # Summary
    print("\n" + "=" * 80)
    print(f"STABILITY AGENT SUMMARY ({len(qs)} questions x {runs} runs)")
    print("=" * 80)
    total = len(all_results)
    ok = sum(1 for o in all_results if o["executed"])
    retried = sum(1 for o in all_results if o.get("retried"))
    print(f"  Success:        {ok}/{total}")
    print(f"  Retried:        {retried}/{total}")
    print(f"  Output:         {run_dir}")
    print()
    # Per-question aggregate
    print("  Per-question (across runs):")
    for qid in qs:
        qres = [o for o in all_results if o["question"] == qid]
        qok = sum(1 for o in qres if o["executed"])
        qret = sum(1 for o in qres if o.get("retried"))
        times = [o.get("elapsed_total") or 0 for o in qres]
        avg_t = round(sum(times) / len(times), 1) if times else 0
        print(f"    {qid:>20}  ok={qok}/{len(qres)}  retry={qret}  avg_t={avg_t}s")
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()