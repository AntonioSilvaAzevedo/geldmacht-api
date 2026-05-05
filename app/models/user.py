from sqlalchemy import Boolean, Column, DateTime, Integer, String
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
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<User {self.email}>"
