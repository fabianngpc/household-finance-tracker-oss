"""
Pydantic output schemas for the reporting endpoints.

All monetary values are integer SGD minor units (cents).
Formatting to display strings is done by the frontend, not here.
"""

from typing import Optional

from pydantic import BaseModel


class CategorySlice(BaseModel):
    """Per-category aggregation slice within a report period."""

    name: str
    color: str
    icon: str
    total_sgd_minor: int
    expense_count: int


class MonthlyReport(BaseModel):
    """Aggregated spend for a single calendar month."""

    total_sgd_minor: int
    expense_count: int
    categories: list[CategorySlice]


class MonthRow(BaseModel):
    """One month's entry within a yearly report."""

    month: int
    total_sgd_minor: int
    expense_count: int
    top_category: Optional[str] = None


class YearlyReport(BaseModel):
    """12-month rollup for a full year (only months with expenses included)."""

    total_sgd_minor: int
    months: list[MonthRow]
