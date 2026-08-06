"""Text and photo message handlers for the Telegram bot.

Routes each non-command message through paths (in priority order):

Text messages:
1. Pending confirm flow  — if the user has a capture in 'pending_confirm' state,
   this message is their answer to the current confirm_step prompt.  Drives
   apply_confirm_input and replies with a save summary or re-prompt.

2. Post-save keyword     — if the user's latest capture is 'done'/'post_save',
   the keyword "undo" removes that expense. The keyword "edit" and natural-
   language price phrases ("change the price above", "change price", "change
   the amount", "edit price", "wrong price") re-open the amount confirm step.
   Natural-language category phrases ("change the category above", "change
   category", "edit category", "wrong category") show an inline category
   picker (see setcat_callback) that updates the expense's category in place.
   Both edit paths refuse to touch a shared expense (see the /undo guard).

3. New capture           — idempotently enqueue a new capture + job and ack
   immediately so the worker can process it asynchronously.

Photo messages:
1. Unlinked user         — link prompt, no capture created.
2. Linked user           — ack "Reading receipt...", download highest-res image,
   enqueue capture with image_path.

DB is the single source of truth for all conversation state.
"""

import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

from app.models.capture import Capture
from app.models.category import Category
from app.models.expense import Expense
from app.models.user import User
from app.services.capture import apply_confirm_input, enqueue_capture
from app.services.categories import list_categories_with_counts
from app.services.expenses import delete_expense
from app.services.link import resolve_user_by_telegram_id
from app.services.money import format_from_minor_units
from app.services.shared_expenses import create_shared_expense


# ---------------------------------------------------------------------------
# Post-save edit phrase matching (natural-language, case-insensitive, substring)
# ---------------------------------------------------------------------------

_EDIT_TRIGGER_WORDS = ("change", "edit", "wrong")
_PRICE_KEYWORDS = ("price", "amount")
_CATEGORY_KEYWORDS = ("category",)


def _matches_price_edit_phrase(text_lower: str) -> bool:
    """True for natural-language price-edit phrases.

    E.g. "change the price above", "change price", "change the amount",
    "edit price", "wrong price". Substring/keyword match on the already-
    lowercased text — does not match the bare "edit" keyword (handled
    separately) or category phrases.
    """
    return any(k in text_lower for k in _PRICE_KEYWORDS) and any(
        w in text_lower for w in _EDIT_TRIGGER_WORDS
    )


def _matches_category_edit_phrase(text_lower: str) -> bool:
    """True for natural-language category-edit phrases.

    E.g. "change the category above", "change category", "edit category",
    "wrong category". Substring/keyword match on the already-lowercased text.
    """
    return any(k in text_lower for k in _CATEGORY_KEYWORDS) and any(
        w in text_lower for w in _EDIT_TRIGGER_WORDS
    )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


async def text_handler(update, context) -> None:
    """Route an incoming non-command text message."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(
                "Please link your account first: /link <code>."
            )
            return

        # --- Path 1: pending confirm flow (DB-backed restart-safe) ----------
        pending = (
            db.query(Capture)
            .filter_by(user_id=app_user.id, status="pending_confirm")
            .order_by(Capture.created_at.desc())
            .first()
        )
        if pending:
            apply_confirm_input(db, pending, update.message.text)
            # apply_confirm_input may commit; re-read attributes from the same object
            if pending.status == "done":
                reply_markup = None
                partner = db.query(User).filter(User.id != app_user.id).first()
                if pending.expense_id is not None and partner is not None:
                    button = InlineKeyboardButton(
                        f"Split 50/50 with {partner.display_name}",
                        callback_data=f"split:{pending.expense_id}",
                    )
                    reply_markup = InlineKeyboardMarkup([[button]])

                await update.message.reply_text(
                    f"Saved! {pending.amount_str} {pending.currency or 'SGD'}"
                    f" at {pending.merchant or 'unknown'}"
                    f" on {pending.expense_date}.\n"
                    "Reply 'undo' to remove this.",
                    reply_markup=reply_markup,
                )
            else:
                # Still pending_confirm — re-prompt for the current step
                if pending.confirm_step == "amount":
                    await update.message.reply_text(
                        "What's the amount? (e.g. 12.50)"
                    )
            return

        # --- Path 2: post-save keywords --------------------------------------
        text_lower = update.message.text.strip().lower()
        post_save = (
            db.query(Capture)
            .filter_by(user_id=app_user.id, status="done", confirm_step="post_save")
            .order_by(Capture.created_at.desc())
            .first()
        )

        if post_save and text_lower == "undo":
            if post_save.expense_id is not None:
                linked_expense = db.get(Expense, post_save.expense_id)
                if linked_expense is not None and linked_expense.shared_expense_id is not None:
                    await update.message.reply_text(
                        "That's a shared expense — manage it on the web."
                    )
                    return
                delete_expense(db, user_id=app_user.id, expense_id=post_save.expense_id)
            post_save.confirm_step = None
            db.commit()
            await update.message.reply_text("Expense removed.")
            return

        if post_save and (text_lower == "edit" or _matches_price_edit_phrase(text_lower)):
            if post_save.expense_id is not None:
                linked_expense = db.get(Expense, post_save.expense_id)
                if linked_expense is not None and linked_expense.shared_expense_id is not None:
                    await update.message.reply_text(
                        "That's a shared expense — manage it on the web."
                    )
                    return
            post_save.status = "pending_confirm"
            post_save.confirm_step = "amount"
            db.commit()
            await update.message.reply_text("What's the amount? (e.g. 12.50)")
            return

        if post_save and _matches_category_edit_phrase(text_lower):
            if post_save.expense_id is not None:
                linked_expense = db.get(Expense, post_save.expense_id)
                if linked_expense is not None and linked_expense.shared_expense_id is not None:
                    await update.message.reply_text(
                        "That's a shared expense — manage it on the web."
                    )
                    return

            categories = list_categories_with_counts(db, app_user.id)
            buttons = [
                InlineKeyboardButton(
                    cat.name, callback_data=f"setcat:{post_save.expense_id}:{cat.id}"
                )
                for cat in categories
            ]
            rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
            reply_markup = InlineKeyboardMarkup(rows)
            await update.message.reply_text(
                "Pick a new category:", reply_markup=reply_markup
            )
            return

        # --- Path 3: new capture (idempotent enqueue + immediate ack) --------
        enqueue_capture(
            db,
            update_id=update.update_id,
            telegram_user_id=update.effective_user.id,
            telegram_chat_id=update.effective_chat.id,
            user_id=app_user.id,
            raw_text=update.message.text,
        )
        await update.message.reply_text("Got it, processing...")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Photo handler
# ---------------------------------------------------------------------------


async def photo_handler(update, context) -> None:
    """Handle an incoming photo message (receipt capture).

    Flow:
    1. Resolve the app user — unlinked users get the link prompt and return.
    2. Reply "Reading receipt..." immediately (before downloading).
    3. Download the highest-resolution PhotoSize (photo[-1]) to a temp file.
    4. Enqueue a capture with image_path set and raw_text="" so the worker
       can pass it through OCR → extractor → gate.
    """
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(
                "Please link your account first: /link <code>."
            )
            return

        # Acknowledge immediately before the (slow) download
        await update.message.reply_text("Reading receipt...")

        # Download highest-resolution image (last in the list)
        photo_size = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo_size.file_id)
        local_path = await tg_file.download_to_drive(
            custom_path=f"{tempfile.mkdtemp(prefix='receipt_')}/{update.update_id}.jpg"
        )

        enqueue_capture(
            db,
            update_id=update.update_id,
            telegram_user_id=update.effective_user.id,
            telegram_chat_id=update.effective_chat.id,
            user_id=app_user.id,
            raw_text="",
            image_path=str(local_path),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Split callback (mark-shared)
# ---------------------------------------------------------------------------


async def split_callback(update, context) -> None:
    """Handle a "Split 50/50 with {partner}" inline button tap.

    Atomic order (never lose the original expense if the split fails):
    call create_shared_expense FIRST (header + both children committed),
    and only delete the original solo row AFTER that succeeds.
    """
    query = update.callback_query
    await query.answer()
    expense_id = int(query.data.split(":", 1)[1])

    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await query.message.reply_text(
                "Please link your account first: /link <code>."
            )
            return

        expense = (
            db.query(Expense)
            .filter(
                Expense.id == expense_id,
                Expense.user_id == app_user.id,
                Expense.shared_expense_id.is_(None),
            )
            .first()
        )
        if expense is None:
            await query.message.reply_text("Already split.")
            return

        partner = db.query(User).filter(User.id != app_user.id).first()
        if partner is None:
            await query.message.reply_text("No partner linked yet.")
            return

        # Capture everything we need BEFORE any mutation — create_shared_expense
        # touches the session and the original row must not be relied on after.
        amount_str = format_from_minor_units(
            expense.original_amount_minor, expense.original_currency
        )
        currency = expense.original_currency
        occurred_on = expense.occurred_on
        merchant = expense.merchant
        category_id = expense.category_id
        original_expense_id = expense.id

        try:
            header, payer_row, partner_row = create_shared_expense(
                db,
                app_user.id,
                partner.id,
                amount_str,
                currency,
                occurred_on,
                "equal",
                payer_category_id=category_id,
                partner_category_id=category_id,
                split_input={},
                merchant=merchant,
            )
        except Exception:
            # create_shared_expense failed (e.g. FX lookup) BEFORE the delete
            # below ever runs — the original solo expense is untouched.
            await query.message.reply_text(
                "Couldn't split right now — your expense is unchanged."
            )
            return

        # Only reached after the shared expense is fully committed.
        delete_expense(db, user_id=app_user.id, expense_id=original_expense_id)

        payer_amt = format_from_minor_units(payer_row.original_amount_minor, currency)
        partner_amt = format_from_minor_units(partner_row.original_amount_minor, currency)
        await query.message.reply_text(
            f"Split. Your half: {currency} {payer_amt}. "
            f"{partner.display_name}'s half: {currency} {partner_amt}."
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Set-category callback (post-save category edit)
# ---------------------------------------------------------------------------


async def setcat_callback(update, context) -> None:
    """Handle a category-picker inline button tap (post-save category edit).

    callback_data format: "setcat:{expense_id}:{category_id}" (see the
    category-edit-phrase branch of text_handler, which builds the keyboard).
    Updates the expense's category_id directly — a metadata-only edit, no FX
    recompute — and confirms with "Category changed to {name}."
    """
    query = update.callback_query
    await query.answer()
    _, expense_id_str, category_id_str = query.data.split(":")
    expense_id = int(expense_id_str)
    category_id = int(category_id_str)

    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await query.message.reply_text(
                "Please link your account first: /link <code>."
            )
            return

        expense = (
            db.query(Expense)
            .filter(Expense.id == expense_id, Expense.user_id == app_user.id)
            .first()
        )
        if expense is None:
            await query.message.reply_text("Expense not found.")
            return

        if expense.shared_expense_id is not None:
            await query.message.reply_text(
                "That's a shared expense — manage it on the web."
            )
            return

        category = (
            db.query(Category)
            .filter_by(id=category_id, user_id=app_user.id)
            .first()
        )
        if category is None:
            await query.message.reply_text("Category not found.")
            return

        expense.category_id = category.id
        db.commit()

        await query.message.reply_text(f"Category changed to {category.name}.")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


def register_message_handlers(application, allowlist_filter) -> None:
    """Register the text_handler, photo_handler, split_callback, and
    setcat_callback on *application*.

    Called by bot/main.py.  Uses the allowlist_filter from bot/main.py
    so only permitted Telegram user IDs reach the message/photo handlers.
    split_callback/setcat_callback resolve app_user internally
    (CallbackQueryHandler cannot take the same User filter directly) so an
    unlinked/unknown caller is handled inside the callback rather than
    dropped at dispatch.
    """
    application.add_handler(
        MessageHandler(
            allowlist_filter & filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )
    application.add_handler(
        MessageHandler(
            allowlist_filter & filters.PHOTO,
            photo_handler,
        )
    )
    application.add_handler(
        CallbackQueryHandler(split_callback, pattern=r"^split:")
    )
    application.add_handler(
        CallbackQueryHandler(setcat_callback, pattern=r"^setcat:")
    )
