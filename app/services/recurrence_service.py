from sqlalchemy.orm import Session

from ..models.category import Category
from ..models.invoice import Invoice
from ..models.recurring_expense import RecurringExpense
from ..models.transaction import Transaction
from .invoice_projection import _add_months

RECORRENTES_KEY = "recorrentes"

RECURRING_MONTHS = 12

SYSTEM_SUGGESTIONS = [
    {
        "key": RECORRENTES_KEY,
        "name": "Recorrentes",
        "description": "Use para assinaturas, aluguel, mensalidades e cobranças que ocorrem todo mês.",
        "icon": "🔁",
    },
]


def recorrentes_category_for_user(db: Session, user_id: int) -> Category | None:
    return (
        db.query(Category)
        .filter(Category.user_id == user_id, Category.system_key == RECORRENTES_KEY)
        .first()
    )


def _is_systemic(tx: Transaction) -> bool:
    return bool(tx.is_payment) or (
        tx.installment_total is not None and tx.installment_total > 1
    )


def sync_recurrence_for_transaction(db: Session, tx: Transaction) -> RecurringExpense | None:
    existing = (
        db.query(RecurringExpense)
        .filter(RecurringExpense.source_transaction_id == tx.id)
        .first()
    )

    rec_category = None
    if tx.category_id is not None:
        rec_category = (
            db.query(Category)
            .filter(
                Category.id == tx.category_id,
                Category.user_id == tx.user_id,
                Category.system_key == RECORRENTES_KEY,
            )
            .first()
        )

    should_recur = (
        rec_category is not None
        and not _is_systemic(tx)
        and tx.card_id is not None
        and tx.invoice_id is not None
        and tx.amount < 0
    )

    if not should_recur:
        if existing is not None:
            db.delete(existing)
        return None

    invoice = tx.invoice or db.query(Invoice).get(tx.invoice_id)
    if invoice is None:
        if existing is not None:
            db.delete(existing)
        return None

    start_month = invoice.due_month
    end_month = _add_months(start_month, RECURRING_MONTHS)
    amount = abs(float(tx.amount))

    if existing is not None:
        existing.description = tx.description
        existing.amount = amount
        existing.category_id = tx.category_id
        existing.card_id = tx.card_id
        existing.start_month = start_month
        existing.end_month = end_month
        existing.active = True
        return existing

    recurring = RecurringExpense(
        user_id=tx.user_id,
        card_id=tx.card_id,
        description=tx.description,
        amount=amount,
        category_id=tx.category_id,
        source_transaction_id=tx.id,
        start_month=start_month,
        end_month=end_month,
        active=True,
    )
    db.add(recurring)
    return recurring
