"""Tests for app/scheduler.py — the short-lived, idempotent generate+backup
driver (driver + daily-backup guard).

Verifies:
1. generate_all() creates the correct count of occurrences on first run.
2. A second generate_all() run with the same `today` creates ZERO new rows
   (idempotent —).
3. already_backed_up_today() correctly guards a same-day second backup.
4. app/scheduler.py imports cleanly as a module.
"""
from datetime import date

from app.scheduler import already_backed_up_today, generate_all
from app.services.recurring import due_dates


def test_generate_all_creates_due_occurrences_then_zero_on_rerun(
    db, recurring_rule_factory
):
    """A monthly rule anchored 2 periods back generates each due occurrence
    once; re-running generate_all with the same `today` creates nothing new."""
    rule = recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
    )
    today = date(2026, 3, 1)  # Jan 1, Feb 1, Mar 1 all due -> 3 periods
    expected = len(due_dates(rule, start=rule.generate_from, until=today))
    assert expected == 3

    created_first = generate_all(db, today=today)
    assert created_first == expected

    created_second = generate_all(db, today=today)
    assert created_second == 0


def test_generate_all_skips_paused_rules(db, recurring_rule_factory):
    recurring_rule_factory(
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
        paused=True,
    )
    created = generate_all(db, today=date(2026, 3, 1))
    assert created == 0


def test_generate_all_sums_across_multiple_rules(db, recurring_rule_factory):
    recurring_rule_factory(
        merchant="Rent",
        frequency="monthly",
        day_of_month=1,
        anchor_date=date(2026, 1, 1),
        generate_from=date(2026, 1, 1),
    )
    recurring_rule_factory(
        merchant="Netflix",
        frequency="monthly",
        day_of_month=5,
        anchor_date=date(2026, 1, 5),
        generate_from=date(2026, 1, 5),
    )
    today = date(2026, 2, 1)  # rule 1: Jan1, Feb1 (2); rule 2: Jan5 only (1)
    created = generate_all(db, today=today)
    assert created == 3


def test_already_backed_up_today_guard(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    today = date(2026, 7, 24)

    assert already_backed_up_today(backup_dir=str(backup_dir), today=today) is False

    (backup_dir / "finance_20260724_003000.db").write_text("fake")
    assert already_backed_up_today(backup_dir=str(backup_dir), today=today) is True

    # A backup from a DIFFERENT day must not satisfy today's guard.
    other_dir = tmp_path / "backups2"
    other_dir.mkdir()
    (other_dir / "finance_20260723_003000.db").write_text("fake")
    assert already_backed_up_today(backup_dir=str(other_dir), today=today) is False


def test_already_backed_up_today_missing_dir_is_false(tmp_path):
    missing_dir = tmp_path / "no-such-backups"
    assert already_backed_up_today(backup_dir=str(missing_dir)) is False


def test_scheduler_module_imports_cleanly():
    import app.scheduler  # noqa: F401 — import-time errors would raise here
