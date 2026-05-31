from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import MetadataSourceResult, PaperRecord, TaskSpec
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import doi_resolve_workflow


def test_resolve_dois_for_run_generates_artifacts(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_resolve",
        task_type="doi_batch_crawl",
        user_request="Resolve metadata",
        query="tests/fixtures/sample_dois.txt",
        sources=["tests/fixtures/sample_dois.txt"],
        outputs=["artifacts/valid_dois.txt"],
    )
    run_id = store.create_run(task_spec, task_input="import-dois tests/fixtures/sample_dois.txt")
    store.save_text(
        run_id,
        "artifacts/valid_dois.txt",
        "10.1000/test-one\n10.1000/test-two\n",
    )

    monkeypatch.setattr(doi_resolve_workflow, "RUN_STORE", store)
    monkeypatch.setattr(doi_resolve_workflow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        doi_resolve_workflow,
        "fetch_crossref_by_doi",
        lambda doi, contact_email=None, **kwargs: _mock_result(doi, "crossref"),
    )
    monkeypatch.setattr(
        doi_resolve_workflow,
        "fetch_openalex_by_doi",
        lambda doi, contact_email=None, **kwargs: _mock_result(doi, "openalex"),
    )
    monkeypatch.setattr(
        doi_resolve_workflow,
        "fetch_semantic_scholar_by_doi",
        lambda doi, api_key=None, **kwargs: _mock_result(doi, "semantic_scholar"),
    )
    monkeypatch.setattr(
        doi_resolve_workflow,
        "fetch_unpaywall_by_doi",
        lambda doi, contact_email=None, **kwargs: _mock_result(doi, "unpaywall", with_pdf=True),
    )

    summary = doi_resolve_workflow.resolve_dois_for_run(run_id)
    run_dir = store.get_run_dir(run_id)

    assert summary["total_dois"] == 2
    assert summary["merged_success"] == 2
    assert summary["has_open_pdf"] == 2
    assert (run_dir / "artifacts" / "papers_metadata_merged.jsonl").exists()
    assert (run_dir / "artifacts" / "access_hints.jsonl").exists()

    merged_lines = (
        run_dir / "artifacts" / "papers_metadata_merged.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    hint_lines = (
        run_dir / "artifacts" / "access_hints.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    assert len(merged_lines) == 2
    assert len(hint_lines) == 2

    first_hint = json.loads(hint_lines[0])
    assert first_hint["has_open_pdf"] is True
    assert first_hint["next_stage"] == "download_open_pdf"


def _mock_result(doi: str, source: str, with_pdf: bool = False) -> MetadataSourceResult:
    pdf_urls = [f"https://example.org/{doi}.pdf"] if with_pdf else []
    source_urls = [f"https://example.org/{doi}"]
    return MetadataSourceResult(
        doi=doi,
        source=source,  # type: ignore[arg-type]
        status="success",
        paper=PaperRecord(
            paper_id=f"doi:{doi}",
            doi=doi,
            title=f"{source} title for {doi}",
            authors=["Test Author"],
            year=2024,
            venue=f"{source} venue",
            source_urls=source_urls,
            pdf_urls=pdf_urls,
            license="cc-by" if with_pdf else None,
            raw={"source": source, "doi": doi},
        ),
    )
