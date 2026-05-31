from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from crawler_scope.schemas import AccessPolicy, QualityRequirements, TaskSpec
from crawler_scope.tools.doi import load_doi_list
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows.access_plan_workflow import plan_access_for_run
from crawler_scope.workflows.doi_resolve_workflow import resolve_dois_for_run
from crawler_scope.workflows.open_pdf_download_workflow import download_open_pdfs_for_run
from crawler_scope.workflows.pdf_parse_workflow import parse_downloaded_pdfs_for_run
from crawler_scope.workflows.report_workflow import report_run

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def run_full_smoke_test(
    input_path: Path,
    allow_user_login: bool = False,
    allow_manual_upload: bool = True,
    max_items: int | None = None,
    use_cache: bool = True,
) -> dict:
    if allow_user_login:
        raise ValueError("Smoke runs do not support institution login in this stage.")
    if not input_path.exists():
        raise FileNotFoundError(f"DOI input file not found: {input_path}")

    run_id = _import_dois_for_smoke(input_path, max_items=max_items)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "smoke_run_started",
            "timestamp": _timestamp(),
            "input_path": str(input_path),
            "max_items": max_items,
            "allow_manual_upload": allow_manual_upload,
            "use_cache": use_cache,
        },
    )

    metadata_summary = _run_stage(
        run_id,
        "resolve_dois",
        lambda: resolve_dois_for_run(run_id, use_cache=use_cache),
    )
    access_plan_summary = _run_stage(
        run_id,
        "plan_access",
        lambda: plan_access_for_run(
            run_id,
            allow_user_login=False,
            allow_manual_upload=allow_manual_upload,
            institution_domains=[],
        ),
    )
    download_summary = _run_stage(
        run_id,
        "download_open_pdfs",
        lambda: download_open_pdfs_for_run(run_id),
    )
    pdf_parse_summary = _run_stage(
        run_id,
        "parse_pdfs",
        lambda: parse_downloaded_pdfs_for_run(run_id),
    )
    report_summary = _run_stage(run_id, "report_run", lambda: report_run(run_id))

    run_dir = RUN_STORE.get_run_dir(run_id)
    report_paths = {
        "final_papers_csv": str(run_dir / "artifacts" / "final_papers.csv"),
        "client_deliverable_summary_md": str(
            run_dir / "artifacts" / "client_deliverable_summary.md"
        ),
        "reports_final_papers_csv": str(
            PROJECT_ROOT / "data" / "reports" / f"{run_id}_final_papers.csv"
        ),
        "reports_client_summary_md": str(
            PROJECT_ROOT / "data" / "reports" / f"{run_id}_client_summary.md"
        ),
    }

    summary = {
        "run_id": run_id,
        "metadata_summary": metadata_summary,
        "access_plan_summary": access_plan_summary,
        "download_summary": download_summary,
        "pdf_parse_summary": pdf_parse_summary,
        "report_summary": report_summary,
        "report_paths": report_paths,
    }
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "smoke_run_completed",
            "timestamp": _timestamp(),
            "run_id": run_id,
            "report_paths": report_paths,
        },
    )
    return summary


def _import_dois_for_smoke(input_path: Path, max_items: int | None) -> str:
    items = load_doi_list(input_path)
    if max_items is not None:
        items = items[:max_items]

    valid_dois = [
        item.normalized_doi
        for item in items
        if item.status == "valid" and item.normalized_doi is not None
    ]
    invalid_dois = [item.original for item in items if item.status == "invalid"]
    duplicate_dois = [
        item.normalized_doi or item.original for item in items if item.status == "duplicate"
    ]

    task_spec = TaskSpec(
        task_id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}",
        task_type="doi_batch_crawl",
        user_request=f"Smoke run DOI file from {input_path}",
        query=str(input_path),
        sources=[str(input_path)],
        outputs=[
            "artifacts/doi_input_items.jsonl",
            "artifacts/valid_dois.txt",
            "artifacts/final_papers.csv",
            "artifacts/client_deliverable_summary.md",
        ],
        access_policy=AccessPolicy(),
        quality=QualityRequirements(),
    )
    run_id = RUN_STORE.create_run(task_spec, task_input=f"smoke-run {input_path}")
    RUN_STORE.save_text(
        run_id,
        "artifacts/doi_input_items.jsonl",
        "".join(item.model_dump_json() + "\n" for item in items),
    )
    RUN_STORE.save_text(run_id, "artifacts/valid_dois.txt", _join_lines(valid_dois))
    RUN_STORE.save_text(run_id, "artifacts/invalid_dois.txt", _join_lines(invalid_dois))
    RUN_STORE.save_text(
        run_id,
        "artifacts/duplicate_dois.txt",
        _join_lines(duplicate_dois),
    )
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "smoke_import_completed",
            "timestamp": _timestamp(),
            "total": len(items),
            "valid": len(valid_dois),
            "invalid": len(invalid_dois),
            "duplicate": len(duplicate_dois),
        },
    )
    return run_id


def _run_stage(run_id: str, stage: str, callback) -> dict:
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "smoke_stage_started",
            "timestamp": _timestamp(),
            "stage": stage,
        },
    )
    try:
        summary = callback()
    except Exception as exc:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "smoke_stage_failed",
                "timestamp": _timestamp(),
                "stage": stage,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        )
        raise

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "smoke_stage_completed",
            "timestamp": _timestamp(),
            "stage": stage,
            "summary": summary,
        },
    )
    return summary


def _join_lines(values: list[str]) -> str:
    return "".join(f"{value}\n" for value in values)


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
