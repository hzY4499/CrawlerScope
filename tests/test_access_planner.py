from __future__ import annotations

from crawler_scope.schemas import AccessHint, PaperRecord
from crawler_scope.tools.academic.access_planner import plan_access_decision


def test_access_planner_uses_hint_open_pdf_first() -> None:
    paper = PaperRecord(
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        title="Example",
        source_urls=["https://publisher.example/article"],
        raw={},
    )
    hint = AccessHint(
        doi="10.1000/test",
        has_open_pdf=True,
        open_pdf_urls=["https://oa.example/file.pdf"],
        evidence_sources=["unpaywall"],
    )

    decision = plan_access_decision("10.1000/test", paper=paper, hint=hint)

    assert decision.access_type == "open_access"
    assert decision.download_strategy == "direct_pdf"
    assert decision.pdf_urls == ["https://oa.example/file.pdf"]


def test_access_planner_routes_landing_pages_to_manual() -> None:
    hint = AccessHint(
        doi="10.1000/test",
        oa_landing_pages=["https://oa.example/landing"],
    )

    decision = plan_access_decision("10.1000/test", hint=hint)

    assert decision.access_type == "manual_required"
    assert decision.download_strategy == "manual_upload"


def test_access_planner_uses_login_when_allowed() -> None:
    paper = PaperRecord(
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        source_urls=["https://publisher.example/article"],
        raw={},
    )

    decision = plan_access_decision(
        "10.1000/test",
        paper=paper,
        allow_user_login=True,
        allow_manual_upload=False,
        institution_domains=["example.edu"],
    )

    assert decision.access_type == "user_authenticated"
    assert decision.download_strategy == "browser_session"
    assert decision.requires_login is True
    assert decision.institution_domains == ["example.edu"]


def test_access_planner_marks_unavailable_when_no_path() -> None:
    decision = plan_access_decision(
        "10.1000/test",
        allow_user_login=False,
        allow_manual_upload=False,
    )

    assert decision.access_type == "unavailable"
    assert decision.download_strategy == "skip"
