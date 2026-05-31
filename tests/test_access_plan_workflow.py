from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import AccessHint, PaperRecord, TaskSpec
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows.access_plan_workflow import plan_access_for_run


def test_access_plan_workflow_generates_partitioned_outputs(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_access",
        task_type="doi_batch_crawl",
        user_request="Plan access",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/papers_metadata_merged.jsonl", "artifacts/access_hints.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")

    papers = [
        PaperRecord(
            paper_id="doi:10.1000/open",
            doi="10.1000/open",
            title="Open Paper",
            pdf_urls=["https://oa.example/open.pdf"],
            raw={},
        ),
        PaperRecord(
            paper_id="doi:10.1000/auth",
            doi="10.1000/auth",
            title="Auth Paper",
            source_urls=["https://publisher.example/auth"],
            raw={},
        ),
    ]
    hints = [
        AccessHint(
            doi="10.1000/open",
            has_open_pdf=True,
            open_pdf_urls=["https://oa.example/open.pdf"],
        ),
        AccessHint(
            doi="10.1000/landing",
            oa_landing_pages=["https://oa.example/landing"],
        ),
        AccessHint(doi="10.1000/auth"),
        AccessHint(doi="10.1000/unavailable"),
    ]

    store.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        "".join(paper.model_dump_json() + "\n" for paper in papers),
    )
    store.save_text(
        run_id,
        "artifacts/access_hints.jsonl",
        "".join(hint.model_dump_json() + "\n" for hint in hints),
    )

    monkeypatch.setattr(
        "crawler_scope.workflows.access_plan_workflow.RUN_STORE",
        store,
    )

    summary = plan_access_for_run(
        run_id,
        allow_user_login=True,
        allow_manual_upload=True,
        institution_domains=["example.edu"],
    )
    run_dir = store.get_run_dir(run_id)

    assert summary["total_dois"] == 4
    assert summary["open_pdf_candidates"] == 1
    assert summary["authenticated_candidates"] == 2
    assert summary["manual_required"] == 1
    assert summary["unavailable"] == 0
    assert (run_dir / "artifacts" / "access_decisions.jsonl").exists()
    assert (run_dir / "artifacts" / "access_plan_summary.json").exists()

    open_lines = (
        run_dir / "artifacts" / "open_pdf_candidates.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    manual_lines = (
        run_dir / "artifacts" / "manual_required.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()
    authenticated_lines = (
        run_dir / "artifacts" / "authenticated_candidates.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()

    assert len(open_lines) == 1
    assert len(manual_lines) == 1
    assert len(authenticated_lines) == 2

    first_open = json.loads(open_lines[0])
    assert first_open["download_strategy"] == "direct_pdf"
