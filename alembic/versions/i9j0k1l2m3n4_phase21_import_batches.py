"""Phase 2.1 — import_batches, transaction import_batch_id + fingerprint.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("import_kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_used", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_batches_user_id"), "import_batches", ["user_id"], unique=False)
    op.create_index(op.f("ix_import_batches_bank_account_id"), "import_batches", ["bank_account_id"], unique=False)
    op.create_index(op.f("ix_import_batches_file_hash"), "import_batches", ["file_hash"], unique=False)

    op.add_column(
        "transactions",
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("transaction_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_transactions_import_batch_id"),
        "transactions",
        ["import_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_transaction_fingerprint"),
        "transactions",
        ["transaction_fingerprint"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_transactions_import_batch_id_import_batches",
        "transactions",
        "import_batches",
        ["import_batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_transactions_import_batch_id_import_batches", "transactions", type_="foreignkey")
    op.drop_index(op.f("ix_transactions_transaction_fingerprint"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_import_batch_id"), table_name="transactions")
    op.drop_column("transactions", "transaction_fingerprint")
    op.drop_column("transactions", "import_batch_id")

    op.drop_index(op.f("ix_import_batches_file_hash"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_bank_account_id"), table_name="import_batches")
    op.drop_index(op.f("ix_import_batches_user_id"), table_name="import_batches")
    op.drop_table("import_batches")
