from pydantic import BaseModel, Field


class RecurringExpenseCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., gt=0)
    category_id: int | None = None
    start_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class RecurringExpenseOut(BaseModel):
    id: int
    card_id: int
    description: str
    amount: float
    category_id: int | None = None
    start_month: str
    active: bool

    model_config = {"from_attributes": True}
