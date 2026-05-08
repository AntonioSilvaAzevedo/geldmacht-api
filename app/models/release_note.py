"""
Release notes / notas de atualização por versão.

ReleaseNote: nota de uma versão. `version` é única.
UserReleaseNoteView: registro de "usuário X já viu versão Y" — garante
exibição única do modal por usuário/versão (constraint composta).
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class ReleaseNote(Base):
    __tablename__ = "release_notes"

    id          = Column(Integer, primary_key=True, index=True)
    version     = Column(String(40), nullable=False, unique=True, index=True)
    title       = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    # Lista de tópicos serializada como JSON string. SQLite-friendly.
    items_json  = Column(Text, nullable=False, default="[]")
    show_modal  = Column(Boolean, nullable=False, default=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    views = relationship("UserReleaseNoteView", back_populates="release_note", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ReleaseNote v{self.version} show_modal={self.show_modal}>"


class UserReleaseNoteView(Base):
    __tablename__ = "user_release_note_views"
    __table_args__ = (
        UniqueConstraint("user_id", "release_note_id", name="uq_user_release_view"),
    )

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    release_note_id = Column(Integer, ForeignKey("release_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    version         = Column(String(40), nullable=False)
    seen_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    release_note = relationship("ReleaseNote", back_populates="views")

    def __repr__(self) -> str:
        return f"<UserReleaseNoteView user={self.user_id} v{self.version}>"
