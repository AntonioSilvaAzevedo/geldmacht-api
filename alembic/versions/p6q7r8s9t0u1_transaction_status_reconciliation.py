"""Issue #108 — status e conciliação de movimentações em transactions.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    op.add_column(
        "transactions",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="confirmed"),
    )
    op.add_column(
        "transactions",
        sa.Column("reconciled_with_transaction_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_transactions_reconciled_with_transaction_id"),
        "transactions",
        ["reconciled_with_transaction_id"],
        unique=False,
    )

    if dialect == "postgresql":
        op.create_foreign_key(
            "fk_transactions_reconciled_with_transaction_id_transactions",
            "transactions",
            "transactions",
            ["reconciled_with_transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.drop_constraint(
            "fk_transactions_reconciled_with_transaction_id_transactions", "transactions", type_="foreignkey"
        )
    op.drop_index(op.f("ix_transactions_reconciled_with_transaction_id"), table_name="transactions")
    op.drop_column("transactions", "reconciled_with_transaction_id")
    op.drop_column("transactions", "status")
