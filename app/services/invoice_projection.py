from datetime import date

from sqlalchemy import and_, case, func, literal
from sqlalchemy.orm import Session

from ..models.invoice import Invoice
from ..models.recurring_expense import RecurringExpense
from ..models.transaction import Transaction

_MONTHS = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def month_label(due_month: str) -> str:
    try:
        return _MONTHS[int(due_month.split("-")[1]) - 1]
    except (ValueError, IndexError):
        return due_month


def _add_months(due_month: str, offset: int) -> str:
    year, month = (int(part) for part in due_month.split("-"))
    index = year * 12 + (month - 1) + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def invoice_net_total_expr():
    return func.coalesce(
        func.sum(
            case(
                (Transaction.amount < 0, func.abs(Transaction.amount)),
                (
                    and_(Transaction.amount > 0, Transaction.is_payment == False),
                    -Transaction.amount,
                ),
                else_=literal(0.0),
            )
        ),
        0.0,
    )


def annual_card_invoices(db: Session, user_id: int, card_id: int, year: int) -> list[dict]:
    rows = (
        db.query(Invoice, invoice_net_total_expr().label("computed_total"))
        .outerjoin(Transaction, Transaction.invoice_id == Invoice.id)
        .filter(Invoice.card_id == card_id, Invoice.user_id == user_id)
        .group_by(Invoice.id)
        .all()
    )

    real_by_month: dict[str, tuple[Invoice, float]] = {}
    latest_month: str | None = None
    for invoice, computed_total in rows:
        total = float(invoice.total_amount if invoice.total_amount is not None else (computed_total or 0))
        real_by_month[invoice.due_month] = (invoice, round(total, 2))
        if latest_month is None or invoice.due_month > latest_month:
            latest_month = invoice.due_month

    predicted_by_month: dict[str, float] = {}
    if latest_month is not None:
        installments = (
            db.query(Transaction)
            .join(Invoice, Transaction.invoice_id == Invoice.id)
            .filter(
                Invoice.card_id == card_id,
                Invoice.user_id == user_id,
                Invoice.due_month == latest_month,
                Transaction.installment_total.isnot(None),
                Transaction.installment_current.isnot(None),
                Transaction.installment_total > Transaction.installment_current,
            )
            .all()
        )
        for tx in installments:
            remaining = int(tx.installment_total) - int(tx.installment_current)
            value = abs(float(tx.amount))
            for offset in range(1, remaining + 1):
                month = _add_months(latest_month, offset)
                if month in real_by_month:
                    continue
                predicted_by_month[month] = round(predicted_by_month.get(month, 0.0) + value, 2)

        active_subs = (
            db.query(RecurringExpense)
            .filter(
                RecurringExpense.card_id == card_id,
                RecurringExpense.user_id == user_id,
                RecurringExpense.active.is_(True),
            )
            .all()
        )
        if active_subs:
            year_end = f"{year:04d}-12"
            offset = 1
            while True:
                month = _add_months(latest_month, offset)
                offset += 1
                if month > year_end:
                    break
                if month in real_by_month:
                    continue
                sub_sum = round(sum(s.amount for s in active_subs if s.start_month <= month), 2)
                if sub_sum > 0:
                    predicted_by_month[month] = round(predicted_by_month.get(month, 0.0) + sub_sum, 2)

    prefix = f"{year:04d}-"
    months: list[dict] = []
    for due_month, (invoice, total) in real_by_month.items():
        if due_month.startswith(prefix):
            months.append({
                "due_month": due_month,
                "label": month_label(due_month),
                "total": total,
                "predicted": False,
                "invoice_id": invoice.id,
            })
    for due_month, total in predicted_by_month.items():
        if due_month.startswith(prefix):
            months.append({
                "due_month": due_month,
                "label": month_label(due_month),
                "total": total,
                "predicted": True,
                "invoice_id": None,
            })

    months.sort(key=lambda entry: entry["due_month"])
    return months


def default_year() -> int:
    return date.today().year


def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"
