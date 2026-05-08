"""
E2E Pipeline Runner — Query Bank Execution & Report Generation
================================================================

Runs the full query bank through the exact server pipeline and generates
detailed reports in the `run/` folder.

Usage:
    # Run everything (single-turn + multi-turn)
    python tests/llm_behavior/run_e2e_bank.py

    # Run only single-turn queries
    python tests/llm_behavior/run_e2e_bank.py --mode single

    # Run only multi-turn conversations
    python tests/llm_behavior/run_e2e_bank.py --mode multi

    # Run a specific query by ID
    python tests/llm_behavior/run_e2e_bank.py --only SS-001

    # Run a specific conversation by ID
    python tests/llm_behavior/run_e2e_bank.py --only MT-001

    # Custom file path
    python tests/llm_behavior/run_e2e_bank.py --file /path/to/data.xlsx

    # Skip registration (reuse existing conversation)
    python tests/llm_behavior/run_e2e_bank.py --conv-id UUID

Output:
    run/e2e_reports/<timestamp>/
        ├── summary.json           — Overall test summary
        ├── single_turn_results.json  — Detailed single-turn results
        ├── multi_turn_results.json   — Detailed multi-turn results
        ├── report.md              — Human-readable findings report
        └── scratch/               — Intermediate scratch files
            ├── registration_state.json
            ├── per_query/          — Per-query detailed JSON
            └── progress.json       — Resumable progress tracker
"""

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Import query bank ──────────────────────────────────────────────────────
from tests.llm_behavior.query_bank import (
    SINGLE_TURN_SIMPLE,
    SINGLE_TURN_COMPLEX,
    EDGE_CASE_QUERIES,
    MULTI_TURN_CONVERSATIONS,
    get_all_single_turn_queries,
    get_query_by_id,
)

# ── Import adversarial query bank ─────────────────────────────────────────
from tests.llm_behavior.query_bank_adversarial import (
    COLUMN_OMISSION,
    CROSS_STRUCT_DEEP,
    AMBIGUOUS_REF,
    IMPLICIT_DEP,
    MULTI_STRUCT_UNNEST,
    NEGATION_EDGE,
    COMPOUND_AGGREGATION,
    TEMPORAL_CROSS,
    EXTREME_SINGLE,
    ADVERSARIAL_MULTI_TURN,
    get_all_adversarial_single_turn_queries,
    get_all_adversarial_multi_turn_conversations,
    get_adversarial_query_by_id,
    get_adversarial_stats,
)

# ── Import adversarial v2 query bank ────────────────────────────────────
from tests.llm_behavior.query_bank_adversarial_v2 import (
    COLUMN_SELECTION_HANDOFF,
    SEMANTIC_MAPPING_GAP,
    STRUCT_INNER_FIELD_BLINDNESS,
    COLUMN_NAME_COLLISION,
    BUDGET_RATIO_EDGE,
    RETRIAL_TRAP_CONVERSATIONS,
    get_all_adversarial_v2_single_turn_queries,
    get_all_adversarial_v2_multi_turn_conversations,
    get_adversarial_v2_query_by_id,
    get_adversarial_v2_stats,
)

# ── Import adversarial v3 query bank ────────────────────────────────────
from tests.llm_behavior.query_bank_adversarial_v3 import (
    HANDOFF_SABOTAGE,
    TRIPLE_NAME_COLLISION,
    ALLOWANCE_MATRIX,
    MULTI_STRUCT_JOIN,
    NEGATION_TRAP,
    CONVERSATION_POISON,
    get_all_adversarial_v3_single_turn_queries,
    get_all_adversarial_v3_multi_turn_conversations,
    get_adversarial_v3_query_by_id,
    get_adversarial_v3_stats,
)

# ── Import adversarial v4 query bank ────────────────────────────────────
from tests.llm_behavior.query_bank_adversarial_v4 import (
    BRACKET_NAMING_INCONSISTENCY,
    EMPLOYEE_ID_LEADING_ZERO,
    STRUCT_FIELD_PROMPT_CONFUSION,
    COLUMN_HINT_PHRASING,
    MULTI_STRUCT_FIELD_SELECTION,
    NAMING_CONVENTION_STRESS,
    get_all_adversarial_v4_single_turn_queries,
    get_all_adversarial_v4_multi_turn_conversations,
    get_adversarial_v4_query_by_id,
    get_adversarial_v4_stats,
)

# ── Import the E2E pipeline test (registration + chat + monitoring) ───────
from tests.llm_behavior.test_e2e_pipeline import (
    DEFAULT_XLSX,
    SEMANTIC_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    StepResult,
    QueryTestResult,
    _install_hooks,
    _uninstall_hooks,
    _step_collector,
    register_file,
    run_chat_query,
    save_detailed_results,
)


# ── Configuration ───────────────────────────────────────────────────────────

DEFAULT_XLSX_PATH = "/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx"
REPORT_BASE_DIR = "/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports"


def create_report_dir() -> str:
    """Create a timestamped report directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = os.path.join(REPORT_BASE_DIR, ts)
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(os.path.join(report_dir, "scratch", "per_query"), exist_ok=True)
    return report_dir


def save_scratch(report_dir: str, filename: str, data: Any):
    """Save data to a scratch file."""
    path = os.path.join(report_dir, "scratch", filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def load_progress(report_dir: str) -> dict:
    """Load resumable progress tracker."""
    path = os.path.join(report_dir, "scratch", "progress.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"completed_single": [], "completed_multi": [], "registration_done": False}


def save_progress(report_dir: str, progress: dict):
    """Save progress tracker."""
    save_scratch(report_dir, "progress.json", progress)


def format_response_type(r: QueryTestResult) -> str:
    """Categorize the LLM's response format."""
    raw = r.llm_raw_response
    if not raw:
        return "no_response"
    has_fences = "```" in raw
    has_marker = bool(
        re.search(r"---\s*\n\s*Code\s*:", raw)
        or re.search(r"\n\s*Code\s*:\s*\n", raw)
    )
    if has_fences and has_marker:
        return "both"
    elif has_fences:
        return "fence"
    elif has_marker:
        return "marker"
    else:
        return "no_code_delimiter"


def count_llm_calls(r: QueryTestResult) -> int:
    """Count how many LLM calls were made for this query (includes retries)."""
    return sum(1 for s in r.steps if s.step_name == "llm_response")


def get_history_depth(r: QueryTestResult) -> int:
    """Get the number of history messages sent to the LLM."""
    for step in r.steps:
        if step.step_name == "llm_call":
            return step.details.get("history_messages", 0)
    return 0


def get_assistant_msg_format(r: QueryTestResult) -> Optional[str]:
    """Check if assistant messages in history use ---\nCode: or code fences."""
    for step in r.steps:
        if step.step_name == "llm_messages_full":
            msgs = step.raw_output or []
            for m in msgs:
                if m.get("role") == "assistant":
                    content = m.get("content", "")
                    if "---" in content and "Code:" in content:
                        return "marker"
                    if "```" in content:
                        return "fence"
                    return "plain"
    return None


# ── Single-turn runner ──────────────────────────────────────────────────────

def run_single_turn_bank(
    agent,
    queries: List[dict],
    report_dir: str,
    progress: dict,
    output_type: str = "string",
    column_selection_enabled: bool = False,
    column_selection_threshold: int = 30,
    column_values_budget_ratio: float = 0.10,
) -> List[dict]:
    """Run all single-turn queries and collect results."""
    results = []

    for q in queries:
        qid = q["id"]
        if qid in progress["completed_single"]:
            # Load previously saved result
            per_query_path = os.path.join(report_dir, "scratch", "per_query", f"{qid}.json")
            if os.path.exists(per_query_path):
                with open(per_query_path) as f:
                    results.append(json.load(f))
                print(f"  ⏭️  Skipping {qid} (already completed)")
                continue

        print(f"\n  ▶ Running {qid}: {q['query'][:60]}...")

        result = run_chat_query(
            agent=agent,
            query=q["query"],
            output_type=output_type,
            column_selection_enabled=column_selection_enabled,
            column_selection_threshold=column_selection_threshold,
            column_values_budget_ratio=column_values_budget_ratio,
        )

        # Enrich result with query metadata
        result_data = {
            "query_id": qid,
            "query": q["query"],
            "category": q.get("category"),
            "difficulty": q.get("difficulty"),
            "expected_output_type": q.get("expected_output_type"),
            "notes": q.get("notes"),
            "success": result.success,
            "final_type": result.final_type,
            "final_response": result.final_response,
            "error": result.error,
            "response_format": format_response_type(result),
            "llm_call_count": count_llm_calls(result),
            "history_depth": get_history_depth(result),
            "assistant_msg_format": get_assistant_msg_format(result),
            "steps_summary": [
                {
                    "step": s.step_name,
                    "has_error": s.error is not None,
                    "details_keys": list(s.details.keys()) if s.details else [],
                }
                for s in result.steps
            ],
        }

        # Save per-query detail
        per_query_path = os.path.join(report_dir, "scratch", "per_query", f"{qid}.json")
        detailed = {
            **result_data,
            "steps": [
                {
                    "step_name": s.step_name,
                    "timestamp": s.timestamp,
                    "details": s.details,
                    "error": s.error,
                    "raw_output": s.raw_output if s.step_name in ("llm_response", "code_extracted", "prompt_rendered", "llm_messages_full") else None,
                }
                for s in result.steps
            ],
        }
        with open(per_query_path, "w") as f:
            json.dump(detailed, f, indent=2, ensure_ascii=False, default=str)

        results.append(result_data)
        progress["completed_single"].append(qid)
        save_progress(report_dir, progress)

        # Brief pause between queries
        time.sleep(1)

    return results


# ── Multi-turn runner ───────────────────────────────────────────────────────

def run_multi_turn_bank(
    register_fn,
    file_path: str,
    conversations: List[dict],
    report_dir: str,
    progress: dict,
    output_type: str = "string",
    column_selection_enabled: bool = False,
    column_selection_threshold: int = 30,
    column_values_budget_ratio: float = 0.10,
) -> List[dict]:
    """Run all multi-turn conversations. Each conversation gets a fresh agent."""
    results = []

    for conv in conversations:
        cid = conv["id"]
        if cid in progress["completed_multi"]:
            per_query_path = os.path.join(report_dir, "scratch", "per_query", f"{cid}.json")
            if os.path.exists(per_query_path):
                with open(per_query_path) as f:
                    results.append(json.load(f))
                print(f"  ⏭️  Skipping {cid} (already completed)")
                continue

        print(f"\n  {'─'*60}")
        print(f"  🔄 Conversation {cid}: {conv['name']}")
        print(f"  {'─'*60}")

        # Register a fresh agent for each conversation
        conversation_id, agent = register_fn(
            file_path=file_path,
            semantic_model=SEMANTIC_MODEL,
            enrich_column_values=True,
            auto_fill_descriptions=False,
        )

        conv_result = {
            "conversation_id": cid,
            "name": conv["name"],
            "turns": [],
        }

        for turn_idx, turn in enumerate(conv["turns"]):
            print(f"\n    Turn {turn_idx + 1}/{len(conv['turns'])}: {turn['query'][:60]}...")

            result = run_chat_query(
                agent=agent,
                query=turn["query"],
                output_type=turn.get("expected_output_type", output_type),
                column_selection_enabled=column_selection_enabled,
                column_selection_threshold=column_selection_threshold,
                column_values_budget_ratio=column_values_budget_ratio,
            )

            turn_data = {
                "turn_index": turn_idx,
                "query": turn["query"],
                "notes": turn.get("notes"),
                "expected_output_type": turn.get("expected_output_type"),
                "success": result.success,
                "final_type": result.final_type,
                "final_response": result.final_response,
                "error": result.error,
                "response_format": format_response_type(result),
                "llm_call_count": count_llm_calls(result),
                "history_depth": get_history_depth(result),
                "assistant_msg_format": get_assistant_msg_format(result),
            }

            conv_result["turns"].append(turn_data)

            # Brief pause between turns
            time.sleep(1)

        # Summary for this conversation
        conv_result["total_turns"] = len(conv["turns"])
        conv_result["successful_turns"] = sum(1 for t in conv_result["turns"] if t["success"])
        conv_result["formats_used"] = list(set(t["response_format"] for t in conv_result["turns"]))

        # Save per-conversation detail
        per_query_path = os.path.join(report_dir, "scratch", "per_query", f"{cid}.json")
        with open(per_query_path, "w") as f:
            json.dump(conv_result, f, indent=2, ensure_ascii=False, default=str)

        results.append(conv_result)
        progress["completed_multi"].append(cid)
        save_progress(report_dir, progress)

    return results


# ── Report generation ───────────────────────────────────────────────────────

def generate_report(
    report_dir: str,
    single_results: List[dict],
    multi_results: List[dict],
    registration_info: dict,
) -> str:
    """Generate a comprehensive Markdown findings report."""

    total_single = len(single_results)
    total_multi = sum(r.get("total_turns", 0) for r in multi_results)
    total_queries = total_single + total_multi

    single_success = sum(1 for r in single_results if r.get("success"))
    multi_success = sum(
        1 for conv in multi_results for t in conv.get("turns", []) if t.get("success")
    )
    total_success = single_success + multi_success

    single_fail = total_single - single_success
    multi_fail = total_multi - multi_success
    total_fail = total_queries - total_success

    # Format breakdown
    format_counts = {}
    for r in single_results:
        fmt = r.get("response_format", "unknown")
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
    for conv in multi_results:
        for t in conv.get("turns", []):
            fmt = t.get("response_format", "unknown")
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

    # Category breakdown
    category_stats = {}
    for r in single_results:
        cat = r.get("category", "uncategorized")
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "success": 0, "fail": 0}
        category_stats[cat]["total"] += 1
        if r.get("success"):
            category_stats[cat]["success"] += 1
        else:
            category_stats[cat]["fail"] += 1

    # Difficulty breakdown
    difficulty_stats = {}
    for r in single_results:
        diff = r.get("difficulty", "unknown")
        if diff not in difficulty_stats:
            difficulty_stats[diff] = {"total": 0, "success": 0, "fail": 0}
        difficulty_stats[diff]["total"] += 1
        if r.get("success"):
            difficulty_stats[diff]["success"] += 1
        else:
            difficulty_stats[diff]["fail"] += 1

    # Multi-turn specific analysis
    multi_turn_marker_exposure = 0
    for conv in multi_results:
        for t in conv.get("turns", []):
            if t.get("assistant_msg_format") == "marker":
                multi_turn_marker_exposure += 1
                break  # Count per conversation, not per turn

    # LLM call count analysis (retries)
    retry_counts = []
    for r in single_results:
        retry_counts.append(r.get("llm_call_count", 1))
    for conv in multi_results:
        for t in conv.get("turns", []):
            retry_counts.append(t.get("llm_call_count", 1))

    avg_retries = sum(retry_counts) / len(retry_counts) if retry_counts else 0
    max_retries = max(retry_counts) if retry_counts else 0

    # ── Build the report ──────────────────────────────────────────────
    lines = []
    lines.append("# E2E LLM Behavior Test Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Report directory:** `{report_dir}`")
    lines.append(f"**Model:** Qwen3.5-35B-A3B-GPTQ-Int4 (via LiteLLM)")
    lines.append(f"**Data file:** `{registration_info.get('file_path', 'N/A')}`")
    lines.append(f"**Conversation ID:** `{registration_info.get('conversation_id', 'N/A')}`")
    lines.append(f"**Column Selection:** `{registration_info.get('column_selection_enabled', False)}` (threshold={registration_info.get('column_selection_threshold', 30)}, budget={registration_info.get('column_values_budget_ratio', 0.10)})")
    lines.append("")

    # ── Executive Summary ─────────────────────────────────────────────
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total queries executed | {total_queries} |")
    lines.append(f"| Successful | {total_success} ({total_success/total_queries*100:.1f}%) |" if total_queries else "| Successful | 0 |")
    lines.append(f"| Failed | {total_fail} ({total_fail/total_queries*100:.1f}%) |" if total_queries else "| Failed | 0 |")
    lines.append(f"| Single-turn queries | {total_single} |")
    lines.append(f"| Multi-turn queries | {total_multi} |")
    lines.append(f"| Avg LLM calls per query | {avg_retries:.1f} |")
    lines.append(f"| Max LLM calls per query | {max_retries} |")
    lines.append("")

    # ── LLM Output Format Analysis ────────────────────────────────────
    lines.append("## 2. LLM Output Format Analysis")
    lines.append("")
    lines.append("This is the key analysis for the `NoCodeFoundError` root cause.")
    lines.append("")
    lines.append("| Format | Count | Percentage |")
    lines.append("|--------|-------|------------|")
    for fmt, count in sorted(format_counts.items(), key=lambda x: -x[1]):
        pct = count / total_queries * 100 if total_queries else 0
        lines.append(f"| {fmt} | {count} | {pct:.1f}% |")
    lines.append("")
    lines.append("**Key finding:** The `marker` format (`---\\nCode:`) in the LLM output would trigger `NoCodeFoundError` ")
    lines.append("without the fallback extractor. The `fence` format (triple backticks) is the expected format.")
    lines.append("")

    # ── Root Cause: Assistant Message Format ───────────────────────────
    lines.append("## 3. Root Cause: Assistant Message Format in Conversation History")
    lines.append("")
    lines.append(f"**Multi-turn conversations where `---\\nCode:` marker appeared in assistant messages:** {multi_turn_marker_exposure}/{len(multi_results)}")
    lines.append("")
    lines.append("The `_store_assistant_message()` method in `pandasai/agent/base.py` stores responses as:")
    lines.append("```")
    lines.append('f"{response_text}\\n\\n---\\nCode:\\n{working_code}"')
    lines.append("```")
    lines.append("")
    lines.append("This format is sent back to the LLM on follow-up turns, potentially teaching it to mimic ")
    lines.append("the `---\\nCode:` format instead of using code fences.")
    lines.append("")

    # ── Category Breakdown ────────────────────────────────────────────
    lines.append("## 4. Results by Category")
    lines.append("")
    lines.append("| Category | Total | Success | Fail | Success Rate |")
    lines.append("|----------|-------|---------|------|--------------|")
    for cat, stats in sorted(category_stats.items()):
        rate = stats["success"] / stats["total"] * 100 if stats["total"] else 0
        lines.append(f"| {cat} | {stats['total']} | {stats['success']} | {stats['fail']} | {rate:.0f}% |")
    lines.append("")

    # ── Difficulty Breakdown ──────────────────────────────────────────
    lines.append("## 5. Results by Difficulty")
    lines.append("")
    lines.append("| Difficulty | Total | Success | Fail | Success Rate |")
    lines.append("|------------|-------|---------|------|--------------|")
    for diff, stats in sorted(difficulty_stats.items()):
        rate = stats["success"] / stats["total"] * 100 if stats["total"] else 0
        lines.append(f"| {diff} | {stats['total']} | {stats['success']} | {stats['fail']} | {rate:.0f}% |")
    lines.append("")

    # ── Single-Turn Detail ────────────────────────────────────────────
    lines.append("## 6. Single-Turn Query Details")
    lines.append("")
    lines.append("| ID | Query | Category | Difficulty | Success | Format | LLM Calls |")
    lines.append("|----|-------|----------|------------|---------|--------|-----------|")
    for r in single_results:
        q_short = r["query"][:40] + "..." if len(r["query"]) > 40 else r["query"]
        status = "✅" if r["success"] else "❌"
        lines.append(f"| {r['query_id']} | {q_short} | {r.get('category', '-')} | {r.get('difficulty', '-')} | {status} | {r.get('response_format', '-')} | {r.get('llm_call_count', 1)} |")
    lines.append("")

    # ── Multi-Turn Detail ─────────────────────────────────────────────
    lines.append("## 7. Multi-Turn Conversation Details")
    lines.append("")
    for conv in multi_results:
        lines.append(f"### {conv['conversation_id']}: {conv['name']}")
        lines.append("")
        lines.append(f"**Turns:** {conv.get('total_turns', 0)} | **Successful:** {conv.get('successful_turns', 0)} | **Formats:** {', '.join(conv.get('formats_used', []))}")
        lines.append("")
        lines.append("| Turn | Query | Success | Format | History Depth | Asst Msg Format | LLM Calls |")
        lines.append("|------|-------|---------|--------|---------------|-----------------|-----------|")
        for t in conv.get("turns", []):
            q_short = t["query"][:40] + "..." if len(t["query"]) > 40 else t["query"]
            status = "✅" if t["success"] else "❌"
            lines.append(f"| {t['turn_index']+1} | {q_short} | {status} | {t.get('response_format', '-')} | {t.get('history_depth', 0)} | {t.get('assistant_msg_format', '-') or 'N/A'} | {t.get('llm_call_count', 1)} |")
        lines.append("")

    # ── Failure Analysis ──────────────────────────────────────────────
    failures = [r for r in single_results if not r.get("success")]
    multi_failures = []
    for conv in multi_results:
        for t in conv.get("turns", []):
            if not t.get("success"):
                multi_failures.append({**t, "conversation_id": conv["conversation_id"], "name": conv["name"]})

    lines.append("## 8. Failure Analysis")
    lines.append("")
    if not failures and not multi_failures:
        lines.append("🎉 **No failures detected!** All queries completed successfully.")
    else:
        lines.append(f"**Single-turn failures:** {len(failures)}")
        for r in failures:
            lines.append(f"- **{r['query_id']}** ({r.get('category', '-')}): {r.get('error', 'Unknown error')}")
            lines.append(f"  - Query: _{r['query']}_")
            lines.append(f"  - Format: {r.get('response_format', '-')}")
        lines.append("")
        lines.append(f"**Multi-turn failures:** {len(multi_failures)}")
        for t in multi_failures:
            lines.append(f"- **{t['conversation_id']}** Turn {t['turn_index']+1}: {t.get('error', 'Unknown error')}")
            lines.append(f"  - Query: _{t['query']}_")
            lines.append(f"  - Format: {t.get('response_format', '-')}")
    lines.append("")

    # ── Recommendations ───────────────────────────────────────────────
    lines.append("## 9. Recommendations")
    lines.append("")
    marker_count = format_counts.get("marker", 0)
    if marker_count > 0:
        lines.append("### ⚠️ CRITICAL: `---\\nCode:` Marker Detected in LLM Output")
        lines.append("")
        lines.append(f"The LLM produced the `---\\nCode:` format in **{marker_count}** query responses. ")
        lines.append("This would cause `NoCodeFoundError` without the fallback extractor fix.")
        lines.append("")
        lines.append("**Immediate fix:** The `_extract_code_after_marker()` fallback in `pandasai/llm/base.py` handles this.")
        lines.append("")
        lines.append("**Root cause fix:** Change `_store_assistant_message()` in `pandasai/agent/base.py` to use code fences:")
        lines.append("```python")
        lines.append('# Before:')
        lines.append('assistant_msg = f"{response_text}\\n\\n---\\nCode:\\n{working_code}"')
        lines.append('')
        lines.append('# After:')
        lines.append('assistant_msg = f"{response_text}\\n\\n```python\\n{working_code}\\n```"')
        lines.append("```")
    else:
        lines.append("### ✅ No `---\\nCode:` Marker in LLM Output")
        lines.append("")
        lines.append("The LLM consistently used code fences. However, the root cause still exists:")
        lines.append("`_store_assistant_message()` stores `---\\nCode:` format in memory, which is sent back to the LLM.")
        lines.append("This may cause the LLM to mimic the format under certain conditions.")
        lines.append("")
        lines.append("**Recommended fix:** Change `_store_assistant_message()` to use code fences instead of `---\\nCode:`.")
    lines.append("")

    report_text = "\n".join(lines)

    # Save report
    report_path = os.path.join(report_dir, "report.md")
    with open(report_path, "w") as f:
        f.write(report_text)

    # Also save summary JSON
    summary = {
        "timestamp": datetime.now().isoformat(),
        "registration_info": registration_info,
        "total_queries": total_queries,
        "total_success": total_success,
        "total_fail": total_fail,
        "format_counts": format_counts,
        "category_stats": category_stats,
        "difficulty_stats": difficulty_stats,
        "avg_llm_calls": avg_retries,
        "max_llm_calls": max_retries,
        "multi_turn_marker_exposure": multi_turn_marker_exposure,
    }
    summary_path = os.path.join(report_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    return report_path


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E Query Bank Runner")
    parser.add_argument("--file", default=DEFAULT_XLSX_PATH, help="Path to XLSX file")
    parser.add_argument("--mode", choices=["single", "multi", "all"], default="all", help="Which queries to run")
    parser.add_argument("--only", default=None, help="Run only a specific query/conversation ID")
    parser.add_argument("--conv-id", default=None, help="Skip registration, use existing conversation ID")
    parser.add_argument("--output-type", default="string", help="Default output type")
    parser.add_argument("--no-enrich", action="store_true", help="Disable column value enrichment")
    parser.add_argument("--bank", choices=["standard", "adversarial", "adversarial_v2", "adversarial_v3", "adversarial_v4", "all"], default="standard", help="Which query bank to use")
    parser.add_argument("--column-selection", action="store_true", help="Enable column selection (2-step LLM call)")
    parser.add_argument("--column-selection-threshold", type=int, default=30, help="Column count threshold to trigger auto column selection")
    parser.add_argument("--column-values-budget-ratio", type=float, default=0.10, help="Fraction of column values to include in prompt")
    parser.add_argument("--resume", default=None, help="Resume from existing report directory")
    args = parser.parse_args()

    # Create or resume report directory
    if args.resume:
        report_dir = args.resume
        print(f"📂 Resuming from: {report_dir}")
    else:
        report_dir = create_report_dir()
        print(f"📂 Report directory: {report_dir}")

    progress = load_progress(report_dir)

    print("=" * 70)
    print("  E2E QUERY BANK RUNNER")
    print(f"  Mode: {args.mode}")
    print(f"  Bank: {args.bank}")
    print(f"  File: {args.file}")
    print(f"  Column Selection: {args.column_selection} (threshold={args.column_selection_threshold}, budget={args.column_values_budget_ratio})")
    print(f"  Report: {report_dir}")
    print("=" * 70)

    # Install monitoring hooks
    _install_hooks()
    print("\n  🔌 Monitoring hooks installed")

    registration_info = {}
    single_results = []
    multi_results = []

    try:
        # ── Registration ──────────────────────────────────────────────
        if args.mode == "single" or args.mode == "all":
            # For single-turn, we register once and reuse the agent
            if not progress.get("registration_done") and not args.conv_id:
                if not os.path.exists(args.file):
                    print(f"\n  ❌ File not found: {args.file}")
                    return

                conversation_id, agent = register_file(
                    file_path=args.file,
                    semantic_model=SEMANTIC_MODEL,
                    enrich_column_values=not args.no_enrich,
                    auto_fill_descriptions=False,
                )
                registration_info = {
                    "file_path": args.file,
                    "conversation_id": conversation_id,
                    "mode": "single_reuse",
                }
                save_scratch(report_dir, "registration_state.json", registration_info)
                progress["registration_done"] = True
                save_progress(report_dir, progress)
            elif args.conv_id:
                from server.core.agent_store import agent_store
                agent = agent_store.get_agent(args.conv_id)
                registration_info = {"conversation_id": args.conv_id, "mode": "reused"}
            else:
                # Load existing registration and re-register a fresh agent
                # (the old agent may have been garbage collected)
                reg_path = os.path.join(report_dir, "scratch", "registration_state.json")
                if os.path.exists(reg_path):
                    with open(reg_path) as f:
                        registration_info = json.load(f)
                    # Re-register since the old agent may be gone from the store
                    print("  🔄 Re-registering file (old agent may be stale)...")
                    conversation_id, agent = register_file(
                        file_path=args.file,
                        semantic_model=SEMANTIC_MODEL,
                        enrich_column_values=not args.no_enrich,
                        auto_fill_descriptions=False,
                    )
                    registration_info["conversation_id"] = conversation_id
                    save_scratch(report_dir, "registration_state.json", registration_info)
                else:
                    print("  ❌ No registration found. Run without --resume first.")
                    return

        # ── Select queries ────────────────────────────────────────────
        if args.only:
            # Try standard bank first, then adversarial
            item = get_query_by_id(args.only)
            if not item:
                item = get_adversarial_query_by_id(args.only)
            if not item:
                item = get_adversarial_v2_query_by_id(args.only)
            if not item:
                item = get_adversarial_v3_query_by_id(args.only)
            if not item:
                item = get_adversarial_v4_query_by_id(args.only)
            if not item:
                print(f"  ❌ Query/Conversation ID not found: {args.only}")
                return
            if "turns" in item:
                # Multi-turn conversation
                multi_queries = [item]
                single_queries = []
            else:
                single_queries = [item]
                multi_queries = []
        else:
            # Select based on --bank flag
            if args.bank in ("standard", "all"):
                single_queries = get_all_single_turn_queries() if args.mode in ("single", "all") else []
                multi_queries = MULTI_TURN_CONVERSATIONS if args.mode in ("multi", "all") else []
            else:
                single_queries = []
                multi_queries = []

            if args.bank in ("adversarial", "all"):
                adv_single = get_all_adversarial_single_turn_queries() if args.mode in ("single", "all") else []
                adv_multi = ADVERSARIAL_MULTI_TURN if args.mode in ("multi", "all") else []
                single_queries = single_queries + adv_single
                multi_queries = multi_queries + adv_multi

            if args.bank in ("adversarial_v2", "all"):
                adv2_single = get_all_adversarial_v2_single_turn_queries() if args.mode in ("single", "all") else []
                adv2_multi = RETRIAL_TRAP_CONVERSATIONS if args.mode in ("multi", "all") else []
                single_queries = single_queries + adv2_single
                multi_queries = multi_queries + adv2_multi

            if args.bank in ("adversarial_v3", "all"):
                adv3_single = get_all_adversarial_v3_single_turn_queries() if args.mode in ("single", "all") else []
                adv3_multi = CONVERSATION_POISON if args.mode in ("multi", "all") else []
                single_queries = single_queries + adv3_single
                multi_queries = multi_queries + adv3_multi

            if args.bank in ("adversarial_v4", "all"):
                adv4_single = get_all_adversarial_v4_single_turn_queries() if args.mode in ("single", "all") else []
                adv4_multi = []  # v4 has no multi-turn conversations
                single_queries = single_queries + adv4_single
                multi_queries = multi_queries + adv4_multi

        # ── Run single-turn queries ───────────────────────────────────
        if single_queries:
            print(f"\n{'='*70}")
            print(f"  SINGLE-TURN QUERIES: {len(single_queries)}")
            print(f"{'='*70}")

            single_results = run_single_turn_bank(
                agent=agent,
                queries=single_queries,
                report_dir=report_dir,
                progress=progress,
                output_type=args.output_type,
                column_selection_enabled=args.column_selection,
                column_selection_threshold=args.column_selection_threshold,
                column_values_budget_ratio=args.column_values_budget_ratio,
            )

            # Save single-turn results
            single_path = os.path.join(report_dir, "single_turn_results.json")
            with open(single_path, "w") as f:
                json.dump(single_results, f, indent=2, ensure_ascii=False, default=str)

        # ── Run multi-turn conversations ──────────────────────────────
        if multi_queries:
            print(f"\n{'='*70}")
            print(f"  MULTI-TURN CONVERSATIONS: {len(multi_queries)}")
            print(f"{'='*70}")

            multi_results = run_multi_turn_bank(
                register_fn=register_file,
                file_path=args.file,
                conversations=multi_queries,
                report_dir=report_dir,
                progress=progress,
                output_type=args.output_type,
                column_selection_enabled=args.column_selection,
                column_selection_threshold=args.column_selection_threshold,
                column_values_budget_ratio=args.column_values_budget_ratio,
            )

            # Save multi-turn results
            multi_path = os.path.join(report_dir, "multi_turn_results.json")
            with open(multi_path, "w") as f:
                json.dump(multi_results, f, indent=2, ensure_ascii=False, default=str)

        # ── Generate report ───────────────────────────────────────────
        print(f"\n{'='*70}")
        print(f"  GENERATING REPORT")
        print(f"{'='*70}")

        report_path = generate_report(
            report_dir=report_dir,
            single_results=single_results,
            multi_results=multi_results,
            registration_info=registration_info,
        )

        print(f"\n  📄 Report saved to: {report_path}")
        print(f"  📊 Summary saved to: {os.path.join(report_dir, 'summary.json')}")

        # ── Quick console summary ─────────────────────────────────────
        total = len(single_results) + sum(r.get("total_turns", 0) for r in multi_results)
        success = sum(1 for r in single_results if r.get("success")) + sum(
            1 for conv in multi_results for t in conv.get("turns", []) if t.get("success")
        )
        print(f"\n  ✅ Completed: {success}/{total} queries successful")

        # Check for marker format
        marker_count = sum(1 for r in single_results if r.get("response_format") == "marker")
        marker_count += sum(
            1 for conv in multi_results for t in conv.get("turns", []) if t.get("response_format") == "marker"
        )
        if marker_count > 0:
            print(f"  ⚠️  WARNING: {marker_count} queries produced `---\\nCode:` marker format!")
        else:
            print(f"  ✅ No `---\\nCode:` marker format detected in LLM output")

    finally:
        _uninstall_hooks()
        print(f"\n  🔌 Monitoring hooks removed")


if __name__ == "__main__":
    main()
