"""
Derived balance service: who-owes-whom, computed from scratch.

Design rules:
- The balance is NEVER stored or mutated — it is recomputed from split rows
  (child Expense rows linked via shared_expense_id) minus active settlements,
  every time it's read.
- Balances are per-currency and independent: settling one currency never
  touches another.
- Sums use Expense.original_amount_minor / Expense.original_currency — NEVER
  the stored SGD-converted column. A debt is denominated in the currency it
  was incurred in; a later FX-rate change must never alter what someone owes
  (Pitfall 7).
- Only active settlements (voided_at IS NULL) reduce the balance; voiding one
  reopens the balance to the exact prior figure.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.models.settlement import Settlement
from app.models.shared_expense import SharedExpense


def compute_balance(db: Session, user_a_id: int, user_b_id: int) -> dict[str, int]:
    """
    Compute the net per-currency balance between two users, from scratch.

    Sign convention: balances[currency] > 0 means user_b owes user_a that many
    minor units of currency; < 0 means user_a owes user_b. A currency is
    omitted entirely when its net is exactly zero (fully settled).
    """
    balances: dict[str, int] = {}

    def _add(rows, sign: int) -> None:
        for currency, total in rows:
            balances[currency] = balances.get(currency, 0) + sign * (total or 0)

    # b's share of expenses a paid for -> b owes a
    rows = (
        db.query(Expense.original_currency, func.sum(Expense.original_amount_minor))
        .join(SharedExpense, Expense.shared_expense_id == SharedExpense.id)
        .filter(
            Expense.user_id == user_b_id,
            SharedExpense.payer_user_id == user_a_id,
        )
        .group_by(Expense.original_currency)
        .all()
    )
    _add(rows, +1)

    # a's share of expenses b paid for -> reduces what b owes a (a owes b)
    rows = (
        db.query(Expense.original_currency, func.sum(Expense.original_amount_minor))
        .join(SharedExpense, Expense.shared_expense_id == SharedExpense.id)
        .filter(
            Expense.user_id == user_a_id,
            SharedExpense.payer_user_id == user_b_id,
        )
        .group_by(Expense.original_currency)
        .all()
    )
    _add(rows, -1)

    # a paid b directly (cash settlement) -> b now owes a that much more,
    # exactly mirroring the expense rule above (value flowed a -> b)
    rows = (
        db.query(Settlement.currency, func.sum(Settlement.amount_minor))
        .filter(
            Settlement.from_user_id == user_a_id,
            Settlement.to_user_id == user_b_id,
            Settlement.voided_at.is_(None),
        )
        .group_by(Settlement.currency)
        .all()
    )
    _add(rows, +1)

    # b paid a directly (cash settlement) -> clears what b owes a
    rows = (
        db.query(Settlement.currency, func.sum(Settlement.amount_minor))
        .filter(
            Settlement.from_user_id == user_b_id,
            Settlement.to_user_id == user_a_id,
            Settlement.voided_at.is_(None),
        )
        .group_by(Settlement.currency)
        .all()
    )
    _add(rows, -1)

    return {c: n for c, n in balances.items() if n != 0}
