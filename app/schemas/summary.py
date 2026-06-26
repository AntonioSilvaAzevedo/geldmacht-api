from pydantic import BaseModel


class InvoiceSummary(BaseModel):
    # Totais gerais
    total_invoice: float
    total_credits: float
    total_transactions: int
    total_expenses: int
    total_credits_count: int

    # Pagamento da fatura anterior
    payment_amount: float
    payment_description: str

    # Estornos e reembolsos, sem pagamento da fatura
    total_other_credits: float
    total_other_credits_count: int

    # Maior gasto
    largest_expense: float
    largest_expense_description: str

    # Parceladas
    total_installment_value: float
    total_installment_count: int
    future_commitment: float


class FinancialSummary(BaseModel):
    period_label: str
    available_balance: float
    monthly_income: float
    monthly_expenses: float
    active_installments_count: int
    future_committed_amount: float
