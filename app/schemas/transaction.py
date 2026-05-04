from datetime import date, datetime
from pydantic import BaseModel


class TransactionBase(BaseModel):
    date: date
    description: str
    raw_description: str | None = None
    amount: float
    category: str | None = None
    category_group: str | None = None
    is_internal_transfer: bool = False
    installment_current: int | None = None
    installment_total: int | None = None


class TransactionCreate(TransactionBase):
    account_id: int | None = None
    source_file: str | None = None


class TransactionOut(TransactionBase):
    id: int
    account_id: int | None = None
    account_type: str | None = None   # 'nubank_pf', 'nubank_cartao', etc.
    source_file: str | None = None
    imported_at: datetime

    model_config = {"from_attributes": True}


# ─── Schema retornado pelo endpoint de upload (preview, sem salvar) ────────────
class ParsedTransaction(BaseModel):
    """Transação parseada — retornada como preview antes de salvar no banco."""
    date: date
    description: str
    raw_description: str | None = None
    amount: float
    account: str                      # 'nubank_pf', 'nubank_pj', etc.
    category: str | None = None
    category_group: str | None = None
    is_internal_transfer: bool = False
    installment_current: int | None = None
    installment_total: int | None = None


class UploadResponse(BaseModel):
    parser_used: str
    source_file: str
    total_transactions: int
    transactions: list[ParsedTransaction]


# ─── Schema para confirmação de importação (Etapa 2.3) ────────────────────────

class ImportRequest(BaseModel):
    """Payload enviado pelo frontend ao confirmar a importação."""
    source_file: str
    parser_used: str
    transactions: list[ParsedTransaction]


class ImportResponse(BaseModel):
    """Resultado da importação: quantas foram salvas e quantas foram ignoradas."""
    imported: int
    skipped: int
