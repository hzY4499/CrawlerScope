from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    status: Literal["success", "failed", "skipped"]
    parser: str
    title: str | None = None
    abstract: str | None = None
    sections: dict[str, Any] = Field(default_factory=dict)
    references: list[dict[str, Any]] = Field(default_factory=list)
    full_text_path: str | None = None
    error_message: str | None = None
    doi: str | None = None
    file_path: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    char_count: int | None = None
    parser_version: str | None = None
    parsed_at: datetime | None = None
    error_type: str | None = None
