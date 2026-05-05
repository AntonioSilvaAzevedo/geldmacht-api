"""add invoices table and invoice_id to transactions

Revision ID: e5f6a7b8c9d0
Revises: b8a741a98760
Create Date: 2026-05-05 18:00:00.000000

Criação da tabela `invoices` para representar faturas reais de cartão
(com due_date, ciclo vigente, vencimento) e adição de `invoice_id`
nas transactions como âncora principal.

Inclui migração de dados: transactions existentes agrupadas por
user_id + card_id + reference_month → invoices criadas com dados mínimos
(due_month = reference_month, campos de data nulos por falta de informação real).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "b8a741a98760"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Cria tabela invoices ──────────────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column("id",                  sa.Integer(),                    nullable=False),
        sa.Column("user_id",             sa.Integer(),                    nullable=False),
        sa.Column("card_id",             sa.Integer(),                    nullable=False),
        sa.Column("due_month",           sa.String(length=7),             nullable=False),
        sa.Column("due_date",            sa.Date(),                       nullable=True),
        sa.Column("cycle_start_date",    sa.Date(),                       nullable=True),
        sa.Column("cycle_end_date",      sa.Date(),                       nullable=True),
        sa.Column("issue_date",          sa.Date(),                       nullable=True),
        sa.Column("closing_date",        sa.Date(),                       nullable=True),
        sa.Column("total_amount",        sa.Float(),                      nullable=True),
        sa.Column("source",              sa.String(length=50),            nullable=True),
        sa.Column("raw_reference_month", sa.String(length=7),             nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True),      server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",          sa.DateTime(timezone=True),      server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],        ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_id"], ["credit_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_id",       "invoices", ["id"])
    op.create_index("ix_invoices_user_id",  "invoices", ["user_id"])
    op.create_index("ix_invoices_card_id",  "invoices", ["card_id"])
    op.create_index("ix_invoices_due_month","invoices", ["due_month"])

    # ── Adiciona invoice_id nas transactions ──────────────────────────────────
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "invoice_id",
                sa.Integer(),
                sa.ForeignKey("invoices.id", name="fk_transactions_invoice_id_invoices", ondelete="SET NULL"),
                nullable=True,
            )
        )
    op.create_index("ix_transactions_invoice_id", "transactions", ["invoice_id"])

    # ── Migração de dados antigos ─────────────────────────────────────────────
    # Cria invoices mínimas para transactions existentes com card_id + reference_month.
    # due_date, cycle_start_date, cycle_end_date, etc. ficam NULL pois não há
    # informação confiável para dados históricos (regra: não inventar datas).
    op.execute("""
        INSERT INTO invoices (user_id, card_id, due_month, raw_reference_month, source, created_at, updated_at)
        SELECT DISTINCT user_id, card_id, reference_month, reference_month, 'legacy',
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM transactions
        WHERE card_id IS NOT NULL
          AND reference_month IS NOT NULL
    """)

    # Vincula transactions às invoices recém-criadas
    op.execute("""
        UPDATE transactions
        SET invoice_id = (
            SELECT i.id FROM invoices i
            WHERE i.user_id    = transactions.user_id
              AND i.card_id    = transactions.card_id
              AND i.due_month  = transactions.reference_month
            LIMIT 1
        )
        WHERE card_id IS NOT NULL
          AND reference_month IS NOT NULL
          AND invoice_id IS NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_transactions_invoice_id", table_name="transactions")
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("invoice_id")

    op.drop_index("ix_invoices_due_month", table_name="invoices")
    op.drop_index("ix_invoices_card_id",   table_name="invoices")
    op.drop_index("ix_invoices_user_id",   table_name="invoices")
    op.drop_index("ix_invoices_id",        table_name="invoices")
    op.drop_table("invoices")
