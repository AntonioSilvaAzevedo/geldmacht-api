from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class BankAccount(Base):
    """Conta bancária cadastrada pelo usuário (âncora para extratos e lançamentos manuais na conta)."""

    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    institution = Column(String(120), nullable=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True)
    account_type = Column(String(32), nullable=False, server_default="checking")
    currency = Column(String(8), nullable=False, server_default="BRL")
    is_active = Column(Boolean, nullable=False, server_default="1")
    is_main = Column(Boolean, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="bank_accounts")
    institution_ref = relationship("Institution", back_populates="bank_accounts")
    transactions = relationship("Transaction", back_populates="bank_account")
    import_batches = relationship("ImportBatch", back_populates="bank_account")

    def __repr__(self) -> str:
        return f"<BankAccount {self.name!r} user={self.user_id}>"
