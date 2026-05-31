from __future__ import annotations

import json
from pathlib import Path

from crawler_scope.schemas import DOIInputItem, TaskSpec
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import report_workflow


def test_report_workflow_handles_missing_optional_files(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_report",
        task_type="doi_batch_crawl",
        user_request="report run",
        query="demo",
        sources=["demo"],
        outputs=["artifacts/doi_input_items.jsonl"],
    )
    run_id = store.create_run(task_spec, task_input="demo")
    store.save_text(
        run_id,
        "artifacts/doi_input_items.jsonl",
        DOIInputItem(original="bad doi", status="invalid").model_dump_json() + "\n",
    )

    monkeypatch.setattr(report_workflow, "RUN_STORE", store)
    monkeypatch.setattr(report_workflow, "PROJECT_ROOT", tmp_path)

    summary = report_workflow.report_run(run_id)
    run_dir = store.get_run_dir(run_id)

    assert summary["unique_final_rows"] == 1
    assert (run_dir / "artifacts" / "final_report.json").exists()
    assert (run_dir / "artifacts" / "final_report.md").exists()
    assert (run_dir / "artifacts" / "final_papers.csv").exists()
    assert (run_dir / "artifacts" / "final_failures.csv").exists()
    assert (run_dir / "artifacts" / "client_deliverable_summary.md").exists()
    assert (tmp_path / "data" / "reports" / f"{run_id}_final_papers.csv").exists()
    assert (tmp_path / "data" / "reports" / f"{run_id}_client_summary.md").exists()

    payload = json.loads((run_dir / "artifacts" / "final_report.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == run_id
