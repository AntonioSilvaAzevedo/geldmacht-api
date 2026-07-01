"""Issue #114 — is_main em bank_accounts, tabela income_sources, income_source_id em transactions.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bank_accounts",
        sa.Column("is_main", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "income_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("nature", sa.String(length=32), nullable=False),
        sa.Column("default_account_id", sa.Integer(), nullable=True),
        sa.Column("expected_amount", sa.Float(), nullable=True),
        sa.Column("frequency", sa.String(length=32), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_account_id"], ["bank_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_income_sources_id", "income_sources", ["id"])
    op.create_index("ix_income_sources_user_id", "income_sources", ["user_id"])
    op.create_index("ix_income_sources_default_account_id", "income_sources", ["default_account_id"])

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "income_source_id",
                sa.Integer(),
                sa.ForeignKey("income_sources.id", name="fk_transactions_income_source_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
    op.create_index("ix_transactions_income_source_id", "transactions", ["income_source_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_income_source_id", table_name="transactions")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("income_source_id")

    op.drop_index("ix_income_sources_default_account_id", table_name="income_sources")
    op.drop_index("ix_income_sources_user_id", table_name="income_sources")
    op.drop_index("ix_income_sources_id", table_name="income_sources")
    op.drop_table("income_sources")

    op.drop_column("bank_accounts", "is_main")
