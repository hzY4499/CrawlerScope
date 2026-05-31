from __future__ import annotations

import pytest

from crawler_scope.tools.academic import crossref_client
from crawler_scope.tools.storage import CacheStore


def test_cache_store_saves_and_reads_json(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache")
    key = store.make_key("crossref", "10.1000/test")

    path = store.set_json("crossref", key, {"status_code": 200, "payload": {"ok": True}})

    assert path == tmp_path / "cache" / "crossref" / f"{key}.json"
    assert store.has("crossref", key) is True
    assert store.get_json("crossref", key) == {
        "status_code": 200,
        "payload": {"ok": True},
    }


def test_cache_store_rejects_path_traversal(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache")

    with pytest.raises(ValueError):
        store.get_json("crossref", "../escape")

    with pytest.raises(ValueError):
        store.set_json("../bad", store.make_key("x"), {"ok": True})


def test_crossref_cache_hit_does_not_open_http_client(tmp_path, monkeypatch) -> None:
    store = CacheStore(tmp_path / "cache")
    doi = "10.1000/cache-hit"
    key = store.make_key("crossref", doi)
    store.set_json(
        "crossref",
        key,
        {
            "source": "crossref",
            "status_code": 200,
            "payload": {
                "message": {
                    "title": ["Cached Title"],
                    "author": [{"given": "Ada", "family": "Cache"}],
                    "issued": {"date-parts": [[2024]]},
                    "URL": "https://doi.org/10.1000/cache-hit",
                }
            },
        },
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("HTTP client should not be opened on cache hit.")

    monkeypatch.setattr(crossref_client, "_make_client", fail_if_called)

    result = crossref_client.fetch_crossref_by_doi(doi, cache_store=store)

    assert result.status == "success"
    assert result.paper is not None
    assert result.paper.title == "Cached Title"
    assert result.paper.authors == ["Ada Cache"]
