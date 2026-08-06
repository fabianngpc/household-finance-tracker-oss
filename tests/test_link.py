"""Tests for Telegram account linking service and endpoint."""

import pytest
from datetime import datetime, timedelta, timezone

from tests.conftest import TEST_TG_USER_ID


# ─── Service layer tests ──────────────────────────────────────────────────────

def test_generate_link_code_returns_nonempty_string(db, seeded_users):
    from app.services.link import generate_link_code

    user1, _ = seeded_users
    code = generate_link_code(db, user1)
    assert isinstance(code, str) and len(code) > 0


def test_generate_link_code_sets_user_fields(db, seeded_users):
    from app.services.link import generate_link_code, LINK_CODE_TTL_MINUTES

    user1, _ = seeded_users
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    code = generate_link_code(db, user1)

    db.refresh(user1)
    assert user1.link_code == code
    assert user1.link_code_expires_at is not None
    # Expiry should be ~15 minutes from now
    expected_expiry = before + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    delta = abs((user1.link_code_expires_at - expected_expiry).total_seconds())
    assert delta < 5  # within 5 seconds


def test_generate_link_code_overwrites_on_second_call(db, seeded_users):
    from app.services.link import generate_link_code

    user1, _ = seeded_users
    code1 = generate_link_code(db, user1)
    code2 = generate_link_code(db, user1)
    assert code1 != code2
    db.refresh(user1)
    assert user1.link_code == code2


def test_bind_telegram_id_binds_and_clears_code(db, seeded_users):
    from app.services.link import generate_link_code, bind_telegram_id

    user1, _ = seeded_users
    code = generate_link_code(db, user1)

    bound_user = bind_telegram_id(db, code, 222)
    db.refresh(user1)

    assert bound_user.id == user1.id
    assert user1.telegram_id == 222
    assert user1.link_code is None
    assert user1.link_code_expires_at is None


def test_bind_telegram_id_unknown_code_raises(db, seeded_users):
    from app.services.link import bind_telegram_id, LinkError

    with pytest.raises(LinkError, match="Invalid code"):
        bind_telegram_id(db, "nonexistent-code", 222)


def test_bind_telegram_id_expired_raises(db, seeded_users):
    from app.services.link import generate_link_code, bind_telegram_id, LinkError

    user1, _ = seeded_users
    code = generate_link_code(db, user1)

    # Manually expire the code
    user1.link_code_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db.commit()

    with pytest.raises(LinkError) as exc_info:
        bind_telegram_id(db, code, 222)
    assert "expired" in str(exc_info.value).lower()


def test_bind_telegram_id_different_account_raises(db, seeded_users):
    from app.services.link import generate_link_code, bind_telegram_id, LinkError

    user1, _ = seeded_users
    code = generate_link_code(db, user1)

    # Bind to telegram_id 222 first
    bind_telegram_id(db, code, 222)

    # Generate a new code for user2 and try to bind to different telegram_id
    _, user2 = seeded_users
    code2 = generate_link_code(db, user2)

    # Bind user2 to a different ID succeeds
    bind_telegram_id(db, code2, 333)

    # Now generate another code for user1 and try to bind to a different existing telegram_id
    code3 = generate_link_code(db, user1)
    # Trying to bind the same code to a different telegram_id (already bound user1 to 222)
    # The user already has telegram_id=222, so binding to 555 should raise
    with pytest.raises(LinkError, match="different account"):
        bind_telegram_id(db, code3, 555)


def test_resolve_user_by_telegram_id_returns_bound_user(db, seeded_users):
    from app.services.link import generate_link_code, bind_telegram_id, resolve_user_by_telegram_id

    user1, _ = seeded_users
    code = generate_link_code(db, user1)
    bind_telegram_id(db, code, 222)

    found = resolve_user_by_telegram_id(db, 222)
    assert found is not None
    assert found.id == user1.id


def test_resolve_user_by_telegram_id_unknown_returns_none(db, seeded_users):
    from app.services.link import resolve_user_by_telegram_id

    result = resolve_user_by_telegram_id(db, 9999999)
    assert result is None


# ─── Endpoint tests ───────────────────────────────────────────────────────────

def test_generate_endpoint_requires_auth(client):
    resp = client.post("/api/link/generate")
    assert resp.status_code == 401


def test_generate_endpoint_returns_code(client, seeded_users):
    # Log in first
    login_resp = client.post(
        "/auth/login",
        json={"username": "alice", "password": "changeme"},
    )
    assert login_resp.status_code == 200, login_resp.text

    # Generate a link code
    resp = client.post("/api/link/generate")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["expires_in_minutes"] == 15
