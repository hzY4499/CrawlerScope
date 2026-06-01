from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import DOIInputItem, PaperRecord, SupplementDownloadResult, SupplementRecord, TaskSpec
from crawler_scope.tools.reporting.report_builder import build_run_report
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import report_workflow, wiley_authenticated_supplement_workflow
from crawler_scope.tools.publishers.wiley_supplement_adapter import SupplementDiscoveryError


def test_wiley_authenticated_workflow_generates_browser_artifacts_and_manual_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_wiley_browser_supplements",
        task_type="doi_batch_crawl",
        user_request="collect browser-assisted wiley supplements",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")
    storage_state_path = tmp_path / "secrets" / "browser_states" / "wiley_default.storage.json"
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    storage_state_path.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")

    papers = [
        PaperRecord(
            paper_id="paper_wiley_ok",
            doi="10.1000/wiley-ok",
            title="Wiley Paper OK",
            publisher="John Wiley & Sons",
            source_urls=["https://onlinelibrary.wiley.com/doi/10.1000/wiley-ok"],
            raw={},
        ),
        PaperRecord(
            paper_id="paper_wiley_blocked",
            doi="10.1000/wiley-blocked",
            title="Wiley Paper Blocked",
            publisher="John Wiley & Sons",
            source_urls=["https://onlinelibrary.wiley.com/doi/10.1000/wiley-blocked"],
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
        "".join(
            DOIInputItem(original=paper.doi, normalized_doi=paper.doi).model_dump_json() + "\n"
            for paper in papers
        ),
    )

    monkeypatch.setattr(wiley_authenticated_supplement_workflow, "RUN_STORE", store)
    monkeypatch.setattr(wiley_authenticated_supplement_workflow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(report_workflow, "RUN_STORE", store)
    monkeypatch.setattr(report_workflow, "PROJECT_ROOT", tmp_path)

    def fake_discover(
        doi: str,
        storage_state_path: Path,
        article_url: str | None = None,
        timeout_seconds: float = 60.0,
        headless: bool = True,
    ):
        if doi == "10.1000/wiley-blocked":
            raise SupplementDiscoveryError(
                "access_challenge",
                "Manual challenge handling is still required.",
            )
        return [
            SupplementRecord(
                doi=doi,
                paper_id="paper_wiley_ok",
                article_url=article_url,
                supplement_url="https://media.wiley.com/one.pdf",
                label="Supporting Information",
                filename="one.pdf",
                extension=".pdf",
                source_section="Supporting Information",
            )
        ]

    def fake_download(
        record: SupplementRecord,
        output_dir: Path,
        timeout_seconds: float = 60.0,
        max_bytes=None,
    ):
        file_path = output_dir / "paper_wiley_ok" / "one.pdf"
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

    monkeypatch.setattr(
        wiley_authenticated_supplement_workflow,
        "discover_wiley_supplements_with_browser_state",
        fake_discover,
    )
    monkeypatch.setattr(
        wiley_authenticated_supplement_workflow,
        "download_supplement_file",
        fake_download,
    )

    summary = wiley_authenticated_supplement_workflow.collect_wiley_supplements_with_session_for_run(
        run_id,
        profile_name="wiley-default",
        storage_state_path=storage_state_path,
        output_dir=tmp_path / "supplements",
        max_articles=5,
        headless=False,
    )
    run_dir = store.get_run_dir(run_id)

    assert summary["total_articles"] == 2
    assert summary["articles_with_supplements"] == 1
    assert summary["total_supplement_links"] == 1
    assert summary["downloaded_success"] == 1
    assert summary["manual_handoff_count"] == 1
    assert summary["failures_by_type"]["access_challenge"] == 1
    assert (run_dir / "artifacts" / "wiley_browser_supplement_records.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_browser_supplement_download_results.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_browser_supplement_success.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_browser_supplement_failed.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_manual_handoff.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_manual_handoff.csv").exists()
    assert (run_dir / "artifacts" / "wiley_browser_supplement_summary.json").exists()
    assert (run_dir / "artifacts" / "wiley_browser_supplement_report.csv").exists()

    bundle = build_run_report(run_id, run_dir / "artifacts")
    assert "Wiley Browser-Assisted Supplementary Materials" in bundle.final_report_md
    assert "wiley_manual_handoff.csv" in bundle.client_deliverable_summary_md

    report_summary = report_workflow.report_run(run_id)
    assert report_summary["browser_supplement_summary"]["downloaded_success"] == 1

    payload = json.loads(
        (run_dir / "artifacts" / "wiley_browser_supplement_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["manual_handoff_count"] == 1
