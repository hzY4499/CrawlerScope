from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_access_first: bool = True
    allow_user_login: bool = False
    allow_manual_upload: bool = True
    institution_access: bool = False
    no_paywall_bypass: bool = True
    no_captcha_bypass: bool = True
    obey_robots_txt: bool = True
    require_source_url: bool = True
    require_license_info: bool = True


class InstitutionAccessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_name: str
    institution_name: str | None = None
    login_url: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    storage_state_path: str | None = None
    status: Literal["not_configured", "login_required", "active", "expired"] = (
        "not_configured"
    )

    @field_validator("storage_state_path")
    @classmethod
    def validate_storage_state_path(cls, value: str | None) -> str | None:
        if value is None:
            return value

        normalized = Path(value).as_posix().lstrip("./")
        if "secrets/browser_states/" not in normalized:
            raise ValueError(
                "storage_state_path must point to a file under secrets/browser_states/."
            )
        return value


class AccessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str | None = None
    doi: str
    title: str | None = None
    status: Literal["allowed", "blocked", "manual_review"]
    access_type: Literal[
        "open_access",
        "user_authenticated",
        "manual_required",
        "unavailable",
    ]
    download_strategy: Literal[
        "direct_pdf",
        "browser_session",
        "manual_upload",
        "skip",
    ]
    access_url: str | None = None
    access_urls: list[str] = Field(default_factory=list)
    pdf_urls: list[str] = Field(default_factory=list)
    oa_landing_pages: list[str] = Field(default_factory=list)
    institution_domains: list[str] = Field(default_factory=list)
    requires_login: bool = False
    reason: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccessHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doi: str
    has_open_pdf: bool = False
    open_pdf_urls: list[str] = Field(default_factory=list)
    oa_landing_pages: list[str] = Field(default_factory=list)
    publisher_urls: list[str] = Field(default_factory=list)
    license: str | None = None
    evidence_sources: list[str] = Field(default_factory=list)
    next_stage: Literal["download_open_pdf", "resolve_access", "manual_review"] = (
        "resolve_access"
    )
