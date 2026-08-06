"""
Budgets API — protected by get_current_user. Operates on the CURRENT user's
own caps only (CRUD + budget-vs-actual status).

Routes registered under /api (main.py mounts this router with prefix="/api").

GET    /budgets/status?year=&month=  -> BudgetStatusOut (defaults to the
                                         current calendar month)
PUT    /budgets                      -> upsert a cap; returns the refreshed
                                         BudgetStatusOut for the current month
DELETE /budgets?category_id=         -> delete a cap (omitted = the total cap)
GET    /budgets                      -> list[BudgetCapOut] (raw caps, for
                                         form pre-fill)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.budget import BudgetCapOut, BudgetSetRequest, BudgetStatusOut
from app.services.budgets import compute_budget_status, delete_budget, list_budgets, upsert_budget

router = APIRouter()


@router.get("/budgets/status", response_model=BudgetStatusOut)
def get_budget_status(
    year: int = Query(None, description="4-digit year, e.g. 2026"),
    month: int = Query(None, ge=1, le=12, description="Month number 1-12"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Budget-vs-actual for one calendar month (defaults to the current month)."""
    today = date.today()
    year = year if year is not None else today.year
    month = month if month is not None else today.month
    return compute_budget_status(db, user.id, year, month)


@router.put("/budgets", response_model=BudgetStatusOut)
def set_budget(
    body: BudgetSetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update the total cap (category_id omitted/None) or a
    per-category cap. Returns the refreshed status for the current month."""
    try:
        upsert_budget(db, user.id, body.amount, category_id=body.category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    today = date.today()
    return compute_budget_status(db, user.id, today.year, today.month)


@router.delete("/budgets")
def remove_budget(
    category_id: int | None = Query(None, description="Omitted = delete the total cap"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a cap (the total cap if category_id is omitted)."""
    delete_budget(db, user.id, category_id=category_id)
    return {"ok": True}


@router.get("/budgets", response_model=list[BudgetCapOut])
def get_budgets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Raw list of the current user's caps, for form pre-fill."""
    return list_budgets(db, user.id)
