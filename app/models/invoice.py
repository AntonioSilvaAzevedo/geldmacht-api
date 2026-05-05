from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.types import Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Invoice(Base):
    """
    Entidade real de fatura do cartão de crédito.

    Representa um ciclo de cobrança com vencimento, período vigente e
    vínculo com o cartão. Serve como âncora para as transações importadas —
    toda transaction de cartão deve referenciar um invoice_id.

    Campos de data são opcionais para compatibilidade com dados legados
    importados antes da criação desta entidade (onde só havia reference_month).
    """
    __tablename__ = "invoices"

    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    card_id          = Column(Integer, ForeignKey("credit_cards.id", ondelete="CASCADE"), nullable=False, index=True)

    # Mês de vencimento/pagamento da fatura — "YYYY-MM" (ex: "2026-04")
    due_month        = Column(String(7), nullable=False, index=True)

    # Data exata de vencimento (ex: 2026-04-13); null para dados legados
    due_date         = Column(Date, nullable=True)

    # Início do período vigente (ex: 2026-03-04); null para dados legados
    cycle_start_date = Column(Date, nullable=True)

    # Fim do período vigente (ex: 2026-04-04); null para dados legados
    cycle_end_date   = Column(Date, nullable=True)

    # Data de emissão/envio da fatura; null para dados legados
    issue_date       = Column(Date, nullable=True)

    # Data de fechamento da fatura; geralmente = cycle_end_date
    closing_date     = Column(Date, nullable=True)

    # Valor total extraído do PDF ("Total a pagar"); null para dados legados
    total_amount     = Column(Float, nullable=True)

    # Origem da fatura (ex: "nubank_pdf", "legacy")
    source           = Column(String(50), nullable=True, default="legacy")

    # Campo legado/compatibilidade: reference_month original da importação
    raw_reference_month = Column(String(7), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user         = relationship("User", back_populates="invoices")
    card         = relationship("CreditCard", back_populates="invoices")
    transactions = relationship("Transaction", back_populates="invoice")

    def __repr__(self) -> str:
        return f"<Invoice {self.due_month} card={self.card_id} user={self.user_id}>"
