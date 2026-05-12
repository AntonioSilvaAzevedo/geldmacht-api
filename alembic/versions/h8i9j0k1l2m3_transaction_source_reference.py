"""Add source_reference to transactions (OFX FITID / extrato).

Revision ID: h8i9j0k1l2m3
Revises: g2h3i4j5k6l7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g2h3i4j5k6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("source_reference", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "source_reference")
