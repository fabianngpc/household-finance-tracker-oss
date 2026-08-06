"""Pydantic schemas for shared-expense request/response models.

Design rules (mirrors app/schemas/expense.py):
- Money crosses the API as strings so Decimal parsing in the service layer
  stays exact and lossless.
- percent/exact split inputs are optional fields on the same create schema —
  the router validates presence based on split_method before calling the
  service.
"""

from datetime import date

from pydantic import BaseModel


class SharedExpenseCreate(BaseModel):
    amount: str
    currency: str
    occurred_on: date
    split_method: str
    payer_category_id: int
    partner_category_id: int
    merchant: str | None = None
    payer_pct: int | None = None
    partner_pct: int | None = None
    payer_amount: str | None = None
    partner_amount: str | None = None


class SharedExpenseOut(BaseModel):
    id: int
    payer_user_id: int
    total_amount_minor: int
    original_currency: str
    split_method: str
    occurred_on: date
    payer_expense_id: int
    partner_expense_id: int

    model_config = {"from_attributes": True}


class SharedExpenseDetail(BaseModel):
    """Full detail view used by the web edit panel to pre-populate the form."""

    id: int
    payer_user_id: int
    partner_user_id: int
    total_amount_minor: int
    original_currency: str
    split_method: str
    occurred_on: date
    merchant: str | None
    payer_expense_id: int
    partner_expense_id: int
    payer_share_minor: int
    partner_share_minor: int
    payer_category_id: int
    partner_category_id: int

    model_config = {"from_attributes": True}
