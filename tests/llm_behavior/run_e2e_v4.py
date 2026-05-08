#!/usr/bin/env python3
"""Run adversarial v4 e2e bank with all three root cause fixes applied."""

import sys
import time
import json
from datetime import datetime

sys.path.insert(0, "/home/jyao/ADEO/services/ait-icarus/pandas-ai")

from tests.llm_behavior.query_bank_adversarial_v4 import get_all_adversarial_v4_single_turn_queries
from tests.llm_behavior.test_e2e_pipeline import (
    SEMANTIC_MODEL, register_file, run_chat_query,
    _install_hooks, _uninstall_hooks,
)

def main():
    queries = get_all_adversarial_v4_single_turn_queries()
    print(f"Running {len(queries)} queries from adversarial v4 bank")
    print("=" * 70)

    _install_hooks()

    try:
        # Register file once
        print("Registering file...")
        conversation_id, agent = register_file(
            file_path="/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/full data unflattened.xlsx",
            semantic_model=SEMANTIC_MODEL,
            enrich_column_values=True,
            auto_fill_descriptions=False,
        )
        print(f"Conversation ID: {conversation_id}")

        results = []
        for i, q in enumerate(queries):
            qid = q.get("id", f"Q{i+1}")
            query = q["query"]
            category = q.get("category", "unknown")
            difficulty = q.get("difficulty", "unknown")

            print(f"\n{'#'*70}")
            print(f"  {qid} ({category}, {difficulty})")
            print(f"  {query}")
            print(f"{'#'*70}")

            try:
                result = run_chat_query(
                    agent=agent,
                    query=query,
                    output_type="string",
                    column_selection_enabled=True,
                    column_selection_threshold=30,
                    column_values_budget_ratio=0.10,
                )
                status = "✅" if result.success else "❌"
                answer = str(result.final_response)[:120] if result.final_response else "NONE"
                print(f"  {status} Answer: {answer}")
                if result.error:
                    print(f"  Error: {result.error[:120]}")
                results.append({
                    "id": qid, "query": query, "category": category,
                    "difficulty": difficulty, "success": result.success,
                    "answer": str(result.final_response) if result.final_response else "",
                    "error": result.error or "",
                })
            except Exception as e:
                import traceback
                print(f"  ❌ EXCEPTION: {type(e).__name__}: {str(e)[:120]}")
                traceback.print_exc()
                results.append({
                    "id": qid, "query": query, "category": category,
                    "difficulty": difficulty, "success": False,
                    "answer": "", "error": f"{type(e).__name__}: {e}",
                })

            time.sleep(1)

        # Summary
        print(f"\n{'='*70}")
        print("  FINAL SUMMARY")
        print(f"{'='*70}")
        total = len(results)
        succeeded = sum(1 for r in results if r["success"])
        print(f"  Total: {total} | Succeeded: {succeeded} | Failed: {total - succeeded}")
        print()

        # By category
        categories = {}
        for r in results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = {"total": 0, "success": 0}
            categories[cat]["total"] += 1
            if r["success"]:
                categories[cat]["success"] += 1

        print("  By Category:")
        for cat, stats in categories.items():
            print(f"    {cat}: {stats['success']}/{stats['total']}")

        print()
        print("  Per-Query:")
        for r in results:
            status = "✅" if r["success"] else "❌"
            answer_short = r["answer"][:80] if r["answer"] else ""
            err_short = r["error"][:60] if r["error"] else ""
            line = f"    {status} {r['id']}: {answer_short}"
            if err_short:
                line += f" | ERR: {err_short}"
            print(line)

        # Save results
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = f"/home/jyao/ADEO/services/ait-icarus/pandas-ai/run/e2e_reports/{ts}_v4_fixes/results.json"
        import os
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "timestamp": ts,
                "total": total,
                "succeeded": succeeded,
                "failed": total - succeeded,
                "by_category": categories,
                "results": results,
            }, f, indent=2)
        print(f"\n  Results saved to: {out_path}")

    finally:
        _uninstall_hooks()
        print("\n  Monitoring hooks removed")


if __name__ == "__main__":
    main()
