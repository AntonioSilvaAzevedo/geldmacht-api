"""add icon to categories

Revision ID: a1b2c3d4e5f6
Revises: b8a741a98760
Create Date: 2026-05-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('icon', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('categories', 'icon')
