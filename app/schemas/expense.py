"""Pydantic schemas for expense request/response models.

Design rules:
- amount is a str so Decimal parsing in the service layer is exact and lossless.
- No bare numeric types on money or rate fields that would lose precision.
- ExpenseOut exposes all integer minor-unit fields so clients can display the
  original currency amount alongside the base SGD conversion.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ExpenseCreate(BaseModel):
    amount: str
    currency: str
    category_id: int
    occurred_on: date
    merchant: str | None = None
    notes: str | None = None


class ExpenseUpdate(BaseModel):
    amount: str | None = None
    currency: str | None = None
    category_id: int | None = None
    occurred_on: date | None = None
    merchant: str | None = None
    notes: str | None = None


class ExpenseOut(BaseModel):
    id: int
    user_id: int
    original_amount_minor: int
    original_currency: str
    amount_base_minor: int
    fx_rate: Decimal
    fx_rate_date: date
    category_id: int
    occurred_on: date
    merchant: str | None
    notes: str | None
    source: str
    shared_expense_id: int | None = None

    model_config = {"from_attributes": True}
