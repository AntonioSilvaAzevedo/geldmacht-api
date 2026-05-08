"""Schemas Pydantic para release notes."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReleaseNoteOut(BaseModel):
    """Saída pública de uma release note. `items` já vem desserializado."""
    id: int
    version: str
    title: str
    description: str | None
    items: list[str]
    show_modal: bool
    released_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=False)


class PendingReleaseNotesResponse(BaseModel):
    """Lista de release notes pendentes para o usuário (acumulativo).

    Ordenadas da mais antiga para a mais recente, para que o frontend possa
    apresentar na ordem cronológica de quando foram lançadas.
    """
    releases: list[ReleaseNoteOut]


class MarkSeenRequest(BaseModel):
    """Marca múltiplas release notes como vistas pelo usuário."""
    release_note_ids: list[int] = Field(default_factory=list)


class MarkSeenResponse(BaseModel):
    success: bool
    seen: bool = True
    marked_as_seen: list[int] = Field(default_factory=list)
