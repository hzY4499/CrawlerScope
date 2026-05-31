from __future__ import annotations

import json
from pathlib import Path

import fitz

from crawler_scope.schemas import DownloadResult, TaskSpec
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import pdf_parse_workflow


def test_pdf_parse_workflow_generates_reports(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_parse",
        task_type="doi_batch_crawl",
        user_request="parse pdfs",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/open_pdf_download_success.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")

    existing_pdf = tmp_path / "sample.pdf"
    _create_pdf(existing_pdf, title="Workflow Title", body="Workflow Title\nAbstract\nAlpha beta.\nIntroduction\nGamma.")

    download_results = [
        DownloadResult(
            paper_id="paper_ok",
            doi="10.1000/ok",
            status="success",
            access_type="open_access",
            strategy="direct_pdf",
            file_path=str(existing_pdf),
        ),
        DownloadResult(
            paper_id="paper_missing",
            doi="10.1000/missing",
            status="success",
            access_type="open_access",
            strategy="direct_pdf",
            file_path=str(tmp_path / "missing.pdf"),
        ),
    ]
    store.save_text(
        run_id,
        "artifacts/open_pdf_download_success.jsonl",
        "".join(item.model_dump_json() + "\n" for item in download_results),
    )

    monkeypatch.setattr(pdf_parse_workflow, "RUN_STORE", store)

    summary = pdf_parse_workflow.parse_downloaded_pdfs_for_run(
        run_id,
        output_dir=tmp_path / "parsed",
    )
    run_dir = store.get_run_dir(run_id)

    assert summary["total_candidates"] == 2
    assert summary["parse_success"] == 1
    assert summary["parse_failed"] == 1
    assert summary["failures_by_type"] == {"file_not_found": 1}
    assert (run_dir / "artifacts" / "parse_results.jsonl").exists()
    assert (run_dir / "artifacts" / "pdf_parse_success.jsonl").exists()
    assert (run_dir / "artifacts" / "pdf_parse_failed.jsonl").exists()
    assert (run_dir / "artifacts" / "pdf_parse_summary.json").exists()

    lines = (
        run_dir / "artifacts" / "parse_results.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["status"] in {"success", "failed"}


def _create_pdf(path: Path, *, title: str, body: str) -> None:
    document = fitz.open()
    document.set_metadata({"title": title})
    page = document.new_page()
    page.insert_text((72, 72), body)
    document.save(path)
    document.close()
