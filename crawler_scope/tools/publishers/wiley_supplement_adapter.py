from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from crawler_scope.schemas import SupplementDownloadResult, SupplementRecord

ARTICLE_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
USER_AGENT = "CrawlerScope/0.1.0"

TEXT_HINTS = [
    "supporting information",
    "supplementary material",
    "supplementary materials",
    "additional supporting information",
    "table s",
    "figure s",
    "appendix s",
    "data s",
    "movie",
    "audio",
    "video",
    "dataset",
    "file",
]
HREF_HINTS = [
    "support",
    "supp",
    "supinfo",
    "supmat",
    "media",
    "asset",
    "pb-assets",
]
ACCESS_BLOCK_PATTERNS = [
    "captcha",
    "access denied",
    "bot challenge",
    "verify you are human",
    "human verification",
]


class SupplementDiscoveryError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def build_wiley_article_url_from_doi(doi: str) -> str:
    return f"https://onlinelibrary.wiley.com/doi/{quote(doi, safe='')}"


def discover_wiley_supplements(
    doi: str,
    article_url: str | None = None,
    timeout_seconds: float = 30.0,
) -> list[SupplementRecord]:
    target_url = article_url or build_wiley_article_url_from_doi(doi)
    headers = {"User-Agent": USER_AGENT}

    try:
        with _make_client(timeout=httpx.Timeout(timeout_seconds, connect=10.0), headers=headers) as client:
            response = client.get(target_url)
    except httpx.TimeoutException as exc:
        raise SupplementDiscoveryError("download_timeout", str(exc)) from exc
    except httpx.RequestError as exc:
        raise SupplementDiscoveryError("network_error", str(exc)) from exc

    if response.status_code == 403:
        raise SupplementDiscoveryError("download_403", "Wiley access denied the article page request.")
    if response.status_code == 404:
        raise SupplementDiscoveryError("not_found", "Wiley article page was not found.")
    if response.status_code == 429:
        raise SupplementDiscoveryError("rate_limited", "Wiley rate limited the article page request.")
    if response.status_code >= 400:
        raise SupplementDiscoveryError(
            f"http_{response.status_code}",
            f"Wiley article page request failed with HTTP {response.status_code}.",
        )

    html = response.text
    lowered_html = html.lower()
    if any(pattern in lowered_html for pattern in ACCESS_BLOCK_PATTERNS):
        raise SupplementDiscoveryError(
            "access_challenge",
            "Wiley page presented a CAPTCHA or access challenge.",
        )

    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()
    records: list[SupplementRecord] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute_url = urljoin(str(response.url), href)
        if absolute_url in seen_urls:
            continue
        if not _looks_like_supplement_link(anchor, absolute_url):
            continue

        seen_urls.add(absolute_url)
        filename = _guess_filename(absolute_url, None)
        extension = _extract_extension(filename)
        records.append(
            SupplementRecord(
                doi=doi,
                article_url=str(response.url),
                supplement_url=absolute_url,
                label=_clean_text(anchor.get_text(" ", strip=True)),
                filename=filename,
                extension=extension,
                content_type=None,
                source_section=_find_source_section(anchor),
                discovered_at=datetime.now(timezone.utc),
            )
        )

    return records


def download_supplement_file(
    record: SupplementRecord,
    output_dir: Path,
    timeout_seconds: float = 60.0,
    max_bytes: int | None = None,
) -> SupplementDownloadResult:
    if not record.supplement_url:
        return SupplementDownloadResult(
            doi=record.doi,
            paper_id=record.paper_id,
            supplement_url=record.supplement_url,
            status="failed",
            error_type="missing_url",
            error_message="Supplement URL is required.",
            downloaded_at=datetime.now(timezone.utc),
        )

    parsed = urlparse(record.supplement_url)
    if parsed.scheme not in {"http", "https"}:
        return SupplementDownloadResult(
            doi=record.doi,
            paper_id=record.paper_id,
            supplement_url=record.supplement_url,
            status="failed",
            error_type="invalid_url",
            error_message="Supplement URL must use http or https.",
            downloaded_at=datetime.now(timezone.utc),
        )

    target_dir = output_dir / _safe_identifier(record.paper_id or record.doi or "unknown")
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f"{hashlib.sha256(record.supplement_url.encode('utf-8')).hexdigest()[:12]}.part"

    headers = {"User-Agent": USER_AGENT}
    hasher = hashlib.sha256()
    size_bytes = 0
    content_type: str | None = None
    final_url = record.supplement_url
    response_filename: str | None = None

    try:
        with _make_client(timeout=httpx.Timeout(timeout_seconds, connect=15.0), headers=headers) as client:
            with client.stream("GET", record.supplement_url) as response:
                final_url = str(response.url)
                content_type = response.headers.get("content-type")
                response_filename = _filename_from_content_disposition(
                    response.headers.get("content-disposition")
                )

                if response.status_code == 403:
                    return _failed_download(record, "download_403", "HTTP 403 from supplement URL.")
                if response.status_code == 404:
                    return _failed_download(record, "download_404", "HTTP 404 from supplement URL.")
                if response.status_code == 429:
                    return _failed_download(record, "rate_limited", "HTTP 429 from supplement URL.")
                if response.status_code >= 400:
                    return _failed_download(
                        record,
                        "not_found",
                        f"HTTP {response.status_code} from supplement URL.",
                    )

                with temp_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        size_bytes += len(chunk)
                        if max_bytes is not None and size_bytes > max_bytes:
                            raise SupplementDiscoveryError("file_too_large", "Supplement exceeds max_bytes.")
                        handle.write(chunk)
                        hasher.update(chunk)
    except httpx.TimeoutException as exc:
        if temp_path.exists():
            temp_path.unlink()
        return _failed_download(record, "download_timeout", str(exc))
    except SupplementDiscoveryError as exc:
        if temp_path.exists():
            temp_path.unlink()
        return _failed_download(record, exc.error_type, str(exc))
    except httpx.RequestError as exc:
        if temp_path.exists():
            temp_path.unlink()
        return _failed_download(record, "network_error", str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        if temp_path.exists():
            temp_path.unlink()
        return _failed_download(record, "unknown_error", str(exc))

    sha256 = hasher.hexdigest()
    filename = _guess_filename(final_url, response_filename or record.filename)
    extension = _extract_extension(filename)
    final_name = _unique_filename(target_dir, filename, sha256)
    final_path = target_dir / final_name
    temp_path.replace(final_path)

    return SupplementDownloadResult(
        doi=record.doi,
        paper_id=record.paper_id,
        supplement_url=record.supplement_url,
        status="success",
        file_path=str(final_path),
        filename=final_name,
        extension=extension,
        content_type=content_type,
        sha256=sha256,
        size_bytes=size_bytes,
        downloaded_at=datetime.now(timezone.utc),
    )


def _make_client(*, timeout: httpx.Timeout, headers: dict[str, str]) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)


def _looks_like_supplement_link(anchor: Tag, absolute_url: str) -> bool:
    text = _clean_text(anchor.get_text(" ", strip=True)).lower()
    href_text = absolute_url.lower()
    if any(pattern in text for pattern in TEXT_HINTS):
        return True
    if any(pattern in href_text for pattern in HREF_HINTS):
        return True
    extension = _extract_extension(_guess_filename(absolute_url, None))
    return extension in {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".zip",
        ".csv",
        ".txt",
        ".mov",
        ".mp4",
        ".avi",
        ".mp3",
        ".wav",
        ".xml",
        ".json",
    }


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _find_source_section(anchor: Tag) -> str | None:
    for parent in [anchor, *anchor.parents]:
        if not isinstance(parent, Tag):
            continue
        heading = parent.find_previous(["h1", "h2", "h3", "h4", "strong"])
        if isinstance(heading, Tag):
            text = _clean_text(heading.get_text(" ", strip=True))
            if text:
                return text
    return None


def _guess_filename(url: str, content_disposition_filename: str | None) -> str:
    if content_disposition_filename:
        return _safe_filename(content_disposition_filename)
    path_name = Path(urlparse(url).path).name
    if path_name:
        return _safe_filename(path_name)
    return _safe_filename(hashlib.sha256(url.encode("utf-8")).hexdigest()[:12])


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', value, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = Path(filename).suffix.lower()
    return suffix or None


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "supplement"


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def _unique_filename(directory: Path, filename: str, sha256: str) -> str:
    target = directory / filename
    if not target.exists():
        return filename
    stem = Path(filename).stem or "supplement"
    suffix = Path(filename).suffix
    return f"{stem}_{sha256[:12]}{suffix}"


def _failed_download(record: SupplementRecord, error_type: str, error_message: str) -> SupplementDownloadResult:
    return SupplementDownloadResult(
        doi=record.doi,
        paper_id=record.paper_id,
        supplement_url=record.supplement_url,
        status="failed",
        filename=record.filename,
        extension=record.extension,
        error_type=error_type,
        error_message=error_message,
        downloaded_at=datetime.now(timezone.utc),
    )
