from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DownloadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    status: Literal["success", "failed", "skipped"]
    access_type: str
    strategy: str
    url: str | None = None
    file_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    doi: str | None = None
    source: str | None = None
    final_url: str | None = None
    downloaded_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
