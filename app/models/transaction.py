from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.types import Date
from datetime import datetime
from ..database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    description = Column(String(500), nullable=False)
    raw_description = Column(String(500), nullable=True)  # texto original do extrato
    amount = Column(Float, nullable=False)                 # negativo = saída
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category = Column(String(100), nullable=True)
    category_group = Column(String(50), nullable=True)     # Entradas, Cartão, Fixos, etc.
    source_file = Column(String(255), nullable=True)       # nome do arquivo importado
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_internal_transfer = Column(Boolean, default=False, nullable=False)
    installment_current  = Column(Integer, nullable=True)   # ex: 4 (de "Parcela 4/12")
    installment_total    = Column(Integer, nullable=True)   # ex: 12

    account = relationship("Account", back_populates="transactions")

    def __repr__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        return f"<Transaction {self.date} {self.description[:30]} {sign}{self.amount:.2f}>"
