from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import DownloadResult, ParseResult
from crawler_scope.tools.parser import parse_pdf_basic
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def parse_downloaded_pdfs_for_run(
    run_id: str,
    output_dir: Path | None = None,
) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    success_path = run_dir / "artifacts" / "open_pdf_download_success.jsonl"
    results_path = run_dir / "artifacts" / "download_results.jsonl"

    if success_path.exists():
        download_results = _load_download_results(success_path)
    elif results_path.exists():
        download_results = [
            item for item in _load_download_results(results_path) if item.status == "success"
        ]
    else:
        raise FileNotFoundError(
            f"Missing download results files: {success_path} and {results_path}"
        )

    resolved_output_dir = (output_dir or (PROJECT_ROOT / "data" / "parsed" / "papers")).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "pdf_parse_started",
            "timestamp": _iso_now(),
            "total_candidates": len(download_results),
            "output_dir": str(resolved_output_dir),
        },
    )
    RUN_STORE.mark_status(run_id, "parsing_pdfs", parse_output_dir=str(resolved_output_dir))

    parse_results: list[ParseResult] = []
    success_results: list[ParseResult] = []
    failed_results: list[ParseResult] = []
    failures_by_type: Counter[str] = Counter()
    skipped = 0

    for download_result in download_results:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "pdf_parse_item_started",
                "timestamp": _iso_now(),
                "doi": download_result.doi,
                "paper_id": download_result.paper_id,
                "file_path": download_result.file_path,
            },
        )

        result = parse_pdf_basic(download_result, resolved_output_dir)
        parse_results.append(result)

        if result.status == "success":
            success_results.append(result)
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "pdf_parse_item_succeeded",
                    "timestamp": _iso_now(),
                    "doi": result.doi,
                    "paper_id": result.paper_id,
                    "full_text_path": result.full_text_path,
                    "page_count": result.page_count,
                    "word_count": result.word_count,
                },
            )
        elif result.status == "failed":
            failed_results.append(result)
            if result.error_type:
                failures_by_type[result.error_type] += 1
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "pdf_parse_item_failed",
                    "timestamp": _iso_now(),
                    "doi": result.doi,
                    "paper_id": result.paper_id,
                    "error_type": result.error_type,
                    "error_message": result.error_message,
                },
            )
        else:
            skipped += 1
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "pdf_parse_item_skipped",
                    "timestamp": _iso_now(),
                    "doi": result.doi,
                    "paper_id": result.paper_id,
                    "reason": result.error_message,
                },
            )

    RUN_STORE.save_text(run_id, "artifacts/parse_results.jsonl", _jsonl_text(parse_results))
    RUN_STORE.save_text(
        run_id,
        "artifacts/pdf_parse_success.jsonl",
        _jsonl_text(success_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/pdf_parse_failed.jsonl",
        _jsonl_text(failed_results),
    )

    summary = {
        "total_candidates": len(download_results),
        "parse_success": len(success_results),
        "parse_failed": len(failed_results),
        "skipped": skipped,
        "failures_by_type": dict(failures_by_type),
        "output_dir": str(resolved_output_dir),
    }
    RUN_STORE.save_json(run_id, "artifacts/pdf_parse_summary.json", summary)
    RUN_STORE.mark_status(run_id, "completed", pdf_parse_summary=summary)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "pdf_parse_completed",
            "timestamp": _iso_now(),
            **summary,
        },
    )
    return summary


def _load_download_results(path: Path) -> list[DownloadResult]:
    items: list[DownloadResult] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(DownloadResult.model_validate_json(line))
    return items


def _jsonl_text(items: list[ParseResult]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
