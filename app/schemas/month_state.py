from pydantic import BaseModel


class MonthStateOut(BaseModel):
    has_manual: bool
    has_imported: bool
    manual_after_import: bool
    can_import_statement: bool
    needs_impact_confirmation: bool


class ClearMonthResponse(BaseModel):
    deleted: int
    bank_account_id: int
    month: str
