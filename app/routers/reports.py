"""
Report endpoints: monthly, yearly, and category-breakdown summaries.

All three routes are protected via get_current_user (session cookie).

user param semantics:
  mine    -> current user only
  partner -> the other seeded user's spend
  both    -> combined household (user_id=None in the service layer)
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.report import CategorySlice, MonthlyReport, YearlyReport
from app.services import reports as reports_service

router = APIRouter()


def resolve_user_id(user: User, db: Session, param: str) -> int | None:
    """
    Map the 'user' query parameter to a concrete user_id (or None for both).

    mine    -> current user.id
    both    -> None  (service layer interprets None as all users)
    partner -> the id of the other user (User.id != current user.id)
    """
    if param == "mine":
        return user.id
    if param == "both":
        return None
    if param == "partner":
        partner = db.query(User).filter(User.id != user.id).first()
        return partner.id if partner else None
    # Fallback — default to current user
    return user.id


@router.get("/reports/monthly", response_model=MonthlyReport)
def get_monthly_report(
    year: int = Query(..., description="4-digit year, e.g. 2026"),
    month: int = Query(..., ge=1, le=12, description="Month number 1–12"),
    user: str = Query("mine", description="mine | partner | both"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Monthly aggregated spend: total + per-category breakdown in SGD minor units."""
    user_id = resolve_user_id(current_user, db, user)
    return reports_service.monthly_summary(db, year, month, user_id)


@router.get("/reports/yearly", response_model=YearlyReport)
def get_yearly_report(
    year: int = Query(..., description="4-digit year, e.g. 2026"),
    user: str = Query("mine", description="mine | partner | both"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Yearly rollup: 12-month breakdown with top category per month."""
    user_id = resolve_user_id(current_user, db, user)
    return reports_service.yearly_summary(db, year, user_id)


@router.get("/reports/category", response_model=list[CategorySlice])
def get_category_report(
    start: date = Query(..., description="Inclusive start date, YYYY-MM-DD"),
    end: date = Query(..., description="Inclusive end date, YYYY-MM-DD"),
    user: str = Query("mine", description="mine | partner | both"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-category breakdown for an arbitrary date range."""
    user_id = resolve_user_id(current_user, db, user)
    return reports_service.category_breakdown(db, start, end, user_id)
