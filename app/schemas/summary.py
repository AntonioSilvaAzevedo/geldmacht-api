from pydantic import BaseModel


class InvoiceSummary(BaseModel):
    # Totais gerais
    total_invoice: float
    total_credits: float
    total_transactions: int
    total_expenses: int
    total_credits_count: int

    # Maior gasto
    largest_expense: float
    largest_expense_description: str

    # Parceladas
    total_installment_value: float
    total_installment_count: int
    future_commitment: float
