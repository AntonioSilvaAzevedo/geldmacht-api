"""add credit_limit to credit_cards

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-08 18:00:00.000000

Adiciona `credit_cards.credit_limit` (Float, nullable). Limite informado
manualmente pelo usuário; serve para cálculos auxiliares (% da fatura usado
do limite, orçamento liberado por parcelas finalizadas).
"""
from alembic import op
import sqlalchemy as sa


revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credit_limit', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.drop_column('credit_limit')
