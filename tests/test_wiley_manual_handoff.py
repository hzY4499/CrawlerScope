from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import PaperRecord, TaskSpec
from crawler_scope.tools.manual import wiley_manual_handoff
from crawler_scope.tools.storage import RunStore


def test_build_wiley_manual_download_tasks_generates_target_dirs_and_readmes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_manual_handoff",
        task_type="doi_batch_crawl",
        user_request="manual handoff",
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

    monkeypatch.setattr(wiley_manual_handoff, "RUN_STORE", store)
    monkeypatch.setattr(wiley_manual_handoff, "PROJECT_ROOT", tmp_path)

    tasks = wiley_manual_handoff.build_wiley_manual_download_tasks_for_run(run_id)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.doi == "10.1000/wiley"
    assert task.target_dir.startswith(str(tmp_path / "data" / "manual" / "wiley_supplements"))
    readme_path = Path(task.target_dir) / "README.txt"
    assert readme_path.exists()
    readme_text = readme_path.read_text(encoding="utf-8")
    assert "https://onlinelibrary.wiley.com/doi/10.1000/wiley" in readme_text
    assert "Keep all file formats" in readme_text

    run_dir = store.get_run_dir(run_id)
    assert (run_dir / "artifacts" / "wiley_manual_download_tasks.jsonl").exists()
    assert (run_dir / "artifacts" / "wiley_manual_download_tasks.csv").exists()
    assert (run_dir / "artifacts" / "wiley_manual_download_instructions.md").exists()
