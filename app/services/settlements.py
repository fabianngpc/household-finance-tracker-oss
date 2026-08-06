"""
Settlements service: record, void, and list settlement
payments between the two household users.

Design rules:
- Settlements are pure minor-unit amounts in a single currency — no FX
  conversion is ever applied (a settlement clears a debt in the currency it
  was incurred in).
- Voiding is a soft-delete (voided_at timestamp) — never a hard delete — so
  the full ledger (including corrections) stays visible in list_settlements.
- Only the two parties to a settlement (from_user_id or to_user_id) may void
  it; anyone else gets the same 404 as a nonexistent settlement (no leakage
  of existence via a distinct error).
"""

from datetime import date, datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.settlement import Settlement
from app.services.money import CURRENCY_DECIMALS, parse_to_minor_units


def record_settlement(
    db: Session,
    from_user_id: int,
    to_user_id: int,
    amount_str: str,
    currency: str,
    occurred_on: date,
    note: str | None = None,
) -> Settlement:
    """
    Record a settlement payment: from_user_id paid to_user_id amount_str currency.

    Raises:
        ValueError: unsupported currency, or invalid amount (non-numeric,
            zero, negative) via parse_to_minor_units.
    """
    if currency not in CURRENCY_DECIMALS:
        raise ValueError(f"Unsupported currency: {currency!r}")

    amount_minor = parse_to_minor_units(amount_str, currency)

    settlement = Settlement(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        amount_minor=amount_minor,
        currency=currency,
        occurred_on=occurred_on,
        note=note,
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)
    return settlement


def void_settlement(db: Session, requester_id: int, settlement_id: int) -> Settlement:
    """
    Soft-delete (void) a settlement, reopening the balance it had cleared.

    Raises:
        HTTPException(404): settlement doesn't exist, or requester_id is
            neither party to it (from_user_id nor to_user_id).
    """
    from fastapi import HTTPException

    settlement = db.get(Settlement, settlement_id)
    if settlement is None:
        raise HTTPException(status_code=404, detail="Settlement not found")

    if requester_id not in (settlement.from_user_id, settlement.to_user_id):
        raise HTTPException(status_code=404, detail="Settlement not found")

    settlement.voided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(settlement)
    return settlement


def list_settlements(
    db: Session, user_a_id: int, user_b_id: int
) -> list[Settlement]:
    """
    Return the full settlement ledger between two users (either direction),
    newest first. Includes voided rows — callers (UI) strike them through
    rather than hiding them, so corrections stay auditable.
    """
    return (
        db.query(Settlement)
        .filter(
            Settlement.from_user_id.in_([user_a_id, user_b_id]),
            Settlement.to_user_id.in_([user_a_id, user_b_id]),
        )
        .order_by(desc(Settlement.occurred_on), desc(Settlement.id))
        .all()
    )
