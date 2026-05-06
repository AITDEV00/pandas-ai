
## DuckDB's complete search toolkit

### Tier 1: Pattern matching (built-in, no setup)

The basic operators that should be the LLM's default for "find rows containing X":

- **`LIKE` / `NOT LIKE`** — case-sensitive substring matching with `%` and `_` wildcards
- **`ILIKE` / `NOT ILIKE`** — case-insensitive version, this should be the default for any user-driven text search
- **`SIMILAR TO`** — POSIX regex-style pattern with SQL syntax
- **`~` and `~*`** — regex match (case-sensitive and case-insensitive respectively)
- **`!~` and `!~*`** — negated regex match
- **`regexp_matches(string, pattern)`** — boolean regex test
- **`regexp_extract(string, pattern, group)`** — pull out captured groups
- **`regexp_replace(string, pattern, replacement)`** — substitute
- **`regexp_full_match()`** — full-string regex match
- **`contains(string, substring)`** — simple substring test (case-sensitive)
- **`starts_with()` / `ends_with()` / `prefix()` / `suffix()`** — anchored matches

For your "find marri" case, the right default is `WHERE "English Name" ILIKE '%marri%'` — this single change fixes the case-sensitivity issue entirely.

### Tier 2: String similarity / fuzzy matching (built-in)

These are all native DuckDB scalar functions, no extension needed:

- `damerau_levenshtein(s1, s2)`, `editdist3(s1, s2)`, `hamming(s1, s2)`, `jaccard(s1, s2)`, `jaro_similarity(s1, s2)`, `jaro_winkler_similarity(s1, s2)`, `levenshtein(s1, s2)`, `mismatches(s1, s2)`

When to use which:

- **`jaro_winkler_similarity`** — best for names. Returns 0–1, weights matching prefixes. Ideal for "Al Marri" vs "Almarri" vs "Al-Marri". Your prompt should suggest a threshold like `>= 0.85` for names.
- **`levenshtein` / `damerau_levenshtein`** — edit distance (integer). Good for IDs, codes, short strings with potential typos. `damerau_levenshtein` also handles transpositions ("teh" vs "the").
- **`jaccard`** — set-overlap on character n-grams. Useful when word order doesn't matter.
- **`hamming`** — only for equal-length strings (e.g., fixed-format codes).

These are also what powers serious record-linkage libraries like Splink on top of DuckDB, so you're in good company.

### Tier 3: Text normalization helpers

Critical for making search robust before you even hit the matching function:

- **`lower()` / `upper()`** — case folding
- **`trim()` / `ltrim()` / `rtrim()`** — whitespace stripping
- **`strip_accents()`** — removes diacritics, important for transliterated Arabic names
- **`replace(string, from, to)`** — manual substitution
- **`translate()`** — character-level mapping (good for normalizing punctuation)
- **`split_part()` / `string_split()` / `string_split_regex()`** — tokenization
- **`regexp_split_to_array()`** — same, regex-based
- **`unicode_normalize()`** — NFC/NFD normalization (in newer versions)

A robust pattern: `WHERE lower(strip_accents("English Name")) LIKE lower(strip_accents('%marri%'))` — handles case AND diacritics in one shot.

### Tier 4: Full-text search via the FTS extension

For real document-style search, DuckDB has a proper FTS extension:

Full-Text Search is an extension to DuckDB that allows for search through strings, similar to SQLite's FTS5 extension. The fts extension will be transparently autoloaded on first use from the official extension repository.

The flow is: create the index, specifying the table name, the unique id column, and the column(s) to index... `PRAGMA create_fts_index('corpus', 'line_id', 'text_entry')`. The table is now ready to query using the Okapi BM25 ranking function. Rows with no match return a NULL score.

Key features worth knowing:

- BM25 scoring (the same algorithm Elasticsearch uses)
- Multi-language stemmer support across 25+ languages, configurable stop words, and customizable regex patterns and text normalization
- Supported stemmers include Arabic, English, French, German, and many others — important for your bilingual workflow
- Multi-field search with field weighting
- Optional conjunctive mode (all terms must match) via the `conjunctive := 1` parameter
- Configurable accent stripping (`strip_accents = 1`) and case folding (`lower = 1`) at index time

The major caveat: the FTS index will not update automatically when the input table changes — you have to rebuild with `overwrite := 1` after data changes. For your use case (Excel uploads, mostly read-heavy) this is fine.

### Tier 5: Vector / semantic search via the VSS extension

For "meaning-based" search where the user's words don't appear literally in the data:

- The **VSS extension** provides `array_cosine_similarity()`, `array_inner_product()`, `array_distance()` and an HNSW index for approximate nearest-neighbor search
- Combined with embeddings (from sentence-transformers, OpenAI, or your local Qwen3 embedding model), you get semantic search inside SQL
- DuckDB can be used for text analytics by combining keyword, full-text, and semantic search techniques. Using the experimental fts and vss extensions with the sentence-transformers library, DuckDB can support both traditional and modern text analytics workflows

For names this is overkill, but for "find directives about renewable energy" against document text columns, it's the right tool.

### Tier 6: Hybrid search

The most robust pattern for "needle in a haystack" is to combine multiple signals and rank:

```sql
WITH scored AS (
  SELECT *,
    -- Exact match: highest signal
    (lower("English Name") = lower('marri'))::INT * 100 AS exact_score,
    -- Substring: strong signal
    ("English Name" ILIKE '%marri%')::INT * 50 AS substring_score,
    -- Fuzzy: catches typos
    jaro_winkler_similarity(lower("English Name"), lower('marri')) * 30 AS fuzzy_score
  FROM employees
)
SELECT *, (exact_score + substring_score + fuzzy_score) AS relevance
FROM scored
WHERE relevance > 20
ORDER BY relevance DESC
LIMIT 20;
```

This pattern handles exact matches, partial matches, and typos all at once with a single ranked result list. DuckDB provides functions out of the box that make it an excellent analytical tool for both full text and embedding-based searches. These search functionalities can be seamlessly implemented directly in SQL without resorting to other tools, and CTEs enable the calculation of fused ranking metrics for the effective integration of hybrid search modes.

### Tier 7: Searching for multiple values at once

Your question mentioned "search using multiple values" — DuckDB has several patterns:

- **`IN (...)`** — exact-match any of a list: `WHERE id IN ('A1', 'B2', 'C3')`
- **`ANY` / `ALL`** — quantified comparisons
- **`list_contains(list, element)`** — works on arrays
- **`array_has_any(arr1, arr2)`** — any overlap between two arrays
- **`array_has_all(arr1, arr2)`** — full containment
- **Joining against a values list:**
  ```sql
  WHERE EXISTS (
    SELECT 1 FROM (VALUES ('marri'), ('ahmed'), ('khalid')) AS terms(t)
    WHERE "English Name" ILIKE '%' || t || '%'
  )
  ```
- **Regex alternation** — `WHERE "English Name" ~* '(marri|ahmed|khalid)'` — efficient for OR-matching many terms
- **Array of patterns with `list_filter`** — programmatic generation

### Tier 8: Phonetic matching (extension territory)

Not built into core DuckDB, but worth knowing:

- **Soundex / Metaphone / Double Metaphone** — phonetic codes that match by pronunciation. There's no official DuckDB extension yet, but you can implement Soundex in pure SQL or via a Python UDF. Useful for Arabic names where transliteration varies wildly: "Mohammed", "Mohamed", "Muhammad" all phonetically collapse.






DUCK DB NATIVELY SUPPORT JSON PER CELL!!

When PandasAI uses DuckDB as its engine, it bridges natural language and your data by passing the **schema** of your DataFrame to the underlying LLM (like OpenAI or Anthropic). 

Because you successfully parsed your columns into native Python lists of dictionaries (which DuckDB reads as `LIST(STRUCT)`), the LLM sees a highly structured schema. For example, it sees that `"Employee Leave Details"` is a list of objects containing `Leave Type`, `Leave Duration`, etc.

When you ask a question, the LLM generates **DuckDB SQL** using specific functions designed for nested data. Here is exactly how PandasAI/DuckDB searches through those lists of structs under the hood.

### Method 1: The `UNNEST` Approach (Flattening)
The most common way the LLM will generate code to search inside your structs is by using DuckDB's `UNNEST` function. This temporarily flattens the array so it can filter using standard SQL `WHERE` clauses.

**Your Prompt to PandasAI:**
> "Find all employees who have taken 'Wellbeing' leave."

**The DuckDB SQL PandasAI generates behind the scenes:**
```sql
SELECT DISTINCT "Employee Name"
FROM my_dataframe, 
     UNNEST("Employee Leave Details") AS t(leave_record)
WHERE leave_record['Leave Type'] = 'Wellbeing';
```
*How it works:* It unpacks the array. If an employee has 5 leave records, they temporarily become 5 rows. It checks if the `Leave Type` inside the struct is 'Wellbeing', filters them, and then returns the distinct employee names.

### Method 2: DuckDB Lambda Functions (List Filtering)
DuckDB has incredibly powerful native functions for lists, such as `list_filter` and `list_transform`. Modern LLMs know these DuckDB dialects very well and often prefer them because they don't require altering the shape of the table.

**Your Prompt to PandasAI:**
> "Count how many employees had an assignment as 'Senior Developer'."

**The DuckDB SQL PandasAI generates:**
```sql
SELECT COUNT(*)
FROM my_dataframe
WHERE len(
    list_filter(
        "Employee Assignment History", 
        x -> x['Position Title'] = 'Senior Developer'
    )
) > 0;
```
*How it works:* The `list_filter` function iterates through the list of structs in the `Employee Assignment History` column for *every single row*. The lambda `x -> x['Position Title'] = 'Senior Developer'` keeps only the structs that match. It then checks if the length of that filtered list is greater than 0.

### Method 3: Aggregating inside the Structs
Because you casted the types (like integers and dates) in Python first, the LLM can also do math *across* the arrays.

**Your Prompt to PandasAI:**
> "What is the total duration of all 'Sick Leave' taken by 'John Doe'?"

**The DuckDB SQL PandasAI generates:**
```sql
SELECT 
    SUM(leave_record['Leave Duration (Days)']) AS total_sick_days
FROM my_dataframe,
     UNNEST("Employee Leave Details") AS t(leave_record)
WHERE "Employee Name" = 'John Doe'
  AND leave_record['Leave Type'] = 'Sick Leave';
```

### Pro-Tip for getting the best results with PandasAI
Sometimes, if the LLM gets confused by complex nested structures, it might try to write clunky Python `apply()` loops instead of clean DuckDB SQL. To force it to write perfect array-search code, you can give it a gentle hint in your prompt:

```python
response = sdf.chat(
    "List the Employee Names who have a 'Goal Status' of 'Completed'. "
    "Hint: 'Employee Objectives' is a LIST of STRUCTS. You can use UNNEST or list_filter on it."
)
```


**Yes, absolutely!** This is where combining DuckDB with an LLM (via PandasAI) becomes incredibly powerful. 

Because DuckDB treats elements inside a `STRUCT` as standard data types, you have full access to its entire library of advanced string functions—even when querying deep inside nested arrays. 

If you prompt PandasAI to do a "fuzzy match" or "find something similar," the underlying LLM will generate DuckDB SQL using those exact functions. 

Here is how DuckDB handles both of those scenarios under the hood:

### 1. Using `ILIKE` (Case-Insensitive & Partial Matching)
If you want to find an employee who held any job title containing "manager" (regardless of whether it says "IT Manager", "Project manager", or "MANAGER"), DuckDB can use `ILIKE` directly inside its list lambda functions.

**Your Prompt to PandasAI:**
> "Find employees who have had any role containing 'manager' in their Assignment History."

**The DuckDB SQL generated:**
```sql
SELECT "Employee Name"
FROM my_dataframe
WHERE len(
    list_filter(
        "Employee Assignment History", 
        x -> x['Position Title'] ILIKE '%manager%'
    )
) > 0;
```

### 2. Using `levenshtein()` (Typo-Tolerant Search)
DuckDB natively supports the Levenshtein distance (as well as Jaro-Winkler similarity). This calculates how many single-character edits it takes to change one word into another. This is perfect for messy HR data where someone might have typed "Welbeing" instead of "Wellbeing".

**Your Prompt to PandasAI:**
> "Count how many employees took 'Wellbeing' leave, but account for minor typos in the data."

**The DuckDB SQL generated:**
```sql
SELECT COUNT(DISTINCT "Employee Name")
FROM my_dataframe, 
     UNNEST("Employee Leave Details") AS t(leave_record)
WHERE levenshtein(leave_record['Leave Type'], 'Wellbeing') <= 2; 
-- Matches exact "Wellbeing", but also "Welbeing" or "Well-being"
```

### 3. Other powerful DuckDB text functions you can trigger:
Because DuckDB is evaluating these structs natively, PandasAI can also leverage:
* **`regexp_matches()`**: For finding complex patterns (e.g., "Find all employees whose Previous Employer Name ends in 'LLC' or 'Inc'").
* **`starts_with()` / `ends_with()`**: Faster alternatives to `ILIKE` for prefixes/suffixes.
* **`contains()`**: For exact, case-sensitive substring searches.

**How to get PandasAI to do this reliably:**
LLMs are usually smart enough to map phrases like "fuzzy search" or "case-insensitive" to `ILIKE`. However, if you specifically want to use Levenshtein distance, it helps to be explicit in your natural language prompt to PandasAI:
