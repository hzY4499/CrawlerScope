from __future__ import annotations

import httpx

from crawler_scope.tools.academic import semantic_scholar_client


def test_fetch_semantic_scholar_by_doi_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "secret-key"
        return httpx.Response(
            200,
            json={
                "paperId": "S2-123",
                "title": "Semantic Scholar Title",
                "year": 2021,
                "authors": [{"name": "Carol"}],
                "abstract": "Semantic abstract",
                "venue": "Conference C",
                "url": "https://www.semanticscholar.org/paper/S2-123",
                "externalIds": {"DOI": "10.1000/test", "ARXIV": "2101.00001"},
                "openAccessPdf": {"url": "https://pdfs.example/s2.pdf"},
                "isOpenAccess": True,
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        semantic_scholar_client,
        "_make_client",
        lambda *, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=semantic_scholar_client.API_TIMEOUT,
            follow_redirects=True,
        ),
    )

    result = semantic_scholar_client.fetch_semantic_scholar_by_doi(
        "10.1000/test",
        api_key="secret-key",
        use_cache=False,
    )

    assert result.status == "success"
    assert result.paper is not None
    assert result.paper.semantic_scholar_id == "S2-123"
    assert result.paper.arxiv_id == "2101.00001"
    assert result.paper.pdf_urls == ["https://pdfs.example/s2.pdf"]
