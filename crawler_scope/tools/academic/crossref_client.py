from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from crawler_scope.schemas import MetadataSourceResult, PaperRecord

API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
API_BASE_URL = "https://api.crossref.org/works"


def fetch_crossref_by_doi(doi: str, contact_email: str | None = None) -> MetadataSourceResult:
    params: dict[str, str] = {}
    if contact_email:
        params["mailto"] = contact_email

    headers = {"User-Agent": _build_user_agent(contact_email)}
    url = f"{API_BASE_URL}/{quote(doi, safe='')}"

    try:
        response = _request(url, params=params, headers=headers)
    except httpx.HTTPStatusError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="crossref",
            status="failed",
            error_type="http_error",
            error_message=str(exc),
        )
    except httpx.RequestError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="crossref",
            status="failed",
            error_type="request_error",
            error_message=str(exc),
        )

    if response.status_code == 404:
        return MetadataSourceResult(doi=doi, source="crossref", status="not_found")
    if response.status_code == 429:
        return MetadataSourceResult(
            doi=doi,
            source="crossref",
            status="failed",
            error_type="rate_limited",
            error_message="Crossref rate limited the request.",
        )
    if response.status_code >= 400:
        return MetadataSourceResult(
            doi=doi,
            source="crossref",
            status="failed",
            error_type=f"http_{response.status_code}",
            error_message=response.text[:500],
        )

    payload = response.json()
    message = payload.get("message", {})
    paper = PaperRecord(
        paper_id=f"doi:{doi}",
        doi=doi,
        title=_first_text(message.get("title")),
        authors=_parse_crossref_authors(message.get("author", [])),
        year=_extract_crossref_year(message),
        venue=_first_text(message.get("container-title")),
        publisher=message.get("publisher"),
        source_urls=_dedupe(
            [
                message.get("URL"),
                _nested_get(message, "resource", "primary", "URL"),
                *[link.get("URL") for link in message.get("link", []) if isinstance(link, dict)],
            ]
        ),
        pdf_urls=_extract_crossref_pdf_urls(message.get("link", [])),
        license=_extract_crossref_license(message),
        raw=message,
    )
    return MetadataSourceResult(doi=doi, source="crossref", status="success", paper=paper)


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


def _build_user_agent(contact_email: str | None) -> str:
    if contact_email:
        return f"CrawlerScope/0.1.0 (mailto:{contact_email})"
    return "CrawlerScope/0.1.0"


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_crossref_authors(authors: list[dict[str, Any]]) -> list[str]:
    parsed: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = " ".join(
            part for part in [author.get("given"), author.get("family")] if isinstance(part, str) and part.strip()
        ).strip()
        if not name:
            name = str(author.get("name") or "").strip()
        if name:
            parsed.append(name)
    return parsed


def _extract_crossref_year(message: dict[str, Any]) -> int | None:
    for key in ["published-print", "published-online", "issued", "created"]:
        year = _extract_date_year(message.get(key))
        if year is not None:
            return year
    return None


def _extract_date_year(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    date_parts = value.get("date-parts")
    if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
        first = date_parts[0][0]
        if isinstance(first, int):
            return first
    return None


def _extract_crossref_pdf_urls(links: list[dict[str, Any]]) -> list[str]:
    pdf_urls: list[str] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("URL")
        content_type = str(link.get("content-type") or "").lower()
        if isinstance(url, str) and (
            "pdf" in content_type or url.lower().endswith(".pdf")
        ):
            pdf_urls.append(url)
    return _dedupe(pdf_urls)


def _extract_crossref_license(message: dict[str, Any]) -> str | None:
    licenses = message.get("license")
    if isinstance(licenses, list):
        for item in licenses:
            if not isinstance(item, dict):
                continue
            url = item.get("URL")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None


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
