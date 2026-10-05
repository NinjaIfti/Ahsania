"""two panels: doctor and admin roles, logins by ID, reg. no. stored as-is, no device key or quarantine

Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'doctor' WHERE role IN ('uploader', 'hospital_doctor')")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'nsu_reviewer'")
    op.alter_column("users", "email", new_column_name="username", type_=sa.String(64))
    op.execute("ALTER TABLE users RENAME CONSTRAINT users_email_key TO users_username_key")
    op.drop_column("users", "institution")
    op.alter_column("patients", "study_code", new_column_name="reg_no", type_=sa.String(64))
    op.alter_column("records", "study_code", new_column_name="reg_no", type_=sa.String(64))
    op.execute("ALTER INDEX ix_records_study_code RENAME TO ix_records_reg_no")
    op.execute("UPDATE records SET status = 'draft' WHERE status IN ('quarantined', 'pending_doctor')")
    op.execute("UPDATE records SET status = 'pending_admin' WHERE status = 'pending_nsu'")
    op.drop_column("records", "quarantine")
    op.drop_column("settings", "expected_key_fingerprint")
    op.drop_column("jobs", "skip_safety_net")


def downgrade() -> None:
    op.add_column("jobs", sa.Column("skip_safety_net", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("settings", sa.Column("expected_key_fingerprint", sa.String(16), nullable=True))
    op.add_column("records", sa.Column("quarantine", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE records SET status = 'pending_nsu' WHERE status = 'pending_admin'")
    op.execute("ALTER INDEX ix_records_reg_no RENAME TO ix_records_study_code")
    op.alter_column("records", "reg_no", new_column_name="study_code")
    op.alter_column("patients", "reg_no", new_column_name="study_code")
    op.add_column("users", sa.Column("institution", sa.String(16), server_default="AMCGH", nullable=False))
    op.execute("ALTER TABLE users RENAME CONSTRAINT users_username_key TO users_email_key")
    op.alter_column("users", "username", new_column_name="email", type_=sa.String(320))
    op.execute("UPDATE users SET role = 'hospital_doctor' WHERE role = 'doctor'")
