from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from crawler_scope.schemas import (
    AccessDecision,
    DOIInputItem,
    DownloadResult,
    FinalFailureRecord,
    FinalPaperRecord,
    PaperRecord,
    ParseResult,
    RunReport,
)

T = TypeVar("T")

ARTIFACT_FILENAMES = [
    "doi_input_items.jsonl",
    "valid_dois.txt",
    "invalid_dois.txt",
    "duplicate_dois.txt",
    "papers_metadata_merged.jsonl",
    "access_hints.jsonl",
    "access_decisions.jsonl",
    "open_pdf_candidates.jsonl",
    "authenticated_candidates.jsonl",
    "manual_required.jsonl",
    "unavailable.jsonl",
    "download_results.jsonl",
    "open_pdf_download_success.jsonl",
    "open_pdf_download_failed.jsonl",
    "parse_results.jsonl",
    "pdf_parse_success.jsonl",
    "pdf_parse_failed.jsonl",
    "wiley_supplement_records.jsonl",
    "wiley_supplement_download_results.jsonl",
    "wiley_supplement_success.jsonl",
    "wiley_supplement_failed.jsonl",
    "wiley_supplement_summary.json",
    "wiley_supplement_report.csv",
    "wiley_browser_supplement_records.jsonl",
    "wiley_browser_supplement_download_results.jsonl",
    "wiley_browser_supplement_success.jsonl",
    "wiley_browser_supplement_failed.jsonl",
    "wiley_browser_supplement_summary.json",
    "wiley_browser_supplement_report.csv",
    "wiley_manual_handoff.jsonl",
    "wiley_manual_handoff.csv",
]


@dataclass
class ReportBundle:
    report: RunReport
    final_report_md: str
    client_deliverable_summary_md: str
    final_papers_csv: str
    final_failures_csv: str


@dataclass
class ArtifactSnapshot:
    doi_input_items: list[DOIInputItem]
    papers: list[PaperRecord]
    access_decisions: list[AccessDecision]
    download_results: list[DownloadResult]
    parse_results: list[ParseResult]
    supplement_summary: dict[str, Any] | None
    browser_supplement_summary: dict[str, Any] | None
    manual_handoff_count: int
    artifacts_present: dict[str, bool]


def build_run_report(run_id: str, artifacts_dir: Path) -> ReportBundle:
    snapshot = _load_snapshot(artifacts_dir)
    final_papers = _build_final_papers(snapshot)
    final_failures = _build_final_failures(final_papers, snapshot)
    summary = _build_summary(snapshot, final_papers, final_failures)
    report = RunReport(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        summary=summary,
        artifacts_present=snapshot.artifacts_present,
        final_papers=final_papers,
        final_failures=final_failures,
    )
    return ReportBundle(
        report=report,
        final_report_md=_build_final_report_md(report),
        client_deliverable_summary_md=_build_client_summary_md(report),
        final_papers_csv=_render_csv(
            final_papers,
            [
                "doi",
                "paper_id",
                "title",
                "authors",
                "year",
                "venue",
                "publisher",
                "access_type",
                "download_strategy",
                "access_url",
                "pdf_path",
                "parsed_text_path",
                "status",
                "failure_type",
                "next_action",
            ],
        ),
        final_failures_csv=_render_csv(
            final_failures,
            [
                "doi",
                "paper_id",
                "status",
                "failure_stage",
                "failure_type",
                "error_message",
                "next_action",
            ],
        ),
    )


def _load_snapshot(artifacts_dir: Path) -> ArtifactSnapshot:
    artifacts_present = {
        filename: (artifacts_dir / filename).exists() for filename in ARTIFACT_FILENAMES
    }
    return ArtifactSnapshot(
        doi_input_items=_load_jsonl(artifacts_dir / "doi_input_items.jsonl", DOIInputItem),
        papers=_load_jsonl(artifacts_dir / "papers_metadata_merged.jsonl", PaperRecord),
        access_decisions=_load_jsonl(artifacts_dir / "access_decisions.jsonl", AccessDecision),
        download_results=_load_jsonl(artifacts_dir / "download_results.jsonl", DownloadResult),
        parse_results=_load_jsonl(artifacts_dir / "parse_results.jsonl", ParseResult),
        supplement_summary=_load_json_file(artifacts_dir / "wiley_supplement_summary.json"),
        browser_supplement_summary=_load_json_file(
            artifacts_dir / "wiley_browser_supplement_summary.json"
        ),
        manual_handoff_count=_count_nonempty_jsonl(
            artifacts_dir / "wiley_manual_handoff.jsonl"
        ),
        artifacts_present=artifacts_present,
    )


def _build_final_papers(snapshot: ArtifactSnapshot) -> list[FinalPaperRecord]:
    inputs_by_key = _aggregate_inputs(snapshot.doi_input_items)
    papers_by_key = {_record_key(paper.doi, paper.paper_id): paper for paper in snapshot.papers}
    access_by_key = _pick_best_map(
        snapshot.access_decisions,
        key_fn=lambda item: _record_key(item.doi, item.paper_id),
        priority={"allowed": 3, "manual_review": 2, "blocked": 1},
        status_fn=lambda item: item.status,
    )
    download_by_key = _pick_best_map(
        snapshot.download_results,
        key_fn=lambda item: _record_key(item.doi, item.paper_id),
        priority={"success": 3, "failed": 2, "skipped": 1},
        status_fn=lambda item: item.status,
    )
    parse_by_key = _pick_best_map(
        snapshot.parse_results,
        key_fn=lambda item: _record_key(item.doi, item.paper_id),
        priority={"success": 3, "failed": 2, "skipped": 1},
        status_fn=lambda item: item.status,
    )

    keys = list(
        dict.fromkeys(
            list(inputs_by_key)
            + list(papers_by_key)
            + list(access_by_key)
            + list(download_by_key)
            + list(parse_by_key)
        )
    )

    final_papers: list[FinalPaperRecord] = []
    for key in keys:
        input_group = inputs_by_key.get(key)
        paper = papers_by_key.get(key)
        access_decision = access_by_key.get(key)
        download_result = download_by_key.get(key)
        parse_result = parse_by_key.get(key)

        doi = _resolve_doi(input_group, paper, access_decision, download_result, parse_result, key)
        status = _determine_status(paper, access_decision, download_result, parse_result)
        failure_type = _determine_failure_type(
            input_group,
            paper,
            access_decision,
            download_result,
            parse_result,
            status,
        )

        final_papers.append(
            FinalPaperRecord(
                doi=doi,
                paper_id=_resolve_paper_id(paper, access_decision, download_result, parse_result),
                title=paper.title if paper is not None else None,
                authors=paper.authors if paper is not None else [],
                year=paper.year if paper is not None else None,
                venue=paper.venue if paper is not None else None,
                publisher=paper.publisher if paper is not None else None,
                access_type=access_decision.access_type if access_decision is not None else None,
                download_strategy=access_decision.download_strategy if access_decision is not None else None,
                access_url=_resolve_access_url(access_decision, paper),
                pdf_path=download_result.file_path if download_result is not None else None,
                parsed_text_path=parse_result.full_text_path if parse_result is not None else None,
                status=status,
                failure_type=failure_type,
                next_action=_determine_next_action(status),
            )
        )

    return sorted(final_papers, key=lambda item: item.doi)


def _build_final_failures(
    final_papers: list[FinalPaperRecord],
    snapshot: ArtifactSnapshot,
) -> list[FinalFailureRecord]:
    failures: list[FinalFailureRecord] = []
    parse_by_key = {
        _record_key(item.doi, item.paper_id): item for item in snapshot.parse_results
    }
    download_by_key = {
        _record_key(item.doi, item.paper_id): item for item in snapshot.download_results
    }

    for paper in final_papers:
        if paper.status in {"parsed", "downloaded", "metadata_resolved", "open_access_pending_download"}:
            continue

        key = _record_key(paper.doi, paper.paper_id)
        parse_result = parse_by_key.get(key)
        download_result = download_by_key.get(key)

        if paper.status == "parse_failed":
            stage = "parse"
            error_message = parse_result.error_message if parse_result is not None else None
        elif paper.status == "download_failed":
            stage = "download"
            error_message = download_result.error_message if download_result is not None else None
        elif paper.status == "metadata_failed":
            stage = "metadata"
            error_message = "No merged paper metadata was produced."
        elif paper.status == "requires_institution_login":
            stage = "access"
            error_message = "Institution-authenticated access is required."
        elif paper.status == "manual_required":
            stage = "access"
            error_message = "Manual review or upload is required."
        else:
            stage = "access"
            error_message = "No legal access path was found."

        failures.append(
            FinalFailureRecord(
                doi=paper.doi,
                paper_id=paper.paper_id,
                status=paper.status,
                failure_stage=stage,
                failure_type=paper.failure_type or "unknown",
                error_message=error_message,
                next_action=paper.next_action,
            )
        )

    return failures


def _build_summary(
    snapshot: ArtifactSnapshot,
    final_papers: list[FinalPaperRecord],
    final_failures: list[FinalFailureRecord],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for item in final_papers:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    failure_counts: dict[str, int] = {}
    for item in final_failures:
        failure_counts[item.failure_type] = failure_counts.get(item.failure_type, 0) + 1

    return {
        "total_inputs": len(snapshot.doi_input_items),
        "unique_final_rows": len(final_papers),
        "final_failures": len(final_failures),
        "status_counts": status_counts,
        "failure_type_counts": failure_counts,
        "artifacts_present": snapshot.artifacts_present,
        "supplement_summary": snapshot.supplement_summary,
        "browser_supplement_summary": snapshot.browser_supplement_summary,
        "manual_handoff_count": snapshot.manual_handoff_count,
    }


def _build_final_report_md(report: RunReport) -> str:
    lines = [
        f"# Run Report: {report.run_id}",
        "",
        "## Summary",
        f"- Generated at: {report.generated_at.isoformat()}",
        f"- Total final rows: {len(report.final_papers)}",
        f"- Final failures: {len(report.final_failures)}",
        "",
        "## Status Counts",
    ]
    for status, count in sorted(report.summary.get("status_counts", {}).items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Failure Type Counts"])
    failure_counts = report.summary.get("failure_type_counts", {})
    if failure_counts:
        for failure_type, count in sorted(failure_counts.items()):
            lines.append(f"- {failure_type}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Artifacts Present"])
    for artifact_name, present in sorted(report.artifacts_present.items()):
        lines.append(f"- {artifact_name}: {'yes' if present else 'no'}")
    supplement_summary = report.summary.get("supplement_summary")
    if isinstance(supplement_summary, dict):
        lines.extend(
            [
                "",
                "## Supplementary Materials",
                f"- articles_with_supplements: {supplement_summary.get('articles_with_supplements', 0)}",
                f"- total_supplement_links: {supplement_summary.get('total_supplement_links', 0)}",
                f"- downloaded_success: {supplement_summary.get('downloaded_success', 0)}",
                f"- downloaded_failed: {supplement_summary.get('downloaded_failed', 0)}",
                f"- extensions_by_count: {supplement_summary.get('extensions_by_count', {})}",
                "- wiley_supplement_report.csv: artifacts/wiley_supplement_report.csv",
            ]
        )
    browser_supplement_summary = report.summary.get("browser_supplement_summary")
    if isinstance(browser_supplement_summary, dict):
        lines.extend(
            [
                "",
                "## Wiley Browser-Assisted Supplementary Materials",
                f"- articles_with_supplements: {browser_supplement_summary.get('articles_with_supplements', 0)}",
                f"- total_supplement_links: {browser_supplement_summary.get('total_supplement_links', 0)}",
                f"- downloaded_success: {browser_supplement_summary.get('downloaded_success', 0)}",
                f"- downloaded_failed: {browser_supplement_summary.get('downloaded_failed', 0)}",
                f"- manual_handoff_count: {report.summary.get('manual_handoff_count', 0)}",
                f"- extensions_by_count: {browser_supplement_summary.get('extensions_by_count', {})}",
                "- wiley_browser_supplement_report.csv: artifacts/wiley_browser_supplement_report.csv",
                "- wiley_manual_handoff.csv: artifacts/wiley_manual_handoff.csv",
            ]
        )
    return "\n".join(lines) + "\n"


def _build_client_summary_md(report: RunReport) -> str:
    parsed_count = report.summary.get("status_counts", {}).get("parsed", 0)
    downloaded_count = report.summary.get("status_counts", {}).get("downloaded", 0)
    manual_count = report.summary.get("status_counts", {}).get("manual_required", 0)
    login_count = report.summary.get("status_counts", {}).get(
        "requires_institution_login",
        0,
    )
    unavailable_count = report.summary.get("status_counts", {}).get("unavailable", 0)
    lines = [
        f"# Client Deliverable Summary: {report.run_id}",
        "",
        f"- Parsed papers ready for downstream analysis: {parsed_count}",
        f"- Ready for downstream analysis: {parsed_count}",
        f"- Downloaded but not parsed yet: {downloaded_count}",
        f"- Need manual review or upload: {manual_count}",
        f"- Need institution login later: {login_count}",
        f"- Currently unavailable: {unavailable_count}",
        "",
        "## Deliverables",
        "- `final_papers.csv`: merged paper-level status table",
        "- `final_failures.csv`: unresolved or failed items",
        "- `final_report.md`: internal run summary",
        "",
        "## Recommended Next Actions",
        "- Parsed rows: Ready for downstream analysis",
        "- Downloaded rows: run `parse-pdfs`",
        "- Manual rows: review or upload PDF",
        "- Institution-login rows: hand off to authenticated workflow later",
    ]
    supplement_summary = report.summary.get("supplement_summary")
    if isinstance(supplement_summary, dict):
        lines.extend(
            [
                "",
                "## Supplementary Materials",
                f"- articles_with_supplements: {supplement_summary.get('articles_with_supplements', 0)}",
                f"- total_supplement_links: {supplement_summary.get('total_supplement_links', 0)}",
                f"- downloaded_success: {supplement_summary.get('downloaded_success', 0)}",
                f"- downloaded_failed: {supplement_summary.get('downloaded_failed', 0)}",
                f"- extensions_by_count: {supplement_summary.get('extensions_by_count', {})}",
                "- wiley_supplement_report.csv: artifacts/wiley_supplement_report.csv",
            ]
        )
    browser_supplement_summary = report.summary.get("browser_supplement_summary")
    if isinstance(browser_supplement_summary, dict):
        lines.extend(
            [
                "",
                "## Wiley Browser-Assisted Supplementary Materials",
                f"- articles_with_supplements: {browser_supplement_summary.get('articles_with_supplements', 0)}",
                f"- total_supplement_links: {browser_supplement_summary.get('total_supplement_links', 0)}",
                f"- downloaded_success: {browser_supplement_summary.get('downloaded_success', 0)}",
                f"- downloaded_failed: {browser_supplement_summary.get('downloaded_failed', 0)}",
                f"- manual_handoff_count: {report.summary.get('manual_handoff_count', 0)}",
                f"- extensions_by_count: {browser_supplement_summary.get('extensions_by_count', {})}",
                "- wiley_browser_supplement_report.csv: artifacts/wiley_browser_supplement_report.csv",
                "- wiley_manual_handoff.csv: artifacts/wiley_manual_handoff.csv",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_csv(items: list[Any], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        if "authors" in row and isinstance(row.get("authors"), list):
            row["authors"] = " | ".join(row["authors"])
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _load_jsonl(path: Path, model_class: type[T]) -> list[T]:
    if not path.exists():
        return []
    items: list[T] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if hasattr(model_class, "model_validate_json"):
            items.append(model_class.model_validate_json(line))  # type: ignore[attr-defined]
    return items


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _count_nonempty_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _aggregate_inputs(doi_input_items: list[DOIInputItem]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in doi_input_items:
        key = item.normalized_doi or f"invalid:{item.row_index}:{item.original}"
        group = grouped.setdefault(
            key,
            {
                "doi": item.normalized_doi or item.original,
                "statuses": set(),
                "originals": [],
            },
        )
        group["statuses"].add(item.status)
        group["originals"].append(item.original)
    return grouped


def _pick_best_map(
    items: list[T],
    *,
    key_fn,
    priority: dict[str, int],
    status_fn,
) -> dict[str, T]:
    selected: dict[str, T] = {}
    for item in items:
        key = key_fn(item)
        if not key:
            continue
        current = selected.get(key)
        if current is None or priority.get(status_fn(item), 0) > priority.get(status_fn(current), 0):
            selected[key] = item
    return selected


def _record_key(doi: str | None, paper_id: str | None) -> str:
    return doi or paper_id or "unknown"


def _resolve_doi(
    input_group: dict[str, Any] | None,
    paper: PaperRecord | None,
    access_decision: AccessDecision | None,
    download_result: DownloadResult | None,
    parse_result: ParseResult | None,
    fallback_key: str,
) -> str:
    if input_group is not None:
        return input_group["doi"]
    for value in [
        paper.doi if paper is not None else None,
        access_decision.doi if access_decision is not None else None,
        download_result.doi if download_result is not None else None,
        parse_result.doi if parse_result is not None else None,
    ]:
        if value:
            return value
    return fallback_key


def _resolve_paper_id(
    paper: PaperRecord | None,
    access_decision: AccessDecision | None,
    download_result: DownloadResult | None,
    parse_result: ParseResult | None,
) -> str | None:
    for value in [
        paper.paper_id if paper is not None else None,
        access_decision.paper_id if access_decision is not None else None,
        download_result.paper_id if download_result is not None else None,
        parse_result.paper_id if parse_result is not None else None,
    ]:
        if value:
            return value
    return None


def _resolve_access_url(access_decision: AccessDecision | None, paper: PaperRecord | None) -> str | None:
    if access_decision is not None and access_decision.access_url:
        return access_decision.access_url
    if paper is not None and paper.source_urls:
        return paper.source_urls[0]
    return None


def _determine_status(
    paper: PaperRecord | None,
    access_decision: AccessDecision | None,
    download_result: DownloadResult | None,
    parse_result: ParseResult | None,
) -> str:
    if parse_result is not None and parse_result.status == "success":
        return "parsed"
    if parse_result is not None and parse_result.status == "failed":
        return "parse_failed"
    if download_result is not None and download_result.status == "success":
        return "downloaded"
    if download_result is not None and download_result.status == "failed":
        return "download_failed"
    if access_decision is not None and access_decision.access_type == "user_authenticated":
        return "requires_institution_login"
    if access_decision is not None and access_decision.access_type == "manual_required":
        return "manual_required"
    if access_decision is not None and access_decision.access_type == "unavailable":
        return "unavailable"
    if access_decision is not None and access_decision.access_type == "open_access":
        return "open_access_pending_download"
    if paper is None:
        return "metadata_failed"
    return "metadata_resolved"


def _determine_failure_type(
    input_group: dict[str, Any] | None,
    paper: PaperRecord | None,
    access_decision: AccessDecision | None,
    download_result: DownloadResult | None,
    parse_result: ParseResult | None,
    status: str,
) -> str | None:
    if parse_result is not None and parse_result.status == "failed":
        return parse_result.error_type or "parse_failed"
    if download_result is not None and download_result.status == "failed":
        return download_result.error_type or "download_failed"
    if status == "metadata_failed":
        if input_group is not None and "invalid" in input_group["statuses"]:
            return "invalid_doi"
        return "metadata_failed"
    if access_decision is not None and access_decision.access_type == "user_authenticated":
        return "requires_institution_login"
    if access_decision is not None and access_decision.access_type == "manual_required":
        return "manual_required"
    if access_decision is not None and access_decision.access_type == "unavailable":
        return "unavailable"
    return None


def _determine_next_action(status: str) -> str:
    if status == "parsed":
        return "Ready for downstream analysis"
    if status == "downloaded":
        return "Run parse-pdfs"
    if status == "requires_institution_login":
        return "Use authenticated download workflow later"
    if status == "manual_required":
        return "Manual review or upload PDF"
    if status == "unavailable":
        return "No legal access path found yet"
    if status == "metadata_failed":
        return "Check DOI validity or metadata providers"
    if status == "open_access_pending_download":
        return "Run download-open-pdfs"
    if status == "download_failed":
        return "Retry open PDF download or inspect source URL"
    if status == "parse_failed":
        return "Inspect PDF and retry parse-pdfs"
    return "Run the next missing workflow step"
