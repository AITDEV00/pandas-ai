#!/usr/bin/env python3
"""
Run adversarial v5 e2e bank — Column Selection Memory Isolation Tests
======================================================================

Tests the fix for the column selection memory leak bug by running
multi-turn conversations where successive queries select DIFFERENT columns.

The key assertions:
  1. Turn N's generated code must NOT reference columns from Turn N-1's
     selection that are not in Turn N's trimmed set.
  2. Step 2's LLM prompt should NOT contain `last_code_generated` or
     conversation history messages when column selection is active.
  3. After a multi-turn conversation completes, the agent's memory should
     still contain all previous turns' messages (merge-back works).

Usage:
    python tests/llm_behavior/run_e2e_v5.py

    # Only run a specific category:
    python tests/llm_behavior/run_e2e_v5.py --category wide_then_narrow

    # Only run a specific conversation by ID:
    python tests/llm_behavior/run_e2e_v5.py --id WN-001

    # Skip the column-leak assertion (just run and see if queries succeed):
    python tests/llm_behavior/run_e2e_v5.py --skip-leak-check
"""

import ast
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, "/home/jyao/ADEO/service/pandas-ai")

from tests.llm_behavior.query_bank_adversarial_v5 import (
    get_all_adversarial_v5_conversations,
    get_adversarial_v5_by_id,
    get_adversarial_v5_by_category,
    get_adversarial_v5_stats,
)
from tests.llm_behavior.test_e2e_pipeline import (
    SEMANTIC_MODEL,
    register_file,
    run_chat_query,
    _install_hooks,
    _uninstall_hooks,
    StepResult,
    QueryTestResult,
)

# ── Configuration ──────────────────────────────────────────────────────────

DEFAULT_XLSX = "/home/jyao/ADEO/service/pandas-ai/run/full data unflattened.xlsx"
COLUMN_SELECTION_THRESHOLD = 30
COLUMN_VALUES_BUDGET_RATIO = 0.10

# ── Column name normalization ──────────────────────────────────────────────
# The semantic model uses bracket-style names like "[Employee Master[Basic Salary]]"
# but the LLM might reference them in code as just "Basic Salary" or with brackets.
# We need to normalize for comparison.

def extract_short_names(column_names: List[str]) -> set:
    """
    Extract short (inner) names from bracket-style column names.
    e.g. "[Employee Master[Basic Salary]]" → {"Basic Salary", "[Employee Master[Basic Salary]]"}
    """
    result = set()
    for name in column_names:
        result.add(name)  # full bracket name
        # Extract inner field name: [Parent[Child]] → Child
        m = re.match(r'\[.+\[(.+)\]\]', name)
        if m:
            result.add(m.group(1))
        # Also add without outer brackets: [Parent[Child]] → Parent[Child]
        m2 = re.match(r'\[(.+)\[(.+)\]\]', name)
        if m2:
            result.add(f"{m2.group(1)}[{m2.group(2)}]")
    return result


def find_forbidden_references(code: str, forbidden_columns: List[str]) -> List[str]:
    """
    Check if the generated code references any forbidden column names.
    Returns a list of forbidden column names found in the code.
    """
    forbidden_set = extract_short_names(forbidden_columns)
    found = []
    for col_name in forbidden_set:
        # Check for the column name as a string literal in the code
        # (e.g., in SQL queries like SELECT "column_name" or in string comparisons)
        if col_name in code:
            found.append(col_name)
    return found


def find_forbidden_references_sql(code: str, forbidden_columns: List[str]) -> List[str]:
    """
    More targeted check: look for forbidden column names inside SQL string literals
    within execute_sql_query calls. This is the primary leak vector — the LLM
    writes SQL that references columns not in the trimmed set.
    """
    found = []

    # Find all string literals in execute_sql_query calls
    sql_pattern = re.compile(r'execute_sql_query\s*\(\s*[f]?["\'](.+?)["\']', re.DOTALL)
    for match in sql_pattern.finditer(code):
        sql_str = match.group(1)

        # Check each forbidden column
        forbidden_set = extract_short_names(forbidden_columns)
        for col_name in forbidden_set:
            if col_name in sql_str:
                found.append(col_name)

    return found


def check_step2_prompt_isolation(result: QueryTestResult) -> Dict:
    """
    Check that Step 2's LLM prompt does NOT leak:
    1. last_code_generated from a previous turn
    2. Conversation history messages from previous turns

    Returns a dict with isolation check results.
    """
    checks = {
        "has_step2_prompt": False,
        "prompt_has_last_code": False,
        "prompt_has_history_messages": False,
        "history_message_count": 0,
        "isolation_passed": True,
        "details": [],
    }

    # Find the prompt_rendered step(s) — Step 2 is the code generation step
    for step in result.steps:
        if step.step_name == "prompt_rendered":
            prompt_str = step.raw_output or ""
            checks["has_step2_prompt"] = True

            # Check for last_code_generated leak
            # The template shows it in a section like:
            #   Last code generated:
            #   ```python
            #   ...
            #   ```
            if "last_code_generated" in prompt_str.lower() or "last code generated" in prompt_str.lower():
                checks["prompt_has_last_code"] = True
                checks["isolation_passed"] = False
                checks["details"].append("Step 2 prompt contains 'last_code_generated' reference")

            # Check for conversation history messages
            # If the prompt contains conversation history, it means the Memory
            # was not properly isolated
            if "Conversation history" in prompt_str or "conversation history" in prompt_str:
                checks["prompt_has_history_messages"] = True
                checks["isolation_passed"] = False
                checks["details"].append("Step 2 prompt contains conversation history section")

    # Also check the LLM messages — if there are history messages beyond
    # system + user, the memory was not properly isolated
    for step in result.steps:
        if step.step_name == "llm_call":
            history_count = step.details.get("history_messages", 0)
            checks["history_message_count"] = history_count
            if history_count > 0:
                # On the FIRST turn of a conversation, history should be 0
                # On subsequent turns, Step 2 should have 0 history (isolated)
                # But Step 1 (column selection) should have history
                checks["prompt_has_history_messages"] = True
                checks["details"].append(f"Step 2 LLM call has {history_count} history messages")

    return checks


def check_memory_merge_back(agent) -> Dict:
    """
    After a multi-turn conversation, verify that the agent's memory
    contains messages from all turns (merge-back works).
    """
    memory = agent._state.memory
    messages = memory.all()
    return {
        "total_messages": len(messages),
        "user_messages": sum(1 for m in messages if m["is_user"]),
        "assistant_messages": sum(1 for m in messages if not m["is_user"]),
    }


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run adversarial v5 e2e — Column Selection Memory Isolation Tests"
    )
    parser.add_argument("--category", default=None, help="Only run this category")
    parser.add_argument("--id", default=None, help="Only run this conversation by ID")
    parser.add_argument("--skip-leak-check", action="store_true",
                        help="Skip the column-leak assertion (just check if queries succeed)")
    parser.add_argument("--save", default=None, help="Save detailed results to JSON file")
    args = parser.parse_args()

    # Get conversations
    if args.id:
        conversations = [get_adversarial_v5_by_id(args.id)]
        if conversations[0] is None:
            print(f"ERROR: Conversation ID '{args.id}' not found")
            sys.exit(1)
    elif args.category:
        conversations = get_adversarial_v5_by_category(args.category)
        if not conversations:
            print(f"ERROR: Category '{args.category}' not found")
            sys.exit(1)
    else:
        conversations = get_all_adversarial_v5_conversations()

    stats = get_adversarial_v5_stats()
    print("=" * 70)
    print("  COLUMN SELECTION MEMORY ISOLATION — V5 E2E TEST")
    print("=" * 70)
    print(f"  Conversations: {stats['total_conversations']}")
    print(f"  Total turns:   {stats['total_turns']}")
    print(f"  Categories:    {', '.join(f'{k} ({v})' for k, v in stats['categories'].items())}")
    print(f"  Leak check:    {'SKIP' if args.skip_leak_check else 'ON'}")
    print("=" * 70)

    _install_hooks()

    try:
        # Register file once
        print("\n  Registering file...")
        conversation_id, agent = register_file(
            file_path=DEFAULT_XLSX,
            semantic_model=SEMANTIC_MODEL,
            enrich_column_values=True,
            auto_fill_descriptions=False,
        )
        print(f"  Conversation ID: {conversation_id}")

        # Track results
        all_results = []  # type: List[Dict]
        conversation_results = []  # type: List[Dict]

        for conv_idx, conv in enumerate(conversations):
            conv_id = conv["id"]
            conv_category = conv["category"]
            conv_difficulty = conv["difficulty"]
            conv_turns = conv["conversation"]

            print(f"\n{'#'*70}")
            print(f"  CONVERSATION: {conv_id} ({conv_category}, {conv_difficulty})")
            print(f"  Turns: {len(conv_turns)}")
            print(f"{'#'*70}")

            # Reset agent memory for each new conversation by re-registering
            # (Each conversation should start fresh)
            if conv_idx > 0:
                print("\n  Re-registering file for fresh conversation...")
                conversation_id, agent = register_file(
                    file_path=DEFAULT_XLSX,
                    semantic_model=SEMANTIC_MODEL,
                    enrich_column_values=True,
                    auto_fill_descriptions=False,
                )
                print(f"  New Conversation ID: {conversation_id}")

            turn_results = []
            all_isolation_passed = True
            all_leak_checks_passed = True

            for turn_def in conv_turns:
                turn_num = turn_def["turn"]
                query = turn_def["query"]
                expected_columns = turn_def.get("expected_columns", [])
                forbidden_columns = turn_def.get("forbidden_columns", [])

                print(f"\n  ── Turn {turn_num}: {query[:70]}...")
                print(f"     Expected columns: {expected_columns}")
                print(f"     Forbidden columns: {forbidden_columns}")

                try:
                    result = run_chat_query(
                        agent=agent,
                        query=query,
                        output_type="string",
                        column_selection_enabled=True,
                        column_selection_threshold=COLUMN_SELECTION_THRESHOLD,
                        column_values_budget_ratio=COLUMN_VALUES_BUDGET_RATIO,
                    )

                    # ── Check 1: Query succeeded ──
                    turn_success = result.success
                    status = "✅" if turn_success else "❌"
                    answer = str(result.final_response)[:120] if result.final_response else "NONE"
                    print(f"  {status} Answer: {answer}")

                    # ── Check 2: Step 2 prompt isolation ──
                    isolation = check_step2_prompt_isolation(result)
                    isolation_passed = isolation["isolation_passed"]
                    if not isolation_passed:
                        all_isolation_passed = False
                        print(f"  ⚠️  ISOLATION CHECK FAILED:")
                        for detail in isolation["details"]:
                            print(f"       - {detail}")
                    else:
                        print(f"  ✅ Isolation check passed (history_messages={isolation['history_message_count']})")

                    # ── Check 3: Generated code does NOT reference forbidden columns ──
                    leak_found = []
                    if not args.skip_leak_check:
                        # Get the extracted code
                        code = result.extracted_code
                        if code and forbidden_columns:
                            leak_found = find_forbidden_references_sql(code, forbidden_columns)
                            if not leak_found:
                                # Also check the broader code (not just SQL strings)
                                leak_found = find_forbidden_references(code, forbidden_columns)
                                # Filter: only count if it's in a string context (not just a substring)
                                # This reduces false positives
                                filtered = []
                                for col in leak_found:
                                    # Check if the column name appears in a string literal
                                    if f'"{col}"' in code or f"'{col}'" in code or f"`{col}`" in code:
                                        filtered.append(col)
                                leak_found = filtered

                        if leak_found:
                            all_leak_checks_passed = False
                            print(f"  ❌ COLUMN LEAK DETECTED: {leak_found}")
                            print(f"     Forbidden columns found in generated code!")
                        else:
                            print(f"  ✅ No column leak detected")

                    turn_results.append({
                        "turn": turn_num,
                        "query": query,
                        "success": turn_success,
                        "isolation_passed": isolation_passed,
                        "leak_check_passed": len(leak_found) == 0,
                        "leaked_columns": leak_found,
                        "expected_columns": expected_columns,
                        "forbidden_columns": forbidden_columns,
                        "answer": str(result.final_response) if result.final_response else "",
                        "error": result.error or "",
                        "isolation_details": isolation,
                    })

                except Exception as e:
                    print(f"  ❌ EXCEPTION: {type(e).__name__}: {str(e)[:120]}")
                    traceback.print_exc()
                    turn_results.append({
                        "turn": turn_num,
                        "query": query,
                        "success": False,
                        "isolation_passed": False,
                        "leak_check_passed": False,
                        "leaked_columns": [],
                        "expected_columns": expected_columns,
                        "forbidden_columns": forbidden_columns,
                        "answer": "",
                        "error": f"{type(e).__name__}: {e}",
                        "isolation_details": {},
                    })

                time.sleep(1)  # Rate limiting

            # ── Check 4: Memory merge-back ──
            memory_info = check_memory_merge_back(agent)
            expected_messages = len(conv_turns) * 2  # Each turn adds 1 user + 1 assistant message
            merge_back_ok = memory_info["total_messages"] >= expected_messages
            print(f"\n  ── Memory merge-back: {memory_info}")
            print(f"     Expected ≥ {expected_messages} messages, got {memory_info['total_messages']}")
            if merge_back_ok:
                print(f"  ✅ Merge-back check passed")
            else:
                print(f"  ⚠️  Merge-back check: fewer messages than expected")

            # Conversation summary
            conv_success = all(t["success"] for t in turn_results)
            conv_isolation = all(t["isolation_passed"] for t in turn_results)
            conv_leak_free = all(t["leak_check_passed"] for t in turn_results)
            conv_overall = conv_success and conv_isolation and conv_leak_free

            overall_status = "✅" if conv_overall else "❌"
            print(f"\n  {overall_status} CONVERSATION {conv_id} SUMMARY:")
            print(f"     Query success:  {'✅' if conv_success else '❌'} ({sum(1 for t in turn_results if t['success'])}/{len(turn_results)})")
            print(f"     Isolation:      {'✅' if conv_isolation else '❌'} ({sum(1 for t in turn_results if t['isolation_passed'])}/{len(turn_results)})")
            print(f"     Leak-free:      {'✅' if conv_leak_free else '❌'} ({sum(1 for t in turn_results if t['leak_check_passed'])}/{len(turn_results)})")
            print(f"     Merge-back:     {'✅' if merge_back_ok else '⚠️ '}")

            conversation_results.append({
                "id": conv_id,
                "category": conv_category,
                "difficulty": conv_difficulty,
                "overall_passed": conv_overall,
                "query_success": conv_success,
                "isolation_passed": conv_isolation,
                "leak_free": conv_leak_free,
                "merge_back_ok": merge_back_ok,
                "turns": turn_results,
                "memory_info": memory_info,
            })

        # ── Global Summary ──
        print(f"\n{'='*70}")
        print("  FINAL SUMMARY — COLUMN SELECTION MEMORY ISOLATION")
        print(f"{'='*70}")

        total_conv = len(conversation_results)
        total_passed = sum(1 for c in conversation_results if c["overall_passed"])
        total_query_success = sum(1 for c in conversation_results if c["query_success"])
        total_isolation = sum(1 for c in conversation_results if c["isolation_passed"])
        total_leak_free = sum(1 for c in conversation_results if c["leak_free"])
        total_merge_back = sum(1 for c in conversation_results if c["merge_back_ok"])

        print(f"\n  Conversations: {total_conv}")
        print(f"  Overall passed: {total_passed}/{total_conv}")
        print(f"  Query success:  {total_query_success}/{total_conv}")
        print(f"  Isolation ok:   {total_isolation}/{total_conv}")
        print(f"  Leak-free:      {total_leak_free}/{total_conv}")
        print(f"  Merge-back ok:  {total_merge_back}/{total_conv}")

        # By category
        print(f"\n  By Category:")
        categories = {}
        for c in conversation_results:
            cat = c["category"]
            if cat not in categories:
                categories[cat] = {"total": 0, "passed": 0, "success": 0, "isolation": 0, "leak_free": 0}
            categories[cat]["total"] += 1
            if c["overall_passed"]:
                categories[cat]["passed"] += 1
            if c["query_success"]:
                categories[cat]["success"] += 1
            if c["isolation_passed"]:
                categories[cat]["isolation"] += 1
            if c["leak_free"]:
                categories[cat]["leak_free"] += 1

        for cat, s in categories.items():
            print(f"    {cat}: passed={s['passed']}/{s['total']} | "
                  f"success={s['success']}/{s['total']} | "
                  f"isolation={s['isolation']}/{s['total']} | "
                  f"leak_free={s['leak_free']}/{s['total']}")

        # Per-turn details
        print(f"\n  Per-Turn Details:")
        for c in conversation_results:
            for t in c["turns"]:
                flags = []
                if not t["success"]:
                    flags.append("FAIL")
                if not t["isolation_passed"]:
                    flags.append("ISOLATION")
                if not t["leak_check_passed"]:
                    flags.append(f"LEAK({t['leaked_columns']})")
                flag_str = " | ".join(flags) if flags else "OK"
                print(f"    {c['id']}/T{t['turn']}: {flag_str}")

        # Save results
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = f"/home/jyao/ADEO/service/pandas-ai/run/e2e_reports/{ts}_v5_isolation"
        out_path = os.path.join(out_dir, "results.json")
        os.makedirs(out_dir, exist_ok=True)

        output_data = {
            "timestamp": ts,
            "test_type": "v5_column_selection_isolation",
            "config": {
                "column_selection_enabled": True,
                "column_selection_threshold": COLUMN_SELECTION_THRESHOLD,
                "column_values_budget_ratio": COLUMN_VALUES_BUDGET_RATIO,
                "leak_check_enabled": not args.skip_leak_check,
            },
            "summary": {
                "total_conversations": total_conv,
                "overall_passed": total_passed,
                "query_success": total_query_success,
                "isolation_passed": total_isolation,
                "leak_free": total_leak_free,
                "merge_back_ok": total_merge_back,
                "by_category": categories,
            },
            "conversations": conversation_results,
        }

        with open(out_path, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  📁 Results saved to: {out_path}")

    finally:
        _uninstall_hooks()
        print("\n  Monitoring hooks removed")


if __name__ == "__main__":
    main()
