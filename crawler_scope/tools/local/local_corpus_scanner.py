from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

import fitz

from crawler_scope.schemas import LocalFileRecord

IGNORED_FILENAMES = {"README.txt", ".DS_Store"}
IGNORED_SUFFIXES = {".crdownload", ".part", ".tmp"}
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
SAFE_DOI_PATTERN = re.compile(r"10\.\d{4,9}[/_-][-._;()/:A-Za-z0-9]+", re.IGNORECASE)


def scan_local_file(path: Path, role_hint: str | None = None) -> LocalFileRecord:
    sha256, size_bytes = _hash_file(path)
    content_type, _ = mimetypes.guess_type(path.name)
    extension = path.suffix.lower() or None
    file_role = _detect_file_role(path, extension, role_hint)

    detected_doi, matched_by = _detect_doi(path)
    if detected_doi is None and extension == ".pdf":
        detected_doi = _extract_doi_from_pdf(path)
        if detected_doi is not None:
            matched_by = "pdf_text_doi"

    detected_paper_id = _detect_paper_id(path, file_role)
    return LocalFileRecord(
        file_path=str(path),
        filename=path.name,
        extension=extension,
        content_type=content_type,
        sha256=sha256,
        size_bytes=size_bytes,
        file_role=file_role,
        detected_doi=detected_doi,
        detected_paper_id=detected_paper_id,
        parent_dir=str(path.parent),
        matched_by=matched_by,
    )


def scan_local_corpus(
    paper_pdf_dir: Path | None = None,
    supplement_dir: Path | None = None,
) -> list[LocalFileRecord]:
    records, _warnings = _scan_local_corpus_with_warnings(
        paper_pdf_dir=paper_pdf_dir,
        supplement_dir=supplement_dir,
    )
    return records


def _scan_local_corpus_with_warnings(
    *,
    paper_pdf_dir: Path | None = None,
    supplement_dir: Path | None = None,
) -> tuple[list[LocalFileRecord], list[str]]:
    records: list[LocalFileRecord] = []
    warnings: list[str] = []
    if paper_pdf_dir is not None:
        _scan_directory(
            paper_pdf_dir,
            role_hint="paper_pdf_dir",
            records=records,
            warnings=warnings,
        )
    if supplement_dir is not None:
        _scan_directory(
            supplement_dir,
            role_hint="supplement_dir",
            records=records,
            warnings=warnings,
        )
    return records, warnings


def _scan_directory(
    root_dir: Path,
    *,
    role_hint: str,
    records: list[LocalFileRecord],
    warnings: list[str],
) -> None:
    if not root_dir.exists():
        warnings.append(f"Directory not found: {root_dir}")
        return
    for path in sorted(root_dir.rglob("*")):
        if not path.is_file():
            continue
        if _should_ignore(path):
            continue
        try:
            records.append(scan_local_file(path, role_hint=role_hint))
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Failed to scan file {path}: {exc}")


def _hash_file(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            hasher.update(chunk)
            size_bytes += len(chunk)
    return hasher.hexdigest(), size_bytes


def _should_ignore(path: Path) -> bool:
    if path.name in IGNORED_FILENAMES:
        return True
    if path.name.startswith("."):
        return True
    if path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def _detect_file_role(
    path: Path,
    extension: str | None,
    role_hint: str | None,
) -> str:
    normalized_parts = " ".join(part.lower() for part in path.parts)
    filename_lower = path.name.lower()
    if "supplement" in normalized_parts or "supporting" in normalized_parts:
        return "supplement"
    if role_hint == "supplement_dir":
        return "supplement"
    if role_hint == "paper_pdf_dir":
        if extension == ".pdf":
            return "paper_pdf"
        return "unknown"
    if extension == ".pdf" and any(
        token in filename_lower or token in normalized_parts
        for token in ["paper", "main", "article"]
    ):
        return "paper_pdf"
    return "unknown"


def _detect_doi(path: Path) -> tuple[str | None, str]:
    candidates: list[tuple[str, str]] = []
    for text, source in _iter_doi_source_strings(path):
        direct = _extract_standard_doi(text)
        if direct is not None:
            return direct, source
        safe = _extract_safe_doi(text)
        if safe is not None:
            candidates.append((safe, source))
    return candidates[0] if candidates else (None, "unknown")


def _iter_doi_source_strings(path: Path) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    values.append((path.stem, "filename_doi"))
    values.extend((parent.name, "folder_doi") for parent in path.parents if parent.name)
    for child_parent, prefix_parent in zip(path.parents, path.parents[1:]):
        if re.fullmatch(r"10\.\d{4,9}", prefix_parent.name, flags=re.IGNORECASE):
            values.append((f"{prefix_parent.name}/{child_parent.name}", "folder_doi"))
    return values


def _extract_standard_doi(text: str) -> str | None:
    match = DOI_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip("._-")


def _extract_safe_doi(text: str) -> str | None:
    match = SAFE_DOI_PATTERN.search(text)
    if not match:
        return None
    candidate = match.group(0).rstrip("._-")
    prefix, separator, suffix = candidate.partition("/")
    if not separator:
        prefix, separator, suffix = candidate.partition("_")
    if not separator:
        prefix, separator, suffix = candidate.partition("-")
    if not separator:
        return None
    return f"{prefix}/{suffix}"


def _extract_doi_from_pdf(path: Path) -> str | None:
    try:
        with fitz.open(path) as document:
            page_text = []
            for page_index in range(min(2, document.page_count)):
                page_text.append(document.load_page(page_index).get_text("text"))
    except Exception:
        return None
    text = "\n".join(page_text)
    return _extract_standard_doi(text)


def _detect_paper_id(path: Path, file_role: str) -> str | None:
    if file_role == "paper_pdf" and path.stem.lower() in {"paper", "article", "main"}:
        return path.parent.name or None
    if file_role == "supplement":
        parent_name = path.parent.name.lower()
        if parent_name in {"supplementaryfiles", "supplementary", "supplements"}:
            return path.parent.parent.name or None
    return None
