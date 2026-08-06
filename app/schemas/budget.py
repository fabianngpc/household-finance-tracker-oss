"""Pydantic schemas for the budgets API (CRUD + status).

All monetary values cross the API as integer SGD minor units except the
write-path amount (BudgetSetRequest.amount), which is a string so Decimal
parsing in the service layer (parse_to_minor_units) stays exact and lossless.
"""

from pydantic import BaseModel


class BudgetSetRequest(BaseModel):
    amount: str  # SGD, e.g. "2000" or "1999.50"
    category_id: int | None = None  # None = user-total cap


class BudgetBand(BaseModel):
    cap_minor: int
    spent_minor: int
    pct: int
    band: str
    left_minor: int
    over_minor: int


class CategoryBudgetStatus(BaseModel):
    category_id: int
    name: str
    color: str
    icon: str
    cap_minor: int
    spent_minor: int
    pct: int
    band: str


class BudgetStatusOut(BaseModel):
    period: str
    total: BudgetBand | None
    categories: list[CategoryBudgetStatus]


class BudgetCapOut(BaseModel):
    """Raw cap row for form pre-fill (GET /budgets)."""

    category_id: int | None
    amount_minor: int

    model_config = {"from_attributes": True}
