from __future__ import annotations

from crawler_scope.schemas import DOIInputItem, InstitutionAccessProfile, PaperRecord


def test_doi_input_item_is_json_serializable() -> None:
    item = DOIInputItem(
        original="doi:10.1000/ABC",
        normalized_doi="10.1000/abc",
        row_index=1,
        status="valid",
    )

    payload = item.model_dump_json()

    assert '"normalized_doi":"10.1000/abc"' in payload


def test_institution_access_profile_has_no_password_field() -> None:
    profile = InstitutionAccessProfile(
        profile_name="demo",
        storage_state_path="secrets/browser_states/demo.json",
    )

    assert profile.storage_state_path == "secrets/browser_states/demo.json"
    assert "password" not in InstitutionAccessProfile.model_fields


def test_paper_record_is_doi_first() -> None:
    record = PaperRecord(
        paper_id="paper_001",
        doi="10.1000/example",
        title="Example",
    )

    assert record.doi == "10.1000/example"
    assert record.primary_lookup_key == "doi"
