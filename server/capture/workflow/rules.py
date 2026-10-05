import enum

from capture.db.models import HOSPITAL_ROLES, Role, Status


class Action(enum.StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    RETURN = "return"
    REOPEN = "reopen"
    RELEASE = "release"
    FILL_BY_HAND = "fill_by_hand"


class TransitionError(Exception):
    def __init__(self, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


NSU_VISIBLE = frozenset({Status.PENDING_NSU, Status.APPROVED})


def can_view(role: str, status: str) -> bool:
    """Hospital staff see everything; NSU only sees records a hospital doctor has approved."""
    return role in HOSPITAL_ROLES or status in NSU_VISIBLE


def can_edit(role: str, status: str) -> bool:
    if role == Role.UPLOADER:
        return status == Status.DRAFT
    if role == Role.HOSPITAL_DOCTOR:
        return status in (Status.DRAFT, Status.PENDING_DOCTOR)
    return False


def next_status(
    *,
    action: str,
    role: str,
    status: str,
    actor_id: int,
    creator_id: int,
    comment: str | None,
    has_errors: bool,
) -> Status:
    has_comment = bool(comment and comment.strip())
    if action == Action.SUBMIT:
        if role not in HOSPITAL_ROLES:
            raise TransitionError("Only hospital staff can submit records", 403)
        if status != Status.DRAFT:
            raise TransitionError("Only drafts can be submitted")
        if has_errors:
            raise TransitionError("Fix the highlighted fields before submitting", 422)
        return Status.PENDING_DOCTOR
    if action == Action.APPROVE:
        if status == Status.PENDING_DOCTOR:
            if role != Role.HOSPITAL_DOCTOR:
                raise TransitionError("Only a hospital doctor can approve at this stage", 403)
            if actor_id == creator_id:
                raise TransitionError("You uploaded this record, so another doctor must approve it", 403)
            if has_errors:
                raise TransitionError("Fix the highlighted fields before approving", 422)
            return Status.PENDING_NSU
        if status == Status.PENDING_NSU:
            if role != Role.NSU_REVIEWER:
                raise TransitionError("Only an NSU reviewer can approve at this stage", 403)
            return Status.APPROVED
        raise TransitionError("This record is not waiting for approval")
    if action == Action.RETURN:
        if not has_comment:
            raise TransitionError("A comment is required when returning a record", 422)
        doctor_stage = status == Status.PENDING_DOCTOR and role == Role.HOSPITAL_DOCTOR
        nsu_stage = status == Status.PENDING_NSU and role == Role.NSU_REVIEWER
        if doctor_stage or nsu_stage:
            return Status.DRAFT
        raise TransitionError("You cannot return this record at this stage", 403)
    if action == Action.REOPEN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can reopen records", 403)
        if status != Status.APPROVED:
            raise TransitionError("Only approved records can be reopened")
        if not has_comment:
            raise TransitionError("A reason is required to reopen a record", 422)
        return Status.DRAFT
    if action == Action.RELEASE:
        if role != Role.HOSPITAL_DOCTOR:
            raise TransitionError("Only a hospital doctor can release a held-back record", 403)
        if status != Status.QUARANTINED:
            raise TransitionError("Only held-back records can be released")
        if not has_comment:
            raise TransitionError("A comment is required to release a record", 422)
        return Status.PROCESSING
    if action == Action.FILL_BY_HAND:
        if role not in HOSPITAL_ROLES:
            raise TransitionError("Only hospital staff can fill in records", 403)
        if status != Status.PROCESSING:
            raise TransitionError("This record is not waiting for the AI")
        return Status.DRAFT
    raise TransitionError(f"Unknown action: {action}", 422)
