from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "legacy_wiley_supplement_backfill_cdp.py"
)
SPEC = importlib.util.spec_from_file_location("legacy_wiley_supplement_backfill_cdp", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


def test_filename_from_wiley_download_supplement_url_keeps_all_formats() -> None:
    assert (
        backfill.filename_from_supplement_url(
            "https://onlinelibrary.wiley.com/action/downloadSupplement?"
            "doi=10.1002%2Fanie.202502563&file=anie202502563-SuppMat.docx"
        )
        == "anie202502563-SuppMat.docx"
    )
    assert (
        backfill.filename_from_supplement_url(
            "https://onlinelibrary.wiley.com/action/downloadSupplement?"
            "doi=10.1002%2Fanie.202418670&file=anie202418670-sup-0001-Supplementary_Video_1.mov"
        )
        == "anie202418670-sup-0001-Supplementary_Video_1.mov"
    )


def test_wiley_article_url_keeps_doi_slash_but_quotes_special_characters() -> None:
    url = backfill.wiley_article_url("10.1002/1099-0682(200105)2001:5<1167::aid-ejic1167>3.0.co;2-z")

    assert url.startswith("https://onlinelibrary.wiley.com/doi/10.1002/")
    assert "%2F" not in url
    assert "%28" in url
    assert "%3C1167%3A%3Aaid-ejic1167%3E" in url


def test_extract_supplement_links_from_html_dedupes_and_does_not_filter_extensions() -> None:
    html = """
    <html><body>
      <a href="/action/downloadSupplement?doi=10.1002%2Fanie.1&file=a.pdf">Supporting Information</a>
      <a href="/action/downloadSupplement?doi=10.1002%2Fanie.1&file=b.docx">Supplementary Material</a>
      <a href="/action/downloadSupplement?doi=10.1002%2Fanie.1&file=c.xlsx">Table S1</a>
      <a href="/action/downloadSupplement?doi=10.1002%2Fanie.1&file=d.mov">Movie S1</a>
      <a href="/action/downloadSupplement?doi=10.1002%2Fanie.1&file=d.mov">Movie S1 duplicate</a>
      <a href="/doi/pdf/10.1002/anie.1">PDF</a>
    </body></html>
    """

    links = backfill.extract_supplement_links_from_html(
        "10.1002/anie.1",
        "https://onlinelibrary.wiley.com/doi/10.1002/anie.1",
        html,
    )

    assert len(links) == 4
    assert any("file=a.pdf" in link for link in links)
    assert any("file=b.docx" in link for link in links)
    assert any("file=c.xlsx" in link for link in links)
    assert any("file=d.mov" in link for link in links)
    assert all("/doi/pdf/" not in link for link in links)


def test_dedupe_links_filters_challenge_and_reference_links() -> None:
    links = backfill.dedupe_links(
        [
            "https://advanced.onlinelibrary.wiley.com/cdn-cgi/content?id=challenge",
            "https://onlinelibrary.wiley.com/action/getFTRLinkout?doi=10.1002%2Fanie.201707097",
            "https://onlinelibrary.wiley.com/action/downloadSupplement?"
            "doi=10.1002%2Fanie.201707097&file=anie201707097-sup-0001-misc_information.pdf",
        ],
        "10.1002/anie.201707097",
    )

    assert links == [
        "https://onlinelibrary.wiley.com/action/downloadSupplement?"
        "doi=10.1002%2Fanie.201707097&file=anie201707097-sup-0001-misc_information.pdf"
    ]


def test_load_corpus_records_reads_existing_record_json(tmp_path: Path) -> None:
    doi_dir = tmp_path / "10.1002_anie.202502563"
    doi_dir.mkdir()
    record_path = doi_dir / "record.json"
    record_path.write_text(
        json.dumps(
            {
                "doi": "10.1002/anie.202502563",
                "supplement_links": [
                    "https://onlinelibrary.wiley.com/action/downloadSupplement?"
                    "doi=10.1002%2Fanie.202502563&file=anie202502563-SuppMat.docx"
                ],
            }
        ),
        encoding="utf-8",
    )

    records = backfill.load_corpus_records(tmp_path)
    record = records["10.1002/anie.202502563"]

    assert record.folder == doi_dir
    assert backfill.record_supplement_links(record) == [
        "https://onlinelibrary.wiley.com/action/downloadSupplement?"
        "doi=10.1002%2Fanie.202502563&file=anie202502563-SuppMat.docx"
    ]


def test_existing_record_file_for_link_uses_legacy_relpath(tmp_path: Path) -> None:
    doi_dir = tmp_path / "10.1002_anie.202418670"
    doi_dir.mkdir()
    supplement_path = doi_dir / "supporting_information.pdf"
    supplement_path.write_bytes(b"%PDF-1.7")
    record = backfill.CorpusRecord(
        doi="10.1002/anie.202418670",
        folder=doi_dir,
        record_path=doi_dir / "record.json",
        record_data={
            "files": [
                {
                    "kind": "supplement",
                    "url": "https://onlinelibrary.wiley.com/action/downloadSupplement?"
                    "doi=10.1002%2Fanie.202418670&file=anie202418670-sup-0001-misc_information.pdf",
                    "relpath": "10.1002_anie.202418670/supporting_information.pdf",
                }
            ]
        },
    )

    existing = backfill.existing_record_file_for_link(
        record,
        "https://onlinelibrary.wiley.com/action/downloadSupplement?"
        "doi=10.1002%2Fanie.202418670&file=anie202418670-sup-0001-misc_information.pdf",
    )

    assert existing == supplement_path


def test_download_with_context_request_returns_skipped_browser_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    existing = tmp_path / "already-there.docx"
    existing.write_bytes(b"existing")

    class FakeResponse:
        status = 403
        headers = {"content-type": "text/html"}
        url = "https://onlinelibrary.wiley.com/action/downloadSupplement"

    class FakeRequest:
        def get(self, *_args, **_kwargs):
            return FakeResponse()

    fake_context = SimpleNamespace(request=FakeRequest())
    fake_page = SimpleNamespace(
        evaluate=lambda _expr: "Mozilla/5.0",
        url="https://onlinelibrary.wiley.com/doi/10.1002/example",
    )

    def fake_browser_fallback(*_args, **_kwargs):
        return {
            "status": "skipped",
            "skip_reason": "duplicate_sha256",
            "file_path": str(existing),
        }

    monkeypatch.setattr(backfill, "download_with_browser_event", fake_browser_fallback)

    result = backfill.download_with_context_request(
        fake_context,
        fake_page,
        "10.1002/example",
        "https://onlinelibrary.wiley.com/action/downloadSupplement?"
        "doi=10.1002%2Fexample&file=new-file.docx",
        tmp_path,
        timeout_ms=1000,
        max_bytes=None,
    )

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "duplicate_sha256"
    assert result["request_fallback_from"] == "download_403"
