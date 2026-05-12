"""Schemas para lotes de importação de extrato (Fase 2.1)."""

from datetime import date, datetime

from pydantic import BaseModel


class ExistingImportBatchInfo(BaseModel):
    """Preview quando arquivo já existe para a mesma conta (mesmo SHA256)."""

    id: int
    file_name: str
    imported_at: datetime | None = None
    imported_count: int
    skipped_count: int


class ImportBatchOut(BaseModel):
    id: int
    file_name: str
    file_hash: str
    parser_used: str
    status: str
    total_transactions: int
    imported_count: int
    skipped_count: int
    period_start: date | None = None
    period_end: date | None = None
    imported_at: datetime | None = None

    model_config = {"from_attributes": True}
