from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import PaperRecord, TaskSpec
from crawler_scope.tools.manual import local_supplement_scanner, wiley_manual_handoff
from crawler_scope.tools.reporting.report_builder import build_run_report
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import report_workflow, wiley_manual_workflow


def test_wiley_manual_workflow_generates_scan_summary_and_report_integration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_manual_workflow",
        task_type="doi_batch_crawl",
        user_request="manual scan",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")
    paper = PaperRecord(
        paper_id="paper_wiley",
        doi="10.1000/wiley",
        title="Wiley Paper",
        publisher="John Wiley & Sons",
        source_urls=["https://onlinelibrary.wiley.com/doi/10.1000/wiley"],
        raw={},
    )
    store.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        paper.model_dump_json() + "\n",
    )

    monkeypatch.setattr(wiley_manual_handoff, "RUN_STORE", store)
    monkeypatch.setattr(wiley_manual_handoff, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(local_supplement_scanner, "RUN_STORE", store)
    monkeypatch.setattr(local_supplement_scanner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(wiley_manual_workflow, "RUN_STORE", store)
    monkeypatch.setattr(wiley_manual_workflow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_workflow, "RUN_STORE", store)
    monkeypatch.setattr(report_workflow, "PROJECT_ROOT", tmp_path)

    prepare_summary = wiley_manual_workflow.prepare_wiley_manual_download_for_run(run_id)
    assert prepare_summary["task_count"] == 1

    task_dir = tmp_path / "data" / "manual" / "wiley_supplements" / "10.1000_wiley"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "dataset.zip").write_bytes(b"PK\x03\x04zip")
    (task_dir / "figure.pdf").write_bytes(b"%PDF-1.7")

    scan_summary = wiley_manual_workflow.scan_wiley_manual_downloads_for_run(run_id)
    run_dir = store.get_run_dir(run_id)

    assert scan_summary["total_tasks"] == 1
    assert scan_summary["articles_with_files"] == 1
    assert scan_summary["total_files"] == 2
    assert scan_summary["missing_articles"] == 0
    assert (run_dir / "artifacts" / "wiley_manual_downloaded_files.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_manual_scan_summary.json").exists()
    assert (run_dir / "artifacts" / "wiley_manual_scan_report.csv").exists()
    assert (run_dir / "artifacts" / "wiley_manual_missing.csv").exists()

    bundle = build_run_report(run_id, run_dir / "artifacts")
    assert "Wiley Manual Supplementary Materials" in bundle.final_report_md
    assert "wiley_manual_scan_report.csv" in bundle.client_deliverable_summary_md

    report_summary = report_workflow.report_run(run_id)
    assert report_summary["manual_scan_summary"]["total_files"] == 2

    payload = json.loads(
        (run_dir / "artifacts" / "wiley_manual_scan_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["files_by_extension"] == {".pdf": 1, ".zip": 1}
