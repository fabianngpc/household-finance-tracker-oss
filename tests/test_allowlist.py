""" allowlist enforcement tests via app.process_update.

Tests run fully offline:
- FAKE:TOKEN is used throughout.
- telegram.Bot.get_me is patched at the class level during app.initialize() so
  no live Telegram network call is made, and bot._bot_user is set manually so
  CommandHandler can read bot.username without a real token.
- telegram.Message.reply_text is patched per-test to capture calls without any
  outbound Bot API request.

Real telegram.Update / telegram.Message objects are used (not MagicMocks) so
that PTB's internal CommandHandler.check_update and filters.User dispatch path
runs exactly as it would in production.  MagicMock(spec=Update) passes
isinstance() but its auto-generated attributes break CommandHandler's entity
inspection — hence the real-object approach here.

The two tests prove:
  - permit:  /start from an allowlisted Telegram user ID reaches start_handler
             and update.message.reply_text is awaited.
  - block:   /start from a non-allowlisted ID is silently dropped at dispatch
             by filters.User — reply_text is NOT called.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from telegram import Chat, Message, MessageEntity
from telegram import User as TGUser
from telegram import Update

from tests.conftest import TEST_TG_USER_ID, TEST_TG_OTHER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_command_update(bot, user_id: int, command: str, update_id: int = 1001) -> Update:
    """Create a real PTB Update for a bot command (e.g. '/start').

    Attaches the bot to the message so CommandHandler can call
    message.get_bot().username without a network round-trip.
    """
    tg_user = TGUser(id=user_id, first_name="Test", is_bot=False)
    chat = Chat(id=user_id, type="private")

    # BOT_COMMAND entity is required for CommandHandler.check_update to
    # recognise the message as a command.
    cmd_len = len(command.split()[0])  # length of '/start' part only
    entities = [MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=cmd_len)]

    msg = Message(
        message_id=update_id,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=tg_user,
        text=command,
        entities=entities,
    )
    msg.set_bot(bot)  # required for message.get_bot() in CommandHandler
    return Update(update_id=update_id, message=msg)


async def _make_initialized_app(db, allowed_ids: list[int]):
    """Build and initialize a PTB Application without any network calls.

    - Patches telegram.Bot.get_me during initialize() to skip the getMe API
      call.
    - Sets bot._bot_user manually so bot.username is available for
      CommandHandler dispatch without a real Telegram token.
    """
    from bot.main import build_application

    app = build_application("FAKE:TOKEN", allowed_ids)
    app.bot_data["db_factory"] = lambda: db

    fake_me = TGUser(id=12345, first_name="TestBot", is_bot=True, username="testbot")
    with patch("telegram.Bot.get_me", new=AsyncMock(return_value=fake_me)):
        await app.initialize()
    # get_me mock prevents the real code from setting _bot_user; set it directly.
    app.bot._bot_user = fake_me

    return app


# ---------------------------------------------------------------------------
# permit: allowlisted user reaches the handler
# ---------------------------------------------------------------------------


async def test_allowlist_permits_allowlisted_user(db):
    """ permit: /start from allowlisted Telegram ID reaches start_handler.

    Expects update.message.reply_text to be called (handler ran).
    """
    app = await _make_initialized_app(db, [TEST_TG_USER_ID])
    try:
        update = _make_command_update(app.bot, TEST_TG_USER_ID, "/start")
        reply_mock = AsyncMock(return_value=None)
        with patch("telegram.Message.reply_text", new=reply_mock):
            await app.process_update(update)
        reply_mock.assert_called()
    finally:
        await app.shutdown()


# ---------------------------------------------------------------------------
# block: non-allowlisted user is silently dropped
# ---------------------------------------------------------------------------


async def test_allowlist_blocks_non_allowlisted_user(db):
    """ block: /start from non-allowlisted Telegram ID is silently ignored.

    filters.User drops the update before any handler callback is invoked;
    reply_text must NOT be called.
    """
    app = await _make_initialized_app(db, [TEST_TG_USER_ID])
    try:
        update = _make_command_update(app.bot, TEST_TG_OTHER_ID, "/start", update_id=1002)
        reply_mock = AsyncMock(return_value=None)
        with patch("telegram.Message.reply_text", new=reply_mock):
            await app.process_update(update)
        reply_mock.assert_not_called()
    finally:
        await app.shutdown()
