from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from ..database import Base


class Account(Base):
    __tablename__ = "accounts"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name           = Column(String(100), nullable=False)
    type           = Column(String(50),  nullable=False)   # nubank_pf, itau, etc.
    bank           = Column(String(100), nullable=False)   # Nubank, Itaú, Mercado Pago, etc.
    account_number = Column(String(50),  nullable=True)

    user         = relationship("User",        back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")

    def __repr__(self) -> str:
        return f"<Account {self.name} ({self.bank}) user={self.user_id}>"
