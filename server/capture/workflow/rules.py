import enum

from capture.db.models import Role, Status


class Action(enum.StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    RETURN = "return"
    REOPEN = "reopen"
    FILL_BY_HAND = "fill_by_hand"


class TransitionError(Exception):
    def __init__(self, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def can_edit(role: str, status: str) -> bool:
    return role == Role.DOCTOR and status == Status.DRAFT


def can_delete(role: str, status: str, ever_sent: bool) -> bool:
    """A doctor may delete a capture until it has gone to the admin once."""
    return role == Role.DOCTOR and status in (Status.PROCESSING, Status.DRAFT) and not ever_sent


def next_status(*, action: str, role: str, status: str, comment: str | None, has_errors: bool) -> Status:
    has_comment = bool(comment and comment.strip())
    if action == Action.SUBMIT:
        if role != Role.DOCTOR:
            raise TransitionError("Only a doctor can approve a draft", 403)
        if status != Status.DRAFT:
            raise TransitionError("Only drafts can be sent to the admin")
        if has_errors:
            raise TransitionError("Fix the highlighted fields before approving", 422)
        return Status.PENDING_ADMIN
    if action == Action.APPROVE:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can give the final approval", 403)
        if status != Status.PENDING_ADMIN:
            raise TransitionError("This record is not waiting for the admin")
        return Status.APPROVED
    if action == Action.RETURN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can send a record back", 403)
        if status != Status.PENDING_ADMIN:
            raise TransitionError("This record is not waiting for the admin")
        if not has_comment:
            raise TransitionError("A comment is required when sending a record back", 422)
        return Status.DRAFT
    if action == Action.REOPEN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can reopen records", 403)
        if status != Status.APPROVED:
            raise TransitionError("Only approved records can be reopened")
        if not has_comment:
            raise TransitionError("A reason is required to reopen a record", 422)
        return Status.DRAFT
    if action == Action.FILL_BY_HAND:
        if role != Role.DOCTOR:
            raise TransitionError("Only a doctor can fill in records", 403)
        if status != Status.PROCESSING:
            raise TransitionError("This record is not waiting for the AI")
        return Status.DRAFT
    raise TransitionError(f"Unknown action: {action}", 422)
