from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Category(Base):
    __tablename__ = "categories"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name       = Column(String(120), nullable=False)
    scope      = Column(String(50), nullable=False, index=True)
    system_key = Column(String(50), nullable=True, index=True)
    applies_to_bank        = Column(Boolean, nullable=False, server_default="0")
    applies_to_credit_card = Column(Boolean, nullable=False, server_default="0")
    color      = Column(String(20), nullable=True)
    icon       = Column(String(50), nullable=True)

    # Aplicação por cartão. null = todos os cartões; preenchido = restrito ao cartão.
    card_id              = Column(Integer, ForeignKey("credit_cards.id", ondelete="SET NULL"), nullable=True, index=True)
    # Hierarquia de 1 nível. null = categoria principal; preenchido = subcategoria.
    parent_id            = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True)
    # Limite de gasto por fatura. null = sem limite. Quando informado, > 0.
    invoice_budget_limit = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user         = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category_ref")
    card         = relationship("CreditCard", foreign_keys=[card_id])
    parent       = relationship("Category", remote_side=[id], back_populates="subcategories")
    subcategories = relationship(
        "Category",
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,
    )

    def __repr__(self) -> str:
        return f"<Category {self.name} ({self.scope}) user={self.user_id} card={self.card_id} parent={self.parent_id}>"
