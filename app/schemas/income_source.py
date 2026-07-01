from datetime import datetime

from pydantic import BaseModel, Field, field_validator

INCOME_SOURCE_TYPES = frozenset(
    {"clt", "pj", "freelance", "benefit", "reimbursement", "investment_return", "sale", "other"}
)
INCOME_SOURCE_NATURES = frozenset(
    {"cash_income", "restricted_benefit", "reimbursement", "internal_return"}
)
INCOME_SOURCE_FREQUENCIES = frozenset(
    {"monthly", "weekly", "biweekly", "variable", "one_time"}
)


class IncomeSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., max_length=32)
    nature: str = Field(..., max_length=32)
    default_account_id: int | None = None
    expected_amount: float | None = None
    frequency: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=500)
    is_active: bool = True

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in INCOME_SOURCE_TYPES:
            raise ValueError("Tipo de fonte de entrada inválido.")
        return v

    @field_validator("nature")
    @classmethod
    def validate_nature(cls, v: str) -> str:
        if v not in INCOME_SOURCE_NATURES:
            raise ValueError("Natureza de fonte de entrada inválida.")
        return v

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in INCOME_SOURCE_FREQUENCIES:
            raise ValueError("Frequência inválida.")
        return v


class IncomeSourceCreate(IncomeSourceBase):
    pass


class IncomeSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    type: str | None = Field(None, max_length=32)
    nature: str | None = Field(None, max_length=32)
    default_account_id: int | None = None
    expected_amount: float | None = None
    frequency: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in INCOME_SOURCE_TYPES:
            raise ValueError("Tipo de fonte de entrada inválido.")
        return v

    @field_validator("nature")
    @classmethod
    def validate_nature(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in INCOME_SOURCE_NATURES:
            raise ValueError("Natureza de fonte de entrada inválida.")
        return v

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in INCOME_SOURCE_FREQUENCIES:
            raise ValueError("Frequência inválida.")
        return v


class IncomeSourceOut(IncomeSourceBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
