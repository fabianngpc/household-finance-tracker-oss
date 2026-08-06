"""
Settlement + balance API — protected by get_current_user.

Routes registered under /api (main.py mounts this router with prefix="/api").

GET    /balance             -> BalanceOut (derived, from-scratch, per currency)
POST   /settlements          -> 201 SettlementOut
DELETE /settlements/{id}     -> {"ok": True} (soft-delete / void)
GET    /settlements           -> list[SettlementOut] (full ledger, includes voided)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.settlement import (
    BalanceEntry,
    BalanceOut,
    SettlementCreate,
    SettlementOut,
)
from app.services.balance import compute_balance
from app.services.settlements import (
    list_settlements,
    record_settlement,
    void_settlement,
)

router = APIRouter()


def _partner(user: User, db: Session) -> User:
    """Resolve the other seeded user (no hardcoded partner id)."""
    return db.query(User).filter(User.id != user.id).first()


@router.get("/balance", response_model=BalanceOut)
def get_balance(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Derived who-owes-whom balance, recomputed from scratch every read."""
    partner = _partner(user, db)
    bal = compute_balance(db, user.id, partner.id)
    return BalanceOut(
        partner_user_id=partner.id,
        partner_display_name=partner.display_name,
        entries=[
            BalanceEntry(currency=c, net_minor=n) for c, n in sorted(bal.items())
        ],
    )


@router.post("/settlements", response_model=SettlementOut, status_code=201)
def create_settlement(
    body: SettlementCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a settlement payment between the two household users."""
    partner = _partner(user, db)
    valid_ids = {user.id, partner.id}
    if body.from_user_id not in valid_ids or body.to_user_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail="from_user_id and to_user_id must be the current user and partner",
        )

    try:
        return record_settlement(
            db,
            body.from_user_id,
            body.to_user_id,
            body.amount,
            body.currency,
            body.occurred_on,
            body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/settlements/{id}")
def delete_settlement(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Void (soft-delete) a settlement, reopening the balance it had cleared."""
    void_settlement(db, user.id, id)
    return {"ok": True}


@router.get("/settlements", response_model=list[SettlementOut])
def get_settlements(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full settlement ledger between the current user and their partner."""
    partner = _partner(user, db)
    return list_settlements(db, user.id, partner.id)
