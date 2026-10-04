"""hardening: idempotent uploads

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("records", sa.Column("client_upload_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_records_client_upload_id", "records", ["client_upload_id"])


def downgrade() -> None:
    op.drop_constraint("uq_records_client_upload_id", "records", type_="unique")
    op.drop_column("records", "client_upload_id")
