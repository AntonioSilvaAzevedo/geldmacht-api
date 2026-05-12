"""bank_accounts table + transaction source/notes/bank_account_id (Fase 1)

Revision ID: g2h3i4j5k6l7
Revises: f4a5b6c7d8e9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2h3i4j5k6l7"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("institution", sa.String(length=120), nullable=True),
        sa.Column("account_type", sa.String(length=32), nullable=False, server_default="checking"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="BRL"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_accounts_id", "bank_accounts", ["id"])
    op.create_index("ix_bank_accounts_user_id", "bank_accounts", ["user_id"])

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "bank_account_id",
                sa.Integer(),
                sa.ForeignKey("bank_accounts.id", name="fk_transactions_bank_account_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("source", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("transaction_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.String(length=500), nullable=True))
    op.create_index("ix_transactions_bank_account_id", "transactions", ["bank_account_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_bank_account_id", table_name="transactions")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("fk_transactions_bank_account_id", type_="foreignkey")
        batch_op.drop_column("bank_account_id")
        batch_op.drop_column("source")
        batch_op.drop_column("transaction_type")
        batch_op.drop_column("notes")
    op.drop_index("ix_bank_accounts_user_id", table_name="bank_accounts")
    op.drop_index("ix_bank_accounts_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
