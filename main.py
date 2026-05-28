from __future__ import annotations

import json
import platform
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from crawler_scope.healthcheck import check_agentscope_import

app = typer.Typer(help="CrawlerScope command line interface.")
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PROJECT_ROOT / "runs" / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    created_at = datetime.now().isoformat(timespec="seconds")

    (run_dir / "task_input.txt").write_text(task, encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "task": task,
                "status": "initialized",
                "created_at": created_at,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "run_initialized",
                "task": task,
                "timestamp": created_at,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    console.print(f"Run directory: {run_dir}")


if __name__ == "__main__":
    app()
