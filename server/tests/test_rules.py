import pytest

from capture.db.models import Role, Status
from capture.workflow.rules import Action, TransitionError, can_edit, can_view, next_status


@pytest.mark.parametrize("role", [Role.UPLOADER, Role.HOSPITAL_DOCTOR])
@pytest.mark.parametrize("status", list(Status))
def test_hospital_roles_see_every_status(role, status):
    assert can_view(role, status)


@pytest.mark.parametrize("role", [Role.NSU_REVIEWER, Role.ADMIN])
@pytest.mark.parametrize("status", list(Status))
def test_nsu_roles_only_see_records_past_the_doctor(role, status):
    assert can_view(role, status) == (status in (Status.PENDING_NSU, Status.APPROVED))


@pytest.mark.parametrize(
    ("role", "status", "expected"),
    [
        (Role.UPLOADER, Status.DRAFT, True),
        (Role.UPLOADER, Status.PENDING_DOCTOR, False),
        (Role.HOSPITAL_DOCTOR, Status.DRAFT, True),
        (Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, True),
        (Role.HOSPITAL_DOCTOR, Status.PENDING_NSU, False),
        (Role.NSU_REVIEWER, Status.PENDING_NSU, False),
        (Role.ADMIN, Status.APPROVED, False),
    ],
)
def test_can_edit(role, status, expected):
    assert can_edit(role, status) is expected


def move(action, role, status, *, actor=1, creator=2, comment=None, errors=False):
    return next_status(
        action=action, role=role, status=status, actor_id=actor, creator_id=creator, comment=comment, has_errors=errors
    )


def rejected(*args, **kwargs) -> TransitionError:
    with pytest.raises(TransitionError) as info:
        move(*args, **kwargs)
    return info.value


def test_submit_draft():
    assert move(Action.SUBMIT, Role.UPLOADER, Status.DRAFT) == Status.PENDING_DOCTOR


def test_submit_with_errors_is_422():
    e = rejected(Action.SUBMIT, Role.UPLOADER, Status.DRAFT, errors=True)
    assert e.http_status == 422
    assert e.message == "Fix the highlighted fields before submitting"


def test_nsu_cannot_submit():
    assert rejected(Action.SUBMIT, Role.NSU_REVIEWER, Status.DRAFT).http_status == 403


def test_submit_only_from_draft():
    assert rejected(Action.SUBMIT, Role.UPLOADER, Status.PENDING_DOCTOR).http_status == 409


def test_doctor_approves():
    assert move(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR) == Status.PENDING_NSU


def test_four_eyes_rule():
    e = rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, actor=7, creator=7)
    assert e.http_status == 403
    assert "another doctor" in e.message


def test_uploader_cannot_approve():
    assert rejected(Action.APPROVE, Role.UPLOADER, Status.PENDING_DOCTOR).http_status == 403


def test_doctor_cannot_approve_with_errors():
    assert rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, errors=True).http_status == 422


def test_nsu_approves():
    assert move(Action.APPROVE, Role.NSU_REVIEWER, Status.PENDING_NSU) == Status.APPROVED


@pytest.mark.parametrize("role", [Role.ADMIN, Role.HOSPITAL_DOCTOR])
def test_only_nsu_reviewer_approves_nsu_stage(role):
    assert rejected(Action.APPROVE, role, Status.PENDING_NSU).http_status == 403


def test_approve_draft_is_409():
    assert rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.DRAFT).http_status == 409


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_return_needs_comment(comment):
    assert rejected(Action.RETURN, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, comment=comment).http_status == 422


def test_doctor_returns():
    assert move(Action.RETURN, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, comment="date wrong") == Status.DRAFT


def test_nsu_returns():
    assert move(Action.RETURN, Role.NSU_REVIEWER, Status.PENDING_NSU, comment="unclear") == Status.DRAFT


def test_uploader_cannot_return():
    assert rejected(Action.RETURN, Role.UPLOADER, Status.PENDING_DOCTOR, comment="x").http_status == 403


def test_admin_reopens():
    assert move(Action.REOPEN, Role.ADMIN, Status.APPROVED, comment="wrong lobe") == Status.DRAFT


def test_reopen_needs_admin():
    assert rejected(Action.REOPEN, Role.NSU_REVIEWER, Status.APPROVED, comment="x").http_status == 403


def test_reopen_needs_reason():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.APPROVED).http_status == 422


def test_reopen_only_approved():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.PENDING_NSU, comment="x").http_status == 409
