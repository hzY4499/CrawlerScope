from __future__ import annotations

from crawler_scope.schemas import AccessDecision, AccessHint, PaperRecord


def plan_access_decision(
    doi: str,
    *,
    paper: PaperRecord | None = None,
    hint: AccessHint | None = None,
    allow_user_login: bool = False,
    allow_manual_upload: bool = True,
    institution_domains: list[str] | None = None,
) -> AccessDecision:
    normalized_hint = hint or AccessHint(doi=doi)
    normalized_institution_domains = institution_domains or []
    paper_pdf_urls = paper.pdf_urls if paper is not None else []
    pdf_urls = _dedupe(normalized_hint.open_pdf_urls + paper_pdf_urls)
    access_urls = _dedupe(
        pdf_urls
        + normalized_hint.oa_landing_pages
        + normalized_hint.publisher_urls
        + (paper.source_urls if paper is not None else [])
    )
    title = paper.title if paper is not None else None

    if normalized_hint.has_open_pdf and normalized_hint.open_pdf_urls:
        return _build_decision(
            doi=doi,
            paper=paper,
            title=title,
            status="allowed",
            access_type="open_access",
            download_strategy="direct_pdf",
            access_urls=access_urls,
            pdf_urls=pdf_urls,
            oa_landing_pages=normalized_hint.oa_landing_pages,
            institution_domains=normalized_institution_domains,
            requires_login=False,
            reason="AccessHint contains direct open PDF URLs.",
            evidence_sources=normalized_hint.evidence_sources,
        )

    if paper is not None and paper.pdf_urls:
        return _build_decision(
            doi=doi,
            paper=paper,
            title=title,
            status="allowed",
            access_type="open_access",
            download_strategy="direct_pdf",
            access_urls=access_urls,
            pdf_urls=pdf_urls,
            oa_landing_pages=normalized_hint.oa_landing_pages,
            institution_domains=normalized_institution_domains,
            requires_login=False,
            reason="Merged paper metadata contains PDF URLs.",
            evidence_sources=normalized_hint.evidence_sources,
        )

    if normalized_hint.oa_landing_pages:
        return _build_decision(
            doi=doi,
            paper=paper,
            title=title,
            status="manual_review",
            access_type="manual_required",
            download_strategy="manual_upload",
            access_urls=access_urls,
            pdf_urls=[],
            oa_landing_pages=normalized_hint.oa_landing_pages,
            institution_domains=normalized_institution_domains,
            requires_login=False,
            reason="Only OA landing pages are available; manual review is required.",
            evidence_sources=normalized_hint.evidence_sources,
        )

    if allow_user_login:
        return _build_decision(
            doi=doi,
            paper=paper,
            title=title,
            status="allowed",
            access_type="user_authenticated",
            download_strategy="browser_session",
            access_urls=access_urls,
            pdf_urls=[],
            oa_landing_pages=[],
            institution_domains=normalized_institution_domains,
            requires_login=True,
            reason="No open PDF found; user-authenticated access is allowed.",
            evidence_sources=normalized_hint.evidence_sources,
        )

    if allow_manual_upload:
        return _build_decision(
            doi=doi,
            paper=paper,
            title=title,
            status="manual_review",
            access_type="manual_required",
            download_strategy="manual_upload",
            access_urls=access_urls,
            pdf_urls=[],
            oa_landing_pages=[],
            institution_domains=normalized_institution_domains,
            requires_login=False,
            reason="No open PDF found; manual upload fallback is allowed.",
            evidence_sources=normalized_hint.evidence_sources,
        )

    return _build_decision(
        doi=doi,
        paper=paper,
        title=title,
        status="blocked",
        access_type="unavailable",
        download_strategy="skip",
        access_urls=access_urls,
        pdf_urls=[],
        oa_landing_pages=[],
        institution_domains=normalized_institution_domains,
        requires_login=False,
        reason="No viable access path is available under the current policy.",
        evidence_sources=normalized_hint.evidence_sources,
    )


def _build_decision(
    *,
    doi: str,
    paper: PaperRecord | None,
    title: str | None,
    status: str,
    access_type: str,
    download_strategy: str,
    access_urls: list[str],
    pdf_urls: list[str],
    oa_landing_pages: list[str],
    institution_domains: list[str],
    requires_login: bool,
    reason: str,
    evidence_sources: list[str],
) -> AccessDecision:
    return AccessDecision(
        paper_id=paper.paper_id if paper is not None else None,
        doi=doi,
        title=title,
        status=status,  # type: ignore[arg-type]
        access_type=access_type,  # type: ignore[arg-type]
        download_strategy=download_strategy,  # type: ignore[arg-type]
        access_url=access_urls[0] if access_urls else None,
        access_urls=access_urls,
        pdf_urls=pdf_urls,
        oa_landing_pages=oa_landing_pages,
        institution_domains=_dedupe(institution_domains),
        requires_login=requires_login,
        reason=reason,
        evidence_sources=_dedupe(evidence_sources),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped
