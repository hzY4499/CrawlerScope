from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
from collections import Counter
from pathlib import Path

from crawler_scope.schemas import ManualDownloadTask, ManualDownloadedFile, ManualScanSummary
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_STORE = RunStore(PROJECT_ROOT)
IGNORED_FILENAMES = {"README.txt", ".DS_Store"}
IGNORED_SUFFIXES = {".crdownload", ".part", ".tmp"}


def scan_manual_supplement_folder(
    task: ManualDownloadTask,
) -> list[ManualDownloadedFile]:
    target_dir = Path(task.target_dir)
    if not target_dir.exists():
        return []

    results: list[ManualDownloadedFile] = []
    for path in sorted(target_dir.rglob("*")):
        if not path.is_file():
            continue
        if _should_ignore(path):
            continue
        sha256, size_bytes = _hash_file(path)
        content_type, _ = mimetypes.guess_type(path.name)
        results.append(
            ManualDownloadedFile(
                doi=task.doi,
                paper_id=task.paper_id,
                source_dir=str(target_dir),
                file_path=str(path),
                filename=path.name,
                extension=path.suffix.lower() or None,
                content_type=content_type,
                sha256=sha256,
                size_bytes=size_bytes,
                matched_by="folder_name",
            )
        )
    return results


def scan_manual_supplements_for_run(run_id: str) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    tasks_path = run_dir / "artifacts" / "wiley_manual_download_tasks.jsonl"
    if not tasks_path.exists():
        raise FileNotFoundError(f"Missing manual download tasks file: {tasks_path}")

    tasks = _load_jsonl(tasks_path, ManualDownloadTask)
    downloaded_files: list[ManualDownloadedFile] = []
    missing_tasks: list[ManualDownloadTask] = []
    warnings: list[str] = []
    files_by_extension: Counter[str] = Counter()
    articles_with_files = 0

    for task in tasks:
        try:
            files = scan_manual_supplement_folder(task)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(
                f"Failed to scan {task.target_dir} for DOI {task.doi or 'unknown'}: {exc}"
            )
            files = []
        if files:
            articles_with_files += 1
        else:
            missing_tasks.append(task.model_copy(update={"status": "missing"}))
        for file_record in files:
            downloaded_files.append(file_record)
            files_by_extension[file_record.extension or "(no_extension)"] += 1

    summary = ManualScanSummary(
        total_tasks=len(tasks),
        pending_tasks=len(missing_tasks),
        articles_with_files=articles_with_files,
        total_files=len(downloaded_files),
        files_by_extension=dict(files_by_extension),
        missing_articles=len(missing_tasks),
        warnings=warnings,
    )

    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_downloaded_files.jsonl",
        _jsonl_text(downloaded_files),
    )
    RUN_STORE.save_json(run_id, "artifacts/wiley_manual_scan_summary.json", summary)
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_scan_report.csv",
        _render_files_csv(downloaded_files),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_missing.csv",
        _render_missing_csv(missing_tasks),
    )
    return summary.model_dump(mode="json")


def _hash_file(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            size_bytes += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size_bytes


def _should_ignore(path: Path) -> bool:
    if path.name in IGNORED_FILENAMES:
        return True
    if path.name.startswith("."):
        return True
    if path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def _load_jsonl(path: Path, model_class):
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(model_class.model_validate_json(line))
    return items


def _jsonl_text(items: list[ManualDownloadedFile]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _render_files_csv(items: list[ManualDownloadedFile]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "doi",
        "paper_id",
        "publisher",
        "source_dir",
        "file_path",
        "filename",
        "extension",
        "content_type",
        "sha256",
        "size_bytes",
        "matched_by",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        row = item.model_dump(mode="json")
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _render_missing_csv(tasks: list[ManualDownloadTask]) -> str:
    buffer = io.StringIO()
    fieldnames = ["doi", "paper_id", "publisher", "article_url", "target_dir", "status", "reason", "notes"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for task in tasks:
        row = task.model_dump(mode="json")
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()
