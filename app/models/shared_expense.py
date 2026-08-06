from datetime import date, datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SharedExpense(Base):
    """Header row for a shared expense split between the payer and their partner.

    total_amount_minor / original_currency mirror the payer's original amount;
    fx_rate / fx_rate_date capture the historical rate used so linked share
    rows can compute their own amount_base_minor without re-fetching FX.
    """

    __tablename__ = "shared_expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    original_currency: Mapped[str] = mapped_column(nullable=False)
    split_method: Mapped[str] = mapped_column(nullable=False)  # "equal" | "percent" | "exact"
    occurred_on: Mapped[date] = mapped_column(nullable=False)
    fx_rate: Mapped[float] = mapped_column(nullable=False)
    fx_rate_date: Mapped[date] = mapped_column(nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
