"""phase 4 shared expenses and settlements schema

Revision ID: 004_shared_expenses
Revises: 003_phase3_capture_image
Create Date: 2026-07-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_shared_expenses"
down_revision = "003_phase3_capture_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create shared_expenses + settlements tables; add expenses.shared_expense_id FK."""
    op.create_table(
        "shared_expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payer_user_id", sa.Integer(), nullable=False),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("original_currency", sa.String(), nullable=False),
        sa.Column("split_method", sa.String(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("fx_rate", sa.Float(), nullable=False),
        sa.Column("fx_rate_date", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(["payer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("to_user_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("expenses", sa.Column("shared_expense_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.create_foreign_key(
            "fk_expenses_shared_expense_id",
            "shared_expenses",
            ["shared_expense_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop expenses.shared_expense_id FK/column, then settlements + shared_expenses tables."""
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_constraint("fk_expenses_shared_expense_id", type_="foreignkey")
        batch_op.drop_column("shared_expense_id")

    op.drop_table("settlements")
    op.drop_table("shared_expenses")
