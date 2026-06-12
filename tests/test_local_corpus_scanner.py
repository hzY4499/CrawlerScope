from __future__ import annotations

import json
from pathlib import Path

import fitz

from crawler_scope.tools.local.local_corpus_scanner import scan_local_corpus, scan_local_file


def test_local_corpus_scanner_scans_multiple_formats_and_extracts_doi(
    tmp_path: Path,
) -> None:
    paper_dir = tmp_path / "papers"
    supplement_dir = tmp_path / "supplements"
    paper_dir.mkdir()
    supplement_dir.mkdir()

    pdf_path = paper_dir / "generic_article" / "paper.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Example DOI 10.1002/chem.202001050")
    document.save(pdf_path)
    document.close()

    scanned_pdf = scan_local_file(pdf_path, role_hint="paper_pdf_dir")
    assert scanned_pdf.file_role == "paper_pdf"
    assert scanned_pdf.detected_doi == "10.1002/chem.202001050"
    assert scanned_pdf.matched_by == "pdf_text_doi"

    safe_doi_dir = supplement_dir / "10.1002_chem.202001050"
    safe_doi_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in {
        "dataset.zip": b"PK\x03\x04zip",
        "table.csv": b"a,b\n1,2\n",
        "movie.mp4": b"mp4data",
        "image.png": b"\x89PNG\r\n",
        "notes.txt": b"note",
    }.items():
        (safe_doi_dir / filename).write_bytes(content)

    ignored_dir = supplement_dir / "ignored"
    ignored_dir.mkdir()
    for filename in [".DS_Store", ".hidden", "download.part", "temp.tmp", "file.crdownload", "README.txt"]:
        (ignored_dir / filename).write_bytes(b"ignored")

    records = scan_local_corpus(
        paper_pdf_dir=paper_dir,
        supplement_dir=supplement_dir,
    )

    assert len(records) == 6
    by_name = {record.filename: record for record in records}
    assert by_name["dataset.zip"].detected_doi == "10.1002/chem.202001050"
    assert by_name["dataset.zip"].matched_by == "folder_doi"
    assert by_name["dataset.zip"].file_role == "supplement"
    assert by_name["table.csv"].file_role == "supplement"
    assert by_name["movie.mp4"].extension == ".mp4"
    assert by_name["image.png"].extension == ".png"
    assert by_name["notes.txt"].extension == ".txt"
    assert all(record.sha256 for record in records)
    assert all(record.size_bytes > 0 for record in records)


def test_local_corpus_scanner_respects_existing_unified_tree_layout(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "Wiley" / "article_001"
    supplement_dir = root_dir / "supplementaryfiles"
    supplement_dir.mkdir(parents=True)
    pdf_path = root_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")
    zip_path = supplement_dir / "dataset.zip"
    zip_path.write_bytes(b"PK\x03\x04zip")

    records = scan_local_corpus(paper_pdf_dir=root_dir.parent.parent)
    by_name = {record.filename: record for record in records}

    assert by_name["paper.pdf"].file_role == "paper_pdf"
    assert by_name["dataset.zip"].file_role == "supplement"


def test_local_corpus_scanner_uses_record_json_manifest_for_complex_wiley_doi(
    tmp_path: Path,
) -> None:
    complex_doi = "10.1002/1439-7641(20020816)3:8<686::aid-cphc686>3.0.co;2-g"
    safe_dir = (
        tmp_path
        / "10.1002_1439-7641_20020816_3_8_686_aid-cphc686_3.0.co_2-g"
    )
    safe_dir.mkdir(parents=True)
    (safe_dir / "record.json").write_text(
        json.dumps({"doi": complex_doi}),
        encoding="utf-8",
    )
    pdf_path = safe_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")
    supplement_path = safe_dir / "supporting_information.pdf"
    supplement_path.write_bytes(b"%PDF-1.7 supplement")

    records = scan_local_corpus(paper_pdf_dir=tmp_path)
    by_name = {record.filename: record for record in records}

    assert by_name["paper.pdf"].detected_doi == complex_doi.lower()
    assert by_name["paper.pdf"].matched_by == "manifest"
    assert by_name["supporting_information.pdf"].detected_doi == complex_doi.lower()
    assert by_name["supporting_information.pdf"].matched_by == "manifest"
