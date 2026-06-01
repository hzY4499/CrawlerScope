from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import ManualHandoffRecord, SupplementDownloadResult, SupplementSummary
from crawler_scope.tools.browser import safe_storage_state_path
from crawler_scope.tools.publishers import (
    SupplementDiscoveryError,
    build_wiley_article_url_from_doi,
    discover_wiley_supplements_with_browser_state,
    download_supplement_file,
)
from crawler_scope.tools.storage import RunStore

from . import wiley_supplement_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def collect_wiley_supplements_with_session_for_run(
    run_id: str,
    profile_name: str = "wiley-default",
    storage_state_path: Path | None = None,
    output_dir: Path | None = None,
    max_articles: int | None = None,
    headless: bool = True,
) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    papers_path = run_dir / "artifacts" / "papers_metadata_merged.jsonl"
    valid_dois_path = run_dir / "artifacts" / "valid_dois.txt"
    resolved_output_dir = (output_dir or (PROJECT_ROOT / "data" / "raw" / "supplements")).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_storage_state_path = Path(
        storage_state_path or safe_storage_state_path(profile_name, "wiley")
    ).resolve()
    if not resolved_storage_state_path.exists():
        raise FileNotFoundError(
            f"Missing Wiley browser storage state: {resolved_storage_state_path}"
        )

    candidates = wiley_supplement_workflow._load_candidates(papers_path, valid_dois_path)
    if max_articles is not None:
        candidates = candidates[:max_articles]

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "wiley_browser_supplement_collection_started",
            "timestamp": _iso_now(),
            "total_candidate_articles": len(candidates),
            "profile_name": profile_name,
            "storage_state_path": str(resolved_storage_state_path),
            "max_articles": max_articles,
            "headless": headless,
            "output_dir": str(resolved_output_dir),
        },
    )
    RUN_STORE.mark_status(
        run_id,
        "collecting_wiley_browser_supplements",
        profile_name=profile_name,
        browser_supplement_output_dir=str(resolved_output_dir),
    )

    supplement_records = []
    download_results: list[SupplementDownloadResult] = []
    success_results: list[SupplementDownloadResult] = []
    failed_results: list[SupplementDownloadResult] = []
    manual_handoffs: list[ManualHandoffRecord] = []
    failures_by_type: Counter[str] = Counter()
    extensions_by_count: Counter[str] = Counter()
    articles_with_supplements = 0

    for candidate in candidates:
        doi = candidate["doi"]
        paper_id = candidate.get("paper_id")
        article_url = candidate.get("article_url") or build_wiley_article_url_from_doi(doi)

        RUN_STORE.append_trace(
            run_id,
            {
                "event": "browser_supplement_discovery_start",
                "timestamp": _iso_now(),
                "doi": doi,
                "paper_id": paper_id,
                "article_url": article_url,
            },
        )

        try:
            discovered = discover_wiley_supplements_with_browser_state(
                doi,
                storage_state_path=resolved_storage_state_path,
                article_url=article_url,
                headless=headless,
            )
        except SupplementDiscoveryError as exc:
            failures_by_type[exc.error_type] += 1
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "browser_supplement_discovery_failed",
                    "timestamp": _iso_now(),
                    "doi": doi,
                    "paper_id": paper_id,
                    "article_url": article_url,
                    "error_type": exc.error_type,
                    "error_message": str(exc),
                },
            )
            handoff = _build_manual_handoff(doi, paper_id, article_url, exc.error_type)
            if handoff is not None:
                manual_handoffs.append(handoff)
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "manual_handoff_created",
                        "timestamp": _iso_now(),
                        "doi": doi,
                        "paper_id": paper_id,
                        "article_url": article_url,
                        "reason": handoff.reason,
                        "next_action": handoff.next_action,
                    },
                )
            continue

        normalized_records = [
            record.model_copy(update={"paper_id": paper_id, "article_url": article_url})
            for record in discovered
        ]
        supplement_records.extend(normalized_records)
        if normalized_records:
            articles_with_supplements += 1
        for record in normalized_records:
            if record.extension:
                extensions_by_count[record.extension] += 1

        RUN_STORE.append_trace(
            run_id,
            {
                "event": "browser_supplement_discovery_success",
                "timestamp": _iso_now(),
                "doi": doi,
                "paper_id": paper_id,
                "article_url": article_url,
                "discovered_count": len(normalized_records),
            },
        )

        for record in normalized_records:
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "browser_supplement_download_start",
                    "timestamp": _iso_now(),
                    "doi": record.doi,
                    "paper_id": record.paper_id,
                    "supplement_url": record.supplement_url,
                    "filename": record.filename,
                },
            )
            result = download_supplement_file(record, resolved_output_dir)
            download_results.append(result)

            if result.status == "success":
                success_results.append(result)
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "browser_supplement_download_success",
                        "timestamp": _iso_now(),
                        "doi": result.doi,
                        "paper_id": result.paper_id,
                        "supplement_url": result.supplement_url,
                        "file_path": result.file_path,
                        "sha256": result.sha256,
                        "size_bytes": result.size_bytes,
                    },
                )
            elif result.status == "failed":
                failed_results.append(result)
                failures_by_type[result.error_type or "unknown_error"] += 1
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "browser_supplement_download_failed",
                        "timestamp": _iso_now(),
                        "doi": result.doi,
                        "paper_id": result.paper_id,
                        "supplement_url": result.supplement_url,
                        "error_type": result.error_type,
                        "error_message": result.error_message,
                    },
                )

    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_browser_supplement_records.jsonl",
        wiley_supplement_workflow._jsonl_text(supplement_records),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_browser_supplement_download_results.jsonl",
        wiley_supplement_workflow._jsonl_text(download_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_browser_supplement_success.jsonl",
        wiley_supplement_workflow._jsonl_text(success_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_browser_supplement_failed.jsonl",
        wiley_supplement_workflow._jsonl_text(failed_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_handoff.jsonl",
        wiley_supplement_workflow._jsonl_text(manual_handoffs),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_handoff.csv",
        _render_manual_handoff_csv(manual_handoffs),
    )

    summary = SupplementSummary(
        total_articles=len(candidates),
        articles_with_supplements=articles_with_supplements,
        total_supplement_links=len(supplement_records),
        downloaded_success=len(success_results),
        downloaded_failed=len(failed_results),
        skipped=sum(1 for item in download_results if item.status == "skipped"),
        manual_handoff_count=len(manual_handoffs),
        failures_by_type=dict(failures_by_type),
        extensions_by_count=dict(extensions_by_count),
    )
    RUN_STORE.save_json(run_id, "artifacts/wiley_browser_supplement_summary.json", summary)
    wiley_supplement_workflow._write_report_csv(
        run_id,
        supplement_records,
        download_results,
        artifact_path="artifacts/wiley_browser_supplement_report.csv",
        store=RUN_STORE,
    )
    RUN_STORE.mark_status(
        run_id,
        "completed",
        wiley_browser_supplement_summary=summary.model_dump(mode="json"),
    )
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "wiley_browser_supplement_collection_completed",
            "timestamp": _iso_now(),
            **summary.model_dump(mode="json"),
        },
    )
    return summary.model_dump(mode="json")


def _build_manual_handoff(
    doi: str,
    paper_id: str | None,
    article_url: str,
    error_type: str,
) -> ManualHandoffRecord | None:
    reason_map = {
        "access_challenge": "access_challenge",
        "captcha_required": "captcha_required",
        "login_required": "login_required",
        "paywall": "paywall",
        "download_403": "paywall",
        "unknown_error": "unknown",
    }
    reason = reason_map.get(error_type)
    if reason is None and error_type.startswith("http_"):
        reason = "manual_review"
    if reason is None:
        return None

    next_action_map = {
        "access_challenge": "Retry collect-wiley-supplements-browser after refreshing browser session.",
        "captcha_required": "Retry collect-wiley-supplements-browser after completing the challenge manually.",
        "login_required": "Open article URL manually after institutional login and retry browser-assisted collection.",
        "paywall": "Open article URL manually after institutional login and download supplements manually.",
        "manual_review": "Check whether the article has supporting information on Wiley page.",
        "unknown": "Check whether the article has supporting information on Wiley page.",
    }
    return ManualHandoffRecord(
        doi=doi,
        paper_id=paper_id,
        article_url=article_url,
        reason=reason,
        next_action=next_action_map[reason],
        created_at=datetime.now(timezone.utc),
    )


def _render_manual_handoff_csv(items: list[ManualHandoffRecord]) -> str:
    buffer = io.StringIO()
    fieldnames = ["doi", "paper_id", "article_url", "reason", "next_action"]
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
    )
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
