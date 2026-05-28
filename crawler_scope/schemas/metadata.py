from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .paper import PaperRecord


class MetadataSourceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str
    source: Literal["crossref", "openalex", "semantic_scholar", "unpaywall"]
    status: Literal["success", "not_found", "failed"]
    paper: PaperRecord | None = None
    raw_path: str | None = None
    error_type: str | None = None
    error_message: str | None = None
