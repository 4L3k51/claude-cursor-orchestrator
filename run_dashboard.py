#!/usr/bin/env python3
"""Orchestrator Analysis Dashboard"""
import sys
import os
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BANNER = """
╔═══════════════════════════════════════════════════════════╗
║           Orchestrator Analysis Dashboard                 ║
╚═══════════════════════════════════════════════════════════╝
"""


def main():
    if len(sys.argv) < 2:
        print("Orchestrator Analysis Dashboard")
        print()
        print("Usage:")
        print("  python run_dashboard.py serve           # Start dashboard server")
        print("  python run_dashboard.py serve --dev     # Start with Vite dev server")
        print("  python run_dashboard.py ingest          # Ingest new reports")
        print("  python run_dashboard.py ingest --force  # Re-ingest all reports")
        print("  python run_dashboard.py classify        # Run AI classification on all")
        print("  python run_dashboard.py classify <run_id>        # Classify specific run")
        print("  python run_dashboard.py classify <run_id> --force # Reclassify run")
        sys.exit(1)

    command = sys.argv[1]

    if command == "serve":
        from dashboard.backend.db import init_db, get_all_runs
        from dashboard.backend.ingest import ingest_reports
        import uvicorn

        dev_mode = "--dev" in sys.argv
        project_root = Path(__file__).parent
        dist_path = project_root / "dashboard" / "frontend" / "dist"

        print(BANNER)

        # Initialize database
        print("Initializing database...")
        init_db()

        # Auto-ingest reports
        print("Auto-ingesting reports...")
        result = ingest_reports(force=False)
        print(f"  {result['ingested']} new, {result['skipped']} skipped, {result['errors']} errors")

        # Get stats
        runs = get_all_runs()
        print(f"  {len(runs)} total runs in database")
        print()

        # Check for production build
        if not dev_mode and not dist_path.exists():
            print("Warning: No production build found at dashboard/frontend/dist/")
            print("         Run 'cd dashboard/frontend && npm run build' to create it")
            print("         Or use 'python run_dashboard.py serve --dev' for development")
            print()

        if dev_mode:
            print("Development Mode")
            print("─" * 50)
            print("API Server:  http://localhost:8000")
            print("API Docs:    http://localhost:8000/docs")
            print()
            print("Start the Vite dev server separately:")
            print("  cd dashboard/frontend && npm run dev")
            print()
            print("Then open http://localhost:5173 in your browser")
        else:
            print("Production Mode")
            print("─" * 50)
            print("Dashboard:   http://localhost:8000")
            print("API Docs:    http://localhost:8000/docs")

        print()
        print("Press Ctrl+C to stop")
        print()

        uvicorn.run(
            "dashboard.backend.app:app",
            host="0.0.0.0",
            port=8000,
            reload=dev_mode,
            log_level="info" if dev_mode else "warning"
        )

    elif command == "ingest":
        from dashboard.backend.db import init_db
        from dashboard.backend.ingest import ingest_reports
        init_db()
        force = "--force" in sys.argv
        print(f"Ingesting reports{' (force)' if force else ''}...")
        result = ingest_reports(force=force)
        print(f"Done: {result['ingested']} ingested, {result['skipped']} skipped, {result['errors']} errors")

    elif command == "classify":
        from dashboard.backend.db import init_db
        from dashboard.backend.classifier import classify_run, classify_all_runs, reclassify_run
        init_db()

        # Check for --force flag
        force = "--force" in sys.argv

        # Check if a specific run_id was provided
        run_id = None
        for arg in sys.argv[2:]:
            if not arg.startswith("--"):
                run_id = arg
                break

        if run_id:
            print(f"Classifying run: {run_id}")
            if force:
                result = reclassify_run(run_id)
            else:
                result = classify_run(run_id)
            print(f"Done: {result['classified']} classified, {result['skipped']} skipped, {result['errors']} errors")
            if result.get("no_api_key"):
                print("Note: No API key available - only clean passes were marked")
        else:
            print("Classifying all unclassified runs...")
            result = classify_all_runs()
            print(f"\nSummary:")
            print(f"  Runs processed: {result['runs_classified']}/{result['total_runs']}")
            print(f"  Steps classified: {result['total_steps_classified']}")
            print(f"  Errors: {result['total_errors']}")
            if result.get("no_api_key"):
                print("Note: No API key available - only clean passes were marked")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
