from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from crawler_scope.schemas import SupplementRecord
from crawler_scope.tools.publishers import wiley_supplement_adapter


def test_build_wiley_article_url_from_doi_url_encodes_value() -> None:
    url = wiley_supplement_adapter.build_wiley_article_url_from_doi("10.1002/abc def")

    assert url == "https://onlinelibrary.wiley.com/doi/10.1002%2Fabc%20def"


def test_discover_wiley_supplements_finds_multiple_formats_and_dedupes(monkeypatch) -> None:
    html = """
    <html>
      <body>
        <h2>Supporting Information</h2>
        <a href="/pb-assets/one.pdf">Supporting Information PDF</a>
        <a href="/pb-assets/two.docx">Additional Supporting Information</a>
        <a href="/pb-assets/three.xlsx">Dataset S1</a>
        <a href="/pb-assets/four.zip">Data S2</a>
        <a href="/pb-assets/five.csv">Table S1</a>
        <a href="/pb-assets/six.mov">Movie S1</a>
        <a href="/pb-assets/seven.mp4">Video abstract</a>
        <a href="/pb-assets/one.pdf">Supporting Information PDF duplicate</a>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        wiley_supplement_adapter,
        "_make_client",
        lambda *, timeout, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ),
    )

    records = wiley_supplement_adapter.discover_wiley_supplements(
        "10.1000/wiley",
        article_url="https://onlinelibrary.wiley.com/doi/10.1000/wiley",
    )

    assert len(records) == 7
    assert {record.extension for record in records} == {
        ".pdf",
        ".docx",
        ".xlsx",
        ".zip",
        ".csv",
        ".mov",
        ".mp4",
    }
    assert all(record.source_section == "Supporting Information" for record in records)


def test_discover_wiley_supplements_raises_on_access_challenge(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>Just a moment... captcha</html>", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        wiley_supplement_adapter,
        "_make_client",
        lambda *, timeout, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ),
    )

    with pytest.raises(wiley_supplement_adapter.SupplementDiscoveryError) as exc_info:
        wiley_supplement_adapter.discover_wiley_supplements("10.1000/wiley")

    assert exc_info.value.error_type == "access_challenge"


def test_download_supplement_file_downloads_binary_and_hashes(monkeypatch, tmp_path: Path) -> None:
    content = b"PK\x03\x04example supplement"
    expected_sha = hashlib.sha256(content).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/zip",
                "content-disposition": 'attachment; filename="dataset.zip"',
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        wiley_supplement_adapter,
        "_make_client",
        lambda *, timeout, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ),
    )

    record = SupplementRecord(
        doi="10.1000/wiley",
        paper_id="paper_wiley",
        article_url="https://onlinelibrary.wiley.com/doi/10.1000/wiley",
        supplement_url="https://media.wiley.com/dataset.zip",
        label="Dataset S1",
    )

    result = wiley_supplement_adapter.download_supplement_file(record, tmp_path)

    assert result.status == "success"
    assert result.sha256 == expected_sha
    assert result.extension == ".zip"
    assert result.content_type == "application/zip"
    assert result.file_path is not None
    assert Path(result.file_path).exists()
