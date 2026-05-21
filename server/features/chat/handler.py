import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple
from fastapi import HTTPException
from server.core.agent_store import agent_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-conversation logging
# ---------------------------------------------------------------------------
# When CONVERSATION_LOG_DIR is set (e.g. in .env), every /chat response is
# appended to a Markdown file named after the conversation_id.  This gives
# a server-side audit trail without requiring any client-side changes.
#   CONVERSATION_LOG_DIR=/tmp/pandasai_conv_logs
# Each turn is a clearly separated section with full pipeline trace.
# ---------------------------------------------------------------------------

_CONV_LOG_DIR_ENV_KEY = "CONVERSATION_LOG_DIR"


def _log_conversation(conversation_id: str, payload: dict) -> None:
    """Append a chat response to a per-conversation Markdown log file.
    
    Reads CONVERSATION_LOG_DIR from env on every call (not at import time)
    so that hot-reload cannot leave a stale/undefined module-level variable.
    """
    log_dir_path = os.environ.get(_CONV_LOG_DIR_ENV_KEY, "")
    if not log_dir_path:
        return
    try:
        log_dir = Path(log_dir_path)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Write Markdown log (single file, both human + LLM readable)
        _write_readable_log(log_dir, conversation_id, payload)
    except Exception:
        # Logging must never break the request
        logger.debug("Failed to write conversation log", exc_info=True)


def _write_readable_log(log_dir: Path, conversation_id: str, payload: dict) -> None:
    """Append a Markdown-formatted log entry with clear section separators.

    Uses Markdown with heavy horizontal-rule separators (═══) and heading
    hierarchy so that both humans and LLMs can:
      - Quickly find each chat turn (separated by ═══ lines)
      - Trace every pipeline step in order
      - See all code attempts, errors, and retries
      - Understand column selection reasoning
      - Inspect SQL queries and their results
      - Debug with full variable values and error tracebacks
    """
    log_file = log_dir / f"{conversation_id}.md"
    ts = datetime.utcnow().isoformat() + "Z"

    with open(log_file, "a", encoding="utf-8") as f:
        # ── Turn separator ──
        f.write("\n═══════════════════════════════════════════════════════════════\n")
        f.write(f"# CHAT TURN — {ts}\n")
        f.write("═══════════════════════════════════════════════════════════════\n\n")

        # ── 1. INCOMING QUERY ──
        query = payload.get("query", "")
        f.write("## ▶ INCOMING QUERY\n\n")
        f.write(f"> {query}\n\n")

        # ── 2. OUTCOME ──
        f.write("## ◆ OUTCOME\n\n")
        if "error" in payload:
            f.write(f"**Status:** ❌ ERROR\n\n")
            f.write(f"**Error:** {payload['error']}\n\n")
            # Full error traceback if available
            pipeline = payload.get("pipeline", {})
            if pipeline.get("last_error_traceback"):
                f.write("<details>\n<summary>Full Error Traceback</summary>\n\n")
                f.write(f"```\n{pipeline['last_error_traceback']}\n```\n\n")
                f.write("</details>\n\n")
        else:
            result = payload.get("result", {})
            resp_type = result.get("type", "unknown")
            is_error = resp_type == "error"
            status_icon = "❌" if is_error else "✅"
            f.write(f"**Status:** {status_icon} {'ERROR' if is_error else 'SUCCESS'}\n\n")
            f.write(f"**Response Type:** `{resp_type}`\n\n")

            if result.get("selected_columns"):
                cols = result["selected_columns"]
                f.write(f"**Selected Columns** ({len(cols)}):\n\n")
                for col in cols:
                    f.write(f"- `{col}`\n")
                f.write("\n")

            # Response value
            resp = result.get("response", "")
            if resp:
                f.write("### Response Value\n\n")
                f.write(f"{resp}\n\n")

            # Final executed code
            if result.get("last_code_executed"):
                f.write("### Final Executed Code\n\n")
                f.write(f"```python\n{result['last_code_executed']}\n```\n\n")

        # ── 3. PIPELINE TRACE ──
        pipeline = payload.get("pipeline", {})
        if pipeline:
            f.write("───────────────────────────────────────────────────────────────\n")
            f.write("## 🔧 PIPELINE TRACE\n\n")

            # ── 3a. Config Snapshot ──
            config_snap = pipeline.get("config_snapshot", {})
            if config_snap:
                f.write("### Config Snapshot\n\n")
                f.write("| Setting | Value |\n")
                f.write("|---------|-------|\n")
                for key, val in config_snap.items():
                    f.write(f"| {key} | `{val}` |\n")
                f.write("\n")

            # ── 3b. Column Selection ──
            col_log = pipeline.get("column_selection_log", [])
            if col_log:
                f.write("### Step 1 — Column Selection\n\n")
                f.write("| Step | Detail |\n")
                f.write("|------|--------|\n")
                for entry in col_log:
                    step = entry.get("step", "")
                    detail = entry.get("detail", "")
                    # Truncate very long detail strings for table readability
                    detail_str = str(detail)
                    if len(detail_str) > 500:
                        detail_str = detail_str[:500] + "..."
                    f.write(f"| {step} | {detail_str} |\n")
                f.write("\n")

            # Column selection prompt
            col_sel_prompt = pipeline.get("column_selection_prompt", "")
            if col_sel_prompt:
                lines = str(col_sel_prompt).splitlines()
                f.write(f"#### Column Selection Prompt ({len(lines)} lines)\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{col_sel_prompt}\n```\n\n")
                f.write("</details>\n\n")

            # Column selection raw LLM response
            col_sel_raw = pipeline.get("column_selection_raw_llm_response", "")
            if col_sel_raw:
                f.write("#### Column Selection — Raw LLM Response\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{col_sel_raw}\n```\n\n")
                f.write("</details>\n\n")

            # Trimmed DataFrame info
            trimmed_info = pipeline.get("trimmed_df_info", [])
            if trimmed_info:
                f.write("#### Trimmed DataFrame Info\n\n")
                for info in trimmed_info:
                    idx = info.get("df_index", "?")
                    orig_cols = info.get("original_columns", [])
                    trim_cols = info.get("trimmed_columns", [])
                    orig_schema = info.get("original_schema_names", [])
                    trim_schema = info.get("trimmed_schema_names", [])
                    f.write(f"**DF[{idx}]:**\n\n")
                    f.write(f"- Original shape: `{info.get('original_shape')}`\n")
                    f.write(f"- Trimmed shape: `{info.get('trimmed_shape')}`\n")
                    f.write(f"- Original columns ({len(orig_cols)}): `{orig_cols}`\n")
                    f.write(f"- Trimmed columns ({len(trim_cols)}): `{trim_cols}`\n")
                    f.write(f"- Original schema ({len(orig_schema)}): `{orig_schema}`\n")
                    f.write(f"- Trimmed schema ({len(trim_schema)}): `{trim_schema}`\n\n")

            # ── 3c. Code Generation Attempts ──
            code_attempts = pipeline.get("code_attempts", [])
            if code_attempts:
                gen_attempts = [a for a in code_attempts if a.get("phase") == "generation"]
                exec_attempts = [a for a in code_attempts if a.get("phase") == "execution"]

                if gen_attempts:
                    f.write(f"### Step 2a — Code Generation ({len(gen_attempts)} attempt(s))\n\n")
                    for entry in gen_attempts:
                        attempt = entry.get("attempt", "?")
                        code = entry.get("code", "")
                        error = entry.get("error")
                        error_type = entry.get("error_type", "")
                        error_tb = entry.get("error_traceback", "")
                        icon = "✅" if error is None else "❌"
                        f.write(f"#### {icon} Generation Attempt {attempt}\n\n")
                        if error:
                            f.write(f"**Error Type:** `{error_type}`\n\n")
                            f.write(f"**Error:** {error}\n\n")
                            if error_tb:
                                f.write("<details>\n<summary>Full Traceback</summary>\n\n")
                                f.write(f"```\n{error_tb}\n```\n\n")
                                f.write("</details>\n\n")
                        if code:
                            f.write(f"```python\n{code}\n```\n\n")

                if exec_attempts:
                    f.write(f"### Step 2b — Code Execution ({len(exec_attempts)} attempt(s))\n\n")
                    for entry in exec_attempts:
                        attempt = entry.get("attempt", "?")
                        code = entry.get("code", "")
                        error = entry.get("error")
                        error_type = entry.get("error_type", "")
                        error_tb = entry.get("error_traceback", "")
                        icon = "✅" if error is None else "❌"
                        f.write(f"#### {icon} Execution Attempt {attempt}\n\n")
                        if error:
                            f.write(f"**Error Type:** `{error_type}`\n\n")
                            f.write(f"**Error:** {error}\n\n")
                            if error_tb:
                                f.write("<details>\n<summary>Full Traceback</summary>\n\n")
                                f.write(f"```\n{error_tb}\n```\n\n")
                                f.write("</details>\n\n")
                        if code:
                            f.write(f"```python\n{code}\n```\n\n")

            # ── 3d. Code Generation Raw LLM Response ──
            code_gen_raw = pipeline.get("code_generation_raw_llm_response", "")
            if code_gen_raw:
                f.write("### Code Generation — Raw LLM Response\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{code_gen_raw}\n```\n\n")
                f.write("</details>\n\n")

            # ── 3e. Raw Execution Result ──
            raw_exec_result = pipeline.get("raw_execution_result")
            if raw_exec_result is not None:
                f.write("### Raw Execution Result (before parsing)\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{raw_exec_result}\n```\n\n")
                f.write("</details>\n\n")

            # ── 3f. SQL Queries ──
            sql_queries = pipeline.get("sql_queries", [])
            if sql_queries:
                f.write(f"### SQL Queries Executed ({len(sql_queries)})\n\n")
                for i, sq in enumerate(sql_queries, 1):
                    f.write(f"#### Query {i}\n\n")
                    if sq.get("original_sql"):
                        f.write("**Original SQL:**\n\n")
                        f.write(f"```sql\n{sq['original_sql']}\n```\n\n")
                    if sq.get("final_sql"):
                        f.write("**Final SQL (after table/column substitution):**\n\n")
                        f.write(f"```sql\n{sq['final_sql']}\n```\n\n")
                    if sq.get("table_mapping"):
                        f.write(f"**Table Mapping:** `{sq['table_mapping']}`\n\n")
                    if sq.get("error"):
                        f.write(f"**❌ Error:** {sq['error']}\n\n")
                    else:
                        f.write(f"**Result Shape:** `{sq.get('result_shape')}`\n\n")
                        if sq.get("result_columns"):
                            f.write(f"**Result Columns:** `{sq['result_columns']}`\n\n")
                        if sq.get("result_preview"):
                            f.write("**Result Preview (first 5 rows):**\n\n")
                            f.write("<details>\n<summary>Click to expand</summary>\n\n")
                            f.write(f"```\n{sq['result_preview']}\n```\n\n")
                            f.write("</details>\n\n")

            # ── 3g. Internal Timeline ──
            logger_logs = pipeline.get("logger_logs", [])
            if logger_logs:
                f.write(f"### Internal Timeline ({len(logger_logs)} events)\n\n")
                f.write("| # | Elapsed | Level | Message |\n")
                f.write("|---|---------|-------|--------|\n")
                for i, log_entry in enumerate(logger_logs, 1):
                    level = log_entry.get("level", "INFO")
                    msg = log_entry.get("msg", "").replace("|", "\\|")
                    elapsed = log_entry.get("time", 0)
                    f.write(f"| {i} | +{elapsed:.2f}s | {level} | {msg} |\n")
                f.write("\n")

            # ── 3h. Prompt Sent to LLM (Step 2) ──
            prompt = pipeline.get("last_prompt_used", "")
            if prompt:
                lines = str(prompt).splitlines()
                f.write(f"### Prompt Sent to LLM — Step 2 ({len(lines)} lines)\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{prompt}\n```\n\n")
                f.write("</details>\n\n")

            # ── 3i. Conversation Memory ──
            memory = pipeline.get("memory", [])
            if memory:
                f.write(f"### Conversation Memory ({len(memory)} messages)\n\n")
                f.write("| Role | Content |\n")
                f.write("|------|---------|\n")
                for msg in memory:
                    role = "👤 User" if msg.get("is_user") else "🤖 Assistant"
                    text = msg.get("message", "").replace("|", "\\|")
                    if len(text) > 300:
                        text = text[:300] + "..."
                    f.write(f"| {role} | {text} |\n")
                f.write("\n")

            # ── 3j. Full Error Traceback (if any) ──
            full_tb = pipeline.get("last_error_traceback", "")
            if full_tb and "error" not in payload:
                # Only show here if not already shown in the OUTCOME error section
                f.write("### Full Error Traceback\n\n")
                f.write("<details>\n<summary>Click to expand</summary>\n\n")
                f.write(f"```\n{full_tb}\n```\n\n")
                f.write("</details>\n\n")

        # ── End of turn ──
        f.write("═══════════════════════════════════════════════════════════════\n")
        f.write("## ■ END OF TURN\n")
        f.write("═══════════════════════════════════════════════════════════════\n\n")

# Issue 10: Supported output types for API validation
SUPPORTED_OUTPUT_TYPES = {"string", "number", "dataframe", "plot", "evidence", "auto"}


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


def _extract_pipeline_log(agent) -> dict:
    """Extract the full pipeline trace from the agent's internal state.

    Returns a dict with:
      - logger_logs: all PandasAI logger messages (retries, column selection, etc.)
      - code_attempts: every generation/execution attempt with code + error
      - column_selection_log: step-by-step column selection details
      - last_prompt_used: the rendered prompt text sent to the LLM
      - memory: the conversation message history
      - column_selection_raw_llm_response: raw LLM response for Step 1
      - column_selection_prompt: prompt sent for Step 1
      - code_generation_raw_llm_response: raw LLM response for Step 2
      - sql_queries: SQL queries executed with results
      - last_error_traceback: full error traceback
      - config_snapshot: key config values at query time
      - trimmed_df_info: before/after column selection DataFrame info
      - raw_execution_result: result dict from code execution before parsing
    """
    state = agent._state
    pipeline = {}

    # 1. Logger logs — captures everything: retries, column selection, execution steps
    if state.logger and hasattr(state.logger, "_logs"):
        pipeline["logger_logs"] = [
            {"msg": log.msg, "level": log.level, "time": log.time}
            for log in state.logger._logs
        ]

    # 2. Code attempts — every generation/execution attempt with code + error
    if state.code_attempts:
        pipeline["code_attempts"] = state.code_attempts

    # 3. Column selection detail log
    if state.column_selection_log:
        pipeline["column_selection_log"] = state.column_selection_log

    # 4. Prompt text
    if state.last_prompt_used:
        pipeline["last_prompt_used"] = state.last_prompt_used

    # 5. Conversation memory
    if state.memory and hasattr(state.memory, "all"):
        pipeline["memory"] = state.memory.all()

    # 6. Column selection raw LLM response
    if state.column_selection_raw_llm_response:
        pipeline["column_selection_raw_llm_response"] = state.column_selection_raw_llm_response

    # 7. Column selection prompt
    if state.column_selection_prompt:
        pipeline["column_selection_prompt"] = state.column_selection_prompt

    # 8. Code generation raw LLM response (before code extraction)
    if state.code_generation_raw_llm_response:
        pipeline["code_generation_raw_llm_response"] = state.code_generation_raw_llm_response

    # 9. SQL queries executed
    if state.sql_queries:
        pipeline["sql_queries"] = state.sql_queries

    # 10. Full error traceback
    if state.last_error_traceback:
        pipeline["last_error_traceback"] = state.last_error_traceback

    # 11. Config snapshot
    if state.config_snapshot:
        pipeline["config_snapshot"] = state.config_snapshot

    # 12. Trimmed DataFrame info
    if state.trimmed_df_info:
        pipeline["trimmed_df_info"] = state.trimmed_df_info

    # 13. Raw execution result (before parsing)
    if state.raw_execution_result is not None:
        # Try to serialize; skip if it contains non-serializable objects
        try:
            import json
            json.dumps(state.raw_execution_result, default=str)
            pipeline["raw_execution_result"] = state.raw_execution_result
        except (TypeError, ValueError):
            pipeline["raw_execution_result"] = str(state.raw_execution_result)

    # 14. Strategy 4: Retrieval mode from Step 1 LLM classification
    if state.retrieval_mode:
        pipeline["retrieval_mode"] = state.retrieval_mode
        pipeline["retrieval_mode_reasoning"] = state.retrieval_mode_reasoning
        pipeline["retrieval_mode_source"] = state.retrieval_mode_source

    return pipeline


def handle_chat_query(
    conversation_id: str,
    query: str,
    output_type: Optional[str] = None,
    message_history: Optional[int] = None,
    column_selection_enabled: Optional[bool] = None,
    column_selection_threshold: Optional[int] = None,
    column_values_budget_ratio: Optional[float] = None,
    column_selection_temperature: Optional[float] = None,
    column_selection_top_p: Optional[float] = None,
    column_selection_top_k: Optional[int] = None,
    code_generation_temperature: Optional[float] = None,
    code_generation_top_p: Optional[float] = None,
    code_generation_top_k: Optional[int] = None,
    step1_only: Optional[bool] = None,
) -> dict:
    """Retrieves session state, queries the LLM, and formats the response object safely."""
    agent = agent_store.get_agent(conversation_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Conversation ID not found or expired.")

    # --- Per-query config overrides (restored in finally block) ---
    _overrides = {}  # {attr_name: original_value}

    # Apply message_history limit if provided
    # 0 = no history, -1 = all history, null = server default
    if message_history is not None:
        _overrides["memory_size"] = agent._state.memory.memory_size
        agent.set_message_history(message_history)

    if column_selection_enabled is not None:
        _overrides["column_selection_enabled"] = agent._state.config.column_selection_enabled
        agent._state.config.column_selection_enabled = column_selection_enabled

    if column_selection_threshold is not None:
        _overrides["column_selection_threshold"] = agent._state.config.column_selection_threshold
        agent._state.config.column_selection_threshold = column_selection_threshold

    if column_values_budget_ratio is not None:
        _overrides["column_values_budget_ratio"] = agent._state.config.column_values_budget_ratio
        agent._state.config.column_values_budget_ratio = column_values_budget_ratio

    # Per-query sampling param overrides
    if column_selection_temperature is not None:
        _overrides["column_selection_temperature"] = agent._state.config.column_selection_temperature
        agent._state.config.column_selection_temperature = column_selection_temperature

    if column_selection_top_p is not None:
        _overrides["column_selection_top_p"] = agent._state.config.column_selection_top_p
        agent._state.config.column_selection_top_p = column_selection_top_p

    if column_selection_top_k is not None:
        _overrides["column_selection_top_k"] = agent._state.config.column_selection_top_k
        agent._state.config.column_selection_top_k = column_selection_top_k

    if code_generation_temperature is not None:
        _overrides["code_generation_temperature"] = agent._state.config.code_generation_temperature
        agent._state.config.code_generation_temperature = code_generation_temperature

    if code_generation_top_p is not None:
        _overrides["code_generation_top_p"] = agent._state.config.code_generation_top_p
        agent._state.config.code_generation_top_p = code_generation_top_p

    if code_generation_top_k is not None:
        _overrides["code_generation_top_k"] = agent._state.config.code_generation_top_k
        agent._state.config.code_generation_top_k = code_generation_top_k

    # Step 1 only mode — skip code generation, return column selection results only
    if step1_only is not None and step1_only:
        agent._state.step1_only = True

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
                result = {
                    "response": (
                        f"Unable to produce output_type '{validated_output_type}'. "
                        f"The query produced type '{actual_type}' which cannot be "
                        f"converted to '{validated_output_type}'."
                    ),
                    "type": "error",
                    "last_code_executed": getattr(agent, "last_code_executed", None),
                    "selected_columns": agent._state.last_selected_names,
                    "retrieval_mode": agent._state.retrieval_mode,
                    "retrieval_mode_reasoning": agent._state.retrieval_mode_reasoning,
                    "retrieval_mode_source": agent._state.retrieval_mode_source,
                }
                _log_conversation(conversation_id, {"query": query, "result": result})
                return result
        else:
            # Serialize response value appropriately based on type
            if actual_type == 'dataframe' and hasattr(response, 'value') and hasattr(response.value, 'to_dict'):
                response_value = response.value.to_dict(orient='records')
            else:
                response_value = str(response) if response is not None else None

        result = {
            "response": response_value,
            "type": actual_type,
            "last_code_executed": getattr(agent, "last_code_executed", None),
            "selected_columns": agent._state.last_selected_names,
            "retrieval_mode": agent._state.retrieval_mode,
            "retrieval_mode_reasoning": agent._state.retrieval_mode_reasoning,
            "retrieval_mode_source": agent._state.retrieval_mode_source,
        }
        # Include pipeline trace when step1_only mode is active
        if step1_only:
            result["pipeline"] = _extract_pipeline_log(agent)
        _log_conversation(conversation_id, {
            "query": query,
            "result": result,
            "pipeline": _extract_pipeline_log(agent),
        })
        return result
    except Exception as e:
        logger.error(f"Chat query failed for conversation {conversation_id}", exc_info=True)
        _log_conversation(conversation_id, {
            "query": query,
            "error": str(e),
            "pipeline": _extract_pipeline_log(agent),
        })
        raise HTTPException(status_code=500, detail="Internal server error. Check server logs for details.")
    finally:
        # Always restore step1_only flag
        agent._state.step1_only = False
        # Always restore per-query config overrides
        for attr, original_value in _overrides.items():
            if attr == "memory_size":
                agent._state.memory.memory_size = original_value
            else:
                setattr(agent._state.config, attr, original_value)
