"""Bot command handlers — thin async shells over app services.

Each handler:
  - Opens a DB session via ``context.bot_data["db_factory"]()``.
  - Closes the session in a try/finally block.
  - Delegates all business logic to the canonical service layer.
  - Never re-implements money/FX or linking logic.

Registration happens in bot/main.py via register_command_handlers().
"""

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from app.services.link import resolve_user_by_telegram_id, bind_telegram_id, LinkError
from app.services.expenses import list_expenses, delete_expense
from app.services.money import format_from_minor_units
from app.services.balance import compute_balance
from app.services.budgets import compute_budget_status
from app.services.recurring import list_rules, next_run_date
from app.models.user import User

_LINK_PROMPT = (
    "Please link your account first: /link <code> "
    "(generate a code in the web app)."
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a greeting that explains how to get started."""
    db = context.bot_data["db_factory"]()
    try:
        await update.message.reply_text(
            "Welcome to Family Finance Tracker!\n\n"
            "To get started, link your Telegram account to the web app:\n"
            "  /link <code>\n\n"
            "Generate the code from Settings in the web app."
        )
    finally:
        db.close()


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the list of available commands."""
    db = context.bot_data["db_factory"]()
    try:
        await update.message.reply_text(
            "Available commands:\n"
            "  /start   — introduction\n"
            "  /help    — show this message\n"
            "  /recent  — list your most recent expenses\n"
            "  /undo    — delete your most recently logged expense\n"
            "  /balance — who owes whom, per currency\n"
            "  /budget  — this month's budget vs. spend\n"
            "  /recurring — your recurring expenses\n"
            "  /link <code> — link this Telegram account to the web app"
        )
    finally:
        db.close()


async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a per-currency directional balance sentence against the partner."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(_LINK_PROMPT)
            return

        partner = db.query(User).filter(User.id != app_user.id).first()
        if partner is None:
            await update.message.reply_text("All settled up.")
            return

        balances = compute_balance(db, app_user.id, partner.id)
        if not balances:
            await update.message.reply_text("All settled up.")
            return

        lines = []
        for currency, net in sorted(balances.items()):
            amt = format_from_minor_units(abs(net), currency)
            if net > 0:
                lines.append(f"{partner.display_name} owes you {currency} {amt}")
            else:
                lines.append(f"You owe {partner.display_name} {currency} {amt}")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with this month's user-total budget-vs-actual plus one line per
    set category cap. Read-only — bot = capture, web = manage."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(_LINK_PROMPT)
            return

        today = date.today()
        status = compute_budget_status(db, app_user.id, today.year, today.month)
        total = status["total"]
        if total is None:
            await update.message.reply_text(
                "No monthly budget set. Set one on the web app to track spending "
                "and get alerts."
            )
            return

        spent = format_from_minor_units(total["spent_minor"], "SGD")
        cap = format_from_minor_units(total["cap_minor"], "SGD")
        left = format_from_minor_units(total["left_minor"], "SGD")
        lines = [
            f"Monthly budget: S${spent} / S${cap} ({total['pct']}%). "
            f"S${left} left this month."
        ]
        for cat in status["categories"]:
            cat_spent = format_from_minor_units(cat["spent_minor"], "SGD")
            cat_cap = format_from_minor_units(cat["cap_minor"], "SGD")
            lines.append(
                f"· {cat['name']}: S${cat_spent} / S${cat_cap} ({cat['pct']}%)"
            )
        lines.append("Manage budgets on the web app.")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def recurring_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the caller's recurring rules — cadence + next run.
    Read-only — bot = capture, web = manage."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(_LINK_PROMPT)
            return

        rules = list_rules(db, app_user.id)
        if not rules:
            await update.message.reply_text(
                "No recurring expenses set up. Add one on the web app."
            )
            return

        lines = ["Recurring expenses:"]
        for rule in rules:
            amt = format_from_minor_units(rule.amount_minor, rule.currency)
            if rule.frequency == "weekly":
                cadence = "week"
            elif rule.frequency == "monthly_nth":
                cadence = f"day {rule.day_of_month}"
            else:
                cadence = "month"

            next_run = next_run_date(rule)
            next_str = next_run.isoformat() if next_run else "—"
            name = rule.merchant or "Recurring"
            suffix = " (paused)" if rule.paused else ""
            lines.append(
                f"· {name} — {rule.currency} {amt} / {cadence}, "
                f"next {next_str}{suffix}"
            )
        lines.append("Add or edit recurring on the web app.")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def recent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List the caller's 5 most recent expenses."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(_LINK_PROMPT)
            return

        expenses = list_expenses(db, user_id=app_user.id, limit=5)
        if not expenses:
            await update.message.reply_text("No expenses yet.")
            return

        lines = []
        for e in expenses:
            amount_str = format_from_minor_units(e.original_amount_minor, e.original_currency)
            merchant = e.merchant or "expense"
            lines.append(
                f"{e.occurred_on} {merchant} {e.original_currency} {amount_str}"
            )
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


async def undo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete the caller's most recently logged expense."""
    db = context.bot_data["db_factory"]()
    try:
        app_user = resolve_user_by_telegram_id(db, update.effective_user.id)
        if app_user is None:
            await update.message.reply_text(_LINK_PROMPT)
            return

        recent = list_expenses(db, user_id=app_user.id, limit=1)
        if not recent:
            await update.message.reply_text("Nothing to undo.")
            return

        exp = recent[0]
        if exp.shared_expense_id is not None:
            await update.message.reply_text(
                "That's a shared expense — manage it on the web."
            )
            return

        amount_str = format_from_minor_units(exp.original_amount_minor, exp.original_currency)
        merchant = exp.merchant or "expense"
        delete_expense(db, user_id=app_user.id, expense_id=exp.id)
        await update.message.reply_text(
            f"Removed: {merchant} ({exp.original_currency} {amount_str}) on {exp.occurred_on}"
        )
    finally:
        db.close()


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bind this Telegram account to an app user via a one-time link code."""
    db = context.bot_data["db_factory"]()
    try:
        if not context.args:
            await update.message.reply_text(
                "Usage: /link <code>\n"
                "Generate a code in the web app under Settings."
            )
            return

        code = context.args[0]
        try:
            bind_telegram_id(db, code, update.effective_user.id)
            await update.message.reply_text(
                "Account linked! You can now log expenses."
            )
        except LinkError as exc:
            await update.message.reply_text(str(exc))
    finally:
        db.close()


def register_command_handlers(application, allowlist_filter) -> None:
    """Register all command handlers with the PTB application.

    Called by bot/main.py after the Application is built.
    Each command is gated behind allowlist_filter so only permitted
    Telegram user IDs can trigger handlers.
    """
    from telegram.ext import CommandHandler

    application.add_handler(CommandHandler("start", start_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("help", help_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("recent", recent_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("undo", undo_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("balance", balance_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("budget", budget_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("recurring", recurring_handler, filters=allowlist_filter))
    application.add_handler(CommandHandler("link", link_handler, filters=allowlist_filter))
