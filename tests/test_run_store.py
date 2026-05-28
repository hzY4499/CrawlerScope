from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import TaskSpec
from crawler_scope.tools.storage import RunStore


def test_run_store_creates_run_and_saves_json(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    task_spec = TaskSpec(
        task_id="task_demo",
        task_type="doi_batch_crawl",
        user_request="Import DOI rows",
        query="demo",
        sources=["tests/fixtures/sample_dois.txt"],
        outputs=["artifacts/doi_input_items.jsonl"],
    )

    run_id = store.create_run(task_spec, task_input="import-dois tests/fixtures/sample_dois.txt")
    run_dir = store.get_run_dir(run_id)

    assert run_dir.exists()
    assert (run_dir / "task_input.txt").read_text(encoding="utf-8") == (
        "import-dois tests/fixtures/sample_dois.txt"
    )
    assert (run_dir / "task.yaml").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "artifacts").is_dir()

    store.save_json(run_id, "artifacts/summary.json", {"total": 3})

    assert store.load_json(run_id, "artifacts/summary.json") == {"total": 3}
