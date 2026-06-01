from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SupplementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    publisher: str = "wiley"
    article_url: str | None = None
    supplement_url: str
    label: str | None = None
    filename: str | None = None
    extension: str | None = None
    content_type: str | None = None
    source_section: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupplementDownloadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    supplement_url: str
    status: Literal["success", "failed", "skipped"]
    file_path: str | None = None
    filename: str | None = None
    extension: str | None = None
    content_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    downloaded_at: datetime | None = None


class SupplementSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_articles: int = 0
    articles_with_supplements: int = 0
    total_supplement_links: int = 0
    downloaded_success: int = 0
    downloaded_failed: int = 0
    skipped: int = 0
    manual_handoff_count: int = 0
    failures_by_type: dict[str, int] = Field(default_factory=dict)
    extensions_by_count: dict[str, int] = Field(default_factory=dict)
