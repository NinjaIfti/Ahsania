"""initial schema

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("institution", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expected_key_fingerprint", sa.String(16), nullable=True),
        sa.Column("phase3_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("id = 1", name="settings_singleton"),
    )
    op.execute("INSERT INTO settings (id, phase3_enabled) VALUES (1, false)")
    op.create_table(
        "patients",
        sa.Column("study_code", sa.String(16), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("key", "version"),
    )
    op.create_table(
        "records",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("study_code", sa.String(16), sa.ForeignKey("patients.study_code"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("extraction_status", sa.String(32), nullable=False),
        sa.Column("field_values", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("extraction", postgresql.JSONB(), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("quarantine", postgresql.JSONB(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_records_study_code", "records", ["study_code"])
    op.create_index("ix_records_status", "records", ["status"])
    op.create_table(
        "record_files",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("dicom_meta", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_record_files_record_id", "record_files", ["record_id"])
    op.create_index("ix_record_files_sha256", "record_files", ["sha256"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        _created_at(),
    )
    op.create_index("ix_jobs_record_id", "jobs", ["record_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("field_changes", postgresql.JSONB(), nullable=True),
        sa.Column("field_flags", postgresql.JSONB(), nullable=True),
        _created_at(),
    )
    op.create_index("ix_review_events_record_id", "review_events", ["record_id"])
    op.execute(
        """
        CREATE FUNCTION review_events_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'review_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_events_no_update_delete
        BEFORE UPDATE OR DELETE ON review_events
        FOR EACH ROW EXECUTE FUNCTION review_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_events_no_update_delete ON review_events")
    op.execute("DROP FUNCTION IF EXISTS review_events_append_only()")
    for table in ("review_events", "jobs", "record_files", "records", "templates", "patients", "settings", "sessions", "users"):
        op.drop_table(table)
