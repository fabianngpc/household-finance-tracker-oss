"""Category CRUD routes — all protected by get_current_user.

Routes registered under /api (main.py mounts this router with prefix="/api").
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.services.categories import (
    create_category,
    delete_category,
    list_categories_with_counts,
    rename_category,
)

router = APIRouter()


@router.get("/categories", response_model=list[CategoryOut])
def get_categories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all categories for the logged-in user, each with its expense count."""
    return list_categories_with_counts(db, user.id)


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category_route(
    body: CategoryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new category for the logged-in user.

    Returns 400 if name is empty.
    """
    try:
        return create_category(db, user.id, body.name, body.color, body.icon)
    except ValueError:
        raise HTTPException(status_code=400, detail="Name is required")


@router.patch("/categories/{id}", response_model=CategoryOut)
def update_category(
    id: int,
    body: CategoryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update name/color/icon for a user-owned category.

    Returns 404 if not found or belongs to another user.
    Returns 400 if trying to rename the protected 'Other' category.
    """
    return rename_category(db, user.id, id, name=body.name, color=body.color, icon=body.icon)


@router.delete("/categories/{id}")
def delete_category_route(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a category, reassigning its expenses to 'Other'.

    Returns 404 if not found or belongs to another user.
    Returns 400 if trying to delete the protected 'Other' category.
    """
    count = delete_category(db, user.id, id)
    return {"ok": True, "reassigned": count}
