from app.schemas.summary import InvoiceSummary


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
