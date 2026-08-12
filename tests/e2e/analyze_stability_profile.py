"""Analyze the per-run JSON emitted by run_stability_agent.py and produce a
precise per-query / per-step timing profile, including every LLM call, every
generation/execution attempt, every retry, and every validation sub-step.

Usage:
    python tests/e2e/analyze_stability_profile.py <run_dir> [--question Q]
"""
import argparse
import json
from pathlib import Path


def fmt(s):
    return f"{s:7.2f}s" if s is not None else "    n/a "


def analyze_run(d):
    qid = d["question"]
    run = d["run"]
    t = d.get("timings", {})
    total = d.get("elapsed_total")
    executed = d.get("executed")
    rtype = d.get("response_type")
    rval = d.get("response_value")
    retried = d.get("retried")
    gen = d.get("gen_attempts")
    exc = d.get("exec_attempts")

    print(f"\n{'='*78}")
    print(f"{qid}  r{run}/5   executed={executed}  type={rtype}  value={rval}")
    print(f"  retried={retried}  gen_attempts={gen}  exec_attempts={exc}  "
          f"elapsed_total={fmt(total)}")
    print(f"  timings: colsel={fmt(t.get('column_selection'))} "
          f"(llm={fmt(t.get('column_selection_llm'))} "
          f"schema={fmt(t.get('column_selection_schema'))}) | "
          f"codegen={fmt(t.get('code_generation'))} "
          f"(retries={t.get('code_generation_retries')}) | "
          f"exec={fmt(t.get('code_execution'))} "
          f"(retries={t.get('code_execution_retries')}) | "
          f"total={fmt(t.get('total'))}")

    # LLM calls
    print("  [LLM calls]")
    if d.get("llm_call_log"):
        for c in d["llm_call_log"]:
            attempts_d = c.get("attempts_detail") or []
            attempt_str = ""
            if attempts_d:
                kinds = ",".join(f"{a['kind']}{a['dur_s']}s" for a in attempts_d)
                attempt_str = f"  attempts=[{kinds}]"
            print(f"    seq={c.get('seq')} {c.get('kind')} "
                  f"phase={c.get('phase')} {fmt(c.get('elapsed_s'))} "
                  f"finish={c.get('finish_reason')} "
                  f"thinking={c.get('thinking_chars')}ch{attempt_str}")
    else:
        print("    (none logged)")

    # Per codegen step timing
    if d.get("codegen_step_timings"):
        print("  [codegen step timings (per attempt)]")
        for s in d["codegen_step_timings"]:
            print(f"    llm_call={fmt(s.get('llm_call_s'))} "
                  f"validate={fmt(s.get('code_validation_s'))} "
                  f"struct={fmt(s.get('structural_review_s'))} "
                  f"clean={fmt(s.get('cleaning_s'))} "
                  f"total={fmt(s.get('total_s'))}")

    # Attempts
    print("  [attempts]")
    for a in d.get("code_attempts", []):
        err = a.get("error_type") or a.get("error")
        print(f"    {a['phase']}#{a['attempt']} time={fmt(a.get('time_s'))} "
              f"err={err if err else 'None'}")

    # SQL
    if d.get("sql_queries"):
        print(f"  [sql_queries] {len(d['sql_queries'])} executed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=str)
    ap.add_argument("--question", type=str, default=None)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    files = sorted(run_dir.glob("*_r*.json"))
    if args.question:
        files = [f for f in files if args.question.lower() in f.name.lower()]
    if not files:
        print(f"No per-run JSON files in {run_dir}")
        return

    for f in files:
        try:
            d = json.load(open(f))
        except Exception as e:
            print(f"skip {f}: {e}")
            continue
        analyze_run(d)

    # Summary aggregation
    print("\n" + "=" * 78)
    print("AGGREGATE SUMMARY")
    print("=" * 78)
    results = []
    for f in files:
        try:
            results.append(json.load(open(f)))
        except Exception:
            pass
    if not results:
        return
    ok = sum(1 for d in results if d.get("executed"))
    retried = sum(1 for d in results if d.get("retried"))
    totals = [d.get("elapsed_total") or 0 for d in results]
    cs_llm = [d.get("timings", {}).get("column_selection_llm") or 0 for d in results]
    cg = [d.get("timings", {}).get("code_generation") or 0 for d in results]
    ex = [d.get("timings", {}).get("code_execution") or 0 for d in results]
    llm_all = [c.get("elapsed_s", 0) for d in results for c in d.get("llm_call_log", [])]
    print(f"  success={ok}/{len(results)}  retried={retried}/{len(results)}")
    print(f"  avg total={sum(totals)/len(totals):.2f}s  "
          f"max total={max(totals):.2f}s")
    print(f"  avg colsel_llm={sum(cs_llm)/len(cs_llm):.2f}s  "
          f"avg codegen={sum(cg)/len(cg):.2f}s  avg exec={sum(ex)/len(ex):.2f}s")
    if llm_all:
        print(f"  total LLM-call wall across all runs={sum(llm_all):.2f}s "
              f"avg per call={sum(llm_all)/len(llm_all):.2f}s "
              f"({len(llm_all)} calls)")
    # by-question
    from collections import defaultdict
    byq = defaultdict(list)
    for d in results:
        byq[d["question"]].append(d)
    print("\n  Per-question:")
    for qid, ds in byq.items():
        qok = sum(1 for d in ds if d.get("executed"))
        qret = sum(1 for d in ds if d.get("retried"))
        qt = [d.get("elapsed_total") or 0 for d in ds]
        qcs = sum(d.get("timings", {}).get("column_selection_llm") or 0 for d in ds)
        qcg = sum(d.get("timings", {}).get("code_generation") or 0 for d in ds)
        qex = sum(d.get("timings", {}).get("code_execution") or 0 for d in ds)
        n = len(ds)
        print(f"    {qid:>24}  ok={qok}/{n} retry={qret} "
              f"avg_total={sum(qt)/n:.1f}s "
              f"colsel_llm={qcs/n:.1f}s codegen={qcg/n:.1f}s exec={qex/n:.1f}s")


if __name__ == "__main__":
    main()