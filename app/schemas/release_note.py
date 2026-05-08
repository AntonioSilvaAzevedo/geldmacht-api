"""Schemas Pydantic para release notes."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class MarkSeenResponse(BaseModel):
    success: bool
    seen: bool
