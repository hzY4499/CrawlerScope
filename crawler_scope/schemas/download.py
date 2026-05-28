from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DownloadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str | None = None
    doi: str
    status: Literal["downloaded", "skipped", "failed"]
    source_url: str | None = None
    output_path: str | None = None
    file_type: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
