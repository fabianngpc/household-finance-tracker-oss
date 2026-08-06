"""Pydantic schemas for the recurring-rules API.

Design rules (mirrors app/schemas/shared_expense.py):
- Money crosses the API as a string (`amount`) so Decimal parsing in the
  service layer stays exact and lossless.
- The wire vocabulary is user-facing (`name`, `starts_on`) while the ORM
  uses its own internal names (`merchant`, `anchor_date`); the router maps
  between them explicitly rather than relying on from_attributes aliasing.
- Split fields mirror SharedExpenseCreate exactly (payer_pct/partner_pct/
  payer_amount/partner_amount) so the same split-input-building logic reads
  naturally for both shared expenses and shared recurring rules.
"""

from datetime import date

from pydantic import BaseModel


class RecurringRuleCreate(BaseModel):
    name: str | None = None  # -> merchant
    amount: str
    currency: str
    category_id: int
    frequency: str  # 'monthly' | 'weekly' | 'monthly_nth'
    day_of_month: int | None = None
    weekday: int | None = None
    starts_on: date  # -> anchor_date
    end_date: date | None = None
    is_shared: bool = False
    split_method: str | None = None
    payer_pct: int | None = None
    partner_pct: int | None = None
    payer_amount: str | None = None
    partner_amount: str | None = None
    partner_category_id: int | None = None


class RecurringRuleUpdate(BaseModel):
    """All fields optional — future-only edit; omitted fields are left
    unchanged on the existing rule."""

    name: str | None = None
    amount: str | None = None
    currency: str | None = None
    category_id: int | None = None
    frequency: str | None = None
    day_of_month: int | None = None
    weekday: int | None = None
    starts_on: date | None = None
    end_date: date | None = None
    is_shared: bool | None = None
    split_method: str | None = None
    payer_pct: int | None = None
    partner_pct: int | None = None
    payer_amount: str | None = None
    partner_amount: str | None = None
    partner_category_id: int | None = None


class RecurringRuleOut(BaseModel):
    id: int
    name: str | None
    amount_minor: int
    currency: str
    category_id: int
    frequency: str
    day_of_month: int | None
    weekday: int | None
    starts_on: date
    end_date: date | None
    paused: bool
    is_shared: bool
    split_method: str | None
    partner_category_id: int | None
    next_run: date | None  # computed: first due date strictly after today

    model_config = {"from_attributes": True}
