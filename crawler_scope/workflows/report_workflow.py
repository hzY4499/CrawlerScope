from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.tools.reporting import build_run_report
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def report_run(run_id: str) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"
    reports_dir = PROJECT_ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "run_report_started",
            "timestamp": _iso_now(),
            "artifacts_dir": str(artifacts_dir),
        },
    )
    RUN_STORE.mark_status(run_id, "building_report")

    bundle = build_run_report(run_id, artifacts_dir)

    RUN_STORE.save_json(run_id, "artifacts/final_report.json", bundle.report)
    RUN_STORE.save_text(run_id, "artifacts/final_report.md", bundle.final_report_md)
    RUN_STORE.save_text(run_id, "artifacts/final_papers.csv", bundle.final_papers_csv)
    RUN_STORE.save_text(run_id, "artifacts/final_failures.csv", bundle.final_failures_csv)
    RUN_STORE.save_text(
        run_id,
        "artifacts/client_deliverable_summary.md",
        bundle.client_deliverable_summary_md,
    )

    (reports_dir / f"{run_id}_final_papers.csv").write_text(
        bundle.final_papers_csv,
        encoding="utf-8",
    )
    (reports_dir / f"{run_id}_client_summary.md").write_text(
        bundle.client_deliverable_summary_md,
        encoding="utf-8",
    )

    summary = dict(bundle.report.summary)
    summary["reports_dir"] = str(reports_dir)
    RUN_STORE.mark_status(run_id, "completed", final_report_summary=summary)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "run_report_completed",
            "timestamp": _iso_now(),
            **summary,
        },
    )
    return summary


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
