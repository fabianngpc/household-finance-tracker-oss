"""Integration tests for authentication endpoints.

Seeded password for both users: changeme (see app/seed.py)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOGIN_URL = "/auth/login"
LOGOUT_URL = "/auth/logout"
ME_URL = "/auth/me"
# A protected route that requires authentication (use /auth/me — expenses stub has no routes yet)
PROTECTED_URL = "/auth/me"

VALID_USER = {"username": "alice", "password": "changeme"}
WRONG_PASSWORD = {"username": "alice", "password": "wrongpassword"}
UNKNOWN_USER = {"username": "nobody", "password": "changeme"}
INVALID_CREDS_MSG = "Invalid username or password. Check your credentials and try again."


# ---------------------------------------------------------------------------
# Test: successful login
# ---------------------------------------------------------------------------

def test_login_success_returns_200_and_user(client, seeded_users):
    """POST /auth/login with valid credentials returns 200 and user info."""
    response = client.post(LOGIN_URL, json=VALID_USER)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["user"]["username"] == "alice"
    assert data["user"]["display_name"] == "Alice"
    assert "id" in data["user"]


def test_login_sets_session_cookie(client, seeded_users):
    """POST /auth/login sets a session cookie on the client."""
    response = client.post(LOGIN_URL, json=VALID_USER)
    assert response.status_code == 200
    # Starlette SessionMiddleware sets 'session' cookie
    assert "session" in client.cookies


# ---------------------------------------------------------------------------
# Test: wrong password → 401
# ---------------------------------------------------------------------------

def test_login_wrong_password_returns_401(client, seeded_users):
    """POST /auth/login with wrong password returns 401 with the exact error message."""
    response = client.post(LOGIN_URL, json=WRONG_PASSWORD)
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDS_MSG


# ---------------------------------------------------------------------------
# Test: unknown username → 401
# ---------------------------------------------------------------------------

def test_login_unknown_username_returns_401(client, seeded_users):
    """POST /auth/login with an unknown username returns 401."""
    response = client.post(LOGIN_URL, json=UNKNOWN_USER)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: protected route without session → 401
# ---------------------------------------------------------------------------

def test_protected_route_without_session_returns_401(client, seeded_users):
    """An unauthenticated GET to a protected route returns 401."""
    response = client.get(PROTECTED_URL)
    assert response.status_code == 401


def test_me_without_session_returns_401(client, seeded_users):
    """GET /auth/me without a session returns 401."""
    response = client.get(ME_URL)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: /me after successful login
# ---------------------------------------------------------------------------

def test_me_after_login_returns_current_user(client, seeded_users):
    """GET /auth/me after login returns the logged-in user's info."""
    login_response = client.post(LOGIN_URL, json=VALID_USER)
    assert login_response.status_code == 200

    me_response = client.get(ME_URL)
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["username"] == "alice"
    assert data["display_name"] == "Alice"
    assert "id" in data


# ---------------------------------------------------------------------------
# Test: logout clears session
# ---------------------------------------------------------------------------

def test_logout_clears_session(client, seeded_users):
    """POST /auth/logout clears the session; subsequent /auth/me returns 401."""
    # Login first
    login_response = client.post(LOGIN_URL, json=VALID_USER)
    assert login_response.status_code == 200

    # Verify session is active
    me_response = client.get(ME_URL)
    assert me_response.status_code == 200

    # Logout
    logout_response = client.post(LOGOUT_URL)
    assert logout_response.status_code == 200
    assert logout_response.json()["ok"] is True

    # Session should be cleared
    me_after_logout = client.get(ME_URL)
    assert me_after_logout.status_code == 401


# ---------------------------------------------------------------------------
# Test: second user can log in independently
# ---------------------------------------------------------------------------

def test_partner_login_success(client, seeded_users):
    """The second seeded user (partner) can also log in."""
    response = client.post(LOGIN_URL, json={"username": "partner", "password": "changeme"})
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["username"] == "partner"
    assert data["user"]["display_name"] == "Bob"
    # partner-of-partner is the other seeded user (Alice)
    assert data["user"]["partner_display_name"] == "Alice"
