"""add release notes and user views

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-07 12:00:00.000000

Cria tabelas:
  - release_notes: notas de atualização por versão (version único, items_json, show_modal).
  - user_release_note_views: registro de visualização por usuário/versão
    (constraint única user_id + release_note_id).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("show_modal", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_release_notes_version", "release_notes", ["version"])

    op.create_table(
        "user_release_note_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("release_note_id", sa.Integer(),
                  sa.ForeignKey("release_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "release_note_id", name="uq_user_release_view"),
    )
    op.create_index("ix_user_release_note_views_user_id", "user_release_note_views", ["user_id"])
    op.create_index("ix_user_release_note_views_release_note_id", "user_release_note_views", ["release_note_id"])


def downgrade() -> None:
    op.drop_index("ix_user_release_note_views_release_note_id", table_name="user_release_note_views")
    op.drop_index("ix_user_release_note_views_user_id", table_name="user_release_note_views")
    op.drop_table("user_release_note_views")
    op.drop_index("ix_release_notes_version", table_name="release_notes")
    op.drop_table("release_notes")
