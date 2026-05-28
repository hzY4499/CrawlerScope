from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from crawler_scope.schemas import MetadataSourceResult, PaperRecord

API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
API_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
API_FIELDS = (
    "title,year,authors,abstract,venue,url,externalIds,openAccessPdf,isOpenAccess"
)


def fetch_semantic_scholar_by_doi(
    doi: str,
    api_key: str | None = None,
) -> MetadataSourceResult:
    headers = {"User-Agent": "CrawlerScope/0.1.0"}
    if api_key:
        headers["x-api-key"] = api_key

    paper_identifier = quote(f"DOI:{doi}", safe="")
    url = f"{API_BASE_URL}/{paper_identifier}"

    try:
        response = _request(url, params={"fields": API_FIELDS}, headers=headers)
    except httpx.HTTPStatusError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="semantic_scholar",
            status="failed",
            error_type="http_error",
            error_message=str(exc),
        )
    except httpx.RequestError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="semantic_scholar",
            status="failed",
            error_type="request_error",
            error_message=str(exc),
        )

    if response.status_code == 404:
        return MetadataSourceResult(doi=doi, source="semantic_scholar", status="not_found")
    if response.status_code == 429:
        return MetadataSourceResult(
            doi=doi,
            source="semantic_scholar",
            status="failed",
            error_type="rate_limited",
            error_message="Semantic Scholar rate limited the request.",
        )
    if response.status_code >= 400:
        return MetadataSourceResult(
            doi=doi,
            source="semantic_scholar",
            status="failed",
            error_type=f"http_{response.status_code}",
            error_message=response.text[:500],
        )

    payload = response.json()
    external_ids = payload.get("externalIds", {}) if isinstance(payload, dict) else {}
    paper = PaperRecord(
        paper_id=f"doi:{doi}",
        doi=doi,
        semantic_scholar_id=payload.get("paperId"),
        arxiv_id=external_ids.get("ARXIV") if isinstance(external_ids, dict) else None,
        title=payload.get("title"),
        authors=_extract_authors(payload.get("authors", [])),
        year=payload.get("year"),
        venue=payload.get("venue"),
        abstract=payload.get("abstract"),
        source_urls=_dedupe([payload.get("url"), f"https://doi.org/{doi}"]),
        pdf_urls=_dedupe([_nested_get(payload, "openAccessPdf", "url")]),
        is_open_access=payload.get("isOpenAccess")
        if isinstance(payload.get("isOpenAccess"), bool)
        else None,
        raw=payload,
    )
    return MetadataSourceResult(
        doi=doi,
        source="semantic_scholar",
        status="success",
        paper=paper,
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
)
def _request(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    with _make_client(headers=headers) as client:
        response = client.get(url, params=params)
        if response.status_code >= 500:
            response.raise_for_status()
        return response


def _make_client(*, headers: dict[str, str]) -> httpx.Client:
    return httpx.Client(timeout=API_TIMEOUT, headers=headers, follow_redirects=True)


def _extract_authors(authors: list[dict[str, Any]]) -> list[str]:
    parsed: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if isinstance(name, str) and name.strip():
            parsed.append(name.strip())
    return parsed


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
