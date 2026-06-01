from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ManualDownloadTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    publisher: str = "wiley"
    article_url: str
    target_dir: str
    status: Literal["pending", "downloaded", "missing", "skipped"] = "pending"
    reason: str | None = None
    notes: str | None = None


class ManualDownloadedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    publisher: str = "wiley"
    source_dir: str
    file_path: str
    filename: str
    extension: str | None = None
    content_type: str | None = None
    sha256: str
    size_bytes: int
    matched_by: Literal["folder_name", "manifest", "manual_mapping", "unknown"] = (
        "unknown"
    )


class ManualScanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_tasks: int = 0
    pending_tasks: int = 0
    articles_with_files: int = 0
    total_files: int = 0
    files_by_extension: dict[str, int] = Field(default_factory=dict)
    missing_articles: int = 0
    warnings: list[str] = Field(default_factory=list)
