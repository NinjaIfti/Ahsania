import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capture.db.base import Base


class Role(enum.StrEnum):
    DOCTOR = "doctor"
    ADMIN = "admin"


class Status(enum.StrEnum):
    PROCESSING = "processing"
    DRAFT = "draft"
    PENDING_ADMIN = "pending_admin"
    APPROVED = "approved"
    DELETED = "deleted"


class ExtractionStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 hex of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class AppSettings(Base):
    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase3_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Patient(Base):
    __tablename__ = "patients"

    reg_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("key", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    phase: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict] = mapped_column(JSONB)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reg_no: Mapped[str] = mapped_column(ForeignKey("patients.reg_no"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    status: Mapped[str] = mapped_column(String(32), index=True)
    extraction_status: Mapped[str] = mapped_column(String(32))
    field_values: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    document_date: Mapped[date | None] = mapped_column(Date)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, name="client_upload_id"
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped[Template] = relationship(lazy="selectin")
    creator: Mapped[User] = relationship(lazy="selectin")
    files: Mapped[list["RecordFile"]] = relationship(order_by="RecordFile.page_no")


class RecordFile(Base):
    __tablename__ = "record_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    page_no: Mapped[int | None] = mapped_column(Integer)
    dicom_meta: Mapped[dict | None] = mapped_column(JSONB)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_queue", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, server_default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = _created_at()


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    field_changes: Mapped[list | None] = mapped_column(JSONB)
    field_flags: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()

    actor: Mapped[User | None] = relationship(lazy="selectin")
