import calendar
from datetime import date

from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.schemas.summary import FinancialSummary, InvoiceSummary

_MONTH_NAMES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def calculate_invoice_summary(transactions: list[dict]) -> InvoiceSummary:
    """
    Recebe lista de transações da fatura e retorna o resumo calculado.

    Convenção:
    - amount < 0 = gasto
    - amount > 0 = entrada/estorno/crédito

    Importante:
    - ``total_invoice`` é a soma dos valores absolutos apenas das linhas com
      ``amount < 0`` (gastos brutos nos lançamentos parseados).
    - Isso não substitui o valor oficial ``total_amount`` da fatura no PDF
      (“Total a pagar”), que pode líquidar IOF, créditos, encargos e outros
      itens não refletidos de forma explícita em cada lançamento.
    """
    expenses = [t for t in transactions if t["amount"] < 0]
    credits = [t for t in transactions if t["amount"] > 0]
    payments = [
        t for t in credits
        if t.get("is_payment")
    ]
    other_credits = [
        t for t in credits
        if not t.get("is_payment")
    ]

    total_invoice = sum(abs(t["amount"]) for t in expenses)
    total_credits = sum(t["amount"] for t in credits)
    payment_amount = sum(t["amount"] for t in payments)
    payment_description = payments[0]["description"] if payments else ""
    total_other_credits = sum(t["amount"] for t in other_credits)

    largest = min(expenses, key=lambda t: t["amount"], default=None)
    largest_expense = abs(largest["amount"]) if largest else 0.0
    largest_desc = largest["description"] if largest else ""

    installments = [
        t for t in expenses
        if t.get("installment_total") is not None
    ]
    total_installment_value = sum(abs(t["amount"]) for t in installments)

    future_commitment = 0.0
    for t in installments:
        current = t.get("installment_current") or 0
        total = t.get("installment_total") or 0
        remaining = total - current
        if remaining > 0:
            future_commitment += abs(t["amount"]) * remaining

    return InvoiceSummary(
        total_invoice=round(total_invoice, 2),
        total_credits=round(total_credits, 2),
        total_transactions=len(transactions),
        total_expenses=len(expenses),
        total_credits_count=len(credits),
        payment_amount=round(payment_amount, 2),
        payment_description=payment_description,
        total_other_credits=round(total_other_credits, 2),
        total_other_credits_count=len(other_credits),
        largest_expense=round(largest_expense, 2),
        largest_expense_description=largest_desc,
        total_installment_value=round(total_installment_value, 2),
        total_installment_count=len(installments),
        future_commitment=round(future_commitment, 2),
    )


def get_financial_summary(
    db: Session,
    user_id: int,
    today: date | None = None,
    institution_id: int | None = None,
) -> FinancialSummary:
    today = today or date.today()
    year, month = today.year, today.month
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    bank_filters = [
        Transaction.user_id == user_id,
        Transaction.bank_account_id.isnot(None),
        Transaction.is_internal_transfer.is_(False),
        Transaction.status != "ignored_duplicate",
        Transaction.affects_summary.is_(True),
        Transaction.date >= start,
        Transaction.date <= end,
    ]
    installment_filters = [
        Transaction.user_id == user_id,
        Transaction.card_id.isnot(None),
        Transaction.amount < 0,
        Transaction.installment_current.isnot(None),
        Transaction.installment_total.isnot(None),
        Transaction.installment_total > 1,
    ]

    if institution_id is not None:
        account_ids = [
            row[0]
            for row in db.query(BankAccount.id)
            .filter(BankAccount.user_id == user_id, BankAccount.institution_id == institution_id)
            .all()
        ]
        card_ids = [
            row[0]
            for row in db.query(CreditCard.id)
            .filter(CreditCard.user_id == user_id, CreditCard.institution_id == institution_id)
            .all()
        ]
        bank_filters.append(Transaction.bank_account_id.in_(account_ids))
        installment_filters.append(Transaction.card_id.in_(card_ids))

    bank_txs = db.query(Transaction).filter(*bank_filters).all()
    monthly_income = sum(t.amount for t in bank_txs if t.amount > 0)
    monthly_expenses = abs(sum(t.amount for t in bank_txs if t.amount < 0))

    installment_txs = db.query(Transaction).filter(*installment_filters).all()

    groups: dict[tuple, dict] = {}
    for tx in installment_txs:
        key = (tx.card_id, (tx.description or "").strip().lower(), tx.installment_total)
        group = groups.get(key)
        if group is None or tx.installment_current > group["current"]:
            groups[key] = {
                "current": tx.installment_current,
                "total": tx.installment_total,
                "amount": abs(float(tx.amount)),
            }

    active_installments_count = 0
    future_committed_amount = 0.0
    for group in groups.values():
        remaining = group["total"] - group["current"]
        if remaining > 0:
            active_installments_count += 1
            future_committed_amount += group["amount"] * remaining

    return FinancialSummary(
        period_label=f"{_MONTH_NAMES[month]} {year}",
        available_balance=0.0,
        monthly_income=round(float(monthly_income), 2),
        monthly_expenses=round(float(monthly_expenses), 2),
        active_installments_count=active_installments_count,
        future_committed_amount=round(future_committed_amount, 2),
    )
