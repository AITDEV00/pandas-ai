import logging
from typing import Any, Optional, Tuple
from fastapi import HTTPException
from server.core.agent_store import agent_store

logger = logging.getLogger(__name__)

# Issue 10: Supported output types for API validation
SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "auto"}


def _validate_output_type(output_type: Optional[str]) -> Optional[str]:
    """Validate output_type against PandasAI's supported types.

    Returns the validated type, or None for auto/null.
    Raises HTTPException(400) for unsupported types.
    """
    if output_type is None:
        return None

    if output_type == "auto":
        return None  # "auto" = LLM chooses freely → normalize to None

    if output_type not in SUPPORTED_OUTPUT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported output_type: '{output_type}'. "
                f"Supported types are: 'string', 'number', 'dataframe', 'plot', 'auto'. "
                f"Hint: Use 'string' instead of 'text'."
            ),
        )

    return output_type


def _coerce_response_type(
    response_obj: Any, actual_type: str, requested_type: str
) -> Optional[Tuple[Any, str]]:
    """Attempt to coerce a response object from actual_type to requested_type.

    Args:
        response_obj: The response object (e.g., NumberResponse, StringResponse).
                      Has .value and .type attributes.
        actual_type: The response object's .type attribute (e.g., "number", "plot").
        requested_type: The output_type the client requested (e.g., "string", "plot").

    Returns (coerced_value, new_type) on success, or None if coercion fails.
    """
    raw_value = getattr(response_obj, 'value', response_obj)

    # string ← number: "10" instead of 10
    if requested_type == "string" and actual_type == "number":
        return (str(raw_value), "string")

    # string ← dataframe: use DataFrame string summary (truncated)
    if requested_type == "string" and actual_type == "dataframe":
        if hasattr(raw_value, 'head'):
            summary = (
                f"DataFrame ({len(raw_value)} rows × {len(raw_value.columns)} columns)\n"
                f"First 5 rows:\n{str(raw_value.head())}"
            )
            return (summary, "string")
        return (str(raw_value), "string")

    # number ← string: try to extract the number
    if requested_type == "number" and actual_type == "string":
        try:
            return (float(str(raw_value)), "number")
        except (ValueError, TypeError):
            return None

    # All other mismatches are nonsensical — can't coerce
    return None


def handle_chat_query(
    conversation_id: str,
    query: str,
    output_type: Optional[str] = None,
    message_history: Optional[int] = None,
    column_selection_enabled: Optional[bool] = None,
    column_selection_threshold: Optional[int] = None,
    column_values_budget_ratio: Optional[float] = None,
) -> dict:
    """Retrieves session state, queries the LLM, and formats the response object safely."""
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")

    # Apply message_history limit if provided
    if message_history is not None and message_history >= 0:
        agent.set_message_history(message_history)

    # --- Per-query config overrides (restored in finally block) ---
    _overrides = {}  # {attr_name: original_value}

    if column_selection_enabled is not None:
        _overrides["column_selection_enabled"] = agent._state.config.column_selection_enabled
        agent._state.config.column_selection_enabled = column_selection_enabled

    if column_selection_threshold is not None:
        _overrides["column_selection_threshold"] = agent._state.config.column_selection_threshold
        agent._state.config.column_selection_threshold = column_selection_threshold

    if column_values_budget_ratio is not None:
        _overrides["column_values_budget_ratio"] = agent._state.config.column_values_budget_ratio
        agent._state.config.column_values_budget_ratio = column_values_budget_ratio

    # Issue 10: Validate output_type at the API boundary
    validated_output_type = _validate_output_type(output_type)

    try:
        # Use follow_up() for subsequent turns to preserve multi-turn memory.
        # chat() clears memory (starts fresh), follow_up() preserves it.
        if agent._state.memory.count() > 0:
            response = agent.follow_up(query, output_type=validated_output_type)
        else:
            response = agent.chat(query, output_type=validated_output_type)

        # Extract the actual type from the response object (authoritative source)
        # Falls back to the requested type, then "auto"
        actual_type = getattr(response, 'type', None) or validated_output_type or "auto"

        # Issue 11: Normalize "chart" → "plot" for backward compatibility
        if actual_type == "chart":
            actual_type = "plot"

        # Issue 9 L3 + Issue 16: Attempt coercion if type mismatch
        if validated_output_type and actual_type != validated_output_type:
            coerced = _coerce_response_type(response, actual_type, validated_output_type)
            if coerced is not None:
                coerced_value, actual_type = coerced
                # Serialize the coerced value
                if actual_type == 'dataframe' and hasattr(coerced_value, 'to_dict'):
                    response_value = coerced_value.to_dict(orient='records')
                else:
                    response_value = str(coerced_value)
            else:
                # Coercion failed — return error response
                return {
                    "response": (
                        f"Unable to produce output_type '{validated_output_type}'. "
                        f"The query produced type '{actual_type}' which cannot be "
                        f"converted to '{validated_output_type}'."
                    ),
                    "type": "error",
                    "last_code_executed": getattr(agent, "last_code_executed", None),
                    "selected_columns": agent._state.last_selected_names,
                }
        else:
            # Serialize response value appropriately based on type
            if actual_type == 'dataframe' and hasattr(response, 'value') and hasattr(response.value, 'to_dict'):
                response_value = response.value.to_dict(orient='records')
            else:
                response_value = str(response) if response is not None else None

        return {
            "response": response_value,
            "type": actual_type,
            "last_code_executed": getattr(agent, "last_code_executed", None),
            "selected_columns": agent._state.last_selected_names,
        }
    except Exception as e:
        logger.error(f"Chat query failed for conversation {conversation_id}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Check server logs for details.")
    finally:
        # Always restore per-query config overrides
        for attr, original_value in _overrides.items():
            setattr(agent._state.config, attr, original_value)
