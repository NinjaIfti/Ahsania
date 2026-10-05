"""extraction worker: job retry time and safety-net flag; worker-written review events have no actor

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("jobs", sa.Column("skip_safety_net", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index("ix_jobs_queue", "jobs", ["status", "run_after"])
    op.alter_column("review_events", "actor_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("review_events", "actor_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_jobs_queue", table_name="jobs")
    op.drop_column("jobs", "skip_safety_net")
    op.drop_column("jobs", "run_after")
