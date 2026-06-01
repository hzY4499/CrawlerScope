from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequirementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    task_type: Literal[
        "doi_batch_crawl",
        "supplement_crawl",
        "wiley_supplement_crawl",
    ]
    publisher: str | None = None
    supplement_policy: Literal["pdf_doc_only", "all_formats"] = "all_formats"
    allowed_file_extensions: list[str] = Field(default_factory=list)
    include_archives: bool = True
    include_media: bool = True
    include_data_files: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
