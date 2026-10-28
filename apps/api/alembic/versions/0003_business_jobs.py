"""Persist business job inputs, results, source ACLs, retry scheduling and worker fencing."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("jobs", sa.Column("result", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("input_hash", sa.String(64), nullable=True))
    op.add_column("jobs", sa.Column("document_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("jobs", sa.Column("claim_token", sa.String(36), nullable=True))
    op.add_column("jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=False,
                                    server_default=sa.func.now()))


def downgrade():
    for column in ("available_at", "claim_token", "document_ids", "input_hash", "result", "payload"):
        op.drop_column("jobs", column)
