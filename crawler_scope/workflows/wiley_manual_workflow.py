from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.tools.manual import (
    build_wiley_manual_download_tasks_for_run,
    scan_manual_supplements_for_run,
)
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def prepare_wiley_manual_download_for_run(run_id: str) -> dict:
    tasks = build_wiley_manual_download_tasks_for_run(run_id)
    for task in tasks:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "manual_download_task_created",
                "timestamp": _iso_now(),
                "doi": task.doi,
                "paper_id": task.paper_id,
                "target_dir": task.target_dir,
            },
        )

    summary = {
        "task_count": len(tasks),
        "instructions_path": str(
            RUN_STORE.get_run_dir(run_id)
            / "artifacts"
            / "wiley_manual_download_instructions.md"
        ),
        "tasks_csv_path": str(
            RUN_STORE.get_run_dir(run_id) / "artifacts" / "wiley_manual_download_tasks.csv"
        ),
        "base_manual_dir": str(PROJECT_ROOT / "data" / "manual" / "wiley_supplements"),
    }
    RUN_STORE.mark_status(run_id, "manual_download_prepared", manual_download_summary=summary)
    return summary


def scan_wiley_manual_downloads_for_run(run_id: str) -> dict:
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "manual_scan_start",
            "timestamp": _iso_now(),
        },
    )
    try:
        summary = scan_manual_supplements_for_run(run_id)
    except Exception as exc:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "manual_scan_failed",
                "timestamp": _iso_now(),
                "error_message": str(exc),
            },
        )
        raise

    result = {
        **summary,
        "scan_report_path": str(
            RUN_STORE.get_run_dir(run_id) / "artifacts" / "wiley_manual_scan_report.csv"
        ),
        "missing_csv_path": str(
            RUN_STORE.get_run_dir(run_id) / "artifacts" / "wiley_manual_missing.csv"
        ),
    }
    RUN_STORE.mark_status(run_id, "manual_download_scanned", manual_scan_summary=result)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "manual_scan_success",
            "timestamp": _iso_now(),
            **result,
        },
    )
    return result


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
