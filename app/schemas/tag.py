from pydantic import BaseModel, Field


class TagOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class SetTransactionTagsRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
