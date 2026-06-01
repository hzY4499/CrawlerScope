from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crawler_scope.schemas import (
    PaperRecord,
    RequirementSpec,
    SupplementDownloadResult,
    SupplementRecord,
    SupplementSummary,
)
from crawler_scope.tools.publishers import (
    SupplementDiscoveryError,
    build_wiley_article_url_from_doi,
    discover_wiley_supplements,
    download_supplement_file,
)
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)
PDF_DOC_ONLY_EXTENSIONS = {".pdf", ".doc", ".docx"}


def collect_wiley_supplements_for_run(
    run_id: str,
    output_dir: Path | None = None,
    all_formats: bool = True,
    max_articles: int | None = None,
) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    papers_path = run_dir / "artifacts" / "papers_metadata_merged.jsonl"
    valid_dois_path = run_dir / "artifacts" / "valid_dois.txt"
    resolved_output_dir = (output_dir or (PROJECT_ROOT / "data" / "raw" / "supplements")).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    candidates = _load_candidates(papers_path, valid_dois_path)
    if max_articles is not None:
        candidates = candidates[:max_articles]

    requirement = RequirementSpec(
        requirement_id=f"requirement_{run_id}_wiley_supplements",
        task_type="wiley_supplement_crawl",
        publisher="wiley",
        supplement_policy="all_formats" if all_formats else "pdf_doc_only",
        allowed_file_extensions=[] if all_formats else sorted(PDF_DOC_ONLY_EXTENSIONS),
    )

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "wiley_supplement_collection_started",
            "timestamp": _iso_now(),
            "total_candidate_articles": len(candidates),
            "all_formats": all_formats,
            "max_articles": max_articles,
            "output_dir": str(resolved_output_dir),
            "requirement": requirement.model_dump(mode="json"),
        },
    )
    RUN_STORE.mark_status(
        run_id,
        "collecting_wiley_supplements",
        all_formats=all_formats,
        supplement_output_dir=str(resolved_output_dir),
    )

    supplement_records: list[SupplementRecord] = []
    download_results: list[SupplementDownloadResult] = []
    success_results: list[SupplementDownloadResult] = []
    failed_results: list[SupplementDownloadResult] = []
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
                "event": "supplement_discovery_start",
                "timestamp": _iso_now(),
                "doi": doi,
                "paper_id": paper_id,
                "article_url": article_url,
            },
        )

        try:
            discovered = discover_wiley_supplements(doi, article_url=article_url)
        except SupplementDiscoveryError as exc:
            failures_by_type[exc.error_type] += 1
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "supplement_discovery_failed",
                    "timestamp": _iso_now(),
                    "doi": doi,
                    "paper_id": paper_id,
                    "article_url": article_url,
                    "error_type": exc.error_type,
                    "error_message": str(exc),
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
                "event": "supplement_discovery_success",
                "timestamp": _iso_now(),
                "doi": doi,
                "paper_id": paper_id,
                "article_url": article_url,
                "discovered_count": len(normalized_records),
            },
        )

        for record in normalized_records:
            if not all_formats and record.extension not in PDF_DOC_ONLY_EXTENSIONS:
                skipped_result = SupplementDownloadResult(
                    doi=record.doi,
                    paper_id=record.paper_id,
                    supplement_url=record.supplement_url,
                    status="skipped",
                    filename=record.filename,
                    extension=record.extension,
                    content_type=record.content_type,
                    error_message="Skipped by pdf_doc_only supplement policy.",
                    downloaded_at=datetime.now(timezone.utc),
                )
                download_results.append(skipped_result)
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "supplement_download_skipped",
                        "timestamp": _iso_now(),
                        "doi": record.doi,
                        "paper_id": record.paper_id,
                        "supplement_url": record.supplement_url,
                        "reason": skipped_result.error_message,
                    },
                )
                continue

            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "supplement_download_start",
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
                        "event": "supplement_download_success",
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
                        "event": "supplement_download_failed",
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
        "artifacts/wiley_supplement_records.jsonl",
        _jsonl_text(supplement_records),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_supplement_download_results.jsonl",
        _jsonl_text(download_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_supplement_success.jsonl",
        _jsonl_text(success_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_supplement_failed.jsonl",
        _jsonl_text(failed_results),
    )

    summary = SupplementSummary(
        total_articles=len(candidates),
        articles_with_supplements=articles_with_supplements,
        total_supplement_links=len(supplement_records),
        downloaded_success=len(success_results),
        downloaded_failed=len(failed_results),
        skipped=sum(1 for item in download_results if item.status == "skipped"),
        failures_by_type=dict(failures_by_type),
        extensions_by_count=dict(extensions_by_count),
    )
    RUN_STORE.save_json(run_id, "artifacts/wiley_supplement_summary.json", summary)
    _write_report_csv(run_id, supplement_records, download_results)
    RUN_STORE.mark_status(
        run_id,
        "completed",
        wiley_supplement_summary=summary.model_dump(mode="json"),
    )
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "wiley_supplement_collection_completed",
            "timestamp": _iso_now(),
            **summary.model_dump(mode="json"),
        },
    )
    return summary.model_dump(mode="json")


def _load_candidates(papers_path: Path, valid_dois_path: Path) -> list[dict[str, str | None]]:
    if papers_path.exists():
        papers = _load_jsonl_models(papers_path, PaperRecord)
        return [
            {
                "doi": paper.doi,
                "paper_id": paper.paper_id,
                "article_url": _find_wiley_url(paper),
            }
            for paper in papers
            if _is_wiley_paper(paper)
        ]

    if not valid_dois_path.exists():
        raise FileNotFoundError(
            f"Missing Wiley supplement inputs: {papers_path} and {valid_dois_path}"
        )

    dois = [line.strip() for line in valid_dois_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"doi": doi, "paper_id": None, "article_url": None} for doi in dois]


def _is_wiley_paper(paper: PaperRecord) -> bool:
    publisher = (paper.publisher or "").lower()
    venue = (paper.venue or "").lower()
    urls = " ".join(paper.source_urls).lower()
    return (
        "wiley" in publisher
        or "wiley" in venue
        or "onlinelibrary.wiley.com" in urls
    )


def _find_wiley_url(paper: PaperRecord) -> str | None:
    for url in paper.source_urls:
        if "onlinelibrary.wiley.com" in url.lower():
            return url
    return None


def _load_jsonl_models(path: Path, model_class: type[PaperRecord]) -> list[Any]:
    items: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(model_class.model_validate_json(line))
    return items


def _jsonl_text(items: list[Any]) -> str:
    lines: list[str] = []
    for item in items:
        if hasattr(item, "model_dump_json"):
            lines.append(item.model_dump_json())
        else:
            lines.append(json.dumps(item, ensure_ascii=False))
    return "".join(f"{line}\n" for line in lines)


def _write_report_csv(
    run_id: str,
    records: list[SupplementRecord],
    results: list[SupplementDownloadResult],
) -> None:
    records_by_url = {record.supplement_url: record for record in records}
    target = RUN_STORE.get_run_dir(run_id) / "artifacts" / "wiley_supplement_report.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "doi",
        "paper_id",
        "article_url",
        "supplement_url",
        "label",
        "filename",
        "extension",
        "content_type",
        "status",
        "file_path",
        "sha256",
        "size_bytes",
        "error_type",
        "error_message",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            record = records_by_url.get(result.supplement_url)
            writer.writerow(
                {
                    "doi": result.doi or (record.doi if record is not None else None),
                    "paper_id": result.paper_id or (record.paper_id if record is not None else None),
                    "article_url": record.article_url if record is not None else None,
                    "supplement_url": result.supplement_url,
                    "label": record.label if record is not None else None,
                    "filename": result.filename or (record.filename if record is not None else None),
                    "extension": result.extension or (record.extension if record is not None else None),
                    "content_type": result.content_type or (record.content_type if record is not None else None),
                    "status": result.status,
                    "file_path": result.file_path,
                    "sha256": result.sha256,
                    "size_bytes": result.size_bytes,
                    "error_type": result.error_type,
                    "error_message": result.error_message,
                }
            )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
