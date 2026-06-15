from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_BANK_ACCOUNT_TYPES = frozenset(
    {"checking", "savings", "payment", "business", "investment", "other"}
)


class BankAccountBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    institution_id: int | None = None
    account_type: str = Field(default="checking", max_length=32)
    currency: str = Field(default="BRL", max_length=8)
    is_active: bool = True

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        if v not in VALID_BANK_ACCOUNT_TYPES:
            raise ValueError("Tipo de conta inválido.")
        return v


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    institution: str | None = Field(None, max_length=120)
    account_type: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=8)
    is_active: bool | None = None

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in VALID_BANK_ACCOUNT_TYPES:
            raise ValueError("Tipo de conta inválido.")
        return v


class BankAccountOut(BankAccountBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
