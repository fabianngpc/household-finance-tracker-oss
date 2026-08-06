"""Integration tests for category management endpoints.

Covers: seed count, per-user CRUD, user isolation, delete-with-reassign to Other,
and the protected 'Other' category (cannot delete or rename).
"""

from datetime import date

import pytest

from app.models.category import Category
from app.models.expense import Expense


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOGIN_URL = "/auth/login"
CATEGORIES_URL = "/api/categories"


def login(client, username: str = "alice", password: str = "changeme"):
    """Log in and assert 200; session cookie is set on the client."""
    resp = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


def _other_category(db, user_id: int) -> Category:
    return db.query(Category).filter_by(user_id=user_id, name="Other").first()


# ---------------------------------------------------------------------------
# Test: seed defaults
# ---------------------------------------------------------------------------

def test_seed(client, seeded_users):
    """A freshly seeded user has exactly 10 categories, exactly one is_protected named 'Other'."""
    login(client)
    resp = client.get(CATEGORIES_URL)
    assert resp.status_code == 200

    cats = resp.json()
    assert len(cats) == 10, f"Expected 10 seeded categories, got {len(cats)}"

    protected = [c for c in cats if c["is_protected"]]
    assert len(protected) == 1, f"Expected exactly 1 protected category, got {len(protected)}"
    assert protected[0]["name"] == "Other"


# ---------------------------------------------------------------------------
# Test: CRUD happy path
# ---------------------------------------------------------------------------

def test_crud(client, seeded_users):
    """Logged-in user can POST a category, PATCH to rename it, and see it in GET list."""
    login(client)

    # Create
    resp = client.post(
        CATEGORIES_URL,
        json={"name": "Test Category", "color": "#123456", "icon": "Star"},
    )
    assert resp.status_code == 201
    cat = resp.json()
    assert cat["name"] == "Test Category"
    assert cat["expense_count"] == 0
    cat_id = cat["id"]

    # Rename
    resp = client.patch(f"{CATEGORIES_URL}/{cat_id}", json={"name": "Renamed Category"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Category"

    # GET list reflects the rename
    resp = client.get(CATEGORIES_URL)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Renamed Category" in names
    assert "Test Category" not in names


# ---------------------------------------------------------------------------
# Test: user isolation
# ---------------------------------------------------------------------------

def test_user_isolation(client, seeded_users, db):
    """User A cannot PATCH or DELETE a category belonging to User B."""
    user1, user2 = seeded_users

    # Find a non-protected category belonging to user2
    cat2 = db.query(Category).filter_by(user_id=user2.id, is_protected=0).first()
    assert cat2 is not None

    # Login as user1
    login(client, "alice")

    # PATCH user2's category → 404
    resp = client.patch(f"{CATEGORIES_URL}/{cat2.id}", json={"name": "Hacked"})
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    # DELETE user2's category → 404
    resp = client.delete(f"{CATEGORIES_URL}/{cat2.id}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Test: delete reassigns expenses to Other
# ---------------------------------------------------------------------------

def test_delete_reassigns(client, seeded_users, db):
    """DELETE a category that has an expense → expense reassigned to Other; reassigned == 1."""
    user1, _ = seeded_users
    login(client)

    # Create a new category to delete
    resp = client.post(
        CATEGORIES_URL,
        json={"name": "Temp Category", "color": "#AAAAAA", "icon": "Box"},
    )
    assert resp.status_code == 201
    new_cat_id = resp.json()["id"]

    other = _other_category(db, user1.id)

    # Insert an expense directly into the test DB pointing at the new category
    expense = Expense(
        user_id=user1.id,
        original_amount_minor=1000,
        original_currency="SGD",
        amount_base_minor=1000,
        fx_rate=1.0,
        fx_rate_date=date(2026, 6, 28),
        category_id=new_cat_id,
        occurred_on=date(2026, 6, 28),
    )
    db.add(expense)
    db.commit()
    expense_id = expense.id

    # Delete the category
    resp = client.delete(f"{CATEGORIES_URL}/{new_cat_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["reassigned"] == 1

    # Verify the expense now points at Other
    db.expire_all()
    reloaded = db.get(Expense, expense_id)
    assert reloaded.category_id == other.id, (
        f"Expected expense to be reassigned to Other ({other.id}), "
        f"got category_id={reloaded.category_id}"
    )


# ---------------------------------------------------------------------------
# Test: cannot delete the protected 'Other'
# ---------------------------------------------------------------------------

def test_cannot_delete_other(client, seeded_users, db):
    """DELETE the protected 'Other' category returns 400."""
    user1, _ = seeded_users
    login(client)

    other = _other_category(db, user1.id)
    assert other is not None

    resp = client.delete(f"{CATEGORIES_URL}/{other.id}")
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    assert "Other" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test: cannot rename the protected 'Other'
# ---------------------------------------------------------------------------

def test_cannot_rename_other(client, seeded_users, db):
    """PATCH 'Other'.name returns 400."""
    user1, _ = seeded_users
    login(client)

    other = _other_category(db, user1.id)
    assert other is not None

    resp = client.patch(f"{CATEGORIES_URL}/{other.id}", json={"name": "Not Other"})
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    assert "Other" in resp.json()["detail"]
