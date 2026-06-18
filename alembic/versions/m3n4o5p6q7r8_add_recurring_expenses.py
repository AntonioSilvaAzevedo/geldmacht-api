"""add recurring_expenses table

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-06-17 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_expenses",
        sa.Column("id",          sa.Integer(),               nullable=False),
        sa.Column("user_id",     sa.Integer(),               nullable=False),
        sa.Column("card_id",     sa.Integer(),               nullable=False),
        sa.Column("description", sa.String(length=200),      nullable=False),
        sa.Column("amount",      sa.Float(),                 nullable=False),
        sa.Column("category_id", sa.Integer(),               nullable=True),
        sa.Column("start_month", sa.String(length=7),        nullable=False),
        sa.Column("active",      sa.Boolean(),               nullable=False, server_default=sa.true()),
        sa.Column("created_at",  sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",  sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["credit_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurring_expenses_id",      "recurring_expenses", ["id"])
    op.create_index("ix_recurring_expenses_user_id", "recurring_expenses", ["user_id"])
    op.create_index("ix_recurring_expenses_card_id", "recurring_expenses", ["card_id"])
    op.create_index("ix_recurring_expenses_category_id", "recurring_expenses", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_recurring_expenses_category_id", table_name="recurring_expenses")
    op.drop_index("ix_recurring_expenses_card_id", table_name="recurring_expenses")
    op.drop_index("ix_recurring_expenses_user_id", table_name="recurring_expenses")
    op.drop_index("ix_recurring_expenses_id",      table_name="recurring_expenses")
    op.drop_table("recurring_expenses")
