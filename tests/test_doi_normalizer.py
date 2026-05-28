from __future__ import annotations

from pathlib import Path

import pytest

from crawler_scope.tools.doi import load_doi_list, normalize_doi


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1000/XYZ-123", "10.1000/xyz-123"),
        (" https://doi.org/10.1000/XYZ-123 ", "10.1000/xyz-123"),
        ("http://dx.doi.org/10.1000/XYZ-123", "10.1000/xyz-123"),
        ("doi:10.1000/XYZ-123", "10.1000/xyz-123"),
        ("DOI 10.1000/XYZ-123", "10.1000/xyz-123"),
    ],
)
def test_normalize_doi_supported_formats(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", ["", "not a doi", "https://example.com/10.1000/test"])
def test_normalize_doi_invalid_returns_none(raw: str) -> None:
    assert normalize_doi(raw) is None


def test_load_doi_list_from_txt_fixture() -> None:
    fixture_path = Path("tests/fixtures/sample_dois.txt")

    items = load_doi_list(fixture_path)

    assert len(items) == 5
    assert [item.status for item in items] == [
        "valid",
        "valid",
        "invalid",
        "duplicate",
        "valid",
    ]
    assert items[0].normalized_doi == "10.1000/abc-123"
    assert items[2].error_message == "Invalid DOI format."
    assert items[3].normalized_doi == "10.1000/abc-123"
    assert [item.row_index for item in items] == [1, 2, 4, 5, 6]


def test_load_doi_list_from_csv_doi_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "dois.csv"
    csv_path.write_text(
        "client_id,doi\nc1,10.1000/ABC\nc2,doi:10.1000/ABC\nc3,not-a-doi\n",
        encoding="utf-8",
    )

    items = load_doi_list(csv_path)

    assert [item.client_id for item in items] == ["c1", "c2", "c3"]
    assert [item.status for item in items] == ["valid", "duplicate", "invalid"]


def test_load_doi_list_from_csv_first_column_fallback(tmp_path: Path) -> None:
    csv_path = tmp_path / "dois_first_column.csv"
    csv_path.write_text(
        "identifier,client_id\n10.1000/FIRST,c1\nhttps://doi.org/10.1000/SECOND,c2\n",
        encoding="utf-8",
    )

    items = load_doi_list(csv_path)

    assert [item.normalized_doi for item in items] == [
        "10.1000/first",
        "10.1000/second",
    ]
