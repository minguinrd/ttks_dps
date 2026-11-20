"""categories fk

Revision ID: b95399332e12
Revises: 245bf1a60eae
Create Date: 2026-11-19 21:58:30.403023

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b95399332e12"
down_revision = "245bf1a60eae"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite DDL is non-transactional: an interrupted prior run can leave the
    # batch temp table behind and block every retry with
    # "table _alembic_tmp_tickets already exists". Clear any leftover first.
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_tickets")

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # Fixed ids: the backfill below maps the legacy enum values onto them.
    op.execute(
        "INSERT INTO categories (id, name) VALUES "
        "(1, 'Hardware'), (2, 'Software'), (3, 'Network'), (4, 'Access'), (5, 'Other')"
    )

    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_tickets_category_id", "categories", ["category_id"], ["id"])

    # Backfill: the five legacy lowercase values map to the seeded ids; any
    # other legacy value becomes its own category row (no ticket loses its
    # category). NOT EXISTS guards a case-variant of a seeded name.
    op.execute(
        """
        UPDATE tickets SET category_id = CASE category
            WHEN 'hardware' THEN 1 WHEN 'software' THEN 2 WHEN 'network' THEN 3
            WHEN 'access' THEN 4 WHEN 'other' THEN 5 END
        """
    )
    op.execute(
        """
        INSERT INTO categories (name)
        SELECT DISTINCT t.category FROM tickets t
        WHERE t.category_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM categories c WHERE c.name = t.category)
        """
    )
    op.execute(
        """
        UPDATE tickets SET category_id =
            (SELECT c.id FROM categories c WHERE c.name = tickets.category)
        WHERE category_id IS NULL
        """
    )
    remaining = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM tickets WHERE category_id IS NULL"))
        .scalar()
    )
    if remaining:
        raise RuntimeError(f"{remaining} tickets have no category after backfill")

    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.alter_column(
            "category_id", existing_type=sa.Integer(), existing_nullable=True, nullable=False
        )
        batch_op.drop_column("category")


def downgrade():
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=20), nullable=True))
    # Legacy column held lowercase enum values; custom names lowercase on the
    # way back (accepted wrinkle — see spec, rollback decision A).
    op.execute(
        "UPDATE tickets SET category = lower("
        "(SELECT name FROM categories WHERE id = tickets.category_id))"
    )
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.alter_column(
            "category", existing_type=sa.String(length=20), existing_nullable=True, nullable=False
        )
        batch_op.drop_column("category_id")
    op.drop_table("categories")
