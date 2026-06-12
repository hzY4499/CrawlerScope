#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler_scope.tools.publishers.wiley_supplement_adapter import (  # noqa: E402
    has_wiley_access_challenge,
    parse_wiley_supplements_from_html,
)

DEFAULT_RUN_ID = "run_20260612_181905_51bf"
DEFAULT_CORPUS_DIR = Path(
    "/Users/yaoyiyao/Desktop/04-\u5316\u5b66\u722c\u866b\u9879\u76ee\u8bc4\u4f30/"
    "\u53e4\u8001\u6587\u4ef6\u5939/doi_clean/wiley/doi-Wiley_cdp_downloads"
)
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
USER_AGENT_FALLBACK = "Mozilla/5.0 CrawlerScope Wiley supplement backfill"

IGNORED_EXISTING = {"paper.pdf", "record.json", "README.txt", ".DS_Store"}
DOWNLOADSUPPLEMENT_RE = re.compile(
    r"""(?:"|')(?P<url>(?:https?://[^"']+)?/action/downloadSupplement\?[^"']+)""",
    re.IGNORECASE,
)


@dataclass
class CorpusRecord:
    doi: str
    folder: Path
    record_path: Path | None
    record_data: dict[str, Any]


def normalize_doi(value: str) -> str:
    return value.strip().lower()


def safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._") or "supplement"


def wiley_article_url(doi: str) -> str:
    return f"https://onlinelibrary.wiley.com/doi/{quote(doi, safe='/')}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dois_from_file(path: Path) -> list[str]:
    seen: set[str] = set()
    dois: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        doi = line.strip()
        if not doi:
            continue
        key = normalize_doi(doi)
        if key in seen:
            continue
        seen.add(key)
        dois.append(doi)
    return dois


def load_default_doi_queue(run_id: str, artifacts_dir: Path) -> list[str]:
    preferred = artifacts_dir / "legacy_wiley_all_format_backfill_queue.txt"
    if preferred.exists():
        return load_dois_from_file(preferred)
    valid = artifacts_dir / "valid_dois.txt"
    if valid.exists():
        return load_dois_from_file(valid)
    raise FileNotFoundError(f"No DOI queue found for {run_id}: {preferred} or {valid}")


def load_corpus_records(corpus_dir: Path) -> dict[str, CorpusRecord]:
    records: dict[str, CorpusRecord] = {}
    for record_path in sorted(corpus_dir.rglob("record.json")):
        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        doi = data.get("doi")
        if not isinstance(doi, str) or not doi.strip():
            continue
        key = normalize_doi(doi)
        records.setdefault(
            key,
            CorpusRecord(
                doi=key,
                folder=record_path.parent,
                record_path=record_path,
                record_data=data,
            ),
        )

    for child in sorted(corpus_dir.iterdir() if corpus_dir.exists() else []):
        if not child.is_dir() or not child.name.lower().startswith("10."):
            continue
        doi = safe_folder_name_to_doi(child.name)
        if doi:
            records.setdefault(
                normalize_doi(doi),
                CorpusRecord(
                    doi=normalize_doi(doi),
                    folder=child,
                    record_path=None,
                    record_data={},
                ),
            )
    return records


def safe_folder_name_to_doi(value: str) -> str | None:
    if "_" not in value and "/" not in value:
        return None
    candidate = value.replace("_", "/", 1)
    if re.match(r"^10\.\d{4,9}/", candidate, flags=re.IGNORECASE):
        return candidate.lower()
    return None


def record_supplement_links(record: CorpusRecord) -> list[str]:
    links: list[str] = []
    raw_links = record.record_data.get("supplement_links")
    if isinstance(raw_links, list):
        links.extend(link for link in raw_links if isinstance(link, str) and link.strip())

    files = record.record_data.get("files")
    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue
            if item.get("kind") != "supplement":
                continue
            url = item.get("url")
            if isinstance(url, str) and url.strip():
                links.append(url)
    return dedupe_links(links, record.doi)


def existing_record_file_for_link(record: CorpusRecord, link: str) -> Path | None:
    files = record.record_data.get("files")
    if not isinstance(files, list):
        return None
    normalized_link = normalize_supplement_url(link)
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "supplement":
            continue
        url = item.get("url")
        relpath = item.get("relpath")
        if not isinstance(url, str) or not isinstance(relpath, str):
            continue
        if normalize_supplement_url(url) != normalized_link:
            continue
        candidate = record.folder.parent / relpath
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_supplement_links_from_html(
    doi: str,
    article_url: str,
    html: str,
) -> list[str]:
    links: list[str] = []
    for record in parse_wiley_supplements_from_html(doi=doi, article_url=article_url, html=html):
        links.append(record.supplement_url)
    for match in DOWNLOADSUPPLEMENT_RE.finditer(html):
        raw = match.group("url").replace("&amp;", "&")
        links.append(urljoin(article_url, raw))
    return dedupe_links(links, doi)


def dedupe_links(links: list[str], doi: str | None = None) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for link in links:
        normalized = normalize_supplement_url(link)
        if not normalized:
            continue
        if doi and not link_matches_doi(normalized, doi):
            continue
        if looks_like_main_pdf_url(normalized):
            continue
        if not looks_like_downloadable_supplement_url(normalized):
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def normalize_supplement_url(link: str) -> str | None:
    link = link.strip().replace("&amp;", "&")
    if not link:
        return None
    if link.startswith("//"):
        link = "https:" + link
    parsed = urlparse(link)
    if not parsed.scheme:
        link = urljoin("https://onlinelibrary.wiley.com/", link)
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"}:
        return None
    return link


def looks_like_main_pdf_url(link: str) -> bool:
    lowered = link.lower()
    return "/doi/pdf" in lowered or "/doi/pdfdirect" in lowered or "/doi/epdf" in lowered


def looks_like_downloadable_supplement_url(link: str) -> bool:
    lowered = link.lower()
    if "/action/downloadsupplement" in lowered:
        return True
    if "/action/getftrlinkout" in lowered or "/cdn-cgi/" in lowered:
        return False
    filename = filename_from_supplement_url(link)
    extension = Path(filename).suffix.lower()
    return extension in {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".zip",
        ".csv",
        ".txt",
        ".mov",
        ".mp4",
        ".avi",
        ".mp3",
        ".wav",
        ".xml",
        ".json",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }


def link_matches_doi(link: str, doi: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    doi_value = query.get("doi", [None])[0]
    if doi_value:
        return normalize_doi(unquote(doi_value)) == normalize_doi(doi)
    return True


def filename_from_supplement_url(link: str) -> str:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    for key in ("file", "filename"):
        value = query.get(key, [None])[0]
        if value:
            return safe_filename(Path(unquote(value)).name)
    path_name = Path(unquote(parsed.path)).name
    if path_name and path_name.lower() != "downloadsupplement":
        return safe_filename(path_name)
    return safe_filename(hashlib.sha256(link.encode("utf-8")).hexdigest()[:12])


def filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    star = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if star:
        return safe_filename(unquote(star.group(1).strip().strip('"')))
    plain = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
    if plain:
        return safe_filename(plain.group(1).strip())
    return None


def existing_casefold_path(directory: Path, filename: str) -> Path | None:
    target = filename.casefold()
    for child in directory.iterdir() if directory.exists() else []:
        if child.is_file() and child.name.casefold() == target:
            return child
    return None


def existing_hashes(directory: Path) -> dict[str, Path]:
    hashes: dict[str, Path] = {}
    if not directory.exists():
        return hashes
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.name in IGNORED_EXISTING or path.name.startswith("."):
            continue
        if path.suffix.lower() in {".part", ".tmp", ".crdownload"}:
            continue
        try:
            hashes[sha256_file(path)] = path
        except Exception:
            continue
    return hashes


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def unique_path(directory: Path, filename: str, sha256: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "supplement"
    suffix = candidate.suffix
    return directory / f"{stem}_{sha256[:12]}{suffix}"


def looks_like_html(data: bytes, content_type: str | None) -> bool:
    if content_type and "text/html" in content_type.lower():
        return True
    head = data[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def classify_http_error(status_code: int) -> str:
    if status_code == 403:
        return "download_403"
    if status_code == 404:
        return "download_404"
    if status_code == 429:
        return "rate_limited"
    return f"http_{status_code}"


def browser_user_agent(page: Any) -> str:
    try:
        value = page.evaluate("() => navigator.userAgent")
    except Exception:
        value = None
    return value or USER_AGENT_FALLBACK


def request_headers(page: Any, url: str) -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": browser_user_agent(page),
    }
    try:
        headers["Referer"] = page.url
    except Exception:
        headers["Referer"] = build_wiley_article_url_from_doi("")
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        headers["Origin"] = f"{parsed.scheme}://{parsed.netloc}"
    return headers


def download_with_context_request(
    context: Any,
    page: Any,
    doi: str,
    link: str,
    target_dir: Path,
    *,
    timeout_ms: int,
    max_bytes: int | None,
) -> dict[str, Any]:
    expected_filename = filename_from_supplement_url(link)
    existing = existing_casefold_path(target_dir, expected_filename)
    if existing:
        return {
            "doi": doi,
            "supplement_url": link,
            "expected_filename": expected_filename,
            "status": "skipped",
            "skip_reason": "already_exists",
            "file_path": str(existing),
            "size_bytes": existing.stat().st_size,
            "extension": existing.suffix.lower() or None,
            "completed_at": now_iso(),
        }

    try:
        response = context.request.get(
            link,
            headers=request_headers(page, link),
            timeout=timeout_ms,
            fail_on_status_code=False,
        )
    except PlaywrightTimeoutError as exc:
        return failed_result(doi, link, expected_filename, "download_timeout", str(exc))
    except PlaywrightError as exc:
        return failed_result(doi, link, expected_filename, "network_error", str(exc))
    except Exception as exc:
        return failed_result(doi, link, expected_filename, "unknown_error", str(exc))

    status_code = response.status
    content_type = response.headers.get("content-type")
    content_disposition = response.headers.get("content-disposition")
    final_url = response.url
    if status_code >= 400:
        failed = failed_result(
            doi,
            link,
            expected_filename,
            classify_http_error(status_code),
            f"HTTP {status_code}",
            content_type=content_type,
            final_url=final_url,
        )
        fallback = download_with_browser_event(
            context,
            doi,
            link,
            target_dir,
            expected_filename=expected_filename,
            timeout_ms=timeout_ms,
            max_bytes=max_bytes,
        )
        if fallback.get("status") == "success":
            fallback["request_fallback_from"] = failed["error_type"]
            return fallback
        failed["browser_fallback_status"] = fallback.get("status")
        failed["browser_fallback_error_type"] = fallback.get("error_type")
        failed["browser_fallback_error_message"] = fallback.get("error_message")
        return failed

    data = response.body()
    if max_bytes is not None and len(data) > max_bytes:
        return failed_result(
            doi,
            link,
            expected_filename,
            "file_too_large",
            f"Downloaded {len(data)} bytes, max is {max_bytes}",
            content_type=content_type,
            final_url=final_url,
        )
    if not data:
        return failed_result(
            doi,
            link,
            expected_filename,
            "empty_file",
            "Supplement response body was empty.",
            content_type=content_type,
            final_url=final_url,
        )
    if looks_like_html(data, content_type):
        text = data[:50000].decode("utf-8", errors="ignore")
        error_type = "access_challenge" if has_wiley_access_challenge(text) else "html_response"
        failed = failed_result(
            doi,
            link,
            expected_filename,
            error_type,
            "Supplement URL returned HTML instead of a downloadable file.",
            content_type=content_type,
            final_url=final_url,
        )
        fallback = download_with_browser_event(
            context,
            doi,
            link,
            target_dir,
            expected_filename=expected_filename,
            timeout_ms=timeout_ms,
            max_bytes=max_bytes,
        )
        if fallback.get("status") == "success":
            fallback["request_fallback_from"] = failed["error_type"]
            return fallback
        failed["browser_fallback_status"] = fallback.get("status")
        failed["browser_fallback_error_type"] = fallback.get("error_type")
        failed["browser_fallback_error_message"] = fallback.get("error_message")
        return failed

    sha256 = hashlib.sha256(data).hexdigest()
    hashes = existing_hashes(target_dir)
    if sha256 in hashes:
        return {
            "doi": doi,
            "supplement_url": link,
            "expected_filename": expected_filename,
            "status": "skipped",
            "skip_reason": "duplicate_sha256",
            "file_path": str(hashes[sha256]),
            "sha256": sha256,
            "size_bytes": len(data),
            "content_type": content_type,
            "final_url": final_url,
            "completed_at": now_iso(),
        }

    response_filename = filename_from_content_disposition(content_disposition)
    final_filename = response_filename or expected_filename
    final_path = unique_path(target_dir, final_filename, sha256)
    temp_path = final_path.with_name(f".{final_path.name}.{sha256[:12]}.part")
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(data)
    temp_path.replace(final_path)

    return {
        "doi": doi,
        "supplement_url": link,
        "expected_filename": expected_filename,
        "status": "success",
        "file_path": str(final_path),
        "filename": final_path.name,
        "extension": final_path.suffix.lower() or None,
        "content_type": content_type or mimetypes.guess_type(final_path.name)[0],
        "sha256": sha256,
        "size_bytes": len(data),
        "final_url": final_url,
        "completed_at": now_iso(),
    }


def download_with_browser_event(
    context: Any,
    doi: str,
    link: str,
    target_dir: Path,
    *,
    expected_filename: str,
    timeout_ms: int,
    max_bytes: int | None,
) -> dict[str, Any]:
    page = context.new_page()
    temp_download_dir = target_dir
    before_names = {child.name.casefold() for child in target_dir.iterdir() if child.is_file()}
    try:
        try:
            session = context.new_cdp_session(page)
            session.send(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(temp_download_dir)},
            )
        except Exception:
            pass
        try:
            with page.expect_download(timeout=timeout_ms) as download_info:
                page.goto(link, wait_until="domcontentloaded", timeout=timeout_ms)
            download = download_info.value
        except PlaywrightTimeoutError as exc:
            materialized = materialized_browser_download(
                target_dir,
                expected_filename,
                before_names,
                doi=doi,
                link=link,
            )
            if materialized is not None:
                return materialized
            return failed_result(
                doi,
                link,
                expected_filename,
                "download_timeout",
                f"Browser download did not start: {exc}",
            )
        except PlaywrightError as exc:
            message = str(exc)
            if "download is starting" not in message.lower():
                return failed_result(doi, link, expected_filename, "network_error", message)
            materialized = materialized_browser_download(
                target_dir,
                expected_filename,
                before_names,
                doi=doi,
                link=link,
            )
            if materialized is not None:
                return materialized
            return failed_result(
                doi,
                link,
                expected_filename,
                "download_timeout",
                "Download started but Playwright did not expose a download object.",
            )

        suggested = safe_filename(download.suggested_filename or expected_filename)
        temp_path = target_dir / f".{suggested}.{int(time.time())}.part"
        download.save_as(str(temp_path))
        data_size = temp_path.stat().st_size
        if max_bytes is not None and data_size > max_bytes:
            temp_path.unlink(missing_ok=True)
            return failed_result(
                doi,
                link,
                expected_filename,
                "file_too_large",
                f"Downloaded {data_size} bytes, max is {max_bytes}",
            )
        if data_size == 0:
            temp_path.unlink(missing_ok=True)
            return failed_result(doi, link, expected_filename, "empty_file", "Downloaded file is empty.")
        if looks_like_html(temp_path.read_bytes()[:50000], mimetypes.guess_type(suggested)[0]):
            temp_path.unlink(missing_ok=True)
            return failed_result(
                doi,
                link,
                expected_filename,
                "html_response",
                "Browser download saved HTML instead of a supplement file.",
            )

        sha256 = sha256_file(temp_path)
        hashes = existing_hashes(target_dir)
        if sha256 in hashes:
            temp_path.unlink(missing_ok=True)
            return {
                "doi": doi,
                "supplement_url": link,
                "expected_filename": expected_filename,
                "status": "skipped",
                "skip_reason": "duplicate_sha256",
                "file_path": str(hashes[sha256]),
                "sha256": sha256,
                "size_bytes": data_size,
                "completed_at": now_iso(),
            }

        final_path = unique_path(target_dir, suggested, sha256)
        temp_path.replace(final_path)
        return {
            "doi": doi,
            "supplement_url": link,
            "expected_filename": expected_filename,
            "status": "success",
            "file_path": str(final_path),
            "filename": final_path.name,
            "extension": final_path.suffix.lower() or None,
            "content_type": mimetypes.guess_type(final_path.name)[0],
            "sha256": sha256,
            "size_bytes": data_size,
            "final_url": link,
            "download_method": "browser_event",
            "completed_at": now_iso(),
        }
    except Exception as exc:
        return failed_result(doi, link, expected_filename, "unknown_error", str(exc))
    finally:
        try:
            page.close()
        except Exception:
            pass


def materialized_browser_download(
    target_dir: Path,
    expected_filename: str,
    before_names: set[str],
    *,
    doi: str,
    link: str,
) -> dict[str, Any] | None:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        existing = existing_casefold_path(target_dir, expected_filename)
        if existing is not None and existing.name.casefold() not in before_names:
            sha256 = sha256_file(existing)
            return {
                "doi": doi,
                "supplement_url": link,
                "expected_filename": expected_filename,
                "status": "success",
                "file_path": str(existing),
                "filename": existing.name,
                "extension": existing.suffix.lower() or None,
                "content_type": mimetypes.guess_type(existing.name)[0],
                "sha256": sha256,
                "size_bytes": existing.stat().st_size,
                "final_url": link,
                "download_method": "browser_materialized_file",
                "completed_at": now_iso(),
            }
        time.sleep(0.2)
    return None


def failed_result(
    doi: str,
    link: str,
    expected_filename: str,
    error_type: str,
    error_message: str,
    *,
    content_type: str | None = None,
    final_url: str | None = None,
) -> dict[str, Any]:
    return {
        "doi": doi,
        "supplement_url": link,
        "expected_filename": expected_filename,
        "status": "failed",
        "error_type": error_type,
        "error_message": error_message,
        "content_type": content_type,
        "final_url": final_url,
        "completed_at": now_iso(),
    }


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def reset_output_files(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def summarize(results: list[dict[str, Any]], doi_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures_by_type: dict[str, int] = {}
    extensions_by_count: dict[str, int] = {}
    skipped_by_reason: dict[str, int] = {}
    for row in results:
        if row.get("status") == "failed":
            key = str(row.get("error_type") or "unknown_error")
            failures_by_type[key] = failures_by_type.get(key, 0) + 1
        if row.get("status") == "skipped":
            key = str(row.get("skip_reason") or "unknown_skip")
            skipped_by_reason[key] = skipped_by_reason.get(key, 0) + 1
        ext = row.get("extension")
        if row.get("status") == "success" and ext:
            extensions_by_count[str(ext)] = extensions_by_count.get(str(ext), 0) + 1

    return {
        "total_dois": len(doi_rows),
        "doi_success": sum(1 for row in doi_rows if row.get("status") == "success"),
        "doi_partial": sum(1 for row in doi_rows if row.get("status") == "partial"),
        "doi_failed": sum(1 for row in doi_rows if row.get("status") == "failed"),
        "doi_skipped": sum(1 for row in doi_rows if row.get("status") == "skipped"),
        "total_links": len(results),
        "downloaded_success": sum(1 for row in results if row.get("status") == "success"),
        "skipped_existing": sum(1 for row in results if row.get("status") == "skipped"),
        "skipped_duplicate_sha256": sum(
            1
            for row in results
            if row.get("status") == "skipped" and row.get("skip_reason") == "duplicate_sha256"
        ),
        "downloaded_failed": sum(1 for row in results if row.get("status") == "failed"),
        "failures_by_type": failures_by_type,
        "skipped_by_reason": skipped_by_reason,
        "extensions_by_count": extensions_by_count,
    }


def process_doi(
    *,
    context: Any,
    page: Any,
    doi: str,
    record: CorpusRecord,
    artifacts_dir: Path,
    results_jsonl: Path,
    timeout_ms: int,
    nav_timeout_ms: int,
    max_bytes: int | None,
    discover_pages: bool,
    delay_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    article_url = wiley_article_url(doi)
    links = record_supplement_links(record)
    discovered_count = 0
    discovery_status = "record_links"
    discovery_error: str | None = None

    if discover_pages:
        try:
            page.goto(article_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            html = page.content()
            if has_wiley_access_challenge(html):
                discovery_status = "failed"
                discovery_error = "access_challenge"
            else:
                discovered = extract_supplement_links_from_html(doi, page.url or article_url, html)
                discovered_count = len(discovered)
                links = dedupe_links([*links, *discovered], doi)
                discovery_status = "success"
        except PlaywrightTimeoutError:
            discovery_status = "failed"
            discovery_error = "navigation_timeout"
        except Exception as exc:
            discovery_status = "failed"
            discovery_error = f"navigation_error: {exc}"
        finally:
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    links = dedupe_links(links, doi)
    if not links:
        doi_row = {
            "doi": doi,
            "article_url": article_url,
            "status": "failed",
            "links_found": 0,
            "record_links": len(record_supplement_links(record)),
            "discovered_links": discovered_count,
            "error_type": discovery_error or "no_supplement_links",
            "target_dir": str(record.folder),
            "completed_at": now_iso(),
        }
        append_jsonl(
            artifacts_dir / "legacy_wiley_batch_backfill_doi_status.jsonl",
            doi_row,
        )
        return [], doi_row

    results: list[dict[str, Any]] = []
    for link in links:
        existing_from_record = existing_record_file_for_link(record, link)
        if existing_from_record is not None:
            row = {
                "doi": doi,
                "supplement_url": link,
                "expected_filename": filename_from_supplement_url(link),
                "status": "skipped",
                "skip_reason": "record_relpath_exists",
                "file_path": str(existing_from_record),
                "filename": existing_from_record.name,
                "extension": existing_from_record.suffix.lower() or None,
                "size_bytes": existing_from_record.stat().st_size,
                "completed_at": now_iso(),
            }
            results.append(row)
            append_jsonl(results_jsonl, row)
            continue
        row = download_with_context_request(
            context,
            page,
            doi,
            link,
            record.folder,
            timeout_ms=timeout_ms,
            max_bytes=max_bytes,
        )
        row["article_url"] = article_url
        row["target_dir"] = str(record.folder)
        row["discovery_status"] = discovery_status
        if discovery_error:
            row["discovery_error"] = discovery_error
        results.append(row)
        append_jsonl(results_jsonl, row)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    success_or_skip = sum(1 for row in results if row.get("status") in {"success", "skipped"})
    failed = sum(1 for row in results if row.get("status") == "failed")
    doi_status = "success" if failed == 0 else "partial" if success_or_skip else "failed"
    doi_row = {
        "doi": doi,
        "article_url": article_url,
        "status": doi_status,
        "links_found": len(links),
        "record_links": len(record_supplement_links(record)),
        "discovered_links": discovered_count,
        "downloaded_success": sum(1 for row in results if row.get("status") == "success"),
        "skipped": sum(1 for row in results if row.get("status") == "skipped"),
        "failed": failed,
        "target_dir": str(record.folder),
        "completed_at": now_iso(),
    }
    append_jsonl(
        artifacts_dir / "legacy_wiley_batch_backfill_doi_status.jsonl",
        doi_row,
    )
    return results, doi_row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill all-format Wiley supplementary materials into existing DOI folders.",
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--queue-file", type=Path, default=None)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--nav-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    parser.add_argument("--max-bytes", type=int, default=None)
    parser.add_argument("--record-links-only", action="store_true")
    parser.add_argument("--create-missing-folders", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifacts_dir = PROJECT_ROOT / "runs" / args.run_id / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    results_jsonl = artifacts_dir / "legacy_wiley_batch_backfill_results.jsonl"
    doi_status_jsonl = artifacts_dir / "legacy_wiley_batch_backfill_doi_status.jsonl"
    results_csv = artifacts_dir / "legacy_wiley_batch_backfill_results.csv"
    doi_status_csv = artifacts_dir / "legacy_wiley_batch_backfill_doi_status.csv"
    summary_json = artifacts_dir / "legacy_wiley_batch_backfill_summary.json"
    reset_output_files(results_jsonl, doi_status_jsonl, results_csv, doi_status_csv, summary_json)

    doi_queue = load_dois_from_file(args.queue_file) if args.queue_file else load_default_doi_queue(args.run_id, artifacts_dir)
    if args.offset:
        doi_queue = doi_queue[args.offset :]
    if args.limit is not None:
        doi_queue = doi_queue[: args.limit]

    corpus_records = load_corpus_records(args.corpus_dir)
    timeout_ms = int(args.timeout_seconds * 1000)
    nav_timeout_ms = int(args.nav_timeout_seconds * 1000)
    all_results: list[dict[str, Any]] = []
    doi_rows: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        page = context.pages[0] if context.pages else context.new_page()

        for index, doi in enumerate(doi_queue, start=1 + args.offset):
            key = normalize_doi(doi)
            record = corpus_records.get(key)
            if record is None:
                if not args.create_missing_folders:
                    doi_row = {
                        "doi": doi,
                        "status": "skipped",
                        "error_type": "missing_corpus_folder",
                        "completed_at": now_iso(),
                    }
                    doi_rows.append(doi_row)
                    append_jsonl(doi_status_jsonl, doi_row)
                    print(f"[{index}] skip missing folder: {doi}")
                    continue
                folder = args.corpus_dir / safe_identifier(doi)
                folder.mkdir(parents=True, exist_ok=True)
                record = CorpusRecord(doi=key, folder=folder, record_path=None, record_data={})

            print(f"[{index}] {doi} -> {record.folder}")
            results, doi_row = process_doi(
                context=context,
                page=page,
                doi=key,
                record=record,
                artifacts_dir=artifacts_dir,
                results_jsonl=results_jsonl,
                timeout_ms=timeout_ms,
                nav_timeout_ms=nav_timeout_ms,
                max_bytes=args.max_bytes,
                discover_pages=not args.record_links_only,
                delay_seconds=args.delay_seconds,
            )
            all_results.extend(results)
            doi_rows.append(doi_row)

        # Do not close the user's authorized Chrome. Let process shutdown only
        # disconnect this Playwright client so the session remains reusable.

    result_fields = [
        "doi",
        "status",
        "skip_reason",
        "error_type",
        "expected_filename",
        "filename",
        "extension",
        "size_bytes",
        "sha256",
        "content_type",
        "supplement_url",
        "final_url",
        "file_path",
        "target_dir",
        "discovery_status",
        "discovery_error",
        "completed_at",
    ]
    doi_fields = [
        "doi",
        "status",
        "links_found",
        "record_links",
        "discovered_links",
        "downloaded_success",
        "skipped",
        "failed",
        "error_type",
        "target_dir",
        "article_url",
        "completed_at",
    ]
    write_csv(results_csv, all_results, result_fields)
    write_csv(doi_status_csv, doi_rows, doi_fields)
    summary = summarize(all_results, doi_rows)
    summary.update(
        {
            "run_id": args.run_id,
            "corpus_dir": str(args.corpus_dir),
            "queue_count": len(doi_queue),
            "results_jsonl": str(results_jsonl),
            "results_csv": str(results_csv),
            "doi_status_csv": str(doi_status_csv),
            "created_at": now_iso(),
        }
    )
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
