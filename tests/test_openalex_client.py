from __future__ import annotations

import httpx

from crawler_scope.tools.academic import openalex_client


def test_fetch_openalex_by_doi_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1000/test",
                "display_name": "OpenAlex Title",
                "publication_year": 2022,
                "authorships": [
                    {"author": {"display_name": "Alice"}},
                    {"author": {"display_name": "Bob"}},
                ],
                "abstract_inverted_index": {
                    "metadata": [0],
                    "from": [1],
                    "openalex": [2],
                },
                "open_access": {"is_oa": True},
                "primary_location": {
                    "landing_page_url": "https://journal.example/article",
                    "pdf_url": "https://journal.example/article.pdf",
                    "license": "cc-by",
                    "source": {
                        "display_name": "Journal B",
                        "host_organization_name": "Publisher B",
                    },
                },
                "locations": [
                    {
                        "landing_page_url": "https://repo.example/landing",
                        "pdf_url": "https://repo.example/file.pdf",
                    }
                ],
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        openalex_client,
        "_make_client",
        lambda *, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=openalex_client.API_TIMEOUT,
            follow_redirects=True,
        ),
    )

    result = openalex_client.fetch_openalex_by_doi("10.1000/test")

    assert result.status == "success"
    assert result.paper is not None
    assert result.paper.openalex_id == "https://openalex.org/W123"
    assert result.paper.abstract == "metadata from openalex"
    assert result.paper.is_open_access is True
    assert "https://journal.example/article.pdf" in result.paper.pdf_urls
