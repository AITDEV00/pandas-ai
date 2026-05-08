"""Auto-fill missing column descriptions using LLM at registration time.

After enrichment, check if any schema column (including struct inner fields)
lacks a description. If so, send the full column list with unique sample values
to the LLM in a single call and ask it to generate descriptions for only those
that are missing. The response is validated against a Pydantic schema of
``{column_name: description}`` key-value pairs.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator
from pandasai.data_loader.semantic_layer_schema import Column

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic model for validating the LLM response
# ---------------------------------------------------------------------------

class ColumnDescriptions(BaseModel):
    """Structured response from the LLM: a list of column-name → description pairs."""

    descriptions: Dict[str, str]

    @field_validator("descriptions")
    @classmethod
    def truncate_long_descriptions(cls, v: Dict[str, str]) -> Dict[str, str]:
        return {k: (d[:197] + "..." if len(d) > 200 else d) for k, d in v.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fill_missing_descriptions(df, llm) -> None:
    """Use LLM to fill missing column descriptions in the schema.

    After enrichment, scans **all** schema columns (including struct inner
    fields).  If any lack a description, sends a single LLM call with the
    full column list and unique sample values, asking the LLM to generate
    descriptions only for those that are missing.

    The LLM response is validated against a Pydantic schema and then applied
    back to the schema columns in-place.

    Args:
        df: PandasAI DataFrame with a ``schema`` attribute.
        llm: A PandasAI LLM instance (e.g. LiteLLM) with a ``call()`` method.
    """
    if not df.schema or not df.schema.columns:
        return

    # --- 1. Build a flat list of all columns needing descriptions ---
    # For flat columns: key = column name
    # For struct inner fields: key = "parent_name.inner_field_name"
    missing_keys: List[str] = []
    for col in df.schema.columns:
        if not col.description:
            missing_keys.append(col.name)
        if col.semantic_type == "struct" and isinstance(col.samples, dict):
            for field_name, field_info in col.samples.items():
                if isinstance(field_info, dict) and not field_info.get("description"):
                    missing_keys.append(f"{col.name}.{field_name}")

    if not missing_keys:
        logger.info("Auto-fill: all columns already have descriptions — skipping")
        return

    logger.info(
        "Auto-fill: %d columns/fields need descriptions out of %d schema columns",
        len(missing_keys),
        len(df.schema.columns),
    )

    # --- 2. Build the prompt context ---
    from pandasai.core.prompts.auto_fill_descriptions import (
        AutoFillDescriptionsPrompt,
    )
    from pandasai.agent.state import AgentState
    from pandasai.helpers.memory import Memory

    state = AgentState()
    state.memory = Memory(memory_size=1, agent_description="You are a data catalog assistant.")
    if hasattr(df, "config") and df.config is not None:
        state.config = df.config
    else:
        from pandasai.config import ConfigManager
        state.config = ConfigManager.get()

    sample_rows = _build_sample_rows(df, max_rows=5)
    column_details = _build_column_details(df.schema.columns)

    prompt = AutoFillDescriptionsPrompt(
        context=state,
        columns=column_details,
        missing_keys=missing_keys,
        sample_rows=sample_rows,
        table_name=df.schema.name or "data",
    )

    # --- 3. Call the LLM ---
    try:
        response = llm.call(prompt, state)
        logger.info("Auto-fill LLM response (first 500 chars): %s", response[:500] if response else "<empty>")
    except Exception as e:
        logger.warning("Auto-fill LLM call failed: %s", e, exc_info=True)
        return

    # --- 4. Parse & validate with Pydantic ---
    descriptions = _parse_and_validate(response)
    if not descriptions:
        return

    # --- 5. Apply descriptions back to schema ---
    filled_top = 0
    filled_inner = 0

    for col in df.schema.columns:
        # Top-level column
        if col.name in descriptions and not col.description:
            col.description = descriptions[col.name]
            filled_top += 1
            logger.info("  ✓ %s: %s", col.name, col.description)

        # Struct inner fields
        if col.semantic_type == "struct" and isinstance(col.samples, dict):
            for field_name, field_info in col.samples.items():
                if isinstance(field_info, dict) and not field_info.get("description"):
                    key = f"{col.name}.{field_name}"
                    if key in descriptions:
                        field_info["description"] = descriptions[key]
                        filled_inner += 1
                        logger.info("  ✓ %s: %s", key, descriptions[key])

    logger.info("Auto-filled %d top-level + %d inner field descriptions", filled_top, filled_inner)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_sample_rows(df, max_rows: int = 5) -> str:
    """Build a CSV snippet of the first few rows for the prompt."""
    try:
        head = df.head(n=max_rows)

        def _truncate(val):
            if isinstance(val, (dict, list)):
                s = json.dumps(val, ensure_ascii=False)
                return s[:100] + "..." if len(s) > 100 else s
            if isinstance(val, str) and len(val) > 100:
                return val[:97] + "..."
            return val

        truncated = head.apply(lambda row: row.apply(_truncate), axis=1)
        return truncated.to_csv(index=False)
    except Exception:
        return ""


def _build_column_details(columns) -> List[Dict[str, Any]]:
    """Build a flat list of column detail dicts for the prompt.

    For struct columns, inner fields are emitted as separate entries with
    key ``"parent_name.inner_field_name"`` so the LLM uses the exact key
    we need for mapping back.
    """
    details = []
    for col in columns:
        if col.semantic_type == "struct" and isinstance(col.samples, dict):
            # Emit each inner field as its own entry
            for field_name, field_info in col.samples.items():
                if isinstance(field_info, dict):
                    entry = {
                        "name": f"{col.name}.{field_name}",
                        "type": field_info.get("type", "unknown"),
                    }
                    if field_info.get("description"):
                        entry["description"] = field_info["description"]
                    if field_info.get("samples"):
                        entry["samples"] = _trim_samples(field_info["samples"], max_items=20)
                    details.append(entry)
        else:
            entry: Dict[str, Any] = {
                "name": col.name,
                "type": col.type or "unknown",
            }
            if col.description:
                entry["description"] = col.description
            if col.samples is not None:
                entry["samples"] = _trim_samples(col.samples, max_items=20)
            details.append(entry)
    return details


def _trim_samples(samples: Any, max_items: int = 20) -> Any:
    """Trim sample values to avoid exceeding prompt length."""
    if isinstance(samples, list):
        return samples[:max_items] if len(samples) > max_items else samples

    if isinstance(samples, dict):
        # Struct vocabulary — trim inner column samples
        is_struct = any(isinstance(v, dict) and "type" in v for v in samples.values())
        if is_struct:
            trimmed = {}
            for inner_name, inner_data in samples.items():
                if isinstance(inner_data, dict):
                    inner_trimmed = dict(inner_data)
                    inner_samples = inner_trimmed.get("samples")
                    if isinstance(inner_samples, list) and len(inner_samples) > max_items:
                        inner_trimmed["samples"] = inner_samples[:max_items]
                    trimmed[inner_name] = inner_trimmed
                else:
                    trimmed[inner_name] = inner_data
            return trimmed
        # Numeric/datetime range dict — already compact
        return samples

    return samples


def _parse_and_validate(response: str) -> Dict[str, str]:
    """Parse the LLM response and validate with Pydantic.

    Returns a validated ``{column_name: description}`` dict, or empty dict
    on failure.
    """
    if not response or not response.strip():
        logger.warning("Auto-fill: empty LLM response")
        return {}

    # Strip markdown code fences (common with Qwen models)
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()

    # Try direct JSON parse
    raw = None
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract JSON block from response text
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                raw = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    if raw is None:
        logger.warning("Auto-fill: could not parse JSON from LLM response (first 200 chars): %s", response[:200])
        return {}

    # Normalise: accept {"descriptions": {...}} or bare {...}
    if isinstance(raw, dict) and "descriptions" in raw:
        raw = raw["descriptions"]

    if not isinstance(raw, dict):
        logger.warning("Auto-fill: LLM response is not a dict — got %s", type(raw).__name__)
        return {}

    # Validate with Pydantic
    try:
        validated = ColumnDescriptions(descriptions=raw)
        return validated.descriptions
    except Exception as e:
        logger.warning("Auto-fill: Pydantic validation failed: %s", e)
        # Fall back to returning the raw dict (best-effort)
        if all(isinstance(v, str) for v in raw.values()):
            return {k: (v[:197] + "..." if len(v) > 200 else v) for k, v in raw.items()}
        return {}
