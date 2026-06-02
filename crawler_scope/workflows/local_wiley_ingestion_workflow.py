from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import LocalCorpusMatchResult, LocalFileRecord
from crawler_scope.tools.local import match_local_files_to_run
from crawler_scope.tools.local import local_corpus_scanner
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def ingest_local_wiley_corpus_for_run(
    run_id: str,
    paper_pdf_dir: Path | None = None,
    supplement_dir: Path | None = None,
) -> dict:
    if paper_pdf_dir is None and supplement_dir is None:
        raise ValueError("At least one of --paper-pdf-dir or --supplement-dir must be provided.")

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "local_ingestion_start",
            "timestamp": _iso_now(),
            "paper_pdf_dir": str(paper_pdf_dir) if paper_pdf_dir is not None else None,
            "supplement_dir": str(supplement_dir) if supplement_dir is not None else None,
        },
    )

    try:
        local_files, scan_warnings = local_corpus_scanner._scan_local_corpus_with_warnings(
            paper_pdf_dir=paper_pdf_dir,
            supplement_dir=supplement_dir,
        )
        for record in local_files:
            RUN_STORE.append_trace(
                run_id,
                {
                    "event": "local_file_scanned",
                    "timestamp": _iso_now(),
                    "file_path": record.file_path,
                    "file_role": record.file_role,
                    "detected_doi": record.detected_doi,
                    "detected_paper_id": record.detected_paper_id,
                },
            )

        updated_files, match_results, summary = match_local_files_to_run(run_id, local_files)
        combined_warnings = list(summary.warnings) + scan_warnings
        summary = summary.model_copy(update={"warnings": combined_warnings})

        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_file_inventory.jsonl",
            _jsonl_text(updated_files),
        )
        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_file_inventory.csv",
            _render_local_files_csv(updated_files),
        )
        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_match_results.jsonl",
            _jsonl_text(match_results),
        )
        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_match_results.csv",
            _render_match_results_csv(match_results),
        )
        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_unmatched_files.csv",
            _render_local_files_csv(
                [item for item in updated_files if not item.matched_doi and not item.matched_paper_id]
            ),
        )
        RUN_STORE.save_text(
            run_id,
            "artifacts/local_wiley_missing_articles.csv",
            _render_match_results_csv(
                [item for item in match_results if item.status == "missing"]
            ),
        )
        RUN_STORE.save_json(
            run_id,
            "artifacts/local_wiley_ingestion_summary.json",
            summary,
        )
    except Exception as exc:
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "local_ingestion_failed",
                "timestamp": _iso_now(),
                "error_message": str(exc),
            },
        )
        raise

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "local_matching_success",
            "timestamp": _iso_now(),
            "matched_articles": summary.matched_articles,
            "complete_articles": summary.complete_articles,
            "missing_articles": summary.missing_articles,
        },
    )
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "local_ingestion_success",
            "timestamp": _iso_now(),
            **summary.model_dump(mode="json"),
        },
    )
    result = summary.model_dump(mode="json")
    result["local_wiley_match_results_csv"] = str(
        RUN_STORE.get_run_dir(run_id) / "artifacts" / "local_wiley_match_results.csv"
    )
    result["local_wiley_unmatched_files_csv"] = str(
        RUN_STORE.get_run_dir(run_id) / "artifacts" / "local_wiley_unmatched_files.csv"
    )
    result["local_wiley_missing_articles_csv"] = str(
        RUN_STORE.get_run_dir(run_id) / "artifacts" / "local_wiley_missing_articles.csv"
    )
    return result


def _jsonl_text(items) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _render_local_files_csv(items: list[LocalFileRecord]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "file_path",
        "filename",
        "extension",
        "content_type",
        "sha256",
        "size_bytes",
        "file_role",
        "detected_doi",
        "detected_paper_id",
        "parent_dir",
        "matched_doi",
        "matched_paper_id",
        "matched_by",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _render_match_results_csv(items: list[LocalCorpusMatchResult]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "doi",
        "paper_id",
        "paper_pdf_files",
        "supplement_files",
        "unmatched_files",
        "status",
        "warnings",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        row["paper_pdf_files"] = " | ".join(row.get("paper_pdf_files", []))
        row["supplement_files"] = " | ".join(row.get("supplement_files", []))
        row["unmatched_files"] = " | ".join(row.get("unmatched_files", []))
        row["warnings"] = " | ".join(row.get("warnings", []))
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
