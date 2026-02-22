"""Report ingestion system for the analysis dashboard."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .db import get_db, run_exists

# Reports directory relative to project root
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"


def get_raw_steps_for_step_number(raw_data: dict, step_number: int) -> list[dict]:
    """
    Extract all raw_data.steps entries for a given step_number.

    Args:
        raw_data: The raw_data section from the report
        step_number: The step number to filter by

    Returns:
        List of raw step dicts matching the step_number
    """
    steps = raw_data.get("steps", [])
    return [s for s in steps if s.get("step") == step_number]


def _delete_run_data(conn: sqlite3.Connection, run_id: str) -> None:
    """Delete all data for a given run_id from all tables."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM web_searches WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM failures WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))


def _extract_phase_from_raw_steps(raw_steps: list[dict]) -> Optional[str]:
    """Extract phase information from raw steps."""
    if not raw_steps:
        return None

    phases = [s.get("phase") for s in raw_steps if s.get("phase")]
    if not phases:
        return None

    # If all phases are the same, return that; otherwise join unique ones
    unique_phases = list(dict.fromkeys(phases))  # Preserve order, remove duplicates
    if len(unique_phases) == 1:
        return unique_phases[0]
    return ",".join(unique_phases)


def _extract_tool_from_raw_steps(raw_steps: list[dict]) -> Optional[str]:
    """Extract tool information from raw steps."""
    if not raw_steps:
        return None

    tools = [s.get("tool") for s in raw_steps if s.get("tool")]
    if not tools:
        return None

    # Return the most common tool, or the first one if tied
    from collections import Counter
    tool_counts = Counter(tools)
    return tool_counts.most_common(1)[0][0] if tool_counts else None


def _get_failures_for_step(failures_details: list[dict], step_number: int) -> list[dict]:
    """Get all failure details for a specific step number."""
    return [f for f in failures_details if f.get("step") == step_number]


def _ingest_single_report(conn: sqlite3.Connection, report_path: Path) -> str:
    """
    Ingest a single report file.

    Returns:
        The run_id of the ingested report

    Raises:
        Exception if the report is malformed
    """
    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    run_id = data["run_id"]
    cursor = conn.cursor()

    # Extract summary data
    summary = data.get("summary", {})
    tools_config = data.get("tools_config", {})
    supabase_specific = data.get("supabase_specific", {})
    token_usage = data.get("token_usage", {})
    raw_data = data.get("raw_data", {})

    # Current timestamp for ingestion
    ingested_at = datetime.now(timezone.utc).isoformat()

    # Insert into runs table
    cursor.execute("""
        INSERT INTO runs (
            run_id, generated_at, prompt, status, duration_minutes,
            total_steps, passed_steps, failed_steps, total_retries,
            replan_checkpoints, replans_triggered, success_rate,
            planner, implementer, verifier, models_used,
            rls_issues, migration_issues, edge_function_issues, auth_issues,
            total_input_tokens, total_output_tokens, total_cache_read_tokens,
            total_cache_creation_tokens, total_cost_usd,
            ingested_at, classified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        data.get("generated_at"),
        summary.get("prompt"),
        summary.get("status"),
        summary.get("duration_minutes"),
        summary.get("total_steps"),
        summary.get("passed_steps"),
        summary.get("failed_steps"),
        summary.get("total_retries"),
        summary.get("replan_checkpoints"),
        summary.get("replans_triggered"),
        summary.get("success_rate"),
        tools_config.get("planner"),
        tools_config.get("implementer"),
        tools_config.get("verifier"),
        json.dumps(tools_config.get("models_used")) if tools_config.get("models_used") else None,
        supabase_specific.get("rls_issues", 0),
        supabase_specific.get("migration_issues", 0),
        supabase_specific.get("edge_function_issues", 0),
        supabase_specific.get("auth_issues", 0),
        token_usage.get("total_input_tokens", 0),
        token_usage.get("total_output_tokens", 0),
        token_usage.get("total_cache_read_tokens", 0),
        token_usage.get("total_cache_creation_tokens", 0),
        token_usage.get("total_cost_usd", 0),
        ingested_at,
        None  # classified_at
    ))

    # Process step_outcomes
    step_outcomes = data.get("step_outcomes", [])
    failures_section = data.get("failures", {})
    failures_details = failures_section.get("details", [])

    for step_outcome in step_outcomes:
        step_number = step_outcome.get("step")
        step_id = f"{run_id}_{step_number}"

        # Get raw steps for this step number
        raw_steps = get_raw_steps_for_step_number(raw_data, step_number)

        # Extract phase and tool from raw steps
        phase = _extract_phase_from_raw_steps(raw_steps)
        tool = _extract_tool_from_raw_steps(raw_steps)

        # Get failures for this step
        step_failures = _get_failures_for_step(failures_details, step_number)

        # Extract error categories
        error_categories = list(set(f.get("category") for f in step_failures if f.get("category")))
        error_categories_json = json.dumps(error_categories) if error_categories else None

        # Build errors summary (truncate to 1000 chars)
        error_messages = [f.get("error", "") for f in step_failures if f.get("error")]
        errors_summary = " | ".join(error_messages)[:1000] if error_messages else None

        # Resolution actions
        resolution_actions = step_outcome.get("resolution_actions")
        resolution_actions_json = json.dumps(resolution_actions) if resolution_actions else None

        cursor.execute("""
            INSERT INTO steps (
                id, run_id, step_number, build_phase, phase, tool,
                final_verdict, attempts, retries, duration_seconds,
                resolution_actions, error_categories, errors_summary,
                classification, classification_confidence,
                classification_reasoning, classification_evidence,
                approach_changed, same_file_repeated, error_category_stable,
                input_tokens, output_tokens, cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            step_id,
            run_id,
            step_number,
            step_outcome.get("build_phase"),
            phase,
            tool,
            step_outcome.get("final_verdict"),
            step_outcome.get("attempts"),
            step_outcome.get("retries"),
            step_outcome.get("duration_seconds"),
            resolution_actions_json,
            error_categories_json,
            errors_summary,
            None,  # classification
            None,  # classification_confidence
            None,  # classification_reasoning
            None,  # classification_evidence
            None,  # approach_changed
            None,  # same_file_repeated
            None,  # error_category_stable
            step_outcome.get("input_tokens", 0),
            step_outcome.get("output_tokens", 0),
            step_outcome.get("cost_usd", 0)
        ))

    # Insert failures
    for failure in failures_details:
        cursor.execute("""
            INSERT INTO failures (
                run_id, step_number, build_phase, phase, category, error, exit_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            failure.get("step"),
            failure.get("build_phase"),
            failure.get("phase"),
            failure.get("category"),
            failure.get("error"),
            failure.get("exit_code")
        ))

    # Insert web searches
    web_searches = data.get("web_searches", [])
    for ws in web_searches:
        cursor.execute("""
            INSERT INTO web_searches (
                run_id, step_id, query, count, timestamp
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            run_id,
            ws.get("step_id"),
            ws.get("query"),
            ws.get("count"),
            ws.get("timestamp")
        ))

    return run_id


def ingest_reports(force: bool = False) -> dict[str, int]:
    """
    Ingest all *_full.json reports from the reports directory.

    Args:
        force: If True, delete existing data and re-ingest.
               If False, skip reports that are already in the DB.

    Returns:
        Dict with counts: {"ingested": N, "skipped": N, "errors": N}
    """
    result = {"ingested": 0, "skipped": 0, "errors": 0}

    # Check if reports directory exists
    if not REPORTS_DIR.exists():
        print(f"Reports directory not found: {REPORTS_DIR}")
        return result

    # Find all *_full.json files
    report_files = list(REPORTS_DIR.glob("*_full.json"))

    if not report_files:
        print(f"No *_full.json files found in {REPORTS_DIR}")
        return result

    print(f"Found {len(report_files)} report file(s)")

    for report_path in report_files:
        try:
            # First, peek at the run_id without fully parsing
            with open(report_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            run_id = data.get("run_id")
            if not run_id:
                print(f"Warning: No run_id in {report_path.name}, skipping")
                result["errors"] += 1
                continue

            # Check if already exists
            if not force and run_exists(run_id):
                print(f"Skipping {run_id} (already exists)")
                result["skipped"] += 1
                continue

            # Ingest the report
            with get_db() as conn:
                if force and run_exists(run_id):
                    print(f"Deleting existing data for {run_id}")
                    _delete_run_data(conn, run_id)

                _ingest_single_report(conn, report_path)
                conn.commit()

            print(f"Ingested {run_id}")
            result["ingested"] += 1

        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in {report_path.name}: {e}")
            result["errors"] += 1
        except KeyError as e:
            print(f"Warning: Missing required field in {report_path.name}: {e}")
            result["errors"] += 1
        except Exception as e:
            print(f"Warning: Error processing {report_path.name}: {e}")
            result["errors"] += 1

    return result
