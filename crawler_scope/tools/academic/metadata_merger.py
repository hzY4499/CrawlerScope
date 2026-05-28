from __future__ import annotations

from typing import Any

from crawler_scope.schemas import AccessHint, MetadataSourceResult, PaperRecord

TITLE_PRIORITY = ("crossref", "openalex", "semantic_scholar", "unpaywall")
AUTHORS_PRIORITY = ("crossref", "openalex", "semantic_scholar")
YEAR_PRIORITY = ("crossref", "openalex", "semantic_scholar", "unpaywall")
ABSTRACT_PRIORITY = ("semantic_scholar", "openalex", "crossref")
LICENSE_PRIORITY = ("unpaywall", "openalex", "crossref")


def merge_metadata_results(
    doi: str,
    results: list[MetadataSourceResult],
) -> tuple[PaperRecord | None, AccessHint]:
    successful = {
        result.source: result.paper
        for result in results
        if result.status == "success" and result.paper is not None
    }

    source_urls = _dedupe(
        [
            url
            for result in results
            for url in (result.paper.source_urls if result.paper is not None else [])
        ]
    )
    pdf_urls = _dedupe(
        [
            url
            for result in results
            for url in (result.paper.pdf_urls if result.paper is not None else [])
        ]
    )
    oa_landing_pages = _collect_oa_landing_pages(results)
    evidence_sources = [
        result.source
        for result in results
        if result.status == "success"
        and (
            (result.paper and (result.paper.pdf_urls or result.paper.source_urls))
            or result.raw_path is not None
        )
    ]

    access_hint = AccessHint(
        doi=doi,
        has_open_pdf=bool(pdf_urls),
        open_pdf_urls=pdf_urls,
        oa_landing_pages=oa_landing_pages,
        publisher_urls=source_urls,
        license=_pick_field(results, "license", LICENSE_PRIORITY),
        evidence_sources=_dedupe(evidence_sources),
        next_stage=_determine_next_stage(results, pdf_urls, oa_landing_pages, source_urls),
    )

    if not successful:
        return None, access_hint

    merged_paper = PaperRecord(
        paper_id=f"doi:{doi}",
        doi=doi,
        openalex_id=_pick_field(results, "openalex_id", ("openalex",)),
        semantic_scholar_id=_pick_field(results, "semantic_scholar_id", ("semantic_scholar",)),
        arxiv_id=_pick_field(results, "arxiv_id", ("semantic_scholar",)),
        title=_pick_field(results, "title", TITLE_PRIORITY),
        authors=_pick_list_field(results, "authors", AUTHORS_PRIORITY),
        year=_pick_field(results, "year", YEAR_PRIORITY),
        venue=_pick_field(results, "venue", TITLE_PRIORITY),
        publisher=_pick_field(results, "publisher", TITLE_PRIORITY),
        abstract=_pick_field(results, "abstract", ABSTRACT_PRIORITY),
        source_urls=source_urls,
        pdf_urls=pdf_urls,
        is_open_access=_merge_open_access(results),
        license=access_hint.license,
        raw={
            result.source: _summarize_source_result(result)
            for result in results
        },
    )
    return merged_paper, access_hint


def _pick_field(
    results: list[MetadataSourceResult],
    field_name: str,
    priority: tuple[str, ...],
) -> Any:
    for source in priority:
        for result in results:
            if result.source != source or result.paper is None:
                continue
            value = getattr(result.paper, field_name)
            if isinstance(value, str):
                if value.strip():
                    return value
            elif value is not None:
                return value
    return None


def _pick_list_field(
    results: list[MetadataSourceResult],
    field_name: str,
    priority: tuple[str, ...],
) -> list[str]:
    for source in priority:
        for result in results:
            if result.source != source or result.paper is None:
                continue
            value = getattr(result.paper, field_name)
            if isinstance(value, list) and value:
                return _dedupe([item for item in value if isinstance(item, str)])
    return []


def _merge_open_access(results: list[MetadataSourceResult]) -> bool | None:
    values = [
        result.paper.is_open_access
        for result in results
        if result.paper is not None and result.paper.is_open_access is not None
    ]
    if not values:
        return None
    return any(values)


def _collect_oa_landing_pages(results: list[MetadataSourceResult]) -> list[str]:
    landing_pages: list[str] = []
    for result in results:
        paper = result.paper
        if paper is None:
            continue
        raw = paper.raw if isinstance(paper.raw, dict) else {}
        if result.source == "openalex":
            locations = raw.get("locations") if isinstance(raw, dict) else []
            landing_pages.extend(
                _dedupe(
                    [
                        _nested_get(raw, "primary_location", "landing_page_url"),
                        _nested_get(raw, "best_oa_location", "landing_page_url"),
                        *[
                            location.get("landing_page_url")
                            for location in (locations or [])
                            if isinstance(location, dict)
                        ],
                    ]
                )
            )
        elif result.source == "unpaywall":
            best_oa_location = raw.get("best_oa_location") if isinstance(raw, dict) else {}
            oa_locations = raw.get("oa_locations") if isinstance(raw, dict) else []
            landing_pages.extend(
                _dedupe(
                    [
                        best_oa_location.get("url_for_landing_page")
                        if isinstance(best_oa_location, dict)
                        else None,
                        *[
                            location.get("url_for_landing_page")
                            for location in (oa_locations or [])
                            if isinstance(location, dict)
                        ],
                    ]
                )
            )
    return _dedupe(landing_pages)


def _summarize_source_result(result: MetadataSourceResult) -> dict[str, Any]:
    paper = result.paper
    if paper is None:
        return {
            "status": result.status,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "raw_path": result.raw_path,
        }

    return {
        "status": result.status,
        "paper_id": paper.paper_id,
        "title": paper.title,
        "year": paper.year,
        "source_urls_count": len(paper.source_urls),
        "pdf_urls_count": len(paper.pdf_urls),
        "license": paper.license,
        "raw_path": result.raw_path,
    }


def _determine_next_stage(
    results: list[MetadataSourceResult],
    pdf_urls: list[str],
    oa_landing_pages: list[str],
    publisher_urls: list[str],
) -> str:
    if pdf_urls:
        return "download_open_pdf"
    if oa_landing_pages or publisher_urls:
        return "resolve_access"
    if all(result.status in {"failed", "not_found"} for result in results):
        return "manual_review"
    return "resolve_access"


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _dedupe(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped
