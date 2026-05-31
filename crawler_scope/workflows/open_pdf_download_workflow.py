from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import AccessDecision, DownloadResult
from crawler_scope.tools.academic import download_open_pdf_candidate
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def download_open_pdfs_for_run(
    run_id: str,
    output_dir: Path | None = None,
    timeout_seconds: float = 30.0,
) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    candidates_path = run_dir / "artifacts" / "open_pdf_candidates.jsonl"
    if not candidates_path.exists():
        raise FileNotFoundError(f"Missing open PDF candidates file: {candidates_path}")

    decisions = _load_decisions(candidates_path)
    resolved_output_dir = (output_dir or (PROJECT_ROOT / "data" / "raw" / "papers")).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "open_pdf_download_started",
            "timestamp": _iso_now(),
            "total_candidates": len(decisions),
            "output_dir": str(resolved_output_dir),
            "timeout_seconds": timeout_seconds,
        },
    )
    RUN_STORE.mark_status(
        run_id,
        "downloading_open_pdfs",
        download_output_dir=str(resolved_output_dir),
        timeout_seconds=timeout_seconds,
    )

    results: list[DownloadResult] = []
    success_results: list[DownloadResult] = []
    failed_results: list[DownloadResult] = []
    failures_by_type: Counter[str] = Counter()
    skipped = 0

    for decision in decisions:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "open_pdf_download_item_started",
                "timestamp": _iso_now(),
                "doi": decision.doi,
                "paper_id": decision.paper_id,
                "url": decision.access_url,
            },
        )

        result = download_open_pdf_candidate(
            decision,
            resolved_output_dir,
            timeout_seconds=timeout_seconds,
        )
        results.append(result)

        if result.status == "success":
            success_results.append(result)
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "open_pdf_download_item_succeeded",
                    "timestamp": _iso_now(),
                    "doi": result.doi,
                    "paper_id": result.paper_id,
                    "file_path": result.file_path,
                    "size_bytes": result.size_bytes,
                    "sha256": result.sha256,
                },
            )
        elif result.status == "failed":
            failed_results.append(result)
            if result.error_type:
                failures_by_type[result.error_type] += 1
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "open_pdf_download_item_failed",
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
                    "event": "open_pdf_download_item_skipped",
                    "timestamp": _iso_now(),
                    "doi": result.doi,
                    "paper_id": result.paper_id,
                    "reason": result.error_message,
                },
            )

    RUN_STORE.save_text(run_id, "artifacts/download_results.jsonl", _jsonl_text(results))
    RUN_STORE.save_text(
        run_id,
        "artifacts/open_pdf_download_success.jsonl",
        _jsonl_text(success_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/open_pdf_download_failed.jsonl",
        _jsonl_text(failed_results),
    )

    summary = {
        "total_candidates": len(decisions),
        "downloaded_success": len(success_results),
        "downloaded_failed": len(failed_results),
        "skipped": skipped,
        "failures_by_type": dict(failures_by_type),
        "output_dir": str(resolved_output_dir),
    }
    RUN_STORE.save_json(run_id, "artifacts/download_summary.json", summary)
    RUN_STORE.mark_status(run_id, "completed", download_summary=summary)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "open_pdf_download_completed",
            "timestamp": _iso_now(),
            **summary,
        },
    )
    return summary


def _load_decisions(path: Path) -> list[AccessDecision]:
    decisions: list[AccessDecision] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decisions.append(AccessDecision.model_validate_json(line))
    return decisions


def _jsonl_text(items: list[DownloadResult]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
