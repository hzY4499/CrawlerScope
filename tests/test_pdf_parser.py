from __future__ import annotations

from pathlib import Path

import fitz

from crawler_scope.schemas import DownloadResult
from crawler_scope.tools.parser.pdf_parser import parse_pdf_basic


def test_parse_pdf_basic_extracts_text_and_abstract(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _create_pdf(
        pdf_path,
        title="Sample Paper Title",
        body="Sample Paper Title\nAbstract\nThis is the abstract text.\nIntroduction\nThis is the introduction.",
    )
    download_result = DownloadResult(
        paper_id="paper_sample",
        doi="10.1000/sample",
        status="success",
        access_type="open_access",
        strategy="direct_pdf",
        file_path=str(pdf_path),
    )

    result = parse_pdf_basic(download_result, tmp_path / "parsed")

    assert result.status == "success"
    assert result.page_count == 1
    assert result.title == "Sample Paper Title"
    assert result.abstract is not None
    assert "abstract text" in result.abstract.lower()
    assert result.full_text_path is not None
    assert Path(result.full_text_path).exists()


def test_parse_pdf_basic_file_not_found(tmp_path: Path) -> None:
    download_result = DownloadResult(
        paper_id="paper_missing",
        doi="10.1000/missing",
        status="success",
        access_type="open_access",
        strategy="direct_pdf",
        file_path=str(tmp_path / "missing.pdf"),
    )

    result = parse_pdf_basic(download_result, tmp_path / "parsed")

    assert result.status == "failed"
    assert result.error_type == "file_not_found"


def test_parse_pdf_basic_skips_non_success_download(tmp_path: Path) -> None:
    download_result = DownloadResult(
        paper_id="paper_skipped",
        doi="10.1000/skipped",
        status="failed",
        access_type="open_access",
        strategy="direct_pdf",
        file_path=None,
    )

    result = parse_pdf_basic(download_result, tmp_path / "parsed")

    assert result.status == "skipped"
    assert result.error_type == "skipped_download_failed"


def test_parse_pdf_basic_empty_text_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "empty.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    download_result = DownloadResult(
        paper_id="paper_empty",
        doi="10.1000/empty",
        status="success",
        access_type="open_access",
        strategy="direct_pdf",
        file_path=str(pdf_path),
    )

    result = parse_pdf_basic(download_result, tmp_path / "parsed")

    assert result.status == "failed"
    assert result.error_type == "empty_text"


def _create_pdf(path: Path, *, title: str, body: str) -> None:
    document = fitz.open()
    document.set_metadata({"title": title})
    page = document.new_page()
    page.insert_text((72, 72), body)
    document.save(path)
    document.close()
