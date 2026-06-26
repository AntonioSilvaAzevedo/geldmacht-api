"""add category system_key and recurrence source/end_month

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-06-25 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("system_key", sa.String(length=50), nullable=True))
    op.create_index("ix_categories_system_key", "categories", ["system_key"])

    op.add_column("recurring_expenses", sa.Column("source_transaction_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_recurring_expenses_source_transaction_id",
        "recurring_expenses",
        ["source_transaction_id"],
    )
    op.add_column("recurring_expenses", sa.Column("end_month", sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_recurring_expenses_source_transaction_id", table_name="recurring_expenses")
    op.drop_index("ix_categories_system_key", table_name="categories")
    with op.batch_alter_table("recurring_expenses") as batch_op:
        batch_op.drop_column("end_month")
        batch_op.drop_column("source_transaction_id")
    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_column("system_key")
