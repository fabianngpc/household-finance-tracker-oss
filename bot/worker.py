"""Background queue worker for the Telegram capture pipeline.

Polls the `jobs` table, atomically claims one pending job via the capture
service, runs the extractor on the capture's raw text or image, and hands the
result to `process_capture` — which either auto-saves (high confidence) or
parks for confirmation (low confidence). The worker then messages the user
using the `telegram_chat_id` stored on the capture row.

Design:
- `process_one` is unit-testable: accepts bot, extractor, engine, db_factory
  as parameters so tests can inject mocks without any live Telegram connection.
- `run_worker` is the production entrypoint: runs as a standalone OS process
  (never embedded in uvicorn — Pitfall 1).
- The extractor is selected via config (build_extractor / EXTRACTOR env var),
  defaulting to HermesExtractor. Swappable without touching this loop (AI-01).

Run as a standalone process:
    uv run python -m bot.worker
"""
import asyncio
import os
from datetime import datetime, timezone

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import BOT_TOKEN, EXTRACTOR
from bot.extractor import Extractor, StubExtractor
from bot.hermes_extractor import build_extractor
from app.services.capture import claim_next_job, process_capture, complete_job
from app.models.capture import Capture
from app.models.user import User
from app.database import engine, SessionLocal


async def process_one(bot, extractor: Extractor, engine, db_factory) -> bool:
    """Claim one pending job, extract, process, and reply to the user.

    Returns True if a job was claimed and handled (including error/duplicate
    cases), False if no pending jobs were found.

    Parameters
    ----------
    bot:
        Telegram Bot instance (AsyncMock in tests; real Bot in production).
    extractor:
        Extractor implementation to call (FakeExtractor in tests; real model in prod).
    engine:
        SQLAlchemy engine used by claim_next_job for BEGIN IMMEDIATE claim.
    db_factory:
        Callable that returns a Session (lambda: db in tests; SessionLocal in prod).
    """
    job = claim_next_job(engine)
    if job is None:
        return False

    db = db_factory()
    capture = None
    try:
        capture = db.get(Capture, job["capture_id"])

        # Duplicate guard (Pitfall 4): re-processing an already-done capture
        # is a no-op — mark the stray job done and return without saving again.
        if capture is None or capture.status == "done":
            complete_job(db, job["job_id"], "done")
            return True

        result = await extractor.extract(capture.raw_message or "", capture.image_path)
        process_capture(db, capture, result)
        db.refresh(capture)

        if capture.status == "done":
            date_str = capture.expense_date or ""
            merchant = capture.merchant or "expense"
            currency = capture.currency or "SGD"
            amount = capture.amount_str or ""
            summary = (
                f"Logged: {merchant} {currency} {amount} ({date_str}) [Other]. "
                "Reply 'undo' to remove this."
            )

            reply_markup = None
            partner = db.query(User).filter(User.id != capture.user_id).first()
            if capture.expense_id is not None and partner is not None:
                button = InlineKeyboardButton(
                    f"Split 50/50 with {partner.display_name}",
                    callback_data=f"split:{capture.expense_id}",
                )
                reply_markup = InlineKeyboardMarkup([[button]])

            await bot.send_message(
                chat_id=capture.telegram_chat_id,
                text=summary,
                reply_markup=reply_markup,
            )

        elif capture.status == "pending_confirm":
            # Photo captures that couldn't be read get a specific prompt;
            # text captures get the plain amount prompt.
            if capture.image_path:
                prompt = "Couldn't read it — reply with the amount."
            else:
                prompt = "What's the amount? (e.g. 12.50)"
            await bot.send_message(
                chat_id=capture.telegram_chat_id,
                text=prompt,
            )

        complete_job(db, job["job_id"], "done")
        return True

    except Exception as exc:
        # Do NOT let one bad job kill the loop (durability).
        try:
            if capture is not None:
                capture.status = "failed"
                db.commit()
            complete_job(db, job["job_id"], "failed", error=str(exc))
        except Exception:
            pass
        return True

    finally:
        # Clean up temp receipt image (success OR failure) — Pitfall 5.
        try:
            if (
                capture is not None
                and capture.image_path
                and os.path.exists(capture.image_path)
            ):
                os.unlink(capture.image_path)
        except OSError:
            pass
        db.close()


def _claim_pending_notification(engine) -> dict | None:
    """Atomically claim exactly one pending outbound_notifications row using
    BEGIN IMMEDIATE — same atomic-claim discipline as
    app.services.capture.claim_next_job (raw DBAPI connection so SQLAlchemy
    doesn't emit its own BEGIN and lose the write-lock guarantee).

    Returns {"id", "telegram_chat_id", "body"} or None if none pending.
    """
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT id, telegram_chat_id, body FROM outbound_notifications "
            "WHERE status='pending' ORDER BY created_at ASC, id ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("COMMIT")
            return None
        cur.execute(
            "UPDATE outbound_notifications SET status='sending' WHERE id=?",
            (row[0],),
        )
        cur.execute("COMMIT")
        return {"id": row[0], "telegram_chat_id": row[1], "body": row[2]}
    finally:
        raw.close()


async def drain_outbound_notifications(bot, db_factory, engine) -> int:
    """Claim pending outbound_notifications one at a time (BEGIN IMMEDIATE,
    same atomic-claim discipline as claim_next_job), await bot.send_message,
    mark sent or failed. Returns count delivered. Never lets one bad row
    kill the loop.
    """
    from app.models.notification import OutboundNotification

    delivered = 0
    while True:
        claimed = _claim_pending_notification(engine)
        if claimed is None:
            break

        db = db_factory()
        try:
            row = db.get(OutboundNotification, claimed["id"])
            if row is None:
                continue
            try:
                await bot.send_message(
                    chat_id=claimed["telegram_chat_id"], text=claimed["body"]
                )
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                delivered += 1
            except Exception as exc:
                row.status = "failed"
                row.error = str(exc)
                db.commit()
        finally:
            db.close()

    return delivered


async def run_worker(poll_interval: float = 1.0) -> None:
    """Standalone worker process: polls the DB queue and processes captures.

    Selects the extractor via config (EXTRACTOR env var, default 'hermes').
    Loads all Category names from the DB at startup for the extractor's
    vocabulary — per-user isolation is still enforced in process_capture.
    Runs as a separate OS process — never embedded in uvicorn (Pitfall 1).

    Parameters
    ----------
    poll_interval:
        Seconds to sleep when the queue is empty.
    """
    from app.models.category import Category

    bot = Bot(token=BOT_TOKEN)

    # Load full category vocabulary for extractor hint resolution.
    db = SessionLocal()
    try:
        all_cats = db.query(Category).all()
        categories = list({cat.name for cat in all_cats})
    finally:
        db.close()

    extractor = build_extractor(EXTRACTOR, categories)

    async with bot:
        while True:
            did = await process_one(bot, extractor, engine, SessionLocal)
            # Same running Bot delivers alert + recurring notifications.
            await drain_outbound_notifications(bot, SessionLocal, engine)
            if not did:
                await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(run_worker())
