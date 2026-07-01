"""Issue #103 — affects_summary em transactions (impacto de lançamento manual pós-importação).

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("affects_summary", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("transactions", "affects_summary")
