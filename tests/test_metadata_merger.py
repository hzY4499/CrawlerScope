from __future__ import annotations

from crawler_scope.schemas import MetadataSourceResult, PaperRecord
from crawler_scope.tools.academic.metadata_merger import merge_metadata_results


def test_merge_metadata_results_combines_sources() -> None:
    crossref = MetadataSourceResult(
        doi="10.1000/test",
        source="crossref",
        status="success",
        paper=PaperRecord(
            paper_id="doi:10.1000/test",
            doi="10.1000/test",
            title="Crossref Preferred Title",
            authors=["Ada Lovelace"],
            year=2024,
            venue="Journal A",
            publisher="Publisher A",
            source_urls=["https://doi.org/10.1000/test"],
            raw={"source": "crossref"},
        ),
    )
    semantic = MetadataSourceResult(
        doi="10.1000/test",
        source="semantic_scholar",
        status="success",
        paper=PaperRecord(
            paper_id="doi:10.1000/test",
            doi="10.1000/test",
            semantic_scholar_id="S2-1",
            arxiv_id="2101.00001",
            title="Secondary Title",
            abstract="Preferred abstract",
            source_urls=["https://www.semanticscholar.org/paper/S2-1"],
            pdf_urls=["https://oa.example/file.pdf"],
            raw={"source": "semantic_scholar"},
        ),
    )
    unpaywall = MetadataSourceResult(
        doi="10.1000/test",
        source="unpaywall",
        status="success",
        paper=PaperRecord(
            paper_id="doi:10.1000/test",
            doi="10.1000/test",
            license="cc-by",
            source_urls=["https://oa.example/landing"],
            pdf_urls=["https://oa.example/file.pdf"],
            raw={
                "best_oa_location": {
                    "url_for_landing_page": "https://oa.example/landing",
                    "url_for_pdf": "https://oa.example/file.pdf",
                }
            },
        ),
    )

    merged_paper, access_hint = merge_metadata_results(
        "10.1000/test",
        [crossref, semantic, unpaywall],
    )

    assert merged_paper is not None
    assert merged_paper.title == "Crossref Preferred Title"
    assert merged_paper.abstract == "Preferred abstract"
    assert merged_paper.license == "cc-by"
    assert merged_paper.pdf_urls == ["https://oa.example/file.pdf"]
    assert access_hint.has_open_pdf is True
    assert access_hint.next_stage == "download_open_pdf"
