"""add tags and transaction_tags tables

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-06-25 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id",              sa.Integer(),               nullable=False),
        sa.Column("user_id",         sa.Integer(),               nullable=False),
        sa.Column("name",            sa.String(length=60),       nullable=False),
        sa.Column("normalized_name", sa.String(length=60),       nullable=False),
        sa.Column("created_at",      sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at",      sa.DateTime(timezone=True),  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_tags_user_normalized"),
    )
    op.create_index("ix_tags_id",              "tags", ["id"])
    op.create_index("ix_tags_user_id",         "tags", ["user_id"])
    op.create_index("ix_tags_normalized_name", "tags", ["normalized_name"])

    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id",         sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("transaction_tags")
    op.drop_index("ix_tags_normalized_name", table_name="tags")
    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_index("ix_tags_id", table_name="tags")
    op.drop_table("tags")
