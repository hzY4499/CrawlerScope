from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import LocalFileRecord, PaperRecord, TaskSpec
from crawler_scope.tools.local import local_corpus_matcher
from crawler_scope.tools.storage import RunStore


def test_local_corpus_matcher_matches_by_doi_and_statuses(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_local_match",
        task_type="doi_batch_crawl",
        user_request="local match",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")
    papers = [
        PaperRecord(
            paper_id="paper_1",
            doi="10.1000/one",
            title="Paper One",
            raw={},
        ),
        PaperRecord(
            paper_id="paper_2",
            doi="10.1000/two",
            title="Paper Two",
            raw={},
        ),
        PaperRecord(
            paper_id="paper_3",
            doi="10.1000/three",
            title="Paper Three",
            raw={},
        ),
    ]
    store.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        "".join(paper.model_dump_json() + "\n" for paper in papers),
    )

    monkeypatch.setattr(local_corpus_matcher, "RUN_STORE", store)

    local_files = [
        LocalFileRecord(
            file_path="/tmp/one/paper.pdf",
            filename="paper.pdf",
            extension=".pdf",
            content_type="application/pdf",
            sha256="a",
            size_bytes=10,
            file_role="paper_pdf",
            detected_doi="10.1000/one",
            matched_by="filename_doi",
        ),
        LocalFileRecord(
            file_path="/tmp/one/data.zip",
            filename="data.zip",
            extension=".zip",
            content_type="application/zip",
            sha256="b",
            size_bytes=20,
            file_role="supplement",
            detected_doi="10.1000/one",
            matched_by="filename_doi",
        ),
        LocalFileRecord(
            file_path="/tmp/two/data.csv",
            filename="data.csv",
            extension=".csv",
            content_type="text/csv",
            sha256="c",
            size_bytes=30,
            file_role="supplement",
            detected_paper_id="paper_2",
            matched_by="unknown",
        ),
        LocalFileRecord(
            file_path="/tmp/unmatched/file.txt",
            filename="file.txt",
            extension=".txt",
            content_type="text/plain",
            sha256="d",
            size_bytes=40,
            file_role="unknown",
            matched_by="unknown",
        ),
    ]

    updated_files, match_results, summary = local_corpus_matcher.match_local_files_to_run(
        run_id,
        local_files,
    )

    assert len(updated_files) == 4
    by_doi = {result.doi: result for result in match_results}
    assert by_doi["10.1000/one"].status == "complete"
    assert by_doi["10.1000/two"].status == "supplement_only"
    assert by_doi["10.1000/three"].status == "missing"
    assert summary.matched_articles == 2
    assert summary.complete_articles == 1
    assert summary.articles_with_paper_pdf == 1
    assert summary.articles_with_supplements == 2
    assert summary.missing_articles == 1
    assert summary.paper_pdf_files == 1
    assert summary.supplement_files == 2
