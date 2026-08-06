from datetime import date, datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    original_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)  # integer minor units
    original_currency: Mapped[str] = mapped_column(nullable=False)               # ISO 4217
    amount_base_minor: Mapped[int] = mapped_column(Integer, nullable=False)      # SGD cents
    fx_rate: Mapped[float] = mapped_column(nullable=False)                       # rate used
    fx_rate_date: Mapped[date] = mapped_column(nullable=False)                   # actual rate date
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    occurred_on: Mapped[date] = mapped_column(nullable=False)
    merchant: Mapped[Optional[str]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(nullable=False, default="web")
    shared_expense_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("shared_expenses.id"), nullable=True
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
