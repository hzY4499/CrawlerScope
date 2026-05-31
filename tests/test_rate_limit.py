from __future__ import annotations

from crawler_scope.utils import rate_limit
from crawler_scope.utils.rate_limit import SimpleRateLimiter


def test_simple_rate_limiter_waits_between_same_source_calls(monkeypatch) -> None:
    current_time = {"value": 0.0}
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return current_time["value"]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time["value"] += seconds

    monkeypatch.setattr(rate_limit.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limit.time, "sleep", fake_sleep)

    limiter = SimpleRateLimiter({"crossref": {"min_delay_seconds": 1.5}})
    limiter.wait("crossref")
    current_time["value"] = 0.5
    limiter.wait("crossref")

    assert sleeps == [1.0]
