"""ensure webhook deliveries table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "980c9a8a96ce"
down_revision: Union[str, Sequence[str], None] = "f25adf7480cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create webhook_deliveries if it does not exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("webhook_deliveries"):
        return

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["webhook_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_webhook_deliveries_event_id",
        "webhook_deliveries",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop webhook_deliveries if it exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("webhook_deliveries"):
        return

    indexes = {
        index["name"]
        for index in inspector.get_indexes("webhook_deliveries")
    }

    if "ix_webhook_deliveries_event_id" in indexes:
        op.drop_index(
            "ix_webhook_deliveries_event_id",
            table_name="webhook_deliveries",
        )

    op.drop_table("webhook_deliveries")
