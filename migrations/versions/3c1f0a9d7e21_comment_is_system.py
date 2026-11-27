"""comment is_system flag

Revision ID: 3c1f0a9d7e21
Revises: b95399332e12
Create Date: 2026-11-27 10:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3c1f0a9d7e21"
down_revision = "b95399332e12"
branch_labels = None
depends_on = None

# The sentences Ticket.add_system_comment has always written.
_SYSTEM_PATTERNS = (
    "Claimed by %.",
    "Released by %.",
    "Assigned to % by %.",
    "Resolved by %.",
    "Reopened by %.",
    "Closed by %.",
)


def upgrade():
    # SQLite accepts ADD COLUMN ... NOT NULL when a default is given, so no
    # batch (table copy) is needed.
    op.add_column(
        "comments",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Backfill: earlier system entries are the comments whose body has one of
    # the fixed shapes above and was never marked internal.
    comments = sa.table(
        "comments",
        sa.column("body", sa.Text),
        sa.column("is_internal", sa.Boolean),
        sa.column("is_system", sa.Boolean),
    )
    op.execute(
        comments.update()
        .where(
            sa.or_(*(comments.c.body.like(pattern) for pattern in _SYSTEM_PATTERNS)),
            comments.c.is_internal.is_(sa.false()),
        )
        .values(is_system=True)
    )


def downgrade():
    with op.batch_alter_table("comments") as batch_op:
        batch_op.drop_column("is_system")
