"""evolve categories: card_id, parent_id, invoice_budget_limit

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-07 00:00:00.000000

Adiciona à tabela `categories`:
  - card_id: FK para credit_cards (nullable). null = aplica em todos os cartões.
  - parent_id: self-FK para categories (nullable). null = categoria principal;
    preenchido = subcategoria. Profundidade máxima de 1 nível (validado no app).
  - invoice_budget_limit: limite de gasto por fatura (Float, nullable, > 0 quando informado).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('card_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('invoice_budget_limit', sa.Float(), nullable=True))
        batch_op.create_foreign_key(
            'fk_categories_card_id',
            'credit_cards',
            ['card_id'], ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_categories_parent_id',
            'categories',
            ['parent_id'], ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index('ix_categories_card_id', ['card_id'])
        batch_op.create_index('ix_categories_parent_id', ['parent_id'])


def downgrade() -> None:
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_index('ix_categories_parent_id')
        batch_op.drop_index('ix_categories_card_id')
        batch_op.drop_constraint('fk_categories_parent_id', type_='foreignkey')
        batch_op.drop_constraint('fk_categories_card_id', type_='foreignkey')
        batch_op.drop_column('invoice_budget_limit')
        batch_op.drop_column('parent_id')
        batch_op.drop_column('card_id')
