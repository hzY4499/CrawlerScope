from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinalPaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str
    paper_id: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    publisher: str | None = None
    access_type: str | None = None
    download_strategy: str | None = None
    access_url: str | None = None
    pdf_path: str | None = None
    parsed_text_path: str | None = None
    status: str
    failure_type: str | None = None
    next_action: str


class FinalFailureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str
    paper_id: str | None = None
    status: str
    failure_stage: str
    failure_type: str
    error_message: str | None = None
    next_action: str


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    generated_at: datetime
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts_present: dict[str, bool] = Field(default_factory=dict)
    final_papers: list[FinalPaperRecord] = Field(default_factory=list)
    final_failures: list[FinalFailureRecord] = Field(default_factory=list)
