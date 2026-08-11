"""Unit tests for the column-selection concept registry (concepts.yaml loader)."""

import os
from pathlib import Path

import pytest

from pandasai.helpers.concept_registry import (
    Concept,
    _load_concepts_from_yaml,
    collect_struct_groups,
    concepts_for_query,
    expected_groups_by_path,
    extract_struct_parent,
    inner_field_names,
    is_group_selected,
    missing_groups,
)


class _Renderer:
    """Minimal stand-in exposing only ``columns`` (all the registry needs)."""

    def __init__(self, columns):
        self.columns = columns


SAMPLE_COLS = [
    "[Employee Master[Employee Name]]",
    "[Employee Master[Employee Number]]",
    "[CV Employee Summary[CV Employee Summary]]",
    "[CV Employee Competencies[Technical Competency Name]]",
    "[Employee Competencies Rating[Competancy Name][Employee Rating][Supervisor Rating]]",
    "[CV Employee Work Experience[CV Job Title][CV Responsibilities Summary]]",
    "[Employee Achievements[Customary Name][Manager OA Comments]]",
    "[CV Employee Education[CV Institution Name][CV Degree Name]]",
    "[Employee Leave Details[Leave Type][Leave Duration (Days)]]",
    "Employee Name",  # flat, not a struct group
]

MINIMAL_YAML = """
concepts:
  skills:
    patterns:
      - '\\bskill\\b'
      - '\\bcompetenc'
    paths:
      direct: [competenc, skill]
      measurement: [rating]
      summary: [summary]
"""


def _write_yaml(tmpdir, body):
    path = os.path.join(str(tmpdir), "concepts.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def test_load_concepts_from_yaml(tmpdir):
    path = _write_yaml(tmpdir, MINIMAL_YAML)
    concepts = _load_concepts_from_yaml(path)
    assert len(concepts) == 1
    concept = concepts[0]
    assert concept.name == "skills"
    assert concept.patterns == (r"\bskill\b", r"\bcompetenc")
    assert concept.paths == {
        "direct": ("competenc", "skill"),
        "measurement": ("rating",),
        "summary": ("summary",),
    }
    assert concept.all_keywords() == ("competenc", "skill", "rating", "summary")


def test_concepts_for_query_matching(tmpdir, monkeypatch):
    path = _write_yaml(tmpdir, MINIMAL_YAML)
    monkeypatch.setenv("PANDASAI_CONCEPTS_YAML", path)
    concepts = concepts_for_query("what competencies does employee 1137 have?")
    assert [c.name for c in concepts] == ["skills"]
    assert concepts_for_query("What is the salary bill?") == []


def test_load_concepts_missing_file_raises():
    with pytest.raises(ValueError):
        _load_concepts_from_yaml("/nonexistent/concepts.yaml")


def test_load_concepts_empty_schema_raises(tmpdir):
    path = _write_yaml(tmpdir, "concepts: {}\n")
    with pytest.raises(ValueError):
        _load_concepts_from_yaml(path)


def test_extract_struct_parent_and_inner_fields():
    assert (
        extract_struct_parent("[Employee Master[Employee Name]]") == "Employee Master"
    )
    assert extract_struct_parent("Employee Name") is None
    assert extract_struct_parent("[FlatColumn]") is None
    assert inner_field_names("[Parent[A][B]]") == ["A", "B"]
    assert inner_field_names("Employee Name") == []


def test_collect_struct_groups_skips_flat_and_non_struct():
    groups = collect_struct_groups([_Renderer(SAMPLE_COLS)])
    assert "Employee Master" in groups
    assert "CV Employee Competencies" in groups
    # Flat column must NOT be treated as a struct group
    assert "Employee Name" not in groups


def test_missing_groups_and_is_group_selected():
    groups = collect_struct_groups([_Renderer(SAMPLE_COLS)])
    concept = Concept(
        name="skills",
        patterns=(r"\bskill\b",),
        paths={"direct": ("competenc", "skill", "summary")},
    )
    selected = [
        "[Employee Master[Employee Name]]",
        "[Employee Master[Employee Number]]",
        "[CV Employee Competencies[Technical Competency Name]]",
    ]
    assert is_group_selected(
        "CV Employee Competencies", groups["CV Employee Competencies"], selected
    )
    assert not is_group_selected(
        "CV Employee Summary", groups["CV Employee Summary"], selected
    )
    missing = missing_groups(concept, groups, selected)
    assert "CV Employee Summary" in missing
    assert "CV Employee Competencies" not in missing


def test_expected_groups_by_path_buckets():
    groups = collect_struct_groups([_Renderer(SAMPLE_COLS)])
    concept = Concept(
        name="skills",
        patterns=(r"\bskill\b",),
        paths={
            "direct": ("competenc", "skill"),
            "measurement": ("rating",),
            "evidence": (),
        },
    )
    by_path = expected_groups_by_path(concept, groups)
    assert "CV Employee Competencies" in by_path["direct"]
    assert "Employee Competencies Rating" in by_path["measurement"]
    # Empty keyword list is skipped entirely
    assert "evidence" not in by_path


def test_bundled_concepts_yaml_is_valid():
    """The shipped concepts.yaml must load and expose all expected concepts."""
    yaml_path = (
        Path(__file__).resolve().parents[3]
        / "pandasai"
        / "helpers"
        / "concepts.yaml"
    )
    assert yaml_path.exists(), f"bundled concepts.yaml not found at {yaml_path}"
    concepts = _load_concepts_from_yaml(str(yaml_path))
    names = {c.name for c in concepts}
    assert {
        "skills",
        "projects",
        "performance",
        "experience",
        "education",
        "leave",
    } <= names
    for concept in concepts:
        assert concept.patterns
        assert concept.paths