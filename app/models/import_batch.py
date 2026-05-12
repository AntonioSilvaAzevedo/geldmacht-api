"""Lote de importação de extrato bancário (rastreabilidade, file_hash)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..database import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_account_id = Column(
        Integer, ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    import_kind = Column(String(32), nullable=False)  # bank_statement (MVP)
    source_type = Column(String(16), nullable=False)  # ofx | csv | pdf | unknown
    file_name = Column(String(512), nullable=False)
    file_hash = Column(String(64), nullable=False, index=True)
    parser_used = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)  # imported | partially_imported | failed
    total_transactions = Column(Integer, nullable=False, default=0)
    imported_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    imported_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bank_account = relationship("BankAccount", back_populates="import_batches")
    user = relationship("User", back_populates="import_batches")
    transactions = relationship("Transaction", back_populates="import_batch")

