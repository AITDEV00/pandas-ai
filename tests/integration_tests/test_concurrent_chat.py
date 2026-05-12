"""
Concurrency load test for the chat-excel-server.

Validates that concurrent chat requests across different conversation IDs
do NOT block each other.  Sends batches of 5, 10, 15, 20, 25 concurrent
chat requests (each with its own registered agent) and profiles wall-clock,
min, max, avg, p50, p95 latencies per batch.

Usage:
    # Start the server first
    uvicorn server.main:app --host 0.0.0.0 --port 8000

    # Run via poetry
    poetry run python tests/integration_tests/test_concurrent_chat.py

    # Or via pytest
    poetry run pytest tests/integration_tests/test_concurrent_chat.py -v -s
"""
import base64
import csv
import json
import os
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
CSV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "sample_data.csv")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "run", "e2e_reports")

# Concurrency levels: 5, 10, 15, 20, 25
BATCH_SIZES = [5, 10, 15, 20, 25]
CHAT_QUERY = "How many records are there?"
TIMEOUT_SECONDS = 120  # per-request timeout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_csv_as_base64(filepath: str) -> str:
    """Read a CSV file and return a base64-encoded data URI."""
    with open(filepath, "rb") as f:
        raw = f.read()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:text/csv;base64,{encoded}"


def _register_agent(client: httpx.Client) -> str:
    """Call POST /api/register/base64 and return the conversation_id."""
    payload = {
        "base64_data": _load_csv_as_base64(CSV_FILE),
        "mimetype": "text/csv",
    }
    resp = client.post(
        f"{BASE_URL}/api/register/base64", json=payload, timeout=TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    data = resp.json()
    conv_id = data["conversation_id"]
    assert conv_id, f"Registration returned empty conversation_id: {data}"
    return conv_id


def _chat(client: httpx.Client, conversation_id: str, query: str) -> Dict[str, Any]:
    """Call POST /api/chat and return the JSON response."""
    payload = {
        "conversation_id": conversation_id,
        "query": query,
    }
    resp = client.post(
        f"{BASE_URL}/api/chat", json=payload, timeout=TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    return resp.json()


def _time_chat_request(
    client: httpx.Client, conversation_id: str, query: str
) -> Dict[str, Any]:
    """Send a chat request and return timing + result metadata."""
    start = time.perf_counter()
    try:
        result = _chat(client, conversation_id, query)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "conversation_id": conversation_id,
            "elapsed_ms": round(elapsed_ms, 2),
            "status": "ok",
            "response_type": result.get("type"),
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "conversation_id": conversation_id,
            "elapsed_ms": round(elapsed_ms, 2),
            "status": "error",
            "error": str(e),
        }


def _percentile(sorted_data: List[float], pct: float) -> float:
    """Compute a percentile from a sorted list of values."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    d0 = sorted_data[f] * (c - k)
    d1 = sorted_data[c] * (k - f)
    return round(d0 + d1, 2)


def _compute_batch_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute wall, min, max, avg, p50, p95, stddev from batch results."""
    ok_results = [r for r in results if r["status"] == "ok"]
    err_results = [r for r in results if r["status"] == "error"]

    if not ok_results:
        return {
            "total": len(results),
            "succeeded": 0,
            "failed": len(err_results),
            "min_ms": 0,
            "max_ms": 0,
            "avg_ms": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "stddev_ms": 0,
            "errors": [r.get("error", "unknown") for r in err_results],
        }

    elapsed = sorted([r["elapsed_ms"] for r in ok_results])
    return {
        "total": len(results),
        "succeeded": len(ok_results),
        "failed": len(err_results),
        "min_ms": elapsed[0],
        "max_ms": elapsed[-1],
        "avg_ms": round(statistics.mean(elapsed), 2),
        "p50_ms": _percentile(elapsed, 50),
        "p95_ms": _percentile(elapsed, 95),
        "stddev_ms": round(statistics.stdev(elapsed), 2) if len(elapsed) > 1 else 0.0,
        "errors": [r.get("error", "unknown") for r in err_results],
    }


def _print_batch_report(
    batch_size: int,
    stats: Dict[str, Any],
    wall_ms: float,
    results: List[Dict[str, Any]],
):
    """Pretty-print a timing report for one batch."""
    sep = "=" * 72
    thin = "-" * 52
    print(f"\n{sep}")
    print(f"  BATCH: {batch_size} concurrent chat requests")
    print(f"{sep}")
    print(f"  Wall time     : {wall_ms:>10.2f} ms  ({wall_ms / 1000:.2f} s)")
    print(f"  Succeeded     : {stats['succeeded']:>10d}")
    print(f"  Failed        : {stats['failed']:>10d}")
    print(f"  ────────────────────────────────────────")
    print(f"  Min latency   : {stats['min_ms']:>10.2f} ms")
    print(f"  Max latency   : {stats['max_ms']:>10.2f} ms")
    print(f"  Avg latency   : {stats['avg_ms']:>10.2f} ms")
    print(f"  P50 latency   : {stats['p50_ms']:>10.2f} ms")
    print(f"  P95 latency   : {stats['p95_ms']:>10.2f} ms")
    print(f"  Stddev        : {stats['stddev_ms']:>10.2f} ms")
    print(f"  ────────────────────────────────────────")

    # Per-request detail
    print(f"  #    Conv ID      Latency (ms)   Status   Type")
    print(f"  {thin}")
    for i, r in enumerate(results, 1):
        cid_short = r["conversation_id"][:8] + "..."
        rtype = r.get("response_type", "n/a")
        print(
            f"  {i:<4} {cid_short:<12} {r['elapsed_ms']:>14.2f} "
            f"{r['status']:<8} {rtype:<10}"
        )

    if stats["errors"]:
        print(f"\n  WARNING - Errors:")
        for err in stats["errors"][:5]:
            print(f"     - {err[:120]}")

    # Blocking analysis
    if stats["succeeded"] > 1:
        total_serial_ms = sum(
            r["elapsed_ms"] for r in results if r["status"] == "ok"
        )
        parallelism_ratio = total_serial_ms / wall_ms if wall_ms > 0 else 0
        print(f"\n  Concurrency Analysis:")
        print(f"     Sum of individual latencies : {total_serial_ms:.2f} ms")
        print(f"     Wall clock time             : {wall_ms:.2f} ms")
        print(f"     Parallelism ratio           : {parallelism_ratio:.2f}x")
        if parallelism_ratio > 1.5:
            print(f"     PASS - Requests ran CONCURRENTLY (ratio > 1.5x)")
        elif parallelism_ratio > 1.0:
            print(f"     PARTIAL - Some concurrency (1.0x < ratio <= 1.5x)")
        else:
            print(f"     FAIL - Requests appear SERIAL (ratio approx 1.0x)")

    print(f"{sep}\n")


def _save_report(all_reports: List[Dict[str, Any]]):
    """Save the full report as JSON + CSV to the e2e_reports directory."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = os.path.join(REPORTS_DIR, f"{timestamp}_concurrency")
    os.makedirs(report_dir, exist_ok=True)

    report_path = os.path.join(report_dir, "results.json")
    with open(report_path, "w") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "test": "concurrent_chat",
                "base_url": BASE_URL,
                "query": CHAT_QUERY,
                "batches": all_reports,
            },
            f,
            indent=2,
        )
    print(f"Report saved to: {report_path}")

    # Also save a human-readable CSV summary
    csv_path = os.path.join(report_dir, "summary.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "batch_size", "wall_ms", "succeeded", "failed",
            "min_ms", "max_ms", "avg_ms", "p50_ms", "p95_ms", "stddev_ms",
            "parallelism_ratio",
        ])
        for report in all_reports:
            writer.writerow([
                report["batch_size"],
                report["wall_ms"],
                report["stats"]["succeeded"],
                report["stats"]["failed"],
                report["stats"]["min_ms"],
                report["stats"]["max_ms"],
                report["stats"]["avg_ms"],
                report["stats"]["p50_ms"],
                report["stats"]["p95_ms"],
                report["stats"]["stddev_ms"],
                report.get("parallelism_ratio", 0),
            ])
    print(f"CSV summary saved to: {csv_path}")


# ---------------------------------------------------------------------------
# Main test logic
# ---------------------------------------------------------------------------

def run_concurrency_test():
    """Send 5->10->15->20->25 concurrent chat requests and profile timing."""
    # Check server is alive
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(f"{BASE_URL}/health")
            resp.raise_for_status()
            print(f"Server is alive: {resp.json()}")
    except Exception as e:
        print(f"Server not reachable at {BASE_URL}: {e}")
        print(f"   Start with: uvicorn server.main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)

    all_reports: List[Dict[str, Any]] = []

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for batch_size in BATCH_SIZES:
            print(f"\nRegistering {batch_size} agents...")

            # --- Phase 1: Register agents (sequential, fast) ---
            conversation_ids: List[str] = []
            register_start = time.perf_counter()
            for _ in range(batch_size):
                cid = _register_agent(client)
                conversation_ids.append(cid)
            register_ms = (time.perf_counter() - register_start) * 1000
            print(f"   Registered {batch_size} agents in {register_ms:.2f} ms")

            # --- Phase 2: Fire all chat requests concurrently ---
            print(f"Sending {batch_size} concurrent chat requests...")
            wall_start = time.perf_counter()

            results: List[Dict[str, Any]] = [None] * batch_size  # type: ignore
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                # Submit all futures
                future_to_idx = {
                    executor.submit(
                        _time_chat_request, client, cid, CHAT_QUERY
                    ): idx
                    for idx, cid in enumerate(conversation_ids)
                }
                # Collect results as they complete
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    results[idx] = future.result()

            wall_ms = (time.perf_counter() - wall_start) * 1000

            # --- Phase 3: Compute stats and report ---
            stats = _compute_batch_stats(results)
            parallelism_ratio = 0.0
            if stats["succeeded"] > 1 and wall_ms > 0:
                total_serial_ms = sum(
                    r["elapsed_ms"] for r in results if r["status"] == "ok"
                )
                parallelism_ratio = round(total_serial_ms / wall_ms, 2)

            _print_batch_report(batch_size, stats, wall_ms, results)

            all_reports.append({
                "batch_size": batch_size,
                "register_ms": round(register_ms, 2),
                "wall_ms": round(wall_ms, 2),
                "stats": stats,
                "parallelism_ratio": parallelism_ratio,
                "per_request": results,
            })

    # --- Save report ---
    _save_report(all_reports)

    # --- Final summary ---
    hash_sep = "#" * 72
    print(f"\n{hash_sep}")
    print(f"  CONCURRENCY TEST SUMMARY")
    print(f"{hash_sep}")
    print(f"  Batch    Wall (ms)     Avg (ms)     P95 (ms)   Ratio   Status")
    print(f"  {'─' * 66}")
    for report in all_reports:
        ratio = report["parallelism_ratio"]
        if ratio > 1.5:
            status = "CONCURRENT"
        elif ratio > 1.0:
            status = "PARTIAL"
        else:
            status = "SERIAL"
        print(
            f"  {report['batch_size']:<8} "
            f"{report['wall_ms']:>12.2f} "
            f"{report['stats']['avg_ms']:>12.2f} "
            f"{report['stats']['p95_ms']:>12.2f} "
            f"{ratio:>8.2f}x "
            f"{status:<10}"
        )
    print(f"{hash_sep}\n")

    # Assert that at least the smallest batch shows concurrency
    if all_reports:
        smallest = all_reports[0]
        if smallest["parallelism_ratio"] <= 1.0:
            print(
                f"WARNING: Even {smallest['batch_size']} concurrent requests "
                f"show no parallelism (ratio={smallest['parallelism_ratio']:.2f}). "
                f"Requests are being serialized."
            )

    return all_reports


# ---------------------------------------------------------------------------
# Pytest integration
# ---------------------------------------------------------------------------

def _check_server_alive():
    """Verify the server is reachable before running tests."""
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(f"{BASE_URL}/health")
            resp.raise_for_status()
            return True
    except Exception:
        return False


try:
    import pytest

    @pytest.fixture(scope="module")
    def server_alive():
        """Skip all tests if the server is not running."""
        if not _check_server_alive():
            pytest.skip(
                "Server not running. Start with: uvicorn server.main:app --port 8000"
            )

    @pytest.mark.usefixtures("server_alive")
    class TestConcurrentChat:
        """Concurrent chat load test with incremental batch sizes."""

        def test_concurrent_chat_batches(self):
            """Send 5->10->15->20->25 concurrent chat requests and profile timing."""
            reports = run_concurrency_test()
            assert reports, "No reports generated"
            # Verify at least the smallest batch shows some concurrency
            smallest = reports[0]
            assert smallest["parallelism_ratio"] > 1.0, (
                f"Even {smallest['batch_size']} concurrent requests show no parallelism "
                f"(ratio={smallest['parallelism_ratio']:.2f}). "
                f"Requests are being serialized."
            )

except ImportError:
    # pytest not available — standalone mode only
    pass


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_concurrency_test()
