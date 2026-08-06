"""phase 5 budgets, alerts, recurring, outbound notifications schema

Revision ID: 005_phase5_budgets_recurring
Revises: 004_shared_expenses
Create Date: 2026-07-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005_phase5_budgets_recurring"
down_revision = "004_shared_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create budgets, budget_alerts_sent, outbound_notifications, recurring_rules,
    recurring_occurrences tables plus the partial unique indexes / unique constraints
    that are the correctness mechanisms for alert dedup (BUD-03) and idempotent
    recurring catch-up (REC-02)."""
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),  # NULL = the user-TOTAL cap
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLite treats NULLs as DISTINCT in UNIQUE, so a plain UNIQUE(user_id, category_id)
    # would allow two "total" rows per user. Two partial unique indexes fix this.
    op.create_index(
        "ux_budget_total",
        "budgets",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("category_id IS NULL"),
    )
    op.create_index(
        "ux_budget_category",
        "budgets",
        ["user_id", "category_id"],
        unique=True,
        sqlite_where=sa.text("category_id IS NOT NULL"),
    )

    op.create_table(
        "budget_alerts_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),  # 'YYYY-MM'
        sa.Column("threshold", sa.Integer(), nullable=False),  # 80 | 100 | 120
        sa.Column(
            "sent_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "period", "threshold", name="uq_budget_alert"),
    )

    op.create_table(
        "outbound_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("generate_from", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("split_method", sa.String(), nullable=True),
        sa.Column("split_input_json", sa.String(), nullable=True),
        sa.Column("partner_category_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.ForeignKeyConstraint(["partner_category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "recurring_occurrences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(), nullable=False),  # the DUE DATE as ISO 'YYYY-MM-DD'
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("shared_expense_id", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["recurring_rules.id"]),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"]),
        sa.ForeignKeyConstraint(["shared_expense_id"], ["shared_expenses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "period_key", name="uq_recurring_occurrence"),
    )


def downgrade() -> None:
    """Drop the two partial indexes then the five tables in reverse FK order."""
    op.drop_index("ux_budget_category", table_name="budgets")
    op.drop_index("ux_budget_total", table_name="budgets")

    op.drop_table("recurring_occurrences")
    op.drop_table("recurring_rules")
    op.drop_table("outbound_notifications")
    op.drop_table("budget_alerts_sent")
    op.drop_table("budgets")
