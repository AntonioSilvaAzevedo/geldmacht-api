from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.types import Date
from datetime import datetime
from ..database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id                   = Column(Integer, primary_key=True, index=True)
    user_id              = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date                 = Column(Date,    nullable=False, index=True)
    description          = Column(String(500), nullable=False)
    raw_description      = Column(String(500), nullable=True)   # texto original do extrato
    amount               = Column(Float,   nullable=False)       # negativo = saída
    account_id           = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    card_id              = Column(Integer, ForeignKey("credit_cards.id"), nullable=True, index=True)
    category_id          = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    category             = Column(String(100), nullable=True)
    category_group       = Column(String(50),  nullable=True)    # Entradas, Cartão, Fixos, etc.
    source_file          = Column(String(255), nullable=True)    # nome do arquivo importado
    imported_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_internal_transfer = Column(Boolean, default=False, nullable=False)
    is_payment           = Column(Boolean, default=False, nullable=False)  # pagamento da fatura anterior
    installment_current  = Column(Integer, nullable=True)        # ex: 4 (de "Parcela 4/12")
    installment_total    = Column(Integer, nullable=True)        # ex: 12
    reference_month      = Column(String(7), nullable=True, index=True)  # "YYYY-MM" — legado
    billing_month        = Column(String(7), nullable=True, index=True)  # "YYYY-MM" — legado

    # invoice_id é a âncora principal para transações de fatura (substituindo reference_month)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)

    # Conta bancária cadastrada ( âncora para extratos futuros / lançamentos manuais na conta)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True, index=True)

    # Origem do lançamento: pdf_invoice_import | bank_statement_import | manual
    source = Column(String(32), nullable=True)
    # Tipo econômico (complementar ao amount assinado): income | expense | transfer | payment | adjustment
    transaction_type = Column(String(32), nullable=True)
    notes = Column(String(500), nullable=True)

    # Referência externa (ex.: FITID do OFX) — dedupe básico na importação de extrato
    source_reference = Column(String(255), nullable=True, index=True)
    import_batch_id = Column(
        Integer, ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # SHA256 hex — mesmo user/conta/fonte quando sem FITID
    transaction_fingerprint = Column(String(64), nullable=True, index=True)

    user           = relationship("User",           back_populates="transactions")
    account        = relationship("Account",        back_populates="transactions")
    card           = relationship("CreditCard",     back_populates="transactions")
    category_ref   = relationship("Category",     back_populates="transactions")
    invoice        = relationship("Invoice",        back_populates="transactions")
    bank_account   = relationship("BankAccount",    back_populates="transactions")
    import_batch   = relationship("ImportBatch",    back_populates="transactions")
    tags           = relationship("Tag", secondary="transaction_tags", back_populates="transactions")

    def __repr__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        return f"<Transaction {self.date} {self.description[:30]} {sign}{self.amount:.2f} user={self.user_id}>"
