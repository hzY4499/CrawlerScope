from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import (
    AccessDecision,
    DOIInputItem,
    DownloadResult,
    PaperRecord,
    ParseResult,
)
from crawler_scope.tools.reporting.report_builder import build_run_report


def test_build_run_report_merges_statuses_and_failures(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)

    doi_items = [
        DOIInputItem(original="10.1000/parsed", normalized_doi="10.1000/parsed"),
        DOIInputItem(
            original="bad doi",
            status="invalid",
            error_message="Invalid DOI format.",
        ),
    ]
    papers = [
        PaperRecord(
            paper_id="paper_parsed",
            doi="10.1000/parsed",
            title="Parsed Paper",
            authors=["Ada"],
            year=2024,
            venue="Journal A",
            publisher="Publisher A",
            raw={},
        )
    ]
    access_decisions = [
        AccessDecision(
            paper_id="paper_parsed",
            doi="10.1000/parsed",
            status="allowed",
            access_type="open_access",
            download_strategy="direct_pdf",
            access_url="https://example.org/paper.pdf",
        )
    ]
    download_results = [
        DownloadResult(
            paper_id="paper_parsed",
            doi="10.1000/parsed",
            status="success",
            access_type="open_access",
            strategy="direct_pdf",
            file_path="/tmp/paper.pdf",
        )
    ]
    parse_results = [
        ParseResult(
            paper_id="paper_parsed",
            doi="10.1000/parsed",
            status="success",
            parser="pymupdf",
            title="Parsed Paper",
            full_text_path="/tmp/paper.txt",
        )
    ]

    _write_jsonl(artifacts_dir / "doi_input_items.jsonl", doi_items)
    _write_jsonl(artifacts_dir / "papers_metadata_merged.jsonl", papers)
    _write_jsonl(artifacts_dir / "access_decisions.jsonl", access_decisions)
    _write_jsonl(artifacts_dir / "download_results.jsonl", download_results)
    _write_jsonl(artifacts_dir / "parse_results.jsonl", parse_results)

    bundle = build_run_report("run_demo", artifacts_dir)

    assert len(bundle.report.final_papers) == 2
    statuses = {item.doi: item.status for item in bundle.report.final_papers}
    assert statuses["10.1000/parsed"] == "parsed"
    assert statuses["bad doi"] == "metadata_failed"
    assert len(bundle.report.final_failures) == 1
    assert "Ready for downstream analysis" in bundle.client_deliverable_summary_md
    assert "final_papers.csv" in bundle.client_deliverable_summary_md


def _write_jsonl(path: Path, items: list) -> None:
    path.write_text("".join(item.model_dump_json() + "\n" for item in items), encoding="utf-8")
