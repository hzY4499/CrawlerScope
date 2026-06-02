from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LocalFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    filename: str
    extension: str | None = None
    content_type: str | None = None
    sha256: str
    size_bytes: int
    file_role: Literal["paper_pdf", "supplement", "unknown"] = "unknown"
    detected_doi: str | None = None
    detected_paper_id: str | None = None
    parent_dir: str | None = None
    matched_doi: str | None = None
    matched_paper_id: str | None = None
    matched_by: Literal[
        "filename_doi",
        "folder_doi",
        "pdf_text_doi",
        "manifest",
        "title_similarity",
        "manual_mapping",
        "unknown",
    ] = "unknown"


class LocalCorpusMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    paper_pdf_files: list[str] = Field(default_factory=list)
    supplement_files: list[str] = Field(default_factory=list)
    unmatched_files: list[str] = Field(default_factory=list)
    status: Literal["complete", "paper_only", "supplement_only", "missing", "ambiguous"] = (
        "missing"
    )
    warnings: list[str] = Field(default_factory=list)


class LocalCorpusSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_files_scanned: int = 0
    paper_pdf_files: int = 0
    supplement_files: int = 0
    unknown_files: int = 0
    matched_articles: int = 0
    articles_with_paper_pdf: int = 0
    articles_with_supplements: int = 0
    complete_articles: int = 0
    missing_articles: int = 0
    ambiguous_articles: int = 0
    files_by_extension: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
