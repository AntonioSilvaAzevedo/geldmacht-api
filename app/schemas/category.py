from datetime import datetime

from pydantic import BaseModel, Field, field_validator


VALID_CATEGORY_SCOPES = {"credit_card"}


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scope: str
    color: str | None = Field(None, max_length=20)

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value not in VALID_CATEGORY_SCOPES:
            raise ValueError("Escopo de categoria inválido.")
        return value


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    scope: str | None = None
    color: str | None = Field(None, max_length=20)

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_CATEGORY_SCOPES:
            raise ValueError("Escopo de categoria inválido.")
        return value


class CategoryOut(CategoryBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
