"""
Expense write-path service: the canonical entry point for all capture surfaces.

Every path that creates or mutates expenses (web routes, the Telegram bot,
and the recurring scheduler) must call these functions rather than
duplicate the money/FX logic in route handlers.

Design rules:
- All amounts stored as integer minor units — never float.
- original_amount_minor + original_currency always preserved on every row.
- Base SGD amount (amount_base_minor) computed at write time from the
  user-supplied calendar date; NEVER from the system clock.
- update_expense re-fetches FX only when amount_str, currency, or occurred_on
  actually change; metadata-only edits (merchant, notes, category) are free.
"""

from datetime import date, datetime, timezone

from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models.capture import Capture
from app.models.expense import Expense
from app.services.fx import compute_base_amount_minor, get_rate_for_date
from app.services.money import CURRENCY_DECIMALS, parse_to_minor_units


def create_expense_from_data(
    db: Session,
    user_id: int,
    amount_str: str,
    currency: str,
    category_id: int,
    expense_date: date,
    merchant: str | None = None,
    notes: str | None = None,
    source: str = "web",
) -> Expense:
    """
    Parse, convert, and persist a new expense row.

    Uses the user-supplied expense_date calendar date for FX — never the
    system clock — so timezone drift (Pitfall 4) cannot corrupt the rate.

    Raises:
        ValueError: if amount is invalid (non-numeric, zero, negative) or
                    currency is not in the supported set (SGD/USD/MYR/EUR/JPY).
    """
    # Wrap KeyError from unknown currency as a clean ValueError
    if currency not in CURRENCY_DECIMALS:
        raise ValueError(f"Unsupported currency: {currency!r}")

    original_minor = parse_to_minor_units(amount_str, currency)
    rate, rate_date = get_rate_for_date(expense_date, currency, db)
    base_minor = compute_base_amount_minor(original_minor, currency, rate)

    expense = Expense(
        user_id=user_id,
        original_amount_minor=original_minor,
        original_currency=currency,
        amount_base_minor=base_minor,
        fx_rate=rate,
        fx_rate_date=rate_date,
        category_id=category_id,
        occurred_on=expense_date,
        merchant=merchant,
        notes=notes,
        source=source,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)

    from app.services.budget_alerts import check_budget_alerts

    check_budget_alerts(db, user_id, expense_date)

    return expense


def update_expense(
    db: Session,
    user_id: int,
    expense_id: int,
    **fields,
) -> Expense:
    """
    Apply field updates to an expense owned by user_id.

    Money recomputation rule: base SGD amount is re-derived from Frankfurter
    only when at least one of {amount_str, currency, occurred_on} changes.
    Editing only merchant/notes/category_id never triggers a network call.

    Raises:
        HTTPException(404): propagated up from a missing-or-not-owned load.
        ValueError: if new amount is invalid or currency unsupported.
    """
    from fastapi import HTTPException

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.user_id == user_id)
        .first()
    )
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    # Detect whether any money-affecting field is being changed
    new_amount_str: str | None = fields.pop("amount_str", None)
    new_currency: str | None = fields.pop("currency", None)
    new_occurred_on: date | None = fields.pop("occurred_on", None)

    money_changed = (
        new_amount_str is not None
        or new_currency is not None
        or new_occurred_on is not None
    )

    # Money-lock: a linked shared-expense child row's amount/currency/date can
    # ONLY be changed via update_shared_expense (keeps both children + the
    # header in sync). This is unconditional — applies to the payer too, not
    # just the partner — so the generic PATCH can never desync the split.
    if expense.shared_expense_id is not None and money_changed:
        raise HTTPException(
            status_code=403,
            detail="Only the payer can change the amount. You can recategorize your share.",
        )

    # Resolve effective values (fall back to current row values)
    eff_currency = new_currency if new_currency is not None else expense.original_currency
    eff_occurred_on = new_occurred_on if new_occurred_on is not None else expense.occurred_on

    if money_changed:
        if eff_currency not in CURRENCY_DECIMALS:
            raise ValueError(f"Unsupported currency: {eff_currency!r}")

        # Use new amount_str if provided; otherwise re-use original minor units
        if new_amount_str is not None:
            original_minor = parse_to_minor_units(new_amount_str, eff_currency)
        else:
            original_minor = expense.original_amount_minor

        rate, rate_date = get_rate_for_date(eff_occurred_on, eff_currency, db)
        base_minor = compute_base_amount_minor(original_minor, eff_currency, rate)

        expense.original_amount_minor = original_minor
        expense.original_currency = eff_currency
        expense.amount_base_minor = base_minor
        expense.fx_rate = rate
        expense.fx_rate_date = rate_date
        expense.occurred_on = eff_occurred_on

    # Apply remaining metadata-only fields (category_id, merchant, notes)
    for field, value in fields.items():
        if hasattr(expense, field):
            setattr(expense, field, value)

    expense.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(expense)

    if money_changed:
        # An edit can push spend over a threshold (e.g. amount bump or a date
        # change into the current month) — re-check after the commit.
        from app.services.budget_alerts import check_budget_alerts

        check_budget_alerts(db, expense.user_id, expense.occurred_on)

    return expense


def delete_expense(db: Session, user_id: int, expense_id: int) -> None:
    """
    Delete an expense owned by user_id.

    Raises:
        HTTPException(404): if the expense does not exist or belongs to another user.
    """
    from fastapi import HTTPException

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.user_id == user_id)
        .first()
    )
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    if expense.shared_expense_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This is part of a shared expense — delete it from the shared expense instead.",
        )

    # Detach any Telegram captures that reference this expense before
    # deleting it. captures.expense_id -> expenses.id has no ON DELETE
    # action, so SQLite's FK enforcement (foreign_keys=ON) would otherwise
    # reject the delete with an IntegrityError. The capture row itself is
    # an audit/idempotency log and must survive — only the link is cleared.
    (
        db.query(Capture)
        .filter(Capture.expense_id == expense_id)
        .update({"expense_id": None})
    )

    db.delete(expense)
    db.commit()


def list_expenses(
    db: Session,
    user_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> list[Expense]:
    """
    Return expenses, optionally filtered by owner and/or date range.

    user_id=None means all users (household "both" view).
    Results ordered by occurred_on descending, then id descending
    (most recent first; stable tie-break for same-day expenses).
    """
    q = db.query(Expense)

    if user_id is not None:
        q = q.filter(Expense.user_id == user_id)
    if start is not None:
        q = q.filter(Expense.occurred_on >= start)
    if end is not None:
        q = q.filter(Expense.occurred_on <= end)

    q = q.order_by(desc(Expense.occurred_on), desc(Expense.id))

    if limit is not None:
        q = q.limit(limit)

    return q.all()
