from __future__ import annotations

import httpx

from crawler_scope.tools.academic import crossref_client


def test_fetch_crossref_by_doi_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("mailto") == "team@example.org"
        return httpx.Response(
            200,
            json={
                "message": {
                    "title": ["Crossref Title"],
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "issued": {"date-parts": [[2024, 5, 1]]},
                    "container-title": ["Journal A"],
                    "publisher": "Publisher A",
                    "URL": "https://doi.org/10.1000/test",
                    "license": [{"URL": "https://license.example/cc-by"}],
                    "link": [
                        {
                            "URL": "https://example.org/paper.pdf",
                            "content-type": "application/pdf",
                        }
                    ],
                }
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        crossref_client,
        "_make_client",
        lambda *, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=crossref_client.API_TIMEOUT,
            follow_redirects=True,
        ),
    )

    result = crossref_client.fetch_crossref_by_doi(
        "10.1000/test",
        contact_email="team@example.org",
        use_cache=False,
    )

    assert result.status == "success"
    assert result.paper is not None
    assert result.paper.title == "Crossref Title"
    assert result.paper.authors == ["Ada Lovelace"]
    assert result.paper.pdf_urls == ["https://example.org/paper.pdf"]


def test_fetch_crossref_by_doi_not_found(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": "resource not found"}, request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        crossref_client,
        "_make_client",
        lambda *, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=crossref_client.API_TIMEOUT,
            follow_redirects=True,
        ),
    )

    result = crossref_client.fetch_crossref_by_doi("10.1000/missing", use_cache=False)

    assert result.status == "not_found"
    assert result.paper is None
