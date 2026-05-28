from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console

from crawler_scope.healthcheck import check_agentscope_import
from crawler_scope.schemas import AccessPolicy, QualityRequirements, TaskSpec
from crawler_scope.tools.doi import load_doi_list
from crawler_scope.tools.storage import RunStore

app = typer.Typer(help="CrawlerScope command line interface.")
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent
RUN_STORE = RunStore(PROJECT_ROOT)


@app.command()
def healthcheck() -> None:
    """Verify local Python and AgentScope availability."""
    try:
        agentscope_version = check_agentscope_import()
        agentscope_importable = True
    except Exception as exc:  # pragma: no cover - kept for CLI diagnostics
        agentscope_importable = False
        agentscope_version = f"error: {exc}"

    console.print(f"Python version: {platform.python_version()}")
    console.print(f"AgentScope importable: {agentscope_importable}")
    console.print(f"AgentScope version: {agentscope_version}")
    console.print(f"Project directory: {PROJECT_ROOT}")

    if not agentscope_importable:
        raise typer.Exit(code=1)


@app.command("init-run")
def init_run(task: str) -> None:
    """Create a local run directory with starter artifacts."""
    task_spec = _build_task_spec(
        task_type="paper_crawl",
        user_request=task,
        query=task,
        sources=[],
        outputs=["artifacts/"],
    )
    run_id = RUN_STORE.create_run(task_spec, task_input=task)
    console.print(f"Run directory: {RUN_STORE.get_run_dir(run_id)}")


@app.command("import-dois")
def import_dois(path: Path) -> None:
    """Normalize and catalog DOI input rows without network access."""
    if not path.exists():
        console.print(f"DOI input file not found: {path}")
        raise typer.Exit(code=1)

    try:
        items = load_doi_list(path)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    valid_dois = [
        item.normalized_doi
        for item in items
        if item.status == "valid" and item.normalized_doi is not None
    ]
    invalid_dois = [item.original for item in items if item.status == "invalid"]
    duplicate_dois = [
        item.normalized_doi or item.original for item in items if item.status == "duplicate"
    ]

    task_spec = _build_task_spec(
        task_type="doi_batch_crawl",
        user_request=f"Import DOI file from {path}",
        query=str(path),
        sources=[str(path)],
        outputs=[
            "artifacts/doi_input_items.jsonl",
            "artifacts/valid_dois.txt",
            "artifacts/invalid_dois.txt",
            "artifacts/duplicate_dois.txt",
        ],
    )
    run_id = RUN_STORE.create_run(task_spec, task_input=f"import-dois {path}")

    jsonl_text = "".join(item.model_dump_json() + "\n" for item in items)
    RUN_STORE.save_text(run_id, "artifacts/doi_input_items.jsonl", jsonl_text)
    RUN_STORE.save_text(run_id, "artifacts/valid_dois.txt", _join_lines(valid_dois))
    RUN_STORE.save_text(run_id, "artifacts/invalid_dois.txt", _join_lines(invalid_dois))
    RUN_STORE.save_text(run_id, "artifacts/duplicate_dois.txt", _join_lines(duplicate_dois))

    stats = {
        "total": len(items),
        "valid": len(valid_dois),
        "invalid": len(invalid_dois),
        "duplicate": len(duplicate_dois),
        "run_id": run_id,
    }
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "doi_import_completed",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            **stats,
        },
    )
    RUN_STORE.mark_status(run_id, "completed", summary=stats)

    console.print(f"total: {stats['total']}")
    console.print(f"valid: {stats['valid']}")
    console.print(f"invalid: {stats['invalid']}")
    console.print(f"duplicate: {stats['duplicate']}")
    console.print(f"run_id: {stats['run_id']}")


def _build_task_spec(
    *,
    task_type: str,
    user_request: str,
    query: str | None,
    sources: list[str],
    outputs: list[str],
) -> TaskSpec:
    return TaskSpec(
        task_id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}",
        task_type=task_type,
        user_request=user_request,
        query=query,
        sources=sources,
        outputs=outputs,
        access_policy=AccessPolicy(),
        quality=QualityRequirements(),
    )


def _join_lines(values: list[str]) -> str:
    return "".join(f"{value}\n" for value in values)


if __name__ == "__main__":
    app()
