"""Run the FULL production retry path for ALL questions via agent.chat().

Unlike `run_step2_all.py` (which uses single-shot codegen + execute_code to
isolate FIRST-TRY accuracy), this harness uses the real end-to-end pipeline:

    agent.chat(query)
      -> _process_query
          -> _apply_column_selection            (Step 1, structured)
          -> generate_code_with_retries(query)  (up to 1 + max_retries attempts)
          -> execute_with_retries(code)         (up to 1 + max_retries attempts;
                                                 on exec error regenerates code
                                                 via _regenerate_code_after_error)
          -> ResponseParser.parse(...)

So this measures PRODUCTION accuracy/performance INCLUDING the retry mechanic
on both the code-generation and code-execution phases. Each question runs on a
fresh Agent (register file -> chat) so retries/conversation state stay isolated.

For each question we log:
  - response type + value (string/number/dataframe/plot/error)
  - retry attempts (code_attempts) with per-attempt phase/error
  - timings (column_selection, code_generation, code_execution, total)
  - LLM call records ([LLM-CALL] lines from the captured logger)

Usage (env vars same as run_step2_all.py + CODEGEN_CONCURRENCY, QUESTIONS):
  CODE_GENERATION_USE_INSTRUCTOR=true STRUCTURED_LLM_THINKING=false \
  CODE_GENERATION_THINKING=false CODE_GENERATION_TEMPERATURE=0.2 \
  STRUCTURED_LLM_MODEL_NAME="openai/deepseek-ai/DeepSeek-V4-Flash-0731" \
  OUTPUT_DIR=/tmp/chat_retry python tests/e2e/run_chat_retry_all.py
"""
import json
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from run_step2_all import (
    PROJECT_ROOT,
    OUTPUT_DIR,
    QUESTIONS,
    build_agent,
    PANDASAI_CONFIG,
)


def run_chat_one(q: dict) -> dict:
    """Build a fresh agent, register the CSV, and chat() one question."""
    from pandasai.agent.state import AgentState

    out = {
        "num": q["num"],
        "test_question": q["test_question"],
        "response_type": None,
        "response_value": None,
        "error": None,
        "code_attempts": [],
        "timings": {},
        "llm_calls": [],
        "validators_passed": None,
        "executed": False,
    }

    agent = build_agent()
    state: AgentState = agent._state

    # Wrap the state logger to capture every [LLM-CALL] / [ATTEMPT] line.
    captured_logs = []
    orig_logger = state.logger

    class _CaptureLogger:
        def log(self, msg):
            captured_logs.append(str(msg))
            if orig_logger is not None:
                orig_logger.log(msg)

    state.logger = _CaptureLogger()

    t_start = time.time()
    try:
        # Bust the provider's response cache (keyed on the prompt) so a repeat
        # query isn't served a stale cached codegen. Append a unique marker to
        # the query — it flows into memory and therefore into BOTH the
        # column-selection and code-generation prompts, forcing a fresh LLM
        # response. This mirrors CODEGEN_CACHE_BUSTER from run_step2_all.py.
        cache_buster = os.environ.get("CODEGEN_CACHE_BUSTER", "").strip()
        chat_query = (
            f"{q['query']}\n<!-- chat_run:{cache_buster} -->"
            if cache_buster else q["query"]
        )
        # Production path: chat() does Step-1 selection + Step-2 codegen WITH
        # retries + execution WITH retries.
        result = agent.chat(chat_query)
        out["response_type"] = getattr(result, "type", None)
        out["response_value"] = _safe_value(getattr(result, "value", None))
        out["executed"] = result.type != "error"
        out["error"] = getattr(result, "error", None)
        if result.type == "error":
            out["failure_stage"] = "execution"
    except Exception as e:
        out["error"] = str(e)
        out["failure_stage"] = "uncaught_exception"
        out["error_traceback"] = traceback.format_exc()
        out["executed"] = False

    out["elapsed_total"] = round(time.time() - t_start, 2)
    out["timings"] = dict(state.timings)
    out["code_attempts"] = state.code_attempts
    out["llm_calls"] = [c for c in captured_logs
                        if c.startswith("[LLM-CALL]") or c.startswith("[ATTEMPT]")]
    out["validators_passed"] = state.code_attempts and any(
        a.get("phase") == "generation" and not a.get("error")
        for a in state.code_attempts
    ) if state.code_attempts else None

    # restore real logger
    state.logger = orig_logger
    return out


def _safe_value(value):
    """Serialize a response value for JSON logging (truncate long frames)."""
    if value is None:
        return None
    try:
        if hasattr(value, "head"):
            return value.head(5).to_dict("records")
    except Exception:
        pass
    s = str(value)
    return s[:2000]


def main():
    from server.core.llm_setup import setup_global_llm
    setup_global_llm()

    run_dir = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_chat_retry"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running PRODUCTION retry path (agent.chat) for {len(QUESTIONS)} questions")
    print(f"Output: {run_dir}\n")

    filter_env = os.environ.get("QUESTIONS", "").strip()
    if filter_env:
        filter_set = {p.strip().lstrip("Q").lower() for p in filter_env.split(",") if p.strip()}
        QUESTIONS_TO_RUN = [q for q in QUESTIONS if str(q["num"]).lower() in filter_set]
        print(f"QUESTIONS filter active: running only {[q['num'] for q in QUESTIONS_TO_RUN]}\n")
    else:
        QUESTIONS_TO_RUN = QUESTIONS

    failures = []
    all_results = []
    pending = []
    for q in QUESTIONS_TO_RUN:
        num = q["num"]
        existing_path = run_dir / f"Q{num}_chat.json"
        if existing_path.exists():
            print(f"Q{num}: {q['test_question'][:50]}... SKIP (already done)", flush=True)
            out = json.loads(existing_path.read_text(encoding="utf-8"))
            all_results.append(out)
            if not out.get("executed"):
                failures.append(out)
        else:
            pending.append(q)

    if pending:
        max_workers = int(os.environ.get("CODEGEN_CONCURRENCY", "4"))
        print(f"Running {len(pending)} questions concurrently (workers={max_workers})...", flush=True)
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_chat_worker, q): q for q in pending}
            for fut in as_completed(futs):
                q = futs[fut]
                num = q["num"]
                try:
                    out = fut.result()
                except Exception as e:
                    out = {
                        "num": num, "test_question": q["test_question"],
                        "error": str(e), "error_traceback": traceback.format_exc(),
                        "failure_stage": "worker_error", "executed": False,
                    }
                all_results.append(out)
                with open(run_dir / f"Q{num}_chat.json", "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
                _write_md(run_dir / f"Q{num}_chat.md", out)

                status = "❌ FAIL" if not out.get("executed") else "✅ OK"
                print(f"    {status}  ({out.get('elapsed_total')}s)  "
                      f"type={out.get('response_type')}  "
                      f"attempts={len(out.get('code_attempts') or [])}  "
                      f"stage={out.get('failure_stage') or '-'}", flush=True)

    # Summary
    ok = sum(1 for o in all_results if o.get("executed"))
    print("\n" + "=" * 70)
    print(f"PRODUCTION CHAT+RETRY RESULTS ({len(all_results)} questions)")
    print("=" * 70)
    print(f"  Success (executed):  {ok}/{len(all_results)}")
    print(f"  Failures:            {len(failures)}")
    print(f"  Output:              {run_dir}")
    print("=" * 70)
    for o in all_results:
        attempts = o.get("code_attempts") or []
        gen_attempts = sum(1 for a in attempts if a.get("phase") == "generation")
        exec_attempts = sum(1 for a in attempts if a.get("phase") == "execution")
        t = o.get("timings") or {}
        print(f"  Q{o.get('num'):>3}  {'✅' if o.get('executed') else '❌'}  "
              f"type={o.get('response_type')}  "
              f"gen×{gen_attempts}/exec×{exec_attempts}  "
              f"tot={o.get('elapsed_total')}s  "
              f"(sel={t.get('column_selection')} cg={t.get('code_generation')} "
              f"exec={t.get('code_execution')})")
    with open(run_dir / "failures.json", "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=2, ensure_ascii=False, default=str)
    if failures:
        print(f"\n  ⚠️ {len(failures)} failed attempts saved to {run_dir / 'failures.json'}")


def _chat_worker(q: dict) -> dict:
    try:
        from server.core.llm_setup import setup_global_llm
        setup_global_llm()
    except Exception:
        pass
    try:
        return run_chat_one(q)
    except Exception as e:
        return {
            "num": q["num"], "test_question": q["test_question"],
            "error": str(e), "error_traceback": traceback.format_exc(),
            "failure_stage": "worker_error", "executed": False,
        }


def _write_md(path: Path, out: dict):
    lines = [f"# Q{out.get('num')}: {out.get('test_question')}\n"]
    lines.append(f"- **response_type**: {out.get('response_type')}")
    lines.append(f"- **executed**: {out.get('executed')}")
    lines.append(f"- **elapsed_total**: {out.get('elapsed_total')}s")
    lines.append(f"- **timings**: {out.get('timings')}")
    attempts = out.get("code_attempts") or []
    lines.append(f"- **attempts ({len(attempts)})**:")
    for a in attempts:
        lines.append(f"  - phase={a.get('phase')} attempt={a.get('attempt')} "
                     f"error={str(a.get('error'))[:120] if a.get('error') else 'None'}")
    if out.get("error"):
        lines.append(f"- **error**: {out.get('error')}")
    if out.get("response_value"):
        lines.append(f"- **response**: {out.get('response_value')}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()