from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from crawler_scope.schemas import MetadataSourceResult, PaperRecord
from crawler_scope.tools.storage import CacheStore

API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
API_BASE_URL = "https://api.openalex.org/works"
SOURCE = "openalex"


def fetch_openalex_by_doi(
    doi: str,
    contact_email: str | None = None,
    use_cache: bool = True,
    cache_store: CacheStore | None = None,
) -> MetadataSourceResult:
    cache_key: str | None = None
    if use_cache:
        cache_store = cache_store or CacheStore()
        cache_key = cache_store.make_key(SOURCE, doi)
        cached = cache_store.get_json(SOURCE, cache_key)
        if cached is not None:
            return _result_from_cached(doi, cached)

    params: dict[str, str] = {}
    if contact_email:
        params["mailto"] = contact_email

    headers = {"User-Agent": _build_user_agent(contact_email)}
    work_identifier = quote(f"https://doi.org/{doi}", safe="")
    url = f"{API_BASE_URL}/{work_identifier}"

    try:
        response = _request(url, params=params, headers=headers)
    except httpx.HTTPStatusError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="openalex",
            status="failed",
            error_type="http_error",
            error_message=str(exc),
        )
    except httpx.RequestError as exc:
        return MetadataSourceResult(
            doi=doi,
            source="openalex",
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
            error_message="OpenAlex rate limited the request.",
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
        error_message="Cached OpenAlex response is not usable.",
    )


def _paper_from_payload(doi: str, payload: dict[str, Any]) -> MetadataSourceResult:
    paper = PaperRecord(
        paper_id=f"doi:{doi}",
        doi=doi,
        openalex_id=payload.get("id"),
        title=payload.get("display_name"),
        authors=_extract_authors(payload.get("authorships", [])),
        year=payload.get("publication_year"),
        venue=_first_available(
            [
                _nested_get(payload, "primary_location", "source", "display_name"),
                _nested_get(payload, "best_oa_location", "source", "display_name"),
            ]
        ),
        publisher=_first_available(
            [
                _nested_get(payload, "primary_location", "source", "host_organization_name"),
                _nested_get(payload, "best_oa_location", "source", "host_organization_name"),
            ]
        ),
        abstract=_reconstruct_abstract(payload.get("abstract_inverted_index")),
        source_urls=_dedupe(
            [
                payload.get("doi"),
                _nested_get(payload, "primary_location", "landing_page_url"),
                _nested_get(payload, "best_oa_location", "landing_page_url"),
                *[
                    location.get("landing_page_url")
                    for location in payload.get("locations", [])
                    if isinstance(location, dict)
                ],
            ]
        ),
        pdf_urls=_dedupe(
            [
                _nested_get(payload, "primary_location", "pdf_url"),
                _nested_get(payload, "best_oa_location", "pdf_url"),
                *[
                    location.get("pdf_url")
                    for location in payload.get("locations", [])
                    if isinstance(location, dict)
                ],
            ]
        ),
        is_open_access=bool(_nested_get(payload, "open_access", "is_oa"))
        if isinstance(_nested_get(payload, "open_access", "is_oa"), bool)
        else None,
        license=_first_available(
            [
                _nested_get(payload, "best_oa_location", "license"),
                _nested_get(payload, "primary_location", "license"),
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


def _build_user_agent(contact_email: str | None) -> str:
    if contact_email:
        return f"CrawlerScope/0.1.0 (mailto:{contact_email})"
    return "CrawlerScope/0.1.0"


def _extract_authors(authorships: list[dict[str, Any]]) -> list[str]:
    authors: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        display_name = _nested_get(authorship, "author", "display_name")
        if isinstance(display_name, str) and display_name.strip():
            authors.append(display_name.strip())
    return authors


def _reconstruct_abstract(abstract_inverted_index: Any) -> str | None:
    if not isinstance(abstract_inverted_index, dict) or not abstract_inverted_index:
        return None
    tokens: list[tuple[int, str]] = []
    for word, positions in abstract_inverted_index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                tokens.append((position, word))
    if not tokens:
        return None
    ordered = [word for _, word in sorted(tokens)]
    return " ".join(ordered)


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


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
