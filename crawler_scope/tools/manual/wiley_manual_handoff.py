from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from crawler_scope.schemas import ManualDownloadTask, ManualHandoffRecord, PaperRecord
from crawler_scope.tools.publishers import build_wiley_article_url_from_doi
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_STORE = RunStore(PROJECT_ROOT)


def build_wiley_manual_download_tasks_for_run(
    run_id: str,
    base_manual_dir: Path = Path("data/manual/wiley_supplements"),
) -> list[ManualDownloadTask]:
    run_dir = RUN_STORE.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"
    manual_handoff_path = artifacts_dir / "wiley_manual_handoff.jsonl"
    papers_path = artifacts_dir / "papers_metadata_merged.jsonl"
    valid_dois_path = artifacts_dir / "valid_dois.txt"
    resolved_base_dir = (PROJECT_ROOT / base_manual_dir).resolve()
    resolved_base_dir.mkdir(parents=True, exist_ok=True)

    tasks = _build_tasks_from_sources(
        manual_handoff_path=manual_handoff_path,
        papers_path=papers_path,
        valid_dois_path=valid_dois_path,
        resolved_base_dir=resolved_base_dir,
    )

    for task in tasks:
        target_dir = Path(task.target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "README.txt").write_text(
            _build_readme_text(task),
            encoding="utf-8",
        )

    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_download_tasks.jsonl",
        _jsonl_text(tasks),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_download_tasks.csv",
        _render_tasks_csv(tasks),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/wiley_manual_download_instructions.md",
        _build_instructions_md(run_id, tasks, resolved_base_dir),
    )
    return tasks


def _build_tasks_from_sources(
    *,
    manual_handoff_path: Path,
    papers_path: Path,
    valid_dois_path: Path,
    resolved_base_dir: Path,
) -> list[ManualDownloadTask]:
    if manual_handoff_path.exists():
        handoffs = _load_jsonl(manual_handoff_path, ManualHandoffRecord)
        return [
            _build_task(
                doi=handoff.doi,
                paper_id=handoff.paper_id,
                article_url=handoff.article_url or build_wiley_article_url_from_doi(handoff.doi or "unknown"),
                target_dir=resolved_base_dir / _safe_identifier(handoff.doi or handoff.paper_id or "unknown"),
                reason=handoff.reason,
                notes=handoff.next_action,
            )
            for handoff in handoffs
        ]

    if papers_path.exists():
        candidates = _load_candidates(papers_path, valid_dois_path)
        return [
            _build_task(
                doi=candidate["doi"],
                paper_id=candidate.get("paper_id"),
                article_url=candidate.get("article_url")
                or build_wiley_article_url_from_doi(candidate["doi"]),
                target_dir=resolved_base_dir / _safe_identifier(candidate["doi"]),
                reason="wiley_manual_download",
                notes="Browser automation was not used for this manual handoff.",
            )
            for candidate in candidates
        ]

    if not valid_dois_path.exists():
        raise FileNotFoundError(
            f"Missing manual handoff inputs: {manual_handoff_path}, {papers_path}, and {valid_dois_path}"
        )

    dois = [
        line.strip()
        for line in valid_dois_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [
        _build_task(
            doi=doi,
            paper_id=None,
            article_url=build_wiley_article_url_from_doi(doi),
            target_dir=resolved_base_dir / _safe_identifier(doi),
            reason="wiley_manual_download",
            notes="Manual download task created from valid DOI list.",
        )
        for doi in dois
    ]


def _build_task(
    *,
    doi: str | None,
    paper_id: str | None,
    article_url: str,
    target_dir: Path,
    reason: str | None,
    notes: str | None,
) -> ManualDownloadTask:
    return ManualDownloadTask(
        doi=doi,
        paper_id=paper_id,
        article_url=article_url,
        target_dir=str(target_dir),
        reason=reason,
        notes=notes,
    )


def _build_readme_text(task: ManualDownloadTask) -> str:
    doi_value = task.doi or "unknown"
    lines = [
        "Wiley Manual Supplement Download",
        "",
        f"DOI: {doi_value}",
        f"Article URL: {task.article_url}",
        "",
        "Please use a real browser to open the article URL above.",
        "Download all Supporting Information / Supplementary Materials.",
        "Keep all file formats. Do not limit the download to PDF or DOCX only.",
        "After downloading, place every supplement file into this directory.",
    ]
    if task.notes:
        lines.extend(["", f"Notes: {task.notes}"])
    return "\n".join(lines) + "\n"


def _load_candidates(papers_path: Path, valid_dois_path: Path) -> list[dict[str, str | None]]:
    if papers_path.exists():
        papers = _load_jsonl(papers_path, PaperRecord)
        return [
            {
                "doi": paper.doi,
                "paper_id": paper.paper_id,
                "article_url": _find_wiley_url(paper),
            }
            for paper in papers
            if _is_wiley_paper(paper)
        ]

    if not valid_dois_path.exists():
        raise FileNotFoundError(
            f"Missing manual handoff inputs: {papers_path} and {valid_dois_path}"
        )

    dois = [
        line.strip()
        for line in valid_dois_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [{"doi": doi, "paper_id": None, "article_url": None} for doi in dois]


def _is_wiley_paper(paper: PaperRecord) -> bool:
    publisher = (paper.publisher or "").lower()
    venue = (paper.venue or "").lower()
    urls = " ".join(paper.source_urls).lower()
    return (
        "wiley" in publisher
        or "wiley" in venue
        or "onlinelibrary.wiley.com" in urls
    )


def _find_wiley_url(paper: PaperRecord) -> str | None:
    for url in paper.source_urls:
        if "onlinelibrary.wiley.com" in url.lower():
            return url
    return None


def _build_instructions_md(
    run_id: str,
    tasks: list[ManualDownloadTask],
    base_dir: Path,
) -> str:
    lines = [
        f"# Wiley Manual Download Instructions: {run_id}",
        "",
        f"- Base manual directory: {base_dir}",
        f"- Total tasks: {len(tasks)}",
        "",
        "## Steps",
        "1. Use a real browser to open each article URL.",
        "2. Download all Supporting Information / Supplementary Materials.",
        "3. Keep all formats, not just PDF or DOCX.",
        "4. Place downloaded files into the matching DOI directory under the base manual directory.",
        "5. After manual download finishes, run `python main.py scan-wiley-manual-downloads --run-id RUN_ID`.",
        "",
        "## Tasks",
    ]
    for task in tasks:
        lines.append(f"- DOI: {task.doi or 'unknown'}")
        lines.append(f"  Article URL: {task.article_url}")
        lines.append(f"  Target Dir: {task.target_dir}")
    return "\n".join(lines) + "\n"


def _render_tasks_csv(tasks: list[ManualDownloadTask]) -> str:
    buffer = io.StringIO()
    fieldnames = ["doi", "paper_id", "publisher", "article_url", "target_dir", "status", "reason", "notes"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for task in tasks:
        row = task.model_dump(mode="json")
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


def _jsonl_text(items: list[ManualDownloadTask]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _load_jsonl(path: Path, model_class):
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(model_class.model_validate_json(line))
    return items


def _safe_identifier(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return sanitized or "unknown"
