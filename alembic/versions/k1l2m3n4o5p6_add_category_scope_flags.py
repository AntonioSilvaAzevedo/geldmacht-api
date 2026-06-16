"""add applies_to_bank and applies_to_credit_card to categories

Revision ID: k1l2m3n4o5p6
Revises: i9j0k1l2m3n4
Create Date: 2026-06-15 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.add_column(
            sa.Column("applies_to_bank", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("applies_to_credit_card", sa.Boolean(), nullable=False, server_default="0")
        )

    op.execute("UPDATE categories SET applies_to_bank = TRUE WHERE scope = 'bank'")
    op.execute("UPDATE categories SET applies_to_credit_card = TRUE WHERE scope = 'credit_card'")


def downgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_column("applies_to_credit_card")
        batch_op.drop_column("applies_to_bank")
