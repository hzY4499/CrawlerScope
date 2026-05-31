from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml


class SimpleRateLimiter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._last_call_at: dict[str, float] = {}

    @classmethod
    def from_yaml(cls, path: Path) -> "SimpleRateLimiter":
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return cls()
        return cls(data)

    def wait(self, source: str) -> None:
        source_config = self.config.get(source, {})
        if not isinstance(source_config, dict):
            source_config = {}
        min_delay = float(source_config.get("min_delay_seconds", 0.0) or 0.0)
        if min_delay <= 0:
            self._last_call_at[source] = time.monotonic()
            return

        now = time.monotonic()
        previous = self._last_call_at.get(source)
        if previous is not None:
            elapsed = now - previous
            remaining = min_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_call_at[source] = now
