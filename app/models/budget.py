from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Budget(Base):
    """A standing spending cap: one row per (user, category) plus one TOTAL row per user.

    NOT a per-month row — "reset on the 1st, no carryover" is achieved by comparing
    this standing cap against that month's actuals (see app/services/reports.py).
    category_id NULL means the user-TOTAL cap.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )  # NULL = the user-TOTAL cap
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)  # SGD minor units
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())

    __table_args__ = (
        # SQLite treats NULLs as DISTINCT in UNIQUE, so a plain UNIQUE(user_id, category_id)
        # would allow two "total" rows per user. Two partial unique indexes fix this.
        Index(
            "ux_budget_total",
            "user_id",
            unique=True,
            sqlite_where=text("category_id IS NULL"),
        ),
        Index(
            "ux_budget_category",
            "user_id",
            "category_id",
            unique=True,
            sqlite_where=text("category_id IS NOT NULL"),
        ),
    )


class BudgetAlertSent(Base):
    """The dedup mechanism: the UNIQUE constraint (not application logic)
    guarantees an alert for a given (user, period, threshold) is ever sent once.
    """

    __tablename__ = "budget_alerts_sent"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    period: Mapped[str] = mapped_column(nullable=False)  # 'YYYY-MM'
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)  # 80 | 100 | 120
    sent_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "period", "threshold", name="uq_budget_alert"),
    )
