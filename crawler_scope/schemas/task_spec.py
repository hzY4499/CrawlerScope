from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .access import AccessPolicy
from .quality import QualityRequirements

TaskType = Literal[
    "doi_batch_crawl",
    "paper_crawl",
    "web_extract",
    "image_crawl",
    "video_metadata",
    "authenticated_download",
]


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: TaskType
    user_request: str
    query: str | None = None
    sources: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    access_policy: AccessPolicy = Field(default_factory=AccessPolicy)
    quality: QualityRequirements = Field(default_factory=QualityRequirements)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
