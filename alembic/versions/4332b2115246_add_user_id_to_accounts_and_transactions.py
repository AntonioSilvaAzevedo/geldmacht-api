"""add_user_id_to_accounts_and_transactions

Revision ID: 4332b2115246
Revises: 301e20142f6f
Create Date: 2026-05-05

Estratégia de upgrade:
  1. Adiciona user_id como nullable=True (não quebra linhas existentes)
  2. Deleta todas as linhas órfãs (sem user_id) — dados sem dono não fazem sentido
  3. Em PostgreSQL, converte para NOT NULL via ALTER COLUMN
     Em SQLite, a coluna fica nullable no schema mas os models impõem NOT NULL na app

Nota: em ambiente de desenvolvimento (SQLite) é recomendado fazer rm geldmacht.db
      antes de rodar este upgrade para começar com banco limpo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '4332b2115246'
down_revision: Union[str, None] = '301e20142f6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name  # "sqlite" ou "postgresql"

    # ── 1. Adiciona colunas como nullable (compatível com linhas existentes) ──
    op.add_column('accounts', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_accounts_user_id'), 'accounts', ['user_id'], unique=False)

    op.add_column('transactions', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_transactions_user_id'), 'transactions', ['user_id'], unique=False)

    # ── 2. Remove linhas órfãs (sem user_id) — dados não segmentados não têm valor ──
    conn.execute(text("DELETE FROM transactions WHERE user_id IS NULL"))
    conn.execute(text("DELETE FROM accounts WHERE user_id IS NULL"))

    # ── 3. Adiciona FK e NOT NULL constraint (apenas PostgreSQL suporta ALTER COLUMN) ──
    if dialect == "postgresql":
        op.create_foreign_key(
            'fk_accounts_user_id', 'accounts', 'users', ['user_id'], ['id'], ondelete='CASCADE'
        )
        op.create_foreign_key(
            'fk_transactions_user_id', 'transactions', 'users', ['user_id'], ['id'], ondelete='CASCADE'
        )
        op.alter_column('accounts',     'user_id', nullable=False)
        op.alter_column('transactions', 'user_id', nullable=False)
    # SQLite: FK e NOT NULL não são alteráveis via ALTER TABLE — enforçados pela app


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.drop_constraint('fk_transactions_user_id', 'transactions', type_='foreignkey')
        op.drop_constraint('fk_accounts_user_id',     'accounts',     type_='foreignkey')

    op.drop_index(op.f('ix_transactions_user_id'), table_name='transactions')
    op.drop_column('transactions', 'user_id')
    op.drop_index(op.f('ix_accounts_user_id'), table_name='accounts')
    op.drop_column('accounts', 'user_id')
