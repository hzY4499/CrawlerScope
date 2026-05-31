from __future__ import annotations

import httpx

from crawler_scope.tools.academic import unpaywall_client


def test_fetch_unpaywall_by_doi_success(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("email") == "team@example.org"
        return httpx.Response(
            200,
            json={
                "doi_url": "https://doi.org/10.1000/test",
                "title": "Unpaywall Title",
                "year": 2020,
                "publisher": "Publisher D",
                "journal_name": "Journal D",
                "is_oa": True,
                "best_oa_location": {
                    "url_for_landing_page": "https://oa.example/landing",
                    "url_for_pdf": "https://oa.example/file.pdf",
                    "license": "cc-by",
                },
                "oa_locations": [
                    {"url_for_landing_page": "https://repo.example/landing"}
                ],
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        unpaywall_client,
        "_make_client",
        lambda *, headers: httpx.Client(
            transport=transport,
            headers=headers,
            timeout=unpaywall_client.API_TIMEOUT,
            follow_redirects=True,
        ),
    )

    result = unpaywall_client.fetch_unpaywall_by_doi(
        "10.1000/test",
        contact_email="team@example.org",
        use_cache=False,
    )

    assert result.status == "success"
    assert result.paper is not None
    assert result.paper.pdf_urls == ["https://oa.example/file.pdf"]
    assert result.paper.license == "cc-by"


def test_fetch_unpaywall_by_doi_requires_contact_email() -> None:
    result = unpaywall_client.fetch_unpaywall_by_doi("10.1000/test", contact_email=None)

    assert result.status == "failed"
    assert result.error_type == "missing_contact_email"
