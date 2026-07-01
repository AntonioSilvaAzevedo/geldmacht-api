from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .import_batch import ExistingImportBatchInfo
from .summary import InvoiceSummary
from .invoice import InvoiceMetadata, InvoiceCreate
from .tag import TagOut

TRANSACTION_SOURCES = frozenset(
    {"pdf_invoice_import", "ofx_invoice_import", "bank_statement_import", "manual", "system"}
)
TRANSACTION_TYPES = frozenset({"income", "expense", "transfer", "payment", "adjustment"})
IMPORT_KINDS = frozenset({"credit_card_invoice", "bank_statement"})
TRANSACTION_STATUSES = frozenset({"pending", "confirmed", "reconciled", "ignored_duplicate"})


class ManualLaunchEligibility(BaseModel):
    has_account: bool
    has_card: bool
    can_launch: bool


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
    bank_account_id: int | None = None
    source: str | None = None
    transaction_type: str | None = None
    movement_type: str | None = None   # income | expense | internal_transfer | credit_card_payment
    status: str | None = None
    reconciled_with_transaction_id: int | None = None
    affects_summary: bool | None = None
    notes: str | None = None
    source_reference: str | None = None  # FITID / ref. externa (extrato OFX)
    import_batch_id: int | None = None
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
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class InvoiceTransactionsResponse(BaseModel):
    transactions: list[TransactionOut]
    summary: InvoiceSummary


class StatementMetadata(BaseModel):
    """Metadados do extrato bancário (preview OFX — campos opcionais)."""

    institution: str | None = None
    account_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    ledger_balance: float | None = None
    total_inflows: float | None = None
    total_outflows: float | None = None


# ─── Schema retornado pelo endpoint de upload (preview, sem salvar) ────────────
class ParsedTransaction(BaseModel):
    """Transação parseada — retornada como preview antes de salvar no banco."""
    date: date
    description: str
    raw_description: str | None = None
    amount: float
    account: str                      # 'nubank_pf', 'nubank_pj', 'bank_statement_ofx', etc.
    category: str | None = None
    category_id: int | None = None
    category_group: str | None = None
    is_internal_transfer: bool = False
    is_payment: bool = False
    installment_current: int | None = None
    installment_total: int | None = None
    transaction_type: str | None = None  # income | expense (preview extrato OFX)
    source_reference: str | None = None  # FITID quando disponível
    metadata: dict[str, Any] | None = None  # ex.: { "ofx_type", "fitid" }


class UploadResponse(BaseModel):
    parser_used: str
    source_file: str
    total_transactions: int
    transactions: list[ParsedTransaction] = Field(default_factory=list)
    detected_reference_month: str | None = None   # legado — derivado de invoice_metadata.due_month
    invoice_metadata: InvoiceMetadata | None = None
    summary: InvoiceSummary | None = None
    import_kind: Literal["credit_card_invoice", "bank_statement"] | None = None
    statement_metadata: StatementMetadata | None = None
    file_hash: str | None = None
    """SHA256 (hex 64 chars) do conteúdo do arquivo — sempre no ramo extrato quando processado."""

    already_imported: bool = False
    existing_import_batch: ExistingImportBatchInfo | None = None


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
    # Fase 1 — preparação para extrato real (Fase 2). None = comportamento legado inferido pelo parser/card.
    import_kind: Literal["credit_card_invoice", "bank_statement"] | None = None
    bank_account_id: int | None = Field(
        default=None,
        description="Obrigatório quando import_kind=bank_statement — conta bancária ativa do usuário.",
    )
    file_hash: str | None = Field(
        default=None,
        description=(
            "Obrigatório quando import_kind=bank_statement — SHA256(hex) igual ao preview. "
            "Impede replay e duplica arquivo já importado (409)."
        ),
    )
    period_start: date | None = Field(default=None, description="Início do extrato (opcional, metadados OFX).")
    period_end: date | None = Field(default=None, description="Fim do extrato (opcional, metadados OFX).")



class ManualTransactionCreate(BaseModel):
    """Criação de lançamento manual em conta bancária (Fase 1)."""

    transaction_type: Literal["income", "expense"]
    amount: float
    transaction_date: date
    description: str = Field(..., min_length=1, max_length=500)
    bank_account_id: int
    category_id: int | None = None
    notes: str | None = Field(None, max_length=500)
    affects_summary: bool = True

    @model_validator(mode="after")
    def validate_amount_matches_type(self) -> "ManualTransactionCreate":
        if self.transaction_type == "income" and self.amount <= 0:
            raise ValueError("Entrada deve ter valor positivo.")
        if self.transaction_type == "expense" and self.amount >= 0:
            raise ValueError("Saída deve ter valor negativo.")
        return self

class ImportResponse(BaseModel):
    """Resultado da importação: quantas foram salvas e quantas foram ignoradas."""
    imported: int
    skipped: int
    card_id: int | None = None
    invoice_id: int | None = None    # ID da Invoice criada
    due_month: str | None = None     # mês de pagamento da fatura
    reference_month: str | None = None   # legado — igual a due_month
    summary: InvoiceSummary | None = None
    bank_account_id: int | None = None
    transactions: list[TransactionOut] | None = None  # apenas import_kind=bank_statement
    import_batch_id: int | None = None


class TransactionUpdate(BaseModel):
    """Campos editáveis pelo usuário (descrição e/ou categoria)."""
    description: str | None = None
    category: str | None = None
    category_id: int | None = None
