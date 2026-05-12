#!/usr/bin/env python3
"""
In-Process Concurrency Test for Chat-Excel-Server
==================================================

Validates that concurrent chat requests across different conversation IDs
do NOT block each other — by calling the exact same Python functions the
server uses (no HTTP, no Docker).

The test replicates the exact server pipeline:
  1. REGISTER: create_agent_from_file_path() → agent_store.register_agent()
  2. CHAT: agent_store.get_agent() → agent.chat() / agent.follow_up()

Batch sizes: [5, 10, 15, 20, 25]
Each batch:
  - Registers N agents (one per conversation ID)
  - Fires N concurrent chat requests via ThreadPoolExecutor
  - Profiles wall time, per-request latency, parallelism ratio

Usage:
    # From the project root
    .venv/bin/python tests/llm_behavior/test_concurrent_chat_inproc.py

    # Or via poetry
    poetry run python tests/llm_behavior/test_concurrent_chat_inproc.py
"""

import json
import os
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# LLM Configuration (mirrors .env.example)
# ---------------------------------------------------------------------------
LLM_API_KEY = os.environ.get(
    "LLM_API_KEY", "sk-2bx-lSX1M-b4a0iuabPHu1hRA2QkDZ5_ONWGXI64zT8"
)
LLM_BASE_URL = os.environ.get(
    "LLM_BASE_URL",
    "https://inference.adeoaiengine.ecouncil.ae/models/eb9de344-f622-476b-8823-47f8f559e348/proxy/v1",
)
LLM_MODEL = os.environ.get(
    "LLM_MODEL_NAME", "openai//model/Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
)
LLM_VERIFY_SSL = os.environ.get("LLM_VERIFY_SSL", "false").lower() == "true"
LLM_CONTEXT_WINDOW = int(os.environ.get("LLM_CONTEXT_WINDOW", "250000"))

# ---------------------------------------------------------------------------
# Test Configuration
# ---------------------------------------------------------------------------
DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "emirati_employees_data.csv"
)
DATA_FILE = os.path.abspath(DATA_FILE)

BATCH_SIZES = [5, 10, 15, 20, 25]
CHAT_QUERY = "How many records are there?"
REPORTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "run", "e2e_reports"
)
REPORTS_DIR = os.path.abspath(REPORTS_DIR)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert data assistant. Use execute_sql_query for data retrieval "
    "and aggregation. For presenting results, write Python code: compute derived "
    "values, format strings, build conditional logic, and choose the best result "
    "type (string for answers, number for counts, dataframe for tables, plot for "
    "charts). Do not make assumptions about data formats without checking the "
    "vocabulary lists."
)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------
@dataclass
class CodeGenTrace:
    """Code generation / execution trace extracted from agent logger."""
    code_gen_attempts: int = 0        # How many times LLM was called to generate code
    code_exec_attempts: int = 0       # How many times code was executed
    code_gen_retried: bool = False    # Did code generation need retrying?
    code_exec_retried: bool = False   # Did code execution need retrying?
    final_code: Optional[str] = None  # The last_code_generated (cleaned)
    executed_code: Optional[str] = None  # The code that actually ran
    log_messages: List[str] = field(default_factory=list)  # All log msgs for this request
    column_selection_skipped: bool = False
    column_selection_triggered: bool = False
    selected_columns: Optional[List[str]] = None


@dataclass
class RequestResult:
    """Outcome of a single chat request."""
    conversation_id: str
    batch_index: int
    success: bool
    latency_ms: float
    response_type: Optional[str] = None
    response_preview: Optional[str] = None
    error: Optional[str] = None
    thread_name: Optional[str] = None
    start_offset_ms: float = 0.0  # ms after batch wall-clock start
    code_trace: Optional[CodeGenTrace] = None  # Code gen / execution trace


@dataclass
class BatchStats:
    """Aggregated statistics for a batch of concurrent requests."""
    batch_size: int
    wall_ms: float
    latencies_ms: List[float] = field(default_factory=list)
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    stddev_ms: float = 0.0
    success_count: int = 0
    fail_count: int = 0
    parallelism_ratio: float = 0.0
    results: List[RequestResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Registration — exact server pipeline
# ---------------------------------------------------------------------------
def register_agent(csv_path: str = DATA_FILE) -> str:
    """
    Replicates the /api/register/file endpoint exactly.
    Returns the conversation_id.
    """
    import pandasai as pai
    from server.core.llm_setup import create_litellm
    from server.features.register.handler import create_agent_from_file_path
    from server.features.register.models import (
        PandasAIConfigPayload,
        LLMConfigPayload,
        SemanticModelPayload,
    )

    semantic_model = SemanticModelPayload(
        name="emirati_employees",
        description="Employee directory with names and IDs.",
        columns=[
            {
                "name": "English Name",
                "type": "string",
                "description": "Employee name in English.",
            },
            {
                "name": "Arabic Name",
                "type": "string",
                "description": "Employee name in Arabic.",
            },
            {
                "name": "Employee Number",
                "type": "string",
                "description": "Unique employee identifier.",
            },
        ],
    )

    config_payload = PandasAIConfigPayload(
        enrich_column_values=True,
        auto_fill_descriptions=False,  # skip LLM call for speed
    )

    llm_payload = LLMConfigPayload(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model_name=LLM_MODEL,
        llm_context_window=LLM_CONTEXT_WINDOW,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
    )

    result = create_agent_from_file_path(
        csv_path,
        "text/csv",
        semantic_model=semantic_model,
        pandasai_config=config_payload,
        llm_config=llm_payload,
    )

    return result.conversation_id


# ---------------------------------------------------------------------------
# Code-generation trace extraction from agent logger
# ---------------------------------------------------------------------------
def extract_code_trace(agent) -> CodeGenTrace:
    """
    Parse the agent's logger to extract code generation / execution details.
    Counts retries, captures the final code, and identifies key steps.
    """
    trace = CodeGenTrace()

    # Capture the generated and executed code from agent state
    trace.final_code = getattr(agent._state, "last_code_generated", None)
    trace.executed_code = getattr(agent._state, "last_code_executed", None)
    trace.selected_columns = getattr(agent._state, "last_selected_names", None)

    # Walk the logger entries
    logs = agent._state.logger.logs if agent._state.logger else []
    for log_entry in logs:
        msg = log_entry.msg if hasattr(log_entry, "msg") else str(log_entry)
        trace.log_messages.append(msg)

        # Detect code generation retries
        if "Retrying Code Generation" in msg:
            trace.code_gen_retried = True
            trace.code_gen_attempts += 1

        # Detect execution retries
        if "Retrying execution" in msg:
            trace.code_exec_retried = True
            trace.code_exec_attempts += 1

        # Detect column selection
        if "[Column Selection] Skipped" in msg:
            trace.column_selection_skipped = True
        if "[Column Selection] Triggered" in msg:
            trace.column_selection_triggered = True

    # Initial attempt counts as 1; retries add more
    if trace.log_messages:
        # If there was any code gen activity, at least 1 attempt happened
        has_code_gen = any(
            "Code Generated" in m or "Generating new code" in m
            or "execute_sql_query" in m
            for m in trace.log_messages
        )
        if has_code_gen:
            trace.code_gen_attempts = max(trace.code_gen_attempts, 1)

        has_code_exec = any(
            "Executing code" in m or "Response generated successfully" in m
            for m in trace.log_messages
        )
        if has_code_exec:
            trace.code_exec_attempts = max(trace.code_exec_attempts, 1)

    return trace


# ---------------------------------------------------------------------------
# Chat — exact server pipeline (same as handle_chat_query)
# ---------------------------------------------------------------------------
def chat_query(
    conversation_id: str,
    query: str,
    output_type: Optional[str] = None,
) -> RequestResult:
    """
    Replicates the /api/chat endpoint exactly.
    Returns a RequestResult with timing and outcome.
    """
    import threading
    from server.core.agent_store import agent_store

    thread_name = threading.current_thread().name
    start = time.perf_counter()

    try:
        agent = agent_store.get_agent(conversation_id)
        if not agent:
            return RequestResult(
                conversation_id=conversation_id,
                batch_index=-1,
                success=False,
                latency_ms=0,
                error="Conversation ID not found or expired.",
                thread_name=thread_name,
            )

        # Determine chat vs follow_up (same logic as handler)
        is_follow_up = agent._state.memory.count() > 0

        if is_follow_up:
            response = agent.follow_up(query, output_type=output_type)
        else:
            response = agent.chat(query, output_type=output_type)

        actual_type = getattr(response, "type", None) or output_type or "auto"
        if actual_type == "chart":
            actual_type = "plot"

        # Extract code generation trace from agent logger
        code_trace = extract_code_trace(agent)

        latency_ms = (time.perf_counter() - start) * 1000

        return RequestResult(
            conversation_id=conversation_id,
            batch_index=-1,
            success=True,
            latency_ms=latency_ms,
            response_type=actual_type,
            response_preview=str(response)[:120] if response else None,
            thread_name=thread_name,
            code_trace=code_trace,
        )

    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            conversation_id=conversation_id,
            batch_index=-1,
            success=False,
            latency_ms=latency_ms,
            error=f"{type(e).__name__}: {str(e)[:200]}",
            thread_name=thread_name,
        )


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------
def run_batch(batch_size: int) -> BatchStats:
    """Register batch_size agents, then fire all chat requests concurrently."""

    print(f"\n{'═' * 70}")
    print(f"  BATCH  n={batch_size}")
    print(f"{'═' * 70}")

    # ── Phase 1: Register agents ──────────────────────────────────────────
    print(f"  Registering {batch_size} agents...")
    reg_start = time.perf_counter()
    conv_ids: List[str] = []
    for i in range(batch_size):
        try:
            cid = register_agent()
            conv_ids.append(cid)
            print(f"    [{i + 1:>2}/{batch_size}] ✅ {cid[:8]}...")
        except Exception as e:
            print(f"    [{i + 1:>2}/{batch_size}] ❌ REGISTER FAILED: {e}")
    reg_ms = (time.perf_counter() - reg_start) * 1000
    print(f"  Registration took {reg_ms:.0f} ms ({len(conv_ids)}/{batch_size} succeeded)")

    if not conv_ids:
        print("  ⚠️  No agents registered — skipping chat phase")
        return BatchStats(batch_size=batch_size, wall_ms=0, fail_count=batch_size)

    # ── Phase 2: Concurrent chat ──────────────────────────────────────────
    print(f"\n  Firing {len(conv_ids)} concurrent chat requests...")
    wall_start = time.perf_counter()
    results: List[RequestResult] = []

    with ThreadPoolExecutor(max_workers=batch_size) as pool:
        # Submit all at once
        future_to_idx = {}
        for i, cid in enumerate(conv_ids):
            fut = pool.submit(chat_query, cid, CHAT_QUERY, "string")
            future_to_idx[fut] = i

        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                r = fut.result()
                r.batch_index = idx
                r.start_offset_ms = 0  # filled below
                results.append(r)
            except Exception as e:
                results.append(
                    RequestResult(
                        conversation_id="unknown",
                        batch_index=idx,
                        success=False,
                        latency_ms=0,
                        error=f"Future exception: {type(e).__name__}: {e}",
                    )
                )

    wall_ms = (time.perf_counter() - wall_start) * 1000

    # ── Compute stats ─────────────────────────────────────────────────────
    stats = BatchStats(
        batch_size=batch_size,
        wall_ms=wall_ms,
        results=results,
    )

    latencies = [r.latency_ms for r in results if r.success]
    stats.success_count = sum(1 for r in results if r.success)
    stats.fail_count = sum(1 for r in results if not r.success)

    if latencies:
        stats.latencies_ms = sorted(latencies)
        stats.min_ms = min(latencies)
        stats.max_ms = max(latencies)
        stats.avg_ms = statistics.mean(latencies)
        stats.p50_ms = statistics.median(latencies)
        if len(latencies) >= 2:
            stats.p95_ms = latencies[int(len(latencies) * 0.95)]
            stats.stddev_ms = statistics.stdev(latencies)
        else:
            stats.p95_ms = latencies[0]
            stats.stddev_ms = 0.0

    # Parallelism ratio: if requests ran truly in parallel,
    # wall time ≈ max latency.  If serial, wall ≈ sum.
    # ratio = sum_latency / wall_time  (>1 means concurrent execution)
    sum_latency = sum(r.latency_ms for r in results)
    stats.parallelism_ratio = sum_latency / wall_ms if wall_ms > 0 else 0.0

    return stats


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_batch_report(stats: BatchStats) -> None:
    """Print a detailed timing report for one batch."""
    print(f"\n  ┌{'─' * 48}┐")
    print(f"  │ {'TIMING REPORT':^46} │")
    print(f"  ├{'─' * 48}┤")
    print(f"  │ {'Batch size':<28} {stats.batch_size:>16} │")
    print(f"  │ {'Success / Fail':<28} {stats.success_count:>7}/{stats.fail_count:<8} │")
    print(f"  │ {'Wall time (ms)':<28} {stats.wall_ms:>16.1f} │")
    print(f"  │ {'Min latency (ms)':<28} {stats.min_ms:>16.1f} │")
    print(f"  │ {'Max latency (ms)':<28} {stats.max_ms:>16.1f} │")
    print(f"  │ {'Avg latency (ms)':<28} {stats.avg_ms:>16.1f} │")
    print(f"  │ {'P50 latency (ms)':<28} {stats.p50_ms:>16.1f} │")
    print(f"  │ {'P95 latency (ms)':<28} {stats.p95_ms:>16.1f} │")
    print(f"  │ {'Stddev latency (ms)':<28} {stats.stddev_ms:>16.1f} │")
    print(f"  │ {'Parallelism ratio':<28} {stats.parallelism_ratio:>16.2f}x │")
    print(f"  └{'─' * 48}┘")

    if stats.parallelism_ratio > 1.0:
        print(f"  ✅ Parallelism > 1.0x → requests ran concurrently")
    else:
        print(f"  ⚠️  Parallelism ≤ 1.0x → requests may have been serialized")

    # Per-request detail
    print(f"\n  {'#':>3}  {'Conv ID':>10}  {'Latency':>10}  {'Type':>8}  {'Retries':>9}  {'Thread':>18}  {'Result'}")
    print(f"  {'─' * 90}")
    for r in sorted(stats.results, key=lambda x: x.batch_index):
        cid_short = r.conversation_id[:8] if r.conversation_id != "unknown" else "????????"
        status = "✅" if r.success else "❌"
        rtype = r.response_type or "-"
        thread = r.thread_name or "-"
        preview = r.response_preview[:30] if r.response_preview else (r.error or "")[:30]
        # Retry info
        if r.code_trace:
            gen_a = r.code_trace.code_gen_attempts
            exec_a = r.code_trace.code_exec_attempts
            gen_r = "🔄" if r.code_trace.code_gen_retried else "  "
            exec_r = "🔄" if r.code_trace.code_exec_retried else "  "
            retry_str = f"G{gen_a}{gen_r} E{exec_a}{exec_r}"
        else:
            retry_str = "-"
        print(
            f"  {r.batch_index:>3}  {cid_short:>10}  {r.latency_ms:>9.1f}  {rtype:>8}  {retry_str:>9}  {thread:>18}  {status} {preview}"
        )

    # ── Code Trace Analysis ───────────────────────────────────────────────
    traced = [r for r in stats.results if r.success and r.code_trace]
    if traced:
        print(f"\n  ── Code Generation Trace Analysis ──")
        gen_retried = [r for r in traced if r.code_trace.code_gen_retried]
        exec_retried = [r for r in traced if r.code_trace.code_exec_retried]
        any_retried = [r for r in traced if r.code_trace.code_gen_retried or r.code_trace.code_exec_retried]

        print(f"  Code gen retries:   {len(gen_retried)}/{len(traced)} requests")
        print(f"  Code exec retries:  {len(exec_retried)}/{len(traced)} requests")
        print(f"  Any retry:          {len(any_retried)}/{len(traced)} requests")

        # Latency comparison: retried vs not-retried
        retried_latencies = [r.latency_ms for r in any_retried]
        no_retry_latencies = [r.latency_ms for r in traced if r not in any_retried]

        if retried_latencies and no_retry_latencies:
            avg_retry = statistics.mean(retried_latencies)
            avg_no_retry = statistics.mean(no_retry_latencies)
            print(f"  Avg latency WITH retry:    {avg_retry:.1f} ms ({len(retried_latencies)} requests)")
            print(f"  Avg latency WITHOUT retry: {avg_no_retry:.1f} ms ({len(no_retry_latencies)} requests)")
            print(f"  Retry overhead:            {avg_retry - avg_no_retry:+.1f} ms")
        elif retried_latencies:
            print(f"  ⚠️  ALL requests had retries! Avg: {statistics.mean(retried_latencies):.1f} ms")

        # Show the generated code for each request
        print(f"\n  ── Generated Code Per Request ──")
        for r in sorted(traced, key=lambda x: x.batch_index):
            ct = r.code_trace
            code = ct.final_code or ct.executed_code or "(no code captured)"
            # Show compact version
            code_lines = code.strip().split("\n")
            code_summary = " | ".join(l.strip() for l in code_lines if l.strip() and not l.strip().startswith("#"))
            if len(code_summary) > 80:
                code_summary = code_summary[:77] + "..."
            retry_flag = "🔄" if (ct.code_gen_retried or ct.code_exec_retried) else "  "
            print(f"  {r.batch_index:>3} {retry_flag} {code_summary}")

        # Show the FULL code for retried requests (these are the interesting ones)
        retried_with_code = [r for r in any_retried if r.code_trace and (r.code_trace.final_code or r.code_trace.executed_code)]
        if retried_with_code:
            print(f"\n  ── Full Code for Retried Requests ──")
            for r in retried_with_code:
                ct = r.code_trace
                print(f"  --- Request #{r.batch_index} (latency={r.latency_ms:.1f}ms) ---")
                code = ct.executed_code or ct.final_code or "(no code)"
                for line in code.strip().split("\n"):
                    print(f"    {line}")
                if ct.code_gen_retried:
                    print(f"    ⚠️  Code generation was retried ({ct.code_gen_attempts} attempts)")
                if ct.code_exec_retried:
                    print(f"    ⚠️  Code execution was retried ({ct.code_exec_attempts} attempts)")


def print_summary_table(all_stats: List[BatchStats]) -> None:
    """Print a cross-batch comparison table."""
    print(f"\n{'═' * 110}")
    print(f"  CONCURRENCY SUMMARY — ALL BATCHES")
    print(f"{'═' * 110}")
    print(
        f"  {'Batch':>5}  {'Success':>8}  {'Wall(ms)':>10}  {'Min':>8}  {'Max':>8}  "
        f"{'Avg':>8}  {'P50':>8}  {'P95':>8}  {'StdDev':>8}  {'Parallel':>9}  {'Retries':>8}"
    )
    print(f"  {'─' * 105}")
    for s in all_stats:
        # Count retries in this batch
        retried = sum(
            1 for r in s.results
            if r.success and r.code_trace and (r.code_trace.code_gen_retried or r.code_trace.code_exec_retried)
        )
        total_success = s.success_count
        retry_str = f"{retried}/{total_success}" if total_success > 0 else "-"
        print(
            f"  {s.batch_size:>5}  {s.success_count:>5}/{s.fail_count:<2}  "
            f"{s.wall_ms:>10.1f}  {s.min_ms:>8.1f}  {s.max_ms:>8.1f}  "
            f"{s.avg_ms:>8.1f}  {s.p50_ms:>8.1f}  {s.p95_ms:>8.1f}  "
            f"{s.stddev_ms:>8.1f}  {s.parallelism_ratio:>8.2f}x  {retry_str:>8}"
        )

    # Verdict
    all_parallel = all(s.parallelism_ratio > 1.0 for s in all_stats if s.success_count > 0)
    if all_parallel:
        print(f"\n  ✅ VERDICT: All batches show parallelism > 1.0x → concurrent execution confirmed")
    else:
        non_parallel = [s for s in all_stats if s.success_count > 0 and s.parallelism_ratio <= 1.0]
        if non_parallel:
            print(f"\n  ⚠️  VERDICT: Some batches show parallelism ≤ 1.0x → possible serialization")
            for s in non_parallel:
                print(f"    - Batch {s.batch_size}: ratio={s.parallelism_ratio:.2f}x")
        else:
            print(f"\n  ⚠️  VERDICT: No successful batches to assess parallelism")


def save_report(all_stats: List[BatchStats]) -> str:
    """Save the full report to JSON."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(REPORTS_DIR, f"{ts}_concurrent_inproc", "results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    report = {
        "timestamp": ts,
        "query": CHAT_QUERY,
        "data_file": DATA_FILE,
        "batch_sizes": BATCH_SIZES,
        "batches": [],
    }

    for s in all_stats:
        batch = {
            "batch_size": s.batch_size,
            "wall_ms": round(s.wall_ms, 1),
            "min_ms": round(s.min_ms, 1),
            "max_ms": round(s.max_ms, 1),
            "avg_ms": round(s.avg_ms, 1),
            "p50_ms": round(s.p50_ms, 1),
            "p95_ms": round(s.p95_ms, 1),
            "stddev_ms": round(s.stddev_ms, 1),
            "success_count": s.success_count,
            "fail_count": s.fail_count,
            "parallelism_ratio": round(s.parallelism_ratio, 3),
            "per_request": [
                {
                    "index": r.batch_index,
                    "conversation_id": r.conversation_id,
                    "success": r.success,
                    "latency_ms": round(r.latency_ms, 1),
                    "response_type": r.response_type,
                    "response_preview": r.response_preview,
                    "error": r.error,
                    "thread_name": r.thread_name,
                    "code_gen_attempts": r.code_trace.code_gen_attempts if r.code_trace else None,
                    "code_exec_attempts": r.code_trace.code_exec_attempts if r.code_trace else None,
                    "code_gen_retried": r.code_trace.code_gen_retried if r.code_trace else None,
                    "code_exec_retried": r.code_trace.code_exec_retried if r.code_trace else None,
                    "final_code": r.code_trace.final_code if r.code_trace else None,
                    "executed_code": r.code_trace.executed_code if r.code_trace else None,
                    "selected_columns": r.code_trace.selected_columns if r.code_trace else None,
                    "log_messages": r.code_trace.log_messages if r.code_trace else None,
                }
                for r in sorted(s.results, key=lambda x: x.batch_index)
            ],
        }
        report["batches"].append(batch)

    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    return out_path


# ---------------------------------------------------------------------------
# Race-condition detector: same conv ID, concurrent requests
# ---------------------------------------------------------------------------
def test_same_conv_id_race() -> None:
    """
    Fire 5 concurrent chat requests against the SAME conversation ID.
    This is the race-condition scenario: agent._state.config is mutated
    per-request without per-agent locking.
    """
    print(f"\n{'═' * 70}")
    print(f"  RACE CONDITION TEST — Same Conversation ID, 5 Concurrent Requests")
    print(f"{'═' * 70}")

    # Register one agent
    print("  Registering single agent...")
    try:
        cid = register_agent()
        print(f"  ✅ {cid[:8]}...")
    except Exception as e:
        print(f"  ❌ Registration failed: {e}")
        return

    # Fire 5 concurrent chats on the SAME conv ID
    print(f"  Firing 5 concurrent requests on same conv ID...")
    wall_start = time.perf_counter()
    results: List[RequestResult] = []

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(chat_query, cid, CHAT_QUERY, "string") for _ in range(5)]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append(
                    RequestResult(
                        conversation_id=cid,
                        batch_index=-1,
                        success=False,
                        latency_ms=0,
                        error=f"Future exception: {e}",
                    )
                )

    wall_ms = (time.perf_counter() - wall_start) * 1000
    successes = sum(1 for r in results if r.success)
    failures = sum(1 for r in results if not r.success)

    print(f"\n  Wall time: {wall_ms:.1f} ms")
    print(f"  Success: {successes}  Fail: {failures}")

    for i, r in enumerate(results):
        status = "✅" if r.success else "❌"
        err = r.error[:80] if r.error else ""
        retry_info = ""
        if r.code_trace:
            flags = []
            if r.code_trace.code_gen_retried:
                flags.append(f"gen_retry×{r.code_trace.code_gen_attempts}")
            if r.code_trace.code_exec_retried:
                flags.append(f"exec_retry×{r.code_trace.code_exec_attempts}")
            if flags:
                retry_info = f"  [{', '.join(flags)}]"
        print(f"    [{i}] {status} {r.latency_ms:.1f}ms  type={r.response_type}{retry_info}  {err}")

    if failures > 0:
        print(f"\n  ⚠️  {failures}/5 requests failed — likely race condition on agent._state.config")
    else:
        print(f"\n  ✅ All 5 succeeded (but config overrides may have interleaved incorrectly)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("  IN-PROCESS CONCURRENCY TEST")
    print("  (No HTTP server — direct Python function calls)")
    print("=" * 70)
    print(f"  Data file : {DATA_FILE}")
    print(f"  LLM       : {LLM_MODEL}")
    print(f"  Base URL  : {LLM_BASE_URL}")
    print(f"  Query     : {CHAT_QUERY}")
    print(f"  Batches   : {BATCH_SIZES}")

    # Verify data file exists
    if not os.path.exists(DATA_FILE):
        print(f"\n  ❌ Data file not found: {DATA_FILE}")
        sys.exit(1)

    # Setup global LLM (required by some code paths)
    from server.core.llm_setup import setup_global_llm
    setup_global_llm()

    all_stats: List[BatchStats] = []

    # ── Run each batch ────────────────────────────────────────────────────
    for n in BATCH_SIZES:
        stats = run_batch(n)
        print_batch_report(stats)
        all_stats.append(stats)

    # ── Race condition test ───────────────────────────────────────────────
    test_same_conv_id_race()

    # ── Summary ───────────────────────────────────────────────────────────
    print_summary_table(all_stats)

    # ── Save report ───────────────────────────────────────────────────────
    out_path = save_report(all_stats)
    print(f"\n  📁 Report saved to: {out_path}")


if __name__ == "__main__":
    main()
