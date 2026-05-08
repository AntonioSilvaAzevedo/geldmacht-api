"""
Schemas Pydantic para Invoice (fatura do cartão).

InvoiceMetadata — retornado no POST /api/upload para faturas Nubank.
InvoiceCreate   — enviado pelo frontend no POST /api/import.
InvoiceListItem — retornado pelo GET /api/cards/{id}/invoices.
InvoiceDetail   — retornado pelo GET /api/cards/{id}/invoices/{invoice_id}
                  (sem transactions — use /api/transactions/invoice?invoice_id= para isso).
"""
from datetime import date, datetime
from pydantic import BaseModel

from .summary import InvoiceSummary


class InvoiceMetadata(BaseModel):
    """
    Metadados extraídos do PDF da fatura durante o upload (preview).
    Todos os campos são opcionais — o parser extrai o que o PDF oferecer.
    """
    invoice_label_month: str | None = None   # "abril" (texto do PDF)
    due_date: str | None = None              # "2026-04-13" — vencimento exato
    due_month: str | None = None             # "2026-04" — derivado de due_date
    cycle_start_date: str | None = None      # "2026-03-04" — início do período
    cycle_end_date: str | None = None        # "2026-04-04" — fim do período
    issue_date: str | None = None            # "2026-04-04" — emissão/envio
    closing_date: str | None = None          # "2026-04-04" — fechamento (= cycle_end)
    total_amount: float | None = None        # 12542.08 — "Total a pagar"
    source: str | None = None               # "nubank_pdf"


class InvoiceCreate(BaseModel):
    """
    Payload de fatura enviado pelo frontend ao confirmar importação.
    due_month é obrigatório para importação credit_card.
    """
    due_month: str                           # "2026-04"
    due_date: str | None = None              # "2026-04-13"
    cycle_start_date: str | None = None      # "2026-03-04"
    cycle_end_date: str | None = None        # "2026-04-04"
    issue_date: str | None = None
    closing_date: str | None = None
    total_amount: float | None = None
    source: str | None = None
    raw_reference_month: str | None = None   # campo legado de compatibilidade


class InvoiceListItem(BaseModel):
    """
    Fatura resumida para listagem na página do cartão.
    Inclui totais calculados a partir das transactions vinculadas.
    """
    id: int
    card_id: int
    due_month: str
    due_date: date | None = None
    cycle_start_date: date | None = None
    cycle_end_date: date | None = None
    total_amount: float | None = None    # valor extraído do PDF
    computed_total: float = 0.0          # soma das transactions (amount < 0)
    transactions_count: int = 0
    label: str = ""                      # ex: "Vencimento em Abril/2026"


class InvoiceMini(BaseModel):
    """Versão mínima para uso em respostas agregadas (dashboard)."""
    id: int
    due_month: str
    due_date: date | None = None
    total_amount: float | None = None
    computed_total: float = 0.0


class TopCategoryItem(BaseModel):
    category_id: int | None = None
    name: str
    icon: str | None = None
    total: float


class CardDashboardResponse(BaseModel):
    """
    Resposta agregada de visão geral do cartão.
    GET /api/cards/{card_id}/dashboard
    """
    card_id: int
    invoice_count: int
    latest_invoice: InvoiceMini | None = None
    monthly_average: float = 0.0
    highest_invoice: InvoiceMini | None = None
    future_installments_total: float = 0.0
    invoice_evolution: list[InvoiceMini] = []
    top_categories: list[TopCategoryItem] = []
    recent_invoices: list[InvoiceMini] = []


class InvoiceDetail(BaseModel):
    """
    Fatura completa com transactions e resumo.
    Retornada no GET /api/cards/{card_id}/invoices/{invoice_id}.
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
    summary: InvoiceSummary
