from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BrowserSessionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_name: str
    publisher: str = "wiley"
    start_url: str | None = None
    storage_state_path: str
    status: Literal[
        "not_configured",
        "active",
        "expired",
        "challenge_required",
        "failed",
    ] = "not_configured"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None
    notes: str | None = None

    @field_validator("storage_state_path")
    @classmethod
    def validate_storage_state_path(cls, value: str) -> str:
        normalized = Path(value).as_posix().lstrip("./")
        if "secrets/browser_states/" not in normalized:
            raise ValueError(
                "storage_state_path must point to a file under secrets/browser_states/."
            )
        return value


class ManualHandoffRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str | None = None
    paper_id: str | None = None
    publisher: str = "wiley"
    article_url: str | None = None
    reason: Literal[
        "access_challenge",
        "login_required",
        "captcha_required",
        "paywall",
        "manual_review",
        "unknown",
    ]
    next_action: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
