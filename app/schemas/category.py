from datetime import datetime

from pydantic import BaseModel, Field, field_validator


VALID_CATEGORY_SCOPES = {"global", "credit_card", "bank"}


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scope: str | None = None
    applies_to_bank: bool = False
    applies_to_credit_card: bool = False
    color: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    card_id: int | None = None
    parent_id: int | None = None
    invoice_budget_limit: float | None = None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_CATEGORY_SCOPES:
            raise ValueError("Escopo de categoria inválido.")
        return value

    @field_validator("invoice_budget_limit")
    @classmethod
    def validate_limit(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("Limite de gasto por fatura deve ser maior que zero.")
        return float(value)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    scope: str | None = None
    applies_to_bank: bool | None = None
    applies_to_credit_card: bool | None = None
    color: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    # Para distinguir "não enviado" de "limpar para null", o frontend
    # deve enviar 0 para limpar card_id e -1 para limpar invoice_budget_limit.
    # Mas para simplificar, usamos sentinelas:
    #   card_id = None        → não altera
    #   card_id = 0           → limpa (todos os cartões)
    #   parent_id = None      → não altera
    #   parent_id = 0         → limpa (vira categoria principal)
    #   invoice_budget_limit = None → não altera
    #   invoice_budget_limit = 0    → remove limite
    card_id: int | None = None
    parent_id: int | None = None
    invoice_budget_limit: float | None = None

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_CATEGORY_SCOPES:
            raise ValueError("Escopo de categoria inválido.")
        return value

    @field_validator("invoice_budget_limit")
    @classmethod
    def validate_limit(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("Limite de gasto por fatura deve ser zero (remover) ou maior.")
        return float(value)


class CategoryOut(CategoryBase):
    id: int
    user_id: int
    system_key: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategorySuggestion(BaseModel):
    key: str
    name: str
    description: str
    icon: str | None = None
