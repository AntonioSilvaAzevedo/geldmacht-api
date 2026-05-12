from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, index=True)
    email            = Column(String(255), unique=True, nullable=False, index=True)
    name             = Column(String(255), nullable=True)
    hashed_password  = Column(String(255), nullable=True)  # nullable: Google OAuth não tem senha
    google_id        = Column(String(255), nullable=True, unique=True)
    is_active        = Column(Boolean, default=True, nullable=False)
    # Onboarding inicial — null = nunca visualizou; preenchido = já marcou como visto.
    onboarding_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    # Dados do usuário — cascade garante limpeza ao deletar o User
    accounts      = relationship("Account",       back_populates="user", cascade="all, delete-orphan")
    bank_accounts = relationship("BankAccount",    back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    credit_cards = relationship("CreditCard",  back_populates="user", cascade="all, delete-orphan")
    categories   = relationship("Category",    back_populates="user", cascade="all, delete-orphan")
    invoices     = relationship("Invoice",     back_populates="user", cascade="all, delete-orphan")
    import_batches = relationship("ImportBatch", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email}>"
