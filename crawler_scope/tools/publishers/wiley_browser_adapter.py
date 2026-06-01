from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import SupplementRecord
from crawler_scope.tools.publishers.wiley_supplement_adapter import (
    SupplementDiscoveryError,
    build_wiley_article_url_from_doi,
    has_wiley_access_challenge,
    parse_wiley_supplements_from_html,
)


def discover_wiley_supplements_with_browser_state(
    doi: str,
    storage_state_path: Path,
    article_url: str | None = None,
    timeout_seconds: float = 60.0,
    headless: bool = True,
) -> list[SupplementRecord]:
    target_url = article_url or build_wiley_article_url_from_doi(doi)
    state_path = Path(storage_state_path)
    if not state_path.exists():
        raise SupplementDiscoveryError(
            "login_required",
            f"Missing browser session state: {state_path}",
        )

    try:
        with _playwright_context_manager() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                context = browser.new_context(storage_state=str(state_path))
                page = context.new_page()
                page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout_seconds * 1000),
                )
                html = page.content()
                current_url = page.url or target_url
            finally:
                browser.close()
    except SupplementDiscoveryError:
        raise
    except Exception as exc:
        raise SupplementDiscoveryError("network_error", str(exc)) from exc

    if has_wiley_access_challenge(html):
        raise SupplementDiscoveryError(
            "access_challenge",
            "Wiley page still requires manual challenge handling in the browser session.",
        )

    return parse_wiley_supplements_from_html(
        doi=doi,
        article_url=current_url,
        html=html,
    )


def _playwright_context_manager():
    from playwright.sync_api import sync_playwright

    return sync_playwright()
