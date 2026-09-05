from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ai_qa_copilot_api.generated_tests import (
    AssertionOperator,
    AssertionTarget,
    GeneratedAssertionV1,
    GeneratedTestCaseV1,
    GeneratedTestKind,
    HttpMethod,
    RequestTemplateV1,
)
from ai_qa_copilot_api.test_revisions import (
    TestRevisionHistoryV1 as RevisionHistory,
    TestRevisionKind as RevisionKind,
    TestRevisionRejected as RevisionRejected,
    TestRevisionV1 as Revision,
    append_user_test_revision,
    create_test_revision_history,
)


TEST_CASE_ID = UUID("00000000-0000-0000-0000-000000000a01")
SOURCE_FINDING_ID = UUID("00000000-0000-0000-0000-000000000a02")
CITATION_ID = UUID("00000000-0000-0000-0000-000000000a03")

ORIGINAL_REVISION_ID = UUID("00000000-0000-0000-0000-000000000a11")
FIRST_EDIT_REVISION_ID = UUID("00000000-0000-0000-0000-000000000a12")
SECOND_EDIT_REVISION_ID = UUID("00000000-0000-0000-0000-000000000a13")

CREATED_AT = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
FIRST_EDIT_AT = CREATED_AT + timedelta(minutes=1)
SECOND_EDIT_AT = CREATED_AT + timedelta(minutes=2)


def generated_test(
    *,
    title: str = "Create order returns HTTP 201",
    json_body: dict[str, object] | None = None,
) -> GeneratedTestCaseV1:
    return GeneratedTestCaseV1(
        id=TEST_CASE_ID,
        title=title,
        kind=GeneratedTestKind.POSITIVE,
        source_finding_id=SOURCE_FINDING_ID,
        citation_ids=(CITATION_ID,),
        request=RequestTemplateV1(
            method=HttpMethod.POST,
            path="/orders",
            query=(),
            headers=(),
            json_body={"quantity": 1} if json_body is None else json_body,
        ),
        assertions=(
            GeneratedAssertionV1(
                target=AssertionTarget.STATUS_CODE,
                selector=None,
                operator=AssertionOperator.EQUALS,
                expected_value=201,
            ),
        ),
    )


def revision_history() -> RevisionHistory:
    return create_test_revision_history(
        generated_test_case=generated_test(),
        created_at=CREATED_AT,
        id_factory=lambda: ORIGINAL_REVISION_ID,
    )


def edited_payload(
    *,
    title: str = "Create order returns HTTP 201 and an identifier",
) -> dict[str, object]:
    payload = deepcopy(generated_test().as_payload())
    payload["title"] = title
    return payload


def test_original_generated_output_creates_revision_one() -> None:
    history = revision_history()

    assert history.test_case_id == TEST_CASE_ID
    assert len(history.revisions) == 1

    original = history.revisions[0]
    assert original.id == ORIGINAL_REVISION_ID
    assert original.revision_number == 1
    assert original.parent_revision_id is None
    assert original.kind is RevisionKind.GENERATED
    assert original.editor_id is None
    assert original.created_at == CREATED_AT
    assert original.test_case == generated_test()


def test_user_edit_appends_an_attributable_immutable_revision() -> None:
    original_history = revision_history()

    updated_history = append_user_test_revision(
        history=original_history,
        edited_payload=edited_payload(),
        editor_id="cognito-subject-123",
        created_at=FIRST_EDIT_AT,
        id_factory=lambda: FIRST_EDIT_REVISION_ID,
    )

    assert len(original_history.revisions) == 1
    assert len(updated_history.revisions) == 2
    assert updated_history.revisions[0] == original_history.revisions[0]

    edit = updated_history.revisions[1]
    assert edit.id == FIRST_EDIT_REVISION_ID
    assert edit.test_case_id == TEST_CASE_ID
    assert edit.revision_number == 2
    assert edit.parent_revision_id == ORIGINAL_REVISION_ID
    assert edit.kind is RevisionKind.USER_EDIT
    assert edit.editor_id == "cognito-subject-123"
    assert edit.created_at == FIRST_EDIT_AT
    assert edit.test_case.title == "Create order returns HTTP 201 and an identifier"


def test_multiple_user_edits_form_a_direct_parent_chain() -> None:
    first_history = append_user_test_revision(
        history=revision_history(),
        edited_payload=edited_payload(title="First user edit"),
        editor_id="editor-one",
        created_at=FIRST_EDIT_AT,
        id_factory=lambda: FIRST_EDIT_REVISION_ID,
    )

    second_history = append_user_test_revision(
        history=first_history,
        edited_payload=edited_payload(title="Second user edit"),
        editor_id="editor-two",
        created_at=SECOND_EDIT_AT,
        id_factory=lambda: SECOND_EDIT_REVISION_ID,
    )

    assert [revision.revision_number for revision in second_history.revisions] == [
        1,
        2,
        3,
    ]
    assert [revision.parent_revision_id for revision in second_history.revisions] == [
        None,
        ORIGINAL_REVISION_ID,
        FIRST_EDIT_REVISION_ID,
    ]
    assert [revision.editor_id for revision in second_history.revisions] == [
        None,
        "editor-one",
        "editor-two",
    ]
    assert second_history.revisions[0].test_case.title == (
        "Create order returns HTTP 201"
    )
    assert second_history.revisions[1].test_case.title == "First user edit"
    assert second_history.revisions[2].test_case.title == "Second user edit"


def test_revision_snapshot_is_immutable_from_source_and_reader_mutation() -> None:
    source_test = generated_test(json_body={"quantity": 1})
    history = create_test_revision_history(
        generated_test_case=source_test,
        created_at=CREATED_AT,
        id_factory=lambda: ORIGINAL_REVISION_ID,
    )

    assert source_test.request.json_body is not None
    source_test.request.json_body["quantity"] = 99

    first_read = history.revisions[0].test_case
    assert first_read.request.json_body == {"quantity": 1}

    assert first_read.request.json_body is not None
    first_read.request.json_body["quantity"] = 500

    assert history.revisions[0].test_case.request.json_body == {"quantity": 1}


def test_invalid_user_payload_is_rejected_without_changing_history() -> None:
    history = revision_history()
    invalid_payload = edited_payload()
    invalid_payload["script"] = "do_not_execute()"

    with pytest.raises(RevisionRejected, match="generated-test contract"):
        append_user_test_revision(
            history=history,
            edited_payload=invalid_payload,
            editor_id="editor-one",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )

    assert len(history.revisions) == 1


def test_user_edit_must_retain_the_original_test_case_id() -> None:
    payload = edited_payload()
    payload["id"] = "00000000-0000-0000-0000-000000000a99"

    with pytest.raises(RevisionRejected, match="retain the original"):
        append_user_test_revision(
            history=revision_history(),
            edited_payload=payload,
            editor_id="editor-one",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )


def test_user_edit_must_change_the_previous_snapshot() -> None:
    with pytest.raises(RevisionRejected, match="must change"):
        append_user_test_revision(
            history=revision_history(),
            edited_payload=generated_test().as_payload(),
            editor_id="editor-one",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )


def test_editor_identity_and_timestamps_are_validated() -> None:
    with pytest.raises(RevisionRejected, match="Editor identity"):
        append_user_test_revision(
            history=revision_history(),
            edited_payload=edited_payload(),
            editor_id="   ",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )

    with pytest.raises(RevisionRejected, match="include a timezone"):
        create_test_revision_history(
            generated_test_case=generated_test(),
            created_at=datetime(2026, 9, 5, 12, 0),
            id_factory=lambda: ORIGINAL_REVISION_ID,
        )

    with pytest.raises(RevisionRejected, match="must not precede"):
        append_user_test_revision(
            history=revision_history(),
            edited_payload=edited_payload(),
            editor_id="editor-one",
            created_at=CREATED_AT - timedelta(seconds=1),
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )


def test_duplicate_revision_id_is_rejected() -> None:
    with pytest.raises(RevisionRejected, match="IDs must be unique"):
        append_user_test_revision(
            history=revision_history(),
            edited_payload=edited_payload(),
            editor_id="editor-one",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: ORIGINAL_REVISION_ID,
        )


def test_invalid_existing_history_is_rejected_before_appending() -> None:
    original = revision_history().revisions[0]
    invalid_first_revision = Revision(
        id=ORIGINAL_REVISION_ID,
        test_case_id=TEST_CASE_ID,
        revision_number=1,
        parent_revision_id=None,
        kind=RevisionKind.USER_EDIT,
        editor_id="editor-one",
        created_at=CREATED_AT,
        test_case_payload=original.test_case_payload,
    )
    invalid_history = RevisionHistory(
        test_case_id=TEST_CASE_ID,
        revisions=(invalid_first_revision,),
    )

    with pytest.raises(RevisionRejected, match="first revision"):
        append_user_test_revision(
            history=invalid_history,
            edited_payload=edited_payload(),
            editor_id="editor-two",
            created_at=FIRST_EDIT_AT,
            id_factory=lambda: FIRST_EDIT_REVISION_ID,
        )


def test_revision_payload_is_canonical_and_revalidates_on_read() -> None:
    history = append_user_test_revision(
        history=revision_history(),
        edited_payload=edited_payload(title="  Edited order test  "),
        editor_id="editor-one",
        created_at=FIRST_EDIT_AT,
        id_factory=lambda: FIRST_EDIT_REVISION_ID,
    )

    revision = history.revisions[1]

    assert revision.test_case.title == "Edited order test"
    assert '"schema_version":"generated-test-case/v1"' in revision.test_case_payload
    assert revision.test_case_payload == revision.test_case_payload.strip()
