from __future__ import annotations

import builtins
from pathlib import Path

from crawler_scope.tools.browser import session_manager


def test_safe_storage_state_path_stays_under_secrets_browser_states(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_manager, "PROJECT_ROOT", tmp_path)

    path = session_manager.safe_storage_state_path("../team/wiley default", "wiley")

    assert path == tmp_path / "secrets" / "browser_states" / "wiley_team_wiley_default.storage.json"
    assert path.parent.exists()
    assert "secrets/browser_states" in path.as_posix()


def test_setup_interactive_browser_session_is_mockable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_manager, "PROJECT_ROOT", tmp_path)

    class FakePage:
        def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            self.url = url

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

        def storage_state(self, path: str) -> None:
            Path(path).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")

    class FakeBrowser:
        def new_context(self) -> FakeContext:
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, *, headless: bool) -> FakeBrowser:
            assert headless is False
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        session_manager,
        "_playwright_context_manager",
        lambda: FakeManager(),
    )
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")

    profile = session_manager.setup_interactive_browser_session(
        profile_name="wiley-default",
        start_url="https://onlinelibrary.wiley.com",
    )

    assert profile.status == "active"
    assert profile.storage_state_path.endswith("wiley_wiley-default.storage.json")
    assert Path(profile.storage_state_path).exists()


def test_setup_interactive_browser_session_returns_failed_on_cancel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_manager, "PROJECT_ROOT", tmp_path)

    class FakePage:
        def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            self.url = url

    class FakeContext:
        def new_page(self) -> FakePage:
            return FakePage()

        def storage_state(self, path: str) -> None:
            raise AssertionError("storage_state should not be called when user cancels")

    class FakeBrowser:
        def new_context(self) -> FakeContext:
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
        session_manager,
        "_playwright_context_manager",
        lambda: FakeManager(),
    )

    def raise_keyboard_interrupt(prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", raise_keyboard_interrupt)

    profile = session_manager.setup_interactive_browser_session(
        profile_name="wiley-default",
    )

    assert profile.status == "failed"
    assert "cancelled" in (profile.notes or "").lower()
