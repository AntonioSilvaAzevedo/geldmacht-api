"""add cards categories and invoice links

Revision ID: b8a741a98760
Revises: 4332b2115246
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8a741a98760"
down_revision: Union[str, None] = "4332b2115246"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("institution", sa.String(length=120), nullable=True),
        sa.Column("closing_day", sa.Integer(), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_cards_id", "credit_cards", ["id"])
    op.create_index("ix_credit_cards_user_id", "credit_cards", ["user_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_categories_id", "categories", ["id"])
    op.create_index("ix_categories_scope", "categories", ["scope"])
    op.create_index("ix_categories_user_id", "categories", ["user_id"])

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("card_id", sa.Integer(), sa.ForeignKey("credit_cards.id", name="fk_transactions_card_id_credit_cards"), nullable=True))
        batch_op.add_column(sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", name="fk_transactions_category_id_categories"), nullable=True))
        batch_op.add_column(sa.Column("reference_month", sa.String(length=7), nullable=True))
    op.create_index("ix_transactions_card_id", "transactions", ["card_id"])
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.create_index("ix_transactions_reference_month", "transactions", ["reference_month"])

    op.execute("UPDATE transactions SET reference_month = billing_month WHERE billing_month IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_transactions_reference_month", table_name="transactions")
    op.drop_index("ix_transactions_category_id", table_name="transactions")
    op.drop_index("ix_transactions_card_id", table_name="transactions")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("reference_month")
        batch_op.drop_column("category_id")
        batch_op.drop_column("card_id")

    op.drop_index("ix_categories_user_id", table_name="categories")
    op.drop_index("ix_categories_scope", table_name="categories")
    op.drop_index("ix_categories_id", table_name="categories")
    op.drop_table("categories")

    op.drop_index("ix_credit_cards_user_id", table_name="credit_cards")
    op.drop_index("ix_credit_cards_id", table_name="credit_cards")
    op.drop_table("credit_cards")
