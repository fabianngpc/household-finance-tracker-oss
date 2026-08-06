"""Expense CRUD routes — all protected by get_current_user.

Routes registered under /api (main.py mounts this router with prefix="/api").

GET    /expenses?user=mine|both&start=&end=  -> 200 list[ExpenseOut]
POST   /expenses                             -> 201 ExpenseOut
PATCH  /expenses/{id}                        -> 200 ExpenseOut
DELETE /expenses/{id}                        -> 200 {"ok": True}
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseUpdate
from app.services.expenses import (
    create_expense_from_data,
    delete_expense,
    list_expenses,
    update_expense,
)

router = APIRouter()


@router.get("/expenses", response_model=list[ExpenseOut])
def get_expenses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    user_filter: str = Query(default="mine", alias="user"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    """
    Return expenses for the logged-in user (default) or the whole household.

    ?user=mine  — only the logged-in user's expenses (default)
    ?user=both  — all users' expenses combined (household view)
    ?start=YYYY-MM-DD  — filter to expenses on or after this date
    ?end=YYYY-MM-DD    — filter to expenses on or before this date
    """
    uid = user.id if user_filter != "both" else None
    return list_expenses(db, user_id=uid, start=start, end=end)


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense_route(
    body: ExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new expense for the logged-in user.

    Returns 400 for invalid amounts (zero, negative, non-numeric) or
    unsupported currency codes.
    """
    try:
        return create_expense_from_data(
            db,
            user.id,
            body.amount,
            body.currency,
            body.category_id,
            body.occurred_on,
            body.merchant,
            body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/expenses/{id}", response_model=ExpenseOut)
def update_expense_route(
    id: int,
    body: ExpenseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update one or more fields of a user-owned expense.

    Base SGD amount is only recomputed when amount, currency, or occurred_on
    changes — metadata-only patches are cheap.

    Returns 404 if the expense does not exist or belongs to another user.
    Returns 400 for invalid amount or unsupported currency.
    """
    updates = body.model_dump(exclude_unset=True)

    # Rename 'amount' -> 'amount_str' so the service function signature matches
    if "amount" in updates:
        updates["amount_str"] = updates.pop("amount")

    try:
        return update_expense(db, user.id, id, **updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/expenses/{id}")
def delete_expense_route(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a user-owned expense.

    Returns 404 if the expense does not exist or belongs to another user.
    """
    delete_expense(db, user.id, id)
    return {"ok": True}
