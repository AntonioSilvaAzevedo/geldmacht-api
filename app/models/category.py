from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class Category(Base):
    __tablename__ = "categories"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name       = Column(String(120), nullable=False)
    scope      = Column(String(50), nullable=False, index=True)
    color      = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user         = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category_ref")

    def __repr__(self) -> str:
        return f"<Category {self.name} ({self.scope}) user={self.user_id}>"
