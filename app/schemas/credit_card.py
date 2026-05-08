from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CreditCardBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    closing_day: int = Field(..., ge=1, le=31)
    due_day: int = Field(..., ge=1, le=31)
    # Limite informado pelo usuário. Nullable; quando preenchido, deve ser > 0.
    credit_limit: float | None = None

    @field_validator("credit_limit")
    @classmethod
    def validate_limit(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("Limite do cartão deve ser maior que zero.")
        return float(value)


class CreditCardCreate(CreditCardBase):
    pass


class CreditCardUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    closing_day: int | None = Field(None, ge=1, le=31)
    due_day: int | None = Field(None, ge=1, le=31)
    # Sentinelas no PATCH:
    #   None = não altera
    #   0    = remove o limite (vira null)
    #   >0   = define o novo limite
    credit_limit: float | None = None

    @field_validator("credit_limit")
    @classmethod
    def validate_limit(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("Limite do cartão deve ser zero (remover) ou maior.")
        return float(value)


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
