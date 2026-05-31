from __future__ import annotations

import httpx

from crawler_scope.schemas import AccessDecision
from crawler_scope.tools.academic import pdf_downloader

PDF_BYTES = b"%PDF-1.4\n" + (b"0" * (11 * 1024))


def _decision(url: str | None = "https://example.org/paper.pdf", *, access_type: str = "open_access") -> AccessDecision:
    return AccessDecision(
        paper_id="doi_10.1000_test",
        doi="10.1000/test",
        title="Example",
        status="allowed",
        access_type=access_type,  # type: ignore[arg-type]
        download_strategy="direct_pdf",
        access_url=url,
        access_urls=[url] if url else [],
        pdf_urls=[url] if url else [],
    )


def test_pdf_downloader_success(tmp_path, monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=PDF_BYTES,
            request=request,
        )
    )
    monkeypatch.setattr(
        pdf_downloader,
        "_make_client",
        lambda timeout_seconds: httpx.Client(transport=transport, follow_redirects=True),
    )

    result = pdf_downloader.download_open_pdf_candidate(_decision(), tmp_path)

    assert result.status == "success"
    assert result.file_path is not None
    assert result.sha256 is not None
    assert result.size_bytes == len(PDF_BYTES)


def test_pdf_downloader_403(tmp_path, monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, request=request)
    )
    monkeypatch.setattr(
        pdf_downloader,
        "_make_client",
        lambda timeout_seconds: httpx.Client(transport=transport, follow_redirects=True),
    )

    result = pdf_downloader.download_open_pdf_candidate(_decision(), tmp_path)

    assert result.status == "failed"
    assert result.error_type == "download_403"


def test_pdf_downloader_404(tmp_path, monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, request=request)
    )
    monkeypatch.setattr(
        pdf_downloader,
        "_make_client",
        lambda timeout_seconds: httpx.Client(transport=transport, follow_redirects=True),
    )

    result = pdf_downloader.download_open_pdf_candidate(_decision(), tmp_path)

    assert result.status == "failed"
    assert result.error_type == "download_404"


def test_pdf_downloader_not_pdf_html(tmp_path, monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html>not a pdf</html>" + (b"x" * (11 * 1024)),
            request=request,
        )
    )
    monkeypatch.setattr(
        pdf_downloader,
        "_make_client",
        lambda timeout_seconds: httpx.Client(transport=transport, follow_redirects=True),
    )

    result = pdf_downloader.download_open_pdf_candidate(_decision(), tmp_path)

    assert result.status == "failed"
    assert result.error_type == "not_pdf"


def test_pdf_downloader_timeout(tmp_path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        pdf_downloader,
        "_make_client",
        lambda timeout_seconds: httpx.Client(transport=transport, follow_redirects=True),
    )

    result = pdf_downloader.download_open_pdf_candidate(_decision(), tmp_path)

    assert result.status == "failed"
    assert result.error_type == "download_timeout"


def test_pdf_downloader_skips_non_open_access(tmp_path) -> None:
    result = pdf_downloader.download_open_pdf_candidate(
        _decision(access_type="manual_required"),
        tmp_path,
    )

    assert result.status == "skipped"


def test_pdf_downloader_missing_url(tmp_path) -> None:
    result = pdf_downloader.download_open_pdf_candidate(_decision(url=None), tmp_path)

    assert result.status == "failed"
    assert result.error_type == "missing_url"
