from __future__ import annotations

from pathlib import Path

from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import smoke_workflow


def test_smoke_workflow_chains_mocked_stages(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "sample_dois.txt"
    input_path.write_text("10.1000/one\n10.1000/two\n", encoding="utf-8")
    store = RunStore(tmp_path)

    monkeypatch.setattr(smoke_workflow, "RUN_STORE", store)
    monkeypatch.setattr(smoke_workflow, "PROJECT_ROOT", tmp_path)

    def fake_resolve(run_id: str, use_cache: bool = True) -> dict:
        assert use_cache is True
        return {"total_dois": 1, "merged_success": 1, "cache_hits": 0, "cache_misses": 4}

    def fake_plan(
        run_id: str,
        allow_user_login: bool = False,
        allow_manual_upload: bool = True,
        institution_domains: list[str] | None = None,
    ) -> dict:
        assert allow_user_login is False
        assert allow_manual_upload is True
        return {"total_dois": 1, "manual_required": 1}

    def fake_download(run_id: str) -> dict:
        return {"total_candidates": 0, "downloaded_success": 0}

    def fake_parse(run_id: str) -> dict:
        return {"total_candidates": 0, "parse_success": 0}

    def fake_report(run_id: str) -> dict:
        store.save_text(run_id, "artifacts/final_papers.csv", "doi,status\n10.1000/one,manual_required\n")
        store.save_text(
            run_id,
            "artifacts/client_deliverable_summary.md",
            "# Client Deliverable Summary\n",
        )
        return {"unique_final_rows": 1}

    monkeypatch.setattr(smoke_workflow, "resolve_dois_for_run", fake_resolve)
    monkeypatch.setattr(smoke_workflow, "plan_access_for_run", fake_plan)
    monkeypatch.setattr(smoke_workflow, "download_open_pdfs_for_run", fake_download)
    monkeypatch.setattr(smoke_workflow, "parse_downloaded_pdfs_for_run", fake_parse)
    monkeypatch.setattr(smoke_workflow, "report_run", fake_report)

    summary = smoke_workflow.run_full_smoke_test(input_path, max_items=1)
    run_id = summary["run_id"]
    run_dir = store.get_run_dir(run_id)

    assert run_id.startswith("run_")
    assert summary["metadata_summary"]["merged_success"] == 1
    assert summary["report_paths"]["final_papers_csv"].endswith("final_papers.csv")
    assert (run_dir / "artifacts" / "valid_dois.txt").read_text(encoding="utf-8") == "10.1000/one\n"
    assert (run_dir / "artifacts" / "final_papers.csv").exists()
    assert (run_dir / "trace.jsonl").read_text(encoding="utf-8").count("smoke_stage_completed") == 5
