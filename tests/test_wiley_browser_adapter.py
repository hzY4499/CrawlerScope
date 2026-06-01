from __future__ import annotations

from pathlib import Path

import pytest

from crawler_scope.tools.publishers import wiley_browser_adapter, wiley_supplement_adapter


def test_parse_wiley_supplements_from_html_extracts_supporting_links() -> None:
    html = """
    <html>
      <body>
        <h2>Supporting Information</h2>
        <a href="/pb-assets/one.pdf">Supporting Information PDF</a>
        <a href="/pb-assets/two.zip">Dataset S1</a>
        <a href="/pb-assets/one.pdf">Duplicate PDF</a>
      </body>
    </html>
    """

    records = wiley_supplement_adapter.parse_wiley_supplements_from_html(
        doi="10.1000/wiley",
        article_url="https://onlinelibrary.wiley.com/doi/10.1000/wiley",
        html=html,
    )

    assert len(records) == 2
    assert {record.extension for record in records} == {".pdf", ".zip"}
    assert all(record.source_section == "Supporting Information" for record in records)


def test_discover_wiley_supplements_with_browser_state_uses_page_html(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage_state_path = tmp_path / "state.json"
    storage_state_path.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
    html = """
    <html>
      <body>
        <h2>Supporting Information</h2>
        <a href="/pb-assets/one.pdf">Supporting Information PDF</a>
        <a href="/pb-assets/two.docx">Additional Supporting Information</a>
      </body>
    </html>
    """

    class FakePage:
        url = "https://onlinelibrary.wiley.com/doi/10.1000/wiley"

        def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 0) -> None:
            self.url = url

        def content(self) -> str:
            return html

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

    class FakeBrowser:
        def new_context(self, *, storage_state: str) -> FakeContext:
            assert storage_state == str(storage_state_path)
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, *, headless: bool) -> FakeBrowser:
            assert headless is True
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        wiley_browser_adapter,
        "_playwright_context_manager",
        lambda: FakeManager(),
    )

    records = wiley_browser_adapter.discover_wiley_supplements_with_browser_state(
        "10.1000/wiley",
        storage_state_path=storage_state_path,
    )

    assert len(records) == 2
    assert {record.extension for record in records} == {".pdf", ".docx"}


def test_discover_wiley_supplements_with_browser_state_raises_access_challenge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage_state_path = tmp_path / "state.json"
    storage_state_path.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")

    class FakePage:
        url = "https://onlinelibrary.wiley.com/doi/10.1000/wiley"

        def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 0) -> None:
            self.url = url

        def content(self) -> str:
            return "<html><title>Just a moment...</title><body>captcha</body></html>"

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

    class FakeBrowser:
        def new_context(self, *, storage_state: str) -> FakeContext:
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, *, headless: bool) -> FakeBrowser:
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        wiley_browser_adapter,
        "_playwright_context_manager",
        lambda: FakeManager(),
    )

    with pytest.raises(wiley_supplement_adapter.SupplementDiscoveryError) as exc_info:
        wiley_browser_adapter.discover_wiley_supplements_with_browser_state(
            "10.1000/wiley",
            storage_state_path=storage_state_path,
        )

    assert exc_info.value.error_type == "access_challenge"
