from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecurringRule(Base):
    """A standing recurring-expense definition (rent, subscriptions, etc.).

    Generation is idempotent catch-up driven by `generate_from` (the watermark)
    up to `end_date`/today — see RecurringOccurrence for the dedup mechanism.
    """

    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # payer for shared rules
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    merchant: Mapped[Optional[str]] = mapped_column(nullable=True)  # user-facing "Name" (Rent, Netflix)
    frequency: Mapped[str] = mapped_column(nullable=False)  # 'monthly' | 'weekly' | 'monthly_nth'
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1..31
    weekday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0=Mon..6=Sun
    anchor_date: Mapped[date] = mapped_column(nullable=False)  # first due date
    generate_from: Mapped[date] = mapped_column(
        nullable=False
    )  # catch-up watermark (= anchor at create; = resume date on unpause)
    end_date: Mapped[Optional[date]] = mapped_column(nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    split_method: Mapped[Optional[str]] = mapped_column(nullable=True)  # equal | percent | exact
    split_input_json: Mapped[Optional[str]] = mapped_column(nullable=True)  # JSON string
    partner_category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())


class RecurringOccurrence(Base):
    """The idempotency key: UNIQUE(rule_id, period_key) guarantees a rule
    never generates a duplicate expense for the same due date, even under concurrent
    or crash-and-retry generation runs.
    """

    __tablename__ = "recurring_occurrences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_rules.id"), nullable=False)
    period_key: Mapped[str] = mapped_column(nullable=False)  # the DUE DATE as ISO 'YYYY-MM-DD'
    expense_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    shared_expense_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shared_expenses.id"), nullable=True)
    generated_at: Mapped[Optional[datetime]] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("rule_id", "period_key", name="uq_recurring_occurrence"),
    )
