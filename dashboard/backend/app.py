"""FastAPI backend for the analysis dashboard."""

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import (
    init_db,
    get_all_runs,
    get_run,
    get_steps_for_run,
    get_step_detail,
    get_failures_for_run,
    get_web_searches_for_run,
    get_classification_summary,
    get_db,
)
from .ingest import ingest_reports

app = FastAPI(title="Orchestrator Analysis Dashboard", version="1.0.0")

# Enable CORS for all origins (local tool)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    init_db()


@app.get("/api/runs")
async def list_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    has_architectural: Optional[bool] = Query(None, description="Filter runs with architectural issues"),
    build_phase: Optional[str] = Query(None, description="Filter by build phase"),
    error_category: Optional[str] = Query(None, description="Filter by error category"),
):
    """
    Get all runs with classification summaries.
    Supports filtering by status, architectural issues, build_phase, and error_category.
    """
    runs = get_all_runs()

    # Add classification summary to each run
    for run in runs:
        run["classifications"] = get_classification_summary(run["run_id"])

    # Apply filters
    if status:
        runs = [r for r in runs if r.get("status") == status]

    if has_architectural is not None:
        if has_architectural:
            runs = [r for r in runs if r["classifications"].get("architectural", 0) > 0]
        else:
            runs = [r for r in runs if r["classifications"].get("architectural", 0) == 0]

    if build_phase:
        # Filter runs that have steps in the specified build_phase
        filtered_runs = []
        for run in runs:
            steps = get_steps_for_run(run["run_id"])
            if any(s.get("build_phase") == build_phase for s in steps):
                filtered_runs.append(run)
        runs = filtered_runs

    if error_category:
        # Filter runs that have failures with the specified category
        filtered_runs = []
        for run in runs:
            failures = get_failures_for_run(run["run_id"])
            if any(f.get("category") == error_category for f in failures):
                filtered_runs.append(run)
        runs = filtered_runs

    # Sort by generated_at descending (already done in get_all_runs by ingested_at)
    runs.sort(key=lambda r: r.get("generated_at") or "", reverse=True)

    return runs


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    """Get full run detail including steps, failures, web searches, and classification summary."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return {
        "run": run,
        "steps": get_steps_for_run(run_id),
        "failures": get_failures_for_run(run_id),
        "web_searches": get_web_searches_for_run(run_id),
        "classifications": get_classification_summary(run_id),
    }


@app.get("/api/runs/{run_id}/steps")
async def get_run_steps(run_id: str):
    """Get all steps for a run with classification data."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return get_steps_for_run(run_id)


@app.get("/api/runs/{run_id}/steps/{step_number}")
async def get_step_details(run_id: str, step_number: int):
    """Get step detail including failures and web searches for this step."""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    step = get_step_detail(run_id, step_number)
    if not step:
        raise HTTPException(status_code=404, detail=f"Step {step_number} not found in run {run_id}")

    # Get failures for this step
    all_failures = get_failures_for_run(run_id)
    step_failures = [f for f in all_failures if f.get("step_number") == step_number]

    # Get web searches for this step (by step_id pattern)
    all_searches = get_web_searches_for_run(run_id)
    step_id = f"{run_id}_{step_number}"
    step_searches = [s for s in all_searches if s.get("step_id") == step_id]

    return {
        "step": step,
        "failures": step_failures,
        "web_searches": step_searches,
    }


@app.get("/api/stats")
async def get_stats():
    """Get global statistics across all runs and steps."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Run counts
        cursor.execute("SELECT COUNT(*) FROM runs")
        total_runs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM runs WHERE status = 'success'")
        completed_runs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM runs WHERE status = 'failed'")
        failed_runs = cursor.fetchone()[0]

        # Step and failure counts
        cursor.execute("SELECT COUNT(*) FROM steps")
        total_steps = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM failures")
        total_failures = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(total_retries), 0) FROM runs")
        total_retries = cursor.fetchone()[0]

        # Average success rate
        cursor.execute("SELECT AVG(success_rate) FROM runs WHERE success_rate IS NOT NULL")
        avg_success_rate = cursor.fetchone()[0] or 0

        # Classification counts across all steps
        cursor.execute("""
            SELECT
                COALESCE(classification, 'pending') as classification,
                COUNT(*) as count
            FROM steps
            GROUP BY COALESCE(classification, 'pending')
        """)
        classification_rows = cursor.fetchall()

        classification_counts = {
            "architectural": 0,
            "implementation": 0,
            "clean_pass": 0,
            "ambiguous": 0,
            "pending": 0,
        }
        for row in classification_rows:
            cls = (row[0] or "pending").lower()
            if cls in classification_counts:
                classification_counts[cls] = row[1]
            elif cls == "":
                classification_counts["pending"] += row[1]

        # Top error categories
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM failures
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """)
        top_error_categories = [
            {"category": row[0], "count": row[1]}
            for row in cursor.fetchall()
        ]

        # Top failure phases
        cursor.execute("""
            SELECT build_phase, COUNT(*) as count
            FROM failures
            WHERE build_phase IS NOT NULL AND build_phase != ''
            GROUP BY build_phase
            ORDER BY count DESC
        """)
        top_failure_phases = [
            {"build_phase": row[0], "count": row[1]}
            for row in cursor.fetchall()
        ]

    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "total_steps": total_steps,
        "total_failures": total_failures,
        "total_retries": total_retries,
        "avg_success_rate": round(avg_success_rate, 4) if avg_success_rate else 0,
        "classification_counts": classification_counts,
        "top_error_categories": top_error_categories,
        "top_failure_phases": top_failure_phases,
    }


@app.post("/api/ingest")
async def trigger_ingest(force: bool = Query(False, description="Force re-ingestion of all reports")):
    """Trigger report ingestion."""
    result = ingest_reports(force=force)
    return result


@app.post("/api/classify")
async def trigger_classify(
    run_id: Optional[str] = Query(None, description="Specific run ID to classify"),
    force: bool = Query(False, description="Force reclassification of already classified steps")
):
    """Trigger AI classification of steps."""
    from .classifier import classify_run, classify_all_runs, reclassify_run

    if run_id:
        if force:
            result = reclassify_run(run_id)
        else:
            result = classify_run(run_id)
        return {"run_id": run_id, **result}
    else:
        result = classify_all_runs()
        return result


@app.get("/api/patterns")
async def get_patterns():
    """Get cross-run pattern analysis."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Error Heatmap: category × build_phase with counts and classification splits
        cursor.execute("""
            SELECT
                f.category,
                f.build_phase,
                COUNT(*) as count,
                SUM(CASE WHEN s.classification = 'architectural' THEN 1 ELSE 0 END) as architectural,
                SUM(CASE WHEN s.classification = 'implementation' THEN 1 ELSE 0 END) as implementation
            FROM failures f
            LEFT JOIN steps s ON f.run_id = s.run_id AND f.step_number = s.step_number
            WHERE f.category IS NOT NULL AND f.category != ''
              AND f.build_phase IS NOT NULL AND f.build_phase != ''
            GROUP BY f.category, f.build_phase
            ORDER BY count DESC
        """)
        error_heatmap = [
            {
                "category": row[0],
                "build_phase": row[1],
                "count": row[2],
                "architectural": row[3] or 0,
                "implementation": row[4] or 0
            }
            for row in cursor.fetchall()
        ]

        # Top Patterns: most common failure patterns with example run IDs
        cursor.execute("""
            SELECT
                f.category,
                f.build_phase,
                COUNT(*) as total_occurrences,
                SUM(CASE WHEN s.classification = 'architectural' THEN 1 ELSE 0 END) as architectural_count,
                SUM(CASE WHEN s.classification = 'implementation' THEN 1 ELSE 0 END) as implementation_count,
                GROUP_CONCAT(DISTINCT f.run_id) as run_ids
            FROM failures f
            LEFT JOIN steps s ON f.run_id = s.run_id AND f.step_number = s.step_number
            WHERE f.category IS NOT NULL AND f.category != ''
              AND f.build_phase IS NOT NULL AND f.build_phase != ''
            GROUP BY f.category, f.build_phase
            ORDER BY total_occurrences DESC
            LIMIT 20
        """)
        top_patterns = []
        for row in cursor.fetchall():
            run_ids = row[5].split(',') if row[5] else []
            top_patterns.append({
                "pattern": f"{row[0]} in {row[1]}",
                "category": row[0],
                "build_phase": row[1],
                "total_occurrences": row[2],
                "architectural_count": row[3] or 0,
                "implementation_count": row[4] or 0,
                "example_run_ids": run_ids[:5]  # Limit to 5 examples
            })

        # Self-Correction: per error category, how often do retried steps succeed
        cursor.execute("""
            SELECT
                f.category,
                COUNT(DISTINCT s.id) as total,
                SUM(CASE
                    WHEN s.retries > 0 AND UPPER(s.final_verdict) IN ('PROCEED', 'PASS')
                    THEN 1 ELSE 0
                END) as self_corrected,
                SUM(CASE
                    WHEN s.retries > 0 AND UPPER(s.final_verdict) IN ('FAIL', 'SKIP')
                    THEN 1 ELSE 0
                END) as failed
            FROM failures f
            JOIN steps s ON f.run_id = s.run_id AND f.step_number = s.step_number
            WHERE f.category IS NOT NULL AND f.category != ''
              AND s.retries > 0
            GROUP BY f.category
            ORDER BY total DESC
        """)
        self_correction = []
        for row in cursor.fetchall():
            total = row[1] or 0
            self_corrected = row[2] or 0
            failed = row[3] or 0
            rate = self_corrected / total if total > 0 else 0
            self_correction.append({
                "category": row[0],
                "total": total,
                "self_corrected": self_corrected,
                "failed": failed,
                "rate": round(rate, 3)
            })

        # Tool Comparison: compare tool configurations across runs
        cursor.execute("""
            SELECT
                planner || '/' || implementer || '/' || verifier as tool_config,
                COUNT(*) as run_count,
                AVG(success_rate) as avg_success_rate,
                SUM(total_retries) as total_retries
            FROM runs
            WHERE planner IS NOT NULL
            GROUP BY planner, implementer, verifier
            ORDER BY run_count DESC
        """)
        tool_configs = cursor.fetchall()

        tool_comparison = []
        for row in tool_configs:
            tool_config = row[0]
            # Get classification counts for runs with this tool config
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN s.classification = 'architectural' THEN 1 ELSE 0 END) as architectural_count,
                    SUM(CASE WHEN s.classification = 'implementation' THEN 1 ELSE 0 END) as implementation_count
                FROM steps s
                JOIN runs r ON s.run_id = r.run_id
                WHERE r.planner || '/' || r.implementer || '/' || r.verifier = ?
            """, (tool_config,))
            cls_row = cursor.fetchone()

            tool_comparison.append({
                "tool_config": tool_config,
                "run_count": row[1],
                "avg_success_rate": round(row[2], 4) if row[2] else 0,
                "total_retries": row[3] or 0,
                "architectural_count": cls_row[0] or 0 if cls_row else 0,
                "implementation_count": cls_row[1] or 0 if cls_row else 0
            })

    return {
        "error_heatmap": error_heatmap,
        "top_patterns": top_patterns,
        "self_correction": self_correction,
        "tool_comparison": tool_comparison
    }


# Mount static files AFTER all API routes are defined
# Only mount production build (dist folder), not the dev source
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists() and any(frontend_dist.iterdir()):
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
