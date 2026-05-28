from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DOIInputItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original: str
    normalized_doi: str | None = None
    row_index: int | None = None
    client_id: str | None = None
    status: Literal["valid", "invalid", "duplicate"] = "valid"
    error_message: str | None = None


class DOIResolutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str
    status: Literal["resolved", "not_found", "failed"]
    crossref_found: bool = False
    openalex_found: bool = False
    semantic_scholar_found: bool = False
    paper_id: str | None = None
    title: str | None = None
    error_message: str | None = None
