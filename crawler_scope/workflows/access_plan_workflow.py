from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crawler_scope.schemas import AccessDecision, AccessHint, PaperRecord
from crawler_scope.tools.academic import plan_access_decision
from crawler_scope.tools.storage import RunStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE = RunStore(PROJECT_ROOT)


def plan_access_for_run(
    run_id: str,
    *,
    allow_user_login: bool = False,
    allow_manual_upload: bool = True,
    institution_domains: list[str] | None = None,
) -> dict:
    run_dir = RUN_STORE.get_run_dir(run_id)
    papers_path = run_dir / "artifacts" / "papers_metadata_merged.jsonl"
    hints_path = run_dir / "artifacts" / "access_hints.jsonl"
    if not papers_path.exists():
        raise FileNotFoundError(f"Missing merged papers file: {papers_path}")
    if not hints_path.exists():
        raise FileNotFoundError(f"Missing access hints file: {hints_path}")

    papers_by_doi = {
        paper.doi: paper for paper in _load_jsonl_models(papers_path, PaperRecord)
    }
    hints_by_doi = {
        hint.doi: hint for hint in _load_jsonl_models(hints_path, AccessHint)
    }
    ordered_dois = list(dict.fromkeys(list(hints_by_doi) + list(papers_by_doi)))
    normalized_institution_domains = institution_domains or []

    RUN_STORE.append_trace(
        run_id,
        {
            "event": "access_plan_started",
            "timestamp": _iso_now(),
            "total_dois": len(ordered_dois),
            "allow_user_login": allow_user_login,
            "allow_manual_upload": allow_manual_upload,
            "institution_domains": normalized_institution_domains,
        },
    )
    RUN_STORE.mark_status(
        run_id,
        "planning_access",
        allow_user_login=allow_user_login,
        allow_manual_upload=allow_manual_upload,
        institution_domains=normalized_institution_domains,
    )

    access_decisions: list[AccessDecision] = []
    open_pdf_candidates: list[AccessDecision] = []
    authenticated_candidates: list[AccessDecision] = []
    manual_required: list[AccessDecision] = []
    unavailable: list[AccessDecision] = []

    for doi in ordered_dois:
        paper = papers_by_doi.get(doi)
        hint = hints_by_doi.get(doi, AccessHint(doi=doi))
        RUN_STORE.append_trace(
            run_id,
            {
                "event": "access_plan_item_started",
                "timestamp": _iso_now(),
                "doi": doi,
            },
        )

        decision = plan_access_decision(
            doi,
            paper=paper,
            hint=hint,
            allow_user_login=allow_user_login,
            allow_manual_upload=allow_manual_upload,
            institution_domains=normalized_institution_domains,
        )
        access_decisions.append(decision)

        if decision.access_type == "open_access":
            open_pdf_candidates.append(decision)
        elif decision.access_type == "user_authenticated":
            authenticated_candidates.append(decision)
        elif decision.access_type == "manual_required":
            manual_required.append(decision)
        else:
            unavailable.append(decision)

        RUN_STORE.append_trace(
            run_id,
            {
                "event": "access_plan_item_completed",
                "timestamp": _iso_now(),
                "doi": doi,
                "access_type": decision.access_type,
                "download_strategy": decision.download_strategy,
            },
        )

    RUN_STORE.save_text(
        run_id,
        "artifacts/access_decisions.jsonl",
        _jsonl_text(access_decisions),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/open_pdf_candidates.jsonl",
        _jsonl_text(open_pdf_candidates),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/authenticated_candidates.jsonl",
        _jsonl_text(authenticated_candidates),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/manual_required.jsonl",
        _jsonl_text(manual_required),
    )
    RUN_STORE.save_text(
        run_id,
        "artifacts/unavailable.jsonl",
        _jsonl_text(unavailable),
    )

    summary = {
        "total_dois": len(ordered_dois),
        "open_pdf_candidates": len(open_pdf_candidates),
        "authenticated_candidates": len(authenticated_candidates),
        "manual_required": len(manual_required),
        "unavailable": len(unavailable),
        "allow_user_login": allow_user_login,
        "allow_manual_upload": allow_manual_upload,
        "institution_domains": normalized_institution_domains,
    }
    RUN_STORE.save_json(run_id, "artifacts/access_plan_summary.json", summary)
    RUN_STORE.mark_status(run_id, "completed", access_plan_summary=summary)
    RUN_STORE.append_trace(
        run_id,
        {
            "event": "access_plan_completed",
            "timestamp": _iso_now(),
            **summary,
        },
    )
    return summary


def _load_jsonl_models(path: Path, model_class: type[PaperRecord] | type[AccessHint]) -> list:
    items: list = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        items.append(model_class.model_validate_json(line))
    return items


def _jsonl_text(items: list[AccessDecision]) -> str:
    return "".join(item.model_dump_json() + "\n" for item in items)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
