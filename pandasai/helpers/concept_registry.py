"""Central registry for multi-struct column-selection concepts.

A *concept* is a user intent (skills, projects, performance, experience,
education, leave) that frequently spans MULTIPLE struct groups in a wide
DataFrame.  The LLM commonly selects only one struct group and stops — the
recurring "stop after one struct" gap.

The concept definitions live in the **YAML file** ``pandasai/helpers/concepts.yaml``
— the single source of truth, editable without touching Python.  This module:

- loads ``concepts.yaml`` into ``Concept`` objects
- derives struct groups from the actual DataFrame schema
- exposes keyword-matching helpers shared by both consumers

Both consumers share this one definition so they can never diverge:

 * ``Agent._detect_missing_struct_groups``  — diagnostic only (logs gaps)
 * ``ColumnSelector._repair_missing_struct_groups`` — self-healing (injects gaps)

To add a new concept, add a block to ``concepts.yaml``.  To extend keywords on an
existing concept, edit its ``paths`` there.  No column names are hardcoded —
groups are matched against the actual DataFrame schema at runtime.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

#: Path to the bundled YAML concept definition. ``PANDASAI_CONCEPTS_YAML`` can
#: override it (e.g. in tests) to point at a custom file without editing Python.
_CONCEPTS_YAML = os.environ.get(
    "PANDASAI_CONCEPTS_YAML",
    str(Path(__file__).resolve().parent / "concepts.yaml"),
)

# Substrings that count as "already selected" when checking a struct group.
# A parent group is considered selected if any of its bracket-form df columns
# appears in the selection string.
_STRUCT_PARENT_RE = re.compile(r"^\[([^\[\]]+)\[")
_INNER_FIELD_RE = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class Concept:
    """A user concept that can span multiple struct groups."""

    name: str
    #: Regex patterns; if ANY matches the (lowercased) query, the concept fires.
    patterns: Tuple[str, ...]
    #: Expansion path -> keyword(s). Paths with no keywords are ignored.
    paths: Dict[str, Tuple[str, ...]]

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        return any(re.search(p, query_lower) for p in self.patterns)

    def all_keywords(self) -> Tuple[str, ...]:
        """Flatten all path keywords into one de-duplicated keyword tuple.

        Used by the repair path, which treats the whole concept as a single
        keyword bag (rather than path-aware) for injection decisions.
        """
        seen: set[str] = set()
        flat: List[str] = []
        for keywords in self.paths.values():
            for kw in keywords:
                if kw not in seen:
                    seen.add(kw)
                    flat.append(kw)
        return tuple(flat)


def _load_concepts_from_yaml(path: str) -> Tuple[Concept, ...]:
    """Load and validate ``Concept`` objects from a YAML file.

    YAML schema (see ``concepts.yaml``)::

        concepts:
          <name>:
            patterns: [<regex>, ...]
            paths:
              <path>: [<keyword>, ...]

    Raises ``ValueError`` if the file is missing, malformed, or a concept is
    missing required keys.
    """
    if not os.path.exists(path):
        raise ValueError(f"Column-selection concepts YAML not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    raw_concepts = (data or {}).get("concepts")
    if not isinstance(raw_concepts, dict) or not raw_concepts:
        raise ValueError(f"concepts YAML '{path}' must define a non-empty 'concepts:' map")

    loaded: List[Concept] = []
    for name, body in raw_concepts.items():
        if not isinstance(body, dict):
            raise ValueError(f"concept '{name}' in '{path}' must be a mapping")
        patterns = body.get("patterns")
        paths = body.get("paths")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"concept '{name}' in '{path}' needs a non-empty 'patterns' list")
        if not isinstance(paths, dict):
            raise ValueError(f"concept '{name}' in '{path}' needs a 'paths' mapping")

        loaded.append(
            Concept(
                name=str(name),
                patterns=tuple(str(p) for p in patterns),
                paths={
                    str(k): tuple(str(kw) for kw in keywords)
                    for k, keywords in paths.items()
                },
            )
        )

    if not loaded:
        raise ValueError(f"concepts YAML '{path}' defined no concepts")
    return tuple(loaded)


# Lazy-loaded on first import so importing the module is cheap and a broken/custom
# YAML only fails at first use (where callers already handle empty concept lists).
_CONCEPTS: Optional[Tuple[Concept, ...]] = None


def _get_concepts() -> Tuple[Concept, ...]:
    global _CONCEPTS
    if _CONCEPTS is None:
        try:
            _CONCEPTS = _load_concepts_from_yaml(_CONCEPTS_YAML)
        except ValueError as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load column-selection concepts YAML: %s", exc)
            _CONCEPTS = ()
    return _CONCEPTS


def concepts_for_query(query: str) -> List[Concept]:
    """Return the concepts that match ``query``, in YAML declaration order."""
    return [c for c in _get_concepts() if c.matches(query)]


def extract_struct_parent(col_name: str) -> Optional[str]:
    """Extract the struct parent group name from a bracket-form column name.

    ``"[Employee Master[Employee Name]]"`` → ``"Employee Master"``.
    Returns ``None`` for names that are not bracket-form struct columns.
    """
    if not (isinstance(col_name, str) and col_name.startswith("[")):
        return None
    m = _STRUCT_PARENT_RE.match(col_name)
    return m.group(1).strip() if m else None


def inner_field_names(col_name: str) -> List[str]:
    """Return the inner field names of a bracket-form column, e.g.
    ``[Parent[A][B]]`` → ``["A", "B"]``."""
    if not (isinstance(col_name, str) and col_name.startswith("[") and "]" in col_name):
        return []
    return _INNER_FIELD_RE.findall(col_name[1:-1])


def collect_struct_groups(dfs) -> Dict[str, List[str]]:
    """Map each struct *parent* group -> its df column name(s), from actual data.

    The DataFrame columns are the source of truth for what can be queried, so
    both diagnostic and repair operate on this map and can never diverge.
    A parent is only treated as a real struct group if it has ≥1 inner field.
    """
    struct_groups: Dict[str, List[str]] = {}
    for df in dfs:
        df_cols = df.columns if hasattr(df, "columns") else []
        for col_name in df_cols:
            if not (isinstance(col_name, str) and col_name.startswith("[")):
                continue
            parent = extract_struct_parent(col_name)
            if not parent or not inner_field_names(col_name):
                continue
            if col_name not in struct_groups.setdefault(parent, []):
                struct_groups[parent].append(col_name)
    return struct_groups


def _group_haystack(parent: str, df_cols: List[str]) -> str:
    """Lowercased parent name + all inner field names, for keyword matching."""
    fields = " ".join(f for col in df_cols for f in inner_field_names(col))
    return f"{parent.lower()} {fields.lower()}"


def is_group_selected(parent: str, df_cols: List[str], selected_names) -> bool:
    """True if any df column of the parent group appears in the selection.

    A parent is selected if ANY of its df columns appear by full bracket name,
    OR the parent name appears as a substring of a selected name (e.g. the LLM
    selected a bare ``"Employee Master"`` without brackets).
    """
    selected_str = " ".join(str(n) for n in selected_names).lower()
    if any(c.lower() in selected_str for c in df_cols):
        return True
    return any(parent.lower() in str(n).lower() for n in selected_names)


def expected_groups(concept: Concept, struct_groups: Dict[str, List[str]]) -> set[str]:
    """Struct parent groups that belong to ``concept``, per its keywords."""
    expected: set[str] = set()
    for parent, df_cols in struct_groups.items():
        haystack = _group_haystack(parent, df_cols)
        if any(kw in haystack for kw in concept.all_keywords()):
            expected.add(parent)
    return expected


def expected_groups_by_path(
    concept: Concept, struct_groups: Dict[str, List[str]]
) -> Dict[str, set[str]]:
    """Like ``expected_groups`` but bucketed by expansion path name."""
    by_path: Dict[str, set[str]] = {}
    for path_name, keywords in concept.paths.items():
        if not keywords:
            continue
        matched: set[str] = set()
        for parent, df_cols in struct_groups.items():
            haystack = _group_haystack(parent, df_cols)
            if any(kw in haystack for kw in keywords):
                matched.add(parent)
        by_path[path_name] = matched
    return by_path


def missing_groups(
    concept: Concept, struct_groups: Dict[str, List[str]], selected_names
) -> List[str]:
    """Struct parent groups expected for ``concept`` but missing from selection.

    A parent is missing if it is expected (by keyword) and none of its df
    columns appear in the selection.
    """
    expected = expected_groups(concept, struct_groups)
    missing: List[str] = []
    for parent in expected:
        df_cols = struct_groups.get(parent, [])
        if not is_group_selected(parent, df_cols, selected_names):
            missing.append(parent)
    return missing