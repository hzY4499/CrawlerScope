from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import DOIInputItem, PaperRecord, SupplementDownloadResult, SupplementRecord, TaskSpec
from crawler_scope.tools.reporting.report_builder import build_run_report
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import wiley_supplement_workflow


def test_wiley_supplement_workflow_generates_artifacts_and_report_integration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_wiley_supplements",
        task_type="doi_batch_crawl",
        user_request="collect wiley supplements",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")

    papers = [
        PaperRecord(
            paper_id="paper_wiley",
            doi="10.1000/wiley",
            title="Wiley Paper",
            publisher="John Wiley & Sons",
            source_urls=["https://onlinelibrary.wiley.com/doi/10.1000/wiley"],
            raw={},
        ),
        PaperRecord(
            paper_id="paper_other",
            doi="10.1000/other",
            title="Other Paper",
            publisher="Elsevier",
            source_urls=["https://example.org/article"],
            raw={},
        ),
    ]
    store.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        "".join(paper.model_dump_json() + "\n" for paper in papers),
    )
    store.save_text(
        run_id,
        "artifacts/doi_input_items.jsonl",
        DOIInputItem(original="10.1000/wiley", normalized_doi="10.1000/wiley").model_dump_json() + "\n",
    )

    monkeypatch.setattr(wiley_supplement_workflow, "RUN_STORE", store)
    monkeypatch.setattr(wiley_supplement_workflow, "PROJECT_ROOT", tmp_path)

    def fake_discover(doi: str, article_url: str | None = None, timeout_seconds: float = 30.0):
        assert doi == "10.1000/wiley"
        return [
            SupplementRecord(
                doi=doi,
                paper_id="paper_wiley",
                article_url=article_url,
                supplement_url="https://media.wiley.com/one.pdf",
                label="Supporting Information",
                filename="one.pdf",
                extension=".pdf",
                source_section="Supporting Information",
            ),
            SupplementRecord(
                doi=doi,
                paper_id="paper_wiley",
                article_url=article_url,
                supplement_url="https://media.wiley.com/two.zip",
                label="Dataset S1",
                filename="two.zip",
                extension=".zip",
                source_section="Supporting Information",
            ),
        ]

    def fake_download(record: SupplementRecord, output_dir: Path, timeout_seconds: float = 60.0, max_bytes=None):
        if record.extension == ".pdf":
            file_path = output_dir / "paper_wiley" / "one.pdf"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"%PDF-1.7")
            return SupplementDownloadResult(
                doi=record.doi,
                paper_id=record.paper_id,
                supplement_url=record.supplement_url,
                status="success",
                file_path=str(file_path),
                filename="one.pdf",
                extension=".pdf",
                content_type="application/pdf",
                sha256="abc123",
                size_bytes=8,
            )
        return SupplementDownloadResult(
            doi=record.doi,
            paper_id=record.paper_id,
            supplement_url=record.supplement_url,
            status="failed",
            filename="two.zip",
            extension=".zip",
            error_type="download_404",
            error_message="HTTP 404",
        )

    monkeypatch.setattr(wiley_supplement_workflow, "discover_wiley_supplements", fake_discover)
    monkeypatch.setattr(wiley_supplement_workflow, "download_supplement_file", fake_download)

    summary = wiley_supplement_workflow.collect_wiley_supplements_for_run(
        run_id,
        output_dir=tmp_path / "supplements",
    )
    run_dir = store.get_run_dir(run_id)

    assert summary["total_articles"] == 1
    assert summary["articles_with_supplements"] == 1
    assert summary["total_supplement_links"] == 2
    assert summary["downloaded_success"] == 1
    assert summary["downloaded_failed"] == 1
    assert summary["extensions_by_count"] == {".pdf": 1, ".zip": 1}
    assert (run_dir / "artifacts" / "wiley_supplement_records.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_supplement_download_results.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_supplement_success.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_supplement_failed.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_supplement_summary.json").exists()
    assert (run_dir / "artifacts" / "wiley_supplement_report.csv").exists()

    bundle = build_run_report(run_id, run_dir / "artifacts")
    assert "Supplementary Materials" in bundle.final_report_md
    assert "wiley_supplement_report.csv" in bundle.client_deliverable_summary_md

    payload = json.loads(
        (run_dir / "artifacts" / "wiley_supplement_summary.json").read_text(encoding="utf-8")
    )
    assert payload["downloaded_success"] == 1
