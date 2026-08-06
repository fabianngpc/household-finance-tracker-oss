"""
Integration tests for reporting aggregation endpoints.

All amounts use SGD (fx_rate=1.0) so no FX mocking is required.
The category-sum invariant is verified in every applicable test.

Behaviors covered:
- test_monthly_total:   monthly total == sum of seeded amount_base_minors
- test_category_sum:    sum of per-category totals == monthly total_sgd_minor
- test_yearly:          yearly rollup total + per-month totals correct across 2 months
- test_user_filter:     user=mine returns only current user; user=both returns combined
- test_date_range:      category breakdown excludes expenses outside the requested range
"""

from datetime import date

from app.models.category import Category
from app.services.expenses import create_expense_from_data

LOGIN_URL = "/auth/login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login(client, username: str = "alice", password: str = "changeme") -> None:
    resp = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _user2_cat_id(db, user2) -> int:
    """Return the first category id belonging to user2."""
    cat = db.query(Category).filter_by(user_id=user2.id).first()
    assert cat is not None, "user2 has no categories (seed_users should have created them)"
    return cat.id


# ---------------------------------------------------------------------------
# test_monthly_total: monthly total == sum of individual SGD expenses
# ---------------------------------------------------------------------------

def test_monthly_total(client, db, seeded_users, seeded_categories):
    """Monthly total_sgd_minor equals the sum of each expense's amount_base_minor."""
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    # SGD amounts in minor units: 1000 (10.00), 2500 (25.00), 500 (5.00)
    create_expense_from_data(db, user1.id, "10.00", "SGD", cat_id, date(2026, 6, 10))
    create_expense_from_data(db, user1.id, "25.00", "SGD", cat_id, date(2026, 6, 15))
    create_expense_from_data(db, user1.id, "5.00",  "SGD", cat_id, date(2026, 6, 20))

    login(client)
    resp = client.get("/api/reports/monthly", params={"year": 2026, "month": 6, "user": "mine"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_sgd_minor"] == 1000 + 2500 + 500
    assert data["expense_count"] == 3


# ---------------------------------------------------------------------------
# test_category_sum: sum of per-category totals == monthly total (invariant)
# ---------------------------------------------------------------------------

def test_category_sum(client, db, seeded_users, seeded_categories):
    """Category breakdown sums exactly to the monthly total_sgd_minor."""
    user1, _ = seeded_users
    cat1_id = seeded_categories[0].id
    cat2_id = seeded_categories[1].id

    create_expense_from_data(db, user1.id, "15.00", "SGD", cat1_id, date(2026, 5, 10))
    create_expense_from_data(db, user1.id, "25.00", "SGD", cat1_id, date(2026, 5, 15))
    create_expense_from_data(db, user1.id, "10.00", "SGD", cat2_id, date(2026, 5, 20))

    login(client)
    resp = client.get("/api/reports/monthly", params={"year": 2026, "month": 5, "user": "mine"})
    assert resp.status_code == 200
    data = resp.json()

    category_sum = sum(c["total_sgd_minor"] for c in data["categories"])
    assert category_sum == data["total_sgd_minor"]
    assert data["total_sgd_minor"] == 1500 + 2500 + 1000


# ---------------------------------------------------------------------------
# test_yearly: yearly rollup has correct total and per-month breakdown
# ---------------------------------------------------------------------------

def test_yearly(client, db, seeded_users, seeded_categories):
    """Yearly total == sum of per-month totals; months list has correct entries."""
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    # January 2026: 50.00 SGD = 5000 minor
    # February 2026: 30.00 SGD = 3000 minor
    create_expense_from_data(db, user1.id, "50.00", "SGD", cat_id, date(2026, 1, 10))
    create_expense_from_data(db, user1.id, "30.00", "SGD", cat_id, date(2026, 2, 10))

    login(client)
    resp = client.get("/api/reports/yearly", params={"year": 2026, "user": "mine"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_sgd_minor"] == 5000 + 3000

    months_by_num = {m["month"]: m for m in data["months"]}
    assert months_by_num[1]["total_sgd_minor"] == 5000
    assert months_by_num[2]["total_sgd_minor"] == 3000
    assert len(data["months"]) == 2  # only months with expenses returned


# ---------------------------------------------------------------------------
# test_user_filter: mine vs both filtering
# ---------------------------------------------------------------------------

def test_user_filter(client, db, seeded_users, seeded_categories):
    """user=mine returns only the logged-in user's spend; user=both returns combined."""
    user1, user2 = seeded_users
    cat_id = seeded_categories[0].id
    user2_cat = _user2_cat_id(db, user2)

    # user1: 20.00 SGD = 2000 minor
    # user2: 30.00 SGD = 3000 minor
    create_expense_from_data(db, user1.id, "20.00", "SGD", cat_id,     date(2026, 7, 5))
    create_expense_from_data(db, user2.id, "30.00", "SGD", user2_cat,  date(2026, 7, 5))

    login(client)  # logged in as alice (user1)

    # mine — only user1's 2000
    resp = client.get("/api/reports/monthly", params={"year": 2026, "month": 7, "user": "mine"})
    assert resp.status_code == 200
    assert resp.json()["total_sgd_minor"] == 2000

    # both — user1 + user2 = 5000
    resp = client.get("/api/reports/monthly", params={"year": 2026, "month": 7, "user": "both"})
    assert resp.status_code == 200
    assert resp.json()["total_sgd_minor"] == 5000


# ---------------------------------------------------------------------------
# test_date_range: category breakdown excludes out-of-range expenses
# ---------------------------------------------------------------------------

def test_date_range(client, db, seeded_users, seeded_categories):
    """Category breakdown for a narrow range excludes expenses outside that range."""
    user1, _ = seeded_users
    cat_id = seeded_categories[0].id

    # Jan 15 (in range), March 15 (out of range)
    create_expense_from_data(db, user1.id, "40.00", "SGD", cat_id, date(2026, 1, 15))
    create_expense_from_data(db, user1.id, "60.00", "SGD", cat_id, date(2026, 3, 15))

    login(client)
    resp = client.get("/api/reports/category", params={
        "start": "2026-01-01",
        "end":   "2026-01-31",
        "user":  "mine",
    })
    assert resp.status_code == 200
    data = resp.json()

    total = sum(c["total_sgd_minor"] for c in data)
    # Only the Jan expense (40.00 SGD = 4000 minor) should be included
    assert total == 4000
