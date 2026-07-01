import calendar
from datetime import date

from sqlalchemy.orm import Session

from ..models.transaction import Transaction


def get_month_bounds(month: str) -> tuple[date, date]:
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    return start, end


def get_month_state(db: Session, bank_account_id: int, month: str) -> dict:
    start, end = get_month_bounds(month)
    rows = (
        db.query(Transaction.source, Transaction.imported_at)
        .filter(
            Transaction.bank_account_id == bank_account_id,
            Transaction.date >= start,
            Transaction.date <= end,
        )
        .all()
    )

    manual_rows = [r for r in rows if r.source == "manual"]
    imported_rows = [r for r in rows if r.source == "bank_statement_import"]

    has_manual = len(manual_rows) > 0
    has_imported = len(imported_rows) > 0

    manual_after_import = False
    if has_manual and has_imported:
        last_import_at = max(r.imported_at for r in imported_rows)
        manual_after_import = any(r.imported_at > last_import_at for r in manual_rows)

    return {
        "has_manual": has_manual,
        "has_imported": has_imported,
        "manual_after_import": manual_after_import,
        "can_import_statement": not has_manual,
        "needs_impact_confirmation": has_imported,
    }
