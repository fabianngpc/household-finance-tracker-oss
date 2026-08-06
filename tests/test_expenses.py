"""Integration tests for expense CRUD endpoints.

Covers:
- SGD expense creation (original == base, fx_rate == 1.0)
- Foreign-currency (JPY 1500) creation via mocked Frankfurter (Pitfall 2 & 3 checks)
- Original-currency preservation visible on GET
- Edit: base recomputed when amount changes; base unchanged on metadata-only patch
- Delete: expense removed from list
- Ownership: user B gets 404 on another user's expense
- Bad amounts (zero, negative) return 400
"""

from datetime import date
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

LOGIN_URL = "/auth/login"
EXPENSES_URL = "/api/expenses"

_EXPENSE_DATE = date(2026, 6, 27)  # matches mock_frankfurter response date


def login(client, username: str = "alice", password: str = "changeme"):
    resp = client.post(LOGIN_URL, json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


def _first_cat_id(seeded_categories) -> int:
    """Return the first non-protected category id for user 1."""
    non_protected = [c for c in seeded_categories if not c.is_protected]
    return non_protected[0].id


def _to_decimal(v) -> Decimal:
    """Parse whatever Pydantic/JSON gives us (str or number) to Decimal."""
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# test_create: SGD expense stores original == base, fx_rate == 1.0
# ---------------------------------------------------------------------------

def test_create(client, seeded_users, seeded_categories):
    """POST a SGD expense: original_amount_minor == amount_base_minor, fx_rate == 1.0."""
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    resp = client.post(EXPENSES_URL, json={
        "amount": "12.50",
        "currency": "SGD",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["original_currency"] == "SGD"
    assert data["original_amount_minor"] == 1250          # 12.50 SGD → 1250 cents
    assert data["amount_base_minor"] == 1250              # SGD→SGD, base == original
    assert _to_decimal(data["fx_rate"]) == Decimal("1.0") # SGD short-circuit


# ---------------------------------------------------------------------------
# test_create_foreign: JPY 1500 — original preserved, base converted
# ---------------------------------------------------------------------------

def test_create_foreign(client, seeded_users, seeded_categories, mock_frankfurter):
    """POST a JPY expense 1500: original=1500 minor units, base is SGD conversion."""
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    resp = client.post(EXPENSES_URL, json={
        "amount": "1500",
        "currency": "JPY",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # Pitfall 2: JPY must be stored as 1500 (0 decimal places), NOT 150000
    assert data["original_amount_minor"] == 1500
    assert data["original_currency"] == "JPY"

    # Pitfall 3: base is in SGD (not the same as original)
    assert data["amount_base_minor"] > 0
    assert data["amount_base_minor"] != 1500               # SGD conversion ≠ JPY amount

    # FX rate stored (mock returns 109.5 per SGD)
    assert _to_decimal(data["fx_rate"]) > Decimal("0")
    assert data["fx_rate_date"] is not None


# ---------------------------------------------------------------------------
# test_original_currency_preserved: GET list shows both original and base
# ---------------------------------------------------------------------------

def test_original_currency_preserved(client, seeded_users, seeded_categories, mock_frankfurter):
    """After creating a JPY expense, GET /expenses returns original 1500 JPY and SGD base."""
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    # Create
    resp = client.post(EXPENSES_URL, json={
        "amount": "1500",
        "currency": "JPY",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]

    # Retrieve via list
    list_resp = client.get(EXPENSES_URL)
    assert list_resp.status_code == 200
    items = list_resp.json()

    expense = next((e for e in items if e["id"] == expense_id), None)
    assert expense is not None, "Created expense not found in GET list"
    assert expense["original_amount_minor"] == 1500
    assert expense["original_currency"] == "JPY"
    assert expense["amount_base_minor"] != 1500  # SGD conversion is different


# ---------------------------------------------------------------------------
# test_edit: PATCH amount recomputes base; PATCH merchant only leaves base unchanged
# ---------------------------------------------------------------------------

def test_edit(client, seeded_users, seeded_categories):
    """
    PATCH amount → base recomputed.
    PATCH only merchant → base unchanged (FX not re-fetched for SGD).
    """
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    # Create SGD expense S$10.00
    resp = client.post(EXPENSES_URL, json={
        "amount": "10.00",
        "currency": "SGD",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    original_base = resp.json()["amount_base_minor"]
    assert original_base == 1000  # S$10.00 = 1000 cents

    # PATCH amount to S$20.00 → base must recompute to 2000
    resp = client.patch(f"{EXPENSES_URL}/{expense_id}", json={"amount": "20.00"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["amount_base_minor"] == 2000     # recomputed
    assert data["original_amount_minor"] == 2000 # also updated

    # PATCH only merchant → base unchanged
    resp = client.patch(f"{EXPENSES_URL}/{expense_id}", json={"merchant": "Coffee Shop"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["amount_base_minor"] == 2000     # unchanged
    assert data["merchant"] == "Coffee Shop"


# ---------------------------------------------------------------------------
# test_delete: DELETE removes the expense
# ---------------------------------------------------------------------------

def test_delete(client, seeded_users, seeded_categories):
    """DELETE → 200 {"ok": True}; subsequent GET list no longer contains the expense."""
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    # Create
    resp = client.post(EXPENSES_URL, json={
        "amount": "5.00",
        "currency": "SGD",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]

    # Delete
    del_resp = client.delete(f"{EXPENSES_URL}/{expense_id}")
    assert del_resp.status_code == 200, del_resp.text
    assert del_resp.json()["ok"] is True

    # Verify not in list
    list_resp = client.get(EXPENSES_URL)
    assert list_resp.status_code == 200
    ids = [e["id"] for e in list_resp.json()]
    assert expense_id not in ids, "Deleted expense still appears in GET list"


# ---------------------------------------------------------------------------
# test_ownership: user B cannot PATCH or DELETE user A's expense
# ---------------------------------------------------------------------------

def test_ownership(client, seeded_users, seeded_categories, db):
    """User B gets 404 when trying to PATCH or DELETE User A's expense."""
    user1, user2 = seeded_users
    cat_id = _first_cat_id(seeded_categories)

    # Login as user A and create an expense
    login(client, "alice")
    resp = client.post(EXPENSES_URL, json={
        "amount": "8.00",
        "currency": "SGD",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    })
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]

    # Logout user A, login as user B
    client.post("/auth/logout")
    login(client, "partner", "changeme")

    # PATCH user A's expense → 404
    resp = client.patch(f"{EXPENSES_URL}/{expense_id}", json={"merchant": "Evil"})
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    # DELETE user A's expense → 404
    resp = client.delete(f"{EXPENSES_URL}/{expense_id}")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# test_bad_amount: zero or negative amounts return 400
# ---------------------------------------------------------------------------

def test_bad_amount(client, seeded_users, seeded_categories):
    """POST with amount '0' or '-5' returns 400."""
    login(client)
    cat_id = _first_cat_id(seeded_categories)

    base_payload = {
        "currency": "SGD",
        "category_id": cat_id,
        "occurred_on": str(_EXPENSE_DATE),
    }

    # Zero amount
    resp = client.post(EXPENSES_URL, json={**base_payload, "amount": "0"})
    assert resp.status_code == 400, f"Expected 400 for zero amount, got {resp.status_code}: {resp.text}"

    # Negative amount
    resp = client.post(EXPENSES_URL, json={**base_payload, "amount": "-5"})
    assert resp.status_code == 400, f"Expected 400 for negative amount, got {resp.status_code}: {resp.text}"
