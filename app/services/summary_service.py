from app.schemas.summary import InvoiceSummary


def calculate_invoice_summary(transactions: list[dict]) -> InvoiceSummary:
    """
    Recebe lista de transações da fatura e retorna o resumo calculado.

    Convenção:
    - amount < 0 = gasto
    - amount > 0 = entrada/estorno/crédito
    """
    expenses = [t for t in transactions if t["amount"] < 0]
    credits = [t for t in transactions if t["amount"] > 0]

    total_invoice = sum(abs(t["amount"]) for t in expenses)
    total_credits = sum(t["amount"] for t in credits)

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
        largest_expense=round(largest_expense, 2),
        largest_expense_description=largest_desc,
        total_installment_value=round(total_installment_value, 2),
        total_installment_count=len(installments),
        future_commitment=round(future_commitment, 2),
    )
