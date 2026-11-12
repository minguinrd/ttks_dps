"""spanish default language

Revision ID: 245bf1a60eae
Revises: 7cee1007d919
Create Date: 2026-11-12 06:44:23.483169

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "245bf1a60eae"
down_revision = "7cee1007d919"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite DDL is non-transactional: an interrupted prior run can leave the
    # batch temp table behind and block every retry with
    # "table _alembic_tmp_users already exists". Clear any leftover first.
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_users")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "language",
            existing_type=sa.String(length=5),
            existing_nullable=False,
            existing_server_default="en",
            server_default="es",
        )

    # Spanish is the default: existing accounts never chose English — it was
    # simply the only default — so move everyone over.
    op.execute("UPDATE users SET language = 'es'")


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "language",
            existing_type=sa.String(length=5),
            existing_nullable=False,
            existing_server_default="es",
            server_default="en",
        )
    # Data is deliberately not flipped back: language is a per-user preference.
