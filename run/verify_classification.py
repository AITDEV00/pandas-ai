"""
Verify the semantic_type classification for each column in "full data unflattened.xlsx"
against the vocabulary_generated.json output.

Handles:
  - Normal flat columns (string, numeric, datetime, boolean)
  - JSON array columns (list-of-structs) with nested inner-column vocabulary
  - Validates inner columns have: type, semantic_type, description, samples
"""
import sys, os, json, math, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from pandasai.helpers.column_enrichment import ColumnValueExtractor
from pandasai.helpers.type_determination import is_json_array_column, safe_json_parse, determine_series_type

# --- 1. Load the vocabulary output ---
vocab_path = os.path.join(os.path.dirname(__file__), "vocabulary_generated.json")
with open(vocab_path) as f:
    vocab = json.load(f)

# Build a lookup: column name -> entry
vocab_by_col = {e["column"]: e for e in vocab["extracted_context"]}

# --- 2. Load the input Excel file ---
xlsx_path = os.path.join(os.path.dirname(__file__), "full data unflattened.xlsx")
df = pd.read_excel(xlsx_path)

# Auto-detect and parse JSON array columns (same as server handler)
json_cols = []
for col in df.columns:
    if is_json_array_column(df[col]):
        df[col] = df[col].apply(lambda v: safe_json_parse(v) or [])
        json_cols.append(col)

print(f"=== Input Excel: {df.shape[0]} rows x {df.shape[1]} cols ===")
print(f"=== JSON array columns detected: {len(json_cols)} ===")
print(f"=== Vocabulary entries: {len(vocab['extracted_context'])} ===\n")

# --- 3. Classify and verify each column ---
print("=" * 110)
print("CLASSIFICATION VERIFICATION")
print("=" * 110)

issues = []
struct_stats = {"total": 0, "with_samples": 0, "inner_cols": 0, "inner_with_desc": 0, "inner_with_semantic": 0}

for col_ref in df.columns:
    series = df[col_ref]
    entry = vocab_by_col.get(col_ref)
    samples = entry["samples"] if entry else None
    vocab_type = entry.get("type", "?") if entry else "?"
    vocab_semantic = entry.get("semantic_type") if entry else None

    if entry is None:
        print(f"\n⚠️  Column '{col_ref}' — NOT in vocabulary_generated.json")
        issues.append({"column": col_ref, "classification": "missing", "issue": "Column missing from vocabulary output"})
        continue

    # ──────────────────────────────────────────────────────────────
    # CASE A: JSON array / struct column
    # ──────────────────────────────────────────────────────────────
    first_valid = series.dropna().iloc[0] if not series.dropna().empty else None
    if isinstance(first_valid, list):
        struct_stats["total"] += 1

        # Check top-level type
        if vocab_type != "list[struct]":
            print(f"\n❌ {col_ref}")
            print(f"   type={vocab_type} — expected 'list[struct]'")
            issues.append({"column": col_ref, "classification": vocab_type, "issue": f"Expected type 'list[struct]', got '{vocab_type}'"})

        # Check top-level semantic_type
        if vocab_semantic != "struct":
            print(f"\n❌ {col_ref}")
            print(f"   semantic_type={vocab_semantic} — expected 'struct'")
            issues.append({"column": col_ref, "classification": str(vocab_semantic), "issue": f"Expected semantic_type 'struct', got '{vocab_semantic}'"})

        if not isinstance(samples, dict):
            print(f"\n❌ {col_ref}")
            print(f"   type={vocab_type}  — JSON array column but samples is NOT a dict of inner columns")
            issues.append({"column": col_ref, "classification": vocab_type, "issue": "Expected nested struct dict, got something else"})
            continue

        struct_stats["with_samples"] += 1
        n_inner = len(samples)
        struct_stats["inner_cols"] += n_inner

        print(f"\n📦 {col_ref}")
        print(f"   type={vocab_type}  semantic_type={vocab_semantic}  — {n_inner} inner columns")

        for inner_col, inner_entry in samples.items():
            # New format: inner_entry is a dict with type, samples, semantic_type, description
            if not isinstance(inner_entry, dict) or "samples" not in inner_entry:
                print(f"   ⚠️  {inner_col}: OLD FORMAT — raw samples without metadata wrapper")
                issues.append({"column": f"{col_ref} -> {inner_col}", "classification": "old_format",
                               "issue": "Inner entry missing metadata wrapper (type/samples/semantic_type)"})
                continue

            inner_type = inner_entry.get("type", "?")
            inner_semantic = inner_entry.get("semantic_type")
            inner_desc = inner_entry.get("description")
            inner_samples = inner_entry["samples"]

            if inner_desc:
                struct_stats["inner_with_desc"] += 1
            if inner_semantic:
                struct_stats["inner_with_semantic"] += 1

            # Format status line
            desc_status = f"desc='{inner_desc[:40]}...'" if inner_desc and len(inner_desc) > 40 else f"desc='{inner_desc}'" if inner_desc else "desc=MISSING"
            semantic_status = f"semantic={inner_semantic}" if inner_semantic else ""

            if isinstance(inner_samples, list):
                n_samples = len(inner_samples)
                status = "✅"
                detail = f"{n_samples} values"
                if n_samples > 0:
                    avg_len = sum(len(str(s)) for s in inner_samples) / n_samples
                    long = sum(1 for s in inner_samples if len(str(s)) > 300)
                    if long > 0:
                        status = "⚠️"
                        issues.append({"column": f"{col_ref} -> {inner_col}", "classification": inner_semantic or inner_type,
                                       "issue": f"{long}/{n_samples} samples >300 chars"})
                    detail += f" (avg_len={avg_len:.0f})"
                print(f"   {status} {inner_col}: {inner_type} {semantic_status} | {detail} | {desc_status}")

            elif isinstance(inner_samples, dict):
                if "min" in inner_samples and "max" in inner_samples:
                    has_mean = "mean" in inner_samples
                    kind = "numeric" if has_mean else "datetime"
                    print(f"   ✅ {inner_col}: {kind} | min={inner_samples['min']}, max={inner_samples['max']} | {desc_status}")
                else:
                    print(f"   ⚠️  {inner_col}: dict but missing min/max keys: {list(inner_samples.keys())}")
                    issues.append({"column": f"{col_ref} -> {inner_col}", "classification": "unknown",
                                   "issue": "Stats dict missing min/max"})
            else:
                print(f"   ⚠️  {inner_col}: unexpected samples type {type(inner_samples).__name__}")

            # Warn if description is missing
            if not inner_desc:
                issues.append({"column": f"{col_ref} -> {inner_col}", "classification": inner_type,
                               "issue": "Missing description from semantic model"})
        continue

    # ──────────────────────────────────────────────────────────────
    # CASE B: Normal flat columns
    # ──────────────────────────────────────────────────────────────
    col_type = determine_series_type(series)
    n_total = series.dropna().shape[0]

    if col_type == "string":
        # Check if the extractor converted it to datetime stats
        if isinstance(samples, dict) and "min" in samples and "max" in samples:
            print(f"\n✅ {col_ref}")
            print(f"   dtype={col_type} (handled as datetime)  n_total={n_total}")
            print(f"   min={samples.get('min')}, max={samples.get('max')}")
            continue

        try:
            n_unique = series.dropna().nunique()
        except TypeError:
            n_unique = "?"

        classification = None
        try:
            classification = ColumnValueExtractor._classify_string_column(series, 50)
        except Exception:
            classification = "error"

        avg_words = series.dropna().astype(str).apply(lambda v: len(str(v).split())).mean() if n_total > 0 else 0
        max_cell_len = series.dropna().astype(str).apply(len).max() if n_total > 0 else 0

        # What does the output look like?
        if isinstance(samples, list):
            n_samples = len(samples)
            avg_sample_words = sum(len(str(s).split()) for s in samples) / max(n_samples, 1)
            max_sample_len = max(len(str(s)) for s in samples) if samples else 0
        else:
            n_samples = "stats"
            avg_sample_words = 0
            max_sample_len = 0

        # --- Detect issues ---
        issue = None

        if classification == "categorical" and isinstance(samples, list):
            long_samples = [s for s in samples if len(str(s)) > 300]
            if long_samples:
                issue = f"CATEGORICAL but {len(long_samples)}/{len(samples)} samples are >300 chars. Should be FREETEXT."

        if classification == "freetext" and isinstance(samples, list):
            multi_word_samples = [s for s in samples if len(str(s).split()) > 5]
            if len(multi_word_samples) > len(samples) * 0.5:
                issue = f"FREETEXT but samples look like full cell values ({len(multi_word_samples)}/{len(samples)} have >5 words)."

        if isinstance(samples, list):
            date_like = [s for s in samples if re.match(r"\d{4}-\d{2}-\d{2}T", str(s))]
            if len(date_like) > len(samples) * 0.8:
                issue = f"STRING column but {len(date_like)}/{len(samples)} samples are ISO date strings. Should be datetime."

        status = "✅" if not issue else "❌"
        print(f"\n{status} {col_ref}")
        print(f"   dtype={col_type}  n_total={n_total}  n_unique={n_unique}  avg_words={avg_words:.1f}  max_cell_len={max_cell_len}")
        print(f"   Classification: {classification}")
        print(f"   Output: {n_samples} samples, avg_sample_words={avg_sample_words:.1f}, max_sample_len={max_sample_len}")
        if issue:
            print(f"   🔴 ISSUE: {issue}")
            issues.append({"column": col_ref, "classification": classification, "issue": issue})

    elif col_type in ("integer", "float"):
        if isinstance(samples, dict):
            print(f"\n✅ {col_ref}")
            print(f"   dtype={col_type}  n_total={n_total}")
            print(f"   numeric — min={samples.get('min')}, max={samples.get('max')}, mean={samples.get('mean')}")
        else:
            print(f"\n⚠️  {col_ref}")
            print(f"   dtype={col_type} but samples is not a stats dict")
            issues.append({"column": col_ref, "classification": "numeric", "issue": "Expected stats dict but got something else"})

    elif col_type == "datetime":
        print(f"\n✅ {col_ref}")
        print(f"   dtype={col_type}  n_total={n_total}  — datetime OK")

    elif col_type == "boolean":
        print(f"\n✅ {col_ref}")
        print(f"   dtype={col_type}  n_total={n_total}  — boolean OK")

    else:
        print(f"\n⚠️  {col_ref}")
        print(f"   dtype={col_type}  — unhandled type")

# --- 4. Summary ---
print("\n" + "=" * 110)
print(f"SUMMARY")
print("=" * 110)
print(f"  Total columns:           {len(df.columns)}")
print(f"  Vocabulary entries:      {len(vocab['extracted_context'])}")
print(f"  JSON array columns:      {struct_stats['total']} ({struct_stats['with_samples']} with nested samples)")
print(f"  Total inner struct cols:  {struct_stats['inner_cols']}")
print(f"  Inner cols with desc:    {struct_stats['inner_with_desc']}/{struct_stats['inner_cols']}")
print(f"  Inner cols with semantic: {struct_stats['inner_with_semantic']}/{struct_stats['inner_cols']}")
print(f"  Issues found:            {len(issues)}")

if issues:
    print(f"\n🔴 ISSUES:")
    for iss in issues:
        print(f"   - {iss['column']}")
        print(f"     classified={iss['classification']} — {iss['issue']}")
else:
    print("\n✅ All classifications look correct!")
