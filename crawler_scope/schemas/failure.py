from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FailureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    error_type: str
    error_message: str
    doi: str | None = None
    paper_id: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
