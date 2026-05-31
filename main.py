from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import typer
from dotenv import load_dotenv
from rich.console import Console

from crawler_scope.healthcheck import check_agentscope_import
from crawler_scope.schemas import AccessPolicy, QualityRequirements, TaskSpec
from crawler_scope.tools.doi import load_doi_list
from crawler_scope.tools.storage import RunStore
from crawler_scope.workflows import (
    download_open_pdfs_for_run,
    parse_downloaded_pdfs_for_run,
    plan_access_for_run,
    report_run,
    resolve_dois_for_run,
    run_full_smoke_test,
)

app = typer.Typer(help="CrawlerScope command line interface.")
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parent
RUN_STORE = RunStore(PROJECT_ROOT)
load_dotenv(PROJECT_ROOT / ".env")


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


@app.command("resolve-dois")
def resolve_dois(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Resolve metadata for the valid DOI list in an existing run."""
    try:
        summary = resolve_dois_for_run(run_id)
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    output_files = [
        "artifacts/crossref_results.jsonl",
        "artifacts/openalex_results.jsonl",
        "artifacts/semantic_scholar_results.jsonl",
        "artifacts/unpaywall_results.jsonl",
        "artifacts/metadata_source_results.jsonl",
        "artifacts/doi_resolution_results.jsonl",
        "artifacts/papers_metadata_merged.jsonl",
        "artifacts/access_hints.jsonl",
        "artifacts/papers_metadata.csv",
        "artifacts/metadata_summary.json",
    ]

    for key, value in summary.items():
        console.print(f"{key}: {value}")

    run_dir = RUN_STORE.get_run_dir(run_id)
    console.print("output_files:")
    for relative_path in output_files:
        console.print(f"- {run_dir / relative_path}")


@app.command("plan-access")
def plan_access(
    run_id: str = typer.Option(..., "--run-id"),
    allow_user_login: bool = typer.Option(
        False,
        "--allow-user-login/--no-allow-user-login",
    ),
    allow_manual_upload: bool = typer.Option(
        True,
        "--allow-manual-upload/--no-allow-manual-upload",
    ),
    institution_domains: list[str] | None = typer.Option(
        None,
        "--institution-domain",
    ),
) -> None:
    """Build access decisions and download planning artifacts for a run."""
    try:
        summary = plan_access_for_run(
            run_id,
            allow_user_login=allow_user_login,
            allow_manual_upload=allow_manual_upload,
            institution_domains=institution_domains or [],
        )
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    output_files = [
        "artifacts/open_pdf_candidates.jsonl",
        "artifacts/authenticated_candidates.jsonl",
        "artifacts/manual_required.jsonl",
        "artifacts/unavailable.jsonl",
        "artifacts/access_decisions.jsonl",
        "artifacts/access_plan_summary.json",
    ]

    for key, value in summary.items():
        console.print(f"{key}: {value}")

    run_dir = RUN_STORE.get_run_dir(run_id)
    console.print("output_files:")
    for relative_path in output_files:
        console.print(f"- {run_dir / relative_path}")


@app.command("download-open-pdfs")
def download_open_pdfs(
    run_id: str = typer.Option(..., "--run-id"),
    timeout_seconds: float = typer.Option(30.0, "--timeout-seconds"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
) -> None:
    """Download only open-access PDF candidates for a run."""
    try:
        summary = download_open_pdfs_for_run(
            run_id,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    run_dir = RUN_STORE.get_run_dir(run_id)
    for key, value in summary.items():
        console.print(f"{key}: {value}")
    console.print(f"download_results: {run_dir / 'artifacts/download_results.jsonl'}")
    console.print(f"pdf_output_dir: {summary['output_dir']}")


@app.command("parse-pdfs")
def parse_pdfs(
    run_id: str = typer.Option(..., "--run-id"),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
) -> None:
    """Parse already-downloaded PDFs into plain text and basic structure."""
    try:
        summary = parse_downloaded_pdfs_for_run(
            run_id,
            output_dir=output_dir,
        )
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    run_dir = RUN_STORE.get_run_dir(run_id)
    for key, value in summary.items():
        console.print(f"{key}: {value}")
    console.print(f"parse_results: {run_dir / 'artifacts/parse_results.jsonl'}")
    console.print(f"parsed_text_output_dir: {summary['output_dir']}")


@app.command("report-run")
def report_run_command(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Build the final run report and client deliverable files."""
    summary = report_run(run_id)
    run_dir = RUN_STORE.get_run_dir(run_id)
    for key, value in summary.items():
        console.print(f"{key}: {value}")
    console.print(f"final_report_json: {run_dir / 'artifacts/final_report.json'}")
    console.print(f"final_report_md: {run_dir / 'artifacts/final_report.md'}")
    console.print(f"final_papers_csv: {run_dir / 'artifacts/final_papers.csv'}")
    console.print(f"client_summary_md: {run_dir / 'artifacts/client_deliverable_summary.md'}")


@app.command("smoke-run")
def smoke_run(
    input_path: Path,
    max_items: int | None = typer.Option(None, "--max-items"),
    allow_manual_upload: bool = typer.Option(
        True,
        "--allow-manual-upload/--no-allow-manual-upload",
    ),
    use_cache: bool = typer.Option(True, "--use-cache/--no-use-cache"),
) -> None:
    """Run the DOI-first pipeline on a small local sample."""
    try:
        summary = run_full_smoke_test(
            input_path,
            allow_user_login=False,
            allow_manual_upload=allow_manual_upload,
            max_items=max_items,
            use_cache=use_cache,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    console.print(f"run_id: {summary['run_id']}")
    report_paths = summary["report_paths"]
    console.print(f"final_papers.csv: {report_paths['final_papers_csv']}")
    console.print(
        f"client_deliverable_summary.md: {report_paths['client_deliverable_summary_md']}"
    )
    _print_summary("metadata_summary", summary["metadata_summary"])
    _print_summary("access_plan_summary", summary["access_plan_summary"])
    _print_summary("download_summary", summary["download_summary"])
    _print_summary("pdf_parse_summary", summary["pdf_parse_summary"])


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


def _print_summary(name: str, summary: dict) -> None:
    console.print(f"{name}:")
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        console.print(f"  {key}: {value}")


if __name__ == "__main__":
    app()
