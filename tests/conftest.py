import os
from datetime import date

import pytest
from unittest.mock import AsyncMock, MagicMock

# Set SECRET_KEY before any app import so SessionMiddleware initializes correctly.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base
from app.main import app
from app.deps import get_db
from app.seed import seed_users, seed_categories_for_user


@pytest.fixture(scope="function")
def db_engine():
    """In-memory SQLite engine for each test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    """Session bound to the in-memory engine."""
    TestingSessionLocal = sessionmaker(bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    """TestClient with get_db overridden to use the test session."""
    def override_get_db():
        try:
            yield db
        finally:
            pass  # session managed by the db fixture

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seeded_users(db):
    """Seed two users and their default categories; return (user1, user2)."""
    seed_users(db)
    from app.models.user import User
    user1 = db.query(User).filter_by(username="alice").first()
    user2 = db.query(User).filter_by(username="partner").first()
    return user1, user2


@pytest.fixture(scope="function")
def seeded_categories(db, seeded_users):
    """Return the seeded categories for user 1."""
    from app.models.category import Category
    user1, _ = seeded_users
    return db.query(Category).filter_by(user_id=user1.id).all()


@pytest.fixture
def mock_frankfurter(mocker):
    """Patch httpx.get to return a fake Frankfurter FX response."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "amount": 1.0,
        "base": "SGD",
        "date": "2026-06-27",
        "rates": {
            "USD": 0.74,
            "MYR": 3.16,
            "EUR": 0.68,
            "JPY": 109.5,
        },
    }
    return mocker.patch("httpx.get", return_value=fake_response)


# ---------------------------------------------------------------------------
# Telegram bot test fixtures
# ---------------------------------------------------------------------------

from telegram import Chat, Message, Update
from telegram import User as TGUser

# Telegram user/chat ID constants used across bot handler tests
TEST_TG_USER_ID = 111111111
TEST_TG_CHAT_ID = 111111111
TEST_TG_OTHER_ID = 999999999


def make_update(
    text: str = "/start",
    telegram_user_id: int = TEST_TG_USER_ID,
    chat_id: int = TEST_TG_CHAT_ID,
    update_id: int = 1001,
) -> MagicMock:
    """Build a MagicMock(spec=Update) without any live Telegram connection.

    The returned mock exposes:
      - .update_id
      - .effective_user  (real TGUser object)
      - .effective_chat  (real Chat object)
      - .message         (MagicMock(spec=Message) with .text and .reply_text=AsyncMock)
    """
    tg_user = TGUser(id=telegram_user_id, first_name="Test", is_bot=False)
    chat = Chat(id=chat_id, type="private")

    message = MagicMock(spec=Message)
    message.text = text
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.update_id = update_id
    update.effective_user = tg_user
    update.effective_chat = chat
    update.message = message

    return update


def make_context(db, args=None) -> MagicMock:
    """Build a minimal PTB context mock with db_factory in bot_data."""
    ctx = MagicMock()
    ctx.args = args or []
    ctx.bot = AsyncMock()
    ctx.bot_data = {"db_factory": (lambda: db)}
    return ctx


@pytest.fixture(scope="function")
def linked_user(db, seeded_users):
    """Return user1 with telegram_id bound to TEST_TG_USER_ID."""
    user1, _ = seeded_users
    user1.telegram_id = TEST_TG_USER_ID
    db.commit()
    return user1


@pytest.fixture(scope="function")
def capture_factory(db):
    """Return a factory function that creates and commits a Capture row.

    Each call auto-increments update_id so multiple captures per test stay unique.
    """
    from app.models.capture import Capture

    counter = [2000]

    def _make_capture(**kwargs):
        uid = counter[0]
        counter[0] += 1
        defaults = {
            "update_id": uid,
            "telegram_user_id": TEST_TG_USER_ID,
            "telegram_chat_id": TEST_TG_CHAT_ID,
            "status": "queued",
        }
        defaults.update(kwargs)
        capture = Capture(**defaults)
        db.add(capture)
        db.commit()
        db.refresh(capture)
        return capture

    return _make_capture


@pytest.fixture(scope="function")
def job_factory(db):
    """Return a factory function that creates and commits a Job row."""
    from app.models.job import Job

    def _make_job(capture_id: int, status: str = "pending", **kwargs):
        job = Job(capture_id=capture_id, status=status, **kwargs)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    return _make_job


# ---------------------------------------------------------------------------
# Budgets / alerts / recurring test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def recurring_rule_factory(db, seeded_users, seeded_categories):
    """Create+commit a RecurringRule with sensible defaults; kwargs override."""
    from app.models.recurring import RecurringRule

    user1, _ = seeded_users

    def _make(**kwargs):
        defaults = {
            "owner_user_id": user1.id,
            "amount_minor": 200000,  # S$2000.00
            "currency": "SGD",
            "category_id": seeded_categories[0].id,
            "merchant": "Rent",
            "frequency": "monthly",
            "day_of_month": 1,
            "anchor_date": date(2026, 1, 1),
            "generate_from": date(2026, 1, 1),
            "paused": False,
            "is_shared": False,
        }
        defaults.update(kwargs)
        rule = RecurringRule(**defaults)
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    return _make


@pytest.fixture(scope="function")
def mock_bot():
    """AsyncMock Bot with send_message — for outbound-notification drain tests."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot
