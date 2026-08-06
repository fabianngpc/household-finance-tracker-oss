"""Bot entry point: builds the PTB Application and starts long-polling.

Runs as a SEPARATE OS process from the FastAPI web server (uvicorn) and the
queue worker (bot/worker.py).  All three processes share the same WAL-mode
SQLite file via app/database.py.

Never embed this in uvicorn — PTB's run_polling() calls loop.run_until_complete()
which conflicts with uvicorn's already-running event loop (Pitfall 1).
"""

from telegram.ext import ApplicationBuilder, filters

from app.database import SessionLocal
from bot.config import BOT_TOKEN, ALLOWED_IDS
from bot.handlers.commands import register_command_handlers
from bot.handlers.messages import register_message_handlers


def build_application(token: str, allowed_ids: list[int]):
    """Build and return a configured PTB Application.

    The Application is NOT started/polled here — call run_polling() or
    initialize()/process_update() separately (e.g. for tests).

    Args:
        token: Telegram Bot API token.
        allowed_ids: List of numeric Telegram user IDs that may use the bot.
                     All other IDs are silently dropped at dispatch via
                     filters.User.

    Returns:
        A configured telegram.ext.Application instance.
    """
    application = ApplicationBuilder().token(token).build()

    # Store the DB session factory in bot_data so every handler can open a
    # fresh DB session without importing SessionLocal directly.
    application.bot_data["db_factory"] = SessionLocal

    # Build the allowlist filter once — applied to every handler registration
    # so non-allowlisted Telegram IDs are silently dropped at the dispatch
    # layer (never reach handler callbacks).  Never inspect effective_user.id
    # inside handler bodies for auth — use this filter exclusively (Pattern 2).
    allowlist = filters.User(user_id=allowed_ids)

    register_command_handlers(application, allowlist)
    register_message_handlers(application, allowlist)

    return application


def main() -> None:
    """Start the bot process (blocks until SIGINT/SIGTERM)."""
    app = build_application(BOT_TOKEN, ALLOWED_IDS)
    # drop_pending_updates=True discards messages that arrived while the bot
    # was offline, preventing a flood of stale messages on restart.
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
