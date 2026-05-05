"""
Verify the semantic_type classification for each column in File (4).xlsx
against the vocabulary_generated.json output.

The Excel has 1 sheet ("Sheet") with 16 rows x 103 cols.
Column names are in bracket notation: [Employee Master[Employee Name]]
"""
import sys, os, json, math, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from pandasai.helpers.column_enrichment import ColumnValueExtractor

# --- 1. Load the vocabulary output ---
with open(os.path.join(os.path.dirname(__file__), "vocabulary_generated.json")) as f:
    vocab = json.load(f)

# --- 2. Load the input Excel file ---
xlsx_path = os.path.join(os.path.dirname(__file__), "File (4).xlsx")
df = pd.read_excel(xlsx_path, sheet_name="Sheet")

print(f"=== Input Excel: {df.shape[0]} rows x {df.shape[1]} cols ===\n")

# --- 3. For each column in the vocabulary, run the classifier and compare ---
print("=" * 100)
print("CLASSIFICATION VERIFICATION")
print("=" * 100)

issues = []
for entry in vocab["extracted_context"]:
    col_ref = entry["column"]  # This IS the actual column name, e.g. "[Employee Master[Employee Name]]"
    samples = entry["samples"]

    if col_ref not in df.columns:
        print(f"\n⚠️  Column '{col_ref}' not found in Excel")
        continue

    series = df[col_ref]
    n_total = series.dropna().shape[0]
    n_unique = series.dropna().nunique()

    # Determine the pandas dtype -> col_type
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        col_type = "string"
    elif pd.api.types.is_integer_dtype(series):
        col_type = "integer"
    elif pd.api.types.is_float_dtype(series):
        col_type = "float"
    elif pd.api.types.is_datetime64_any_dtype(series):
        col_type = "datetime"
    elif pd.api.types.is_bool_dtype(series):
        col_type = "boolean"
    else:
        col_type = "unknown"

    # --- Classify string columns ---
    if col_type == "string":
        # Check if the new logic converted it to datetime stats
        if isinstance(samples, dict) and "min" in samples and "max" in samples:
            print(f"\n✅ {col_ref}")
            print(f"   dtype={col_type} (handled as datetime)  n_total={n_total}  n_unique={n_unique}")
            print(f"   Classification: datetime_from_string — min={samples.get('min')}, max={samples.get('max')}")
            continue

        classification = ColumnValueExtractor._classify_string_column(series, 50)
        avg_words = series.dropna().astype(str).apply(lambda v: len(str(v).split())).mean()
        max_cell_len = series.dropna().astype(str).apply(len).max() if n_total > 0 else 0

        # What does the output look like?
        if isinstance(samples, list):
            avg_sample_words = sum(len(s.split()) for s in samples) / max(len(samples), 1)
            max_sample_len = max(len(s) for s in samples) if samples else 0
            n_samples = len(samples)
        else:
            avg_sample_words = 0
            max_sample_len = 0
            n_samples = "stats"

        # --- Detect issues ---
        issue = None

        # Issue 1: Classified as CATEGORICAL but samples contain very long text (paragraphs)
        if classification == "categorical" and isinstance(samples, list):
            long_samples = [s for s in samples if len(s) > 300]
            if long_samples:
                issue = f"CATEGORICAL but {len(long_samples)}/{len(samples)} samples are >300 chars (paragraphs). Should be FREETEXT."

        # Issue 2: Classified as FREETEXT but samples are full cell values (not word tokens)
        if classification == "freetext" and isinstance(samples, list):
            multi_word_samples = [s for s in samples if len(s.split()) > 5]
            if len(multi_word_samples) > len(samples) * 0.5:
                issue = f"FREETEXT but samples look like full cell values, not word tokens ({len(multi_word_samples)}/{len(samples)} have >5 words)."

        # Issue 3: Should be id_like but classified as categorical
        if classification == "categorical" and n_unique == n_total and avg_words <= 1.5:
            # Every value is unique and short -> probably id_like
            if any(kw in col_ref.lower() for kw in ["passport", "email", "number"]):
                issue = f"CATEGORICAL but every value is unique ({n_unique}/{n_total}) and column name suggests ID-like. Consider id_like."

        # Issue 4: Dates stored as strings
        if col_type == "string" and isinstance(samples, list):
            date_like = [s for s in samples if re.match(r"\d{4}-\d{2}-\d{2}T", s)]
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
        if isinstance(samples, list) and max_sample_len > 200:
            print(f"   📝 LONGEST SAMPLE: {samples[-1][:120]}...")

    elif col_type in ("integer", "float"):
        if isinstance(samples, dict):
            print(f"\n✅ {col_ref}")
            print(f"   dtype={col_type}  n_total={n_total}  n_unique={n_unique}")
            print(f"   Classification: numeric — min={samples.get('min')}, max={samples.get('max')}, mean={samples.get('mean')}")
        else:
            print(f"\n⚠️  {col_ref}")
            print(f"   dtype={col_type} but samples is a list, not stats")
            issues.append({"column": col_ref, "classification": "numeric", "issue": "Expected stats dict but got list"})

    elif col_type == "datetime":
        print(f"\n✅ {col_ref}")
        print(f"   dtype={col_type}  n_total={n_total}  n_unique={n_unique}  — datetime OK")

    else:
        print(f"\n⚠️  {col_ref}")
        print(f"   dtype={col_type}  — unhandled type")

# --- 4. Summary ---
print("\n" + "=" * 100)
print(f"SUMMARY: {len(vocab['extracted_context'])} columns analyzed, {len(issues)} issue(s)")
print("=" * 100)
if issues:
    print(f"\n🔴 ISSUES FOUND:")
    for iss in issues:
        print(f"   - {iss['column']}")
        print(f"     classified={iss['classification']} — {iss['issue']}")
else:
    print("\n✅ All classifications look correct!")
