"""Pydantic schemas for settlement + balance request/response models.

Design rules (mirrors app/schemas/shared_expense.py):
- Money crosses the API as strings (SettlementCreate.amount) so Decimal
  parsing in the service layer stays exact and lossless.
- from_user_id/to_user_id are both explicit on SettlementCreate — the settle
  dialog derives which is which from the balance sign, so there's no implicit
  "current user always pays" assumption baked into the schema.
"""

from datetime import date, datetime

from pydantic import BaseModel


class SettlementCreate(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: str
    currency: str
    occurred_on: date
    note: str | None = None


class SettlementOut(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount_minor: int
    currency: str
    occurred_on: date
    note: str | None = None
    voided_at: datetime | None = None

    model_config = {"from_attributes": True}


class BalanceEntry(BaseModel):
    currency: str
    net_minor: int


class BalanceOut(BaseModel):
    partner_user_id: int
    partner_display_name: str
    entries: list[BalanceEntry]
