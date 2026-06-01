from __future__ import annotations

from pathlib import Path

from crawler_scope.schemas import ManualDownloadTask
from crawler_scope.tools.manual.local_supplement_scanner import scan_manual_supplement_folder


def test_scan_manual_supplement_folder_supports_many_formats_and_ignores_temp_files(
    tmp_path: Path,
) -> None:
    target_dir = tmp_path / "10.1000_wiley"
    target_dir.mkdir(parents=True)
    nested_dir = target_dir / "nested"
    nested_dir.mkdir()

    files = {
        "one.pdf": b"%PDF-1.7",
        "two.docx": b"PK\x03\x04docx",
        "three.xlsx": b"PK\x03\x04xlsx",
        "four.zip": b"PK\x03\x04zip",
        "five.csv": b"a,b\n1,2\n",
        "six.mov": b"movdata",
        "nested/seven.mp4": b"mp4data",
    }
    ignored_files = {
        "README.txt": b"readme",
        ".DS_Store": b"junk",
        "downloading.crdownload": b"temp",
        "partial.part": b"temp",
        "temp.tmp": b"temp",
    }

    for relative_path, content in files.items():
        path = target_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for relative_path, content in ignored_files.items():
        path = target_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    task = ManualDownloadTask(
        doi="10.1000/wiley",
        article_url="https://onlinelibrary.wiley.com/doi/10.1000/wiley",
        target_dir=str(target_dir),
    )

    scanned_files = scan_manual_supplement_folder(task)

    assert len(scanned_files) == 7
    assert {item.extension for item in scanned_files} == {
        ".pdf",
        ".docx",
        ".xlsx",
        ".zip",
        ".csv",
        ".mov",
        ".mp4",
    }
    assert all(item.sha256 for item in scanned_files)
    assert all(item.size_bytes > 0 for item in scanned_files)
    assert all(item.matched_by == "folder_name" for item in scanned_files)
