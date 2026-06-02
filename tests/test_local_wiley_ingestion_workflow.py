from __future__ import annotations

import json
from pathlib import Path

import fitz

from crawler_scope.schemas import PaperRecord, TaskSpec
from crawler_scope.tools.local import local_corpus_matcher
from crawler_scope.tools.reporting.report_builder import build_run_report
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import local_wiley_ingestion_workflow, report_workflow


def test_local_wiley_ingestion_workflow_generates_artifacts_and_report_integration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_local_ingest",
        task_type="doi_batch_crawl",
        user_request="local ingest",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")
    paper = PaperRecord(
        paper_id="paper_chem",
        doi="10.1002/chem.202001050",
        title="Chem Paper",
        publisher="John Wiley & Sons",
        raw={},
    )
    store.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        paper.model_dump_json() + "\n",
    )

    monkeypatch.setattr(local_wiley_ingestion_workflow, "RUN_STORE", store)
    monkeypatch.setattr(local_corpus_matcher, "RUN_STORE", store)
    monkeypatch.setattr(report_workflow, "RUN_STORE", store)
    monkeypatch.setattr(report_workflow, "PROJECT_ROOT", tmp_path)

    paper_dir = tmp_path / "papers"
    supplement_dir = tmp_path / "supplements" / "10.1002_chem.202001050"
    paper_dir.mkdir()
    supplement_dir.mkdir(parents=True)

    pdf_path = paper_dir / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "DOI 10.1002/chem.202001050")
    document.save(pdf_path)
    document.close()
    (supplement_dir / "dataset.zip").write_bytes(b"PK\x03\x04zip")
    (supplement_dir / "image.png").write_bytes(b"\x89PNG\r\n")
    (supplement_dir / "README.txt").write_text("ignore", encoding="utf-8")

    summary = local_wiley_ingestion_workflow.ingest_local_wiley_corpus_for_run(
        run_id,
        paper_pdf_dir=paper_dir,
        supplement_dir=supplement_dir.parent,
    )
    run_dir = store.get_run_dir(run_id)

    assert summary["total_files_scanned"] == 3
    assert summary["paper_pdf_files"] == 1
    assert summary["supplement_files"] == 2
    assert summary["complete_articles"] == 1
    assert (run_dir / "artifacts" / "local_wiley_file_inventory.jsonl").exists()
    assert (run_dir / "artifacts" / "local_wiley_file_inventory.csv").exists()
    assert (run_dir / "artifacts" / "local_wiley_match_results.jsonl").exists()
    assert (run_dir / "artifacts" / "local_wiley_match_results.csv").exists()
    assert (run_dir / "artifacts" / "local_wiley_unmatched_files.csv").exists()
    assert (run_dir / "artifacts" / "local_wiley_missing_articles.csv").exists()
    assert (run_dir / "artifacts" / "local_wiley_ingestion_summary.json").exists()

    bundle = build_run_report(run_id, run_dir / "artifacts")
    assert "Local Existing Wiley Corpus" in bundle.final_report_md
    assert "local_wiley_match_results.csv" in bundle.client_deliverable_summary_md

    report_summary = report_workflow.report_run(run_id)
    assert report_summary["local_ingestion_summary"]["complete_articles"] == 1

    payload = json.loads(
        (run_dir / "artifacts" / "local_wiley_ingestion_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["files_by_extension"] == {".pdf": 1, ".png": 1, ".zip": 1}
