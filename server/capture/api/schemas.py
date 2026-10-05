import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from capture.db.models import Role
from capture.workflow.rules import Action


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    role: str


class TemplateOut(BaseModel):
    key: str
    version: int
    phase: int
    kind: str
    title: str
    definition: dict[str, Any]
    locked: bool


class SettingsIn(BaseModel):
    phase3_enabled: bool


class SettingsOut(BaseModel):
    phase3_enabled: bool


def normalize_username(raw: str) -> str:
    value = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", value):
        raise ValueError("ID must be 3 to 64 letters, digits, dots, dashes or underscores")
    return value


def normalize_reg_no(raw: str) -> str:
    """Spec: the hospital patient ID, RC + digits; whitespace removed, uppercased."""
    value = "".join(raw.split()).upper()
    if not re.fullmatch(r"RC[0-9]{1,30}", value):
        raise ValueError("Patient ID must be RC followed by numbers")
    return value


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    role: str
    active: bool


class AccountIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    username: Annotated[str, AfterValidator(normalize_username)]
    password: str = Field(min_length=10)
    role: Role


class AccountPatch(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10)


class CreateMeta(BaseModel):
    reg_no: Annotated[str, AfterValidator(normalize_reg_no)]
    template_key: str
    client_upload_id: uuid.UUID
    fill_by_hand: bool = False


class ReadIdOut(BaseModel):
    reg_no: str | None  # None when no RC number was found on the page


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    page_no: int | None
    size: int


class LastEventOut(BaseModel):
    action: str
    comment: str | None
    actor_name: str
    created_at: datetime


class EventOut(LastEventOut):
    id: int
    field_changes: list[dict[str, Any]] | None
    field_flags: dict[str, str] | None


class RecordSummary(BaseModel):
    id: uuid.UUID
    reg_no: str
    template_key: str
    template_title: str
    template_version: int
    status: str
    extraction_status: str
    document_date: date | None
    created_by_id: int
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    last_event: LastEventOut | None
    ai_amber: int = 0
    ai_red: int = 0


class RecordDetail(RecordSummary):
    values: dict[str, Any]
    extraction: dict[str, Any] | None
    row_version: int
    files: list[FileOut]
    events: list[EventOut]
    template: TemplateOut
    errors: list[dict[str, str]]
    duplicate_of: list[uuid.UUID] = []
    extraction_queued_at: datetime | None = None


class ValuesIn(BaseModel):
    row_version: int
    values: dict[str, Any]


class TransitionIn(BaseModel):
    row_version: int
    action: Action
    comment: str | None = None
    field_flags: dict[str, str] | None = None

