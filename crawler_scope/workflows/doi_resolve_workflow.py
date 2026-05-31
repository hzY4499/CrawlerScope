from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from crawler_scope.schemas import DOIResolutionResult, MetadataSourceResult, PaperRecord
from crawler_scope.tools.academic import (
    fetch_crossref_by_doi,
    fetch_openalex_by_doi,
    fetch_semantic_scholar_by_doi,
    fetch_unpaywall_by_doi,
    merge_metadata_results,
)
from crawler_scope.tools.storage import CacheStore, RunStore
from crawler_scope.utils import SimpleRateLimiter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)
SOURCE_FILENAMES = {
    "crossref": "artifacts/crossref_results.jsonl",
    "openalex": "artifacts/openalex_results.jsonl",
    "semantic_scholar": "artifacts/semantic_scholar_results.jsonl",
    "unpaywall": "artifacts/unpaywall_results.jsonl",
}


def resolve_dois_for_run(
    run_id: str,
    *,
    use_cache: bool = True,
    cache_store: CacheStore | None = None,
    rate_limiter: SimpleRateLimiter | None = None,
) -> dict:
    load_dotenv(PROJECT_ROOT / ".env")

    run_dir = RUN_STORE.get_run_dir(run_id)
    valid_dois_path = run_dir / "artifacts" / "valid_dois.txt"
    if not valid_dois_path.exists():
        raise FileNotFoundError(f"Missing valid DOI list: {valid_dois_path}")

    dois = [line.strip() for line in valid_dois_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    contact_email = os.getenv("CONTACT_EMAIL") or None
    semantic_scholar_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY") or None
    resolved_cache_store = cache_store or CacheStore(PROJECT_ROOT / "data" / "cache" / "api")
    resolved_rate_limiter = rate_limiter or SimpleRateLimiter.from_yaml(
        PROJECT_ROOT / "configs" / "rate_limits.yaml"
    )

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "doi_resolve_started",
            "timestamp": _iso_now(),
            "total_dois": len(dois),
            "use_cache": use_cache,
        },
    )
    RUN_STORE.mark_status(run_id, "resolving_metadata", total_dois=len(dois), use_cache=use_cache)

    per_source_results: dict[str, list[MetadataSourceResult]] = {
        source: [] for source in SOURCE_FILENAMES
    }
    combined_results: list[MetadataSourceResult] = []
    merged_papers: list[PaperRecord] = []
    access_hints: list[dict] = []
    resolution_results: list[DOIResolutionResult] = []
    source_success_counts = {source: 0 for source in SOURCE_FILENAMES}
    has_open_pdf = 0
    failed_all_sources = 0
    cache_hits = 0
    cache_misses = 0
    rate_limited_count = 0
    missing_contact_email_count = 0

    fetchers: list[tuple[str, Callable[[str], MetadataSourceResult]]] = [
        (
            "crossref",
            lambda doi: fetch_crossref_by_doi(
                doi,
                contact_email=contact_email,
                use_cache=use_cache,
                cache_store=resolved_cache_store,
            ),
        ),
        (
            "openalex",
            lambda doi: fetch_openalex_by_doi(
                doi,
                contact_email=contact_email,
                use_cache=use_cache,
                cache_store=resolved_cache_store,
            ),
        ),
        (
            "semantic_scholar",
            lambda doi: fetch_semantic_scholar_by_doi(
                doi,
                api_key=semantic_scholar_api_key,
                use_cache=use_cache,
                cache_store=resolved_cache_store,
            ),
        ),
        (
            "unpaywall",
            lambda doi: fetch_unpaywall_by_doi(
                doi,
                contact_email=contact_email,
                use_cache=use_cache,
                cache_store=resolved_cache_store,
            ),
        ),
    ]

    for doi in dois:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "doi_resolve_item_started",
                "timestamp": _iso_now(),
                "doi": doi,
            },
        )

        doi_results: list[MetadataSourceResult] = []
        for source, fetcher in fetchers:
            cache_key = resolved_cache_store.make_key(source, doi)
            cache_hit = bool(use_cache and resolved_cache_store.has(source, cache_key))
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "metadata_query_start",
                    "timestamp": _iso_now(),
                    "doi": doi,
                    "source": source,
                    "use_cache": use_cache,
                    "cache_hit": cache_hit,
                },
            )
            if cache_hit:
                cache_hits += 1
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "metadata_query_cache_hit",
                        "timestamp": _iso_now(),
                        "doi": doi,
                        "source": source,
                    },
                )
            else:
                cache_misses += 1
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "metadata_query_cache_miss",
                        "timestamp": _iso_now(),
                        "doi": doi,
                        "source": source,
                    },
                )
                resolved_rate_limiter.wait(source)

            try:
                result = fetcher(doi)
            except Exception as exc:
                result = MetadataSourceResult(
                    doi=doi,
                    source=source,
                    status="failed",
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )

            if result.status == "success":
                source_success_counts[source] += 1
            if result.error_type == "rate_limited":
                rate_limited_count += 1
            if result.error_type == "missing_contact_email":
                missing_contact_email_count += 1
            if use_cache and not cache_hit and result.status in {"success", "not_found"}:
                RUN_STORE.append_trace(
                    run_id,
                    {
                        "event": "metadata_query_cache_write",
                        "timestamp": _iso_now(),
                        "doi": doi,
                        "source": source,
                        "status": result.status,
                    },
                )

            stored_result = _persist_result(run_id, result)
            per_source_results[source].append(stored_result)
            combined_results.append(stored_result)
            doi_results.append(result)

            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "metadata_query_success"
                    if stored_result.status == "success"
                    else "metadata_query_failed",
                    "timestamp": _iso_now(),
                    "doi": doi,
                    "source": source,
                    "status": stored_result.status,
                    "error_type": stored_result.error_type,
                    "raw_path": stored_result.raw_path,
                },
            )

        merged_paper, access_hint = merge_metadata_results(doi, doi_results)
        if merged_paper is not None:
            merged_papers.append(merged_paper)
        access_hints.append(access_hint.model_dump(mode="json"))

        if access_hint.has_open_pdf:
            has_open_pdf += 1

        all_failed_or_not_found = all(
            result.status in {"failed", "not_found"} for result in doi_results
        )
        if all_failed_or_not_found:
            failed_all_sources += 1

        resolution_results.append(
            DOIResolutionResult(
                doi=doi,
                status=_resolution_status(doi_results, merged_paper),
                crossref_found=any(
                    result.source == "crossref" and result.status == "success"
                    for result in doi_results
                ),
                openalex_found=any(
                    result.source == "openalex" and result.status == "success"
                    for result in doi_results
                ),
                semantic_scholar_found=any(
                    result.source == "semantic_scholar" and result.status == "success"
                    for result in doi_results
                ),
                paper_id=merged_paper.paper_id if merged_paper is not None else None,
                title=merged_paper.title if merged_paper is not None else None,
                error_message=_collect_error_message(doi_results, merged_paper),
            )
        )

        RUN_STORE.append_trace(
            run_id,
            {
                "event": "doi_resolve_item_completed",
                "timestamp": _iso_now(),
                "doi": doi,
                "merged": merged_paper is not None,
                "next_stage": access_hint.next_stage,
            },
        )

    for source, items in per_source_results.items():
        RUN_STORE.save_text(run_id, SOURCE_FILENAMES[source], _jsonl_text(items))
    RUN_STORE.save_text(
        run_id,
        "artifacts/metadata_source_results.jsonl",
        _jsonl_text(combined_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/doi_resolution_results.jsonl",
        _jsonl_text(resolution_results),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/papers_metadata_merged.jsonl",
        _jsonl_text(merged_papers),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/access_hints.jsonl",
        _jsonl_text(access_hints),
    )
    _write_papers_csv(run_id, merged_papers)

    summary = {
        "total_dois": len(dois),
        "crossref_success": source_success_counts["crossref"],
        "openalex_success": source_success_counts["openalex"],
        "semantic_scholar_success": source_success_counts["semantic_scholar"],
        "unpaywall_success": source_success_counts["unpaywall"],
        "merged_success": len(merged_papers),
        "has_open_pdf": has_open_pdf,
        "failed_all_sources": failed_all_sources,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "rate_limited_count": rate_limited_count,
        "missing_contact_email_count": missing_contact_email_count,
    }
    RUN_STORE.save_json(run_id, "artifacts/metadata_summary.json", summary)
    RUN_STORE.mark_status(run_id, "completed", summary=summary)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "doi_resolve_completed",
            "timestamp": _iso_now(),
            **summary,
        },
    )
    return summary


def _persist_result(run_id: str, result: MetadataSourceResult) -> MetadataSourceResult:
    if result.paper is None:
        return result

    safe_name = _safe_filename(result.doi)
    raw_relative_path = f"artifacts/raw/{result.source}/{safe_name}.json"
    RUN_STORE.save_json(run_id, raw_relative_path, result.paper.raw)

    summarized_paper = result.paper.model_copy(
        update={
            "raw": {
                "source": result.source,
                "keys": sorted(result.paper.raw.keys())[:25]
                if isinstance(result.paper.raw, dict)
                else [],
            }
        }
    )
    return result.model_copy(update={"paper": summarized_paper, "raw_path": raw_relative_path})


def _resolution_status(
    results: list[MetadataSourceResult],
    merged_paper: PaperRecord | None,
) -> str:
    if merged_paper is not None:
        return "resolved"
    if all(result.status == "not_found" for result in results):
        return "not_found"
    return "failed"


def _collect_error_message(
    results: list[MetadataSourceResult],
    merged_paper: PaperRecord | None,
) -> str | None:
    if merged_paper is not None:
        return None
    messages = [
        f"{result.source}:{result.error_type or result.status}"
        for result in results
        if result.status != "success"
    ]
    return "; ".join(messages) or None


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _jsonl_text(items: list[object]) -> str:
    lines: list[str] = []
    for item in items:
        if hasattr(item, "model_dump_json"):
            lines.append(item.model_dump_json())
        else:
            lines.append(json.dumps(item, ensure_ascii=False))
    return "".join(f"{line}\n" for line in lines)


def _write_papers_csv(run_id: str, papers: list[PaperRecord]) -> None:
    target = RUN_STORE.get_run_dir(run_id) / "artifacts" / "papers_metadata.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "paper_id",
        "doi",
        "openalex_id",
        "semantic_scholar_id",
        "arxiv_id",
        "title",
        "authors",
        "year",
        "venue",
        "publisher",
        "abstract",
        "source_urls",
        "pdf_urls",
        "is_open_access",
        "license",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for paper in papers:
            writer.writerow(
                {
                    "paper_id": paper.paper_id,
                    "doi": paper.doi,
                    "openalex_id": paper.openalex_id,
                    "semantic_scholar_id": paper.semantic_scholar_id,
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "authors": " | ".join(paper.authors),
                    "year": paper.year,
                    "venue": paper.venue,
                    "publisher": paper.publisher,
                    "abstract": paper.abstract,
                    "source_urls": " | ".join(paper.source_urls),
                    "pdf_urls": " | ".join(paper.pdf_urls),
                    "is_open_access": paper.is_open_access,
                    "license": paper.license,
                }
            )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
