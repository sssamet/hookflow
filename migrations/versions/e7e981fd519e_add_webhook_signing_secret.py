
"""Add webhook signing secret

Revision ID: e7e981fd519e
Revises: 77952699ade7
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7e981fd519e"
down_revision: str | Sequence[str] | None = "77952699ade7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column(
            "signing_secret",
            sa.String(length=64),
            nullable=True,
        ),
    )

    connection = op.get_bind()
    webhooks = sa.table(
        "webhooks",
        sa.column("id", sa.String(length=36)),
        sa.column("signing_secret", sa.String(length=64)),
    )

    rows = connection.execute(
        sa.select(webhooks.c.id)
    ).fetchall()

    for row in rows:
        connection.execute(
            webhooks.update()
            .where(webhooks.c.id == row.id)
            .values(signing_secret=secrets.token_hex(32))
        )

    with op.batch_alter_table("webhooks") as batch_op:
        batch_op.alter_column(
            "signing_secret",
            existing_type=sa.String(length=64),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("webhooks", "signing_secret")
