from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalize_dois: bool = True
    track_invalid_rows: bool = True
    track_duplicate_dois: bool = True
    preserve_original_inputs: bool = True
    require_doi_as_primary_key: bool = True


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str | None = None
    doi: str | None = None
    status: Literal["pass", "warn", "fail"]
    checks: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
