"""Immutable, attributable revision history for generated test proposals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
from typing import Final, cast
from uuid import UUID, uuid4

from ai_qa_copilot_api.generated_tests import (
    GeneratedTestCaseV1,
    GeneratedTestCaseValidationError,
    validate_generated_test_case,
)


MAX_EDITOR_ID_LENGTH: Final = 255


class TestRevisionRejected(ValueError):
    """Raised when a test revision would break immutable attributable history."""


class TestRevisionKind(StrEnum):
    """Closed provenance states for generated output and user changes."""

    GENERATED = "generated"
    USER_EDIT = "user_edit"


@dataclass(frozen=True)
class TestRevisionV1:
    """One immutable snapshot in a generated-test revision chain."""

    id: UUID
    test_case_id: UUID
    revision_number: int
    parent_revision_id: UUID | None
    kind: TestRevisionKind
    editor_id: str | None
    created_at: datetime
    test_case_payload: str

    @property
    def test_case(self) -> GeneratedTestCaseV1:
        """Rebuild a fresh validated proposal from the immutable snapshot."""

        return _test_case_from_snapshot(self.test_case_payload)


@dataclass(frozen=True)
class TestRevisionHistoryV1:
    """One ordered immutable history retaining original output and user edits."""

    test_case_id: UUID
    revisions: tuple[TestRevisionV1, ...]


def create_test_revision_history(
    *,
    generated_test_case: GeneratedTestCaseV1,
    created_at: datetime,
    id_factory: Callable[[], UUID] = uuid4,
) -> TestRevisionHistoryV1:
    """Create revision one from original generated output without a user actor."""

    _require_aware_timestamp(created_at)
    snapshot = _canonical_snapshot(generated_test_case)
    revision = TestRevisionV1(
        id=id_factory(),
        test_case_id=generated_test_case.id,
        revision_number=1,
        parent_revision_id=None,
        kind=TestRevisionKind.GENERATED,
        editor_id=None,
        created_at=created_at,
        test_case_payload=snapshot,
    )
    history = TestRevisionHistoryV1(
        test_case_id=generated_test_case.id,
        revisions=(revision,),
    )
    _validate_history(history)
    return history


def append_user_test_revision(
    *,
    history: TestRevisionHistoryV1,
    edited_payload: Mapping[str, object],
    editor_id: str,
    created_at: datetime,
    id_factory: Callable[[], UUID] = uuid4,
) -> TestRevisionHistoryV1:
    """Append one validated user edit while preserving all prior snapshots."""

    _validate_history(history)
    _require_aware_timestamp(created_at)
    normalized_editor_id = _normalized_editor_id(editor_id)
    edited_test_case = _validated_test_case(edited_payload)
    if edited_test_case.id != history.test_case_id:
        raise TestRevisionRejected(
            "User edits must retain the original generated test case ID"
        )

    snapshot = _canonical_snapshot(edited_test_case)
    parent = history.revisions[-1]
    if snapshot == parent.test_case_payload:
        raise TestRevisionRejected("User edits must change the prior revision")
    if created_at < parent.created_at:
        raise TestRevisionRejected(
            "User revision timestamps must not precede their parent revision"
        )

    revision_id = id_factory()
    if revision_id in {revision.id for revision in history.revisions}:
        raise TestRevisionRejected("Test revision IDs must be unique")

    revision = TestRevisionV1(
        id=revision_id,
        test_case_id=history.test_case_id,
        revision_number=parent.revision_number + 1,
        parent_revision_id=parent.id,
        kind=TestRevisionKind.USER_EDIT,
        editor_id=normalized_editor_id,
        created_at=created_at,
        test_case_payload=snapshot,
    )
    updated_history = TestRevisionHistoryV1(
        test_case_id=history.test_case_id,
        revisions=(*history.revisions, revision),
    )
    _validate_history(updated_history)
    return updated_history


def _validate_history(history: TestRevisionHistoryV1) -> None:
    if not history.revisions:
        raise TestRevisionRejected(
            "Test revision history requires an original revision"
        )

    revision_ids: set[UUID] = set()
    previous: TestRevisionV1 | None = None
    for expected_number, revision in enumerate(history.revisions, start=1):
        if revision.id in revision_ids:
            raise TestRevisionRejected("Test revision IDs must be unique")
        revision_ids.add(revision.id)

        if revision.test_case_id != history.test_case_id:
            raise TestRevisionRejected(
                "Every revision must retain the original generated test case ID"
            )
        if revision.revision_number != expected_number:
            raise TestRevisionRejected("Revision numbers must be contiguous")
        if revision.test_case.id != history.test_case_id:
            raise TestRevisionRejected(
                "Revision snapshots must retain the original generated test case ID"
            )
        _require_aware_timestamp(revision.created_at)

        if previous is None:
            if (
                revision.kind is not TestRevisionKind.GENERATED
                or revision.parent_revision_id is not None
                or revision.editor_id is not None
            ):
                raise TestRevisionRejected(
                    "The first revision must be unattributed generated output"
                )
        else:
            if (
                revision.kind is not TestRevisionKind.USER_EDIT
                or revision.parent_revision_id != previous.id
                or revision.editor_id is None
            ):
                raise TestRevisionRejected(
                    "User revisions must directly reference their parent revision"
                )
            _normalized_editor_id(revision.editor_id)
            if revision.created_at < previous.created_at:
                raise TestRevisionRejected(
                    "Revision timestamps must not precede their parent revision"
                )

        previous = revision


def _canonical_snapshot(test_case: GeneratedTestCaseV1) -> str:
    validated = _validated_test_case(test_case.as_payload())
    return json.dumps(
        validated.as_payload(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _validated_test_case(payload: Mapping[str, object]) -> GeneratedTestCaseV1:
    try:
        return validate_generated_test_case(payload)
    except GeneratedTestCaseValidationError as error:
        raise TestRevisionRejected(
            "Test revision payload violates the generated-test contract"
        ) from error


def _test_case_from_snapshot(snapshot: str) -> GeneratedTestCaseV1:
    try:
        payload = json.loads(snapshot)
    except json.JSONDecodeError as error:
        raise TestRevisionRejected(
            "Test revision snapshot is not valid JSON"
        ) from error
    if not isinstance(payload, dict):
        raise TestRevisionRejected("Test revision snapshot must be a JSON object")
    return _validated_test_case(cast(Mapping[str, object], payload))


def _normalized_editor_id(editor_id: str) -> str:
    normalized = editor_id.strip()
    if not normalized or len(normalized) > MAX_EDITOR_ID_LENGTH:
        raise TestRevisionRejected("Editor identity must be bounded, non-empty text")
    return normalized


def _require_aware_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TestRevisionRejected("Revision timestamps must include a timezone")
