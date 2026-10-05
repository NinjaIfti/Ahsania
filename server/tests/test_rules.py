import pytest

from capture.db.models import Role, Status
from capture.workflow.rules import Action, TransitionError, can_edit, next_status


@pytest.mark.parametrize(
    ("role", "status", "expected"),
    [
        (Role.DOCTOR, Status.DRAFT, True),
        (Role.DOCTOR, Status.PROCESSING, False),
        (Role.DOCTOR, Status.PENDING_ADMIN, False),
        (Role.DOCTOR, Status.APPROVED, False),
        (Role.ADMIN, Status.DRAFT, False),
        (Role.ADMIN, Status.PENDING_ADMIN, False),
    ],
)
def test_can_edit(role, status, expected):
    assert can_edit(role, status) is expected


def move(action, role, status, *, comment=None, errors=False):
    return next_status(action=action, role=role, status=status, comment=comment, has_errors=errors)


def rejected(*args, **kwargs) -> TransitionError:
    with pytest.raises(TransitionError) as info:
        move(*args, **kwargs)
    return info.value


def test_doctor_sends_a_draft_to_the_admin():
    assert move(Action.SUBMIT, Role.DOCTOR, Status.DRAFT) == Status.PENDING_ADMIN


def test_submit_with_errors_is_422():
    e = rejected(Action.SUBMIT, Role.DOCTOR, Status.DRAFT, errors=True)
    assert e.http_status == 422
    assert e.message == "Fix the highlighted fields before approving"


def test_admin_cannot_submit():
    assert rejected(Action.SUBMIT, Role.ADMIN, Status.DRAFT).http_status == 403


def test_only_drafts_can_be_submitted():
    assert rejected(Action.SUBMIT, Role.DOCTOR, Status.PENDING_ADMIN).http_status == 409


def test_admin_approves():
    assert move(Action.APPROVE, Role.ADMIN, Status.PENDING_ADMIN) == Status.APPROVED


def test_doctor_cannot_give_the_final_approval():
    assert rejected(Action.APPROVE, Role.DOCTOR, Status.PENDING_ADMIN).http_status == 403


def test_approve_needs_a_record_waiting_for_the_admin():
    assert rejected(Action.APPROVE, Role.ADMIN, Status.DRAFT).http_status == 409


def test_admin_sends_back_with_a_comment():
    assert move(Action.RETURN, Role.ADMIN, Status.PENDING_ADMIN, comment="Check the date") == Status.DRAFT


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_send_back_needs_a_comment(comment):
    e = rejected(Action.RETURN, Role.ADMIN, Status.PENDING_ADMIN, comment=comment)
    assert e.http_status == 422


def test_doctor_cannot_send_back():
    assert rejected(Action.RETURN, Role.DOCTOR, Status.PENDING_ADMIN, comment="x").http_status == 403


def test_send_back_needs_a_record_waiting_for_the_admin():
    assert rejected(Action.RETURN, Role.ADMIN, Status.APPROVED, comment="x").http_status == 409


def test_admin_reopens_with_a_reason():
    assert move(Action.REOPEN, Role.ADMIN, Status.APPROVED, comment="Wrong patient") == Status.DRAFT


def test_reopen_needs_a_reason():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.APPROVED).http_status == 422


def test_doctor_cannot_reopen():
    assert rejected(Action.REOPEN, Role.DOCTOR, Status.APPROVED, comment="x").http_status == 403


def test_only_approved_records_reopen():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.PENDING_ADMIN, comment="x").http_status == 409


def test_doctor_fills_by_hand_while_the_ai_reads():
    assert move(Action.FILL_BY_HAND, Role.DOCTOR, Status.PROCESSING) == Status.DRAFT


def test_fill_by_hand_needs_a_record_waiting_for_the_ai():
    assert rejected(Action.FILL_BY_HAND, Role.DOCTOR, Status.DRAFT).http_status == 409


def test_admin_cannot_fill_by_hand():
    assert rejected(Action.FILL_BY_HAND, Role.ADMIN, Status.PROCESSING).http_status == 403


def test_unknown_action_is_422():
    e = rejected("release", Role.DOCTOR, Status.DRAFT)
    assert e.http_status == 422
    assert "release" not in {a.value for a in Action}
