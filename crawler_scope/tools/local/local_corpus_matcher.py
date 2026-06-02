from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from crawler_scope.schemas import (
    LocalCorpusMatchResult,
    LocalCorpusSummary,
    LocalFileRecord,
    PaperRecord,
)
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_STORE = RunStore(PROJECT_ROOT)


def load_run_papers(run_id: str) -> list[PaperRecord]:
    run_dir = RUN_STORE.get_run_dir(run_id)
    papers_path = run_dir / "artifacts" / "papers_metadata_merged.jsonl"
    valid_dois_path = run_dir / "artifacts" / "valid_dois.txt"
    if papers_path.exists():
        return _load_jsonl(papers_path, PaperRecord)
    if not valid_dois_path.exists():
        raise FileNotFoundError(
            f"Missing local corpus run inputs: {papers_path} and {valid_dois_path}"
        )
    papers: list[PaperRecord] = []
    for doi in _load_text_lines(valid_dois_path):
        papers.append(
            PaperRecord(
                paper_id=f"paper_{_safe_identifier(doi)}",
                doi=doi,
                title=None,
                raw={},
            )
        )
    return papers


def match_local_files_to_run(
    run_id: str,
    local_files: list[LocalFileRecord],
) -> tuple[list[LocalFileRecord], list[LocalCorpusMatchResult], LocalCorpusSummary]:
    run_papers = load_run_papers(run_id)
    papers_by_doi = {paper.doi: paper for paper in run_papers}
    papers_by_paper_id = {paper.paper_id: paper for paper in run_papers}
    results_by_key = {
        _result_key(paper.doi, paper.paper_id): LocalCorpusMatchResult(
            doi=paper.doi,
            paper_id=paper.paper_id,
        )
        for paper in run_papers
    }
    warnings: list[str] = []
    files_by_extension: Counter[str] = Counter()
    updated_files: list[LocalFileRecord] = []
    unmatched_files: list[LocalFileRecord] = []

    for record in local_files:
        updated_record, paper, warning = _match_record(
            record,
            papers_by_doi=papers_by_doi,
            papers_by_paper_id=papers_by_paper_id,
        )
        updated_files.append(updated_record)
        files_by_extension[updated_record.extension or "(no_extension)"] += 1
        if warning:
            warnings.append(warning)
        if paper is None:
            unmatched_files.append(updated_record)
            continue

        key = _result_key(paper.doi, paper.paper_id)
        result = results_by_key[key]
        if updated_record.file_role == "paper_pdf":
            result.paper_pdf_files.append(updated_record.file_path)
        elif updated_record.file_role == "supplement":
            result.supplement_files.append(updated_record.file_path)
        else:
            result.unmatched_files.append(updated_record.file_path)

    match_results = list(results_by_key.values())
    for result in match_results:
        if result.paper_pdf_files and result.supplement_files:
            result.status = "complete"
        elif result.paper_pdf_files:
            result.status = "paper_only"
        elif result.supplement_files:
            result.status = "supplement_only"
        else:
            result.status = "missing"

    paper_pdf_files = sum(1 for item in updated_files if item.file_role == "paper_pdf")
    supplement_files = sum(1 for item in updated_files if item.file_role == "supplement")
    unknown_files = sum(1 for item in updated_files if item.file_role == "unknown")
    matched_articles = sum(1 for item in match_results if item.status != "missing")
    articles_with_paper_pdf = sum(1 for item in match_results if item.paper_pdf_files)
    articles_with_supplements = sum(1 for item in match_results if item.supplement_files)
    complete_articles = sum(1 for item in match_results if item.status == "complete")
    missing_articles = sum(1 for item in match_results if item.status == "missing")
    ambiguous_articles = sum(1 for item in match_results if item.status == "ambiguous")

    summary = LocalCorpusSummary(
        total_files_scanned=len(updated_files),
        paper_pdf_files=paper_pdf_files,
        supplement_files=supplement_files,
        unknown_files=unknown_files,
        matched_articles=matched_articles,
        articles_with_paper_pdf=articles_with_paper_pdf,
        articles_with_supplements=articles_with_supplements,
        complete_articles=complete_articles,
        missing_articles=missing_articles,
        ambiguous_articles=ambiguous_articles,
        files_by_extension=dict(files_by_extension),
        warnings=warnings,
    )
    return updated_files, match_results, summary


def _match_record(
    record: LocalFileRecord,
    *,
    papers_by_doi: dict[str, PaperRecord],
    papers_by_paper_id: dict[str, PaperRecord],
) -> tuple[LocalFileRecord, PaperRecord | None, str | None]:
    if record.detected_doi and record.detected_doi in papers_by_doi:
        paper = papers_by_doi[record.detected_doi]
        return (
            record.model_copy(
                update={
                    "matched_doi": paper.doi,
                    "matched_paper_id": paper.paper_id,
                }
            ),
            paper,
            None,
        )
    if record.detected_paper_id and record.detected_paper_id in papers_by_paper_id:
        paper = papers_by_paper_id[record.detected_paper_id]
        return (
            record.model_copy(
                update={
                    "matched_doi": paper.doi,
                    "matched_paper_id": paper.paper_id,
                    "matched_by": "manual_mapping"
                    if record.matched_by == "unknown"
                    else record.matched_by,
                }
            ),
            paper,
            None,
        )

    folder_doi = _find_folder_doi(Path(record.file_path))
    if folder_doi and folder_doi in papers_by_doi:
        paper = papers_by_doi[folder_doi]
        return (
            record.model_copy(
                update={
                    "matched_doi": paper.doi,
                    "matched_paper_id": paper.paper_id,
                    "matched_by": "folder_doi",
                }
            ),
            paper,
            None,
        )

    return record, None, None


def _find_folder_doi(path: Path) -> str | None:
    for parent in path.parents:
        doi = _restore_safe_doi(parent.name)
        if doi:
            return doi
    return None


def _restore_safe_doi(text: str) -> str | None:
    if not re.match(r"10\.\d{4,9}[_-].+", text, flags=re.IGNORECASE):
        return None
    prefix, separator, suffix = text.partition("_")
    if not separator:
        prefix, separator, suffix = text.partition("-")
    if not separator:
        return None
    return f"{prefix}/{suffix}"


def _load_jsonl(path: Path, model_class):
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(model_class.model_validate_json(line))
    return items


def _load_text_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def _result_key(doi: str | None, paper_id: str | None) -> str:
    return doi or paper_id or "unknown"
