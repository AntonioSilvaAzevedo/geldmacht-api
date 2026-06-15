from datetime import datetime

from pydantic import BaseModel, Field


class InstitutionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class InstitutionOut(BaseModel):
    id: int
    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    account_count: int = 0
    card_count: int = 0

    model_config = {"from_attributes": True}
