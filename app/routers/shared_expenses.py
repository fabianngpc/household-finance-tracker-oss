"""Shared-expense CRUD routes — protected by get_current_user.

Routes registered under /api (main.py mounts this router with prefix="/api").

POST   /shared-expenses      -> 201 SharedExpenseOut
GET    /shared-expenses/{id} -> 200 SharedExpenseDetail
PATCH  /shared-expenses/{id} -> 200 SharedExpenseOut
DELETE /shared-expenses/{id} -> 200 {"ok": True}
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.expense import Expense
from app.models.shared_expense import SharedExpense
from app.models.user import User
from app.schemas.shared_expense import (
    SharedExpenseCreate,
    SharedExpenseDetail,
    SharedExpenseOut,
)
from app.services.money import parse_to_minor_units
from app.services.shared_expenses import (
    create_shared_expense,
    delete_shared_expense,
    update_shared_expense,
)

router = APIRouter()


def _resolve_partner_id(user: User, db: Session) -> int:
    """Resolve the other seeded user's id (no hardcoded partner id)."""
    partner = db.query(User).filter(User.id != user.id).first()
    return partner.id


def _build_split_input(body: SharedExpenseCreate) -> dict:
    """Build the split_input dict for the service layer from a request body.

    Shared by the POST and PATCH routes so split-input resolution never
    diverges between create and edit.
    """
    if body.split_method == "percent":
        if body.payer_pct is None or body.partner_pct is None:
            raise HTTPException(
                status_code=400,
                detail="payer_pct and partner_pct are required for percent split",
            )
        return {"payer_pct": body.payer_pct, "partner_pct": body.partner_pct}
    elif body.split_method == "exact":
        if body.payer_amount is None or body.partner_amount is None:
            raise HTTPException(
                status_code=400,
                detail="payer_amount and partner_amount are required for exact split",
            )
        try:
            return {
                "payer_minor": parse_to_minor_units(body.payer_amount, body.currency),
                "partner_minor": parse_to_minor_units(
                    body.partner_amount, body.currency
                ),
            }
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        return {}


@router.post("/shared-expenses", response_model=SharedExpenseOut, status_code=201)
def create_shared_expense_route(
    body: SharedExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a shared expense split between the logged-in user (payer) and
    their partner.

    Returns 400 for invalid amounts/currency, unknown split_method, missing
    percent/exact fields, percentages not summing to 100, or exact amounts
    not summing to the total.
    """
    split_input = _build_split_input(body)

    try:
        header, payer_row, partner_row = create_shared_expense(
            db,
            user.id,
            _resolve_partner_id(user, db),
            body.amount,
            body.currency,
            body.occurred_on,
            body.split_method,
            body.payer_category_id,
            body.partner_category_id,
            split_input,
            body.merchant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SharedExpenseOut(
        id=header.id,
        payer_user_id=header.payer_user_id,
        total_amount_minor=header.total_amount_minor,
        original_currency=header.original_currency,
        split_method=header.split_method,
        occurred_on=header.occurred_on,
        payer_expense_id=payer_row.id,
        partner_expense_id=partner_row.id,
    )


@router.get("/shared-expenses/{id}", response_model=SharedExpenseDetail)
def get_shared_expense_route(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return full detail for a shared expense — used by the web edit panel to
    pre-populate the form.

    Returns 404 if the shared expense does not exist, or the requester is
    neither the payer nor the partner.
    """
    header = db.get(SharedExpense, id)
    if header is None:
        raise HTTPException(status_code=404, detail="Shared expense not found")

    children = db.query(Expense).filter(Expense.shared_expense_id == id).all()
    if user.id not in {header.payer_user_id, *[c.user_id for c in children]}:
        raise HTTPException(status_code=404, detail="Shared expense not found")

    payer_row = next(c for c in children if c.user_id == header.payer_user_id)
    partner_row = next(c for c in children if c.user_id != header.payer_user_id)

    return SharedExpenseDetail(
        id=header.id,
        payer_user_id=header.payer_user_id,
        partner_user_id=partner_row.user_id,
        total_amount_minor=header.total_amount_minor,
        original_currency=header.original_currency,
        split_method=header.split_method,
        occurred_on=header.occurred_on,
        merchant=payer_row.merchant,
        payer_expense_id=payer_row.id,
        partner_expense_id=partner_row.id,
        payer_share_minor=payer_row.original_amount_minor,
        partner_share_minor=partner_row.original_amount_minor,
        payer_category_id=payer_row.category_id,
        partner_category_id=partner_row.category_id,
    )


@router.patch("/shared-expenses/{id}", response_model=SharedExpenseOut)
def update_shared_expense_route(
    id: int,
    body: SharedExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Edit a shared expense (full-replace — the split editor always submits the
    whole panel). Only the payer may call this.

    Returns 400 for invalid amounts/currency, unknown split_method, missing
    percent/exact fields, percentages not summing to 100, or exact amounts
    not summing to the total. Returns 403 if the requester is not the payer,
    404 if the shared expense does not exist.
    """
    split_input = _build_split_input(body)

    try:
        header, payer_row, partner_row = update_shared_expense(
            db,
            user.id,
            id,
            amount_str=body.amount,
            currency=body.currency,
            occurred_on=body.occurred_on,
            split_method=body.split_method,
            split_input=split_input,
            payer_category_id=body.payer_category_id,
            partner_category_id=body.partner_category_id,
            merchant=body.merchant,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SharedExpenseOut(
        id=header.id,
        payer_user_id=header.payer_user_id,
        total_amount_minor=header.total_amount_minor,
        original_currency=header.original_currency,
        split_method=header.split_method,
        occurred_on=header.occurred_on,
        payer_expense_id=payer_row.id,
        partner_expense_id=partner_row.id,
    )


@router.delete("/shared-expenses/{id}")
def delete_shared_expense_route(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a shared expense: removes the header AND both linked child Expense
    rows atomically.

    Returns 404 if the shared expense does not exist, or the requester is
    neither the payer nor the partner.
    """
    delete_shared_expense(db, user.id, id)
    return {"ok": True}
