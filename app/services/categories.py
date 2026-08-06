"""Category service — per-user CRUD with 'Other' protection and delete-reassign."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.expense import Expense


# ---------------------------------------------------------------------------
# Category resolvers (used by capture service and phase 3 gating)
# ---------------------------------------------------------------------------


def resolve_other_category_id(db: Session, user_id: int) -> int:
    """Return the id of the protected 'Other' category for user_id.

    Raises:
        ValueError: if the category is absent (seed data missing).
    """
    cat = (
        db.query(Category)
        .filter_by(user_id=user_id, name="Other", is_protected=1)
        .first()
    )
    if cat is None:
        raise ValueError(f"No 'Other' category for user {user_id}")
    return cat.id


def resolve_category_for_hint(db: Session, user_id: int, hint: str | None) -> int:
    """Map an AI category hint onto the user's own categories.

    - Case-insensitive match against the given user's category names.
    - Falls back to the protected 'Other' category for unknown, empty, or None hints.
    - Scoped to user_id — never returns another user's category id.

    Args:
        db: SQLAlchemy session.
        user_id: The user whose categories are searched.
        hint: Free-text category name from the AI extractor (may be None).

    Returns:
        The matched category's id, or the user's 'Other' category id as fallback.
    """
    if hint:
        cat = (
            db.query(Category)
            .filter(
                Category.user_id == user_id,
                func.lower(Category.name) == hint.lower(),
            )
            .first()
        )
        if cat is not None:
            return cat.id
    return resolve_other_category_id(db, user_id)


def list_categories_with_counts(db: Session, user_id: int) -> list:
    """Return all categories for the user, each with an `expense_count` attribute.

    Uses an outer-join so categories with zero expenses appear with count 0.
    Ordered by created_at (preserves seed order) then name.
    """
    rows = (
        db.query(Category, func.count(Expense.id).label("expense_count"))
        .outerjoin(Expense, Expense.category_id == Category.id)
        .filter(Category.user_id == user_id)
        .group_by(Category.id)
        .order_by(Category.created_at, Category.name)
        .all()
    )
    result = []
    for cat, count in rows:
        cat.expense_count = count
        result.append(cat)
    return result


def create_category(
    db: Session, user_id: int, name: str, color: str, icon: str
) -> Category:
    """Insert a new category for the user.

    Raises ValueError if `name` is empty or blank.
    Returns the new Category with `expense_count` set to 0.
    """
    if not name or not name.strip():
        raise ValueError("Name is required")
    cat = Category(
        user_id=user_id,
        name=name.strip(),
        color=color,
        icon=icon,
        is_protected=0,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    cat.expense_count = 0
    return cat


def rename_category(
    db: Session,
    user_id: int,
    category_id: int,
    name: str | None = None,
    color: str | None = None,
    icon: str | None = None,
) -> Category:
    """Update name/color/icon fields for a user-owned category.

    Raises HTTPException(404) if the category is not found or belongs to another user.
    Raises HTTPException(400) if the caller tries to rename a protected category.
    Returns the updated Category with `expense_count` populated.
    """
    cat = db.query(Category).filter_by(id=category_id, user_id=user_id).first()
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    if cat.is_protected and name is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot rename the protected 'Other' category",
        )

    if name is not None:
        cat.name = name.strip()
    if color is not None:
        cat.color = color
    if icon is not None:
        cat.icon = icon

    db.commit()
    db.refresh(cat)

    count = (
        db.query(func.count(Expense.id))
        .filter(Expense.category_id == category_id)
        .scalar()
        or 0
    )
    cat.expense_count = count
    return cat


def delete_category(db: Session, user_id: int, category_id: int) -> int:
    """Delete a category, reassigning its expenses to the user's 'Other' category.

    Raises HTTPException(404) if the category is not found or belongs to another user.
    Raises HTTPException(400) if the category is the protected 'Other' category.
    Returns the number of expenses that were reassigned.
    """
    cat = db.query(Category).filter_by(id=category_id, user_id=user_id).first()
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    if cat.is_protected:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the protected 'Other' category",
        )

    other = db.query(Category).filter_by(user_id=user_id, name="Other").first()

    # Reassign all expenses in the deleted category to Other.
    reassigned = (
        db.query(Expense)
        .filter(Expense.user_id == user_id, Expense.category_id == category_id)
        .update({"category_id": other.id})
    )

    db.delete(cat)
    db.commit()
    return reassigned
