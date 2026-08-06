"""
Budgets service: standing spending-cap CRUD + budget-vs-actual
compute.

Design rules:
- Budget rows are NOT per-month — "resets on the 1st, no carryover" is
  achieved by comparing the standing cap against monthly_summary's actuals
  for the requested (year, month), never by storing a per-month snapshot.
- The total-cap spend figure is read straight from monthly_summary — it is
  NEVER re-aggregated from Expense.original_amount_minor + a current FX rate
  (that would let historical totals drift as exchange rates move).
- Shared-expense attribution needs NO special-casing here: monthly_summary
  filters Expense.user_id == user_id, and the shared-expense fan-out
  (app/services/shared_expenses.py) already writes one Expense row per
  participant holding only their own share — filtering by owner therefore
  yields exactly that owner's own share, automatically.
"""

import calendar
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.category import Category
from app.models.expense import Expense
from app.services.money import parse_to_minor_units
from app.services.reports import monthly_summary

BASE_CURRENCY = "SGD"


def budget_band(pct: int) -> str:
    """Map a spend percentage to a semantic band. Matches the 05-UI-SPEC
    color bands and the 80/100/120 alert thresholds:
    <80 healthy, 80..99 warning, >=100 over."""
    if pct < 80:
        return "healthy"
    if pct < 100:
        return "warning"
    return "over"


def _find_budget(db: Session, user_id: int, category_id: int | None) -> Budget | None:
    return db.scalar(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category_id.is_(None) if category_id is None else Budget.category_id == category_id,
        )
    )


def upsert_budget(
    db: Session, user_id: int, amount_str: str, category_id: int | None = None
) -> Budget:
    """Create or update the (user, category_id) cap. category_id=None is the
    user-TOTAL cap. Amount parsed as SGD minor units (raises ValueError if
    the amount is non-numeric, zero, or negative)."""
    amount_minor = parse_to_minor_units(amount_str, BASE_CURRENCY)
    row = _find_budget(db, user_id, category_id)
    if row is None:
        row = Budget(user_id=user_id, category_id=category_id, amount_minor=amount_minor)
        db.add(row)
    else:
        row.amount_minor = amount_minor
    db.commit()
    db.refresh(row)
    return row


def delete_budget(db: Session, user_id: int, category_id: int | None = None) -> None:
    """Delete the matching cap (total if category_id is None). No-op if the
    row does not exist."""
    row = _find_budget(db, user_id, category_id)
    if row is not None:
        db.delete(row)
        db.commit()


def get_total_budget(db: Session, user_id: int) -> Budget | None:
    """Return the user's TOTAL cap row (category_id IS NULL), or None."""
    return _find_budget(db, user_id, None)


def list_budgets(db: Session, user_id: int) -> list[Budget]:
    """Return all of a user's cap rows (total + per-category)."""
    return list(db.scalars(select(Budget).where(Budget.user_id == user_id)))


def _category_spend_minor(
    db: Session, user_id: int, category_id: int, start: date, end: date
) -> int:
    """Direct sum of a single category's spend for one user over [start, end]
    inclusive. Kept in this service (does not touch reports.py) since it
    needs to be joined against the caps list, not the monthly_summary
    category-by-name breakdown."""
    total = (
        db.query(func.sum(Expense.amount_base_minor))
        .filter(
            Expense.user_id == user_id,
            Expense.category_id == category_id,
            Expense.occurred_on >= start,
            Expense.occurred_on <= end,
        )
        .scalar()
    )
    return total or 0


def _band_fields(cap_minor: int, spent_minor: int) -> dict:
    pct = (spent_minor * 100 // cap_minor) if cap_minor else 0
    return {
        "pct": pct,
        "band": budget_band(pct),
        "left_minor": max(cap_minor - spent_minor, 0),
        "over_minor": max(spent_minor - cap_minor, 0),
    }


def compute_budget_status(db: Session, user_id: int, year: int, month: int) -> dict:
    """Budget-vs-actual for one calendar month, reusing monthly_summary for
    the total spend figure (never recomputed from original amount + FX).

    Returns:
      { "period": "YYYY-MM",
        "total": None | {"cap_minor","spent_minor","pct","band",
                          "left_minor","over_minor"},
        "categories": [ {"category_id","name","color","icon","cap_minor",
                         "spent_minor","pct","band"}, ... ] }

    Only categories that HAVE a cap are included; spend defaults to 0 if the
    category has no expenses this month.
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    total = None
    total_budget = get_total_budget(db, user_id)
    if total_budget is not None:
        summary = monthly_summary(db, year, month, user_id=user_id)
        spent_minor = summary["total_sgd_minor"]
        cap_minor = total_budget.amount_minor
        total = {
            "cap_minor": cap_minor,
            "spent_minor": spent_minor,
            **_band_fields(cap_minor, spent_minor),
        }

    category_budgets = db.scalars(
        select(Budget).where(Budget.user_id == user_id, Budget.category_id.isnot(None))
    ).all()

    categories = []
    for b in category_budgets:
        cat = db.get(Category, b.category_id)
        spent_minor = _category_spend_minor(db, user_id, b.category_id, start, end)
        cap_minor = b.amount_minor
        categories.append(
            {
                "category_id": b.category_id,
                "name": cat.name if cat else "",
                "color": cat.color if cat else "",
                "icon": cat.icon if cat else "",
                "cap_minor": cap_minor,
                "spent_minor": spent_minor,
                **_band_fields(cap_minor, spent_minor),
            }
        )

    return {
        "period": f"{year:04d}-{month:02d}",
        "total": total,
        "categories": categories,
    }
