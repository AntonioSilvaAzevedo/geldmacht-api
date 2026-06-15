"""add institutions table and institution_id to bank_accounts and credit_cards

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-15 17:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "institutions",
        sa.Column("id",         sa.Integer(),               nullable=False),
        sa.Column("user_id",    sa.Integer(),               nullable=False),
        sa.Column("name",       sa.String(length=120),      nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_institutions_user_name"),
    )
    op.create_index("ix_institutions_id",      "institutions", ["id"])
    op.create_index("ix_institutions_user_id", "institutions", ["user_id"])

    with op.batch_alter_table("bank_accounts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "institution_id",
                sa.Integer(),
                sa.ForeignKey("institutions.id", name="fk_bank_accounts_institution_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
    op.create_index("ix_bank_accounts_institution_id", "bank_accounts", ["institution_id"])

    with op.batch_alter_table("credit_cards") as batch_op:
        batch_op.add_column(
            sa.Column(
                "institution_id",
                sa.Integer(),
                sa.ForeignKey("institutions.id", name="fk_credit_cards_institution_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
    op.create_index("ix_credit_cards_institution_id", "credit_cards", ["institution_id"])

    op.execute("""
        INSERT INTO institutions (user_id, name, created_at, updated_at)
        SELECT user_id, institution, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM (
            SELECT DISTINCT user_id, institution FROM bank_accounts
            WHERE institution IS NOT NULL AND TRIM(institution) <> ''
            UNION
            SELECT DISTINCT user_id, institution FROM credit_cards
            WHERE institution IS NOT NULL AND TRIM(institution) <> ''
        ) AS combined
    """)

    op.execute("""
        UPDATE bank_accounts SET institution_id = (
            SELECT i.id FROM institutions i
            WHERE i.user_id = bank_accounts.user_id AND i.name = bank_accounts.institution
        )
        WHERE institution IS NOT NULL AND TRIM(institution) <> ''
    """)

    op.execute("""
        UPDATE credit_cards SET institution_id = (
            SELECT i.id FROM institutions i
            WHERE i.user_id = credit_cards.user_id AND i.name = credit_cards.institution
        )
        WHERE institution IS NOT NULL AND TRIM(institution) <> ''
    """)


def downgrade() -> None:
    op.drop_index("ix_credit_cards_institution_id", table_name="credit_cards")
    with op.batch_alter_table("credit_cards") as batch_op:
        batch_op.drop_column("institution_id")

    op.drop_index("ix_bank_accounts_institution_id", table_name="bank_accounts")
    with op.batch_alter_table("bank_accounts") as batch_op:
        batch_op.drop_column("institution_id")

    op.drop_index("ix_institutions_user_id", table_name="institutions")
    op.drop_index("ix_institutions_id",      table_name="institutions")
    op.drop_table("institutions")
