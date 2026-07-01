from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class IncomeSource(Base):
    __tablename__ = "income_sources"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    type = Column(String(32), nullable=False)
    nature = Column(String(32), nullable=False)
    default_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    expected_amount = Column(Float, nullable=True)
    frequency = Column(String(32), nullable=True)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="income_sources")
    default_account = relationship("BankAccount")
    transactions = relationship("Transaction", back_populates="income_source")

    def __repr__(self) -> str:
        return f"<IncomeSource {self.name!r} user={self.user_id}>"
