from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import unquote

from crawler_scope.schemas.doi import DOIInputItem

DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:<>[]{}\"'"


def normalize_doi(raw: str) -> str | None:
    text = unquote(raw).strip()
    if not text:
        return None

    if re.match(r"^https?://", text, flags=re.IGNORECASE) and not re.match(
        r"^https?://(?:dx\.)?doi\.org/",
        text,
        flags=re.IGNORECASE,
    ):
        return None

    text = re.sub(r"^\s*https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*doi\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*doi\s+", "", text, flags=re.IGNORECASE)

    match = DOI_PATTERN.search(text)
    if not match:
        return None

    doi = match.group(0).strip()
    doi = doi.rstrip(TRAILING_PUNCTUATION).rstrip()
    doi = doi.strip("()")

    if not DOI_PATTERN.fullmatch(doi):
        return None

    return doi.lower()


def load_doi_list(path: Path) -> list[DOIInputItem]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        rows = _read_txt_rows(path)
    elif suffix == ".csv":
        rows = _read_csv_rows(path)
    else:
        raise ValueError(f"Unsupported DOI input format: {path.suffix}")

    return _build_doi_items(rows)


def _read_txt_rows(path: Path) -> list[tuple[str, int, str | None]]:
    rows: list[tuple[str, int, str | None]] = []
    for row_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        original = line.rstrip("\r")
        if not original.strip():
            continue
        rows.append((original, row_index, None))
    return rows


def _read_csv_rows(path: Path) -> list[tuple[str, int, str | None]]:
    rows: list[tuple[str, int, str | None]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return rows

        doi_column = _find_column_name(reader.fieldnames, "doi") or reader.fieldnames[0]
        client_id_column = _find_column_name(reader.fieldnames, "client_id")

        for row_index, row in enumerate(reader, start=2):
            original_value = row.get(doi_column, "")
            original = str(original_value or "")
            if not original.strip():
                continue

            client_id = None
            if client_id_column is not None:
                client_id_value = row.get(client_id_column, "")
                client_id = str(client_id_value or "").strip() or None

            rows.append((original, row_index, client_id))
    return rows


def _find_column_name(fieldnames: list[str], expected_name: str) -> str | None:
    for fieldname in fieldnames:
        if fieldname.strip().lower() == expected_name:
            return fieldname
    return None


def _build_doi_items(rows: list[tuple[str, int, str | None]]) -> list[DOIInputItem]:
    seen_dois: set[str] = set()
    items: list[DOIInputItem] = []

    for original, row_index, client_id in rows:
        normalized_doi = normalize_doi(original)
        if normalized_doi is None:
            items.append(
                DOIInputItem(
                    original=original,
                    row_index=row_index,
                    client_id=client_id,
                    status="invalid",
                    error_message="Invalid DOI format.",
                ),
            )
            continue

        if normalized_doi in seen_dois:
            items.append(
                DOIInputItem(
                    original=original,
                    normalized_doi=normalized_doi,
                    row_index=row_index,
                    client_id=client_id,
                    status="duplicate",
                    error_message="Duplicate DOI.",
                ),
            )
            continue

        seen_dois.add(normalized_doi)
        items.append(
            DOIInputItem(
                original=original,
                normalized_doi=normalized_doi,
                row_index=row_index,
                client_id=client_id,
                status="valid",
            ),
        )

    return items
