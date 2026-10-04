import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
