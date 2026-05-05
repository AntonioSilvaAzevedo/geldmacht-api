from datetime import datetime

from pydantic import BaseModel, Field


class CreditCardBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    closing_day: int = Field(..., ge=1, le=31)
    due_day: int = Field(..., ge=1, le=31)


class CreditCardCreate(CreditCardBase):
    pass


class CreditCardUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    closing_day: int | None = Field(None, ge=1, le=31)
    due_day: int | None = Field(None, ge=1, le=31)


class CreditCardOut(CreditCardBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CardInvoiceMonth(BaseModel):
    reference_month: str
    label: str
    total: float
    transactions_count: int
