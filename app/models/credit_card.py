from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class CreditCard(Base):
    __tablename__ = "credit_cards"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name        = Column(String(120), nullable=False)
    institution = Column(String(120), nullable=True)
    closing_day = Column(Integer, nullable=False)
    due_day     = Column(Integer, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user         = relationship("User", back_populates="credit_cards")
    transactions = relationship("Transaction", back_populates="card")
    invoices     = relationship("Invoice", back_populates="card", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<CreditCard {self.name} user={self.user_id}>"
