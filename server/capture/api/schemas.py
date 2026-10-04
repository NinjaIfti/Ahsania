import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from capture.workflow.rules import Action


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    institution: str


class TemplateOut(BaseModel):
    key: str
    version: int
    phase: int
    kind: str
    title: str
    definition: dict[str, Any]
    locked: bool


class FingerprintIn(BaseModel):
    fingerprint: str = Field(pattern=r"^K-[0-9A-F]{4}$")


class FingerprintOut(BaseModel):
    expected: str | None
    status: Literal["set", "match"] | None = None


class SettingsIn(BaseModel):
    phase3_enabled: bool


class SettingsOut(BaseModel):
    phase3_enabled: bool
    expected_key_fingerprint: str | None


STUDY_CODE_PATTERN = r"^AMH-[0-9A-HJKMNP-TV-Z]{10}$"


class CreateMeta(BaseModel):
    study_code: str = Field(pattern=STUDY_CODE_PATTERN)
    template_key: str
    key_fingerprint: str
    client_upload_id: uuid.UUID


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
    study_code: str
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


class RecordDetail(RecordSummary):
    values: dict[str, Any]
    extraction: dict[str, Any] | None
    row_version: int
    files: list[FileOut]
    events: list[EventOut]
    template: TemplateOut
    errors: list[dict[str, str]]
    duplicate_of: list[uuid.UUID] = []


class ValuesIn(BaseModel):
    row_version: int
    values: dict[str, Any]


class TransitionIn(BaseModel):
    row_version: int
    action: Action
    comment: str | None = None
    field_flags: dict[str, str] | None = None
