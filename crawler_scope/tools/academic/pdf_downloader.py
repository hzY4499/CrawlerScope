from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import httpx

from crawler_scope.schemas import AccessDecision, DownloadResult

MIN_PDF_BYTES = 10 * 1024
CHUNK_SIZE = 64 * 1024


def download_open_pdf_candidate(
    decision: AccessDecision,
    output_dir: Path,
    timeout_seconds: float = 30.0,
    max_bytes: int | None = None,
) -> DownloadResult:
    if decision.access_type != "open_access" or decision.download_strategy not in {
        "direct_pdf",
        "api_pdf",
    }:
        return _result(
            decision,
            status="skipped",
            error_type=None,
            error_message="Decision is not an open-access PDF download candidate.",
        )

    url = decision.access_url or _first_or_none(decision.pdf_urls)
    if not url:
        return _result(
            decision,
            status="failed",
            error_type="missing_url",
            error_message="No download URL is available for this decision.",
        )

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return _result(
            decision,
            status="failed",
            error_type="invalid_url",
            error_message=f"Unsupported URL scheme: {parsed.scheme or 'missing'}",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None

    try:
        with _make_client(timeout_seconds=timeout_seconds) as client:
            with client.stream("GET", url, follow_redirects=True) as response:
                if response.status_code == 403:
                    return _result(decision, status="failed", error_type="download_403", error_message="HTTP 403")
                if response.status_code == 404:
                    return _result(decision, status="failed", error_type="download_404", error_message="HTTP 404")
                if response.status_code == 429:
                    return _result(decision, status="failed", error_type="rate_limited", error_message="HTTP 429")
                if response.status_code != 200:
                    return _result(
                        decision,
                        status="failed",
                        error_type="unknown_error",
                        error_message=f"Unexpected HTTP status: {response.status_code}",
                    )

                content_type = response.headers.get("content-type")
                suffix = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".part"
                with NamedTemporaryFile(delete=False, suffix=suffix, dir=output_dir) as temp_file:
                    temp_path = Path(temp_file.name)
                    total_bytes = 0
                    hasher = hashlib.sha256()
                    first_bytes = b""

                    for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        if len(first_bytes) < 8:
                            first_bytes += chunk[: 8 - len(first_bytes)]
                        total_bytes += len(chunk)
                        if max_bytes is not None and total_bytes > max_bytes:
                            raise ValueError("download exceeded max_bytes limit")
                        temp_file.write(chunk)
                        hasher.update(chunk)

                if total_bytes <= MIN_PDF_BYTES:
                    _cleanup(temp_path)
                    return _result(
                        decision,
                        status="failed",
                        error_type="file_too_small",
                        error_message=f"Downloaded file is too small: {total_bytes} bytes.",
                        url=url,
                        final_url=str(response.url),
                        content_type=content_type,
                        size_bytes=total_bytes,
                    )

                is_pdf_header = first_bytes.startswith(b"%PDF")
                content_type_is_pdf = "application/pdf" in (content_type or "").lower()
                content_type_is_html = "text/html" in (content_type or "").lower()

                if not is_pdf_header and content_type_is_html:
                    _cleanup(temp_path)
                    return _result(
                        decision,
                        status="failed",
                        error_type="not_pdf",
                        error_message="Response content appears to be HTML, not PDF.",
                        url=url,
                        final_url=str(response.url),
                        content_type=content_type,
                        size_bytes=total_bytes,
                    )

                if not is_pdf_header and not content_type_is_pdf:
                    _cleanup(temp_path)
                    return _result(
                        decision,
                        status="failed",
                        error_type="corrupted_pdf",
                        error_message="Response is not recognized as a valid PDF.",
                        url=url,
                        final_url=str(response.url),
                        content_type=content_type,
                        size_bytes=total_bytes,
                    )

                sha256 = hasher.hexdigest()
                safe_paper_id = _safe_file_stem(decision.paper_id or decision.doi or "paper")
                final_path = output_dir / f"{safe_paper_id}_{sha256[:12]}.pdf"
                os.replace(temp_path, final_path)
                temp_path = None

                return _result(
                    decision,
                    status="success",
                    url=url,
                    file_path=str(final_path),
                    sha256=sha256,
                    size_bytes=total_bytes,
                    content_type=content_type,
                    final_url=str(response.url),
                    downloaded_at=datetime.now(timezone.utc),
                )
    except httpx.TimeoutException as exc:
        _cleanup(temp_path)
        return _result(
            decision,
            status="failed",
            error_type="download_timeout",
            error_message=str(exc),
            url=url,
        )
    except httpx.RequestError as exc:
        _cleanup(temp_path)
        return _result(
            decision,
            status="failed",
            error_type="network_error",
            error_message=str(exc),
            url=url,
        )
    except ValueError as exc:
        _cleanup(temp_path)
        return _result(
            decision,
            status="failed",
            error_type="unknown_error",
            error_message=str(exc),
            url=url,
        )
    except Exception as exc:
        _cleanup(temp_path)
        return _result(
            decision,
            status="failed",
            error_type="unknown_error",
            error_message=str(exc),
            url=url,
        )


def _make_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
        headers={"User-Agent": "CrawlerScope/0.1.0 open-pdf-downloader"},
    )


def _result(
    decision: AccessDecision,
    *,
    status: str,
    url: str | None = None,
    file_path: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    content_type: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    final_url: str | None = None,
    downloaded_at: datetime | None = None,
) -> DownloadResult:
    return DownloadResult(
        paper_id=decision.paper_id or decision.doi,
        doi=decision.doi,
        status=status,  # type: ignore[arg-type]
        access_type=decision.access_type,
        strategy=decision.download_strategy,
        url=url or decision.access_url,
        file_path=file_path,
        sha256=sha256,
        size_bytes=size_bytes,
        content_type=content_type,
        error_type=error_type,
        error_message=error_message,
        source=_first_or_none(decision.evidence_sources),
        final_url=final_url,
        downloaded_at=downloaded_at,
    )


def _cleanup(path: Path | None) -> None:
    if path is not None and path.exists():
        path.unlink(missing_ok=True)


def _first_or_none(values: list[str]) -> str | None:
    return values[0] if values else None


def _safe_file_stem(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
