from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import BrowserSessionProfile

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def safe_storage_state_path(profile_name: str, publisher: str = "wiley") -> Path:
    safe_profile = _safe_name(profile_name)
    safe_publisher = _safe_name(publisher)
    target = (
        PROJECT_ROOT
        / "secrets"
        / "browser_states"
        / f"{safe_publisher}_{safe_profile}.storage.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def setup_interactive_browser_session(
    profile_name: str = "wiley-default",
    start_url: str = "https://onlinelibrary.wiley.com",
    publisher: str = "wiley",
) -> BrowserSessionProfile:
    storage_state_path = safe_storage_state_path(profile_name, publisher)
    created_at = datetime.now(timezone.utc)

    try:
        with _playwright_context_manager() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto(start_url, wait_until="domcontentloaded")
                try:
                    input(
                        "请在打开的浏览器中手动登录 Wiley / 手动完成机构认证 / 手动处理 challenge。完成后回到终端按 Enter。"
                    )
                except (EOFError, KeyboardInterrupt):
                    return BrowserSessionProfile(
                        profile_name=profile_name,
                        publisher=publisher,
                        start_url=start_url,
                        storage_state_path=str(storage_state_path),
                        status="failed",
                        created_at=created_at,
                        updated_at=datetime.now(timezone.utc),
                        notes="User cancelled before saving browser session state.",
                    )
                context.storage_state(path=str(storage_state_path))
            finally:
                browser.close()
    except Exception as exc:
        return BrowserSessionProfile(
            profile_name=profile_name,
            publisher=publisher,
            start_url=start_url,
            storage_state_path=str(storage_state_path),
            status="failed",
            created_at=created_at,
            updated_at=datetime.now(timezone.utc),
            notes=str(exc),
        )

    return BrowserSessionProfile(
        profile_name=profile_name,
        publisher=publisher,
        start_url=start_url,
        storage_state_path=str(storage_state_path),
        status="active",
        created_at=created_at,
        updated_at=datetime.now(timezone.utc),
    )


def _playwright_context_manager():
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def _safe_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return sanitized or "default"
