from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_institutions_user_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="institutions")
    bank_accounts = relationship("BankAccount", back_populates="institution_ref")
    credit_cards = relationship("CreditCard", back_populates="institution_ref")

    def __repr__(self) -> str:
        return f"<Institution {self.name!r} user={self.user_id}>"
