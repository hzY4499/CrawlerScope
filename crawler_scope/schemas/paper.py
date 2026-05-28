from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    doi: str
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    arxiv_id: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    publisher: str | None = None
    abstract: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    pdf_urls: list[str] = Field(default_factory=list)
    is_open_access: bool | None = None
    license: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    primary_lookup_key: Literal["doi"] = "doi"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
