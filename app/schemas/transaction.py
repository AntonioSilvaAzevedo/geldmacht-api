from datetime import date, datetime
from pydantic import BaseModel

from .summary import InvoiceSummary
from .invoice import InvoiceMetadata, InvoiceCreate


class TransactionBase(BaseModel):
    date: date
    description: str
    raw_description: str | None = None
    amount: float
    category: str | None = None
    category_id: int | None = None
    category_group: str | None = None
    is_internal_transfer: bool = False
    is_payment: bool = False
    installment_current: int | None = None
    installment_total: int | None = None


class TransactionCreate(TransactionBase):
    account_id: int | None = None
    card_id: int | None = None
    source_file: str | None = None


class TransactionOut(TransactionBase):
    id: int
    account_id: int | None = None
    account_type: str | None = None   # 'nubank_pf', 'nubank_cartao', etc.
    card_id: int | None = None
    invoice_id: int | None = None     # âncora principal da fatura
    category_id: int | None = None
    category_name: str | None = None
    # Enriquecimento a partir de Category (+ parent), preenchido pelo serializer
    category_icon: str | None = None
    category_parent_id: int | None = None
    category_parent_name: str | None = None
    category_invoice_budget_limit: float | None = None
    category_display_label: str | None = None
    source_file: str | None = None
    imported_at: datetime
    reference_month: str | None = None   # legado — mantido para compatibilidade
    billing_month: str | None = None     # legado

    model_config = {"from_attributes": True}


class InvoiceTransactionsResponse(BaseModel):
    transactions: list[TransactionOut]
    summary: InvoiceSummary


# ─── Schema retornado pelo endpoint de upload (preview, sem salvar) ────────────
class ParsedTransaction(BaseModel):
    """Transação parseada — retornada como preview antes de salvar no banco."""
    date: date
    description: str
    raw_description: str | None = None
    amount: float
    account: str                      # 'nubank_pf', 'nubank_pj', etc.
    category: str | None = None
    category_id: int | None = None
    category_group: str | None = None
    is_internal_transfer: bool = False
    is_payment: bool = False
    installment_current: int | None = None
    installment_total: int | None = None


class UploadResponse(BaseModel):
    parser_used: str
    source_file: str
    total_transactions: int
    transactions: list[ParsedTransaction]
    detected_reference_month: str | None = None   # legado — derivado de invoice_metadata.due_month
    invoice_metadata: InvoiceMetadata | None = None
    summary: InvoiceSummary | None = None


# ─── Schema para confirmação de importação (Etapa 2.3) ────────────────────────

class InvoiceDetailResponse(BaseModel):
    """
    Resposta completa do GET /api/cards/{id}/invoices/{invoice_id}:
    metadados da fatura + transactions + summary.
    """
    id: int
    card_id: int
    due_month: str
    due_date: date | None = None
    cycle_start_date: date | None = None
    cycle_end_date: date | None = None
    issue_date: date | None = None
    closing_date: date | None = None
    total_amount: float | None = None
    source: str | None = None
    raw_reference_month: str | None = None
    created_at: datetime
    transactions: list[TransactionOut]
    summary: InvoiceSummary


class ImportRequest(BaseModel):
    """Payload enviado pelo frontend ao confirmar a importação."""
    source_file: str
    parser_used: str
    card_id: int | None = None
    reference_month: str | None = None   # legado — usar invoice.due_month quando disponível
    invoice: InvoiceCreate | None = None  # metadados reais da fatura
    transactions: list[ParsedTransaction]


class ImportResponse(BaseModel):
    """Resultado da importação: quantas foram salvas e quantas foram ignoradas."""
    imported: int
    skipped: int
    card_id: int | None = None
    invoice_id: int | None = None    # ID da Invoice criada
    due_month: str | None = None     # mês de pagamento da fatura
    reference_month: str | None = None   # legado — igual a due_month
    summary: InvoiceSummary | None = None


class TransactionUpdate(BaseModel):
    """Campos editáveis pelo usuário (descrição e/ou categoria)."""
    description: str | None = None
    category: str | None = None
    category_id: int | None = None
