"""add billing_month to transactions

Revision ID: fd3210abc901
Revises: 1dcb12179e52
Create Date: 2026-05-04 22:05:41.926997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd3210abc901'
down_revision: Union[str, None] = '1dcb12179e52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("billing_month", sa.String(7), nullable=True),
    )
    op.create_index("ix_transactions_billing_month", "transactions", ["billing_month"])


def downgrade() -> None:
    op.drop_index("ix_transactions_billing_month", table_name="transactions")
    op.drop_column("transactions", "billing_month")
