"""
Reporting aggregation layer: monthly, yearly, and category-breakdown summaries.

Design rules:
- ALL sums use func.sum(Expense.amount_base_minor) — the stored SGD minor units.
- NEVER recompute from the original captured amount + a current exchange rate.
- Historical totals are immutable: whatever was stored at capture time is what
  the report reflects, regardless of any FX movement since.
- user_id=None means the combined household view (both users).
"""

import calendar
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.expense import Expense


def _category_query(db: Session, start: date, end: date, user_id: int | None):
    """
    Shared per-category aggregation query for [start, end] inclusive.

    Returns a SQLAlchemy query (not yet executed) that yields rows of:
        (name, color, icon, total_sgd_minor, expense_count)
    grouped by Category.id, ordered by total_sgd_minor descending.
    """
    q = (
        db.query(
            Category.name,
            Category.color,
            Category.icon,
            func.sum(Expense.amount_base_minor).label("total_sgd_minor"),
            func.count(Expense.id).label("expense_count"),
        )
        .join(Category, Expense.category_id == Category.id)
        .filter(Expense.occurred_on >= start, Expense.occurred_on <= end)
    )
    if user_id is not None:
        q = q.filter(Expense.user_id == user_id)
    return q.group_by(Category.id).order_by(
        func.sum(Expense.amount_base_minor).desc()
    )


def monthly_summary(
    db: Session,
    year: int,
    month: int,
    user_id: int | None = None,
) -> dict:
    """
    Return aggregated spend for a single calendar month.

    Returns:
        {
            total_sgd_minor: int,
            expense_count: int,
            categories: [{name, color, icon, total_sgd_minor, expense_count}, ...]
        }
    user_id=None returns combined household spend.
    """
    _, days_in_month = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    # Per-category breakdown
    categories = [
        {
            "name": row.name,
            "color": row.color,
            "icon": row.icon,
            "total_sgd_minor": row.total_sgd_minor,
            "expense_count": row.expense_count,
        }
        for row in _category_query(db, start, end, user_id).all()
    ]

    # Overall month total
    total_q = db.query(
        func.sum(Expense.amount_base_minor).label("total"),
        func.count(Expense.id).label("count"),
    ).filter(Expense.occurred_on >= start, Expense.occurred_on <= end)
    if user_id is not None:
        total_q = total_q.filter(Expense.user_id == user_id)
    totals = total_q.first()

    return {
        "total_sgd_minor": totals.total or 0,
        "expense_count": totals.count or 0,
        "categories": categories,
    }


def yearly_summary(
    db: Session,
    year: int,
    user_id: int | None = None,
) -> dict:
    """
    Return the 12-month rollup for a full year.

    Returns:
        {
            total_sgd_minor: int,
            months: [{month, total_sgd_minor, expense_count, top_category}, ...]
        }
    Only months that have at least one expense are included in `months`.
    user_id=None returns combined household spend.
    """
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    month_col = func.strftime("%m", Expense.occurred_on)

    # Aggregate by month
    month_q = (
        db.query(
            month_col.label("month_str"),
            func.sum(Expense.amount_base_minor).label("total_sgd_minor"),
            func.count(Expense.id).label("expense_count"),
        )
        .filter(Expense.occurred_on >= start, Expense.occurred_on <= end)
    )
    if user_id is not None:
        month_q = month_q.filter(Expense.user_id == user_id)
    month_q = month_q.group_by(month_col).order_by(month_col)

    month_rows: dict[int, dict] = {}
    for row in month_q.all():
        m = int(row.month_str)
        month_rows[m] = {
            "month": m,
            "total_sgd_minor": row.total_sgd_minor,
            "expense_count": row.expense_count,
            "top_category": None,
        }

    # Top category per month (secondary query — simple and correct)
    for m, row_data in month_rows.items():
        _, days_in_month = calendar.monthrange(year, m)
        m_start = date(year, m, 1)
        m_end = date(year, m, days_in_month)
        top_q = (
            db.query(
                Category.name,
                func.sum(Expense.amount_base_minor).label("cat_total"),
            )
            .join(Category, Expense.category_id == Category.id)
            .filter(Expense.occurred_on >= m_start, Expense.occurred_on <= m_end)
        )
        if user_id is not None:
            top_q = top_q.filter(Expense.user_id == user_id)
        top_q = (
            top_q.group_by(Category.id)
            .order_by(func.sum(Expense.amount_base_minor).desc())
            .limit(1)
        )
        top = top_q.first()
        if top:
            row_data["top_category"] = top.name

    # Overall year total
    year_total_q = db.query(func.sum(Expense.amount_base_minor)).filter(
        Expense.occurred_on >= start, Expense.occurred_on <= end
    )
    if user_id is not None:
        year_total_q = year_total_q.filter(Expense.user_id == user_id)
    year_total = year_total_q.scalar() or 0

    months = sorted(month_rows.values(), key=lambda r: r["month"])

    return {
        "total_sgd_minor": year_total,
        "months": months,
    }


def category_breakdown(
    db: Session,
    start: date,
    end: date,
    user_id: int | None = None,
) -> list[dict]:
    """
    Per-category aggregation for an arbitrary [start, end] date range.

    Returns:
        [{name, color, icon, total_sgd_minor, expense_count}, ...]
    Ordered by total_sgd_minor descending.
    user_id=None returns combined household spend.
    """
    return [
        {
            "name": row.name,
            "color": row.color,
            "icon": row.icon,
            "total_sgd_minor": row.total_sgd_minor,
            "expense_count": row.expense_count,
        }
        for row in _category_query(db, start, end, user_id).all()
    ]
