from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import fitz

from crawler_scope.schemas import DownloadResult, ParseResult

PARSER_NAME = "pymupdf"
ABSTRACT_PATTERN = re.compile(
    r"(?is)\babstract\b[:\s\-]*?(?P<body>.+?)(?=\bkeywords\b|\bintroduction\b|\b1\s+introduction\b|$)"
)
ABSTRACT_CN_PATTERN = re.compile(
    r"(?is)摘要[:：\s\-]*?(?P<body>.+?)(?=关键词|引言|\bintroduction\b|$)"
)


def parse_pdf_basic(download_result: DownloadResult, output_dir: Path) -> ParseResult:
    if download_result.status != "success":
        return _result(
            download_result,
            status="skipped",
            error_type="skipped_download_failed",
            error_message="Download result was not successful.",
        )

    if not download_result.file_path:
        return _result(
            download_result,
            status="failed",
            error_type="file_not_found",
            error_message="Download result has no file_path.",
        )

    pdf_path = Path(download_result.file_path)
    if not pdf_path.exists():
        return _result(
            download_result,
            status="failed",
            error_type="file_not_found",
            error_message=f"PDF file does not exist: {pdf_path}",
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with fitz.open(pdf_path) as document:
            page_count = document.page_count
            metadata = document.metadata or {}
            first_page_text = ""
            full_text_parts: list[str] = []

            for page_index, page in enumerate(document):
                page_text = page.get_text("text") or ""
                if page_index == 0:
                    first_page_text = page_text
                full_text_parts.append(page_text)

            full_text = "\n".join(part for part in full_text_parts if part).strip()
            if not full_text:
                return _result(
                    download_result,
                    status="failed",
                    error_type="empty_text",
                    error_message="No extractable text was found in the PDF.",
                    file_path=str(pdf_path),
                    page_count=page_count,
                    parser_version=fitz.VersionBind,
                )

            word_count = len(full_text.split())
            char_count = len(full_text)
            metadata_title = _clean_text(metadata.get("title"))
            title_guess = metadata_title or _guess_title(first_page_text)
            abstract_guess = _extract_abstract(full_text)

            safe_paper_id = _safe_file_stem(download_result.paper_id)
            full_text_path = output_dir / f"{safe_paper_id}.txt"
            full_text_path.write_text(full_text + "\n", encoding="utf-8")

            return _result(
                download_result,
                status="success",
                title=title_guess,
                abstract=abstract_guess,
                sections={
                    "metadata_title": metadata_title,
                    "first_page_text": first_page_text[:5000],
                    "title_guess": title_guess,
                    "abstract_guess": abstract_guess,
                },
                full_text_path=str(full_text_path),
                file_path=str(pdf_path),
                page_count=page_count,
                word_count=word_count,
                char_count=char_count,
                parser_version=fitz.VersionBind,
                parsed_at=datetime.now(timezone.utc),
            )
    except RuntimeError as exc:
        return _result(
            download_result,
            status="failed",
            error_type="open_failed",
            error_message=str(exc),
            file_path=str(pdf_path),
            parser_version=fitz.VersionBind,
        )
    except Exception as exc:
        return _result(
            download_result,
            status="failed",
            error_type="unknown_error",
            error_message=str(exc),
            file_path=str(pdf_path),
            parser_version=fitz.VersionBind,
        )


def _result(
    download_result: DownloadResult,
    *,
    status: str,
    title: str | None = None,
    abstract: str | None = None,
    sections: dict | None = None,
    full_text_path: str | None = None,
    error_message: str | None = None,
    file_path: str | None = None,
    page_count: int | None = None,
    word_count: int | None = None,
    char_count: int | None = None,
    parser_version: str | None = None,
    parsed_at: datetime | None = None,
    error_type: str | None = None,
) -> ParseResult:
    return ParseResult(
        paper_id=download_result.paper_id,
        doi=download_result.doi,
        status=status,  # type: ignore[arg-type]
        parser=PARSER_NAME,
        title=title,
        abstract=abstract,
        sections=sections or {},
        references=[],
        full_text_path=full_text_path,
        error_message=error_message,
        file_path=file_path or download_result.file_path,
        page_count=page_count,
        word_count=word_count,
        char_count=char_count,
        parser_version=parser_version,
        parsed_at=parsed_at,
        error_type=error_type,
    )


def _guess_title(first_page_text: str) -> str | None:
    for line in first_page_text.splitlines():
        cleaned = _clean_text(line)
        if cleaned and len(cleaned) > 5:
            return cleaned
    return None


def _extract_abstract(full_text: str) -> str | None:
    normalized_text = re.sub(r"\r\n?", "\n", full_text)
    for pattern in (ABSTRACT_PATTERN, ABSTRACT_CN_PATTERN):
        match = pattern.search(normalized_text)
        if not match:
            continue
        body = _clean_text(match.group("body"))
        if body:
            return body[:3000]
    return None


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[ \t]+", " ", value).strip()
    return cleaned or None


def _safe_file_stem(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
