from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from ..database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # pf, pj, itau, mercado_pago, nuinvest
    bank = Column(String(100), nullable=False)  # Nubank, Itaú, Mercado Pago, etc.
    account_number = Column(String(50), nullable=True)

    transactions = relationship("Transaction", back_populates="account")

    def __repr__(self) -> str:
        return f"<Account {self.name} ({self.bank})>"
