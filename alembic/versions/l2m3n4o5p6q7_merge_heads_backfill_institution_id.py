"""merge institutions + category scope heads and backfill institution_id

Revision ID: l2m3n4o5p6q7
Revises: j0k1l2m3n4o5, k1l2m3n4o5p6
Create Date: 2026-06-17 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, Sequence[str], None] = ("j0k1l2m3n4o5", "k1l2m3n4o5p6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INSERT_MISSING_INSTITUTIONS = text("""
    INSERT INTO institutions (user_id, name, created_at, updated_at)
    SELECT combined.user_id, combined.institution, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    FROM (
        SELECT DISTINCT user_id, institution FROM bank_accounts
        WHERE institution IS NOT NULL AND TRIM(institution) <> ''
        UNION
        SELECT DISTINCT user_id, institution FROM credit_cards
        WHERE institution IS NOT NULL AND TRIM(institution) <> ''
    ) AS combined
    WHERE NOT EXISTS (
        SELECT 1 FROM institutions i
        WHERE i.user_id = combined.user_id AND i.name = combined.institution
    )
""")

LINK_BANK_ACCOUNTS = text("""
    UPDATE bank_accounts SET institution_id = (
        SELECT i.id FROM institutions i
        WHERE i.user_id = bank_accounts.user_id AND i.name = bank_accounts.institution
    )
    WHERE institution_id IS NULL AND institution IS NOT NULL AND TRIM(institution) <> ''
""")

LINK_CREDIT_CARDS = text("""
    UPDATE credit_cards SET institution_id = (
        SELECT i.id FROM institutions i
        WHERE i.user_id = credit_cards.user_id AND i.name = credit_cards.institution
    )
    WHERE institution_id IS NULL AND institution IS NOT NULL AND TRIM(institution) <> ''
""")


def _backfill(conn) -> None:
    conn.execute(INSERT_MISSING_INSTITUTIONS)
    conn.execute(LINK_BANK_ACCOUNTS)
    conn.execute(LINK_CREDIT_CARDS)


def upgrade() -> None:
    _backfill(op.get_bind())


def downgrade() -> None:
    pass
