from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import AccessDecision, TaskSpec
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import open_pdf_download_workflow


def test_open_pdf_download_workflow_generates_reports(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_download",
        task_type="doi_batch_crawl",
        user_request="download open pdfs",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/open_pdf_candidates.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")

    decisions = [
        AccessDecision(
            paper_id="paper_one",
            doi="10.1000/one",
            status="allowed",
            access_type="open_access",
            download_strategy="direct_pdf",
            access_url="https://example.org/one.pdf",
            access_urls=["https://example.org/one.pdf"],
            pdf_urls=["https://example.org/one.pdf"],
        ),
        AccessDecision(
            paper_id="paper_two",
            doi="10.1000/two",
            status="allowed",
            access_type="open_access",
            download_strategy="direct_pdf",
            access_url="https://example.org/two.pdf",
            access_urls=["https://example.org/two.pdf"],
            pdf_urls=["https://example.org/two.pdf"],
        ),
    ]
    store.save_text(
        run_id,
        "artifacts/open_pdf_candidates.jsonl",
        "".join(decision.model_dump_json() + "\n" for decision in decisions),
    )

    monkeypatch.setattr(open_pdf_download_workflow, "RUN_STORE", store)

    def fake_download(decision, output_dir, timeout_seconds=30.0):
        if decision.doi == "10.1000/one":
            return open_pdf_download_workflow.DownloadResult(
                paper_id=decision.paper_id or decision.doi,
                doi=decision.doi,
                status="success",
                access_type=decision.access_type,
                strategy=decision.download_strategy,
                url=decision.access_url,
                file_path=str(output_dir / "paper_one.pdf"),
                sha256="abc123",
                size_bytes=12345,
                content_type="application/pdf",
            )
        return open_pdf_download_workflow.DownloadResult(
            paper_id=decision.paper_id or decision.doi,
            doi=decision.doi,
            status="failed",
            access_type=decision.access_type,
            strategy=decision.download_strategy,
            url=decision.access_url,
            error_type="download_404",
            error_message="HTTP 404",
        )

    monkeypatch.setattr(
        open_pdf_download_workflow,
        "download_open_pdf_candidate",
        fake_download,
    )

    summary = open_pdf_download_workflow.download_open_pdfs_for_run(run_id, output_dir=tmp_path / "papers")
    run_dir = store.get_run_dir(run_id)

    assert summary["total_candidates"] == 2
    assert summary["downloaded_success"] == 1
    assert summary["downloaded_failed"] == 1
    assert summary["failures_by_type"] == {"download_404": 1}
    assert (run_dir / "artifacts" / "download_results.jsonl").exists()
    assert (run_dir / "artifacts" / "open_pdf_download_success.jsonl").exists()
    assert (run_dir / "artifacts" / "open_pdf_download_failed.jsonl").exists()
    assert (run_dir / "artifacts" / "download_summary.json").exists()

    lines = (
        run_dir / "artifacts" / "download_results.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["status"] == "success"
