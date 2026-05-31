from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from crawler_scope.schemas import MetadataSourceResult, PaperRecord
from crawler_scope.tools.storage import CacheStore

API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
API_BASE_URL = "https://api.unpaywall.org/v2"
SOURCE = "unpaywall"


def fetch_unpaywall_by_doi(
    doi: str,
    contact_email: str | None,
    use_cache: bool = True,
    cache_store: CacheStore | None = None,
) -> MetadataSourceResult:
    if not contact_email:
        return MetadataSourceResult(
            doi=doi,
            source=SOURCE,
            status="failed",
            error_type="missing_contact_email",
            error_message="CONTACT_EMAIL is required for Unpaywall requests.",
        )

    cache_key: str | None = None
    if use_cache:
        cache_store = cache_store or CacheStore()
        cache_key = cache_store.make_key(SOURCE, doi)
        cached = cache_store.get_json(SOURCE, cache_key)
        if cached is not None:
            return _result_from_cached(doi, cached)

    url = f"{API_BASE_URL}/{quote(doi, safe='')}"
    headers = {"User-Agent": f"CrawlerScope/0.1.0 (mailto:{contact_email})"}

    try:
        response = _request(url, params={"email": contact_email}, headers=headers)
    except httpx.HTTPStatusError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="unpaywall",
            status="failed",
            error_type="http_error",
            error_message=str(exc),
        )
    except httpx.RequestError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="unpaywall",
            status="failed",
            error_type="request_error",
            error_message=str(exc),
        )

    if response.status_code == 404:
        _cache_response(cache_store, cache_key, response.status_code, _safe_json(response))
        return MetadataSourceResult(doi=doi, source=SOURCE, status="not_found")
    if response.status_code == 429:
        return MetadataSourceResult(
            doi=doi,
            source=SOURCE,
            status="failed",
            error_type="rate_limited",
            error_message="Unpaywall rate limited the request.",
        )
    if response.status_code >= 400:
        return MetadataSourceResult(
            doi=doi,
            source=SOURCE,
            status="failed",
            error_type=f"http_{response.status_code}",
            error_message=response.text[:500],
        )

    payload = response.json()
    _cache_response(cache_store, cache_key, response.status_code, payload)
    return _paper_from_payload(doi, payload)


def _result_from_cached(doi: str, cached: dict[str, Any]) -> MetadataSourceResult:
    status_code = cached.get("status_code")
    payload = cached.get("payload")
    if status_code == 404:
        return MetadataSourceResult(doi=doi, source=SOURCE, status="not_found")
    if status_code == 200 and isinstance(payload, dict):
        return _paper_from_payload(doi, payload)
    return MetadataSourceResult(
        doi=doi,
        source=SOURCE,
        status="failed",
        error_type="cache_error",
        error_message="Cached Unpaywall response is not usable.",
    )


def _paper_from_payload(doi: str, payload: dict[str, Any]) -> MetadataSourceResult:
    best_oa_location = payload.get("best_oa_location") or {}
    oa_locations = payload.get("oa_locations") or []
    paper = PaperRecord(
        paper_id=f"doi:{doi}",
        doi=doi,
        title=payload.get("title"),
        year=payload.get("year"),
        venue=payload.get("journal_name"),
        publisher=payload.get("publisher"),
        source_urls=_dedupe(
            [
                payload.get("doi_url"),
                best_oa_location.get("url_for_landing_page")
                if isinstance(best_oa_location, dict)
                else None,
                *[
                    location.get("url_for_landing_page")
                    for location in oa_locations
                    if isinstance(location, dict)
                ],
            ]
        ),
        pdf_urls=_dedupe(
            [
                best_oa_location.get("url_for_pdf")
                if isinstance(best_oa_location, dict)
                else None,
                *[
                    location.get("url_for_pdf")
                    for location in oa_locations
                    if isinstance(location, dict)
                ],
            ]
        ),
        is_open_access=payload.get("is_oa")
        if isinstance(payload.get("is_oa"), bool)
        else None,
        license=_first_available(
            [
                best_oa_location.get("license") if isinstance(best_oa_location, dict) else None,
                *[
                    location.get("license")
                    for location in oa_locations
                    if isinstance(location, dict)
                ],
            ]
        ),
        raw=payload,
    )
    return MetadataSourceResult(doi=doi, source=SOURCE, status="success", paper=paper)


def _cache_response(
    cache_store: CacheStore | None,
    cache_key: str | None,
    status_code: int,
    payload: dict[str, Any],
) -> None:
    if cache_store is None or cache_key is None:
        return
    cache_store.set_json(
        SOURCE,
        cache_key,
        {
            "source": SOURCE,
            "status_code": status_code,
            "payload": payload,
        },
    )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text[:500]}
    return payload if isinstance(payload, dict) else {"payload": payload}


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


def _first_available(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
